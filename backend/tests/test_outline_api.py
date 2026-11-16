import io
import time
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app import source_api


def test_outline_upload_and_poll_do_not_import_a_document(monkeypatch):
    app=FastAPI();app.include_router(source_api.router)
    app.dependency_overrides[source_api.current_user]=lambda:SimpleNamespace(id='preview-owner')
    app.dependency_overrides[source_api.db_session]=lambda:None
    ownership=[]
    monkeypatch.setattr(source_api.access,'notebook',lambda db,owner,notebook:ownership.append((owner,notebook)))
    monkeypatch.setattr(source_api,'rate_limit',lambda *args:None)
    def forbidden(*args,**kwargs):raise AssertionError('Preview must not queue imports')
    monkeypatch.setattr(source_api,'create_job',forbidden)
    writer=PdfWriter();writer.add_blank_page(100,100);writer.add_outline_item('第1章 概论',0)
    data=io.BytesIO();writer.write(data)
    with TestClient(app) as client:
        response=client.post('/notebooks/book/outline-preview',files={'file':('contents.pdf',data.getvalue(),'application/pdf')})
        assert response.status_code==200
        ident=response.json()['job_id'];deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            response=client.get(f'/notebooks/book/outline-preview/{ident}')
            if response.json()['status']=='done':break
            time.sleep(.01)
        result=response.json()['result']
        assert result['model_calls']==result['embedding_calls']==0
        assert result['pages_read']==[] and result['entries'][0]['target_pdf_page']==1
        app.dependency_overrides[source_api.current_user]=lambda:SimpleNamespace(id='other-owner')
        assert client.get(f'/notebooks/book/outline-preview/{ident}').status_code==404
    assert ownership and ownership[0]==('preview-owner','book')
