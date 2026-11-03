"""V3 real-stack integration plus adversarial structured-output checks (protocol model only)."""

import asyncio
import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select, func
from app.db import SessionLocal
from app.models import LearningSet, Document, Message, now
from app.learning_generation import process, fail_job, generate_and_review
from app.learning_validation import validate_result, review_result, InsufficientEvidence
from app.model_service import ModelError
from app.config import settings
from .test_integration import BASE, HEADERS, call, wait_for
from .pdf_factory import pdf


def key():
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def ctx3():
    a, b = [httpx.Client(base_url=BASE, headers=HEADERS, timeout=100) for _ in range(2)]
    for c in (a, b):
        call(
            c,
            "POST",
            "/auth/register",
            201,
            json={
                "email": "v3-" + uuid.uuid4().hex[:12] + "@example.com",
                "password": "safe-v3-password-2026",
            },
        )
    nb = call(a, "POST", "/notebooks", 201, json={"name": "第三版学习验收"})["id"]
    docs = []
    for name, text in [
        (
            "方案.pdf",
            "青禾项目第一阶段预算为三百万元。主要工作包括城市绿化与社区公共空间改造。",
        ),
        (
            "计划.pdf",
            "青禾项目第二阶段计划于二零二七年完成。重点建设社区活动空间和无障碍设施。",
        ),
    ]:
        docs.append(
            call(
                a,
                "POST",
                f"/notebooks/{nb}/documents",
                202,
                files={"file": (name, pdf([text]), "application/pdf")},
            )["id"]
        )
    wait_for(
        lambda: all(
            d["status"] == "ready"
            for d in call(a, "GET", f"/notebooks/{nb}/documents")["items"]
        )
    )
    yield {"a": a, "b": b, "nb": nb, "docs": docs}
    a.close()
    b.close()


def create(c, ctx, kind="quiz", **extra):
    return call(
        c,
        "POST",
        f"/notebooks/{ctx['nb']}/learning",
        202,
        json={"kind": kind, "document_ids": ctx["docs"], "request_key": key(), **extra},
    )


def done(c, sid):
    row = call(c, "GET", "/learning/" + sid)
    assert row["status"] not in ("failed", "cancelled"), row
    return row if row["status"] == "complete" else None


def no_answers(obj):
    if isinstance(obj, dict):
        assert not (
            {"correct_index", "answer", "explanation", "quotes", "correct", "point"}
            & obj.keys()
        ), obj.keys()
        for v in obj.values():
            no_answers(v)
    elif isinstance(obj, list):
        for v in obj:
            no_answers(v)


def test_01_generate_all_and_publish_atomically(ctx3):
    c = ctx3["a"]
    for kind in ("mindmap", "flashcards", "quiz"):
        payload = {"kind": kind, "document_ids": ctx3["docs"], "request_key": key()}
        row = call(c, "POST", f"/notebooks/{ctx3['nb']}/learning", 202, json=payload)
        repeated = call(
            c, "POST", f"/notebooks/{ctx3['nb']}/learning", 202, json=payload
        )
        assert row["id"] == repeated["id"] and "items" not in row
        result = wait_for(lambda: done(c, row["id"]))
        ctx3[kind] = result
        assert len(result["items"]) == 4
        process(row["id"])
        assert call(c, "GET", "/learning/" + row["id"])["count"] == 4
        with SessionLocal() as db:
            saved = db.get(LearningSet, row["id"])
            assert saved.attempts == 1 and saved.result["review"]["approved"] == 4
            assert len(saved.usage) == (6 if kind == "quiz" else 2)
        if kind == "quiz":
            no_answers(result["items"])
            assert result["citations"] == []
        else:
            assert all(
                x["page"] == 1 and x["state"] == "active" for x in result["citations"]
            )
        if kind != "mindmap":
            assert "少于" in result["warning"]


