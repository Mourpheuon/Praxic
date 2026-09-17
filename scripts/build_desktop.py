"""One local build path: consistency -> frozen backend -> smoke -> native shell.

Prerequisites: python -m pip install -e ".[desktop]" pyinstaller; npm ci.
Never publishes. Cross-platform releases are built on native GitHub runners.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def commands(backend_only=False, shell_only=False):
    steps = [[sys.executable, str(ROOT / 'scripts/check_repository.py')]]
    if not shell_only:
        steps.append([sys.executable, '-m', 'PyInstaller', 'praxic.spec', '--noconfirm', '--clean'])
    steps.append([sys.executable, str(ROOT / 'scripts/smoke_backend.py')])
    if not backend_only:
        node = os.environ.get('PRAXIC_NODE_PATH') or shutil.which('node')
        if node and Path(node).is_dir():
            node = str(Path(node) / ('node.exe' if os.name == 'nt' else 'node'))
        builder = ROOT / 'node_modules/electron-builder/cli.js'
        if not node or not builder.is_file():
            raise RuntimeError('Node.js / electron-builder missing: install Node.js and run npm ci first.')
        if sys.platform == 'darwin':
            steps.append(['iconutil', '-c', 'icns', 'assets/icon.iconset', '-o', 'assets/icon.icns'])
        target = {'win32': '--win', 'darwin': '--mac'}.get(sys.platform, '--linux')
        steps.append([node, str(builder), target, '--publish', 'never'])
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--backend-only', action='store_true')
    mode.add_argument('--shell-only', action='store_true', help='Verify an existing backend before packaging')
    args = parser.parse_args()
    try:
        for command in commands(args.backend_only, args.shell_only):
            subprocess.run(command, cwd=ROOT, check=True)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Build failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
