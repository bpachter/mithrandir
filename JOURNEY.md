# The Enkidu Journey

A running log of what was actually built, in order, including mistakes. Updated as each step completes.

The goal of this log is to give future builders an honest picture of the process — not just the commands that worked, but the things that broke and why.

---

## Phase 0 — Claude API Proof of Concept

**Date:** April 12, 2026

### What was done
- Set up Python 3.11 environment via Anaconda
- Installed `anthropic`, `python-dotenv`, `requests`
- Created `test_claude.py` — a minimal script that calls the Claude API and prints a response
- Initialized a local git repo, pushed to GitHub

### What broke

**Dependency version conflicts.** The Anaconda base environment had older versions of packages (pydantic, requests, etc.). Pinning specific versions in requirements.txt caused install failures. Fix: use flexible version ranges (`anthropic>=0.94.0`) instead of pinned versions.

**Committed .env to GitHub.** The `.env` file containing the API key was accidentally included in the first commit. GitHub's push protection caught it. The key was immediately rotated in the Anthropic console. Fix: add `.env` to `.gitignore` *before* the first commit.

**`.gitignore` didn't work.** The gitignore file was saved as `.gitignore.txt` (Windows sometimes adds the extension). Git never read it. Fix: rename to `.gitignore` with no extension.

**Stale model string.** `test_claude.py` was using `claude-opus-4-1-20250805`, a model ID from August 2025 that had since been rotated. Fix: update to `claude-opus-4-6` (current as of April 2026).

**Git history contained the leaked key.** Even after removing `.env` from the working directory and adding it to `.gitignore`, the original commit still had the key in history. GitHub's push protection blocked all future pushes. Fix: used `git-filter-repo` to rewrite history and scrub the file from all commits, then force-pushed.

### What was learned
- Always create `.gitignore` before the first commit, and verify it works (no `.txt` extension)
- API keys rotate; never hardcode or commit them; rotate immediately if leaked
- Git history is permanent unless you rewrite it — `git-filter-repo` is the right tool for this
- Anaconda base environments accumulate cruft; flexible version pinning is safer than exact pins

### Files created
- `test_claude.py` — Claude API hello world
- `requirements.txt` — Python dependencies
- `.gitignore` — excludes `.env`, `__pycache__`, `.venv`, etc.
- `.env` (not committed) — holds `ANTHROPIC_API_KEY`

---

## Phase 1 — Local Inference Setup

**Date:** April 12, 2026 (in progress)

### What was done
- Verified WSL2 was already installed (Ubuntu distro, WSL version 2)
- Installed Docker Desktop 4.68.0 (Windows AMD64)
- Verified Docker engine working: `docker run --rm hello-world`
- Pulled and started Ollama container with GPU passthrough:
  ```bash
  docker run -d --gpus all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
  ```

### What broke

**Started pulling the wrong model.** Initially pulled `gemma3:27b` (Gemma 3) before realizing Gemma 4 was available on Ollama. Cancelled the download at 35% and switched to `gemma4:26b`. No harm done — the partial download was discarded.

**`gemma4:latest` is not the big model.** Discovered that running `ollama pull gemma4` without a tag pulls the `latest` tag which maps to `e4b` — a tiny 4.5B edge model. Always specify the tag explicitly: `gemma4:26b`.

### In progress
- Pulling Gemma 4 26B model into Ollama (~18GB)
- Setting up Open WebUI
- Running inference benchmarks

### What was learned so far
- WSL2 was already present on Windows 11 — no manual install needed
- Docker Desktop uses WSL2 as its backend by default on Windows 11; this is what enables GPU passthrough to Linux containers
- The `-v ollama:/root/.ollama` volume flag is critical — without it, the 18GB model download disappears when the container restarts
- `--gpus all` passes the RTX 4090 through to the container via the NVIDIA Container Toolkit (bundled with Docker Desktop)
- Gemma 4 26B is a **Mixture of Experts (MoE)** model: 25.2B total parameters, only 3.8B active per inference. Runs fast like a 4B model, quality of a much larger one. 256K token context window.
- Gemma 4 26B uses ~18GB VRAM — more than the ~16GB originally estimated for Gemma 3 27B Q4. Still fits in the 4090's 24GB with ~6GB headroom.

---

*This log will be updated as each phase progresses.*
