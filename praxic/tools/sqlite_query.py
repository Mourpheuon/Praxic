"""
Praxic Agent —— SQLite 查询工具（只读）

对工作区内的 .db/.sqlite/.sqlite3 数据库执行只读 SQL 查询。
- 仅允许 SELECT / PRAGMA / EXPLAIN（查询类语句），禁止写操作
- 结果行数限制，避免大表溢出
- observe 类，全权限档自动放行
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .base import ActionKind, BaseTool, ToolResult, ToolStatus
from .filesystem import _safe_path

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"

# 允许的 SQL 前缀（只读）
_ALLOWED_PREFIXES = ("select", "pragma", "explain", "with")
_MAX_ROWS = 500
_MAX_COL_WIDTH = 120


class SqliteQueryTool(BaseTool):
    """对 SQLite 数据库执行只读查询"""

    name = "sqlite_query"
    category = "data"
    description = "对工作区内 SQLite 数据库（.db/.sqlite）执行只读 SELECT/PRAGMA 查询"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "path": {"type": "string", "description": "数据库文件路径（相对工作区）"},
        "query": {"type": "string", "description": "只读 SQL（SELECT/PRAGMA/EXPLAIN/WITH）"},
        "limit": {"type": "number", "default": 100, "description": "结果行数上限"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _validate_query(self, query: str) -> str:
        q = query.strip().rstrip(";").strip()
        if not q:
            raise ValueError("query 不能为空")
        lower = q.lower()
        if not any(lower.startswith(p) for p in _ALLOWED_PREFIXES):
            raise ValueError("仅允许只读查询（SELECT/PRAGMA/EXPLAIN/WITH），收到非查询语句")
        # 防御性：禁止分号拼接多条语句
        if ";" in q:
            raise ValueError("仅允许单条语句，不支持分号拼接")
        return q

    async def run(self, path: str, query: str, limit: int = 100) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists() or not target.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"数据库不存在：{path}")
            q = self._validate_query(query)
            max_rows = max(1, min(int(limit), _MAX_ROWS))
            conn = sqlite3.connect(str(target))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(q)
                columns = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                if truncated:
                    rows = rows[:max_rows]
                dict_rows = [dict(r) for r in rows]
            finally:
                conn.close()
            lines = []
            if not columns:
                lines.append("（语句无结果集）")
            else:
                header = " | ".join(columns)
                lines.append(f"字段：{header}")
                for r in dict_rows:
                    vals = []
                    for c in columns:
                        v = r.get(c)
                        s = str(v) if v is not None else "NULL"
                        if len(s) > _MAX_COL_WIDTH:
                            s = s[:_MAX_COL_WIDTH] + "..."
                        vals.append(s)
                    lines.append(" | ".join(vals))
            if truncated:
                lines.append(f"...（结果超过 {max_rows} 行已截断）")
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="\n".join(lines),
                data={"columns": columns, "rows": dict_rows, "count": len(dict_rows), "truncated": truncated},
                metadata={"count": len(dict_rows)},
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except ValueError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except sqlite3.Error as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"SQL 错误：{e}")
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"查询失败：{e}")
