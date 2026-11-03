"""Owned visual documents, immutable revisions and idempotent stage requests."""
import copy
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from . import access, storage, writings
from .db import db_session
from .models import VisualArtifact, VisualRevision, VisualJob, VisualFile, Document, Writing, Notebook, Chunk, now, uid
from .security import current_user, rate_limit
from .errors import fail
from .visual_schema import validate_content, mark_edits, THEMES
from .model_service import ModelError
from .config import settings

router = APIRouter(tags=["演示文稿与信息图"])
ACTIVE = ("queued", "running")

class Params(BaseModel):
    purpose: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=200)
    topic: str = Field(default="", max_length=500)
    mode: Literal["presentation", "reading"] = "presentation"
    count: int = Field(default=8, ge=5, le=15)
    template: Literal["business", "teaching", "research"] = "business"
    color: str = Field(default="", pattern=r"^(?:[0-9a-fA-F]{6})?$")
    form: Literal["overview", "comparison", "process"] = "overview"
    orientation: Literal["portrait", "landscape"] = "portrait"
    density: Literal["low", "standard", "high"] = "standard"

class Create(BaseModel):
    request_key: UUID
    kind: Literal["presentation", "infographic"]
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    writing_ids: list[str] = Field(default_factory=list, max_length=10)
    params: Params = Field(default_factory=Params)
    manual: bool = False

class Edit(BaseModel):
    revision: int = Field(ge=1)
    content: dict
    params: Params

class Action(BaseModel):
    request_key: UUID
    revision: int = Field(ge=1)
    kind: Literal["outline", "pages", "page", "render", "export"]
    page_id: str = Field(default="", max_length=40)
    instruction: str = Field(default="", max_length=1500)
    format: Literal["pptx", "pdf", "png"] = "pdf"


def owned(db, user_id, artifact_id, lock=False):
    row = db.get(VisualArtifact, artifact_id)
    if not row or row.deleted_at:
        fail(404, "not_found", "成果不存在")
    access.notebook(db, user_id, row.notebook_id, lock=lock)
    if lock:
        row = db.scalar(select(VisualArtifact).where(VisualArtifact.id == artifact_id).with_for_update().execution_options(populate_existing=True))
    if not row or row.deleted_at:
        fail(404, "not_found", "成果不存在")
    return row


def snapshot(row):
    return {"kind":row.kind, "title":row.title, "params":copy.deepcopy(row.params), "inputs":copy.deepcopy(row.inputs), "evidence":copy.deepcopy(row.evidence), "content":copy.deepcopy(row.content), "stage":row.stage}


def record(db, row):
    db.add(VisualRevision(artifact_id=row.id, revision=row.revision, snapshot=snapshot(row)))


def job_view(row):
    return {**{k:getattr(row,k) for k in ("id","kind","revision","status","phase","error","attempts","model","usage","created_at")},"result":{k:v for k,v in row.result.items() if k in ("completed","total","failed_page","published_revision")}}


def serialize(db, row, full=True):
    result = {k:getattr(row,k) for k in ("id","notebook_id","kind","title","revision","stage","params","updated_at")}
    jobs = list(db.scalars(select(VisualJob).where(VisualJob.artifact_id==row.id).order_by(VisualJob.created_at.desc()).limit(60)))
    result["jobs"] = [job_view(j) for j in jobs]
    if full:
        result.update(content=row.content, inputs=row.inputs, evidence=[dict(e,state=writings.source_state(db,row.notebook_id,e)) for e in row.evidence])
        result["versions"] = [{"revision":r.revision,"created_at":r.created_at,"stage":r.snapshot["stage"]} for r in db.scalars(select(VisualRevision).where(VisualRevision.artifact_id==row.id).order_by(VisualRevision.revision.desc()))]
        result["files"] = [{**{k:getattr(f,k) for k in ("id","revision","format","ordinal","job_id")},"purpose":db.get(VisualJob,f.job_id).kind} for f in db.scalars(select(VisualFile).where(VisualFile.artifact_id==row.id,VisualFile.status=="ready",VisualFile.job_id.in_(select(VisualJob.id).where(VisualJob.status=="complete"))).order_by(VisualFile.ordinal))]
    states=[]
    for source in row.inputs.get("documents",[]):
        d=db.get(Document,source["id"])
        states.append("deleted" if not d or d.deleted_at else "changed" if d.active_version!=source["version"] else "active")
    states += [writings.source_state(db,row.notebook_id,e) for e in row.evidence]
    for w in row.inputs.get("writings",[]):
        value=db.get(Writing,w["id"])
        states.append("deleted" if not value else "changed" if value.version!=w["version"] else "active")
    result["source_state"] = "deleted" if "deleted" in states else "changed" if "changed" in states else "active"
    return result


def enqueue(db, row, kind, key, extra=None):
    old=db.scalar(select(VisualJob).where(VisualJob.artifact_id==row.id,VisualJob.request_key==key))
    if old:return old
    job=VisualJob(artifact_id=row.id,revision=row.revision,kind=kind,request_key=key,snapshot={**snapshot(row),"evidence":[dict(e,state=writings.source_state(db,row.notebook_id,e)) for e in row.evidence],**(extra or {})})
    db.add(job);db.flush()
    return job


