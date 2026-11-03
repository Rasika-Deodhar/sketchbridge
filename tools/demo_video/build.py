"""Turn screencast frames into an MP4: each frame lasts until the next one, divided by the speed in force."""
import json, subprocess, sys
out = sys.argv[1]
data = json.load(open(f"{out}/frames.json"))
frames, marks = data["frames"], data["marks"]
end_t = marks[-1]["t"]

def factor_at(t):
    f = 1
    for m in marks:
        if m["t"] <= t:
            f = m["factor"]
    return f

lines, total = ["ffconcat version 1.0"], 0.0
for i, fr in enumerate(frames):
    nxt = frames[i + 1]["t"] if i + 1 < len(frames) else end_t
    # Split the gap at speed-change marks so a long frame is sped up only for its fast part.
    t, dur = fr["t"], 0.0
    cuts = sorted([m["t"] for m in marks if fr["t"] < m["t"] < nxt]) + [nxt]
    for c in cuts:
        dur += max(0.0, c - t) / factor_at(t)
        t = c
    dur = max(dur, 0.001)
    total += dur
    lines += [f"file '{fr['file']}'", f"duration {dur:.4f}"]
lines.append(f"file '{frames[-1]['file']}'")
open(f"{out}/list.txt", "w").write("\n".join(lines) + "\n")
print(f"{len(frames)} frames, {total:.1f} s")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{out}/list.txt",
                "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-movflags", "+faststart", f"{out}/sketchbridge-demo.mp4"],
               check=True)
