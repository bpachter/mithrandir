# Enkidu — Building a Local AI Assistant from Scratch

A public learning journal and working codebase for building a privacy-first, locally-hosted AI assistant on consumer hardware.

**Hardware used:** NVIDIA RTX 4090 (24GB VRAM), Windows 11, Alienware Aurora R15

**Goal:** Run a capable LLM locally at zero recurring cost, with Claude API as a fallback for complex reasoning only.

This is not a polished product. It is a documented journey — including the mistakes. If you want to build something similar, start here.

---

## Who This Is For

- You want to run an LLM locally and actually understand what's happening under the hood
- You care about privacy (no sending queries to third-party inference APIs)
- You want to learn CUDA, Docker, agentic frameworks, and RAG from a practical project
- You have a modern GPU (RTX 3080+ recommended, 16GB+ VRAM for 27B models)

---

## Architecture (Target State)

```
User query
    ↓
Routing logic (Python)
    ├── Simple / local → Gemma 3 27B via Ollama (RTX 4090, CUDA)
    └── Complex / fallback → Claude API (Anthropic)
                ↓
        Tool pipeline (optional)
        ├── SEC Edgar screener
        ├── Web search
        └── Custom tools
                ↓
        Response + memory storage
        ├── ChromaDB (vector, semantic search)
        └── SQLite (structured history)
```

---

## Build Phases

| Phase | Goal | Status |
|-------|------|--------|
| [Phase 1](./phase1-local-inference/) | Local inference — Gemma 3 27B via Ollama + Open WebUI | 🔄 In Progress |
| [Phase 2](./phase2-tool-use/) | Tool use + routing logic (local vs Claude) | ⬜ Not Started |
| [Phase 3](./phase3-agents/) | Agentic orchestration via Discord/CLI | ⬜ Not Started |
| [Phase 4](./phase4-memory/) | Persistent memory via ChromaDB + SQLite | ⬜ Not Started |
| Phase 5 | Voice interface (wake word → STT → TTS) | ⬜ Not Started |

---

## Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Local inference | [Ollama](https://ollama.com) + Gemma 3 27B | Best perf/size ratio, runs in 16GB VRAM |
| GPU | NVIDIA RTX 4090, CUDA 12.x | 24GB VRAM, fast enough for 27B Q4 |
| Container runtime | Docker Desktop + WSL2 | Reproducible, GPU passthrough works well |
| Chat UI | [Open WebUI](https://github.com/open-webui/open-webui) | Browser-based, connects to Ollama out of the box |
| Cloud fallback | Anthropic Claude API | Best reasoning quality, selective use only |
| Vector memory | ChromaDB + nomic-embed-text | Local embeddings, no cloud required |
| Conversation history | SQLite | Simple, zero infrastructure |
| Orchestration | TBD (Phase 3) | Evaluating options |
| Voice (optional) | openwakeword + faster-whisper + Kokoro TTS | All local, all free |

---

## Getting Started

### Prerequisites
- Python 3.11+ (Anaconda recommended)
- Docker Desktop with WSL2 backend
- NVIDIA GPU with 16GB+ VRAM (for 27B models; 8GB works for smaller models)
- NVIDIA drivers updated (CUDA 12.x)
- An [Anthropic API key](https://console.anthropic.com) (for Claude fallback only)

### Setup

```bash
git clone https://github.com/bpachter/enkidu.git
cd enkidu
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
python test_claude.py  # Should print: Enkidu lives
```

Then follow the [Phase 1 guide](./phase1-local-inference/README.md) to get Ollama running.

---

## Repo Structure

```
enkidu/
├── README.md                    # You are here
├── JOURNEY.md                   # Running log of what was built, learned, and broken
├── .env.example                 # Secret template — copy to .env and fill in
├── requirements.txt             # Python dependencies
├── test_claude.py               # Phase 0: Claude API proof of concept
├── phase1-local-inference/      # Docker + Ollama + Open WebUI
├── phase2-tool-use/             # Routing logic + tool integrations
├── phase3-agents/               # Agentic orchestration
└── phase4-memory/               # ChromaDB + SQLite memory layer
```

---

## Follow the Journey

The honest, unfiltered log of what was actually done (including mistakes) lives in [JOURNEY.md](./JOURNEY.md).

---

## Why "Enkidu"?

In the Epic of Gilgamesh, Enkidu is the wild companion created to match Gilgamesh — powerful, loyal, and built from scratch. Seemed right for a locally-built AI assistant.
