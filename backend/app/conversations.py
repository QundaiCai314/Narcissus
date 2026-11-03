from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from .db import db_session
from .models import Conversation, Message, Citation, Chunk, Document, Notebook, SourceVersion
from .security import current_user
from . import access

router = APIRouter(tags=["对话"])


def citations(db, message_id):
    rows = db.execute(
        select(Citation, Chunk, Document)
        .join(Chunk, Citation.chunk_id == Chunk.id)
        .join(Document, Chunk.document_id == Document.id)
        .join(Notebook)
        .where(
            Citation.message_id == message_id,
            Document.deleted_at.is_(None),
            Notebook.deleted_at.is_(None),
        )
        .order_by(Citation.label)
    ).all()
    from .source_references import evidence
    return [dict(evidence(db, doc, chunk), label=cite.label) for cite, chunk, doc in rows]


def batch_citations(db, message_ids: list[str]) -> dict[str, list[dict]]:
    if not message_ids:
        return {}
    cite_rows = db.execute(
        select(Citation, Chunk, Document)
        .join(Chunk, Citation.chunk_id == Chunk.id)
        .join(Document, Chunk.document_id == Document.id)
        .join(Notebook)
        .where(
            Citation.message_id.in_(message_ids),
            Document.deleted_at.is_(None),
            Notebook.deleted_at.is_(None),
        )
        .order_by(Citation.message_id, Citation.label)
    ).all()
    if not cite_rows:
        return {}

    doc_ver_pairs = {(doc.id, chunk.version) for _, chunk, doc in cite_rows}
    version_map = {}
    if doc_ver_pairs:
        filters = [
            (SourceVersion.document_id == d_id) & (SourceVersion.version == v)
            for d_id, v in doc_ver_pairs
        ]
        ver_rows = db.scalars(select(SourceVersion).where(or_(*filters))).all()
        version_map = {(v.document_id, v.version): v for v in ver_rows}

    by_msg = defaultdict(list)
    for cite, chunk, doc in cite_rows:
        ver = version_map.get((doc.id, chunk.version))
        location = chunk.location or {"label": f"第 {chunk.page} 页", "page": chunk.page}
        by_msg[cite.message_id].append({
            "kind": "document",
            "document_id": doc.id,
            "chunk_id": chunk.id,
            "filename": ver.title if ver else doc.filename,
            "version": chunk.version,
            "warning": (
                "资料不完整，以下页面未识别："
                + ",".join(str(p["page"]) for p in ver.details["failed_pages"])
            )
            if ver and ver.details.get("failed_pages")
            else None,
            "source_type": doc.source_type,
            "page": chunk.page,
            "ordinal": chunk.ordinal,
            "source_url": ver.source_url if ver else None,
            "fetched_at": ver.details.get("fetched_at") if ver else None,
            "location": location,
            "position": location.get("label", "原文片段"),
            "text": chunk.text,
            "label": cite.label,
        })
    return by_msg


def serialize_message(db, msg):
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "status": msg.status,
        "error": msg.error,
        "created_at": msg.created_at,
        "citations": citations(db, msg.id),
    }


@router.get("/notebooks/{notebook_id}/conversations")
def listing(
    notebook_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    access.notebook(db, user.id, notebook_id)
    q = select(Conversation).where(Conversation.notebook_id == notebook_id)
    rows = db.scalars(
        q.order_by(Conversation.updated_at.desc(), Conversation.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [
            {"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in rows
        ],
        "total": db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.notebook_id == notebook_id)
        ),
        "offset": offset,
        "limit": limit,
    }


@router.post("/notebooks/{notebook_id}/conversations", status_code=201)
def create(notebook_id: str, user=Depends(current_user), db=Depends(db_session)):
    access.notebook(db, user.id, notebook_id, lock=True)
    conv = Conversation(notebook_id=notebook_id)
    db.add(conv)
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.get("/conversations/{conversation_id}/messages")
def messages(
    conversation_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    newest: bool = False,
    user=Depends(current_user),
    db=Depends(db_session),
):
    access.conversation(db, user.id, conversation_id)
    order = (
        (Message.created_at.desc(), Message.id.desc())
        if newest
        else (Message.created_at, Message.id)
    )
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
        )
    )
    if newest:
        rows.reverse()
    citations_map = batch_citations(db, [m.id for m in rows])
    return {
        "items": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "status": m.status,
                "error": m.error,
                "created_at": m.created_at,
                "citations": citations_map.get(m.id, []),
            }
            for m in rows
        ],
        "total": db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        ),
        "offset": offset,
        "limit": limit,
    }
