"""
phase6-ui/server/voice.py — Speech-to-text + text-to-speech for Enkidu

STT: faster-whisper (base.en CUDA float16 -> CPU int8 fallback)

TTS priority:
    1. Kokoro (fast local neural TTS)
    2. edge-tts (cloud fallback)
    3. pyttsx3 SAPI5 (offline Windows fallback)

Voice cloning paths were intentionally removed from active runtime flow to
favor reliability, low latency, and lower GPU pressure.
"""

import asyncio
import io
import json as _json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Coroutine, Optional

import numpy as np

logger = logging.getLogger("enkidu.voice")

# ---------------------------------------------------------------------------
# Voice profile directory  (reference wavs used by F5-TTS / future Fish Speech)
# ---------------------------------------------------------------------------

_VOICES_DIR = Path(__file__).parent / "voices"

# Kokoro built-in voice IDs — these are the voices you can select in the UI.
# British voices need lang_code='b', American need lang_code='a'.
_KOKORO_BUILTIN = [
    "bm_george",    # British male  — deep, authoritative (default)
    "bm_lewis",     # British male  — warm, conversational
    "am_adam",      # American male — neutral
    "am_michael",   # American male — clear
    "af_heart",     # American female — warm
    "bf_emma",      # British female — crisp
    "bf_isabella",  # British female — soft
]

# Maps voice ID → Kokoro lang_code ('a' or 'b')
_KOKORO_LANG_MAP: dict[str, str] = {
    "bm_george": "b", "bm_lewis": "b", "bf_emma": "b", "bf_isabella": "b",
    "am_adam":   "a", "am_michael": "a", "af_heart": "a", "af_bella": "a",
    "af_sky":    "a", "af_nicole": "a",
}


def list_voices() -> list[str]:
    """Return available voice IDs (Kokoro built-ins only)."""
    return sorted(set(_KOKORO_BUILTIN))


def get_voice_path(profile_id: str) -> Optional[Path]:
    """Return path to reference wav for F5/Chatterbox, or None."""
    p = _VOICES_DIR / f"{profile_id}.wav"
    return p if p.exists() else None


# Active voice (Kokoro voice ID or wav profile name).
# ENKIDU_DEFAULT_VOICE lets .env pick a .wav profile (e.g. 'bmo') at startup.
_active_voice: str = os.environ.get(
    "ENKIDU_DEFAULT_VOICE",
    os.environ.get("KOKORO_VOICE", "bm_george"),
)


def get_active_voice() -> str:
    return _active_voice


def set_active_voice(profile_id: str) -> bool:
    """Set the active voice. Accepts Kokoro voice IDs or wav profile names."""
    global _active_voice
    all_ids = list_voices()
    if profile_id == "default":
        _active_voice = os.environ.get("KOKORO_VOICE", "af_heart")
        logger.info(f"Active voice reset to default: {_active_voice}")
        return True
    if profile_id in all_ids or get_voice_path(profile_id) is not None:
        _active_voice = profile_id
        logger.info(f"Active voice set to: {_active_voice}")
        return True
    logger.warning(f"Voice profile not found: {profile_id}")
    return False


# ---------------------------------------------------------------------------
# STT — faster-whisper
# ---------------------------------------------------------------------------

_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base.en")
_WHISPER_PROMPT = (
    "Enkidu is an AI assistant built by Ben Pachter. "
    "He runs locally on an NVIDIA RTX 4090 GPU."
)
_whisper: Optional[object] = None


def _load_whisper():
    global _whisper
    if _whisper is not None:
        return _whisper
    try:
        from faster_whisper import WhisperModel
        logger.info(f"Loading Whisper '{_WHISPER_MODEL_SIZE}' on CUDA (float16)…")
        _whisper = WhisperModel(_WHISPER_MODEL_SIZE, device="cuda", compute_type="float16")
        logger.info("Whisper ready (CUDA).")
    except Exception as e:
        logger.warning(f"CUDA Whisper failed ({e}), falling back to CPU…")
        try:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info("Whisper ready (CPU).")
        except Exception as e2:
            logger.error(f"Whisper unavailable: {e2}")
    return _whisper


def _resample(audio: np.ndarray, orig_rate: int, target_rate: int = 16000) -> np.ndarray:
    if orig_rate == target_rate:
        return audio
    try:
        from scipy.signal import resample_poly
        g = math.gcd(orig_rate, target_rate)
        return resample_poly(audio, target_rate // g, orig_rate // g).astype(np.float32)
    except ImportError:
        n_out = int(len(audio) * target_rate / orig_rate)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio
        ).astype(np.float32)


def transcribe(raw_bytes: bytes, sample_rate: int = 16000) -> str:
    # Optional NVIDIA NeMo Parakeet path. Activated by ENKIDU_USE_PARAKEET=1.
    # Falls through to Whisper on any failure so deployments without NeMo work.
    try:
        import parakeet_asr  # type: ignore
        if parakeet_asr.is_enabled() and parakeet_asr.is_available():
            audio = np.frombuffer(raw_bytes, dtype=np.float32).copy()
            text = parakeet_asr.transcribe(audio, sample_rate=sample_rate)
            if text:
                return _fix_proper_nouns(text)
            # If Parakeet produced empty output, fall back to Whisper for this call.
    except ImportError as _e:
        logger.debug(f"Parakeet not installed: {_e!r}")
    except Exception as _e:
        logger.warning(f"Parakeet transcribe failed, using Whisper: {_e!r}")

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
            initial_prompt=_WHISPER_PROMPT,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return _fix_proper_nouns(text)
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""


_ENKIDU_ALIASES = [
    "and kidu", "and kiddo", "inkido", "inkidu", "en kidu", "en-kidu",
    "enkido", "enkidoo", "and cue do", "and queue do", "kidu", "unkidu",
]


