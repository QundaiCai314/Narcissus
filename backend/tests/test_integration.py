"""Full-stack tests: real HTTP, PostgreSQL/pgvector, MinIO, Redis and Celery.
Only the external model protocol is a TEST fixture. Run in the isolated test project.
"""

import io
import json
import os
import time
import uuid
import threading
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select, func
from pypdf import PdfReader
from app.db import SessionLocal, engine
from app.models import Document, Chunk, Job, Message, User, now
from app.tasks import process_job, sweep
from app import storage
from .pdf_factory import pdf

BASE = os.getenv("TEST_BASE_URL", "http://localhost:3100")
MODEL = os.getenv("TEST_MODEL_URL", "http://localhost:8090")
HEADERS = {"X-Requested-With": "narcissus", "Origin": "http://localhost:3100"}


def wait_for(check, timeout=90):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = check()
        if last:
            return last
        time.sleep(0.5)
    pytest.fail(f"timed out waiting for state, last={last}")


def call(client, method, path, status=200, **kw):
    r = client.request(method, "/api" + path, **kw)
    assert r.status_code == status, (path, r.status_code, r.text[:1000])
    return r.json() if r.content else None


@pytest.fixture(scope="module")
def ctx():
    a = httpx.Client(base_url=BASE, headers=HEADERS, timeout=90)
    b = httpx.Client(base_url=BASE, headers=HEADERS, timeout=90)
    email = f"a-{uuid.uuid4().hex[:10]}@example.com"
    call(
        a,
        "POST",
        "/auth/register",
        201,
        json={"email": email, "password": "safe-test-password-123"},
    )
    call(
        b,
        "POST",
        "/auth/register",
        201,
        json={
            "email": f"b-{uuid.uuid4().hex[:10]}@example.com",
            "password": "safe-test-password-456",
        },
    )
    nb = call(a, "POST", "/notebooks", 201, json={"name": "青禾城市更新研究"})
    nb_b = call(b, "POST", "/notebooks", 201, json={"name": "第二位用户的独立空间"})
    yield {"a": a, "b": b, "nb": nb["id"], "nb_b": nb_b["id"], "email": email}
    a.close()
    b.close()


def upload(ctx, data=None, name="青禾研究.pdf"):
    return call(
        ctx["a"],
        "POST",
        f"/notebooks/{ctx['nb']}/documents?keep_copy=true",
        202,
        files={"file": (name, data or pdf(), "application/pdf")},
    )


def state(ctx, doc_id):
    docs = call(ctx["a"], "GET", f"/notebooks/{ctx['nb']}/documents")["items"]
    return next((d for d in docs if d["id"] == doc_id), None)


def ask(ctx, question, sources=None, conv=None):
    conv = (
        conv
        or call(ctx["a"], "POST", f"/notebooks/{ctx['nb']}/conversations", 201)["id"]
    )
    r = ctx["a"].post(
        f"/api/conversations/{conv}/ask",
        json={"question": question, "source_ids": sources},
    )
    assert r.status_code == 200, r.text
    events = []
    for block in r.text.split("\n\n"):
        lines = block.splitlines()
        typ = next((l[6:].strip() for l in lines if l.startswith("event:")), None)
        data = next((l[5:].strip() for l in lines if l.startswith("data:")), None)
        if typ and data:
            events.append((typ, json.loads(data)))
    return conv, events


def test_01_auth_and_ownership(ctx):
    a, b = ctx["a"], ctx["b"]
    me = call(a, "GET", "/auth/me")
    assert me["email"] == ctx["email"]
    with SessionLocal() as db:
        user = db.get(User, me["id"])
        assert user.password_hash.startswith("$argon2id$")
        assert "safe-test-password" not in user.password_hash
    for method, path, kw in [
        ("GET", f"/notebooks/{ctx['nb']}", {}),
        ("PATCH", f"/notebooks/{ctx['nb']}", {"json": {"name": "越权修改"}}),
        ("DELETE", f"/notebooks/{ctx['nb']}", {}),
        ("GET", f"/notebooks/{ctx['nb']}/documents", {}),
        ("POST", f"/notebooks/{ctx['nb']}/conversations", {}),
    ]:
        call(b, method, path, 404, **kw)
    assert (
        a.post(
            "/api/notebooks",
            headers={"Origin": "https://evil.example"},
            json={"name": "跨站"},
        ).status_code
        == 403
    )
    call(a, "PATCH", f"/notebooks/{ctx['nb']}", json={"name": "青禾城市更新 · 验证"})
    call(a, "POST", "/auth/logout", 204)
    assert a.get("/api/auth/me").status_code == 401
    call(
        a,
        "POST",
        "/auth/login",
        json={"email": ctx["email"], "password": "safe-test-password-123"},
    )


