"""Sketchbridge web server.

    uvicorn app.main:app --reload        then open http://127.0.0.1:8000

Routes:
    GET  /                  the web page (web/index.html)
    POST /options           concept, interest -> 3 analogy options
    POST /explain           concept, option   -> analogy, mapping, checked image
    POST /followup          a question or request about the current picture
    POST /check             the learner explains it back -> which mapping parts they got
    POST /connect           connect the dots: where each part is in the picture, in process order
    GET  /image/{image_id}  a saved picture from cache/
    GET  /demos             the 5 pre-built demo concepts (instant, no API calls)
    POST /transcribe        a short WAV recording (raw body) -> text, via Muse Voice Transcribe

Access code: if ACCESS_CODE is set (environment or .env), every route that calls Meta (and so costs
money) needs the header "X-Access-Code: <code>". The page, the demos and pictures stay open.
Leave ACCESS_CODE empty to run without a code (local use).

Progress: /explain and /followup can take up to a minute. If the request sends
"Accept: application/x-ndjson", the reply is streamed as one JSON object per line:
{"type": "progress", "stage": "draw"} ... then {"type": "result", ...} or {"type": "error", ...}.
Without that header they return plain JSON as before.
"""

from __future__ import annotations

import hmac
import json
import os
import queue
import threading
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import meta_client as mc
from app import pipeline

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Sketchbridge")

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # about 2 minutes of 16 kHz mono speech; the page stops at 30 s


# ------------------------------------------------------------ request shapes


