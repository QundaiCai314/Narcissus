from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import data_tables,research_gaps,research,learning
from app.models import Base,User,Notebook,Document,SourceVersion,ResearchTask,ResearchCandidate,Writing
from app.security import current_user
from app.db import db_session
from app.source_parsing import parse_file

@pytest.fixture
def setup(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[c.__table__ for c in [User,Notebook,Document,SourceVersion,Writing,ResearchTask,ResearchCandidate]])
    with Session(engine) as db:
        db.add(User(id='owner',email='parity@example.test',password_hash='unused'));db.add(Notebook(id='book',user_id='owner',name='隔离验收'))
        units,_=parse_file('csv','名称,编号\n人工样例,001\n'.encode())
        db.add(Document(id='doc',notebook_id='book',filename='样例.csv',object_key='unused',size=20,status='ready',source_type='csv',active_version=1))
        db.add(SourceVersion(document_id='doc',version=1,title='样例',object_key='unused',status='ready',units=units,details={}))
        task=ResearchTask(id='root',notebook_id='book',request_key='initial',question='人工研究问题',params={'language':'zh','requirements':''},status='complete',reports=[{'writing_id':'report'}])
        db.add(task);db.add(Writing(id='report',notebook_id='book',title='模拟报告',kind='summary',edited=False,details={'structured':{'reviewed':True,'blocks':[{'id':'gap1','section':'uncertainties','type':'uncertainty','text':'尚缺长期数据'},{'id':'gap2','section':'uncertainties','type':'uncertainty','text':'尚缺样本范围'}]}}));db.commit()
        monkeypatch.setattr(research_gaps.writings,'latest',lambda *args:SimpleNamespace(status='complete'))
        monkeypatch.setattr(research_gaps,'rate_limit',lambda *args:None)
        monkeypatch.setattr(research,'serialize',lambda db,row:dict(id=row.id,question=row.question,params=row.params,status=row.status))
        app=FastAPI();app.include_router(data_tables.router);app.include_router(research_gaps.router)
        app.dependency_overrides[current_user]=lambda:SimpleNamespace(id='owner');app.dependency_overrides[db_session]=lambda:db
        with TestClient(app) as client:yield client,db,app
    engine.dispose()

def test_table_preview_and_exports_are_owned_and_read_only(setup):
    client,db,app=setup
    assert client.get('/notebooks/book/data-tables').json()['items'][0]['rows']==2
    assert client.get('/documents/doc/tables/t1').json()['rows'][1]['cells']==['人工样例','001']
    assert client.get('/documents/doc/table-exports/t1/xlsx').content.startswith(b'PK')
    assert client.get('/documents/doc/table-exports/t1/csv').content.startswith(b'\xef\xbb\xbf')
    assert db.scalar(select(func.count()).select_from(SourceVersion))==1
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(id='other')
    for path in ['/notebooks/book/data-tables','/documents/doc/tables/t1','/documents/doc/table-exports/t1/csv']:assert client.get(path).status_code==404

def test_gap_preview_budget_idempotency_and_no_unconfirmed_search(setup):
    client,db,app=setup
    preview=client.get('/research/root/gap-plan').json();assert preview['remaining_rounds']==2
    assert db.scalar(select(func.count()).select_from(ResearchTask))==1
    body=dict(request_key=str(uuid4()),gap_id='gap1',fingerprint=preview['fingerprint'],confirmed=False)
    assert client.post('/research/root/follow-up',json=body).status_code==422
    body['confirmed']=True
    first=client.post('/research/root/follow-up',json=body);assert first.status_code==202,first.text
    assert client.post('/research/root/follow-up',json=body).json()['id']==first.json()['id']
    next_plan=client.get('/research/root/gap-plan').json();assert len(next_plan['gaps'])==1
    second=client.post('/research/root/follow-up',json={**body,'request_key':str(uuid4()),'gap_id':'gap2','fingerprint':next_plan['fingerprint']})
    assert second.status_code==202,second.text
    assert client.post('/research/root/follow-up',json={**body,'request_key':str(uuid4())}).status_code==429
    assert db.scalar(select(func.count()).select_from(ResearchTask))==3
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(id='other')
    assert client.get('/research/root/gap-plan').status_code==404
    assert client.post('/research/root/follow-up',json=body).status_code==404
