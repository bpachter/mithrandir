"""
Enkidu Gateway — Railway-hosted reverse proxy to home GPU via Cloudflare Tunnel.

Set GPU_URL env var to your Cloudflare tunnel base URL, e.g.:
  GPU_URL=https://your-tunnel-name.trycloudflare.com

Forwards all /api/* HTTP requests and /ws/* WebSocket connections to the home GPU.
Returns a 503 with a friendly message if the GPU is offline.
"""

import asyncio
import logging
import os
import time
import json

import httpx
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

GPU_URL = os.environ.get("GPU_URL", "").strip().rstrip("/")
VOICE_GPU_URL = os.environ.get("VOICE_GPU_URL", "").strip().rstrip("/")
ENKIDU_UI_URL = os.environ.get("ENKIDU_UI_URL", "").strip()
VOICE_UPSTREAM_COOLDOWN_SEC = int(os.environ.get("VOICE_UPSTREAM_COOLDOWN_SEC", "20"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("enkidu.gateway")

app = FastAPI(title="Enkidu Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bpachter.github.io",
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_OFFLINE_BODY = b'{"error":"Home GPU is offline or tunnel is down","online":false}'
_NO_CONFIG_BODY = b'{"error":"GPU_URL not configured","online":false}'

# When upstream repeatedly rejects /ws/voice (commonly Cloudflare 502 while the
# home GPU origin is unavailable), clients can reconnect in a tight loop.
# Use a short cooldown to fast-fail subsequent attempts and reduce log storms.
_voice_block_until = 0.0

_PARAMS_FALLBACK = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.0,
    "repeat_penalty": 1.1,
    "num_ctx": 8192,
    "num_predict": 2048,
    "seed": -1,
    "gateway_fallback": True,
}


def _fallback_api(path: str) -> tuple[dict, int] | None:
    """Return fallback JSON payloads for critical UI endpoints during outages."""
    path = path.strip("/")
    if path == "params":
        return _PARAMS_FALLBACK, 200
    if path == "portfolio":
        return {
            "picks": [],
            "error": "upstream unavailable (gateway fallback)",
            "provenance": None,
            "gateway_fallback": True,
        }, 200
    if path == "regime":
        return {
            "regime": "Unknown",
            "confidence": 0,
            "error": "upstream unavailable (gateway fallback)",
            "gateway_fallback": True,
        }, 200
    if path == "history":
        return {
            "exchanges": [],
            "error": "upstream unavailable (gateway fallback)",
            "gateway_fallback": True,
        }, 200
    if path == "voices":
        return {
            "voices": ["default", "bm_george", "bm_lewis", "am_adam", "am_michael", "af_heart", "bf_emma", "bf_isabella"],
            "active": "default",
            "gateway_fallback": True,
        }, 200
    if path == "memory":
        return {
            "entries": [],
            "stats": {
                "total": 0,
                "rated": 0,
                "avg_score": None,
            },
            "gateway_fallback": True,
            "error": "upstream unavailable (gateway fallback)",
        }, 200
    return None


def _generic_fallback_api(path: str) -> tuple[dict, int]:
    return {
        "gateway_fallback": True,
        "error": "upstream unavailable (gateway fallback)",
        "path": path.strip("/"),
    }, 200


@app.get("/")
def root():
    """Open a browser-friendly landing target for the gateway base URL."""
    if ENKIDU_UI_URL:
        return RedirectResponse(url=ENKIDU_UI_URL, status_code=307)
    return JSONResponse(
        {
            "ok": True,
            "service": "Enkidu Gateway",
            "health": "/api/health",
            "note": "Set ENKIDU_UI_URL to redirect browser traffic to your UI.",
        }
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "gpu_url_configured": bool(GPU_URL),
        "voice_gpu_url_configured": bool(VOICE_GPU_URL),
    }


@app.get("/api/probe")
async def probe():
    """Diagnostic: attempt a real connection to GPU_URL and return error details."""
    if not GPU_URL:
        return {"gpu_url": None, "error": "GPU_URL not set"}
    import traceback
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            r = await client.get(f"{GPU_URL}/api/health")
            return {"gpu_url": GPU_URL, "status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        return {"gpu_url": GPU_URL, "error_type": type(e).__name__, "error": str(e), "trace": traceback.format_exc()[-500:]}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(request: Request, path: str):
    if not GPU_URL:
        return Response(content=_NO_CONFIG_BODY, status_code=503, media_type="application/json")

    qs = ("?" + str(request.query_params)) if request.query_params else ""
    url = f"{GPU_URL}/api/{path}{qs}"
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "connection", "transfer-encoding", "accept-encoding"}
    }

    try:
        async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=await request.body(),
            )

        # Graceful degradation for key UI reads when upstream is returning 5xx.
        if request.method == "GET" and resp.status_code >= 500:
            fb = _fallback_api(path)
            if fb is not None:
                body, code = fb
                return JSONResponse(body, status_code=code)
            body, code = _generic_fallback_api(path)
            return JSONResponse(body, status_code=code)

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except Exception as e:
        logger.warning("GPU proxy error (%s): %s", type(e).__name__, e)
        if request.method == "GET":
            fb = _fallback_api(path)
            if fb is not None:
                body, code = fb
                return JSONResponse(body, status_code=code)
            body, code = _generic_fallback_api(path)
            return JSONResponse(body, status_code=code)
        return Response(content=_OFFLINE_BODY, status_code=503, media_type="application/json")


