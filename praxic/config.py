"""Praxic -- unified config loader."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

# Load .env file before anything else reads os.environ.
try:
    from dotenv import load_dotenv

    _cwd_env = Path.cwd() / ".env"
    if _cwd_env.exists():
        load_dotenv(_cwd_env)
    else:
        _pkg_env = Path(__file__).parent.parent / ".env"
        if _pkg_env.exists():
            load_dotenv(_pkg_env)
except ImportError:
    pass


def _normalize_no_proxy_for_httpx() -> None:
    """Make IPv6 ``NO_PROXY`` entries compatible with the installed httpx.

    httpx 0.28 builds URL patterns from ``NO_PROXY`` values.  IPv6 CIDR
    entries such as ``::1/128`` are bracketed as ``[::1/128]`` and then
    parsed as an invalid URL, which prevents every httpx-based client from
    being constructed.  A /128 network is equivalent to its host address;
    wider IPv6 CIDRs cannot be represented by httpx's URL-pattern matcher,
    so they are omitted rather than crashing client initialization.
    """
    for variable in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(variable)
        if raw is None:
            continue

        normalized: list[str] = []
        changed = False
        for token in raw.split(","):
            entry = token.strip()
            if not entry:
                continue

            network = None
            if "/" in entry:
                try:
                    network = ipaddress.ip_network(entry, strict=False)
                except ValueError:
                    pass

            if network is not None and network.version == 6:
                if network.prefixlen == network.max_prefixlen:
                    host = str(network.network_address)
                    changed = changed or host != entry
                    entry = host
                else:
                    changed = True
                    continue

            normalized.append(entry)

        if changed:
            os.environ[variable] = ",".join(normalized)


# Apply the compatibility fix before any httpx-backed client is created.
_normalize_no_proxy_for_httpx()

_tomllib: Any = None
try:
    import tomllib as _stdlib_tomllib

    _tomllib = _stdlib_tomllib
except ImportError:
    try:
        import tomli as _backport_tomllib

        _tomllib = _backport_tomllib
    except ImportError:
        pass

_PKG_DIR = Path(__file__).parent.parent
_CWD_CONFIG = Path.cwd() / "config.toml"
_PKG_CONFIG = _PKG_DIR / "config.toml"

ROOT_DIR = _PKG_DIR
CONFIG_TOML = _CWD_CONFIG if _CWD_CONFIG.exists() else _PKG_CONFIG

_CWD_PROMPTS = Path.cwd() / "prompts"
_PKG_PROMPTS = _PKG_DIR / "prompts"


def _resolve_prompts_dir() -> Path:
    if _CWD_PROMPTS.is_dir():
        return _CWD_PROMPTS
    return _PKG_PROMPTS


def _resolve_workspace_dir(raw: str) -> Path:
    p = Path(raw)
    return p.resolve() if p.is_absolute() else (Path.cwd() / raw).resolve()


def _resolve_data_dir(raw: str) -> Path:
    p = Path(raw)
    return p.resolve() if p.is_absolute() else (Path.cwd() / raw).resolve()


from .core.autonomy import AutonomyLevel, PermissionMode

_AUTONOMY_MAP = {
    "read_only": AutonomyLevel.READ_ONLY,
    "sandboxed": AutonomyLevel.SANDBOXED,
    "standard": AutonomyLevel.STANDARD,
    "elevated": AutonomyLevel.ELEVATED,
}

_PERMISSION_MAP = {
    "read_only": PermissionMode.READ_ONLY,
    "ask": PermissionMode.ASK,
    "auto_review": PermissionMode.AUTO_REVIEW,
    "full": PermissionMode.FULL,
}


@dataclass
class PhaseConfig:
    temperature: float = 0.5
    max_tokens: int = 4096
    reasoning_effort: str = "medium"
    system_prompt: str = ""


@dataclass
class Settings:
    llm_provider: str = "auto"
    default_model: str = "deepseek-v4-pro"
    llm_base_url: str = ""
    llm_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    tavily_api_key: str = ""
    autonomy_level: AutonomyLevel = AutonomyLevel.STANDARD   # 行为自主（推理指导）
    permission_mode: PermissionMode = PermissionMode.ASK     # 权限模式（放行档位）
    max_iterations: int = 5
    enable_trajectory_logging: bool = True
    stream_output: bool = True
    log_level: str = "INFO"
    debug: bool = False
    web_search_enabled: bool = True
    web_search_max_results: int = 5
    data_dir: Path = field(default_factory=lambda: Path.cwd() / "data")
    db_url: str = ""
    chroma_dir: Path = field(default_factory=lambda: Path.cwd() / "data" / "chroma")
    workspace_dir: Path = field(default_factory=lambda: Path.cwd() / "workspace")
    projects_dir: Path = field(default_factory=lambda: Path.cwd() / "projects")
    prompts_dir: Path = field(default_factory=_resolve_prompts_dir)
    phases: dict = field(default_factory=dict)
    review_strategy: str = "once"  # off | once | iterative
    practice_rounds: int = 3  # 实践阶段最大实验轮数（可配置）
    # ── 技能系统 ──
    skills_dir: Path = field(default_factory=lambda: Path.cwd() / "praxic" / "skills")
    skill_auto_distill: bool = True
    skill_draft_validation_required: int = 3
    skill_max_per_phase: int = 3
    skill_max_tokens_per_phase: int = 2000
    # ── 实践阶段沙箱级别 ── strict=禁网禁pip; relaxed=允许 pip 安装与联网
    practice_sandbox_level: str = "relaxed"
    cockpit_managed: bool = False
    cockpit_profile: str = "default"
    dev_enabled: bool = False
    dev_log_dir: str = "./logs"
    dev_console_output: bool = True
    # ── UI 设置 ──
    ui_font_family: str = "system"
    ui_font_size: str = "medium"
    ui_page_zoom: int = 100
    ui_show_thinking: bool = True
    ui_agent_persona: str = ""
    ui_custom_knowledge: str = ""
    # ── 调查阶段：本地文件检索 ──
    local_retrieval_mode: str = "keyword"  # keyword | embedding | off
    local_retrieval_max_chunks: int = 15
    local_retrieval_max_per_file: int = 3
    local_retrieval_chunk_size: int = 800
    local_retrieval_chunk_overlap: int = 100
    # ── 调查阶段：网络搜索／网页抓取 ──
    web_fetch_enabled: bool = True
    web_fetch_max_urls: int = 6
    web_fetch_max_chars_per_page: int = 5000
    web_fetch_timeout: float = 15.0
    web_fetch_min_score: float = 0.4
    web_fetch_max_total_chars: int = 30000
    # ── 调查阶段：LLM 输入控制 ──
    investigation_external_info_max_chars: int = 40000
    investigation_legacy_per_file_max_chars: int = 2000
    # ── 文件加载器（用户上传文件 → Markdown 注入调查阶段）──
    file_loader_max_total_chars: int = 80000  # 所有上传文件合并后的最大字符数
    file_loader_max_per_file: int = 10_000_000  # 单文件最大字节数（10MB）
    # ── 最终回答 / 详实报告 token 预算 ──
    # 0 表示不添加应用层输出上限，交给模型提供方决定。
    final_answer_max_tokens: int = 0
    detailed_report_max_tokens: int = 0

    def phase(self, name: str) -> PhaseConfig:
        return self.phases.get(name, PhaseConfig())

    def effective_db_url(self) -> str:
        return self.db_url or ("sqlite+aiosqlite:///" + str(self.data_dir / "praxic.db"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)


def _load_toml() -> dict:
    if not CONFIG_TOML.exists() or _tomllib is None:
        return {}
    with open(CONFIG_TOML, "rb") as f:
        return _tomllib.load(f)


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


def _bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return default


def _build() -> Settings:
    t = _load_toml()
    llm = t.get("llm", {})
    rt = t.get("runtime", {})
    pth = t.get("paths", {})
    ph = t.get("phases", {})
    ck = t.get("cockpit", {})
    dv = t.get("developer", {})
    inv = t.get("investigation", {})
    ui = t.get("ui", {})
    ak = _env("ANTHROPIC_API_KEY") or llm.get("anthropic_api_key", "")
    dk = _env("DEEPSEEK_API_KEY") or llm.get("deepseek_api_key", "")
    tk = _env("TAVILY_API_KEY") or llm.get("tavily_api_key", "")

    _raw_prov = (_env("PRAXIC_LLM_PROVIDER") or llm.get("provider", "auto")).lower()
    if _raw_prov == "auto":
        _raw_prov = (
            "openai_compatible"
            if (dk or llm.get("api_key") or _env("PRAXIC_LLM_API_KEY") or _env("OPENAI_API_KEY"))
            else "anthropic"
        )
    _PROVIDER_ALIASES = {"deepseek": "openai_compatible", "openai": "openai_compatible"}
    prov = _PROVIDER_ALIASES.get(_raw_prov, _raw_prov)

    base_url = _env("PRAXIC_LLM_BASE_URL") or llm.get("base_url", "")
    if not base_url:
        base_url = "https://api.deepseek.com"

    api_key = _env("PRAXIC_LLM_API_KEY") or _env("OPENAI_API_KEY") or llm.get("api_key", "") or dk

    mdl = (
        _env("PRAXIC_LLM_MODEL")
        or _env("PRAXIC_DEFAULT_MODEL")
        or llm.get("model", llm.get("default_model", ""))
    )
    if not mdl:
        mdl = "deepseek-v4-pro" if prov == "openai_compatible" else "claude-opus-4-5"
    al = _AUTONOMY_MAP.get(
        (_env("PRAXIC_AUTONOMY_LEVEL") or str(rt.get("autonomy_level", "standard"))).lower(),
        AutonomyLevel.STANDARD,
    )
    pm = _PERMISSION_MAP.get(
        (_env("PRAXIC_PERMISSION_MODE") or str(rt.get("permission_mode", "ask"))).lower(),
        PermissionMode.ASK,
    )
    dd_raw = _env("PRAXIC_DATA_DIR") or pth.get("data_dir", "./data")
    cd_raw = pth.get("chroma_dir", "./data/chroma")
    ws_raw = _env("PRAXIC_WORKSPACE_DIR") or pth.get("workspace_dir", "./workspace")
    pj_raw = _env("PRAXIC_PROJECTS_DIR") or pth.get("projects_dir", "./projects")
    pd_raw = _env("PRAXIC_PROMPTS_DIR") or pth.get("prompts_dir", "./prompts")
    dd = _resolve_data_dir(dd_raw)
    cd = _resolve_data_dir(cd_raw)
    wd = _resolve_workspace_dir(ws_raw)
    pj = _resolve_workspace_dir(pj_raw)
    if not pd_raw or pd_raw == "./prompts":
        pd = _resolve_prompts_dir()
    else:
        pd = (
            Path(pd_raw).resolve()
            if Path(pd_raw).is_absolute()
            else (Path.cwd() / pd_raw).resolve()
        )
    phases = {}
    for n, d in ph.items():
        if isinstance(d, dict):
            phases[n] = PhaseConfig(
                temperature=float(d.get("temperature", 0.5)),
                max_tokens=int(d.get("max_tokens", 4096)),
                reasoning_effort=d.get("reasoning_effort", "medium"),
                system_prompt=d.get("system_prompt", "").strip(),
            )
    return Settings(
        llm_provider=prov,
        default_model=mdl,
        llm_base_url=base_url,
        llm_api_key=api_key,
        anthropic_api_key=ak,
        deepseek_api_key=dk,
        tavily_api_key=tk,
        autonomy_level=al,
        permission_mode=pm,
        max_iterations=int(_env("PRAXIC_MAX_ITERATIONS") or rt.get("max_iterations", 5)),
        enable_trajectory_logging=_bool(
            _env("PRAXIC_ENABLE_TRAJECTORY_LOGGING") or rt.get("enable_trajectory_logging", True),
            True,
        ),
        stream_output=_bool(_env("PRAXIC_STREAM_OUTPUT") or rt.get("stream_output", True), True),
        log_level=(_env("PRAXIC_LOG_LEVEL") or str(rt.get("log_level", "INFO"))).upper(),
        debug=_bool(_env("PRAXIC_DEBUG") or rt.get("debug", False)),
        web_search_enabled=_bool(
            _env("PRAXIC_WEB_SEARCH_ENABLED") or rt.get("web_search_enabled", True), True
        ),
        web_search_max_results=int(
            _env("PRAXIC_WEB_SEARCH_MAX_RESULTS") or rt.get("web_search_max_results", 5)
        ),
        data_dir=dd,
        db_url=_env("PRAXIC_DB_URL") or pth.get("db_url", ""),
        chroma_dir=cd,
        workspace_dir=wd,
        projects_dir=pj,
        prompts_dir=pd,
        phases=phases,
        review_strategy=rt.get("review_strategy", "once"),
        practice_rounds=int(rt.get("practice_rounds", 3)),
        skills_dir=Path(dv.get("skills_dir", str(Path.cwd() / "praxic" / "skills"))),
        skill_auto_distill=_bool(dv.get("skill_auto_distill", True), True),
        skill_draft_validation_required=int(dv.get("skill_draft_validation_required", 3)),
        skill_max_per_phase=int(dv.get("skill_max_per_phase", 3)),
        skill_max_tokens_per_phase=int(dv.get("skill_max_tokens_per_phase", 2000)),
        practice_sandbox_level=str(dv.get("practice_sandbox_level", "relaxed")),
        cockpit_managed=_bool(ck.get("managed", False)),
        cockpit_profile=ck.get("profile", "default"),
        dev_enabled=_bool(dv.get("enabled", False)),
        dev_log_dir=_env("PRAXIC_DEV_LOG_DIR") or dv.get("log_dir", "./logs"),
        dev_console_output=_bool(dv.get("console_output", True), True),
        # ── UI ──
        ui_font_family=ui.get("font_family", "system"),
        ui_font_size=ui.get("font_size", "medium"),
        ui_page_zoom=int(ui.get("page_zoom", 100)),
        ui_show_thinking=_bool(ui.get("show_thinking", True), True),
        ui_agent_persona=ui.get("agent_persona", ""),
        ui_custom_knowledge=ui.get("custom_knowledge", ""),
        # ── 调查阶段 ──
        local_retrieval_mode=_env("PRAXIC_LOCAL_RETRIEVAL_MODE")
        or inv.get("local_retrieval_mode", "keyword"),
        local_retrieval_max_chunks=int(
            _env("PRAXIC_LOCAL_RETRIEVAL_MAX_CHUNKS") or inv.get("local_retrieval_max_chunks", 15)
        ),
        local_retrieval_max_per_file=int(
            _env("PRAXIC_LOCAL_RETRIEVAL_MAX_PER_FILE")
            or inv.get("local_retrieval_max_per_file", 3)
        ),
        local_retrieval_chunk_size=int(
            _env("PRAXIC_LOCAL_RETRIEVAL_CHUNK_SIZE") or inv.get("local_retrieval_chunk_size", 800)
        ),
        local_retrieval_chunk_overlap=int(
            _env("PRAXIC_LOCAL_RETRIEVAL_CHUNK_OVERLAP")
            or inv.get("local_retrieval_chunk_overlap", 100)
        ),
        web_fetch_enabled=_bool(
            _env("PRAXIC_WEB_FETCH_ENABLED") or inv.get("web_fetch_enabled", True), True
        ),
        web_fetch_max_urls=int(
            _env("PRAXIC_WEB_FETCH_MAX_URLS") or inv.get("web_fetch_max_urls", 6)
        ),
        web_fetch_max_chars_per_page=int(
            _env("PRAXIC_WEB_FETCH_MAX_CHARS_PER_PAGE")
            or inv.get("web_fetch_max_chars_per_page", 5000)
        ),
        web_fetch_timeout=float(
            _env("PRAXIC_WEB_FETCH_TIMEOUT") or inv.get("web_fetch_timeout", 15.0)
        ),
        web_fetch_min_score=float(
            _env("PRAXIC_WEB_FETCH_MIN_SCORE") or inv.get("web_fetch_min_score", 0.4)
        ),
        web_fetch_max_total_chars=int(
            _env("PRAXIC_WEB_FETCH_MAX_TOTAL_CHARS") or inv.get("web_fetch_max_total_chars", 30000)
        ),
        investigation_external_info_max_chars=int(
            _env("PRAXIC_INVESTIGATION_EXTERNAL_INFO_MAX_CHARS")
            or inv.get("investigation_external_info_max_chars", 40000)
        ),
        investigation_legacy_per_file_max_chars=int(
            _env("PRAXIC_INVESTIGATION_LEGACY_PER_FILE_MAX_CHARS")
            or inv.get("investigation_legacy_per_file_max_chars", 2000)
        ),
        final_answer_max_tokens=int(
            _env("PRAXIC_FINAL_ANSWER_MAX_TOKENS") or rt.get("final_answer_max_tokens", 0)
        ),
        detailed_report_max_tokens=int(
            _env("PRAXIC_DETAILED_REPORT_MAX_TOKENS") or rt.get("detailed_report_max_tokens", 0)
        ),
    )


settings = _build()
settings.ensure_dirs()


# ── Config.toml section patcher ──────────────────────────────────────
# Reads config.toml line-by-line, replaces or appends named [section] blocks.
# Avoids pulling in a TOML writer dependency.


def save_config_section(section: str, lines: list[str]) -> None:
    """Patch *section* in CONFIG_TOML with *lines* (key=value, without the header).
    If the section exists, its content is replaced.  Otherwise it is appended.
    Values in *lines* are treated as raw strings — it's the caller's
    responsibility to ensure they are valid TOML."""
    header = f"[{section}]"
    existing: list[str] = []
    try:
        existing = CONFIG_TOML.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        existing = []

    out: list[str] = []
    i = 0
    replaced = False
    while i < len(existing):
        raw = existing[i]
        stripped = raw.strip()
        if stripped == header or stripped.startswith(header + " "):
            # Found the target section — skip old content until next section or EOF
            out.append(raw if stripped == header else f"{header}\n")
            i += 1
            while i < len(existing):
                s = existing[i].strip()
                if s.startswith("[") and s.endswith("]") and not s.startswith("[["):
                    break
                i += 1
            # Insert replacement content
            for l in lines:
                out.append(l if l.endswith("\n") else l + "\n")
            replaced = True
        else:
            out.append(raw)
            i += 1

    if not replaced:
        out.append(f"\n{header}\n")
        for l in lines:
            out.append(l if l.endswith("\n") else l + "\n")

    CONFIG_TOML.write_text("".join(out), encoding="utf-8")


def save_config_key(section: str, key: str, value) -> None:
    """Update a single key inside a [section] in CONFIG_TOML."""
    header = f"[{section}]"
    existing: list[str] = []
    try:
        existing = CONFIG_TOML.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        existing = []

    val_str = _toml_value(value)

    # Find the section boundaries
    sec_start = -1
    sec_end = len(existing)
    for i, raw in enumerate(existing):
        stripped = raw.strip()
        if stripped == header or stripped.startswith(header + " "):
            sec_start = i
        elif (
            sec_start >= 0
            and stripped.startswith("[")
            and stripped.endswith("]")
            and not stripped.startswith("[[")
        ):
            sec_end = i
            break

    # Look for the key within the section
    if sec_start >= 0:
        for i in range(sec_start + 1, sec_end):
            stripped = existing[i].strip()
            if (
                stripped.startswith(f"{key} ")
                or stripped.startswith(f"{key}=")
                or stripped.startswith(f"{key}\t")
            ):
                existing[i] = f"{key} = {val_str}\n"
                CONFIG_TOML.write_text("".join(existing), encoding="utf-8")
                return

    # Key not found — insert after the section header (or append a new section)
    if sec_start >= 0:
        existing.insert(sec_start + 1, f"{key} = {val_str}\n")
    else:
        existing.append(f"\n{header}\n")
        existing.append(f"{key} = {val_str}\n")
    CONFIG_TOML.write_text("".join(existing), encoding="utf-8")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Escape for TOML basic string: backslash → \\, double-quote → \"
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        # Replace control characters that would break a single-line basic string
        escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{escaped}"'
    return str(value)


def load_phase_prompt(name: str, fallback: str = "") -> str:
    """Load phase-specific prompt from file or fall back to default."""
    prompt_file = settings.prompts_dir / f"{name}.md"
    if prompt_file.exists():
        try:
            return prompt_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return fallback
