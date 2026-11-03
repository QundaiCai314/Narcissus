"""Owned learning publications and server-authoritative progress/assessment APIs.
Never serialize the private quiz result directly to a client.
"""

import random
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func
from . import access
from .db import db_session
from .errors import fail
from .models import LearningSet, CardProgress, QuizAttempt, Document, Chunk, now, uid
from .security import current_user, rate_limit
from .writings import source_state

router = APIRouter(tags=["学习"])
ACTIVE = ("queued", "running")


class GenerateInput(BaseModel):
    kind: Literal["mindmap", "flashcards", "quiz"]
    document_ids: list[str] = Field(min_length=1, max_length=10)
    topic: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=200)
    difficulty: Literal["easy", "standard", "advanced"] = "standard"
    count: int | None = None
    request_key: UUID

    @model_validator(mode="after")
    def count_range(self):
        self.topic, self.audience = self.topic.strip(), self.audience.strip()
        self.count = (
            self.count
            if self.count is not None
            else {"mindmap": 40, "flashcards": 15, "quiz": 10}[self.kind]
        )
        low, high = {"mindmap": (1, 40), "flashcards": (10, 30), "quiz": (5, 20)}[
            self.kind
        ]
        if not low <= self.count <= high or len(set(self.document_ids)) != len(
            self.document_ids
        ):
            raise ValueError("数量不在允许范围或来源重复")
        return self


class RequestKey(BaseModel):
    request_key: UUID


