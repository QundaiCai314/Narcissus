from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest
from app import sharing,writings,access
from app.models import Base,User,Notebook,NotebookMember,Writing
from app.db import db_session
from app.security import current_user

@pytest.fixture
def setup(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[c.__table__ for c in [User,Notebook,NotebookMember,Writing]])
    with Session(engine) as db:
        for who in ['owner','viewer','editor','other']:db.add(User(id=who,email=who+'@example.com',password_hash='unused'))
        db.add(Notebook(id='book',user_id='owner',name='共享样例'));db.add(Notebook(id='private',user_id='other',name='其他私有'))
        db.add(Writing(id='note',notebook_id='book',kind='note',title='手记',content='人工协作样例',version=1));db.add(Writing(id='summary',notebook_id='book',kind='summary',title='不共享总结',content='不可见'))
        db.add(Writing(id='foreign',notebook_id='private',kind='note',title='其他私有手记',content='不可见'))
        db.add_all([NotebookMember(notebook_id='book',user_id='viewer',role='viewer'),NotebookMember(notebook_id='book',user_id='editor',role='editor')]);db.commit()
        monkeypatch.setattr(sharing,'settings',lambda:SimpleNamespace(collaboration_enabled=True))
        monkeypatch.setattr(sharing,'rate_limit',lambda *args:None);monkeypatch.setattr(writings,'ensure_idle',lambda *args:None)
        app=FastAPI();app.include_router(sharing.router);app.dependency_overrides[db_session]=lambda:db
        state={'user':'owner'};app.dependency_overrides[current_user]=lambda:SimpleNamespace(id=state['user'])
        with TestClient(app) as client:yield client,db,state
    engine.dispose()

def test_viewer_read_scope_write_denied_and_private_api_stays_private(setup):
    client,db,state=setup;state['user']='viewer'
    value=client.get('/shared-notebooks/book').json();assert value['role']=='viewer' and [n['id'] for n in value['notes']]==['note']
    assert client.put('/shared-notebooks/book/notes/note',json={'title':'改','content':'改','version':1}).status_code==403
    assert client.get('/shared-notebooks/private').status_code==404
    with pytest.raises(Exception):access.notebook(db,'viewer','book')

def test_editor_version_conflict_cross_notebook_and_owner_only_membership(setup):
    client,db,state=setup;state['user']='editor';body=dict(title='修订',content='人工修订内容',version=1)
    assert client.put('/shared-notebooks/book/notes/note',json=body).json()['version']==2
    assert client.put('/shared-notebooks/book/notes/note',json=body).status_code==409
    assert client.put('/shared-notebooks/book/notes/foreign',json=body).status_code==404
    assert client.put('/shared-notebooks/book/notes/summary',json=body).status_code==404
    assert client.get('/notebooks/book/members').status_code==404
    assert client.put('/notebooks/book/members',json={'email':'other@example.com','role':'editor'}).status_code==404

def test_owner_grant_downgrade_and_revoke_take_effect(setup):
    client,db,state=setup
    assert client.put('/notebooks/book/members',json={'email':'other@example.com','role':'editor'}).status_code==200
    state['user']='other';assert client.get('/shared-notebooks/book').json()['role']=='editor'
    state['user']='owner';assert client.put('/notebooks/book/members',json={'email':'other@example.com','role':'viewer'}).status_code==200
    state['user']='other';assert client.put('/shared-notebooks/book/notes/note',json={'title':'x','content':'x','version':1}).status_code==403
    state['user']='owner';assert client.delete('/notebooks/book/members/other').status_code==204
    state['user']='other';assert client.get('/shared-notebooks/book').status_code==404

def test_disabled_sharing_never_touches_membership_table(setup,monkeypatch):
    client,db,state=setup;monkeypatch.setattr(sharing,'settings',lambda:SimpleNamespace(collaboration_enabled=False))
    assert client.get('/sharing-capabilities').json()['enabled'] is False
    assert client.get('/shared-notebooks/book').status_code==503
    assert client.get('/notebooks/book/members').status_code==503
