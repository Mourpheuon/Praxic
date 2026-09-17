# Praxic

An AI agent organized around investigation, analysis, practical verification and iterative reflection.

Current release: **v0.2.0**, including fixes for packaged Windows backend startup, Unicode logs and writable runtime directories.

[Download](https://github.com/Mourpheuon/Praxic/releases/tag/v0.2.0) · [Upgrade notes](maintenance/releases/v0.2.0.md) · [中文](README_zh.md)

## Released applications

Select the installer matching your operating system and architecture: Windows exe, macOS dmg/zip, or Linux AppImage/deb.
Builds are currently unsigned. Back up existing configuration and data before upgrading; data from older installation directories is not migrated automatically.
Desktop runtime data lives in the user-data backend subdirectory; PRAXIC_RUNTIME_DIR overrides it. Configure the model service in Settings on first launch.

## Run from source

Python 3.11+ is required. Create and activate a virtual environment first:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[desktop]"
```

Copy config.toml.example to config.toml and .env.example to .env, or use Settings.
Keep credentials in .env, not config.toml. The template selects deepseek-v4-flash; the no-config code fallback selects deepseek-v4-pro. Both are configurable.

```bash
python -m praxic --host 127.0.0.1
praxic run "Your question" --mode standard
praxic run --help
```

The module command launches Web; the installed praxic run command launches CLI tasks.
On Windows, start-praxic.bat prefers the project virtual environment without hardcoded drive paths.

## Scope and boundaries

- Preprocessing plus investigation, contradiction analysis, rational synthesis, practice and reflection.
- Fast, standard, deep and custom phase-skipping modes.
- Tools, authorization, projects, workspaces, session memory and resumable SSE activity.
- Phase budgets, skills and evidence-aware practical verification.
- File, web, data and execution tools; some require extra dependencies or external services.

The product frontend is the inline praxic/web/index.html served directly by FastAPI and the desktop backend; some resources require CDN access.
The web/src component tree is not connected to that product entrypoint. Vite build success does not mean the desktop UI uses those components. See [frontend boundaries](praxic/web/README.md).

## Develop and build

```bash
python -m pip install -e ".[desktop,dev]" pyinstaller
npm ci
python scripts/check_repository.py
python -m pytest -q
node --test tests/backend-ready.test.cjs
python scripts/build_desktop.py
```

Local builds target the current OS only and never publish: consistency checks → frozen backend → startup/version smoke → Electron installer.
npm run electron:build packages an existing backend after validation.
Output is in dist-electron, with names such as Praxic-0.2.0-win-x64.exe.

Official releases use the GitHub tag workflow, with all native builds and checks required before publication.
The former in-app build/release endpoints now return HTTP 410; they cannot delete releases or rewrite tags.

See [build and release procedures](maintenance/BUILD_RELEASE.md).

## Repository map

| Path | Responsibility |
| --- | --- |
| praxic/core/ | Orchestration and phase modules |
| praxic/cordis/ | Composition and session lifecycle |
| praxic/tools/ | Tools, permissions and execution contracts |
| praxic/memory/ | Memory, retrieval and context caching |
| praxic/llm/ | Model adapters and call caching |
| praxic/api/ | Settings, sessions, projects and streaming |
| praxic/web/ | Inline product UI and unintegrated components |
| electron/ | Desktop host and backend readiness |
| scripts/ | Build, check and import commands |
| scripts/diagnostics/ | Explicit real-service probes that may incur charges |
| tests/ | Automated regression |
| maintenance/ | Current boundaries, release notes and historical evidence |

Local archives, credentials, runtime data and build outputs are excluded from Git.
See [maintenance inventory](maintenance/README.md). Project metadata declares the MIT license.
