"""
Praxic Agent —— 网页全文抓取工具

双引擎：
1. GitHub 仓库首页 → raw.githubusercontent.com README.md
2. 其他网页 → httpx GET → trafilatura 提取正文 → fallback bs4.get_text()

所有参数从 config.py 读取，不硬编码。
"""
from __future__ import annotations

import asyncio
import re
import structlog
from typing import Optional

import httpx

from ..config import settings

log = structlog.get_logger(__name__)

_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)(?:/)?$",
    re.IGNORECASE,
)

# 常见非文本 Content-Type 前缀
_SKIP_CONTENT_TYPES = (
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "application/pdf",
    "image/",
    "video/",
    "audio/",
)


def _is_github_repo_homepage(url: str) -> bool:
    """检查 URL 是否为 GitHub 仓库首页（不含子路径如 /blob/ /tree/ 等）"""
    return bool(_GITHUB_REPO_RE.match(url))


def _extract_text_from_html(html: str, url: str) -> str:
    """trafilatura 提取正文，失败时 fallback 到 bs4"""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if text and len(text.strip()) > 100:
            return text.strip()
    except Exception:
        pass

    # Fallback: BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # 移除 script/style/nav/footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # 压缩连续空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +", " ", text)
        return text.strip()
    except Exception:
        pass

    return ""


