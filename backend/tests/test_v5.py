"""V5: real parsers/OCR/DB/outbox/storage; synthetic models only in isolated test stack."""
import io
import json
import socket
import uuid
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from docx import Document as Word
from PIL import Image
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select, func
from app.source_parsing import parse_file, make_chunks, decode_text
from app.pdf_processing import InvalidPDF
from app import web_import
from app.models import SourceVersion, Document, Chunk, Job, uid, now
from app.db import SessionLocal
from app.tasks import process_job
from .test_integration import BASE, HEADERS, call, wait_for
from .pdf_factory import pdf

TEXT = "青禾项目第一阶段预算为三百万元。主要工作包括城市绿化与社区公共空间改造。"
SECOND = "青禾项目第二阶段计划于二零二七年完成。重点建设社区活动空间和无障碍设施。"
SCAN = Path(__file__).parent / "fixtures/chinese-scan.png"


@pytest.fixture(autouse=True)
def deterministic_dns(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings(), "web_dns_mode", "system")


def word():
    doc = Word()
    doc.add_heading("青禾社区计划", 1)
    doc.add_paragraph(TEXT)
    doc.add_paragraph("每季度召开一次居民座谈会。", style="List Bullet")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0,0).text="阶段"; table.cell(0,1).text="工作"
    table.cell(1,0).text="第二阶段"; table.cell(1,1).text=SECOND
    out=io.BytesIO(); doc.save(out); return out.getvalue()


def scanned_pdf(mixed=False):
    image=Image.open(SCAN).convert("RGB")
    out=io.BytesIO(); image.save(out,format="PDF")
    if not mixed: return out.getvalue()
    writer=PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(pdf([TEXT]))).pages[0])
    writer.add_page(PdfReader(io.BytesIO(out.getvalue())).pages[0])
    out=io.BytesIO(); writer.write(out); return out.getvalue()


def test_docx_order_and_true_locations():
    units,info=parse_file("docx",word())
    assert [u["location"]["kind"] for u in units]==["heading","paragraph","list","table","table"]
    assert units[1]["text"]==TEXT and units[-1]["location"]["table"]==1
    assert units[-1]["location"]["heading"]=="青禾社区计划"
    assert all(p["page"] is None for p in make_chunks(units))


@pytest.mark.parametrize("encoding",["utf-8","utf-8-sig","gb18030","utf-16"])
def test_chinese_encodings(encoding):
    assert decode_text(TEXT.encode(encoding))[0]==TEXT


def test_invalid_encoding_and_zip_limits(monkeypatch):
    with pytest.raises(InvalidPDF):decode_text(b"\x00\x01\xff\x03")
    from app.config import settings
    monkeypatch.setattr(settings(),"max_unpacked_mb",0)
    with pytest.raises(InvalidPDF,match="解压"):parse_file("docx",word())


def test_markdown_is_inert_and_keeps_lines():
    units,_=parse_file("markdown",("# 社区\n\n"+TEXT+'\n<script>alert(1)</script>\n![x](http://127.0.0.1/)').encode())
    assert units[1]["location"]["line"]==3
    assert "<script>" in units[2]["text"]  # Plain text, never executed or fetched.


@pytest.mark.parametrize("url",["file:///etc/passwd","https://user:pass@example.com/","http://example.com:8080/","http://localhost/","https://example.com\\@127.0.0.1/","http://[fe80::1%25eth0]/"])
def test_web_url_boundary(url):
    with pytest.raises(InvalidPDF):web_import.validate_url(url)


@pytest.mark.parametrize("ip",["127.0.0.1","10.0.0.1","192.168.0.1","169.254.169.254","::1","fc00::1","::ffff:127.0.0.1","0.0.0.0","224.0.0.1"])
def test_web_dns_boundary(monkeypatch,ip):
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:[(2,1,6,"",(ip,80))])
    with pytest.raises(InvalidPDF):web_import.resolve_public("public.example",80)


def test_redirect_revalidation_and_pinning(monkeypatch):
    lookups=[]; connections=[]
    def resolve(host,port,**kw):
        lookups.append(host)
        return [(2,1,6,"",("93.184.215.14" if len(lookups)==1 else "127.0.0.1",port))]
    class Response:
        status=302
        def getheader(self,key,default=None):return "http://public.example/again" if key=="Location" else default
    class Conn:
        def request(self,*a,**kw):
            assert "Cookie" not in kw["headers"] and "Authorization" not in kw["headers"]
        def getresponse(self):return Response()
        def close(self):pass
    def connect(host,port,ip,secure,timeout):connections.append(ip);return Conn()
    monkeypatch.setattr(socket,"getaddrinfo",resolve)
    monkeypatch.setattr(web_import,"connect_pinned",connect)
    with pytest.raises(InvalidPDF,match="公网"):web_import.fetch_public("http://public.example/")
    assert len(lookups)==2 and connections==["93.184.215.14"]


