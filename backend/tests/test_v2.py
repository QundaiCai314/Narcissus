"""V2 integration tests run only in the isolated Compose project with protocol fixtures."""

import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import httpx
import pytest
from docx import Document as WordDocument
from sqlalchemy import select, func
from app.db import SessionLocal
from app.models import Writing, WritingCitation, GenerationJob, Notebook, now
from app.generation import process, fail_job, parse_result
from app.model_service import ModelError
from .test_integration import BASE, MODEL, HEADERS, call, wait_for
from .pdf_factory import pdf


@pytest.fixture(scope="module")
def v2():
    a, b = [httpx.Client(base_url=BASE, headers=HEADERS, timeout=90) for _ in range(2)]
    for client in (a, b):
        call(
            client,
            "POST",
            "/auth/register",
            201,
            json={
                "email": f"v2-{uuid.uuid4().hex[:12]}@example.com",
                "password": "safe-v2-password-2026",
            },
        )
    nb = call(a, "POST", "/notebooks", 201, json={"name": "第二版验收"})["id"]
    doc = call(
        a,
        "POST",
        f"/notebooks/{nb}/documents",
        202,
        files={"file": ("预算依据.pdf", pdf(), "application/pdf")},
    )["id"]
    wait_for(
        lambda: any(
            d["id"] == doc and d["status"] == "ready"
            for d in call(a, "GET", f"/notebooks/{nb}/documents")["items"]
        )
    )
    yield {"a": a, "b": b, "nb": nb, "doc": doc}
    a.close()
    b.close()


def get(c, wid):
    return call(c, "GET", f"/writings/{wid}")


def completed(c, wid):
    w = get(c, wid)
    if w["job"] and w["job"]["status"] == "failed":
        pytest.fail(str(w["job"]))
    return w if w["job"] and w["job"]["status"] == "complete" else None


def test_01_automatic_guide_and_idempotency(v2):
    c = v2["a"]
    guide = wait_for(lambda: call(c, "GET", f"/documents/{v2['doc']}/guide"))
    guide = wait_for(lambda: completed(c, guide["id"]))
    assert len(guide["details"]["structured"]["questions"]) == 3
    assert guide["citations"][0]["text"] and guide["citations"][0]["page"] == 1
    assert guide["details"]["inputs"]["documents"][0]["version"] == 1
    process(guide["job"]["id"])
    assert get(c, guide["id"])["version"] == guide["version"]
    call(v2["b"], "GET", f"/documents/{v2['doc']}/guide", 404)
    # Repeated regenerate requests while queued/running must reuse the same task.
    x = call(c, "POST", f"/documents/{v2['doc']}/guide", 202)
    y = call(c, "POST", f"/documents/{v2['doc']}/guide", 202)
    assert x["job"]["id"] == y["job"]["id"]
    wait_for(lambda: completed(c, x["id"]))


def test_02_manual_note_and_revision_conflict(v2):
    c = v2["a"]
    note = call(
        c,
        "POST",
        f"/notebooks/{v2['nb']}/notes",
        201,
        json={
            "title": "用户看法",
            "content": "我建议优先改善步行空间，这只是个人建议。",
        },
    )
    v2["note"] = note["id"]

    def save(text):
        return c.patch(
            f"/api/writings/{note['id']}",
            json={"title": "用户看法", "content": text, "version": note["version"]},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(save, ["较早的内容", "最新意见：我希望先改善步行空间。"])
        )
    assert sorted(results) == [200, 409]
    saved = get(c, note["id"])
    assert saved["version"] == 2 and saved["edited"]
    call(v2["b"], "GET", f"/writings/{note['id']}", 404)
    call(
        v2["b"],
        "PATCH",
        f"/writings/{note['id']}",
        404,
        json={"title": "越权", "content": "bad", "version": 2},
    )
    call(v2["b"], "DELETE", f"/writings/{note['id']}", 404)
    call(v2["b"], "GET", f"/writings/{note['id']}/export?format=docx", 404)


