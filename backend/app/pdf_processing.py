import io
import re
import unicodedata
from .ocr import LocalOCR, OCRFailure
from pypdf import PdfReader
from .config import settings


class InvalidPDF(Exception):
    pass


def unreadable(text):
    chars = [c for c in text if not c.isspace()]
    bad = sum(c == '\ufffd' or unicodedata.category(c).startswith('C') for c in chars)
    return bool(chars) and bad / len(chars) > 0.03


def has_large_image(page):
    def visit(resources, seen, depth=0):
        if depth > 8:
            return False
        resources = resources.get_object() if hasattr(resources, 'get_object') else resources
        objects = resources.get('/XObject', {})
        objects = objects.get_object() if hasattr(objects, 'get_object') else objects
        for ref in objects.values():
            obj = ref.get_object()
            identity = getattr(ref, 'idnum', id(obj))
            if identity in seen:
                continue
            seen.add(identity)
            if obj.get('/Subtype') == '/Image' and obj.get('/Width', 0) * obj.get('/Height', 0) > 150000:
                return True
            if obj.get('/Subtype') == '/Form' and visit(obj.get('/Resources', {}), seen, depth+1):
                return True
        return False
    return visit(page.get('/Resources', {}), set())


def extract_chunks(data: bytes, diagnostics=None, progress=None):
    s = settings()
    if not data or not data.startswith(b"%PDF-"):
        raise InvalidPDF("文件为空或不是有效的 PDF")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise InvalidPDF(f"文件不能超过 {s.max_upload_mb}MB")
    ocr = None
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(ocr_pages=[], ocr_confidence={}, characters=0)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise InvalidPDF("暂不支持加密 PDF，请移除密码后重新上传")
        count = len(reader.pages)
        if count == 0:
            raise InvalidPDF("PDF 没有页面")
        if count > s.max_pdf_pages:
            raise InvalidPDF(f"PDF 不能超过 {s.max_pdf_pages} 页")
        result, total = [], 0
        for page_no, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            broken = unreadable(text)
            scanned = has_large_image(page) and len(re.sub(r"\s", "", text)) < 80
            if progress:
                progress(page_no, count, 'ocr' if broken or scanned else 'text')
            if broken or scanned:
                if not s.ocr_enabled:
                    raise InvalidPDF(f"第 {page_no} 页需要识别图片文字，当前未开启识别；请启用识别或上传带完整文字层的PDF")
                if ocr is None:
                    ocr = LocalOCR(data)
                text, confidence = ocr.page(page_no)
                diagnostics['ocr_pages'].append(page_no)
                diagnostics['ocr_confidence'][str(page_no)] = confidence
            text = re.sub(r"[ \t]+", " ", text.replace("\x00", "")).strip()
            if unreadable(text):
                raise InvalidPDF(f"第 {page_no} 页文字无法正确读取，请重新导出原件")
            total += len(text)
            if total > s.max_document_chars:
                raise InvalidPDF("PDF 文字量过大，请拆分为较小文件")
            if len(re.sub(r"\s", "", text)) < 5:
                if page.get("/Resources", {}).get("/XObject"):
                    raise InvalidPDF(f"第 {page_no} 页为扫描页或空白图片，未找到可用文字")
                continue
            for ordinal, start in enumerate(range(0, len(text), 700), 1):
                result.append(
                    {
                        "page": page_no,
                        "ordinal": ordinal,
                        "text": text[start : start + 900],
                    }
                )
                if len(result) > s.max_chunks:
                    raise InvalidPDF("资料片段过多，请拆分文件")
        if total < 20 or not result:
            raise InvalidPDF(
                "未找到足够的可提取文字，文件可能为空或是无法辨认的扫描件"
            )
        diagnostics["characters"] = total
        return count, result
    except OCRFailure as error:
        raise InvalidPDF(str(error)) from None
    except InvalidPDF:
        raise
    except Exception:
        raise InvalidPDF("PDF 损坏或无法解析，请重新导出文件") from None

    finally:
        if ocr is not None:
            ocr.close()
