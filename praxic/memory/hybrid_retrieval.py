"""本地记忆的混合检索：中文 BM25 相关性召回 + 短语/时间/置信度重排。

语义记忆与情节记忆过去都用 ``query.split()+SQLite LIKE``：中文长问题通常没有
空格，整句 LIKE 命中率极低。本模块复用 LocalRetriever 已验证的 BM25 中文分词，
在小型 SQLite 记忆库上按需建索引，零新依赖、可确定回退。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable

from ..tools.local_retriever import BM25Retriever


def _timestamp(value) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def rank_records(
    query: str,
    records: Iterable[dict],
    text_of: Callable[[dict], str],
    *,
    limit: int = 5,
    confidence_of: Callable[[dict], float] | None = None,
    time_key: str = "created_at",
) -> list[dict]:
    """按 BM25 相关性检索记录，并以轻量短语/时间/置信度重排。

    只返回有 BM25 命中的记录，避免把不相关的最近记忆伪装成相关知识。
    每条结果补充 ``_retrieval_score`` 与 ``_retrieval_method`` 供遥测/展示使用。
    """
    rows = [dict(r) for r in records]
    if not query or not query.strip() or not rows or limit <= 0:
        return []

    docs: list[tuple[str, str]] = []
    id_to_row: dict[str, dict] = {}
    for i, row in enumerate(rows):
        rid = str(row.get("id", i))
        # id 理论上唯一；异常数据时加序号防止 BM25 doc_id 覆盖
        if rid in id_to_row:
            rid = f"{rid}#{i}"
        text = text_of(row) or ""
        if not text.strip():
            continue
        docs.append((rid, text))
        id_to_row[rid] = row
    if not docs:
        return []

    bm25 = BM25Retriever()
    bm25.index(docs)
    ranked = bm25.search(query, top_k=len(docs))
    if not ranked:
        return []

    max_bm25 = max(score for _, score in ranked) or 1.0
    timestamps = [_timestamp(row.get(time_key, "")) for row in id_to_row.values()]
    lo, hi = min(timestamps, default=0.0), max(timestamps, default=0.0)
    q_norm = " ".join(query.lower().split())
    scored: list[tuple[float, dict]] = []
    for rid, bm25_score in ranked:
        row = dict(id_to_row[rid])
        text = text_of(row)
        relevance = bm25_score / max_bm25
        # 整句/核心短语命中给小幅加分；不覆盖 BM25 主排序。
        phrase_bonus = 0.20 if len(q_norm) >= 4 and q_norm in " ".join(text.lower().split()) else 0.0
        ts = _timestamp(row.get(time_key, ""))
        recency = (ts - lo) / (hi - lo) if hi > lo else 0.5
        try:
            confidence = max(0.0, min(1.0, float(confidence_of(row)))) if confidence_of else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        score = relevance + phrase_bonus + 0.08 * recency + 0.08 * confidence
        row["_retrieval_score"] = round(score, 4)
        row["_retrieval_method"] = "bm25_hybrid"
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]