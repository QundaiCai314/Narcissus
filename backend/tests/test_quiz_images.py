"""Private answer images use in-memory storage and SQLite, never business data."""
import io
from types import SimpleNamespace
from uuid import uuid4
import pytest
from PIL import Image
from app import learning, quiz_images
from tests.test_quiz_workflow import client, start, answer


def png():
    out = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def objects(monkeypatch):
    data = {}
    monkeypatch.setattr(learning.storage, "put", lambda key, value, mime: data.update({key: value}))
    monkeypatch.setattr(learning.storage, "read", lambda key: data[key])
    monkeypatch.setattr(learning.storage, "remove", lambda key: data.pop(key, None))
    return data


def upload(c, a, qid="short_answer", key=None, data=None):
    return c.post(f'/api/quiz-attempts/{a["id"]}/answers/{qid}/images',
        data={"revision": a["revision"], "request_key": key or str(uuid4())},
        files={"file": ("answer.png", png() if data is None else data, "image/png")})


def test_image_only_submit_restore_and_private_access(client, objects):
    c, app, _ = client; a = start(c)
    key = str(uuid4()); before = a
    r = upload(c, a, key=key); assert r.status_code == 200, r.text
    a = r.json(); q = next(q for q in a["items"] if q["id"] == "short_answer")
    image = q["images"][0]; assert "key" not in image
    assert not {"answer", "rubric", "explanation"} & set(q)
    assert upload(c, before, key=key).json()["revision"] == a["revision"]
    assert len(objects) == 1
    loaded = c.get(image["url"]); assert loaded.status_code == 200
    assert loaded.headers["content-type"] == "image/jpeg"
    assert "no-store" in loaded.headers["cache-control"]
    a = answer(c, a, "short_answer", {"text": ""}, "submit")
    q = next(q for q in a["items"] if q["id"] == "short_answer")
    assert q["grading"] == "self_pending" and q["images"] == [image]
    assert upload(c, a).status_code == 409
    assert c.request("DELETE", image["url"], json={"revision":a["revision"]}).status_code == 409
    a = answer(c, a, "short_answer", {"rubric_scores":{"r1":8}}, "assess")
    assert c.get(image["url"]).status_code == 200
    app.dependency_overrides[learning.current_user] = lambda: SimpleNamespace(id="other")
    assert c.get(image["url"]).status_code == 404
    assert upload(c, a).status_code == 404
    assert c.request("DELETE", image["url"], json={"revision":a["revision"]}).status_code == 404


def test_image_text_save_delete_and_revision(client, objects):
    c, _, _ = client; a = start(c, delivery="exam")
    a = answer(c, a, "short_answer", {"text": "$\\frac{a}{b}$"})
    before = a; a = upload(c, a).json()
    assert upload(c, before).status_code == 409
    a = answer(c, a, "short_answer", {"text": "新增推导 $x^2$"})
    image = next(q for q in a["items"] if q["id"] == "short_answer")["images"][0]
    assert c.request("DELETE", image["url"], json={"revision":1}).status_code == 409
    a = c.request("DELETE", image["url"], json={"revision":a["revision"]}).json()
    q = next(q for q in a["items"] if q["id"] == "short_answer")
    assert q["text"] == "新增推导 $x^2$" and q["images"] == [] and not objects
    assert c.get(image["url"]).status_code == 404
    a = upload(c, a).json()
    a = answer(c, a, "short_answer", {"text":""})
    a = c.post(f'/api/quiz-attempts/{a["id"]}/finish', json={"revision":a["revision"]}).json()
    assert a["pending_review"] == 1
    assert next(q for q in a["items"] if q["id"] == "short_answer")["grading"] == "self_pending"


def test_reject_bad_images_limit_and_objective_upload(client, objects):
    c, _, _ = client; a = start(c)
    assert upload(c, a, qid="single").status_code == 422
    assert upload(c, a, data=b'<svg onload="alert(1)"></svg>').status_code == 422
    assert upload(c, a, data=b'x' * (quiz_images.MAX_BYTES + 1)).status_code == 413
    assert not objects
    for _ in range(4):
        r=upload(c,a); assert r.status_code==200; a=r.json()
    assert upload(c,a).status_code==422
    assert len(objects)==4


def test_storage_failure_does_not_change_answer(client, objects, monkeypatch):
    c, _, _=client; a=start(c)
    def unavailable(*args): raise RuntimeError("storage unavailable")
    monkeypatch.setattr(learning.storage,"put",unavailable)
    assert upload(c,a).status_code==503
    restored=c.get(f'/api/quiz-attempts/{a["id"]}').json()
    assert restored["revision"]==a["revision"]
    assert all(not q["images"] for q in restored["items"])


def test_normalized_image_strips_metadata_and_limits_resolution():
    original=Image.new("RGB",(4000,1000),"white")
    exif=Image.Exif(); exif[270]="private metadata"
    out=io.BytesIO(); original.save(out,"JPEG",exif=exif)
    data,width,height=quiz_images.normalize(out.getvalue())
    assert (width,height)==(3000,750)
    with Image.open(io.BytesIO(data)) as clean:
        assert clean.format=="JPEG" and not clean.getexif()
