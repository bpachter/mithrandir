# Enkidu — Building a Local AI Assistant from Scratch

> *A public learning journal and working codebase for building a privacy-first, locally-hosted AI assistant on consumer hardware.*

> Visual placeholder: add `assets/hero-enkidu-ui.png` once captured (see [assets/README.md](./assets/README.md)).

## In one paragraph (for non-engineers)

A "large language model" (LLM) is the kind of AI behind ChatGPT, Claude, and Gemini. Most people use them through a website and pay per question. **This project shows how to run one yourself, on your own computer, for free, with no data ever leaving your machine.** The model is Google's open-source Gemma 4. The hardware is a normal gaming PC with an NVIDIA graphics card. The result is a private assistant that's actually useful — it reads SEC filings, tracks markets, remembers past conversations, and even speaks in a cloned voice.

## In one paragraph (for engineers)

Local-first agentic stack: **Gemma 4 26B (MoE, 18 GB VRAM, ~144 tok/s on a 4090)** served via Ollama, fronted by a ReAct loop with Pydantic-validated tool calls, smart routing to Claude for heavy reasoning, ChromaDB+SQLite memory with codebase RAG, HMM-based market regime injection, a quantitative-value EDGAR screener over 9.8 K filings, faster-whisper STT + F5-TTS voice cloning with a 5-tier fallback chain, and a custom React/FastAPI/WebSocket UI. Telegram bot for mobile. All local except an optional Claude/Tavily fallback.

## What this is — and is not

- **It is** a documented, reproducible build with every step, every bug, every fix in [JOURNEY.md](./JOURNEY.md).
- **It is not** a polished product. There is no installer. There are sharp edges. That is the point — you'll learn more from a real build than a sanitised one.

