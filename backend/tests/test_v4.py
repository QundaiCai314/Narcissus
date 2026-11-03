"""V4 real infrastructure with explicit model/TTS protocol fixtures; no quality claims."""
import copy
import io
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import AudioOverview, AudioRender, AudioSegment, AudioBlob, Document, now
from app.audio_validation import validate_script
from app.tts_service import encode_wav, decode_wav, SpeechError
from app.model_service import ModelError
from app.audio_tasks import render_task, sweep_audio
from app import storage
from .test_integration import BASE, MODEL, HEADERS, call, wait_for
from .pdf_factory import pdf


def control(**data):
    return httpx.post(MODEL + '/control', json=data).json()


def key(): return str(uuid.uuid4())


@pytest.fixture(scope='module')
def ctx4():
    a,b=[httpx.Client(base_url=BASE,headers=HEADERS,timeout=60) for _ in range(2)]
    for c in (a,b):
        call(c,'POST','/auth/register',201,json={'email':'v4-'+uuid.uuid4().hex[:12]+'@example.com','password':'safe-v4-password-2026'})
    nb=call(a,'POST','/notebooks',201,json={'name':'第四版音频验收'})['id']
    docs=[]
    for name,text in [('预算.pdf','青禾项目第一阶段预算为三百万元。主要工作包括城市绿化与社区公共空间改造。'),('计划.pdf','青禾项目第二阶段计划于二零二七年完成。重点建设社区活动空间和无障碍设施。')]:
        docs.append(call(a,'POST',f'/notebooks/{nb}/documents',202,files={'file':(name,pdf([text]),'application/pdf')})['id'])
    wait_for(lambda: all(d['status']=='ready' for d in call(a,'GET',f'/notebooks/{nb}/documents')['items']))
    yield {'a':a,'b':b,'nb':nb,'docs':docs}
    control(tts_delay=0,tts_failures=0,tts_bad_wav=False,audio_malformed=False,audio_insufficient=False,audio_script_delay=0,audio_review_reject=False)
    a.close();b.close()


def create(ctx,**extra):
    return call(ctx['a'],'POST',f"/notebooks/{ctx['nb']}/audio",202,json={'request_key':key(),'document_ids':ctx['docs'],'mode':'duo','length':'short',**extra})


def script_done(ctx,sid,status='draft'):
    def check():
        r=call(ctx['a'],'GET','/audio/'+sid)
        if status=='draft': assert r['status'] not in ('failed','cancelled'),r['error']
        return r if r['status']==status else None
    return wait_for(check,120)


def start(ctx,row,**extra):
    return call(ctx['a'],'POST',f"/audio/{row['id']}/renders",202,json={'request_key':key(),'revision':row['revision'],'voice_a':'cixingnansheng','voice_b':'wenrounvsheng',**extra})


def render_done(ctx,rid,status='complete'):
    def check():
        r=call(ctx['a'],'GET','/audio-renders/'+rid)
        if status=='complete': assert r['status'] not in ('failed','cancelled'),r['error']
        return r if r['status']==status else None
    return wait_for(check,150)


def test_script_validation_and_wav():
    evidence=[{'label':1,'text':'青禾项目第一阶段预算为三百万元。'}]
    value={'title':'预算','intro':'预算说明','paragraphs':[{'id':'p1','chapter':'预算','speaker':'A','text':'预算为三百万元。[1]','refs':[1],'quotes':[{'ref':1,'text':'第一阶段预算为三百万元'}]}]}
    result=validate_script(value,'single',evidence,True)
    assert '[1]' not in result['paragraphs'][0]['text']
    without_quotes=copy.deepcopy(value);without_quotes['paragraphs'][0].pop('quotes')
    assert validate_script(without_quotes,'single',evidence,True)['paragraphs'][0]['refs']==[1]
    for bad in ([],{'paragraphs':'invalid'},dict(value,paragraphs=[])):
        with pytest.raises(ModelError): validate_script(bad,'single',evidence,True)
    for field,new in [('refs',[999]),('quotes',[{'ref':1,'text':'这是完全编造的来源段落'}]),('speaker','B')]:
        bad=copy.deepcopy(value);bad['paragraphs'][0][field]=new
        with pytest.raises(ModelError):validate_script(bad,'single',evidence,True)
    bad=copy.deepcopy(value);bad['paragraphs']*=2
    with pytest.raises(ModelError):validate_script(bad,'single',evidence,True)
    with pytest.raises(ModelError):validate_script(value,'duo',evidence,True)
    assert decode_wav(encode_wav(b'\0'*48000))==b'\0'*48000
    with pytest.raises(SpeechError) as ex:decode_wav(b'invalid')
    assert ex.value.uncertain


