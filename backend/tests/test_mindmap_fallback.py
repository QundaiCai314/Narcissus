from types import SimpleNamespace
import pytest
from app import generation, source_references
from app.model_service import ModelError

@pytest.fixture
def evidence_case(monkeypatch):
    doc = SimpleNamespace(id='d1', active_version=2, embedding_model='current')
    chunks = [SimpleNamespace(id=f'c{i}', page=i, ordinal=i, text=f'第{i}页原始知识点。') for i in range(1, 8)]
    db = SimpleNamespace(get=lambda model, ident: doc if ident == 'd1' else next(c for c in chunks if c.id == ident), scalars=lambda query: chunks)
    monkeypatch.setattr(generation, 'embedding_signature', lambda: 'current')
    monkeypatch.setattr(source_references, 'evidence', lambda db, d, c: {'document_id':d.id,'chunk_id':c.id,'filename':'课程.pdf','text':c.text,'page':c.page,'kind':'document','version':2})
    request={'documents':[{'id':'d1'}],'notes':[],'purpose':'核心知识','audience':''}
    def unavailable(*args): raise ModelError('资料理解服务暂时不可用，请稍后重试')
    monkeypatch.setattr(generation, 'embed', unavailable)
    return db, SimpleNamespace(id='nb',user_id='u'), request, doc

def test_fallback_keeps_bounded_original_evidence(evidence_case):
    db,nb,request,_=evidence_case
    sources, coverage=generation.build_evidence(db,nb,request,'summary',max_sources=4,allow_embedding_fallback=True)
    assert len(sources)==4
    assert sources[0]['page']==1 and sources[-1]['page']==7
    assert all(s['version']==2 and s['chunk_id'] and s['text'].endswith('原始知识点。') for s in sources)
    assert [s['label'] for s in sources]==[1,2,3,4]
    assert coverage['retrieval_mode']=='document_coverage_fallback'

def test_other_generation_still_surfaces_embedding_failure(evidence_case):
    db,nb,request,_=evidence_case
    with pytest.raises(ModelError): generation.build_evidence(db,nb,request,'summary')

def test_fallback_does_not_bypass_vector_version_check(evidence_case):
    db,nb,request,doc=evidence_case;doc.embedding_model='other'
    with pytest.raises(ModelError,match='不同的向量配置'):
        generation.build_evidence(db,nb,request,'summary',allow_embedding_fallback=True)

def test_available_embedding_still_uses_semantic_search(evidence_case,monkeypatch):
    db,nb,request,_=evidence_case;calls=[]
    monkeypatch.setattr(generation,'embed',lambda texts:([[1.0]],{}))
    monkeypatch.setattr(generation,'retrieve',lambda *args:calls.append(args) or [])
    _,coverage=generation.build_evidence(db,nb,request,'summary',allow_embedding_fallback=True)
    assert len(calls)==1 and coverage['retrieval_mode']=='semantic_and_document_coverage'


def test_manual_retry_clears_previous_failure(monkeypatch):
    from app import learning
    row = SimpleNamespace(status='failed', error='旧错误', warning='旧提示', attempts=3)
    monkeypatch.setattr(learning, 'owned', lambda *args: row)
    monkeypatch.setattr(learning, 'valid_sources', lambda *args: True)
    monkeypatch.setattr(learning, 'rate_limit', lambda *args: None)
    monkeypatch.setattr(learning, 'serialize', lambda *args: row)
    result = learning.retry('set', SimpleNamespace(id='u'), SimpleNamespace(commit=lambda: None))
    assert result.status == result.phase == 'queued'
    assert result.error is None and result.warning is None and result.attempts == 0


