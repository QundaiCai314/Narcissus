"""Explicit printed-to-PDF calibration. Never reads page text or infers offsets."""
import hashlib
import io
from uuid import UUID
from pydantic import BaseModel,Field,StrictInt
from pypdf import PdfReader


class SourcePDF(BaseModel):
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    total_pages:StrictInt=Field(ge=1,le=100000)


class PageRange(BaseModel):
    printed_start:StrictInt=Field(ge=1,le=100000)
    printed_end:StrictInt=Field(ge=1,le=100000)
    pdf_start:StrictInt=Field(ge=1,le=100000)
    pdf_end:StrictInt=Field(ge=1,le=100000)
    verified:bool=False


class PageTarget(BaseModel):
    entry_id:str=Field(min_length=1,max_length=80)
    pdf_page:StrictInt=Field(ge=1,le=100000)
    verified:bool=False


class MappingInput(BaseModel):
    source_pdf:SourcePDF
    ranges:list[PageRange]=Field(default_factory=list,max_length=100)
    entry_targets:list[PageTarget]=Field(default_factory=list,max_length=2000)
    confirmed:bool=False
    request_key:UUID
    base_fingerprint:str=Field(default='',max_length=64)
    plan_fingerprint:str=Field(default='',max_length=64)


def identity(data,reader):
    return dict(sha256=hashlib.sha256(data).hexdigest(),total_pages=len(reader.pages))


def metadata(data):
    reader=PdfReader(io.BytesIO(data),strict=False)
    if reader.is_encrypted and not reader.decrypt(''):raise ValueError('PDF需要密码，暂时无法核对页码')
    source=SourcePDF(**identity(data,reader))
    explicit='/PageLabels' in reader.trailer['/Root']
    labels={}
    if explicit:
        if source.total_pages>10000:raise ValueError('页码标签超过本次核对上限，请使用较小的PDF')
        for page,label in enumerate(reader.page_labels,1):
            if label.isdecimal() and 0<int(label)<=100000:labels.setdefault(str(int(label)),[]).append(page)
    return dict(source_pdf=source.model_dump(),explicit_page_labels=explicit,numeric_labels=labels,
        labels_are_candidates=True,text_pages_read=[],model_calls=0,embedding_calls=0)


def validate(data:MappingInput,entries):
    ids={entry['id'] for entry in entries};seen=set();intervals=[];pdf_intervals=[]
    for target in data.entry_targets:
        if target.entry_id not in ids:raise ValueError('单条定位指向了不存在的目录条目')
        if target.entry_id in seen:raise ValueError('同一目录条目有重复定位')
        if target.pdf_page>data.source_pdf.total_pages:raise ValueError('PDF定位页码超出文件总页数')
        seen.add(target.entry_id)
    for rule in data.ranges:
        if rule.printed_start>rule.printed_end or rule.pdf_start>rule.pdf_end:raise ValueError('页码区间的起点不能大于终点')
        if rule.pdf_end>data.source_pdf.total_pages:raise ValueError('PDF区间超出文件总页数')
        if rule.printed_end-rule.printed_start!=rule.pdf_end-rule.pdf_start:
            raise ValueError('区间起止页差不一致，可能有缺页或插页，请拆成多个连续区间')
        if any(not(rule.printed_end<a or rule.printed_start>b) for a,b in intervals):raise ValueError('印刷页码区间重叠，请分开核对')
        if any(not(rule.pdf_end<a or rule.pdf_start>b) for a,b in pdf_intervals):raise ValueError('PDF页码区间重叠，请核对是否指向了相同页面')
        intervals.append((rule.printed_start,rule.printed_end))
        pdf_intervals.append((rule.pdf_start,rule.pdf_end))


def resolve(entries,reference_fingerprint,source_pdf,settings=None):
    bound=source_pdf is not None
    stale=bool(settings) and (settings.get('reference_fingerprint')!=reference_fingerprint or settings.get('source_pdf')!=source_pdf)
    targets={item['entry_id']:item for item in (settings or {}).get('entry_targets',[])} if not stale else {}
    ranges=(settings or {}).get('ranges',[]) if not stale else []
    locations=[]
    for entry in entries:
        page=None;method='unmapped';target=targets.get(entry['id'])
        if target and target.get('verified'):
            page=target['pdf_page'];method='manual_entry'
        elif target:
            method='unverified_entry'
        elif entry.get('printed_page') is not None:
            for rule in ranges:
                if rule.get('verified') and rule['printed_start']<=entry['printed_page']<=rule['printed_end']:
                    page=rule['pdf_start']+entry['printed_page']-rule['printed_start'];method='verified_range';break
        if not bound or stale or page is not None and not 1<=page<=source_pdf['total_pages']:
            page=None;method='stale' if stale else 'unbound' if not bound else 'out_of_bounds'
        toc=entry.get('toc_pdf_page')
        if not bound or toc is not None and not 1<=toc<=source_pdf['total_pages']:toc=None
        locations.append(dict(entry_id=entry['id'],number=entry.get('number'),title=entry['title'],printed_page=entry.get('printed_page'),
            toc_pdf_page=toc,body_pdf_page=page,method=method,verified=page is not None,
            legacy_target_ignored=entry.get('target_pdf_page') is not None))
    mapped=sum(item['verified'] for item in locations)
    return dict(source_bound=bound,stale=stale,source_pdf=source_pdf,entries=len(entries),mapped=mapped,unmapped=len(entries)-mapped,
        locations=locations,model_calls=0,embedding_calls=0,
        reason='目录基准或PDF已变化，请重新核对映射' if stale else '尚未绑定PDF' if not bound else '')


def current(result):
    from .directory_coverage import reference_for
    compiled=reference_for(result)
    if compiled is None:return dict(available=False,reason='请先在章节覆盖核对中保存独立目录基准')
    return dict(available=True,**resolve(compiled['reference']['entries'],compiled['fingerprint'],compiled['reference'].get('source_pdf'),result.get('page_mapping')))


def plan(result,data:MappingInput):
    from .directory_coverage import reference_for,digest
    from .directory_maps import DirectoryMapInput,build
    old=reference_for(result)
    if old is None:raise ValueError('请先在章节覆盖核对中保存独立目录基准')
    source=data.source_pdf.model_dump();existing=old['reference'].get('source_pdf')
    if existing is not None and existing!=source:raise ValueError('该PDF与此版本绑定的文件不同，请选择原文件或新建独立导图')
    reference={**old['reference'],'source_pdf':source}
    compiled=build(DirectoryMapInput(**reference,confirmed=True,request_key=UUID(int=0)))
    validate(data,reference['entries'])
    settings=dict(source_pdf=source,ranges=[r.model_dump() for r in data.ranges],entry_targets=[t.model_dump() for t in data.entry_targets],reference_fingerprint=compiled['fingerprint'])
    report=dict(available=True,**resolve(reference['entries'],compiled['fingerprint'],source,settings))
    pending=sum(not r.verified for r in data.ranges)+sum(not t.verified for t in data.entry_targets)
    base=digest(result);token=digest(dict(base=base,settings=settings))
    return dict(base_fingerprint=base,plan_fingerprint=token,pending=pending,report=report,settings=settings,reference=reference,
        reference_fingerprint=compiled['fingerprint'],has_changes=settings!=result.get('page_mapping') or reference!=result.get('directory_reference'))