def test_02_trusted_node_chat_and_scopes(ctx3):
    c = ctx3["a"]
    row = ctx3["mindmap"]
    conv = call(c, "POST", f"/notebooks/{ctx3['nb']}/conversations", 201)["id"]
    payload = {
        "question": "请解释这个知识点",
        "learning_context": {"set_id": row["id"], "node_id": row["items"][1]["id"]},
        "source_ids": ["forged"],
    }
    r = c.post("/api/conversations/" + conv + "/ask", json=payload)
    assert r.status_code == 200 and "event: done" in r.text
    messages = call(c, "GET", "/conversations/" + conv + "/messages")["items"]
    assert messages[-1]["status"] == "complete" and messages[-1]["citations"]
    assert all(s["document_id"] in ctx3["docs"] for s in messages[-1]["citations"])
    with SessionLocal() as db:
        msg = db.get(Message, messages[-1]["id"])
        assert msg.learning_context == payload["learning_context"]
        assert set(msg.source_ids) == set(ctx3["docs"])
    payload["learning_context"]["node_id"] = "unknown"
    call(c, "POST", "/conversations/" + conv + "/ask", 404, json=payload)
    foreign = call(c, "POST", "/notebooks", 201, json={"name": "另一个笔记本"})["id"]
    cv = call(c, "POST", f"/notebooks/{foreign}/conversations", 201)["id"]
    payload["learning_context"]["node_id"] = row["items"][0]["id"]
    call(c, "POST", "/conversations/" + cv + "/ask", 404, json=payload)
    ctx3["conv"] = conv


def test_03_flashcards_persistent_mastery_and_conflict(ctx3):
    c = ctx3["a"]
    row = ctx3["flashcards"]
    path = "/learning/" + row["id"] + "/flashcards/progress"
    p = call(c, "GET", path)
    ids = p["order"]
    assert len(ids) == 4
    p = call(
        c,
        "PATCH",
        path,
        json={
            "revision": p["revision"],
            "card_id": ids[0],
            "state": "review",
            "current_id": ids[1],
        },
    )
    p = call(
        c,
        "PATCH",
        path,
        json={"revision": p["revision"], "card_id": ids[1], "state": "mastered"},
    )
    assert call(c, "GET", path) == p
    stale = p["revision"]
    p = call(
        c, "PATCH", path, json={"revision": stale, "mode": "review", "shuffle": True}
    )
    assert p["order"] == [ids[0]] and p["current_id"] == ids[0]
    call(c, "PATCH", path, 409, json={"revision": stale, "mode": "all"})
    call(c, "DELETE", "/learning/" + row["id"] + "/flashcards/" + ids[0], 204)
    p = call(c, "GET", path)
    assert p["order"] == [] and p["current_id"] is None
    assert call(c, "GET", "/learning/" + row["id"])["mastery"] == {
        "mastered": 1,
        "review": 0,
        "total": 3,
    }
    ctx3["progress_path"] = path


def test_04_quiz_secrecy_grading_idempotency_history(ctx3):
    c = ctx3["a"]
    sid = ctx3["quiz"]["id"]
    path = "/learning/" + sid + "/attempts"
    payload = {"request_key": key()}
    a = call(c, "POST", path, 201, json=payload)
    assert call(c, "POST", path, 201, json=payload)["id"] == a["id"]
    no_answers(a["items"])
    assert a["citations"] == []
    first = a["items"][0]["id"]
    route = "/quiz-attempts/" + a["id"] + "/answers/" + first
    a = call(c, "PATCH", route, json={"selected": 1, "revision": a["revision"]})
    no_answers(a["items"])
    assert a["items"][0]["selected"] == 1 and not a["items"][0]["submitted"]
    revision = a["revision"]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: c.post(
                    "/api" + route + "/submit",
                    json={"selected": 1, "revision": revision},
                ),
                range(2),
            )
        )
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()["answered"] == results[1].json()["answered"] == 1
    a = results[0].json()
    assert a["items"][0]["correct"] is False and a["items"][0]["correct_index"] == 0
    no_answers(a["items"][1:])
    assert a["citations"]
    call(
        c,
        "POST",
        route + "/submit",
        409,
        json={"selected": 0, "revision": a["revision"]},
    )
    for item in a["items"][1:]:
        a = call(
            c,
            "POST",
            "/quiz-attempts/" + a["id"] + "/answers/" + item["id"] + "/submit",
            json={"selected": 0, "revision": a["revision"]},
        )
    assert (
        a["status"] == "complete"
        and a["score"] == 75
        and a["correct"] == 3
        and a["weak_points"][0]["wrong"] == 1
    )
    ctx3["attempt"] = a
    retry = call(c, "POST", path, 201, json={"request_key": key()})
    no_answers(retry["items"])
    assert retry["id"] != a["id"]
    wrong = call(
        c,
        "POST",
        path,
        201,
        json={"request_key": key(), "mode": "wrong", "previous_id": a["id"]},
    )
    assert len(wrong["items"]) == 1 and wrong["items"][0]["id"] == first
    assert call(c, "GET", "/quiz-attempts/" + a["id"])["score"] == 75
    assert call(c, "GET", path)["total"] == 3


