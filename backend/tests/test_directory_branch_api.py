import copy
from uuid import uuid4
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import learning
from app.models import Base,User,Notebook,LearningSet
from .test_directory_coverage import fixture_result


@pytest.fixture
def setup(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__,Notebook.__table__,LearningSet.__table__])
    with Session(engine) as db:
        db.add(User(id='owner',email='branch@example.test',password_hash='unused'))
        db.add(Notebook(id='book',user_id='owner',name='分支隔离验收'));db.commit()
        app=FastAPI();app.include_router(learning.router)
        app.dependency_overrides[learning.current_user]=lambda:SimpleNamespace(id='owner')
        app.dependency_overrides[learning.db_session]=lambda:db
        monkeypatch.setattr(learning,'rate_limit',lambda *args:None)
        data,result=fixture_result()
        result['reader_note']={'text':'保留来源说明'}
        row=LearningSet(id='original',notebook_id='book',family_id='family',version=1,request_key='original',
            kind='mindmap',title='课程目录',params={'origin':'outline'},sources=[],status='complete',phase='complete',result=result,citations=[])
        db.add(row);db.commit()
        with TestClient(app) as client:yield client,db,app,data
    engine.dispose()


def damage(db):
    row=db.get(LearningSet,'original');row.result={**row.result,'items':[n for n in row.result['items'] if n['id'] not in ['chapter','section','leaf']]}
    db.commit();return copy.deepcopy(row.result)


def test_preview_then_save_creates_immutable_idempotent_version(setup):
    client,db,app,data=setup;original=damage(db)
    report=client.post('/learning/original/directory-coverage',json={}).json()
    assert len(report['missing'])==3
    payload={'branch_id':'chapter','request_key':str(uuid4())}
    response=client.post('/learning/original/directory-branch/preview',json=payload)
    assert response.status_code==200,response.text
    staged=response.json();assert staged['added']==3 and staged['after']['complete']
    assert db.scalar(select(func.count()).select_from(LearningSet))==1
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    assert client.post('/learning/original/directory-branch',json={**body,'plan_fingerprint':'stale'}).status_code==409
    assert client.post('/learning/original/directory-branch',json={**body,'confirmed':False}).status_code==422
    response=client.post('/learning/original/directory-branch',json=body)
    assert response.status_code==201,response.text
    published=response.json();ident=published['id']
    assert published['version']==2 and published['family_id']=='family' and published['model'] is None
    assert published['directory_coverage']['complete'] and published['outline']['covered_entries']==6
    assert db.get(LearningSet,'original').result==original
    assert db.get(LearningSet,ident).result['reader_note']==original['reader_note']
    assert client.post('/learning/original/directory-branch',json=body).json()['id']==ident
    assert db.scalar(select(func.count()).select_from(LearningSet))==2
    app.dependency_overrides[learning.current_user]=lambda:SimpleNamespace(id='other')
    for suffix in ['directory-coverage','directory-branch/preview','directory-branch']:
        assert client.post('/learning/original/'+suffix,json=body).status_code==404


def test_legacy_requires_reference_and_baseline_only_keeps_nodes(setup):
    client,db,_,data=setup;row=db.get(LearningSet,'original');row.result={k:v for k,v in row.result.items() if k!='directory_reference'};db.commit()
    original=copy.deepcopy(row.result['items'])
    assert not client.post('/learning/original/directory-coverage',json={}).json()['available']
    payload={'branch_id':None,'request_key':str(uuid4())}
    assert client.post('/learning/original/directory-branch/preview',json=payload).status_code==422
    payload['reference']=data.model_dump(mode='json')
    staged=client.post('/learning/original/directory-branch/preview',json=payload).json()
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    response=client.post('/learning/original/directory-branch',json=body)
    assert response.status_code==201,response.text
    assert response.json()['items']==original and response.json()['directory_coverage']['complete']


def test_source_snapshot_change_invalidates_staged_plan(setup):
    client,db,_,data=setup;damage(db)
    payload={'branch_id':'chapter','request_key':str(uuid4())}
    staged=client.post('/learning/original/directory-branch/preview',json=payload).json()
    row=db.get(LearningSet,'original');row.result={**row.result,'external_change':'模拟预览后发生变化'};db.commit()
    body={**payload,'confirmed':True,'base_fingerprint':staged['base_fingerprint'],'plan_fingerprint':staged['plan_fingerprint']}
    assert client.post('/learning/original/directory-branch',json=body).status_code==409
    assert db.scalar(select(func.count()).select_from(LearningSet))==1


def test_regular_knowledge_map_cannot_be_replaced_with_directory_nodes(setup):
    client,db,_,data=setup;row=db.get(LearningSet,'original');row.params={};row.result={**row.result,'coverage_review':{'expected_sections':['主题一'],'missing_sections':[]}};db.commit()
    public=client.get('/learning/original').json()
    assert public['coverage_review']['basis']=='model_planned_topics' and 'directory_coverage' not in public
    assert client.post('/learning/original/directory-coverage',json={}).status_code==409
    assert client.post('/learning/original/directory-branch/preview',json={'request_key':str(uuid4())}).status_code==409
