"""
Praxic Agent —— 情节记忆
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
                    context         TEXT NOT NULL DEFAULT '',
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
            try:
                conn.execute("ALTER TABLE episodes ADD COLUMN context TEXT NOT NULL DEFAULT ''")
                log.info("episodic_memory.migration", added="context")
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
                    updated_at      TEXT NOT NULL,
                    pinned          INTEGER NOT NULL DEFAULT 0
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
            try:
                conn.execute("ALTER TABLE conversation_meta ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
                log.info("episodic_memory.migration", added="conversation_meta.pinned")
            except sqlite3.OperationalError:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    session_id      TEXT NOT NULL DEFAULT '',
                    phase           TEXT NOT NULL DEFAULT '',
                    summary         TEXT NOT NULL DEFAULT '',
                    event_type      TEXT NOT NULL DEFAULT 'phase',
                    data            TEXT NOT NULL DEFAULT '{}',
                    speaker         TEXT NOT NULL DEFAULT 'agent',
                    created_at      TEXT NOT NULL
                )
            """)
            # speaker 迁移（v0.2.x）：发言人标记——user / agent / tool / system，
            # 供结构化上下文提取按发言人过滤（区分用户输入与智能体/工具产物）。
            try:
                conn.execute("ALTER TABLE conversation_events ADD COLUMN speaker TEXT NOT NULL DEFAULT 'agent'")
                log.info("episodic_memory.migration", added="conversation_events.speaker")
            except sqlite3.OperationalError:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ce_conversation ON conversation_events(conversation_id, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ce_session ON conversation_events(session_id, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ep_project ON episodes(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cm_project ON conversation_meta(project_id)")
            conn.commit()

    def save_episode(self, session_id, question, summary, action_items=None,
                     principal_contradiction="", lessons=None, conversation_id="",
                     derivation_chains=None, upsert_session=False, project_id="", context=""):
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
                   (session_id, conversation_id, project_id, question, context, summary, action_items,
                    principal_contradiction, lessons, created_at, derivation_chains)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, conversation_id, project_id, question, context or "", summary,
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

    def _events_conversation_context(self, conversation_id, max_turns=5, exclude_session="") -> str:
        """从 conversation_events 按发言人/阶段结构化提取历史上下文。

        规则：
        - 按时间顺序取最近 max_turns 个会话（session_id 分组）
        - 用户发言（speaker=user）作为【用户】
        - 阶段事件（speaker=agent）取阶段结论摘要
        - 工具事件（speaker=tool）取工具名与执行摘要
        - 思维链等长文本不进入上下文（仅供前端展示），只取结论层
        总预算受 history_budget 约束，超出时丢弃最早会话。
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, session_id, phase, summary, event_type, data, speaker, created_at
                   FROM conversation_events WHERE conversation_id = ? AND conversation_id != ''
                   ORDER BY id ASC""",
                (conversation_id,),
            ).fetchall()
        if not rows:
            return ""

        # 按 session_id 分组，保留会话内顺序
        sessions: dict = {}
        order = []
        for ev in rows:
            sid = ev["session_id"] or ""
            if sid and sid != exclude_session:
                if sid not in sessions:
                    sessions[sid] = []
                    order.append(sid)
                sessions[sid].append(ev)
        if not order:
            return ""
        # 只取最近 max_turns 个会话
        recent_sids = order[-max_turns:]

        def _line(ev) -> str:
            speaker = (ev["speaker"] or "agent")
            phase = ev["phase"] or ""
            summary = (ev["summary"] or "").strip()[:600]
            etype = ev["event_type"] or "phase"
            # data 列是 JSON 字符串，解析为 dict
            try:
                ev_data = json.loads(ev["data"] or "{}") if isinstance(ev["data"], str) else (ev["data"] or {})
            except (json.JSONDecodeError, TypeError):
                ev_data = {}
            if not isinstance(ev_data, dict):
                ev_data = {}
            if speaker == "user":
                return f"【用户】{summary}"
            if speaker == "tool":
                tool = str(ev_data.get("tool") or (ev_data.get("record") or {}).get("tool") or "")
                if not tool:
                    tool = summary.split("：")[0][:40] if summary else phase
                return f"【工具·{tool[:40]}】{summary[:200]}"
            if etype in ("result", "error"):
                return f"【智能体】{summary[:400]}"
            label = {
                "preprocessing": "问题解析", "investigation": "调查研究",
                "contradiction": "矛盾分析", "rational": "理性认识",
                "practice": "实践检验", "reflection": "反思",
            }.get(phase, phase or "阶段")
            return f"【智能体·{label}】{summary[:300]}"

        entries = []
        for sid in recent_sids:
            events = sessions[sid]
            lines = []
            for ev in events:
                ln = _line(ev)
                if ln:
                    lines.append(ln)
            if lines:
                entries.append("\n".join(lines))

        history_budget = 18000
        while entries and len("\n".join(entries)) > history_budget:
            entries.pop(0)
        if not entries:
            return ""
        return "[此前对话记录（按发言人/阶段）]\n" + "\n\n".join(entries)

    def build_conversation_context(self, conversation_id="", current_question="",
                                   max_turns=5, exclude_session="", project_id=None):
        parts = []
        recent = []
        if conversation_id:
            recent = self.get_recent_by_conversation(
                conversation_id, limit=max_turns, exclude_session=exclude_session,
                project_id=project_id,
            )
            # 结构化事件提取：从 conversation_events 按发言人/阶段组装历史，
            # 保留时间顺序与发言人标记，供上下文整合按结构取用。
            event_ctx = self._events_conversation_context(
                conversation_id, max_turns=max_turns, exclude_session=exclude_session
            )
            if event_ctx:
                parts.append(event_ctx)
            elif recent:
                # 回退：无事件记录时退化为 episodes 拼装（兼容旧数据）
                entries = []
                for i, ep in enumerate(reversed(recent), 1):
                    entries.append(
                        f"第{i}轮 - 用户问题：{ep['question'][:4000]}\n"
                        f"      结论：{ep['summary'][:4000]}"
                    )
                history_budget = 18000
                while entries and len("\n".join(entries)) > history_budget:
                    entries.pop(0)
                parts.append("[此前对话记录]\n" + "\n".join(entries))
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
        """列出全部对话，按最近活动排序。"""
        where = ""
        params = []
        if project_id is not None:
            where = "WHERE cm.project_id = ?"
            params.append(project_id or "")
        sql = """
                SELECT cm.conversation_id,
                       cm.project_id,
                       cm.pinned,
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
                {where}
                GROUP BY cm.conversation_id
                ORDER BY last_active DESC
        """.format(where=where)
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

    def set_conversation_pinned(self, conversation_id, pinned):
        """设置对话置顶状态，并确保 conversation_meta 行存在。"""
        if not conversation_id:
            return
        value = 1 if pinned else 0
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO conversation_meta (conversation_id, name, updated_at, pinned)
                   VALUES (?, '', ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET pinned = ?, updated_at = ?""",
                (conversation_id, now, value, value, now),
            )
            conn.commit()

    def append_conversation_event(self, conversation_id, session_id, phase,
                                  summary, event_type="phase", data=None,
                                  speaker="agent"):
        """持久化一次认知事件，供历史会话恢复完整过程。

        speaker：发言人标记——user（用户输入）/ agent（智能体阶段产出）/
        tool（工具调用）/ system（系统事件）。供结构化上下文提取按发言人过滤。
        """
        if not conversation_id:
            return None
        payload = data
        if hasattr(payload, "model_dump"):
            try:
                payload = payload.model_dump(mode="json")
            except TypeError:
                payload = payload.model_dump()
        elif hasattr(payload, "dict") and not isinstance(payload, dict):
            try:
                payload = payload.dict()
            except Exception:
                payload = str(payload)
        if payload is None:
            payload = {}
        elif not isinstance(payload, dict):
            payload = {"value": payload}
        else:
            payload = dict(payload)
        if event_type:
            payload.setdefault("event_type", event_type)
        try:
            data_json = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            data_json = json.dumps({"event_type": event_type, "value": str(payload)}, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO conversation_events
                   (conversation_id, session_id, phase, summary, event_type, data, speaker, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    session_id or "",
                    phase or "",
                    str(summary or ""),
                    event_type or "phase",
                    data_json,
                    speaker or "agent",
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def record_user_message(self, conversation_id, session_id, question, context=""):
        """把用户问题记录为事件流中的 user 发言（speaker=user）。

        供结构化上下文提取时区分"用户说了什么"与"智能体/工具产出了什么"。
        返回事件 id；conversation_id 为空时返回 None（不落库）。
        """
        if not conversation_id:
            return None
        return self.append_conversation_event(
            conversation_id=conversation_id,
            session_id=session_id or "",
            phase="user",
            summary=question[:2000],
            event_type="user_question",
            data={"event_type": "user_question", "content": question, "context": context or ""},
            speaker="user",
        )

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
                """SELECT session_id, question, context, summary, action_items, created_at
                   FROM episodes WHERE conversation_id = ?
                   ORDER BY created_at ASC""",
                (conversation_id,),
            ).fetchall()
            event_rows = conn.execute(
                """SELECT id, session_id, phase, summary, event_type, data, speaker, created_at
                   FROM conversation_events WHERE conversation_id = ?
                   ORDER BY id ASC""",
                (conversation_id,),
            ).fetchall()
        phase_logs_by_session = {}
        for event in event_rows:
            raw_data = event["data"] or ""
            if (event["event_type"] or "phase") == "phase" and raw_data in ("", "{}", "null"):
                event_data = None
            else:
                try:
                    event_data = json.loads(raw_data or "{}")
                except (json.JSONDecodeError, TypeError):
                    event_data = {"value": raw_data}
                if not isinstance(event_data, dict):
                    event_data = {"value": event_data}
                event_data.setdefault("event_type", event["event_type"] or "phase")
            session_id = event["session_id"] or ""
            phase_logs_by_session.setdefault(session_id, []).append({
                "id": str(event["id"]),
                "phase": event["phase"] or "",
                "summary": event["summary"] or "",
                "data": event_data,
                "speaker": event["speaker"] or "agent",
                "timestamp": event["created_at"] or "",
            })
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["action_items"] = json.loads(d.get("action_items", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["action_items"] = []
            d["phase_logs"] = phase_logs_by_session.get(d.get("session_id", ""), [])
            results.append(d)
        return results

    def truncate_conversation_from(self, conversation_id, session_id):
        """Remove a selected turn and all later turns from a conversation."""
        if not conversation_id or not session_id:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT MIN(id) FROM episodes
                   WHERE conversation_id = ? AND session_id = ?""",
                (conversation_id, session_id),
            ).fetchone()
            cutoff_id = row[0] if row else None
            if cutoff_id is None:
                return 0

            conn.execute(
                """DELETE FROM derivation_chains
                   WHERE episode_id IN (
                     SELECT id FROM episodes
                     WHERE conversation_id = ? AND id >= ?
                   )""",
                (conversation_id, cutoff_id),
            )
            conn.execute(
                """DELETE FROM conversation_events
                   WHERE conversation_id = ?
                     AND session_id IN (
                       SELECT session_id FROM episodes
                       WHERE conversation_id = ? AND id >= ?
                     )""",
                (conversation_id, conversation_id, cutoff_id),
            )
            deleted = conn.execute(
                """DELETE FROM episodes
                   WHERE conversation_id = ? AND id >= ?""",
                (conversation_id, cutoff_id),
            ).rowcount
            conn.commit()
        log.info(
            "episodic_memory.truncated_conversation",
            conversation=conversation_id,
            from_session=session_id,
            deleted=deleted,
        )
        return deleted

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
            conn.execute(
                "DELETE FROM conversation_events WHERE conversation_id = ?",
                (conversation_id,),
            )
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
