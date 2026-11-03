"""Explicit operational CLI: python -m app.admin retry-cleanup | status."""

import sys
from sqlalchemy import select
from .db import SessionLocal
from .models import Job, now

if __name__ == "__main__":
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "failed")):
            print(job.id, job.kind, job.document_id, job.attempts, job.error)
            if sys.argv[1:] == ["retry-cleanup"] and job.kind == "cleanup":
                job.status, job.attempts, job.available_at, job.dispatched_at = (
                    "queued",
                    0,
                    now(),
                    None,
                )
        db.commit()
