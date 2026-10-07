#!/usr/bin/env python3
"""Turns reel specs (*.reel.json) into Instagram-ready MP4s (H.264 + AAC, 1080x1920, 30fps).

A spec looks like:
{
  "output": "ageniusbillionair/2026-10/some-reel.mp4",
  "duration": 8,
  "base": {"webm": "ageniusbillionair/2026-10/some-reel.webm"}      # rendered animation
       or {"url": "https://cdn.pixabay.com/video/...mp4", "start": 0}  # stock footage
  "overlays": [{"png": "ageniusbillionair/2026-10/some-reel-1.png", "from": 0, "to": 3}],
  "audio": {                                                          # optional; silent without it
    "voice": {"text": "Spoken script.", "voice": "en-US-AndrewMultilingualNeural", "rate": "-4%", "delay": 0.6},
    "music": {"mood": "calm"}            # generated bed (calm | bright), or
          or {"path": "music/track.mp3"} # a track in this repo, or {"library": "music/calm"} to pick one
          or {"url": "https://cdn.pixabay.com/audio/...mp3"}
  }
}
Paths are relative to the repo root. Only Pixabay's CDN is allowed as a remote source.
The voice-over is spoken by edge-tts (Microsoft neural voices). If the voice is longer than
the video, the last frame is held until it has finished.
"""
import hashlib, json, pathlib, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

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


# Chords for the generated music bed, in Hz. Each chord fades into the next.
MOODS = {
    "calm": [  # Am9, Fmaj7, Cmaj7, G6
        [110.0, 164.81, 196.0, 246.94, 261.63],
        [87.31, 130.81, 164.81, 220.0, 261.63],
        [65.41, 130.81, 196.0, 246.94, 329.63],
        [98.0, 146.83, 196.0, 246.94, 293.66],
    ],
    "bright": [  # Cmaj9, G6, Am7, Fmaj7
        [65.41, 130.81, 196.0, 246.94, 293.66],
        [98.0, 146.83, 196.0, 246.94, 329.63],
        [110.0, 164.81, 196.0, 261.63, 329.63],
        [87.31, 130.81, 164.81, 220.0, 329.63],
    ],
}
CHORD_SECONDS = 4.0
VOICE_TAIL = 1.2  # seconds of music after the last word


def run(args):
    subprocess.run(args, check=True)


def media_seconds(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def bed_expr(chords, detune):
    """A soft pad: each chord is a few sines with a quiet octave, cross-faded with cos^2
    windows that always sum to 1, plus a gentle arpeggio that plucks the chord's notes."""
    L, n = CHORD_SECONDS, len(chords)
    period = L * n
    terms = []
    for k, notes in enumerate(chords):
        weight = f"pow(max(0,cos(2*PI*(t-{k * L})/{period})),2)" if n == 4 else "1"
        pad = "+".join(
            f"{1 / (1 + i * 0.35):.3f}*(sin(2*PI*{f * detune:.3f}*t)+0.25*sin(4*PI*{f * detune:.3f}*t))"
            for i, f in enumerate(notes)
        )
        arp_notes = sorted(notes)[-4:]
        arp = "+".join(
            f"eq(mod(floor(t*2),4),{j})*sin(4*PI*{f * detune:.3f}*t)" for j, f in enumerate(arp_notes)
        )
        pluck = "(1-exp(-120*mod(t,0.5)))*exp(-5*mod(t,0.5))"
        terms.append(f"{weight}*(({pad})+0.9*{pluck}*({arp}))")
    return "0.05*(1+0.12*sin(2*PI*0.11*t))*(" + "+".join(terms) + ")"


def generated_bed(mood, seconds, dest):
    chords = MOODS.get(mood, MOODS["calm"])
    exprs = f"{bed_expr(chords, 0.999)}|{bed_expr(chords, 1.001)}"
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"aevalsrc=exprs='{exprs}':s=48000:d={seconds:.2f}",
        "-af", "lowpass=f=2400,aecho=0.8:0.6:70|140|280:0.3|0.2|0.12,loudnorm=I=-20:TP=-3",
        "-ar", "48000", "-ac", "2", str(dest),
    ])
    return dest


def pick_music(music, seconds, tmp):
    """Returns (path, loop) for the music bed."""
    if "path" in music:
        return local(music["path"]), True
    if "url" in music:
        ext = pathlib.Path(urllib.parse.urlparse(music["url"]).path).suffix or ".mp3"
        return fetch(music["url"], str(tmp / f"music{ext}")), True
    if "library" in music:
        tracks = sorted(
            p for p in local(music["library"]).glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg"}
        ) if local(music["library"]).is_dir() else []
        if tracks:
            seed = int(hashlib.sha1(music.get("seed", "").encode()).hexdigest(), 16)
            return tracks[seed % len(tracks)], True
    return generated_bed(music.get("mood", "calm"), seconds, tmp / "bed.wav"), False


