"""Database outbox + bounded leases. All writes are fenced by document generation and claim."""

import logging
from datetime import timedelta
from celery import Celery
from sqlalchemy import select, delete, update, or_, exists
from .config import settings
from .db import SessionLocal
from .models import Document, Notebook, Job, Chunk, Message, LoginSession, now, uid

log = logging.getLogger("narcissus.tasks")
celery = Celery(
    "narcissus",
    broker=settings().redis_url,
    include=["app.generation", "app.learning_generation", "app.audio_tasks", "app.research_tasks", "app.visual_tasks"],
)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=240,
    task_time_limit=270,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 600},
    beat_schedule={
        "recover-and-dispatch": {"task": "app.tasks.sweep", "schedule": 10.0}
    },
)


def create_job(db, doc, kind="ingest"):
    job = Job(
        document_id=doc.id,
        kind=kind,
        generation=doc.generation,
        object_key=doc.object_key,
    )
    db.add(job)
    return job


def tombstone(db, doc):
    if doc.deleted_at:
        return
    doc.deleted_at = now()
    doc.status = "deleting"
    doc.generation += 1
    from .writings import cancel_source

    cancel_source(db, doc.notebook_id, doc.id)
    from .learning import cancel_source as cancel_learning

    cancel_learning(db, doc.notebook_id, doc.id)
    from .audio import cancel_source as cancel_audio
    cancel_audio(db, doc.notebook_id, doc.id)
    db.execute(
        update(Job)
        .where(
            Job.document_id == doc.id,
            Job.kind.in_(["ingest", "fingerprint"]),
            Job.status.in_(["queued", "running", "awaiting_confirmation"]),
        )
        .values(status="cancelled")
    )
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    create_job(db, doc, "cleanup")


@celery.task(name="app.tasks.sweep")
def sweep():
    """Republish undelivered outbox rows, recover worker crashes, and expire abandoned streams."""
    with SessionLocal() as db:
        # Recover by taking the document lock before the job lock everywhere.
        stale_ids = list(
            db.scalars(
                select(Job.id).where(
                    Job.status == "running",
                    Job.started_at < now() - timedelta(seconds=300),
                )
            )
        )
    for job_id in stale_ids:
        finish_failure(job_id, None, "处理超时或工作进程中断，请重试")
    with SessionLocal() as db:
        for doc in db.scalars(
            select(Document)
            .where(
                Document.status == "uploading",
                Document.created_at < now() - timedelta(minutes=5),
            )
            .with_for_update(skip_locked=True)
        ):
            tombstone(db, doc)
        db.execute(
            update(Message)
            .where(
                Message.status == "generating",
                Message.heartbeat_at
                < now() - timedelta(seconds=settings().generation_timeout_seconds + 60),
            )
            .values(status="failed", error="回答连接中断，请重试")
        )
        db.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
        # Notebook contents have been removed from storage before the tombstone is purged.
        db.execute(
            delete(Notebook).where(
                Notebook.deleted_at.is_not(None),
                ~exists(select(Document.id).where(Document.notebook_id == Notebook.id)),
            )
        )
        db.commit()

    from .generation import sweep_generations

    sweep_generations()
    from .learning_generation import sweep_learning

    sweep_learning()
    from .audio_tasks import sweep_audio
    sweep_audio()
    from .research_tasks import sweep_research
    sweep_research()
    from .visual_tasks import sweep_visuals
    sweep_visuals()
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(Job)
                .where(
                    Job.status == "queued",
                    Job.available_at <= now(),
                    or_(
                        Job.dispatched_at.is_(None),
                        Job.dispatched_at < now() - timedelta(seconds=30),
                    ),
                )
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for job in jobs:
            try:
                process_job.apply_async(args=[job.id], task_id=uid())
                job.dispatched_at = now()
            except Exception:
                log.warning("dispatch_failed job_id=%s", job.id)
        db.commit()


def finish_failure(job_id, claim, reason, permanent=False):
    with SessionLocal() as db:
        snapshot = db.get(Job, job_id)
        if not snapshot:
            return
        doc = db.scalar(
            select(Document)
            .where(Document.id == snapshot.document_id)
            .with_for_update()
        )
        job = db.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job.status != "running" or (claim is not None and job.claim != claim):
            return
        if claim is None and job.started_at > now() - timedelta(seconds=300):
            return
        job.error = reason
        job.claim = None
        job.status = "failed" if permanent or job.attempts >= 3 else "queued"
        job.available_at = now() + timedelta(seconds=10 * job.attempts)
        job.dispatched_at = None
        if job.kind == "ingest" and doc and not doc.deleted_at and doc.generation == job.generation:
            from .source_jobs import version_row
            ver = version_row(db, doc.id, job.generation)
            if ver:
                ver.status, ver.error = ("failed" if job.status == "failed" else "queued"), reason
            doc.status = "ready" if doc.active_version else ("failed" if job.status == "failed" else "queued")
            doc.error = reason
        db.commit()
    log.warning("job_failed job_id=%s reason=%s", job_id, reason)


@celery.task(name="app.tasks.process_job")
def process_job(job_id):
    from .source_jobs import process
    return process(job_id)
