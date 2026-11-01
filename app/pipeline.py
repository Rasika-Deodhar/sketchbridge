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

    interest_line = (
        f"The learner is interested in: {interest.strip()}. Make at least one option use this interest."
        if interest and interest.strip()
        else "No interest given. Use common everyday life."
    )
    avoid_line = (
        "Do not reuse these domains, which were already shown: " + ", ".join(avoid_domains) + "."
        if avoid_domains else ""
    )
    prompt = f"""You help people understand hard ideas through analogies.

Concept: {concept}
{interest_line}
{avoid_line}

Give exactly 3 analogy options. Each must come from a different everyday domain.
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
- image_prompt: one clear scene that shows the analogy parts from the mapping.
  Describe what is visible: objects, people, actions, layout. Simple, friendly illustration style.
  Use no words or letters in the image, except at most 3 very short labels."""
    data = budget.add(mc.chat(prompt, schema=ANALOGY_SCHEMA, schema_name="analogy")).json()
    if not data.get("mapping") or not data.get("image_prompt"):
        raise mc.MetaError("Analogy reply was missing the mapping or the image prompt.")
    return data


# ------------------------------------------------------------ steps 2 and 3: draw and check


def draw_image(image_prompt: str, name: str, budget: Budget) -> str:
    """Draw one picture (counts against the image cap) and return its path."""
    budget.allow_image()
    return budget.add(mc.draw(image_prompt, str(CACHE_DIR / name))).image_path


def check_image(image_path: str, mapping: list[dict], budget: Budget) -> dict:
    """Have Muse Spark look at the picture and say if it shows the mapping."""
    pairs = "\n".join(f"- {m['analogy_part']}  (stands for: {m['concept_part']})" for m in mapping)
    prompt = f"""This picture is meant to illustrate an analogy. It should visibly show these parts:
{pairs}

Check the picture:
- Can a viewer clearly see the main parts listed above?
- Is it one clear scene, with little or no text, and no garbled writing?
Set pass to true only if both are true.
fixes: short, concrete instructions for redrawing it (empty list if pass is true)."""
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
