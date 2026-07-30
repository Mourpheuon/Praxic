"""
Praxic Agent —— 文件加载器

将用户上传的文件（PDF/docx/txt/py/ipynb 等）统一转换为 Markdown 文本，
在调查阶段之前注入认知循环上下文。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

import structlog
from .pdf_converter import PdfConverter

log = structlog.get_logger(__name__)


@dataclass
class FileDocument:
    """单个文件转换后的结构化文档"""
    file_path: str
    file_name: str
    extension: str
    content: str
    char_count: int = 0
    error: str = ""
    metadata: dict = field(default_factory=dict)


class FileLoader:
    """
    文件加载器——根据扩展名选择合适的转换策略，统一输出 Markdown。

    支持类型：
    - 纯文本：.txt .md .py .json .csv 等 → 直接读取，包裹在代码块中
    - PDF/Word/Excel/PPT：通过 markitdown 转换
    - Jupyter：.ipynb → 解析 code + output 单元格

    单文件上限 10MB；所有文件合并后的总字符数上限由构造参数控制。
    """

    TEXT_EXTENSIONS = {
        ".txt", ".md", ".py", ".json", ".csv", ".toml", ".yaml", ".yml",
        ".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".log", ".cfg",
        ".ini", ".xml", ".rst", ".tex", ".c", ".h", ".cpp", ".hpp",
        ".java", ".go", ".rs", ".rb", ".php", ".sql", ".sh", ".bat",
        ".ps1", ".swift", ".kt", ".scala", ".r",
    }

    MARKITDOWN_EXTENSIONS = {".docx", ".xlsx", ".xls", ".pptx"}

    SPECIAL_EXTENSIONS = {".ipynb"}

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, max_total_chars: int = 80000, workspace_dir: str = ""):
        self.max_total_chars = max_total_chars
        self.workspace_dir = workspace_dir
        # PDF 转换器：图片输出到 workspace/_pdf_images/
        pdf_image_dir = os.path.join(workspace_dir, "_pdf_images") if workspace_dir else ""
        self._pdf_converter = PdfConverter(
            enable_ocr=True,
            enable_image_extraction=True,
            image_output_dir=pdf_image_dir or None,
        )

    def load(self, file_paths: list[str]) -> list[FileDocument]:
        """加载并转换文件列表。转换失败的文件 content 为空、error 非空。"""
        docs: list[FileDocument] = []
        total_chars = 0

        for fp in file_paths:
            path = Path(fp)
            if not path.exists():
                docs.append(FileDocument(
                    file_path=fp, file_name=path.name, extension=path.suffix.lower(),
                    content="", error="文件不存在: %s" % fp,
                ))
                continue
            if not path.is_file():
                docs.append(FileDocument(
                    file_path=fp, file_name=path.name, extension=path.suffix.lower(),
                    content="", error="不是文件: %s" % fp,
                ))
                continue

            fsize = path.stat().st_size
            if fsize > self.MAX_FILE_SIZE:
                docs.append(FileDocument(
                    file_path=fp, file_name=path.name, extension=path.suffix.lower(),
                    content="", error="文件过大: %d bytes (max %d)" % (fsize, self.MAX_FILE_SIZE),
                ))
                continue

            ext = path.suffix.lower()
            doc = self._convert(path, ext, fsize)

            if total_chars + doc.char_count > self.max_total_chars:
                truncate_to = self.max_total_chars - total_chars
                if truncate_to <= 0:
                    doc = FileDocument(
                        file_path=fp, file_name=path.name, extension=ext,
                        content="", char_count=0,
                        error="已达总字符数上限 %d，跳过此文件" % self.max_total_chars,
                    )
                else:
                    doc.content = doc.content[:truncate_to] + "\n\n[内容截断——已达总字符数上限]"
                    doc.char_count = len(doc.content)

            total_chars += doc.char_count
            docs.append(doc)

        log.info("file_loader.done", n_files=len(file_paths),
                 n_success=sum(1 for d in docs if not d.error), total_chars=total_chars)
        return docs

    def _convert(self, path: Path, ext: str, fsize: int) -> FileDocument:
        try:
            if ext in self.TEXT_EXTENSIONS:
                return self._load_text(path)
            elif ext == ".pdf":
                return self._load_pdf(path)
            elif ext in self.MARKITDOWN_EXTENSIONS:
                return self._load_via_markitdown(path, ext)
            elif ext == ".ipynb":
                return self._load_ipynb(path)
            else:
                return self._load_text(path)
        except Exception as e:
            log.warning("file_loader.convert_error", path=str(path), error=str(e))
            return FileDocument(
                file_path=str(path), file_name=path.name, extension=ext,
                content="", char_count=0, error="转换失败: %s" % e,
            )

    def _load_pdf(self, path: Path) -> FileDocument:
        """PDF 专用转换——多级回退 + OCR + 图片提取。"""
        pdf_result = self._pdf_converter.convert(str(path), path.name)
        if pdf_result.error and not pdf_result.text:
            return FileDocument(
                file_path=str(path), file_name=path.name, extension=".pdf",
                content="", char_count=0,
                error=pdf_result.error,
            )
        md = pdf_result.text
        if pdf_result.warnings:
            md += "\n\n### 处理备注\n"
            for w in pdf_result.warnings:
                md += f"- {w}\n"
        meta = pdf_result.metadata.copy() if pdf_result.metadata else {}
        meta["extraction_method"] = pdf_result.extraction_method
        meta["images_extracted"] = pdf_result.images_extracted
        meta["has_scanned_pages"] = pdf_result.has_scanned_pages
        return FileDocument(
            file_path=str(path), file_name=path.name, extension=".pdf",
            content=md, char_count=len(md),
            metadata=meta,
        )

    def _load_text(self, path: Path) -> FileDocument:
        content = path.read_text(encoding="utf-8", errors="replace")
        lang = self._lang_for_ext(path.suffix.lstrip("."))
        md = "## 文件：%s\n\n```%s\n%s\n```\n" % (path.name, lang, content)
        return FileDocument(
            file_path=str(path), file_name=path.name, extension=path.suffix.lower(),
            content=md, char_count=len(md),
            metadata={"original_size": path.stat().st_size, "format": "text"},
        )

    def _load_via_markitdown(self, path: Path, ext: str) -> FileDocument:
        try:
            from markitdown import MarkItDown
        except ImportError:
            log.warning("file_loader.markitdown_not_installed", path=str(path))
            return FileDocument(
                file_path=str(path), file_name=path.name, extension=ext,
                content="", char_count=0,
                error="markitdown 未安装——无法解析此文件类型。请运行: pip install \"markitdown[all]\"",
            )
        try:
            result = MarkItDown().convert(str(path))
            text = result.text_content or ""
        except Exception as e:
            log.warning("file_loader.markitdown_convert_failed", path=str(path), error=str(e))
            return FileDocument(
                file_path=str(path), file_name=path.name, extension=ext,
                content="", char_count=0,
                error="markitdown 转换失败: %s（可能缺少该格式的依赖，试 pip install \"markitdown[all]\"）" % e,
            )
        if not text.strip():
            return FileDocument(
                file_path=str(path), file_name=path.name, extension=ext,
                content="", char_count=0,
                error="文件可能为空或格式不支持。请确保已安装 markitdown[all]。",
            )
        md = "## 文件：%s\n\n%s\n" % (path.name, text)
        return FileDocument(
            file_path=str(path), file_name=path.name, extension=ext,
            content=md, char_count=len(md),
            metadata={"original_size": path.stat().st_size, "format": ext.lstrip(".")},
        )

    def _load_ipynb(self, path: Path) -> FileDocument:
        import json
        nb = json.loads(path.read_text(encoding="utf-8"))
        parts = ["## Notebook: %s\n" % path.name]
        for i, cell in enumerate(nb.get("cells", [])):
            ctype = cell.get("cell_type")
            if ctype == "code":
                src = "".join(cell.get("source", []))
                parts.append("### Cell [%d] (code)\n\n```python\n%s\n```\n" % (i + 1, src))
                for output in cell.get("outputs", []):
                    otype = output.get("output_type")
                    if otype == "stream":
                        text = "".join(output.get("text", []))
                        if text.strip():
                            parts.append("**Output:**\n```\n%s\n```\n" % text[:2000])
                    elif otype in ("execute_result", "display_data"):
                        td = output.get("data", {}).get("text/plain", [])
                        text = "".join(td) if isinstance(td, list) else str(td)
                        if text.strip():
                            parts.append("**Result:**\n```\n%s\n```\n" % text[:2000])
            elif ctype == "markdown":
                parts.append("".join(cell.get("source", [])) + "\n")
        md = "\n".join(parts)
        return FileDocument(
            file_path=str(path), file_name=path.name, extension=".ipynb",
            content=md, char_count=len(md),
            metadata={"format": "ipynb", "cell_count": len(nb.get("cells", []))},
        )

    @staticmethod
    def _lang_for_ext(ext: str) -> str:
        _map = {
            "py": "python", "js": "javascript", "ts": "typescript",
            "jsx": "jsx", "tsx": "tsx", "json": "json", "yaml": "yaml",
            "yml": "yaml", "html": "html", "css": "css", "sql": "sql",
            "sh": "bash", "bat": "batch", "ps1": "powershell",
            "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp",
            "java": "java", "go": "go", "rs": "rust", "rb": "ruby",
            "toml": "toml", "xml": "xml", "rst": "rst", "tex": "latex",
        }
        return _map.get(ext, "")

    @staticmethod
    def format_for_context(docs: list[FileDocument]) -> str:
        """将 FileDocument 列表格式化为可注入认知循环上下文的文本块。"""
        parts: list[str] = []
        success_docs = [d for d in docs if not d.error and d.content]
        error_docs = [d for d in docs if d.error]

        if success_docs:
            parts.append("## 用户上传文件（%d 个）\n" % len(success_docs))
            for i, doc in enumerate(success_docs, 1):
                parts.append("### %d. %s" % (i, doc.file_name))
                if doc.metadata:
                    meta_str = ", ".join("%s: %s" % (k, v) for k, v in doc.metadata.items())
                    parts.append("*(%s)*" % meta_str)
                parts.append("")
                parts.append(doc.content)
                parts.append("---\n")

        if error_docs:
            parts.append("## 以下文件未能加载\n")
            for doc in error_docs:
                parts.append("- **%s**: %s" % (doc.file_name, doc.error))

        return "\n".join(parts)