def _fix_proper_nouns(text: str) -> str:
    lower = text.lower()
    for alias in _ENKIDU_ALIASES:
        if alias in lower:
            text = re.sub(re.escape(alias), "Enkidu", text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# TTS — Kokoro  (primary — fast local neural TTS + character FX)
# ---------------------------------------------------------------------------

_KOKORO_VOICE    = os.environ.get("KOKORO_VOICE",     "bm_george")
_KOKORO_SPEED    = float(os.environ.get("KOKORO_SPEED",    "0.90"))  # slightly deliberate
_KOKORO_LANG     = os.environ.get("KOKORO_LANG",      "b")       # 'b'=British (bm_george requires this)
_KOKORO_SR       = 24000

# Character FX parameters — tuned for BMO from Adventure Time (voiced by Niki Yang):
#
# Voice signature: high-pitched, warm, innocent — the voice of a small sentient
# game console. Earnest, slightly sing-song, NOT metallic or aggressive.
# Think: a child's toy that gained consciousness and is trying its best.
#
# Source voice: af_heart (American female, warm) — best Kokoro match for BMO's
# soft, rounded delivery. Niki Yang's accent/lilt can't be fully cloned but
# af_heart's warmth gets us close.
# FX chain: high pitch shift (+5.5st) → slight formant brighten → very soft drive
# → trace vocoder (game-console electronic hum) → short speaker-box comb
# → light bitcrush (13-bit — subtle digital texture, not 8-bit crunch)
# → gentle presence peak → tiny room reverb.
_FX_PITCH        = float(os.environ.get("ENKIDU_PITCH",     "0.0"))    # bm_george is already deep — no pitch shift needed
_FX_LOW_BOOST_DB = float(os.environ.get("ENKIDU_LOW_BOOST", "0.0"))    # no bass boost — BMO is a small speaker
_FX_LOW_CUTOFF   = float(os.environ.get("ENKIDU_LOW_CUTOFF", "220"))   # bass shelf cutoff (Hz)
_FX_RING_RATE_HZ = float(os.environ.get("ENKIDU_RING_HZ",   "0.0"))    # NO ring mod — BMO is warm, not buzzy
_FX_RING_DEPTH   = float(os.environ.get("ENKIDU_RING_DEPTH", "0.0"))   # off
_FX_COMB_MS      = float(os.environ.get("ENKIDU_COMB_MS",   "2.0"))    # short speaker-box resonance (not metallic plate)
_FX_COMB_FB      = float(os.environ.get("ENKIDU_COMB_FB",   "0.22"))   # light feedback — subtle, not resonant
_FX_COMB_MIX     = float(os.environ.get("ENKIDU_COMB_MIX",  "0.12"))   # wet/dry mix
_FX_DRIVE        = float(os.environ.get("ENKIDU_DRIVE",     "1.8"))    # soft warmth — no aggression
_FX_FORMANT      = float(os.environ.get("ENKIDU_FORMANT",   "1.06"))   # slight brightening — small vocal tract
_FX_SUB_MIX      = float(os.environ.get("ENKIDU_SUB_MIX",   "0.0"))    # no subharmonic
_FX_SUB_CUTOFF   = float(os.environ.get("ENKIDU_SUB_CUTOFF", "120"))   # subharmonic LPF cutoff (Hz)
_FX_VOC_MIX      = float(os.environ.get("ENKIDU_VOC_MIX",   "0.05"))   # trace vocoder — hint of game-console hum
_FX_VOC_BASE_HZ  = float(os.environ.get("ENKIDU_VOC_BASE",  "380"))    # higher carrier = lighter, brighter electronic tone
# Small-speaker presence peak — brightens the upper midrange of a tiny speaker.
_FX_CHEST_DB     = float(os.environ.get("ENKIDU_CHEST_DB",  "2.5"))    # peak gain (dB)
_FX_CHEST_HZ     = float(os.environ.get("ENKIDU_CHEST_HZ",  "1400"))   # small-speaker box resonance, not chest
_FX_CHEST_Q      = float(os.environ.get("ENKIDU_CHEST_Q",   "2.0"))    # moderate width
# Presence peak — warm upper-mid clarity (not aggression).
_FX_BITE_DB      = float(os.environ.get("ENKIDU_BITE_DB",   "2.5"))
_FX_BITE_HZ      = float(os.environ.get("ENKIDU_BITE_HZ",   "2200"))
_FX_BITE_Q       = float(os.environ.get("ENKIDU_BITE_Q",    "1.5"))
# Sibilance shelf — light, clear consonants without harshness.
_FX_SIB_DB       = float(os.environ.get("ENKIDU_SIB_DB",    "2.0"))
_FX_SIB_HZ       = float(os.environ.get("ENKIDU_SIB_HZ",    "6500"))
# Small-room reverb — tiny speaker in a small box, not a chamber.
_FX_VERB_MS      = float(os.environ.get("ENKIDU_VERB_MS",   "20"))
_FX_VERB_FB      = float(os.environ.get("ENKIDU_VERB_FB",   "0.15"))
_FX_VERB_MIX     = float(os.environ.get("ENKIDU_VERB_MIX",  "0.04"))
# Post pitch tweak (for cloned voices). Default off.
_FX_POST_PITCH   = float(os.environ.get("ENKIDU_POST_PITCH", "0.0"))
# Bitcrusher — 13-bit is subtle digital texture (game-console feel without
# the harsh 8-bit crunch). decim=1 keeps sample rate clean.
_FX_CRUSH_MIX    = float(os.environ.get("ENKIDU_CRUSH_MIX",  "0.06"))
_FX_CRUSH_BITS   = int(float(os.environ.get("ENKIDU_CRUSH_BITS", "13")))
_FX_CRUSH_DECIM  = int(float(os.environ.get("ENKIDU_CRUSH_DECIM", "1")))   # downsample factor
_FX_MEGATRON     = os.environ.get("ENKIDU_MEGATRON", "1") == "1"       # enable extended character FX chain
_MEGATRON_SLOWDOWN = float(os.environ.get("ENKIDU_MEGATRON_SLOWDOWN", "1.00"))

_kokoro_pipeline = None
_kokoro_pipeline_lang: Optional[str] = None
_kokoro_lock     = threading.Lock()


def _load_kokoro(lang: Optional[str] = None) -> Optional[object]:
    """Load Kokoro pipeline, rebuilding it if the requested lang_code differs.
    Thread-safe. Pass ``lang`` as 'a' (American) or 'b' (British).
    """
    global _kokoro_pipeline, _kokoro_pipeline_lang
    want_lang = lang or _KOKORO_LANG_MAP.get(_active_voice, _KOKORO_LANG)
    if _kokoro_pipeline is not None and _kokoro_pipeline_lang == want_lang:
        return _kokoro_pipeline
    with _kokoro_lock:
        if _kokoro_pipeline is not None and _kokoro_pipeline_lang == want_lang:
            return _kokoro_pipeline
        # Model is fully cached at ~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M
        # HF_HUB_OFFLINE=1 skips all network checks — uses cache only.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            from kokoro import KPipeline
            logger.info(f"Loading Kokoro pipeline (lang={want_lang})…")
            _kokoro_pipeline = KPipeline(lang_code=want_lang)
            _kokoro_pipeline_lang = want_lang
            logger.info("Kokoro ready.")
        except Exception as e:
            logger.warning(f"Kokoro unavailable: {e}")
            _kokoro_pipeline = None
            _kokoro_pipeline_lang = None
    return _kokoro_pipeline


def _pitch_shift(audio: np.ndarray, semitones: float) -> np.ndarray:
    """
    Pitch shift via rational resampling.
    Negative semitones = lower pitch (deeper voice).
    Note: also slightly stretches/compresses duration (tape-speed effect),
    which adds a natural heaviness to the voice.
    """
    if semitones == 0:
        return audio
    # freq_ratio < 1 for lower pitch (e.g. -3 semitones → 0.841)
    freq_ratio = 2 ** (semitones / 12)
    # n_out = n_in / freq_ratio  — more samples = lower pitch at same playback rate
    try:
        from scipy.signal import resample_poly
        SCALE = 10000
        up    = round(SCALE / freq_ratio)
        down  = SCALE
        g     = math.gcd(up, down)
        return resample_poly(audio, up // g, down // g).astype(np.float32)
    except Exception:
        n_out = max(1, int(len(audio) / freq_ratio))
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio
        ).astype(np.float32)


def _low_shelf_boost(
    audio: np.ndarray,
    boost_db: float,
    cutoff_hz: float = 300.0,
    sr: int = _KOKORO_SR,
) -> np.ndarray:
    """Boost frequencies below cutoff_hz — adds chest resonance / weight."""
    if boost_db <= 0:
        return audio
    try:
        from scipy.signal import butter, sosfilt
        sos           = butter(2, cutoff_hz / (sr / 2), btype="low", output="sos")
        low_component = sosfilt(sos, audio).astype(np.float32)
        gain          = 10 ** (boost_db / 20)
        return np.clip(audio + (gain - 1.0) * low_component, -1.0, 1.0).astype(np.float32)
    except Exception:
        return audio


def _peaking_eq(
    audio: np.ndarray,
    sr: int,
    center_hz: float,
    gain_db: float,
    q: float = 1.4,
) -> np.ndarray:
    """Biquad peaking EQ — Hugo-Weaving Megatron's chest-cavity body lives at
    ~200-260 Hz. A moderate +4-5 dB peak there gives the 'speaking from inside
    armor' resonance without muddying the low end.
    """
    if gain_db == 0 or center_hz <= 0 or center_hz >= sr / 2:
        return audio
    try:
        from scipy.signal import lfilter
        A     = 10 ** (gain_db / 40.0)
        w0    = 2 * np.pi * center_hz / sr
        alpha = np.sin(w0) / (2 * max(0.1, q))
        cw0   = np.cos(w0)
        b0 = 1 + alpha * A
        b1 = -2 * cw0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cw0
        a2 = 1 - alpha / A
        b = np.array([b0, b1, b2], dtype=np.float64) / a0
        a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
        return lfilter(b, a, audio.astype(np.float64)).astype(np.float32)
    except Exception:
        return audio


def _high_shelf(
    audio: np.ndarray,
    sr: int,
    cutoff_hz: float,
    gain_db: float,
    slope: float = 1.0,
) -> np.ndarray:
    """RBJ high-shelf — sibilance lift for crisp Megatron consonants."""
    if gain_db == 0 or cutoff_hz <= 0 or cutoff_hz >= sr / 2:
        return audio
    try:
        from scipy.signal import lfilter
        A     = 10 ** (gain_db / 40.0)
        w0    = 2 * np.pi * cutoff_hz / sr
        cw0   = np.cos(w0)
        sw0   = np.sin(w0)
        alpha = sw0 / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / max(0.1, slope) - 1.0) + 2.0)
        beta  = 2.0 * np.sqrt(A) * alpha
        b0 =     A * ((A + 1) + (A - 1) * cw0 + beta)
        b1 = -2 * A * ((A - 1) + (A + 1) * cw0)
        b2 =     A * ((A + 1) + (A - 1) * cw0 - beta)
        a0 =          (A + 1) - (A - 1) * cw0 + beta
        a1 =      2 * ((A - 1) - (A + 1) * cw0)
        a2 =          (A + 1) - (A - 1) * cw0 - beta
        b = np.array([b0, b1, b2], dtype=np.float64) / a0
        a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
        return lfilter(b, a, audio.astype(np.float64)).astype(np.float32)
    except Exception:
        return audio


