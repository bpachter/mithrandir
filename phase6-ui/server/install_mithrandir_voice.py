"""
install_mithrandir_voice.py — Install the ElevenLabs reference clip as the Mithrandir F5-TTS voice.

Usage:
    python install_mithrandir_voice.py <path_to_clip.mp3_or_wav>

What it does:
    1. Converts and resamples to 24 kHz mono WAV (F5-TTS requirement)
    2. Saves to voices/mithrandir.wav
    3. Runs Whisper to transcribe → voices/mithrandir.txt (prevents F5 stalls)
    4. Prints instructions to activate the voice

Then update .env:
    MITHRANDIR_DEFAULT_VOICE=mithrandir
    MITHRANDIR_FORCE_VOICE_PROFILE=mithrandir
and restart the server.
"""

import argparse
import sys
from pathlib import Path

_HERE       = Path(__file__).parent
_VOICES_DIR = _HERE / "voices"


def convert_to_wav(src: Path, dst: Path) -> None:
    import subprocess, shutil
    dst.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
    if not Path(ffmpeg).exists() and not shutil.which("ffmpeg"):
        # Fallback: try librosa/soundfile
        import librosa, soundfile as sf, numpy as np
        audio, sr = librosa.load(str(src), sr=24000, mono=True)
        sf.write(str(dst), audio, 24000, subtype="PCM_16")
        return
    subprocess.run(
        [ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(dst)],
        check=True, capture_output=True,
    )


def transcribe(wav_path: Path) -> str:
    import numpy as np, soundfile as sf
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed — skipping transcript (F5 will auto-transcribe, slower)")
        return ""
    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    try:
        model = WhisperModel("base.en", device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", help="Path to the ElevenLabs voice sample (mp3 or wav)")
    args = ap.parse_args()

    src = Path(args.clip).resolve()
    if not src.exists():
        sys.exit(f"File not found: {src}")

    out_wav = _VOICES_DIR / "mithrandir.wav"
    out_txt = _VOICES_DIR / "mithrandir.txt"

    print(f"Converting {src.name} → {out_wav}…")
    convert_to_wav(src, out_wav)
    print(f"  {out_wav.stat().st_size:,} bytes written")

    print("Transcribing reference clip with Whisper…")
    text = transcribe(out_wav)
    if text:
        out_txt.write_text(text + "\n", encoding="utf-8")
        print(f"  Transcript: {text[:100]}")
    else:
        print("  (no transcript written — F5 will auto-transcribe on first use)")

    print()
    print("=" * 60)
    print("Mithrandir voice reference installed.")
    print()
    print("To activate Layer 2 (F5-TTS cloning), update .env:")
    print("  MITHRANDIR_DEFAULT_VOICE=mithrandir")
    print("  MITHRANDIR_FORCE_VOICE_PROFILE=mithrandir")
    print("  MITHRANDIR_PREWARM_F5=1")
    print()
    print("Then restart the Mithrandir server.")
    print("=" * 60)


if __name__ == "__main__":
    main()
