# Sketchbridge

Explain a concept with a picture analogy, drawn and checked by Meta's hosted models.

Work in progress. See [documentations/](documentations/).

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then put your key after META_API_KEY=
.venv/bin/python -m app.smoke_test                              # step 1: check the API works
.venv/bin/python -m app.run "backpropagation" --interest "cooking"  # step 2: full pipeline
```

On Windows use `.venv\Scripts\python` instead of `.venv/bin/python`.
