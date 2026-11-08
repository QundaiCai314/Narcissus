"""Isolated contracts, model-review gates and API flows. No external services."""
import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import learning, quiz_rules as rules
from app.db import Base
from app.models import User, Notebook, Document, LearningSet, QuizAttempt
from app.learning_validation import validate_result, review_result, InsufficientEvidence
from app.model_service import ModelError

SOURCE = {"label": 1, "filename": "课程讲义", "text": "完全竞争市场中企业是价格接受者。利润等于总收益减去总成本。边际收益等于边际成本是内部最优解的必要条件。"}


def question(t="single", qid=None):
    q = {"id": qid or t, "question_type": t, "question": "根据讲义，企业利润如何确定？", "explanation": "利润等于总收益减去总成本。", "point": "利润", "refs": [1], "quotes": [{"ref": 1, "text": "利润等于总收益减去总成本。"}]}
    if t in rules.OBJECTIVE:
        q["options"] = ["总收益减总成本", "总成本减总收益", "仅总收益", "仅总成本"]
        if t == "multiple": q["correct_indices"] = [0, 2]
        elif t == "true_false": q.update(options=["正确", "错误"], correct_index=0)
        else: q["correct_index"] = 0
    else:
        if t == "fill_blank": q["question"] = "利润等于总收益减去 ___ 。"
        q.update(answer="总收益减去总成本。", rubric=[{"text": "正确说明收益减去成本的关系，等价表述可得分", "points": rules.TYPES[t][1]}])
    return q


def validated(t):
    return validate_result(json.dumps({"items": [question(t)]}), "quiz", {"count": 5, "question_types": [t]}, [SOURCE])["items"][0]


@pytest.mark.parametrize("t", list(rules.TYPES))
def test_all_question_contracts_hide_answers(t):
    q = validated(t)
    assert q["points"] == rules.TYPES[t][1]
    public = rules.public_question(q)
    assert not {"answer", "rubric", "correct_index", "correct_indices", "explanation", "point", "refs", "quotes"} & set(public)


@pytest.mark.parametrize("change", [
    {"options": ["A. 相同", "相同", "C", "D"]},
    {"correct_index": True}, {"correct_index": 4},
    {"options": ["甲", "乙", "丙", "以上皆是"]},
    {"question_type": "multiple", "correct_indices": [0]},
    {"question_type": "multiple", "correct_indices": [0, 0]},
    {"question_type": "true_false", "options": ["是", "否"], "correct_index": 0},
])
def test_invalid_choices_rejected(change):
    q = dict(question(), **change)
    with pytest.raises(ModelError): rules.validate_question(q, {"question_types": list(rules.TYPES)})


def test_rubric_sum_and_fill_slots():
    q = question("short_answer"); q["rubric"][0]["points"] = 7
    with pytest.raises(ModelError): rules.validate_question(q, {"question_types": ["short_answer"]})
    q = question("fill_blank"); q["question"] = "没有空格"
    with pytest.raises(ModelError): rules.validate_question(q, {"question_types": ["fill_blank"]})


def test_plan_limits_and_duplicate_items():
    params = {"count": 5, "question_types": ["single", "short_answer"]}
    assert [p["count"] for p in rules.plan(params)] == [3, 2]
    items = [dict(question(), id=f"q{i}", question=f"第{i}种情形如何计算利润？") for i in range(4)]
    with pytest.raises(ModelError): validate_result(json.dumps({"items": items}), "quiz", params, [SOURCE])
    with pytest.raises(ValueError): learning.GenerateInput(kind="quiz", document_ids=["d"], count=5, question_types=list(rules.TYPES), request_key=uuid4())


@pytest.mark.parametrize("answers,correct", [([0,2], True), ([2,0], True), ([0], False), ([0,1,2], False), ([], False)])
def test_multiple_scoring(answers, correct):
    result = rules.grade(validated("multiple"), {"selected_indices": answers})
    assert result["correct"] is correct
    assert result["earned"] == (3 if correct else 0)


