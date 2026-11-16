from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import learning
from app.models import Base,User,Notebook,LearningSet
from .test_directory_maps import sample


def test_save_is_owned_idempotent_and_never_queues_generation(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__,Notebook.__table__,LearningSet.__table__])
    with Session(engine) as db:
        db.add(User(id='owner',email='preview@example.test',password_hash='unused'))
        db.add(Notebook(id='book',user_id='owner',name='隔离验收'))
        db.add(LearningSet(id='previous',notebook_id='book',family_id='previous',request_key='previous',version=1,
            kind='mindmap',title='已有导图',params={},sources=[],status='complete',phase='complete',result={'items':[]},citations=[]))
        db.commit()
        app=FastAPI();app.include_router(learning.router)
        app.dependency_overrides[learning.current_user]=lambda:SimpleNamespace(id='owner')
        app.dependency_overrides[learning.db_session]=lambda:db
        monkeypatch.setattr(learning,'rate_limit',lambda *args:None)
        payload=sample(confirmed=True).model_dump(mode='json')
        with TestClient(app) as client:
            preview=client.post('/notebooks/book/outline-map/preview',json=payload)
            assert preview.status_code==200 and db.scalar(select(func.count()).select_from(LearningSet))==1
            response=client.post('/notebooks/book/outline-map',json=payload)
            assert response.status_code==201,response.text
            row=response.json();ident=row['id']
            assert row['outline']['covered_entries']==4 and row['params']['origin']=='outline'
            assert row['model'] is None and row['status']=='complete'
            assert client.post('/notebooks/book/outline-map',json=payload).json()['id']==ident
            changed={**payload,'title':'不同目录'}
            assert client.post('/notebooks/book/outline-map',json=changed).status_code==409
            assert client.post(f'/learning/{ident}/regenerate',json={'request_key':payload['request_key']}).status_code==409
            assert client.post(f'/learning/{ident}/nodes/leaf/explanation').status_code==409
            assert db.scalar(select(func.count()).select_from(LearningSet))==2
            assert db.get(LearningSet,'previous').title=='已有导图'
            app.dependency_overrides[learning.current_user]=lambda:SimpleNamespace(id='other')
            assert client.post('/notebooks/book/outline-map',json=payload).status_code==404
            assert client.post('/notebooks/book/outline-map/preview',json=payload).status_code==404
    engine.dispose()


def test_unreviewed_directory_cannot_be_saved(monkeypatch):
    from fastapi import HTTPException
    import pytest
    monkeypatch.setattr(learning.access,'notebook',lambda *args,**kwargs:None)
    data=sample();data.entries[-1].needs_review=True
    with pytest.raises(HTTPException) as error:
        learning.save_directory_map('book',data,SimpleNamespace(id='owner'),None)
    assert error.value.status_code==422
