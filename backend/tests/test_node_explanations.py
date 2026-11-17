import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import learning, security, node_explanations as detail
from app.errors import fail
from app.model_service import ModelError

SOURCE = dict(label=1,document_id='d',chunk_id='c',filename='课程.pdf',text='货币供给包括流通中的现金和银行存款。',state='active')
NODE = dict(id='n',parent_id='root',title='货币供给',explanation='货币供给的组成',refs=[1])


def test_scope_is_bounded_and_starts_with_selected_evidence():
    nodes=[NODE]+[dict(NODE,id=f'c{i}',parent_id='n',refs=[i+2]) for i in range(30)]
    sources=[dict(SOURCE,label=i+1,text='原文'*1000) for i in range(31)]
    chosen,evidence=detail.scope(nodes,'n',sources)
    assert chosen[0]['id']=='n' and len(chosen)==12
    assert evidence[0]['label']==1 and len(evidence)<=12
    assert all(len(s['text'])<=1600 for s in evidence)


def test_explanation_only_publishes_reviewed_sections(monkeypatch):
    from app import learning_generation as gen
    base=dict(parent_id=None,refs=[1],quotes=[dict(ref=1,text=SOURCE['text'])])
    replies=iter([{'items':[dict(base,id='s1',title='概念',explanation=SOURCE['text']),dict(base,id='s2',title='不支持',explanation='外部断言')]}, {'approved_ids':['s1']}])
    async def complete(*args,**kwargs): return json.dumps(next(replies))
    monkeypatch.setattr(gen,'complete',complete)
    result=asyncio.run(detail.explain([NODE],[SOURCE]))
    assert [s['id'] for s in result['sections']]==['s1']
    assert result['warning'] and result['citations'][0]['chunk_id']=='c'


def test_fabricated_reference_is_rejected(monkeypatch):
    from app import learning_generation as gen
    async def complete(*args,**kwargs):
        return json.dumps({'items':[dict(id='s',title='概念',parent_id=None,explanation='无依据',refs=[999],quotes=[dict(ref=999,text=SOURCE['text'])])]})
    monkeypatch.setattr(gen,'complete',complete)
    with pytest.raises(ModelError): asyncio.run(detail.explain([NODE],[SOURCE]))


def test_unfixable_quote_only_removes_its_section(monkeypatch):
    from app import learning_generation as gen
    good=dict(id='s1',title='概念',parent_id=None,explanation=SOURCE['text'],refs=[1],quotes=[dict(ref=1,text=SOURCE['text'])])
    bad=dict(good,id='s2',quotes=[dict(ref=1,text='无法在原文找到的引文')])
    replies=iter([{'items':[good,bad]}, {'repairs':[{'id':'s2','refs':[1],'quotes':bad['quotes']}]}, {'approved_ids':['s1']}])
    async def complete(*args,**kwargs):return json.dumps(next(replies))
    monkeypatch.setattr(gen,'complete',complete)
    result=asyncio.run(detail.explain([NODE],[SOURCE]))
    assert [s['id'] for s in result['sections']]==['s1'] and result['warning']


@pytest.fixture
def endpoint(monkeypatch):
    store={};state={'active':True,'calls':0}
    class Cache:
        def get(self,key): return store.get(key)
        def set(self,key,value,**kwargs):
            if key in store:return False
            store[key]=value;return True
        def setex(self,key,ttl,value):store[key]=value
        def eval(self,script,num,key,token):
            if store.get(key)==token:store.pop(key)
    monkeypatch.setattr(security,'redis',Cache())
    monkeypatch.setattr(learning,'rate_limit',lambda *args:None)
    row=SimpleNamespace(notebook_id='nb',result={'items':[NODE]},citations=[SOURCE])
    def owned(db,user_id,*args):
        if user_id!='owner':fail(404,'not_found','无权限')
        return row
    def resolve(*args):
        if not state['active']:fail(409,'source_changed','资料已更新')
        return NODE,[SOURCE],['d']
    monkeypatch.setattr(learning,'owned',owned)
    monkeypatch.setattr(learning,'resolve_node',resolve)
    monkeypatch.setattr(learning,'refs',lambda *args:[SOURCE])
    db=SimpleNamespace(get=lambda *args:SimpleNamespace(document_id='d'),expire_all=lambda:None,rollback=lambda:None)
    async def explain(*args):
        state['calls']+=1
        return dict(title='货币供给',sections=[],citations=[SOURCE],warning=None)
    monkeypatch.setattr(detail,'explain',explain)
    def run(owner='owner'):return asyncio.run(learning.node_explanation('set','n',SimpleNamespace(id=owner),db))
    state['read']=lambda owner='owner':learning.read_node_explanation('set','n',SimpleNamespace(id=owner),db)
    return run,state,store


def test_cache_still_checks_ownership_and_current_sources(endpoint):
    run,state,_=endpoint
    assert run()==run() and state['calls']==1
    with pytest.raises(HTTPException) as denied:run('other')
    assert denied.value.status_code==404
    state['active']=False
    with pytest.raises(HTTPException) as changed:run()
    assert changed.value.status_code==409 and state['calls']==1


def test_source_change_during_generation_is_not_cached(endpoint,monkeypatch):
    run,state,store=endpoint
    async def explain(*args):
        state['active']=False
        return {}
    monkeypatch.setattr(detail,'explain',explain)
    with pytest.raises(HTTPException) as changed:run()
    assert changed.value.status_code==409 and not store


def test_read_missing_and_pending_never_generates_or_writes_cache(endpoint):
    _,state,store=endpoint
    assert state['read']()=={'status':'missing','detail':None}
    assert state['calls']==0 and not store
    store[learning.node_explanation_key('owner','set','n')+':lock']='other-request'
    before=dict(store)
    assert state['read']()=={'status':'pending','detail':None}
    assert state['calls']==0 and store==before


def test_read_reuses_saved_detail_but_rechecks_access_and_sources(endpoint):
    run,state,_=endpoint
    saved=run()
    assert state['read']()=={'status':'ready','detail':saved}
    assert state['read']()['status']=='ready' and state['calls']==1
    with pytest.raises(HTTPException) as denied:state['read']('other')
    assert denied.value.status_code==404
    state['active']=False
    with pytest.raises(HTTPException) as changed:state['read']()
    assert changed.value.status_code==409 and state['calls']==1


def test_read_failure_does_not_fall_back_to_model(endpoint,monkeypatch):
    from redis.exceptions import RedisError
    _,state,_=endpoint
    def unavailable(*args):raise RedisError('offline')
    monkeypatch.setattr(security.redis,'get',unavailable)
    with pytest.raises(HTTPException) as error:state['read']()
    assert error.value.status_code==503 and state['calls']==0
