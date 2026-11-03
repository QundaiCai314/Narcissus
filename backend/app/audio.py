from .source_references import position
"""Authorized audio overview API. Script edits and render snapshots are versioned separately."""
import re
from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from .db import db_session
from .models import AudioOverview, AudioRender, AudioSegment, AudioBlob, Notebook, User, now, uid
from .security import current_user, rate_limit
from .errors import fail
from .config import settings
from . import access, storage
from .learning import valid_sources, source_status
from .writings import source_state
from .audio_validation import ScriptEdit, validate_script
from .model_service import ModelError
from .tts_service import VOICES, decode_wav

router = APIRouter(tags=["音频概览"])
ACTIVE_SCRIPT = ["queued", "generating"]
ACTIVE_RENDER = ["queued", "synthesizing", "merging"]

class CreateAudio(BaseModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9-]{8,36}$")
    document_ids: list[str] = Field(min_length=1, max_length=10)
    mode: Literal["single", "duo"] = "single"
    length: Literal["short", "standard", "deep"] = "standard"
    topic: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=200)
    voice_a: str = "cixingnansheng"
    voice_b: str = "wenrounvsheng"

class RenderAudio(BaseModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9-]{8,36}$")
    revision: int = Field(ge=1)
    voice_a: str
    voice_b: str = "wenrounvsheng"

class RetryAudio(BaseModel):
    accept_possible_charge: bool = False

class Regenerate(BaseModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9-]{8,36}$")


def get_overview(db, user, overview_id, lock=False):
    peek = db.get(AudioOverview, overview_id)
    if not peek:
        fail(404, "not_found", "音频概览不存在")
    access.notebook(db, user.id, peek.notebook_id, lock=lock)
    row = db.scalar(select(AudioOverview).where(AudioOverview.id == overview_id).with_for_update().execution_options(populate_existing=True) if lock else select(AudioOverview).where(AudioOverview.id == overview_id))
    if not row or row.deleted_at:
        fail(404, "not_found", "音频概览不存在")
    return row


def get_render(db, user, render_id, lock=False):
    peek = db.get(AudioRender, render_id)
    if not peek:
        fail(404, "not_found", "音频不存在")
    parent = get_overview(db, user, peek.overview_id, lock)
    row = db.scalar(select(AudioRender).where(AudioRender.id == render_id).with_for_update().execution_options(populate_existing=True) if lock else select(AudioRender).where(AudioRender.id == render_id))
    if not row:
        fail(404, "not_found", "音频不存在")
    return parent, row


def voices(a, b):
    if a not in VOICES or b not in VOICES:
        fail(422, "invalid_voice", "请选择语音服务支持的声音")
    return {"A": a, "B": b}


def quota(db, user):
    # The user row serializes cross-notebook admission; workers never acquire it.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    scripts = db.scalar(select(func.count()).select_from(AudioOverview).join(Notebook).where(Notebook.user_id == user.id, AudioOverview.status.in_(ACTIVE_SCRIPT), AudioOverview.deleted_at.is_(None)))
    renders = db.scalar(select(func.count()).select_from(AudioRender).join(AudioOverview).join(Notebook).where(Notebook.user_id == user.id, or_(AudioRender.status.in_(ACTIVE_RENDER), select(AudioSegment.id).where(AudioSegment.render_id == AudioRender.id, AudioSegment.status == "requesting").exists())))
    if scripts + renders >= max(1, settings().audio_user_concurrency):
        fail(429, "audio_concurrency", "正在处理的音频任务较多，请完成或取消后再创建")
    day = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    rate_limit(f"audio-daily:{user.id}:{day}", max(1, settings().audio_daily_limit), 86400)


def citations(db, parent, snapshots=None):
    return [dict(c, state=source_state(db, parent.notebook_id, c)) for c in (parent.citations if snapshots is None else snapshots)]


def render_json(db, row, full=False):
    segments = list(db.scalars(select(AudioSegment).where(AudioSegment.render_id == row.id).order_by(AudioSegment.ordinal)))
    data = {k: getattr(row, k) for k in ("id", "overview_id", "revision", "status", "error", "voices", "model", "duration_ms", "created_at", "usage")}
    data.update(completed_segments=sum(s.status == "complete" for s in segments), total_segments=len(segments), uncertain_segments=sum(s.status in ("uncertain", "requesting") for s in segments), characters=sum(len(s.text) for s in segments))
    if full:
        parent = db.get(AudioOverview, row.overview_id)
        data.update(snapshot=row.snapshot, timeline=row.timeline, citations=citations(db, parent, row.snapshot["citations"]))
        data["segments"] = [{"ordinal": s.ordinal, "status": s.status, "duration_ms": s.duration_ms, "attempts": s.attempts, "usage": s.usage} for s in segments]
    return data


