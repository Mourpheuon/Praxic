from __future__ import annotations

import asyncio
import os

import httpx

from praxic.config import _normalize_no_proxy_for_httpx


def test_httpx_accepts_ipv6_no_proxy_entries(monkeypatch):
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,::1/128,2001:db8::/32,127.0.0.1")

    _normalize_no_proxy_for_httpx()

    no_proxy = os.environ.get("NO_PROXY", "")
    assert "::1" in no_proxy
    assert "::1/128" not in no_proxy
    assert "2001:db8::/32" not in no_proxy

    client = httpx.AsyncClient(timeout=1.0)
    asyncio.run(client.aclose())
