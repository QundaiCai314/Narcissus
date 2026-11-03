from sqlalchemy import select
from .models import Notebook, Document, Conversation, Message
from .errors import fail


def notebook(db, user_id, notebook_id, lock=False):
    q = select(Notebook).where(
        Notebook.id == notebook_id,
        Notebook.user_id == user_id,
        Notebook.deleted_at.is_(None),
    )
    if lock:
        q = q.with_for_update()
    obj = db.scalar(q)
    if not obj:
        fail(404, "not_found", "笔记本不存在")
    return obj


def document(db, user_id, document_id):
    obj = db.scalar(
        select(Document)
        .join(Notebook)
        .where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
            Notebook.user_id == user_id,
            Notebook.deleted_at.is_(None),
        )
    )
    if not obj:
        fail(404, "not_found", "资料不存在")
    return obj


def conversation(db, user_id, conversation_id, lock=False):
    obj = db.scalar(
        select(Conversation)
        .join(Notebook)
        .where(
            Conversation.id == conversation_id,
            Notebook.user_id == user_id,
            Notebook.deleted_at.is_(None),
        )
        .with_for_update(of=Conversation)
        if lock
        else select(Conversation)
        .join(Notebook)
        .where(
            Conversation.id == conversation_id,
            Notebook.user_id == user_id,
            Notebook.deleted_at.is_(None),
        )
    )
    if not obj:
        fail(404, "not_found", "对话不存在")
    return obj


def message(db, user_id, message_id):
    obj = db.get(Message, message_id)
    if not obj:
        fail(404, "not_found", "消息不存在")
    conversation(db, user_id, obj.conversation_id)
    return obj