def cancel_artifact(db,row,delete=False):
    for job in db.scalars(select(VisualJob).where(VisualJob.artifact_id==row.id,VisualJob.status.in_(ACTIVE))):
        job.status,job.claim,job.error="cancelled",None,"成果或笔记本已删除" if delete else "用户已取消"
    if delete:
        row.deleted_at=now()
        for f in db.scalars(select(VisualFile).where(VisualFile.artifact_id==row.id,VisualFile.status!="deleted")):
            f.status="deleting"


@router.get("/visual-capabilities")
def capabilities(user=Depends(current_user)):
    return {"templates":THEMES,"max_pages":15,"font":"Noto Sans CJK SC","configured":bool(settings().chat_api_key)}


@router.get("/notebooks/{notebook_id}/visuals")
def listing(notebook_id:str,kind:Literal["presentation","infographic"]|None=None,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),user=Depends(current_user),db=Depends(db_session)):
    access.notebook(db,user.id,notebook_id)
    filters=[VisualArtifact.notebook_id==notebook_id,VisualArtifact.deleted_at.is_(None)]
    if kind:filters.append(VisualArtifact.kind==kind)
    rows=db.scalars(select(VisualArtifact).where(*filters).order_by(VisualArtifact.updated_at.desc()).offset(offset).limit(limit))
    return {"items":[serialize(db,r,False) for r in rows],"total":db.scalar(select(func.count()).select_from(VisualArtifact).where(*filters)),"offset":offset,"limit":limit}


@router.post("/notebooks/{notebook_id}/visuals",status_code=201)
def create(notebook_id:str,data:Create,user=Depends(current_user),db=Depends(db_session)):
    access.notebook(db,user.id,notebook_id,lock=True)
    old=db.scalar(select(VisualArtifact).where(VisualArtifact.notebook_id==notebook_id,VisualArtifact.request_key==str(data.request_key)))
    if old:
        if old.deleted_at:fail(409,"deleted","此创建请求已被删除，请重新创建")
        if old.kind!=data.kind or old.params!=data.params.model_dump() or {d["id"] for d in old.inputs["documents"]}!=set(data.document_ids) or {w["id"] for w in old.inputs["writings"]}!=set(data.writing_ids):
            fail(409,"idempotency","此请求编号已用于不同参数，请新建请求")
        return serialize(db,old)
    rate_limit("visual-create:"+user.id,settings().visual_daily_jobs,86400)
    inputs={"documents":[],"writings":[]}
    for identity in dict.fromkeys(data.document_ids):
        d=access.document(db,user.id,identity)
        if d.notebook_id!=notebook_id or d.status!="ready":fail(422,"source","请选择当前笔记本可用资料")
        inputs["documents"].append({"id":d.id,"version":d.active_version,"filename":d.filename})
    for identity in dict.fromkeys(data.writing_ids):
        w=writings.owned(db,user.id,identity)
        if w.notebook_id!=notebook_id:fail(404,"source","来源不存在")
        writings.ensure_idle(db,w)
        refs=writings.references(db,w)
        inputs["writings"].append({"id":w.id,"version":w.version,"title":w.title,"content":w.content[:6000],"citations":refs,"edited":w.edited})
    if not data.manual and not (inputs["documents"] or inputs["writings"]):fail(422,"source","请选择资料、笔记或报告")
    title="未命名演示文稿" if data.kind=="presentation" else "未命名信息图"
    row=VisualArtifact(notebook_id=notebook_id,request_key=str(data.request_key),kind=data.kind,title=title,params=data.params.model_dump(),inputs=inputs,evidence=[],content={"title":title,"pages":[{"id":"p1","title":"在此填写标题","claim":"","layout":"bullets","points":[],"notes":"","data":[],"edited":True}]},stage="outline")
    db.add(row);db.flush();record(db,row)
    if not data.manual:enqueue(db,row,"outline","initial")
    db.commit();return serialize(db,row)


@router.get("/visuals/{artifact_id}")
def detail(artifact_id:str,user=Depends(current_user),db=Depends(db_session)):
    return serialize(db,owned(db,user.id,artifact_id))


@router.get("/visuals/{artifact_id}/versions/{revision}")
def version(artifact_id:str,revision:int,user=Depends(current_user),db=Depends(db_session)):
    row=owned(db,user.id,artifact_id)
    v=db.scalar(select(VisualRevision).where(VisualRevision.artifact_id==row.id,VisualRevision.revision==revision))
    if not v:fail(404,"version","版本不存在")
    return {"revision":v.revision,"snapshot":{**v.snapshot,"evidence":[dict(e,state=writings.source_state(db,row.notebook_id,e)) for e in v.snapshot["evidence"]]}}


