"""调查阶段的内部事实源 —— 填充 facts 的 source_type="internal" 槽位。

此前调查阶段只收集外部信息（网络搜索 / 工作区文件），internal 槽位形同虚设，
"我能做什么 / 环境里有什么 / 之前调查过什么"这类问题被迫走网络搜索。
本模块为**每一次**调查聚合内部事实（internal 是一等事实源，不局限于自身能力问题）：

1. 本地记忆（按当前问题动态检索）：
   - episodic：相关历史 episode + 最近记录兜底
   - 历史推导链（跨会话累积的推理路径）
   - semantic：蒸馏知识（pattern / heuristic / anti-pattern）
2. 自我快照（静态，可跨问题缓存）：
   - 运行环境（平台 / 解释器 / 工作区 / 数据目录）
   - 工具目录（可用能力完整清单）
   - 执行约束（shell 白名单 / python_exec import 白名单 / 权限模式）

所有检索失败均容错降级：内部事实获取不到时调查照常进行，只记警告日志。
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import structlog

from ..config import settings

log = structlog.get_logger(__name__)

# 内部事实注入的字符上限（控制 prompt 体积；外部信息另有 40k 配额）
MAX_INTERNAL_CHARS = 8000


# ── 自我快照 ────────────────────────────────────────────────────

def build_self_model(registry, workspace=None) -> str:
    """生成"助手自身能力与运行环境"快照（文本块）。"""
    lines = ["## 自我快照（助手自身能力与环境）"]
    lines.append(f"- 平台：{platform.system()} {platform.release()}（{platform.machine()}）")
    lines.append(f"- Python 解释器：{sys.version.split()[0]}（{sys.executable}）")
    try:
        lines.append(f"- 当前目录：{Path.cwd()}")
    except Exception:  # noqa: BLE001
        pass
    ws = getattr(workspace, "workspace", None) or settings.workspace_dir
    lines.append(f"- 工作区：{ws}")
    lines.append(f"- 数据目录：{settings.data_dir}")
    lines.append("- 可用工具（能力完整清单）：")
    try:
        names = sorted(registry.get_names()) if registry is not None else []
    except Exception:  # noqa: BLE001
        names = []
    if names:
        for n in names:
            try:
                t = registry.get(n)
                desc = (getattr(t, "description", "") or "").replace("\n", " ").strip()
                if len(desc) > 160:
                    desc = desc[:160] + "…"
                kind = getattr(t, "action_kind", "")
                kind = getattr(kind, "value", kind) or ""
                lines.append(f"  - {n}（{kind}）：{desc}")
            except Exception:  # noqa: BLE001
                continue
    else:
        lines.append("  -（无注册工具）")
    lines.append("- 执行约束：")
    try:
        from ..tools.shell import ShellTool
        cmds = sorted(str(c) for c in ShellTool._READ_COMMANDS)
        lines.append(f"  - shell_exec 仅允许白名单命令：{cmds}；禁止链接/管道/重定向（&&、|、>、; 等）")
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..tools.python_exec import PythonExecTool
        mods = sorted(PythonExecTool._SAFE_IMPORTS)
        lines.append(f"  - python_exec 仅允许 import：{mods}；禁止 os.system / subprocess 等；open 只读")
    except Exception:  # noqa: BLE001
        pass
    pm = getattr(settings.permission_mode, "name", str(settings.permission_mode))
    web = "启用" if settings.web_search_enabled else "禁用"
    lines.append(f"  - 权限模式：{pm}；网络搜索：{web}")
    return "\n".join(lines)


# ── 本地记忆检索 ─────────────────────────────────────────────────

def _format_derivation_chains(chains) -> str:
    if not chains:
        return ""
    lines = ["[历史推导链]"]
    for dc in chains:
        summary = (dc.get("summary") or "").replace("\n", " ")[:150]
        src = (dc.get("source_question") or "")[:80]
        lines.append(f"- {summary}（来源问题：{src}）")
    return "\n".join(lines)


_FOLLOW_UP_MARKERS = ("再试", "再尝试", "继续", "刚才", "上一个", "上述", "这个", "那个", "它")


def _looks_like_follow_up(question: str) -> bool:
    q = (question or "").strip()
    return bool(q) and len(q) <= 16 and any(marker in q for marker in _FOLLOW_UP_MARKERS)


def build_memory_context(question: str, episodic=None, semantic=None, conversation_id: str = "") -> str:
    """按当前问题检索本地记忆（episodic + 推导链 + semantic）。全部容错。

    只对同一会话的短跟进问句回补最近上下文；普通问题绝不塞全局最近记录，
    防止测试噪音或无关历史污染调查。
    """
    parts = []
    if episodic is not None:
        try:
            eps = list(episodic.search(question, limit=5) or [])
            # "再试/继续"类短跟进需要连续性，但只允许读取同一 conversation。
            if not eps and conversation_id and _looks_like_follow_up(question):
                eps = list(episodic.get_recent_by_conversation(conversation_id, limit=3) or [])
            fmt = episodic.format_for_context(eps)
            if fmt:
                parts.append("## 历史相关记录（episodic，检索线索，需复核）\n" + fmt)
        except Exception:  # noqa: BLE001
            log.warning("internal_facts.episodic_search_failed", exc_info=True)
        try:
            chains = episodic.search_derivation_chains(question, limit=3) or []
            fmt = _format_derivation_chains(chains)
            if fmt:
                parts.append("## 历史推导链\n" + fmt)
        except Exception:  # noqa: BLE001
            log.warning("internal_facts.derivation_search_failed", exc_info=True)
    if semantic is not None:
        try:
            entries = semantic.retrieve(question, limit=5) or []
            fmt = semantic.format_for_context(entries)
            if fmt:
                parts.append("## 蒸馏知识（semantic，检索线索，需复核）\n" + fmt)
        except Exception:  # noqa: BLE001
            log.warning("internal_facts.semantic_search_failed", exc_info=True)
    return "\n\n".join(parts)


def build_internal_context(
    question: str,
    registry,
    workspace=None,
    episodic=None,
    semantic=None,
    self_model: str = "",
    conversation_id: str = "",
) -> str:
    """聚合内部事实：本地记忆（按问题动态检索）+ 自我快照。

    self_model 为空时现场构建；调用方可自行缓存后传入以省去重复构建。
    """
    parts = []
    memory = build_memory_context(
        question, episodic=episodic, semantic=semantic, conversation_id=conversation_id
    )
    if memory:
        parts.append("## 内部记忆（本地数据库检索）\n" + memory)
    if not self_model:
        try:
            self_model = build_self_model(registry, workspace)
        except Exception:  # noqa: BLE001
            log.warning("internal_facts.self_model_failed", exc_info=True)
            self_model = ""
    if self_model:
        parts.append(self_model)
    text = "\n\n".join(parts)
    if len(text) > MAX_INTERNAL_CHARS:
        text = text[:MAX_INTERNAL_CHARS] + "\n…（内部事实已截断）"
    return text