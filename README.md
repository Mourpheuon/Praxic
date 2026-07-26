# Praxic

> **An AI agent with dialectical-materialist methodology as its cognitive core**
>
> "Jiwu" (即物) to engage with things, "Qiongli" (穷理) to exhaust their principles. Praxic = Praxis + Dialectic — knowledge forged through contradiction in practice.

---

## Cognitive Loop

```
User Input
   │
   ▼
① Investigation — No investigation, no right to speak (web search + file reading + web fetching)
   │
   ▼
② Contradiction Analysis — Identify the principal contradiction, dissect its dominant aspect
   │
   ▼
③ Rational Synthesis — Discard the dross, select the essential; eliminate the false, retain the true
   │
   ▼
④ Decision — Despise the enemy strategically, take full account of him tactically (action items + feasibility assessment)
   │
   ▼
⑤ Practice — Multi-round progressive experiments: auto-write code, execute, analyze, repair
   │
   ▼
⑥ Reflection — Practice is the sole criterion of truth (convergence judgment + evidence pipeline)
   │
   ▼
Converged? → If not, re-investigate (with reflection hints carried forward)
```

---

## Quick Start

### 1. Requirements

- Python 3.11+
- API Key (DeepSeek, OpenAI, or Anthropic)
- (Optional) Tavily API Key — for web search

### 2. Configuration

Copy and edit the config file:

```bash
cp config.toml.example config.toml
# Or configure directly via the Web UI Settings page
```

Set up your API Key (choose one):

```bash
# DeepSeek (default, recommended)
export SIWU_API_KEY="sk-xxx"
export SIWU_BASE_URL="https://api.deepseek.com"

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-xxx"

# Or write to a .env file (not tracked by Git)
cp .env.example .env
# Edit .env with your real key
```

### 3. Run

**Command Line (CLI):**

```bash
python -m siwu run "Why is my open-source project struggling to attract contributors?"
python -m siwu run "Consider a group of agents playing..." --mode deep
python -m siwu run --help   # Show all options
```

**Web UI (browser):**

```bash
python -m siwu
# Automatically opens http://localhost:8000
```

**Electron Desktop App (Windows):**

```powershell
.\scripts\build-electron.ps1
# Run dist-electron/win-unpacked/Praxic.exe after build
```

**Python SDK:**

```python
import asyncio
from siwu.core.cognitive_loop import CognitiveLoop

async def main():
    loop = CognitiveLoop()
    response = await loop.run(
        question="Why is my open-source project struggling to attract contributors?",
        mode="standard",
    )
    print(response.summary)
    for item in response.action_items:
        print(f"- {item}")

asyncio.run(main())
```

---

## Run Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `fast` | Skip contradiction/practice/reflection, single round | Simple Q&A, information lookup |
| `standard` | Full six-phase loop, multi-round practice | Most scenarios |
| `deep` | Multi-round iteration + multi-perspective review | Complex analysis, decision simulation |
| `custom` | Skip specified phases (e.g. `skip=contradiction,practice`) | Flexible control |

---

## Features

| Feature | Description |
|---------|-------------|
| **Web Search** | Tavily + web fetching, multi-result parallel |
| **File Reading** | TXT, code, PDF (multi-fallback + OCR), DOCX, XLSX, PPTX, IPYNB |
| **Multi-LLM Backend** | DeepSeek, OpenAI, Anthropic, Ollama, custom proxy |
| **Practice Engine** | Auto write code, execute, analyze results, repair errors — multi-round progressive |
| **Skill System** | Extensible skill registry, batch import (94+ skills) |
| **Project System** | Conversations organized by project, working memory shared across sessions |
| **Conversation Management** | History, SSE streaming, user steering / interrupt / termination |
| **Termination Evidence Pipeline** | Sub-question coverage + action verification + contradiction status — structured convergence |
| **Settings Persistence** | UI settings stored in `config.toml`, account config written to `.env` |
| **Electron Shell** | Windows installer, auto-launches Python backend |

---

## Project Structure

