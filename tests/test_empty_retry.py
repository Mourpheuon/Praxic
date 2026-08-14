# ruff: noqa: E402
"""empty_content 兜底重试（E1）—— 模型无关，放 adapter 层。"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DEEPSEEK_API_KEY"] = "x"

from praxic.llm.openai_compatible import OpenAICompatibleLLM


def _choice(content, finish_reason):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, reasoning_content=None),
        finish_reason=finish_reason,
    )


def _resp(choice):
    return SimpleNamespace(
        choices=[choice],
        model="test-model",
        usage=None,
    )


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **params):
        self.calls.append(params)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Client:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_Completions(responses))


def _build_llm(responses):
    llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
    llm.default_model = "test-model"
    llm._client = _Client(responses)
    return llm


def test_empty_content_retries_with_doubled_tokens():
    """第一次返回空 content + finish=length，第二次成功；断言 max_tokens 翻倍且只重试一次。"""
    first = _resp(_choice("", "length"))
    second = _resp(_choice("ok", "stop"))
    llm = _build_llm([first, second])

    import asyncio
    result = asyncio.run(llm.call(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=500,
    ))

    create = llm._client.chat.completions
    assert len(create.calls) == 2
    assert create.calls[1]["max_tokens"] == 1000  # 翻倍
    assert result.content == "ok"


def test_non_empty_no_retry():
    """content 非空不触发重试（默认行为不变）。"""
    ok = _resp(_choice("fine", "stop"))
    llm = _build_llm([ok])

    import asyncio
    result = asyncio.run(llm.call(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=500,
    ))
    assert len(llm._client.chat.completions.calls) == 1
    assert result.content == "fine"


def test_empty_not_length_no_retry():
    """空 content 但 finish_reason 非 length，不重试（只空交上层 fallback）。"""
    empty = _resp(_choice("", "stop"))
    llm = _build_llm([empty])

    import asyncio
    result = asyncio.run(llm.call(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=500,
    ))
    assert len(llm._client.chat.completions.calls) == 1
    assert result.content == ""


def test_retry_still_empty_returns_empty():
    """重试后仍空则返回空，交上层 fallback，不再继续递归。"""
    empty1 = _resp(_choice("", "length"))
    empty2 = _resp(_choice("", "length"))
    llm = _build_llm([empty1, empty2])

    import asyncio
    result = asyncio.run(llm.call(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=500,
    ))
    create = llm._client.chat.completions
    assert len(create.calls) == 2  # 只重试一次
    assert result.content == ""
