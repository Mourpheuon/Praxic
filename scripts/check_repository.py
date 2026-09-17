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
    # Documentation links must resolve without ignored handoff/experiment files.
    documents = [root / 'README.md', root / 'README_zh.md', root / 'maintenance/README.md',
                 root / 'maintenance/BUILD_RELEASE.md', root / 'praxic/web/README.md']
    for document in documents:
        text = document.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in target or target.startswith('#'):
                continue
            if not (document.parent / target.split('#')[0]).exists():
                errors.append(f'{document.relative_to(root)} broken link: {target}')
    for obsolete in ('scripts/push.sh', 'scripts/release.sh', 'scratch_probe_real.py',
                     'scripts/verify_practice_real.py', 'scripts/probe_reasoning_control.py'):
        if (root / obsolete).exists():
            errors.append('retired file restored to active tree: ' + obsolete)
    build_script = (root / 'scripts/build_desktop.py').read_text(encoding='utf-8')
    for required in ('check_repository.py', 'smoke_backend.py', "'--publish', 'never'"):
        if required not in build_script:
            errors.append('local build guard missing: ' + required)
    setup = (root / 'praxic/api/routes/setup.py').read_text(encoding='utf-8')
    if '_gh_release_create' in setup or '_bump_versions' in setup:
        errors.append('legacy API release implementation restored')
    ignore = (root / '.dockerignore').read_text(encoding='utf-8').splitlines()
    if '**' not in ignore or '**/.github-token' not in ignore:
        errors.append('Docker context exclusion guard missing')
    return errors


if __name__ == '__main__':
    failures = check()
    print('\n'.join(failures) if failures else 'Repository consistency checks passed.')
    raise SystemExit(bool(failures))
