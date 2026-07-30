"""即物穷理 —— 认知循环智能体（`python -m praxic` / PyInstaller 入口）"""
from __future__ import annotations
import sys, subprocess, threading, webbrowser, signal, os, socket, argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000

# PyInstaller frozen: sys._MEIPASS is read-only temp dir; CWD should be exe dir
if getattr(sys, 'frozen', False):
    _ROOT = sys._MEIPASS
    _CWD = os.path.dirname(sys.executable)
    os.chdir(_CWD)
else:
    _ROOT = HERE.parent
    _CWD = str(_ROOT)

# ── Auto-activate .venv if present ──
if sys.version_info < (3, 10):
    sys.exit("需要 Python 3.10+")
try:
    import uvicorn  # noqa
except ImportError:
    _venv = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "Scripts", "python.exe"))
    if not os.path.exists(_venv):
        _venv = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "bin", "python3"))
    if os.path.exists(_venv) and _venv != sys.executable:
        print("[即物穷理] 切换虚拟环境:", _venv)
        os.execv(_venv, [_venv] + sys.argv)
    for m in ["uvicorn", "fastapi", "pydantic", "structlog"]:
        try:
            __import__(m)
        except ImportError:
            sys.exit(f"缺少 {m}, Python: {sys.executable}")


def _ensure_config():
    cfg = os.path.join(os.getcwd(), "config.toml")
    if os.path.exists(cfg):
        return
    for fname in ("config.toml", "config.toml.example"):
        bundled = os.path.join(_ROOT, fname)
        if os.path.exists(bundled):
            import shutil
            shutil.copy(bundled, cfg)
            print("[即物穷理] 已复制配置:", cfg)
            print("[即物穷理] 请编辑此文件填入你的 API Key 后重新启动")
            return
    with open(cfg, "w", encoding="utf-8") as f:
        f.write('[llm]\nprovider="openai_compatible"\nbase_url="https://api.deepseek.com"\napi_key=""\nmodel="deepseek-v4-pro"\n')
    print("[即物穷理] 已创建默认配置:", cfg)


def _port_is_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.bind((host, port))
        s.close()
        return True
    except OSError:
        return False


def _kill_port(port: int):
    if sys.platform != "win32":
        return
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if (f":{port}") in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid and pid != "0":
                    print(f"[即物穷理] 关闭端口 {port} 旧进程 PID={pid}")
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                    import time; time.sleep(0.5)
                    break
    except Exception as e:
        print(f"[即物穷理] 关闭旧进程出错: {e}")


def _find_free_port(host: str, start: int) -> int:
    """Find a free port starting from `start`. Tries neighbors, then kills old process on start as last resort."""
    if _port_is_free(host, start):
        return start

    print(f"[即物穷理] 端口 {start} 已被占用，尝试切换…")
    for offset in range(1, 11):
        if _port_is_free(host, start + offset):
            print(f"[即物穷理] 自动切换至端口 {start + offset}")
            return start + offset

    # All ports start..start+10 busy — kill the old one on the original port and retry
    print(f"[即物穷理] 端口 {start}-{start+10} 均被占用，强制关闭 {start}…")
    _kill_port(start)
    import time; time.sleep(1)
    if _port_is_free(host, start):
        return start

    # Desperate: random high port
    from random import randint
    while True:
        p = randint(1024, 65535)
        if _port_is_free(host, p):
            print(f"[即物穷理] 随机分配端口 {p}")
            return p


def _print_help(url: str):
    print()
    print(f"  即物穷理已启动 -> {url}")
    print(f"  按 R + Enter 重启服务")
    print(f"  按 Q + Enter 或 Ctrl+C 停止服务")
    print()


def run_forever(host: str, port: int, open_browser: bool = True):
    _ensure_config()
    port = _find_free_port(host, port)
    url = f"http://localhost:{port}"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    proc: subprocess.Popen | None = None

    def _start() -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "praxic.api.server:app",
             "--host", host, "--port", str(port),
             "--log-level", "info"],
            cwd=str(HERE.parent),
            stdout=None,           # inherit parent stdout
            stderr=subprocess.STDOUT,  # merge stderr → stdout (avoids PowerShell error wrapping)
        )

    def _stdin_listener():
        nonlocal proc
        while True:
            try:
                cmd = sys.stdin.readline().strip().lower()
            except (EOFError, OSError):
                break
            if cmd in ("q", "quit"):
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                os._exit(0)
            elif cmd in ("r", "restart"):
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                proc = _start()
                _print_help(url)

    _print_help(f"http://localhost:{port}")
    listener = threading.Thread(target=_stdin_listener, daemon=True)
    listener.start()

    def _sigint(*_):
        if proc and proc.poll() is None:
            proc.terminate()
        os._exit(0)
    signal.signal(signal.SIGINT, _sigint)

    proc = _start()
    proc.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="即物穷理 Praxic")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"监听端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST,
                        help=f"监听地址（默认 {DEFAULT_HOST}）")
    args = parser.parse_args()

    run_forever(host=args.host, port=args.port, open_browser=not args.no_browser)
