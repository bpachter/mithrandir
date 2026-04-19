# Contributing to Enkidu

Thanks for your interest. Enkidu is a personal project — contributions are welcome but this isn't a large open-source org. Expect quick feedback on small, focused PRs.

---

## Getting started

### Prerequisites
- Python 3.11+
- Node.js 18+ (for the React UI)
- An NVIDIA GPU (RTX 3000+ recommended for local inference)
- Windows 10/11 (Linux/WSL2 partially supported)

### First-time setup

```bash
git clone https://github.com/bpachter/Enkidu.git
cd Enkidu

# Guided setup (installs deps, copies .env, checks Ollama)
python scripts/bootstrap.py

# Fill in your API key
notepad .env   # set ANTHROPIC_API_KEY

# Start everything
python scripts/start.py
```

### Run health checks before you start coding

```bash
python enkidu_health.py
```

---

## Development workflow

### Run the test suite

```bash
# Unit tests (fast, no LLM)
python tests/test_health.py

# Golden benchmarks (requires ANTHROPIC_API_KEY)
python tests/benchmark.py --category identity
python tests/benchmark.py --category routing
```

### Start the UI in dev mode

```bash
# Backend + frontend with hot reload
python scripts/start.py

# Backend only (if you're not touching the UI)
cd phase6-ui/server && python -m uvicorn main:app --reload
```

### Project structure

```
enkidu_health.py          Unified health checker (run first)
scripts/                  Setup and launch scripts
tests/                    Benchmark runner + golden prompts
phase1-local-inference/   Ollama + Docker
phase2-tool-use/          EDGAR screener, routing, lighting
  tools/edgar_screener.py  Financial data tool
  quant-value/            QV pipeline (data not in git)
phase3-agents/            ReAct agent, Telegram, tool registry
  enkidu_agent.py         Main agent loop
  tools/registry.py       Tool dispatch + telemetry
phase4-memory/            ChromaDB + SQLite memory
phase5-intelligence/      Signal logger, backtesting, alerts
phase6-ui/
  server/main.py          FastAPI backend
  server/voice.py         STT + TTS pipeline
  server/demos.py         Prebuilt demo definitions
  client/src/             React 18 + TypeScript + Vite
```

---

## Making changes

### Good first issues

Start here: issues labelled [`good first issue`](../../issues?q=is%3Aissue+label%3A%22good+first+issue%22).

These are typically:
- Adding a new golden prompt to `tests/golden_prompts.json`
- Fixing a typo or improving an error message
- Adding a new demo step to `phase6-ui/server/demos.py`
- Improving the health check output for a specific subsystem

### Adding a new tool

1. Write the tool function in `phase3-agents/tools/` or `phase2-tool-use/tools/`
2. Register it in `phase3-agents/tools/registry.py` with `register()`
3. Add keywords to `_TOOL_KEYWORDS` in `phase3-agents/enkidu_agent.py` so the router knows when to use it
4. Add a golden prompt in `tests/golden_prompts.json` with `must_contain_any` constraints
5. Run `python tests/benchmark.py --id your_new_id` to verify

### Adding a benchmark prompt

Edit `tests/golden_prompts.json`. Each entry needs:

```json
{
  "id": "unique_snake_case_id",
  "category": "identity|routing|tool_use|finance|cuda|voice|safety",
  "prompt": "The prompt text",
  "routing": "local|cloud|either",
  "must_contain_any": ["expected", "keywords"],
  "max_latency_ms": 30000
}
```

Run `python tests/benchmark.py --id your_id` to verify it passes before submitting.

---

## Pull request guidelines

- **One PR per concern** — don't bundle unrelated changes
- **PR title format**: `feat:`, `fix:`, `refactor:`, `test:`, or `docs:`
- **Tests must pass**: `python tests/test_health.py` and the benchmark categories relevant to your change
- **Update `.env.example`** if you added new env vars
- Fill in the PR template — especially the test plan section

---

## Release cadence

Releases are tagged when a meaningful set of features ships. There's no fixed schedule — roughly:

- **Patch** (`7.1.x`): bug fixes, test additions, doc updates
- **Minor** (`7.x.0`): new feature or subsystem
- **Major** (`x.0.0`): new phase completes

Changelogs are maintained in [CHANGELOG.md](CHANGELOG.md).

---

## Code style

- Python: PEP 8, no autoformatter enforced (yet). Match the style of the file you're editing.
- TypeScript: match the existing component patterns (functional components, Zustand store).
- No external linters required to pass CI — just the benchmark tests.

---

## Questions

Open an issue. No DMs needed.
