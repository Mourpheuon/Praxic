"""
Praxic Agent —— 结构化数据查询工具（observe 类）

读取 CSV / JSON / JSONL 文件并提供结构化查询：
- 概述：schema、行数、字段
- 筛选：按字段条件过滤
- 统计：数值列聚合（sum/mean/min/max/count）
- 取行：前 N 行 / 指定区间

全部为只读操作，ActionKind.OBSERVE。数据校验严格，输出结构化便于分析层读取。
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .base import ActionKind, BaseTool, ToolResult, ToolStatus
from .filesystem import _safe_path

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"


class DataQueryTool(BaseTool):
    """查询 CSV/JSON/JSONL 结构化数据（只读）"""

    name = "data_query"
    description = "查询 CSV/JSON/JSONL 数据文件：概述、筛选、统计、取行（只读）"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "path": {"type": "string", "description": "数据文件路径（相对工作区）"},
        "action": {"type": "string", "default": "overview", "description": "overview | filter | stats | head"},
        "fields": {"type": "array", "default": [], "description": "要返回/操作的字段名列表（空=全部）"},
        "condition": {"type": "string", "default": "", "description": "筛选条件，如 'age > 30' 或 'city == 北京'"},
        "limit": {"type": "number", "default": 20},
        "offset": {"type": "number", "default": 0},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        path: str,
        action: str = "overview",
        fields: list | None = None,
        condition: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        fields = fields or []
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists() or not target.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"文件不存在：{path}")
            suffix = target.suffix.lower()
            if suffix == ".csv":
                rows, headers = self._read_csv(target)
            elif suffix in (".json", ".jsonl"):
                rows, headers = self._read_json(target, suffix == ".jsonl")
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"不支持的数据格式：{suffix}（支持 .csv / .json / .jsonl）",
                )
            if not rows:
                return ToolResult(status=ToolStatus.SUCCESS, content="（数据为空）", data={"rows": [], "count": 0})

            if action == "overview":
                return self._overview(rows, headers)
            if action == "head":
                return self._head(rows, fields, limit, offset)
            if action == "filter":
                filtered = self._filter(rows, condition)
                return self._head(filtered, fields, limit, offset, total=len(filtered))
            if action == "stats":
                return self._stats(rows, fields)
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"未知 action：{action}（支持 overview|filter|stats|head）")
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"查询失败：{e}")

    # ── 读取 ──
    def _read_csv(self, target: Path) -> tuple[list[dict], list[str]]:
        with open(target, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [dict(row) for row in reader]
        return rows, headers

    def _read_json(self, target: Path, jsonl: bool) -> tuple[list[dict], list[str]]:
        if jsonl:
            rows = []
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        else:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            rows = data if isinstance(data, list) else [data]
        rows = [r for r in rows if isinstance(r, dict)]
        headers = []
        for r in rows:
            for k in r:
                if k not in headers:
                    headers.append(k)
        return rows, headers

    # ── 动作 ──
    def _overview(self, rows: list[dict], headers: list[str]) -> ToolResult:
        lines = [f"行数：{len(rows)}", f"字段：{', '.join(headers) if headers else '（无）'}"]
        # 字段类型推断（抽样前 100 行）
        sample = rows[:100]
        for h in headers:
            types = set()
            for r in sample:
                v = r.get(h)
                if v is None or v == "":
                    continue
                types.add("number" if isinstance(v, (int, float)) else "string")
            types_s = "/".join(sorted(types)) if types else "?"
            lines.append(f"  {h}: {types_s}")
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="\n".join(lines),
            data={"count": len(rows), "headers": headers},
            metadata={"count": len(rows)},
        )

    def _head(self, rows: list[dict], fields: list[str], limit: int, offset: int, total: int | None = None) -> ToolResult:
        selected = rows[offset:offset + limit] if limit > 0 else rows[offset:]
        out = []
        for r in selected:
            if fields:
                out.append({f: r.get(f) for f in fields if f in r})
            else:
                out.append(r)
        count = total if total is not None else len(rows)
        lines = [f"共 {count} 行，返回 {len(out)} 行："]
        for i, r in enumerate(out):
            lines.append(f"  [{offset + i}] {json.dumps(r, ensure_ascii=False)[:200]}")
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="\n".join(lines),
            data={"rows": out, "count": count, "returned": len(out)},
            metadata={"count": count, "returned": len(out)},
        )

    def _filter(self, rows: list[dict], condition: str) -> list[dict]:
        if not condition.strip():
            return rows
        cond = condition.strip()
        # 支持 "field op value"：== != > < >= <=，value 数字或字符串（不带引号或带单双引号）
        import re
        m = re.match(r"^(\S+)\s*(==|!=|>=|<=|>|<)\s*(.+)$", cond)
        if not m:
            raise ValueError(f"无法解析筛选条件：{condition}（格式：field op value）")
        field, op, raw_value = m.group(1), m.group(2), m.group(3).strip().strip("\"'")
        if re.fullmatch(r"-?\d+(\.\d+)?", raw_value):
            value: object = float(raw_value) if "." in raw_value else int(raw_value)
        else:
            value = raw_value
        result = []
        for r in rows:
            if field not in r:
                continue
            cell = r[field]
            try:
                cell_num = float(cell) if isinstance(cell, str) and re.fullmatch(r"-?\d+(\.\d+)?", cell.strip()) else cell
            except (ValueError, TypeError):
                cell_num = cell
            cmp_val = value
            if isinstance(cell_num, (int, float)) and isinstance(value, (int, float)):
                cmp_val = float(value)
                cell_cmp = float(cell_num)
            else:
                cell_cmp = str(cell_num)
                cmp_val = str(value)
            if op == "==" and cell_cmp == cmp_val:
                result.append(r)
            elif op == "!=" and cell_cmp != cmp_val:
                result.append(r)
            elif op == ">" and cell_cmp > cmp_val:
                result.append(r)
            elif op == "<" and cell_cmp < cmp_val:
                result.append(r)
            elif op == ">=" and cell_cmp >= cmp_val:
                result.append(r)
            elif op == "<=" and cell_cmp <= cmp_val:
                result.append(r)
        return result

    def _stats(self, rows: list[dict], fields: list[str]) -> ToolResult:
        targets = fields or self._numeric_fields(rows)
        lines = []
        data: dict = {}
        for f in targets:
            values = []
            for r in rows:
                v = r.get(f)
                if isinstance(v, (int, float)):
                    values.append(float(v))
                elif isinstance(v, str):
                    try:
                        values.append(float(v))
                    except ValueError:
                        pass
            if not values:
                continue
            stats = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": round(statistics.mean(values), 4),
            }
            if len(values) > 1:
                stats["stdev"] = round(statistics.stdev(values), 4)
            lines.append(f"{f}: count={stats['count']} min={stats['min']} max={stats['max']} mean={stats['mean']}")
            data[f] = stats
        if not lines:
            return ToolResult(status=ToolStatus.SUCCESS, content="（没有可统计的数值字段）", data={})
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="\n".join(lines),
            data={"stats": data},
            metadata={"fields": list(data.keys())},
        )

    def _numeric_fields(self, rows: list[dict]) -> list[str]:
        numeric = []
        sample = rows[:50]
        for r in sample:
            for k, v in r.items():
                if k in numeric:
                    continue
                if isinstance(v, (int, float)):
                    numeric.append(k)
                elif isinstance(v, str):
                    try:
                        float(v)
                        numeric.append(k)
                    except ValueError:
                        pass
        return numeric
