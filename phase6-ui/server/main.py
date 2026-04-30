"""
phase6-ui/server/main.py — Mithrandir UI backend (FastAPI)

Endpoints:
  GET  /api/health
  GET  /api/params            current Gemma4 generation params
  POST /api/params            update Gemma4 generation params
  POST /api/chat              non-streaming chat (fallback)
  GET  /api/portfolio         top QV picks
  GET  /api/regime            current HMM market regime
  GET  /api/history           recent conversation history
  GET  /api/docs              CUDA/hardware reference docs (all)
  GET  /api/docs/search?q=    keyword search over docs
  WS   /ws/gpu                real-time GPU/CPU/RAM stats at 2 Hz
  WS   /ws/chat               streaming chat tokens

Serves compiled React SPA from ../client/dist in production.
"""

import asyncio
import base64
import json
import logging
import os
import random
import re
import sys
import time
import threading
from pathlib import Path
from typing import Optional

import psutil
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

_FORCED_VOICE_PROFILE = os.environ.get("MITHRANDIR_FORCE_VOICE_PROFILE", "").strip()

# Voice module (STT + TTS) — imported lazily so missing deps don't crash startup
_voice = None

def _get_voice():
    global _voice
    if _voice is not None:
        return _voice
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("voice", Path(__file__).parent / "voice.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _voice = mod
        logger.info("Voice module loaded.")
        try:
            if hasattr(mod, "prewarm_tts"):
                mod.prewarm_tts()
            elif hasattr(mod, "prewarm_chatterbox"):
                # Backward compatibility with older voice.py versions.
                mod.prewarm_chatterbox()
            logger.info("Voice pre-warm started (background thread).")
        except Exception as e:
            logger.error(f"Voice pre-warm failed: {e}", exc_info=True)
    except Exception as e:
        logger.warning(f"Voice module unavailable: {e}")
    return _voice


def _effective_voice_profile(requested: Optional[str]) -> Optional[str]:
    """Resolve requested profile with optional server-side override."""
    if _FORCED_VOICE_PROFILE:
        return _FORCED_VOICE_PROFILE
    return requested

# ---------------------------------------------------------------------------
# Paths — reach back into the Mithrandir monorepo
# ---------------------------------------------------------------------------

_ROOT     = Path(__file__).parent.parent.parent
_PHASE3   = _ROOT / "phase3-agents"
_PHASE2T  = _ROOT / "phase2-tool-use" / "tools"
_PHASE5   = _ROOT / "phase5-intelligence"
_PHASE4   = _ROOT / "phase4-memory"
_CLIENT_DIST = Path(__file__).parent.parent / "client" / "dist"

for p in [str(_PHASE3), str(_PHASE3 / "tools"), str(_PHASE2T), str(_PHASE5), str(_PHASE4)]:
    if p not in sys.path:
        sys.path.insert(0, p)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
# Rotate server.log at 10 MB, keep 3 backups
from logging.handlers import RotatingFileHandler as _RFH
_file_handler = _RFH(
    Path(__file__).parent / "server.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.getLogger().addHandler(_file_handler)
logger = logging.getLogger("mithrandir.ui")

# ---------------------------------------------------------------------------
# Lazy imports (don't crash if a subsystem is unavailable)
# ---------------------------------------------------------------------------

def _import_agent():
    try:
        from mithrandir_agent import run_agent
        return run_agent
    except Exception as e:
        logger.warning(f"mithrandir_agent unavailable: {e}")
        return None

def _import_system_info():
    try:
        sys.path.insert(0, str(_PHASE2T))
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_info", _PHASE2T / "system_info.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_context
    except Exception as e:
        logger.warning(f"system_info unavailable: {e}")
        return None

def _import_regime_mod():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("regime_detector", _PHASE3 / "tools" / "regime_detector.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        logger.warning(f"regime_detector unavailable: {e}")
        return None

def _import_regime():
    mod = _import_regime_mod()
    return mod.get_regime if mod else None

def _import_edgar():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("edgar_screener", _PHASE2T / "edgar_screener.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_context
    except Exception as e:
        logger.warning(f"edgar_screener unavailable: {e}")
        return None


def _import_speech_quality():
    try:
        import speech_quality
        return speech_quality
    except Exception as e:
        logger.warning(f"speech_quality unavailable: {e}")
        return None


def _import_spoken_text():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("spoken_text", Path(__file__).parent / "spoken_text.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        logger.warning(f"spoken_text unavailable: {e}")
        return None

# ---------------------------------------------------------------------------
# NVIDIA GPU stats via nvidia-smi
# ---------------------------------------------------------------------------

import subprocess

def _safe_float(s: str, fallback: float = 0.0) -> float:
    try:
        return float(s.strip().replace("N/A", str(fallback)).replace("[Not Supported]", str(fallback)))
    except Exception:
        return fallback


def _gpu_stats() -> dict:
    """Query live GPU stats including clocks and fan. Returns zeros if nvidia-smi is unavailable."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,"
                "memory.used,memory.total,temperature.gpu,power.draw,power.limit,"
                "clocks.current.sm,clocks.current.memory,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        parts = [p.strip() for p in out.split(",")]
        return {
            "gpu_util":    _safe_float(parts[0]),
            "mem_util":    _safe_float(parts[1]),
            "vram_used":   _safe_float(parts[2]),
            "vram_total":  _safe_float(parts[3], 24576),
            "temp":        _safe_float(parts[4]),
            "power_draw":  _safe_float(parts[5]),
            "power_limit": _safe_float(parts[6], 300),
            "clock_sm":    _safe_float(parts[7]),
            "clock_mem":   _safe_float(parts[8]),
            "fan_speed":   _safe_float(parts[9]),
        }
    except Exception:
        return {
            "gpu_util": 0, "mem_util": 0,
            "vram_used": 0, "vram_total": 24576,
            "temp": 0, "power_draw": 0, "power_limit": 300,
            "clock_sm": 0, "clock_mem": 0, "fan_speed": 0,
        }


def _system_stats() -> dict:
    cpu = psutil.cpu_percent(interval=None)
    vm  = psutil.virtual_memory()
    return {
        "cpu_percent": cpu,
        "ram_used_gb": round(vm.used / 1e9, 1),
        "ram_total_gb": round(vm.total / 1e9, 1),
        "ram_percent": vm.percent,
    }

# ---------------------------------------------------------------------------
# Gemma4 parameter store (in-memory, persisted to a JSON sidecar)
# ---------------------------------------------------------------------------

_PARAMS_FILE = Path(__file__).parent / "gemma_params.json"
_LOCAL_BACKEND = os.environ.get("MITHRANDIR_LOCAL_BACKEND", "gemma").strip().lower()

_DEFAULT_PARAMS_GEMMA = {
    "temperature":    0.7,
    "top_p":          0.9,
    "top_k":          40,
    "min_p":          0.0,
    "repeat_penalty": 1.1,
    "num_ctx":        8192,
    "num_predict":    640,
    "seed":           -1,
}
_DEFAULT_PARAMS_NEMOTRON = {
    "temperature":    0.7,
    "top_p":          0.9,
    "top_k":          40,
    "min_p":          0.0,
    "repeat_penalty": 1.1,
    "num_ctx":        32768,
    "num_predict":    640,
    "seed":           -1,
}
_DEFAULT_PARAMS = _DEFAULT_PARAMS_NEMOTRON if _LOCAL_BACKEND == "nemotron" else _DEFAULT_PARAMS_GEMMA

def _load_params() -> dict:
    if _PARAMS_FILE.exists():
        try:
            return json.loads(_PARAMS_FILE.read_text())
        except Exception:
            pass
    return dict(_DEFAULT_PARAMS)

def _save_params(p: dict):
    _PARAMS_FILE.write_text(json.dumps(p, indent=2))

_gemma_params = _load_params()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Mithrandir UI", version="7.0.0")

_VOICE_MAX_B64_CHARS = int(os.environ.get("MITHRANDIR_VOICE_MAX_B64_CHARS", "8000000"))
_VOICE_MAX_RAW_BYTES = int(os.environ.get("MITHRANDIR_VOICE_MAX_RAW_BYTES", "5000000"))
_VOICE_MIN_RATE = int(os.environ.get("MITHRANDIR_VOICE_MIN_SAMPLE_RATE", "8000"))
_VOICE_MAX_RATE = int(os.environ.get("MITHRANDIR_VOICE_MAX_SAMPLE_RATE", "48000"))
_PRELUDE_CACHE_LIMIT = int(os.environ.get("MITHRANDIR_PRELUDE_CACHE_LIMIT", "12"))
_PRELUDES_ENABLED = os.environ.get("MITHRANDIR_PRELUDES_ENABLED", "0").strip() not in ("", "0", "false", "no")
_STREAM_SENTENCE_MIN_CHARS = int(os.environ.get("MITHRANDIR_STREAM_SENTENCE_MIN_CHARS", "12"))
_STREAM_SENTENCE_SOFT_CHARS = int(os.environ.get("MITHRANDIR_STREAM_SENTENCE_SOFT_CHARS", "48"))

_LATENCY_MAX_RECORDS = int(os.environ.get("MITHRANDIR_LATENCY_MAX_RECORDS", "200"))
_LATENCY_LOCK = threading.Lock()
_LATENCY_EVENTS: list[dict] = []


def _record_latency(stage: str, elapsed_ms: float, **meta) -> None:
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": stage,
        "ms": round(float(elapsed_ms), 1),
    }
    if meta:
        event["meta"] = meta
    with _LATENCY_LOCK:
        _LATENCY_EVENTS.append(event)
        if len(_LATENCY_EVENTS) > _LATENCY_MAX_RECORDS:
            del _LATENCY_EVENTS[0 : len(_LATENCY_EVENTS) - _LATENCY_MAX_RECORDS]

_PROCESSING_PRELUDES = [
    "Give me a moment to process your query.",
    "One moment while I think this through.",
    "Understood. Let me work through that for you.",
    "I heard you. Give me just a moment.",
    "Very well. I am processing that now.",
    "Hold fast. I will have an answer shortly.",
    "Understood. One moment while I gather my thoughts.",
    "I have it. Give me a brief moment.",
    "Acknowledged. Processing now.",
    "Let me take a moment to work that out.",
    "I am on it now. One moment.",
    "Good question. Give me a second to process it.",
    "Received. I am working on your answer.",
    "I hear you clearly. One moment while I process.",
    "Let me trace that through quickly.",
    "Working through it now. One moment.",
    "I am analyzing that now.",
    "Processing your request now.",
    "Give me a short moment to assemble the best answer.",
    "On it. One moment while I compute that.",
    "I am checking that now. One moment.",
    "Allow me a moment to think this through carefully.",
    "I will have that for you in just a moment.",
    "Certainly. Give me one moment.",
    "Right away. Processing your query now.",
    "Understood. I am preparing your response.",
    "I am working on that now.",
    "Let me process that and report back.",
    "One moment. I am assembling the relevant details.",
    "I have begun processing your request.",
    "Excellent. Give me a brief moment to resolve that.",
    "I will sort that out now. One moment.",
    "Understood. Let me verify the details quickly.",
    "Very good. I am processing that request.",
    "I hear you. Working through it now.",
    "One moment while I map that out.",
    "Give me a breath to put this together.",
    "Processing now. I will be with you shortly.",
    "Allow me a moment to form a precise answer.",
    "I am evaluating that now.",
    "One moment while I pull that into focus.",
    "Understood. Calculating the best response now.",
    "Acknowledged. Give me a brief instant.",
    "Working on it. One moment please.",
    "I have started processing your query.",
    "Let me gather the right context for that.",
    "One moment while I prepare a clear answer.",
    "I am reviewing that now.",
    "Give me a short moment to reason that through.",
    "Understood. I am on the trail of it now.",
    "I will return with an answer shortly.",
    "One moment while I refine that response.",
    "Processing your request with care. One moment.",
    "I am with you. Give me a moment to compute this.",
    "Let me turn that over for a moment.",
    "Very well. One moment while I resolve the details.",
    "I am preparing a focused answer now.",
    "Understood. Brief pause while I process.",
    "One moment while I line up the right answer.",
    "Working through the details now.",
    "I am processing that request right now.",
    "Give me a moment to confirm the best path.",
    "Understood. Let me synthesize that for you.",
    "One moment while I shape that response.",
    "I have heard you. Processing now.",
    "I will have an answer for you in a moment.",
    "One moment.",
    "Okay one moment...",
    "A Wizard is never late, nor is he early. He arrives precisely when he means to.",
]

_PRELUDE_AUDIO_CACHE: dict[tuple[str, str], tuple[bytes, str]] = {}
_PRELUDE_CACHE_LOCK = threading.Lock()
_PRELUDE_WARMED_PROFILES: set[str] = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:8000",
        "https://bpachter.github.io",
        "https://gpu.bpachter.dev",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_prelude_warmup() -> None:
    voice = _get_voice()
    if voice is None:
        return
    startup_profile = _effective_voice_profile(None)
    _start_prelude_cache_warmup(voice, startup_profile)

# ---------------------------------------------------------------------------
# Dev panel password gate — protects ALL /api/dev/* endpoints
# ---------------------------------------------------------------------------

_DEV_PANEL_PASSWORD = os.environ.get("MITHRANDIR_DEV_PASSWORD", "").strip() or "antifragile"


@app.middleware("http")
async def _dev_password_middleware(request, call_next):
    """Require X-Dev-Password header (or ?password= query) for /api/dev/* routes."""
    path = request.url.path
    if path.startswith("/api/dev/"):
        provided = (
            request.headers.get("x-dev-password")
            or request.query_params.get("password")
            or ""
        )
        if provided != _DEV_PANEL_PASSWORD:
            return JSONResponse(
                {"error": "dev_password_required", "message": "Dev panel requires authentication."},
                status_code=401,
            )
    return await call_next(request)

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    """Serve SPA when available; otherwise return a useful service landing payload."""
    index = _CLIENT_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))

    ui_url = os.environ.get("MITHRANDIR_UI_URL", "").strip()
    return JSONResponse(
        {
            "ok": True,
            "service": "Mithrandir API",
            "ui": ui_url or "not configured",
            "health": "/api/health",
            "docs": "/docs",
            "note": "Frontend build not found on this backend instance.",
        }
    )

@app.get("/api/health")
def health():
    return {"ok": True, "version": "7.0.0", "backend": _LOCAL_BACKEND}


@app.get("/api/health/detailed")
def health_detailed():
    """Run all subsystem health checks and return a full diagnostic report."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mithrandir_health", _ROOT / "mithrandir_health.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["mithrandir_health"] = mod  # required for @dataclass forward-ref resolution
        spec.loader.exec_module(mod)
        results = mod.run_all(parallel=True, timeout=20.0)
        return mod.summary(results)
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        return {"overall": "unknown", "error": str(e), "counts": {}, "checks": []}


@app.get("/api/params")
def get_params():
    return {**_gemma_params, "_backend": _LOCAL_BACKEND}


class ParamsUpdate(BaseModel):
    temperature:    Optional[float] = None
    top_p:          Optional[float] = None
    top_k:          Optional[int]   = None
    min_p:          Optional[float] = None
    repeat_penalty: Optional[float] = None
    num_ctx:        Optional[int]   = None
    num_predict:    Optional[int]   = None
    seed:           Optional[int]   = None


@app.post("/api/params")
def update_params(body: ParamsUpdate):
    global _gemma_params
    update = body.model_dump(exclude_none=True)
    _gemma_params.update(update)
    _save_params(_gemma_params)
    return _gemma_params


@app.get("/api/regime")
def get_regime_endpoint():
    fn = _import_regime()
    if fn is None:
        return {"regime": "Unknown", "confidence": 0, "error": "regime_detector unavailable"}
    try:
        return fn()
    except Exception as e:
        return {"regime": "Unknown", "confidence": 0, "error": str(e)}


@app.post("/api/regime/retrain")
def retrain_regime_endpoint():
    """Force a fresh HMM retrain from 10 years of SPY data."""
    mod = _import_regime_mod()
    if mod is None:
        return JSONResponse(status_code=503, content={"error": "regime_detector unavailable"})
    try:
        result = mod.retrain()
        return {"status": "ok", **result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/portfolio")
def get_portfolio():
    try:
        import pandas as pd
        _qv_root = os.environ.get("QV_PATH", "")
        qv_path = Path(_qv_root) / "data/processed/quantitative_value_portfolio.csv" if _qv_root else Path()
        if not _qv_root or not qv_path.exists():
            return {"picks": [], "error": "portfolio CSV not found", "provenance": None}
        df = pd.read_csv(qv_path)
        top = df.head(25)
        cols = [c for c in ["ticker", "sector", "ev_ebit", "value_composite", "quality_score", "f_score"] if c in top.columns]
        # to_json() converts NaN → null so frontend gets null (not "") for missing values
        records = json.loads(top[cols].to_json(orient="records"))
        # Provenance tag
        age_hours = (time.time() - qv_path.stat().st_mtime) / 3600
        last_updated = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(qv_path.stat().st_mtime))
        freshness = "fresh" if age_hours <= 72 else "stale"
        return {
            "picks": records,
            "provenance": {
                "source": "SEC EDGAR XBRL (via QV pipeline)",
                "last_updated": last_updated,
                "age_hours": round(age_hours, 1),
                "freshness": freshness,
                "filing_period": "trailing-twelve-months (TTM)",
            },
        }
    except Exception as e:
        return {"picks": [], "error": str(e), "provenance": None}


def _get_db_path():
    candidates = [
        _ROOT / "phase4-memory" / "mithrandir_memory.db",
        _ROOT / "phase4-memory" / "memory.db",
    ]
    return next((p for p in candidates if p.exists()), None)


@app.get("/api/history")
def get_history():
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return {"exchanges": []}
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id, timestamp, user_msg, asst_msg FROM exchanges ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        conn.close()
        return {
            "exchanges": [
                {"id": r[0], "timestamp": r[1], "user": r[2][:120], "assistant": r[3][:300]}
                for r in rows
            ]
        }
    except Exception as e:
        return {"exchanges": [], "error": str(e)}


@app.get("/api/history/{exchange_id}")
def get_history_item(exchange_id: str):
    """Return the full (untruncated) text of a single exchange."""
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return JSONResponse({"error": "DB not found"}, status_code=404)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT id, timestamp, user_msg, asst_msg FROM exchanges WHERE id = ?",
            (exchange_id,)
        ).fetchone()
        conn.close()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"id": row[0], "timestamp": row[1], "user": row[2], "assistant": row[3]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/memory")
def get_memory():
    """Return all exchanges with score/rating, sorted by auto_score desc."""
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return {"entries": [], "stats": {}}
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """SELECT id, timestamp, user_msg, asst_msg, rating, auto_score
               FROM exchanges
               ORDER BY COALESCE(auto_score, 0) DESC, timestamp DESC
               LIMIT 100"""
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
        rated = conn.execute("SELECT COUNT(*) FROM exchanges WHERE rating IS NOT NULL").fetchone()[0]
        avg   = conn.execute("SELECT AVG(auto_score) FROM exchanges WHERE auto_score IS NOT NULL").fetchone()[0]
        conn.close()
        return {
            "entries": [
                {
                    "id": r[0], "timestamp": r[1],
                    "user": r[2][:100], "assistant": r[3][:200],
                    "rating": r[4], "score": r[5],
                }
                for r in rows
            ],
            "stats": {
                "total": total,
                "rated": rated,
                "avg_score": round(avg, 2) if avg else None,
            },
        }
    except Exception as e:
        return {"entries": [], "stats": {}, "error": str(e)}


@app.post("/api/memory/{exchange_id}/rate")
async def rate_memory(exchange_id: str, body: dict):
    """Set user rating on an exchange. rating: 1 (up) or -1 (down)."""
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return JSONResponse({"error": "DB not found"}, status_code=404)
        rating = body.get("rating")
        if rating not in (1, -1, None):
            return JSONResponse({"error": "rating must be 1, -1, or null"}, status_code=400)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE exchanges SET rating = ? WHERE id = ?", (rating, exchange_id))
        conn.commit()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/mind")
def get_mind():
    """Return Mithrandir's consciousness state — memory depth, insights, topic map, recent awareness."""
    try:
        import sqlite3
        import re
        from collections import Counter

        db_path = _get_db_path()
        if db_path is None:
            return {"stats": {}, "insights": [], "recent_topics": [], "topic_map": []}

        conn = sqlite3.connect(db_path)

        total     = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
        rated     = conn.execute("SELECT COUNT(*) FROM exchanges WHERE rating IS NOT NULL").fetchone()[0]
        thumbs_up = conn.execute("SELECT COUNT(*) FROM exchanges WHERE rating = 1").fetchone()[0]
        first_ts  = conn.execute("SELECT MIN(timestamp) FROM exchanges").fetchone()[0]

        # Top insights: thumbs-up first, then by auto_score
        insight_rows = conn.execute(
            """SELECT id, timestamp, user_msg, asst_msg, rating, auto_score
               FROM exchanges
               WHERE rating = 1 OR auto_score IS NOT NULL
               ORDER BY CASE WHEN rating = 1 THEN 0 ELSE 1 END,
                        CAST(COALESCE(auto_score, 0) AS REAL) DESC
               LIMIT 10"""
        ).fetchall()

        # Recent queries for the awareness stream
        recent_rows = conn.execute(
            "SELECT user_msg, timestamp FROM exchanges ORDER BY timestamp DESC LIMIT 25"
        ).fetchall()

        # All user messages for topic map
        all_msgs = conn.execute("SELECT user_msg FROM exchanges").fetchall()
        conn.close()

        # Topic map — word frequency with stopword filter
        stopwords = {
            'the','a','an','is','are','was','were','be','been','being','have','has',
            'had','do','does','did','will','would','could','should','may','might',
            'shall','can','of','to','in','for','on','with','at','by','from','as',
            'into','through','during','before','after','above','below','up','down',
            'out','off','over','under','again','then','once','here','there','when',
            'where','why','how','all','both','each','few','more','most','other',
            'some','such','no','nor','not','only','own','same','so','than','too',
            'very','just','but','and','or','if','i','you','he','she','it','we',
            'they','me','him','her','us','them','my','your','his','its','our',
            'their','this','that','these','those','what','which','who','whom',
            'about','get','got','also','please','let','make','use','using','used',
            'need','want','help','know','think','see','tell','give','look','going',
            'gone','come','take','show','keep','say','said','does','much','many',
            'any','like','well','okay','yeah','sure','right','good','great','true',
        }
        word_counts: Counter = Counter()
        for (msg,) in all_msgs:
            words = re.findall(r"\b[a-zA-Z]{4,}\b", msg.lower())
            for w in words:
                if w not in stopwords:
                    word_counts[w] += 1

        max_count = max((c for _, c in word_counts.most_common(1)), default=1)
        topic_map = [
            {"term": term, "count": count, "pct": round(count / max_count * 100)}
            for term, count in word_counts.most_common(20)
        ]

        return {
            "stats": {
                "total": total,
                "rated": rated,
                "thumbs_up": thumbs_up,
                "first_exchange": first_ts,
            },
            "insights": [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "user": r[2][:140],
                    "assistant": r[3][:320],
                    "rating": r[4],
                    "score": r[5],
                }
                for r in insight_rows
            ],
            "recent_topics": [
                {"msg": r[0][:100], "timestamp": r[1]}
                for r in recent_rows
            ],
            "topic_map": topic_map,
        }
    except Exception as e:
        logger.error(f"mind endpoint error: {e}", exc_info=True)
        return {"stats": {}, "insights": [], "recent_topics": [], "topic_map": [], "error": str(e)}


@app.delete("/api/memory/{exchange_id}")
async def delete_memory(exchange_id: str):
    """Permanently delete an exchange from memory."""
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return JSONResponse({"error": "DB not found"}, status_code=404)
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM exchanges WHERE id = ?", (exchange_id,))
        conn.commit()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Mind panel live tool routes
# ---------------------------------------------------------------------------

@app.get("/api/mind/orator-snapshot")
def mind_orator_snapshot():
    """Proxy Orator's /api/snapshot for the Mind panel live macro brief."""
    import httpx
    orator_url = os.environ.get("ORATOR_URL", "").rstrip("/")
    if not orator_url:
        return JSONResponse(
            {"error": "ORATOR_URL not configured — add it to Mithrandir .env"},
            status_code=503,
        )
    try:
        r = httpx.get(f"{orator_url}/api/snapshot", timeout=15.0)
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException:
        return JSONResponse({"error": "Orator request timed out"}, status_code=504)
    except httpx.HTTPStatusError as e:
        return JSONResponse({"error": f"Orator returned {e.response.status_code}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/mind/site-scout")
def mind_site_scout(q: str = "", archetype: str = "mixed"):
    """Filter + score sample sites matching a state abbreviation or name query."""
    bundle = _import_siting()
    if not bundle:
        return JSONResponse({"error": "Avalon siting engine unavailable"}, status_code=503)
    try:
        sites = _load_sample_sites()
        if not sites:
            return JSONResponse({"error": "No sample sites loaded"}, status_code=404)

        q_lower = q.strip().lower()
        if q_lower:
            filtered = [
                s for s in sites
                if q_lower in s.get("state", "").lower()
                or q_lower in s.get("name", "").lower()
                or q_lower in s.get("notes", "").lower()
            ]
            # Fallback: all sites if nothing matches the query
            if not filtered:
                filtered = sites
        else:
            filtered = sites

        Site = bundle["Site"]
        score_sites = bundle["score_sites"]
        site_objs = [Site(**{k: v for k, v in s.items() if k in ("site_id", "name", "lat", "lon", "acres", "state", "notes")}) for s in filtered]
        results = score_sites(site_objs, archetype=archetype)

        top = sorted(results, key=lambda r: r.composite, reverse=True)[:8]
        return {
            "query": q,
            "archetype": archetype,
            "results": [
                {
                    "site_id": r.site_id,
                    "name": r.name,
                    "state": r.state,
                    "composite": round(r.composite, 3),
                    "archetype": r.archetype,
                }
                for r in top
            ],
        }
    except Exception as e:
        logger.error(f"mind site-scout error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/mind/regime-pulse")
def mind_regime_pulse():
    """Return a compact regime + signal summary for the Mind panel."""
    mod = _import_regime_mod()
    if mod is None:
        return JSONResponse({"error": "regime_detector unavailable"}, status_code=503)
    try:
        raw = mod.detect_regime() if hasattr(mod, "detect_regime") else mod.get_regime()
        regime = raw.get("regime", "Unknown")
        confidence = raw.get("confidence", 0)
        # Build a compact signals list from whatever fields are available
        signals = []
        for key in ("signals", "indicators", "features"):
            if isinstance(raw.get(key), list):
                for s in raw[key][:6]:
                    if isinstance(s, dict):
                        signals.append({
                            "name": s.get("name", s.get("id", "?")),
                            "value": str(s.get("value", s.get("val", "?"))),
                            "direction": s.get("direction", s.get("trend", "—")),
                        })
                break
        if not signals:
            # Flatten top-level numeric fields as signals
            skip = {"regime", "confidence", "error", "updated", "trained_at"}
            for k, v in raw.items():
                if k in skip:
                    continue
                if isinstance(v, (int, float)):
                    signals.append({"name": k, "value": f"{v:.3f}", "direction": "—"})
                if len(signals) >= 6:
                    break
        return {
            "regime": regime,
            "confidence": confidence,
            "signals": signals,
            "updated": raw.get("updated", raw.get("trained_at", "")),
        }
    except Exception as e:
        logger.error(f"mind regime-pulse error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/freshness")
def get_freshness():
    """Return a data freshness audit for all Mithrandir data sources."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("data_freshness", Path(__file__).parent / "data_freshness.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["data_freshness"] = mod  # required for @dataclass forward-ref resolution
        spec.loader.exec_module(mod)
        return mod.get_freshness_report()
    except Exception as e:
        logger.error(f"Freshness check error: {e}", exc_info=True)
        return {"overall": "unknown", "error": str(e), "sources": []}


@app.get("/api/demos")
def get_demos():
    """Return all prebuilt demo definitions for the in-app demo launcher."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("demos", Path(__file__).parent / "demos.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {"demos": mod.get_all_demos()}
    except Exception as e:
        return {"demos": [], "error": str(e)}


@app.get("/api/demos/{demo_id}")
def get_demo(demo_id: str):
    """Return a full demo definition (including steps) by ID."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("demos", Path(__file__).parent / "demos.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        demo = mod.get_demo(demo_id)
        if not demo:
            return JSONResponse({"error": f"Demo '{demo_id}' not found"}, status_code=404)
        return demo
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/telemetry")
def get_telemetry(n: int = 50):
    """Return recent tool-call telemetry (latency, success rate, errors)."""
    try:
        sys.path.insert(0, str(_PHASE3 / "tools"))
        from registry import get_telemetry as _get_telem
        records = _get_telem(n)
        # Compute per-tool stats
        from collections import defaultdict
        stats: dict = defaultdict(lambda: {"calls": 0, "errors": 0, "total_ms": 0.0})
        for r in records:
            t = stats[r["tool"]]
            t["calls"] += 1
            if not r["success"]:
                t["errors"] += 1
            t["total_ms"] += r.get("latency_ms", 0)
        tool_stats = {
            tool: {
                "calls": s["calls"],
                "errors": s["errors"],
                "error_rate": round(s["errors"] / s["calls"], 3) if s["calls"] else 0,
                "avg_latency_ms": round(s["total_ms"] / s["calls"], 1) if s["calls"] else 0,
            }
            for tool, s in stats.items()
        }
        return {"records": records, "tool_stats": tool_stats}
    except Exception as e:
        return {"records": [], "tool_stats": {}, "error": str(e)}


@app.get("/api/latency")
def get_latency_events(n: int = 100):
    """Return recent conversational latency timing events."""
    n = max(1, min(int(n), _LATENCY_MAX_RECORDS))
    with _LATENCY_LOCK:
        events = list(_LATENCY_EVENTS[-n:])
    return {"count": len(events), "events": events}


@app.get("/api/docs")
def get_docs():
    """Return all CUDA/hardware/inference reference entries."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cuda_docs", Path(__file__).parent / "cuda_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {"docs": mod.get_all_docs(), "categories": mod.get_categories()}
    except Exception as e:
        logger.warning(f"cuda_docs unavailable: {e}")
        return {"docs": [], "categories": [], "error": str(e)}


@app.get("/api/docs/search")
def search_docs(q: str = ""):
    """Keyword search over CUDA/hardware docs. Returns plain-text results."""
    if not q.strip():
        return {"results": "", "query": q}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cuda_docs", Path(__file__).parent / "cuda_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        results = mod.search_docs(q, max_results=5)
        return {"results": results, "query": q}
    except Exception as e:
        logger.warning(f"cuda_docs search failed: {e}")
        return {"results": "", "query": q, "error": str(e)}


@app.get("/api/test-audio")
async def test_audio():
    """Returns a short TTS clip directly as audio — open in browser to test playback."""
    voice = _get_voice()
    if voice is None:
        return JSONResponse({"error": "voice unavailable"}, status_code=503)
    test_profile = _effective_voice_profile(None)
    data, fmt = await voice.synthesize(
        "Mithrandir online. Audio system is working.",
        voice_profile=test_profile,
    )
    mime = "audio/wav" if fmt == "wav" else "audio/mpeg"
    return Response(content=data, media_type=mime)


@app.get("/api/voices")
def get_voices():
    """List available voice profiles from the voices/ directory."""
    voice = _get_voice()
    if voice is None:
        return {"voices": [], "active": "default"}
    profiles = voice.list_voices()
    active = _FORCED_VOICE_PROFILE or voice.get_active_voice()
    return {
        "voices": ["default"] + profiles,
        "active": active,
    }


class VoiceSelect(BaseModel):
    profile: str


class LexiconEntry(BaseModel):
    term: str
    spoken: str
    ipa: str = ""
    notes: str = ""


class SpeechFeedbackBody(BaseModel):
    exchange_id: str = ""
    user_text: str = ""
    assistant_text: str = ""
    spoken_text: str = ""
    feedback: str = ""
    corrected_text: str = ""
    issue_tags: str | list[str] = ""


def _rewrite_for_speech(text: str, user_query: str = "") -> dict:
    mod = _import_spoken_text()
    if mod is None:
        return {"spoken_text": text, "notes": ["rewrite_unavailable"]}
    try:
        return mod.rewrite_for_speech(text, user_query=user_query)
    except Exception as e:
        logger.warning(f"speech rewrite failed: {e}")
        return {"spoken_text": text, "notes": ["rewrite_failed"]}


def _save_spoken_exchange(user_text: str, assistant_text: str, spoken_text: str, response_mode: str, voice_profile: Optional[str]) -> None:
    mod = _import_speech_quality()
    if mod is None:
        return
    try:
        mod.attach_spoken_exchange(user_text, assistant_text, spoken_text, response_mode, voice_profile or "")
    except Exception as e:
        logger.warning(f"save_spoken_exchange failed: {e}")


def _normalize_issue_tags(tags: str | list[str]) -> str:
    if isinstance(tags, list):
        return ",".join(tag.strip() for tag in tags if str(tag).strip())
    return str(tags or "").strip()


def _pick_processing_prelude(preferred_profile: Optional[str] = None) -> str:
    """Pick a prelude phrase, preferring ones that are already cached for this profile."""
    if preferred_profile:
        profile_key = preferred_profile.strip()
        with _PRELUDE_CACHE_LOCK:
            cached_phrases = [text for (prof, text) in _PRELUDE_AUDIO_CACHE if prof == profile_key]
        if cached_phrases:
            return random.choice(cached_phrases)
    return random.choice(_PROCESSING_PRELUDES)


async def _synthesize_prelude_strict(voice, text: str, requested_profile: Optional[str]) -> tuple[bytes, str, Optional[str]]:
    if voice is None:
        return b"", "wav", None

    profile = requested_profile
    if hasattr(voice, "_resolve_voice_profile"):
        try:
            profile = voice._resolve_voice_profile(requested_profile)
        except Exception:
            profile = requested_profile

    profile = (profile or "").strip()
    if not profile:
        return b"", "wav", None

    # Skip immediately if F5 worker is restarting — don't block on it for a prelude.
    if hasattr(voice, "_f5_worker_is_starting") and voice._f5_worker_is_starting():
        logger.info("TTS prelude skipped: F5 worker is restarting")
        return b"", "wav", None

    loop = asyncio.get_event_loop()

    clone_ref = None
    if hasattr(voice, "get_voice_path"):
        try:
            clone_ref = voice.get_voice_path(profile)
        except Exception:
            clone_ref = None

    if hasattr(voice, "_styletts2_available") and hasattr(voice, "_synth_styletts2") and voice._styletts2_available():
        wav = await loop.run_in_executor(None, lambda: voice._synth_styletts2(text))
        if wav and hasattr(voice, "_postprocess_wav_bytes"):
            wav = voice._postprocess_wav_bytes(wav, profile)
        if wav:
            return wav, "wav", profile

    if clone_ref and hasattr(voice, "_f5_available") and hasattr(voice, "_synth_f5tts") and voice._f5_available():
        wav = await loop.run_in_executor(None, lambda: voice._synth_f5tts(text, clone_ref))
        if wav and hasattr(voice, "_postprocess_wav_bytes"):
            wav = voice._postprocess_wav_bytes(wav, profile)
        if wav:
            return wav, "wav", profile

    return b"", "wav", profile


def _pick_cached_preludes() -> list[str]:
    ranked = sorted(_PROCESSING_PRELUDES, key=len)
    return ranked[: max(1, min(_PRELUDE_CACHE_LIMIT, len(ranked)))]


async def _warm_prelude_cache_async(voice, requested_profile: Optional[str]) -> None:
    profile = (requested_profile or "").strip()
    if not profile:
        return

    with _PRELUDE_CACHE_LOCK:
        if profile in _PRELUDE_WARMED_PROFILES:
            return
        _PRELUDE_WARMED_PROFILES.add(profile)

    logger.info(f"Prelude cache warmup starting profile={profile!r}")
    for line in _pick_cached_preludes():
        key = (profile, line)
        with _PRELUDE_CACHE_LOCK:
            if key in _PRELUDE_AUDIO_CACHE:
                continue
        try:
            audio_bytes, fmt, actual_profile = await _synthesize_prelude_strict(voice, line, profile)
            if audio_bytes and actual_profile:
                with _PRELUDE_CACHE_LOCK:
                    _PRELUDE_AUDIO_CACHE[(actual_profile, line)] = (audio_bytes, fmt)
        except Exception as exc:
            logger.warning(f"Prelude cache warmup failed profile={profile!r} text={line!r}: {exc}")
    logger.info(f"Prelude cache warmup finished profile={profile!r}")


def _start_prelude_cache_warmup(voice, requested_profile: Optional[str]) -> None:
    profile = (requested_profile or "").strip()
    if not profile:
        return

    def _runner() -> None:
        try:
            asyncio.run(_warm_prelude_cache_async(voice, profile))
        except Exception as exc:
            logger.warning(f"Prelude cache background warmup failed profile={profile!r}: {exc}")

    threading.Thread(target=_runner, daemon=True).start()


async def _stream_processing_prelude(ws: WebSocket, voice, voice_profile: Optional[str]) -> None:
    if voice is None:
        return

    prelude_text = _pick_processing_prelude(preferred_profile=(voice_profile or "").strip() or None)
    requested_profile = (voice_profile or "").strip() or None
    cache_key = ((requested_profile or "").strip(), prelude_text)
    logger.info(
        f"TTS prelude starting requested_profile={requested_profile!r} text={prelude_text!r}"
    )

    with _PRELUDE_CACHE_LOCK:
        cached = _PRELUDE_AUDIO_CACHE.get(cache_key)

    if cached:
        audio_bytes, fmt = cached
        actual_profile = requested_profile
        logger.info(f"TTS prelude cache hit profile={actual_profile!r} format={fmt}")
    else:
        _start_prelude_cache_warmup(voice, requested_profile)
        audio_bytes, fmt, actual_profile = await asyncio.wait_for(
            _synthesize_prelude_strict(voice, prelude_text, requested_profile),
            timeout=30.0,
        )
        if audio_bytes and actual_profile:
            with _PRELUDE_CACHE_LOCK:
                _PRELUDE_AUDIO_CACHE[(actual_profile, prelude_text)] = (audio_bytes, fmt)

    if not audio_bytes:
        logger.warning(f"TTS prelude skipped because requested profile produced no audio profile={requested_profile!r}")
        return

    logger.info(f"TTS prelude first chunk profile={actual_profile!r} format={fmt}")
    try:
        await ws.send_json(
            {
                "type": "tts_prelude_chunk",
                "data": base64.b64encode(audio_bytes).decode(),
                "format": fmt,
                "seq": 0,
                "text": prelude_text,
            }
        )
    except Exception as send_exc:
        raise WebSocketDisconnect() from send_exc
    logger.info(f"TTS prelude finished profile={actual_profile!r}")


async def _play_processing_prelude(ws: WebSocket, voice, voice_profile: Optional[str]) -> None:
    if not _PRELUDES_ENABLED:
        return
    try:
        await _stream_processing_prelude(ws, voice, voice_profile)
    except WebSocketDisconnect:
        raise
    except Exception as prelude_exc:
        logger.warning(f"Processing prelude failed: {prelude_exc}")


@app.post("/api/voice")
def set_voice(body: VoiceSelect):
    """Switch the active TTS voice profile."""
    voice = _get_voice()
    if voice is None:
        return JSONResponse({"error": "voice module unavailable"}, status_code=503)
    if _FORCED_VOICE_PROFILE and body.profile != _FORCED_VOICE_PROFILE:
        return {
            "ok": True,
            "active": _FORCED_VOICE_PROFILE,
            "locked": True,
            "note": f"voice is locked to '{_FORCED_VOICE_PROFILE}'",
        }
    ok = voice.set_active_voice(body.profile)
    if not ok:
        return JSONResponse({"error": f"profile '{body.profile}' not found"}, status_code=404)
    return {"ok": True, "active": body.profile}


@app.get("/api/speech/lexicon")
def get_speech_lexicon(q: str = ""):
    mod = _import_speech_quality()
    if mod is None:
        return JSONResponse({"error": "speech_quality unavailable"}, status_code=503)
    try:
        return {"entries": mod.list_lexicon(q)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/speech/lexicon")
def add_speech_lexicon(body: LexiconEntry):
    mod = _import_speech_quality()
    if mod is None:
        return JSONResponse({"error": "speech_quality unavailable"}, status_code=503)
    try:
        return {"ok": True, "entry": mod.upsert_lexicon(body.term, body.spoken, body.ipa, body.notes, "api")}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/speech/rewrite")
def preview_speech_rewrite(body: dict):
    text = str(body.get("text", "")).strip()
    query = str(body.get("query", "")).strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    return _rewrite_for_speech(text, user_query=query)


@app.post("/api/speech/feedback")
def add_speech_feedback(body: SpeechFeedbackBody):
    mod = _import_speech_quality()
    if mod is None:
        return JSONResponse({"error": "speech_quality unavailable"}, status_code=503)
    try:
        result = mod.record_speech_feedback(
            exchange_id=body.exchange_id,
            feedback=body.feedback,
            corrected_text=body.corrected_text,
            issue_tags=_normalize_issue_tags(body.issue_tags),
            user_msg=body.user_text,
            assistant_msg=body.assistant_text,
            spoken_text=body.spoken_text,
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/speech/readiness")
def get_speech_readiness():
    mod = _import_speech_quality()
    if mod is None:
        return JSONResponse({"error": "speech_quality unavailable"}, status_code=503)
    try:
        return mod.finetune_readiness_report()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/speech/export")
def export_speech_dataset(body: dict | None = None):
    mod = _import_speech_quality()
    if mod is None:
        return JSONResponse({"error": "speech_quality unavailable"}, status_code=503)
    try:
        output_path = None if body is None else body.get("output_path")
        return mod.export_spoken_lora_dataset(output_path)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chat")
async def chat_rest(body: dict):
    """Non-streaming chat endpoint (fallback for clients that don't use WS)."""
    message = body.get("message", "")
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    run_agent = _import_agent()
    if run_agent is None:
        return JSONResponse({"error": "agent unavailable"}, status_code=503)
    try:
        t0 = time.perf_counter()
        response_mode = "spoken" if body.get("tts", False) else str(body.get("response_mode", "visual"))
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_agent(
                message,
                response_mode=response_mode,
                ollama_options=dict(_gemma_params),
            ),
        )
        _record_latency(
            "chat_rest_total_ms",
            (time.perf_counter() - t0) * 1000,
            mode=response_mode,
            chars=len(response or ""),
        )
        if response_mode == "spoken":
            rewritten = _rewrite_for_speech(response or "", user_query=message)
            return {"response": response, "spoken_text": rewritten.get("spoken_text", response), "rewrite_notes": rewritten.get("notes", [])}
        return {"response": response}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ---------------------------------------------------------------------------
# WebSocket: GPU stats (2 Hz)
# ---------------------------------------------------------------------------

@app.websocket("/ws/gpu")
async def ws_gpu(ws: WebSocket):
    await ws.accept()
    # prime psutil cpu_percent (first call always returns 0)
    psutil.cpu_percent(interval=None)
    try:
        while True:
            payload = {**_gpu_stats(), **_system_stats(), "ts": time.time()}
            await ws.send_json(payload)
            await asyncio.sleep(0.5)   # 2 Hz
    except (WebSocketDisconnect, Exception):
        pass

# ---------------------------------------------------------------------------
# WebSocket: streaming chat
# ---------------------------------------------------------------------------

def _fetch_prior_messages(exchange_id: str) -> list:
    """Load a prior exchange from the DB as a [user, assistant] message pair."""
    try:
        import sqlite3
        db_path = _get_db_path()
        if db_path is None:
            return []
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT user_msg, asst_msg FROM exchanges WHERE id = ?",
            (exchange_id,)
        ).fetchone()
        conn.close()
        if not row:
            return []
        return [
            {"role": "user",      "content": row[0]},
            {"role": "assistant", "content": row[1]},
        ]
    except Exception:
        return []


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    run_agent = _import_agent()
    voice     = _get_voice()
    try:
        while True:
            data = await ws.receive_json()
            message = data.get("message", "").strip()
            if not message:
                continue
            turn_t0 = time.perf_counter()

            conversation_id  = data.get("conversation_id")
            prior_messages   = _fetch_prior_messages(conversation_id) if conversation_id else []
            tts_enabled      = data.get("tts", True)   # client can opt out
            voice_profile_req = _effective_voice_profile(data.get("voice_profile"))
            response_mode = "spoken" if tts_enabled else "visual"

            if tts_enabled and voice and message:
                try:
                    await _play_processing_prelude(ws, voice, voice_profile_req)
                except WebSocketDisconnect:
                    return

            loop = asyncio.get_running_loop()
            tokens_sent = [0]
            collected_tokens: list[str] = []
            first_token_at = [None]
            first_audio_at = [None]

            # ── Streaming TTS state ────────────────────────────────────────────
            # Synthesise each sentence as Gemma produces it rather than waiting
            # for the full response. _s_pending tracks submitted futures so we
            # can await them before handing off to synthesize_streaming.
            _s_buf: list[str] = []
            _s_seq = [0]
            _s_pending: list = []
            _stt2_live = (
                tts_enabled and voice
                and hasattr(voice, "_styletts2_available")
                and voice._styletts2_available()
            )

            def _fire_stream_sentence(sentence: str) -> None:
                sentence = sentence.strip()
                if not sentence:
                    return
                clean = re.sub(r'\*+|`+|^#+\s+', '', sentence, flags=re.MULTILINE).strip()
                if not clean:
                    return
                seq = _s_seq[0]
                _s_seq[0] += 1

                async def _do(s=clean, q=seq):
                    try:
                        audio_bytes = b""
                        fmt = "wav"

                        # Use full backend fallback chain per sentence so a StyleTTS2
                        # timeout does not silently drop the rest of the spoken reply.
                        if hasattr(voice, "synthesize"):
                            audio_bytes, fmt = await voice.synthesize(s, voice_profile=voice_profile_req)
                        else:
                            wav = await loop.run_in_executor(None, lambda: voice._synth_styletts2(s))
                            if wav:
                                audio_bytes = wav
                                fmt = "wav"

                        if audio_bytes:
                            if fmt == "wav" and hasattr(voice, "_postprocess_wav_bytes"):
                                audio_bytes = voice._postprocess_wav_bytes(audio_bytes, voice_profile_req)
                            if first_audio_at[0] is None:
                                first_audio_at[0] = time.perf_counter()
                                _record_latency(
                                    "ws_chat_first_audio_ms",
                                    (first_audio_at[0] - turn_t0) * 1000,
                                    mode=response_mode,
                                    streaming=True,
                                )
                            await ws.send_json({
                                "type": "tts_chunk",
                                "data": base64.b64encode(audio_bytes).decode(),
                                "format": fmt,
                                "seq": q,
                            })
                    except WebSocketDisconnect:
                        pass
                    except Exception as exc:
                        logger.debug(f"Streaming TTS seq={q}: {exc}")

                _s_pending.append(asyncio.run_coroutine_threadsafe(_do(), loop))

            def _drain_stream_buf() -> None:
                buf = "".join(_s_buf)
                has_hard_boundary = re.search(r'[.!?]["\']?\s', buf)
                has_soft_boundary = len(buf) >= _STREAM_SENTENCE_SOFT_CHARS and re.search(r'[,;:]\s', buf)
                if len(buf) < _STREAM_SENTENCE_MIN_CHARS or not (has_hard_boundary or has_soft_boundary):
                    return
                parts = (
                    voice.split_sentences(buf)
                    if hasattr(voice, "split_sentences")
                    else re.split(r'(?<=[.!?])\s+', buf, maxsplit=1)
                )
                if len(parts) < 2:
                    return
                for s in parts[:-1]:
                    _fire_stream_sentence(s)
                _s_buf.clear()
                if parts[-1]:
                    _s_buf.append(parts[-1])
            # ──────────────────────────────────────────────────────────────────

            def on_step(msg: str):
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "step", "content": msg}),
                    loop,
                )

            def on_token(tok: str):
                tokens_sent[0] += 1
                collected_tokens.append(tok)
                if first_token_at[0] is None:
                    first_token_at[0] = time.perf_counter()
                    _record_latency(
                        "ws_chat_ttft_ms",
                        (first_token_at[0] - turn_t0) * 1000,
                        mode=response_mode,
                    )
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "token", "content": tok}),
                    loop,
                )
                if _stt2_live:
                    _s_buf.append(tok)
                    _drain_stream_buf()

            if run_agent is None:
                await ws.send_json({"type": "error", "content": "Agent unavailable"})
                await ws.send_json({"type": "done"})
                continue

            # Run agent in thread pool (it's synchronous)
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: run_agent(message, on_step=on_step, on_token=on_token, prior_messages=prior_messages, ollama_options=dict(_gemma_params), response_mode=response_mode),
                )
                if tokens_sent[0] == 0:
                    final_text = response or ""
                else:
                    final_text = "".join(collected_tokens)
                # Always send final authoritative text so the client can replace
                # any streamed partial/malformed tokens with the cleaned output.
                await ws.send_json({"type": "response", "content": final_text})
            except Exception as e:
                await ws.send_json({"type": "error", "content": str(e)})
                await ws.send_json({"type": "done"})
                continue

            # Flush any remaining partial sentence and await all streaming synthesis
            if _stt2_live:
                remaining = "".join(_s_buf).strip()
                if remaining:
                    _fire_stream_sentence(remaining)
                    _s_buf.clear()
                if _s_pending:
                    await asyncio.gather(
                        *[asyncio.wrap_future(f) for f in _s_pending],
                        return_exceptions=True,
                    )

            spoken_result = _rewrite_for_speech(final_text, user_query=message)
            spoken_text = spoken_result.get("spoken_text", final_text).strip() or final_text
            if spoken_text != final_text:
                await ws.send_json({"type": "spoken_preview", "content": spoken_text, "notes": spoken_result.get("notes", [])})
            threading.Thread(
                target=_save_spoken_exchange,
                args=(message, final_text, spoken_text, response_mode, voice_profile_req),
                daemon=True,
            ).start()

            # TTS: if streaming synthesis already handled it, skip synthesize_streaming.
            # Fall through to synthesize_streaming only for the Claude tool-use path
            # (no tokens streamed) or when StyleTTS2 is unavailable.
            if tts_enabled and voice and final_text.strip():
                if _s_pending:
                    # Streaming synthesis ran during generation — already done.
                    pass
                elif not hasattr(voice, "synthesize_streaming"):
                    logger.error("voice.py missing synthesize_streaming — restart the server")
                    await ws.send_json({"type": "tts_error", "content": "TTS: restart server (old voice.py loaded)"})
                else:
                    seq = 0

                    async def _send_chunk(audio_bytes: bytes, fmt: str, _seq: int) -> None:
                        nonlocal seq
                        try:
                            await ws.send_json({
                                "type":   "tts_chunk",
                                "data":   base64.b64encode(audio_bytes).decode(),
                                "format": fmt,
                                "seq":    _seq,
                            })
                            if first_audio_at[0] is None:
                                first_audio_at[0] = time.perf_counter()
                                _record_latency(
                                    "ws_chat_first_audio_ms",
                                    (first_audio_at[0] - turn_t0) * 1000,
                                    mode=response_mode,
                                    streaming=False,
                                )
                            seq += 1
                        except Exception as send_exc:
                            raise WebSocketDisconnect() from send_exc

                    try:
                        logger.info(f"TTS: synthesizing {len(spoken_text)} chars (profile={voice_profile_req!r})")
                        await asyncio.wait_for(
                            voice.synthesize_streaming(
                                spoken_text,
                                _send_chunk,
                                voice_profile=voice_profile_req,
                            ),
                            timeout=60.0,
                        )
                        if seq == 0:
                            logger.warning("TTS: synthesize_streaming produced no audio chunks")
                            try:
                                await ws.send_json({"type": "tts_error", "content": "TTS: no audio produced (check server logs)"})
                            except Exception:
                                pass
                    except WebSocketDisconnect:
                        return
                    except Exception as e:
                        logger.error(f"Chat TTS error: {e}", exc_info=True)
                        try:
                            await ws.send_json({"type": "tts_error", "content": f"TTS error: {e}"})
                        except Exception:
                            pass

            try:
                _record_latency(
                    "ws_chat_total_ms",
                    (time.perf_counter() - turn_t0) * 1000,
                    mode=response_mode,
                    tokens=tokens_sent[0],
                    chars=len(final_text),
                )
                await ws.send_json({"type": "done"})
            except Exception:
                return

    except (WebSocketDisconnect, Exception):
        pass

# ---------------------------------------------------------------------------
# WebSocket: voice (STT → agent → TTS)
# ---------------------------------------------------------------------------

@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    """
    Voice conversation loop.

    Client sends:  {"type": "audio", "data": "<base64 float32 PCM>", "rate": 16000}
    Server sends:  {"type": "status",     "content": "..."}     — progress label
                   {"type": "transcript", "text": "..."}         — Whisper result
                   {"type": "step",       "content": "..."}      — ReAct loop step
                   {"type": "token",      "content": "..."}      — streaming token
                   {"type": "response",   "content": "..."}      — full response (Claude path)
                   {"type": "tts_audio",  "data": "<base64 mp3>"} — TTS output
                   {"type": "done"}
                   {"type": "error",      "content": "..."}
    """
    await ws.accept()
    run_agent = _import_agent()
    voice     = _get_voice()
    loop      = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") != "audio":
                continue
            turn_t0 = time.perf_counter()

            b64_audio = data.get("data", "")
            if not isinstance(b64_audio, str) or not b64_audio:
                await ws.send_json({"type": "error", "content": "Invalid audio payload"})
                await ws.send_json({"type": "done"})
                continue
            if len(b64_audio) > _VOICE_MAX_B64_CHARS:
                await ws.send_json({"type": "error", "content": "Audio payload too large"})
                await ws.send_json({"type": "done"})
                continue

            try:
                raw_bytes = base64.b64decode(b64_audio, validate=True)
            except Exception:
                await ws.send_json({"type": "error", "content": "Malformed base64 audio"})
                await ws.send_json({"type": "done"})
                continue

            if len(raw_bytes) > _VOICE_MAX_RAW_BYTES:
                await ws.send_json({"type": "error", "content": "Decoded audio exceeds size limit"})
                await ws.send_json({"type": "done"})
                continue

            try:
                sample_rate = int(data.get("rate", 16000))
            except Exception:
                await ws.send_json({"type": "error", "content": "Invalid sample rate"})
                await ws.send_json({"type": "done"})
                continue
            if sample_rate < _VOICE_MIN_RATE or sample_rate > _VOICE_MAX_RATE:
                await ws.send_json({"type": "error", "content": "Unsupported sample rate"})
                await ws.send_json({"type": "done"})
                continue

            voice_profile = _effective_voice_profile(data.get("voice_profile"))
            _loop_mode    = bool(data.get("loop", False))

            # ── 1. Transcribe ──────────────────────────────────────────────
            await ws.send_json({"type": "status", "content": "Transcribing…"})

            if voice is None:
                await ws.send_json({"type": "error", "content": "Voice module not available"})
                await ws.send_json({"type": "done"})
                continue

            text = await loop.run_in_executor(
                None, lambda: voice.transcribe(raw_bytes, sample_rate)
            )

            if not text:
                await ws.send_json({"type": "error", "content": "Could not understand audio"})
                await ws.send_json({"type": "done"})
                continue

            await ws.send_json({"type": "transcript", "text": text})
            if voice and text:
                try:
                    await _play_processing_prelude(ws, voice, voice_profile)
                except WebSocketDisconnect:
                    return
            await ws.send_json({"type": "status", "content": "Thinking…"})

            # ── 2. Run agent ───────────────────────────────────────────────
            collected_tokens: list[str] = []
            first_token_at = [None]
            first_audio_at = [None]

            # Streaming TTS state (same pattern as ws_chat)
            _vs_buf: list[str] = []
            _vs_seq = [0]
            _vs_pending: list = []
            _vstt2_live = (
                voice
                and hasattr(voice, "_styletts2_available")
                and voice._styletts2_available()
            )

            def _fire_vs_sentence(sentence: str) -> None:
                sentence = sentence.strip()
                if not sentence:
                    return
                clean = re.sub(r'\*+|`+|^#+\s+', '', sentence, flags=re.MULTILINE).strip()
                if not clean:
                    return
                seq = _vs_seq[0]
                _vs_seq[0] += 1

                async def _do(s=clean, q=seq):
                    try:
                        wav = await loop.run_in_executor(None, lambda: voice._synth_styletts2(s))
                        if wav:
                            if hasattr(voice, "_postprocess_wav_bytes"):
                                wav = voice._postprocess_wav_bytes(wav, voice_profile)
                            if first_audio_at[0] is None:
                                first_audio_at[0] = time.perf_counter()
                                _record_latency(
                                    "ws_voice_first_audio_ms",
                                    (first_audio_at[0] - turn_t0) * 1000,
                                    mode="spoken",
                                    streaming=True,
                                )
                            await ws.send_json({
                                "type": "tts_chunk",
                                "data": base64.b64encode(wav).decode(),
                                "format": "wav",
                                "seq": q,
                            })
                    except WebSocketDisconnect:
                        pass
                    except Exception as exc:
                        logger.debug(f"Voice streaming TTS seq={q}: {exc}")

                _vs_pending.append(asyncio.run_coroutine_threadsafe(_do(), loop))

            def _drain_vs_buf() -> None:
                buf = "".join(_vs_buf)
                has_hard_boundary = re.search(r'[.!?]["\']?\s', buf)
                has_soft_boundary = len(buf) >= _STREAM_SENTENCE_SOFT_CHARS and re.search(r'[,;:]\s', buf)
                if len(buf) < _STREAM_SENTENCE_MIN_CHARS or not (has_hard_boundary or has_soft_boundary):
                    return
                parts = (
                    voice.split_sentences(buf)
                    if hasattr(voice, "split_sentences")
                    else re.split(r'(?<=[.!?])\s+', buf, maxsplit=1)
                )
                if len(parts) < 2:
                    return
                for s in parts[:-1]:
                    _fire_vs_sentence(s)
                _vs_buf.clear()
                if parts[-1]:
                    _vs_buf.append(parts[-1])

            def on_step(msg: str):
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "step", "content": msg}), loop
                )

            def on_token(tok: str):
                collected_tokens.append(tok)
                if first_token_at[0] is None:
                    first_token_at[0] = time.perf_counter()
                    _record_latency(
                        "ws_voice_ttft_ms",
                        (first_token_at[0] - turn_t0) * 1000,
                        mode="spoken",
                    )
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "token", "content": tok}), loop
                )
                if _vstt2_live:
                    _vs_buf.append(tok)
                    _drain_vs_buf()

            if run_agent is None:
                final_text = "Agent is unavailable right now."
                await ws.send_json({"type": "response", "content": final_text})
            else:
                try:
                    _resp_mode = "loop" if _loop_mode else "spoken"
                    response = await loop.run_in_executor(
                        None,
                        lambda: run_agent(text, on_step=on_step, on_token=on_token, ollama_options=dict(_gemma_params), response_mode=_resp_mode),
                    )
                    if collected_tokens:
                        final_text = "".join(collected_tokens)
                    else:
                        # Claude tool-use path — full response, no tokens
                        final_text = response or ""
                    # Always send final authoritative text so the client can
                    # overwrite streamed partials with the cleaned final output.
                    await ws.send_json({"type": "response", "content": final_text})
                except Exception as e:
                    await ws.send_json({"type": "error", "content": str(e)})
                    await ws.send_json({"type": "done"})
                    continue

            # Flush remaining partial sentence and await all streaming synthesis
            if _vstt2_live:
                remaining = "".join(_vs_buf).strip()
                if remaining:
                    _fire_vs_sentence(remaining)
                    _vs_buf.clear()
                if _vs_pending:
                    await asyncio.gather(
                        *[asyncio.wrap_future(f) for f in _vs_pending],
                        return_exceptions=True,
                    )

            spoken_result = _rewrite_for_speech(final_text, user_query=text)
            spoken_text = spoken_result.get("spoken_text", final_text).strip() or final_text
            if spoken_text != final_text:
                await ws.send_json({"type": "spoken_preview", "content": spoken_text, "notes": spoken_result.get("notes", [])})
            threading.Thread(
                target=_save_spoken_exchange,
                args=(text, final_text, spoken_text, "spoken", voice_profile),
                daemon=True,
            ).start()

            # ── 3. TTS — sentence streaming ────────────────────────────────
            try:
                await ws.send_json({"type": "status", "content": "Speaking…"})
            except Exception:
                # Client already gone — abandon this request quietly.
                continue

            async def _send_voice_chunk(audio_bytes: bytes, fmt: str, seq: int) -> None:
                try:
                    await ws.send_json({
                        "type":   "tts_chunk",
                        "data":   base64.b64encode(audio_bytes).decode(),
                        "format": fmt,
                        "seq":    seq,
                    })
                    if first_audio_at[0] is None:
                        first_audio_at[0] = time.perf_counter()
                        _record_latency(
                            "ws_voice_first_audio_ms",
                            (first_audio_at[0] - turn_t0) * 1000,
                            mode="spoken",
                            streaming=False,
                        )
                except Exception as send_exc:
                    # Translate send-after-close into a normal disconnect so
                    # synthesize_streaming can unwind without logging a traceback.
                    raise WebSocketDisconnect() from send_exc

            try:
                if not _vs_pending:
                    await asyncio.wait_for(
                        voice.synthesize_streaming(
                            spoken_text,
                            _send_voice_chunk,
                            voice_profile=voice_profile,
                        ),
                        timeout=60.0,
                    )
            except asyncio.TimeoutError:
                logger.error("TTS timed out after 60s")
                try:
                    await ws.send_json({"type": "tts_error", "content": "TTS timed out"})
                except Exception:
                    pass
            except WebSocketDisconnect:
                # Client closed the socket mid-stream — nothing more to do.
                return
            except Exception as e:
                logger.error(f"TTS error: {e}")
                try:
                    await ws.send_json({"type": "tts_error", "content": str(e)})
                except Exception:
                    pass

            try:
                _record_latency(
                    "ws_voice_total_ms",
                    (time.perf_counter() - turn_t0) * 1000,
                    mode="spoken",
                    tokens=len(collected_tokens),
                    chars=len(final_text),
                )
                await ws.send_json({"type": "done"})
            except Exception:
                return

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Voice WS error: {e}", exc_info=True)
        try:
            await ws.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Serve voice profile previews (for selecting reference clips)
# ---------------------------------------------------------------------------

_VOICES_DIR = Path(__file__).parent / "voices"
if _VOICES_DIR.exists():
    app.mount("/voices", StaticFiles(directory=str(_VOICES_DIR)), name="voices")


# ---------------------------------------------------------------------------
# Avalon — datacenter siting (phase7) bridge
# ---------------------------------------------------------------------------

_PHASE7 = _ROOT / "phase7-datacenter-siting"
if str(_PHASE7) not in sys.path:
    sys.path.insert(0, str(_PHASE7))


def _import_siting():
    """Lazy import of phase7 scoring engine. Returns module bundle or None."""
    try:
        from src import config as siting_config  # type: ignore
        from src.score import Site, score_sites  # type: ignore
        from src.factors import FACTOR_REGISTRY  # type: ignore
        return {
            "config": siting_config,
            "Site": Site,
            "score_sites": score_sites,
            "FACTOR_REGISTRY": FACTOR_REGISTRY,
        }
    except Exception as e:
        logger.warning(f"phase7 siting unavailable: {e}")
        return None


def _load_sample_sites() -> list[dict]:
    import csv as _csv
    csv_path = _PHASE7 / "config" / "sample_sites.csv"
    out: list[dict] = []
    if not csv_path.exists():
        return out
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            try:
                out.append({
                    "site_id": row["site_id"],
                    "name":    row.get("name", row["site_id"]),
                    "lat":     float(row["lat"]),
                    "lon":     float(row["lon"]),
                    "acres":   float(row["acres"]) if row.get("acres") else None,
                    "state":   row.get("state", ""),
                    "notes":   row.get("notes", ""),
                })
            except (KeyError, ValueError):
                continue
    return out


@app.get("/api/siting/health")
def siting_health():
    """Report whether the phase7 engine is wired up."""
    bundle = _import_siting()
    if not bundle:
        return {"ok": False, "error": "phase7 module not importable"}
    cfg = bundle["config"]
    return {
        "ok":          True,
        "factors":     list(cfg.FACTOR_NAMES),
        "archetypes":  ["training", "inference", "mixed"],
        "default":     cfg.DEFAULT_ARCHETYPE,
        "sample_path": str(_PHASE7 / "config" / "sample_sites.csv"),
    }


@app.get("/api/siting/factors")
def siting_factors():
    """Return factor catalog with current implementation status."""
    bundle = _import_siting()
    if not bundle:
        return JSONResponse({"error": "phase7 unavailable"}, status_code=503)
    cfg = bundle["config"]
    # Probe each factor with a dummy site to detect stub_result vs real impl
    Site = bundle["Site"]
    probe = Site(site_id="_probe", lat=39.0, lon=-77.6)  # Loudoun VA
    out = []
    for fname in cfg.FACTOR_NAMES:
        fn = bundle["FACTOR_REGISTRY"][fname]
        try:
            res = fn(probe)
            prov = res.provenance or {}
            is_stub = bool(prov.get("stub")) or "TODO" in str(prov)
            out.append({
                "name":       fname,
                "implemented": not is_stub,
                "provenance": prov,
            })
        except Exception as e:
            out.append({"name": fname, "implemented": False, "provenance": {"error": repr(e)}})
    return {"factors": out}


@app.get("/api/siting/weights")
def siting_weights(archetype: str = "training"):
    """Return factor weights for the requested archetype."""
    bundle = _import_siting()
    if not bundle:
        return JSONResponse({"error": "phase7 unavailable"}, status_code=503)
    try:
        weights = bundle["config"].load_weights(archetype)  # type: ignore[arg-type]
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"archetype": archetype, "weights": weights}


@app.get("/api/siting/sample")
def siting_sample():
    """Return the sample sites catalog (for map markers + scoring)."""
    return {"sites": _load_sample_sites()}


class SitingScoreRequest(BaseModel):
    archetype: Optional[str] = "training"
    weight_overrides: Optional[dict] = None
    sites: Optional[list[dict]] = None  # if omitted, scores the sample catalog


@app.post("/api/siting/score")
def siting_score(body: SitingScoreRequest):
    """Score a cohort of sites and return composite + per-factor breakdowns."""
    bundle = _import_siting()
    if not bundle:
        return JSONResponse({"error": "phase7 unavailable"}, status_code=503)

    raw_sites = body.sites if body.sites else _load_sample_sites()
    if not raw_sites:
        return JSONResponse({"error": "no sites provided"}, status_code=400)

    Site = bundle["Site"]
    sites = []
    for s in raw_sites:
        try:
            sites.append(Site(
                site_id=str(s["site_id"]),
                lat=float(s["lat"]),
                lon=float(s["lon"]),
                extras={k: v for k, v in s.items() if k not in {"site_id", "lat", "lon"}},
            ))
        except (KeyError, ValueError, TypeError):
            continue

    try:
        results = bundle["score_sites"](
            sites,
            archetype=body.archetype or "training",  # type: ignore[arg-type]
            weight_overrides=body.weight_overrides,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"siting score error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

    # Merge geometry back in for the client (lat/lon/name)
    by_id = {s["site_id"]: s for s in raw_sites}
    enriched = []
    for r in results:
        d = r.to_dict()
        meta = by_id.get(r.site_id, {})
        d["lat"]   = meta.get("lat")
        d["lon"]   = meta.get("lon")
        d["name"]  = meta.get("name", r.site_id)
        d["state"] = meta.get("state", "")
        d["acres"] = meta.get("acres")
        enriched.append(d)
    enriched.sort(key=lambda d: d["composite"], reverse=True)
    return {
        "archetype": body.archetype or "training",
        "count":     len(enriched),
        "results":   enriched,
    }


# ---------------------------------------------------------------------------
# Dev orchestration — task queue, file tools, Claude delegation
# ---------------------------------------------------------------------------

import importlib.util as _ilu

def _import_dev_tools():
    try:
        spec = _ilu.spec_from_file_location("dev_tools", Path(__file__).parent / "dev_tools.py")
        mod = _ilu.module_from_spec(spec)
        import sys as _sys
        _sys.modules["dev_tools"] = mod   # required: @dataclass resolves cls.__module__ via sys.modules
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        logger.warning(f"dev_tools unavailable: {e}")
        return None

_dev = _import_dev_tools()

# Wire the asyncio event loop into dev_tools so it can broadcast WS events
# from background threads. Done once at first request rather than at import
# time to ensure the loop is running.
_dev_loop_wired = False

def _wire_dev_loop():
    global _dev_loop_wired
    if _dev and not _dev_loop_wired:
        try:
            _dev.set_event_loop(asyncio.get_event_loop())
            _dev_loop_wired = True
        except Exception:
            pass


class _DevTaskRequest(BaseModel):
    goal: str
    project: str
    context_files: list[str] = []


class _ApplyPatchRequest(BaseModel):
    project: str
    path: str
    proposed: str
    task_id: str = ""


@app.get("/api/dev/projects")
def dev_projects():
    """List configured project names and whether their roots exist."""
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return {
        "projects": [
            {"name": k, "exists": v.exists()}
            for k, v in _dev.PROJECT_ROOTS.items()
        ]
    }


@app.get("/api/dev/tasks")
def dev_list_tasks(project: str = ""):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    tasks = _dev.list_tasks(project or None)
    return {"tasks": [t.to_dict() for t in tasks]}


@app.post("/api/dev/tasks")
async def dev_create_task(body: _DevTaskRequest):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    if not body.goal.strip():
        return JSONResponse({"error": "goal is required"}, status_code=400)
    task = _dev.create_task(
        goal=body.goal.strip(),
        project=body.project,
        context_files=body.context_files,
    )
    # Run in background thread — non-blocking
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _dev.run_task_sync, task.id)
    return {"task_id": task.id, "status": task.status}


@app.get("/api/dev/tasks/{task_id}")
def dev_get_task(task_id: str):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    task = _dev.get_task(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)
    return task.to_dict()


@app.get("/api/dev/diff")
def dev_git_diff(project: str):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.get_git_diff(project)


@app.get("/api/dev/files")
def dev_file_tree(project: str, path: str = ""):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.get_file_tree(project, path)


@app.get("/api/dev/file")
def dev_read_file(project: str, path: str, password: str = ""):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.read_file_contents(project, path, password)


@app.post("/api/dev/apply")
def dev_apply_patch(body: _ApplyPatchRequest):
    """Apply an approved patch to disk."""
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    result = _dev.apply_patch(body.project, body.path, body.proposed)
    if body.task_id:
        # Mark the patch as accepted in the task record
        task = _dev.get_task(body.task_id)
        if task:
            for p in task.patches:
                if p["path"] == body.path:
                    p["status"] = "accepted"
    return result


class _GitCommitPushRequest(BaseModel):
    project: str
    message: str
    push: bool = True


class _GitPullRequest(BaseModel):
    project: str


@app.get("/api/dev/git/status")
def dev_git_status(project: str):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.git_status_summary(project)


@app.post("/api/dev/git/commit-push")
def dev_git_commit_push(body: _GitCommitPushRequest):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.git_commit_push(body.project, body.message, body.push)


@app.post("/api/dev/git/pull")
def dev_git_pull(body: _GitPullRequest):
    _wire_dev_loop()
    if not _dev:
        return JSONResponse({"error": "dev_tools unavailable"}, status_code=503)
    return _dev.git_pull(body.project)


@app.websocket("/ws/dev")
async def ws_dev(ws: WebSocket):
    """Stream DevTask events to the DevPanel in real time."""
    # Password gate — same as REST middleware
    provided = ws.query_params.get("password", "")
    if provided != _DEV_PANEL_PASSWORD:
        await ws.close(code=4401)
        return
    await ws.accept()
    _wire_dev_loop()
    if not _dev:
        await ws.send_json({"kind": "error", "message": "dev_tools unavailable"})
        return

    q = _dev.subscribe_ws()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=20.0)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                await ws.send_json({"kind": "ping"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _dev.unsubscribe_ws(q)


# ---------------------------------------------------------------------------
# Serve compiled React SPA (production)
# ---------------------------------------------------------------------------

if _CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_CLIENT_DIST / "assets")), name="assets")

    def _spa_index_response():
        index = _CLIENT_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
        return JSONResponse({"error": "client not built — run: npm run build"}, status_code=404)

    @app.get("/mithrandir/assets/{asset_path:path}")
    def spa_prefixed_assets(asset_path: str):
        asset = (_CLIENT_DIST / "assets" / asset_path).resolve()
        assets_root = (_CLIENT_DIST / "assets").resolve()
        if asset.is_file() and (asset == assets_root or assets_root in asset.parents):
            return FileResponse(str(asset))
        return _spa_index_response()

    @app.get("/mithrandir")
    @app.get("/mithrandir/")
    def spa_prefixed_root():
        return _spa_index_response()

    @app.get("/mithrandir/favicon.svg")
    def spa_prefixed_favicon():
        icon = _CLIENT_DIST / "favicon.svg"
        if icon.exists():
            return FileResponse(str(icon))
        return _spa_index_response()

    @app.get("/mithrandir/icons.svg")
    def spa_prefixed_icons():
        icon = _CLIENT_DIST / "icons.svg"
        if icon.exists():
            return FileResponse(str(icon))
        return _spa_index_response()

    @app.get("/mithrandir/{full_path:path}")
    def spa_prefixed_fallback(full_path: str):
        return _spa_index_response()

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        return _spa_index_response()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # reload=False: the server writes server.log, test_tts.wav and touches voices/
    # during TTS. watchfiles would restart the process mid-stream and kill in-flight
    # WebSocket TTS chunks before the browser plays them. Only /api/test-audio
    # survives reload (single fast HTTP response), which is why that was audible
    # while chat/voice TTS was not.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
