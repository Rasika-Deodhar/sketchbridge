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

from app import meta_client as mc

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

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
- domain: 2 to 4 words, e.g. "making soup"
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


def explain(concept: str, option: dict) -> dict:
    """Run analogy -> draw -> check (-> redraw once) for the chosen option."""
    concept = concept.strip()
    if not concept:
        raise ValueError("Concept is empty.")
    budget = Budget()
    analogy = make_analogy(concept, option, budget)

    run_id = f"{_slug(concept)}-{int(time.time())}"
    prompt = analogy["image_prompt"]
    image_path, check, attempts = None, {"pass": False, "fixes": []}, 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        image_path = draw_image(prompt, f"{run_id}-{attempt}", budget)
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
             history: list[dict] | None = None) -> dict:
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
  (focus_part = its analogy part). image_prompt = a NEW close-up view of that part in the same world,
  style and characters: a different camera angle and composition, not a copy of the current picture. reply = 2 to 3 sentences explaining what this scene shows about the concept.
Rules: new_analogy is "" unless action is simplify. focus_part is "" unless action is next_scene.
Images: no words or letters, except at most 3 very short labels."""

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
        path = draw_image(image_prompt, name, budget, reference_image=str(current))
        result.update(image_path=path, image_id=Path(path).name)
    result.update(images_used=budget.images, cost_usd=round(budget.cost_usd, 4))
    return result
