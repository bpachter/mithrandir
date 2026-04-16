"""
phase7-ui/server/voice.py — Speech-to-text + text-to-speech for Enkidu

STT: faster-whisper (base.en, CUDA float16 → CPU int8 fallback)
TTS: edge-tts  (en-US-GuyNeural, Microsoft neural voice)
"""

import asyncio
import logging
import math
from typing import Optional

import numpy as np

logger = logging.getLogger("enkidu.voice")

# ---------------------------------------------------------------------------
# STT — faster-whisper
# ---------------------------------------------------------------------------

_WHISPER_MODEL_SIZE = "small.en"  # English-only, ~244 MB — noticeably better than base
_whisper: Optional[object] = None


def _load_whisper():
    global _whisper
    if _whisper is not None:
        return _whisper
    try:
        from faster_whisper import WhisperModel
        logger.info(f"Loading Whisper '{_WHISPER_MODEL_SIZE}' on CUDA (float16)…")
        _whisper = WhisperModel(
            _WHISPER_MODEL_SIZE,
            device="cuda",
            compute_type="float16",
        )
        logger.info("Whisper ready (CUDA).")
    except Exception as e:
        logger.warning(f"CUDA Whisper failed ({e}), falling back to CPU…")
        try:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info("Whisper ready (CPU).")
        except Exception as e2:
            logger.error(f"Whisper unavailable: {e2}")
            _whisper = None
    return _whisper


def _resample(audio: np.ndarray, orig_rate: int, target_rate: int = 16000) -> np.ndarray:
    """Simple linear-interpolation resample — good enough for speech."""
    if orig_rate == target_rate:
        return audio
    try:
        from scipy.signal import resample_poly
        g = math.gcd(orig_rate, target_rate)
        return resample_poly(audio, target_rate // g, orig_rate // g).astype(np.float32)
    except ImportError:
        n_out = int(len(audio) * target_rate / orig_rate)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)


def transcribe(raw_bytes: bytes, sample_rate: int = 16000) -> str:
    """
    Transcribe raw float32 PCM bytes to text.

    raw_bytes:   little-endian float32 samples from the browser Web Audio API
    sample_rate: sample rate reported by the browser AudioContext (default 16000)
    """
    model = _load_whisper()
    if model is None:
        return ""
    try:
        audio = np.frombuffer(raw_bytes, dtype=np.float32).copy()
        if sample_rate != 16000:
            audio = _resample(audio, sample_rate)
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,       # skip silence
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""


# ---------------------------------------------------------------------------
# TTS — edge-tts
# ---------------------------------------------------------------------------

_TTS_VOICE = "en-US-BrianNeural"  # deep, natural Microsoft neural voice


async def synthesize(text: str) -> bytes:
    """Return MP3 bytes for the given text using edge-tts neural voices."""
    if not text.strip():
        return b""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, _TTS_VOICE)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}")
        return b""