def test_05_ownership_and_version_history(ctx3):
    c, b = ctx3["a"], ctx3["b"]
    for kind in ("mindmap", "flashcards", "quiz"):
        sid = ctx3[kind]["id"]
        for method, tail, body in [
            ("GET", "", None),
            ("POST", "/cancel", {}),
            ("POST", "/retry", {}),
            ("POST", "/regenerate", {"request_key": key()}),
        ]:
            call(
                b,
                method,
                "/learning/" + sid + tail,
                404,
                **({"json": body} if body is not None else {}),
            )
    call(b, "GET", ctx3["progress_path"], 404)
    call(b, "GET", "/quiz-attempts/" + ctx3["attempt"]["id"], 404)
    call(
        b,
        "POST",
        "/quiz-attempts/" + ctx3["attempt"]["id"] + "/answers/n1/submit",
        404,
        json={"selected": 0, "revision": 1},
    )
    call(
        b,
        "POST",
        "/learning/" + ctx3["quiz"]["id"] + "/attempts",
        404,
        json={"request_key": key()},
    )
    old = ctx3["quiz"]
    new = call(
        c,
        "POST",
        "/learning/" + old["id"] + "/regenerate",
        202,
        json={"request_key": key()},
    )
    assert (
        new["version"] == 2
        and new["family_id"] == old["family_id"]
        and new["id"] != old["id"]
    )
    wait_for(lambda: done(c, new["id"]))
    assert call(c, "GET", "/quiz-attempts/" + ctx3["attempt"]["id"])["version"] == 1
    assert call(c, "GET", "/learning/" + new["id"] + "/attempts")["total"] == 0


def test_06_insufficient_malformed_timeout_and_cancel(ctx3):
    c = ctx3["a"]
    row = create(c, ctx3, topic="依据不足验收")
    r = wait_for(
        lambda: (
            x
            if (x := call(c, "GET", "/learning/" + row["id"]))["status"] == "failed"
            else None
        )
    )
    assert r["attempts"] == 1 and "足够依据" in r["error"] and "items" not in r
    bad = create(c, ctx3, topic="格式错误验收")
    r = wait_for(
        lambda: (
            x
            if (x := call(c, "GET", "/learning/" + bad["id"]))["status"] == "failed"
            else None
        ),
        timeout=130,
    )
    assert r["attempts"] == 3 and "items" not in r
    cancelled = create(c, ctx3, topic="手动取消验收")
    call(c, "POST", "/learning/" + cancelled["id"] + "/cancel")
    process(cancelled["id"])
    assert call(c, "GET", "/learning/" + cancelled["id"])["status"] == "cancelled"
    call(c, "POST", "/learning/" + cancelled["id"] + "/retry", 202)
    wait_for(lambda: done(c, cancelled["id"]))
    timeout = create(c, ctx3, topic="租约超时验收")
    with SessionLocal() as db:
        r = db.get(LearningSet, timeout["id"])
        r.status = "running"
        r.attempts = 3
        r.started_at = now() - timedelta(seconds=400)
        r.claim = "expired"
        db.commit()
    fail_job(timeout["id"], None, "学习任务超时")
    assert call(c, "GET", "/learning/" + timeout["id"])["status"] == "failed"


