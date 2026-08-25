"""混合记忆检索测试：中文问题不再依赖 split()+LIKE。"""

from pathlib import Path

from praxic.core.internal_facts import build_memory_context
from praxic.memory.episodic_memory import EpisodicMemory
from praxic.memory.semantic_memory import SemanticMemory


def test_episodic_bm25_retrieves_chinese_without_exact_sentence(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    mem.save_episode(
        "lean-session",
        "如何检查 Lean 工具链是否可运行",
        "应调用 command_exists 批量检测 lean 和 lake 的路径及版本。",
    )
    mem.save_episode(
        "tomato-session",
        "如何种植番茄",
        "应控制光照和浇水。",
    )
    # 旧 split()+LIKE 会把整句当成一个 LIKE 条件，无法命中第一条。
    rows = mem.search("你可以运行Lean代码吗", limit=2)
    assert rows
    assert "Lean" in rows[0]["question"]
    assert rows[0]["_retrieval_method"] == "bm25_hybrid"
    assert rows[0]["_retrieval_score"] > 0


def test_semantic_bm25_retrieves_relevant_memory(tmp_path: Path):
    mem = SemanticMemory(tmp_path / "semantic.db")
    lean_id = mem.store(
        "对于 Lean 或 Lake 等命令能力，应调用 command_exists 批量探测路径和版本。",
        domain="agent-tools", category="heuristic", confidence=0.9,
    )
    mem.store(
        "番茄需要充足光照和适度浇水。",
        domain="gardening", category="pattern", confidence=0.9,
    )
    rows = mem.retrieve("你能运行 Lean 代码吗", limit=2)
    assert rows
    assert rows[0]["id"] == lean_id
    assert rows[0]["_retrieval_method"] == "bm25_hybrid"
    formatted = mem.format_for_context(rows)
    assert "检索相关度" in formatted
    assert "原置信" in formatted


def test_no_bm25_match_does_not_inject_unrelated_records(tmp_path: Path):
    mem = SemanticMemory(tmp_path / "semantic.db")
    mem.store("番茄需要光照。", confidence=0.9)
    # 无重叠字符/英文 token 时返回空，不把最近记忆伪装为相关知识。
    assert mem.retrieve("quantum entanglement photon", limit=5) == []


def test_internal_context_does_not_append_global_recent_noise(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    mem.save_episode("tomato", "如何种植番茄", "控制光照。")
    # 非跟进问题无相关命中时不应把无关的全局最近记录塞入内部事实。
    assert build_memory_context("quantum entanglement photon", episodic=mem) == ""


def test_follow_up_uses_only_same_conversation_recent_memory(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    mem.save_episode("lean", "如何检查 Lean 工具链", "调用 command_exists。", conversation_id="conv-lean")
    mem.save_episode("tomato", "如何种植番茄", "控制光照。", conversation_id="conv-tomato")
    text = build_memory_context("再试", episodic=mem, conversation_id="conv-lean")
    assert "Lean" in text
    assert "番茄" not in text