"""The Sketchbridge pipeline: plain functions called in order.

    get_options(concept, interest)  -> 3 analogy options        (step 0, text)
    explain(concept, option)        -> analogy + checked image  (steps 1 to 3)

explain() runs:
    make_analogy  -> analogy, mapping, image_prompt   (Muse Spark)
    draw          -> image saved in cache/            (Muse Image)
    check_image   -> pass / fixes                     (Muse Spark looking at the image)
    if the check fails: redraw once with the fixes, then check again.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from app import meta_client as mc

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

# Optional callback that reports which stage is running ("analogy", "draw", "check", ...).
# The web server streams these to the page for its progress bar.
Progress = Callable[[str], None] | None


def _report(progress: Progress, stage: str) -> None:
    if progress:
        progress(stage)

# ------------------------------------------------------------ cost guard

MAX_IMAGES_PER_REQUEST = 2  # hard rule: never more than 2 images per request
MAX_ATTEMPTS = 2            # first draw + one redraw
MAX_OPTION_ROUNDS = 5       # first set of options + "Try another" rounds, per concept
DRAW_RETRIES = 1            # extra try when a draw call fails and returns no image (not billed)
SAFE_PREFIX = "Wholesome, family-friendly educational cartoon illustration. "

assert MAX_ATTEMPTS <= MAX_IMAGES_PER_REQUEST, "attempts would exceed the image cap"


class LimitError(RuntimeError):
    """A cost guard stopped the request."""


class Budget:
    """Counts cost and image calls for one request, and refuses a 3rd image."""

    def __init__(self) -> None:
        self.cost_usd = 0.0
        self.images = 0

    def add(self, reply: mc.Reply) -> mc.Reply:
        self.cost_usd += reply.cost_usd
        return reply

    def allow_image(self) -> None:
        if self.images >= MAX_IMAGES_PER_REQUEST:
            raise LimitError(f"Refusing: a request may make at most {MAX_IMAGES_PER_REQUEST} image calls.")
        self.images += 1


# How many option rounds each concept has used (kept in memory while the app runs).
_option_rounds: dict[str, int] = {}


def _concept_key(concept: str) -> str:
    return " ".join(concept.lower().split())


def option_rounds_left(concept: str) -> int:
    return MAX_OPTION_ROUNDS - _option_rounds.get(_concept_key(concept), 0)


# ------------------------------------------------------------ JSON shapes

OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "domain": {"type": "string"},
                    "one_line": {"type": "string"},
                },
                "required": ["id", "domain", "one_line"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}

ANALOGY_SCHEMA = {
    "type": "object",
    "properties": {
        "analogy": {"type": "string"},
        "mapping": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_part": {"type": "string"},
                    "analogy_part": {"type": "string"},
                },
                "required": ["concept_part", "analogy_part"],
                "additionalProperties": False,
            },
        },
        "image_prompt": {"type": "string"},
    },
    "required": ["analogy", "mapping", "image_prompt"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "fixes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["pass", "fixes"],
    "additionalProperties": False,
}

# ------------------------------------------------------------ step 0: options


def get_options(concept: str, interest: str | None = None,
                avoid_domains: list[str] | None = None) -> tuple[list[dict], float]:
    """Ask for 3 analogy options from different everyday domains.

    Returns (options, cost). Pass the domains already shown in `avoid_domains`
    so "Try another" gives fresh ideas. Capped at MAX_OPTION_ROUNDS per concept.
    """
    concept = concept.strip()
    if not concept:
        raise ValueError("Concept is empty.")
    key = _concept_key(concept)
    if _option_rounds.get(key, 0) >= MAX_OPTION_ROUNDS:
        raise LimitError(f"Option limit reached: at most {MAX_OPTION_ROUNDS} rounds per concept.")
    _option_rounds[key] = _option_rounds.get(key, 0) + 1

    if interest and interest.strip():
        # The user named a world (e.g. "Restaurant"): all 3 options live there.
        variety_line = (
            f"The learner chose this domain: {interest.strip()}. Set all 3 options in that world, "
            "each using a different scene, role, or object from it."
        )
    else:
        variety_line = "No domain given. Use 3 different everyday domains."
    avoid_line = (
        "Do not reuse these, which were already shown: " + ", ".join(avoid_domains) + "."
        if avoid_domains else ""
    )
    prompt = f"""You help people understand hard ideas through analogies.

