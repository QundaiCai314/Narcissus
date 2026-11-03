"""Research boundary and real-stack tests. HTTP fixtures are explicitly synthetic; no production fallback."""

import json
import uuid
from datetime import timedelta

import httpx
import pytest
from .test_integration import ctx as ctx
from app import research_tasks, search_service
from app.config import settings
from app.db import SessionLocal
from app.model_service import ModelError
from app.models import (
    ResearchCandidate,
    ResearchTask,
    now,
)
from app.research_report import validate

from .test_integration import call, wait_for

TEXT = "青禾社区阅读计划安排每周三开放讨论活动，第一阶段预算为三百万元。活动面向十二至十八岁青少年，内容包含科普阅读、读书分享与图书借阅。每次讨论活动持续四十五分钟，工作人员应提前准备书目并记录参与人数。项目将根据参与者反馈改进后续活动，尚未规定每日参与人数。"
HTML = (
    "<html><title>青禾社区阅读计划</title><article><h1>社区阅读</h1><p>"
    + TEXT
    + "</p></article></html>"
).encode()


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://example.com/a?utm_source=x&q=1#top", "https://example.com/a?q=1"),
        ("https://EXAMPLE.com:443/", "https://example.com/"),
        ("https://example.com/a?q=2&x=1", "https://example.com/a?x=1&q=2"),
    ],
)
def test_search_url_dedup(left, right):
    assert search_service.canonical_url(left) == search_service.canonical_url(right)


def test_search_secret_not_reused_for_other_host(monkeypatch):
    s = settings()
    monkeypatch.setattr(s, "search_api_key", "")
    monkeypatch.setattr(s, "search_reuse_stepfun_key", True)
    monkeypatch.setattr(s, "search_base_url", "https://other.example/v1")
    assert search_service.credential() == ""


def sample_block():
    return {
        "findings": [
            {
                "id": "b1",
                "type": "fact",
                "text": "预算三百万元。",
                "refs": [1],
                "quotes": [{"ref": 1, "text": TEXT[:40]}],
            }
        ],
        "analysis": [],
        "disagreements": [],
        "uncertainties": [],
    }


@pytest.mark.parametrize(
    "problem", ["ref", "quote", "duplicate", "type", "empty", "format"]
)
def test_report_rejects_invalid_evidence(problem):
    data = sample_block()
    b = data["findings"][0]
    if problem == "ref":
        b["refs"] = [99]
    if problem == "quote":
        b["quotes"][0]["text"] = "这是从未出现过的编造原文"
    if problem == "duplicate":
        data["analysis"] = [b]
    if problem == "type":
        b["type"] = "verified"
    if problem == "empty":
        b["refs"] = []
    if problem == "format":
        data["analysis"] = "not a list"
    with pytest.raises(ModelError):
        validate(json.dumps(data), [{"label": 1, "text": TEXT}])


def test_report_exact_evidence_passes():
    assert (
        validate(json.dumps(sample_block()), [{"label": 1, "text": TEXT}])[0]["section"]
        == "findings"
    )


def manual_search(ctx, monkeypatch):
    a, nb = ctx["a"], ctx["nb"]
    request = {
        "request_key": str(uuid.uuid4()),
        "question": "青禾社区阅读计划有哪些安排？",
    }
    row = call(a, "POST", f"/notebooks/{nb}/research", 202, json=request)
    assert (
        call(a, "POST", f"/notebooks/{nb}/research", 202, json=request)["id"]
        == row["id"]
    )
    with SessionLocal() as db:
        task = db.get(ResearchTask, row["id"])
        task.dispatched_at = now() + timedelta(days=1)
        db.commit()
    monkeypatch.setattr(
        research_tasks,
        "search",
        lambda query: (
            [
                {
                    "title": "青禾社区阅读计划",
                    "url": "https://example.com/research-" + row["id"],
                    "url_hash": row["id"].replace("-", ""),
                    "rank": 1,
                    "snippet": "搜索摘要含有不应成为正文的词语：伪造预算九千万元",
                    "details": {},
                }
            ],
            {"calls": 1, "fixture": True},
        ),
    )
    research_tasks.process("search", row["id"])
    task = call(a, "GET", f"/research/{row['id']}")
    return task, task["candidates"][0]