def overview_json(db, row, full=False):
    data = {k: getattr(row, k) for k in ("id", "notebook_id", "title", "status", "error", "params", "revision", "model", "created_at", "usage")}
    data["sources"] = source_status(db, row)
    data["estimated_seconds"] = {"short": 180, "standard": 360, "deep": 600}[row.params["length"]]
    latest = db.scalar(select(AudioRender).where(AudioRender.overview_id == row.id).order_by(AudioRender.created_at.desc()).limit(1))
    data["latest_render"] = render_json(db, latest) if latest else None
    if full:
        data.update(script=row.script, citations=citations(db, row), renders=[render_json(db, r) for r in db.scalars(select(AudioRender).where(AudioRender.overview_id == row.id).order_by(AudioRender.created_at.desc()))])
    return data


@router.get("/audio/options")
def options(user=Depends(current_user)):
    s = settings()
    return {"configured": bool(s.tts_api_key), "voices": [{"id": k, "name": v} for k, v in VOICES.items()], "default_voice": s.tts_default_voice, "second_voice": s.tts_second_voice, "max_chars": min(s.audio_max_chars, 10000), "max_segments": min(s.audio_max_segments, 40)}


@router.get("/notebooks/{notebook_id}/audio")
def listing(notebook_id: str, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), user=Depends(current_user), db=Depends(db_session)):
    access.notebook(db, user.id, notebook_id)
    filters = (AudioOverview.notebook_id == notebook_id, AudioOverview.deleted_at.is_(None))
    return {"items": [overview_json(db, r) for r in db.scalars(select(AudioOverview).where(*filters).order_by(AudioOverview.created_at.desc(), AudioOverview.id).offset(offset).limit(limit))], "total": db.scalar(select(func.count()).select_from(AudioOverview).where(*filters)), "offset": offset, "limit": limit}


