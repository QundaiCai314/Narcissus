"""Bounded parsers produce ordered evidence units, never model-authored locations."""
import hashlib
import io
import re
import zipfile
from .config import settings
from .pdf_processing import InvalidPDF, unreadable, has_large_image
from .ocr import LocalOCR, OCRFailure


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def decode_text(data):
    encodings = ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    for encoding in encodings:
        try:
            value = data.decode(encoding, errors="strict")
            # Reject binary controls, replacement characters and suspicious private-use text.
            if unreadable(value) or "\ufffd" in value or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ue000-\uf8ff]", value):
                continue
            return value, encoding
        except UnicodeError:
            pass
    raise InvalidPDF("无法可靠读取中文编码，请将文件另存为 UTF-8 后重试")


def unit(text, number, label, **location):
    return {"id": f"u{number:06}", "text": text.strip(), "location": {
        "block_id": f"u{number:06}", "label": label, **location}}


def text_units(text, markdown=False):
    if not text.strip() or len(text) > settings().max_document_chars:
        raise InvalidPDF(f"正文不能为空，且不能超过 {settings().max_document_chars} 字")
    result, headings = [], []
    for line, value in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if not value.strip():
            continue
        match = re.match(r"^(#{1,6})\s+(.+)", value) if markdown else None
        if match:
            depth = len(match[1])
            headings = headings[:depth-1] + [match[2]]
        result.append(unit(value, len(result)+1, f"第 {line} 行", line=line,
                           heading=" / ".join(headings), kind="heading" if match else "paragraph"))
    return result


def docx_units(data):
    from docx import Document as WordDocument
    from docx.table import Table
    warnings = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) > 2000 or sum(f.file_size for f in files) > settings().max_unpacked_mb*1024*1024:
                raise InvalidPDF("Word 解压后过大，请拆分文档")
            if any(f.flag_bits & 1 for f in files) or "word/document.xml" not in archive.namelist():
                raise InvalidPDF("文件不是可读取的 DOCX，或已加密")
            for f in files:
                if f.filename.endswith((".xml", ".rels")):
                    raw = archive.read(f)
                    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
                        raise InvalidPDF("Word 包含不支持的 XML 声明")
            xml = archive.read("word/document.xml")
            if b"oMath" in xml:
                warnings.append("文档包含复杂公式，公式未识别，请核对原件")
            if "word/comments.xml" in archive.namelist():
                warnings.append("批注不参与资料正文")
            if b"w:txbxContent" in xml or b"w:altChunk" in xml:
                warnings.append("文本框或嵌入内容未完整提取，请核对原件")
        doc = WordDocument(io.BytesIO(data))
        result, headings, paragraph, table = [], [], 0, 0
        for item in doc.iter_inner_content():
            if isinstance(item, Table):
                table += 1
                for row_no, row in enumerate(item.rows, 1):
                    text = " | ".join(cell.text for cell in row.cells)
                    if text.strip(" |"):
                        result.append(unit(text, len(result)+1, f"表格 {table} · 第 {row_no} 行",
                            table=table, row=row_no, heading=" / ".join(headings), kind="table"))
                    if any(cell.tables for cell in row.cells):
                        raise InvalidPDF("暂不支持嵌套表格，请先转为普通表格或粘贴正文")
            else:
                paragraph += 1
                text = item.text.strip()
                if not text:
                    continue
                style = item.style.name if item.style else ""
                match = re.match(r"(?:Heading|标题)\s*(\d)", style, re.I)
                if match:
                    headings = headings[:int(match[1])-1] + [text]
                numbered = item._p.pPr is not None and item._p.pPr.numPr is not None
                result.append(unit(text, len(result)+1, f"第 {paragraph} 段",
                    paragraph=paragraph, heading=" / ".join(headings),
                    kind="heading" if match else "list" if numbered or "List" in style else "paragraph"))
        return result, {"method": "docx", "warnings": warnings}
    except InvalidPDF:
        raise
    except Exception:
        raise InvalidPDF("Word 损坏或格式不支持，请使用 DOCX，旧版 DOC 暂不支持") from None