@app.websocket("/ws/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str):
    global _voice_block_until

    ws_base = VOICE_GPU_URL if path == "voice" and VOICE_GPU_URL else GPU_URL

    if not ws_base:
        await websocket.close(code=1011, reason="GPU_URL not configured")
        return

    now = time.time()
    if path == "voice" and now < _voice_block_until:
        remaining = int(max(1, _voice_block_until - now))
        await websocket.accept()
        await websocket.close(code=1013, reason=f"Voice upstream cooling down ({remaining}s)")
        return

    ws_url = ws_base.replace("https://", "wss://").replace("http://", "ws://")
    target = f"{ws_url}/ws/{path}"

    await websocket.accept()
    logger.info("WS proxy: %s → %s", path, target)

    try:
        async with websockets.connect(target, open_timeout=10) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await upstream.send(data)
                except (WebSocketDisconnect, Exception):
                    pass
                finally:
                    try:
                        await upstream.close()
                    except Exception:
                        pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        text = message if isinstance(message, str) else message.decode()
                        await websocket.send_text(text)
                except (websockets.ConnectionClosed, Exception):
                    pass
                finally:
                    try:
                        await websocket.close()
                    except Exception:
                        pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())

    except Exception as e:
        if path == "voice":
            _voice_block_until = time.time() + max(1, VOICE_UPSTREAM_COOLDOWN_SEC)
        if path == "gpu":
            # Keep UI alive with a lightweight stub stream while upstream is down.
            try:
                while True:
                    payload = {
                        "gpu_util": 0,
                        "mem_util": 0,
                        "vram_used": 0,
                        "vram_total": 0,
                        "temp": 0,
                        "power_draw": 0,
                        "power_limit": 0,
                        "clock_sm": 0,
                        "clock_mem": 0,
                        "fan_speed": 0,
                        "cpu_percent": 0,
                        "ram_used_gb": 0,
                        "ram_total_gb": 0,
                        "ram_percent": 0,
                        "ts": time.time(),
                        "gateway_fallback": True,
                        "upstream_error": "gpu upstream unavailable",
                    }
                    await websocket.send_text(json.dumps(payload))
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            try:
                await websocket.close(code=1011, reason="GPU upstream unavailable")
            except Exception:
                pass
            return
        logger.warning("WS upstream unreachable (%s): %s", path, e)
        try:
            await websocket.close(code=1011, reason="Home GPU offline or upstream rejected")
        except Exception:
            pass
