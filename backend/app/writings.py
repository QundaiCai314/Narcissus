"""Owned editable documents, optimistic saves, and immutable evidence snapshots."""

import re
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select, func, delete
from .db import db_session
from .models import (
    Writing,
    WritingCitation,
    GenerationJob,
    Document,
    Chunk,
    Notebook,
    now,
)
from .security import current_user, rate_limit
from .errors import fail
from . import access
from .conversations import citations as answer_citations

router = APIRouter(tags=["笔记与总结"])
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class NoteInput(BaseModel):
    title: Title = "未命名笔记"
    content: str = Field(default="", max_length=100000)


class EditInput(NoteInput):
    version: int = Field(ge=1)


class SummaryInput(BaseModel):
    title: Title = "资料总结"
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    note_ids: list[str] = Field(default_factory=list, max_length=20)
    purpose: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=200)
    length: Literal["short", "medium", "long"] = "medium"


def owned(db, user_id, writing_id, lock=False):
    row = db.get(Writing, writing_id)
    if not row:
        fail(404, "not_found", "笔记或总结不存在")
    access.notebook(db, user_id, row.notebook_id, lock=lock)
    if lock:
        row = db.scalar(
            select(Writing)
            .where(Writing.id == writing_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if not row:
        fail(404, "not_found", "笔记或总结不存在")
    return row


def latest(db, writing_id):
    return db.scalar(
        select(GenerationJob)
        .where(GenerationJob.writing_id == writing_id)
        .order_by(GenerationJob.generation.desc())
        .limit(1)
    )


def source_state(db, notebook_id, snapshot):
    if snapshot.get("kind") == "note":
        row = db.get(Writing, snapshot["note_id"])
        if not row or row.notebook_id != notebook_id:
            return "deleted"
        return "active" if row.version == snapshot["version"] else "changed"
    row = db.get(Document, snapshot["document_id"])
    if not row or row.notebook_id != notebook_id or row.deleted_at:
        return "deleted"
    chunk = db.get(Chunk, snapshot.get("chunk_id"))
    if row.active_version != snapshot.get("version") or not chunk:
        return "changed"
    return "active"


def references(db, writing):
    return [
        dict(
            c.snapshot,
            label=c.label,
            state=source_state(db, writing.notebook_id, c.snapshot),
        )
        for c in db.scalars(
            select(WritingCitation)
            .where(WritingCitation.writing_id == writing.id)
            .order_by(WritingCitation.label)
        )
    ]


def serialize(db, row, full=True):
    job = latest(db, row.id)
    result = {
        k: getattr(row, k)
        for k in (
            "id",
            "notebook_id",
            "kind",
            "title",
            "version",
            "edited",
            "updated_at",
            "document_id",
        )
    }
    result["job"] = (
        {
            k: getattr(job, k)
            for k in ("id", "generation", "status", "attempts", "error")
        }
        if job
        else None
    )
    if full:
        result.update(
            content=row.content, details=row.details, citations=references(db, row)
        )
    return result


def add_references(db, writing_id, items):
    for item in items:
        snapshot = dict(item)
        label = snapshot.pop("label")
        snapshot.pop("state", None)
        db.add(WritingCitation(writing_id=writing_id, label=label, snapshot=snapshot))


def ensure_idle(db, row):
    job = latest(db, row.id)
    if job and job.status in ("queued", "running"):
        fail(409, "generating", "正在生成，请完成后再编辑")


def enqueue(db, row, request):
    previous = latest(db, row.id)
    if previous and previous.status in ("queued", "running"):
        return previous
    job = GenerationJob(
        writing_id=row.id,
        generation=(previous.generation + 1 if previous else 1),
        request=request,
    )
    db.add(job)
    return job


def queue_guide(db, doc, force=False):
    row = db.scalar(select(Writing).where(Writing.document_id == doc.id))
    if row and not force:
        job = latest(db, row.id)
        if job and job.request["documents"][0]["version"] == doc.active_version:
            return row
    if not row:
        row = Writing(
            notebook_id=doc.notebook_id,
            kind="guide",
            document_id=doc.id,
            title=f"导读 · {doc.filename}"[:120],
        )
        db.add(row)
        db.flush()
    enqueue(
        db,
        row,
        {
            "documents": [
                {"id": doc.id, "version": doc.active_version, "filename": doc.filename}
            ],
            "notes": [],
            "purpose": "理解文档主题、核心观点与待探讨的问题",
            "audience": "资料阅读者",
            "length": "short",
        },
    )
    return row


def validate_request(db, notebook_id, request):
    if request.get("research"):
        from .models import ResearchTask
        task = db.get(ResearchTask, request["research"]["id"])
        if not task or task.notebook_id != notebook_id or task.status != "complete":
            return False
    for item in request["documents"]:
        doc = db.get(Document, item["id"])
        if (
            not doc
            or doc.notebook_id != notebook_id
            or doc.deleted_at
            or doc.status != "ready"
            or doc.active_version != item["version"]
        ):
            return False
    for item in request["notes"]:
        note = db.get(Writing, item["id"])
        if (
            not note
            or note.notebook_id != notebook_id
            or note.version != item["version"]
        ):
            return False
    return True


def cancel_source(db, notebook_id, source_id):
    jobs = db.scalars(
        select(GenerationJob)
        .join(Writing)
        .where(
            Writing.notebook_id == notebook_id,
            GenerationJob.status.in_(["queued", "running"]),
        )
        .with_for_update(of=GenerationJob)
    )
    for job in jobs:
        if any(
            x["id"] == source_id
            for x in job.request["documents"] + job.request["notes"]
        ):
            job.status, job.claim, job.error = (
                "cancelled",
                None,
                "所选来源已删除，请重新选择后生成",
            )


@router.get("/notebooks/{notebook_id}/writings")
def listing(
    notebook_id: str,
    kind: Literal["note", "summary", "guide"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    access.notebook(db, user.id, notebook_id)
    filters = [Writing.notebook_id == notebook_id]
    if kind:
        filters.append(Writing.kind == kind)
    rows = db.scalars(
        select(Writing)
        .where(*filters)
        .order_by(Writing.updated_at.desc(), Writing.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [serialize(db, r, False) for r in rows],
        "total": db.scalar(select(func.count()).select_from(Writing).where(*filters)),
        "offset": offset,
        "limit": limit,
    }


@router.post("/notebooks/{notebook_id}/notes", status_code=201)
def create(
    notebook_id: str,
    data: NoteInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    nb = access.notebook(db, user.id, notebook_id, lock=True)
    rate_limit("notes:" + user.id, 120, 3600)
    row = Writing(
        notebook_id=notebook_id,
        kind="note",
        title=data.title,
        content=data.content,
        edited=True,
    )
    db.add(row)
    nb.updated_at = now()
    db.commit()
    return serialize(db, row)


@router.post("/messages/{message_id}/save-note", status_code=201)
def save_answer(message_id: str, user=Depends(current_user), db=Depends(db_session)):
    msg = access.message(db, user.id, message_id)
    conv = access.conversation(db, user.id, msg.conversation_id)
    nb = access.notebook(db, user.id, conv.notebook_id, lock=True)
    row = db.scalar(select(Writing).where(Writing.source_message_id == message_id))
    if row:
        return serialize(db, row)
    if msg.role != "assistant" or msg.status != "complete" or not msg.content:
        fail(409, "incomplete_answer", "请等待回答完成后保存")
    row = Writing(
        notebook_id=nb.id,
        kind="note",
        title=conv.title[:120],
        content=msg.content,
        source_message_id=msg.id,
    )
    db.add(row)
    db.flush()
    items = []
    for cite in answer_citations(db, msg.id):
        if f"[{cite['label']}]" in msg.content:
            doc = db.get(Document, cite["document_id"])
            items.append(dict(cite, kind="document"))
    add_references(db, row.id, items)
    nb.updated_at = now()
    db.commit()
    return serialize(db, row)


@router.get("/writings/{writing_id}")
def detail(writing_id: str, user=Depends(current_user), db=Depends(db_session)):
    return serialize(db, owned(db, user.id, writing_id))


@router.patch("/writings/{writing_id}")
def edit(
    writing_id: str, data: EditInput, user=Depends(current_user), db=Depends(db_session)
):
    row = owned(db, user.id, writing_id, lock=True)
    if row.kind == "guide":
        fail(409, "read_only", "导读请通过重新生成更新")
    ensure_idle(db, row)
    if row.version != data.version:
        fail(
            409,
            "version_conflict",
            "此文档已在其他位置修改。请保留本地内容，加载最新版本后再合并。",
        )
    row.title, row.content = data.title, data.content
    row.version += 1
    row.edited, row.updated_at = True, now()
    labels = {int(x) for x in re.findall(r"\[(\d+)\]", row.content)}
    db.execute(
        delete(WritingCitation).where(
            WritingCitation.writing_id == row.id, WritingCitation.label.not_in(labels)
        )
    )
    db.get(Notebook, row.notebook_id).updated_at = now()
    db.commit()
    return serialize(db, row)


@router.delete("/writings/{writing_id}", status_code=204)
def remove(writing_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, user.id, writing_id, lock=True)
    if row.kind == "guide":
        fail(409, "guide", "删除资料时会停止对应导读任务")
    cancel_source(db, row.notebook_id, row.id)
    db.delete(row)
    db.commit()


@router.get("/documents/{document_id}/guide")
def guide(document_id: str, user=Depends(current_user), db=Depends(db_session)):
    access.document(db, user.id, document_id)
    row = db.scalar(select(Writing).where(Writing.document_id == document_id))
    return serialize(db, row) if row else None


@router.post("/documents/{document_id}/guide", status_code=202)
def regenerate_guide(
    document_id: str, user=Depends(current_user), db=Depends(db_session)
):
    doc = access.document(db, user.id, document_id)
    access.notebook(db, user.id, doc.notebook_id, lock=True)
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not doc or doc.deleted_at or doc.status != "ready":
        fail(409, "not_ready", "请等待资料处理完成")
    rate_limit("generation:" + user.id, 30, 3600)
    row = queue_guide(db, doc, force=True)
    db.commit()
    return serialize(db, row)


@router.post("/notebooks/{notebook_id}/summaries", status_code=202)
def summarize(
    notebook_id: str,
    data: SummaryInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    nb = access.notebook(db, user.id, notebook_id, lock=True)
    rate_limit("generation:" + user.id, 30, 3600)
    if not data.document_ids and not data.note_ids:
        fail(422, "empty_sources", "请至少选择一份资料或笔记")
    if len(set(data.document_ids)) != len(data.document_ids) or len(
        set(data.note_ids)
    ) != len(data.note_ids):
        fail(422, "duplicate_sources", "来源不能重复选择")
    sources, notes = [], []
    for doc_id in data.document_ids:
        doc = access.document(db, user.id, doc_id)
        if doc.notebook_id != notebook_id or doc.status != "ready":
            fail(404, "source_unavailable", "所选资料不存在或尚不可用")
        sources.append(
            {"id": doc.id, "version": doc.active_version, "filename": doc.filename}
        )
    for note_id in data.note_ids:
        note = owned(db, user.id, note_id)
        if note.notebook_id != notebook_id or note.kind == "guide":
            fail(404, "source_unavailable", "所选笔记不存在")
        ensure_idle(db, note)
        notes.append(
            {
                "id": note.id,
                "version": note.version,
                "title": note.title,
                "content": note.content,
            }
        )
    request = {
        "documents": sources,
        "notes": notes,
        "purpose": data.purpose,
        "audience": data.audience,
        "length": data.length,
    }
    # Repeated clicks while identical input is queued/running return the same document.
    for job, existing in db.execute(
        select(GenerationJob, Writing)
        .join(Writing)
        .where(
            Writing.notebook_id == notebook_id,
            Writing.kind == "summary",
            GenerationJob.status.in_(["queued", "running"]),
        )
    ):
        if job.request == request and existing.title == data.title:
            return serialize(db, existing)
    row = Writing(notebook_id=notebook_id, kind="summary", title=data.title)
    db.add(row)
    db.flush()
    enqueue(db, row, request)
    nb.updated_at = now()
    db.commit()
    return serialize(db, row)


@router.post("/writings/{writing_id}/retry", status_code=202)
def retry(writing_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, user.id, writing_id, lock=True)
    job = latest(db, row.id)
    if not job or job.status not in ("failed", "cancelled"):
        fail(409, "not_failed", "只有失败或已取消的生成可重试")
    if not validate_request(db, row.notebook_id, job.request):
        fail(409, "sources_changed", "来源已修改或删除，请重新选择来源生成")
    rate_limit("generation:" + user.id, 30, 3600)
    enqueue(db, row, job.request)
    db.commit()
    return serialize(db, row)
