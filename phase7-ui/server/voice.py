"""
phase7-ui/server/voice.py — Speech-to-text + text-to-speech for Enkidu

STT: faster-whisper (base.en CUDA float16 → CPU int8 fallback)
     initial_prompt biases Whisper toward "Enkidu" and other proper nouns

TTS priority:
  1. Kokoro  — fast local neural TTS (~50-100ms on RTX 4090)
               Voices: bm_george (default), bm_lewis, am_adam, am_michael, etc.
               Character FX applied: pitch shift + low-freq boost
  2. F5-TTS  — if Kokoro unavailable AND a .wav voice profile is present
               Voice cloning from reference audio (~2-5s, subprocess worker)
  3. Chatterbox — if F5-TTS unavailable AND .wav profile present (~25s)
  4. edge-tts BrianNeural — cloud neural TTS (internet required)
  5. pyttsx3 SAPI5 — offline Windows last resort

Voice profiles (.wav):
  Drop any .wav into phase7-ui/server/voices/ — used as reference by F5/Chatterbox.
  Kokoro uses its own built-in voices (no reference wav needed).
  GET /api/voices → list of all available voice IDs (Kokoro + wav profiles)
  Active voice stored in module-level _active_voice.

Character FX (tunable via env vars):
  ENKIDU_PITCH     — semitones, negative = deeper (default: -3.0)
  ENKIDU_LOW_BOOST — dB bass shelf boost (default: 4.0)
  KOKORO_VOICE     — default Kokoro voice ID (default: bm_george)
  KOKORO_SPEED     — speech speed multiplier (default: 0.92)
  KOKORO_LANG      — pipeline lang code: 'b'=British, 'a'=American (default: b)
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
    """Return available voice IDs: Kokoro built-ins first, then wav-only profiles."""
    wav_stems = sorted(p.stem for p in _VOICES_DIR.glob("*.wav")) if _VOICES_DIR.exists() else []
    seen = set(_KOKORO_BUILTIN)
    extras = [v for v in wav_stems if v not in seen]
    return _KOKORO_BUILTIN + extras


def get_voice_path(profile_id: str) -> Optional[Path]:
    """Return path to reference wav for F5/Chatterbox, or None."""
    p = _VOICES_DIR / f"{profile_id}.wav"
    return p if p.exists() else None


# Active voice (Kokoro voice ID or wav profile name)
_active_voice: str = os.environ.get("KOKORO_VOICE", "bm_george")


def get_active_voice() -> str:
    return _active_voice


def set_active_voice(profile_id: str) -> bool:
    """Set the active voice. Accepts Kokoro voice IDs or wav profile names."""
    global _active_voice
    all_ids = list_voices()
    if profile_id == "default":
        _active_voice = os.environ.get("KOKORO_VOICE", "bm_george")
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
_KOKORO_SPEED    = float(os.environ.get("KOKORO_SPEED",    "0.92"))
_KOKORO_LANG     = os.environ.get("KOKORO_LANG",      "b")       # 'b'=British default
_KOKORO_SR       = 24000

# Character FX parameters
_FX_PITCH        = float(os.environ.get("ENKIDU_PITCH",     "-3.0"))  # semitones, neg = deeper
_FX_LOW_BOOST_DB = float(os.environ.get("ENKIDU_LOW_BOOST", "4.0"))   # dB bass boost

_kokoro_pipeline = None
_kokoro_lock     = threading.Lock()


def _load_kokoro() -> Optional[object]:
    """Load Kokoro pipeline once and cache it. Thread-safe."""
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return _kokoro_pipeline
    with _kokoro_lock:
        if _kokoro_pipeline is not None:
            return _kokoro_pipeline
        # Model is fully cached at ~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M
        # HF_HUB_OFFLINE=1 skips all network checks — uses cache only.
        # huggingface.co is blocked on this machine anyway (WinError 10054).
        # If cache is ever cleared, set HF_ENDPOINT=https://hf-mirror.com and
        # remove HF_HUB_OFFLINE to re-download.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # fallback if offline ever removed
        try:
            from kokoro import KPipeline
            lang = _KOKORO_LANG_MAP.get(_active_voice, _KOKORO_LANG)
            logger.info(f"Loading Kokoro pipeline (lang={lang})…")
            _kokoro_pipeline = KPipeline(lang_code=lang)
            logger.info("Kokoro ready.")
        except Exception as e:
            logger.warning(f"Kokoro unavailable: {e}")
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


def _apply_character_fx(audio: np.ndarray) -> np.ndarray:
    """Full character voice FX chain: pitch shift → low shelf boost."""
    audio = _pitch_shift(audio, _FX_PITCH)
    audio = _low_shelf_boost(audio, _FX_LOW_BOOST_DB)
    return audio


def _numpy_to_wav(audio: np.ndarray, sr: int = _KOKORO_SR) -> bytes:
    """Convert float32 numpy array to WAV bytes (PCM_16)."""
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _resolve_kokoro_voice(profile: Optional[str]) -> str:
    """Map a profile ID to a Kokoro voice ID. Falls back to env-configured default."""
    v = profile or _active_voice
    if v in _KOKORO_LANG_MAP:
        return v
    # wav-only profile or unrecognised name — use the env default
    return _KOKORO_VOICE


def _synth_kokoro(text: str, voice_profile: Optional[str] = None) -> Optional[bytes]:
    """Synthesize with Kokoro + character FX. Returns WAV bytes or None."""
    pipeline = _load_kokoro()
    if pipeline is None:
        return None
    voice = _resolve_kokoro_voice(voice_profile)
    try:
        chunks: list[np.ndarray] = []
        for _gs, _ps, audio in pipeline(text, voice=voice, speed=_KOKORO_SPEED):
            chunks.append(audio)
        if not chunks:
            logger.warning("Kokoro returned no audio chunks")
            return None
        audio = np.concatenate(chunks)
        audio = _apply_character_fx(audio)
        wav   = _numpy_to_wav(audio)
        logger.info(f"Kokoro: '{text[:40]}…' → {len(wav):,} bytes (voice={voice})")
        return wav
    except Exception as e:
        logger.error(f"Kokoro synthesis error: {e}")
        return None


def prewarm_chatterbox():
    """Pre-warm Kokoro (and F5-TTS worker if model available) in a background thread."""
    def _prewarm():
        logger.info("Pre-warming Kokoro…")
        result = _synth_kokoro("Enkidu online.")
        if result:
            logger.info(f"Kokoro pre-warm complete ({len(result):,} bytes).")
        else:
            logger.warning("Kokoro pre-warm failed — check installation.")
        # Optionally also pre-warm F5-TTS worker in background
        if _f5_available():
            t = threading.Thread(target=_start_f5_worker, name="f5-prewarm", daemon=True)
            t.start()
    threading.Thread(target=_prewarm, name="kokoro-prewarm", daemon=True).start()


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


def _f5_available() -> bool:
    return (
        (_F5_MODEL_DIR / "model_1250000.safetensors").exists()
        and (_F5_MODEL_DIR / "vocab.txt").exists()
    )


def _start_f5_worker() -> bool:
    global _f5_proc, _f5_ready
    if _f5_proc is not None and _f5_proc.poll() is None:
        return _f5_ready
    if not _f5_available():
        return False
    logger.info("Starting F5-TTS worker process…")
    try:
        _f5_proc = subprocess.Popen(
            [sys.executable, str(_F5_WORKER_SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        import time as _time
        deadline = _time.time() + 60
        while _time.time() < deadline:
            line = _f5_proc.stdout.readline().strip()
            if line == "READY":
                _f5_ready = True
                logger.info("F5-TTS worker ready.")
                return True
            if line:
                logger.debug(f"F5-TTS (startup): {line}")
        logger.error("F5-TTS worker did not become ready within 60s")
        _f5_ready = False
        return False
    except Exception as e:
        logger.error(f"Failed to start F5-TTS worker: {e}")
        _f5_proc = None; _f5_ready = False
        return False


def _synth_f5tts(text: str, voice_path: Optional[Path], timeout: int = 60) -> Optional[bytes]:
    global _f5_proc, _f5_ready
    with _f5_lock:
        if not _start_f5_worker():
            return None
        req = {"text": text, "voice_path": str(voice_path) if voice_path else ""}
        try:
            _f5_proc.stdin.write(_json.dumps(req) + "\n")
            _f5_proc.stdin.flush()
        except Exception as e:
            logger.error(f"F5-TTS write error: {e}")
            _f5_proc = None; _f5_ready = False
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
            logger.error("F5-TTS timed out")
            _f5_proc.kill(); _f5_proc = None; _f5_ready = False
            return None

        resp = result_holder[0]
        if not resp.get("ok"):
            logger.error(f"F5-TTS error: {resp.get('error')}")
            return None
        try:
            with open(resp["path"], "rb") as f:
                data = f.read()
            os.unlink(resp["path"])
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


def _start_worker() -> bool:
    global _worker_proc, _worker_ready
    if _worker_proc is not None and _worker_proc.poll() is None:
        return _worker_ready
    logger.info("Starting Chatterbox worker…")
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


def _synth_chatterbox(text: str, voice_path: Optional[Path], timeout: int = 120) -> Optional[bytes]:
    global _worker_proc, _worker_ready
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
            _worker_proc.kill(); _worker_proc = None; _worker_ready = False
            return None

        resp = result_holder[0]
        if not resp.get("ok"):
            logger.error(f"Chatterbox error: {resp.get('error')}")
            return None
        try:
            with open(resp["path"], "rb") as f:
                data = f.read()
            os.unlink(resp["path"])
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

async def synthesize(text: str, voice_profile: Optional[str] = None) -> tuple[bytes, str]:
    """
    Full-text synthesis. Returns (audio_bytes, format_str).

    Priority: Kokoro → F5-TTS (if wav profile) → Chatterbox → edge-tts → pyttsx3
    """
    if not text.strip():
        return b"", "wav"

    profile    = voice_profile if voice_profile is not None else _active_voice
    voice_path = get_voice_path(profile) if profile and profile not in _KOKORO_LANG_MAP else None
    loop       = asyncio.get_event_loop()

    # 1. Kokoro (primary — fast, GPU, character FX applied)
    wav = await loop.run_in_executor(None, lambda: _synth_kokoro(text, profile))
    if wav:
        return wav, "wav"
    logger.warning("Kokoro failed, trying F5-TTS…")

    # 2. F5-TTS (voice cloning — needs reference wav)
    if voice_path is not None and _f5_available():
        wav = await loop.run_in_executor(None, lambda: _synth_f5tts(text, voice_path))
        if wav:
            return wav, "wav"
        logger.warning("F5-TTS failed, trying Chatterbox…")

    # 3. Chatterbox (slowest voice cloning — needs reference wav)
    if voice_path is not None:
        wav = await loop.run_in_executor(None, lambda: _synth_chatterbox(text, voice_path))
        if wav:
            return wav, "wav"
        logger.warning("Chatterbox failed, falling back to edge-tts…")

    # 4. edge-tts (cloud)
    mp3 = await _synth_edge_tts(text)
    if mp3:
        return mp3, "mp3"

    # 5. pyttsx3 SAPI5 (offline)
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

    Splits text into sentences, synthesizes each with Kokoro (~50-100ms each),
    and calls on_sentence(audio_bytes, fmt, seq) immediately as each is ready.
    The client can start playing sentence 0 while the server is generating sentence 1,
    making the response feel nearly instantaneous.

    Falls back to full synthesize() per-sentence if Kokoro is unavailable.
    """
    if not text.strip():
        return

    sentences  = split_sentences(text)
    loop       = asyncio.get_event_loop()
    profile    = voice_profile if voice_profile is not None else _active_voice

    for seq, sentence in enumerate(sentences):
        if not sentence.strip():
            continue
        wav = await loop.run_in_executor(None, lambda s=sentence: _synth_kokoro(s, profile))
        if wav:
            await on_sentence(wav, "wav", seq)
        else:
            # Kokoro unavailable — fall through to full synthesize for this sentence
            wav_bytes, fmt = await synthesize(sentence, voice_profile=profile)
            if wav_bytes:
                await on_sentence(wav_bytes, fmt, seq)
