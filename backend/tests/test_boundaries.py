"""Additional real-service regression checks for disconnects and concurrent uploads."""

import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Document, Job, now
from app.tasks import sweep
from datetime import timedelta
from .test_integration import BASE, HEADERS, call, wait_for
from .pdf_factory import pdf


@pytest.fixture(scope="module")
def boundary():
    client = httpx.Client(base_url=BASE, headers=HEADERS, timeout=60)
    call(
        client,
        "POST",
        "/auth/register",
        201,
        json={
            "email": f"boundary-{uuid.uuid4().hex[:10]}@example.com",
            "password": "boundary-password-123",
        },
    )
    nb = call(client, "POST", "/notebooks", 201, json={"name": "并发与断线验收"})["id"]
    doc = call(
        client,
        "POST",
        f"/notebooks/{nb}/documents?keep_copy=true",
        202,
        files={"file": ("boundary.pdf", pdf(), "application/pdf")},
    )["id"]

    def ready():
        return any(
            d["id"] == doc and d["status"] == "ready"
            for d in call(client, "GET", f"/notebooks/{nb}/documents")["items"]
        )

    wait_for(ready)
    yield client, nb, doc
    client.close()


def test_http_disconnect_persists_stopped_and_retry(boundary):
    client, nb, _ = boundary
    conv = call(client, "POST", f"/notebooks/{nb}/conversations", 201)["id"]
    with client.stream(
        "POST", f"/api/conversations/{conv}/ask", json={"question": "慢速断线验收"}
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                break

    def stopped():
        rows = call(client, "GET", f"/conversations/{conv}/messages")["items"]
        return rows[-1] if rows and rows[-1]["status"] == "stopped" else None

    answer = wait_for(stopped, 15)
    retried = client.post(f"/api/messages/{answer['id']}/retry")
    assert retried.status_code == 200 and "event: done" in retried.text
    result = call(client, "GET", f"/conversations/{conv}/messages")["items"][-1]
    assert result["status"] == "complete" and result["citations"]


def test_direct_backend_isolation(boundary):
    owner, nb, doc = boundary
    with httpx.Client(
        base_url="http://api:8000", headers=HEADERS, timeout=30
    ) as outsider:
        call(
            outsider,
            "POST",
            "/auth/register",
            201,
            json={
                "email": f"outsider-{uuid.uuid4().hex[:10]}@example.com",
                "password": "outsider-password-123",
            },
        )
        call(outsider, "GET", f"/notebooks/{nb}", 404)
        call(outsider, "GET", f"/documents/{doc}/file", 404)
        conv = call(outsider, "POST", "/notebooks", 201, json={"name": "独立资料空间"})[
            "id"
        ]
        cid = call(outsider, "POST", f"/notebooks/{conv}/conversations", 201)["id"]
        call(
            outsider,
            "POST",
            f"/conversations/{cid}/ask",
            404,
            json={"question": "越权读取", "source_ids": [doc]},
        )


def test_concurrent_upload_cap(boundary):
    owner, _, _ = boundary
    nb = call(owner, "POST", "/notebooks", 201, json={"name": "十份资料的并发上限"})[
        "id"
    ]
    cookies = {"narcissus_session": owner.cookies.get("narcissus_session")}

    def upload(i):
        with httpx.Client(
            base_url=BASE, headers=HEADERS, cookies=cookies, timeout=60
        ) as client:
            return client.post(
                f"/api/notebooks/{nb}/documents?keep_copy=true",
                files={"file": (f"{i}.pdf", pdf(), "application/pdf")},
            ).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(upload, range(12)))
    assert codes.count(202) == 10 and codes.count(409) == 2, codes
    assert len(call(owner, "GET", f"/notebooks/{nb}/documents")["items"]) == 10
    call(owner, "DELETE", f"/notebooks/{nb}", 202)


def test_expired_job_exhausts_bounded_attempts(boundary):
    owner, nb, _ = boundary
    doc = call(
        owner,
        "POST",
        f"/notebooks/{nb}/documents?keep_copy=true",
        202,
        files={"file": ("exhausted.pdf", pdf(), "application/pdf")},
    )["id"]
    with SessionLocal() as db:
        d = db.get(Document, doc)
        d.status = "processing"
        job = db.scalar(select(Job).where(Job.document_id == doc).with_for_update())
        job.status = "running"
        job.claim = str(uuid.uuid4())
        job.attempts = 3
        job.started_at = now() - timedelta(seconds=400)
        db.commit()
    sweep()
    with SessionLocal() as db:
        assert db.get(Document, doc).status == "failed"
        job = db.scalar(select(Job).where(Job.document_id == doc))
        assert job.attempts == 3 and job.status == "failed"
