"""Owned sources, candidate edits and immutable historical previews."""
import re
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, UploadFile, File, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from .db import db_session
from .models import Document, SourceVersion, Chunk, Job, now, uid
from .security import current_user, rate_limit
from .config import settings
from .errors import fail
from . import access, storage
from .tasks import create_job, tombstone
from .source_jobs import version_row, duplicate
from .source_parsing import digest, text_units, make_chunks
from .pdf_processing import InvalidPDF

router = APIRouter(tags=["资料"])
EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".txt": "text", ".md": "markdown", ".markdown": "markdown", ".png": "image", ".jpg": "image", ".jpeg": "image"}
MIMES = {"pdf": "application/pdf", "image": "image/png", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text": "text/plain", "markdown": "text/plain", "paste": "text/plain", "web": "text/plain"}


def serialize(doc, db=None, ver_map=None, job_map=None):
    result = {k: getattr(doc, k) for k in ("id", "notebook_id", "filename", "size", "pages", "status", "error", "created_at", "source_type")}
    result["generation"] = doc.active_version or doc.generation
    result["latest_version"] = doc.generation
    if db is not None or ver_map is not None:
        ver = ver_map.get((doc.id, doc.generation)) if ver_map is not None else version_row(db, doc.id, doc.generation)
        job = job_map.get((doc.id, doc.generation)) if job_map is not None else db.scalar(select(Job).where(Job.document_id == doc.id, Job.kind == "ingest", Job.generation == doc.generation))
        result["processing"] = (job.usage or {}).get("processing") if job else None
        result["extraction"] = {k:v for k,v in (ver.details if ver else {}).items() if k not in ("original_units",)}
        result["import_status"] = ver.status if ver else doc.status
        result["import_error"] = ver.error if ver else doc.error
        result["source_url"] = ver.source_url if ver else None
    return result


def lock_owned(db, user, document_id):
    original = access.document(db, user.id, document_id)
    access.notebook(db, user.id, original.notebook_id, lock=True)
    doc = db.scalar(select(Document).where(Document.id == document_id).with_for_update().execution_options(populate_existing=True))
    if not doc or doc.deleted_at:
        fail(404, "not_found", "资料不存在")
    return doc


def new_source(db, user, notebook_id, title, kind, raw=None, url=None, keep_copy=False):
    nb = access.notebook(db, user.id, notebook_id, lock=True)
    if kind == "web" and not keep_copy:
        existing = db.scalar(select(Document).join(SourceVersion).where(Document.notebook_id == notebook_id,
            Document.deleted_at.is_(None), SourceVersion.source_url == url,
            SourceVersion.status.not_in(["failed", "cancelled"])).limit(1))
        if existing:
            fail(409, "duplicate", f"此网页已添加为「{existing.filename}」，可打开资料重新获取或明确保留副本")
    count = db.scalar(select(func.count()).select_from(Document).where(Document.notebook_id == notebook_id, Document.deleted_at.is_(None)))
    if count >= settings().max_files:
        fail(409, "file_limit", f"每个笔记本最多 {settings().max_files} 份资料")
    identity = uid()
    doc = Document(id=identity, notebook_id=notebook_id, filename=title, source_type=kind,
                   size=len(raw or b""), object_key=f"{user.id}/{notebook_id}/{identity}/1", generation=1, active_version=0)
    file_hash = digest(raw) if raw is not None else None
    other = duplicate(db, doc, file_hash, file=True) if file_hash else None
    if other and not keep_copy:
        fail(409, "duplicate", f"已有相同资料「{other.filename}」。如确需保留独立副本，请选择“保留副本”")
    ver = SourceVersion(document_id=identity, version=1, title=title, object_key=doc.object_key,
                        source_url=url, file_hash=file_hash, status="queued", units=[], details={"keep_copy": keep_copy})
    db.add(doc)
    db.flush()
    db.add(ver)
    nb.updated_at = now()
    db.commit()  # Durable reservation ensures every possibly-written object has a cleanup owner.
    doc = db.scalar(select(Document).where(Document.id == identity).with_for_update().execution_options(populate_existing=True))
    if not doc or doc.deleted_at:
        fail(409, "deleted", "资料已删除")
    try:
        if raw is not None:
            storage.put(doc.object_key, raw, MIMES[kind])
        doc.status = "queued"
        create_job(db, doc)
        db.commit()
    except Exception:
        db.rollback()
        doc = db.scalar(select(Document).where(Document.id == identity).with_for_update())
        if doc:
            tombstone(db, doc)
            db.commit()
        fail(503, "upload_failed", "文件保存失败，请重试")
    return serialize(doc, db)


@router.get("/import-limits")
def limits(user=Depends(current_user)):
    s = settings()
    return {k:getattr(s,k) for k in ("max_upload_mb", "max_files", "max_batch_files", "max_pdf_pages", "max_document_chars", "ocr_max_pages", "ocr_daily_pages")}


@router.get("/notebooks/{notebook_id}/documents")
def listing(notebook_id: str, user=Depends(current_user), db=Depends(db_session)):
    access.notebook(db, user.id, notebook_id)
    docs = list(
        db.scalars(
            select(Document)
            .where(
                Document.notebook_id == notebook_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at)
        )
    )
    if not docs:
        return {"items": []}
    from sqlalchemy import or_
    doc_gens = [(d.id, d.generation) for d in docs]
    v_filters = [
        (SourceVersion.document_id == d_id) & (SourceVersion.version == gen)
        for d_id, gen in doc_gens
    ]
    vers = db.scalars(select(SourceVersion).where(or_(*v_filters))).all()
    ver_map = {(v.document_id, v.version): v for v in vers}

    j_filters = [
        (Job.document_id == d_id) & (Job.generation == gen) & (Job.kind == "ingest")
        for d_id, gen in doc_gens
    ]
    jobs = db.scalars(select(Job).where(or_(*j_filters))).all()
    job_map = {(j.document_id, j.generation): j for j in jobs}
    return {"items": [serialize(d, ver_map=ver_map, job_map=job_map) for d in docs]}


@router.post("/notebooks/{notebook_id}/documents", status_code=202)
def upload(notebook_id: str, file: UploadFile = File(...), keep_copy: bool = False, user=Depends(current_user), db=Depends(db_session)):
    access.notebook(db, user.id, notebook_id)
    rate_limit("uploads:"+user.id, 60, 3600)
    title = re.sub(r"[\x00-\x1f\x7f]", "", (file.filename or "资料").replace("\\", "/").split("/")[-1])[:240]
    kind = EXTENSIONS.get(PurePosixPath(title.lower()).suffix)
    if not kind:
        fail(422, "unsupported_file", "支持 PDF、DOCX、TXT、Markdown、PNG 和 JPG；旧版 DOC 请先另存为 DOCX")
    raw = file.file.read(settings().max_upload_mb*1024*1024+1)
    if not raw:
        fail(422, "empty_file", "文件为空")
    if len(raw) > settings().max_upload_mb*1024*1024:
        fail(413, "too_large", f"单份资料不能超过 {settings().max_upload_mb}MB")
    if kind == "pdf" and not raw.startswith(b"%PDF-"):
        fail(422, "invalid_pdf", "不是有效的 PDF 文件")
    return new_source(db, user, notebook_id, title, kind, raw, keep_copy=keep_copy)


class TextInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=20, max_length=500000)
    keep_copy: bool = False


