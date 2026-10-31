# Architecture

Sketchbridge turns a hard concept into a picture analogy. The user picks the
analogy, Sketchbridge draws it, then checks its own drawing.

## Layers

```
web/index.html  ──HTTP──▶  app/main.py (FastAPI)  ─┐
                                                   ├─▶ app/pipeline.py ─▶ app/meta_client.py ─▶ Meta Model API
command line    ────────▶  app/run.py  ────────────┘
```

- **meta_client.py**: the only file that talks to Meta. Three functions:
  `chat`, `chat_with_image`, and `draw`. Each returns a `Reply` with the result and its cost.
- **pipeline.py**: plain functions called in order (options, analogy, draw, check). No framework.
- **run.py / main.py**: two front doors (command line and web) to the same pipeline.

## Pipeline

| Step | Model | In | Out |
| --- | --- | --- | --- |
| 0 Options | Muse Spark 1.3 | concept, interest | 3 options (`id`, `domain`, `one_line`) |
| 1 Analogy | Muse Spark 1.3 | concept, chosen option | `analogy`, `mapping`, `image_prompt` |
| 2 Draw | Muse Image 1.0 | `image_prompt` | image file in `cache/` |
| 3 Check | Muse Spark 1.3 (vision) | image, `mapping` | `pass`, `fixes`; if it fails, redraw once |

Hard limit: at most 2 images per request.