def test_stack_research_preview_import_report_permissions_and_history(ctx, monkeypatch):
    a, b = ctx["a"], ctx["b"]
    task, c = manual_search(ctx, monkeypatch)
    root = f"/research/{task['id']}"
    source = root + f"/sources/{c['id']}"
    for path in (root, source):
        call(b, "GET", path, 404)
    call(b, "POST", source + "/fetch", 404)
    call(b, "DELETE", root, 404)
    call(
        a,
        "POST",
        root + "/reports",
        422,
        json={"request_key": str(uuid.uuid4()), "candidate_ids": [c["id"]]},
    )
    call(a, "POST", source + "/fetch", 202)
    with SessionLocal() as db:
        row = db.get(ResearchCandidate, c["id"])
        row.dispatched_at = now() + timedelta(days=1)
        db.commit()
    monkeypatch.setattr(
        research_tasks,
        "fetch_public",
        lambda url: (
            HTML,
            {
                "url": url,
                "original_url": url,
                "domain": "example.com",
                "mime": "text/html",
            },
        ),
    )
    research_tasks.process("source", c["id"])
    preview = call(a, "GET", source)
    assert (
        preview["status"] == "preview"
        and not preview["document_id"]
        and TEXT in str(preview["units"])
    )
    assert "九千万元" not in str(preview["units"])
    call(a, "PUT", root + "/selection", json={"candidate_ids": [c["id"]]})
    assert call(a, "GET", root)["candidates"][0]["selected"]
    call(a, "POST", source + "/import", 202, json={})
    imported = wait_for(
        lambda: r if (r := call(a, "GET", source))["status"] == "ready" else None,
        timeout=120,
    )
    doc_id = imported["document_id"]
    assert call(a, "POST", source + "/import", 202, json={})["document_id"] == doc_id
    call(b, "GET", f"/documents/{doc_id}/snapshot", 404)
    snap = call(a, "GET", f"/documents/{doc_id}/snapshot")
    assert snap["details"]["fetched_at"] == preview["fetched_at"]
    body = {"request_key": str(uuid.uuid4()), "candidate_ids": [c["id"]]}
    link = call(a, "POST", root + "/reports", 202, json=body)
    assert (
        call(a, "POST", root + "/reports", 202, json=body)["writing_id"]
        == link["writing_id"]
    )
    writing = wait_for(
        lambda: (
            w
            if (w := call(a, "GET", f"/writings/{link['writing_id']}"))["job"]["status"]
            == "complete"
            else None
        ),
        timeout=120,
    )
    assert writing["citations"] and "九千万元" not in writing["content"]
    assert writing["details"]["inputs"]["documents"][0]["version"] == 1
    assert writing["citations"][0]["source_url"] == c["url"]
    for path in (
        f"/writings/{link['writing_id']}",
        f"/writings/{link['writing_id']}/export?format=md",
    ):
        call(b, "GET", path, 404)
    body["request_key"] = str(uuid.uuid4())
    second = call(a, "POST", root + "/reports", 202, json=body)
    assert second["writing_id"] != link["writing_id"] and second["version"] == 2
    call(a, "POST", root + "/cancel")
    call(
        a,
        "POST",
        root + "/reports",
        409,
        json={"request_key": str(uuid.uuid4()), "candidate_ids": [c["id"]]},
    )
    assert (
        call(a, "GET", f"/writings/{link['writing_id']}")["content"]
        == writing["content"]
    )
    call(a, "DELETE", root, 204)
    call(a, "GET", root, 404)
    assert call(a, "GET", f"/documents/{doc_id}/snapshot")["status"] == "ready"
    assert call(a, "GET", f"/writings/{link['writing_id']}")["content"]


def test_stack_research_cancel_fences_running_fetch(ctx, monkeypatch):
    task, c = manual_search(ctx, monkeypatch)
    root = f"/research/{task['id']}"
    call(ctx["a"], "POST", root + f"/sources/{c['id']}/fetch", 202)

    def fetch(url):
        call(ctx["a"], "POST", root + "/cancel")
        return HTML, {"url": url, "domain": "example.com", "mime": "text/html"}

    monkeypatch.setattr(research_tasks, "fetch_public", fetch)
    research_tasks.process("source", c["id"])
    row = call(ctx["a"], "GET", root + f"/sources/{c['id']}")
    assert row["status"] == "cancelled" and not row["units"]


