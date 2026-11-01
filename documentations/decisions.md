# Decisions

1. **Only Meta-hosted models.** No local models, weights, or GPUs. Everything goes through `api.meta.ai`.
2. **`httpx` instead of the OpenAI SDK.** The cookbook uses the OpenAI SDK, but the project allows only
   `fastapi`, `uvicorn`, and `httpx`. The API is plain JSON over HTTPS, so `httpx` is enough.
3. **One file talks to Meta** (`meta_client.py`). This keeps the key handling and API details in one place.
4. **Key from `META_API_KEY`.** It is read from the environment, or from a local `.env` file that git ignores.
   It is never printed or logged.
5. **Default to `muse-spark-1.3`, not the Contributor variant.** Meta trains on Contributor inputs and outputs.
6. **Structured JSON output** (`response_format` with a JSON schema), so replies always parse.
7. **`store: false` on image calls.** We never chain image turns, so the server does not need to keep state.
8. **Cost is computed from each reply's `usage`** (text) or a flat $0.01 (image), and returned with every call.
9. **The app assigns option ids "1", "2", "3"** instead of trusting the model's ids, so the buttons and
   the command line always match.
10. **"Try another" sends the domains already shown**, so new options don't repeat them.
11. **Redraw prompt = original prompt + the reviewer's fixes.** We never send the old image back;
    one fresh draw keeps it simple and inside the 2-image cap.
12. **Cost guard lives in the pipeline** (`Budget`), so the command line and the web app share it.
    The option-round counter is in memory, so it resets when the app restarts. That's enough for a demo.
13. **If the second picture still fails the check, we return it anyway** with `pass: false` and the fixes,
    instead of drawing a third time.
14. **Retry a failed draw once.** A failed call returns no image and is not billed, so the 2-image cap
    counts images actually made. Worst case is 4 draw calls per request (2 images + 2 failed calls).
15. **The check judges like a teacher, not a perfectionist.** It passes if the core idea and most mapped
    parts are visible. Time and repetition can't be shown in one still picture.
16. **`META_API_KEY` is optional in code.** In a cloud session the key can be a network secret that the
    proxy adds to requests, so the key never reaches the app at all.
17. **Domain field drives the options.** If the learner gives a domain (e.g. "Restaurant"), all 3 options
    are set in that world, each with a different scene. With no domain, the 3 options come from different
    everyday domains. This follows the user's design, and differs from the original brief.
18. **One follow-up box, the model picks the action.** Learners say things like "I don't understand"
    instead of pressing the right button, so Muse Spark routes the message to answer / simplify / edit /
    next_scene. Two quick buttons force simplify or next_scene.
19. **Follow-up pictures use the current picture as a reference** (`input_image`, from the cookbook), so a
    series keeps the same style and characters. Follow-up pictures are not self-checked, to save cost.
20. **Simplify must keep the core idea.** The first live test lost "go backwards", so the prompt now says
    to drop details, never the key mechanism.
21. **Stateless server.** The browser sends the conversation state with each follow-up. There are no
    sessions to store or expire. Inputs are length-limited with pydantic, and image ids must match
    `^[a-z0-9-]+\.(webp|png|jpg)$`, so no path tricks.
22. **Follow-ups are capped at 15 per concept** (each makes at most 1 picture).
23. **Demo files are committed** (`cache/demos.json`, `cache/demo-*.webp`, about 3.7 MB), so a fresh clone
    can show the demo with no key and no waiting. Other generated pictures stay git-ignored.
24. **Demos store one follow-up (simplify)**, because "I don't understand" is the main moment in the demo
    story. Other follow-ups on a demo still run live.
25. **One-shot transcription, not the streaming WebSocket.** Questions are a few seconds long, so one HTTP
    request after recording is simpler than streaming and needs no extra library.
26. **Convert audio to WAV in the browser.** Browsers record compressed audio (webm/opus), but the API
    wants mono 16-bit WAV. The page decodes and resamples with the Web Audio API, so the server needs no
    ffmpeg and no extra Python packages.
27. **Voice fills the question box but does not submit it.** The learner can fix a misheard word first.
