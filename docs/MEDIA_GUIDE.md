# Media Capture Guide

A checklist of every screenshot, GIF, and clip referenced from the Enkidu docs and the LinkedIn post. Capture these once and the docs become handhold-friendly for both technical and non-technical readers.

Tools that work well on Windows:
- **Screenshots** → Snipping Tool (Win + Shift + S) or [ShareX](https://getsharex.com/) (free, scriptable)
- **GIFs / short clips** → [ScreenToGif](https://www.screentogif.com/) (free, frame-level editing) or ShareX → "Screen recording (GIF)"
- **Annotations / arrows** → ShareX or [Greenshot](https://getgreenshot.org/)

For each slot below: the **filename** is what the README expects, the **frame** describes what to capture, and **caption** is the alt-text / figure caption to use.

---

## Hero / Repo-level

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Repo hero (top of `README.md`) | `assets/hero-enkidu-ui.png` | Full Enkidu UI mid-stream — chat panel showing a Gemma response, GPU sparklines visible top-right, market panel populated | "Enkidu running locally — Gemma 4 26B streaming on an RTX 4090" |
| Architecture diagram (rendered) | `assets/architecture-diagram.png` | Either render the existing ASCII diagram in the README as a clean SVG, or screenshot a draw.io / Excalidraw recreation | "Enkidu system overview — interfaces, routing, tools, memory" |
| Hardware shot (optional but powerful for LinkedIn) | `assets/hardware-rig.jpg` | Photo of the actual desktop / GPU / RGB lighting in idle blue | "The hardware: one RTX 4090, no cloud" |

---

## Phase 1 — Local Inference

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Docker compose up | `assets/phase1-docker-compose-up.gif` | Terminal: `docker compose up -d` → containers start → `docker ps` showing both running | "One command brings up Ollama + Open WebUI" |
| Pulling Gemma 4 | `assets/phase1-ollama-pull.gif` | `docker exec ollama ollama pull gemma4:26b` showing progress bar | "Pulling 18 GB of model weights" |
| First chat in Open WebUI | `assets/phase1-openwebui-chat.png` | Browser at `localhost:3000` mid-response | "First chat with a local frontier model" |
| Benchmark results | `assets/phase1-benchmark.png` | Terminal output of `inference_bench.py` showing the 144 tok/s number side-by-side with Claude | "Local Gemma vs cloud Claude — same prompt" |
| `nvidia-smi` during inference | `assets/phase1-nvidia-smi.png` | `nvidia-smi` output with VRAM at ~18 GB used and Ollama process visible | "What 18 GB of VRAM looks like" |

---

## Phase 2 — Tool Use & Routing

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Routing decision in REPL | `assets/phase2-routing-decision.gif` | Terminal: type a short query → "[ROUTING: LOCAL]" prints → Gemma responds; then a long analytical query → "[ROUTING: CLOUD]" → Claude responds | "Routing in action — local for short, cloud for heavy" |
| EDGAR tool answering ticker question | `assets/phase2-edgar-tool.png` | REPL transcript of "how is NUE performing?" with `[EDGAR CONTEXT]` block visible above the answer | "The model reasons over real SEC filings, not memorised data" |
| QV portfolio top picks | `assets/phase2-qv-portfolio.png` | Output of "top 10 most undervalued stocks" with the table | "360 stocks pre-screened from 9,867 filings" |
| RGB keyboard during inference | `assets/phase2-rgb-inference.gif` | Webcam / phone clip of keyboard cycling galaxy purple while Gemma streams (hold the phone still, 5 s loop) | "Visual indicator: lights spin while the GPU thinks" |

---

## Phase 3 — Agentic Orchestration

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Telegram chat on iPhone | `assets/phase3-telegram-iphone.png` | iPhone screenshot of the bot answering a stock question with multi-step output | "Same agent, accessible from anywhere via Telegram" |
| ReAct loop in console | `assets/phase3-react-loop.gif` | Terminal log of an agent run: Thought → Action → Observation → Thought → Final Answer | "ReAct loop — reason, act, observe, repeat" |
| Pydantic self-correction | `assets/phase3-self-correction.png` | Log excerpt where the agent emits a bad tool name, gets a ValidationError back, and recovers next iteration | "When the model gets it wrong, the loop teaches it" |
| HMM regime injection | `assets/phase3-regime-injection.png` | Snippet of system prompt showing `[MARKET REGIME]: Contraction (78% confidence)` | "Every query is regime-aware" |

---

## Phase 4 — Memory + RAG

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Memory recall across sessions | `assets/phase4-memory-recall.gif` | Two-session demo: Session 1 user mentions "DUK", quits; Session 2 asks "what was that utility we discussed?" — agent recalls | "Memory that survives a restart" |
| Codebase RAG hit | `assets/phase4-search-docs.png` | REPL: ask "why did we add HMM regime detection?" → answer cites JOURNEY.md verbatim | "It can search its own codebase" |
| ChromaDB stats | `assets/phase4-stats.png` | `/stats` output from Telegram showing memory exchange count + document chunks | "Local vector DB, no cloud" |

---

## Phase 5 — Intelligence (Backtesting + Alerts)

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Performance vs SPY chart | `assets/phase5-performance-chart.png` | Matplotlib chart of QV signals vs SPY at 30/90/180/365-day horizons | "QV signals vs benchmark, by horizon" |
| Telegram dip alert | `assets/phase5-dip-alert.png` | iPhone screenshot of the proactive alert message | "Proactive alerts, pushed by Windows Task Scheduler" |
| Signals DB schema | `assets/phase5-signals-db.png` | DB Browser screenshot of `signals.db` rows | "Every pick logged, every horizon tracked" |

---

## Phase 6 / 7 — UI + Voice

| Slot | Filename | Frame | Caption |
|---|---|---|---|
| Full UI hero shot | `assets/phase6-ui-hero.png` | Full window screenshot of the 3-column dashboard at idle | "The Blade Runner terminal — custom React UI" |
| Streaming response | `assets/phase6-streaming.gif` | 8-second clip of typing a query and watching tokens stream | "Live token streaming via WebSocket" |
| GPU sparklines live | `assets/phase6-gpu-sparklines.gif` | 6 sparkline panels updating in real time during inference | "GPU/VRAM/temp/power telemetry at 2 Hz" |
| Voice round-trip (subtitled) | `assets/phase7-voice-roundtrip.mp4` | 15-second clip: click mic → speak → see transcription → hear cloned-voice response. Add subtitles for silent autoplay on LinkedIn | "Speech in, cloned voice out — all on the same GPU" |
| Oscilloscope waveform | `assets/phase7-waveform.gif` | The audio visualiser pulsing during a TTS playback | "Real-time waveform from Web Audio API" |

---

## LinkedIn-specific assets

For the post itself, prepare:

1. **Hero (1200 × 627)** — `assets/linkedin-hero.png` — UI screenshot cropped landscape
2. **Carousel** (4 slides, 1200 × 1200 each):
   - Slide 1: Bold text "I'm running a frontier LLM on my desk." + Gemma logo
   - Slide 2: Architecture diagram
   - Slide 3: Benchmark table (144 tok/s vs 31 tok/s)
   - Slide 4: "Read the journey → github.com/bpachter/enkidu"
3. **Demo GIF (≤ 5 MB, ≤ 8 s)** — `assets/linkedin-demo.gif` — UI mid-stream with sparklines spiking

Square Canva or Figma templates work well. Keep the colour palette aligned with the UI: deep navy/black background, amber `#ff9500`, cyan `#00e5ff` accents.