@router.post("/notebooks/{notebook_id}/audio", status_code=202)
def create(notebook_id: str, data: CreateAudio, user=Depends(current_user), db=Depends(db_session)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    access.notebook(db, user.id, notebook_id, lock=True)
    existing = db.scalar(select(AudioOverview).where(AudioOverview.notebook_id == notebook_id, AudioOverview.request_key == data.request_key))
    params = data.model_dump(exclude={"request_key", "document_ids"})
    if existing:
        if existing.deleted_at or existing.params != params or sorted(s["id"] for s in existing.sources) != sorted(data.document_ids):
            fail(409, "request_conflict", "请求编号已用于其他内容")
        return overview_json(db, existing, True)
    if len(set(data.document_ids)) != len(data.document_ids):
        fail(422, "duplicate_sources", "资料不能重复选择")
    voices(data.voice_a, data.voice_b)
    sources = []
    for doc_id in sorted(data.document_ids):
        doc = access.document(db, user.id, doc_id)
        if doc.notebook_id != notebook_id or doc.status != "ready":
            fail(422, "invalid_sources", "只能选择本笔记本的可用资料")
        sources.append({"id": doc.id, "filename": doc.filename, "version": doc.active_version})
    quota(db, user)
    row = AudioOverview(notebook_id=notebook_id, request_key=data.request_key, params=params, sources=sources)
    db.add(row); db.commit()
    return overview_json(db, row, True)


@router.get("/audio/{overview_id}")
def detail(overview_id: str, user=Depends(current_user), db=Depends(db_session)):
    return overview_json(db, get_overview(db, user, overview_id), True)


@router.patch("/audio/{overview_id}")
def edit(overview_id: str, data: ScriptEdit, user=Depends(current_user), db=Depends(db_session)):
    row = get_overview(db, user, overview_id, True)
    if row.status != "draft" or data.revision != row.revision:
        fail(409, "version_conflict", "讲稿已变化，请重新加载后编辑")
    try:
        script = validate_script(data.model_dump(), row.params["mode"], row.citations)
    except ModelError as e:
        fail(422, "invalid_script", str(e))
    original = {p["id"]: p for p in row.script["paragraphs"]}
    for p in script["paragraphs"]:
        old = original.get(p["id"])
        p["edited"] = not old or old.get("edited", False) or any(p[k] != old[k] for k in ("text", "speaker", "chapter", "refs"))
    script["intro_edited"] = row.script.get("intro_edited", False) or script["intro"] != row.script.get("intro") or script["title"] != row.script.get("title")
    row.script, row.title, row.revision = script, data.title, row.revision + 1
    db.commit()
    return overview_json(db, row, True)


@router.post("/audio/{overview_id}/regenerate", status_code=202)
def regenerate(overview_id: str, data: Regenerate, user=Depends(current_user), db=Depends(db_session)):
    row = get_overview(db, user, overview_id)
    request = CreateAudio(request_key=data.request_key, document_ids=[s["id"] for s in row.sources], **row.params)
    return create(row.notebook_id, request, user, db)


@router.post("/audio/{overview_id}/retry", status_code=202)
def retry_script(overview_id: str, user=Depends(current_user), db=Depends(db_session)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = get_overview(db, user, overview_id, True)
    if row.status in ACTIVE_SCRIPT:
        return overview_json(db, row, True)
    if row.status not in ("failed", "cancelled") or not valid_sources(db, row):
        fail(409, "invalid_state", "资料已变化或讲稿不能重试，请重新生成")
    quota(db, user)
    row.status, row.error, row.claim, row.attempts, row.dispatched_at, row.available_at = "queued", None, None, 0, None, now()
    db.commit(); return overview_json(db, row, True)


@router.post("/audio/{overview_id}/cancel")
def cancel_script(overview_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = get_overview(db, user, overview_id, True)
    if row.status in ACTIVE_SCRIPT:
        row.status, row.claim, row.error = "cancelled", None, "生成已取消"
    db.commit(); return overview_json(db, row, True)


@router.delete("/audio/{overview_id}", status_code=202)
def remove(overview_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = get_overview(db, user, overview_id, True)
    row.deleted_at, row.status, row.claim = now(), "cancelled", None
    for r in db.scalars(select(AudioRender).where(AudioRender.overview_id == row.id).with_for_update()):
        if r.status in ACTIVE_RENDER:
            r.status, r.claim = "cancelled", None
    db.commit(); return {"status": "deleting"}


@router.post("/audio/{overview_id}/renders", status_code=202)
def render(overview_id: str, data: RenderAudio, user=Depends(current_user), db=Depends(db_session)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    parent = get_overview(db, user, overview_id, True)
    chosen = voices(data.voice_a, data.voice_b)
    existing = db.scalar(select(AudioRender).where(AudioRender.overview_id == overview_id, AudioRender.request_key == data.request_key))
    if existing:
        if existing.revision != data.revision or existing.voices != chosen:
            fail(409, "request_conflict", "请求编号已用于其他讲稿或声音")
        return render_json(db, existing, True)
    if parent.status != "draft" or parent.revision != data.revision:
        fail(409, "version_conflict", "请先保存并确认最新讲稿")
    if not valid_sources(db, parent):
        fail(409, "sources_changed", "来源已更新或删除，请核对后重新生成讲稿")
    if not settings().tts_api_key:
        fail(503, "tts_unconfigured", "尚未配置语音服务")
    # Repeated clicks reuse the same version, including ambiguous failures: retry requires explicit acknowledgement.
    for prior in db.scalars(select(AudioRender).where(AudioRender.overview_id == parent.id, AudioRender.revision == parent.revision)):
        if prior.voices == chosen and prior.model == settings().tts_model and prior.provider == settings().tts_base_url:
            return render_json(db, prior, True)
    quota(db, user)
    render_id = uid()
    prefix = f"audio/{user.id}/{parent.notebook_id}/{parent.id}/{render_id}"
    row = AudioRender(id=render_id, overview_id=parent.id, revision=parent.revision, request_key=data.request_key, snapshot={"script": parent.script, "citations": parent.citations}, voices=chosen, model=settings().tts_model, provider=settings().tts_base_url, object_key=prefix + "/full.wav")
    db.add(row)
    db.add(AudioBlob(object_key=row.object_key, notebook_id=parent.notebook_id, overview_id=parent.id))
    for i, p in enumerate(parent.script["paragraphs"]):
        key = f"{prefix}/{i}.wav"
        db.add(AudioSegment(render_id=render_id, ordinal=i, paragraph_id=p["id"], text=p["text"], voice=chosen[p["speaker"]], object_key=key))
        db.add(AudioBlob(object_key=key, notebook_id=parent.notebook_id, overview_id=parent.id))
    db.commit(); return render_json(db, row, True)


@router.get("/audio-renders/{render_id}")
def render_detail(render_id: str, user=Depends(current_user), db=Depends(db_session)):
    _, row = get_render(db, user, render_id)
    return render_json(db, row, True)


@router.post("/audio-renders/{render_id}/cancel")
def cancel_render(render_id: str, user=Depends(current_user), db=Depends(db_session)):
    _, row = get_render(db, user, render_id, True)
    if row.status in ACTIVE_RENDER:
        row.status, row.claim, row.error = "cancelled", None, "已停止后续合成；已发送的语音请求可能仍会计费"
    db.commit(); return render_json(db, row, True)


@router.post("/audio-renders/{render_id}/retry", status_code=202)
def retry_render(render_id: str, data: RetryAudio, user=Depends(current_user), db=Depends(db_session)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    parent, row = get_render(db, user, render_id, True)
    if row.status in ACTIVE_RENDER + ["complete"]:
        return render_json(db, row, True)
    if not valid_sources(db, parent):
        fail(409, "sources_changed", "来源已更新或删除，不能继续合成")
    segments = list(db.scalars(select(AudioSegment).where(AudioSegment.render_id == row.id).with_for_update()))
    if any(s.status == "requesting" for s in segments):
        fail(409, "request_pending", "上次语音请求仍在处理中，请稍后再试")
    # A response may already be in storage even if the database commit was interrupted.
    for segment in segments:
        if segment.status != "uncertain":
            continue
        try:
            frames = decode_wav(storage.read(segment.object_key))
        except Exception:
            continue
        segment.status, segment.duration_ms = "complete", len(frames) // 48
        usage = {"recovered": True, "characters": len(segment.text), "duration_ms": segment.duration_ms, "provider_usage": None}
        segment.usage = segment.usage + [usage]
        row.usage = row.usage + [dict(usage, segment=segment.ordinal)]
        blob = db.get(AudioBlob, segment.object_key)
        if blob:
            blob.status = "ready"
    if any(s.status == "uncertain" for s in segments) and not data.accept_possible_charge:
        fail(409, "charge_uncertain", "部分请求可能已计费，核查后需明确确认可能重复计费才能重试")
    quota(db, user)
    for s in segments:
        if s.status != "complete":
            s.status, s.attempts = "pending", 0
    row.status, row.claim, row.error, row.dispatched_at, row.available_at = "queued", None, None, None, now()
    db.commit(); return render_json(db, row, True)


@router.get("/audio-renders/{render_id}/file")
def file(render_id: str, request: Request, download: bool = False, user=Depends(current_user), db=Depends(db_session)):
    _, row = get_render(db, user, render_id)
    if row.status != "complete":
        fail(409, "not_ready", "音频尚未完成")
    try:
        data = storage.read(row.object_key)
    except Exception:
        fail(503, "file_unavailable", "暂时无法读取音频，请稍后重试")
    headers = {"Cache-Control": "private, no-store", "Accept-Ranges": "bytes", "Content-Disposition": ('attachment' if download else 'inline') + '; filename="audio-overview.wav"'}
    range_header = request.headers.get("range")
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        start = int(match[1]) if match[1] else max(0, len(data) - int(match[2]))
        end = min(int(match[2]), len(data) - 1) if match[1] and match[2] else len(data) - 1
        if start > end or start >= len(data):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(data[start:end+1], status_code=206, media_type="audio/wav", headers=headers)
    return Response(data, media_type="audio/wav", headers=headers)


@router.get("/audio/{overview_id}/script.md")
def export_script(overview_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = get_overview(db, user, overview_id)
    if not row.script:
        fail(409, "not_ready", "讲稿尚未完成")
    return markdown_script(row.script, citations(db, row))


def markdown_script(script, refs):
    lines = ["# " + script["title"], script.get("intro", "")]
    if script.get("intro_edited"):
        lines += ["标题或简介已修改，请核对依据。"]
    for p in script["paragraphs"]:
        lines += ["## " + p["chapter"], f"讲解者 {p['speaker']}：{p['text']} " + "".join(f"[{n}]" for n in p["refs"])]
        if p.get("edited"):
            lines += ["内容已修改，引用需核对。"]
    lines += ["## 来源"]
    for c in refs:
        lines += [f"[{c['label']}] {c['filename']} · {position(c)}" + ("（原始资料已删除）" if c['state'] == 'deleted' else "（资料已更新）" if c['state'] == 'changed' else ""), c['text']]
    return Response("\n\n".join(lines), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="audio-script.md"'})


@router.get("/audio-renders/{render_id}/script.md")
def render_script(render_id: str, user=Depends(current_user), db=Depends(db_session)):
    parent, row = get_render(db, user, render_id)
    return markdown_script(row.snapshot["script"], citations(db, parent, row.snapshot["citations"]))


def cancel_source(db, notebook_id, document_id=None):
    for parent in db.scalars(select(AudioOverview).where(AudioOverview.notebook_id == notebook_id).order_by(AudioOverview.id).with_for_update()):
        if document_id is not None and not any(s["id"] == document_id for s in parent.sources):
            continue
        if parent.status in ACTIVE_SCRIPT:
            parent.status, parent.claim, parent.error = "cancelled", None, "原始资料已删除或更新"
        for row in db.scalars(select(AudioRender).where(AudioRender.overview_id == parent.id, AudioRender.status.in_(ACTIVE_RENDER)).order_by(AudioRender.id).with_for_update()):
            row.status, row.claim, row.error = "cancelled", None, "来源已变化，已停止后续合成；已发出的请求可能计费"