def test_web_extraction_and_access_barriers():
    meta={"mime":"text/html","domain":"example.com"}
    content=f'<html><head><title>社区计划</title><meta name="author" content="测试作者"></head><article><h1>社区计划</h1><p>{TEXT*4}</p><p>{SECOND}</p><script>secret()</script></article></html>'
    title,units,info=web_import.extract_web(content.encode(),meta)
    assert title=="社区计划" and info["author"]=="测试作者"
    assert not any("secret()" in u["text"] for u in units)
    for html in ['<title>请登录</title><p>'+TEXT*4+'</p>','<title>验证码</title><p>'+TEXT*4+'</p>','<div id="app"></div>','<article><p>'+TEXT*4+'登录后查看</p></article>']:
        with pytest.raises(InvalidPDF):web_import.extract_web(html.encode(),meta)


@pytest.mark.parametrize("kind",["image","scan","mixed"])
def test_real_local_ocr(kind):
    units,info=parse_file("image" if kind=="image" else "pdf",SCAN.read_bytes() if kind=="image" else scanned_pdf(kind=="mixed"))
    assert not info["failed_pages"] and "三百万元" in "\n".join(u["text"] for u in units)
    assert info["ocr_pages"]==([2] if kind=="mixed" else [1])
    assert all(0 < u["confidence"] <= 100 for u in units if u.get("ocr"))
    if kind=="mixed":assert not units[0]["ocr"] and units[1]["location"]["page"]==2


def test_partial_ocr_and_only_failed_page_retry(monkeypatch):
    from app import source_parsing
    from app.ocr import OCRFailure
    monkeypatch.setattr(source_parsing.LocalOCR,"page",lambda *a: (_ for _ in ()).throw(OCRFailure("测试超时")))
    units,info=parse_file("pdf",scanned_pdf(True))
    assert len(units)==1 and info["failed_pages"]==[{"page":2,"error":"测试超时"}]
    monkeypatch.setattr(source_parsing.LocalOCR,"page",lambda *a:(SECOND,90))
    progress=[]
    newer,info=parse_file("pdf",scanned_pdf(True),lambda p,n,s:progress.append(p),units)
    assert len(newer)==2 and progress==[2] and not info["failed_pages"]


@pytest.fixture(scope="module")
def ctx5():
    a,b=[httpx.Client(base_url=BASE,headers=HEADERS,timeout=100) for _ in range(2)]
    for c in (a,b):call(c,"POST","/auth/register",201,json={"email":f"v5-{uuid.uuid4().hex[:12]}@example.com","password":"v5-test-password-2026"})
    nb=call(a,"POST","/notebooks",201,json={"name":"第五版多来源验收"})["id"]
    yield {"a":a,"b":b,"nb":nb}
    a.delete("/api/notebooks/"+nb)
    a.close();b.close()


def source_done(c,doc,version=1):
    result=call(c,"GET",f"/documents/{doc}/snapshot?version={version}")
    assert result["status"] not in ("failed","cancelled"),result
    return result if result["status"]=="ready" else None


def test_stack_import_versions_permissions_and_history(ctx5):
    c,b,nb=ctx5["a"],ctx5["b"],ctx5["nb"]
    docs=[]
    for name,raw in [("社区.docx",word()),("计划.txt",SECOND.encode("gb18030")),("要点.md",("# 青禾资料\n"+TEXT+SECOND).encode()),("原文.pdf",pdf())]:
        docs.append(call(c,"POST",f"/notebooks/{nb}/documents",202,files={"file":(name,raw)})["id"])
    pasted=call(c,"POST",f"/notebooks/{nb}/sources/text",202,json={"title":"居民意见","text":TEXT+"每季度召开一次居民座谈会。"})["id"]
    docs.append(pasted);ctx5["docs"]=docs;ctx5["paste"]=pasted
    for doc in docs:wait_for(lambda:source_done(c,doc))
    with SessionLocal() as db:
        for doc in docs:
            assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id==doc))>0
        assert db.get(Document,pasted).active_version==1
    for path in [f"/documents/{pasted}/snapshot",f"/documents/{pasted}/file?version=1"]:call(b,"GET",path,404)
    for path,body in [("content",{"version":1,"title":"入侵","text":SECOND}),("confirm",{"version":1}),("cancel",{"version":1}),("reprocess",{"version":1})]:
        call(b,"PUT" if path=="content" else "POST",f"/documents/{pasted}/{path}",404,json=body)
    conv=call(c,"POST",f"/notebooks/{nb}/conversations",201)["id"]
    response=c.post(f"/api/conversations/{conv}/ask",json={"question":"这些资料主要讲了什么？","source_ids":docs})
    assert response.status_code==200 and "event: done" in response.text
    messages=call(c,"GET",f"/conversations/{conv}/messages")["items"]
    refs=messages[-1]["citations"]
    assert refs and all(r["version"]==1 and r["position"] for r in refs)
    assert all(r["page"] is None for r in refs if r["source_type"]!="pdf")
    body={"version":1,"title":"居民意见修订","text":TEXT+"每月召开一次居民座谈会。"}
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:c.put(f"/api/documents/{pasted}/content",json=body),range(2)))
    assert sorted(r.status_code for r in responses)==[202,409]
    old=call(c,"GET",f"/documents/{pasted}/snapshot?version=1")
    assert "每季度" in old["units"][0]["text"]
    wait_for(lambda:source_done(c,pasted,2))
    old=call(c,"GET",f"/documents/{pasted}/snapshot?version=1")
    assert old["changed"] and "每季度" in old["units"][0]["text"]
    assert call(c,"GET",f"/conversations/{conv}/messages")["items"][-1]["citations"]==refs
    with SessionLocal() as db:
        job=db.scalar(select(Job).where(Job.document_id==pasted,Job.kind=="ingest",Job.generation==2))
        job_id=job.id
        before=db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id==pasted))
    process_job(job_id)
    with SessionLocal() as db:assert before==db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id==pasted))


