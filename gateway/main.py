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

import httpx
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

GPU_URL = os.environ.get("GPU_URL", "").strip().rstrip("/")
ENKIDU_UI_URL = os.environ.get("ENKIDU_UI_URL", "").strip()

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
    return {"ok": True, "gpu_url_configured": bool(GPU_URL)}


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
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except Exception as e:
        logger.warning("GPU proxy error (%s): %s", type(e).__name__, e)
        return Response(content=_OFFLINE_BODY, status_code=503, media_type="application/json")


@app.websocket("/ws/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str):
    if not GPU_URL:
        await websocket.close(code=1011, reason="GPU_URL not configured")
        return

    ws_url = GPU_URL.replace("https://", "wss://").replace("http://", "ws://")
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
        logger.warning("WS upstream unreachable (%s): %s", path, e)
        try:
            await websocket.close(code=1011, reason="Home GPU offline")
        except Exception:
            pass
