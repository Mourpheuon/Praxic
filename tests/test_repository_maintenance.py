"""Guard against known documentation/metadata drift without model calls."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repository_consistency():
    spec = importlib.util.spec_from_file_location('check_repository', ROOT / 'scripts/check_repository.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check() == []


async def test_api_version_and_missing_frontend(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from praxic import __version__
    from praxic.api import server

    app = server.create_app()
    assert app.version == __version__
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/')
    assert (await endpoint()).status_code == 200
    monkeypatch.setattr(server, 'WEB_DIR', tmp_path)
    import pytest
    with pytest.raises(HTTPException) as exc:
        await endpoint()
    assert exc.value.status_code == 503
