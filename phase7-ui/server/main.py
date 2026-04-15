"""
phase7-ui/server/main.py — Enkidu UI backend (FastAPI)

Endpoints:
  GET  /api/health
  GET  /api/params            current Gemma4 generation params
  POST /api/params            update Gemma4 generation params
  POST /api/chat              non-streaming chat (fallback)
  GET  /api/portfolio         top QV picks
  GET  /api/regime            current HMM market regime
  GET  /api/history           recent conversation history
  WS   /ws/gpu                real-time GPU/CPU/RAM stats at 2 Hz
  WS   /ws/chat               streaming chat tokens

Serves compiled React SPA from ../client/dist in production.
"""

import asyncio
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent.parent / ".env")

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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

def _import_regime():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("regime_detector", _PHASE3 / "tools" / "regime_detector.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_regime
    except Exception as e:
        logger.warning(f"regime_detector unavailable: {e}")
        return None

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

def _gpu_stats() -> dict:
    """Query live GPU stats. Returns zeros if nvidia-smi is unavailable."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,"
                "memory.used,memory.total,temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ],
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        parts = [p.strip() for p in out.split(",")]
        return {
            "gpu_util":    float(parts[0]),
            "mem_util":    float(parts[1]),
            "vram_used":   float(parts[2]),
            "vram_total":  float(parts[3]),
            "temp":        float(parts[4]),
            "power_draw":  float(parts[5].replace("N/A", "0")),
            "power_limit": float(parts[6].replace("N/A", "300")),
        }
    except Exception:
        return {
            "gpu_util": 0, "mem_util": 0,
            "vram_used": 0, "vram_total": 24576,
            "temp": 0, "power_draw": 0, "power_limit": 300,
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
    "repeat_penalty": 1.1,
    "num_ctx":        8192,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "version": "7.0.0"}


@app.get("/api/params")
def get_params():
    return _gemma_params


class ParamsUpdate(BaseModel):
    temperature:    Optional[float] = None
    top_p:          Optional[float] = None
    top_k:          Optional[int]   = None
    repeat_penalty: Optional[float] = None
    num_ctx:        Optional[int]   = None
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


@app.get("/api/portfolio")
def get_portfolio():
    try:
        import pandas as pd
        qv_path = Path("C:/Users/benpa/QuantitativeValue/data/processed/quantitative_value_portfolio.csv")
        if not qv_path.exists():
            return {"picks": [], "error": "portfolio CSV not found"}
        df = pd.read_csv(qv_path)
        top = df.head(25)
        cols = [c for c in ["ticker", "sector", "ev_ebit", "value_composite", "quality_score", "f_score"] if c in top.columns]
        return {"picks": top[cols].fillna("").to_dict(orient="records")}
    except Exception as e:
        return {"picks": [], "error": str(e)}


@app.get("/api/history")
def get_history():
    try:
        import sqlite3
        db_candidates = [
            _ROOT / "phase4-memory" / "enkidu_memory.db",
            _ROOT / "phase4-memory" / "memory.db",
        ]
        db_path = next((p for p in db_candidates if p.exists()), None)
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

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    run_agent = _import_agent()
    try:
        while True:
            data = await ws.receive_json()
            message = data.get("message", "").strip()
            if not message:
                continue

            # Stream progress steps back to client
            loop = asyncio.get_running_loop()

            def on_step(msg: str):
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "step", "content": msg}),
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
                    lambda: run_agent(message, on_step=on_step),
                )
                await ws.send_json({"type": "response", "content": response})
            except Exception as e:
                await ws.send_json({"type": "error", "content": str(e)})

            await ws.send_json({"type": "done"})

    except (WebSocketDisconnect, Exception):
        pass

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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
