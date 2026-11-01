"""Step 1 smoke test: call each Meta function once and print the cost.

Run:  python -m app.smoke_test
Makes 2 text calls and 1 image call (about 1 to 2 cents in total).
"""

from __future__ import annotations

import sys
import time

from app import meta_client as mc


def step(name, fn):
    start = time.time()
    try:
        reply = fn()
    except mc.MetaError as exc:
        print(f"[FAIL] {name}: {exc}")
        return None
    print(f"[ OK ] {name} ({time.time() - start:.1f}s, ~${reply.cost_usd:.4f})")
    return reply


def main() -> int:
    total = 0.0
    r3 = None

    r1 = step("chat", lambda: mc.chat("Reply with the single word: ready"))
    if not r1:
        return 1
    print("       ->", r1.text.strip()[:80])
    total += r1.cost_usd

    r2 = step("draw", lambda: mc.draw(
        "A simple flat illustration of a red apple on a white table. No text.",
        "cache/smoke_apple"))
    if r2:
        print("       -> saved", r2.image_path)
        total += r2.cost_usd

        r3 = step("chat_with_image", lambda: mc.chat_with_image(
            "What fruit is in this picture? Answer as JSON.", r2.image_path,
            schema={"type": "object",
                    "properties": {"fruit": {"type": "string"}},
                    "required": ["fruit"], "additionalProperties": False},
            schema_name="fruit"))
        if r3:
            print("       ->", r3.json())
            total += r3.cost_usd

    print(f"\nEstimated total cost: ${total:.4f}")
    return 0 if (r1 and r2 and r3) else 1


if __name__ == "__main__":
    sys.exit(main())