def test_02_async_pdf_and_private_file(ctx):
    data = pdf(
        [
            "青禾项目第一阶段预算为三百万元。主要工作包括城市绿化与社区公共空间改造。",
            "青禾项目第二阶段计划于二零二七年完成。重点建设无障碍设施和社区活动空间。",
        ]
    )
    doc = upload(ctx, data)
    ctx["doc"] = doc["id"]
    ctx["pdf"] = data
    assert doc["status"] == "queued"
    wait_for(lambda: state(ctx, doc["id"])["status"] == "ready")
    assert state(ctx, doc["id"])["pages"] == 2
    response = ctx["a"].get("/api/documents/" + doc["id"] + "/file")
    assert (
        response.content == data
        and response.headers["content-type"] == "application/pdf"
    )
    partial = ctx["a"].get(
        "/api/documents/" + doc["id"] + "/file", headers={"Range": "bytes=0-15"}
    )
    assert partial.status_code == 206 and partial.content == data[:16]
    for path in [f"/documents/{doc['id']}/file", f"/documents/{doc['id']}/retry"]:
        method = "POST" if path.endswith("retry") else "GET"
        call(ctx["b"], method, path, 404)
    call(ctx["b"], "DELETE", f"/documents/{doc['id']}", 404)
    with httpx.Client(base_url=BASE) as anonymous:
        assert anonymous.get("/api/documents/" + doc["id"] + "/file").status_code == 401
    with SessionLocal() as db:
        docrow = db.get(Document, doc["id"])
        ctx["object_key"] = docrow.object_key
        chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == doc["id"])))
        assert len(chunks) == 2 and {c.page for c in chunks} == {1, 2}
        job = db.scalar(
            select(Job).where(Job.document_id == doc["id"], Job.kind == "ingest")
        )
        ctx["job"] = job.id
    # Late duplicate delivery must leave the same identifiers and count.
    process_job(ctx["job"])
    with SessionLocal() as db:
        assert set(
            db.scalars(select(Chunk.id).where(Chunk.document_id == doc["id"]))
        ) == {c.id for c in chunks}
    unsigned = httpx.get(
        f"http://minio:9000/{storage.settings().s3_bucket}/{ctx['object_key']}"
    )
    assert unsigned.status_code == 403


def test_03_streaming_citation_followup_and_scope(ctx):
    second = upload(
        ctx,
        pdf(["青禾项目设立居民议事会。每月举行一次公开讨论，记录需求并跟踪改造进展。"]),
        "居民议事.pdf",
    )
    ctx["second"] = second["id"]
    wait_for(lambda: state(ctx, second["id"])["status"] == "ready")
    conv, events = ask(ctx, "第一阶段预算是多少？", [ctx["doc"]])
    ctx["conv"] = conv
    assert events[0][0] == "meta" and events[-1][1]["status"] == "complete"
    assert any(k == "delta" and "[1]" in d["text"] for k, d in events)
    msgs = call(ctx["a"], "GET", f"/conversations/{conv}/messages")["items"]
    answer = msgs[-1]
    ctx["answer"] = answer["id"]
    assert answer["status"] == "complete" and answer["citations"]
    for cite in answer["citations"]:
        assert cite["document_id"] == ctx["doc"]
        assert (
            cite["text"]
            in PdfReader(io.BytesIO(ctx["pdf"])).pages[cite["page"] - 1].extract_text()
        )
        with SessionLocal() as db:
            chunk = db.get(Chunk, cite["chunk_id"])
            assert chunk.text == cite["text"] and chunk.page == cite["page"]
    _, follow = ask(ctx, "它的下一阶段是什么？", None, conv)
    assert follow[-1][1]["status"] == "complete"
    retrieved = next(d["items"] for k, d in follow if k == "sources")
    assert {s["document_id"] for s in retrieved} == {ctx["doc"], ctx["second"]}
    call(ctx["b"], "GET", f"/conversations/{conv}/messages", 404)
    call(ctx["b"], "POST", f"/conversations/{conv}/ask", 404, json={"question": "越权"})
    call(ctx["b"], "POST", f"/messages/{ctx['answer']}/stop", 404)
    bconv = call(ctx["b"], "POST", f"/notebooks/{ctx['nb_b']}/conversations", 201)["id"]
    call(
        ctx["b"],
        "POST",
        f"/conversations/{bconv}/ask",
        404,
        json={"question": "越权选择资料", "source_ids": [ctx["doc"]]},
    )


