"""Deterministic directory trees. No body retrieval, embeddings or generation."""
import hashlib
import json
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, StrictInt


class DirectoryEntry(BaseModel):
    id:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    parent_id:str|None=Field(default=None,max_length=80)
    kind:Literal['part','chapter','section','appendix','reference','bookmark']
    number:str|None=Field(default=None,max_length=30)
    title:str=Field(min_length=1,max_length=180)
    printed_page:StrictInt|None=Field(default=None,ge=1,le=100000)
    toc_pdf_page:StrictInt|None=Field(default=None,ge=1,le=100000)
    target_pdf_page:StrictInt|None=Field(default=None,ge=1,le=100000)
    needs_review:bool=False
    reviewed:bool=False


class DirectoryMapInput(BaseModel):
    title:str=Field(min_length=1,max_length=100)
    source_name:str=Field(default='',max_length=240)
    entries:list[DirectoryEntry]=Field(min_length=1,max_length=2000)
    pages_read:list[StrictInt]=Field(default_factory=list,max_length=12)
    unresolved_lines:StrictInt=Field(default=0,ge=0)
    failed_pages:list[StrictInt]=Field(default_factory=list,max_length=12)
    confirmed:bool=False
    request_key:UUID


def chapter_number(value):
    match=re.fullmatch(r'第([\d一二三四五六七八九十百]+)章',value or '')
    if not match:return None
    text=match[1]
    if text.isdecimal():return str(int(text))
    digits={c:i for i,c in enumerate('零一二三四五六七八九')}
    if text in digits:return str(digits[text])
    if text.count('十')==1:
        left,right=text.split('十')
        if (not left or left in digits) and (not right or right in digits):
            return str((digits[left] if left else 1)*10+(digits[right] if right else 0))
    return None


def build(data:DirectoryMapInput):
    if data.unresolved_lines or data.failed_pages:
        raise ValueError('还有未解析的目录行或失败页，请补齐目录后再生成导图')
    if len(set(data.pages_read))!=len(data.pages_read) or any(p<1 for p in data.pages_read):
        raise ValueError('目录来源页码无效')
    by_id={e.id:e for e in data.entries}
    if len(by_id)!=len(data.entries) or '__outline_root__' in by_id:raise ValueError('目录节点编号重复或保留编号冲突')
    numbers=set();depths={}
    for entry in data.entries:
        if not entry.title.strip():raise ValueError('目录标题不能为空')
        if entry.number:
            if entry.number in numbers:raise ValueError(f'目录编号{entry.number}重复')
            numbers.add(entry.number)
        parent=by_id.get(entry.parent_id) if entry.parent_id else None
        if entry.parent_id and parent is None:raise ValueError(f'{entry.number or entry.title}缺少上级目录')
        seen={entry.id};current=entry;depth=1
        while current.parent_id:
            if current.parent_id in seen:raise ValueError('目录层级存在循环')
            seen.add(current.parent_id);current=by_id.get(current.parent_id)
            if current is None:raise ValueError('目录缺少上级节点')
            depth+=1
            if depth>12:raise ValueError('目录层级超过12层')
        depths[entry.id]=depth
        if entry.kind in ['part','appendix','reference'] and parent:raise ValueError(f'{entry.title}应位于目录顶层')
        if entry.kind=='chapter' and parent and parent.kind!='part':raise ValueError(f'{entry.title}必须归属部分或目录顶层')
        if entry.kind=='section':
            number=re.fullmatch(r'(?:\d+|[A-Z])(?:\.\d+){1,4}',entry.number or '')
            if not number or parent is None:raise ValueError(f'{entry.title}的小节编号或上级无效')
            expected=entry.number.rsplit('.',1)[0]
            actual=chapter_number(parent.number) if parent.kind=='chapter' else (parent.number or '').replace('附录','') if parent.kind=='appendix' else parent.number
            if actual!=expected:raise ValueError(f'编号{entry.number}应归属{expected}，请核对层级')
    root=dict(id='__outline_root__',parent_id=None,title=data.title.strip(),refs=[],explanation='书名导航')
    items=[root]+[dict(id=e.id,parent_id=e.parent_id or root['id'],title=((e.number+' ') if e.number else '')+e.title.strip(),
        refs=[],explanation='',source_entry_id=e.id,directory=e.model_dump()) for e in data.entries]
    summary=dict(entry_count=len(data.entries),covered_entries=len(items)-1,node_count=len(items),
        chapter_count=sum(e.kind=='chapter' for e in data.entries),part_count=sum(e.kind=='part' for e in data.entries),
        directory_depth=max(depths.values()),map_depth=max(depths.values())+1,source_name=data.source_name,
        pages_read=data.pages_read,model_calls=0,embedding_calls=0,
        review_pending=sum(e.needs_review and not e.reviewed for e in data.entries))
    canonical=dict(title=data.title.strip(),source_name=data.source_name,entries=[e.model_dump() for e in data.entries],pages_read=data.pages_read)
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(items=items,outline=summary,fingerprint=fingerprint,reference=canonical,reference_confirmed=data.confirmed)
