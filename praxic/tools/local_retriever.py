"""
Praxic Agent —— 本地文件检索工具

替代旧的 _read_workspace_files 全读截断逻辑。

双模式：
- "keyword":  BM25 关键词检索（纯 Python，零额外依赖）
- "embedding": BAAI/bge-small-en 语义检索 + BM25 重排序（懒加载，80MB 模型）
- "off":       回退到旧版全读截断

懒索引 + mtime 缓存：仅变更文件重新索引。
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings

log = structlog.get_logger(__name__)

# 可读文本文件扩展名
_TEXT_EXTS = {
    ".txt", ".md", ".py", ".json", ".csv", ".toml",
    ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".log", ".cfg", ".ini", ".xml", ".rst", ".tex", ".c", ".h",
    ".cpp", ".hpp", ".java", ".go", ".rs", ".rb", ".php", ".sql",
    ".sh", ".bat", ".ps1", ".swift", ".kt", ".scala", ".r",
}

# 跳过的目录/文件
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
_SKIP_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock"}
_MAX_FILE_SIZE = 1_000_000  # 1MB
_MAX_FILE_COUNT = 500       # 最多索引 500 个文件


# ═══════════════════════════════════════════════════════════════════
# BM25 纯 Python 实现（约 50 行，零依赖）
# ═══════════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    """简单分词：中文按字 + 英文按词"""
    # 中文：按 CJK 字符拆开，保留英文/数字词
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif ch.isalnum() or ch == "_":
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return [t for t in tokens if len(t) >= 1]


class BM25Retriever:
    """BM25 纯 Python，无外部依赖"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []      # 每个文档的 token 列表
        self._doc_ids: list[str] = []          # 每个文档的 id (path:chunk_idx)
        self._doc_lens: list[int] = []         # 每个文档的长度
        self._avg_dl: float = 0.0
        self._df: dict[str, int] = {}          # 词 → 出现在多少个文档中
        self._built: bool = False

    def index(self, documents: list[tuple[str, str]]):
        """
        构建 BM25 索引。

        Args:
            documents: [(doc_id, text), ...]  doc_id 如 "path/to/file.py:3"
        """
        self._docs.clear()
        self._doc_ids.clear()
        self._doc_lens.clear()
        self._df.clear()

        for doc_id, text in documents:
            tokens = _tokenize(text)
            self._docs.append(tokens)
            self._doc_ids.append(doc_id)
            self._doc_lens.append(len(tokens))
            seen: set[str] = set()
            for t in tokens:
                if t not in seen:
                    self._df[t] = self._df.get(t, 0) + 1
                    seen.add(t)

        n = len(self._docs)
        self._avg_dl = sum(self._doc_lens) / n if n > 0 else 0.0
        self._built = n > 0

    def search(self, query: str, top_k: int = 30) -> list[tuple[str, float]]:
        """
        检索 top-k 文档。

        Returns:
            [(doc_id, score), ...] 按分降序
        """
        if not self._built:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        n = len(self._docs)
        scores: list[float] = [0.0] * n
        idf_cache: dict[str, float] = {}

        for qt in query_tokens:
            df = self._df.get(qt, 0)
            if df == 0:
                continue
            idf = idf_cache.get(qt)
            if idf is None:
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                idf_cache[qt] = idf
            for i, doc_tokens in enumerate(self._docs):
                tf = doc_tokens.count(qt)
                if tf == 0:
                    continue
                dl = self._doc_lens[i]
                score = idf * ((tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self._avg_dl)))
                scores[i] += score

        ranked = sorted(
            [(self._doc_ids[i], scores[i]) for i in range(n) if scores[i] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:top_k]


# ═══════════════════════════════════════════════════════════════════
# LocalRetriever
# ═══════════════════════════════════════════════════════════════════

class LocalRetriever:
    """本地文件检索：BM25 + 可选 Embedding"""

    def __init__(
        self,
        workspace: Path,
        mode: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        max_chunks: int | None = None,
        max_per_file: int | None = None,
    ):
        self.workspace = workspace
        self.mode = mode if mode is not None else settings.local_retrieval_mode
        self.chunk_size = chunk_size if chunk_size is not None else settings.local_retrieval_chunk_size
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.local_retrieval_chunk_overlap
        self.max_chunks = max_chunks if max_chunks is not None else settings.local_retrieval_max_chunks
        self.max_per_file = max_per_file if max_per_file is not None else settings.local_retrieval_max_per_file

        self.bm25 = BM25Retriever()
        self.embedder = None  # 懒加载
        self.cache_dir = settings.data_dir / "embeddings_cache"
        self._index_manifest: dict[str, float] = {}  # path_str → mtime

    # ── Public API ────────────────────────────────────────────

    async def retrieve(self, question: str) -> str:
        """
        检索与问题最相关的本地文件段落。

        Returns:
            Markdown 格式文本，可直接注入 LLM 上下文；无结果返回 ""
        """
        if not self.workspace.exists():
            log.warning("local_retriever.workspace_missing", path=str(self.workspace))
            return ""

        try:
            files = self._collect_files()
            if not files:
                return ""

            chunks = self._chunk_all(files)
            if not chunks:
                return ""

            if self.mode == "embedding":
                try:
                    results = await self._embedding_retrieve(question, chunks)
                except Exception as e:
                    log.warning("local_retriever.embedding_fallback", error=str(e))
                    results = self._keyword_retrieve(question, chunks)
            else:
                results = self._keyword_retrieve(question, chunks)

            if not results:
                return ""

            formatted = self._format_results(results)
            log.info("local_retriever.done", n_chunks=len(chunks), n_results=len(results), mode=self.mode)
            return formatted

        except Exception as e:
            log.error("local_retriever.error", error=str(e), exc_info=True)
            return ""

    # ── File collection ───────────────────────────────────────

    def _collect_files(self) -> list[Path]:
        """收集 workspace 下需要索引的文本文件"""
        files: list[Path] = []
        for path in self.workspace.rglob("*"):
            if len(files) >= _MAX_FILE_COUNT:
                break
            if not path.is_file():
                continue
            if path.stat().st_size > _MAX_FILE_SIZE:
                continue
            # 跳过目录
            if any(p.name in _SKIP_DIRS for p in path.parents):
                continue
            # 跳过锁定文件
            if path.name in _SKIP_FILES:
                continue
            ext = path.suffix.lower()
            if ext not in _TEXT_EXTS and not path.name.lower().startswith("dockerfile"):
                continue
            try:
                # 尝试读取以确认可读
                path.read_text(encoding="utf-8", errors="ignore")
                files.append(path)
            except Exception:
                pass
        return sorted(files)[:_MAX_FILE_COUNT]

    # ── Chunking ──────────────────────────────────────────────

    def _chunk_all(self, files: list[Path]) -> list[tuple[str, str, str]]:
        """
        对所有文件切分段落。

        Returns:
            [(doc_id, text_chunk, source_path_str), ...]
        """
        all_chunks: list[tuple[str, str, str]] = []
        for fp in files:
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, chunk in enumerate(self._chunk_text(content)):
                doc_id = f"{fp.relative_to(self.workspace)}:{i}"
                all_chunks.append((doc_id, chunk, str(fp.relative_to(self.workspace))))
        return all_chunks

    def _chunk_text(self, text: str) -> list[str]:
        """按段落边界切分，优先在空行处断句"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        # 按空行切分
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # 如果当前段太长，进一步按句子边界切
            if len(para) > self.chunk_size * 2:
                if current:
                    chunks.append(current)
                    current = ""
                for sub in self._split_long_paragraph(para):
                    chunks.append(sub)
                continue
            if len(current) + len(para) + 2 <= self.chunk_size:
                if current:
                    current += "\n\n" + para
                else:
                    current = para
            else:
                if current:
                    chunks.append(current)
                current = para

        if current:
            chunks.append(current)

        # 添加重叠：最后 N 个字符复制到下段开头
        if self.chunk_overlap > 0 and len(chunks) > 1:
            overlapped: list[str] = []
            for i, ch in enumerate(chunks):
                if i > 0:
                    prev = chunks[i - 1]
                    overlap = prev[-self.chunk_overlap:] if len(prev) > self.chunk_overlap else prev
                    ch = overlap + "\n" + ch
                overlapped.append(ch)
            return overlapped

        return chunks

    def _split_long_paragraph(self, text: str) -> list[str]:
        """将超长段落按 chunk_size 切分"""
        chunks: list[str] = []
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunk = text[i:i + self.chunk_size].strip()
            if chunk:
                chunks.append(chunk)
        return chunks

    # ── Keyword retrieval ─────────────────────────────────────

    def _keyword_retrieve(self, question: str, chunks: list[tuple[str, str, str]]) -> list[tuple[str, float, str]]:
        """BM25 检索 → top-N（同文件最多 M 个）"""
        docs = [(cid, text) for cid, text, _ in chunks]
        self.bm25.index(docs)
        ranked = self.bm25.search(question, top_k=min(len(docs), 100))
        return self._dedup_per_file(ranked, chunks)

    # ── Embedding retrieval ───────────────────────────────────

    async def _embedding_retrieve(self, question: str, chunks: list[tuple[str, str, str]]) -> list[tuple[str, float, str]]:
        """Embedding 召回 top-30 → BM25 重排序 → 同文件去重"""
        if len(chunks) < 5:
            return self._keyword_retrieve(question, chunks)

        # 懒加载 embedder
        if self.embedder is None:
            await self._load_embedder()

        # 1) Embedding 召回
        texts = [text for _, text, _ in chunks]
        try:
            embeddings = await asyncio.to_thread(self.embedder.encode, texts, show_progress_bar=False)
        except Exception:
            log.warning("local_retriever.encode_failed")
            return self._keyword_retrieve(question, chunks)

        q_emb = await asyncio.to_thread(self.embedder.encode, [question], show_progress_bar=False)
        q_vec = q_emb[0]

        # 点积相似度
        scores = embeddings @ q_vec
        top_k = min(30, len(scores))
        top_indices = scores.argsort()[-top_k:][::-1]

        # 2) BM25 重排序
        candidate_chunks = [chunks[i] for i in top_indices]
        return self._keyword_retrieve(question, candidate_chunks)

    async def _load_embedder(self):
        """懒加载 sentence-transformers 模型"""
        # 在 executor 线程中加载（避免阻塞事件循环）
        def _load():
            try:
                from sentence_transformers import SentenceTransformer
                return SentenceTransformer("BAAI/bge-small-en")
            except Exception as e:
                log.warning("local_retriever.load_embedder_failed", error=str(e))
                raise

        self.embedder = await asyncio.to_thread(_load)
        log.info("local_retriever.embedder_loaded", model="BAAI/bge-small-en")

    # ── Dedup ─────────────────────────────────────────────────

    def _dedup_per_file(
        self,
        ranked: list[tuple[str, float]],
        chunks: list[tuple[str, str, str]],
    ) -> list[tuple[str, float, str]]:
        """每个文件最多保留 max_per_file 个 chunks，总共 max_chunks 个"""
        chunk_map: dict[str, tuple[str, str]] = {cid: (text, src) for cid, text, src in chunks}
        file_counts: dict[str, int] = defaultdict(int)
        results: list[tuple[str, float, str]] = []

        for doc_id, score in ranked:
            src_path = doc_id.rsplit(":", 1)[0]
            if file_counts[src_path] >= self.max_per_file:
                continue
            text_src = chunk_map.get(doc_id)
            if text_src is None:
                continue
            text, src = text_src
            results.append((doc_id, score, text))
            file_counts[src_path] += 1
            if len(results) >= self.max_chunks:
                break

        return results

    # ── Formatting ─────────────────────────────────────────────

    def _format_results(self, results: list[tuple[str, float, str]]) -> str:
        """格式化为 LLM 可用的 Markdown"""
        lines: list[str] = []
        for i, (doc_id, _, text) in enumerate(results):
            src = doc_id.rsplit(":", 1)[0]
            lines.append(f"### [{i+1}] {src}")
            lines.append(text.strip())
            lines.append("")
        return "\n".join(lines)
