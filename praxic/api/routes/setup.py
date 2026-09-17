"""
即物穷理 Praxic —— 设置 / 引导路由
POST /api/v1/setup        保存 LLM 配置到 config.toml + .env
GET  /api/v1/setup/status 检查是否已完成配置
GET  /api/v1/settings     读取 UI 设置（字体、角色、知识）
PUT  /api/v1/settings     保存 UI 设置
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import settings, CONFIG_TOML, save_config_section, save_config_key, _toml_value
from ... import __version__
from ...core.autonomy import PermissionMode
from .agent import init_agent_resources

router = APIRouter(prefix="/api/v1", tags=["setup", "settings"])
log = logging.getLogger(__name__)

PROVIDER_PRESETS = {
    "deepseek": {"label": "DeepSeek", "url": "https://api.deepseek.com", "model": "deepseek-v4-pro"},
    "openai": {"label": "OpenAI", "url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "anthropic": {"label": "Anthropic Claude", "url": "", "model": "claude-sonnet-4-5"},
    "ollama": {"label": "Ollama 本地", "url": "http://localhost:11434/v1", "model": "llama3"},
    "custom": {"label": "自定义 / 中转站", "url": "", "model": ""},
}

PROVIDER_MODELS = {
    "deepseek": ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3-mini", "o4-mini"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5", "claude-sonnet-4"],
    "ollama": ["llama3", "llama3.1", "mistral", "qwen2.5"],
    "custom": [],
}

# ── UI Settings persistence ───────────────────────────────────

def _ui_settings_path() -> Path:
    p = settings.data_dir / "ui-settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _load_ui_settings() -> dict:
    path = _ui_settings_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def _save_ui_settings(data: dict) -> None:
    path = _ui_settings_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_runtime_overrides() -> dict:
    """Read runtime parameter overrides from ui-settings.
    Callers should merge with their own defaults.
    Returns a flat dict of known runtime keys (no nesting)."""
    data = _load_ui_settings()
    known_keys = {
        "max_iterations", "practice_rounds",
        "web_search_max_results", "web_fetch_max_urls",
        "web_fetch_max_chars_per_page", "web_fetch_max_total_chars",
    }
    return {k: data[k] for k in known_keys if k in data}


class UiSettings(BaseModel):
    font_family: str = "system"       # system | serif | mono
    font_size: str = "medium"         # small | medium | large
    page_zoom: int = 100              # 页面缩放百分比
    show_thinking_after_answer: bool = True  # 回答后是否显示思维过程
    agent_persona: str = ""           # Agent 角色设定
    custom_knowledge: str = ""        # 用户自定义知识 / 重要经验
    # ── 运行时高级参数 ──
    max_iterations: int = 0           # 0 = 使用 config.toml 默认值
    practice_rounds: int = 0          # 实践阶段实验轮数
    web_search_max_results: int = 0   # 搜索最大结果数
    web_fetch_max_urls: int = 0       # 网页抓取最大URL数
    web_fetch_max_chars_per_page: int = 0  # 单页最大字符数
    web_fetch_max_total_chars: int = 0     # 总抓取最大字符数
    permission_mode: str = ""             # 权限模式：read_only | ask | auto_review | full（空=用默认）


def _get_default_ui_settings() -> dict:
    return {
        "font_family": "system",
        "font_size": "medium",
        "page_zoom": 100,
        "show_thinking_after_answer": True,
        "agent_persona": "",
        "custom_knowledge": "",
        # Runtime params — 0 means "use config.toml default"
        "max_iterations": 0,
        "practice_rounds": 0,
        "web_search_max_results": 0,
        "web_fetch_max_urls": 0,
        "web_fetch_max_chars_per_page": 0,
        "web_fetch_max_total_chars": 0,
        "permission_mode": "",
    }


@router.get("/settings")
async def get_settings():
    """读取 UI 设置（config.toml [ui] 优先，回退到 ui-settings.json）。"""
    # Read from config.toml's [ui] section first
    data = {
        "font_family": settings.ui_font_family,
        "font_size": settings.ui_font_size,
        "page_zoom": settings.ui_page_zoom,
        "show_thinking_after_answer": settings.ui_show_thinking,
        "agent_persona": settings.ui_agent_persona,
        "custom_knowledge": settings.ui_custom_knowledge,
    }
    # Fallback to ui-settings.json for any missing non-empty values, and for runtime params
    legacy = _load_ui_settings()
    for k in ["font_family", "font_size", "page_zoom", "show_thinking_after_answer",
               "agent_persona", "custom_knowledge"]:
        if not data.get(k) and legacy.get(k):
            data[k] = legacy[k]
    # Runtime params still come from ui-settings.json (not in config.toml)
    for k in ["max_iterations", "practice_rounds", "web_search_max_results",
               "web_fetch_max_urls", "web_fetch_max_chars_per_page", "web_fetch_max_total_chars"]:
        data[k] = legacy.get(k, _get_default_ui_settings().get(k, 0))
    data["permission_mode"] = settings.permission_mode.name.lower()
    data["dev_enabled"] = settings.dev_enabled
    return data


@router.put("/settings")
async def save_settings(req: UiSettings):
    """保存 UI 设置到 config.toml 和 ui-settings.json。"""
    # Write [ui] section to config.toml
    ui_lines = [
        f"font_family = {_toml_value(req.font_family)}",
        f"font_size = {_toml_value(req.font_size)}",
        f"page_zoom = {req.page_zoom}",
        f"show_thinking = {'true' if req.show_thinking_after_answer else 'false'}",
    ]
    if req.agent_persona:
        ui_lines.append(f"agent_persona = {_toml_value(req.agent_persona)}")
    if req.custom_knowledge:
        ui_lines.append(f"custom_knowledge = {_toml_value(req.custom_knowledge)}")

    save_config_section("ui", ui_lines)
    # Also write runtime params to [runtime] section in config.toml
    if req.max_iterations > 0:
        save_config_key("runtime", "max_iterations", req.max_iterations)
    if req.practice_rounds > 0:
        save_config_key("runtime", "practice_rounds", req.practice_rounds)
    if req.permission_mode:
        save_config_key("runtime", "permission_mode", req.permission_mode)

    # Still write ui-settings.json for legacy compatibility (runtime params)
    data = req.model_dump()
    _save_ui_settings(data)

    # Update in-memory settings
    settings.ui_font_family = req.font_family
    settings.ui_font_size = req.font_size
    settings.ui_page_zoom = req.page_zoom
    settings.ui_show_thinking = req.show_thinking_after_answer
    settings.ui_agent_persona = req.agent_persona or ""
    settings.ui_custom_knowledge = req.custom_knowledge or ""
    if req.max_iterations > 0:
        settings.max_iterations = req.max_iterations
    if req.permission_mode:
        settings.permission_mode = PermissionMode[req.permission_mode.upper()]

    log.info("ui_settings_saved")
    return {"ok": True}


# ── Dev mode toggle ──

class DevModeRequest(BaseModel):
    enabled: bool = False


@router.put("/settings/dev")
async def set_dev_mode(req: DevModeRequest):
    """Enable or disable developer mode."""
    save_config_key("developer", "enabled", req.enabled)
    settings.dev_enabled = req.enabled
    log.info("dev_mode_toggled | enabled=%s", req.enabled)
    return {"ok": True, "dev_enabled": req.enabled}


# ── Plugins ──────────────────────────────────────────────────


def _plugins_dir() -> Path:
    return settings.data_dir / "plugins"


@router.get("/plugins")
async def list_plugins():
    """列出插件目录中已发现的插件及加载状态。"""
    from ...tools.plugin import PluginScanner
    scanner = PluginScanner(_plugins_dir())
    items = []
    for manifest_path in sorted(scanner.plugins_dir.rglob("manifest.yaml")):
        entry = {"name": manifest_path.parent.name, "path": str(manifest_path.parent), "status": "error", "error": ""}
        try:
            tool = scanner._load_manifest(manifest_path)
            if tool is not None:
                entry.update({
                    "name": tool.name,
                    "description": tool.description,
                    "category": tool.category,
                    "action_kind": tool.action_kind.value,
                    "group": tool.group,
                    "status": "loaded",
                })
        except Exception as exc:
            entry["error"] = str(exc)
        items.append(entry)
    return {"plugins": items, "dir": str(_plugins_dir())}


@router.post("/plugins/scan")
async def scan_plugins():
    """重新扫描插件目录（下次新建 CognitiveLoop 时生效）。"""
    from ...tools.plugin import PluginScanner, load_plugins
    scanner = PluginScanner(_plugins_dir())
    tools = scanner.scan()
    return {"ok": True, "found": len(tools), "names": [t.name for t in tools]}


# ── 对话级权限 ─────────────────────────────────────────────

_VALID_PERMISSION_MODES = {"read_only", "ask", "auto_review", "full"}


@router.get("/conversations/{conv_id}/permission")
async def get_conversation_permission(conv_id: str):
    """读取某对话的权限模式；未显式设置返回当前全局默认。"""
    from ...core.conversation_permissions import get_conversation_permission as _get
    explicit = _get(conv_id)
    effective = explicit if explicit else settings.permission_mode.name.lower()
    return {"conversation_id": conv_id, "permission_mode": effective, "explicit": bool(explicit)}


class ConversationPermissionRequest(BaseModel):
    permission_mode: str = ""


@router.put("/conversations/{conv_id}/permission")
async def set_conversation_permission(conv_id: str, req: ConversationPermissionRequest):
    """设置某对话的权限模式（覆盖全局默认）。"""
    mode = (req.permission_mode or "").strip().lower()
    if mode not in _VALID_PERMISSION_MODES:
        raise HTTPException(status_code=400, detail=f"非法权限模式：{mode}（可选 {', '.join(sorted(_VALID_PERMISSION_MODES))}）")
    from ...core.conversation_permissions import set_conversation_permission as _set
    _set(conv_id, mode)
    return {"ok": True, "conversation_id": conv_id, "permission_mode": mode}


# ── Models endpoint ──────────────────────────────────────────

@router.get("/models")
async def list_models(provider_key: str = ""):
    """返回当前 provider 可用的模型列表。可传入 provider_key 查询特定服务商的模型。"""
    pk = provider_key.strip().lower() if provider_key else ""
    if not pk:
        # Auto-detect from current settings
        pk = "deepseek"
        if settings.llm_provider == "anthropic":
            pk = "anthropic"
        elif settings.llm_base_url:
            url = settings.llm_base_url.lower()
            if "deepseek" in url:
                pk = "deepseek"
            elif "openai" in url:
                pk = "openai"
            elif "ollama" in url or "localhost" in url:
                pk = "ollama"
            else:
                pk = "custom"
    models = PROVIDER_MODELS.get(pk, [])
    current = settings.default_model
    return {"models": models, "current": current, "provider_key": pk}


# ── Setup routes ─────────────────────────────────────────────

class SetupRequest(BaseModel):
    provider: str = "deepseek"
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class TestConnectionRequest(BaseModel):
    provider: str = "deepseek"
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class TestConnectionResponse(BaseModel):
    ok: bool
    latency_ms: float = 0.0
    model: str = ""
    error: str = ""


class SetupStatusResponse(BaseModel):
    configured: bool
    provider: str = ""
    model: str = ""
    base_url: str = ""
    provider_key: str = ""  # deepseek / openai / anthropic / ollama / custom
    dev_enabled: bool = False


class LlmConfigResponse(BaseModel):
    provider_key: str = ""     # deepseek / openai / anthropic / ollama / custom
    base_url: str = ""
    model: str = ""
    api_key: str = ""          # current saved key (local-only, safe for localhost)
    configured: bool = False


@router.get("/setup/status", response_model=SetupStatusResponse)
async def setup_status():
    """检查是否已配置 API Key。"""
    has_key = bool(settings.llm_api_key or settings.anthropic_api_key or settings.deepseek_api_key)
    # Determine provider_key from current settings
    provider_key = "deepseek"
    if settings.llm_provider == "anthropic":
        provider_key = "anthropic"
    elif settings.llm_base_url:
        url = settings.llm_base_url.lower()
        if "deepseek" in url:
            provider_key = "deepseek"
        elif "openai" in url:
            provider_key = "openai"
        elif "ollama" in url or "localhost" in url:
            provider_key = "ollama"
        else:
            provider_key = "custom"
    return SetupStatusResponse(
        configured=has_key,
        provider=settings.llm_provider,
        model=settings.default_model,
        base_url=settings.llm_base_url,
        provider_key=provider_key,
        dev_enabled=settings.dev_enabled,
    )


@router.get("/setup/config", response_model=LlmConfigResponse)
async def get_llm_config():
    """获取当前 LLM 配置（用于设置界面的账户 tab）。"""
    provider_key = "deepseek"
    if settings.llm_provider == "anthropic":
        provider_key = "anthropic"
    elif settings.llm_base_url:
        url = settings.llm_base_url.lower()
        if "deepseek" in url:
            provider_key = "deepseek"
        elif "openai" in url:
            provider_key = "openai"
        elif "ollama" in url or "localhost" in url:
            provider_key = "ollama"
        else:
            provider_key = "custom"
    has_key = bool(settings.llm_api_key or settings.anthropic_api_key or settings.deepseek_api_key)
    return LlmConfigResponse(
        provider_key=provider_key,
        base_url=settings.llm_base_url,
        model=settings.default_model,
        api_key=settings.llm_api_key or settings.anthropic_api_key or settings.deepseek_api_key,
        configured=has_key,
    )


def _patch_env_file(updates: dict[str, str], removes: list[str] | None = None) -> Path:
    """Patch .env in place: known keys are replaced, listed keys removed,
    and all other lines (comments, unrelated vars like TAVILY_API_KEY) kept."""
    env_path = Path.cwd() / ".env"
    lines: list[str] = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            lines = []
    removes = removes or []
    keys_seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(raw)
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in removes:
                continue
            if key in updates:
                out.append(f'{key}="{updates[key]}"\n')
                keys_seen.add(key)
                continue
        out.append(raw)
    for key, value in updates.items():
        if key not in keys_seen:
            out.append(f'{key}="{value}"\n')
    env_path.write_text("".join(out), encoding="utf-8")
    return env_path


@router.post("/setup")
async def save_setup(req: SetupRequest):
    """保存 LLM 配置到 config.toml 和 .env，并重新加载。"""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    is_anthropic = req.provider.lower() == "anthropic"

    # ── config.toml：只保存 provider/base_url/model，永不落盘 API Key ──
    # （密钥只存在于 .env；config.toml 会随设置生成/更新，不能成为密钥容器）
    if is_anthropic:
        save_config_section("llm", [
            'provider = "anthropic"',
            f"model = {_toml_value(req.model)}",
        ])
    else:
        save_config_section("llm", [
            'provider = "openai_compatible"',
            f"base_url = {_toml_value(req.base_url)}",
            f"model = {_toml_value(req.model)}",
        ])
    log.info("config_patched | section=llm (no api_key — secrets live in .env)")

    # ── API Key 只写入 .env（原地补丁，保留 TAVILY_API_KEY 等其他变量）──
    try:
        updates = {
            "PRAXIC_LLM_PROVIDER": "anthropic" if is_anthropic else "openai_compatible",
            "PRAXIC_LLM_MODEL": req.model.strip(),
        }
        removes: list[str] = []
        if is_anthropic:
            updates["ANTHROPIC_API_KEY"] = req.api_key.strip()
        else:
            updates["PRAXIC_LLM_API_KEY"] = req.api_key.strip()
            updates["PRAXIC_LLM_BASE_URL"] = req.base_url.strip()
            # OPENAI_API_KEY 是旧版 UI 写法的别名，与 PRAXIC_LLM_API_KEY 同义，删除避免残留
            removes = ["OPENAI_API_KEY"]
        env_path = _patch_env_file(updates, removes)
        log.info("env_patched | path=%s", str(env_path))
    except Exception as e:
        log.warning("env_write_failed | %s", str(e))
        raise HTTPException(status_code=500, detail=f"API Key 写入 .env 失败：{e}") from e

    # Update in-memory settings so the next request uses the new config
    if is_anthropic:
        settings.anthropic_api_key = req.api_key.strip()
        settings.llm_api_key = ""
        settings.llm_base_url = ""
        settings.llm_provider = "anthropic"
    else:
        settings.llm_api_key = req.api_key.strip()
        settings.llm_base_url = req.base_url.strip()
        settings.anthropic_api_key = ""
        settings.llm_provider = "openai_compatible"
    settings.default_model = req.model.strip()

    # Reinitialize agent resources with the new config
    try:
        init_agent_resources()
        log.info("agent_reinitialized_after_setup")
    except Exception as e:
        log.warning("agent_reinit_failed | %s", str(e))

    return {"ok": True, "message": "配置已保存", "path": str(CONFIG_TOML)}


@router.post("/setup/test")
async def test_connection(req: TestConnectionRequest):
    """测试 LLM 连接 —— 发送一条简短的测试消息并返回延迟。"""
    import time

    if not req.api_key.strip():
        return {"ok": False, "latency_ms": 0, "model": "", "error": "API Key 不能为空"}

    provider_key = req.provider.lower()
    is_openai_compat = provider_key in ("deepseek", "openai", "ollama", "custom")
    is_anthropic = provider_key == "anthropic"

    if not is_openai_compat and not is_anthropic:
        return {"ok": False, "latency_ms": 0, "model": "", "error": f"不支持的服务商: {req.provider}"}

    t0 = time.perf_counter()
    try:
        if is_openai_compat:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=req.api_key.strip(), base_url=req.base_url.strip(), timeout=30.0, max_retries=1)
            resp = await client.chat.completions.create(
                model=req.model.strip(),
                messages=[{"role": "user", "content": "reply 'ok'"}],
                max_tokens=20,
                temperature=0.0,
            )
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {"ok": True, "latency_ms": latency, "model": str(resp.model or req.model)}
        else:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=req.api_key.strip(), timeout=30.0, max_retries=1)
            resp = await client.messages.create(
                model=req.model.strip(),
                messages=[{"role": "user", "content": "reply 'ok'"}],
                max_tokens=20,
            )
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {"ok": True, "latency_ms": latency, "model": str(resp.model)}
    except Exception as e:
        latency = round((time.perf_counter() - t0) * 1000, 1)
        err_msg = str(e)
        if len(err_msg) > 500:
            err_msg = err_msg[:500] + "…"
        log.warning("llm_test_connection_failed | provider=%s | %s", req.provider, err_msg[:120])
        return {"ok": False, "latency_ms": latency, "model": "", "error": err_msg}


# ── Version / Update routes ──────────────────────────────────────

class VersionInfoResponse(BaseModel):
    python_version: str = __version__
    electron_version: str = __version__
    latest_version: str = ""
    update_available: bool = False
    release_url: str = ""
    release_date: str = ""
    release_notes: str = ""
    download_urls: list[str] = []
    error: str = ""


def _get_pyproject_version() -> str:
    # Frozen builds have no pyproject.toml in the writable runtime directory.
    return __version__


def _get_package_json_version() -> str:
    # Desktop and backend versions are kept equal by check_repository.py.
    return __version__


@router.get("/setup/version", response_model=VersionInfoResponse)
async def check_version():
    """Check version + latest GitHub release."""
    py_ver = _get_pyproject_version()
    el_ver = _get_package_json_version()

    result = VersionInfoResponse(python_version=py_ver, electron_version=el_ver)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.github.com/repos/Mourpheuon/Praxic/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Praxic-Agent"},
            )
            if r.status_code == 200:
                release = r.json()
                tag = release.get("tag_name", "").lstrip("v")
                result.latest_version = tag
                result.release_url = release.get("html_url", "")
                result.release_date = release.get("published_at", "")[:10]
                result.release_notes = (release.get("body") or "")[:3000]
                for asset in release.get("assets", []):
                    url = asset.get("browser_download_url", "")
                    if url:
                        result.download_urls.append(url)
                if tag and el_ver:
                    try:
                        from packaging.version import Version
                        if Version(tag) > Version(el_ver):
                            result.update_available = True
                    except Exception:
                        result.update_available = tag != el_ver
            elif r.status_code == 404:
                result.error = "未找到 GitHub Release"
            elif r.status_code == 403:
                result.error = "GitHub API 限流，请稍后重试"
            else:
                result.error = f"GitHub API 返回 {r.status_code}"
    except Exception as e:
        result.error = f"获取更新信息失败: {e}"

    return result


# Retired endpoints return an explicit response for older UI clients.
@router.get('/setup/release-check', deprecated=True)
@router.post('/setup/build-electron', deprecated=True)
async def retired_desktop_release():
    raise HTTPException(
        status_code=410,
        detail='页面内构建与发布已停用。源码构建请运行 python scripts/build_desktop.py；正式发布请使用 GitHub 标签构建流程。',
    )
