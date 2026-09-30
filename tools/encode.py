#!/usr/bin/env python3
"""Turns reel specs (*.reel.json) into Instagram-ready MP4s (H.264 + AAC, 1080x1920, 30fps).

A spec looks like:
{
  "output": "ageniusbillionair/2026-10/some-reel.mp4",
  "duration": 8,
  "base": {"webm": "ageniusbillionair/2026-10/some-reel.webm"}      # rendered animation
       or {"url": "https://cdn.pixabay.com/video/...mp4", "start": 0}  # stock footage
  "overlays": [{"png": "ageniusbillionair/2026-10/some-reel-1.png", "from": 0, "to": 3}]
}
Paths are relative to the repo root. Only Pixabay's CDN is allowed as a remote source.
"""
import json, pathlib, subprocess, sys, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED_HOSTS = {"cdn.pixabay.com"}
W, H, FPS = 1080, 1920, 30


def local(rel):
    p = (ROOT / rel).resolve()
    if ROOT not in p.parents:
        raise ValueError(f"path escapes repo: {rel}")
    return p


def fetch(url, dest):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"source not allowed: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "agenius-media-encoder"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def encode(spec_path):
    spec = json.loads(spec_path.read_text())
    out = local(spec["output"])
    if out.exists():
        return None
    duration = float(spec.get("duration", 10))
    base = spec["base"]
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if "webm" in base:
        args += ["-i", str(local(base["webm"]))]
    else:
        src = fetch(base["url"], "/tmp/source.mp4")
        args += ["-ss", str(float(base.get("start", 0))), "-i", src]
    overlays = spec.get("overlays", [])
    for o in overlays:
        args += ["-loop", "1", "-i", str(local(o["png"]))]
    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]

    grade = "" if "webm" in base else ",eq=saturation=0.92:contrast=1.04"
    chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}{grade},format=yuv420p[v0]"]
    last = "v0"
    for i, o in enumerate(overlays, start=1):
        a, b = float(o.get("from", 0)), float(o.get("to", duration))
        fade = min(0.4, (b - a) / 4)
        chain.append(
            f"[{i}:v]format=rgba,fade=t=in:st={a}:d={fade}:alpha=1,fade=t=out:st={b - fade}:d={fade}:alpha=1[o{i}]"
        )
        chain.append(f"[{last}][o{i}]overlay=0:0:enable='between(t,{a},{b})'[v{i}]")
        last = f"v{i}"
    audio_idx = 1 + len(overlays)
    args += [
        "-filter_complex", ";".join(chain),
        "-map", f"[{last}]", "-map", f"{audio_idx}:a",
        "-t", str(duration),
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", str(out),
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(args, check=True)
    return out


def main():
    made = []
    for spec in sorted(ROOT.rglob("*.reel.json")):
        try:
            out = encode(spec)
            if out:
                made.append(out)
                print(f"encoded {out.relative_to(ROOT)}")
        except Exception as e:  # keep going so one bad spec doesn't block the rest
            print(f"failed {spec.relative_to(ROOT)}: {e}", file=sys.stderr)
            (spec.with_suffix(".error.txt")).write_text(str(e) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
