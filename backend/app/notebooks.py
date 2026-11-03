from typing import Annotated
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select, func, update
from .db import db_session
from .models import Notebook, Document, Writing, GenerationJob, now
from .security import current_user, rate_limit
from . import access
from .tasks import tombstone

router = APIRouter(prefix="/notebooks", tags=["笔记本"])


class Name(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]


def serialize(db, obj):
    count = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.notebook_id == obj.id, Document.deleted_at.is_(None))
    )
    return {
        "id": obj.id,
        "name": obj.name,
        "document_count": count,
        "updated_at": obj.updated_at,
    }


@router.get("")
def listing(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    filters = (Notebook.user_id == user.id, Notebook.deleted_at.is_(None))
    rows = list(
        db.scalars(
            select(Notebook)
            .where(*filters)
            .order_by(Notebook.updated_at.desc(), Notebook.id)
            .offset(offset)
            .limit(limit)
        )
    )
    nb_ids = [x.id for x in rows]
    counts = dict(
        db.execute(
            select(Document.notebook_id, func.count())
            .where(Document.notebook_id.in_(nb_ids), Document.deleted_at.is_(None))
            .group_by(Document.notebook_id)
        ).all()
    ) if nb_ids else {}
    return {
        "items": [
            {
                "id": x.id,
                "name": x.name,
                "document_count": counts.get(x.id, 0),
                "updated_at": x.updated_at,
            }
            for x in rows
        ],
        "total": db.scalar(select(func.count()).select_from(Notebook).where(*filters)),
        "offset": offset,
        "limit": limit,
    }


@router.post("", status_code=201)
def create(data: Name, user=Depends(current_user), db=Depends(db_session)):
    rate_limit("notebooks:" + user.id, 30, 3600)
    obj = Notebook(user_id=user.id, name=data.name)
    db.add(obj)
    db.commit()
    return serialize(db, obj)


@router.get("/{notebook_id}")
def detail(notebook_id: str, user=Depends(current_user), db=Depends(db_session)):
    return serialize(db, access.notebook(db, user.id, notebook_id))


@router.patch("/{notebook_id}")
def rename(
    notebook_id: str, data: Name, user=Depends(current_user), db=Depends(db_session)
):
    obj = access.notebook(db, user.id, notebook_id, lock=True)
    obj.name, obj.updated_at = data.name, now()
    db.commit()
    return serialize(db, obj)


@router.delete("/{notebook_id}", status_code=202)
def remove(notebook_id: str, user=Depends(current_user), db=Depends(db_session)):
    obj = access.notebook(db, user.id, notebook_id, lock=True)
    obj.deleted_at = now()
    from .models import VisualArtifact
    from .visuals import cancel_artifact
    for artifact in db.scalars(select(VisualArtifact).where(VisualArtifact.notebook_id == notebook_id)):
        cancel_artifact(db, artifact, True)
    from .models import ResearchTask
    from .research import cancel as cancel_research
    for task in db.scalars(select(ResearchTask).where(ResearchTask.notebook_id == notebook_id)):
        cancel_research(db, task)
    from .learning import cancel_source as cancel_learning

    cancel_learning(db, notebook_id)
    from .audio import cancel_source as cancel_audio
    cancel_audio(db, notebook_id)
    db.execute(
        update(GenerationJob)
        .where(
            GenerationJob.writing_id.in_(
                select(Writing.id).where(Writing.notebook_id == notebook_id)
            ),
            GenerationJob.status.in_(["queued", "running"]),
        )
        .values(status="cancelled", claim=None, error="笔记本已删除")
    )
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.notebook_id == notebook_id)
            .order_by(Document.id)
            .with_for_update()
        )
    )
    for doc in docs:
        tombstone(db, doc)
    db.commit()
    return {"status": "deleting"}
