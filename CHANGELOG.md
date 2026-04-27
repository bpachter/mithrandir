# Changelog

All notable changes to Mithrandir are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: `<phase>.<feature>.<patch>` — major version tracks completed phase.

---

## [Unreleased]

### Added — Phase 8: Local-Only Research Pipeline
- New `phase8-local-research/` module: structured, Gemma-only research workflow with no dependency on external planning models.
- `pipeline_contracts.py`: Pydantic contracts for two research domains — data center siting rows and LLM release history rows.
- `stages.py`: 5-stage pipeline — discovery, source verification, normalization, QA/conflict checks, export.
- `run_pipeline.py`: CLI runner (`python phase8-local-research/run_pipeline.py --domain datacenter|llm --input-file <brief>`), with `--target-count`, `--run-id`, and `--out-dir` flags.
- `exporters.py`: CSV and JSON export with provenance metadata included in every artifact.
- `local_gemma_client.py`: lightweight Ollama/Gemma client wrapper for the research pipeline.
- Stage artifacts written to `phase8-local-research/output/<domain>/<run_id>/stage{1-4}_*.json` + `summary.json`.
- Final exports: `datacenter_research_local_<run_id>.csv/.json` and `llm_releases_local_<run_id>.csv/.json`.

### Added — UI: Consciousness / Mind Panel
- New `MindPanel.tsx` component in the right column (`Mind` tab, default selected at launch).
- Animated sagittal brain SVG with anatomically-placed lobes (frontal, parietal, occipital, temporal, cerebellum), major sulci (central, lateral, parieto-occipital, calcarine), and brainstem connector.
- 7 synaptic pathways with traveling pulse animations; central thalamus glow core.
- Awareness stats section: total exchange count, valued exchanges, rated count, awakened date.
- Reflections system: Mithrandir generates structured self-reflections over recent memory context (TITLE / REFLECTION / IMPLICATION / TAGS format), stored in localStorage with up to 18 entries.
- Knowledge map: top-20 topic frequency bars from conversation history.
- `AWARENESS` header with live pulse indicator.
- Right-column tab order changed: **Mind** (left, default) | **Vault** (memory browser).

### Added — UI: Celestial Background + Day/Night Theme
- `CelestialBackground.tsx`: animated WebGL-free canvas layer — parallax star fields (two layers), procedural shooting stars, and aurora borealis bands.
- Auto day/night theme switching: polls EST clock every 30 s; transitions to `light` theme 7 AM–6 PM, `dark` otherwise. Smooth opacity fade on switch.
- Manual override: day/night toggle button in header (moon/sun icon).
- CSS `data-theme` attribute on `<html>` drives the full design token set.

### Added — UI: DevPanel
- New `DevPanel.tsx` component accessible via DEV mode toggle in the header.
- Surfaces health check status, telemetry ring buffer, and raw API state for development debugging.

### Added — UI: MetricDetailModal
- `MetricDetailModal.tsx`: click-to-drill-down modal for GPU/system performance metrics — shows sparkline history, min/max/avg, and contextual notes.

### Added — Phase 7 (extended): Data Center Siting Selection
- New `phase7-datacenter-siting/` module: quantitative siting engine for hyperscale AI data centers, mirroring the QV-screener pattern (transparent multi-factor model, percentile-ranked composites, public-source provenance on every input).
- 14-factor catalog: power_transmission, power_cost, power_carbon, gas_pipeline, fiber, water, climate, hazard, land_zoning, tax_incentives, permitting, latency, labor, community.
- Composite scorer (`src/score.py`) emits a single 0-10 score per site with cohort-median imputation, kill-criteria gate, and per-factor provenance preserved in the output.
- Three archetype weight presets in `config/weights.json`: `training` (power-dominant), `inference` (latency-dominant), `mixed` (default).
- Public-source ingest stubs (HIFLD, EIA, FERC, ISO/RTO queues, FCC, PeeringDB, USGS, NOAA, FEMA, EPA, IRS OZ, BLS, county GIS) — each documented with format, license, and refresh cadence in `docs/DATA_SOURCES.md`.
- CLI: `python -m src.cli score --input <csv>` and `python -m src.cli ingest --factor <name>|--all [--max N]` plus `python -m src.cli status`.
- Phase 6 UI backend wired with `/api/siting/factors`, `/api/siting/score`, `/api/siting/sample`.
- Smoke run on 10 known hyperscaler hot zones (Abilene, Loudoun, Douglas, Phoenix West Valley, Altoona, Mount Pleasant, Quincy, Sarpy, Clarksville, Temple) returns valid composites end-to-end (uniform 5.0 until ingest lands).

### Added — Phase 7 ingest layer (real public data)
- `src/ingest/arcgis_client.py`: paginated ArcGIS REST FeatureServer downloader with `tenacity` retries, dated cache writes (`data/raw/<source>/<layer>/<YYYY-MM-DD>/`), manifest provenance.
- `src/ingest/spatial_index.py`: lazy in-memory spatial index — line geometries densified at ~1mi spacing, 5° degree-prefilter + haversine NN, `nearest_distance_mi()` and `features_in_bbox()` accessors.
- `src/ingest/hifld.py`: 5 layers wired to live HIFLD ArcGIS endpoints (transmission ≥230 kV, in-service substations, natural gas pipelines, long-haul fiber, internet exchange points).
- `src/ingest/eia.py`: EIA v2 industrial retail electricity prices (TTM rolling), state-keyed lookups for `power_cost`.
- Real-data factors: `power_transmission`, `gas_pipeline`, `fiber` (haversine NN to ingested infrastructure with kill flags), `latency` (NN to nearest IXP), `power_cost` (state lookup).

### Added — Phase 6 UI: enterprise-grade siting map (Paces-style)
- New full-screen workspace toggle (CONSOLE / SITING) in the header.
- `phase6-ui/client/src/components/SitingPanel.tsx` + `SitingPanel.css` — MapLibre GL dark-matter basemap with:
  - Candidate-site markers colored by composite score (red→amber→green gradient), score label, halo glow, click-to-detail.
  - Toggleable overlay layers: transmission, substations, pipelines, long-haul fiber, IXPs — bbox-filtered fetches via `/api/siting/layer/{key}?bbox=` on every map move.
  - Archetype switcher (training / inference / mixed) with hot rescore.
  - Per-factor weight sliders (sidebar) bounded to default ±, "RESCORE" button, reset link.
  - Right-rail ranked list with click-to-fly, kill-flag strikethrough.
  - Selected-site detail card: composite, kill tags, weighted factor breakdown table, imputed-factors note.
  - Layer rows show "not cached" hint linking to the `python -m src.cli ingest --all` workflow.
- New `/api/siting/layers` (catalog + cache status) and `/api/siting/layer/{layer_key}?bbox=&limit=` (GeoJSON FeatureCollection with `_meta` provenance) endpoints in `phase6-ui/server/main.py`.
- Frontend deps: `maplibre-gl@^5.23.0` + `@types/maplibre-gl`.
- Frontend API helpers: `fetchSitingFactors`, `fetchSitingSample`, `scoreSites`, `fetchSitingLayers`, `fetchSitingLayerGeoJSON` plus `SiteResultDTO`/`SitingLayer` types.

---

## [7.1.0] — 2026-04-18

### Added

**Phase 1 — Reliability Hardening**
- `mithrandir_health.py`: unified health checker for all subsystems (Ollama, Anthropic API, memory bridge, voice workers, Telegram, QV data, Python deps). Runs in parallel, exits 1 on critical failure.
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