def test_stack_research_search_failure_no_fake_results(ctx, monkeypatch):
    row = call(
        ctx["a"],
        "POST",
        f"/notebooks/{ctx['nb']}/research",
        202,
        json={"request_key": str(uuid.uuid4()), "question": "搜索服务未配置"},
    )

    def unavailable(query):
        raise search_service.SearchError("尚未配置搜索服务")

    monkeypatch.setattr(research_tasks, "search", unavailable)
    research_tasks.process("search", row["id"])
    failed = call(ctx["a"], "GET", f"/research/{row['id']}")
    assert (
        failed["status"] == "failed"
        and not failed["candidates"]
        and "尚未配置" in failed["error"]
    )


def test_stack_research_quota_and_deleted_notebook(ctx, monkeypatch):
    row = call(
        ctx["a"],
        "POST",
        f"/notebooks/{ctx['nb']}/research",
        202,
        json={"request_key": str(uuid.uuid4()), "question": "配额边界验证"},
    )
    monkeypatch.setattr(settings(), "research_daily_searches", 0)
    monkeypatch.setattr(
        research_tasks,
        "search",
        lambda _: pytest.fail("quota must prevent network call"),
    )
    research_tasks.process("search", row["id"])
    result = call(ctx["a"], "GET", f"/research/{row['id']}")
    assert result["status"] == "failed" and result["attempts"] == 0
    assert "上限" in result["error"]
    nb = call(ctx["a"], "POST", "/notebooks", 201, json={"name": "删除研究并发边界"})
    task = call(
        ctx["a"],
        "POST",
        f"/notebooks/{nb['id']}/research",
        202,
        json={"request_key": str(uuid.uuid4()), "question": "取消后不能运行搜索"},
    )
    call(ctx["a"], "DELETE", f"/notebooks/{nb['id']}", 202)
    research_tasks.process("search", task["id"])
    call(ctx["a"], "GET", f"/research/{task['id']}", 404)


def test_stack_cancelled_preview_restores_without_fetch(ctx, monkeypatch):
    task, c = manual_search(ctx, monkeypatch)
    root = f"/research/{task['id']}/sources/{c['id']}"
    call(ctx["a"], "POST", root + "/fetch", 202)
    monkeypatch.setattr(
        research_tasks,
        "fetch_public",
        lambda url: (HTML, {"url": url, "domain": "example.com", "mime": "text/html"}),
    )
    research_tasks.process("source", c["id"])
    first = call(ctx["a"], "GET", root)
    call(ctx["a"], "POST", root + "/cancel")
    restored = call(ctx["a"], "POST", root + "/fetch", 202)
    assert restored["status"] == "preview" and restored["attempts"] == first["attempts"]
    assert restored["units"] == first["units"]


def test_search_protocol_discards_provider_body(monkeypatch):
    s = settings()
    monkeypatch.setattr(s, "search_api_key", "test-key")
    payload = {
        "results": [
            {
                "url": "https://example.com/a?utm_source=one",
                "title": "甲",
                "snippet": "摘要不是正文",
                "content": "不得作为原文入库",
                "time": "2026-01-01",
            },
            {
                "url": "https://example.com/a#fragment",
                "title": "甲的重复",
                "snippet": "重复",
            },
            {"url": "file:///etc/passwd", "title": "不安全地址"},
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(search_service.httpx, "Client", lambda **_: client)
    rows, usage = search_service.search("中文研究问题")
    assert len(rows) == 1 and rows[0]["details"]["published_at"] is None
    assert "content" not in rows[0] and "不得作为原文" not in str(rows)
    assert usage["calls"] == 1


def test_web_definition_heading_preserves_fact_context():
    from app.web_import import extract_web
    raw = ("<html><title>地址属性说明</title><main><h1>属性</h1><dl><dt>is_global</dt><dd><p>"
           + "共享地址空间的全局属性为假，必须结合属性名称阅读解释。" * 5
           + "</p></dd></dl></main></html>").encode()
    _, units, _ = extract_web(raw, {"url": "https://example.com/definition", "mime": "text/html", "domain": "example.com"})
    assert any(u["text"] == "is_global" for u in units)
    paragraph = next(u for u in units if "共享地址" in u["text"])
    assert paragraph["location"]["heading"] == "is_global"