def owned(db, user_id, set_id, lock=False):
    row = db.get(LearningSet, set_id)
    if not row:
        fail(404, "not_found", "学习内容不存在")
    access.notebook(db, user_id, row.notebook_id, lock=lock)
    if lock:
        row = db.scalar(
            select(LearningSet)
            .where(LearningSet.id == set_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if not row:
        fail(404, "not_found", "学习内容不存在")
    return row


def require_complete(row, kind=None):
    if row.status != "complete" or (kind and row.kind != kind):
        fail(409, "not_ready", "学习内容尚未可用或类型不符")


def valid_sources(db, row):
    for s in row.sources:
        doc = db.get(Document, s["id"])
        if (
            not doc
            or doc.notebook_id != row.notebook_id
            or doc.deleted_at
            or doc.status != "ready"
            or doc.active_version != s["version"]
        ):
            return False
    return True


def source_status(db, row):
    items = []
    for s in row.sources:
        doc = db.get(Document, s["id"])
        state = (
            "deleted"
            if not doc or doc.deleted_at or doc.notebook_id != row.notebook_id
            else "changed"
            if doc.active_version != s["version"] or doc.status != "ready"
            else "active"
        )
        items.append(dict(s, state=state))
    return items


def refs(db, row, labels=None):
    return [
        dict(s, state=source_state(db, row.notebook_id, s))
        for s in row.citations
        if labels is None or s["label"] in labels
    ]


def card_items(row):
    return [c for c in row.result.get("items", []) if c["id"] not in row.removed_cards]


def score(attempt):
    submitted = [a for a in attempt.answers.values() if a.get("submitted")]
    correct = sum(a["correct"] for a in submitted)
    total = len(attempt.question_ids)
    return {
        "answered": len(submitted),
        "correct": correct,
        "total": total,
        "score": round(correct * 100 / total)
        if attempt.status == "complete" and total
        else None,
    }


def attempt_brief(a):
    return {
        "id": a.id,
        "status": a.status,
        "mode": a.mode,
        "created_at": a.created_at,
        "completed_at": a.completed_at,
        **score(a),
    }


def serialize(db, row, user_id, full=False):
    data = {
        k: getattr(row, k)
        for k in (
            "id",
            "family_id",
            "version",
            "kind",
            "title",
            "params",
            "status",
            "phase",
            "attempts",
            "warning",
            "error",
            "model",
            "created_at",
            "completed_at",
        )
    }
    data["sources"] = source_status(db, row)
    data["count"] = (
        len(card_items(row))
        if row.kind == "flashcards"
        else len(row.result.get("items", []))
    )
    if row.kind == "flashcards":
        p = db.scalar(
            select(CardProgress).where(
                CardProgress.set_id == row.id, CardProgress.user_id == user_id
            )
        )
        states = p.states if p else {}
        cards = card_items(row)
        data["mastery"] = {
            "mastered": sum(states.get(c["id"]) == "mastered" for c in cards),
            "review": sum(states.get(c["id"]) == "review" for c in cards),
            "total": len(cards),
        }
    if row.kind == "quiz":
        a = db.scalar(
            select(QuizAttempt)
            .where(QuizAttempt.set_id == row.id, QuizAttempt.user_id == user_id)
            .order_by(QuizAttempt.created_at.desc())
            .limit(1)
        )
        data["latest_attempt"] = attempt_brief(a) if a else None
    if full and row.status == "complete":
        if row.kind == "quiz":
            # Explicit allowlist: no correct choices, explanations, point details, quotes or evidence before submission.
            data["items"] = [
                {k: q[k] for k in ("id", "question", "options")}
                for q in row.result["items"]
            ]
            data["citations"] = []
        else:
            data["items"] = (
                card_items(row) if row.kind == "flashcards" else row.result["items"]
            )
            data["citations"] = refs(db, row)
    return data


def enqueue(db, user, nb_id, data, previous=None):
    nb = access.notebook(db, user.id, nb_id, lock=True)
    request_key = str(data.request_key)
    existing = db.scalar(
        select(LearningSet).where(
            LearningSet.notebook_id == nb_id, LearningSet.request_key == request_key
        )
    )
    params = {
        "topic": data.topic,
        "audience": data.audience,
        "difficulty": data.difficulty,
        "count": data.count,
        "max_depth": 3,
    }
    if existing:
        if (
            existing.kind != data.kind
            or existing.params != params
            or [s["id"] for s in existing.sources] != sorted(data.document_ids)
            or (previous and existing.family_id != previous.family_id)
        ):
            fail(409, "key_reused", "此请求编号已用于其他生成，请重新发起")
        return existing
    sources = []
    for doc_id in sorted(data.document_ids):
        doc = access.document(db, user.id, doc_id)
        if doc.notebook_id != nb_id or doc.status != "ready":
            fail(404, "source_unavailable", "所选资料不存在或尚不可用")
        sources.append(
            {"id": doc.id, "filename": doc.filename, "version": doc.active_version}
        )
    for row in db.scalars(
        select(LearningSet).where(
            LearningSet.notebook_id == nb_id,
            LearningSet.kind == data.kind,
            LearningSet.status.in_(ACTIVE),
        )
    ):
        if (
            row.params == params
            and row.sources == sources
            and (not previous or row.family_id == previous.family_id)
        ):
            return row
    rate_limit("learning_generation:" + user.id, 30, 3600)
    family = previous.family_id if previous else uid()
    version = (
        db.scalar(
            select(func.max(LearningSet.version)).where(LearningSet.family_id == family)
        )
        or 0
    ) + 1
    name = {"mindmap": "思维导图", "flashcards": "闪卡", "quiz": "测验"}[data.kind]
    row = LearningSet(
        notebook_id=nb_id,
        family_id=family,
        version=version,
        request_key=request_key,
        kind=data.kind,
        title=((data.topic or sources[0]["filename"])[:95] + " · " + name),
        params=params,
        sources=sources,
    )
    db.add(row)
    nb.updated_at = now()
    db.commit()
    return row


@router.get("/notebooks/{notebook_id}/learning")
def listing(
    notebook_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    access.notebook(db, user.id, notebook_id)
    q = select(LearningSet).where(LearningSet.notebook_id == notebook_id)
    rows = db.scalars(
        q.order_by(LearningSet.created_at.desc(), LearningSet.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [serialize(db, r, user.id) for r in rows],
        "total": db.scalar(
            select(func.count())
            .select_from(LearningSet)
            .where(LearningSet.notebook_id == notebook_id)
        ),
        "offset": offset,
        "limit": limit,
    }


@router.post("/notebooks/{notebook_id}/learning", status_code=202)
def create(
    notebook_id: str,
    data: GenerateInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    return serialize(db, enqueue(db, user, notebook_id, data), user.id, True)


@router.get("/learning/{set_id}")
def detail(set_id: str, user=Depends(current_user), db=Depends(db_session)):
    return serialize(db, owned(db, user.id, set_id), user.id, True)


@router.post("/learning/{set_id}/regenerate", status_code=202)
def regenerate(
    set_id: str, data: RequestKey, user=Depends(current_user), db=Depends(db_session)
):
    row = owned(db, user.id, set_id, True)
    value = GenerateInput(
        kind=row.kind,
        document_ids=[s["id"] for s in row.sources],
        request_key=data.request_key,
        **{k: row.params[k] for k in ("topic", "audience", "difficulty", "count")},
    )
    return serialize(db, enqueue(db, user, row.notebook_id, value, row), user.id, True)


@router.post("/learning/{set_id}/cancel")
def cancel(set_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, user.id, set_id, True)
    if row.status in ACTIVE:
        row.status, row.phase, row.claim, row.error = (
            "cancelled",
            "cancelled",
            None,
            "已取消生成",
        )
        db.commit()
    return serialize(db, row, user.id, True)


@router.post("/learning/{set_id}/retry", status_code=202)
def retry(set_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, user.id, set_id, True)
    if row.status not in ("failed", "cancelled"):
        fail(409, "not_retryable", "只有失败或取消的任务可以重试")
    if not valid_sources(db, row):
        fail(409, "source_changed", "资料已更新或删除，请选择当前资料生成新版")
    rate_limit("learning_generation:" + user.id, 30, 3600)
    row.status, row.phase, row.claim, row.attempts = "queued", "queued", None, 0
    row.available_at, row.dispatched_at, row.started_at = now(), None, None
    db.commit()
    return serialize(db, row, user.id)


def cancel_source(db, notebook_id, document_id=None):
    for row in db.scalars(
        select(LearningSet)
        .where(LearningSet.notebook_id == notebook_id, LearningSet.status.in_(ACTIVE))
        .with_for_update()
    ):
        if document_id is None or any(s["id"] == document_id for s in row.sources):
            row.status, row.phase, row.claim, row.error = (
                "cancelled",
                "cancelled",
                None,
                "来源或笔记本已删除",
            )


def card_progress(db, row, user_id):
    p = db.scalar(
        select(CardProgress)
        .where(CardProgress.set_id == row.id, CardProgress.user_id == user_id)
        .with_for_update()
    )
    if not p:
        ids = [c["id"] for c in card_items(row)]
        p = CardProgress(
            set_id=row.id,
            user_id=user_id,
            states={},
            order=ids,
            current_id=ids[0] if ids else None,
        )
        db.add(p)
        db.flush()
    return p


def progress_json(p):
    return {
        k: getattr(p, k)
        for k in (
            "revision",
            "states",
            "order",
            "current_id",
            "mode",
            "shuffled",
            "updated_at",
        )
    }


@router.get("/learning/{set_id}/flashcards/progress")
def progress(set_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, user.id, set_id, True)
    require_complete(row, "flashcards")
    p = card_progress(db, row, user.id)
    db.commit()
    return progress_json(p)


class CardEdit(BaseModel):
    revision: int = Field(ge=1)
    card_id: str | None = Field(default=None, max_length=40)
    state: Literal["mastered", "review", "new"] | None = None
    current_id: str | None = Field(default=None, max_length=40)
    mode: Literal["all", "review"] | None = None
    shuffle: bool | None = None


@router.patch("/learning/{set_id}/flashcards/progress")
def update_progress(
    set_id: str, data: CardEdit, user=Depends(current_user), db=Depends(db_session)
):
    row = owned(db, user.id, set_id, True)
    require_complete(row, "flashcards")
    p = card_progress(db, row, user.id)
    if p.revision != data.revision:
        fail(409, "stale_progress", "复习进度已在其他窗口更新，请重新加载")
    ids = [c["id"] for c in card_items(row)]
    if data.state is not None:
        if data.card_id not in ids:
            fail(404, "card_not_found", "闪卡不存在")
        p.states = {**p.states, data.card_id: data.state}
    if data.mode is not None:
        p.mode = data.mode
    if data.shuffle is not None:
        p.shuffled = data.shuffle
    eligible = [i for i in ids if p.mode == "all" or p.states.get(i) == "review"]
    if data.mode is not None or data.shuffle is not None:
        order = eligible[:]
        if p.shuffled:
            random.SystemRandom().shuffle(order)
        p.order = order
        p.current_id = order[0] if order else None
    else:
        p.order = [i for i in p.order if i in eligible] + [
            i for i in eligible if i not in p.order
        ]
        if p.current_id not in p.order:
            p.current_id = p.order[0] if p.order else None
    if data.current_id is not None:
        if data.current_id not in p.order:
            fail(422, "invalid_cursor", "该卡片不在本次复习范围")
        p.current_id = data.current_id
    p.revision += 1
    p.updated_at = now()
    db.commit()
    return progress_json(p)


@router.delete("/learning/{set_id}/flashcards/{card_id}", status_code=204)
def delete_card(
    set_id: str, card_id: str, user=Depends(current_user), db=Depends(db_session)
):
    row = owned(db, user.id, set_id, True)
    require_complete(row, "flashcards")
    if card_id not in {c["id"] for c in row.result["items"]}:
        fail(404, "card_not_found", "闪卡不存在")
    if card_id not in row.removed_cards:
        row.removed_cards = row.removed_cards + [card_id]
        p = card_progress(db, row, user.id)
        p.order = [i for i in p.order if i != card_id]
        p.states = {k: v for k, v in p.states.items() if k != card_id}
        if p.current_id == card_id:
            p.current_id = p.order[0] if p.order else None
        p.revision += 1
        p.updated_at = now()
        db.commit()


class AttemptInput(RequestKey):
    mode: Literal["all", "wrong"] = "all"
    previous_id: str | None = None


def owned_attempt(db, user_id, attempt_id, lock=False):
    a = db.get(QuizAttempt, attempt_id)
    if not a or a.user_id != user_id:
        fail(404, "not_found", "测验记录不存在")
    row = owned(db, user_id, a.set_id, lock)
    if lock:
        a = db.scalar(
            select(QuizAttempt)
            .where(QuizAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return row, a


def attempt_json(db, row, a):
    questions = {q["id"]: q for q in row.result["items"]}
    items, labels, weak = [], set(), {}
    for qid in a.question_ids:
        q, answer = questions[qid], a.answers.get(qid, {})
        public = {k: q[k] for k in ("id", "question", "options")}
        public.update(
            selected=answer.get("selected"), submitted=bool(answer.get("submitted"))
        )
        if answer.get("submitted"):
            public.update(
                point=q["point"],
                correct=answer["correct"],
                correct_index=q["correct_index"],
                explanation=q["explanation"],
                refs=q["refs"],
            )
            labels.update(q["refs"])
            if not answer["correct"]:
                point = weak.setdefault(
                    q["point"], {"point": q["point"], "wrong": 0, "refs": []}
                )
                point["wrong"] += 1
                point["refs"] = sorted(set(point["refs"]) | set(q["refs"]))
        items.append(public)
    return {
        **attempt_brief(a),
        "set_id": row.id,
        "version": row.version,
        "revision": a.revision,
        "items": items,
        "weak_points": list(weak.values()),
        "citations": refs(db, row, labels),
    }


@router.post("/learning/{set_id}/attempts", status_code=201)
def start_attempt(
    set_id: str, data: AttemptInput, user=Depends(current_user), db=Depends(db_session)
):
    row = owned(db, user.id, set_id, True)
    require_complete(row, "quiz")
    existing = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.request_key == str(data.request_key),
        )
    )
    if existing:
        if (
            existing.set_id != set_id
            or existing.mode != data.mode
            or existing.previous_id != data.previous_id
        ):
            fail(409, "key_reused", "此请求编号已用于其他测验")
        return attempt_json(db, row, existing)
    ids = [q["id"] for q in row.result["items"]]
    if data.mode == "wrong":
        previous = db.get(QuizAttempt, data.previous_id)
        if (
            not previous
            or previous.user_id != user.id
            or previous.set_id != row.id
            or previous.status != "complete"
        ):
            fail(404, "previous_unavailable", "请选择本版本已完成的测验记录")
        ids = [i for i in previous.question_ids if not previous.answers[i]["correct"]]
        if not ids:
            fail(409, "no_wrong_answers", "本轮没有错题")
    elif data.previous_id is not None:
        fail(422, "invalid_previous", "仅错题练习可指定上一轮")
    rate_limit("quiz_attempts:" + user.id, 120, 3600)
    a = QuizAttempt(
        set_id=set_id,
        user_id=user.id,
        request_key=str(data.request_key),
        previous_id=data.previous_id,
        mode=data.mode,
        question_ids=ids,
    )
    db.add(a)
    db.commit()
    return attempt_json(db, row, a)


@router.get("/learning/{set_id}/attempts")
def attempts(
    set_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    row = owned(db, user.id, set_id)
    require_complete(row, "quiz")
    filters = (QuizAttempt.set_id == set_id, QuizAttempt.user_id == user.id)
    rows = db.scalars(
        select(QuizAttempt)
        .where(*filters)
        .order_by(QuizAttempt.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [attempt_brief(a) for a in rows],
        "total": db.scalar(
            select(func.count()).select_from(QuizAttempt).where(*filters)
        ),
        "offset": offset,
        "limit": limit,
    }


@router.get("/quiz-attempts/{attempt_id}")
def get_attempt(attempt_id: str, user=Depends(current_user), db=Depends(db_session)):
    row, a = owned_attempt(db, user.id, attempt_id)
    return attempt_json(db, row, a)


class AnswerInput(BaseModel):
    selected: int = Field(ge=0, le=3, strict=True)
    revision: int = Field(ge=1)


@router.patch("/quiz-attempts/{attempt_id}/answers/{question_id}")
def save_answer(
    attempt_id: str,
    question_id: str,
    data: AnswerInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    row, a = owned_attempt(db, user.id, attempt_id, True)
    if question_id not in a.question_ids:
        fail(404, "question_not_found", "题目不在本次测验中")
    old = a.answers.get(question_id, {})
    if old.get("submitted"):
        fail(409, "already_submitted", "本题已提交，不能修改；可以开始新一轮测验")
    if old.get("selected") == data.selected:
        return attempt_json(db, row, a)
    if a.revision != data.revision:
        fail(409, "stale_attempt", "作答进度已更新，请重新加载")
    a.answers = {
        **a.answers,
        question_id: {"selected": data.selected, "submitted": False},
    }
    a.revision += 1
    db.commit()
    return attempt_json(db, row, a)


@router.post("/quiz-attempts/{attempt_id}/answers/{question_id}/submit")
def submit_answer(
    attempt_id: str,
    question_id: str,
    data: AnswerInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    row, a = owned_attempt(db, user.id, attempt_id, True)
    if question_id not in a.question_ids:
        fail(404, "question_not_found", "题目不在本次测验中")
    old = a.answers.get(question_id, {})
    if old.get("submitted"):
        if old["selected"] != data.selected:
            fail(409, "already_submitted", "本题已提交，不能修改答案")
        return attempt_json(db, row, a)
    if a.revision != data.revision:
        fail(409, "stale_attempt", "作答进度已更新，请重新加载")
    q = next(q for q in row.result["items"] if q["id"] == question_id)
    a.answers = {
        **a.answers,
        question_id: {
            "selected": data.selected,
            "submitted": True,
            "correct": data.selected == q["correct_index"],
        },
    }
    a.revision += 1
    if all(a.answers.get(i, {}).get("submitted") for i in a.question_ids):
        a.status, a.completed_at = "complete", now()
    db.commit()
    return attempt_json(db, row, a)


def resolve_node(db, user_id, notebook_id, context):
    row = owned(db, user_id, context["set_id"])
    require_complete(row, "mindmap")
    if row.notebook_id != notebook_id:
        fail(404, "not_found", "知识点不属于当前笔记本")
    node = next((n for n in row.result["items"] if n["id"] == context["node_id"]), None)
    if not node:
        fail(404, "not_found", "知识点不存在")
    if not valid_sources(db, row):
        fail(409, "source_changed", "资料已更新或删除，请先生成新版导图")
    sources = refs(db, row, set(node["refs"]))
    for s in sources:
        chunk = db.get(Chunk, s["chunk_id"])
        if s["state"] != "active" or not chunk or chunk.document_id != s["document_id"]:
            fail(409, "source_changed", "知识点原始依据已失效")
    return node, sources, [s["id"] for s in row.sources]
