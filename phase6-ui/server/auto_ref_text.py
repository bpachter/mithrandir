"""
phase6-ui/server/auto_ref_text.py — Auto-generate <profile>.txt from <profile>.wav

F5-TTS voice cloning needs a transcript of the reference clip. If voices/bmo.txt
is missing or stale, F5 has to auto-transcribe live, which adds 2-3 s on first
call and occasionally hallucinates phrases ("surprise!") that bleed into output.

This module fills the .txt on demand using whichever ASR is available:
preference order Parakeet → faster-whisper → no-op.

Usage from voice.py / startup:
    from auto_ref_text import ensure_ref_text
    ensure_ref_text(Path("voices/bmo.wav"))
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mithrandir.voice.auto_ref")

# Hard cap so a long source clip can't produce a 200-word ref transcript that
# F5 then leaks into generated audio. Keep ref text short and neutral.
_MAX_CHARS = 180


def _read_audio(wav_path: Path):
    """Load a wav file as (float32 mono, sample_rate)."""
    import numpy as np
    import soundfile as sf  # type: ignore

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)
    return audio, int(sr)


def _transcribe_parakeet(wav_path: Path) -> Optional[str]:
    try:
        import parakeet_asr  # type: ignore

        if not parakeet_asr.is_available():
            return None
        text = parakeet_asr.transcribe_file(str(wav_path))
        return text or None
    except Exception as e:
        logger.debug(f"Parakeet ref-text fallback: {e!r}")
        return None


def _transcribe_whisper(wav_path: Path) -> Optional[str]:
    try:
        # Reuse the already-loaded faster-whisper model in voice.py if possible.
        import voice as _voice  # type: ignore

        loader = getattr(_voice, "_load_whisper", None)
        if loader is None:
            return None
        model = loader()
        if model is None:
            return None
        audio, sr = _read_audio(wav_path)
        if sr != 16000:
            from scipy.signal import resample_poly  # type: ignore
            import math

            g = math.gcd(sr, 16000)
            audio = resample_poly(audio, 16000 // g, sr // g)
        segments, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text or None
    except Exception as e:
        logger.debug(f"Whisper ref-text fallback: {e!r}")
        return None


def _normalise(text: str) -> str:
    """Trim, collapse whitespace, cap length, and ensure a terminal period."""
    import re

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_CHARS:
        # Trim at last sentence boundary that fits, else hard cut.
        cut = text.rfind(".", 0, _MAX_CHARS)
        text = text[: cut + 1] if cut > 30 else text[:_MAX_CHARS].rstrip() + "."
    if text and text[-1] not in ".!?":
        text += "."
    return text


def ensure_ref_text(wav_path: Path, force: bool = False) -> Optional[Path]:
    """Generate <stem>.txt next to <stem>.wav if missing.

    Returns the path to the .txt on success, None if no ASR was available
    or if the file operations failed.
    """
    try:
        wav_path = Path(wav_path)
        if not wav_path.exists():
            return None
        txt_path = wav_path.with_suffix(".txt")
        if txt_path.exists() and not force:
            return txt_path

        text = _transcribe_parakeet(wav_path) or _transcribe_whisper(wav_path)
        if not text:
            logger.debug(f"No ASR available for {wav_path.name}")
            return None
        text = _normalise(text)
        if not text:
            return None
        txt_path.write_text(text, encoding="utf-8")
        logger.info(f"Auto-generated ref text for {wav_path.name}: {text[:60]}…")
        return txt_path
    except OSError as e:
        logger.warning(f"Could not write ref text for {wav_path.name}: {e!r}")
        return None
    except Exception as e:
        logger.error(f"ensure_ref_text error: {e!r}")
        return None