class OptionsIn(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    interest: str | None = Field(default=None, max_length=100)
    avoid_domains: list[str] = Field(default_factory=list, max_length=20)


class Option(BaseModel):
    id: str = Field(max_length=4)
    domain: str = Field(max_length=100)
    one_line: str = Field(max_length=500)


class ExplainIn(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    option: Option


class MappingPair(BaseModel):
    concept_part: str = Field(max_length=300)
    analogy_part: str = Field(max_length=300)


class Turn(BaseModel):
    role: str = Field(max_length=20)
    text: str = Field(max_length=2000)


class FollowupIn(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    analogy: str = Field(max_length=3000)
    mapping: list[MappingPair] = Field(max_length=10)
    image_id: str = Field(max_length=100)
    message: str = Field(default="", max_length=500)
    action: str | None = None
    shown_parts: list[str] = Field(default_factory=list, max_length=20)
    history: list[Turn] = Field(default_factory=list, max_length=20)


class CheckIn(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    analogy: str = Field(max_length=3000)
    mapping: list[MappingPair] = Field(min_length=1, max_length=10)
    explanation: str = Field(min_length=1, max_length=2000)


class ConnectIn(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    analogy: str = Field(max_length=3000)
    mapping: list[MappingPair] = Field(min_length=1, max_length=10)
    image_id: str = Field(max_length=100)
    scenes: list[str] = Field(default_factory=list, max_length=20)


# ------------------------------------------------------------ helpers

ACCESS_DENIED = "access_code"  # the page looks for this detail and asks for the code


def require_access_code(x_access_code: str = Header(default="")) -> None:
    """Refuse paid routes without the right code (only when ACCESS_CODE is set)."""
    mc._load_dotenv()
    expected = os.environ.get("ACCESS_CODE", "").strip()
    if expected and not hmac.compare_digest(x_access_code.strip().encode(), expected.encode()):
        raise HTTPException(401, ACCESS_DENIED)


PAID = [Depends(require_access_code)]



def _run(label: str, fn):
    """Call the pipeline, print the estimated cost, and turn errors into HTTP errors."""
    try:
        result = fn()
    except pipeline.LimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except mc.MetaError as exc:
        print(f"[{label}] Meta error: {exc}")
        raise HTTPException(502, f"Meta Model API error: {exc}") from exc
    print(f"[{label}] estimated cost ${result.get('cost_usd', 0):.4f}")
    return result


def _public(result: dict) -> dict:
    """Drop local file paths before sending a result to the browser."""
    return {k: v for k, v in result.items() if k != "image_path"}


def _respond(request: Request, label: str, fn):
    """Run fn(progress) and return its result: streamed with progress if the page asks, else plain JSON."""
    if "application/x-ndjson" not in request.headers.get("accept", ""):
        return _public(_run(label, lambda: fn(None)))

    events: queue.Queue = queue.Queue()

    def work():
        try:
            result = _run(label, lambda: fn(lambda stage: events.put({"type": "progress", "stage": stage})))
            events.put({"type": "result", **_public(result)})
        except HTTPException as exc:
            events.put({"type": "error", "status": exc.status_code, "detail": exc.detail})
        except Exception:  # noqa: BLE001 - report, never leave the page waiting
            traceback.print_exc()
            events.put({"type": "error", "status": 500, "detail": "Server error. Please try again."})
        finally:
            events.put(None)

    # The Meta calls block, so they run on their own thread while this reply streams the events.
    threading.Thread(target=work, daemon=True).start()

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ routes


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/options", dependencies=PAID)
def options(body: OptionsIn):
    def go():
        opts, cost = pipeline.get_options(body.concept, body.interest, body.avoid_domains)
        return {"options": opts, "cost_usd": round(cost, 4),
                "rounds_left": pipeline.option_rounds_left(body.concept)}
    return _run("options", go)


@app.post("/explain", dependencies=PAID)
def explain(body: ExplainIn, request: Request):
    return _respond(request, "explain",
                    lambda progress: pipeline.explain(body.concept, body.option.model_dump(), progress))


@app.post("/followup", dependencies=PAID)
def followup(body: FollowupIn, request: Request):
    return _respond(request, "followup", lambda progress: pipeline.followup(
        concept=body.concept,
        analogy=body.analogy,
        mapping=[m.model_dump() for m in body.mapping],
        image_id=body.image_id,
        message=body.message,
        action=body.action,
        shown_parts=body.shown_parts,
        history=[t.model_dump() for t in body.history],
        progress=progress,
    ))


@app.post("/check", dependencies=PAID)
def check(body: CheckIn):
    return _run("check", lambda: pipeline.check_understanding(
        concept=body.concept,
        analogy=body.analogy,
        mapping=[m.model_dump() for m in body.mapping],
        explanation=body.explanation,
    ))


@app.post("/connect", dependencies=PAID)
def connect(body: ConnectIn):
    return _run("connect", lambda: pipeline.connect_dots(
        concept=body.concept,
        analogy=body.analogy,
        mapping=[m.model_dump() for m in body.mapping],
        image_id=body.image_id,
        scenes=body.scenes,
    ))


IMAGE_TYPES = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg"}


@app.get("/image/{image_id}")
def image(image_id: str):
    try:
        path = pipeline.image_file(image_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    # Set the type explicitly: slim Linux images (Docker, Render) may not know .webp.
    return FileResponse(path, media_type=IMAGE_TYPES.get(path.suffix, "application/octet-stream"))


@app.get("/health")
def health():
    """For the host's health check: no API calls."""
    return {"ok": True}


@app.get("/demos")
def demos():
    """Pre-built results from `python -m app.build_demo` (empty list if not built)."""
    manifest = pipeline.CACHE_DIR / "demos.json"
    return json.loads(manifest.read_text()) if manifest.exists() else []


@app.post("/transcribe", dependencies=PAID)
async def transcribe(request: Request):
    """Speech to text for the question box. The browser sends a mono 16 kHz WAV as the body."""
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Recording is too long.")
    wav = await request.body()
    if len(wav) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Recording is too long.")

    def go():
        reply = mc.transcribe(wav)
        return {"text": reply.text, "seconds": round(reply.usage.get("audio_ms", 0) / 1000, 1),
                "cost_usd": round(reply.cost_usd, 6)}
    # The Meta call blocks, so run it on a worker thread and keep the server responsive.
    return await run_in_threadpool(_run, "transcribe", go)
