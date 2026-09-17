import importlib.util
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location('build_desktop', ROOT / 'scripts/build_desktop.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backend_build_order():
    plan = load_build().commands(backend_only=True)
    assert plan[0][-1].endswith('check_repository.py')
    assert plan[1][1:3] == ['-m', 'PyInstaller']
    assert plan[2][-1].endswith('smoke_backend.py')
    assert len(plan) == 3


def test_shell_build_always_checks_backend_and_never_publishes(monkeypatch, tmp_path):
    module = load_build()
    builder = tmp_path / 'node_modules/electron-builder/cli.js'
    builder.parent.mkdir(parents=True)
    builder.touch()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setenv('PRAXIC_NODE_PATH', 'node')
    plan = module.commands(shell_only=True)
    assert not any('PyInstaller' in command for command in plan)
    assert plan[1][-1].endswith('smoke_backend.py')
    assert plan[-1][-2:] == ['--publish', 'never']


def test_failed_check_stops_build(monkeypatch):
    module = load_build()
    monkeypatch.setattr(sys, 'argv', ['build_desktop.py', '--backend-only'])
    calls = []
    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(module.subprocess, 'run', fail)
    assert module.main() == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retired_release_endpoints_have_no_side_effects(monkeypatch):
    import asyncio
    from praxic.api.server import create_app
    async def forbidden(*args, **kwargs):
        raise AssertionError('retired endpoint spawned a process')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url='http://test') as client:
        response = await client.post('/api/v1/setup/build-electron', json={'release_version': '0.2.0', 'skip_build': True})
        assert response.status_code == 410
        assert 'GitHub' in response.json()['detail']
        assert (await client.get('/api/v1/setup/release-check')).status_code == 410


def test_active_ui_no_longer_calls_retired_endpoints():
    text = (ROOT / 'praxic/web/index.html').read_text(encoding='utf-8')
    assert '/setup/build-electron' not in text
    assert '/setup/release-check' not in text