def test_create_edit_synthesize_authorization_and_versions(ctx4):
    c=ctx4;a,b=c['a'],c['b'];request_key=key()
    first=create(c,request_key=request_key)
    assert create(c,request_key=request_key)['id']==first['id']
    row=script_done(c,first['id']);c['row']=row
    assert {p['speaker'] for p in row['script']['paragraphs']}=={'A','B'}
    assert all(ref in {x['label'] for x in row['citations']} for p in row['script']['paragraphs'] for ref in p['refs'])
    assert {x['document_id'] for x in row['citations']}==set(c['docs'])
    for path in [f"/notebooks/{c['nb']}/audio",f"/audio/{row['id']}",f"/audio/{row['id']}/script.md"]:
        assert b.get('/api'+path).status_code==404
    edit={'revision':row['revision'],**row['script']}
    edit['paragraphs']=[{k:v for k,v in p.items() if k!='edited'} for p in edit['paragraphs']]
    edit['paragraphs'][0]['text']+='请核对这段说明。'
    assert b.patch('/api/audio/'+row['id'],json=edit).status_code==404
    row=call(a,'PATCH','/audio/'+row['id'],json=edit)
    assert row['script']['paragraphs'][0]['edited']
    call(a,'PATCH','/audio/'+row['id'],409,json=edit)
    control(tts_calls=0,tts_voices=[])
    r=start(c,row); assert start(c,row)['id']==r['id']
    for path in [f"/audio-renders/{r['id']}",f"/audio-renders/{r['id']}/file",f"/audio-renders/{r['id']}/script.md"]:
        assert b.get('/api'+path).status_code==404
    assert b.post(f"/api/audio-renders/{r['id']}/cancel").status_code==404
    r=render_done(c,r['id']);c['render']=r;c['row']=row
    assert r['completed_segments']==2 and r['duration_ms']==2350
    assert r['timeline']==[{'paragraph_id':'p1','start_ms':0,'end_ms':1000},{'paragraph_id':'p2','start_ms':1350,'end_ms':2350}]
    state=control();assert state['tts_calls']==2 and set(state['tts_voices'])=={'cixingnansheng','wenrounvsheng'}
    result=a.get(f"/api/audio-renders/{r['id']}/file",headers={'Range':'bytes=0-43'})
    assert result.status_code==206 and len(result.content)==44 and result.content.startswith(b'RIFF')
    assert a.get(f"/api/audio-renders/{r['id']}/file",headers={'Range':'bytes=999999999-'}).status_code==416
    raw=a.get(f"/api/audio-renders/{r['id']}/file?download=true");assert 'attachment' in raw.headers['content-disposition']
    with wave.open(io.BytesIO(raw.content),'rb') as wav:assert wav.getnframes()==56400
    edit['revision']=row['revision'];edit['title']='后续编辑的标题'
    updated=call(a,'PATCH','/audio/'+row['id'],json=edit);c['row']=updated
    historical=a.get(f"/api/audio-renders/{r['id']}/script.md").text
    assert '后续编辑的标题' not in historical and '预算.pdf' in historical and '第 1 页' in historical
    assert call(a,'GET','/audio/'+row['id'])['script']['title']=='后续编辑的标题'


