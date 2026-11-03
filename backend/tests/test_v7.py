"""V7: real storage/DB/worker, explicit model protocol fixture; rendering uses real fonts/tools."""
import copy
import io
import json
import uuid
import zipfile
import asyncio
from datetime import timedelta
import httpx
import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from app.db import SessionLocal
from app.models import VisualJob, VisualFile, VisualArtifact, now
from app.visual_schema import validate_content
from app.visual_render import scene, svg, png, export
from app.visuals import Params
from app.model_service import ModelError
from app import visual_tasks


def test_chinese_wrap_preserves_identifiers_and_citation_tokens():
    from app.visual_render import wrap
    text='中文is_private与is_global，地址100.64.0.0/10需单独核对。[19] [25]'
    lines=wrap(text,300,30)
    assert ''.join(lines)==text
    for token in ['is_private','is_global','100.64.0.0/10','[19]','[25]']:
        assert any(token in line for line in lines)
    assert not any(line.startswith(('，','。','；','：')) for line in lines)
    with pytest.raises(ModelError,match='栏宽'):wrap('very_long_identifier',20,30)
from .test_integration import ctx as ctx, call, wait_for, MODEL

TEXT='青禾社区阅读计划为测试样本文档。2025年参与人数为120人，2026年参与人数为180人。活动分为报名、阅读、讨论三个步骤。资料要求保留年份，不把不同年份人数直接当作同一时期总人数。'
EVIDENCE=[{'label':1,'kind':'document','document_id':'d','chunk_id':'c','version':1,'filename':'中文样本文档','position':'第1段','text':TEXT}]


def test_visual_historical_labels_do_not_enter_model_namespace(monkeypatch):
    evidence=copy.deepcopy(EVIDENCE)+[{'label':2,'kind':'note','text':'用户观点[60]、原引文[19, 25]。','note_id':'private-metadata'}]
    compact=visual_tasks.model_evidence(evidence)
    assert compact[1]['text']=='用户观点（原笔记引文标记）、原引文（原笔记引文标记）。'
    assert evidence[1]['text']=='用户观点[60]、原引文[19, 25]。'
    assert all(set(e)=={'label','kind','text'} for e in compact)
    calls=[]
    async def complete(messages,usages,max_tokens=None,**options):
        calls.append((messages,options))
        return json.dumps({'approved':True}) if len(calls)==2 else json.dumps(sample(),ensure_ascii=False)
    monkeypatch.setattr(visual_tasks,'complete',complete)
    snap={'kind':'infographic','params':Params(count=8).model_dump()}
    result=asyncio.run(visual_tasks.generate(snap,'outline',evidence,None,[],None))
    assert len(result['pages'])==1 and snap['params']['count']==8
    payload=json.loads(calls[0][0][1]['content'])
    assert payload['params']['count']==1 and payload['evidence']==compact
    assert 'pages必须恰好一项' in calls[0][0][0]['content']
    checks=json.loads(calls[1][0][1]['content'])['checks']
    assert json.loads(calls[1][0][1]['content'])['generation_parameters']['count']==1
    assert checks[0]['evidence']==compact[:1]  # Uncited report text cannot validate this page.


def test_visual_support_review_repairs_once(monkeypatch):
    calls=[]
    async def complete(messages,usages,max_tokens=None,**options):
        calls.append(messages)
        if len(calls)==2:return json.dumps({'approved':False,'reason':'备注包含原文未提及的背景'})
        if len(calls)==4:return json.dumps({'approved':True})
        return json.dumps(sample(),ensure_ascii=False)
    monkeypatch.setattr(visual_tasks,'complete',complete)
    snap={'kind':'presentation','params':Params().model_dump()}
    result=asyncio.run(visual_tasks.generate(snap,'outline',EVIDENCE,None,[],None))
    assert len(calls)==4 and len(result['pages'])==1
    assert '原文未提及的背景' in json.loads(calls[2][1]['content'])['previous_error']


