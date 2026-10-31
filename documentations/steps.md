# Build log

## Step 1: Smoke test (meta_client.py)

- Read the official cookbook to confirm the endpoint, auth, model IDs, vision format, and image output.
- Wrote `app/meta_client.py` with `chat`, `chat_with_image`, and `draw`.
- Wrote `app/smoke_test.py`: 1 text call, 1 drawing, 1 vision call on that drawing (about $0.01 to $0.02).
- Status: the code runs and fails cleanly. The build container had no `META_API_KEY`, and its network
  policy blocked `api.meta.ai`, so no live call was made yet.
