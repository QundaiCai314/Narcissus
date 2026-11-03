"""Unified ingestion with immutable publication and per-version leases."""
import uuid
import logging
import traceback
from datetime import timedelta
from sqlalchemy import select, func, delete
from .models import Document, SourceVersion, Notebook, Job, Chunk, now, uid
from .db import SessionLocal
from .config import settings
from .source_parsing import parse_file, make_chunks, digest
from .pdf_processing import InvalidPDF
from .model_service import embed, embedding_signature, ModelError
from . import storage


def version_row(db, doc_id, version):
    return db.scalar(select(SourceVersion).where(SourceVersion.document_id == doc_id, SourceVersion.version == version))


def duplicate(db, doc, hash_value, file=False):
    column = SourceVersion.file_hash if file else SourceVersion.content_hash
    return db.scalar(select(Document).join(SourceVersion).where(
        Document.notebook_id == doc.notebook_id, Document.id != doc.id,
        Document.deleted_at.is_(None), column == hash_value,
        SourceVersion.status.not_in(["cancelled", "failed"])).order_by(Document.created_at).limit(1))


def current(db, doc_id, job_id, claim, generation):
    doc = db.scalar(select(Document).where(Document.id == doc_id).with_for_update())
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not doc or doc.deleted_at or doc.generation != generation or not job or job.claim != claim or job.status != "running":
        raise InvalidPDF("资料已删除或任务已取消")
    return doc, job, version_row(db, doc_id, generation)


