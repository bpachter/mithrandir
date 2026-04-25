"""
title: Mithrandir Agent
author: benpa
author_url: https://github.com/bpachter/mithrandir
version: 0.1.0
required_open_webui_version: 0.6.0
"""

from typing import Generator, Iterator, Optional, Union

import requests
from pydantic import BaseModel, Field
from open_webui.utils.misc import get_last_user_message


class Pipe:
    class Valves(BaseModel):
        BRIDGE_URL: str = Field(
            default="http://host.docker.internal:8011/chat",
            description="URL of the local Mithrandir bridge endpoint",
        )
        REQUEST_TIMEOUT_SECONDS: int = Field(
            default=600,
            description="HTTP timeout for Mithrandir agent requests",
        )
        SAVE_MEMORY: bool = Field(
            default=True,
            description="Persist Open WebUI chats into Mithrandir's Phase 4 memory store",
        )

    def __init__(self):
        self.type = "pipe"
        self.name = "Mithrandir Agent"
        self.valves = self.Valves()

    def _make_title(self, body: dict) -> str:
        prompt = get_last_user_message(body.get("messages", [])) or "Mithrandir Chat"
        prompt = " ".join(prompt.split())
        if len(prompt) <= 60:
            return prompt
        return prompt[:57].rstrip() + "..."

    def _call_bridge(self, body: dict) -> str:
        payload = {
            "messages": body.get("messages", []),
            "save_memory": self.valves.SAVE_MEMORY,
        }

        response = requests.post(
            self.valves.BRIDGE_URL,
            json=payload,
            timeout=self.valves.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        data = response.json()
        if "response" in data:
            return data["response"]
        if "error" in data:
            return f"Error: {data['error']}"
        return "Error: malformed response from Mithrandir bridge"

    def pipe(self, body: dict, __user__: Optional[dict] = None) -> Union[str, Generator, Iterator]:
        if body.get("title", False):
            return self._make_title(body)

        if body.get("stream", False):
            def _stream():
                yield {
                    "event": {
                        "type": "status",
                        "data": {
                            "description": "Mithrandir agent running...",
                            "done": False,
                        },
                    }
                }
                try:
                    yield self._call_bridge(body)
                except Exception as e:
                    yield (
                        "Error: could not reach the local Mithrandir bridge. "
                        "Start mithrandir_openwebui_bridge.py on the host machine. "
                        f"Details: {e}"
                    )
                yield {
                    "event": {
                        "type": "status",
                        "data": {
                            "description": "",
                            "done": True,
                        },
                    }
                }

            return _stream()

        try:
            return self._call_bridge(body)
        except Exception as e:
            return (
                "Error: could not reach the local Mithrandir bridge. "
                "Start mithrandir_openwebui_bridge.py on the host machine. "
                f"Details: {e}"
            )