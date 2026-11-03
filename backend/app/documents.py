"""Compatibility import for the V1 documents router."""
from .source_api import *  # noqa: F403
@router.get("/cleanup")
def cleanup_status(user=Depends(current_user), db=Depends(db_session)):
    from .models import Notebook

    rows = db.execute(
        select(Job, Document.filename)
        .join(Document)
        .join(Notebook)
        .where(
            Notebook.user_id == user.id, Job.kind == "cleanup", Job.status != "complete"
        )
    ).all()
    return {
        "items": [
            {
                "id": j.id,
                "filename": name,
                "status": j.status,
                "error": j.error,
                "attempts": j.attempts,
            }
            for j, name in rows
        ]
    }


@router.post("/cleanup/{job_id}/retry", status_code=202)
def cleanup_retry(job_id: str, user=Depends(current_user), db=Depends(db_session)):
    from .models import Notebook

    job = db.scalar(
        select(Job)
        .join(Document)
        .join(Notebook)
        .where(Job.id == job_id, Notebook.user_id == user.id, Job.kind == "cleanup")
        .with_for_update(of=Job)
    )
    if not job:
        fail(404, "not_found", "清理任务不存在")
    if job.status != "failed":
        fail(409, "not_failed", "任务正在处理")
    job.status, job.attempts, job.available_at, job.dispatched_at = (
        "queued",
        0,
        now(),
        None,
    )
    db.commit()
    return {"status": "queued"}