def test_review_independent_answers_and_subjective_proof():
    q = validated("multiple")
    result, _ = review_result(json.dumps({"approved_ids": [q["id"]], "answers": [{"id": q["id"], "valid_options": [2,0]}]}), {"items": [q]}, "quiz")
    assert result["items"]
    with pytest.raises(InsufficientEvidence): review_result(json.dumps({"approved_ids": [q["id"]], "answers": [{"id": q["id"], "valid_options": [0]}]}), {"items": [q]}, "quiz")
    q = validated("short_answer")
    with pytest.raises(ModelError): review_result(json.dumps({"approved_ids": [q["id"]], "answers": [{"id": q["id"]}]}), {"items": [q]}, "quiz")


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [User.__table__, Notebook.__table__, Document.__table__, LearningSet.__table__, QuizAttempt.__table__]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        db.add(User(id="u", email="fixture@example.com", password_hash="unused"))
        db.add(Notebook(id="nb", user_id="u", name="课程练习"))
        items = [validated(t) for t in ("single", "multiple", "true_false", "short_answer", "fill_blank")]
        db.add(LearningSet(id="set", notebook_id="nb", family_id="family", request_key=str(uuid4()), kind="quiz", title="课程复习", params={"count": 5}, sources=[], citations=[], status="complete", phase="complete", result={"items": items}))
        db.commit()
    app = FastAPI(); app.include_router(learning.router, prefix="/api")
    def sessions():
        with Session() as db: yield db
    app.dependency_overrides[learning.db_session] = sessions
    app.dependency_overrides[learning.current_user] = lambda: SimpleNamespace(id="u")
    monkeypatch.setattr(learning, "rate_limit", lambda *a: None)
    with TestClient(app) as c: yield c, app, Session
    engine.dispose()