@router.post("/notebooks/{notebook_id}/sources/text", status_code=202)
def paste(notebook_id: str, data: TextInput, user=Depends(current_user), db=Depends(db_session)):
    rate_limit("uploads:"+user.id, 60, 3600)
    validate_units(text_units_checked(data.text))
    return new_source(db, user, notebook_id, data.title.strip(), "paste", data.text.encode("utf-8"), keep_copy=data.keep_copy)


class WebInput(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    keep_copy: bool = False


@router.post("/notebooks/{notebook_id}/sources/web", status_code=202)
def web(notebook_id: str, data: WebInput, user=Depends(current_user), db=Depends(db_session)):
    from .web_import import validate_url
    try:
        _, host, _ = validate_url(data.url)
    except InvalidPDF as exc:
        fail(422, "invalid_url", str(exc))
    rate_limit("web-import:"+user.id, 30, 3600)
    return new_source(db, user, notebook_id, host, "web", url=data.url, keep_copy=data.keep_copy)


def validate_units(units):
    try:
        make_chunks(units)
    except InvalidPDF as exc:
        fail(422, "invalid_content", str(exc))


def text_units_checked(text):
    try:
        return text_units(text)
    except InvalidPDF as exc:
        fail(422, "invalid_content", str(exc))


def snapshot_units(db, ver):
    if ver.units:
        return ver.units
    # Legacy PDF snapshots retain the exact indexed excerpts; no invented full-page text.
    job = db.scalar(select(Job).where(Job.document_id == ver.document_id, Job.generation == ver.version, Job.kind == "ingest"))
    extraction = (job.usage or {}).get("extraction", {}) if job else {}
    return [{"id": c.id, "text": c.text, "ocr": c.page in extraction.get("ocr_pages", []),
             **({"confidence": extraction["ocr_confidence"][str(c.page)]} if str(c.page) in extraction.get("ocr_confidence", {}) else {}),
             "location": c.location or {"page": c.page, "label": f"第 {c.page} 页", "block_id": c.id}}
            for c in db.scalars(select(Chunk).where(Chunk.document_id == ver.document_id, Chunk.version == ver.version).order_by(Chunk.page, Chunk.ordinal))]


@router.get("/documents/{document_id}/snapshot")
def snapshot(document_id: str, version: int | None = Query(None, ge=1), user=Depends(current_user), db=Depends(db_session)):
    doc = access.document(db, user.id, document_id)
    ver = version_row(db, doc.id, version or doc.active_version or doc.generation)
    if not ver:
        fail(404, "version_unavailable", "此历史版本没有保存完整快照，仅可查看成果中保留的引用片段")
    return {"document_id": doc.id, "source_type": doc.source_type, "version": ver.version, "title": ver.title,
        "status": ver.status, "error": ver.error, "units": snapshot_units(db, ver), "details": ver.details,
        "source_url": ver.source_url, "created_at": ver.created_at, "changed": ver.version != doc.active_version,
        "versions": [{"version":v.version, "title":v.title, "status":v.status, "created_at":v.created_at} for v in db.scalars(select(SourceVersion).where(SourceVersion.document_id == doc.id).order_by(SourceVersion.version.desc()))]}


class VersionInput(BaseModel):
    version: int = Field(ge=1)


class EditInput(VersionInput):
    title: str = Field(min_length=1, max_length=240)
    text: str | None = Field(default=None, min_length=20, max_length=500000)
    corrections: dict[str, str] | None = None


def candidate(db, doc, expected):
    if doc.generation != expected:
        fail(409, "source_changed", "资料已有更新，请刷新后再编辑，避免覆盖其他修改")
    old = version_row(db, doc.id, doc.generation)
    if old and old.status in ("queued", "processing", "indexing", "awaiting_confirmation"):
        fail(409, "processing", "请先完成或取消当前导入")
    doc.generation += 1
    ver = SourceVersion(document_id=doc.id, version=doc.generation, title=old.title if old else doc.filename,
        object_key=old.object_key if old else doc.object_key, source_url=old.source_url if old else None,
        status="queued", units=[], details={"keep_copy": bool(old and old.details.get("keep_copy"))})
    db.add(ver)
    doc.status, doc.error = ("ready" if doc.active_version else "queued"), None
    create_job(db, doc).object_key = ver.object_key
    return old, ver


@router.put("/documents/{document_id}/content", status_code=202)
def edit(document_id: str, data: EditInput, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    if doc.source_type not in ("paste", "text", "markdown", "web", "pdf", "image"):
        fail(422, "not_editable", "请在原 Word 中修改后重新上传")
    old, ver = candidate(db, doc, data.version)
    if doc.source_type in ("pdf", "image"):
        if data.text is not None or not data.corrections or len(data.corrections) > settings().max_pdf_pages:
            fail(422, "invalid_correction", "请按页或图片修正识别文本")
        units = [dict(u) for u in snapshot_units(db, old)]
        mapping = {u["id"]:u for u in units}
        if not set(data.corrections).issubset(mapping):
            fail(422, "invalid_location", "修正位置不属于此版本")
        for key, value in data.corrections.items():
            if not mapping[key].get("ocr"):
                fail(422, "not_ocr", "只支持修正图片识别的段落")
            mapping[key]["text"], mapping[key]["user_corrected"] = value, True
    else:
        if data.text is None or data.corrections:
            fail(422, "invalid_content", "请输入修改后的正文")
        units = text_units_checked(data.text)
    validate_units(units)
    ver.title, ver.units = data.title.strip(), units
    ver.details = {**old.details, "parsed": True, "confirmed": True, "user_adjusted": True,
                   "edited_from_version": old.version, "original_units": old.details.get("original_units", old.units)}
    db.commit()
    return serialize(doc, db)


class ConfirmInput(EditInput):
    title: str = Field(default="", max_length=240)
    accept_partial: bool = False
    keep_copy: bool = False


@router.post("/documents/{document_id}/confirm", status_code=202)
def confirm(document_id: str, data: ConfirmInput, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    ver = version_row(db, doc.id, data.version)
    if doc.generation != data.version or not ver:
        fail(409, "source_changed", "预览版本已变化，请刷新")
    if ver.status in ("queued", "indexing", "ready") and ver.details.get("confirmed"):
        return serialize(doc, db)
    if ver.status != "awaiting_confirmation":
        fail(409, "not_pending", "此资料不在待确认状态")
    if ver.details.get("failed_pages") and not data.accept_partial:
        fail(422, "incomplete", "仍有失败页，请重试或明确确认仅使用成功内容")
    if data.corrections:
        fail(422, "invalid_content", "请在导入完成后按页修正识别文本")
    details = dict(ver.details)
    if data.text is not None:
        if doc.source_type != "web":
            fail(422, "invalid_content", "该预览不支持整篇覆盖")
        units = text_units_checked(data.text)
        validate_units(units)
        if "\n".join(u["text"] for u in ver.units) != data.text:
            details["user_adjusted"] = True
        ver.units = units
    validate_units(ver.units)
    hash_value = digest("\n".join(u["text"] for u in ver.units))
    other = duplicate(db, doc, hash_value)
    if other and not data.keep_copy and not details.get("keep_copy"):
        fail(409, "duplicate", f"已有相同正文「{other.filename}」，请明确选择保留独立副本")
    details.update(confirmed=True, partial_confirmed=data.accept_partial, keep_copy=data.keep_copy or details.get("keep_copy", False))
    ver.details, ver.content_hash, ver.status = details, hash_value, "queued"
    if data.title.strip():
        ver.title = data.title.strip()
    job = db.scalar(select(Job).where(Job.document_id == doc.id, Job.kind == "ingest", Job.generation == ver.version).with_for_update())
    job.status, job.attempts, job.available_at, job.dispatched_at = "queued", 0, now(), None
    doc.status = "ready" if doc.active_version else "queued"
    db.commit()
    return serialize(doc, db)


@router.post("/documents/{document_id}/cancel")
def cancel(document_id: str, data: VersionInput, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    ver = version_row(db, doc.id, data.version)
    if not ver or data.version != doc.generation or ver.status == "ready":
        fail(409, "not_cancellable", "当前版本已经完成或发生变化")
    ver.status = "cancelled"
    job = db.scalar(select(Job).where(Job.document_id == doc.id, Job.generation == data.version, Job.kind == "ingest").with_for_update())
    if job:
        job.status, job.claim = "cancelled", None
    doc.status = "ready" if doc.active_version else "cancelled"
    db.commit()
    return serialize(doc, db)


@router.post("/documents/{document_id}/retry", status_code=202)
def retry(document_id: str, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    ver = version_row(db, doc.id, doc.generation)
    if not ver or (ver.status not in ("failed", "cancelled") and not (ver.status == "awaiting_confirmation" and ver.details.get("failed_pages"))):
        fail(409, "not_failed", "没有可重试的失败任务")
    rate_limit("retry:"+user.id, 30, 3600)
    ver.status, ver.error = "queued", None
    if ver.details.get("failed_pages"):
        ver.details = {**ver.details, "parsed": False, "retry_pages": True, "partial_confirmed": False}
    job = db.scalar(select(Job).where(Job.document_id == doc.id, Job.generation == doc.generation, Job.kind == "ingest").with_for_update())
    job.status, job.claim, job.attempts, job.error, job.available_at, job.dispatched_at = "queued", None, 0, None, now(), None
    doc.status, doc.error = ("ready" if doc.active_version else "queued"), None
    db.commit()
    return serialize(doc, db)


@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess(document_id: str, data: VersionInput, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    rate_limit("retry:"+user.id, 30, 3600)
    old, ver = candidate(db, doc, data.version)
    if old and old.details.get("failed_pages") and doc.source_type in ("pdf", "image"):
        ver.units = old.units
        ver.details = {**old.details, "parsed": False, "retry_pages": True, "partial_confirmed": False}
    if doc.source_type == "web":
        ver.object_key = f"{user.id}/{doc.notebook_id}/{doc.id}/{ver.version}"
        db.flush()
        job = db.scalar(select(Job).where(Job.document_id == doc.id, Job.generation == ver.version, Job.kind == "ingest"))
        job.object_key = ver.object_key
    db.commit()
    return serialize(doc, db)


@router.delete("/documents/{document_id}", status_code=202)
def remove(document_id: str, user=Depends(current_user), db=Depends(db_session)):
    doc = lock_owned(db, user, document_id)
    tombstone(db, doc)
    db.commit()
    return {"status": "deleting"}


@router.get("/documents/{document_id}/file")
def preview(document_id: str, request: Request, version: int | None = Query(None, ge=1), user=Depends(current_user), db=Depends(db_session)):
    doc = access.document(db, user.id, document_id)
    ver = version_row(db, doc.id, version or doc.active_version or doc.generation)
    if not ver:
        fail(404, "version_unavailable", "此版本的原件不可用")
    try:
        obj_meta = storage.head(ver.object_key)
        total_size = obj_meta.get("ContentLength", 0)
    except Exception:
        fail(503, "file_unavailable", "暂时无法读取原件，请稍后重试")
    mime = MIMES.get(doc.source_type, "application/octet-stream")
    inline = doc.source_type in ("pdf", "image")
    from urllib.parse import quote
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Content-Disposition": ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(ver.title),
        "Accept-Ranges": "bytes",
    }
    byte_range = request.headers.get("range")
    if byte_range:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{total_size}"})
        a, b = match.groups()
        start = int(a) if a else max(0, total_size - int(b))
        end = min(int(b), total_size - 1) if a and b else total_size - 1
        if start > end or start >= total_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{total_size}"})
        try:
            chunk = storage.read_range(ver.object_key, start, end)
        except Exception:
            fail(503, "file_unavailable", "读取文件片段失败，请稍后重试")
        if doc.source_type == "image" and chunk.startswith(b"\xff\xd8"):
            mime = "image/jpeg"
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
        return Response(chunk, 206, headers, media_type=mime)
    try:
        data = storage.read(ver.object_key)
    except Exception:
        fail(503, "file_unavailable", "暂时无法读取原件，请稍后重试")
    if doc.source_type == "image" and data.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    return Response(data, headers=headers, media_type=mime)