def process(job_id):
    from .tasks import finish_failure
    claim = uid()
    with SessionLocal() as db:
        snapshot = db.get(Job, job_id)
        if not snapshot:
            return
        original = db.get(Document, snapshot.document_id)
        if not original:
            return
        # Serialize per-user concurrency claims by locking the owner, not just one notebook.
        from .models import User
        nb = db.get(Notebook, original.notebook_id)
        db.scalar(select(User).where(User.id == nb.user_id).with_for_update())
        doc = db.scalar(select(Document).where(Document.id == original.id).with_for_update())
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True))
        if job.status != "queued" or job.available_at > now():
            return
        if (job.kind != "cleanup" and doc.deleted_at) or (job.kind == "ingest" and doc.generation != job.generation):
            job.status = "cancelled"
            db.commit()
            return
        running = db.scalar(select(func.count()).select_from(Job).join(Document).join(Notebook).where(
            Notebook.user_id == nb.user_id, Job.kind == "ingest", Job.status == "running"))
        if job.kind == "ingest" and running >= max(1, settings().import_user_concurrency):
            job.available_at, job.dispatched_at = now()+timedelta(seconds=10), None
            db.commit()
            return
        job.status, job.claim, job.started_at = "running", claim, now()
        job.attempts += 1
        ver = version_row(db, doc.id, job.generation)
        if job.kind == "ingest":
            if not ver:
                ver = SourceVersion(document_id=doc.id, version=job.generation, title=doc.filename, object_key=job.object_key, units=[], details={})
                db.add(ver)
            ver.status, ver.error = "processing", None
            doc.status, doc.error = ("ready" if doc.active_version else "processing"), None
        kind, key, doc_id, generation, user_id, source_type = job.kind, job.object_key, doc.id, job.generation, nb.user_id, doc.source_type
        details, saved_units, url = (dict(ver.details or {}), list(ver.units or []), ver.source_url) if ver else ({}, [], None)
        db.commit()
    try:
        if kind == "fingerprint":
            file_hash = digest(storage.read(key))
            with SessionLocal() as db:
                doc = db.scalar(select(Document).where(Document.id == doc_id).with_for_update())
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                ver = version_row(db, doc_id, generation)
                if doc and not doc.deleted_at and ver and job and job.claim == claim and job.status == "running":
                    ver.file_hash, job.status = file_hash, "complete"
                    db.commit()
            return
        if kind == "cleanup":
            with SessionLocal() as db:
                keys = set(db.scalars(select(SourceVersion.object_key).where(SourceVersion.document_id == doc_id))) | {key}
            for object_key in keys:
                storage.remove(object_key)
            with SessionLocal() as db:
                doc = db.scalar(select(Document).where(Document.id == doc_id).with_for_update())
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if job and job.claim == claim and job.status == "running":
                    job.status = "complete"
                    if doc and doc.deleted_at:
                        db.delete(doc)
                    db.commit()
            return

        def progress(page, total, stage):
            with SessionLocal() as db:
                _, job, _ = current(db, doc_id, job_id, claim, generation)
                job.usage = {**(job.usage or {}), "processing": {"page": page, "pages": total, "stage": stage}}
                db.commit()
            if stage == "ocr":
                from .security import redis
                quota = f"ocr-pages:{user_id}:{now().date().isoformat()}"
                used = redis.incr(quota)
                redis.expire(quota, 172800)
                if used > settings().ocr_daily_pages:
                    from .ocr import OCRFailure
                    raise OCRFailure("今日图片文字识别页数达到上限，请明日重试或粘贴正文")

        if details.get("parsed"):
            units, extraction = saved_units, details
        elif source_type == "web":
            from .web_import import fetch_public, extract_web
            raw, meta = fetch_public(url)
            title, units, extraction = extract_web(raw, meta)
            extraction.update(fetched_at=now().isoformat(), original_units=units, parsed=True, confirmed=False)
            make_chunks(units)  # Enforce size and usable-body limits before preview.
            with SessionLocal() as db:
                doc, job, ver = current(db, doc_id, job_id, claim, generation)
                storage.put(key, raw, "text/plain")
                ver.title = title
                ver.file_hash = digest(raw)
                db.commit()
        else:
            units, extraction = parse_file(source_type, storage.read(key), progress, saved_units if details.get("retry_pages") else None)
            extraction.update(parsed=True)
        if extraction.get("failed_pages") and not units:
            with SessionLocal() as db:
                _, _, ver = current(db, doc_id, job_id, claim, generation)
                ver.details = {**details, **extraction, "parsed": False}
                db.commit()
            raise InvalidPDF("所有页面均未成功识别：" + extraction["failed_pages"][0]["error"])
        extraction["characters"] = sum(len(u["text"]) for u in units)
        content_hash = digest("\n".join(u["text"] for u in units))
        with SessionLocal() as db:
            nb_id = db.get(Document, doc_id).notebook_id if db.get(Document, doc_id) else None
            db.scalar(select(Notebook).where(Notebook.id == nb_id).with_for_update())
            doc, job, ver = current(db, doc_id, job_id, claim, generation)
            extraction = {**details, **extraction}
            other = duplicate(db, doc, content_hash)
            if other and not extraction.get("keep_copy"):
                extraction["duplicate"] = {"id": other.id, "title": other.filename}
            ver.units, ver.details, ver.content_hash = units, extraction, content_hash
            awaiting = (source_type == "web" and not extraction.get("confirmed")) or (
                bool(extraction.get("failed_pages")) and not extraction.get("partial_confirmed")) or (
                other and not extraction.get("keep_copy"))
            if awaiting:
                job.status = ver.status = "awaiting_confirmation"
                doc.status = "ready" if doc.active_version else "awaiting_confirmation"
                db.commit()
                return
            ver.status = "indexing"
            doc.status = "ready" if doc.active_version else "indexing"
            db.commit()
        parts = make_chunks(units)
        vectors, usage = [], {"total_tokens": 0, "extraction": {k:v for k,v in extraction.items() if k not in ("original_units",)}, "characters": sum(len(u["text"]) for u in units)}
        batch_size = max(1, min(settings().embedding_batch_size, 10))
        for i in range(0, len(parts), batch_size):
            progress(i, len(parts), "indexing")
            batch, used = embed([p["text"] for p in parts[i:i+batch_size]])
            vectors.extend(batch)
            usage["total_tokens"] += used.get("total_tokens", 0)
        with SessionLocal() as db:
            doc, job, ver = current(db, doc_id, job_id, claim, generation)
            # Only a candidate's own index can be replaced. Historical chunks are retained.
            db.execute(delete(Chunk).where(Chunk.document_id == doc_id, Chunk.version == generation))
            for part, vector in zip(parts, vectors, strict=True):
                chunk_id = str(uuid.uuid5(uuid.UUID(doc_id), f"v{generation}:{part['ordinal']}"))
                db.add(Chunk(id=chunk_id, document_id=doc_id, version=generation, embedding=vector, **part))
            from .writings import cancel_source, queue_guide
            from .learning import cancel_source as cancel_learning
            from .audio import cancel_source as cancel_audio
            cancel_source(db, doc.notebook_id, doc.id)
            cancel_learning(db, doc.notebook_id, doc.id)
            cancel_audio(db, doc.notebook_id, doc.id)
            doc.active_version = generation
            doc.filename, doc.pages = ver.title, extraction.get("pages")
            doc.status, doc.error, doc.embedding_model, doc.updated_at = "ready", None, embedding_signature(), now()
            ver.status, ver.error = "ready", None
            job.status, job.usage = "complete", usage
            db.flush()
            queue_guide(db, doc)
            db.commit()
    except InvalidPDF as error:
        finish_failure(job_id, claim, str(error), permanent=True)
    except ModelError as error:
        finish_failure(job_id, claim, str(error))
    except Exception as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        logging.getLogger("narcissus.sources").error("task_id=%s error_type=%s location=%s:%s", job_id, type(exc).__name__, frame.filename.rsplit("/",1)[-1], frame.lineno)
        finish_failure(job_id, claim, "资料处理或文件清理失败，请重试")
