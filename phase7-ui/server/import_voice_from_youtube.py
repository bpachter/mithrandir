"""
import_voice_from_youtube.py — turn a YouTube clip into a voice profile.

Usage:
    python import_voice_from_youtube.py <youtube_url> <profile_name> [--start SS] [--duration SS]

What it does:
    1. Downloads the audio with yt-dlp (best audio, m4a/webm).
    2. Extracts a clean ~10-15 s segment with ffmpeg.
    3. Converts to mono 24 kHz PCM16 WAV \u2014 the format F5-TTS likes best.
    4. Saves to phase7-ui/server/voices/<profile_name>.wav.
    5. Optionally writes a sidecar <profile_name>.txt transcript (Whisper)
       so F5-TTS can clone reliably without auto-transcription stalls.

Requirements:
    pip install yt-dlp
    ffmpeg on PATH (set FFMPEG_DIR in .env if not)
    faster-whisper (already installed for STT)

Example \u2014 BMO clip from the Adventure Time compilation (known clean segment):
    python import_voice_from_youtube.py https://www.youtube.com/watch?v=l1wxMWy0WjI bmo --start 81 --duration 6

Tip: use scan_bmo_voice.py to auto-detect the best segment if you don't know the timestamp.

Tip: pick a segment with ONLY the target voice \u2014 no music, no sound effects,
no other characters. ~10-15 seconds is the sweet spot for F5-TTS.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE       = Path(__file__).parent
_VOICES_DIR = _HERE / "voices"

_FFMPEG_DIR = os.environ.get(
    "FFMPEG_DIR",
    r"C:\ffmpeg\bin\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin",
)
if os.path.isdir(_FFMPEG_DIR) and _FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run(cmd: list[str]) -> None:
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def download_audio(url: str, out_dir: Path) -> Path:
    if _which("yt-dlp") is None:
        raise SystemExit("yt-dlp not found. Install with: pip install yt-dlp")
    out_tpl = str(out_dir / "raw.%(ext)s")
    _run(["yt-dlp", "-x", "--audio-format", "wav", "-o", out_tpl, url])
    for p in out_dir.iterdir():
        if p.stem == "raw" and p.suffix == ".wav":
            return p
    raise RuntimeError("yt-dlp completed but no raw.wav found")


def slice_clip(src: Path, start: float, duration: float, dst: Path) -> None:
    if _which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH (set FFMPEG_DIR in .env).")
    _run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t",  f"{duration:.3f}",
        "-ac", "1",
        "-ar", "24000",
        "-sample_fmt", "s16",
        str(dst),
    ])


def transcribe(wav_path: Path) -> str:
    try:
        import numpy as np
        import soundfile as sf
        from faster_whisper import WhisperModel
    except ImportError as e:
        print(f"(skipping transcript: {e})")
        return ""
    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)
    try:
        model = WhisperModel("base.en", device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a voice profile from a YouTube clip.")
    ap.add_argument("url")
    ap.add_argument("profile")
    ap.add_argument("--start",    type=float, default=0.0,  help="start time in seconds")
    ap.add_argument("--duration", type=float, default=12.0, help="clip length in seconds (10-15 ideal)")
    ap.add_argument("--no-transcript", action="store_true", help="skip whisper transcript")
    args = ap.parse_args()

    _VOICES_DIR.mkdir(parents=True, exist_ok=True)
    out_wav = _VOICES_DIR / f"{args.profile}.wav"
    out_txt = _VOICES_DIR / f"{args.profile}.txt"

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        raw = download_audio(args.url, td_path)
        slice_clip(raw, args.start, args.duration, out_wav)

    print(f"\nWrote {out_wav} ({out_wav.stat().st_size:,} bytes)")
    if not args.no_transcript:
        text = transcribe(out_wav)
        if text:
            out_txt.write_text(text + "\n", encoding="utf-8")
            print(f"Wrote {out_txt}: {text[:120]}...")
    print("\nDone. Restart the server and select the profile in the UI.")


if __name__ == "__main__":
    main()
