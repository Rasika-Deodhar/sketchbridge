# Meta Model API details

Source: the official cookbook, github.com/meta-models/meta-model-cookbook
(recipes `01_api_fundamentals/04_structured_output`, `07_vision_input`,
`05_muse_image/01_image_api_fundamentals`, `06_muse_voice/01_voice_api_fundamentals`).
The docs site (dev.meta.ai / ai.developer.meta.com) was blocked in the build container,
so the cookbook was the source.

| Item | Value |
| --- | --- |
| Base URL | `https://api.meta.ai/v1` |
| Auth | header `Authorization: Bearer <key>` |
| Key | the cookbook names it `MODEL_API_KEY`; Sketchbridge reads `META_API_KEY` (project rule) |
| Text model | `muse-spark-1.3` on `POST /chat/completions` (OpenAI-compatible) |
| JSON output | `response_format: {"type": "json_schema", "json_schema": {"name", "schema"}}` |
| Image input | content part `{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}`, user messages only |
| Image model | `muse-image-1.0` on `POST /responses`, body `{"model", "input": "<prompt>"}` |
| Image output | `output` list; the item with `type == "image_generation_call"` has base64 `result` (WebP in the examples) |
| Reasoning effort | chat completions accept `reasoning_effort`: `minimal` < `low` < `medium` < `high` (cookbook recipe `06_reasoning_tokens`). Lower is faster and cheaper; used as `low` for connect the dots |
| Gateway time limit | a request that takes more than about 30 s returns HTTP 502 "upstream request failed" (seen on long vision answers) |
| Models listed by `GET /v1/models` (November 2026) | `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, Contributor variants, `muse-image-1.0`, `muse-wonder-1.0` (a text model), `sam-3.1` (segmentation), `muse-voice-transcribe-1.0`. No video model |
| Speech to text | `muse-voice-transcribe-1.0`, `POST /v1/asr/transcribe`, multipart: `request` (JSON: `model`, `mode`, `audioEncoding: "WAV"`) + `audio` (mono 16-bit WAV, 16 or 24 kHz); reply has `transcript` and `audioDurationMs`. Limits: 10 min / 32 MB |

## Prices used for cost estimates

| Model | Price |
| --- | --- |
| Muse Spark 1.3 | $1.25 per 1M input, $0.15 per 1M cached input, $4.25 per 1M output |
| Muse Image 1.0 | $0.01 per image |
| Muse Voice Transcribe | $0.18 per hour |
