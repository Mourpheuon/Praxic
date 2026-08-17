"""cordis YAML 组合加载器。

对应 dsh 的 loader + group 插件。组合文件是一组声明行：

.. code-block:: yaml

    - id: llm
      name: praxic.cordis.services.llm:LLMService
      config:
        model: deepseek
      inject: []
      disabled: false
      isolate: {}
      group:
        - id: sub
          name: ...

行为约定：
- ``group`` 递归展开为扁平行，组路径保留用于定位；
- ``isolate: {serviceName: true}`` 为 entry 建 entry-local realm，
  同名行（id == serviceName）注册进 realm，同 label 幂等复用；
- ``disabled`` 仅支持白名单表达式，不支持任意 eval；
- 坏行（缺 id/name、导入失败、schema 校验失败）记录并标记失败，
  不拖垮整个组合；inject 环是组合级错误，直接抛出。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import structlog
import yaml

from .context import Context
from .errors import CompositionError
from .registry import PluginDef, Registry

log = structlog.get_logger(__name__)

# YAML 行允许的字段（白名单，未知字段忽略并告警）
_ALLOWED_FIELDS = {"id", "name", "config", "disabled", "inject", "isolate", "group"}


@dataclass
class LoadedRow:
    """一行组合声明的加载结果。"""

    id: str
    group: list[str] = field(default_factory=list)
    ok: bool = True
    error: str | None = None


@dataclass
class LoadResult:
    """一次组合加载的完整结果。"""

    rows: list[LoadedRow]
    activated: list[str]
    failed: list[tuple[str, str]]
    registry: Registry
    realms: dict[str, Context] = field(default_factory=dict)


# ----------------------------------------------------------------------
# disabled 白名单
# ----------------------------------------------------------------------
def eval_disabled(expr: Any, platform: str | None = None, env: Mapping | None = None) -> bool:
    """求值 disabled 表达式。

    支持三种形式：
    - 布尔 ``true/false``；
    - 字符串 ``platform:win32|linux`` / ``env:KEY``；
    - 映射 ``{platform: "win32|linux"}`` / ``{env: KEY}``。

    其余形式抛 ``ValueError``（不做任意 eval）。
    """
    platform = platform or sys.platform
    env = env if env is not None else os.environ

    if isinstance(expr, bool):
        return expr
    if isinstance(expr, str):
        text = expr.strip()
        if text == "true":
            return True
        if text == "false":
            return False
        if text.startswith("platform:"):
            targets = [p.strip() for p in text[len("platform:"):].split("|") if p.strip()]
            return platform in targets
        if text.startswith("env:"):
            return bool(env.get(text[len("env:"):].strip()))
        raise ValueError(f"不支持的 disabled 表达式: {expr!r}")
    if isinstance(expr, Mapping):
        if "platform" in expr:
            targets = [p.strip() for p in str(expr["platform"]).split("|") if p.strip()]
            return platform in targets
        if "env" in expr:
            return bool(env.get(str(expr["env"])))
        raise ValueError(f"不支持的 disabled 表达式: {expr!r}")
    raise ValueError(f"不支持的 disabled 表达式: {expr!r}")


# ----------------------------------------------------------------------
# group 展开
# ----------------------------------------------------------------------
def _flatten_groups(
    raw_rows: Sequence[Mapping[str, Any]],
    group_path: list[str] | None = None,
) -> list[tuple[Mapping[str, Any], list[str]]]:
    """递归展开 group 嵌套，返回 (行 dict, 组路径) 列表。

    group 行本身不产生服务行，仅作为容器；组路径保留用于定位与报错。
    """
    result: list[tuple[Mapping[str, Any], list[str]]] = []
    for row in raw_rows or []:
        if not isinstance(row, Mapping):
            log.warning("cordis.loader.non_mapping_row", row=row)
            continue
        children = row.get("group")
        if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
            path = list(group_path or [])
            if row.get("id"):
                path = path + [str(row["id"])]
            result.extend(_flatten_groups(children, path))
            continue
        result.append((row, list(group_path or [])))
    return result


# ----------------------------------------------------------------------
# entry-local realm
# ----------------------------------------------------------------------
class _EntryScope:
    """一次组合加载的 entry 作用域：管理 entry-local realm。

    同 label（此处即服务名）的 realm 幂等复用，对齐 P2 会话 realm 语义。
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._realms: dict[str, Context] = {}

    def realm_for(self, name: str) -> Context:
        if name not in self._realms:
            self._realms[name] = self.ctx.isolate(name, label=name)
        return self._realms[name]


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------
def load_composition(
    source: str | Path,
    ctx: Context,
    *,
    platform: str | None = None,
    env: Mapping | None = None,
    registry: Registry | None = None,
) -> LoadResult:
    """加载组合并逐行激活插件。

    ``source`` 为 YAML 文件路径或 YAML 文本。``ctx`` 为组合挂载的根
    context（通常来自 host root）。返回 ``LoadResult``。
    """
    if isinstance(source, (str, Path)) and _looks_like_path(source):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = source
    raw = yaml.safe_load(text) or []
    if not isinstance(raw, list):
        raise ValueError(f"组合文件必须是行列表，收到 {type(raw).__name__}")

    flat = _flatten_groups(raw)
    reg = registry or Registry(ctx)
    rows: list[LoadedRow] = []
    valid: list[tuple[Mapping[str, Any], list[str]]] = []
    schema_failures: list[tuple[str, str]] = []

    # 第一遍：schema 校验 + disabled 求值
    for row, path in flat:
        row_id = row.get("id")
        if not row_id or not isinstance(row_id, str):
            shown = repr(row_id)
            hint = (
                "（注意：YAML 1.1 会把 off/on/yes/no/true/false 解析为布尔值，"
                "id 请避免使用这些词）"
            )
            message = f"缺少 id 或 id 非字符串（实际为 {shown}）{hint}"
            rows.append(LoadedRow(id=str(row_id or "<no-id>"), group=path, ok=False,
                                  error=message))
            schema_failures.append((str(row_id or "<no-id>"), message))
            log.warning("cordis.loader.missing_id", id=shown, group=path)
            continue
        if "name" not in row and "apply" not in row:
            message = "缺少 name（module:Class）或 apply"
            rows.append(LoadedRow(id=row_id, group=path, ok=False, error=message))
            schema_failures.append((row_id, message))
            log.warning("cordis.loader.missing_name", id=row_id)
            continue
        try:
            disabled = eval_disabled(row.get("disabled", False), platform=platform, env=env)
        except ValueError as exc:
            message = str(exc)
            rows.append(LoadedRow(id=row_id, group=path, ok=False, error=message))
            schema_failures.append((row_id, message))
            continue
        if disabled:
            rows.append(LoadedRow(id=row_id, group=path, ok=True,
                                  error=None))
            log.info("cordis.loader.disabled", id=row_id)
            continue
        valid.append((row, path))
        rows.append(LoadedRow(id=row_id, group=path))

    # inject 环检测：组合级错误，发现即抛
    valid_rows = [PluginDef(id=r[0]["id"], inject=list(r[0].get("inject", []) or [])) for r in valid]
    Registry.detect_inject_cycle(valid_rows)

    # 撞名预检（P2 收紧）：组合内行 id 必须唯一，重复即组合级错误
    seen_ids: dict[str, list[str]] = {}
    for row, path in valid:
        seen_ids.setdefault(row["id"], []).append(".".join(path) or "<root>")
    duplicates = {rid: paths for rid, paths in seen_ids.items() if len(paths) > 1}
    if duplicates:
        detail = "; ".join(f"{rid}@{','.join(paths)}" for rid, paths in duplicates.items())
        raise CompositionError(f"组合存在重复服务 id（撞名收紧，必须唯一）：{detail}")

    # 第二遍：收集 isolate 声明，预建 entry-local realm（同 label 幂等复用）
    scope = _EntryScope(ctx)
    isolated_names: set[str] = set()
    for row, _path in valid:
        for name, flag in (row.get("isolate") or {}).items():
            if flag:
                isolated_names.add(str(name))
    for name in sorted(isolated_names):
        scope.realm_for(name)

    # 第三遍：逐行激活
    for row, path in valid:
        row_id = row["id"]
        target = scope.realm_for(row_id) if row_id in isolated_names else ctx
        plugin = PluginDef(
            id=row_id,
            name=row.get("name"),
            config=dict(row.get("config") or {}),
            inject=list(row.get("inject", []) or []),
            isolate=dict(row.get("isolate") or {}),
        )
        # 组合文件不提供内联 apply；保留字段以备未来扩展
        ok = reg.activate(plugin, ctx=target)
        if not ok:
            message = "; ".join(err for rid, err in reg.failed if rid == row_id)
            for loaded in rows:
                if loaded.id == row_id and loaded.ok:
                    loaded.ok = False
                    loaded.error = message or "激活失败"
                    break

    return LoadResult(
        rows=rows,
        activated=reg.activated,
        failed=list(reg.failed) + schema_failures,
        registry=reg,
        realms=dict(scope._realms),
    )


def _looks_like_path(source: Any) -> bool:
    """判断 source 是否更像文件路径而非 YAML 文本。"""
    if isinstance(source, Path):
        return True
    if not isinstance(source, str):
        return False
    text = source.lstrip()
    if text.startswith(("-", "id:", "{", "[", " ")):
        return False
    if "\n" in source:
        return False
    return not source.startswith("{") and len(source) < 300
