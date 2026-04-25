"""
phase6-ui/server/demos.py — Prebuilt demo mode definitions for Mithrandir.

Each demo has:
  - id:           slug used in API routes
  - title:        display name
  - description:  one-line summary for the UI
  - category:     "local" | "finance" | "voice" | "system"
  - steps:        ordered list of scripted prompts to send to the chat
  - intro:        narration shown in the UI before the demo starts
  - tags:         keywords for filtering

The /api/demos endpoint returns all demos.
The /api/demos/{id}/prompts endpoint returns the step list for a given demo
so the React frontend can drive each step as a button click.
"""

from __future__ import annotations
from typing import Any

DEMOS: list[dict[str, Any]] = [
    {
        "id": "local_speed",
        "title": "Local Speed + Privacy",
        "description": "Showcases real-time GPU inference — all computation stays on your machine.",
        "category": "local",
        "tags": ["gpu", "privacy", "local", "speed", "ollama"],
        "intro": (
            "This demo runs entirely on the RTX 4090 — no data leaves your machine. "
            "Watch the GPU utilization spike in the hardware panel as Gemma 4 generates tokens locally."
        ),
        "steps": [
            {
                "label": "Introduce Mithrandir",
                "prompt": "Who are you, what hardware are you running on, and why does local inference matter for privacy?",
                "expected_keywords": ["RTX 4090", "local", "Ollama", "privacy"],
            },
            {
                "label": "Explain the GPU stack",
                "prompt": "How does my RTX 4090 run a 26 billion parameter model in real time? Walk me through the VRAM math.",
                "expected_keywords": ["VRAM", "quantization", "Q4", "13 GB"],
            },
            {
                "label": "Latency comparison",
                "prompt": "How does local GPU inference compare to calling an API like GPT-4 in terms of latency, cost, and privacy?",
                "expected_keywords": ["latency", "cost", "privacy", "API"],
            },
            {
                "label": "Watch the hardware panel",
                "prompt": "Run a compute-heavy task: generate the first 200 digits of pi using a Python approach and explain each step.",
                "expected_keywords": ["pi", "digit", "compute"],
            },
        ],
    },
    {
        "id": "edgar_analysis",
        "title": "EDGAR Financial Analysis",
        "description": "Live SEC EDGAR data: quantitative value screening, EV/EBIT, Piotroski F-Score.",
        "category": "finance",
        "tags": ["stocks", "EDGAR", "valuation", "QV", "finance", "screener"],
        "intro": (
            "Mithrandir pulls real-time data from SEC EDGAR filings. "
            "No data services subscription needed — just the public EDGAR API. "
            "This demo shows the quantitative value screener finding undervalued, high-quality stocks."
        ),
        "steps": [
            {
                "label": "Run the QV screener",
                "prompt": "Show me the top 5 most undervalued stocks from the QV screener right now with their EV/EBIT ratios.",
                "expected_keywords": ["EV/EBIT", "rank", "ticker"],
            },
            {
                "label": "Deep-dive a pick",
                "prompt": "Take the #1 pick from that list and give me a full analysis: valuation, quality score, Piotroski F-Score, and why it might be undervalued.",
                "expected_keywords": ["Piotroski", "F-Score", "undervalued"],
            },
            {
                "label": "Sector diversification",
                "prompt": "Show me the top 3 picks from different sectors to build a diversified watchlist.",
                "expected_keywords": ["sector", "diversif"],
            },
            {
                "label": "Market regime context",
                "prompt": "What is the current market regime and how should I adjust my value screening thresholds in this environment?",
                "expected_keywords": ["regime", "Expansion", "Contraction", "Recovery", "Crisis"],
            },
            {
                "label": "Track record",
                "prompt": "How has the QV model performed historically? Show me the signal returns vs SPY.",
                "expected_keywords": ["return", "alpha", "SPY"],
            },
        ],
    },
    {
        "id": "voice_agent",
        "title": "Voice Agent",
        "description": "Full voice round-trip: Whisper STT → Gemma/Claude → F5-TTS with character FX.",
        "category": "voice",
        "tags": ["voice", "TTS", "STT", "Whisper", "F5-TTS", "microphone"],
        "intro": (
            "This demo showcases the full voice pipeline: "
            "speech-to-text via faster-Whisper (local GPU), "
            "reasoning via Gemma 4 or Claude, and "
            "text-to-speech via F5-TTS with BMO character effects. "
            "All processing is local. Click the mic or press Space to speak."
        ),
        "steps": [
            {
                "label": "Say hello (voice)",
                "prompt": "VOICE_PROMPT: Say: Hello Mithrandir, are you there?",
                "voice_only": True,
                "tip": "Click the microphone and say: 'Hello Mithrandir, are you there?'",
            },
            {
                "label": "Ask a financial question (voice)",
                "prompt": "VOICE_PROMPT: Ask about the top stocks verbally",
                "voice_only": True,
                "tip": "Say: 'What are your top 3 stock picks right now?'",
            },
            {
                "label": "Test TTS audio quality",
                "prompt": "Please describe yourself in exactly three sentences, with enthusiasm — this is a TTS quality test.",
                "expected_keywords": ["Mithrandir", "RTX", "local"],
            },
            {
                "label": "Voice round-trip latency",
                "prompt": "How long does it take for your voice pipeline to go from my speech to audio output? Break down each stage.",
                "expected_keywords": ["Whisper", "TTS", "latency", "ms"],
            },
        ],
    },
    {
        "id": "system_monitoring",
        "title": "Live Hardware Monitoring",
        "description": "Real-time GPU/CPU telemetry, temperature, power draw, and clock speeds.",
        "category": "system",
        "tags": ["gpu", "cpu", "ram", "temperature", "monitoring", "hardware"],
        "intro": (
            "Watch Mithrandir's live hardware panel while asking about your system. "
            "The GPU stats WebSocket streams at 2 Hz — every metric is live."
        ),
        "steps": [
            {
                "label": "Current system snapshot",
                "prompt": "Give me a full snapshot of current system stats: GPU utilization, VRAM usage, temperature, power draw, and CPU load.",
                "expected_keywords": ["GPU", "VRAM", "temperature", "%"],
            },
            {
                "label": "Explain what you're seeing",
                "prompt": "My GPU is at the utilization level you just reported. Is that normal for idle inference? What would push it higher?",
                "expected_keywords": ["inference", "utilization", "Gemma"],
            },
            {
                "label": "Power efficiency",
                "prompt": "What is the tokens-per-watt efficiency of running Gemma 4 26B on my RTX 4090 compared to cloud inference?",
                "expected_keywords": ["watt", "efficiency", "token"],
            },
            {
                "label": "Thermal headroom",
                "prompt": "At current temperatures, how much thermal headroom do I have before the GPU throttles? What's the safe sustained load limit?",
                "expected_keywords": ["thermal", "throttle", "temperature", "°C"],
            },
        ],
    },
]

_DEMO_BY_ID = {d["id"]: d for d in DEMOS}


def get_all_demos() -> list[dict]:
    """Return all demo definitions (without the full step prompts for list view)."""
    return [
        {
            "id": d["id"],
            "title": d["title"],
            "description": d["description"],
            "category": d["category"],
            "tags": d["tags"],
            "step_count": len(d["steps"]),
            "intro": d["intro"],
        }
        for d in DEMOS
    ]


def get_demo(demo_id: str) -> dict | None:
    """Return a full demo definition including steps."""
    return _DEMO_BY_ID.get(demo_id)


def get_demo_prompts(demo_id: str) -> list[dict] | None:
    """Return just the step list for a demo."""
    demo = _DEMO_BY_ID.get(demo_id)
    if not demo:
        return None
    return demo["steps"]
