# Enkidu — Building a Local AI Assistant from Scratch

A public learning journal and working codebase for building a privacy-first, locally-hosted AI assistant on consumer hardware.

**Goal:** Run open-source LLM inference locally on your own GPU for private, zero-cost queries — with Claude API as a fallback for tasks requiring more powerful reasoning.

**Required Vibe Check:** https://www.youtube.com/watch?v=vWGQBQU8Vr0

This is not a polished product. It is a documented journey — including the mistakes. If you want to build something similar, start here.

---

## Gemma vs Claude — What's the Difference?

This is the most important concept to understand before diving in.

**You are not building an LLM. You are building a system that runs one.**

An LLM (Large Language Model) is a trained neural network — billions of mathematical parameters that encode language knowledge. Someone else trains it. You run it.

| | Gemma 4 | Claude (Anthropic) |
|---|---|---|
| **Made by** | Google DeepMind | Anthropic |
| **Type** | Open-weight model — Google releases the weights publicly | Proprietary model — weights are never released |
| **Where it runs** | On your machine, on your GPU | On Anthropic's servers |
| **How you access it** | Download the weights, run locally via Ollama | HTTP API call to api.anthropic.com |
| **Cost** | Free — you pay only for electricity | Pay per token (input + output) |
| **Privacy** | Your queries never leave your machine | Queries are sent to Anthropic's servers |
| **Quality** | Very capable, especially for its size | State-of-the-art reasoning and instruction following |
| **Speed** | Depends on your GPU (this build: ~144 tok/s on RTX 4090) | Depends on Anthropic's infrastructure + your network |
| **Control** | Full — you choose the model, version, and parameters | Limited — you call their API as-is |

**The analogy:** Gemma is like a recipe book you own — you cook the food yourself in your kitchen. Claude is like calling a restaurant — they do the cooking, you pay per meal, and you don't see the kitchen.

**Why use both?** Gemma handles the everyday queries cheaply and privately. Claude steps in when you need higher reasoning quality — complex analysis, nuanced writing, tasks where getting it right matters more than cost.

**What Enkidu adds on top:** routing logic, tool use, memory, and an interface. The LLMs are the engines. Enkidu is the car.

---

## What You Need

### Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA GPU, 8GB VRAM | NVIDIA GPU, 20GB+ VRAM |
| RAM | 16GB | 32GB+ |
| Storage | 50GB free | 100GB+ free (models + EDGAR data are large) |
| OS | Windows 10/11 or Linux | Windows 11 or Ubuntu |

> **VRAM is the main constraint.** The model you can run depends entirely on how much VRAM your GPU has. See the [Phase 1 model table](./phase1-local-inference/README.md) to pick the right size for your hardware. This build uses an RTX 4090 (24GB), which runs the full Gemma 4 26B model. A GPU with 8GB VRAM can still run the smaller Gemma 4 e4b variant.

### Software

Everything below is free and open source.