def test_stack_duplicates_cancel_and_delete(ctx5):
    c,nb=ctx5["a"],ctx5["nb"]
    call(c,"POST",f"/notebooks/{nb}/documents",409,files={"file":("原文副本.pdf",pdf())})
    duplicate=call(c,"POST",f"/notebooks/{nb}/documents?keep_copy=true",202,files={"file":("独立原文.pdf",pdf())})["id"]
    wait_for(lambda:source_done(c,duplicate))
    pending=call(c,"POST",f"/notebooks/{nb}/sources/text",202,json={"title":"取消测试","text":"取消任务不会重新建立索引。"*20})["id"]
    result=c.post(f"/api/documents/{pending}/cancel",json={"version":1})
    assert result.status_code==200
    with SessionLocal() as db:job_id=db.scalar(select(Job.id).where(Job.document_id==pending,Job.kind=="ingest"))
    process_job(job_id)
    assert call(c,"GET",f"/documents/{pending}/snapshot")["status"]=="cancelled"
    call(c,"DELETE",f"/documents/{pending}",202)
    process_job(job_id)
    call(c,"GET",f"/documents/{pending}/snapshot",404)
    call(c,"GET",f"/documents/{pending}/file",404)


def test_stack_image_correction_keeps_original_and_old_snapshot(ctx5):
    c,nb=ctx5["a"],ctx5["nb"]
    doc=call(c,"POST",f"/notebooks/{nb}/documents",202,files={"file":("中文扫描.png",SCAN.read_bytes(),"image/png")})["id"]
    old=wait_for(lambda:source_done(c,doc),120)
    assert old["units"][0]["ocr"]
    body={"version":1,"title":"修正后的扫描文字","corrections":{old["units"][0]["id"]:TEXT+"修正说明：每季度召开居民座谈会。"}}
    call(c,"PUT",f"/documents/{doc}/content",202,json=body)
    new=wait_for(lambda:source_done(c,doc,2))
    assert new["units"][0]["user_corrected"]
    assert c.get(f"/api/documents/{doc}/file?version=1").content==c.get(f"/api/documents/{doc}/file?version=2").content==SCAN.read_bytes()
    assert call(c,"GET",f"/documents/{doc}/snapshot?version=1")["units"]==old["units"]


def test_stack_mixed_sources_all_generators(ctx5):
    from .test_v2 import completed
    from .test_v3 import done
    from .test_v4 import script_done
    c,nb,docs=ctx5["a"],ctx5["nb"],ctx5["docs"][:2]
    guide=call(c,"GET",f"/documents/{docs[0]}/guide")
    wait_for(lambda:completed(c,guide["id"]))
    summary=call(c,"POST",f"/notebooks/{nb}/summaries",202,json={"title":"混合资料总结","document_ids":docs})
    result=wait_for(lambda:completed(c,summary["id"]))
    assert result["citations"] and all(r["page"] is None and r["position"] for r in result["citations"])
    for kind in ("mindmap","flashcards","quiz"):
        row=call(c,"POST",f"/notebooks/{nb}/learning",202,json={"request_key":str(uuid.uuid4()),"kind":kind,"document_ids":docs})
        result=wait_for(lambda:done(c,row["id"]),120)
        if kind!="quiz":assert result["citations"] and all(r["page"] is None for r in result["citations"])
    audio=call(c,"POST",f"/notebooks/{nb}/audio",202,json={"request_key":str(uuid.uuid4()),"document_ids":docs,"mode":"single","length":"short"})
    script=script_done(ctx5,audio["id"])
    assert script["citations"] and all(r["page"] is None and r["position"] for r in script["citations"])


