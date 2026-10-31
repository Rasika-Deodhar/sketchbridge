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