Concept (the learner may phrase it as a question): {concept}
{variety_line}
{avoid_line}

Give exactly 3 analogy options.
Each analogy must be accurate: its parts must match how the concept really works.
For each option give:
- id: "1", "2" or "3"
- domain: 2 to 4 words naming the specific scene, e.g. "fixing salty soup" (never just the domain name)
- one_line: one plain sentence saying how the concept is like this."""

    reply = mc.chat(prompt, schema=OPTIONS_SCHEMA, schema_name="options")
    options = reply.json().get("options", [])
    if len(options) < 3:
        raise mc.MetaError(f"Expected 3 options, got {len(options)}.")
    options = options[:3]
    for i, opt in enumerate(options, start=1):
        opt["id"] = str(i)  # keep ids predictable for the buttons
    return options, reply.cost_usd


# ------------------------------------------------------------ step 1: analogy


def make_analogy(concept: str, option: dict, budget: Budget) -> dict:
    """Turn the chosen option into a full analogy, a mapping, and an image prompt."""
    prompt = f"""Explain this concept with the chosen analogy.

Concept: {concept}
Analogy domain: {option.get('domain', '')}
Idea: {option.get('one_line', '')}

Return:
- analogy: 3 to 5 plain sentences a beginner can follow.
- mapping: 3 to 6 pairs. Each pair matches one part of the concept (concept_part)
  to the matching part of the analogy (analogy_part).
- image_prompt: one clear scene that shows the analogy parts from the mapping
  (focus on the parts that can be seen in one still picture).
  Describe what is visible: objects, people, actions, layout. Simple, friendly illustration style.
  Use no words or letters in the image, except at most 3 very short labels."""
    data = budget.add(mc.chat(prompt, schema=ANALOGY_SCHEMA, schema_name="analogy")).json()
    if not data.get("mapping") or not data.get("image_prompt"):
        raise mc.MetaError("Analogy reply was missing the mapping or the image prompt.")
    return data


# ------------------------------------------------------------ steps 2 and 3: draw and check


def draw_image(image_prompt: str, name: str, budget: Budget,
               reference_image: str | None = None) -> str:
    """Draw one picture (counts against the image cap) and return its path.

    Muse Image sometimes fails with a 502 or a false content-filter refusal.
    Those calls return no image, so we try once more. A content refusal is
    retried with a "family-friendly" prefix that usually gets past the filter.
    """
    budget.allow_image()
    prompt = image_prompt
    for attempt in range(DRAW_RETRIES + 1):
        try:
            return budget.add(mc.draw(prompt, str(CACHE_DIR / name), reference_image)).image_path
        except mc.MetaError as exc:
            if attempt == DRAW_RETRIES or not exc.retryable:
                raise
            print(f"  (draw failed: {exc.code or exc.status}; retrying once)")
            if exc.code == "content_policy_violation":
                prompt = SAFE_PREFIX + image_prompt
            else:
                time.sleep(3)
    raise AssertionError("unreachable")


def check_image(image_path: str, mapping: list[dict], budget: Budget) -> dict:
    """Have Muse Spark look at the picture and say if it shows the mapping."""
    pairs = "\n".join(f"- {m['analogy_part']}  (stands for: {m['concept_part']})" for m in mapping)
    prompt = f"""This picture is meant to illustrate an analogy. These are its parts:
{pairs}

Judge it as a teacher would use it, not as a perfectionist:
- Does the scene show the core idea, with most of the parts above recognizable?
  A single still picture cannot show time or repetition, so do not require those.