def test_ambiguous_requests_require_ack_and_cache_success(ctx4):
    c=ctx4;row=c['row'];control(tts_calls=0,tts_bad_wav=True)
    r=start(c,row)
    failed=render_done(c,r['id'],'failed')
    assert failed['uncertain_segments']==1 and control()['tts_calls']==1
    assert start(c,row)['id']==r['id']
    time.sleep(11);assert control()['tts_calls']==1
    call(c['a'],'POST',f"/audio-renders/{r['id']}/retry",409,json={})
    control(tts_bad_wav=False)
    call(c['a'],'POST',f"/audio-renders/{r['id']}/retry",202,json={'accept_possible_charge':True})
    complete=render_done(c,r['id']);assert complete['completed_segments']==2 and control()['tts_calls']==3
    # Failure after successful segments: merge retry must not issue another speech request.
    with SessionLocal() as db:
        stored=db.get(AudioRender,r['id']);stored.status='failed';stored.error='test commit interruption'
        segment=db.scalar(select(AudioSegment).where(AudioSegment.render_id==r['id']).order_by(AudioSegment.ordinal));segment.status='uncertain';db.commit()
    call(c['a'],'POST',f"/audio-renders/{r['id']}/retry",202,json={})
    render_done(c,r['id']);assert control()['tts_calls']==3


def test_cancel_inflight_and_resume(ctx4):
    c=ctx4;row=script_done(c,create(c)['id']);control(tts_calls=0,tts_delay=1.8)
    r=start(c,row)
    wait_for(lambda:control()['tts_calls']==1)
    call(c['a'],'POST',f"/audio-renders/{r['id']}/cancel")
    wait_for(lambda:call(c['a'],'GET','/audio-renders/'+r['id'])['completed_segments']==1)
    time.sleep(11);assert control()['tts_calls']==1
    control(tts_delay=0)
    call(c['a'],'POST',f"/audio-renders/{r['id']}/retry",202,json={})
    render_done(c,r['id']);assert control()['tts_calls']==2


def test_safe_rejection_retries_but_timeout_does_not(ctx4):
    c=ctx4;row=script_done(c,create(c)['id']);control(tts_calls=0,tts_failures=1,tts_status=429)
    r=render_done(c,start(c,row)['id']);assert control()['tts_calls']==3
    row=script_done(c,create(c)['id']);control(tts_calls=0,tts_delay=5)
    r=render_done(c,start(c,row)['id'],'failed')
    assert r['uncertain_segments']==1 and '超时' in r['error']
    control(tts_delay=0);time.sleep(11);assert control()['tts_calls']==1


@pytest.mark.parametrize('flag,reason',[('audio_insufficient','足够依据'),('audio_malformed','结构'),('audio_review_reject','复核'),('audio_script_delay','超时')])
def test_model_failure_is_not_published(ctx4,flag,reason):
    control(**{flag:20 if flag=='audio_script_delay' else True})
    try:
        row=script_done(ctx4,create(ctx4)['id'],'failed')
        assert not row['script'] and reason in row['error']
    finally:control(**{flag:0 if flag=='audio_script_delay' else False})



def test_quota_and_cleanup_failure_are_durable(ctx4,monkeypatch):
    from app.audio import quota
    from app.config import settings
    from app.models import User,Notebook
    from fastapi import HTTPException
    c=ctx4
    with SessionLocal() as db:
        nb=db.get(Notebook,c['nb']);user=db.get(User,nb.user_id)
        parked=AudioOverview(notebook_id=nb.id,request_key=key(),params={},sources=[],available_at=now()+timedelta(days=1))
        db.add(parked);db.commit()
        monkeypatch.setattr(settings(),'audio_user_concurrency',1)
        with pytest.raises(HTTPException) as ex:quota(db,user)
        assert ex.value.status_code==429
        db.delete(parked);db.commit()
    orphan='audio/test-cleanup-'+key()+'.wav'
    storage.put(orphan,encode_wav(b'\0'*48000),'audio/wav')
    with SessionLocal() as db:
        db.add(AudioBlob(object_key=orphan,notebook_id=key(),overview_id=key(),status='ready'));db.commit()
    original=storage.remove
    def fail_once(k):
        if k==orphan:raise RuntimeError('simulated object storage outage')
        original(k)
    monkeypatch.setattr(storage,'remove',fail_once)
    sweep_audio()
    with SessionLocal() as db:
        blob=db.get(AudioBlob,orphan);assert blob.status=='deleting' and blob.attempts==1 and blob.error
        blob.available_at=now();db.commit()
    monkeypatch.setattr(storage,'remove',original)
    sweep_audio()
    with SessionLocal() as db:assert db.get(AudioBlob,orphan).status=='deleted'


