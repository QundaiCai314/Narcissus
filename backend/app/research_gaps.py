"""Explicit, bounded follow-up searches from reviewed report evidence gaps."""
import hashlib,json
from uuid import UUID
from pydantic import BaseModel,Field
from fastapi import APIRouter,Depends
from sqlalchemy import select,func
from . import research,writings,access
from .models import ResearchTask,Writing,Notebook,User
from .db import db_session
from .security import current_user,rate_limit
from .errors import fail
router=APIRouter(tags=['研究证据缺口'])

def plan(db,task):
    root=task.params.get('lineage_root',task.id)
    family=[r for r in db.scalars(select(ResearchTask).where(ResearchTask.notebook_id==task.notebook_id)) if r.id==root or r.params.get('lineage_root')==root]
    report=None
    for link in reversed(task.reports):
        row=db.get(Writing,link['writing_id'])
        job=writings.latest(db,row.id) if row and row.notebook_id==task.notebook_id else None
        if row and not row.edited and job and job.status=='complete' and row.details.get('structured',{}).get('reviewed'):
            report=row;break
    if report is None:return dict(available=False,reason='请先完成一份未经手动改写、已通过证据复核的研究报告。')
    gaps=[]
    existing={' '.join(r.question.lower().split()) for r in family}
    for block in report.details['structured'].get('blocks',[]):
        if block.get('section')!='uncertainties' or block.get('type')!='uncertainty':continue
        query=(task.question[:250]+' '+block['text'][:450]).strip()
        if ' '.join(query.lower().split()) in existing:continue
        gaps.append(dict(id=block['id'],text=block['text'],query=query))
    fingerprint=hashlib.sha256(json.dumps(dict(root=root,report=report.id,version=report.version,gaps=gaps),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(available=True,root_id=root,report_id=report.id,used_rounds=len(family),remaining_rounds=max(0,3-len(family)),gaps=gaps[:5],fingerprint=fingerprint,
        notice='最多3轮搜索；每轮正文获取和报告仍需核对后确认，不自动使用搜索摘要。搜索可能计费。')

@router.get('/research/{research_id}/gap-plan')
def preview(research_id:str,user=Depends(current_user),db=Depends(db_session)):
    return plan(db,research.owned(db,user.id,research_id))

class Followup(BaseModel):
    request_key:UUID
    gap_id:str=Field(min_length=1,max_length=30)
    fingerprint:str=Field(min_length=64,max_length=64)
    confirmed:bool=False

@router.post('/research/{research_id}/follow-up',status_code=202)
def followup(research_id:str,data:Followup,user=Depends(current_user),db=Depends(db_session)):
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    task=research.owned(db,user.id,research_id,True)
    if not data.confirmed:fail(422,'unconfirmed','请确认本轮检索及可能产生的搜索费用')
    previous=db.scalar(select(ResearchTask).where(ResearchTask.notebook_id==task.notebook_id,ResearchTask.request_key==str(data.request_key)))
    if previous:
        if previous.params.get('parent_research')!=task.id or previous.params.get('gap_id')!=data.gap_id or previous.params.get('gap_plan')!=data.fingerprint:fail(409,'idempotency_conflict','请求编号已用于其他研究')
        return research.serialize(db,previous)
    value=plan(db,task)
    if not value['available']:fail(409,'report_required',value['reason'])
    if not value['remaining_rounds']:fail(429,'round_limit','此研究已达到3轮上限')
    if value['fingerprint']!=data.fingerprint:fail(409,'plan_changed','报告或检索计划已改变，请重新预览')
    gap=next((g for g in value['gaps'] if g['id']==data.gap_id),None)
    if not gap:fail(422,'gap_missing','缺口已检索或不存在')
    active=db.scalar(select(func.count()).select_from(ResearchTask).join(Notebook).where(Notebook.user_id==user.id,ResearchTask.status.in_(research.ACTIVE)))
    if active>=research.settings().research_user_concurrency:fail(429,'research_limit','同时进行的搜索已达上限')
    rate_limit('research-create:'+user.id,60,86400)
    row=ResearchTask(notebook_id=task.notebook_id,request_key=str(data.request_key),question=gap['query'],params={**task.params,'lineage_root':value['root_id'],'parent_research':task.id,'gap_id':data.gap_id,'gap_plan':data.fingerprint})
    db.add(row);db.commit();return research.serialize(db,row)
