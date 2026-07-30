"""
Praxic Agent —— 语义记忆
将情节经验抽象化为可复用的理性知识（理性认识的积累）
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings

log = structlog.get_logger(__name__)


class SemanticMemory:
    """
    语义记忆 —— 从感性认识到理性认识的知识积累

    存储跨会话抽象化后的知识片段：
    - 领域规律（domain patterns）
    - 经验法则（heuristics）
    - 反模式（anti-patterns）

    使用 SQLite 持久化，后续可接入向量数据库做相似度检索。
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.data_dir / "semantic.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain      TEXT NOT NULL DEFAULT 'general',
                    category    TEXT NOT NULL DEFAULT 'pattern',
                    content     TEXT NOT NULL,
                    evidence    TEXT DEFAULT '[]',
                    confidence  REAL DEFAULT 0.7,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    use_count   INTEGER DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain ON knowledge(domain)"
            )
            conn.commit()

    def store(
        self,
        content: str,
        domain: str = "general",
        category: str = "pattern",   # pattern | heuristic | anti-pattern
        evidence: list[str] = None,
        confidence: float = 0.7,
    ) -> int:
        """存储一条抽象化的知识"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge
                  (domain, category, content, evidence, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    category,
                    content,
                    json.dumps(evidence or [], ensure_ascii=False),
                    confidence,
                    now,
                    now,
                ),
            )
            conn.commit()
            kid = cursor.lastrowid
            log.info("semantic_memory.stored", id=kid, domain=domain)
            return kid

    def retrieve(
        self,
        query: str,
        domain: str = "",
        limit: int = 5,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """检索相关知识"""
        conditions = ["confidence >= ?"]
        params: list = [min_confidence]
        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if query:
            kws = query.split()[:4]
            kw_conds = " OR ".join("content LIKE ?" for _ in kws)
            conditions.append(f"({kw_conds})")
            for kw in kws:
                params.append(f"%{kw}%")
        params.append(limit)
        where = " AND ".join(conditions)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM knowledge WHERE {where} "
                "ORDER BY confidence DESC, use_count DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def increment_use(self, knowledge_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE knowledge SET use_count = use_count + 1 WHERE id = ?",
                (knowledge_id,),
            )
            conn.commit()

    def format_for_context(self, entries: list[dict]) -> str:
        if not entries:
            return ""
        lines = ["[相关知识经验]"]
        for e in entries:
            tag = f"[{e.get('category', 'pattern')}]"
            lines.append(f"- {tag} {e['content'][:120]}")
        return "\n".join(lines)

    def consolidate_from_lessons(
        self,
        lessons: list[str],
        domain: str = "general",
    ) -> None:
        """
        将反思引擎产出的经验教训固化为语义记忆。
        这是"从实践到理性认识"的具体实现。
        """
        for lesson in lessons:
            if len(lesson.strip()) > 10:
                self.store(
                    content=lesson.strip(),
                    domain=domain,
                    category="heuristic",
                    confidence=0.6,
                )
