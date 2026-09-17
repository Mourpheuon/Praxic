from pathlib import Path
import sys
import pytest


def test_frozen_logs_use_utf8_even_with_western_windows_encoding(monkeypatch):
    import io
    import praxic.__main__ as entry
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding='cp1252')
    monkeypatch.setattr(entry.sys, 'stdout', stream)
    monkeypatch.setattr(entry.sys, 'stderr', None)
    entry._configure_stdio()
    print('即物穷理 用户数据', file=stream)
    assert '即物穷理' in raw.getvalue().decode('utf-8')


def test_frozen_server_runs_in_process(monkeypatch, tmp_path):
    import praxic.__main__ as entry
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entry.sys, 'frozen', True, raising=False)
    monkeypatch.setenv('PRAXIC_RUNTIME_DIR', str(tmp_path / '用户数据'))
    monkeypatch.setattr(entry, '_ROOT', tmp_path)
    monkeypatch.setattr(entry.subprocess, 'Popen', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('must not reexec')))
    calls = []
    monkeypatch.setattr(entry.uvicorn, 'run', lambda *a, **kw: calls.append((a, kw)))
    entry.run_forever('127.0.0.1', 18881, open_browser=False)
    assert Path.cwd() == tmp_path / '用户数据'
    assert (Path.cwd() / 'config.toml').is_file()
    assert calls == [(('praxic.api.server:app',), {'host': '127.0.0.1', 'port': 18881, 'log_level': 'info'})]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows default runtime directory')
def test_frozen_default_directory_is_not_install_dir(monkeypatch, tmp_path):
    import praxic.__main__ as entry
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entry.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(entry.sys, 'platform', 'win32')
    monkeypatch.delenv('PRAXIC_RUNTIME_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    entry._prepare_runtime_dir()
    assert Path.cwd() == tmp_path / 'local' / 'Praxic' / 'backend'
