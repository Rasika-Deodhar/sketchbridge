"""The only file in Sketchbridge that talks to Meta Model API.

Facts below come from the official Meta Model API cookbook
(github.com/meta-models/meta-model-cookbook):
  - base URL  https://api.meta.ai/v1
  - auth      "Authorization: Bearer <key>"
  - text      POST /chat/completions   model "muse-spark-1.3"
  - vision    same endpoint; an {"type": "image_url"} part in a *user* message
  - drawing   POST /responses          model "muse-image-1.0"; the image comes
              back as base64 in output[type == "image_generation_call"].result
  - speech    POST /asr/transcribe     model "muse-voice-transcribe-1.0"; multipart with a
              JSON "request" part and an "audio" part (mono 16-bit WAV, 16 or 24 kHz)
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE_URL = "https://api.meta.ai/v1"
TEXT_MODEL = "muse-spark-1.3"
IMAGE_MODEL = "muse-image-1.0"
VOICE_MODEL = "muse-voice-transcribe-1.0"

# Prices in US dollars (from the project brief).
PRICE_IN_PER_M = 1.25
PRICE_CACHED_IN_PER_M = 0.15
PRICE_OUT_PER_M = 4.25
PRICE_PER_IMAGE = 0.01
PRICE_VOICE_PER_HOUR = 0.18

MAX_AUDIO_BYTES = 32 * 1024 * 1024  # the one-shot endpoint's limit (also max 10 minutes)

TIMEOUT = httpx.Timeout(180.0, connect=15.0)  # image calls can take a while


class MetaError(RuntimeError):
    """Meta Model API returned an error or something we could not read."""

    def __init__(self, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status  # HTTP status (0 if we never got one)
        self.code = code      # API error code, e.g. "content_policy_violation"

    @property
    def retryable(self) -> bool:
        """Worth one more try: a server hiccup, rate limit, or a (often false) content filter."""
        return self.status in (0, 429, 500, 502, 503, 504) or self.code == "content_policy_violation"


@dataclass
class Reply:
    """What every call returns: the result plus what it cost."""

    text: str = ""
    image_path: str | None = None
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)

    def json(self) -> dict:
        """Parse `text` as JSON (used when we asked for a JSON schema)."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise MetaError(f"Model did not return valid JSON: {self.text[:200]}") from exc


# ---------------------------------------------------------------- helpers


def _load_dotenv() -> None:
    """Read KEY=value lines from the project's .env into os.environ (if present)."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _api_key() -> str:
    """The key from META_API_KEY (or .env). Empty if not set.

    Empty is allowed for cloud sessions where a network secret makes the proxy
    add the Authorization header itself, so the key never reaches this code.
    """
    _load_dotenv()
    return os.environ.get("META_API_KEY", "").strip()


def _post(path: str, body: dict | None = None, files: dict | None = None) -> dict:
    """Send one POST to Meta (JSON body, or multipart `files`) and return the decoded reply."""
    headers = {}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        if files is not None:
            resp = httpx.post(f"{BASE_URL}{path}", files=files, headers=headers, timeout=TIMEOUT)
        else:
            resp = httpx.post(f"{BASE_URL}{path}", json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise MetaError(f"Could not reach Meta Model API: {exc}") from exc
    if resp.status_code == 401 and not key:
        raise MetaError("HTTP 401: no key. Set META_API_KEY (export it or put it in .env).", status=401)
    if resp.status_code >= 400:
        # The body is the API's error message; it never contains our key.
        try:
            code = (resp.json().get("error") or {}).get("code", "")
        except ValueError:
            code = ""
        raise MetaError(f"HTTP {resp.status_code} from {path}: {resp.text[:300]}",
                        status=resp.status_code, code=code)
    return resp.json()


def _text_cost(usage: dict) -> float:
    """Dollar cost of a Muse Spark call from its `usage` block."""
    prompt = usage.get("prompt_tokens", 0)
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    out = usage.get("completion_tokens", 0)
    return (
        (prompt - cached) * PRICE_IN_PER_M
        + cached * PRICE_CACHED_IN_PER_M
        + out * PRICE_OUT_PER_M
    ) / 1_000_000


def _schema_format(schema: dict, name: str) -> dict:
    """Wrap a JSON schema the way /chat/completions expects it."""
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}


def _image_data_url(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    mime = _sniff_mime(data)
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _sniff_mime(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/webp"


_EXT = {"image/webp": ".webp", "image/png": ".png", "image/jpeg": ".jpg"}


def _chat(content, schema: dict | None, schema_name: str) -> Reply:
    body = {"model": TEXT_MODEL, "messages": [{"role": "user", "content": content}]}
    if schema:
        body["response_format"] = _schema_format(schema, schema_name)
    data = _post("/chat/completions", body)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise MetaError(f"Unexpected chat reply: {str(data)[:300]}") from exc
    usage = data.get("usage") or {}
    return Reply(text=text, cost_usd=_text_cost(usage), usage=usage)


# ---------------------------------------------------------------- public API


def chat(prompt: str, schema: dict | None = None, schema_name: str = "reply") -> Reply:
    """Ask Muse Spark a text question. Pass `schema` to force a JSON shape."""
    return _chat(prompt, schema, schema_name)


def chat_with_image(
    prompt: str, image_path: str, schema: dict | None = None, schema_name: str = "reply"
) -> Reply:
    """Ask Muse Spark a question about a local image file."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
    ]
    return _chat(content, schema, schema_name)


def draw(prompt: str, out_path_without_ext: str, reference_image: str | None = None) -> Reply:
    """Draw one picture with Muse Image and save it. Costs one image call.

    `reference_image`: a local image to edit or keep consistent with. It is sent
    as an `input_image` part inside a user message, as the cookbook shows.
    """
    if reference_image:
        model_input = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": _image_data_url(reference_image)},
            ],
        }]
    else:
        model_input = prompt
    # store=False: we do not need the server to remember this conversation.
    data = _post("/responses", {"model": IMAGE_MODEL, "input": model_input, "store": False})
    b64 = next(
        (item.get("result") for item in data.get("output", [])
         if item.get("type") == "image_generation_call" and item.get("result")),
        None,
    )
    if not b64:
        raise MetaError(f"No image in Muse Image reply (status={data.get('status')})")
    raw = base64.b64decode(b64)
    path = Path(out_path_without_ext).with_suffix(_EXT.get(_sniff_mime(raw), ".webp"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    # Any text message the model wrote alongside the image (usually short).
    text = " ".join(
        part.get("text", "")
        for item in data.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if isinstance(part, dict)
    ).strip()
    return Reply(text=text, image_path=str(path), cost_usd=PRICE_PER_IMAGE,
                 usage=data.get("usage") or {})


def transcribe(wav: bytes) -> Reply:
    """Turn a short spoken WAV recording into text with Muse Voice Transcribe."""
    if not (wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"):
        raise ValueError("Audio must be a WAV file.")
    if len(wav) > MAX_AUDIO_BYTES:
        raise ValueError("Audio is over 32 MB.")
    request = {"model": VOICE_MODEL, "mode": "PUSH_TO_TALK", "audioEncoding": "WAV"}
    data = _post("/asr/transcribe", files={
        # As in the cookbook: the settings travel as a JSON part, not as form fields.
        "request": (None, json.dumps(request), "application/json"),
        "audio": ("speech.wav", wav, "audio/wav"),
    })
    ms = data.get("audioDurationMs") or 0
    return Reply(text=(data.get("transcript") or "").strip(),
                 cost_usd=ms / 3_600_000 * PRICE_VOICE_PER_HOUR,
                 usage={"audio_ms": ms})
