"""
phase6-ui/server/main.py — Enkidu UI backend (FastAPI)

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

_FORCED_VOICE_PROFILE = os.environ.get("ENKIDU_FORCE_VOICE_PROFILE", "").strip()

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
# Paths — reach back into the Enkidu monorepo
# ---------------------------------------------------------------------------

_ROOT     = Path(__file__).parent.parent.parent
_PHASE3   = _ROOT / "phase3-agents"
_PHASE2T  = _ROOT / "phase2-tool-use" / "tools"
_PHASE5   = _ROOT / "phase5-intelligence"
_CLIENT_DIST = Path(__file__).parent.parent / "client" / "dist"

for p in [str(_PHASE3), str(_PHASE3 / "tools"), str(_PHASE2T), str(_PHASE5)]:
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
logger = logging.getLogger("enkidu.ui")

# ---------------------------------------------------------------------------
# Lazy imports (don't crash if a subsystem is unavailable)
# ---------------------------------------------------------------------------

def _import_agent():
    try:
        from enkidu_agent import run_agent
        return run_agent
    except Exception as e:
        logger.warning(f"enkidu_agent unavailable: {e}")
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

_DEFAULT_PARAMS = {
    "temperature":    0.7,
    "top_p":          0.9,
    "top_k":          40,
    "min_p":          0.0,
    "repeat_penalty": 1.1,
    "num_ctx":        8192,
    "num_predict":    2048,
    "seed":           -1,
}

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

app = FastAPI(title="Enkidu UI", version="7.0.0")

_VOICE_MAX_B64_CHARS = int(os.environ.get("ENKIDU_VOICE_MAX_B64_CHARS", "8000000"))
_VOICE_MAX_RAW_BYTES = int(os.environ.get("ENKIDU_VOICE_MAX_RAW_BYTES", "5000000"))
_VOICE_MIN_RATE = int(os.environ.get("ENKIDU_VOICE_MIN_SAMPLE_RATE", "8000"))
_VOICE_MAX_RATE = int(os.environ.get("ENKIDU_VOICE_MAX_SAMPLE_RATE", "48000"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Dev panel password gate — protects ALL /api/dev/* endpoints
# ---------------------------------------------------------------------------

_DEV_PANEL_PASSWORD = os.environ.get("ENKIDU_DEV_PASSWORD", "").strip() or "antifragile"


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

    ui_url = os.environ.get("ENKIDU_UI_URL", "").strip()
    return JSONResponse(
        {
            "ok": True,
            "service": "Enkidu API",
            "ui": ui_url or "not configured",
            "health": "/api/health",
            "docs": "/docs",
            "note": "Frontend build not found on this backend instance.",
        }
    )

@app.get("/api/health")
def health():
    return {"ok": True, "version": "7.0.0"}


@app.get("/api/health/detailed")
def health_detailed():
    """Run all subsystem health checks and return a full diagnostic report."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("enkidu_health", _ROOT / "enkidu_health.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        results = mod.run_all(parallel=True, timeout=20.0)
        return mod.summary(results)
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        return {"overall": "unknown", "error": str(e), "counts": {}, "checks": []}


@app.get("/api/params")
def get_params():
    return _gemma_params


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
        _ROOT / "phase4-memory" / "enkidu_memory.db",
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


@app.get("/api/freshness")
def get_freshness():
    """Return a data freshness audit for all Enkidu data sources."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("data_freshness", Path(__file__).parent / "data_freshness.py")
        mod = importlib.util.module_from_spec(spec)
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
        "Enkidu online. Audio system is working.",
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
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_agent(message)
        )
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

            conversation_id  = data.get("conversation_id")
            prior_messages   = _fetch_prior_messages(conversation_id) if conversation_id else []
            tts_enabled      = data.get("tts", True)   # client can opt out
            voice_profile_req = _effective_voice_profile(data.get("voice_profile"))

            loop = asyncio.get_running_loop()
            tokens_sent = [0]
            collected_tokens: list[str] = []

            def on_step(msg: str):
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "step", "content": msg}),
                    loop,
                )

            def on_token(tok: str):
                tokens_sent[0] += 1
                collected_tokens.append(tok)
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "token", "content": tok}),
                    loop,
                )

            if run_agent is None:
                await ws.send_json({"type": "error", "content": "Agent unavailable"})
                await ws.send_json({"type": "done"})
                continue

            # Run agent in thread pool (it's synchronous)
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: run_agent(message, on_step=on_step, on_token=on_token, prior_messages=prior_messages, ollama_options=dict(_gemma_params)),
                )
                if tokens_sent[0] == 0:
                    final_text = response or ""
                    await ws.send_json({"type": "response", "content": final_text})
                else:
                    final_text = "".join(collected_tokens)
            except Exception as e:
                await ws.send_json({"type": "error", "content": str(e)})
                await ws.send_json({"type": "done"})
                continue

            # TTS — sentence-split streaming: client starts playing sentence 0
            # while the server is synthesizing sentence 1, etc.
            if tts_enabled and voice and final_text.strip():
                if not hasattr(voice, "synthesize_streaming"):
                    # Server is running old voice.py — needs restart
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
                            seq += 1
                        except Exception as send_exc:
                            raise WebSocketDisconnect() from send_exc

                    try:
                        logger.info(f"TTS: synthesizing {len(final_text)} chars (profile={voice_profile_req!r})")
                        await asyncio.wait_for(
                            voice.synthesize_streaming(
                                final_text,
                                _send_chunk,
                                voice_profile=voice_profile_req,
                            ),
                            timeout=60.0,
                        )
                        if seq == 0:
                            # synthesize_streaming ran but sent nothing — all engines failed
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
            await ws.send_json({"type": "status", "content": "Thinking…"})

            # ── 2. Run agent ───────────────────────────────────────────────
            collected_tokens: list[str] = []

            def on_step(msg: str):
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "step", "content": msg}), loop
                )

            def on_token(tok: str):
                collected_tokens.append(tok)
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "token", "content": tok}), loop
                )

            if run_agent is None:
                final_text = "Agent is unavailable right now."
                await ws.send_json({"type": "response", "content": final_text})
            else:
                try:
                    response = await loop.run_in_executor(
                        None,
                        lambda: run_agent(text, on_step=on_step, on_token=on_token, ollama_options=dict(_gemma_params)),
                    )
                    if collected_tokens:
                        final_text = "".join(collected_tokens)
                    else:
                        # Claude tool-use path — full response, no tokens
                        final_text = response or ""
                        await ws.send_json({"type": "response", "content": final_text})
                except Exception as e:
                    await ws.send_json({"type": "error", "content": str(e)})
                    await ws.send_json({"type": "done"})
                    continue

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
                except Exception as send_exc:
                    # Translate send-after-close into a normal disconnect so
                    # synthesize_streaming can unwind without logging a traceback.
                    raise WebSocketDisconnect() from send_exc

            try:
                await asyncio.wait_for(
                    voice.synthesize_streaming(
                        final_text,
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

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        index = _CLIENT_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"error": "client not built — run: npm run build"}, status_code=404)


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
