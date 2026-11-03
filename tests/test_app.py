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


def _fake_draw(prompt, out_path_without_ext, reference_image=None):
    path = out_path_without_ext + ".webp"
    with open(path, "wb") as f:
        f.write(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    return mc.Reply(image_path=path, cost_usd=0.01)


def test_explain_streams_progress_then_result(monkeypatch, tmp_path):
    analogy = {"analogy": "A kitchen.", "image_prompt": "a kitchen",
               "mapping": [{"concept_part": "error", "analogy_part": "salty soup"}]}
    checks = iter([{"pass": False, "fixes": ["show the soup"]}, {"pass": True, "fixes": []}])
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mc, "chat", lambda *a, **k: mc.Reply(text=json.dumps(analogy)))
    monkeypatch.setattr(mc, "chat_with_image", lambda *a, **k: mc.Reply(text=json.dumps(next(checks))))
    monkeypatch.setattr(mc, "draw", _fake_draw)
    body = {"concept": "stream test", "option": {"id": "1", "domain": "kitchen", "one_line": "x"}}

    r = client.post("/explain", json=body, headers={"Accept": "application/x-ndjson"})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    stages = [e["stage"] for e in events if e["type"] == "progress"]
    assert stages == ["analogy", "draw", "check", "redraw", "recheck"]
    assert events[-1]["type"] == "result" and events[-1]["attempts"] == 2
    assert "image_path" not in events[-1]  # local paths never reach the browser


def test_explain_plain_json_and_stream_errors(monkeypatch):
    def boom(*a, **k):
        raise mc.MetaError("HTTP 502 from /chat/completions: upstream request failed", status=502)
    monkeypatch.setattr(mc, "chat", boom)
    body = {"concept": "error test", "option": {"id": "1", "domain": "kitchen", "one_line": "x"}}
    assert client.post("/explain", json=body).status_code == 502  # no Accept header: plain JSON
    r = client.post("/explain", json=body, headers={"Accept": "application/x-ndjson"})
    last = json.loads(r.text.strip().splitlines()[-1])
    assert last["type"] == "error" and last["status"] == 502


def test_connect_dots_repairs_model_reply(monkeypatch):
    reply = {"steps": [
        {"index": 3, "visible": True, "x": 900, "y": 100, "says": "third first"},
        {"index": 1, "visible": True, "x": 1500, "y": -20, "says": "off the grid"},  # clamped
        {"index": 1, "visible": False, "x": 0, "y": 0, "says": "duplicate, ignored"},
        {"index": 7, "visible": True, "x": 1, "y": 1, "says": "no such part"},
    ], "summary": "It all fits."}  # part 2 missing -> added at the end
    monkeypatch.setattr(mc, "chat_with_image", lambda *a, **k: mc.Reply(text=json.dumps(reply), cost_usd=0.01))
    demo = client.get("/demos").json()[0]["result"]
    r = pipeline.connect_dots("connect-test", "a restaurant", MAPPING, demo["image_id"])
    assert [s["concept_part"] for s in r["steps"]] == ["backward pass", "prediction", "error"]
    assert [s["step"] for s in r["steps"]] == [1, 2, 3]
    assert (r["steps"][0]["x"], r["steps"][0]["y"]) == (0.9, 0.1)
    assert (r["steps"][1]["x"], r["steps"][1]["y"]) == (1.0, 0.0)
    assert r["steps"][2]["visible"] is False and r["summary"] == "It all fits."


def test_connect_route_checks(monkeypatch):
    body = {"concept": "c", "analogy": "a", "mapping": MAPPING, "image_id": "missing.webp"}
    assert client.post("/connect", json=body).status_code == 400  # unknown picture
    monkeypatch.setenv("ACCESS_CODE", "open-sesame")
    assert client.post("/connect", json=body).status_code == 401


def test_chat_retries_gateway_timeout_with_low_effort(monkeypatch):
    sent = []

    def fake_post(path, body=None, files=None):
        sent.append(dict(body))
        if len(sent) == 1:
            raise mc.MetaError("HTTP 502 from /chat/completions: upstream request failed", status=502)
        return {"choices": [{"message": {"content": "OK"}}], "usage": {}}

    monkeypatch.setattr(mc, "_post", fake_post)
    assert mc.chat("hi").text == "OK"
    assert "reasoning_effort" not in sent[0] and sent[1]["reasoning_effort"] == "low"

    # Already at low effort, or another error: no retry.
    sent.clear()
    with pytest.raises(mc.MetaError):
        mc.chat("hi", effort="low")
    assert len(sent) == 1