@router.patch("/visuals/{artifact_id}")
def edit(artifact_id:str,data:Edit,user=Depends(current_user),db=Depends(db_session)):
    row=owned(db,user.id,artifact_id,True)
    if row.revision!=data.revision:fail(409,"conflict","内容已更新，请重新加载后合并修改")
    try:content=validate_content(data.content,row.evidence,row.kind)
    except ModelError as exc:fail(422,"content",str(exc))
    content=mark_edits(content,row.content)
    if row.revision>=500:fail(422,"limit","版本数量已达上限，请创建新成果")
    row.content,row.params,row.title=content,data.params.model_dump(),content["title"]
    row.revision+=1;row.updated_at=now();record(db,row)
    db.commit();return serialize(db,row)


@router.post("/visuals/{artifact_id}/jobs",status_code=202)
def action(artifact_id:str,data:Action,user=Depends(current_user),db=Depends(db_session)):
    row=owned(db,user.id,artifact_id,True)
    old=db.scalar(select(VisualJob).where(VisualJob.artifact_id==row.id,VisualJob.request_key==str(data.request_key)))
    if old:
        if old.kind!=data.kind or old.revision!=data.revision or old.snapshot.get("page_id","")!=data.page_id or old.snapshot.get("instruction","")!=data.instruction or (data.kind=="export" and old.snapshot.get("format")!=data.format):fail(409,"idempotency","此请求编号已用于其他操作")
        return job_view(old)
    if row.revision!=data.revision:fail(409,"conflict","版本已更新，请刷新后再操作")
    if data.kind in ("pages","page") and not row.evidence:fail(422,"source","缺少生成证据，请先生成大纲，或直接手动编辑后预览")
    if data.kind=="page" and data.page_id not in {p["id"] for p in row.content["pages"]}:fail(404,"page","页面不存在")
    if data.kind=="export" and ((row.kind=="presentation" and data.format=="png") or (row.kind=="infographic" and data.format=="pptx")):fail(422,"format","此成果不支持该导出格式")
    active_jobs=db.scalars(select(VisualJob).where(VisualJob.artifact_id==row.id,VisualJob.kind==data.kind,VisualJob.revision==row.revision,VisualJob.status.in_(ACTIVE)))
    if any(data.kind!="export" or j.snapshot.get("format")==data.format for j in active_jobs):fail(409,"busy","当前阶段正在执行，请等待或取消")
    rate_limit("visual-jobs:"+user.id,settings().visual_daily_jobs,86400)
    # Rendering is deterministic; reuse an already completed revision rather than producing duplicate files.
    if data.kind=="render":
        cached=db.scalar(select(VisualJob).where(VisualJob.artifact_id==row.id,VisualJob.revision==row.revision,VisualJob.kind=="render",VisualJob.status=="complete"))
        if cached:return job_view(cached)
    job=enqueue(db,row,data.kind,str(data.request_key),{"page_id":data.page_id,"instruction":data.instruction,"format":data.format})
    db.commit();return job_view(job)


@router.post("/visual-jobs/{job_id}/{operation}")
def job_action(job_id:str,operation:Literal["cancel","retry"],user=Depends(current_user),db=Depends(db_session)):
    peek=db.get(VisualJob,job_id)
    if not peek:fail(404,"job","任务不存在")
    row=owned(db,user.id,peek.artifact_id,True)
    job=db.scalar(select(VisualJob).where(VisualJob.id==job_id).with_for_update().execution_options(populate_existing=True))
    if operation=="cancel":
        if job.status in ACTIVE:job.status,job.claim,job.error="cancelled",None,"已停止后续工作；已发出的模型请求可能仍计费"
    else:
        if job.status not in ("failed","cancelled") or job.attempts>=3:fail(409,"retry","此任务无法重试或已达三次上限")
        if job.kind not in ("render","export") and job.revision!=row.revision:fail(409,"version","编辑后请重新发起生成")
        rate_limit("visual-jobs:"+user.id,settings().visual_daily_jobs,86400)
        job.status,job.claim,job.error,job.dispatched_at,job.available_at="queued",None,None,None,now()
    db.commit();return job_view(job)


@router.delete("/visuals/{artifact_id}",status_code=202)
def remove(artifact_id:str,user=Depends(current_user),db=Depends(db_session)):
    row=owned(db,user.id,artifact_id,True);cancel_artifact(db,row,True);db.commit()
    return {"status":"deleting"}


@router.get("/visual-files/{file_id}")
def download(file_id:str,user=Depends(current_user),db=Depends(db_session)):
    f=db.get(VisualFile,file_id)
    if not f:fail(404,"file","文件不存在")
    row=owned(db,user.id,f.artifact_id)
    job=db.get(VisualJob,f.job_id)
    if f.status!="ready" or not job or job.status!="complete":fail(404,"file","文件尚未可用")
    mime={"svg":"image/svg+xml","png":"image/png","pdf":"application/pdf","pptx":"application/vnd.openxmlformats-officedocument.presentationml.presentation"}[f.format]
    name=f"narcissus-v{f.revision}-{f.ordinal+1}.{f.format}"
    return Response(storage.read(f.object_key),media_type=mime,headers={"Cache-Control":"private, no-store","Content-Disposition":f'{"inline" if f.format in ("svg","png") else "attachment"}; filename="{name}"',"Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; sandbox","X-Content-Type-Options":"nosniff"})
