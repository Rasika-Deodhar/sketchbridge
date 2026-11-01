"""Step 4: build the demo cache, so a demo video does not depend on live API speed.

    python -m app.build_demo            build any demo that is not cached yet
    python -m app.build_demo --force    rebuild all 5
    python -m app.build_demo --only vaccine   rebuild one

For each concept it runs: options -> explain (option 1) -> one "simplify" follow-up,
then saves pictures as cache/demo-<slug>*.webp and everything else in cache/demos.json.
Costs about 5 to 6 cents per concept.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import meta_client as mc
from app import pipeline

DEMOS = [
    ("backpropagation", "What is backpropagation?", "Restaurant"),
    ("hash-table", "What is a hash table?", "Library"),
    ("compound-interest", "How does compound interest work?", "Gardening"),
    ("photosynthesis", "What is photosynthesis?", "Factory"),
    ("vaccine", "How does a vaccine train the immune system?", "Security team"),
]

MANIFEST = pipeline.CACHE_DIR / "demos.json"


def _rename(image_id: str, new_stem: str) -> str:
    """Give a cached picture a stable demo name and return its new id."""
    old = pipeline.image_file(image_id)
    new = old.with_name(new_stem + old.suffix)
    old.replace(new)
    return new.name


def build_one(slug: str, concept: str, interest: str) -> dict:
    total = 0.0
    options, cost = pipeline.get_options(concept, interest)
    total += cost
    chosen = options[0]
    print(f"  options: {[o['domain'] for o in options]}  -> picked '{chosen['domain']}'")

    result = pipeline.explain(concept, chosen)
    total += result["cost_usd"]
    result["image_id"] = _rename(result["image_id"], f"demo-{slug}")
    result.pop("image_path", None)
    print(f"  explain: check={'PASS' if result['check'].get('pass') else 'not passed'}, "
          f"attempts={result['attempts']}, ${result['cost_usd']:.4f}")

    simple = pipeline.followup(concept, result["analogy"], result["mapping"], result["image_id"],
                               "I don't understand - simplify it", action="simplify")
    total += simple["cost_usd"]
    if simple.get("image_id"):
        simple["image_id"] = _rename(simple["image_id"], f"demo-{slug}-simple")
    simple.pop("image_path", None)
    print(f"  simplify: {simple['new_analogy'][:90]}...  ${simple['cost_usd']:.4f}")

    return {"slug": slug, "concept": concept, "interest": interest, "options": options,
            "chosen": chosen, "result": result, "simplify": simple, "cost_usd": round(total, 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild demos that already exist")
    parser.add_argument("--only", help="build just this slug, e.g. vaccine")
    args = parser.parse_args()

    demos = {d["slug"]: d for d in json.loads(MANIFEST.read_text())} if MANIFEST.exists() else {}
    spent = 0.0
    for slug, concept, interest in DEMOS:
        if args.only and slug != args.only:
            continue
        if slug in demos and not (args.force or args.only):
            print(f"[skip] {concept} (already cached)")
            continue
        print(f"[build] {concept} / {interest}")
        try:
            demos[slug] = build_one(slug, concept, interest)
            spent += demos[slug]["cost_usd"]
        except (mc.MetaError, pipeline.LimitError) as exc:
            print(f"  FAILED: {exc}  (run again later to retry this one)")
        # Save after every concept so a failure later does not lose earlier work.
        ordered = [demos[s] for s, _, _ in DEMOS if s in demos]
        MANIFEST.write_text(json.dumps(ordered, indent=2, ensure_ascii=False))
    print(f"\n{len(demos)}/{len(DEMOS)} demos cached in {MANIFEST}. Spent this run: ${spent:.4f}")
    return 0 if len(demos) == len(DEMOS) else 1


if __name__ == "__main__":
    sys.exit(main())
