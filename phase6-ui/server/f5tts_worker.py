"""
f5tts_worker.py — Long-running F5-TTS worker process.

Much faster than Chatterbox (~2-5s per response vs ~25s).
Uses flow-matching (non-autoregressive) — parallelised generation.

Protocol (same as chatterbox_worker):
  stdin:  {"text": "...", "voice_path": "path/to/ref.wav or empty"}
  stdout: {"ok": true, "path": "/tmp/xxx.wav"}
          {"ok": false, "error": "..."}
  Prints "READY" after model load.
"""

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Inference tuning ─────────────────────────────────────────────────────────
# F5_SPEED: >1.0 = faster speech (1.1 = 10% faster). Tunable via env var.
# F5_CFG_STRENGTH: higher = model adheres more strictly to gen_text, reducing
#   reference-audio phrase bleed (hallucinations like "ever shown"). Default 2.0.
_F5_SPEED        = float(os.environ.get("F5_SPEED",        "1.2"))
_F5_CFG_STRENGTH = float(os.environ.get("F5_CFG_STRENGTH", "2.5"))

# ── Add ffmpeg to PATH so torchaudio / soundfile can find it ─────────────────
# Set FFMPEG_DIR in .env to point at the bin/ folder containing ffmpeg.exe.
_FFMPEG_DIR = os.environ.get(
    "FFMPEG_DIR",
    r"C:\ffmpeg\bin\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin",
)
if os.path.isdir(_FFMPEG_DIR) and _FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

# Suppress F5-TTS load chatter.
# Must use utf-8 encoding — F5-TTS internals print unicode chars (e.g. ≈)
# that cp1252 (Windows default) cannot encode, causing a UnicodeEncodeError.
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")

import torch
import torchaudio
from f5_tts.api import F5TTS

_SERVER_DIR = Path(__file__).parent
_MODEL_DIR  = _SERVER_DIR / "f5tts_model"

device = "cuda" if torch.cuda.is_available() else "cpu"

tts = F5TTS(
    ckpt_file =str(_MODEL_DIR / "model_1250000.safetensors"),
    vocab_file =str(_MODEL_DIR / "vocab.txt"),
    device     =device,
)

# Restore stdout and signal ready
sys.stdout.close()
sys.stdout = _real_stdout
print("READY", flush=True)

# ── Main request loop ─────────────────────────────────────────────────────────

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req        = json.loads(line)
        text       = req["text"]
        voice_path = req.get("voice_path", "")
        ref_text   = req.get("ref_text", "")  # empty \u2192 F5 auto-transcribes (slow!)

        if not voice_path or not os.path.exists(voice_path):
            print(json.dumps({"ok": False, "error": "no valid voice_path for F5-TTS"}), flush=True)
            continue

        # Suppress any stdout prints from tts.infer() (e.g. "Converting audio...")
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
        try:
            wav, sr, _ = tts.infer(
                ref_file        =voice_path,
                ref_text        =ref_text,  # pass through: "" → auto-transcribe, else use as-is
                gen_text        =text,
                seed            =-1,
                remove_silence  =True,   # VAD-trim trailing artifacts / hallucinated speech
                speed           =_F5_SPEED,
                cfg_strength    =_F5_CFG_STRENGTH,
            )
        finally:
            sys.stdout.close()
            sys.stdout = _real_stdout

        # wav may be numpy array or tensor — normalise to tensor
        if not isinstance(wav, torch.Tensor):
            import numpy as np
            wav = torch.from_numpy(np.array(wav))
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        torchaudio.save(out_path, wav.cpu(), sr)
        print(json.dumps({"ok": True, "path": out_path}), flush=True)

    except Exception as e:
        import traceback
        print(json.dumps({"ok": False, "error": traceback.format_exc()[-400:]}), flush=True)