def _short_reverb(
    audio: np.ndarray,
    sr: int,
    delay_ms: float,
    feedback: float,
    mix: float,
) -> np.ndarray:
    """Single-tap chamber reverb (cinematic tail). delay ~60-80 ms with low
    feedback simulates a small armored chamber without the smear of a true
    convolution reverb. Keeps Megatron sounding 'on screen' rather than
    booth-dry."""
    if mix <= 0 or delay_ms <= 0:
        return audio
    try:
        from scipy.signal import butter, sosfilt, lfilter
        delay_samples = max(1, int(sr * delay_ms / 1000.0))
        # Damped feedback delay line: y[n] = x[n] + fb * y[n-D]
        b = np.zeros(delay_samples + 1, dtype=np.float64); b[0] = 1.0
        a = np.zeros(delay_samples + 1, dtype=np.float64); a[0] = 1.0; a[-1] = -float(np.clip(feedback, 0.0, 0.7))
        tail = lfilter(b, a, audio.astype(np.float64)).astype(np.float32)
        # Gently low-pass the tail so it sits behind the dry voice.
        sos  = butter(2, min(0.99, 4500.0 / (sr / 2.0)), btype="low", output="sos")
        tail = sosfilt(sos, tail).astype(np.float32)
        return np.clip((1.0 - mix) * audio + mix * tail, -1.0, 1.0).astype(np.float32)
    except Exception:
        return audio


def _ring_modulate(audio: np.ndarray, sr: int, rate_hz: float, depth: float) -> np.ndarray:
    """Subtle amplitude modulation — adds mechanical vibration / robotic edge.
    depth=0 is a no-op; depth=0.3 is clearly audible tremolo."""
    if depth <= 0 or rate_hz <= 0:
        return audio
    t = np.arange(len(audio), dtype=np.float32) / sr
    mod = (1.0 - depth) + depth * np.sin(2 * np.pi * rate_hz * t, dtype=np.float32)
    return (audio * mod).astype(np.float32)


def _bitcrush(
    audio: np.ndarray,
    bits: int,
    decim: int,
    mix: float,
) -> np.ndarray:
    """Bitcrusher / sample-rate decimator — the canonical 'robot voice'
    artifact. Lower bits = harsher quantization noise; higher decim =
    grittier aliasing. Wet/dry mixed back so it adds robotic texture
    without destroying intelligibility.
    """
    if mix <= 0:
        return audio
    bits  = int(np.clip(bits, 2, 16))
    decim = max(1, int(decim))
    levels = float(2 ** (bits - 1) - 1)
    # Sample-and-hold downsample then upsample back to original length.
    held = np.repeat(audio[::decim], decim)[: len(audio)].astype(np.float32)
    if len(held) < len(audio):
        # pad final samples
        pad = np.full(len(audio) - len(held), held[-1] if len(held) else 0.0, dtype=np.float32)
        held = np.concatenate([held, pad])
    crushed = np.round(held * levels) / levels
    return np.clip((1.0 - mix) * audio + mix * crushed, -1.0, 1.0).astype(np.float32)


