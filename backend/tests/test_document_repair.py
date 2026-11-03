"""Regression: garbled scan headers, broad document coverage and fenced reprocessing."""
import uuid
from types import SimpleNamespace
import httpx
import pytest
from app import pdf_processing
from app.retrieval import is_overview, spread_chunks, overview_sources
from app.db import SessionLocal
from .pdf_factory import pdf
from .test_integration import BASE, HEADERS, call, wait_for
from app.learning_validation import decode, navigation_root, validate_result, split_exact_quotes
from app.model_service import ModelError


def test_truncated_stream_keeps_usage_and_reports_real_failure(monkeypatch):
    import asyncio, json
    from app import model_service
    from app.config import settings
    monkeypatch.setattr(settings(), 'chat_api_key', 'test-fixture-not-a-real-key')
    client_type = httpx.AsyncClient
    def handler(request):
        chunks=[{'choices':[{'delta':{'content':'部分回答'},'finish_reason':None}]},
                {'choices':[{'delta':{},'finish_reason':'length'}]},
                {'choices':[],'usage':{'completion_tokens':8}}]
        body=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        return httpx.Response(200,text=body,headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(model_service.httpx,'AsyncClient',lambda **kwargs: client_type(**kwargs,transport=httpx.MockTransport(handler)))
    parts=[]
    async def run():
        async for part in model_service.chat_stream([{'role':'user','content':'测试'}]):
            parts.append(part)
    with pytest.raises(ModelError,match='生成长度上限'):
        asyncio.run(run())
    assert {'usage':{'completion_tokens':8}} in parts


def test_only_missing_outer_json_terminator_can_be_repaired():
    assert decode('{"items":[{"id":"n1"}]') == {'items':[{'id':'n1'}]}
    for bad in ['{"items":[{"id":"n1', '{"items":[{"id":"n1",}]', '{"items":[}']:
        with pytest.raises(ModelError): decode(bad)


def test_navigation_header_cannot_publish_model_claims():
    import json
    sources=[{'label':1,'document_id':'doc1','text':'货币的职能包括价值尺度、流通手段、支付手段。'}]
    child={'id':'n2','parent_id':'n1','title':'货币职能','explanation':'货币的职能包括价值尺度。','refs':[1],'quotes':[{'ref':1,'text':'货币的职能包括价值尺度'}]}
    raw=json.dumps({'items':[{'id':'n1','parent_id':None,'title':'伪造结论','explanation':'无依据事实','refs':[999],'quotes':[]},child]})
    fixed=navigation_root(raw,sources)
    result=validate_result(fixed,'mindmap',{'count':40},sources)
    assert result['items'][0]['title']=='所选资料知识导图'
    assert result['items'][0]['refs']==[1]
    assert result['items'][1]==child
    # Knowledge nodes are never repaired into seemingly verified claims.
    child['refs']=[999]
    bad=json.dumps({'items':[result['items'][0],child]})
    with pytest.raises(ModelError):
        validate_result(navigation_root(bad,sources),'mindmap',{'count':40},sources)


def test_long_exact_quote_splits_without_losing_evidence_or_accepting_forgery():
    import json
    from app.learning_validation import normalize
    text=('货币的职能包括价值尺度、流通手段。'*50)[:701]
    item={'id':'n1','parent_id':None,'title':'货币职能','explanation':'货币的职能包括价值尺度。','refs':[1],'quotes':[{'ref':1,'text':text}]}
    sources=[{'label':1,'text':text}]
    result=validate_result(split_exact_quotes(json.dumps({'items':[item]}),sources),'mindmap',{'count':40},sources)
    assert ''.join(q['text'] for q in result['items'][0]['quotes'])==normalize(text)
    item['quotes'][0]['text']=text+'原文没有的数字999'
    with pytest.raises(ModelError):
        validate_result(split_exact_quotes(json.dumps({'items':[item]}),sources),'mindmap',{'count':40},sources)


def test_garbled_layer_is_not_usable_text():
    assert pdf_processing.unreadable('g\x01N\x12水印\x83')
    assert not pdf_processing.unreadable('货币是一般等价物。\n信用与利息。')


def test_image_with_short_header_uses_body_ocr(monkeypatch):
    class OCR:
        def __init__(self, data): pass
        def page(self, page): return '货币是商品交换的媒介。信用分为商业信用和银行信用。', 91
        def close(self): pass
    monkeypatch.setattr(pdf_processing, 'has_large_image', lambda page: True)
    monkeypatch.setattr(pdf_processing, 'LocalOCR', OCR)
    info = {}
    pages, chunks = pdf_processing.extract_chunks(pdf(['仅有页眉文字']), info)
    assert pages == 1 and '商业信用' in chunks[0]['text']
    assert info['ocr_pages'] == [1] and info['characters'] > 20


def test_failed_ocr_is_not_published(monkeypatch):
    class OCR:
        def __init__(self, data): pass
        def page(self, page): raise pdf_processing.OCRFailure('识别超时')
        def close(self): pass
    monkeypatch.setattr(pdf_processing, 'has_large_image', lambda page: True)
    monkeypatch.setattr(pdf_processing, 'LocalOCR', OCR)
    with pytest.raises(pdf_processing.InvalidPDF, match='识别超时'):
        pdf_processing.extract_chunks(pdf(['页眉']))


def test_overview_covers_pages_not_just_first_and_last():
    chunks = [SimpleNamespace(id=f'{p}-{i}', page=p) for p in range(1,18) for i in range(3)]
    result = spread_chunks(chunks, 24)
    assert len(result) == len({c.id for c in result}) == 24
    assert {c.page for c in result} == set(range(1,18))
    assert spread_chunks([], 24) == []


def test_generic_questions_use_overview_but_details_keep_retrieval():
    assert is_overview('这些资料主要讲了什么？')
    assert is_overview('请整理资料中的核心观点和依据。')
    assert is_overview('不同资料有哪些相同或不同的观点？')
    assert is_overview('该金融学知识点总结文档预期覆盖哪些金融学核心模块与知识点范畴？')
    assert not is_overview('明天的天气如何？')
    assert not is_overview('项目预算是多少？')


def test_reprocess_ownership_fencing_and_overview_scope():
    clients = [httpx.Client(base_url=BASE, headers=HEADERS, timeout=90) for _ in range(2)]
    notebooks=[]
    try:
        users=[]
        for c in clients:
            user=call(c,'POST','/auth/register',201,json={'email':f'repair-{uuid.uuid4().hex[:12]}@example.com','password':'repair-test-password-2026'})
            nb=call(c,'POST','/notebooks',201,json={'name':'资料修复回归'})['id']
            notebooks.append(nb)
            users.append(call(c,'GET','/auth/me')['id'])
        a,b=clients
        nb=notebooks[0]
        doc=call(a,'POST',f'/notebooks/{nb}/documents',202,files={'file':('中文资料.pdf',pdf(),'application/pdf')})
        def ready():
            d=call(a,'GET',f'/notebooks/{nb}/documents')['items'][0]
            return d if d['status']=='ready' else None
        before=wait_for(ready)
        with SessionLocal() as db:
            assert overview_sources(db,users[0],nb,[doc['id']])
            assert not overview_sources(db,users[1],nb,[doc['id']])
            assert not overview_sources(db,users[0],notebooks[1],[doc['id']])
            assert not overview_sources(db,users[0],nb,[])
        body={'version':before['generation']}
        call(b,'POST',f"/documents/{doc['id']}/reprocess",404,json=body)
        call(a,'POST',f"/documents/{doc['id']}/reprocess",202,json=body)
        call(a,'POST',f"/documents/{doc['id']}/reprocess",409,json=body)
        after=wait_for(lambda: (d if (d := ready()) and d["generation"] > before["generation"] else None))
        assert after['generation']==before['generation']+1
        assert after['extraction']['characters']>20
        with SessionLocal() as db:
            from app.models import Writing, GenerationJob
            from app.writings import latest
            from sqlalchemy import select
            guide=db.scalar(select(Writing).where(Writing.document_id==doc['id']))
            assert latest(db,guide.id).request['documents'][0]['version']==after['generation']
        call(b,'GET',f"/documents/{doc['id']}/file",404)
    finally:
        for c,nb in zip(clients,notebooks):
            c.delete('/api/notebooks/'+nb)
        for c in clients: c.close()
