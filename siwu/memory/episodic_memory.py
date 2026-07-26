"""
思悟 Agent —— 情节记忆
存储历史交互记录（实践经验），支持跨会话检索和多轮对话上下文
改进四：推导链持久化 —— 跨会话累积和检索推理路径
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


class EpisodicMemory:
    """
    情节记忆 —— 历史实践经验的积累

    使用 SQLite 持久化存储。支持按 conversation_id 分组的多轮对话上下文。
    改进四：新增 derivation_chains 表，支持推理路径的跨会话累积和检索。
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.data_dir / "episodic.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id      TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    question        TEXT NOT NULL,
                    summary         TEXT NOT NULL,
                    action_items    TEXT DEFAULT '[]',
                    principal_contradiction TEXT DEFAULT '',
                    lessons         TEXT DEFAULT '[]',
                    created_at      TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON episodes(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation ON episodes(conversation_id)")
            try:
                conn.execute("ALTER TABLE episodes ADD COLUMN conversation_id TEXT NOT NULL DEFAULT ''")
                log.info("episodic_memory.migration", added="conversation_id")
            except sqlite3.OperationalError:
                pass
            # 改进四：推导链持久化
            try:
                conn.execute("ALTER TABLE episodes ADD COLUMN derivation_chains TEXT DEFAULT '[]'")
                log.info("episodic_memory.migration", added="derivation_chains column")
            except sqlite3.OperationalError:
                pass
            # 清理旧版产生的重复占位记录（每轮保存两条：[...] + 真实摘要）
            try:
                conn.execute(
                    "DELETE FROM episodes WHERE summary = '[...]' "
                    "AND session_id IN (SELECT session_id FROM episodes WHERE summary != '[...]')"
                )
            except sqlite3.OperationalError:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS derivation_chains (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id        TEXT NOT NULL,
                    episode_id      INTEGER NOT NULL,
                    contradiction   TEXT NOT NULL DEFAULT '',
                    summary         TEXT NOT NULL,
                    steps_json      TEXT NOT NULL,
                    factual_foundation TEXT DEFAULT '[]',
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (episode_id) REFERENCES episodes(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dc_chain_id ON derivation_chains(chain_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_meta (
                    conversation_id TEXT PRIMARY KEY,
                    name            TEXT NOT NULL DEFAULT '',
                    updated_at      TEXT NOT NULL
                )
            """)
            # project_id 迁移（v0.2.0）—— 项目归属，conversation_meta 为权威来源
            try:
                conn.execute("ALTER TABLE episodes ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
                log.info("episodic_memory.migration", added="episodes.project_id")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE conversation_meta ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
                log.info("episodic_memory.migration", added="conversation_meta.project_id")
            except sqlite3.OperationalError:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ep_project ON episodes(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cm_project ON conversation_meta(project_id)")
            conn.commit()

    def save_episode(self, session_id, question, summary, action_items=None,
                     principal_contradiction="", lessons=None, conversation_id="",
                     derivation_chains=None, upsert_session=False, project_id=""):
        """Save an episode. If upsert_session=True, deletes the in-progress
        placeholder ('[...]') for this session_id before inserting the real one."""
        with sqlite3.connect(self.db_path) as conn:
            if upsert_session:
                conn.execute(
                    "DELETE FROM episodes WHERE session_id = ? AND summary = '[...]'",
                    (session_id,),
                )
            # 改进四：保存推导链 JSON 到 episodes 表
            dc_json = "[]"
            if derivation_chains:
                try:
                    dc_json = json.dumps(derivation_chains, ensure_ascii=False)
                except (TypeError, ValueError):
                    dc_json = "[]"

            cursor = conn.execute(
                """INSERT INTO episodes
                   (session_id, conversation_id, project_id, question, summary, action_items,
                    principal_contradiction, lessons, created_at, derivation_chains)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, conversation_id, project_id, question, summary,
                 json.dumps(action_items or [], ensure_ascii=False),
                 principal_contradiction,
                 json.dumps(lessons or [], ensure_ascii=False),
                 datetime.now().isoformat(),
                 dc_json),
            )
            eid = cursor.lastrowid

            # 改进四：保存推导链到独立表（用于跨会话检索）
            if derivation_chains:
                for dc in derivation_chains:
                    conn.execute(
                        """INSERT INTO derivation_chains
                           (chain_id, episode_id, contradiction, summary, steps_json,
                            factual_foundation, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (dc.get("chain_id", ""),
                         eid,
                         dc.get("contradiction", "")[:200],
                         dc.get("summary", ""),
                         json.dumps(dc.get("steps", []), ensure_ascii=False),
                         json.dumps(dc.get("factual_foundation", []), ensure_ascii=False),
                         datetime.now().isoformat()),
                    )

            conn.commit()
            log.info("episodic_memory.saved", id=eid, session=session_id, conversation=conversation_id)
            return eid

    def get_recent_by_conversation(self, conversation_id, limit=5, exclude_session="", project_id=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM episodes WHERE conversation_id = ? AND conversation_id != '' AND summary != '[...]' "
            params = [conversation_id]
            if exclude_session:
                query += "AND session_id != ? "
                params.append(exclude_session)
            if project_id is not None:
                query += "AND project_id = ? "
                params.append(project_id)
            query += "ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def search(self, query, limit=5):
        keywords = query.split()[:5]
        if not keywords:
            return self.get_recent(limit)
        conditions = " OR ".join("question LIKE ? OR summary LIKE ?" for _ in keywords)
        params = []
        for kw in keywords:
            params.extend(["%" + kw + "%", "%" + kw + "%"])
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM episodes WHERE " + conditions + " ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, limit=5):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ═══════════════════════════════════════════════════════════════════
    # 改进四：推导链检索 —— 跨会话累积推理路径
    # ═══════════════════════════════════════════════════════════════════

    def search_derivation_chains(self, question: str, limit: int = 3) -> list[dict]:
        """检索与当前问题相关的历史推导链"""
        keywords = question.split()[:5]
        if not keywords:
            return []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conditions = " OR ".join("dc.summary LIKE ?" for _ in keywords)
            params = []
            for kw in keywords:
                params.append("%" + kw + "%")
            params.append(limit)

            rows = conn.execute(
                "SELECT dc.*, e.question as source_question "
                "FROM derivation_chains dc "
                "JOIN episodes e ON dc.episode_id = e.id "
                "WHERE " + conditions +
                " ORDER BY dc.created_at DESC LIMIT ?",
                params,
            ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            try:
                d["steps"] = json.loads(d.get("steps_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["steps"] = []
            try:
                d["factual_foundation"] = json.loads(d.get("factual_foundation", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["factual_foundation"] = []
            results.append(d)
        return results

    def build_conversation_context(self, conversation_id="", current_question="",
                                   max_turns=5, exclude_session="", project_id=None):
        parts = []
        recent = []
        if conversation_id:
            recent = self.get_recent_by_conversation(
                conversation_id, limit=max_turns, exclude_session=exclude_session,
                project_id=project_id,
            )
            if recent:
                lines = ["[此前对话记录]"]
                for i, ep in enumerate(reversed(recent), 1):
                    lines.append(
                        f"第{i}轮 - 用户问题：{ep['question'][:200]}\n"
                        f"      结论：{ep['summary'][:250]}"
                    )
                parts.append("\n".join(lines))
        if current_question:
            relevant = self.search(current_question, limit=3)
            existing_ids = {ep["id"] for ep in recent}
            filtered = [ep for ep in relevant if ep["id"] not in existing_ids]
            if filtered:
                lines = ["[相关历史经验（跨对话）]"]
                for ep in filtered:
                    lines.append(
                        f"- 曾分析过类似问题：{ep['question'][:80]}... -> {ep['summary'][:100]}"
                    )
                parts.append("\n".join(lines))

        # 改进四：历史推导链注入
        if current_question:
            past_chains = self.search_derivation_chains(current_question, limit=3)
            if past_chains:
                lines = ["[历史推导链 —— 过往类似问题的推理路径，供参考而非直接套用]"]
                for i, dc in enumerate(past_chains, 1):
                    steps_text = ""
                    for s in dc.get("steps", [])[:4]:
                        steps_text += (
                            "\n    步骤：" + (s.get("inference", "") or "")[:150] +
                            "\n    结论：" + (s.get("conclusion", "") or "")[:150]
                        )
                    source_q = (dc.get("source_question", "") or "")[:60]
                    lines.append(
                        "推导链" + str(i) + "（来源问题：" + source_q + "...）\n"
                        "  整体逻辑：" + (dc.get("summary", "") or "")[:200] + "\n"
                        "  推理步骤：" + steps_text
                    )
                parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def list_conversations(self, project_id=None):
        """列出对话，按最近活动排序。
        project_id=None → 全部；'' → 默认项目（未归属）；'x' → 指定项目。
        以 conversation_meta.project_id 为权威归属来源。"""
        where = ""
        params: list = []
        if project_id is not None:
            where = "WHERE cm.project_id = ?"
            params.append(project_id)
        sql = """
                SELECT cm.conversation_id,
                       cm.project_id,
                       COALESCE(MAX(e.created_at), cm.updated_at) AS last_active,
                       COUNT(e.id) AS question_count,
                       (SELECT question FROM episodes e2
                        WHERE e2.conversation_id = cm.conversation_id
                          AND e2.conversation_id != ''
                          AND e2.summary != '[...]'
                        ORDER BY created_at DESC LIMIT 1) AS last_question
                FROM conversation_meta cm
                LEFT JOIN episodes e ON e.conversation_id = cm.conversation_id
                                      AND e.summary != '[...]'
                %s
                GROUP BY cm.conversation_id
                ORDER BY last_active DESC
        """ % where
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_conversation_project(self, conversation_id, project_id):
        """设置/更新对话所属项目（并确保 conversation_meta 行存在）。"""
        if not conversation_id:
            return
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO conversation_meta (conversation_id, name, updated_at, project_id)
                   VALUES (?, '', ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET project_id = ?, updated_at = ?""",
                (conversation_id, now, project_id or "", project_id or "", now),
            )
            conn.commit()

    def list_projects(self):
        """列出所有项目（以 conversation_meta.project_id 分组）及统计。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT cm.project_id AS project_id,
                       COUNT(DISTINCT cm.conversation_id) AS conversation_count,
                       MAX(COALESCE(e.created_at, cm.updated_at)) AS last_active
                FROM conversation_meta cm
                LEFT JOIN episodes e ON e.conversation_id = cm.conversation_id
                                      AND e.summary != '[...]'
                GROUP BY cm.project_id
                ORDER BY last_active DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def get_conversation_turns(self, conversation_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT session_id, question, summary, action_items, created_at
                   FROM episodes WHERE conversation_id = ?
                   ORDER BY created_at ASC""",
                (conversation_id,),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["action_items"] = json.loads(d.get("action_items", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["action_items"] = []
            results.append(d)
        return results

    def get_conversation_name(self, conversation_id):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT name FROM conversation_meta WHERE conversation_id = ? AND name != ''",
                (conversation_id,),
            ).fetchone()
            if row:
                return row[0]
            row = conn.execute(
                "SELECT question FROM episodes WHERE conversation_id = ? ORDER BY created_at ASC LIMIT 1",
                (conversation_id,),
            ).fetchone()
        if row:
            return row[0][:60]
        return ""

    def set_conversation_name(self, conversation_id, name):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO conversation_meta (conversation_id, name, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET name = ?, updated_at = ?""",
                (conversation_id, name, datetime.now().isoformat(), name, datetime.now().isoformat()),
            )
            conn.commit()
            log.info("episodic_memory.conversation_renamed", conversation=conversation_id, name=name)

    def delete_conversation(self, conversation_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM episodes WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM conversation_meta WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()
            deleted = cursor.rowcount
            log.info("episodic_memory.conversation_deleted",
                     conversation=conversation_id, rows=deleted)
            return deleted > 0

    def format_for_context(self, episodes):
        if not episodes:
            return ""
        lines = ["[相关历史经验]"]
        for ep in episodes:
            lines.append(f"- 问题：{ep['question'][:60]}... -> 结论：{ep['summary'][:80]}")
        return "\n".join(lines)
