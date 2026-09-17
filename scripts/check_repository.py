"""Read-only consistency check for release metadata and active entrypoints."""
import ast
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    errors = []
    tree = ast.parse((root / 'praxic/__init__.py').read_text(encoding='utf-8'))
    version = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    if project['project']['version'] != version:
        errors.append('pyproject.toml version mismatch')
    for folder in ('', 'praxic/web/'):
        for filename in ('package.json', 'package-lock.json'):
            path = folder + filename
            data = json.loads((root / path).read_text(encoding='utf-8'))
            if data.get('version') != version:
                errors.append(path + ' version mismatch')
            if filename == 'package-lock.json' and data.get('packages', {}).get('', {}).get('version') != version:
                errors.append(path + ' root package version mismatch')
    docker = (root / 'Dockerfile').read_text(encoding='utf-8')
    if not re.search(r'^ARG PRAXIC_VERSION=' + re.escape(version) + r'$', docker, re.M):
        errors.append('Dockerfile default version mismatch')
    for name in ('README.md', 'README_zh.md'):
        text = (root / name).read_text(encoding='utf-8')
        if 'python -m praxic run' in text or 'bash scripts/release.sh' in text:
            errors.append(name + ' obsolete command')
    if not (root / 'praxic/web/index.html').is_file():
        errors.append('active frontend missing')
    return errors


if __name__ == '__main__':
    failures = check()
    print('\n'.join(failures) if failures else 'Repository consistency checks passed.')
    raise SystemExit(bool(failures))
