"""
Praxic Agent —— 对话级权限存储

每个 conversation 可以覆盖全局默认权限模式（SettingsDialog 里设的"默认权限"）。
存储：data_dir/conversation-permissions.json，dict: conversation_id -> mode 字符串。

查找优先级：conversation 显式设置 > 全局默认（settings.permission_mode）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings

log = structlog.get_logger(__name__)

_lock = threading.Lock()


def _store_path() -> Path:
    p = settings.data_dir / "conversation-permissions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> dict[str, str]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def _save(data: dict[str, str]) -> None:
    with open(_store_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_conversation_permission(conversation_id: str) -> Optional[str]:
    """返回对话的显式权限模式字符串；未设置返回 None（调用方用全局默认）。"""
    if not conversation_id:
        return None
    with _lock:
        return _load().get(conversation_id)


def set_conversation_permission(conversation_id: str, mode: str) -> None:
    """设置对话的权限模式（覆盖全局默认）。"""
    if not conversation_id:
        return
    with _lock:
        data = _load()
        data[conversation_id] = mode
        _save(data)
    log.info("conversation_permission.set", conversation_id=conversation_id, mode=mode)


def clear_conversation_permission(conversation_id: str) -> None:
    """清除对话的显式权限设置，回落到全局默认。"""
    with _lock:
        data = _load()
        if conversation_id in data:
            del data[conversation_id]
            _save(data)
