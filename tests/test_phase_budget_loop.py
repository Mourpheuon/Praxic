# ruff: noqa: E402
"""端到端验证：反思输出 phase_budgets → cognitive_loop 写入 working_mem → 下一轮各阶段应用。

跑 2 轮迭代：第 1 轮反思返回 budget（investigation max_calls=1/low、
practice max_rounds=2/off），第 2 轮各阶段应收到并应用。
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DEEPSEEK_API_KEY"] = "x"

from praxic.config import settings
from praxic.llm.base import BaseLLM, LLMResponse

_SUPERSET = {
    "original_question": "q", "expanded_question": "用代码验证质数", "question_intent": "行动",
    "question_domains": [], "structured_sub_questions": [],
    "facts": [{"content": "质数是大于1的自然数", "credibility": 0.9}], "gaps": [],
    "summary": "质数求和",
    "principal_contradiction": {"description": "效率vs正确", "tension_poles": ["效率", "正确"],
                                "contradiction_type": "internal", "rank": 1,
                                "primary_aspect": "正确", "transformation_condition": "运行验证"},
    "secondary_contradictions": [],
    "essence": "试除法", "patterns": ["试除"], "hypotheses": ["遍历可判质数"],
    "synthesis_text": "综合", "contradiction_motion": "缓", "unexplained_phenomena": [],
    "return_to_concrete": "", "abstract_from": "",
    "round_rationale": "运行脚本建立基线", "files_to_create": [], "commands_to_run": [],
    "tool_calls": [], "expected_outcomes": [], "done": True,
    "quality_assessment": "ok", "convergence_score": 0.9,
    "should_reinvestigate": False,
    "lessons_learned": [], "final_answer": "答案是X",
    "skill_draft_candidates": [],
    # 第 1 轮反思产出预算
    "phase_budgets": {
        "investigation": {"max_calls": 1, "max_tokens": 4000,
                         "reasoning_effort": "low", "reason": "已充分"},
        "practice": {"max_rounds": 2, "reasoning_effort": "off",
                     "reason": "首轮已收敛"},
    },
}


class LoopFake(BaseLLM):
    def __init__(self):
        self.calls = []

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        sysp = system or ""
        body = json.dumps(_SUPERSET, ensure_ascii=False)
        self.calls.append({
            "sys": sysp[:40],
            "max_tokens": max_tokens,
            "reasoning_effort": kwargs.get("reasoning_effort"),
            "enable_reasoning": kwargs.get("enable_reasoning"),
        })
        # practice 的文件生成走这里（否则 content 为 JSON 会被当代码）
        if "文件 {path} 生成可运行内容" in str(messages[-1].get("content", "")):
            return LLMResponse(content="print('ok')", model="fake")
        return LLMResponse(content=body, model="fake")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


def test_practice_rounds_capped_by_budget_in_run():
    from praxic.core.autonomy import PermissionMode
    from praxic.core.cognitive_loop import CognitiveLoop
    settings.max_iterations = 2
    settings.practice_rounds = 3
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False
    settings.permission_mode = PermissionMode.AUTO_REVIEW

    # 隔离工作区
    wd = tempfile.mkdtemp(prefix="budget-loop-")
    try:
        fake = LoopFake()
        loop = CognitiveLoop(llm=fake)
        settings.workspace_dir = Path(wd)
        for attr in ("preprocessing", "investigation", "contradiction", "rational",
                     "practice", "reflection"):
            obj = getattr(loop, attr, None)
            if obj is not None and hasattr(obj, "llm"):
                obj.llm = fake
        loop.workspace.workspace = Path(wd)

        r = asyncio.run(loop.run(
            question="用Python计算质数之和", mode="standard",
            session_id="budgettest", conversation_id="budgettest",
        ))
        t = r.full_trace
        assert t.practice is not None
        assert t.reflection is not None
        # 反思输出里解析到了预算
        assert t.reflection.phase_budgets["practice"]["max_rounds"] == 2
        assert t.reflection.phase_budgets["investigation"]["reasoning_effort"] == "low"
        # 实践只跑了预算限制的轮数（首轮 + 至多1补充 = 2），不因 practice_rounds=3 而多跑
        # 通过日志/时长无法直接拿轮数，这里验证 practice 阶段收到的 max_rounds 已被读取
        # （直接检查 practice 模块在当前迭代末尾的状态）
        assert getattr(loop.practice, "_current_budget", {}).get("max_rounds") == 2
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_investigation_budget_kwargs_in_run():
    """在真实 run 中被注入的 investigation 预算应透传到其 llm.call。"""
    from praxic.core.investigation import InvestigationModule
    fake = LoopFake()
    inv = InvestigationModule(llm=fake, phase_config={}, web_search_enabled=False, workspace=None)
    fake.calls = []
    asyncio.run(inv.investigate(
        "q", budget={"depth": "deep", "max_tokens": 4000}))
    # 主调用（不含搜索 query 生成，因为无 key 不联网）用 max_tokens=4000，深度由 depth 控制
    main_call = fake.calls[-1]
    assert main_call["reasoning_effort"] is None  # 不再透传推理私有参数
    assert main_call["max_tokens"] == 4000
    assert main_call["sys"]  # system 有内容（含 DEEP 档 schema 说明）
