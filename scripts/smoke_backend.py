"""Exercise a frozen backend from an isolated, writable runtime, with no API keys."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


def smoke(executable):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='praxic smoke 中文 ') as temp:
        runtime = Path(temp) / 'runtime'
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('PRAXIC_', 'DEEPSEEK_', 'ANTHROPIC_', 'OPENAI_', 'TAVILY_'))}
        env.update(PRAXIC_RUNTIME_DIR=str(runtime), PYTHONIOENCODING='utf-8')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with tempfile.TemporaryFile() as logs:
            child = subprocess.Popen([str(executable.resolve()), '--no-browser', '--host', '127.0.0.1', '--port', str(port)],
                                     cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                     stdout=logs, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(f'Backend exited: {child.returncode}')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/v1/setup/status', timeout=2) as response:
                            data = json.load(response)
                        assert data['configured'] is False, 'Smoke test must not inherit API credentials'
                        break
                    except (OSError, ValueError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Backend health timeout')
                        time.sleep(0.2)
                for route in ('/', '/favicon.svg', '/assets/brand/praxic-mark-v2.svg'):
                    with opener.open(f'http://127.0.0.1:{port}{route}', timeout=5) as response:
                        assert response.status == 200
                        assert response.read(), route
                assert (runtime / 'config.toml').is_file()
                print('Frozen backend smoke passed: health, HTML, static assets, Unicode runtime path.')
            except Exception:
                logs.seek(0)
                print(logs.read().decode('utf-8', errors='replace')[-8000:])
                raise
            finally:
                if child.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True)
                    else:
                        child.terminate()
                    child.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', nargs='?', type=Path,
                        default=Path('dist') / ('praxic-backend.exe' if os.name == 'nt' else 'praxic-backend'))
    smoke(parser.parse_args().executable)