| Software | Purpose | How to get it |
|----------|---------|---------------|
| Python 3.11+ | Running scripts and orchestration logic | [python.org](https://www.python.org) or [Anaconda](https://www.anaconda.com) |
| Git | Version control | [git-scm.com](https://git-scm.com) |
| Docker Desktop | Runs Ollama and Open WebUI in isolated containers | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| WSL2 *(Windows only)* | Linux kernel backend that Docker and DefeatBeta require on Windows | Built into Windows 10/11 — run `wsl --install` in PowerShell as admin |
| NVIDIA GPU drivers | Enables CUDA so the GPU can run inference | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) — update to latest |
| OpenRGB *(optional)* | RGB lighting effects during inference | [openrgb.org](https://openrgb.org) — enable SDK Server on port 6742 |

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

## Architecture (Current State)

```
User query
    ↓
enkidu.py REPL
    ↓
Routing logic — LOCAL (Gemma) or CLOUD (Claude)?
    ↓
Tool pipeline (query-triggered, optional)
    ├── system_info    → GPU/CPU/RAM stats via nvidia-smi + psutil
    ├── edgar_screener → SEC EDGAR financials + QV screened portfolio
    └── (more tools in future phases)
    ↓
Local: Gemma 4 26B via Ollama (CUDA, RTX 4090, ~144 tok/s)
   or
Cloud: Claude claude-opus-4-6 via Anthropic API
    ↓
Response streamed to terminal
    ↓
RGB keyboard animation while local GPU is running (OpenRGB)
```

---

## Build Phases

| Phase | Goal | Status |
|-------|------|--------|
| [Phase 1](./phase1-local-inference/) | Local inference — Gemma 4 26B via Ollama + Open WebUI | ✅ Complete |
| [Phase 2](./phase2-tool-use/) | Tool use + routing + EDGAR financial screener | ✅ Complete |
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
| Financial data | SEC EDGAR + DefeatBeta (via WSL) | Free, comprehensive, no API key required |
| RGB lighting | OpenRGB SDK | Visual indicator when local GPU is running |
| Vector memory | ChromaDB + nomic-embed-text *(Phase 4)* | Local embeddings, no cloud required |
| Conversation history | SQLite *(Phase 4)* | Simple, zero infrastructure |
| Voice *(Phase 5)* | openwakeword + faster-whisper + Kokoro TTS | All local, all free |

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

### 4. Configure your environment

```bash
cp .env.example .env
# Open .env and fill in your values (see .env.example for all options)
```

### 5. Verify Claude API works (optional)

```bash
python test_claude.py  # Should print: Enkidu lives
```

### 6. Set up local inference

Follow the **[Phase 1 guide](./phase1-local-inference/README.md)** to get Ollama and Gemma running on your GPU.

### 7. Run Enkidu

```bash
python enkidu.py
```

Commands during the session:
- `/local` — force next query to local Gemma
- `/cloud` — force next query to Claude API
- `/stats` — show session token usage
- `/refresh` — re-download EDGAR data and regenerate the QV screened portfolio
- `/exit` — quit

---

## EDGAR Financial Screener (Phase 2 Tool)

Enkidu includes a quantitative value investment screener built directly into the tool pipeline. When you ask about stocks or financial data, it automatically:

1. Detects the query is financial (keyword match or uppercase ticker like `AAPL`)
2. Fetches the relevant data from the local EDGAR dataset
3. Injects it as `[EDGAR CONTEXT]` into the prompt
4. Routes to Gemma or Claude to interpret and explain

**What it knows:**
- 360 stocks passing the full QV screen (positive EBIT, quality ≥ 50th percentile, value composite ≤ 30th percentile)
- 181K+ rows of financial metrics for 9,867 companies (full fallback universe)
- All data sourced from SEC EDGAR filings — free, no API key required

**Example queries:**
```
> what are the top 10 most undervalued stocks right now?
> how is NUE performing?
> compare AMPY and XYF on value metrics
> what is DUK's free cash flow?
```

**Refreshing the data** (quarterly):
```
> /refresh
```
This re-downloads EDGAR filings for ~9,867 companies and regenerates the screened portfolio. Takes ~2 hours for the EDGAR fetch + ~20 minutes for the QV screen with fresh market prices.

**Setup:** The QV pipeline lives at `phase2-tool-use/quant-value/`. It needs its own Python environment with heavier dependencies (edgartools, scipy):
```bash
cd phase2-tool-use/quant-value
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```
Data is stored outside the repo (GB-scale). Set `QV_PATH` in `.env` to point to an existing data directory, or let the pipeline create `phase2-tool-use/quant-value/data/` on first run.

---

## Repo Structure

```
enkidu/
├── README.md                         # You are here
├── JOURNEY.md                        # Running log of what was built and broken
├── .env.example                      # Secret template — copy to .env and fill in
├── requirements.txt                  # Core Python dependencies
├── enkidu.py                         # Main entry point — run this
├── test_claude.py                    # Phase 0: Claude API proof of concept
│
├── phase1-local-inference/           # Docker + Ollama + Open WebUI setup
│   ├── README.md
│   └── docker-compose.yml
│
├── phase2-tool-use/                  # Routing + tool integrations
│   ├── README.md
│   ├── router.py                     # LOCAL vs CLOUD routing logic
│   ├── tools/
│   │   ├── system_info.py            # GPU/CPU/RAM context tool
│   │   ├── edgar_screener.py         # EDGAR financial data tool
│   │   └── lighting.py               # RGB keyboard animation (OpenRGB)
│   └── quant-value/                  # Quantitative Value pipeline (bundled)
│       ├── README.md
│       ├── requirements.txt          # QV-specific heavy deps (edgartools, scipy)
│       ├── src/                      # Python pipeline source
│       ├── config/                   # Pipeline settings + ticker universe
│       ├── docs/                     # QV methodology documentation
│       └── data/                     # NOT in git — GB-scale EDGAR + market data
│
├── phase3-agents/                    # Agentic orchestration (not started)
└── phase4-memory/                    # ChromaDB + SQLite memory (not started)
```

---

## Follow the Journey

The honest, unfiltered log of what was actually done (including mistakes) lives in [JOURNEY.md](./JOURNEY.md).

---

## Why "Enkidu"?

In the Epic of Gilgamesh, Enkidu is the wild companion created to match Gilgamesh — powerful, loyal, and built from scratch. Seemed right for a locally-built AI assistant.
