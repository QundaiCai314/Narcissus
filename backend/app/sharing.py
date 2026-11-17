"""Opt-in note collaboration; existing private API permissions stay owner-only."""
from typing import Literal
from pydantic import BaseModel,EmailStr,Field
from fastapi import APIRouter,Depends
from sqlalchemy import select
from . import access
from .models import User,Notebook,NotebookMember,Writing,now
from .config import settings
from .db import db_session
from .security import current_user,rate_limit
from .errors import fail
router=APIRouter(tags=['手记协作'])

def enabled():
    if not settings().collaboration_enabled:fail(503,'sharing_disabled','手记协作尚未启用，请先完成权限表迁移与管理员配置')

@router.get('/sharing-capabilities')
def capabilities(user=Depends(current_user)):
    return dict(enabled=settings().collaboration_enabled,scope='notes',roles=['viewer','editor'],notice='仅共享手记；原始文件、对话、作答及其他成果不开放。')

def permission(db,user_id,notebook_id,write=False):
    enabled();nb=db.scalar(select(Notebook).where(Notebook.id==notebook_id).with_for_update().execution_options(populate_existing=True)) if write else db.get(Notebook,notebook_id)
    if not nb or nb.deleted_at:fail(404,'not_found','共享笔记本不存在')
    if nb.user_id==user_id:return nb,'owner'
    member=db.get(NotebookMember,(notebook_id,user_id))
    if not member:fail(404,'not_found','共享笔记本不存在')
    if write and member.role!='editor':fail(403,'read_only','当前账号只有阅读权限')
    return nb,member.role

@router.get('/notebooks/{notebook_id}/members')
def members(notebook_id:str,user=Depends(current_user),db=Depends(db_session)):
    enabled();access.notebook(db,user.id,notebook_id)
    rows=db.execute(select(NotebookMember,User.email).join(User).where(NotebookMember.notebook_id==notebook_id))
    return dict(items=[dict(user_id=m.user_id,email=email,role=m.role) for m,email in rows])

class Grant(BaseModel):
    email:EmailStr
    role:Literal['viewer','editor']='viewer'

@router.put('/notebooks/{notebook_id}/members')
def grant(notebook_id:str,data:Grant,user=Depends(current_user),db=Depends(db_session)):
    enabled();access.notebook(db,user.id,notebook_id,lock=True);rate_limit('share:'+user.id,60,3600)
    target=db.scalar(select(User).where(User.email==str(data.email).lower()))
    if not target:fail(422,'account_required','对方需先注册Narcissus账号')
    if target.id==user.id:fail(422,'owner','不能修改所有者角色')
    row=db.get(NotebookMember,(notebook_id,target.id))
    if row:row.role=data.role
    else:db.add(NotebookMember(notebook_id=notebook_id,user_id=target.id,role=data.role))
    db.commit();return dict(user_id=target.id,role=data.role)

@router.delete('/notebooks/{notebook_id}/members/{member_id}',status_code=204)
def revoke(notebook_id:str,member_id:str,user=Depends(current_user),db=Depends(db_session)):
    enabled();access.notebook(db,user.id,notebook_id,lock=True)
    row=db.get(NotebookMember,(notebook_id,member_id))
    if row:db.delete(row);db.commit()

def note_view(row):return dict(id=row.id,title=row.title,content=row.content,version=row.version,updated_at=row.updated_at)

@router.get('/shared-notebooks/{notebook_id}')
def read(notebook_id:str,user=Depends(current_user),db=Depends(db_session)):
    nb,role=permission(db,user.id,notebook_id)
    notes=db.scalars(select(Writing).where(Writing.notebook_id==nb.id,Writing.kind=='note').order_by(Writing.updated_at.desc()))
    return dict(id=nb.id,name=nb.name,role=role,notes=[note_view(row) for row in notes])

class NoteEdit(BaseModel):
    title:str=Field(min_length=1,max_length=120)
    content:str=Field(max_length=100000)
    version:int=Field(ge=1)

@router.put('/shared-notebooks/{notebook_id}/notes/{note_id}')
def edit(notebook_id:str,note_id:str,data:NoteEdit,user=Depends(current_user),db=Depends(db_session)):
    permission(db,user.id,notebook_id,True)
    if not data.title.strip():fail(422,'title_required','手记标题不能为空')
    row=db.scalar(select(Writing).where(Writing.id==note_id,Writing.notebook_id==notebook_id,Writing.kind=='note').with_for_update())
    if not row:fail(404,'not_found','手记不存在')
    from .writings import ensure_idle
    ensure_idle(db,row)
    if row.version!=data.version:fail(409,'version_changed','手记已由其他人修改，请重新加载后再编辑')
    row.title=data.title.strip();row.content=data.content;row.version+=1;row.edited=True;row.updated_at=now();db.commit();return note_view(row)
