# Deployment

Sketchbridge is one FastAPI server. Any host that runs Python or Docker can run it.
The only secret is `META_API_KEY`. Set it in the host's settings, never in the code.

| | Render (free) | Hugging Face Spaces (free CPU) |
| --- | --- | --- |
| Link stays live | no end date | no end date |
| Sleeps after | 15 min without visitors | 48 h without visitors |
| Wake-up | about 1 minute | about 1 to 2 minutes |
| New code | redeploys on every push to `main` | press "Factory rebuild" |
| Generated pictures | lost on sleep / restart (demos are safe in git) | lost on restart (demos are safe in git) |

Always run **one worker**: the cost limits are counted in memory.

## Render

1. render.com -> New -> Web Service -> repo `Rasika-Deodhar/sketchbridge`, branch `main`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
4. Environment: add `META_API_KEY`.

## Hugging Face Spaces

The Space holds only two files from `deploy/huggingface/`. Its Dockerfile downloads this GitHub repo's
`main` branch at build time, so nothing needs to be copied by hand when the app changes.

1. huggingface.co -> New Space -> name `sketchbridge`, SDK **Docker**, template **Blank**, hardware
   **CPU basic (free)**, visibility Public.
2. In the Space: Files -> Add file -> Create a new file. Create `Dockerfile` and paste
   `deploy/huggingface/Dockerfile`. Then open the Space's existing `README.md`, replace all of it with
   `deploy/huggingface/README.md`, and commit. The README's top block (`sdk: docker`, `app_port: 7860`)
   tells Hugging Face how to run it.
3. Settings -> Variables and secrets -> New secret: `META_API_KEY` = your key.
4. The Space builds (a few minutes) and opens at `https://huggingface.co/spaces/<you>/sketchbridge`.
5. After new commits on GitHub `main`: Settings -> Factory rebuild.

Tested in Docker in the build container: the image builds; the app runs as user 1000 on port 7860;
the page, the 5 demos and the demo pictures load; the app can write new pictures to `cache/`; and a
live `/options` call works.

## Before sharing a public link

There is no login yet, so anyone with the link can spend the Meta API credit behind `META_API_KEY`.
The ready-made examples cost nothing; everything else calls the API (about 3 to 5 cents per picture).
Consider an access code and a daily spending cap before sharing widely.
