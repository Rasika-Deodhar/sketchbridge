# Sketchbridge

Explain a concept with a picture analogy, drawn and checked by Meta's hosted models.

Work in progress. See [documentations/](documentations/).

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then put your key after META_API_KEY=
.venv/bin/python -m app.smoke_test                              # step 1: check the API works
.venv/bin/python -m app.run "backpropagation" --interest "cooking"  # step 2: full pipeline
.venv/bin/uvicorn app.main:app                                  # step 3: web app at http://127.0.0.1:8000
.venv/bin/python -m app.build_demo                              # step 4: (re)build the 5 cached demos
```

The 5 demo examples are already in `cache/`, so the web app shows them instantly even without a key.

On Windows use `.venv\Scripts\python` instead of `.venv/bin/python`.
