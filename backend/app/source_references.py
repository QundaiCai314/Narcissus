from sqlalchemy import select
from .models import SourceVersion


def position(source):
    label = source.get("position") or (f"第 {source['page']} 页" if source.get("page") else "原文片段")
    return "PDF "+label if source.get("page") and source.get("source_type", "pdf") == "pdf" and not label.startswith("PDF") else label


def evidence(db, doc, chunk):
    ver = db.scalar(select(SourceVersion).where(SourceVersion.document_id == doc.id, SourceVersion.version == chunk.version))
    location = chunk.location or {"label": f"第 {chunk.page} 页", "page": chunk.page}
    return {"kind": "document", "document_id": doc.id, "chunk_id": chunk.id,
        "filename": ver.title if ver else doc.filename, "version": chunk.version,
        "warning": ("资料不完整，以下页面未识别：" + ",".join(str(p["page"]) for p in ver.details["failed_pages"])) if ver and ver.details.get("failed_pages") else None,
        "source_type": doc.source_type, "page": chunk.page, "ordinal": chunk.ordinal,
        "source_url": ver.source_url if ver else None, "fetched_at": ver.details.get("fetched_at") if ver else None,
        "location": location, "position": location.get("label", "原文片段"), "text": chunk.text}
