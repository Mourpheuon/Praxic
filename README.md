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
⓪ Question Preprocessing — parse intent, task nature, complexity, and phase plan
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
④ Practice — Despise the enemy strategically, take full account of him tactically.
                Distill falsifiable claims from prior phases, plan actions autonomously,
                call tools, analyze results, and hand verification evidence to reflection
   │
   ▼
⑤ Reflection — Practice is the sole criterion of truth (convergence judgment + evidence pipeline)
   │
   ▼
Converged? → If not, re-investigate (with reflection hints carried forward, bounded by max_iterations)
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
export PRAXIC_LLM_API_KEY="sk-xxx"
export PRAXIC_LLM_BASE_URL="https://api.deepseek.com"

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-xxx"

# Or write to a .env file (not tracked by Git)
cp .env.example .env
# Edit .env with your real key
```

### 3. Run

**Command Line (CLI):**

```bash
python -m praxic run "Why is my open-source project struggling to attract contributors?"
python -m praxic run "Consider a group of agents playing..." --mode deep
python -m praxic run --help   # Show all options
```

**Web UI (browser):**

```bash
python -m praxic
# Automatically opens http://localhost:8000
```

**Electron Desktop App (Windows):**

```powershell
npm run electron:build
# Run dist-electron/win-unpacked/即物穷理.exe after build
```

**Python SDK:**

```python
import asyncio
from praxic.core.cognitive_loop import CognitiveLoop

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
| `fast` | Investigation followed by fast contradiction/rational passes; skips practice and reflection, single round | Simple Q&A, information lookup |
| `standard` | Full cognitive loop (preprocessing + five phases), multi-round practice | Most scenarios |
| `deep` | Multi-round iteration with a higher iteration cap (at least 7), reflection-driven re-investigation | Complex analysis, decision simulation |
| `custom` | Skip specified phases (e.g. `skip=contradiction,practice`) | Flexible control |

---

## Features

| Feature | Description |
|---------|-------------|
| **Cognitive Loop** | Preprocessing → Investigation → Contradiction → Rational Synthesis → Practice → Reflection |
| **Web Search** | Tavily + web fetching, multi-result parallel |
| **File Reading** | TXT, code, PDF (multi-fallback + OCR), DOCX, XLSX, PPTX, IPYNB |
| **Multi-LLM Backend** | DeepSeek, OpenAI, Anthropic, Ollama, custom compatible endpoint |
| **Practice Engine** | Distills falsifiable claims from prior phases, plans actions, calls tools, analyzes results — multi-round progressive with auto-repair |
| **Permissions & Authorization** | Reads auto-approved; writes, deletes, and external side effects gated by permission checks and async authorization, with change logs and read-back verification |
| **Tool Registry** | Unified tool contract, structured serialization of results, distinguishes tool failure from unchanged world state |
| **Credibility Tracing** | Evidence-based caps on claim credibility (V3/V2), preventing assertions beyond the evidence |
| **Context Caching** | App-level KV cache + provider prompt cache, isolated by session/project/model/version, with hit and token metrics |
| **Skill System** | Extensible skill registry, injected per cognitive phase, batch import supported |
| **Project System** | Conversations organized by project, session pinning, memory shared across sessions, historical phase-log replay |
| **Conversation Management** | History, SSE streaming, user steering / interrupt / terminate / resume |
| **Live Activity Stream** | Frontend shows phases, tool activity, pending authorization, verification and failure states in real time |
| **Settings Persistence** | UI settings stored in `config.toml`, account config written to `.env` |
| **Electron Shell** | Windows installer, auto-launches Python backend |

---

## Project Structure

```
Praxic/
├── praxic/                          # Core package
│   ├── core/                      # Cognitive engine
│   │   ├── cognitive_loop.py      # Cognitive loop controller (main entry)
│   │   ├── question_preprocessing.py  # Question preprocessing (intent/task/phase plan)
│   │   ├── investigation.py       # Investigation
│   │   ├── contradiction.py       # Contradiction analysis
│   │   ├── rational.py            # Rational synthesis
│   │   ├── practice.py            # Practice (multi-round experiments + auto-repair)
│   │   ├── practice_harness.py    # Practice execution prompts (high-churn, isolated)
│   │   ├── reflection.py          # Reflection engine (convergence + evidence pipeline)
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
│   │   ├── base.py                # Tool abstraction
│   │   ├── registry.py            # Tool registry
│   │   ├── permissions.py         # Permission / authorization gate
│   │   ├── filesystem.py          # File I/O
│   │   ├── file_loader.py         # Multi-format file reader
│   │   ├── pdf_converter.py       # PDF multi-fallback conversion + OCR
│   │   ├── web_search.py          # Tavily web search
│   │   ├── web_fetch.py           # Web content fetching
│   │   ├── shell.py / python_exec.py  # Command execution
│   │   ├── user_context.py        # User context
│   │   └── local_retriever.py     # Local knowledge retrieval
│   ├── memory/                    # Memory system
│   │   ├── working_memory.py      # Cross-round context passing
│   │   ├── episodic_memory.py     # Episodic memory (SQLite)
│   │   ├── semantic_memory.py     # Semantic memory
│   │   └── context_cache.py       # Context compilation & caching
│   ├── api/                       # REST API (FastAPI)
│   │   ├── server.py
│   │   ├── routes/
│   │   │   ├── agent.py           # Cognitive loop SSE streaming endpoint
│   │   │   ├── setup.py           # Settings / config / build routes
│   │   │   └── conversations.py   # Conversation + project management
│   │   └── schemas/models.py      # Pydantic data models
│   ├── skills/                    # Skill packages & registry
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Config management (TOML + env vars)
│   ├── web/                       # Frontend (actual entry: index.html; src/ is an unmerged TypeScript tree)
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
├── Dockerfile / docker-compose.yml
└── PROJECT_HANDOFF.md             # Internal handoff doc (git-ignored)
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
autonomy_level = "standard"      # behavior autonomy: read_only | sandboxed | standard | elevated
permission_mode = "ask"           # permission mode: read_only | ask | auto_review | full
max_iterations = 5
web_search_enabled = true
```

### Environment variables (take precedence over config.toml)

| Variable | Description |
|----------|-------------|
| `PRAXIC_LLM_API_KEY` | OpenAI-compatible API Key |
| `PRAXIC_LLM_BASE_URL` | Compatible endpoint URL |
| `PRAXIC_LLM_MODEL` | Default model |
| `PRAXIC_LLM_PROVIDER` | `openai_compatible` or `anthropic` |
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
npm run electron:build
# Output: dist-electron/即物穷理 Setup *.exe
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
