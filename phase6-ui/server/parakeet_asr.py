"""
phase6-ui/server/parakeet_asr.py — NVIDIA NeMo Parakeet ASR adapter

Drop-in alternative to faster-whisper for Mithrandir. Parakeet-TDT-0.6B-v2 is
NVIDIA's production-grade English ASR model — significantly more accurate
than Whisper base.en on noisy mics, with native CUDA inference on Ampere/Ada.

Why Parakeet over Whisper for Mithrandir
------------------------------------
- ~25 % lower WER than Whisper base.en on common-voice-style audio.
- Native fp16/bf16 on RTX 4090; uses TensorCores aggressively.
- No subprocess required — runs in-process via PyTorch.
- Streaming-friendly (Token-and-Duration Transducer architecture).
- Apache 2.0 (commercial-friendly).

Activation
----------
Set MITHRANDIR_USE_PARAKEET=1 in .env. If the import fails (NeMo not installed),
voice.transcribe() silently falls back to faster-whisper — nothing breaks.

Install (one-time, opt-in):
    pip install --extra-index-url https://pypi.nvidia.com nemo_toolkit[asr]

Reference: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
"""
from __future__ import annotations

import logging
import math
import os
from typing import Optional

import numpy as np

logger = logging.getLogger("mithrandir.voice.parakeet")

_MODEL_NAME = os.environ.get("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v2")
_PARAKEET_DEVICE = os.environ.get("PARAKEET_DEVICE", "cuda")
_PARAKEET_PRECISION = os.environ.get("PARAKEET_PRECISION", "bf16")  # bf16|fp16|fp32

_model: Optional[object] = None
_load_failed = False


def is_enabled() -> bool:
    """Return True if Parakeet is enabled via env flag."""
    return os.environ.get("MITHRANDIR_USE_PARAKEET", "0") == "1"


def is_available() -> bool:
    """Return True if the model successfully loaded (or can be loaded now)."""
    if _load_failed:
        return False
    if _model is not None:
        return True
    return _try_load() is not None


def _try_load():
    """Lazy-load the NeMo Parakeet model. Returns the model or None on failure."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        # NeMo's import is heavy — only pulled in on first use.
        import nemo.collections.asr as nemo_asr  # type: ignore
        import torch  # type: ignore

        logger.info(f"Loading Parakeet ASR '{_MODEL_NAME}' on {_PARAKEET_DEVICE} ({_PARAKEET_PRECISION})…")
        model = nemo_asr.models.ASRModel.from_pretrained(_MODEL_NAME)

        if _PARAKEET_DEVICE.startswith("cuda") and torch.cuda.is_available():
            dtype = {
                "fp16": torch.float16,
                "bf16": torch.bfloat16,
                "fp32": torch.float32,
            }.get(_PARAKEET_PRECISION, torch.bfloat16)
            model = model.to(_PARAKEET_DEVICE).to(dtype)
            # Tensor-core friendly defaults on Ada Lovelace (RTX 4090).
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
        model.eval()
        _model = model
        logger.info("Parakeet ready.")
        return _model
    except Exception as e:
        _load_failed = True
        logger.warning(
            f"Parakeet load failed ({e!r}). Falling back to Whisper. "
            f"Install with: pip install --extra-index-url https://pypi.nvidia.com nemo_toolkit[asr]"
        )
        return None


def _resample_to_16k(audio: np.ndarray, orig_rate: int) -> np.ndarray:
    """Polyphase resample to 16 kHz (Parakeet's expected rate)."""
    target = 16000
    if orig_rate == target:
        return audio.astype(np.float32, copy=False)
    try:
        from scipy.signal import resample_poly  # type: ignore

        g = math.gcd(orig_rate, target)
        return resample_poly(audio, target // g, orig_rate // g).astype(np.float32)
    except Exception:
        n_out = int(len(audio) * target / orig_rate)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)


def transcribe(audio_f32: np.ndarray, sample_rate: int = 16000) -> str:
    """Transcribe a float32 mono PCM array to text. Returns '' on failure."""
    model = _try_load()
    if model is None:
        return ""
    try:
        audio = _resample_to_16k(audio_f32, sample_rate)
        # NeMo's transcribe API accepts a list of numpy arrays (or filepaths).
        # batch_size=1 keeps memory bounded for the single-mic Mithrandir use case.
        result = model.transcribe([audio], batch_size=1, verbose=False)
        # Newer NeMo returns Hypothesis objects with .text; older returns plain strings.
        if not result:
            return ""
        first = result[0]
        if isinstance(first, list) and first:
            first = first[0]
        text = getattr(first, "text", first)
        return str(text).strip()
    except Exception as e:
        logger.error(f"Parakeet transcription error: {e!r}")
        return ""


def transcribe_file(path: str) -> str:
    """Transcribe an audio file from disk (used by auto_ref_text)."""
    model = _try_load()
    if model is None:
        return ""
    try:
        result = model.transcribe([path], batch_size=1, verbose=False)
        if not result:
            return ""
        first = result[0]
        if isinstance(first, list) and first:
            first = first[0]
        return str(getattr(first, "text", first)).strip()
    except Exception as e:
        logger.error(f"Parakeet transcribe_file error: {e!r}")
        return ""