- Is it one clear scene, with little or no text, and no garbled writing?
Set pass to true if both are true.
fixes: only if pass is false, at most 3 short, concrete changes for a redraw. Otherwise an empty list."""
    return budget.add(
        mc.chat_with_image(prompt, image_path, schema=CHECK_SCHEMA, schema_name="check")
    ).json()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "concept"


# ------------------------------------------------------------ steps 1 to 3 together


def explain(concept: str, option: dict, progress: Progress = None) -> dict:
    """Run analogy -> draw -> check (-> redraw once) for the chosen option.

    Stages reported to `progress`: analogy, draw, check, and if the check fails, redraw, recheck.
    """
    concept = concept.strip()
    if not concept:
        raise ValueError("Concept is empty.")
    budget = Budget()
    _report(progress, "analogy")
    analogy = make_analogy(concept, option, budget)

    run_id = f"{_slug(concept)}-{int(time.time())}"
    prompt = analogy["image_prompt"]
    image_path, check, attempts = None, {"pass": False, "fixes": []}, 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        _report(progress, "draw" if attempt == 1 else "redraw")
        image_path = draw_image(prompt, f"{run_id}-{attempt}", budget)
        _report(progress, "check" if attempt == 1 else "recheck")
        check = check_image(image_path, analogy["mapping"], budget)
        if check.get("pass"):
            break
        # Failed: add the reviewer's fixes to the prompt and try one more time.
        fixes = "; ".join(check.get("fixes") or ["make every mapped part clearly visible"])
        prompt = f"{analogy['image_prompt']}\n\nImportant fixes from a review of the last attempt: {fixes}"

    return {
        "concept": concept,
        "option": option,
        "analogy": analogy["analogy"],
        "mapping": analogy["mapping"],
        "image_prompt": prompt,
        "image_path": image_path,
        "image_id": Path(image_path).name if image_path else None,
        "check": check,
        "attempts": attempts,
        "images_used": budget.images,
        "cost_usd": round(budget.cost_usd, 4),
    }


# ------------------------------------------------------------ follow-ups (after the first picture)

FOLLOWUP_ACTIONS = ["answer", "simplify", "edit", "next_scene"]
MAX_FOLLOWUPS_PER_CONCEPT = 15  # each follow-up makes at most 1 image
_followups: dict[str, int] = {}

FOLLOWUP_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": FOLLOWUP_ACTIONS},
        "reply": {"type": "string"},
        "new_analogy": {"type": "string"},
        "image_prompt": {"type": "string"},
        "focus_part": {"type": "string"},
    },
    "required": ["action", "reply", "new_analogy", "image_prompt", "focus_part"],
    "additionalProperties": False,
}

IMAGE_NAME_RE = re.compile(r"^[a-z0-9-]+\.(webp|png|jpg)$")


def image_file(image_id: str) -> Path:
    """Turn an image id like 'backprop-123-1.webp' into a safe path inside cache/."""
    if not IMAGE_NAME_RE.match(image_id or ""):
        raise ValueError("Bad image id.")
    path = CACHE_DIR / image_id
    if not path.is_file():
        raise ValueError("Image not found.")
    return path


def followup(concept: str, analogy: str, mapping: list[dict], image_id: str, message: str,
             action: str | None = None, shown_parts: list[str] | None = None,
             history: list[dict] | None = None, progress: Progress = None) -> dict:
    """Handle what the learner says after seeing the picture.

    Muse Spark looks at the current picture and the message and picks one action:
      answer      reply in text only (no new image)
      simplify    rewrite the explanation more simply and draw a simpler picture
      edit        change the picture the way the learner asked
      next_scene  draw a close-up scene of one mapping part not shown yet (a series)
    `action` forces one of these (used by the quick buttons).
    """
    concept, message = concept.strip(), (message or "").strip()
    if action and action not in FOLLOWUP_ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    if not message and not action:
        raise ValueError("Type a question or pick an action.")
    key = _concept_key(concept)
    if _followups.get(key, 0) >= MAX_FOLLOWUPS_PER_CONCEPT:
        raise LimitError(f"Follow-up limit reached: {MAX_FOLLOWUPS_PER_CONCEPT} per concept.")
    _followups[key] = _followups.get(key, 0) + 1

    current = image_file(image_id)
    budget = Budget()
    pairs = "\n".join(f"- {m['concept_part']}  ->  {m['analogy_part']}" for m in mapping)
    shown = ", ".join(shown_parts or []) or "none yet"
    talk = "\n".join(f"{h.get('role', 'user')}: {h.get('text', '')}" for h in (history or [])[-6:])
    forced = f"You MUST use action: {action}." if action else "Pick the action that best fits the message."

    prompt = f"""You are a patient tutor. The learner is studying "{concept}" through an analogy,
