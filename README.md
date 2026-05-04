# Run Your Own AI — A Plain-English Guide to Local LLMs

> *How to get a real AI model running on your own computer, for free, with your data never leaving the machine.*

---

## What is this guide?

This is a step-by-step walkthrough for anyone who wants to run a large language model — the same technology behind ChatGPT and Claude — on their own GPU at home. No cloud subscriptions, no per-query fees, no sending your conversations to someone else's server.

The guide covers:
- What a local LLM is and why you'd want one
- What hardware you actually need
- The software stack (Docker, Ollama, Railway)
- Running two models at once for speed and quality
- Optionally exposing it remotely via Railway

This repo is also a working project ([Mithrandir](./JOURNEY.md)) built on top of exactly this stack, so every recommendation here has been tested in a real build.

---

## Why run it locally?

Most people access AI through a website or API — you type a question, it goes to a company's server, they charge you per word, and your data sits in their logs. That works fine for casual use. But there are real reasons to run your own:

| Reason | What it means in practice |
|--------|--------------------------|
| **Privacy** | Your queries never leave your machine. Useful for sensitive documents, work data, personal notes. |
| **Cost** | $0 per query once it's running. You pay only for electricity. |
| **Speed** | A modern gaming GPU runs a good model faster than most cloud APIs respond. |
| **Control** | You pick the model, set the parameters, and can run it offline. |
| **Learning** | You actually understand how it works, not just how to use a website. |

---

## First: understand what you're doing (and not doing)

**You are not building an AI. You are running one that already exists.**

A large language model (LLM) is a neural network — billions of mathematical weights trained by a research team. Google, Meta, and others release the weights of some models publicly (called "open-weight"). You download those weights and run inference on them with your GPU.

The tools in this guide handle all the hard parts. Your job is to install them, pull a model, and point a chat interface at it.

### Open-weight models vs. proprietary APIs

| | Open-weight (e.g. Gemma 4, Qwen 2.5) | Proprietary API (e.g. Claude, GPT-4) |
|---|---|---|
| **Who made it** | Google DeepMind, Alibaba, Meta, etc. | Anthropic, OpenAI |
| **Where it runs** | On your machine | On their servers |
| **Cost** | Free — electricity only | Pay per token |
| **Privacy** | Queries never leave your machine | Sent to their servers |
| **Quality** | Excellent for most tasks | Still ahead on the hardest reasoning |
| **Internet required** | No | Yes |

**The honest take:** For everyday tasks — writing, summarizing, answering questions, coding help — a well-chosen local model is genuinely competitive with the paid APIs. For the most complex reasoning tasks, the frontier proprietary models are still better. A common pattern is to run locally by default and fall back to Claude or GPT only when you need the extra quality.

---

## What hardware do you need?

The one number that matters is **VRAM** — the memory on your graphics card. The model has to fit in VRAM to run at full speed.

| GPU VRAM | What you can run | Example card |
|----------|-----------------|-------------|
| 8 GB | Small models (3–7B params) — good for chat, code | RTX 3070, RTX 4060 |
| 12–16 GB | Mid-size models (8–14B) — noticeably more capable | RTX 3080, RTX 4070 Ti |
| 20–24 GB | Large models (26B+) — quality close to cloud APIs | RTX 3090, RTX 4090 |

> **If your GPU has less VRAM than the model requires,** Ollama will automatically offload some layers to system RAM. The model still works, just slower. A 26B model with 8 GB of VRAM will run — at maybe 5–10 tokens/second instead of 100+.

Other requirements:
- **RAM:** 16 GB minimum, 32 GB recommended
- **Storage:** 50 GB free (models range from 4–20 GB each)
- **OS:** Windows 10/11, Ubuntu, or macOS (macOS uses Apple Silicon instead of CUDA)
- **NVIDIA GPU drivers:** Update to the latest before you start — [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx)

---

## The software stack

You only need three tools to get a model running. Everything below is free and open source.

### 1. Ollama — the model runner

