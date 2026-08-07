"""
Praxic Agent —— PDF 文本提取工具（只读）

包装 PdfConverter 的多级回退（pymupdf → markitdown → OCR → 图片提取），
对工作区内 PDF 提取文本。observe 类，全权限档自动放行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .base import ActionKind, BaseTool, ToolResult, ToolStatus
from .filesystem import _safe_path
from .pdf_converter import PdfConverter

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"


class PdfExtractTool(BaseTool):
    """提取 PDF 文件文本（只读）"""

    name = "pdf_extract"
    category = "data"
    group = "document"
    description = "提取工作区内 PDF 文件的文本内容（支持扫描件 OCR）"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "path": {"type": "string", "description": "PDF 路径（相对工作区）"},
        "max_chars": {"type": "number", "default": 20000, "description": "返回文本上限"},
        "enable_ocr": {"type": "boolean", "default": False, "description": "扫描页是否尝试 OCR（慢）"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._converter = PdfConverter(enable_ocr=False, enable_image_extraction=False)

    async def run(self, path: str, max_chars: int = 20000, enable_ocr: bool = False) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists() or not target.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"PDF 不存在：{path}")
            if target.suffix.lower() != ".pdf":
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"不是 PDF 文件：{path}")
            converter = self._converter
            if enable_ocr and not converter.enable_ocr:
                converter = PdfConverter(enable_ocr=True, enable_image_extraction=False)
            result = converter.convert(str(target))
            if result.error:
                return ToolResult(status=ToolStatus.ERROR, content="", error=result.error)
            text = result.text
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n...[文本超 {max_chars} 字符已截断]"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=text,
                data={
                    "char_count": result.char_count,
                    "page_count": result.page_count,
                    "extraction_method": result.extraction_method,
                    "has_scanned_pages": result.has_scanned_pages,
                    "warnings": result.warnings[:5],
                },
                metadata={
                    "page_count": result.page_count,
                    "method": result.extraction_method,
                    "char_count": result.char_count,
                },
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"PDF 提取失败：{e}")