def test_07_changed_and_deleted_sources_keep_learning(ctx3):
    c = ctx3["a"]
    sid = ctx3["mindmap"]["id"]
    with SessionLocal() as db:
        doc = db.get(Document, ctx3["docs"][0])
        doc.generation += 1
        doc.active_version = doc.generation
        db.commit()
    changed = call(c, "GET", "/learning/" + sid)
    assert any(s["state"] == "changed" for s in changed["sources"])
    call(
        c,
        "POST",
        "/conversations/" + ctx3["conv"] + "/ask",
        409,
        json={
            "question": "继续讲解",
            "learning_context": {"set_id": sid, "node_id": "n1"},
        },
    )
    # Simulated source version change tests the fence without pretending there is a PDF replacement UI.
    queued = create(c, ctx3, topic="删除来源验收")
    call(c, "DELETE", "/documents/" + ctx3["docs"][0], 202)
    process(queued["id"])
    assert call(c, "GET", "/learning/" + queued["id"])["status"] == "cancelled"
    row = call(c, "GET", "/learning/" + sid)
    assert row["items"] == ctx3["mindmap"]["items"] and any(
        s["state"] == "deleted" and s["text"] for s in row["citations"]
    )
    assert call(c, "GET", "/quiz-attempts/" + ctx3["attempt"]["id"])["score"] == 75
    call(
        c, "POST", "/learning/" + sid + "/regenerate", 404, json={"request_key": key()}
    )
    call(c, "POST", "/learning/" + queued["id"] + "/retry", 409)


def test_08_notebook_delete_cascades_and_fences(ctx3):
    c = ctx3["a"]
    remaining = {**ctx3, "docs": [ctx3["docs"][1]]}
    row = create(c, remaining, topic="删除笔记本验收")
    call(c, "DELETE", "/notebooks/" + ctx3["nb"], 202)
    process(row["id"])
    call(c, "GET", "/learning/" + row["id"], 404)
    call(c, "GET", "/quiz-attempts/" + ctx3["attempt"]["id"], 404)

    def gone():
        with SessionLocal() as db:
            return (
                db.scalar(
                    select(func.count())
                    .select_from(LearningSet)
                    .where(LearningSet.notebook_id == ctx3["nb"])
                )
                == 0
            )

    wait_for(gone)


SOURCES = [{"label": 1, "text": "青禾项目第一阶段预算为三百万元。", "kind": "document"}]
BASE_ITEM = {
    "id": "n1",
    "parent_id": None,
    "title": "项目预算",
    "explanation": "第一阶段预算三百万元",
    "refs": [1],
    "quotes": [{"ref": 1, "text": "第一阶段预算为三百万元"}],
}


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_ref",
        "fake_quote",
        "duplicate_id",
        "cycle",
        "orphan",
        "depth",
        "duplicate_options",
        "invalid_answer",
    ],
)
def test_structural_rejection(mutation):
    items = [copy.deepcopy(BASE_ITEM)]
    kind = "mindmap"
    if mutation == "unknown_ref":
        items[0]["refs"] = [999]
    elif mutation == "fake_quote":
        items[0]["quotes"][0]["text"] = "实际不存在的证据内容"
    elif mutation == "duplicate_id":
        items.append(copy.deepcopy(items[0]))
    elif mutation == "cycle":
        items[0]["parent_id"] = "n1"
    elif mutation == "orphan":
        items[0]["parent_id"] = "missing"
    elif mutation == "depth":
        for i in range(2, 5):
            items.append(
                {**copy.deepcopy(BASE_ITEM), "id": f"n{i}", "parent_id": f"n{i - 1}"}
            )
    else:
        kind = "quiz"
        items[0].update(
            question="预算多少？",
            point="预算",
            options=["300万", "500万", "700万", "900万"],
            correct_index=0,
        )
        if mutation == "duplicate_options":
            items[0]["options"][1] = "３００万"
        else:
            items[0]["correct_index"] = True
    with pytest.raises(ModelError):
        validate_result(json.dumps({"items": items}), kind, {"count": 40}, SOURCES)


def test_quality_review_rejects_unsupported_and_orphans():
    result = {
        "items": [
            BASE_ITEM,
            {**BASE_ITEM, "id": "n2", "parent_id": "n1"},
            {**BASE_ITEM, "id": "n3", "parent_id": "n2"},
        ]
    }
    filtered, rejected = review_result(
        json.dumps({"approved_ids": ["n1", "n3"]}), result, "mindmap"
    )
    assert len(filtered["items"]) == 1 and rejected == 2
    with pytest.raises(InsufficientEvidence):
        review_result('{"approved_ids":[]}', result, "mindmap")


