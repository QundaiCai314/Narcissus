"""Durable, claim-fenced search/fetch/import outbox. Unknown remote outcomes need explicit retry."""

import logging
from datetime import timedelta

from sqlalchemy import func, or_, select

from . import storage
from .config import settings
from .db import SessionLocal
from .models import (
    Document,
    Job,
    Notebook,
    ResearchCandidate,
    ResearchTask,
    SourceVersion,
    User,
    now,
    uid,
)
from .pdf_processing import InvalidPDF
from .search_service import SearchError, search
from .source_parsing import digest, make_chunks
from .tasks import celery, create_job
from .web_import import extract_web, fetch_public

log = logging.getLogger("narcissus.research")


def context(db, kind, identity):
    row = db.get(ResearchTask if kind == "search" else ResearchCandidate, identity)
    task = (
        row
        if kind == "search"
        else db.get(ResearchTask, row.research_id)
        if row
        else None
    )
    nb = db.get(Notebook, task.notebook_id) if task else None
    return row, task, nb


def locked(db, kind, identity):
    _, task, nb = context(db, kind, identity)
    if not nb:
        return None, None, None
    nb = db.scalar(
        select(Notebook)
        .where(Notebook.id == nb.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = db.scalar(
        select(ResearchTask)
        .where(ResearchTask.id == task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = (
        task
        if kind == "search"
        else db.scalar(
            select(ResearchCandidate)
            .where(ResearchCandidate.id == identity)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return row, task, nb


def valid(row, task, nb, claim):
    return (
        row
        and task
        and nb
        and not nb.deleted_at
        and task.status != "cancelled"
        and row.status == "running"
        and row.claim == claim
    )


def quota(db, user_id):
    # All calls recorded durably before dispatch, including timeouts / worker loss.
    tasks = list(
        db.scalars(
            select(ResearchTask).join(Notebook).where(Notebook.user_id == user_id)
        )
    )
    today = now().date().isoformat()
    return sum(
        1
        for task in tasks
        for entry in task.usage
        if entry.get("started_at", "").startswith(today)
    )


@celery.task(name="app.research_tasks.process", soft_time_limit=100, time_limit=120)
def process(kind, identity):
    claim = uid()
    with SessionLocal() as db:
        _, _, nb = context(db, kind, identity)
        if not nb:
            return
        user_id = nb.user_id
        db.scalar(select(User).where(User.id == user_id).with_for_update())
        row, task, nb = locked(db, kind, identity)
        if (
            not row
            or not task
            or not nb
            or nb.deleted_at
            or task.status == "cancelled"
            or row.status != "queued"
            or row.available_at > now()
        ):
            return
        active_search = db.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .join(Notebook)
            .where(Notebook.user_id == user_id, ResearchTask.status == "running")
        )
        active_fetch = db.scalar(
            select(func.count())
            .select_from(ResearchCandidate)
            .join(ResearchTask)
            .join(Notebook)
            .where(Notebook.user_id == user_id, ResearchCandidate.status == "running")
        )
        if active_search + active_fetch >= max(
            1, min(4, settings().research_user_concurrency)
        ):
            row.available_at, row.dispatched_at = now() + timedelta(seconds=10), None
            db.commit()
            return
        if (
            kind == "search"
            and quota(db, user_id) >= settings().research_daily_searches
        ):
            row.status, row.error = "failed", "今日搜索调用次数已达上限，请明日再试"
            db.commit()
            return
        from .security import rate_limit

        try:
            if kind == "search":
                rate_limit(
                    "research-search:" + user_id + ":" + now().date().isoformat(),
                    settings().research_daily_searches,
                    172800,
                )
            elif row.action == "fetch":
                rate_limit(
                    "research-fetch:" + user_id + ":" + now().date().isoformat(),
                    60,
                    172800,
                )
            elif (
                row.details.get("import_attempts", 0)
                >= settings().research_max_attempts
            ):
                raise SearchError("导入已达到重试上限")
        except Exception:
            row.status, row.error = (
                "failed",
                "调用配额已用完、限流服务不可用或重试达到上限，请稍后再试",
            )
            db.commit()
            return
        row.status, row.claim, row.started_at = "running", claim, now()
        if kind == "search" or row.action == "fetch":
            row.attempts += 1
        else:
            row.details = {
                **row.details,
                "import_attempts": row.details.get("import_attempts", 0) + 1,
            }
        row.usage = [
            *row.usage,
            {
                "started_at": now().isoformat(),
                "stage": "search" if kind == "search" else row.action,
            },
        ]
        question = task.question
        if kind == "search":
            # Chinese original questions stay unchanged. An explicit English preference is shown as a keyword hint.
            query = question + (" English" if task.params["language"] == "en" else "")
            task.queries = [query]
            action, url = "search", None
        else:
            action, url = row.action, row.url
        db.commit()
    try:
        if action == "search":
            results, usage = search(query)
            with SessionLocal() as db:
                row, task, nb = locked(db, kind, identity)
                if not valid(row, task, nb, claim):
                    return
                for result in results:
                    db.add(
                        ResearchCandidate(
                            research_id=task.id, status="waiting", **result
                        )
                    )
                row.status, row.error, row.claim = "complete", None, None
                row.usage = [
                    *row.usage[:-1],
                    {**row.usage[-1], **usage, "completed_at": now().isoformat()},
                ]
                db.commit()
        elif action == "fetch":
            raw, meta = fetch_public(url)
            title, units, details = extract_web(raw, meta)
            make_chunks(units)
            with SessionLocal() as db:
                row, task, nb = locked(db, kind, identity)
                if not valid(row, task, nb, claim):
                    return
                row.title, row.units, row.raw_snapshot = title[:255], units, raw
                row.details = {
                    **row.details,
                    **details,
                    "fetched_at": now().isoformat(),
                    "original_units": units,
                    "parsed": True,
                }
                row.status, row.error, row.claim = "preview", None, None
                row.usage = [
                    *row.usage[:-1],
                    {
                        **row.usage[-1],
                        "bytes": len(raw),
                        "characters": sum(len(u["text"]) for u in units),
                    },
                ]
                db.commit()
        else:
            import_snapshot(identity, claim, user_id)
        log.info("research_complete task_id=%s stage=%s", identity, action)
    except (SearchError, InvalidPDF) as exc:
        fail_task(kind, identity, claim, str(exc))
    except Exception:
        fail_task(kind, identity, claim, "处理失败或超时，已完成的阶段仍会保留，请重试")


def import_snapshot(identity, claim, user_id):
    with SessionLocal() as db:
        row, task, nb = locked(db, "source", identity)
        if not valid(row, task, nb, claim):
            return
        # Recheck duplicates and capacity under the same notebook lock used by every upload.
        from .research import existing_document

        existing = existing_document(db, task, row)
        if existing and existing.id != row.document_id:
            raise InvalidPDF("网页已被添加到笔记本，请选择使用已有资料")
        doc = db.get(Document, row.document_id) if row.document_id else None
        if not doc:
            count = db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.notebook_id == nb.id, Document.deleted_at.is_(None))
            )
            if count >= settings().max_files:
                raise InvalidPDF(
                    f"笔记本最多 {settings().max_files} 份资料，请先整理来源"
                )
            identity_doc = uid()
            doc = Document(
                id=identity_doc,
                notebook_id=nb.id,
                filename=row.title,
                source_type="web",
                generation=1,
                active_version=0,
                size=len(row.raw_snapshot or b""),
                object_key=f"{user_id}/{nb.id}/{identity_doc}/1",
            )
            db.add(doc)
            db.flush()
            db.add(
                SourceVersion(
                    document_id=doc.id,
                    version=1,
                    title=row.title,
                    object_key=doc.object_key,
                    source_url=row.url,
                    file_hash=digest(row.raw_snapshot or b""),
                    status="queued",
                    units=row.units,
                    details={
                        **row.details,
                        "parsed": True,
                        "confirmed": True,
                        "research_id": task.id,
                        "candidate_id": row.id,
                    },
                )
            )
            row.document_id = doc.id
            db.commit()  # Private object now has a durable cleanup owner before any write.
        else:
            db.commit()
    with SessionLocal() as db:
        row, task, nb = locked(db, "source", identity)
        if not valid(row, task, nb, claim):
            return
        doc = db.scalar(
            select(Document).where(Document.id == row.document_id).with_for_update()
        )
        if not doc or doc.deleted_at:
            raise InvalidPDF("资料已删除，不能继续导入")
        storage.put(doc.object_key, row.raw_snapshot, "text/plain")
        if not db.scalar(
            select(Job.id).where(
                Job.document_id == doc.id,
                Job.kind == "ingest",
                Job.generation == doc.generation,
            )
        ):
            create_job(db, doc)
        doc.status = "queued"
        row.status, row.error, row.claim = "imported", None, None
        row.details = {**row.details, "imported": True}
        nb.updated_at = now()
        db.commit()


def fail_task(kind, identity, claim, reason):
    with SessionLocal() as db:
        row, task, nb = locked(db, kind, identity)
        if not row or row.status != "running" or (claim and row.claim != claim):
            return
        if claim is None and row.started_at > now() - timedelta(seconds=150):
            return
        row.status, row.claim, row.error = "failed", None, reason
        db.commit()
    log.warning("research_failed task_id=%s stage=%s", identity, kind)


def sweep_research():
    for kind, model in (("search", ResearchTask), ("source", ResearchCandidate)):
        with SessionLocal() as db:
            stale = list(
                db.scalars(
                    select(model.id).where(
                        model.status == "running",
                        model.started_at < now() - timedelta(seconds=150),
                    )
                )
            )
        for identity in stale:
            fail_task(
                kind,
                identity,
                None,
                "任务超时或进程中断，结果不明；不会自动重复调用，请核对后重试",
            )
        with SessionLocal() as db:
            rows = db.scalars(
                select(model)
                .where(
                    model.status == "queued",
                    model.available_at <= now(),
                    or_(
                        model.dispatched_at.is_(None),
                        model.dispatched_at < now() - timedelta(seconds=30),
                    ),
                )
                .limit(50)
                .with_for_update(skip_locked=True)
            )
            for row in rows:
                try:
                    process.apply_async(args=[kind, row.id], task_id=uid())
                    row.dispatched_at = now()
                except Exception:
                    log.warning("research_dispatch_failed task_id=%s", row.id)
            db.commit()