def _formant_warp(audio: np.ndarray, ratio: float) -> np.ndarray:
    """Approximate formant shift while preserving duration.
    ratio < 1.0 darkens timbre (larger vocal tract impression)."""
    if abs(ratio - 1.0) < 1e-3:
        return audio
    ratio = float(np.clip(ratio, 0.65, 1.35))
    try:
        from scipy.signal import resample_poly
        scale = 4000
        up = max(1, int(round(scale * ratio)))
        down = scale
        g = math.gcd(up, down)
        warped = resample_poly(audio, up // g, down // g).astype(np.float32)
        if len(warped) < 2:
            return audio
        # Time-align back to original duration so this mostly shifts timbre.
        out = np.interp(
            np.linspace(0, len(warped) - 1, len(audio), dtype=np.float32),
            np.arange(len(warped), dtype=np.float32),
            warped,
        )
        return out.astype(np.float32)
    except Exception:
        return audio


def _subharmonic_enhance(audio: np.ndarray, sr: int, mix: float, cutoff_hz: float) -> np.ndarray:
    """Add low growl energy using rectified low-frequency component."""
    if mix <= 0:
        return audio
    try:
        from scipy.signal import butter, sosfilt
        # Full-wave rectification generates octave/sub-octave-like low energy.
        rect = np.abs(audio).astype(np.float32)
        rect = rect - np.mean(rect)
        sos = butter(2, min(0.99, cutoff_hz / (sr / 2.0)), btype="low", output="sos")
        sub = sosfilt(sos, rect).astype(np.float32)
        if np.max(np.abs(sub)) > 1e-6:
            sub = sub / (np.max(np.abs(sub)) + 1e-8)
        out = (1.0 - mix) * audio + mix * sub
        return np.clip(out, -1.0, 1.0).astype(np.float32)
    except Exception:
        return audio


def _vocoder_layer(audio: np.ndarray, sr: int, base_hz: float, mix: float) -> np.ndarray:
    """Light carrier vocoder to add robotic metallic articulation."""
    if mix <= 0 or base_hz <= 0:
        return audio
    t = np.arange(len(audio), dtype=np.float32) / float(sr)
    # Harmonic-rich carrier (odd/even blend), normalized.
    carrier = (
        np.sin(2 * np.pi * base_hz * t)
        + 0.55 * np.sin(2 * np.pi * base_hz * 2.0 * t)
        + 0.35 * np.sin(2 * np.pi * base_hz * 3.0 * t)
        + 0.20 * np.sin(2 * np.pi * base_hz * 4.0 * t)
    ).astype(np.float32)
    carrier = carrier / (np.max(np.abs(carrier)) + 1e-8)
    # Slow envelope follower for intelligibility.
    env = np.abs(audio).astype(np.float32)
    try:
        from scipy.signal import butter, sosfilt
        sos = butter(1, min(0.99, 28.0 / (sr / 2.0)), btype="low", output="sos")
        env = sosfilt(sos, env).astype(np.float32)
    except Exception:
        pass
    voc = (env * carrier).astype(np.float32)
    out = (1.0 - mix) * audio + mix * voc
    return np.clip(out, -1.0, 1.0).astype(np.float32)


def _metallic_comb(
    audio: np.ndarray,
    sr: int,
    delay_ms: float,
    feedback: float,
    mix: float,
) -> np.ndarray:
    """Short feedback comb filter — gives a metallic / chest-plate resonance
    (short delays with moderate feedback create narrow resonant peaks)."""
    if mix <= 0 or delay_ms <= 0:
        return audio
    try:
        from scipy.signal import lfilter
        delay_samples = max(1, int(sr * delay_ms / 1000.0))
        # y[n] = x[n] + fb * y[n-D]
        b = np.zeros(delay_samples + 1, dtype=np.float64); b[0] = 1.0
        a = np.zeros(delay_samples + 1, dtype=np.float64); a[0] = 1.0; a[-1] = -float(feedback)
        filtered = lfilter(b, a, audio.astype(np.float64)).astype(np.float32)
        return np.clip((1.0 - mix) * audio + mix * filtered, -1.0, 1.0).astype(np.float32)
    except Exception:
        return audio


def _tanh_drive(audio: np.ndarray, drive: float) -> np.ndarray:
    """Soft-clip saturation for analog warmth / chest-growl. drive<=1 is a no-op."""
    if drive <= 1.0:
        return audio
    return (np.tanh(audio * drive) / np.tanh(drive)).astype(np.float32)


def _apply_character_fx(audio: np.ndarray, voice: Optional[str] = None) -> np.ndarray:
    """Full character voice FX chain.

    Base chain (always on for Kokoro output):
        pitch shift → formant warp → low shelf boost

    Extended character chain (adds when ENKIDU_MEGATRON=1) — tuned for BMO
    from Adventure Time (small sentient game console, warm + innocent):
        → small-speaker presence peak (~1400 Hz) — console body resonance
        → soft tanh warmth                        — gentle saturation, no aggression
        → trace vocoder layer                     — subtle game-console electronic hum
        → short speaker-box comb (2ms)            — tiny speaker resonance
        → 13-bit bitcrush                         — light digital texture, not crunch
        → gentle presence high-shelf              — clear consonants
        → small-room reverb (20ms)                — tiny speaker, not a chamber
    """
    audio = _pitch_shift(audio, _FX_PITCH)
    audio = _formant_warp(audio, _FX_FORMANT)
    audio = _low_shelf_boost(audio, _FX_LOW_BOOST_DB, cutoff_hz=_FX_LOW_CUTOFF)
    if _FX_MEGATRON:
        audio = _peaking_eq(audio, _KOKORO_SR, _FX_CHEST_HZ, _FX_CHEST_DB, _FX_CHEST_Q)
        audio = _peaking_eq(audio, _KOKORO_SR, _FX_BITE_HZ,  _FX_BITE_DB,  _FX_BITE_Q)
        audio = _tanh_drive(audio, _FX_DRIVE)
        audio = _subharmonic_enhance(audio, _KOKORO_SR, _FX_SUB_MIX, _FX_SUB_CUTOFF)
        audio = _vocoder_layer(audio, _KOKORO_SR, _FX_VOC_BASE_HZ, _FX_VOC_MIX)
        audio = _ring_modulate(audio, _KOKORO_SR, _FX_RING_RATE_HZ, _FX_RING_DEPTH)
        audio = _metallic_comb(audio, _KOKORO_SR, _FX_COMB_MS, _FX_COMB_FB, _FX_COMB_MIX)
        audio = _bitcrush(audio, _FX_CRUSH_BITS, _FX_CRUSH_DECIM, _FX_CRUSH_MIX)
        audio = _high_shelf(audio, _KOKORO_SR, _FX_SIB_HZ, _FX_SIB_DB)
        audio = _short_reverb(audio, _KOKORO_SR, _FX_VERB_MS, _FX_VERB_FB, _FX_VERB_MIX)
    # Final safety clip
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def _numpy_to_wav(audio: np.ndarray, sr: int = _KOKORO_SR) -> bytes:
    """Convert float32 numpy array to WAV bytes (PCM_16)."""
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _vad_trim(audio: np.ndarray, sr: int,
              threshold_rms: float = 0.008,
              window_ms: int = 30,
              tail_padding_ms: int = 220) -> np.ndarray:
    """Trim trailing low-energy frames from TTS output.

    F5-TTS over-estimates output duration and fills the excess with artifacts or
    words from its training data.  This finds the last window with energy above
    threshold and discards everything after it + a short tail (preserves reverb).
    Safe to run on Kokoro output too — it has no effect on normal endings.
    """
    if len(audio) < sr * 0.1:
        return audio
    window  = max(1, int(sr * window_ms / 1000))
    padding = int(sr * tail_padding_ms / 1000)
    n_frames = len(audio) // window
    last_active = 0
    for i in range(n_frames):
        chunk = audio[i * window: (i + 1) * window]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        if rms > threshold_rms:
            last_active = i
    trim_at = min(len(audio), (last_active + 1) * window + padding)
    return audio[:trim_at].astype(np.float32)


def _slowdown_audio(audio: np.ndarray, factor: float) -> np.ndarray:
    """Slightly stretch audio duration to slow speech pacing.
    factor > 1.0 makes speech slower.
    """
    if factor <= 1.0 or len(audio) < 2:
        return audio
    factor = float(np.clip(factor, 1.0, 1.25))
    n_out = max(2, int(round(len(audio) * factor)))
    return np.interp(
        np.linspace(0, len(audio) - 1, n_out, dtype=np.float32),
        np.arange(len(audio), dtype=np.float32),
        audio,
    ).astype(np.float32)


def _resolve_kokoro_voice(profile: Optional[str]) -> str:
    """Map a profile ID to a Kokoro voice ID. Falls back to env-configured default.

    For wav-only profiles (e.g. a future clone), falls back to the env-configured
    KOKORO_VOICE (default: af_heart for BMO) so the FX chain always has good
    source material.
    """
    v = profile or _active_voice
    if v in _KOKORO_LANG_MAP:
        return v
    # wav-only profile or unrecognised name — use the env default
    return _KOKORO_VOICE


def _synth_kokoro(text: str, voice_profile: Optional[str] = None) -> Optional[bytes]:
    """Synthesize with Kokoro + character FX. Returns WAV bytes or None."""
    voice = _resolve_kokoro_voice(voice_profile)
    lang  = _KOKORO_LANG_MAP.get(voice, _KOKORO_LANG)
    pipeline = _load_kokoro(lang=lang)
    if pipeline is None:
        logger.error(f"Kokoro pipeline unavailable (voice={voice!r}, lang={lang!r})")
        return None
    try:
        chunks: list[np.ndarray] = []
        for _gs, _ps, audio in pipeline(text, voice=voice, speed=_KOKORO_SPEED):
            chunks.append(audio)
        if not chunks:
            logger.warning("Kokoro returned no audio chunks")
            return None
        audio = np.concatenate(chunks)
        if _MEGATRON_SLOWDOWN > 1.0:
            audio = _slowdown_audio(audio, _MEGATRON_SLOWDOWN)
        audio = _apply_character_fx(audio, voice=voice_profile or _active_voice)
        audio = _vad_trim(audio, _KOKORO_SR)
        wav   = _numpy_to_wav(audio)
        logger.info(f"Kokoro: '{text[:40]}…' → {len(wav):,} bytes (voice={voice})")
        return wav
    except Exception as e:
        logger.error(f"Kokoro synthesis error: {e}")
        return None


def prewarm_tts():
    """Pre-warm Kokoro in a background thread."""
    def _prewarm():
        # NVIDIA tensor-core hints + cuDNN benchmark (idempotent, safe on CPU).
        try:
            import voice_optim  # type: ignore
            voice_optim.enable_tensorcores()
        except ImportError as _e:
            logger.debug(f"voice_optim not available: {_e!r}")
        except Exception as _e:
            logger.warning(f"voice_optim.enable_tensorcores failed: {_e!r}")

        logger.info("Pre-warming Kokoro…")
        # Multi-pass warmup so cuDNN picks the fastest convolution algorithms
        # before the first user request. Falls back to single pass if optim missing.
        try:
            import voice_optim  # type: ignore
            voice_optim.warmup_kokoro(lambda t: _synth_kokoro(t))
        except Exception:
            result = _synth_kokoro("Enkidu online.")
            if result:
                logger.info(f"Kokoro pre-warm complete ({len(result):,} bytes).")
            else:
                logger.warning("Kokoro pre-warm failed — check installation.")

        # Auto-generate reference transcripts for any wav voice profile that
        # is missing its sidecar .txt file. Closes the F5 cold-start hole.
        # DISABLED by default (set ENKIDU_AUTO_REF_TEXT=1 to enable).
        if os.environ.get("ENKIDU_AUTO_REF_TEXT", "0") == "1":
            try:
                import auto_ref_text  # type: ignore
                if _VOICES_DIR.exists():
                    try:
                        for wav in _VOICES_DIR.glob("*.wav"):
                            auto_ref_text.ensure_ref_text(wav)
                    except Exception as _inner:
                        logger.warning(f"auto_ref_text error iterating voices: {_inner!r}")
            except ImportError as _e:
                logger.debug(f"auto_ref_text module unavailable: {_e!r}")
            except Exception as _e:
                logger.error(f"auto_ref_text failed: {_e!r}")

    threading.Thread(target=_prewarm, name="kokoro-prewarm", daemon=True).start()


def prewarm_chatterbox():
    """Backward-compatible alias retained for existing callers."""
    prewarm_tts()


# ---------------------------------------------------------------------------
# Markdown stripping — clean text before TTS so Kokoro doesn't speak symbols
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """
    Remove markdown formatting so Kokoro doesn't speak asterisks, hashes, etc.
    Paragraph breaks become '. ' so the sentence splitter creates natural pauses.
    """
    # Code fences — remove entirely (no value read aloud)
    text = re.sub(r'```[\s\S]*?```', ' ', text)
    # Inline code — strip backticks, keep content
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Headers — strip leading hashes, keep text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bold / italic — strip asterisks and underscores
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)
    # Blockquotes
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
    # Bullet list items (- / * / +)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Numbered list items
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Em-dash / en-dash → natural pause (spoken as a comma beat, not "dash")
    text = re.sub(r'[—–]', ', ', text)
    # Common inline symbols: percent and currency expand to natural speech
    text = re.sub(r'(\d)%', r'\1 percent', text)
    text = re.sub(r'\$(\d)', r'\1 dollars', text)
    # Paragraph breaks → '. ' so split_sentences creates natural pauses
    text = re.sub(r'\n{2,}', '. ', text)
    # Single newlines → space
    text = re.sub(r'\n', ' ', text)
    # Collapse duplicate periods (e.g. end-of-sentence + inserted '.')
    text = re.sub(r'\.[ .]+', '. ', text)
    # Remove punctuation/symbol clusters that TTS engines may read aloud literally.
    # Keep sentence punctuation and apostrophes inside words.
    text = re.sub(r'[,;:]+', ' ', text)
    text = re.sub(r'[\[\]{}<>|/\\~`^*_#@+=]+', ' ', text)
    text = re.sub(r'\s+([.!?])', r'\1', text)
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    # Strip leading/trailing '. ' artifacts introduced by the paragraph-break rule
    text = re.sub(r'^[\s.]+', '', text)
    return text.strip()