@pytest.mark.parametrize('enabled',[False,True])
def test_model_structured_options_are_opt_in(monkeypatch,enabled):
    from app import model_service
    captured=[]
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n')
    original=httpx.AsyncClient
    monkeypatch.setattr(model_service.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    monkeypatch.setattr(model_service.settings(),'chat_api_key','test-not-a-real-key')
    async def run():
        options={'json_mode':True,'reasoning_effort':'low'} if enabled else {}
        return [part async for part in model_service.chat_stream([{'role':'user','content':'JSON'}],**options)]
    assert asyncio.run(run())==[{'text':'{}'}]
    if enabled:
        assert captured[0]['response_format']=={'type':'json_object'} and captured[0]['reasoning_effort']=='low'
    else:
        assert 'response_format' not in captured[0] and 'reasoning_effort' not in captured[0]

def sample(layout='bullets'):
    page={'id':'p1','title':'中文阅读计划的安排与进展','claim':'','layout':layout,'points':[{'text':'先报名，再阅读，最后参加讨论。','refs':[1],'basis':'fact'}],'notes':'核对原始资料。','data':[]}
    if layout=='chart':
        page['data']=[{'label':'参与人数','raw':['120'],'operation':'value','unit':'人','period':'2025年','refs':[1]},{'label':'参与人数','raw':['180'],'operation':'value','unit':'人','period':'2026年','refs':[1]}]
    if layout=='table':page.update(columns=['年份','人数'],rows=[{'cells':['2025年','120人'],'refs':[1]},{'cells':['2026年','180人'],'refs':[1]}])
    return {'title':'中文验收样本','pages':[page]}

@pytest.mark.parametrize('bad',['foreign','unverified_note','number','unit','period','incomplete','duplicate_id'])
def test_reject_invalid_provenance(bad):
    content=sample('chart');evidence=copy.deepcopy(EVIDENCE)
    if bad=='foreign':content['pages'][0]['points'][0]['refs']=[999]
    elif bad=='unverified_note':evidence[0]['kind']='note'
    elif bad=='number':content['pages'][0]['data'][0]['raw']=['9999']
    elif bad=='unit':content['pages'][0]['data'][0]['unit']='亿元'
    elif bad=='period':content['pages'][0]['data'][0]['period']='2028年'
    elif bad=='incomplete':content['pages'][0]['data']=[]
    else:content['pages'].append(copy.deepcopy(content['pages'][0]))
    with pytest.raises(ModelError):validate_content(content,evidence,generated=True)


def test_generated_claim_cannot_cite_only_navigation_headings():
    evidence=copy.deepcopy(EVIDENCE)
    evidence[0]['text']='is_private¶'
    with pytest.raises(ModelError,match='标题'):
        validate_content(sample(),evidence,generated=True)
    evidence.append({**EVIDENCE[0],'label':2})
    c=sample();c['pages'][0]['points'][0]['refs']=[1,2]
    assert validate_content(c,evidence,generated=True)['pages']


def test_numeric_calculation_is_server_owned():
    c=sample('chart');d=c['pages'][0]['data'][0];d.update(raw=['180','120'],operation='difference',value=9999)
    data=validate_content(c,EVIDENCE)['pages'][0]['data'][0]
    assert data['value']==60 and '第一项减第二项' in data['method']

@pytest.mark.parametrize('layout',['cover','section','bullets','comparison','timeline','chart','sources','table'])
@pytest.mark.parametrize('template',['business','teaching','research'])
def test_layout_chinese_png_pdf_and_editable_pptx(layout,template):
    content=validate_content(sample(layout),EVIDENCE)
    snap={'kind':'presentation','params':{**Params().model_dump(),'template':template},'content':content,'evidence':EVIDENCE}
    s=scene(snap,content['pages'][0]);data=svg(s)
    im=Image.open(io.BytesIO(png(data)));assert im.size==(1280,720)
    pdf=PdfReader(io.BytesIO(export([s],'pdf')));assert len(pdf.pages)==1
    text=pdf.pages[0].extract_text();assert '中文阅读计划' in text and '第1段' not in text # detail belongs to PPT notes
    pptx=zipfile.ZipFile(io.BytesIO(export([s],'pptx')))
    xml=pptx.read('ppt/slides/slide1.xml').decode()
    assert '中文阅读计划' in xml and '<p:sp>' in xml and '<a:t>' in xml
    assert '中文样本文档' in pptx.read('ppt/notesSlides/notesSlide1.xml').decode()
    if layout=='chart':assert 'ppt/charts/chart1.xml' in pptx.namelist()


def test_overflow_rejected_and_text_not_executed():
    c=sample();c['pages'][0]['points']=[{'text':'很长的中文内容。'*20,'refs':[1],'basis':'fact'}]*6
    c=validate_content(c,EVIDENCE)
    snap={'kind':'presentation','params':Params().model_dump(),'content':c,'evidence':EVIDENCE}
    with pytest.raises(ModelError,match='精简|拆页'):scene(snap,c['pages'][0])
    c=sample();c['pages'][0]['title']='<script>alert(1)</script>'
    snap['content']=validate_content(c,EVIDENCE)
    assert b'<script>' not in svg(scene(snap,snap['content']['pages'][0]))


def finished(a,identity):
    row=call(a,'GET',f'/visuals/{identity}')
    if any(j['status']=='failed' for j in row['jobs']):pytest.fail(str(row['jobs']))
    return row if row['jobs'] and all(j['status']=='complete' for j in row['jobs']) else None


def action(a,row,kind,**extra):
    return call(a,'POST',f"/visuals/{row['id']}/jobs",202,json={'request_key':str(uuid.uuid4()),'revision':row['revision'],'kind':kind,**extra})


def test_stack_outline_edit_page_export_isolation_and_versions(ctx):
    a,b,nb=ctx['a'],ctx['b'],ctx['nb']
    doc=call(a,'POST',f'/notebooks/{nb}/sources/text',202,json={'title':'阅读样本','text':TEXT})['id']
    wait_for(lambda:call(a,'GET',f'/documents/{doc}/snapshot')['status']=='ready')
    body={'request_key':str(uuid.uuid4()),'kind':'presentation','document_ids':[doc],'params':{'count':5}}
    row=call(a,'POST',f'/notebooks/{nb}/visuals',201,json=body)
    assert call(a,'POST',f'/notebooks/{nb}/visuals',201,json=body)['id']==row['id']
    call(b,'GET',f"/visuals/{row['id']}",404)
    call(b,'GET',f"/visuals/{row['id']}/versions/1",404)
    row=wait_for(lambda:finished(a,row['id']),timeout=180)
    assert len(row['content']['pages'])==5 and row['stage']=='outline'
    row['content']['pages'][0]['title']='人工确认的标题'
    old=row['revision']
    row=call(a,'PATCH',f"/visuals/{row['id']}",json={'revision':old,'content':row['content'],'params':row['params']})
    assert row['content']['pages'][0]['edited']
    call(a,'PATCH',f"/visuals/{row['id']}",409,json={'revision':old,'content':row['content'],'params':row['params']})
    action(a,row,'pages');row=wait_for(lambda:finished(a,row['id']),timeout=210)
    assert row['stage']=='pages' and len([f for f in row['files'] if f['format']=='png'])==5
    previous=copy.deepcopy(row['content']['pages'])
    action(a,row,'page',page_id=previous[1]['id'],instruction='精简本页')
    row=wait_for(lambda:finished(a,row['id']),timeout=180)
    assert row['content']['pages'][0]==previous[0] and row['content']['pages'][2:]==previous[2:]
    frozen=row['revision'];action(a,row,'export',format='pptx');action(a,row,'export',format='pdf')
    row['content']['pages'][0]['title']='后来编辑，不应进入旧导出'
    row=call(a,'PATCH',f"/visuals/{row['id']}",json={'revision':row['revision'],'content':row['content'],'params':row['params']})
    row=wait_for(lambda:finished(a,row['id']),timeout=120)
    exports=[f for f in row['files'] if f['format'] in ('pptx','pdf')]
    assert len(exports)==2 and all(f['revision']==frozen for f in exports)
    for f in exports:
        call(b,'GET',f"/visual-files/{f['id']}",404)
        response=a.get(f"/api/visual-files/{f['id']}");assert response.status_code==200
        if f['format']=='pdf':assert '后来编辑' not in ''.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
    call(a,'PUT',f'/documents/{doc}/content',202,json={'version':1,'title':'阅读样本新版','text':TEXT+'新版新增活动提醒。'})
    wait_for(lambda:call(a,'GET',f'/documents/{doc}/snapshot')['version']==2)
    row=call(a,'GET',f"/visuals/{row['id']}")
    assert row['source_state']=='changed' and row['evidence'][0]['version']==1
    assert call(a,'GET',f"/documents/{doc}/snapshot?version=1")['units'][0]['text'] in TEXT
    job=action(a,row,'page',page_id=row['content']['pages'][0]['id'])
    wait_for(lambda:next(j for j in call(a,'GET',f"/visuals/{row['id']}")['jobs'] if j['id']==job['id'])['status']=='cancelled')
    call(a,'DELETE',f'/documents/{doc}',202)
    row=call(a,'GET',f"/visuals/{row['id']}");assert row['source_state']=='deleted' and row['evidence'][0]['state']=='deleted'
    assert call(a,'GET',f"/visuals/{row['id']}/versions/{frozen}")['snapshot']['content']['pages'][0]['title']=='人工确认的标题'
    call(b,'DELETE',f"/visuals/{row['id']}",404)
    call(a,'DELETE',f"/visuals/{row['id']}",202)
    for f in exports:call(a,'GET',f"/visual-files/{f['id']}",404)
    visual_tasks.sweep_visuals()
    with SessionLocal() as db:assert not db.scalar(select(VisualFile.id).where(VisualFile.artifact_id==row['id'],VisualFile.status!='deleted'))


def test_cancel_fences_result_and_notebook_delete(ctx,monkeypatch):
    a=ctx['a'];nb=call(a,'POST','/notebooks',201,json={'name':'取消验收'})['id']
    row=call(a,'POST',f'/notebooks/{nb}/visuals',201,json={'request_key':str(uuid.uuid4()),'kind':'infographic','manual':True})
    job=action(a,row,'outline')
    with SessionLocal() as db:
        j=db.get(VisualJob,job['id']);j.dispatched_at=now()+timedelta(days=1);db.commit()
    monkeypatch.setattr(visual_tasks,'gather',lambda *args:EVIDENCE)
    async def generate(*args,**kwargs):
        call(a,'POST',f"/visual-jobs/{job['id']}/cancel")
        return validate_content(sample(),EVIDENCE)
    monkeypatch.setattr(visual_tasks,'generate',generate)
    visual_tasks.process(job['id'])
    after=call(a,'GET',f"/visuals/{row['id']}")
    assert after['revision']==row['revision'] and after['jobs'][0]['status']=='cancelled'
    job=action(a,after,'render')
    call(a,'DELETE',f'/notebooks/{nb}',202)
    visual_tasks.process(job['id']);call(a,'GET',f"/visuals/{row['id']}",404)


@pytest.mark.parametrize('form',['overview','comparison','process'])
def test_manual_infographic_export(ctx,form):
    a=ctx['a'];row=call(a,'POST',f"/notebooks/{ctx['nb']}/visuals",201,json={'request_key':str(uuid.uuid4()),'kind':'infographic','manual':True,'params':{'form':form,'orientation':'portrait'}})
    content=sample({'overview':'bullets','comparison':'comparison','process':'timeline'}[form]);content['pages'][0]['points'][0].update(refs=[],basis='opinion')
    row=call(a,'PATCH',f"/visuals/{row['id']}",json={'revision':row['revision'],'content':content,'params':row['params']})
    action(a,row,'render');action(a,row,'export',format='png');action(a,row,'export',format='pdf')
    row=wait_for(lambda:finished(a,row['id']),timeout=120)
    file=next(f for f in row['files'] if f['format']=='png' and f['purpose']=='export')
    image=Image.open(io.BytesIO(a.get('/api/visual-files/'+file['id']).content));assert image.size==(2400,3200)
    call(ctx['b'],'GET','/visual-files/'+file['id'],404)


def test_partial_page_retry_reuses_success(ctx):
    a=ctx['a'];doc=call(a,'POST',f"/notebooks/{ctx['nb']}/sources/text",202,json={'title':'重试样本','text':TEXT+'仅验证失败页恢复。'})['id']
    wait_for(lambda:call(a,'GET',f'/documents/{doc}/snapshot')['status']=='ready')
    row=call(a,'POST',f"/notebooks/{ctx['nb']}/visuals",201,json={'request_key':str(uuid.uuid4()),'kind':'presentation','document_ids':[doc],'params':{'count':5}})
    row=wait_for(lambda:finished(a,row['id']),timeout=150)
    httpx.post(MODEL+'/control',json={'visual_fail_page':'p2','visual_calls':{}}).raise_for_status()
    try:
        job=action(a,row,'pages')
        def failed():
            fresh=call(a,'GET',f"/visuals/{row['id']}")
            j=next(j for j in fresh['jobs'] if j['id']==job['id'])
            return j if j['status']=='failed' else None
        j=wait_for(failed,timeout=150)
        assert j['result']['completed']==1 and j['result']['failed_page']=='p2'
        # No partial pages published over the confirmed outline.
        assert call(a,'GET',f"/visuals/{row['id']}")['revision']==row['revision']
        httpx.post(MODEL+'/control',json={'visual_fail_page':None}).raise_for_status()
        call(a,'POST',f"/visual-jobs/{job['id']}/retry")
        complete=wait_for(lambda:finished(a,row['id']),timeout=180)
        counts=httpx.post(MODEL+'/control',json={}).json()['visual_calls']
        assert counts['p1']==1 and counts['p2']==2 and complete['stage']=='pages'
    finally:httpx.post(MODEL+'/control',json={'visual_fail_page':None})


@pytest.mark.parametrize('control',[{'visual_malformed':True},{'visual_delay':20}])
def test_model_errors_do_not_publish(ctx,control):
    a=ctx['a'];doc=call(a,'POST',f"/notebooks/{ctx['nb']}/sources/text",202,json={'title':'错误状态样本','text':TEXT+str(uuid.uuid4())})['id']
    wait_for(lambda:call(a,'GET',f'/documents/{doc}/snapshot')['status']=='ready')
    httpx.post(MODEL+'/control',json=control)
    try:
        row=call(a,'POST',f"/notebooks/{ctx['nb']}/visuals",201,json={'request_key':str(uuid.uuid4()),'kind':'infographic','document_ids':[doc]})
        def failure():
            r=call(a,'GET',f"/visuals/{row['id']}")
            return r if r['jobs'][0]['status']=='failed' else None
        value=wait_for(failure,timeout=100)
        assert value['revision']==1 and not value['files'] and value['jobs'][0]['error']
    finally:httpx.post(MODEL+'/control',json={'visual_malformed':False,'visual_delay':0})
