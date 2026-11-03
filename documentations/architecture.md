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

## Follow-ups (after the first picture)

The learner types anything, or presses a quick button. One Muse Spark call looks at the
current picture plus the message and picks an action:

| Action | Trigger example | What happens | Images |
| --- | --- | --- | --- |
| answer | "why do the arrows go backwards?" | text answer that points at the picture | 0 |
| simplify | "I don't get it, simplify" | simpler text (keeps the core idea) + simpler picture | 1 |
| edit | "make the chef a robot" | the current picture is edited | 1 |
| next_scene | "show the next scene" | close-up of one mapping part not shown yet; builds a series | 1 |

New pictures send the current picture as a reference (`input_image`), so style and characters stay
the same across the series. The browser keeps the conversation state (analogy, mapping, current
image, shown parts, last messages) and sends it with each follow-up, so the server stores nothing.

## Explain it back (checking understanding)

Under the picture, the learner explains the idea in their own words (typed, or spoken through
`/transcribe`). One Muse Spark text call (`check_understanding`, medium reasoning effort, about $0.01, no image) grades the
explanation against the mapping:

| Field | Meaning |
| --- | --- |
| `parts` | one entry per mapping part, in mapping order: `got`, `partly` or `missed`, with a short note |
| `misconception` | a wrong idea the learner stated, such as taking the analogy literally ("" if none) |
| `feedback` | 2 to 3 encouraging sentences: what they got, then the one thing to fix |
| `focus_part` | the most important gap; the page offers a `next_scene` follow-up aimed at it |

The server rebuilds `parts` in mapping order, so a skipped or repeated index from the model cannot
misalign the page. The page shows the score of the previous try next to the new one, so the learner
sees progress. Guard: 10 checks per concept.

## Connect the dots (the whole picture)

After separate close-up scenes, learners can lose how the parts fit together. "Connect the dots" makes
one Muse Spark vision call (`connect_dots`, low reasoning effort, about $0.012, no new image) on the
current whole picture. This is "perception grounding", as in Meta's cookbook: for every mapping part it
returns where the part is in the picture (x, y on a 0..1000 grid), whether it is visible, and one
sentence on what happens there and how it leads to the next part, ordered the way the concept works.
It also returns a 2 to 3 sentence summary.

The page draws numbered dots joined by a path and plays a walkthrough (Back / Play / Next). A step whose
part already has a close-up from "Show the next scene" links to it ("See its close-up"). Next scenes
also start by saying how they follow from the previous one. Dots that land on top of each other are
nudged apart. The server keeps the model's order but drops unknown or repeated parts, appends skipped
ones, and clamps positions to the picture. The result is kept per picture, so replaying is free; the
5 demos ship with it.

## Progress

`/explain` and `/followup` report their stages through a `progress` callback in the pipeline
(`analogy`, `draw`, `check`, `redraw`, `recheck`; `plan`, `draw`). When the page sends
`Accept: application/x-ndjson`, the server runs the request on a thread and streams one JSON line per
stage, then the result (or an error with its HTTP status). Without that header the routes return plain
JSON, so the command line and tests are unchanged. The page shows a toast with the current stage, a
bar that eases through each stage's usual duration (measured live: about 20 s each for analogy,
drawing and check), and the seconds elapsed. The tab title shows the stage, and says "Ready" if the
learner switched tabs.

## Web routes (app/main.py)

| Route | Does |
| --- | --- |
| `GET /` | serves `web/index.html` |
| `POST /options` | step 0 |
| `POST /explain` | steps 1 to 3 (streams progress if asked) |
| `POST /followup` | answer / simplify / edit / next_scene (streams progress if asked) |
| `POST /connect` | connect the dots: each part's position and the walkthrough, in process order |
| `POST /check` | the learner's own explanation -> which mapping parts they got, misconception, feedback |
| `GET /image/{id}` | a picture from `cache/` (name checked against a strict pattern) |
| `GET /demos` | the 5 cached demos |
| `GET /health` | `{"ok": true}` for Render's health check (no API calls) |
| `POST /transcribe` | a short WAV recording -> text (Muse Voice Transcribe) |
