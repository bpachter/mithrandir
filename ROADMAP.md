# Enkidu Roadmap

Personal local AI assistant for Ben — RTX 4090, Ollama + Claude, quantitative value investing.

> **Status:** Active development. Phases 0-6 shipped. See [CHANGELOG.md](CHANGELOG.md) for what's in each release.

---

## Completed

### Phase 0-2 — Foundation
- [x] CLI REPL with Claude API integration
- [x] Ollama local inference (Gemma 4 26B, Q4_K_M)
- [x] Routing logic (local vs cloud tool calls)
- [x] SEC EDGAR quantitative value screener
- [x] RGB lighting feedback (AlienFX / Corsair)
- [x] Windows Task Scheduler automation

### Phase 3 — Agents
- [x] ReAct agent loop (multi-step reasoning)
- [x] Telegram bot interface with TLS fix
- [x] Tool registry and dispatch
- [x] Python sandbox, web search, market regime detector

### Phase 4 — Memory
- [x] ChromaDB + SQLite dual-write memory
- [x] Document RAG indexer (JOURNEY.md, codebase)
- [x] Memory bridge subprocess isolation

### Phase 5 — Intelligence
- [x] Daily signal logger (QV picks snapshot)
- [x] Backtesting engine (30/90/180/365d returns vs SPY)
- [x] Alert engine (price dips, ranking changes, perf summaries)
- [x] RL parameter optimizer for screening thresholds

### Phase 6 — UI
- [x] FastAPI + React 18 + Vite + TypeScript
- [x] Streaming chat (WebSocket + RAG tokens)
- [x] Whisper STT (local GPU, faster-whisper)
- [x] 5-tier TTS fallback: F5-TTS → Chatterbox → Kokoro → edge-tts → pyttsx3
- [x] BMO voice cloning with character FX chain
- [x] GPU/CPU/RAM real-time dashboard (2 Hz WebSocket)
- [x] Conversation history with thumbs-up/down rating

### Phase 7 — Reliability, Eval, and Productization (shipped 2026-04-18)
- [x] Unified health checks for all subsystems
- [x] Startup self-test command (`python enkidu_health.py`)
- [x] Tool-call retry with exponential backoff
- [x] In-memory telemetry ring buffer
- [x] Golden benchmark suite (15 prompts, 6 categories)
- [x] CI pipeline (GitHub Actions)
- [x] One-command Windows bootstrap
- [x] Prebuilt demo modes (local speed, EDGAR, voice, system)
- [x] Data freshness audit surface
- [x] Provenance tags on all financial answers
- [x] GitHub issue templates and PR template

---

## In Progress / Near-term

### Phase 8 — Hardening and Scale
- [ ] **24-hour soak test** — run overnight, verify no crash
- [ ] **Deterministic fallback** for every critical subsystem (documented and tested)
- [ ] **Benchmark trendline UI** in React — plot score/latency over releases
- [ ] **Freshness panel** in React — show data source ages in the UI

### Phase 9 — Expanded Financial Intelligence
- [ ] **Sector rotation signals** — macro overlay on QV picks
- [ ] **Earnings calendar integration** — flag picks with upcoming earnings
- [ ] **Short interest overlay** — surface stocks with high squeeze potential
- [ ] **DCF calculator** in python_sandbox with guided prompts
- [ ] **Multi-period comparison** — compare TTM vs prior year for a ticker

### Phase 10 — Voice 2.0
- [ ] **Sub-second TTS** via speculative decoding or streaming synthesis
- [ ] **Speaker diarization** — attribute multi-speaker recordings correctly
- [ ] **Wake word** — "Hey Enkidu" without pressing Space
- [ ] **Voice-to-chart** — "Show me NUE's EV/EBIT over 5 years" → chart

### Phase 11 — Agent Autonomy
- [ ] **Autonomous morning brief** — proactive Telegram message at 7am with regime, picks, and news
- [ ] **Portfolio monitoring daemon** — alert on material ranking changes
- [ ] **Self-improving benchmarks** — Enkidu suggests new golden prompts based on failure patterns
- [ ] **GitHub App commit** — autonomous changelog and signal log commits via bot identity

### Phase 12 — Community and Distribution
- [ ] **Docker Compose for full stack** — one `docker compose up` starts everything
- [ ] **Linux / WSL2 support** — test and document non-Windows paths
- [ ] **Video walkthroughs** — 3-part series: setup, architecture, results
- [ ] **Public benchmark leaderboard** — track score across model upgrades

---

## Known Issues

| ID | Component | Description | Priority |
|----|-----------|-------------|----------|
| #1 | Voice TTS | F5-TTS first sentence latency 1-3s | High |
| #2 | Memory | ChromaDB cold start ~15s on first query | Medium |
| #3 | EDGAR | YoY F-Score components missing (pipeline limitation) | Medium |
| #4 | UI | No error page for backend-down state | Low |
| #5 | Telegram | TLS ALPN workaround required on Windows | Low |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.  
Good first issues are labelled [`good first issue`](../../issues?q=is%3Aissue+label%3A%22good+first+issue%22).  
Benchmark-needed issues are labelled [`benchmark-needed`](../../issues?q=is%3Aissue+label%3Abenchmark-needed).

Questions? Open an issue — no DM needed.