def start(c, delivery="practice", **kw):
    r = c.post("/api/learning/set/attempts", json={"request_key": str(uuid4()), "delivery": delivery, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def answer(c, a, qid, payload, action="", status=200):
    method = c.post if action else c.patch
    r = method(f'/api/quiz-attempts/{a["id"]}/answers/{qid}' + (f"/{action}" if action else ""), json={"revision": a["revision"], **payload})
    assert r.status_code == status, r.text
    return r.json()


def test_exam_save_restore_whole_submit_and_self_assessment(client):
    c, _, _ = client
    a = start(c, "exam")
    assert a["total_points"] == 19
    a = answer(c, a, "single", {"selected": 0})
    a = answer(c, a, "multiple", {"selected_indices": [0,2]})
    a = answer(c, a, "short_answer", {"text": "利润=总收益-总成本"})
    saved = c.get(f'/api/quiz-attempts/{a["id"]}').json()
    assert saved["items"][3]["text"] == "利润=总收益-总成本"
    for q in saved["items"]:
        assert not {"answer", "rubric", "correct_index", "correct_indices", "refs", "explanation"} & set(q)
    answer(c, a, "single", {"selected": 0}, "submit", 409)
    a = c.post(f'/api/quiz-attempts/{a["id"]}/finish', json={"revision": a["revision"]}).json()
    assert a["status"] == "reviewing" and a["pending_review"] == 1 and a["score"] is None
    assert a["items"][2]["grading"] == "unanswered" and a["items"][4]["earned"] == 0
    answer(c, a, "short_answer", {"rubric_scores": {"r1": 9}}, "assess", 422)
    a = answer(c, a, "short_answer", {"rubric_scores": {"r1": 4}}, "assess")
    assert a["status"] == "complete" and a["earned_points"] == 9 and a["score"] == 47
    assert a["self_assessed"] is True
    again = answer(c, a, "short_answer", {"rubric_scores": {"r1": 4}}, "assess")
    assert again["revision"] == a["revision"]
    wrong = start(c, mode="wrong", previous_id=a["id"])
    assert {q["id"] for q in wrong["items"]} == {"true_false", "short_answer", "fill_blank"}


def test_practice_idempotency_revision_and_ownership(client):
    c, app, _ = client; a = start(c)
    a = answer(c, a, "single", {"selected": 0}, "submit")
    b = answer(c, a, "single", {"selected": 0}, "submit")
    assert a["revision"] == b["revision"]
    answer(c, a, "single", {"selected": 1}, "submit", 409)
    stale = dict(a, revision=1)
    answer(c, stale, "multiple", {"selected_indices": [0]}, status=409)
    answer(c, a, "multiple", {"selected_indices": [True]}, status=422)
    answer(c, a, "true_false", {"selected": 3}, status=422)
    answer(c, a, "short_answer", {"text": " "}, "submit", 422)
    app.dependency_overrides[learning.current_user] = lambda: SimpleNamespace(id="another-user")
    assert c.get(f'/api/quiz-attempts/{a["id"]}').status_code == 404
    assert c.get('/api/learning/set').status_code == 404


def test_legacy_question_and_grade_still_work(client):
    c, _, Session = client
    with Session() as db:
        row = db.get(LearningSet, "set")
        q = question(); q.pop("question_type")
        row.result = {"items": [q]}; db.commit()
    a = start(c)
    a = answer(c, a, "single", {"selected": 0}, "submit")
    assert a["score"] == 100 and a["total_points"] == 1


def test_generation_blinds_answers_and_reviews_rubric(monkeypatch):
    from app import learning_generation as gen
    calls=[]
    async def fake(messages, usages, *args, **kwargs):
        payload=json.loads(messages[-1]["content"]);calls.append(payload)
        if payload["mode"] == "learning_quiz": return json.dumps({"items":[question("short_answer")]})
        if payload["kind"] == "quiz":
            q=payload["candidate"]["items"][0]
            assert not {"answer","rubric","correct_indices","correct_index","explanation"}&set(q)
            return json.dumps({"approved_ids":[q["id"]],"answers":[{"id":q["id"],"solution":"利润等于收益减去成本。"}]})
        q=payload["candidate"]["items"][0]
        assert q["review_solution"] and q["rubric"]
        return json.dumps({"approved_ids":[q["id"]]})
    monkeypatch.setattr(gen,"complete",fake);monkeypatch.setattr(gen,"phase",lambda *a:None)
    result,_=asyncio.run(gen.generate_and_review("s","c","quiz",{"count":5,"question_types":["short_answer"]},[SOURCE],None,[]))
    assert len(calls)==3 and calls[0]["question_plan"][0]["count"]==5
    assert "review_solution" not in result["items"][0]

@pytest.mark.parametrize('status,permanent,word', [(402, True, '额度不足'), (401, True, '鉴权失败'), (403, True, '无访问权限'), (404, True, '不存在'), (429, False, '调用限制'), (500, False, '暂时不可用')])
def test_provider_errors_are_actionable_without_leaking_secrets(status, permanent, word):
    from app.model_service import provider_error
    error = provider_error(status, '聊天模型')
    assert error.permanent is permanent and word in str(error)


def test_permanent_model_failure_does_not_retry_learning_job(monkeypatch):
    from app import learning_generation as gen
    from app.model_service import provider_error
    assert provider_error(402, '聊天模型').permanent
    # The generation path propagates this typed error rather than converting it to
    # evidence rejection or repairing an unauthenticated response.
    async def unavailable(*a, **kw): raise provider_error(402, '聊天模型')
    monkeypatch.setattr(gen, 'complete', unavailable)
    with pytest.raises(ModelError) as caught:
        asyncio.run(gen.generate_and_review('s', 'c', 'quiz', {'count':5,'question_types':['single']}, [SOURCE], None, []))
    assert caught.value.permanent