and is looking at the attached picture of it.

Current explanation: {analogy}
Mapping (concept part -> analogy part):
{pairs}
Close-up scenes already shown: {shown}
Recent conversation:
{talk or "(none)"}

Learner says: "{message or "(pressed a button)"}"
{forced}

Actions:
- answer: they ask a question that words can answer. reply = a clear answer in 2 to 5 plain sentences,
  pointing at things in the picture. image_prompt = "".
- simplify: they are confused or ask for simpler. new_analogy = a much simpler explanation
  (2 to 4 short sentences, everyday words, no jargon) that STILL keeps the one key idea of the
  concept (for example, for backpropagation: go backwards from the mistake to find which step caused it).
  Drop details, never the core idea. image_prompt = a simpler version of the scene with fewer objects,
  big and clear, that still shows that key idea. reply = one sentence saying what changed.
- edit: they ask to change the picture. image_prompt = the change to make, keeping everything else.
  reply = one sentence saying what changed.
- next_scene: they want more, the next step, or a closer look. Pick one mapping part not shown yet
  (focus_part = its analogy part). If the learner names a part, use that part even if it was shown.
  image_prompt = a NEW close-up view of that part in the same world,
  style and characters: a different camera angle and composition, not a copy of the current picture.
  reply = 2 to 3 sentences: first one sentence linking this scene to the previous one (what led here),
  then what this scene shows about the concept.
Rules: new_analogy is "" unless action is simplify. focus_part is "" unless action is next_scene.
Images: no words or letters, except at most 3 very short labels."""

    _report(progress, "plan")
    plan = budget.add(mc.chat_with_image(prompt, str(current), schema=FOLLOWUP_SCHEMA,
                                         schema_name="followup")).json()
    chosen = action or plan.get("action", "answer")
    result = {
        "action": chosen,
        "reply": plan.get("reply", ""),
        "new_analogy": plan.get("new_analogy", "") if chosen == "simplify" else "",
        "focus_part": plan.get("focus_part", "") if chosen == "next_scene" else "",
        "image_id": None,
        "image_path": None,
    }
    if chosen != "answer":
        image_prompt = plan.get("image_prompt") or message
        if chosen == "edit":
            image_prompt = f"Edit this picture: {image_prompt}. Keep the same style and everything else."
        elif chosen == "next_scene":
            image_prompt = (f"Draw a new scene, a different view from this picture. Keep only its art style "
                            f"and characters. Scene: {image_prompt}")
        else:
            image_prompt = f"In the same art style and with the same characters as this picture: {image_prompt}"
        name = f"{_slug(concept)}-{int(time.time())}-{chosen.replace('_', '')}"
        _report(progress, "draw")
        path = draw_image(image_prompt, name, budget, reference_image=str(current))
        result.update(image_path=path, image_id=Path(path).name)
    result.update(images_used=budget.images, cost_usd=round(budget.cost_usd, 4))
    return result


# ------------------------------------------------------------ explain it back (check understanding)

MAX_CHECKS_PER_CONCEPT = 10  # text only, about $0.01 each
_checks: dict[str, int] = {}
CHECK_STATUSES = ["got", "partly", "missed"]

UNDERSTANDING_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {"type": "string", "enum": CHECK_STATUSES},
                    "note": {"type": "string"},
                },
                "required": ["index", "status", "note"],
                "additionalProperties": False,
            },
        },
        "misconception": {"type": "string"},
        "feedback": {"type": "string"},
        "focus_index": {"type": "integer"},
    },
    "required": ["parts", "misconception", "feedback", "focus_index"],
    "additionalProperties": False,
}


def check_understanding(concept: str, analogy: str, mapping: list[dict], explanation: str) -> dict:
    """Grade the learner's own explanation against the mapping (retrieval practice).

    Returns one status per mapping part (got / partly / missed), any misconception,
    short encouraging feedback, and the most important part to show next (or none).
    Text only: no image is made here. The page offers a next_scene follow-up for the gap.
    """
    concept, explanation = concept.strip(), (explanation or "").strip()
    if not concept or not mapping:
        raise ValueError("Nothing to check against yet.")
    if len(explanation.split()) < 3:
        raise ValueError("Write (or say) a sentence or two in your own words first.")
    key = _concept_key(concept)
    if _checks.get(key, 0) >= MAX_CHECKS_PER_CONCEPT:
        raise LimitError(f"Check limit reached: {MAX_CHECKS_PER_CONCEPT} per concept.")
    _checks[key] = _checks.get(key, 0) + 1

    pairs = "\n".join(f"{i}. {m['concept_part']}  (in the analogy: {m['analogy_part']})"
                      for i, m in enumerate(mapping, start=1))
    prompt = f"""You are a kind, honest teacher checking whether a learner understood "{concept}".