**Required vibe check before you start:** [youtube.com/watch?v=vWGQBQU8Vr0](https://www.youtube.com/watch?v=vWGQBQU8Vr0)

## TL;DR — Why this matters

| Question | Answer |
|---|---|
| Can a normal person actually run a frontier LLM at home? | Yes, if you have an NVIDIA GPU with 8 GB+ VRAM. |
| What does it cost? | $0 in API fees. You pay for electricity. |
| Is it as good as ChatGPT / Claude? | For most everyday questions, yes. For the hardest reasoning, Claude is still better — so Enkidu uses Claude *only when needed* and keeps everything else local. |
| How fast is it? | ~144 tokens/second on an RTX 4090 — about 4× the speed I get from a typical cloud API. |
| Does my data leave the machine? | No, unless you explicitly route a query to the Claude fallback. |
| How long does setup take? | ~1–2 hours, mostly waiting for the model to download. |

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
| [Tavily](https://app.tavily.com) | Web search API key (`TAVILY_API_KEY`) — 1,000 free searches/month | Optional — DuckDuckGo is the free fallback |
| [GitHub](https://github.com) | Fork this repo and track your own journey | Optional but recommended |

---

## Who This Is For

- You want to run an LLM locally and actually understand what's happening under the hood
- You care about privacy (no sending queries to third-party inference APIs)
- You want to learn CUDA, Docker, agentic frameworks, and RAG from a practical project
- You have a modern NVIDIA GPU (8GB VRAM minimum; 20GB+ recommended for the full 26B model)

---

## Architecture (Current State)

> Visual placeholder: add `assets/architecture-diagram.png` once rendered (see [assets/README.md](./assets/README.md)).

> **Plain English:** Two ways in (browser or iPhone). One brain in the middle (the agent). Two engines under the hood (local Gemma for cheap/fast, Claude for hard reasoning). A toolbox of things the agent can do (read SEC filings, run Python, search the web, recall memory). Everything underlined below is what gets shoved into the model's prompt *before* it answers, so the answers are grounded in real data instead of guesses.

```
Interfaces
    ├── Browser (React SPA — Blade Runner terminal UI)
    │       WebSocket /ws/chat   ← streaming chat tokens
    │       WebSocket /ws/gpu    ← live GPU/CPU/RAM stats (2 Hz)
    │       WebSocket /ws/voice  ← STT → agent → TTS pipeline
    │       REST APIs            ← history, portfolio, regime, params
    └── iPhone (Telegram app)
            Telegram Bot API (short-polling, TLS patched for Windows)
    ↓
enkidu_agent.py — ReAct loop (Reason → Act → Observe)
    ↓
Routing: keyword/ticker heuristic
    ├── Gemma 4 26B via Ollama (local GPU, free)    ← everyday queries
    └── Claude claude-sonnet-4-6 via Anthropic API  ← tool-use / agentic queries
    ↓
Tool dispatch (Claude path)
    ├── edgar_screener   → SEC EDGAR financials + QV screened portfolio (~360 quality-gated stocks)
    ├── python_sandbox   → subprocess code execution (pandas/numpy/scipy)
    ├── system_info      → GPU/CPU/RAM stats via nvidia-smi + psutil
    ├── market_regime    → HMM regime detection (Expansion/Recovery/Contraction/Crisis)
    ├── qv_performance   → signal track record vs SPY (30/90/180/365-day horizons)
    ├── qv_snapshot      → current QV watchlist with quality flags + sector labels
    ├── recall_memory    → semantic search over past conversations (ChromaDB)
    ├── search_docs      → semantic search over codebase + JOURNEY.md (ChromaDB)
    └── web_search       → live web search via Tavily API (DDG fallback, no API key needed)

[Every query: HMM market regime + memory context + last exchange injected into system prompt]
[Gemma path attempts a live DuckDuckGo pre-search; if it fails, query continues normally]
[Identity grounding: user is always "Ben Pachter (Ben)" — prevents name hallucination]
[RGB keyboard soft blue at idle; deep purple / galaxy swirl during inference]
[Windows Task Scheduler: daily signal log + weekly alert push]

Voice pipeline (Phase 7)
    Microphone (Web Audio API, native sample rate, float32 PCM)
    → VAD auto-stop (AnalyserNode RMS threshold, 900ms silence window)
    → WebSocket /ws/voice (base64 PCM + sample rate)
    → Whisper base.en (CUDA float16, faster-whisper)
    → enkidu_agent.run_agent()
    → TTS (5-tier fallback chain, sentence-streamed for low latency):
         1. F5-TTS voice cloning (~1-3s/sentence, uses voices/<profile>.wav reference)
         2. Chatterbox voice cloning (~25s, slower fallback for .wav profiles)
         3. Kokoro neural TTS (~50-100ms, primary for built-in voices + fast fallback)
         4. edge-tts BrianNeural (cloud fallback, requires internet)
         5. pyttsx3 SAPI5 (Windows offline last resort)
    → WAV chunks streamed per-sentence, queued for sequential playback
    → Character FX chain (pitch / formant / EQ / reverb / bitcrush) applied post-synthesis
    → [optional] auto-restart listening for hands-free conversation loop

    Voice profiles: drop any 5-8s clean .wav into phase6-ui/server/voices/.
    Auto-scan from YouTube: python phase6-ui/server/scan_bmo_voice.py <url> --out <name>
```

---

## Build Phases

| Phase | Goal | Status |
|-------|------|--------|
| [Phase 1](./phase1-local-inference/) | Local inference — Gemma 4 26B via Ollama + Open WebUI | ✅ Complete |
| [Phase 2](./phase2-tool-use/) | Tool use + routing + EDGAR financial screener | ✅ Complete |
| [Phase 3](./phase3-agents/) | ReAct agent loop + Telegram interface + HMM regime detection | ✅ Complete |
| [Phase 4](./phase4-memory/) | Persistent memory via ChromaDB + SQLite + codebase RAG | ✅ Complete |
| [Phase 5](./phase5-intelligence/) | Signal integrity, backtesting engine, proactive alerts | ✅ Complete |
| [Phase 6](./phase6-ui/) | Custom Blade Runner terminal UI — React/Vite/FastAPI, 3-column dashboard | ✅ Complete |
| Phase 7 | Voice interaction — Whisper STT, F5-TTS voice cloning (BMO), Kokoro/Chatterbox/edge-tts fallbacks, VAD auto-stop | ✅ Complete |

---

## Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Local inference | [Ollama](https://ollama.com) + Gemma 4 26B (MoE) | 256K context, only 3.8B params active per inference, 18GB VRAM |
| GPU | NVIDIA CUDA 12.x | Required for local inference — AMD ROCm not covered here |
| Container runtime | Docker Desktop + WSL2 | Reproducible setup, GPU passthrough works well on Windows |
| UI frontend | React 18 + Vite + TypeScript | Custom Blade Runner terminal dashboard; replaces Open WebUI |
| UI backend | FastAPI (Python) | Serves SPA + WebSocket endpoints for chat, GPU, and voice |
| Charts | Recharts | GPU/system sparklines with ring-buffer history |
| State management | Zustand | Minimal boilerplate for chat + GPU + voice state |
| Cloud fallback | Anthropic Claude API | Best reasoning quality, used selectively |
| Financial data | SEC EDGAR + DefeatBeta (via WSL) | Free, comprehensive, no API key required |
| RGB lighting | Corsair iCUE SDK + Alienware LightFX | Keyboard idle blue / deep purple during inference; tower galaxy swirl rainbow |
| Web search | Tavily API + DuckDuckGo fallback | Live internet results are attempted on the Gemma path and injected when available; full page extraction via Tavily |
| Agentic interface | Telegram Bot (pyTelegramBotAPI) | iPhone access, no server needed, first-class Bot API |
| Regime detection | hmmlearn GaussianHMM + yfinance SPY data | Local, 4-state market regime injected into every prompt |
| Vector memory | ChromaDB + nomic-embed-text | Local embeddings, no cloud required |
| Conversation history | SQLite | Simple, zero infrastructure |
| Backtesting | SQLite signals.db + yfinance | Tracks QV signal alpha over 30/90/180/365-day horizons |
| Proactive alerts | Windows Task Scheduler + alert_engine.py | Daily dip scans + weekly performance push to Telegram |
| Speech-to-text | faster-whisper base.en (CUDA float16) | English-only, near-realtime on RTX 4090 |
| Text-to-speech | F5-TTS voice cloning (~1-3s) + Kokoro neural TTS (~50-100ms) + edge-tts/pyttsx3 fallbacks | 5-tier fallback chain; sentence-streamed; character FX post-process |
| VAD | Web Audio API AnalyserNode (RMS) | Client-side voice activity detection — auto-stops on silence |

---

## Getting Started

> **First time setting up an AI project?** Read each step before running it. The order matters, and a couple of these (Docker, WSL2) need a one-time machine reboot. Budget ~1–2 hours, mostly waiting for downloads. See [phase1-local-inference/README.md](./phase1-local-inference/README.md) for the full walkthrough.

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

### 7. Run the UI (Phase 6+)

```bash
# Install frontend dependencies and start the dev server (hot-reload)
cd phase6-ui/client
npm install
npm run dev          # http://localhost:5173

# In a second terminal — start the FastAPI backend
cd phase6-ui/server
pip install fastapi uvicorn faster-whisper kokoro soundfile edge-tts psutil pynvml
uvicorn main:app --host 0.0.0.0 --port 8000
```

Or use `phase6-ui/start_ui.bat` on Windows to start both with one click.

Open `http://localhost:5173` in your browser (dev) or `http://localhost:8000` (production build).

**Voice setup:**
- First launch auto-downloads Whisper `base.en` (~145 MB) on first voice query.
- F5-TTS voice cloning requires model weights in `phase6-ui/server/f5tts_model/` (~1.3 GB). These files are not tracked in git and must be placed manually.
- The default voice profile is BMO (Adventure Time). To use a different voice, record 5-8s of clean audio, save as `phase6-ui/server/voices/<name>.wav`, and update `ENKIDU_DEFAULT_VOICE` in `.env`.

### 7b. Run Enkidu via Telegram (Phase 3)

```bash
# In phase3-agents/
python telegram_interface.py
# Or use start_enkidu_bot.bat for Windows startup
```

Commands during the session:
- `/help` — show available commands and examples
- `/stats` — show session token usage + memory counts
- `/history` — last 5 saved exchanges with timestamps
- `/watchlist` — current QV top-15 picks
- `/performance` — QV signal track record vs SPY
- `/refresh` — re-download EDGAR data and regenerate the QV screened portfolio
- `/rate <text>` — save feedback on the last response

---

## EDGAR Financial Screener (Phase 2 Tool)

> Visual placeholder: add `assets/phase2-edgar-tool.png` after capture (see [assets/README.md](./assets/README.md)).

> **Plain English:** Public companies in the U.S. are required to file their financials with the SEC. Those filings are free. Enkidu downloads them in bulk, computes a quality + value score for every company, and lets you ask plain-English questions like "what's undervalued right now?" The model doesn't *know* the answer — it *looks it up* from real filings before answering.

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
├── enkidu.py                         # Phase 0–2 entry point (REPL)
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
│   │   └── lighting.py               # Corsair iCUE + AlienFX lighting (idle blue / inference swirl)
│   └── quant-value/                  # Quantitative Value pipeline (bundled)
│       ├── README.md
│       ├── requirements.txt          # QV-specific heavy deps (edgartools, scipy)
│       ├── src/                      # Python pipeline source
│       ├── config/                   # Pipeline settings + ticker universe
│       ├── docs/                     # QV methodology documentation
│       └── data/                     # NOT in git — GB-scale EDGAR + market data
│
├── phase3-agents/                    # Agentic orchestration
│   ├── enkidu_agent.py               # ReAct loop — Reason → Act → Observe; Gemma/Claude routing
│   ├── telegram_interface.py         # Telegram bot + TLS fix + lighting hooks + crash isolation
│   ├── requirements.txt              # pyTelegramBotAPI, pydantic, anthropic, tavily-python, ddgs
│   └── tools/
│       ├── registry.py               # Tool registration + dispatch (UTF-8 subprocess)
│       ├── python_sandbox.py         # Subprocess code execution
│       ├── regime_detector.py        # HMM market regime inference
│       └── web_search.py             # Tavily primary / DuckDuckGo fallback web search
│
├── phase4-memory/                    # ChromaDB + SQLite memory
│   ├── memory_store.py               # Dual-write conversation store (SQLite + ChromaDB)
│   ├── document_indexer.py           # Codebase + docs RAG indexer
│   ├── memory_bridge.py              # Subprocess CLI bridge (isolates heavy deps)
│   └── .venv/                        # Isolated env with chromadb, onnxruntime
│
├── phase5-intelligence/              # Signal integrity + backtesting + alerts
│   ├── sector_classifier.py          # SIC code fetch → sectors.csv (43 financials/utilities separated)
│   ├── signal_logger.py              # Timestamp QV picks daily → signals.db
│   ├── performance_tracker.py        # Compute returns vs SPY at 30/90/180/365-day horizons
│   └── alert_engine.py               # Proactive Telegram alerts (price dips, ranking changes, perf)
│
└── phase6-ui/                        # Custom Blade Runner terminal UI (Phase 6–7)
    ├── server/
    │   ├── main.py                   # FastAPI — chat/gpu/voice WebSockets + REST APIs
    │   ├── voice.py                  # STT (faster-whisper) + TTS (5-tier: F5-TTS/Chatterbox/Kokoro/edge-tts/pyttsx3) + character FX
    │   ├── cuda_docs.py              # CUDA/GPU documentation search (RAG via ChromaDB)
    │   ├── f5tts_worker.py           # F5-TTS subprocess worker (persistent process, stdin/stdout JSON)
    │   ├── chatterbox_worker.py      # Chatterbox subprocess worker
    │   ├── import_voice_from_youtube.py  # CLI: download + slice a YouTube clip into a voice profile
    │   ├── scan_bmo_voice.py         # CLI: auto-detect best voice segment from a full video
    │   ├── gemma_params.json         # Gemma inference parameter presets (temperature, top_p, etc.)
    │   └── voices/
    │       └── bmo.wav               # BMO (Adventure Time) voice reference clip for F5-TTS cloning
    └── client/                       # React 18 + Vite + TypeScript SPA
        ├── src/
        │   ├── App.tsx               # 3-column grid layout, GPU WebSocket owner
        │   ├── store.ts              # Zustand state (messages, GPU history, params, memory)
        │   ├── index.css             # Blade Runner design system — CSS variables + grid
        │   └── components/
        │       ├── ChatPanel.tsx     # Unified chat + voice (VAD mic, oscilloscope waveform, audio queue)
        │       ├── DocsPanel.tsx     # CUDA/GPU docs browser with "Ask Enkidu" integration
        │       ├── GpuHistoryPanel.tsx # iCUE-style sparkline history charts (Recharts)
        │       ├── MarketPanel.tsx   # Regime badge + QV portfolio picks
        │       ├── ModelParamsPanel.tsx # Gemma parameter sliders
        │       ├── MemoryPanel.tsx   # Past conversation memory viewer
        │       ├── HistoryPanel.tsx  # Session history
        │       └── Header.tsx        # Live GPU stats inline
        └── dist/                     # Production build (served by FastAPI)
```

---

## Follow the Journey

The honest, unfiltered log of what was actually done (including mistakes) lives in [JOURNEY.md](./JOURNEY.md).

---

## Why "Enkidu"?

In the Epic of Gilgamesh, Enkidu is the wild companion created to match Gilgamesh — powerful, loyal, and built from scratch. Seemed right for a locally-built AI assistant.