def test_expired_lease_and_source_deletion(ctx4):
    c=ctx4;row=script_done(c,create(c)['id'])
    # Prevent dispatcher from claiming until explicit recovery.
    r=start(c,row)
    with SessionLocal() as db:
        stored=db.get(AudioRender,r['id']);stored.status='synthesizing';stored.started_at=now()-timedelta(seconds=400);stored.claim=key()
        segment=db.scalar(select(AudioSegment).where(AudioSegment.render_id==r['id']).order_by(AudioSegment.ordinal));segment.status='requesting';db.commit()
    sweep_audio()
    failed=call(c['a'],'GET','/audio-renders/'+r['id']);assert failed['status']=='failed' and failed['uncertain_segments']==1
    # A newer source version marks old evidence without rewriting prior records.
    with SessionLocal() as db:
            doc=db.get(Document,c['docs'][0]);doc.generation+=1;doc.active_version=doc.generation;db.commit()
    changed=call(c['a'],'GET','/audio/'+row['id']);assert any(s['state']=='changed' for s in changed['sources'])
    call(c['a'],'POST',f"/audio-renders/{r['id']}/retry",409,json={'accept_possible_charge':True})
    call(c['a'],'DELETE','/documents/'+c['docs'][0],202)
    old=call(c['a'],'GET','/audio/'+c['row']['id']);assert old['script'] and any(s['state']=='deleted' for s in old['citations'])
    assert '原始资料已删除' in c['a'].get(f"/api/audio-renders/{c['render']['id']}/script.md").text
    assert c['a'].get(f"/api/audio-renders/{c['render']['id']}/file").status_code==200
    # Notebook deletion fences stale tasks and cleanup ledger survives cascading database deletion.
    rid=c['render']['id']
    with SessionLocal() as db:keys=list(db.scalars(select(AudioBlob.object_key).where(AudioBlob.notebook_id==c['nb'])))
    pending=create(c,document_ids=[c['docs'][1]],mode='single')
    call(c['a'],'DELETE','/notebooks/'+c['nb'],202)
    from app.audio_tasks import script_task
    script_task(pending['id'])
    render_task(rid)
    assert c['a'].get('/api/audio-renders/'+rid).status_code==404
    def cleaned():
        with SessionLocal() as db:return all(db.get(AudioBlob,k).status=='deleted' for k in keys)
    wait_for(cleaned,120)
    for k in keys:
        with pytest.raises(Exception):storage.read(k)



def test_review_sees_only_its_paragraph_evidence(monkeypatch):
    import asyncio,json
    from app import audio_tasks
    evidence=[{'label':1,'text':'资料一：第一阶段预算为三百万元。'},{'label':2,'text':'资料二：项目计划在二零二七年完成。'}]
    script={'title':'摘要','intro':'项目资料','paragraphs':[{'id':'p1','chapter':'预算','speaker':'A','text':'预算为三百万元。','refs':[1]},{'id':'p2','chapter':'时间','speaker':'A','text':'计划在二零二七年完成。','refs':[2]}]}
    seen=[]
    async def complete(messages,usages,max_tokens):
        payload=json.loads(messages[-1]['content'])
        if payload['mode']=='audio_script':return json.dumps(script)
        if payload['mode']=='audio_paragraph_review':
            assert [e['label'] for e in payload['evidence']]==payload['paragraph']['refs']
            assert 'script' not in payload
            seen.append(payload['paragraph']['id'])
        return '{"approved":true}'
    monkeypatch.setattr(audio_tasks,'complete',complete)
    monkeypatch.setattr(audio_tasks,'ensure_script_current',lambda *a:None)
    result=asyncio.run(audio_tasks.make_script('id','claim',{'mode':'single','length':'short'},evidence,[]))
    assert set(seen)=={'p1','p2'} and len(result['paragraphs'])==2
