# Phase 1 — Local Inference

Get Gemma 4 26B running locally on your GPU. By the end of this phase you will be able to chat with a state-of-the-art LLM in a browser with no internet connection required and no API costs.

**Time to complete:** 1-2 hours (mostly waiting for downloads)
**Disk space needed:** ~25GB free
**VRAM needed:** 20GB+ (Gemma 4 26B uses ~18GB)

> **Note on Gemma 4 26B architecture:** This is a Mixture of Experts (MoE) model. It has 25.2B total parameters but only activates 3.8B per inference — meaning it runs at roughly the speed of a 4B model while delivering the quality of a much larger one. 256K token context window.

---

## Gemma 4 Model Options

| Tag | VRAM | Parameters | Notes |
|-----|------|------------|-------|
| `gemma4:e2b` | ~5GB | 2.3B active | Edge variant, audio support |
| `gemma4:e4b` | ~7GB | 4.5B active | Edge variant, audio support |
| `gemma4:26b` | ~18GB | 3.8B active (MoE) | **Recommended for 20GB+ GPUs** |
| `gemma4:31b` | ~20GB | 30.7B dense | Most capable, needs 22GB+ VRAM |

> **Warning:** `ollama pull gemma4` (no tag) pulls the `latest` tag which maps to `e4b` — the small 4.5B edge model. Always specify the tag explicitly.

---

## Prerequisites

- Docker Desktop installed with WSL2 backend ([install guide](https://docs.docker.com/desktop/install/windows-install/))
- NVIDIA GPU drivers up to date (CUDA 12.x)
- Verify Docker is working: `docker run --rm hello-world`

---

## Step 1 — Start Ollama + Open WebUI

This repo includes a `docker-compose.yml` that starts both Ollama and Open WebUI in one command. From this directory:

```bash
docker compose up -d
```

That's it. Docker will pull both images and start the containers.

> **Already have Ollama running from a manual `docker run`?**
> You can keep using it — the compose file is just a cleaner way to manage both containers together for fresh setups. If Ollama is already up, skip to Step 2.

**What docker-compose gives you over raw `docker run`:**
- One command starts the entire stack
- Services communicate by name (`open-webui` reaches `ollama` automatically — no `host.docker.internal` needed)
- `docker compose down` cleanly stops everything
- Easier to version control and share

Verify both containers are running:
```bash
docker ps
# Should show both "ollama" and "open-webui" with status "Up"
```

---

## Step 2 — Pull Gemma 4 26B

This downloads the model weights (~18GB). Go make coffee.

```bash
docker exec ollama ollama pull gemma4:26b
```

To see what models are downloaded:
```bash
docker exec ollama ollama list
```

---

## Step 3 — Test Inference via CLI

```bash
docker exec -it ollama ollama run gemma4:26b "What is CUDA and why does it matter for AI?"
```

You should see a streamed response. Note the time — this is your baseline latency.

---

## Step 4 — Start Open WebUI

Open WebUI gives you a browser-based chat interface connected to your local Ollama instance.

```bash
docker run -d \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

Then open [http://localhost:3000](http://localhost:3000) in your browser.

On first launch it will ask you to create an admin account — this is local only, no cloud signup required.

---

## Step 5 — Benchmark

Once you can chat with Gemma locally, run the benchmark script to measure performance and compare it against Claude API:

```bash
# From the project root
python phase1-local-inference/inference_bench.py
```

This sends the same prompt to both Gemma (local) and Claude (cloud) and prints a side-by-side table:

```
Metric                   Local                    Cloud
------------------------------------------------------------------------
Model                    gemma4:26b               claude-opus-4-6
Provider                 local (Ollama)           cloud (Anthropic API)
Time to first token      2.341s                   0.823s
Total time               18.204s                  12.451s
Tokens generated         312                      287
Tokens / second          42.1 tok/s               23.0 tok/s
```

> **First run will be slower** — Ollama needs to load the model weights into VRAM. Subsequent runs are faster.

Also monitor VRAM usage while the benchmark runs (open a second terminal):
```bash
# In a separate terminal — watch GPU memory usage live
watch -n 1 nvidia-smi
# On Windows PowerShell:
nvidia-smi
```

---

## Troubleshooting

**Container starts but GPU not detected:**
- Ensure NVIDIA drivers are updated (470+ for CUDA 12)
- In Docker Desktop: Settings → Resources → check GPU is enabled
- Try: `docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi`

**Port 11434 already in use:**
- Something else is using the port: `netstat -ano | findstr 11434`
- Or Ollama is already running outside Docker

**Model download stalls:**
- Normal for large files to pause briefly — wait a few minutes
- If stuck: `docker exec ollama ollama pull gemma4:26b` (it will resume)

---

## What You Learned in Phase 1

- How Docker containers work (images, containers, volumes, port mapping)
- How WSL2 enables Linux containers on Windows with GPU passthrough
- How Ollama abstracts model loading and CUDA inference
- What Mixture of Experts (MoE) architecture is and why it matters for inference speed
- What model quantization is (Q4 = 4-bit, trades some quality for ~4x smaller size)
- Practical VRAM constraints for running large models
