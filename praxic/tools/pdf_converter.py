"""
Praxic Agent —— PDF 转换器
多级回退策略：pymupdf 文本提取 -> markitdown -> OCR 扫描件 -> 图片提取
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os
import structlog

log = structlog.get_logger(__name__)


@dataclass
class PdfResult:
    text: str
    char_count: int = 0
    page_count: int = 0
    extraction_method: str = ""
    has_scanned_pages: bool = False
    images_extracted: int = 0
    image_paths: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


class PdfConverter:
    """
    PDF 转换器——多级回退策略：

    Level 1: pymupdf 文本提取（最快，对嵌入字体的 PDF 效果好）
    Level 2: markitdown（pdfplumber+pdfminer，表格检测优）
    Level 3: OCR（pymupdf 渲染页面为图像 -> tesseract，扫描件专用）
    Level 4: 最低限度——仅提取图片 + 元数据

    每一页独立判断：文本页走 Level 1/2，扫描页走 Level 3，
    混合 PDF 自动分页处理。
    """

    SCANNED_PAGE_THRESHOLD = 100
    OCR_LANG = "chi_sim+eng"

    def __init__(
        self,
        enable_ocr: bool = True,
        enable_image_extraction: bool = True,
        image_output_dir: str | None = None,
        ocr_dpi: int = 200,
    ):
        self.enable_ocr = enable_ocr
        self.enable_image_extraction = enable_image_extraction
        self.image_output_dir = image_output_dir
        self.ocr_dpi = ocr_dpi

    def convert(self, path: str | Path, file_name: str = "") -> PdfResult:
        """主入口：转换 PDF 文件。返回 PdfResult。"""
        path = Path(path)
        if not path.exists():
            return PdfResult(text="", error=f"文件不存在: {path}")

        name = file_name or path.name
        result = PdfResult(text="", page_count=0)

        try:
            import pymupdf
        except ImportError:
            log.warning("pdf_converter.pymupdf_not_installed")
            return self._fallback_markitdown_only(path, name)

        doc = None
        try:
            doc = pymupdf.open(str(path))
            result.page_count = doc.page_count

            if doc.page_count == 0:
                result.error = "PDF 页面数为 0"
                return result

            # 图片提取（全量，不依赖文本提取结果）
            if self.enable_image_extraction:
                image_paths = self._extract_images(doc, name, path)
                result.images_extracted = len(image_paths)
                result.image_paths = image_paths

            # 分页处理
            page_results = []
            scanned_page_indices = []

            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                page_text = page.get_text("text").strip()
                char_count = len(page_text)

                if char_count < self.SCANNED_PAGE_THRESHOLD:
                    scanned_page_indices.append(page_idx)
                    if self.enable_ocr:
                        ocr_text = self._ocr_page(page, page_idx, doc)
                        if ocr_text.strip():
                            page_results.append({"page": page_idx + 1, "text": ocr_text, "method": "ocr"})
                            continue
                    page_results.append({"page": page_idx + 1, "text": page_text, "method": "pymupdf (low text)"})
                else:
                    page_results.append({"page": page_idx + 1, "text": page_text, "method": "pymupdf"})


            # 全文档文本总量极低时尝试 markitdown 回退
            total_pymupdf_chars = sum(len(p["text"]) for p in page_results)
            total_pages_with_text = sum(1 for p in page_results if len(p["text"]) > self.SCANNED_PAGE_THRESHOLD)

            if total_pymupdf_chars < 200 and total_pages_with_text == 0:
                markitdown_result = self._try_markitdown(path)
                if markitdown_result and len(markitdown_result) > total_pymupdf_chars:
                    result.text = markitdown_result
                    result.extraction_method = "markitdown (pymupdf fallback)"
                    result.char_count = len(markitdown_result)
                else:
                    result.text = self._build_markdown(name, page_results, result.image_paths)
                    result.extraction_method = "pymupdf+ocr (low text)"
                    result.char_count = total_pymupdf_chars
            else:
                result.text = self._build_markdown(name, page_results, result.image_paths)
                result.extraction_method = "pymupdf" + ("+ocr" if scanned_page_indices else "")
                result.char_count = total_pymupdf_chars

            result.has_scanned_pages = len(scanned_page_indices) > 0

            # 元数据
            meta = doc.metadata or {}
            result.metadata = {
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "subject": meta.get("subject", ""),
                "page_count": doc.page_count,
                "format": "pdf",
                "file_size": path.stat().st_size,
                "scanned_pages": scanned_page_indices,
                "extraction_method": result.extraction_method,
                "toc": self._extract_toc(doc),
            }

        except Exception as e:
            log.warning("pdf_converter.pymupdf_error", path=str(path), error=str(e))
            fallback = self._fallback_markitdown_only(path, name)
            fallback.warnings.insert(0, f"pymupdf 打开失败，已回退 markitdown: {e}")
            return fallback
        finally:
            if doc is not None and hasattr(doc, "close"):
                try:
                    doc.close()
                except Exception:
                    pass
            elif doc is not None:
                try:
                    pymupdf = __import__("pymupdf")
                    if hasattr(doc, "save"):
                        pass  # not a real document instance
                except Exception:
                    pass

        if result.has_scanned_pages and not self.enable_ocr:
            result.warnings.append(
                f"检测到 {len(scanned_page_indices)} 个疑似扫描页（页码：{scanned_page_indices[:5]}...），"
                "OCR 未启用，这些页面的文本可能不完整。"
            )

        return result

    def _ocr_page(self, page, page_idx: int, doc) -> str:
        """对单个页面执行 OCR：pymupdf 渲染为图像 -> tesseract。"""
        try:
            import subprocess
            subprocess.run(["tesseract", "--version"], capture_output=True, check=True)
        except Exception:
            log.warning("pdf_converter.tesseract_unavailable")
            return ""

        try:
            import pymupdf
            mat = pymupdf.Matrix(self.ocr_dpi / 72, self.ocr_dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
                pix.save(tmp_path)

            try:
                from PIL import Image
                import pytesseract
                img = Image.open(tmp_path)
                text = pytesseract.image_to_string(img, lang=self.OCR_LANG)
                return text
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            log.warning("pdf_converter.ocr_page_failed", page=page_idx + 1, error=str(e))
            return ""

    def _extract_images(self, doc, file_name: str, pdf_path: Path) -> list[str]:
        """从 PDF 中提取所有嵌入图片，保存到 image_output_dir。"""
        image_paths = []
        try:
            output_dir = self.image_output_dir
            if not output_dir:
                output_dir = str(pdf_path.parent / "_pdf_images")
            os.makedirs(output_dir, exist_ok=True)

            base_name = Path(file_name).stem
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                image_list = page.get_images(full=True)
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        img_filename = f"{base_name}_p{page_idx+1}_img{img_idx+1}.{image_ext}"
                        img_path = os.path.join(output_dir, img_filename)
                        if len(image_bytes) < 1024:
                            continue
                        with open(img_path, "wb") as f:
                            f.write(image_bytes)
                        image_paths.append(img_path)
                    except Exception as e:
                        log.debug("pdf_converter.image_extract_failed",
                                  page=page_idx + 1, img=img_idx, error=str(e))
        except Exception as e:
            log.warning("pdf_converter.image_extraction_error", error=str(e))
        return image_paths

    def _extract_toc(self, doc) -> list[dict]:
        try:
            toc = doc.get_toc()
            if toc:
                return [
                    {"level": item[0], "title": item[1], "page": item[2]}
                    for item in toc[:50]
                ]
        except Exception:
            pass
        return []

    def _build_markdown(self, file_name: str, page_results: list[dict], image_paths: list[str]) -> str:
        parts = [f"## PDF: {file_name}\n"]
        if image_paths:
            parts.append("### 提取的图片\n")
            for img_path in image_paths[:20]:
                img_name = os.path.basename(img_path)
                parts.append(f"![{img_name}]({img_path})\n")
            parts.append("")
        methods = set(p.get("method", "") for p in page_results)
        if "ocr" in methods:
            parts.append("*（部分页面通过 OCR 识别，可能有错字）*\n")
        current_page = 0
        buffer = []
        for pr in page_results:
            page_num = pr["page"]
            text = pr["text"].strip()
            if not text:
                continue
            if current_page > 0 and page_num > current_page + 1:
                buffer.append(f"\n<!-- page break: {current_page} -> {page_num} -->\n")
            buffer.append(f"### 第 {page_num} 页\n\n{text}\n")
            current_page = page_num
        parts.extend(buffer)
        return "\n".join(parts)

    def _try_markitdown(self, path: Path) -> str:
        try:
            from markitdown import MarkItDown
            result = MarkItDown().convert(str(path))
            return result.text_content or ""
        except Exception:
            return ""

    def _fallback_markitdown_only(self, path: Path, file_name: str) -> PdfResult:
        result = PdfResult(text="", extraction_method="markitdown (fallback)")
        try:
            text = self._try_markitdown(path)
            if text.strip():
                result.text = f"## PDF: {file_name}\n\n{text}"
                result.char_count = len(result.text)
            else:
                result.error = "所有 PDF 提取方法均失败——pymupdf 和 markitdown 都未能提取文本"
        except Exception as e:
            result.error = f"PDF 转换完全失败: {e}"
        return result
