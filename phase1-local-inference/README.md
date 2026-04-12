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

## Step 1 — Start Ollama

Ollama manages local LLM downloads and serves them via a local HTTP API.

```bash
docker run -d \
  --gpus all \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  --name ollama \
  ollama/ollama
```

**What each flag does:**
- `--gpus all` — passes your GPU through to the container (CUDA access)
- `-v ollama:/root/.ollama` — persistent volume so downloaded models survive container restarts
- `-p 11434:11434` — exposes Ollama's API on localhost:11434
- `--name ollama` — names the container so you can reference it easily

Verify it's running:
```bash
docker ps
# Should show the ollama container with status "Up"
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

Once you can chat with Gemma locally, measure performance:

```bash
python inference_bench.py
```

*(See `inference_bench.py` in this folder — to be built once Ollama is running)*

Record:
- Time to first token (latency)
- Tokens per second (throughput)
- GPU VRAM usage (`nvidia-smi` in a separate terminal)
- Compare the same question to Claude API response time

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