def test_04_insufficient_and_invalid_citations(ctx):
    _, events = ask(ctx, "火星上有多少恐龙？")
    assert "当前资料中未找到足够依据" in "".join(
        d["text"] for k, d in events if k == "delta"
    )
    _, events = ask(ctx, "伪造引用测试")
    text = "".join(d["text"] for k, d in events if k == "delta")
    assert "[999]" not in text and "当前资料中未找到足够依据" in text


def test_05_fail_retry_and_stop(ctx):
    conv, events = ask(ctx, "服务失败测试")
    answer = call(ctx["a"], "GET", f"/conversations/{conv}/messages")["items"][-1]
    assert answer["status"] == "failed" and answer["error"]
    retry = ctx["a"].post(f"/api/messages/{answer['id']}/retry")
    assert retry.status_code == 200 and "event: error" in retry.text
    conv = call(ctx["a"], "POST", f"/notebooks/{ctx['nb']}/conversations", 201)["id"]
    done = []

    def consume():
        with httpx.Client(
            base_url=BASE, headers=HEADERS, cookies=ctx["a"].cookies, timeout=40
        ) as client:
            done.append(
                client.post(
                    f"/api/conversations/{conv}/ask", json={"question": "慢速回答测试"}
                )
            )

    thread = threading.Thread(target=consume)
    thread.start()
    rows = wait_for(
        lambda: call(ctx["a"], "GET", f"/conversations/{conv}/messages")["items"]
    )
    mid = rows[-1]["id"]
    call(
        ctx["a"],
        "POST",
        f"/conversations/{conv}/ask",
        409,
        json={"question": "重复生成"},
    )
    call(ctx["a"], "POST", f"/messages/{mid}/stop")
    thread.join(15)
    assert not thread.is_alive()
    assert (
        call(ctx["a"], "GET", f"/conversations/{conv}/messages")["items"][-1]["status"]
        == "stopped"
    )
    # A previous generator must never overwrite a newly retried answer.
    from app.qa import persist

    with SessionLocal() as db:
        msg = db.get(Message, mid)
        old_generation = msg.generation
        msg.generation += 1
        msg.status = "complete"
        msg.content = "new answer"
        db.commit()
    persist(mid, old_generation, "stale answer", "stopped", None, {}, [], set())
    with SessionLocal() as db:
        assert db.get(Message, mid).content == "new answer"


def test_06_processing_failure_retry(ctx):
    bad = upload(ctx, pdf(encrypted=True), "加密.pdf")
    wait_for(lambda: state(ctx, bad["id"])["status"] == "failed")
    assert "加密" in state(ctx, bad["id"])["error"]
    call(ctx["a"], "POST", f"/documents/{bad['id']}/retry", 202)
    wait_for(lambda: state(ctx, bad["id"])["status"] == "failed")
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == bad["id"])
            )
            == 0
        )
        assert db.get(Document, bad["id"]).generation == 1
    # Real transient model HTTP failures trigger finite Worker retries.
    httpx.post(MODEL + "/control", json={"embedding_failures": 1}).raise_for_status()
    good = upload(ctx, name="瞬时失败恢复.pdf")
    wait_for(lambda: state(ctx, good["id"])["status"] == "ready", 120)
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.document_id == good["id"]))
        assert job.attempts == 2 and job.status == "complete"


