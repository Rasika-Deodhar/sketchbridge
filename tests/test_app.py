"""Offline checks for CI: no API key, no Meta calls, no cost.

Run: python -m pytest -q
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import meta_client as mc
from app import pipeline
from app.main import app

client = TestClient(app)
MAPPING = [
    {"concept_part": "prediction", "analogy_part": "the dish"},
    {"concept_part": "error", "analogy_part": "the complaint"},
    {"concept_part": "backward pass", "analogy_part": "tracing the complaint back"},
]


@pytest.fixture(autouse=True)
def no_code(monkeypatch):
    # Empty, not unset: .env is loaded with setdefault, so this keeps a local ACCESS_CODE out of tests.
    monkeypatch.setenv("ACCESS_CODE", "")
    monkeypatch.setenv("META_API_KEY", "")


def test_page_health_and_demos():
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"ok": True}
    demos = client.get("/demos").json()
    assert len(demos) == 5
    for d in demos:
        r = client.get(f"/image/{d['result']['image_id']}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


@pytest.mark.parametrize("bad", ["..%2F.env", "x.txt", "missing.webp"])
def test_image_rejects_bad_names(bad):
    assert client.get(f"/image/{bad}").status_code == 404


def test_input_validation():
    assert client.post("/options", json={"concept": ""}).status_code == 422
    base = {"concept": "backprop", "analogy": "a restaurant", "mapping": MAPPING}
    assert client.post("/check", json={**base, "explanation": "it goes"}).status_code == 400
    assert client.post("/check", json={**base, "mapping": [], "explanation": "x y z w"}).status_code == 422


def test_access_code(monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "open-sesame")
    # Paid routes are refused before anything else, even with a bad body.
    assert client.post("/options", json={}).json()["detail"] == "access_code"
    r = client.post("/options", json={"concept": ""}, headers={"X-Access-Code": "wrong"})
    assert r.status_code == 401
    # The right code gets through to normal validation.
    r = client.post("/options", json={"concept": ""}, headers={"X-Access-Code": "open-sesame"})
    assert r.status_code == 422
    assert client.post("/transcribe", content=b"x").status_code == 401
    # Free routes stay open.
    assert client.get("/demos").status_code == 200
    assert client.get("/").status_code == 200


def test_check_understanding_repairs_model_reply(monkeypatch):
    reply = {
        "parts": [
            {"index": 1, "status": "got", "note": "ok"},
            {"index": 2, "status": "partly", "note": "vague"},
            {"index": 2, "status": "got", "note": "duplicate, ignored"},
            {"index": 9, "status": "got", "note": "out of range, ignored"},
        ],  # index 3 missing -> counted as missed
        "misconception": "",
        "feedback": "Good start.",
        "focus_index": 1,  # points at a part already understood -> moved to the first gap
    }
    monkeypatch.setattr(mc, "chat", lambda *a, **k: mc.Reply(text=json.dumps(reply), cost_usd=0.004))
    r = pipeline.check_understanding("test-concept-a", "a restaurant", MAPPING, "it goes back from the mistake")
    assert [p["status"] for p in r["parts"]] == ["got", "partly", "missed"]
    assert (r["got"], r["total"], r["understood"]) == (1, 3, False)
    assert r["focus_concept_part"] == "error"


def test_check_understanding_all_got(monkeypatch):
    reply = {"parts": [{"index": i, "status": "got", "note": ""} for i in (1, 2, 3)],
             "misconception": "", "feedback": "Great.", "focus_index": 0}
    monkeypatch.setattr(mc, "chat", lambda *a, **k: mc.Reply(text=json.dumps(reply)))
    r = pipeline.check_understanding("test-concept-b", "a restaurant", MAPPING, "it goes back from the mistake")
    assert r["understood"] and r["focus_part"] == ""
