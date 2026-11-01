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
