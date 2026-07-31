from __future__ import annotations

import pytest

from praxic.config import settings
from praxic.core.cognitive_loop import CognitiveLoop
from praxic.llm.base import BaseLLM, LLMResponse
from praxic.tools.permissions import PermissionPolicy
from praxic.tools.registry import ToolRegistry
from praxic.tools.web_fetch import WebFetchTool


class _DummyLLM(BaseLLM):
    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        return LLMResponse(content="{}", model="dummy")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        if False:
            yield ""


@pytest.mark.asyncio
async def test_web_fetch_runs_through_tool_registry(monkeypatch):
    async def fake_fetch_one(self, url, score):
        assert url == "https://example.com/page"
        assert score == 1.0
        return {
            "url": url,
            "title": "Example",
            "text": "Fetched page content.",
            "fetched": True,
            "error": "",
        }

    monkeypatch.setattr(WebFetchTool, "_fetch_one", fake_fetch_one)
    registry = ToolRegistry(policy=PermissionPolicy(allow_network=True))
    registry.register(WebFetchTool())

    result = await registry.call("web_fetch", url="https://example.com/page")

    assert result.ok
    assert "Fetched page content." in result.content
    assert result.source == "https://example.com/page"
    assert result.metadata["fetched"] is True


def test_cognitive_loop_registers_web_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "web_search_enabled", True)
    monkeypatch.setattr(settings, "web_fetch_enabled", True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    loop = CognitiveLoop(llm=_DummyLLM(), project_id="web-fetch-registration")

    registered = loop._registry.get("web_fetch")
    assert isinstance(registered, WebFetchTool)
    assert registered.requires_network is True
