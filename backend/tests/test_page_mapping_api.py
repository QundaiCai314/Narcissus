import copy,io
from uuid import uuid4
from types import SimpleNamespace
from sqlalchemy import select,func
from pypdf import PdfWriter
from app.models import LearningSet
from .test_directory_branch_api import setup
from .test_page_mapping import SOURCE,rule


def test_mapping_preview_and_version_save_preserve_nodes_and_old_version(setup):
    client,db,app,_=setup;old=copy.deepcopy(db.get(LearningSet,'original').result)
    payload=dict(source_pdf=SOURCE,ranges=[rule()],entry_targets=[],request_key=str(uuid4()))
    response=client.post('/learning/original/page-mapping/preview',json=payload)
    assert response.status_code==200,response.text
    staged=response.json();assert staged['report']['mapped']==3
    assert db.scalar(select(func.count()).select_from(LearningSet))==1
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    assert client.post('/learning/original/page-mapping',json={**body,'plan_fingerprint':'stale'}).status_code==409
    response=client.post('/learning/original/page-mapping',json=body)
    assert response.status_code==201,response.text
    value=response.json();ident=value['id']
    assert value['version']==2 and value['family_id']=='family' and value['model'] is None
    assert value['items']==old['items'] and value['page_locations']['mapped']==3
    assert db.get(LearningSet,'original').result==old
    assert client.post('/learning/original/page-mapping',json=body).json()['id']==ident
    assert db.scalar(select(func.count()).select_from(LearningSet))==2
    app.dependency_overrides[next(key for key in app.dependency_overrides if key.__name__=='current_user')]=lambda:SimpleNamespace(id='other')
    assert client.post('/learning/original/page-mapping/preview',json=payload).status_code==404
    assert client.post('/learning/original/page-mapping',json=body).status_code==404


def test_pending_positions_and_changed_snapshot_block_save(setup):
    client,db,_,_=setup
    payload=dict(source_pdf=SOURCE,entry_targets=[dict(entry_id='leaf',pdf_page=20,verified=False)],request_key=str(uuid4()))
    staged=client.post('/learning/original/page-mapping/preview',json=payload).json()
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    assert client.post('/learning/original/page-mapping',json=body).status_code==422
    payload['entry_targets'][0]['verified']=True
    staged=client.post('/learning/original/page-mapping/preview',json=payload).json()
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    row=db.get(LearningSet,'original');row.result={**row.result,'snapshot_change':True};db.commit()
    assert client.post('/learning/original/page-mapping',json=body).status_code==409
    assert db.scalar(select(func.count()).select_from(LearningSet))==1


def test_metadata_upload_is_read_only_and_owner_scoped(setup):
    client,db,app,_=setup
    writer=PdfWriter();writer.add_blank_page(100,100);writer.add_blank_page(100,100)
    buf=io.BytesIO();writer.write(buf)
    before=copy.deepcopy(db.get(LearningSet,'original').result)
    response=client.post('/learning/original/pdf-page-metadata',files={'file':('local.pdf',buf.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    value=response.json();assert value['source_pdf']['total_pages']==2 and not value['explicit_page_labels']
    assert value['text_pages_read']==[] and value['model_calls']==0
    assert db.get(LearningSet,'original').result==before
    app.dependency_overrides[next(key for key in app.dependency_overrides if key.__name__=='current_user')]=lambda:SimpleNamespace(id='other')
    assert client.post('/learning/original/pdf-page-metadata',files={'file':('local.pdf',buf.getvalue(),'application/pdf')}).status_code==404