def manual_candidate(nb, kind, raw=None, document_id=None, version=1):
    """Durable outbox with a future dispatch stamp: only this test executes acquisition."""
    from app import storage
    with SessionLocal() as db:
        doc = db.get(Document, document_id) if document_id else None
        if not doc:
            identity = uid()
            doc = Document(id=identity, notebook_id=nb, filename="测试来源", source_type=kind,
                object_key=f"test-v5/{identity}/1", size=len(raw or b""), generation=1, active_version=0, status="queued")
            db.add(doc); db.flush()
        doc.generation = version
        key = f"test-v5/{doc.id}/{version}"
        ver = SourceVersion(document_id=doc.id, version=version, title="测试来源", object_key=key,
            source_url="https://example.com/article" if kind=="web" else None, units=[], details={}, status="queued")
        job = Job(document_id=doc.id, kind="ingest", generation=version, object_key=key, dispatched_at=now()+timedelta(days=1))
        db.add_all([ver,job]); db.commit()
        if raw:storage.put(key,raw)
        return doc.id, job.id


def test_stack_web_confirmation_versions_and_failed_refresh(ctx5,monkeypatch):
    c,b=ctx5["a"],ctx5["b"]
    nb=call(c,"POST","/notebooks",201,json={"name":"网页确认与回退"})["id"]
    original=f"<title>社区网页</title><article><h1>社区计划</h1><p>{TEXT*4}</p><p>{SECOND}</p></article>".encode()
    meta={"mime":"text/html","domain":"example.com","url":"https://example.com/article","original_url":"https://example.com/article"}
    monkeypatch.setattr(web_import,"fetch_public",lambda url:(original,meta))
    doc,job=manual_candidate(nb,"web")
    process_job(job)
    snap=call(c,"GET",f"/documents/{doc}/snapshot")
    assert snap["status"]=="awaiting_confirmation" and snap["details"]["fetched_at"]
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id==doc))==0
    call(b,"GET",f"/documents/{doc}/snapshot",404)
    call(b,"POST",f"/documents/{doc}/confirm",404,json={"version":1})
    confirmed={"version":1,"title":"我整理的网页","text":TEXT+SECOND}
    call(c,"POST",f"/documents/{doc}/confirm",202,json=confirmed)
    call(c,"POST",f"/documents/{doc}/confirm",202,json=confirmed)
    ready=wait_for(lambda:source_done(c,doc))
    assert ready["details"]["user_adjusted"] and ready["details"]["original_units"]==snap["units"]
    assert c.get(f"/api/documents/{doc}/file?version=1").content==original
    _,job=manual_candidate(nb,"web",document_id=doc,version=2)
    monkeypatch.setattr(web_import,"fetch_public",lambda url:(_ for _ in ()).throw(InvalidPDF("网页需要登录")))
    process_job(job)
    assert call(c,"GET",f"/documents/{doc}/snapshot?version=2")["status"]=="failed"
    assert call(c,"GET",f"/documents/{doc}/snapshot")["version"]==1
    assert call(c,"GET",f"/notebooks/{nb}/documents")["items"][0]["status"]=="ready"
    call(c,"DELETE",f"/notebooks/{nb}",202)
    process_job(job)
    call(c,"GET",f"/documents/{doc}/snapshot",404)


def test_stack_partial_ocr_confirmation_and_retry(ctx5,monkeypatch):
    from app import source_parsing
    from app.ocr import OCRFailure
    c=ctx5["a"]
    nb=call(c,"POST","/notebooks",201,json={"name":"部分识别验收"})["id"]
    doc,job=manual_candidate(nb,"pdf",scanned_pdf(True))
    monkeypatch.setattr(source_parsing.LocalOCR,"page",lambda *a:(_ for _ in ()).throw(OCRFailure("测试页面超时")))
    process_job(job)
    snap=call(c,"GET",f"/documents/{doc}/snapshot")
    assert snap["status"]=="awaiting_confirmation" and snap["details"]["failed_pages"][0]["page"]==2
    call(c,"POST",f"/documents/{doc}/confirm",422,json={"version":1})
    call(c,"POST",f"/documents/{doc}/confirm",202,json={"version":1,"accept_partial":True})
    partial=wait_for(lambda:source_done(c,doc))
    assert partial["details"]["partial_confirmed"] and len(partial["units"])==1
    call(c,"POST",f"/documents/{doc}/reprocess",202,json={"version":1})
    # The real worker uses real OCR; successful native page is reused, not reprocessed.
    full=wait_for(lambda:source_done(c,doc,2),120)
    assert len(full["units"])==2 and not full["details"]["failed_pages"]
    assert call(c,"GET",f"/documents/{doc}/snapshot?version=1")["details"]["failed_pages"]
    call(c,"DELETE",f"/notebooks/{nb}",202)
