# Demo video

Records the real app in Chromium and turns it into `sketchbridge-demo.mp4` (1920x1080, about 2 minutes).
It uses the ready-made backpropagation example, plus two live calls (a next scene and an explain-it-back
check, about $0.03) so the progress bar and grading are real. Waits for those calls are sped up and
marked "sped up" on screen. Captions, a cursor dot and title cards are drawn over the page while recording.

Needs Node.js with Playwright (and its Chromium), ffmpeg, and a working `META_API_KEY`.

```bash
uvicorn app.main:app --port 8769
```

In a second terminal (`out/` can be any empty folder):

```bash
node tools/demo_video/record.js out
```

```bash
python tools/demo_video/build.py out
```

The video is `out/sketchbridge-demo.mp4`. Edit the captions and timing in `record.js`.
Leave `ACCESS_CODE` empty for the recording server, or the paid steps will ask for the code.