```
praxic/
├── siwu/                          # Core package
│   ├── core/                      # Cognitive engine
│   │   ├── cognitive_loop.py      # Cognitive loop controller (main entry)
│   │   ├── investigation.py       # Investigation
│   │   ├── contradiction.py       # Contradiction analysis
│   │   ├── rational.py            # Rational synthesis
│   │   ├── decision.py            # Decision engine
│   │   ├── practice.py            # Practice (multi-round experiments + auto-repair)
│   │   ├── practice_harness.py    # Practice execution prompts (high-churn, isolated)
│   │   ├── practice_classifier.py # Practice feasibility classification
│   │   ├── perspectives.py        # Multi-perspective review
│   │   ├── reflection.py          # Reflection engine (convergence + evidence pipeline)
│   │   ├── question_preprocessing.py  # Five-step preprocessing pipeline
│   │   ├── loop_controller.py     # Steering / interrupt / termination control
│   │   ├── skill_manager.py       # Skill loading & management
│   │   ├── skill_importer.py      # Batch skill import
│   │   ├── autonomy.py            # Autonomy level control
│   │   ├── credibility_chain.py   # Credibility tracing
│   │   └── dev_tracer.py          # Development tracer
│   ├── llm/                       # LLM backends
│   │   ├── base.py                # Abstract base
│   │   ├── claude.py              # Anthropic Claude
│   │   └── openai_compatible.py   # OpenAI / DeepSeek / Ollama
│   ├── tools/                     # Tool system
│   │   ├── filesystem.py          # File I/O
│   │   ├── file_loader.py         # Multi-format file reader
│   │   ├── pdf_converter.py       # PDF multi-fallback conversion + OCR
│   │   ├── web_search.py          # Tavily web search
│   │   ├── web_fetch.py           # Web content fetching
│   │   ├── search.py              # Search tool base
│   │   ├── local_retriever.py     # Local knowledge retrieval
│   │   └── base.py                # Tool abstraction
│   ├── memory/                    # Memory system
│   │   ├── working_memory.py      # Cross-round context passing
│   │   ├── episodic_memory.py     # Episodic memory (SQLite)
│   │   └── semantic_memory.py     # Semantic memory
│   ├── api/                       # REST API (FastAPI)
│   │   ├── server.py
│   │   ├── routes/
│   │   │   ├── agent.py           # Cognitive loop SSE streaming endpoint
│   │   │   ├── setup.py           # Settings / config / build routes
│   │   │   └── conversations.py   # Conversation + project management
│   │   └── schemas/models.py      # Pydantic data models
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Config management (TOML + env vars)
│   ├── web/                       # Frontend (React + Vite + Tailwind)
│   └── __main__.py                # Desktop entry (uvicorn subprocess + hot reload)
├── electron/                      # Electron shell
│   ├── main.js                    # Main process (Python subprocess management)
│   └── preload.js                 # Secure bridge (file picker etc. native APIs)
├── scripts/
│   ├── push.sh                    # GitHub token push
│   ├── release.sh                 # Version release
│   ├── import_skills.py           # Batch skill import
│   ├── build-electron.ps1         # Windows Electron build
│   └── build-electron.sh          # Linux Electron build
├── tests/                         # Tests
│   ├── test_cognitive_loop.py
│   ├── test_contradiction.py
│   ├── test_full_loop_integration.py
│   ├── test_steering.py           # Steering / interrupt / termination
│   ├── test_clarification.py      # Active clarification
│   ├── test_practice_integration.py
│   ├── test_skill_manager.py
│   └── ...
├── config.toml.example            # Config template
├── pyproject.toml
├── package.json                   # Electron dependencies
├── electron-builder.yml           # Electron packaging config
└── Dockerfile                     # Docker image
```

---

## Configuration

### Basic config

Edit `config.toml` (see `config.toml.example`):

```toml
[llm]
provider = "openai_compatible"   # openai_compatible | anthropic
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"

[runtime]
autonomy_level = "standard"      # standard | high | low
max_iterations = 5
web_search_enabled = true
```

### Environment variables (take precedence over config.toml)

| Variable | Description |
|----------|-------------|
| `SIWU_API_KEY` | OpenAI-compatible API Key |
| `SIWU_BASE_URL` | Compatible endpoint URL |
| `SIWU_MODEL` | Default model |
| `SIWU_LLM_PROVIDER` | `openai_compatible` or `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `TAVILY_API_KEY` | Tavily search API Key |

### Web UI Account Tab

The Web UI Settings dialog supports:
- Provider selection (DeepSeek / OpenAI / Anthropic / Ollama / Custom)
- Automatic model list loading
- **Connection test** — verify API Key validity before saving
- **Save config** — writes to both `config.toml` and `.env`

---

## Build & Release

### Electron Desktop App (Windows)

```powershell
npm install
cd siwu/web; npx vite build; cd ..\..
npx electron-builder
# Output: dist-electron/Praxic Setup *.exe
```

### Docker Image

```bash
docker build -t praxic .
docker run -p 8000:8000 -v $(pwd)/data:/app/data praxic
```

### Version Release

```bash
bash scripts/release.sh 0.2.0
# Updates pyproject.toml → creates release commit → tags → pushes
```

---

## License

MIT

---

*This project explores the possibility of internalizing dialectical-materialist methodology as an AI reasoning process.*
