"""Run save, restart all stateful/application services, then run verify in the same API container."""

import hashlib
import json
import sys
from pathlib import Path
from sqlalchemy import select
from app.db import SessionLocal
from app.models import User, Notebook, Document, Message, Citation
from app import storage

path = Path("/tmp/narcissus-persistence-check.json")
with SessionLocal() as db:
    if sys.argv[1] == "save":
        user = db.scalar(
            select(User)
            .where(User.email.like("a-%@example.com"))
            .order_by(User.created_at.desc())
        )
        notebook = db.scalar(
            select(Notebook).where(
                Notebook.user_id == user.id, Notebook.deleted_at.is_(None)
            )
        )
        doc = db.scalar(
            select(Document).where(
                Document.notebook_id == notebook.id,
                Document.status == "ready",
                Document.deleted_at.is_(None),
            )
        )
        msg = db.scalar(
            select(Message)
            .join(Citation)
            .where(Message.status == "complete")
            .order_by(Message.created_at.desc())
        )
        state = {
            "user_id": user.id,
            "email": user.email,
            "notebook_id": notebook.id,
            "name": notebook.name,
            "document_id": doc.id,
            "file_hash": hashlib.sha256(storage.read(doc.object_key)).hexdigest(),
            "message_id": msg.id,
            "content": msg.content,
        }
        path.write_text(json.dumps(state), encoding="utf-8")
        print(
            "Saved database and object-storage fingerprints for restart verification."
        )
    else:
        state = json.loads(path.read_text(encoding="utf-8"))
        assert db.get(User, state["user_id"]).email == state["email"]
        assert db.get(Notebook, state["notebook_id"]).name == state["name"]
        doc = db.get(Document, state["document_id"])
        assert (
            hashlib.sha256(storage.read(doc.object_key)).hexdigest()
            == state["file_hash"]
        )
        assert db.get(Message, state["message_id"]).content == state["content"]
        assert db.scalar(
            select(Citation.id).where(Citation.message_id == state["message_id"])
        )
        print(
            "PASS: user, notebook, original PDF bytes, message and citation survived full service restart."
        )