def test_deep_mindmap_accepts_eight_levels_and_rejects_ninth():
    import json
    from app.learning_validation import validate_result
    source = [{'label':1,'text':'金融市场包括多种金融工具及其具体分类。'}]
    items = [{'id':f'n{i}', 'parent_id':f'n{i-1}' if i else None,
              'title':f'知识点{i}', 'explanation':'由原文支持的分类', 'refs':[1],
              'quotes':[{'ref':1,'text':source[0]['text']}]} for i in range(9)]
    assert len(validate_result(json.dumps({'items':items[:8]}),'mindmap',{'count':120,'max_depth':8},source)['items']) == 8
    with pytest.raises(ModelError,match='层级'):
        validate_result(json.dumps({'items':items}),'mindmap',{'count':120,'max_depth':8},source)


def test_mindmap_input_allows_large_map_but_keeps_quiz_limits():
    from app.learning import GenerateInput
    import uuid
    from pydantic import ValidationError
    base = dict(document_ids=['d'],request_key=uuid.uuid4())
    assert GenerateInput(kind='mindmap',**base).count == 120
    with pytest.raises(ValidationError): GenerateInput(kind='mindmap',count=121,**base)
    with pytest.raises(ValidationError): GenerateInput(kind='quiz',count=120,**base)


def test_outline_quote_repair_and_deep_generation(monkeypatch):
    import asyncio, json
    from app import learning_generation as gen
    source = {'label':1,'filename':'课程.pdf','document_id':'d','text':'金融市场包括多种金融工具及其具体分类。'}
    base = dict(title='金融市场',explanation='金融工具的分类',refs=[1],quotes=[{'ref':1,'text':source['text']}])
    outline = dict(base,id='p1',parent_id=None,quotes=[{'ref':1,'text':'不存在的引文'}])
    nodes = [dict(base,id='root',parent_id=None),dict(base,id='p1',parent_id='root')]
    for i in range(4): nodes.append(dict(base,id=f'n{i}',parent_id='p1' if i==0 else f'n{i-1}'))
    replies = iter([
        {'items':[outline]},
        {'repairs':[{'id':'p1','refs':[1],'quotes':base['quotes']}]},
        {'items':nodes},
        {'approved_ids':[n['id'] for n in nodes]},
    ])
    async def complete(*args,**kwargs): return json.dumps(next(replies))
    monkeypatch.setattr(gen,'complete',complete)
    monkeypatch.setattr(gen,'phase',lambda *args:None)
    result,rejected = asyncio.run(gen.generate_and_review('s','c','mindmap',{'count':120,'max_depth':8},[source],'',[]))
    assert len(result['items'])==6 and rejected==0
    assert result['coverage_review']=={'expected_sections':['金融市场'],'missing_sections':[]}


def test_taxonomy_pass_changes_only_parents(monkeypatch):
    import asyncio, json
    from app import learning_generation as gen
    source = {'label':1,'filename':'课程.pdf','document_id':'d','text':'金融市场包括多种金融工具及其具体分类。'}
    base = dict(title='金融市场',explanation='金融工具的分类',refs=[1],quotes=[{'ref':1,'text':source['text']}])
    nodes = [dict(base,id='root',parent_id=None),dict(base,id='p1',parent_id='root')]
    nodes += [dict(base,id=f'n{i}',parent_id='p1') for i in range(24)]
    edges = [{'id':n['id'],'parent_id':n['parent_id']} for n in nodes]
    edges[3]['parent_id']='n0'
    edges[4]['parent_id']='n1'
    replies=iter([{'items':[dict(base,id='p1',parent_id=None)]},{'items':nodes},
                  {'parents':edges},{'approved_ids':[n['id'] for n in nodes]}])
    async def complete(*args,**kwargs): return json.dumps(next(replies))
    monkeypatch.setattr(gen,'complete',complete)
    monkeypatch.setattr(gen,'phase',lambda *args:None)
    result,_=asyncio.run(gen.generate_and_review('s','c','mindmap',{'count':120,'max_depth':8},[source],'',[]))
    assert result['items'][4]['parent_id']=='n1'
    for old,new in zip(nodes[1:],result['items'][1:]):
        assert all(old[k]==new[k] for k in ['id','title','explanation','refs','quotes'])
