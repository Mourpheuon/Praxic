"""内部事实源测试：internal 槽位从空壳变为一等事实源。"""

import asyncio

from praxic.core.internal_facts import (
    build_internal_context,
    build_memory_context,
    build_self_model,
)
from praxic.tools.registry import ToolRegistry
from praxic.tools.user_context import ReadUserContextTool


def test_build_self_model_contains_env_tools_constraints():
    reg = ToolRegistry()
    reg.register(ReadUserContextTool())
    text = build_self_model(reg)
    assert "自我快照" in text
    assert "user_context" in text
    assert "shell_exec" in text
    assert "python_exec" in text
    assert "权限模式" in text


class _FakeEpisodic:
    def __init__(self):
        self.eps = [
            {"id": 1, "question": "用Python计算质数之和", "summary": "用埃氏筛完成"},
            {"id": 2, "question": "检查环境", "summary": "无 lean 工具"},
        ]

    def search(self, query, limit=5):
        kws = query.split()
        return [e for e in self.eps if any(k in e["question"] for k in kws)]

    def get_recent(self, limit=5):
        return list(self.eps[:limit])

    def format_for_context(self, episodes):
        if not episodes:
            return ""
        return "\n".join(
            f"- 问题：{e["question"][:60]} -> 结论：{e["summary"][:80]}" for e in episodes
        )

    def search_derivation_chains(self, question, limit=3):
        return []


class _FakeSemantic:
    def __init__(self):
        self.entries = [{"category": "anti-pattern", "content": "不要为验证自身能力去网络搜索"}]

    def retrieve(self, query, domain="", limit=5, min_confidence=0.5):
        return list(self.entries)

    def format_for_context(self, entries):
        if not entries:
            return ""
        return "\n".join(f"- [{e["category"]}] {e["content"][:120]}" for e in entries)


def test_memory_context_queries_local_memory():
    ep = _FakeEpisodic()
    text = build_memory_context("用Python计算质数之和", episodic=ep, semantic=_FakeSemantic())
    assert "历史相关记录" in text
    assert "质数之和" in text
    assert "蒸馏知识" in text
    assert "anti-pattern" in text


def test_internal_context_combines_memory_and_self_model():
    reg = ToolRegistry()
    reg.register(ReadUserContextTool())
    text = build_internal_context(
        "用Python计算质数之和", reg, episodic=_FakeEpisodic(), semantic=_FakeSemantic()
    )
    assert "内部记忆" in text
    assert "自我快照" in text


class CaptureLLM:
    def __init__(self):
        self.last_user = ""
        self.last_system = ""

    async def call(self, messages=None, system="", **kwargs):
        self.last_system = system or ""
        self.last_user = messages[-1]["content"] if messages else ""
        return type("_R", (), {"content": '{"facts": [], "gaps": [], "summary": "ok"}'})()


def test_investigate_injects_internal_context():
    from praxic.core.investigation import InvestigationModule

    async def _run():
        llm = CaptureLLM()
        mod = InvestigationModule(llm=llm, web_search_enabled=False, workspace=None)
        await mod.investigate(
            question="你可以跑lean代码吗",
            internal_context="## 内部事实\n- 平台：Windows\n- 无 lean 工具",
            skip_external_collection=True,
        )
        assert "## 内部事实" in llm.last_user
        assert "平台：Windows" in llm.last_user
        assert "内部事实" in llm.last_system

    asyncio.run(_run())


def test_web_search_gate_blocks_search_when_disallowed():
    """web_search_allowed=False 时，即使具备搜索能力也不触发网络搜索。"""
    from praxic.core.investigation import InvestigationModule

    async def _run():
        llm = CaptureLLM()
        mod = InvestigationModule(llm=llm, web_search_enabled=False, workspace=None)

        class _FakeSearch:
            enabled = True

        mod._web_search = _FakeSearch()
        mod._multi_search = None
        calls = []

        async def _spy(*a, **k):
            calls.append(1)
            return "", []

        mod._do_web_search = _spy
        # 关闭闸门 → 不搜索
        await mod.investigate(
            question="你可以跑lean代码吗",
            web_search_allowed=False,
            skip_external_collection=False,
        )
        assert calls == []
        # 开启闸门 → 正常搜索
        await mod.investigate(
            question="你可以跑lean代码吗",
            web_search_allowed=True,
            skip_external_collection=False,
        )
        assert calls == [1]

    asyncio.run(_run())


class SeqLLM:
    """按序列返回多次调用结果的假 LLM。"""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0
        self.max_tokens_seen = []

    async def call(self, messages=None, system="", **kwargs):
        self.calls += 1
        self.max_tokens_seen.append(kwargs.get("max_tokens"))
        content = self.contents.pop(0) if self.contents else self.contents[-1]
        return type("_R", (), {"content": content})()


def test_looks_truncated_detects_cut_json():
    from praxic.core.investigation import _looks_truncated

    assert _looks_truncated('{"facts": [{"id": "f1", "content": "abc...') is True
    assert _looks_truncated('{"facts": [], "gaps": [], "summary": "ok"}') is False


def test_parse_failure_marks_parse_failed_not_internal():
    from praxic.core.investigation import InvestigationModule

    mod = object.__new__(InvestigationModule)
    report = mod._parse_response('{"facts": [{"id": "f1", "content": "被截断', "q")
    assert report.parse_failed is True
    assert report.facts[0].source_type == "parse_error"
    assert report.facts[0].credibility == 0.0


def test_investigate_retries_with_half_budget_on_truncation():
    from praxic.core.investigation import InvestigationModule

    async def _run():
        truncated = '{"facts": [{"id": "f1", "content": "vibe coding 是 Karpathy 提出'
        valid = '{"facts": [], "gaps": [], "summary": "ok"}'
        llm = SeqLLM([truncated, valid])
        mod = InvestigationModule(llm=llm, web_search_enabled=False, workspace=None)
        report = await mod.investigate(
            question="vibe research 的工作流",
            skip_external_collection=True,
        )
        assert llm.calls == 2
        assert report.parse_failed is False
        assert llm.max_tokens_seen[1] is not None
        assert llm.max_tokens_seen[1] < llm.max_tokens_seen[0]

    asyncio.run(_run())

