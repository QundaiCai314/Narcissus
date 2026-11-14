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
