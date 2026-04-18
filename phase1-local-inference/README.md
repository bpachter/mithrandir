# Phase 1 — Local Inference

**Status: ✅ Complete**

![Open WebUI chatting with local Gemma](../assets/phase1-openwebui-chat.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 1 — Local Inference” -->

> **Plain English:** This phase puts a real AI model on your own GPU. Two free programs (Docker and Ollama) do all the heavy lifting. After ~1 hour you'll be chatting with Gemma in your browser at `localhost:3000`, with **no internet required and no per-question cost.** If you've ever installed a Steam game, the difficulty level is similar — wait for downloads, click some things, run two terminal commands.

Get Gemma 4 26B running locally on your GPU. By the end of this phase you will be able to chat with a state-of-the-art LLM in a browser with no internet connection required and no API costs.

**Time to complete:** 1-2 hours (mostly waiting for downloads)
**Disk space needed:** ~25GB free
**VRAM needed:** 20GB+ (Gemma 4 26B uses ~18GB)

> **Note on Gemma 4 26B architecture:** This is a Mixture of Experts (MoE) model. It has 25.2B total parameters but only activates 3.8B per inference — meaning it runs at roughly the speed of a 4B model while delivering the quality of a much larger one. 256K token context window.

---

## Gemma 4 Model Options

| Tag | VRAM | Parameters | Notes |
|-----|------|------------|-------|
| `gemma4:e2b` | ~5GB | 2.3B active | Edge variant, includes audio support |
| `gemma4:e4b` | ~7GB | 4.5B active | Edge variant, includes audio support |
| `gemma4:26b` | ~18GB | 3.8B active (MoE) | **Recommended for 20GB+ GPUs** |
| `gemma4:31b` | ~20GB | 30.7B dense | Most capable, needs 22GB+ VRAM |

> **Warning:** `ollama pull gemma4` with no tag pulls `latest`, which maps to `e4b` — the small 4.5B edge model. Always specify the tag explicitly.

---

## Prerequisites

- Docker Desktop installed with WSL2 backend ([install guide](https://docs.docker.com/desktop/install/windows-install/))
- NVIDIA GPU drivers up to date (CUDA 12.x)
- Verify Docker is working: `docker run --rm hello-world`

---

![docker compose up](../assets/phase1-docker-compose-up.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 1” -->

## Step 1 — Start Ollama + Open WebUI

This repo includes a `docker-compose.yml` that starts both Ollama and Open WebUI in one command. From this directory:

```bash
docker compose up -d
```

Docker will pull both images and start the containers. Both are configured with `restart: unless-stopped`, so they start automatically when Docker starts, and Docker starts automatically on boot — no manual restarts needed.

> **Already have Ollama running from a manual `docker run`?**
> You can keep using it — the compose file is just the cleaner approach for fresh setups.

Verify both containers are running:
```bash
docker ps
# Should show both "ollama" and "open-webui" with status "Up"
```

---

![Pulling Gemma weights](../assets/phase1-ollama-pull.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 1” -->

## Step 2 — Pull Gemma 4 26B

This downloads the model weights (~18GB). Go make coffee.

```bash
docker exec ollama ollama pull gemma4:26b
```

To see what models are available:
```bash
docker exec ollama ollama list
```

---

## Step 3 — Test Inference via CLI

```bash
docker exec -it ollama ollama run gemma4:26b "What is CUDA and why does it matter for AI?"
```

You should see a streamed response. Note the time — this is your cold-start baseline (model loading into VRAM). Subsequent calls will be faster.

---

## Step 4 — Open WebUI

Open your browser to [http://localhost:3000](http://localhost:3000).

On first launch it will ask you to create a local admin account — nothing leaves your machine. Select `gemma4:26b` from the model dropdown and start chatting.

**Note:** Gemma knows it was created by Google DeepMind, but it has no awareness of where it's running. If you ask "where do you live?" it may say "Google's servers" — that's wrong. It's running on your GPU. Open-weight models can't detect their runtime environment.

---

## Step 5 — Benchmark

Run the benchmark to measure local vs cloud performance:

```bash
# From the project root
python phase1-local-inference/inference_bench.py
```

![Benchmark output — 144 tok/s local vs 31 tok/s cloud](../assets/phase1-benchmark.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 1” -->

### Actual results from this build (RTX 4090, cold start)

| Metric | Gemma 4 26B (local) | Claude Opus 4.6 (cloud) |
|--------|-------------------|------------------------|
| Time to first token | 6.36s *(VRAM load)* | 1.60s |
| Total time | **8.13s** | 10.20s |
| Tokens generated | 1077 | 315 |
| Tokens / second | **144 tok/s** | 31 tok/s |
| Cost | **$0** | ~$0.02 |

Monitor GPU VRAM usage while the benchmark runs:
```bash
# PowerShell
nvidia-smi
```

![nvidia-smi during inference](../assets/phase1-nvidia-smi.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 1” — shows ~18 GB VRAM used by the Ollama process -->

---

## Optional: Eliminate Cold Starts

By default, Ollama unloads the model from VRAM after 5 minutes of inactivity. To keep it loaded permanently, add `OLLAMA_KEEP_ALIVE=-1` to the ollama service environment in `docker-compose.yml`:

```yaml
ollama:
  environment:
    - OLLAMA_KEEP_ALIVE=-1
```

Then restart: `docker compose up -d`

---

## Troubleshooting

**Container starts but GPU not detected:**
- Update NVIDIA drivers (470+ for CUDA 12)
- Docker Desktop: Settings → Resources → confirm GPU is enabled
- Test: `docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi`

**Port 11434 already in use:**
- Check what's using it: `netstat -ano | findstr 11434`
- Or Ollama is already running outside Docker

**Model download stalls:**
- Normal for large files to pause — wait a few minutes
- If truly stuck: re-run `docker exec ollama ollama pull gemma4:26b` (it resumes)

**`ModuleNotFoundError` when running Python scripts:**
- Your venv may not be routing `python` correctly
- Use `.venv/Scripts/python.exe` directly instead of `python`

---

## What You Learned in Phase 1

- How Docker containers work: images, containers, volumes, port mapping
- How WSL2 enables Linux containers on Windows with near-native GPU passthrough
- How Ollama abstracts model loading and CUDA inference behind a simple HTTP API
- What Mixture of Experts (MoE) architecture is and why it runs faster than a dense model of the same parameter count
- What model quantization is (Q4 = 4-bit weights, ~4x smaller than full precision with modest quality loss)
- Practical VRAM constraints for running large models on consumer hardware
- That open-weight models have no awareness of their runtime environment — they only know their training origin
