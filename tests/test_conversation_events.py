"""会话事件流：发言人标记、用户消息入事件、结构化上下文提取。"""
import json
import pytest

from praxic.api.schemas.models import ContradictionGraph, Contradiction, ContradictionType
from praxic.memory.episodic_memory import EpisodicMemory


@pytest.fixture
def mem(tmp_path):
    return EpisodicMemory(db_path=tmp_path / "episodic.db")


def _contra_graph(thinking="思维链内容"):
    return ContradictionGraph(
        principal_contradiction=Contradiction(
            description="主要矛盾描述", tension_poles=["A", "B"],
            contradiction_type=ContradictionType.INTERNAL, rank=1,
        ),
        thinking_trace=thinking,
        iteration=1,
    )


class TestSpeakerMarking:
    def test_speaker_column_migrated_default_agent(self, mem):
        """speaker 列存在且默认 agent（迁移兼容）。"""
        mem.append_conversation_event("c1", "s1", "investigation", "调查完成", "phase", {"event_type": "phase"})
        turns = mem.get_conversation_turns("c1")
        # 无 episode 时 turns 为空；直接查事件
        import sqlite3
        conn = sqlite3.connect(mem.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT speaker FROM conversation_events").fetchone()
        assert row["speaker"] == "agent"

    def test_append_with_explicit_speaker(self, mem):
        mem.append_conversation_event("c1", "s1", "practice", "执行 python_exec", "tool_call",
                                      {"event_type": "tool_call", "tool": "python_exec"}, speaker="tool")
        mem.append_conversation_event("c1", "s1", "contradiction", "矛盾分析完成", "phase",
                                      _contra_graph(), speaker="agent")
        import sqlite3
        conn = sqlite3.connect(mem.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT speaker, phase FROM conversation_events ORDER BY id").fetchall()
        assert [r["speaker"] for r in rows] == ["tool", "agent"]

    def test_turns_recover_speaker(self, mem):
        mem.save_episode(session_id="s1", conversation_id="c1", question="q", summary="摘要")
        mem.append_conversation_event("c1", "s1", "contradiction", "矛盾分析完成", "phase",
                                      _contra_graph(), speaker="agent")
        mem.append_conversation_event("c1", "s1", "practice", "工具执行", "tool_call",
                                      {"event_type": "tool_call"}, speaker="tool")
        turns = mem.get_conversation_turns("c1")
        logs = turns[0]["phase_logs"]
        speakers = [e["speaker"] for e in logs]
        assert "agent" in speakers and "tool" in speakers
        # thinking_trace 在结构化 data 里完整保留
        contra = [e for e in logs if e["phase"] == "contradiction"][0]
        assert contra["data"]["thinking_trace"] == "思维链内容"


class TestUserMessage:
    def test_record_user_message(self, mem):
        eid = mem.record_user_message("c1", "s1", "用户的问题", context="背景")
        assert eid is not None
        import sqlite3
        conn = sqlite3.connect(mem.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM conversation_events WHERE id=?", (eid,)).fetchone()
        assert row["speaker"] == "user"
        assert row["event_type"] == "user_question"
        data = json.loads(row["data"])
        assert data["content"] == "用户的问题"
        assert data["context"] == "背景"

    def test_record_user_message_no_conversation_returns_none(self, mem):
        assert mem.record_user_message("", "s1", "问题") is None


class TestStructuredContext:
    def test_events_context_groups_by_speaker_and_phase(self, mem):
        mem.save_episode(session_id="s1", conversation_id="c1", question="q", summary="摘要")
        mem.record_user_message("c1", "s1", "用户的问题是什么？")
        mem.append_conversation_event("c1", "s1", "investigation", "发现3条事实", "phase",
                                      {"event_type": "phase"}, speaker="agent")
        mem.append_conversation_event("c1", "s1", "contradiction", "主要矛盾：能力不足", "phase",
                                      _contra_graph(), speaker="agent")
        mem.append_conversation_event("c1", "s1", "practice", "执行 python_exec", "tool_call",
                                      {"event_type": "tool_call", "tool": "python_exec"}, speaker="tool")
        ctx = mem._events_conversation_context("c1")
        assert "【用户】用户的问题是什么？" in ctx
        assert "【智能体·调查研究】发现3条事实" in ctx
        assert "【智能体·矛盾分析】主要矛盾：能力不足" in ctx
        assert "【工具·python_exec】执行 python_exec" in ctx
        # 时间顺序：用户在前
        assert ctx.index("【用户】") < ctx.index("【智能体·调查研究】")

    def test_events_context_excludes_other_sessions(self, mem):
        mem.save_episode(session_id="s1", conversation_id="c1", question="q", summary="摘要")
        mem.record_user_message("c1", "s1", "本轮问题")
        mem.record_user_message("c1", "s_other", "其他会话问题")
        ctx = mem._events_conversation_context("c1", exclude_session="s_other")
        assert "本轮问题" in ctx
        assert "其他会话问题" not in ctx

    def test_build_context_prefers_events_falls_back_episodes(self, mem):
        # 无事件时回退 episodes 拼装（兼容旧数据）
        mem.save_episode(session_id="s1", conversation_id="c1", question="旧问题", summary="旧结论")
        ctx = mem.build_conversation_context(conversation_id="c1", current_question="新问题")
        assert "旧问题" in ctx
        assert "旧结论" in ctx
        assert "此前对话记录" in ctx

    def test_build_context_with_events(self, mem):
        mem.save_episode(session_id="s1", conversation_id="c1", question="q", summary="摘要")
        mem.record_user_message("c1", "s1", "上一轮用户问题")
        mem.append_conversation_event("c1", "s1", "contradiction", "主要矛盾判断", "phase",
                                      _contra_graph(), speaker="agent")
        ctx = mem.build_conversation_context(conversation_id="c1", current_question="新问题")
        assert "上一轮用户问题" in ctx
        assert "主要矛盾判断" in ctx
        assert "按发言人/阶段" in ctx


class TestLoopIntegration:
    """CognitiveLoop 端到端：用户问题入事件、阶段事件带 speaker、思维链落库。"""

    @pytest.mark.asyncio
    async def test_loop_records_speaker_events_and_thinking(self, tmp_path, monkeypatch):
        import json as _json
        from praxic.core.cognitive_loop import CognitiveLoop
        from tests.mock_llm import MockLLM

        mem = EpisodicMemory(db_path=tmp_path / "episodic.db")

        INV = _json.dumps({"facts": [{"id": "f1", "content": "事实1", "source_type": "internal", "credibility": 0.8}],
                           "gaps": [], "summary": "调查完成"})
        CONTR = _json.dumps({"principal_contradiction": {"description": "主要矛盾", "tension_poles": ["A", "B"],
                                                        "contradiction_type": "internal", "rank": 1,
                                                        "primary_aspect": "A"},
                             "secondary_contradictions": [], "dynamic_note": "", "synthesis": ""})
        RATION = _json.dumps({"essence": "本质", "patterns": [], "hypotheses": [], "synthesis_text": "",
                              "contradiction_motion": "", "quantitative_changes": [], "qualitative_threshold": "",
                              "negation_of_negation": "", "fact_foundation": ""})

        mk = MockLLM()
        # 预处理若干次调用 + 调查 + 矛盾 + 理性
        mk.set_responses([INV, CONTR, RATION])
        mk._next_metadata = {"reasoning": "矛盾分析的思维链内容"}

        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        loop.episodic = mem
        await loop.run(question="测试问题", mode="fast", conversation_id="c1", session_id="s1")

        turns = mem.get_conversation_turns("c1")
        # 事件流里有用户发言、矛盾阶段、理性阶段
        all_events = [e for t in turns for e in t.get("phase_logs", [])]
        speakers = {e["speaker"] for e in all_events}
        assert "user" in speakers
        assert "agent" in speakers
        user_evs = [e for e in all_events if e["speaker"] == "user"]
        assert user_evs and user_evs[0]["data"]["content"] == "测试问题"
        # 矛盾阶段事件保留 thinking_trace（思维链随图落库）
        contra_evs = [e for e in all_events if e["phase"] == "contradiction"]
        assert contra_evs
        if contra_evs[0].get("data") and contra_evs[0]["data"].get("thinking_trace"):
            assert "思维链内容" in contra_evs[0]["data"]["thinking_trace"]
