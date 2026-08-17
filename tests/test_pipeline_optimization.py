"""Regression tests for preprocessing latency."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from praxic.core.question_preprocessing import QuestionPreprocessing
from praxic.llm.base import LLMResponse
from praxic.llm.openai_compatible import OpenAICompatibleLLM


class PreprocessingLLM:
    provider_name = "mock"

    def __init__(
        self,
        *,
        complexity: str = "standard",
        fail_analysis: bool = False,
        fail_combined: bool = False,
    ):
        self.complexity = complexity
        self.fail_analysis = fail_analysis
        self.fail_combined = fail_combined
        self.calls: list[dict] = []
        self.active_analysis_calls = 0
        self.max_parallel_analysis_calls = 0

    async def call(
        self, messages, system=None, temperature=0.5, max_tokens=None, **kwargs
    ):
        step = self._step_name(system or "")
        self.calls.append({"step": step, "kwargs": kwargs})

        if step == "step1":
            content = json.dumps(
                {
                    "task_nature": "causal_explanation",
                    "complexity": self.complexity,
                    "needs_investigation": True,
                    "reasoning": "测试",
                },
                ensure_ascii=False,
            )
        elif step == "combined":
            if self.fail_combined:
                raise RuntimeError("combined failed")
            content = json.dumps(
                {
                    "contradiction_in_question": "意图矛盾",
                    "questionable_premises": ["待核实预设"],
                    "overlooked_factors": ["遗漏因素"],
                    "question_intent": "因果解释",
                    "core_anxiety": "",
                    "question_domains": ["测试"],
                    "structured_sub_questions": ["子问题"],
                    "expanded_question": "扩展问题",
                    "clarifying_questions": [],
                    "wants_detailed_report": False,
                },
                ensure_ascii=False,
            )
        elif step in {"step3", "step4"}:
            if self.fail_analysis:
                raise RuntimeError(f"{step} failed")
            self.active_analysis_calls += 1
            self.max_parallel_analysis_calls = max(
                self.max_parallel_analysis_calls, self.active_analysis_calls
            )
            await asyncio.sleep(0.03)
            self.active_analysis_calls -= 1
            if step == "step3":
                content = json.dumps({"contradiction_in_question": "意图矛盾"})
            else:
                content = json.dumps(
                    {
                        "questionable_premises": ["待核实预设"],
                        "overlooked_factors": ["遗漏因素"],
                    },
                    ensure_ascii=False,
                )
        else:
            content = json.dumps(
                {
                    "question_intent": "因果解释",
                    "core_anxiety": "",
                    "question_domains": ["测试"],
                    "structured_sub_questions": ["子问题"],
                    "expanded_question": "扩展问题",
                    "clarifying_questions": [],
                    "wants_detailed_report": False,
                },
                ensure_ascii=False,
            )
        return LLMResponse(content=content, model="mock")

    @staticmethod
    def _step_name(system: str) -> str:
        if "任务性质与复杂度" in system:
            return "step1"
        if "一次完成用户问题的意图矛盾分析" in system:
            return "combined"
        if "提问行为本身可能蕴含的矛盾" in system:
            return "step3"
        if "隐含的预设和框架" in system:
            return "step4"
        return "step5"


@pytest.mark.asyncio
async def test_preprocessing_runs_step3_and_step4_concurrently():
    llm = PreprocessingLLM(fail_combined=True)

    result = await QuestionPreprocessing(llm=llm).preprocess("为什么会出现这个现象？")

    assert llm.max_parallel_analysis_calls == 2
    assert result.contradiction_in_question == "意图矛盾"
    assert result.questionable_premises == ["待核实预设"]
    assert result.overlooked_factors == ["遗漏因素"]
    # 深度体系不再透传 reasoning_effort（provider 私有推理参数）
    assert all("reasoning_effort" not in call["kwargs"] for call in llm.calls)


@pytest.mark.asyncio
async def test_preprocessing_combined_fast_path_uses_two_calls():
    llm = PreprocessingLLM()

    result = await QuestionPreprocessing(llm=llm).preprocess("为什么会出现这个现象？")

    assert [call["step"] for call in llm.calls] == ["step1", "combined"]
    assert result.contradiction_in_question == "意图矛盾"
    assert result.questionable_premises == ["待核实预设"]
    assert result.expanded_question == "扩展问题"
    # 深度体系不再透传 reasoning_effort
    assert all("reasoning_effort" not in call["kwargs"] for call in llm.calls)


@pytest.mark.asyncio
async def test_simple_task_preserves_step4_condition():
    llm = PreprocessingLLM(complexity="simple")

    result = await QuestionPreprocessing(llm=llm).preprocess("为什么会出现这个现象？")

    steps = [call["step"] for call in llm.calls]
    assert "step3" not in steps
    assert steps == ["step1", "combined"]
    assert result.contradiction_in_question == ""
    assert result.questionable_premises == ["待核实预设"]


@pytest.mark.asyncio
async def test_parallel_analysis_keeps_per_step_fallbacks():
    llm = PreprocessingLLM(fail_analysis=True, fail_combined=True)

    result = await QuestionPreprocessing(llm=llm).preprocess("为什么会出现这个现象？")

    assert result.contradiction_in_question == ""
    assert result.questionable_premises == []
    assert result.overlooked_factors == []
    assert result.expanded_question == "扩展问题"


def _completion_response(content: str = "ok"):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content, reasoning_content=None),
        finish_reason="stop",
    )
    return SimpleNamespace(choices=[choice], usage=None, model="fake-model")


class FakeCompletions:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls: list[dict] = []

    async def create(self, **params):
        self.calls.append(deepcopy(params))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class FakeStream:
    def __init__(self, *parts: str):
        self.parts = iter(parts)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            content = next(self.parts)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        delta = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _adapter_with(completions: FakeCompletions) -> OpenAICompatibleLLM:
    adapter = object.__new__(OpenAICompatibleLLM)
    adapter.default_model = "fake-model"
    adapter._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return adapter


@pytest.mark.asyncio
async def test_openai_adapter_forwards_explicit_reasoning_controls():
    completions = FakeCompletions(_completion_response())
    adapter = _adapter_with(completions)

    response = await adapter.call(
        [{"role": "user", "content": "test"}],
        reasoning_effort="low",
        enable_reasoning=False,
    )

    assert response.content == "ok"
    assert completions.calls[0]["reasoning_effort"] == "low"
    assert completions.calls[0]["extra_body"]["enable_reasoning"] is False


@pytest.mark.asyncio
async def test_openai_adapter_retries_once_without_unsupported_control():
    completions = FakeCompletions(
        RuntimeError("Unsupported parameter: reasoning_effort"),
        _completion_response(),
    )
    adapter = _adapter_with(completions)

    response = await adapter.call(
        [{"role": "user", "content": "test"}], reasoning_effort="low"
    )

    assert response.content == "ok"
    assert completions.calls[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in completions.calls[1]


@pytest.mark.asyncio
async def test_openai_adapter_does_not_retry_unrelated_errors():
    completions = FakeCompletions(RuntimeError("rate limit exceeded"))
    adapter = _adapter_with(completions)

    with pytest.raises(RuntimeError, match="rate limit"):
        await adapter.call(
            [{"role": "user", "content": "test"}], reasoning_effort="low"
        )

    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_openai_stream_degrades_unsupported_enable_reasoning():
    completions = FakeCompletions(
        RuntimeError("enable_reasoning is not supported"),
        FakeStream("a", "b"),
    )
    adapter = _adapter_with(completions)

    parts = [
        part
        async for part in adapter.stream(
            [{"role": "user", "content": "test"}], enable_reasoning=False
        )
    ]

    assert parts == ["a", "b"]
    assert completions.calls[0]["extra_body"]["enable_reasoning"] is False
    assert "extra_body" not in completions.calls[1]
