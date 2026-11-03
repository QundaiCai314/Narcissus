"""Owned research workflow. Candidates are private previews until explicitly imported."""

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from . import access, writings
from .config import settings
from .db import db_session
from .errors import fail
from .models import (
    Document,
    GenerationJob,
    Notebook,
    ResearchCandidate,
    ResearchTask,
    SourceVersion,
    User,
    Writing,
    now,
)
from .pdf_processing import InvalidPDF
from .search_service import canonical_url, credential
from .security import current_user, rate_limit
from .source_parsing import make_chunks, text_units

router = APIRouter(tags=["联网研究"])
ACTIVE = ("queued", "running")


def owned(db, user_id, research_id, lock=False):
    row = db.get(ResearchTask, research_id)
    if not row:
        fail(404, "not_found", "研究任务不存在")
    access.notebook(db, user_id, row.notebook_id, lock=lock)
    if lock:
        row = db.scalar(
            select(ResearchTask)
            .where(ResearchTask.id == research_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if not row:
        fail(404, "not_found", "研究任务不存在")
    return row


def candidate(db, task, candidate_id):
    row = db.scalar(
        select(ResearchCandidate)
        .where(
            ResearchCandidate.id == candidate_id,
            ResearchCandidate.research_id == task.id,
        )
        .with_for_update()
    )
    if not row:
        fail(404, "not_found", "候选来源不存在")
    return row


def existing_document(db, task, row):
    if row.document_id:
        doc = db.get(Document, row.document_id)
        return doc if doc and not doc.deleted_at else None
    pairs = db.execute(
        select(Document, SourceVersion.source_url)
        .join(SourceVersion)
        .where(
            Document.notebook_id == task.notebook_id,
            Document.deleted_at.is_(None),
            SourceVersion.source_url.is_not(None),
        )
    )
    for doc, url in pairs:
        try:
            if canonical_url(url) == row.url:
                return doc
        except InvalidPDF:
            continue
    return None


def candidate_view(db, task, row, full=False):
    doc = db.get(Document, row.document_id) if row.document_id else None
    state, error = row.status, row.error
    if doc and not doc.deleted_at:
        state = "ready" if doc.status == "ready" else "importing"
        if doc.status == "uploading" and row.status == "failed":
            state, error = "failed", row.error
        if doc.status in ("failed", "cancelled", "awaiting_confirmation"):
            state, error = doc.status, doc.error
    elif row.details.get("imported"):
        state, error = "deleted", "已导入的原始资料已删除"
    found = existing_document(db, task, row)
    result = {
        k: getattr(row, k)
        for k in (
            "id",
            "title",
            "url",
            "snippet",
            "rank",
            "selected",
            "document_id",
            "action",
            "attempts",
            "usage",
        )
    }
    result.update(
        status=state,
        error=error,
        domain=urlsplit(row.url).hostname,
        existing_document_id=found.id if found else None,
        published_at=row.details.get("published_at"),
        fetched_at=row.details.get("fetched_at"),
        relevance="由搜索服务按本次检索词返回；正文与研究问题的相关性需在预览后核对。",
    )
    if full:
        result.update(
            units=row.units,
            details={k: v for k, v in row.details.items() if k != "original_units"},
        )
    return result


def serialize(db, row, full=True):
    result = {
        k: getattr(row, k)
        for k in (
            "id",
            "question",
            "params",
            "status",
            "error",
            "queries",
            "attempts",
            "usage",
            "created_at",
        )
    }
    result["reports"] = [
        dict(
            item,
            writing=writings.serialize(db, w, False)
            if (w := db.get(Writing, item["writing_id"]))
            else None,
        )
        for item in row.reports
    ]
    if full:
        result["candidates"] = [
            candidate_view(db, row, c)
            for c in db.scalars(
                select(ResearchCandidate)
                .where(ResearchCandidate.research_id == row.id)
                .order_by(ResearchCandidate.rank)
            )
        ]
    return result


def active_check(task):
    if task.status != "complete":
        fail(409, "research_not_ready", "请等待搜索完成；已取消的任务不能继续调度")


@router.get("/research-capabilities")
def capabilities(user=Depends(current_user)):
    s = settings()
    return {
        "configured": bool(credential()),
        "provider": "阶跃星辰",
        "time_filter": False,
        "language_filter": False,
        "notice": "服务暂不提供语言或时间筛选。语言作为检索词偏好，不保证结果语言；时间未知的来源不推断发布时间。",
        "max_results": min(20, s.research_max_results),
        "max_fetches": s.research_max_fetches,
        "daily_searches": s.research_daily_searches,
    }


class CreateInput(BaseModel):
    request_key: UUID
    question: str = Field(min_length=2, max_length=1000)
    requirements: str = Field(default="", max_length=1500)
    language: Literal["zh", "en", "any"] = "zh"
    time_range: Literal["any"] = "any"


@router.post("/notebooks/{notebook_id}/research", status_code=202)
def create(
    notebook_id: str,
    data: CreateInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    nb = access.notebook(db, user.id, notebook_id, lock=True)
    previous = db.scalar(
        select(ResearchTask).where(
            ResearchTask.notebook_id == notebook_id,
            ResearchTask.request_key == str(data.request_key),
        )
    )
    if previous:
        if (
            previous.question != data.question.strip()
            or previous.params["requirements"] != data.requirements
            or previous.params["language"] != data.language
        ):
            fail(
                409, "idempotency_conflict", "此请求编号已用于不同研究问题，请重新提交"
            )
        return serialize(db, previous)
    active = db.scalar(
        select(func.count())
        .select_from(ResearchTask)
        .join(Notebook)
        .where(Notebook.user_id == user.id, ResearchTask.status.in_(ACTIVE))
    )
    if active >= settings().research_user_concurrency:
        fail(429, "research_limit", "同时进行的搜索已达上限，请稍后再试")
    rate_limit("research-create:" + user.id, 60, 86400)
    row = ResearchTask(
        notebook_id=nb.id,
        request_key=str(data.request_key),
        question=data.question.strip(),
        params={
            "requirements": data.requirements,
            "language": data.language,
            "time_range": "any",
            "provider": "stepfun",
        },
    )
    db.add(row)
    db.commit()
    return serialize(db, row)


@router.get("/notebooks/{notebook_id}/research")
def listing(
    notebook_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_session),
):
    access.notebook(db, user.id, notebook_id)
    query = select(ResearchTask).where(ResearchTask.notebook_id == notebook_id)
    return {
        "items": [
            serialize(db, x, False)
            for x in db.scalars(
                query.order_by(ResearchTask.created_at.desc(), ResearchTask.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "offset": offset,
        "limit": limit,
        "total": db.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .where(ResearchTask.notebook_id == notebook_id)
        ),
    }


@router.get("/research/{research_id}")
def detail(research_id: str, user=Depends(current_user), db=Depends(db_session)):
    return serialize(db, owned(db, user.id, research_id))


@router.get("/research/{research_id}/sources/{candidate_id}")
def preview(
    research_id: str,
    candidate_id: str,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id)
    return candidate_view(db, task, candidate(db, task, candidate_id), True)


@router.post("/research/{research_id}/sources/{candidate_id}/fetch", status_code=202)
def fetch(
    research_id: str,
    candidate_id: str,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id, True)
    active_check(task)
    row = candidate(db, task, candidate_id)
    if row.units and row.status == "cancelled" and not row.document_id:
        row.status, row.error = "preview", None
        db.commit()
    if row.units or row.status in ACTIVE or row.document_id:
        return candidate_view(db, task, row, True)
    candidates = list(
        db.scalars(
            select(ResearchCandidate).where(ResearchCandidate.research_id == task.id)
        )
    )
    if (
        sum(c.attempts for c in candidates)
        + sum(c.status == "queued" for c in candidates)
        >= settings().research_max_fetches
    ):
        fail(
            429, "fetch_limit", "本次研究的网页获取次数已用完，可粘贴正文或创建新的研究"
        )
    if row.attempts >= settings().research_max_attempts:
        fail(429, "retry_limit", "此来源已达到重试上限")
    row.status, row.action, row.error, row.dispatched_at, row.available_at = (
        "queued",
        "fetch",
        None,
        None,
        now(),
    )
    db.commit()
    return candidate_view(db, task, row)


class ImportInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    text: str | None = Field(default=None, min_length=100, max_length=500000)
    use_existing: bool = False


@router.post("/research/{research_id}/sources/{candidate_id}/import", status_code=202)
def import_candidate(
    research_id: str,
    candidate_id: str,
    data: ImportInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id, True)
    active_check(task)
    row = candidate(db, task, candidate_id)
    if (
        row.document_id
        and row.status == "failed"
        and (doc := db.get(Document, row.document_id))
        and not doc.deleted_at
        and doc.status == "uploading"
    ):
        row.status, row.error, row.claim, row.dispatched_at, row.available_at = (
            "queued",
            None,
            None,
            None,
            now(),
        )
        db.commit()
        return candidate_view(db, task, row)
    if row.document_id or (row.action == "import" and row.status in ACTIVE):
        return candidate_view(db, task, row)
    existing = existing_document(db, task, row)
    if existing:
        if not data.use_existing:
            fail(409, "duplicate", "网页已在当前笔记本中，请确认使用已有资料")
        row.document_id, row.selected, row.status = existing.id, True, "imported"
        row.details = {**row.details, "imported": True}
    else:
        if not row.units or row.status not in ("preview", "failed"):
            fail(409, "preview_required", "请先获取并核对网页正文")
        if data.text is not None:
            try:
                units = text_units(data.text)
                make_chunks(units)
            except InvalidPDF as exc:
                fail(422, "invalid_content", str(exc))
            row.units = units
            row.details = {**row.details, "user_adjusted": True}
        if data.title:
            row.title = data.title.strip()
        (
            row.action,
            row.status,
            row.selected,
            row.error,
            row.dispatched_at,
            row.available_at,
        ) = "import", "queued", True, None, None, now()
    db.commit()
    return candidate_view(db, task, row)


@router.post("/research/{research_id}/sources/{candidate_id}/cancel")
def cancel_candidate(
    research_id: str,
    candidate_id: str,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id, True)
    row = candidate(db, task, candidate_id)
    stop_candidate(db, row)
    db.commit()
    return candidate_view(db, task, row)


class ReportInput(BaseModel):
    request_key: UUID
    candidate_ids: list[str] = Field(default_factory=list, max_length=20)
    document_ids: list[str] = Field(default_factory=list, max_length=10)


class SelectionInput(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list, max_length=20)
    document_ids: list[str] = Field(default_factory=list, max_length=10)


@router.put("/research/{research_id}/selection")
def selection(
    research_id: str,
    data: SelectionInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id, True)
    active_check(task)
    rows = list(
        db.scalars(
            select(ResearchCandidate).where(ResearchCandidate.research_id == task.id)
        )
    )
    if not set(data.candidate_ids) <= {c.id for c in rows}:
        fail(422, "invalid_selection", "所选来源不属于本次研究")
    for identity in data.document_ids:
        doc = access.document(db, user.id, identity)
        if doc.notebook_id != task.notebook_id:
            fail(422, "invalid_selection", "所选资料不属于此笔记本")
    for row in rows:
        row.selected = row.id in data.candidate_ids
    task.params = {
        **task.params,
        "selected_document_ids": list(dict.fromkeys(data.document_ids)),
    }
    db.commit()
    return serialize(db, task)


@router.post("/research/{research_id}/reports", status_code=202)
def report(
    research_id: str,
    data: ReportInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    task = owned(db, user.id, research_id, True)
    active_check(task)
    for item in task.reports:
        if item["request_key"] == str(data.request_key):
            return item
    if len(task.reports) >= 10:
        fail(429, "report_limit", "每次研究最多保存 10 个报告版本")
    for item in task.reports:
        if (job := writings.latest(db, item["writing_id"])) and job.status in ACTIVE:
            fail(409, "generating", "本次研究已有报告正在生成")
    ids = set(data.document_ids)
    for identity in set(data.candidate_ids):
        source = candidate(db, task, identity)
        if not source.document_id:
            fail(422, "not_imported", "报告只能使用已成功导入的正文")
        ids.add(source.document_id)
    if not ids or len(ids) > 10:
        fail(422, "source_required", "请选择 1 至 10 份可用的原始资料")
    sources = []
    for identity in sorted(ids):
        doc = access.document(db, user.id, identity)
        if doc.notebook_id != task.notebook_id or doc.status != "ready":
            fail(422, "not_ready", "所选资料不属于此笔记本或尚未可用")
        ver = db.scalar(
            select(SourceVersion).where(
                SourceVersion.document_id == doc.id,
                SourceVersion.version == doc.active_version,
            )
        )
        sources.append(
            {
                "id": doc.id,
                "version": doc.active_version,
                "filename": doc.filename,
                "source_url": ver.source_url if ver else None,
                "fetched_at": ver.details.get("fetched_at") if ver else None,
            }
        )
    rate_limit("research-report:" + user.id, 20, 86400)
    row = Writing(
        notebook_id=task.notebook_id,
        kind="summary",
        title=("研究报告 · " + task.question)[:120],
    )
    db.add(row)
    db.flush()
    excluded = [
        {
            "title": c.title,
            "url": c.url,
            "status": candidate_view(db, task, c)["status"],
            "error": c.error,
        }
        for c in db.scalars(
            select(ResearchCandidate).where(ResearchCandidate.research_id == task.id)
        )
        if c.document_id not in ids
    ]
    request = {
        "documents": sources,
        "notes": [],
        "purpose": task.question,
        "audience": "研究资料阅读者",
        "length": "long",
        "research": {
            "id": task.id,
            "question": task.question,
            "params": task.params,
            "queries": task.queries,
            "excluded": excluded,
        },
    }
    row.details = {"inputs": request}
    writings.enqueue(db, row, request)
    link = {
        "request_key": str(data.request_key),
        "writing_id": row.id,
        "version": len(task.reports) + 1,
        "created_at": now().isoformat(),
        "sources": sources,
    }
    task.reports = [*task.reports, link]
    for c in db.scalars(
        select(ResearchCandidate).where(ResearchCandidate.research_id == task.id)
    ):
        c.selected = c.id in data.candidate_ids
    db.commit()
    return link


def stop_candidate(db, row):
    from .models import Job
    from .tasks import tombstone

    row.selected = False
    if row.document_id:
        doc = db.scalar(
            select(Document).where(Document.id == row.document_id).with_for_update()
        )
        ver = db.scalar(
            select(SourceVersion).where(
                SourceVersion.document_id == row.document_id, SourceVersion.version == 1
            )
        )
        # Never cancel a pre-existing source used by another workflow.
        if (
            doc
            and ver
            and not doc.active_version
            and ver.details.get("candidate_id") == row.id
            and not doc.deleted_at
        ):
            if doc.status == "uploading":
                tombstone(db, doc)
                row.document_id = None
            elif doc.status in ("queued", "processing", "indexing"):
                db.execute(
                    update(Job)
                    .where(
                        Job.document_id == doc.id, Job.status.in_(["queued", "running"])
                    )
                    .values(status="cancelled", claim=None)
                )
                doc.status = ver.status = "cancelled"
                doc.error = ver.error = "研究来源导入已取消，可在资料列表重试"
    if not row.document_id or row.status in ACTIVE:
        row.status, row.claim = "cancelled", None


def cancel(db, task):
    task.status, task.claim = "cancelled", None
    for row in db.scalars(
        select(ResearchCandidate)
        .where(ResearchCandidate.research_id == task.id)
        .with_for_update()
    ):
        stop_candidate(db, row)
    for item in task.reports:
        db.execute(
            update(GenerationJob)
            .where(
                GenerationJob.writing_id == item["writing_id"],
                GenerationJob.status.in_(ACTIVE),
            )
            .values(status="cancelled", claim=None, error="研究任务已取消")
        )


@router.post("/research/{research_id}/cancel")
def cancel_task(research_id: str, user=Depends(current_user), db=Depends(db_session)):
    task = owned(db, user.id, research_id, True)
    cancel(db, task)
    db.commit()
    return serialize(db, task)


@router.post("/research/{research_id}/retry", status_code=202)
def retry(research_id: str, user=Depends(current_user), db=Depends(db_session)):
    task = owned(db, user.id, research_id, True)
    if task.status not in ("failed", "cancelled"):
        return serialize(db, task)
    has_results = any(entry.get("completed_at") for entry in task.usage)
    if not has_results and task.attempts >= settings().research_max_attempts:
        fail(429, "retry_limit", "搜索已达到重试上限，请检查配置后新建研究")
    task.status, task.error, task.dispatched_at, task.available_at = (
        "complete" if has_results else "queued",
        None,
        None,
        now(),
    )
    db.commit()
    return serialize(db, task)


@router.delete("/research/{research_id}", status_code=204)
def delete_task(research_id: str, user=Depends(current_user), db=Depends(db_session)):
    task = owned(db, user.id, research_id, True)
    cancel(db, task)
    db.delete(
        task
    )  # Imported sources and saved writings deliberately survive this deletion.
    db.commit()