def test_07_delete_during_processing_and_cleanup_recovery(ctx):
    httpx.post(MODEL + "/control", json={"embedding_delay": 8}).raise_for_status()
    doc = upload(ctx, name="并发删除.pdf")
    wait_for(lambda: state(ctx, doc["id"])["status"] in ("processing", "indexing"))
    call(ctx["a"], "DELETE", f"/documents/{doc['id']}", 202)
    assert state(ctx, doc["id"]) is None

    def removed():
        with SessionLocal() as db:
            return db.get(Document, doc["id"]) is None

    wait_for(removed)
    httpx.post(MODEL + "/control", json={"embedding_delay": 0}).raise_for_status()
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == doc["id"])
            )
            == 0
        )
    call(ctx["a"], "DELETE", f"/documents/{ctx['second']}", 202)
    # Force a failed cleanup record to exercise the actual authorized retry endpoint.
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .where(Job.document_id == ctx["second"], Job.kind == "cleanup")
            .with_for_update()
        )
        if job:
            job.status = "failed"
            job.error = "test injected storage outage"
            job.available_at = now() + timedelta(hours=1)
            jobid = job.id
            db.commit()
        else:
            pytest.fail("cleanup job missing before dispatch")
    call(ctx["b"], "POST", f"/cleanup/{jobid}/retry", 404)
    call(ctx["a"], "POST", f"/cleanup/{jobid}/retry", 202)

    def cleaned():
        with SessionLocal() as db:
            return db.get(Job, jobid).status == "complete"

    wait_for(cleaned)


def test_08_database_reconnect_and_fresh_login(ctx):
    engine.dispose()
    with httpx.Client(base_url=BASE, headers=HEADERS) as fresh:
        call(
            fresh,
            "POST",
            "/auth/login",
            json={"email": ctx["email"], "password": "safe-test-password-123"},
        )
        assert call(fresh, "GET", f"/notebooks/{ctx['nb']}")["document_count"] >= 1
        assert (
            call(fresh, "GET", f"/conversations/{ctx['conv']}/messages")["total"] == 4
        )
        assert fresh.get(f"/api/documents/{ctx['doc']}/file").content == ctx["pdf"]


def test_09_recover_expired_worker_lease(ctx):
    doc = upload(ctx, name="宕机恢复.pdf")
    with SessionLocal() as db:
        row = db.get(Document, doc["id"])
        row.status = "processing"
        job = db.scalar(
            select(Job).where(Job.document_id == doc["id"]).with_for_update()
        )
        job.status = "running"
        job.claim = str(uuid.uuid4())
        job.attempts = 1
        job.started_at = now() - timedelta(seconds=400)
        db.commit()
    sweep()
    wait_for(lambda: state(ctx, doc["id"])["status"] == "ready")
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.document_id == doc["id"]))
        assert job.attempts == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == doc["id"])
            )
            == 1
        )


def test_10_notebook_delete_and_upload_limits(ctx):
    call(
        ctx["a"],
        "POST",
        f"/notebooks/{ctx['nb']}/documents",
        422,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    call(
        ctx["a"],
        "POST",
        f"/notebooks/{ctx['nb']}/documents",
        413,
        files={
            "file": (
                "large.pdf",
                b"%PDF-" + b"x" * (200 * 1024 * 1024),
                "application/pdf",
            )
        },
    )
    nb = call(ctx["a"], "POST", "/notebooks", 201, json={"name": "验证删除整个笔记本"})[
        "id"
    ]
    d = call(
        ctx["a"],
        "POST",
        f"/notebooks/{nb}/documents",
        202,
        files={"file": ("remove.pdf", pdf(), "application/pdf")},
    )
    conv = call(ctx["a"], "POST", f"/notebooks/{nb}/conversations", 201)["id"]
    call(ctx["a"], "DELETE", f"/notebooks/{nb}", 202)
    call(ctx["a"], "GET", f"/notebooks/{nb}", 404)
    call(ctx["a"], "GET", f"/documents/{d['id']}/file", 404)
    call(ctx["a"], "GET", f"/conversations/{conv}/messages", 404)

    def gone():
        from app.models import Notebook, Conversation

        with SessionLocal() as db:
            return (
                db.get(Notebook, nb) is None
                and db.get(Document, d["id"]) is None
                and db.get(Conversation, conv) is None
            )

    wait_for(gone)


def test_11_login_rate_limit():
    with httpx.Client(base_url=BASE, headers=HEADERS) as client:
        email = "limit-" + uuid.uuid4().hex[:10] + "@example.com"
        for _ in range(12):
            call(
                client,
                "POST",
                "/auth/login",
                401,
                json={"email": email, "password": "wrong-password-123"},
            )
        call(
            client,
            "POST",
            "/auth/login",
            429,
            json={"email": email, "password": "wrong-password-123"},
        )
