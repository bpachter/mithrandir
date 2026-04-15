"""
enkidu_openwebui_bridge.py — local HTTP bridge for Open WebUI

Exposes the Enkidu Phase 3 agent over a small local HTTP API so Open WebUI can
call it as a native custom function without using any OpenAI-compatible API.

Endpoints:
    GET  /health
    POST /chat

Example request:
    {
      "messages": [{"role": "user", "content": "Compare NUE and CLF"}],
      "save_memory": true
    }

Example response:
    {
      "response": "...",
      "steps": ["🔧 Calling `edgar_screener`..."],
      "model": "enkidu"
    }
"""

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

load_dotenv()

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from enkidu_agent import run_agent  # noqa: E402


HOST = os.environ.get("ENKIDU_OPENWEBUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("ENKIDU_OPENWEBUI_PORT", "8011"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("ENKIDU_OPENWEBUI_MAX_CONTEXT_MESSAGES", "10"))


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("enkidu.openwebui")


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = item.get("type", "")
            if item_type in {"text", "input_text"} and item.get("text"):
                parts.append(item["text"])
            elif item_type == "text" and item.get("content"):
                parts.append(item["content"])
            elif "text" in item and isinstance(item["text"], str):
                parts.append(item["text"])

        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

    return ""


def _build_agent_input(messages, fallback_message: str = "") -> str:
    normalized = []
    for message in (messages or [])[-MAX_CONTEXT_MESSAGES:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "user")
        if role not in {"user", "assistant", "system"}:
            role = "user"
        text = _extract_text(message.get("content", ""))
        if text:
            normalized.append((role, text))

    if not normalized:
        return fallback_message.strip()

    if len(normalized) == 1 and normalized[0][0] == "user":
        return normalized[0][1]

    lines = [
        "Use the conversation transcript below as context for the current request.",
        "",
        "Conversation transcript:",
    ]

    for role, text in normalized[:-1]:
        label = {"system": "System", "user": "User", "assistant": "Assistant"}[role]
        lines.append(f"{label}: {text}")

    last_role, last_text = normalized[-1]
    lines.append("")
    if last_role == "user":
        lines.append(f"Current user request: {last_text}")
    else:
        lines.append(f"Latest conversation state: {last_text}")
        if fallback_message.strip():
            lines.append(f"Current user request: {fallback_message.strip()}")

    lines.append("")
    lines.append("Answer the current user request using the conversation context above.")
    return "\n".join(lines)


class _Handler(BaseHTTPRequestHandler):
    server_version = "EnkiduOpenWebUI/0.1"

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "service": "enkidu-openwebui-bridge"})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/chat":
            self._send_json(404, {"error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)

        try:
            body = json.loads(raw.decode("utf-8") if raw else "{}")
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"invalid_json: {e}"})
            return

        messages = body.get("messages", [])
        fallback_message = str(body.get("message", ""))
        save_memory = bool(body.get("save_memory", True))

        user_message = _build_agent_input(messages, fallback_message)
        if not user_message:
            self._send_json(400, {"error": "empty_message"})
            return

        steps = []

        def on_step(msg: str):
            steps.append(msg)

        try:
            response = run_agent(user_message, on_step=on_step, save_memory=save_memory)
        except Exception as e:
            logger.exception("Bridge request failed")
            self._send_json(500, {"error": str(e)})
            return

        self._send_json(
            200,
            {
                "response": response,
                "steps": steps,
                "model": "enkidu",
            },
        )


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    logger.info("Enkidu Open WebUI bridge listening on http://%s:%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()