def test_03_answer_saved_with_citation_snapshot(v2):
    c = v2["a"]
    conv = call(c, "POST", f"/notebooks/{v2['nb']}/conversations", 201)["id"]
    response = c.post(
        f"/api/conversations/{conv}/ask",
        json={"question": "第一阶段预算是多少？", "source_ids": [v2["doc"]]},
    )
    assert response.status_code == 200 and "event: done" in response.text
    msg = call(c, "GET", f"/conversations/{conv}/messages")["items"][-1]
    note = call(c, "POST", f"/messages/{msg['id']}/save-note", 201)
    repeated = call(c, "POST", f"/messages/{msg['id']}/save-note", 201)
    assert note["id"] == repeated["id"]
    assert note["citations"][0]["text"] == msg["citations"][0]["text"]
    v2["saved"] = note["id"]
    call(v2["b"], "POST", f"/messages/{msg['id']}/save-note", 404)


def test_04_mixed_summary_provenance_and_exports(v2):
    c = v2["a"]
    data = {
        "title": "评审总结",
        "document_ids": [v2["doc"]],
        "note_ids": [v2["note"]],
        "purpose": "准备项目评审",
        "audience": "项目负责人",
        "length": "short",
    }
    summary = call(c, "POST", f"/notebooks/{v2['nb']}/summaries", 202, json=data)
    duplicate = call(c, "POST", f"/notebooks/{v2['nb']}/summaries", 202, json=data)
    assert summary["id"] == duplicate["id"]
    summary = wait_for(lambda: completed(c, summary["id"]))
    v2["summary"] = summary["id"]
    assert "来自用户笔记（未经原始资料核验）" in summary["content"]
    assert {x["kind"] for x in summary["citations"]} == {"document", "note"}
    assert summary["details"]["inputs"]["notes"][0]["id"] == v2["note"]
    for section in ("概览", "主要发现", "关键细节", "尚不确定或资料不足的部分"):
        assert section in summary["content"]
    md = c.get(f"/api/writings/{summary['id']}/export?format=md")
    assert md.status_code == 200 and "原文快照" in md.text and "PDF 第 1 页" in md.text
    docx = c.get(f"/api/writings/{summary['id']}/export?format=docx")
    assert docx.status_code == 200
    word = WordDocument(io.BytesIO(docx.content))
    texts = "\n".join(p.text for p in word.paragraphs)
    assert "评审总结" in texts and "用户笔记" in texts and "来源引用" in texts
    assert any(p.style.name.startswith("Heading") for p in word.paragraphs)
    assert any(p.style.name == "List Bullet" for p in word.paragraphs)


def test_05_retry_bounded_lease_and_wrong_citations(v2):
    c = v2["a"]
    with httpx.Client() as control:
        control.post(MODEL + "/control", json={"generation_failures": 1})
    row = call(
        c,
        "POST",
        f"/notebooks/{v2['nb']}/summaries",
        202,
        json={"note_ids": [v2["note"]], "purpose": "生成失败验收"},
    )
    row = wait_for(lambda: completed(c, row["id"]))
    assert row["job"]["attempts"] == 2
    request = {
        "documents": [],
        "notes": [],
        "purpose": "",
        "audience": "",
        "length": "short",
    }
    with SessionLocal() as db:
        w = Writing(notebook_id=v2["nb"], kind="summary", title="租约恢复", content="")
        db.add(w)
        db.flush()
        job = GenerationJob(
            writing_id=w.id,
            generation=1,
            status="running",
            request=request,
            attempts=3,
            started_at=now() - timedelta(seconds=400),
            claim="old",
        )
        db.add(job)
        db.commit()
        jid = job.id
    fail_job(jid, None, "超时")
    with SessionLocal() as db:
        assert db.get(GenerationJob, jid).status == "failed"
    with pytest.raises(ModelError):
        parse_result(
            json.dumps(
                {
                    "abstract": [{"text": "假来源", "refs": [999]}],
                    "topics": [],
                    "questions": [],
                }
            ),
            "guide",
            [{"label": 1, "kind": "document"}],
        )


