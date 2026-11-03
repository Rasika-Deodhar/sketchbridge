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

## Step 4: Demo cache (build_demo.py, cache/demos.json)

- `app/build_demo.py` runs 5 concepts through options -> explain (option 1) -> one "simplify" follow-up,
  renames the pictures to `cache/demo-<slug>.webp` / `-simple.webp`, and writes `cache/demos.json`.
  `--only <slug>` rebuilds one demo; `--force` rebuilds all.
- The 5 demos (all passed the self-check):

| Concept | Domain | Picked analogy | Drawings |
| --- | --- | --- | --- |
| What is backpropagation? | Restaurant | fixing salty soup | 1 |
| What is a hash table? | Library | Library card catalog | 2 |
| How does compound interest work? | Gardening | growing tomato plants | 1 |
| What is photosynthesis? | Factory | solar panel factory | 1 |
| How does a vaccine train the immune system? | Security team | building fire drill | 1 |

- Cost: $0.31 for the first build, plus $0.05 to rebuild the vaccine demo after fixing option names
  (they had all come back as just "Security team"; the prompt now asks for a specific scene name).
- Web: `GET /demos` serves the manifest. The page shows the 5 as "Ready-made examples". Clicking one loads
  its options and result instantly; the cached option is marked "instant", and "I don't get it, simplify"
  on the first picture uses the saved answer. Everything else (other options, other follow-ups) goes live.
- Browser test: all 5 demos plus a cached simplify made zero API calls.

## Step 5: Voice input (optional)

- `meta_client.transcribe(wav)`: Muse Voice Transcribe (`muse-voice-transcribe-1.0`) via the one-shot
  `POST /v1/asr/transcribe`, sent as multipart (a JSON `request` part + an `audio` WAV part), as in the
  cookbook's `06_muse_voice` recipe. Cost = audio length x $0.18/hour.
- `POST /transcribe` in `main.py`: the browser sends the WAV as the raw body (max 4 MB), so no extra
  upload library is needed. The blocking Meta call runs on a worker thread.
- Page: a 🎤 button beside the question box. It records with the browser mic (auto-stops at 30 s),
  converts the recording to 16 kHz mono 16-bit WAV in the browser, and fills the question box.
- Tests: a synthetic "What is backpropagation?" clip (made with espeak-ng in the build container only)
  came back as "What is back propagation?" ($0.0001 for 2 s). End to end in Chromium with a fake
  microphone: the box filled correctly, $0.0002. A non-WAV upload returns HTTP 400.

## Step 6: README

- Rewrote `README.md`: what Sketchbridge does, a flow diagram, setup for macOS/Linux and Windows,
  all commands, typical costs, and a "Built during the hackathon" section listing every file,
  the 3 Meta models (with IDs and prices), and the dates: October 26 to November 4, 2026
  (commits from October 31 to November 1, 2026).

## Step 7: Explain-it-back check

- `pipeline.check_understanding(concept, analogy, mapping, explanation)`: one Muse Spark text call
  grades the learner's own explanation part by part (`got` / `partly` / `missed`), names any
  misconception, gives short feedback, and picks the most important gap. No image, about $0.004.
- `POST /check` in `main.py`. Guard: 10 checks per concept.
- Page: a "Check yourself: explain it back" panel under the picture, with its own 🎤 button
  (the voice code now fills whichever box it belongs to). The result lists every part with ✓ ~ ✗,
  shows the last try's score for comparison, and offers "Show me a scene about …", which reuses the
  `next_scene` follow-up aimed at the gap.
- Tests: in Chromium with the Meta calls mocked, including a model reply with a skipped index, a
  repeated index and a focus on a part already understood (the server corrects all three). The panel
  fits a 390 px phone screen. Not yet tested against the live API.

## Step 8: Deployment on Render, CI, and an access code

- Removed `deploy/huggingface/`: Docker Spaces are not free for this account.
- `render.yaml`: a Render Blueprint (free plan, Python 3.11, one worker, `/health` check). It deploys
  `main` only after CI passes (`autoDeployTrigger: checksPass`). `META_API_KEY` and `ACCESS_CODE` are
  entered in Render's dashboard.
- `.github/workflows/ci.yml` + `tests/test_app.py`: 8 offline tests (no key, no cost).
- Access code: `ACCESS_CODE` protects the routes that call Meta. The page asks for the code once, remembers
  it in that browser, and retries the request. Demos and pictures stay open. `GET /health` added.
- Tests: all 8 pass locally. In Chromium with the Meta calls mocked: demos load with no code; a paid action
  shows the code form; a wrong code is refused with a clear message; the right code goes through and is
  remembered after a reload; Cancel shows a message and leaves the page usable.
- Not tested: a real deploy on Render, and the workflow running on GitHub (it runs on the next push).

## Step 9: Progress bar and connect the dots

- Progress: the pipeline reports stages through a `progress` callback; `/explain` and `/followup` stream
  them as JSON lines when asked. The page shows a toast at the bottom (stage, bar, stage chips, seconds)
  for every wait, including options, checks, connect and voice. The tab title shows the stage.
- Connect the dots: `pipeline.connect_dots` + `POST /connect`, numbered dots with an animated path and a
  walkthrough on the picture, links to matching close-ups, and next scenes that say how they follow on.
  `meta_client` can now pass `reasoning_effort`.
- Demos: `python -m app.build_demo --connect` added connect-the-dots to all 5 demos ($0.058).
- Tests: 12 offline tests pass (new: streamed stages and errors, connect-the-dots repair, `/connect`
  checks). Live in Chromium ($0.085): "How does a refrigerator keep food cold?" streamed analogy (20 s),
  drawing (17 s), check (21 s), redraw and recheck; next scene linked back to the first picture; connect
  placed 4 dots on the right objects and linked step 2 to its close-up. The demo walkthrough made 0 API
  calls. Fits a 390 px screen, no browser errors.
- Found: at default reasoning effort, connect on the backpropagation picture failed twice with HTTP 502
  after 30 s; low effort fixed it.