class WebFetchTool:
    """并发抓取 URL 全文，提取清洗后的正文"""

    def __init__(
        self,
        max_urls: int | None = None,
        max_chars_per_page: int | None = None,
        timeout: float | None = None,
        min_score: float | None = None,
        max_total_chars: int | None = None,
    ):
        """所有参数从 config 读取，也可显式传入覆盖"""
        self.max_urls = max_urls if max_urls is not None else settings.web_fetch_max_urls
        self.max_chars_per_page = max_chars_per_page if max_chars_per_page is not None else settings.web_fetch_max_chars_per_page
        self.timeout = timeout if timeout is not None else settings.web_fetch_timeout
        self.min_score = min_score if min_score is not None else settings.web_fetch_min_score
        self.max_total_chars = max_total_chars if max_total_chars is not None else settings.web_fetch_max_total_chars

    async def fetch_urls(self, url_score_pairs: list[tuple[str, float]]) -> list[dict]:
        """
        并发抓取 URL 全文。

        Args:
            url_score_pairs: [(url, score), ...]，score 来自 Tavily 相关性评分

        Returns:
            [{"url": str, "title": str, "text": str, "fetched": bool, "error": str}, ...]
        """
        # 1. 筛选：按评分过滤 + 去重 + 截断
        seen: set[str] = set()
        candidates: list[tuple[str, float]] = []
        for url, score in url_score_pairs:
            if not url:
                continue
            url = url.strip()
            if url in seen:
                continue
            if score < self.min_score:
                continue
            seen.add(url)
            candidates.append((url, score))

        # 按评分降序，取前 N
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[: self.max_urls]

        if not candidates:
            log.info("web_fetch.no_candidates")
            return []

        log.info("web_fetch.start", n_candidates=len(candidates))

        # 2. 并发抓取
        tasks = [self._fetch_one(url, score) for url, score in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        safe: list[dict] = []
        for r in results:
            if isinstance(r, dict):
                safe.append(r)
            else:
                safe.append({
                    "url": "",
                    "title": "",
                    "text": "",
                    "fetched": False,
                    "error": str(r),
                })

        n_fetched = sum(1 for r in safe if r["fetched"])
        log.info("web_fetch.done", n_total=len(safe), n_fetched=n_fetched)
        return safe

    async def _fetch_one(self, url: str, score: float) -> dict:
        """抓取单个 URL（支持 GitHub 仓库首页特殊处理）"""
        base_result = {"url": url, "title": "", "text": "", "fetched": False, "error": ""}

        # GitHub 仓库首页 → 直接取 README.md
        if _is_github_repo_homepage(url):
            return await self._fetch_github_readme(url, base_result)

        # 普通网页
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; PraxicBot/0.1; +https://praxic.ai)",
                        "Accept": "text/html,application/xhtml+xml,*/*",
                    },
                    follow_redirects=True,
                )

            if resp.status_code != 200:
                base_result["error"] = f"HTTP {resp.status_code}"
                return base_result

            content_type = resp.headers.get("content-type", "")
            if any(content_type.startswith(skip) for skip in _SKIP_CONTENT_TYPES):
                base_result["error"] = f"non-text content-type: {content_type}"
                return base_result

            html = resp.text
            if not html or len(html) < 50:
                base_result["error"] = "empty or too-short response"
                return base_result

            text = _extract_text_from_html(html, url)
            if not text:
                base_result["error"] = "text extraction produced empty result"
                return base_result

            # 提取标题
            title = ""
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                t = soup.find("title")
                if t:
                    title = t.get_text(strip=True)[:200]
            except Exception:
                pass

            # 截断
            if len(text) > self.max_chars_per_page:
                text = text[:self.max_chars_per_page]

            base_result["fetched"] = True
            base_result["title"] = title
            base_result["text"] = text
            return base_result

        except asyncio.TimeoutError:
            base_result["error"] = "timeout"
            return base_result
        except httpx.HTTPError as e:
            base_result["error"] = f"http error: {e}"
            return base_result
        except Exception as e:
            base_result["error"] = f"unexpected: {e}"
            return base_result

    async def _fetch_github_readme(self, url: str, base_result: dict) -> dict:
        """GitHub 仓库首页 → 取 raw.githubusercontent.com README.md"""
        m = _GITHUB_REPO_RE.match(url)
        if not m:
            return base_result
        owner, repo = m.group(1), m.group(2)

        # 尝试 main → master 分支
        for branch in ("main", "master"):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(raw_url, follow_redirects=True)
                if resp.status_code == 200 and resp.text:
                    text = resp.text.strip()
                    # 提取一级标题作为 title
                    title = ""
                    h1 = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
                    if h1:
                        title = h1.group(1)
                    else:
                        title = f"{owner}/{repo}"
                    if len(text) > self.max_chars_per_page:
                        text = text[:self.max_chars_per_page]
                    base_result["fetched"] = True
                    base_result["title"] = title
                    base_result["text"] = text
                    base_result["url"] = raw_url
                    return base_result
            except Exception:
                continue

        # Fallback: GitHub API（无认证 60次/小时，够用）
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    api_url,
                    headers={
                        "User-Agent": "PraxicBot/0.1",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
            if resp.status_code == 200:
                import base64
                data = resp.json()
                content = data.get("content", "")
                if content:
                    text = base64.b64decode(content).decode("utf-8", errors="replace")
                    if len(text) > self.max_chars_per_page:
                        text = text[:self.max_chars_per_page]
                    base_result["fetched"] = True
                    base_result["title"] = f"{owner}/{repo}"
                    base_result["text"] = text
                    return base_result
        except Exception:
            pass

        base_result["error"] = "GitHub README: all branches and API failed"
        return base_result

    @staticmethod
    def format_for_llm(fetched: list[dict]) -> str:
        """
        将抓取结果格式化为 LLM 可用的 Markdown。

        按 fetched 状态分组，成功的在前。受 max_total_chars 限制。
        """
        if not fetched:
            return ""

        max_total = settings.web_fetch_max_total_chars
        parts: list[str] = []
        total = 0

        # 成功的
        for i, r in enumerate(fetched):
            if not r["fetched"] or not r["text"]:
                continue
            header = f"### 全文 [{i+1}] {r['title'] or r['url']}"
            source = r['url'] if r['url'] else "(unknown)"
            block = f"{header}\n> 来源: {source}\n\n{r['text'].strip()}"
            if total + len(block) <= max_total:
                parts.append(block)
                total += len(block)
            else:
                remaining = max_total - total
                if remaining > 200:
                    parts.append(block[:remaining] + "\n\n[截断]")
                break

        # 失败的（简述）
        failed = [r for r in fetched if not r["fetched"]]
        if failed and total < max_total:
            failures = "\n".join(
                f"- {r['url']}: {r.get('error', 'unknown')}" for r in failed[:10]
            )
            note = f"### 抓取失败的 URL\n{failures}"
            if total + len(note) <= max_total:
                parts.append(note)

        return "\n\n".join(parts)