def test_real_generation_deadline(monkeypatch):
    import app.learning_generation as module

    async def slow(*args):
        await asyncio.sleep(1)

    monkeypatch.setattr(module, "complete", slow)
    monkeypatch.setattr(settings(), "generation_timeout_seconds", 0.01)
    with pytest.raises(TimeoutError):
        asyncio.run(
            generate_and_review("test", "claim", "quiz", {"count": 5}, [], None, [])
        )


def test_quote_repair_is_bounded_and_revalidated(monkeypatch):
    import app.learning_generation as module

    item = copy.deepcopy(BASE_ITEM)
    item["quotes"][0]["text"] = "不存在的引用原文"

    async def repair(*args):
        return json.dumps(
            {"repairs": [{"id": "n1", "refs": [1], "quotes": BASE_ITEM["quotes"]}]}
        )

    monkeypatch.setattr(module, "complete", repair)
    raw = asyncio.run(module.repair_quotes(json.dumps({"items": [item]}), SOURCES, []))
    assert (
        validate_result(raw, "mindmap", {"count": 40}, SOURCES)["items"][0]["title"]
        == item["title"]
    )
    item["refs"] = [999]
    with pytest.raises(ModelError):
        asyncio.run(module.repair_quotes(json.dumps({"items": [item]}), SOURCES, []))

    async def forged(*args):
        return json.dumps(
            {
                "repairs": [
                    {
                        "id": "n1",
                        "refs": [1],
                        "quotes": [{"ref": 1, "text": "依然不存在的原文"}],
                    }
                ]
            }
        )

    monkeypatch.setattr(module, "complete", forged)
    item["refs"] = [1]
    raw = asyncio.run(module.repair_quotes(json.dumps({"items": [item]}), SOURCES, []))
    with pytest.raises(ModelError):
        validate_result(raw, "mindmap", {"count": 40}, SOURCES)


def test_multiple_exact_quotes_in_same_fragment():
    item = copy.deepcopy(BASE_ITEM)
    item["quotes"].append({"ref": 1, "text": "预算为三百万元"})
    assert validate_result(
        json.dumps({"items": [item]}), "mindmap", {"count": 40}, SOURCES
    )["items"][0]["refs"] == [1]


def test_quiz_independent_review_rejects_multiple_valid_options():
    item = {**BASE_ITEM, "correct_index": 3}
    with pytest.raises(InsufficientEvidence):
        review_result(
            json.dumps(
                {
                    "approved_ids": ["n1"],
                    "answers": [{"id": "n1", "valid_options": [0, 3]}],
                }
            ),
            {"items": [item]},
            "quiz",
        )
    with pytest.raises(InsufficientEvidence):
        review_result(
            json.dumps(
                {
                    "approved_ids": ["n1"],
                    "answers": [{"id": "n1", "valid_options": [0]}],
                }
            ),
            {"items": [item]},
            "quiz",
        )
    approved, rejected = review_result(
        json.dumps(
            {"approved_ids": ["n1"], "answers": [{"id": "n1", "valid_options": [3]}]}
        ),
        {"items": [item]},
        "quiz",
    )
    assert len(approved["items"]) == 1 and rejected == 0


def test_quote_repair_rejects_unfixed_node_and_descendants():
    from app.learning_validation import filter_invalid_items

    bad = {
        **copy.deepcopy(BASE_ITEM),
        "id": "n2",
        "parent_id": "n1",
        "quotes": [{"ref": 1, "text": "不存在的原文说明"}],
    }
    child = {**BASE_ITEM, "id": "n3", "parent_id": "n2"}
    result, rejected = filter_invalid_items(
        json.dumps({"items": [BASE_ITEM, bad, child]}),
        "mindmap",
        {"count": 40},
        SOURCES,
    )
    assert len(result["items"]) == 1 and rejected == 2
    with pytest.raises(InsufficientEvidence):
        filter_invalid_items(
            json.dumps({"items": [bad, child]}), "mindmap", {"count": 40}, SOURCES
        )
