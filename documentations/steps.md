# Build log

## Step 1: Smoke test (meta_client.py)

- Read the official cookbook to confirm the endpoint, auth, model IDs, vision format, and image output.
- Wrote `app/meta_client.py` with `chat`, `chat_with_image`, and `draw`.
- Wrote `app/smoke_test.py`: 1 text call, 1 drawing, 1 vision call on that drawing (about $0.01 to $0.02).
- Status: the code runs and fails cleanly. The build container had no `META_API_KEY`, and its network
  policy blocked `api.meta.ai`, so no live call was made yet.

## Step 2: Pipeline on the command line (pipeline.py, run.py)

- `app/pipeline.py`: `get_options` (step 0), then `explain`, which calls `make_analogy`,
  `draw_image`, and `check_image`, redrawing once if the check fails.
- `app/run.py`: `python -m app.run "backpropagation" --interest "cooking"`. Shows 3 options,
  you type 1, 2, 3, or `a` for another set, then it runs the rest and prints the cost.
- Cost guards: a `Budget` object counts images and refuses a 3rd; option rounds are capped at 5 per concept.
- Tested offline with fake Meta replies (a scratch script, not committed): menu flow, redraw-once,
  2-image cap, and 5-round cap all behave. Not yet run against the live API from this session (no key here).

### Step 1 and 2: live test (cloud session, key added by the proxy as a network secret)

- Smoke test: all 3 calls OK. Text $0.0003, drawing $0.01 (13 to 26 s), vision check $0.005. Total about $0.015.
- Pipeline ("backpropagation" + "cooking", option 1): worked end to end, about $0.054 with a redraw.
- Found and fixed:
  - Muse Image is sometimes flaky: 1 false `content_policy_violation` and 1 `502` in 5 calls.
    Draws now retry once (with a "family-friendly" prefix after a content refusal).
  - The check was too strict: it asked for "repeat until perfect", which one still picture cannot show.
    The check prompt now judges the core idea, with most parts visible; the same picture then passed.
  - The key can come from the proxy (a network secret), so `META_API_KEY` is now optional in code.
- Typical cost: about $0.03 when the first picture passes, about $0.05 with one redraw.

## Step 3: Web page (main.py, web/index.html) + follow-ups

- `app/main.py`: FastAPI with `/options`, `/explain`, `/followup`, `/image/{id}`, and `/` for the page.
  Prints the estimated cost of every request.
- `web/index.html`: one page, no framework. Question + domain boxes, 3 option buttons + Try another,
  result card (picture, picture strip, analogy, mapping table, self-check badge), and a follow-up chat
  with "I don't get it, simplify" and "Show the next scene" buttons. Light and dark themes.
- `pipeline.followup`: routes a message to answer / simplify / edit / next_scene (see architecture.md).
- Live browser test (Playwright): "What is backpropagation?" + domain "Restaurant" -> 3 restaurant options
  -> "Fixing Salty Soup" (passed the check on the first drawing, $0.026) -> "I don't understand - simplify it"
  (simpler text + picture, $0.018) -> "Show the next scene" ($0.019) -> "why does the feedback go
  backwards?" (text answer, $0.009). Total about $0.08.
- Fixed after the test: simplify had dropped the core "go backwards" idea, and the next scene copied
  the previous picture too closely. Both prompts were tightened; simplify was re-tested and now keeps the idea.