def test_generation_rejects_mixed_authority_and_empty_refs():
    sources = [{"label": 1, "kind": "document"}, {"label": 2, "kind": "note"}]
    for refs in ([1, 2], []):
        data = {key: [{"text": "不能混淆资料与用户观点", "refs": refs}]
                for key in ("overview", "findings", "details", "uncertainties")}
        with pytest.raises(ModelError):
            parse_result(json.dumps(data), "summary", sources)


def test_06_deleted_sources_keep_snapshots_and_exports(v2):
    c = v2["a"]
    saved = get(c, v2["saved"])
    call(c, "DELETE", f"/documents/{v2['doc']}", 202)
    after = get(c, v2["saved"])
    assert (
        after["content"] == saved["content"]
        and after["citations"][0]["state"] == "deleted"
    )
    assert after["citations"][0]["text"] == saved["citations"][0]["text"]
    assert (
        "原始资料已删除" in c.get(f"/api/writings/{after['id']}/export?format=md").text
    )
    call(c, "DELETE", f"/writings/{v2['note']}", 204)
    summary = get(c, v2["summary"])
    assert all(x["state"] == "deleted" for x in summary["citations"])
    new = call(
        c,
        "PATCH",
        f"/writings/{after['id']}",
        json={
            "title": "已编辑",
            "content": "这是修改后的观点，没有来源标记。",
            "version": after["version"],
        },
    )
    assert new["edited"] and new["citations"] == []


def test_07_generation_cancelled_on_note_or_notebook_delete(v2):
    c = v2["a"]
    note = call(
        c,
        "POST",
        f"/notebooks/{v2['nb']}/notes",
        201,
        json={"title": "待删除", "content": "这是一个临时观点。"},
    )
    summary = call(
        c,
        "POST",
        f"/notebooks/{v2['nb']}/summaries",
        202,
        json={"note_ids": [note["id"]], "purpose": "慢速生成并发删除"},
    )
    call(c, "DELETE", f"/writings/{note['id']}", 204)
    assert get(c, summary["id"])["job"]["status"] == "cancelled"
    process(summary["job"]["id"])
    assert get(c, summary["id"])["content"] == ""
    nb = call(c, "POST", "/notebooks", 201, json={"name": "生成中删除笔记本"})["id"]
    note = call(
        c,
        "POST",
        f"/notebooks/{nb}/notes",
        201,
        json={"title": "临时笔记", "content": "观点"},
    )
    summary = call(
        c,
        "POST",
        f"/notebooks/{nb}/summaries",
        202,
        json={"note_ids": [note["id"]], "purpose": "慢速"},
    )
    call(c, "DELETE", f"/notebooks/{nb}", 202)
    call(c, "GET", f"/writings/{summary['id']}", 404)
    process(summary["job"]["id"])
    with SessionLocal() as db:
        job = db.get(GenerationJob, summary["job"]["id"])
        assert job is None or job.status == "cancelled"


def test_08_cross_notebook_scope_and_persistence(v2):
    c = v2["a"]
    other = call(c, "POST", "/notebooks", 201, json={"name": "另一知识空间"})["id"]
    call(
        c,
        "POST",
        f"/notebooks/{other}/summaries",
        404,
        json={"note_ids": [v2["saved"]]},
    )
    with SessionLocal() as db:
        assert (
            db.get(Writing, v2["saved"]).content == "这是修改后的观点，没有来源标记。"
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(WritingCitation)
                .where(WritingCitation.writing_id == v2["summary"])
            )
            > 0
        )
        assert db.get(Notebook, v2["nb"])
