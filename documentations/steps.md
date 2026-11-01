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
