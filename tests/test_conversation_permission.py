"""对话级权限：存储、API、CognitiveLoop 覆盖。"""
import pytest

from praxic.config import settings
from praxic.core.autonomy import PermissionMode
from praxic.core import conversation_permissions as cp
from praxic.core.cognitive_loop import CognitiveLoop
from praxic.llm.base import BaseLLM, LLMResponse


class _FakeLLM(BaseLLM):
    async def call(self, *a, **k):
        return LLMResponse(content="{}", model="f")

    async def stream(self, *a, **k):
        yield ""


@pytest.fixture(autouse=True)
def _clean_store(tmp_path, monkeypatch):
    """隔离存储文件到临时目录，测试后清理。"""
    monkeypatch.setattr(cp, "_store_path", lambda: tmp_path / "conv-perms.json")
    yield
    cp._store_path().unlink(missing_ok=True)


def test_store_set_get_clear():
    assert cp.get_conversation_permission("c1") is None
    cp.set_conversation_permission("c1", "auto_review")
    assert cp.get_conversation_permission("c1") == "auto_review"
    cp.clear_conversation_permission("c1")
    assert cp.get_conversation_permission("c1") is None


def test_apply_explicit_overrides_policy():
    cp.set_conversation_permission("c-full", "full")
    loop = CognitiveLoop(llm=_FakeLLM())
    loop._apply_conversation_permission("c-full")
    assert loop._registry.policy.permission_mode == PermissionMode.FULL


def test_apply_no_explicit_resets_to_global_default(monkeypatch):
    # 先设全局默认非 ASK，验证无显式对话回落到它
    monkeypatch.setattr(settings, "permission_mode", PermissionMode.AUTO_REVIEW)
    loop = CognitiveLoop(llm=_FakeLLM())
    loop._apply_conversation_permission("c-none")
    assert loop._registry.policy.permission_mode == PermissionMode.AUTO_REVIEW


def test_apply_auto_review_wires_reviewer_then_removes():
    cp.set_conversation_permission("c-r", "auto_review")
    loop = CognitiveLoop(llm=_FakeLLM())
    loop._apply_conversation_permission("c-r")
    assert loop._registry.policy.reviewer is not None
    cp.set_conversation_permission("c-r", "ask")
    loop._apply_conversation_permission("c-r")
    assert loop._registry.policy.reviewer is None


def test_invalid_mode_ignored(monkeypatch):
    monkeypatch.setattr(cp, "_load", lambda: {"c-bad": "not_a_mode"})
    loop = CognitiveLoop(llm=_FakeLLM())
    # 不应抛异常，保持全局默认
    loop._apply_conversation_permission("c-bad")
    assert loop._registry.policy.permission_mode == settings.permission_mode
