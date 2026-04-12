# Enkidu — Building a Local AI Assistant from Scratch

A public learning journal and working codebase for building a privacy-first, locally-hosted AI assistant on consumer hardware.

**Goal:** Run a capable LLM locally at zero recurring cost, with Claude API as a fallback for complex reasoning only.

**Required Vibe Check:** https://www.youtube.com/watch?v=vWGQBQU8Vr0

This is not a polished product. It is a documented journey — including the mistakes. If you want to build something similar, start here.

---

## What You Need

### Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA GPU, 8GB VRAM | NVIDIA GPU, 20GB+ VRAM |
| RAM | 16GB | 32GB+ |
| Storage | 50GB free | 100GB+ free (models are large) |
| OS | Windows 10/11 or Linux | Windows 11 or Ubuntu |

> **VRAM is the main constraint.** The model you can run depends entirely on how much VRAM your GPU has. See the [Phase 1 model table](./phase1-local-inference/README.md) to pick the right size for your hardware. This build uses an RTX 4090 (24GB), which runs the full Gemma 4 26B model. A GPU with 8GB VRAM can still run the smaller Gemma 4 e4b variant.

> **AMD GPU note:** AMD GPU support via ROCm is possible but not covered in this guide. NVIDIA is strongly recommended for CUDA compatibility.

### Software

Everything below is free and open source.

| Software | Purpose | How to get it |
|----------|---------|---------------|
| Python 3.11+ | Running scripts and orchestration logic | [python.org](https://www.python.org) or [Anaconda](https://www.anaconda.com) |
| Git | Version control | [git-scm.com](https://git-scm.com) |
| Docker Desktop | Runs Ollama and Open WebUI in isolated containers | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| WSL2 *(Windows only)* | Linux kernel backend that Docker requires on Windows | Built into Windows 10/11 — run `wsl --install` in PowerShell as admin |
| NVIDIA GPU drivers | Enables CUDA so the GPU can run inference | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) — update to latest |

### Accounts

| Account | Purpose | Required? |
|---------|---------|-----------|
| [Anthropic Console](https://console.anthropic.com) | Claude API key for fallback reasoning | Optional — only needed for the Claude fallback |
| [GitHub](https://github.com) | Fork this repo and track your own journey | Optional but recommended |

---

## Who This Is For

- You want to run an LLM locally and actually understand what's happening under the hood
- You care about privacy (no sending queries to third-party inference APIs)
- You want to learn CUDA, Docker, agentic frameworks, and RAG from a practical project
- You have a modern NVIDIA GPU (8GB VRAM minimum; 20GB+ recommended for the full 26B model)

---

## Architecture (Target State)

```
User query
    ↓
Routing logic (Python)
    ├── Simple / local → Gemma 4 26B via Ollama (CUDA, local GPU)
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
| [Phase 1](./phase1-local-inference/) | Local inference — Gemma 4 26B via Ollama + Open WebUI | 🔄 In Progress |
| [Phase 2](./phase2-tool-use/) | Tool use + routing logic (local vs Claude) | ⬜ Not Started |
| [Phase 3](./phase3-agents/) | Agentic orchestration via Discord/CLI | ⬜ Not Started |
| [Phase 4](./phase4-memory/) | Persistent memory via ChromaDB + SQLite | ⬜ Not Started |
| Phase 5 | Voice interface (wake word → STT → TTS) | ⬜ Not Started |

---

## Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Local inference | [Ollama](https://ollama.com) + Gemma 4 26B (MoE) | 256K context, only 3.8B params active per inference, 18GB VRAM |
| GPU | NVIDIA CUDA 12.x | Required for local inference — AMD ROCm not covered here |
| Container runtime | Docker Desktop + WSL2 | Reproducible setup, GPU passthrough works well on Windows |
| Chat UI | [Open WebUI](https://github.com/open-webui/open-webui) | Browser-based, connects to Ollama out of the box |
| Cloud fallback | Anthropic Claude API | Best reasoning quality, used selectively |
| Vector memory | ChromaDB + nomic-embed-text | Local embeddings, no cloud required |
| Conversation history | SQLite | Simple, zero infrastructure |
| Orchestration | TBD (Phase 3) | Evaluating options |
| Voice (optional) | openwakeword + faster-whisper + Kokoro TTS | All local, all free |

---

## Getting Started

### 1. Install prerequisites

Make sure you have Python, Git, Docker Desktop, and WSL2 (Windows) installed from the table above before continuing.

### 2. Clone the repo

```bash
git clone https://github.com/bpachter/enkidu.git
cd enkidu
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

```bash
cp .env.example .env
# Open .env and add your ANTHROPIC_API_KEY
```

### 5. Verify Claude API works (optional)

```bash
python test_claude.py  # Should print: Enkidu lives
```

### 6. Set up local inference

Follow the **[Phase 1 guide](./phase1-local-inference/README.md)** to get Ollama and Gemma running on your GPU.

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
