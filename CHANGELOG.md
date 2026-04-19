# Changelog

All notable changes to Enkidu are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: `<phase>.<feature>.<patch>` — major version tracks completed phase.

---

## [7.1.0] — 2026-04-18

### Added

**Phase 1 — Reliability Hardening**
- `enkidu_health.py`: unified health checker for all subsystems (Ollama, Anthropic API, memory bridge, voice workers, Telegram, QV data, Python deps). Runs in parallel, exits 1 on critical failure.
- `GET /api/health/detailed`: full diagnostic report via FastAPI.
- `GET /api/telemetry`: per-tool call latency and error rate from in-memory ring buffer.
- Tool dispatch retry logic: automatic exponential backoff (up to 2 retries) for transient errors in `registry.dispatch()`.

**Phase 2 — Evaluation + Regression Suite**
- `tests/golden_prompts.json`: 15 golden prompts across identity, routing, tool_use, finance, cuda, voice, and safety categories.
- `tests/benchmark.py`: benchmark runner with category/ID filters, fail-fast mode, JSON scorecard output, and trendline viewer. CI gate: fails if score < 0.85.
- `tests/test_health.py`: fast unit tests for the health check module (no LLM required).
- `.github/workflows/benchmark.yml`: CI pipeline — unit tests on every PR, golden benchmarks + latency regression on main push.

**Phase 3 — One-Command Install**
- `scripts/bootstrap.py`: guided Windows setup (Python, `.env`, deps, Node.js, Ollama, memory bridge). Modes: `--check`, `--yes`, `--skip-ollama`.
- `scripts/start.py`: unified launcher with readiness probe, auto-browser open, clean Ctrl+C shutdown.
- `scripts/start.bat` / `scripts/bootstrap.bat`: Windows wrappers for the above.

**Phase 4 — Productize Killer Demos**
- `phase6-ui/server/demos.py`: 4 prebuilt demo modes — local speed + privacy, EDGAR financial analysis, voice agent, system monitoring.
- `GET /api/demos` and `GET /api/demos/{id}` endpoints.
- `DemoPanel.tsx`: React component with step-by-step demo walkthrough, progress bar, voice-only step tips, and Run buttons.
- DEMOS tab added to App.tsx left column.

**Phase 5 — Data and Finance Pipeline Trust**
- `phase6-ui/server/data_freshness.py`: freshness audit for 7 data sources (QV portfolio, metrics, companies, sectors, memory DB, signals DB, regime model).
- `GET /api/freshness`: data freshness report for UI/CI.
- Provenance metadata added to `GET /api/portfolio`: source, last_updated, age_hours, freshness, filing period.
- `_get_provenance_block()` in `edgar_screener.py`: structured provenance injected into every [EDGAR CONTEXT] with source, TTM period, timestamp, freshness flag, and confidence advisory.

**Phase 6 — Distribution and Community Loop**
- GitHub issue templates: bug report, feature request, good first issue, benchmark needed.
- PR template with test plan checklist and co-author attribution.
- `CHANGELOG.md` (this file) and `ROADMAP.md`.

---

## [7.0.0] — 2026-04-17 (pre-sprint baseline)

### Summary
Full-stack local AI assistant with RTX 4090 inference, ReAct agent, quantitative value screener, voice pipeline, React UI, and Telegram bot. See `README.md` for the complete feature list.

**Components shipped:**
- Phase 0-2: CLI REPL, Ollama/Gemma4 inference, tool-use routing, EDGAR screener, RGB lighting
- Phase 3: ReAct agent loop, Telegram bot, tool registry
- Phase 4: ChromaDB + SQLite dual-write memory, document RAG indexer
- Phase 5: Signal logger, performance tracker, alert engine, RL optimizer
- Phase 6: FastAPI + React UI, Whisper STT, F5-TTS/Kokoro/edge-tts voice chain, streaming TTS with character FX

---

## How to read this changelog

- **Added** — new features and files
- **Changed** — modifications to existing behaviour
- **Fixed** — bug fixes
- **Removed** — deprecated or deleted features
- **Security** — vulnerability fixes
