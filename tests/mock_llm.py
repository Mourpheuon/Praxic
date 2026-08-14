"""Mock LLM for testing."""
from __future__ import annotations
from typing import AsyncIterator, Optional
from praxic.llm.base import BaseLLM, LLMResponse

class MockLLM(BaseLLM):
    def __init__(self, default_model="mock-model", default_response="{}"):
        self._next_response = ""
        self._next_responses = []
        self._next_metadata = None
        self._call_count = 0
        self._call_history = []
        self._default_model = default_model
        self._default_response = default_response

    @property
    def call_count(self):
        return self._call_count

    @property
    def call_history(self):
        return self._call_history

    def set_response(self, content):
        self._next_response = content

    def set_response_with_metadata(self, content, metadata):
        self._next_response = content
        self._next_metadata = metadata

    def set_responses(self, contents):
        self._next_responses = list(contents)

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        self._call_count += 1
        self._call_history.append({
            "messages": messages, "system": system,
            "temperature": temperature, "max_tokens": max_tokens,
            "kwargs": dict(kwargs),
        })
        if self._next_responses:
            content = self._next_responses.pop(0)
            self._last_response = content
        elif self._next_response:
            content = self._next_response
            self._last_response = content
        else:
            # Repeat the last response when queue is exhausted
            content = getattr(self, '_last_response', self._default_response)
        meta = self._next_metadata
        self._next_metadata = None
        return LLMResponse(content=content, model=self._default_model, metadata=meta or {})

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        content = await self.call(messages, system, temperature, max_tokens, **kwargs)
   