They were taught with this analogy: {analogy}

The key parts of the concept (numbered):
{pairs}

The learner explained it back in their own words (it may come from speech, so ignore typos and filler):
\"\"\"{explanation}\"\"\"

For EVERY numbered part, give:
- index: its number
- status: "got" if their explanation clearly shows that part (in concept words OR analogy words),
  "partly" if it is vague or half right, "missed" if it is absent or wrong
- note: at most 12 words on why
misconception: one sentence naming a wrong idea they stated, or "" if there is none.
  Mixing up the analogy with the real thing counts (e.g. saying neurons are literally waiters).
feedback: 2 to 3 plain, encouraging sentences: first what they got right, then the one most
  important thing to fix. Speak to them as "you".
focus_index: the number of the most important part they missed or got partly, or 0 if they got all.
Judge understanding, not wording. Do not reward copying the analogy text without the idea."""

    budget = Budget()
    # Medium effort: at the default it took 30 s (the gateway limit); medium took 17 s and graded the same.
    data = budget.add(mc.chat(prompt, schema=UNDERSTANDING_SCHEMA, schema_name="understanding",
                              effort="medium")).json()

    # Rebuild the list in mapping order so a skipped or repeated index can't misalign the page.
    by_index: dict[int, dict] = {}
    for p in data.get("parts", []):
        if p.get("status") in CHECK_STATUSES:
            by_index.setdefault(p.get("index"), p)  # first answer wins
    parts = []
    for i, m in enumerate(mapping, start=1):
        p = by_index.get(i, {"status": "missed", "note": "not mentioned"})
        parts.append({"concept_part": m["concept_part"], "analogy_part": m["analogy_part"],
                      "status": p["status"], "note": p.get("note", "")})

    focus = data.get("focus_index", 0)
    if not (1 <= focus <= len(parts)) or parts[focus - 1]["status"] == "got":
        gaps = [i for i, p in enumerate(parts, start=1) if p["status"] != "got"]
        focus = gaps[0] if gaps else 0
    got = sum(p["status"] == "got" for p in parts)
    misconception = (data.get("misconception") or "").strip()
    return {
        "parts": parts,
        "got": got,
        "total": len(parts),
        "understood": got == len(parts) and not misconception,
        "misconception": misconception,
        "feedback": data.get("feedback", ""),
        "focus_part": parts[focus - 1]["analogy_part"] if focus else "",
        "focus_concept_part": parts[focus - 1]["concept_part"] if focus else "",
        "cost_usd": round(budget.cost_usd, 4),
    }


# ------------------------------------------------------------ connect the dots (the whole picture)

MAX_CONNECTS_PER_CONCEPT = 10  # text only, about $0.006 each
_connects: dict[str, int] = {}
GRID = 1000  # dot positions use a 0..1000 grid over the picture's width and height

CONNECT_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "visible": {"type": "boolean"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "says": {"type": "string"},
                },
                "required": ["index", "visible", "x", "y", "says"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["steps", "summary"],
    "additionalProperties": False,
}


def connect_dots(concept: str, analogy: str, mapping: list[dict], image_id: str,
                 scenes: list[str] | None = None) -> dict:
    """Locate each mapping part in the picture and walk through them in the order the concept works.

    One Muse Spark vision call ("perception grounding", as in Meta's cookbook) returns, for every part:
    where it is in the picture (x, y on a 0..1000 grid), and one sentence on what happens there and how
    it leads to the next part. The page draws numbered dots joined by a path and plays the walkthrough.
    `scenes`: analogy parts that already have a close-up scene, so the story can point to them.
    Text only: no new picture is made.
    """
    concept = concept.strip()
    if not concept or not mapping:
        raise ValueError("Nothing to connect yet.")
    current = image_file(image_id)
    key = _concept_key(concept)
    if _connects.get(key, 0) >= MAX_CONNECTS_PER_CONCEPT:
        raise LimitError(f"Connect-the-dots limit reached: {MAX_CONNECTS_PER_CONCEPT} per concept.")
    _connects[key] = _connects.get(key, 0) + 1

    pairs = "\n".join(f"{i}. {m['analogy_part']}  (stands for: {m['concept_part']})"
                      for i, m in enumerate(mapping, start=1))
    seen = ", ".join(scenes or []) or "none"
    prompt = f"""The attached picture illustrates "{concept}" with this analogy: {analogy}

Numbered parts (analogy part, and the concept part it stands for):
{pairs}

The learner has seen separate close-up scenes of: {seen}. Help them see how everything fits together.

Return steps: one entry for EVERY numbered part, ordered the way the concept actually works
(cause before effect, start to finish), not in list order.
- index: the part's number
- visible: true if the part can be seen in the picture
- x, y: the CENTER of that part in the picture, on a 0 to {GRID} grid
  (x = 0 left edge, {GRID} right edge; y = 0 top edge, {GRID} bottom edge). Look carefully and be precise.
  If not visible, the best guess of where it would be.
- says: ONE plain sentence, max 25 words: what happens at this part, in analogy words AND concept words,
  and how it leads to the next step (the last step says what the whole process achieves).
summary: 2 to 3 plain sentences giving the whole picture: how the parts work together as one process."""

    budget = Budget()
    # Low effort: on busy pictures the default thinking ran past the API gateway's 30 s limit (HTTP 502).
    data = budget.add(mc.chat_with_image(prompt, str(current), schema=CONNECT_SCHEMA,
                                         schema_name="connect", effort="low")).json()

    # Keep the model's order, drop bad or repeated indexes, and add any part it skipped at the end.
    steps, used = [], set()
    for s in data.get("steps", []):
        i = s.get("index")
        if isinstance(i, int) and 1 <= i <= len(mapping) and i not in used:
            used.add(i)
            steps.append((i, s))
    steps += [(i, {"visible": False, "x": GRID / 2, "y": GRID / 2, "says": ""})
              for i in range(1, len(mapping) + 1) if i not in used]

    def clamp(v) -> float:
        try:
            return round(min(max(float(v), 0.0), GRID) / GRID, 4)  # 0..1 for the page
        except (TypeError, ValueError):
            return 0.5

    out = []
    for n, (i, s) in enumerate(steps, start=1):
        m = mapping[i - 1]
        out.append({"step": n, "concept_part": m["concept_part"], "analogy_part": m["analogy_part"],
                    "visible": bool(s.get("visible")), "x": clamp(s.get("x")), "y": clamp(s.get("y")),
                    "says": (s.get("says") or "").strip()})
    return {"image_id": image_id, "steps": out, "summary": data.get("summary", ""),
            "cost_usd": round(budget.cost_usd, 4)}