def parse_file(source_type, data, progress=None, cached=None):
    info = {"method": source_type, "warnings": [], "failed_pages": [], "ocr_pages": [], "ocr_confidence": {}}
    if source_type in ("text", "markdown", "paste"):
        value, encoding = decode_text(data)
        info["encoding"] = encoding
        return text_units(value, source_type == "markdown"), info
    if source_type == "docx":
        return docx_units(data)
    if source_type not in ("pdf", "image"):
        raise InvalidPDF("不支持该来源格式")
    from pypdf import PdfReader
    ocr = None
    units = []
    try:
        if source_type == "pdf":
            if not data.startswith(b"%PDF-"):
                raise InvalidPDF("不是有效的 PDF 文件")
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise InvalidPDF("暂不支持加密 PDF，请移除密码")
            pages = reader.pages
            if not 1 <= len(pages) <= settings().max_pdf_pages:
                raise InvalidPDF(f"PDF 页数必须在 1 至 {settings().max_pdf_pages} 页之间")
        else:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG") or image.width * image.height > settings().max_image_pixels:
                    raise InvalidPDF("仅支持 PNG/JPG，且图片尺寸超过上限时需要缩小")
                image.verify()
            pages = [None]
        info["pages"] = len(pages) if source_type == "pdf" else None
        previous = {u["location"].get("page", u["location"].get("image")): u for u in (cached or [])}
        for number, page in enumerate(pages, 1):
            if number in previous:
                units.append(previous[number])
                if previous[number].get("ocr"):
                    info["ocr_pages"].append(number)
                    if "confidence" in previous[number]:
                        info["ocr_confidence"][str(number)] = previous[number]["confidence"]
                continue
            try:
                text = (page.extract_text() or "") if page is not None else ""
                needs_ocr = page is None or unreadable(text) or (len(re.sub(r"\s", "", text)) < 80 and has_large_image(page))
                if progress:
                    progress(number, len(pages), "ocr" if needs_ocr else "text")
                confidence = None
                if needs_ocr:
                    if not settings().ocr_enabled:
                        raise OCRFailure("图片文字识别未开启")
                    if ocr is None:
                        ocr = LocalOCR(data if source_type == "pdf" else None)
                    text, confidence = ocr.page(number) if page is not None else ocr.image(data)
                    info["ocr_pages"].append(number)
                    info["ocr_confidence"][str(number)] = confidence
                if unreadable(text):
                    raise OCRFailure("文字不可辨认，请核对原件")
                if len(text.strip()) < 5:
                    if page is not None and not has_large_image(page):
                        continue
                    raise OCRFailure("未识别出正文，请提供清晰原件")
                u = unit(text, number, f"第 {number} 页" if page is not None else "图片 1",
                         **({"page": number} if page is not None else {"image": 1}))
                u["ocr"] = needs_ocr
                if confidence is not None:
                    u["confidence"] = confidence
                    if confidence < 80:
                        info["warnings"].append(f"第 {number} 页识别质量较低，请核对并修正")
                units.append(u)
            except OCRFailure as exc:
                info["failed_pages"].append({"page": number, "error": str(exc)})
        if info["ocr_pages"]:
            info["warnings"].append("图片识别可能误读数字、公式与专有名词，请对照原件核对")
        return units, info
    except InvalidPDF:
        raise
    except Exception:
        raise InvalidPDF("原件损坏或无法解析，请重新导出") from None
    finally:
        if ocr:
            ocr.close()


def make_chunks(units):
    if sum(len(u["text"]) for u in units) > settings().max_document_chars:
        raise InvalidPDF("正文过长，请拆分资料")
    result = []
    for u in units:
        for start in range(0, len(u["text"]), 700):
            result.append({"page": u["location"].get("page"), "ordinal": len(result)+1,
                "text": u["text"][start:start+900], "location": dict(u["location"], offset=start)})
            if len(result) > settings().max_chunks:
                raise InvalidPDF("资料片段过多，请拆分资料")
    if sum(len(p["text"]) for p in result) < 20:
        raise InvalidPDF("未找到足够正文，请补充至少 20 字可核对内容")
    return result
