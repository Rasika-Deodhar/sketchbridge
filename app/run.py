"""Command line for Sketchbridge.

    python -m app.run "backpropagation" --interest "cooking"

Shows 3 analogy options. Type 1, 2 or 3 to pick one, or "a" for another set.
"""

from __future__ import annotations

import argparse
import sys

from app import meta_client as mc
from app import pipeline


def show_options(options: list[dict]) -> None:
    print()
    for opt in options:
        print(f"  {opt['id']}. [{opt['domain']}] {opt['one_line']}")
    print("  a. Try another set")


def show_result(result: dict) -> None:
    print("\n=== Analogy ===")
    print(result["analogy"])
    print("\n=== Mapping ===")
    for m in result["mapping"]:
        print(f"  {m['concept_part']}  ->  {m['analogy_part']}")
    check = result["check"]
    print("\n=== Picture ===")
    print(f"  saved:    {result['image_path']}")
    print(f"  check:    {'PASS' if check.get('pass') else 'NOT PASSED'}")
    for fix in check.get("fixes") or []:
        print(f"            - {fix}")
    print(f"  attempts: {result['attempts']} (images used: {result['images_used']})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain a concept with a drawn analogy.")
    parser.add_argument("concept", nargs="?", default="backpropagation")
    parser.add_argument("--interest", default=None, help='e.g. "cooking" or "a chef"')
    args = parser.parse_args()

    total = 0.0
    shown_domains: list[str] = []
    try:
        # Step 0: options. Loop until the user picks one.
        while True:
            options, cost = pipeline.get_options(args.concept, args.interest, shown_domains)
            total += cost
            print(f"\nOptions for '{args.concept}'  (est. cost ${cost:.4f}, "
                  f"{pipeline.option_rounds_left(args.concept)} 'try another' left)")
            shown_domains += [o["domain"] for o in options]
            show_options(options)

            choice = input("\nPick 1, 2, 3 or a: ").strip().lower()
            while choice not in {"1", "2", "3", "a"}:
                choice = input("Please type 1, 2, 3 or a: ").strip().lower()
            if choice == "a":
                if pipeline.option_rounds_left(args.concept) <= 0:
                    print("No more 'try another' rounds for this concept. Pick 1, 2 or 3.")
                    choice = input("Pick 1, 2 or 3: ").strip()
                    while choice not in {"1", "2", "3"}:
                        choice = input("Please type 1, 2 or 3: ").strip()
                else:
                    continue
            chosen = options[int(choice) - 1]
            break

        # Steps 1 to 3: analogy, draw, check (and maybe one redraw).
        print(f"\nDrawing '{chosen['domain']}' ... (this can take a minute)")
        result = pipeline.explain(args.concept, chosen)
        total += result["cost_usd"]
        show_result(result)
        print(f"\nEstimated cost: this request ${result['cost_usd']:.4f}, whole session ${total:.4f}")
        return 0
    except (mc.MetaError, pipeline.LimitError, ValueError) as exc:
        print(f"\nStopped: {exc}")
        print(f"Estimated cost so far: ${total:.4f}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print(f"\nCancelled. Estimated cost so far: ${total:.4f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