def speak(voice, dest):
    """Neural text-to-speech with edge-tts. Returns the file, or None if it failed."""
    exe = shutil.which("edge-tts")
    if not exe:
        print("edge-tts is not installed; encoding without a voice-over", file=sys.stderr)
        return None
    try:
        run([
            exe, "--voice", voice.get("voice", "en-US-AndrewMultilingualNeural"),
            f"--rate={voice.get('rate', '+0%')}", "--text", voice["text"], "--write-media", str(dest),
        ])
        return dest if dest.exists() and dest.stat().st_size > 0 else None
    except Exception as e:
        print(f"voice-over failed ({e}); encoding without it", file=sys.stderr)
        return None


def encode(spec_path):
    spec = json.loads(spec_path.read_text())
    out = local(spec["output"])
    if out.exists():
        return None
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="reel-"))
    duration = float(spec.get("duration", 10))
    video_seconds = duration
    audio = spec.get("audio") or {}

    voice_file, delay = None, 0.0
    if audio.get("voice", {}).get("text"):
        delay = float(audio["voice"].get("delay", 0.6))
        voice_file = speak(audio["voice"], tmp / "voice.mp3")
        if voice_file:
            duration = max(duration, round(delay + media_seconds(voice_file) + VOICE_TAIL, 2))

    base = spec["base"]
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if "webm" in base:
        args += ["-i", str(local(base["webm"]))]
    else:
        src = fetch(base["url"], str(tmp / "source.mp4"))
        args += ["-ss", str(float(base.get("start", 0))), "-i", src]
    overlays = spec.get("overlays", [])
    for o in overlays:
        args += ["-loop", "1", "-i", str(local(o["png"]))]

    audio_inputs = []
    if voice_file:
        args += ["-i", str(voice_file)]
        audio_inputs.append("voice")
    if "music" in audio:
        music, loop = pick_music(audio["music"], duration, tmp)
        args += (["-stream_loop", "-1"] if loop else []) + ["-i", str(music)]
        audio_inputs.append("music")
    if not audio_inputs:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]

    grade = "" if "webm" in base else ",eq=saturation=0.92:contrast=1.04"
    # Hold the last frame if the voice-over runs past the rendered video.
    hold = f",tpad=stop_mode=clone:stop_duration={duration - video_seconds + 1:.2f}" if duration > video_seconds else ""
    chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}{grade}{hold},format=yuv420p[v0]"]
    last = "v0"
    for i, o in enumerate(overlays, start=1):
        a, b = float(o.get("from", 0)), float(o.get("to", video_seconds))
        if b >= video_seconds:
            b = duration  # layers that lasted to the end still do
        fade = min(0.4, (b - a) / 4)
        chain.append(
            f"[{i}:v]format=rgba,fade=t=in:st={a}:d={fade}:alpha=1,fade=t=out:st={b - fade}:d={fade}:alpha=1[o{i}]"
        )
        chain.append(f"[{last}][o{i}]overlay=0:0:enable='between(t,{a},{b})'[v{i}]")
        last = f"v{i}"
    first_audio = 1 + len(overlays)
    chain += audio_chain(audio_inputs, first_audio, delay, duration)
    args += [
        "-filter_complex", ";".join(chain),
        "-map", f"[{last}]", "-map", "[aout]",
        "-t", str(duration),
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", str(out),
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    run(args)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def audio_chain(inputs, first, delay, duration):
    """Voice up front at -16 LUFS; music underneath, ducking while the voice speaks."""
    fade_out = f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5"
    if not inputs:
        return [f"[{first}:a]anull[aout]"]
    idx = {name: first + i for i, name in enumerate(inputs)}
    chain = []
    if "voice" in idx:
        ms = int(delay * 1000)
        chain.append(
            f"[{idx['voice']}:a]aresample=48000,aformat=channel_layouts=stereo,highpass=f=70,"
            f"acompressor=threshold=0.1:ratio=3:attack=10:release=200,loudnorm=I=-16:TP=-2,"
            f"adelay={ms}|{ms},apad[vo]"
        )
    if "music" in idx:
        level = "-11dB" if "voice" in idx else "+3dB"
        chain.append(
            f"[{idx['music']}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"afade=t=in:d=1.2,volume={level}[mus]"
        )
    if "voice" in idx and "music" in idx:
        chain += [
            "[vo]asplit=2[vo1][vokey]",
            "[mus][vokey]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=500[duck]",
            f"[vo1][duck]amix=inputs=2:normalize=0:duration=first,{fade_out},alimiter=limit=0.9[aout]",
        ]
    else:
        only = "vo" if "voice" in idx else "mus"
        chain.append(f"[{only}]{fade_out},alimiter=limit=0.9[aout]")
    return chain


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