def _sanitize_ref_text(text: str) -> str:
    """Keep reference transcript short and neutral for stable cloning.
    Long or dramatic transcripts can leak phrases into generated output
    (F5-TTS will literally echo ref_text if it doesn't match ref_audio).
    We:
      - strip markdown and exotic symbols
      - downgrade exclamations to periods (less shouting bleed)
      - cap length to ~100 chars (one short sentence)
    """
    text = _strip_markdown(text)
    text = re.sub(r'[^A-Za-z0-9\s\'\.!\?-]', ' ', text)
    text = text.replace('!', '.')
    # Guard against stale prompt-injected phrases from earlier sidecars.
    text = re.sub(r'\b(i am real|proceed with the objective)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    # Prefer the first full sentence if it's reasonably sized.
    m = re.match(r'^(.{15,100}?[.?])\s', text + ' ')
    if m:
        return m.group(1).strip()
    if len(text) > 100:
        text = text[:100].rsplit(' ', 1)[0].strip().rstrip(',;:-') + '.'
    return text


# ---------------------------------------------------------------------------
# Sentence splitting — for streaming TTS
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')


def split_sentences(text: str) -> list[str]:
    """
    Split text into sentences for per-sentence TTS streaming.
    Short fragments (< 30 chars) are merged into the next sentence to avoid
    clipping artefacts from synthesizing single words.
    """
    raw = [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]
    if not raw:
        return [text.strip()] if text.strip() else []

    merged: list[str] = []
    for s in raw:
        if merged and len(merged[-1]) < 30:
            merged[-1] = merged[-1] + " " + s
        else:
            merged.append(s)
    return merged


# ---------------------------------------------------------------------------
# TTS — F5-TTS  (voice-cloning fallback) — persistent subprocess worker
# ---------------------------------------------------------------------------

_F5_WORKER_SCRIPT = Path(__file__).parent / "f5tts_worker.py"
_F5_MODEL_DIR     = Path(__file__).parent / "f5tts_model"
_f5_proc:   Optional[subprocess.Popen] = None
_f5_lock  = threading.Lock()
_f5_ready = False
# Kill-switch strategy: infrastructure failures (worker crash, write error) count
# against the global session limit and can disable F5 entirely.  Per-profile
# timeouts / synthesis errors are tracked per voice_path key so a single bad
# .wav profile doesn't stall other profiles. Tunable via ENKIDU_F5_MAX_FAILS.
_F5_MAX_FAILS = int(os.environ.get("ENKIDU_F5_MAX_FAILS", "2"))
_f5_fail_count = 0          # infrastructure failures (worker crash / write error)
_f5_disabled_session = False  # True → skip F5 for entire session
_f5_profile_fails: dict[str, int] = {}    # per voice_path failure counts
_f5_profiles_disabled: set[str]   = set() # profiles disabled after repeated failure
_AUTO_REF_TEXT = os.environ.get("ENKIDU_AUTO_REF_TEXT", "1") == "1"
_ref_text_cache: dict[str, str] = {}
# Pre-warm F5-TTS in background at startup so it's ready if clone mode is used later.
# Takes ~40s — runs as a daemon thread and doesn't block the server.
_F5_PREWARM = os.environ.get("ENKIDU_PREWARM_F5", "1") == "1"


def _f5_available() -> bool:
    if _f5_disabled_session:
        return False
    return (
        (_F5_MODEL_DIR / "model_1250000.safetensors").exists()
        and (_F5_MODEL_DIR / "vocab.txt").exists()
    )


def _load_ref_text(voice_path: Optional[Path]) -> str:
    """Load optional reference-transcript sidecar (voices/<stem>.txt).

    F5-TTS is much faster and more stable when the ref text is given explicitly
    instead of being auto-transcribed with Whisper on every call (which is what
    caused the 60-second stalls for the Megatron profile).
    """
    if voice_path is None:
        return ""

    key = str(voice_path)
    if key in _ref_text_cache:
        return _ref_text_cache[key]

    side = voice_path.with_suffix(".txt")
    if side.exists():
        try:
            raw = side.read_text(encoding="utf-8").strip()
            txt = _sanitize_ref_text(raw)
            # If the sidecar was polluted by a previous run's dramatic auto-
            # transcript, keep only the first safe sentence to avoid phrase
            # bleed into F5-TTS generated audio.
            if re.search(r'\b(i am real|proceed with the objective|decepticon|prime)\b', txt, flags=re.IGNORECASE):
                # Keep only up to the first period.
                first = txt.split('.', 1)[0].strip()
                if 8 <= len(first) <= 120:
                    txt = first + '.'
                else:
                    txt = "The signal is clear."
            _ref_text_cache[key] = txt
            return txt
        except Exception:
            pass

    if not _AUTO_REF_TEXT:
        return ""

    # Best-effort one-time auto transcription to stabilize F5 voice cloning.
    # We cache in memory and persist to sidecar for next server boot.
    txt = _auto_transcribe_ref_text(voice_path)
    if txt:
        txt = _sanitize_ref_text(txt)
        _ref_text_cache[key] = txt
        try:
            side.write_text(txt + "\n", encoding="utf-8")
            logger.info(f"Saved auto ref transcript: {side.name}")
        except Exception as e:
            logger.warning(f"Could not write {side.name}: {e}")
        return txt
    return ""


def _auto_transcribe_ref_text(voice_path: Path) -> str:
    """Transcribe a reference wav once (best effort) for F5 ref_text.
    Uses the same faster-whisper model already used for STT.
    """
    try:
        import soundfile as sf
        audio, sr = sf.read(str(voice_path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype(np.float32)
        if sr != 16000:
            audio = _resample(audio, sr, 16000)
            sr = 16000
        model = _load_whisper()
        if model is None:
            return ""
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 200},
        )
        txt = " ".join(s.text.strip() for s in segments).strip()
        if txt:
            logger.info(f"Auto-transcribed reference clip {voice_path.name}: {txt[:80]}...")
        return txt
    except Exception as e:
        logger.warning(f"Auto ref_text transcription failed for {voice_path.name}: {e}")
        return ""


def _start_f5_worker() -> bool:
    global _f5_proc, _f5_ready
    if _f5_proc is not None and _f5_proc.poll() is None:
        return _f5_ready
    if not _f5_available():
        return False
    logger.info("Starting F5-TTS worker process…")
    try:
        _f5_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        _f5_proc = subprocess.Popen(
            [sys.executable, str(_F5_WORKER_SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=_f5_env,
        )
        import time as _time
        _startup_timeout = int(os.environ.get("ENKIDU_F5_STARTUP_TIMEOUT", "180"))
        deadline = _time.time() + _startup_timeout
        while _time.time() < deadline:
            line = _f5_proc.stdout.readline().strip()
            if line == "READY":
                _f5_ready = True
                logger.info("F5-TTS worker ready.")
                return True
            if line:
                logger.debug(f"F5-TTS (startup): {line}")
        logger.error(f"F5-TTS worker did not become ready within {_startup_timeout}s")
        _f5_ready = False
        return False
    except Exception as e:
        logger.error(f"Failed to start F5-TTS worker: {e}")
        _f5_proc = None; _f5_ready = False
        return False


def _synth_f5tts(text: str, voice_path: Optional[Path], timeout: Optional[int] = None) -> Optional[bytes]:
    global _f5_proc, _f5_ready, _f5_fail_count, _f5_disabled_session
    if _f5_disabled_session:
        return None
    profile_key = str(voice_path) if voice_path else ""
    if profile_key in _f5_profiles_disabled:
        logger.debug(f"F5-TTS skipped for disabled profile: {profile_key}")
        return None
    # 20s is plenty when ref_text is supplied (~1-3s actual inference). Tunable
    # via ENKIDU_F5_TIMEOUT for longer reference clips.
    if timeout is None:
        timeout = int(os.environ.get("ENKIDU_F5_TIMEOUT", "20"))
    with _f5_lock:
        if not _start_f5_worker():
            return None
        req = {
            "text":       text,
            "voice_path": str(voice_path) if voice_path else "",
            "ref_text":   _load_ref_text(voice_path),
        }
        try:
            _f5_proc.stdin.write(_json.dumps(req) + "\n")
            _f5_proc.stdin.flush()
        except Exception as e:
            # Infrastructure failure — worker process died or pipe broken.
            # Count against global session limit (not per-profile).
            logger.error(f"F5-TTS write error: {e}")
            _f5_proc = None; _f5_ready = False
            _f5_fail_count += 1
            if _f5_fail_count >= _F5_MAX_FAILS:
                _f5_disabled_session = True
                logger.warning("F5-TTS disabled for this session after repeated infrastructure failures.")
            return None

        result_holder: list = []

        def _read():
            while True:
                try:
                    line = _f5_proc.stdout.readline()
                except Exception:
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    result_holder.append(_json.loads(line))
                    return
                except _json.JSONDecodeError:
                    logger.debug(f"F5-TTS non-JSON: {line!r}")

        t = threading.Thread(target=_read, daemon=True)
        t.start(); t.join(timeout)

        if not result_holder:
            # Timeout — likely a bad/long reference clip. Track per-profile so
            # other profiles can still use F5.
            logger.error(f"F5-TTS timed out for profile: {profile_key or '(none)'}")
            try: _f5_proc.kill()
            except Exception: pass
            _f5_proc = None; _f5_ready = False
            _f5_profile_fails[profile_key] = _f5_profile_fails.get(profile_key, 0) + 1
            if _f5_profile_fails[profile_key] >= _F5_MAX_FAILS:
                _f5_profiles_disabled.add(profile_key)
                logger.warning(
                    f"F5-TTS disabled for profile '{profile_key}' after "
                    f"{_f5_profile_fails[profile_key]} timeouts. "
                    f"Add a voices/<name>.txt sidecar to fix, then restart."
                )
            return None

        resp = result_holder[0]
        if not resp.get("ok"):
            # Synthesis error — also per-profile.
            logger.error(f"F5-TTS error for profile '{profile_key}': {resp.get('error')}")
            _f5_profile_fails[profile_key] = _f5_profile_fails.get(profile_key, 0) + 1
            if _f5_profile_fails[profile_key] >= _F5_MAX_FAILS:
                _f5_profiles_disabled.add(profile_key)
                logger.warning(f"F5-TTS disabled for profile '{profile_key}' after repeated errors.")
            return None
        try:
            with open(resp["path"], "rb") as f:
                data = f.read()
            os.unlink(resp["path"])
            # Success — reset this profile's fail counter
            _f5_profile_fails.pop(profile_key, None)
            return data
        except Exception as e:
            logger.error(f"F5-TTS output read error: {e}")
            return None


# ---------------------------------------------------------------------------
# TTS — Chatterbox  (slowest fallback) — persistent subprocess worker
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = Path(__file__).parent / "chatterbox_worker.py"
_worker_proc:   Optional[subprocess.Popen] = None
_worker_lock  = threading.Lock()
_worker_ready = False
# Same session-level kill-switch as F5 \u2014 Chatterbox takes ~25s even on a good
# run; if it's broken we must not stall every sentence for 30s.
_CHATTERBOX_MAX_FAILS = int(os.environ.get("ENKIDU_CHATTERBOX_MAX_FAILS", "1"))
_chatterbox_fail_count = 0
_chatterbox_disabled_session = False


def _chatterbox_available() -> bool:
    return not _chatterbox_disabled_session and _WORKER_SCRIPT.exists()


def _start_worker() -> bool:
    global _worker_proc, _worker_ready
    if _worker_proc is not None and _worker_proc.poll() is None:
        return _worker_ready
    if _chatterbox_disabled_session:
        return False
    logger.info("Starting Chatterbox worker\u2026")
    try:
        _worker_proc = subprocess.Popen(
            [sys.executable, str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        import time as _time
        deadline = _time.time() + 120
        while _time.time() < deadline:
            line = _worker_proc.stdout.readline().strip()
            if line == "READY":
                _worker_ready = True
                logger.info("Chatterbox worker ready.")
                return True
            if line:
                logger.debug(f"Chatterbox (startup): {line}")
        logger.error("Chatterbox worker did not become ready within 120s")
        _worker_ready = False
        return False
    except Exception as e:
        logger.error(f"Failed to start Chatterbox: {e}")
        _worker_proc = None; _worker_ready = False
        return False


def _synth_chatterbox(text: str, voice_path: Optional[Path], timeout: Optional[int] = None) -> Optional[bytes]:
    global _worker_proc, _worker_ready, _chatterbox_fail_count, _chatterbox_disabled_session
    if _chatterbox_disabled_session:
        return None
    if timeout is None:
        # Keep well under the 60s outer TTS wall clock so Kokoro+FX gets a turn
        # if Chatterbox stalls. Override with ENKIDU_CHATTERBOX_TIMEOUT if needed.
        timeout = int(os.environ.get("ENKIDU_CHATTERBOX_TIMEOUT", "20"))

    def _mark_fail(reason: str) -> None:
        global _chatterbox_fail_count, _chatterbox_disabled_session
        _chatterbox_fail_count += 1
        if _chatterbox_fail_count >= _CHATTERBOX_MAX_FAILS:
            _chatterbox_disabled_session = True
            logger.warning(f"Chatterbox disabled for this session ({reason}).")

    with _worker_lock:
        if not _start_worker():
            return None
        req = {"text": text, "voice_path": str(voice_path) if voice_path else ""}
        try:
            _worker_proc.stdin.write(_json.dumps(req) + "\n")
            _worker_proc.stdin.flush()
        except Exception as e:
            logger.error(f"Chatterbox write error: {e}")
            _worker_proc = None; _worker_ready = False
            _mark_fail("write error")
            return None

        result_holder: list = []

        def _read():
            while True:
                try:
                    line = _worker_proc.stdout.readline()
                except Exception:
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    result_holder.append(_json.loads(line))
                    return
                except _json.JSONDecodeError:
                    logger.debug(f"Chatterbox non-JSON: {line!r}")

        t = threading.Thread(target=_read, daemon=True)
        t.start(); t.join(timeout)

        if not result_holder:
            logger.error("Chatterbox timed out")
            try: _worker_proc.kill()
            except Exception: pass
            _worker_proc = None; _worker_ready = False
            _mark_fail("timeout")
            return None

        resp = result_holder[0]
        if not resp.get("ok"):
            logger.error(f"Chatterbox error: {resp.get('error')}")
            _mark_fail("error")
            return None
        try:
            with open(resp["path"], "rb") as f:
                data = f.read()
            os.unlink(resp["path"])
            _chatterbox_fail_count = 0
            return data
        except Exception as e:
            logger.error(f"Chatterbox output read error: {e}")
            return None


# ---------------------------------------------------------------------------
# TTS — edge-tts  (cloud neural, internet required)
# ---------------------------------------------------------------------------

_EDGE_TTS_VOICE = "en-US-BrianNeural"


async def _synth_edge_tts(text: str) -> Optional[bytes]:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, _EDGE_TTS_VOICE)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        result = b"".join(chunks)
        if result:
            logger.info(f"edge-tts: {len(result):,} bytes")
            return result
        logger.warning("edge-tts returned empty audio")
    except Exception as e:
        logger.warning(f"edge-tts failed: {e}")
    return None


# ---------------------------------------------------------------------------
# TTS — pyttsx3 SAPI5  (offline Windows last resort)
# ---------------------------------------------------------------------------

def _synth_sapi(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    script = (
        "import pyttsx3\n"
        "engine = pyttsx3.init()\n"
        "engine.setProperty('rate', 165)\n"
        "engine.setProperty('volume', 1.0)\n"
        "for v in engine.getProperty('voices'):\n"
        "    if 'david' in v.name.lower():\n"
        "        engine.setProperty('voice', v.id); break\n"
        f"engine.save_to_file({repr(text)}, {repr(tmp_path)})\n"
        "engine.runAndWait()\n"
    )
    try:
        subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=20)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _postprocess_wav_bytes(wav_bytes: bytes, voice_profile: Optional[str]) -> bytes:
    """Re-apply character FX (pitch + extended chain) to WAV bytes from F5-TTS /
    Chatterbox / edge-tts / SAPI so every backend shares the same voice signature.
    VAD trim is always applied to strip F5-TTS trailing hallucinations."""
    if not wav_bytes:
        return wav_bytes
    try:
        import soundfile as sf
        buf_in = io.BytesIO(wav_bytes)
        audio, sr = sf.read(buf_in, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype(np.float32)
        # Always trim trailing artifacts from voice-cloning models — trim before FX
        # so the energy detector sees the raw speech, not reverb/comb ringing.
        audio = _vad_trim(audio, sr)
        if not _FX_MEGATRON:
            buf_out = io.BytesIO()
            sf.write(buf_out, audio, sr, format="WAV", subtype="PCM_16")
            return buf_out.getvalue()
        if _MEGATRON_SLOWDOWN > 1.0:
            audio = _slowdown_audio(audio, _MEGATRON_SLOWDOWN)
        # Cloned voices already match the reference timbre; only apply a post-pitch
        # nudge if explicitly configured (default off).
        if _FX_POST_PITCH != 0:
            audio = _pitch_shift(audio, _FX_POST_PITCH)
        audio = _formant_warp(audio, max(0.90, _FX_FORMANT + 0.02))
        audio = _low_shelf_boost(audio, _FX_LOW_BOOST_DB, cutoff_hz=_FX_LOW_CUTOFF, sr=sr)
        audio = _peaking_eq(audio, sr, _FX_CHEST_HZ, _FX_CHEST_DB, _FX_CHEST_Q)
        audio = _peaking_eq(audio, sr, _FX_BITE_HZ,  _FX_BITE_DB,  _FX_BITE_Q)
        audio = _tanh_drive(audio, _FX_DRIVE)
        audio = _subharmonic_enhance(audio, sr, _FX_SUB_MIX, _FX_SUB_CUTOFF)
        audio = _vocoder_layer(audio, sr, _FX_VOC_BASE_HZ, _FX_VOC_MIX)
        audio = _ring_modulate(audio, sr, _FX_RING_RATE_HZ, _FX_RING_DEPTH)
        audio = _metallic_comb(audio, sr, _FX_COMB_MS, _FX_COMB_FB, _FX_COMB_MIX)
        audio = _bitcrush(audio, _FX_CRUSH_BITS, _FX_CRUSH_DECIM, _FX_CRUSH_MIX)
        audio = _high_shelf(audio, sr, _FX_SIB_HZ, _FX_SIB_DB)
        audio = _short_reverb(audio, sr, _FX_VERB_MS, _FX_VERB_FB, _FX_VERB_MIX)
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
        buf_out = io.BytesIO()
        sf.write(buf_out, audio, sr, format="WAV", subtype="PCM_16")
        return buf_out.getvalue()
    except Exception as e:
        logger.warning(f"Character FX post-process failed, returning raw wav: {e}")
        return wav_bytes


async def synthesize(text: str, voice_profile: Optional[str] = None) -> tuple[bytes, str]:
    """
    Full-text synthesis. Returns (audio_bytes, format_str).

        Priority:
            • Kokoro is the primary path (fast, local).
            • Fall back: edge-tts -> pyttsx3 SAPI5.
    """
    text = _strip_markdown(text)
    if not text.strip():
        return b"", "wav"

    profile    = voice_profile if voice_profile is not None else _active_voice
    loop           = asyncio.get_event_loop()

    # 1. Kokoro (primary local path).
    wav = await loop.run_in_executor(None, lambda: _synth_kokoro(text, profile))
    if wav:
        return wav, "wav"
    logger.warning("Kokoro failed, falling back to edge-tts…")

    # 2. edge-tts (cloud)
    mp3 = await _synth_edge_tts(text)
    if mp3:
        return mp3, "mp3"

    # 3. pyttsx3 SAPI5 (offline)
    try:
        wav = await loop.run_in_executor(None, lambda: _synth_sapi(text))
        if wav:
            logger.info(f"SAPI fallback: {len(wav):,} bytes")
            return wav, "wav"
    except Exception as e:
        logger.error(f"SAPI fallback failed: {e}")

    return b"", "wav"

async def synthesize_streaming(
    text:          str,
    on_sentence:   Callable[[bytes, str, int], Coroutine],
    voice_profile: Optional[str] = None,
) -> None:
    """
    Sentence-split streaming TTS.

    For built-in Kokoro voices, each sentence is synthesised directly with Kokoro
    (~50-100 ms each) — the client starts playing sentence 0 while the server
    generates sentence 1.

    Streaming path is Kokoro-first for all profiles to prioritize reliability and
    low latency.
    """
    text = _strip_markdown(text)
    if not text.strip():
        return

    sentences  = split_sentences(text)
    profile    = voice_profile if voice_profile is not None else _active_voice
    loop       = asyncio.get_event_loop()

    for seq, sentence in enumerate(sentences):
        if not sentence.strip():
            continue

        wav = await loop.run_in_executor(None, lambda s=sentence: _synth_kokoro(s, profile))
        if wav:
            await on_sentence(wav, "wav", seq)
        else:
            logger.warning(f"Kokoro returned nothing for sentence {seq} (profile={profile!r}), skipping")