[Ollama](https://ollama.com) is the engine. It downloads models, loads them onto your GPU, and exposes a simple API. Think of it as the server that your GPU runs inside.

Once installed, you pull and run a model in two commands:
```bash
ollama pull gemma4:26b
ollama run gemma4:26b
```

That's it. You now have a chat interface in your terminal.

Ollama also exposes an OpenAI-compatible REST API at `http://localhost:11434`, so any tool built for ChatGPT's API can talk to your local model with a one-line config change.

### 2. Docker Desktop — clean, reproducible containers

[Docker](https://www.docker.com/products/docker-desktop/) lets you run software in isolated containers without worrying about conflicting dependencies. For this stack, it's the cleanest way to run Ollama and Open WebUI (a browser-based chat interface).

**Windows only:** Docker requires WSL2 (Windows Subsystem for Linux). Enable it once with:
```powershell
wsl --install
# Then reboot
```

After that, everything Linux-based just works.

### 3. Open WebUI — a browser chat interface (optional but recommended)

[Open WebUI](https://docs.openwebui.com/) is a polished, self-hosted chat interface that connects to your local Ollama instance. It looks and feels like ChatGPT, supports multiple models, and stores your chat history locally.

Run it with Docker in one command:
```bash
docker run -d -p 3000:80 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main
```

Open `http://localhost:3000` — you now have a fully local ChatGPT-style interface.

---

## Running two models at once: fast lane + deep lane

One of the most useful patterns for a local setup is running two models simultaneously:

- **A small, fast model** (7B parameters) for quick conversational replies
- **A large, capable model** (26B parameters) for heavy reasoning and longer tasks

On a 24 GB card (RTX 4090), both fit in VRAM at the same time. Ollama manages them concurrently.

**Recommended combination:**

| Lane | Model | Purpose |
|------|-------|---------|
| Fast | `qwen2.5:7b` | Quick chat replies, voice, low-latency turns (~3–4× faster) |
| Deep | `gemma4:26b` | Complex questions, document analysis, long-form reasoning |

Pull both:
```bash
ollama pull qwen2.5:7b
ollama pull gemma4:26b
```

**Why Qwen for fast lane?** Qwen 2.5 7B has excellent instruction-following for its size, responds in under a second for short turns, and is noticeably more coherent than older 7B models. It handles the bulk of conversational traffic without burning through the compute budget of the bigger model.

**Why Gemma 4 for deep lane?** Gemma 4 26B is a mixture-of-experts architecture — only a fraction of its parameters activate per inference, so it fits in 18 GB of VRAM while reasoning at a quality level close to much larger models.

If you only have 8–16 GB of VRAM, a single `qwen2.5:7b` or `gemma4:12b` will still give you a genuinely useful local assistant.

---

## Getting started: step by step

> Read each step before running it. A couple of these (Docker, WSL2) require a one-time reboot. Budget about 1–2 hours, mostly waiting for model downloads.

### Step 1: Install prerequisites

| Tool | Download |
|------|----------|
| Python 3.11+ | [python.org](https://www.python.org) |
| Git | [git-scm.com](https://git-scm.com) |
| Docker Desktop | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| Ollama | [ollama.com](https://ollama.com) |
| NVIDIA drivers (latest) | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) |

**Windows only:** After installing Docker, run `wsl --install` in PowerShell as administrator, then reboot.

### Step 2: Pull your models

```bash
# The deep reasoning model (~18 GB download)
ollama pull gemma4:26b

# The fast conversational model (~5 GB download)
ollama pull qwen2.5:7b
```

If you have limited VRAM, use these smaller alternatives:
```bash
ollama pull gemma4:12b   # 12B variant — fits in 8–10 GB VRAM
ollama pull qwen2.5:3b   # Smallest Qwen — works on almost any GPU
```

### Step 3: Start a chat

Test that the model is working:
```bash
ollama run gemma4:26b
```

You'll see a `>>>` prompt. Type a question and press Enter. Type `/bye` to exit.

### Step 4: Launch the browser interface

```bash
docker run -d -p 3000:80 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main
```

Open `http://localhost:3000` in your browser. Open WebUI will automatically detect your local Ollama models. You can now chat with either model from a clean browser UI.

### Step 5: Build on top (optional)

Once you have the base running, the interesting work is adding things on top:

- **Memory** — have the model remember past conversations (ChromaDB + SQLite)
- **Web search** — inject live search results before the model answers (Tavily or DuckDuckGo)
- **Voice** — Whisper for speech-to-text, Kokoro or F5-TTS for text-to-speech
- **Custom tools** — give the model the ability to run code, read files, or call APIs
- **A custom UI** — replace Open WebUI with your own React/FastAPI frontend

For a real working example of all of the above built on this exact stack, see the [JOURNEY.md](./JOURNEY.md) in this repo.

---

## Going further: Railway for remote access

By default, your model only runs on your local network. If you want to access it from your phone, a laptop on a different network, or share it with someone else, you need a way to expose it.

[Railway](https://railway.app) is the simplest option. It lets you deploy a small proxy or gateway service that tunnels to your local machine via a public URL. You keep your model on your own GPU — Railway just handles the routing.

**The pattern:**
1. Run a lightweight FastAPI app on your local machine that forwards requests to Ollama
2. Deploy a gateway service on Railway that proxies to a tunnel on your machine
3. Access your model from anywhere via `https://your-app.railway.app`

**Cloudflare Tunnel** (free) is the most reliable way to create the tunnel from your local machine to Railway without port-forwarding or exposing your home IP:

```bash
# Install cloudflared, then:
cloudflared tunnel --url http://localhost:8000
```

This gives you a public `https://` URL that forwards to your local FastAPI backend, which in turn calls Ollama. Your model stays on your hardware; the URL is just a door in.

The `gateway/` folder in this repo has a working example of this pattern.

---

## Common questions

**Do I need an internet connection to run the model?**
No. Once the model weights are downloaded, inference is entirely local. You only need internet if you explicitly add a web search tool.

**Can I use an AMD GPU?**
Ollama supports AMD ROCm on Linux. The setup is more involved and not covered here, but it does work.

**Is this against any terms of service?**
No. The open-weight models (Gemma, Qwen, Llama) are released under licenses that explicitly permit local use. Check each model's license for commercial use restrictions.

**What's the difference between parameters and VRAM?**
Parameters are the "weights" — the numbers that make the model work. Each parameter takes about 2 bytes of VRAM in the standard quantization formats Ollama uses. A 7B model ≈ 5 GB VRAM. A 26B model ≈ 18 GB VRAM.

**The model is slow. What do I do?**
Check that Ollama is actually using your GPU: run `ollama ps` to see active models and which layers are on GPU vs CPU. If most layers say "CPU", your GPU drivers may not be set up correctly for CUDA — reinstall the latest NVIDIA drivers and restart.

---

## Recommended models by use case

| Use case | Recommended model | Why |
|----------|------------------|-----|
| General chat, Q&A | `qwen2.5:7b` | Fast, sharp instruction following, small footprint |
| Complex reasoning, long docs | `gemma4:26b` | Deep lane — excellent quality-per-VRAM ratio |
| Coding | `qwen2.5-coder:7b` | Trained specifically on code |
| Smallest usable model | `gemma4:4b` | Runs on almost any NVIDIA GPU |
| Best quality on 24 GB | `gemma4:26b` + `qwen2.5:7b` | Two-model hybrid (this guide's recommended setup) |

---

## Further reading

- [Ollama documentation](https://github.com/ollama/ollama) — model list, API reference, GPU setup
- [Open WebUI docs](https://docs.openwebui.com/) — features, auth, multi-user setup
- [Gemma model page](https://ollama.com/library/gemma4) — available sizes, license
- [Qwen model page](https://ollama.com/library/qwen2.5) — available sizes, benchmarks
- [Railway docs](https://docs.railway.app) — deploying gateway services
- [JOURNEY.md](./JOURNEY.md) — the unfiltered build log for this specific project

---

## About this repo

This repository contains Mithrandir — a personal AI assistant built on the stack described above. It serves as a working reference implementation: every tool, pattern, and decision in this guide is reflected somewhere in the codebase. The build log ([JOURNEY.md](./JOURNEY.md)) documents every step, bug, and fix from first boot to current state.
