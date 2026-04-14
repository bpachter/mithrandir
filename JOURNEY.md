# The Enkidu Journey

A running log of what was actually built, in order, including mistakes. Updated as each step completes.

The goal of this log is to give future builders an honest picture of the process — not just the commands that worked, but the things that broke and why.

---

## Phase 0 — Claude API Proof of Concept

**Date:** April 12, 2026 | **Status:** ✅ Complete

### What was done
- Set up Python 3.11 environment via Anaconda
- Installed `anthropic`, `python-dotenv`, `requests`
- Created `test_claude.py` — a minimal script that calls the Claude API and prints a response
- Initialized a local git repo, pushed to GitHub

### What broke

**Dependency version conflicts.** The Anaconda base environment had older versions of packages (pydantic, requests, etc.). Pinning specific versions in requirements.txt caused install failures. Fix: use flexible version ranges (`anthropic>=0.94.0`) instead of exact pins.

**Committed .env to GitHub.** The `.env` file containing the API key was accidentally included in the first commit. GitHub's push protection caught it. Key was immediately rotated in the Anthropic console. Fix: add `.env` to `.gitignore` *before* the first commit.

**`.gitignore` didn't work.** The file was saved as `.gitignore.txt` — Windows sometimes adds the extension silently. Git never read it. Fix: rename to `.gitignore` with no extension.

**Stale model string.** `test_claude.py` was using `claude-opus-4-1-20250805`, a model ID from August 2025 that had since been rotated. Fix: update to `claude-opus-4-6` (current as of April 2026).

**Git history contained the leaked key.** Even after removing `.env` and updating `.gitignore`, the original commit still had the key embedded in history. GitHub's push protection blocked all future pushes. Fix: used `git-filter-repo` to rewrite history, scrubbing `.env` from every commit, then force-pushed.

### What was learned
- Always create `.gitignore` before the first commit and verify it's working (no `.txt` extension)
- API keys rotate — never hardcode or commit them; rotate immediately if leaked
- Git history is permanent unless you rewrite it — `git-filter-repo` is the right tool for scrubbing secrets
- Anaconda base environments accumulate cruft; flexible version pinning is safer than exact pins

### Files created
- `test_claude.py` — Claude API hello world
- `requirements.txt` — Python dependencies
- `.gitignore` — excludes `.env`, `__pycache__`, `.venv`, etc.
- `.env.example` — template for required secrets
- `.env` (not committed) — holds `ANTHROPIC_API_KEY`

---

## Phase 1 — Local Inference Setup

**Date:** April 12, 2026 | **Status:** ✅ Complete

### What was done
- Verified WSL2 was already installed (Ubuntu distro, WSL version 2) — no manual install needed
- Installed Docker Desktop 4.68.0 (Windows AMD64)
- Verified Docker engine working: `docker run --rm hello-world`
- Pulled and started Ollama container with GPU passthrough
- Pulled Gemma 4 26B model weights (~17GB) into Ollama
- Started Open WebUI — browser chat interface at localhost:3000
- Ran inference benchmark comparing local Gemma vs Claude API

### What broke

**Started pulling the wrong model.** Initially pulled `gemma3:27b` (Gemma 3) before realizing Gemma 4 was available on Ollama. Cancelled at 35% and switched to `gemma4:26b`. No harm done — partial download was discarded.

**`gemma4:latest` is not the big model.** Running `ollama pull gemma4` without a tag pulls `latest`, which maps to `e4b` — a tiny 4.5B edge model. Always specify the tag explicitly: `gemma4:26b`.

**`.venv` activation doesn't always work in PowerShell.** The terminal showed `(.venv)` in the prompt but `python` still resolved to the global Python 3.12 install. `requests` and `anthropic` weren't in the global env, causing `ModuleNotFoundError`. Fix: use `.venv/Scripts/python.exe` directly to guarantee the right interpreter.

**Gemma doesn't know where it's running.** When asked "Where do you live?", Gemma responded "Google's data centers." This is wrong — it's running on a local RTX 4090. Gemma knows its training origin (Google DeepMind) but has no awareness of its runtime environment. Open-weight models have no way to detect where they've been deployed.

### What was learned
- Docker Desktop uses WSL2 as its backend on Windows 11 — this enables GPU passthrough to Linux containers
- The `-v ollama:/root/.ollama` volume flag is critical — without it, the 18GB download disappears when the container restarts
- `--gpus all` passes the RTX 4090 through via the NVIDIA Container Toolkit (bundled with Docker Desktop)
- Gemma 4 26B is a **Mixture of Experts (MoE)** model: 25.2B total parameters, only 3.8B active per inference — fast like a 4B model, quality of a much larger one, 256K token context window
- Gemma 4 26B uses ~18GB VRAM — fits in the 4090's 24GB with ~6GB headroom
- Docker Compose is cleaner than raw `docker run` for multi-container setups — services communicate by name, one command starts the whole stack
- Ollama's streaming API returns NDJSON — each line is a JSON object; the final chunk (`done: true`) contains built-in timing stats in nanoseconds (`eval_count`, `eval_duration`), making tokens/sec trivial to calculate
- Open WebUI runs with `--restart always` — it starts automatically when Docker starts, which starts automatically on Windows boot. No manual restarts needed.
- Gemma stays in VRAM until idle for ~5 minutes (Ollama default). Set `OLLAMA_KEEP_ALIVE=-1` to keep it loaded permanently and eliminate cold starts.

### Benchmark results (cold start — model loading into VRAM for first time)

Prompt: *"Explain how a transformer neural network works. Be thorough but concise. Aim for about 200 words."*

| Metric | Gemma 4 26B (local) | Claude Opus 4.6 (cloud) |
|--------|-------------------|------------------------|
| Time to first token | 6.36s *(VRAM load penalty)* | 1.60s |
| Total time | **8.13s** | 10.20s |
| Tokens generated | 1077 | 315 |
| Tokens / second | **144 tok/s** | 31 tok/s |
| Cost | **$0** | ~$0.02 |

**Interpretation:**
- Local wins on throughput (144 vs 31 tok/s) and total time once warm
- Cloud wins on time-to-first-token — Anthropic's infrastructure is always warm; the 6s cold start only happens once per session
- Response quality was comparable — Gemma more verbose, Claude more structured
- **Routing conclusion:** use local for everyday queries (free, fast, private); use cloud only when quality is the deciding factor

### Files created
- `phase1-local-inference/docker-compose.yml` — starts Ollama + Open WebUI in one command
- `phase1-local-inference/inference_bench.py` — benchmarks local vs Claude API side-by-side

---

## Phase 2 — Tool Use and Routing Logic

**Date:** April 12, 2026 | **Status:** ✅ Complete

### What was built

**Routing logic (`phase2-tool-use/router.py`)**
- Heuristic router that classifies every query as LOCAL (Gemma) or CLOUD (Claude)
- Signals that push to cloud: prompt length > 500 tokens, complexity keywords (analyze, compare, explain why, etc.), tool requirements
- Default is LOCAL — biases toward free and private
- Routing decision carries a reason string and estimated token count, printed before each response

**Unified entry point (`enkidu.py`)**
- Single REPL loop replacing the separate test scripts from Phase 1
- Streams from Ollama (local) or Anthropic SDK (cloud) based on routing decision
- Session stats tracking: queries sent, local vs cloud split, total tokens
- Slash commands: `/local`, `/cloud`, `/stats`, `/refresh`, `/exit`

**Tool: system_info (`phase2-tool-use/tools/system_info.py`)**
- Pattern: Python fetches real data → injected as `[SYSTEM CONTEXT]` block → LLM reasons over it
- Queries `nvidia-smi` for GPU temperature, VRAM, clock speed, power draw
- Queries `psutil` for CPU % and RAM usage
- Trigger keywords: "gpu", "vram", "temperature", "cpu", "ram", etc.
- Before this tool: Gemma would answer hardware questions by hallucinating. After: it reports real live numbers.

**Tool: edgar_screener (`phase2-tool-use/tools/edgar_screener.py`)**
- Queries the QuantitativeValue processed datasets (1,294 screened stocks, 186K rows of fundamentals)
- Handles three query types: specific ticker lookup, top-N by value composite, filtered by F-Score/debt
- Falls back from screened portfolio → full metrics dataset for tickers that didn't pass the screen (e.g., DUK — Duke Energy is a utility, excluded by the quant value methodology)
- `/refresh` command wipes cached EDGAR JSON files and re-runs the full QuantitativeValue pipeline (~66 min)
- Refresh shows a time estimate broken down by stage before asking for confirmation

### What broke

**Column names didn't match the actual CSVs.**
Exploring the data in Windows Explorer showed column names like `overall_rank`, `quality_rank`, `value_rank`. None of those exist in the actual files. Actual columns are `value_composite`, `quality_score`, `p_franchise_power`, `ev_ebit_rank`. Always query the real file rather than trusting UI previews.

**DUK not in the screened portfolio.**
Duke Energy (DUK) didn't pass the quantitative value screen — utilities are capital-heavy, rate-regulated, and fail the EV/EBIT and debt filters by design. The tool initially returned nothing for DUK. Fix: added a fallback that queries the full `metrics.csv` (all 186K rows) when a ticker isn't in the portfolio, so any public company is accessible.

**Ticker detection was too aggressive.**
`get_context()` was calling `query.upper().split()` and testing every word against the ticker database. Queries like "what is the **cash** flow" matched `CASH` (a real ticker). "show me **top** 10 stocks" matched `TOP`. "what **ARE** the most undervalued" matched `ARE` (Alexandria Real Estate Equities — also a real ticker). Every common English word that happened to be 2-5 letters was getting looked up.

Fix: only detect tickers if the word is already uppercase in the original query (user deliberately typed `DUK`) or appears as a possessive (`DUK's`). Added a `_NOT_TICKERS` blocklist for English function words that match the pattern: `ARE`, `TOP`, `MOST`, `WILL`, `HAVE`, `WHAT`, `THEY`, etc.

**`run_all.py` failed with `ModuleNotFoundError: No module named 'universe_fixed'`.**
The QuantitativeValue pipeline's `run_all.py` imports `universe_fixed`, but that file had been moved to `archive/test_files/` at some point. A compiled `.pyc` still existed in `__pycache__` (evidence it used to work), but the source was gone. Fix: copied `universe_fixed.py` back to `src/`.

**`edgartools` and its dependencies weren't installed.**
The edgar pipeline uses the `edgartools` Python package, which wasn't in any environment. Normally a `pip install` away, but the global Python's `Scripts/` directory had a Windows file-locking issue — pip kept failing with `[WinError 2] .exe -> .exe.deleteme`. Every transitive dependency that included a console script (rich, httpx, markdown-it-py, unidecode...) failed to install.

Fix: created a dedicated `.venv` inside the QuantitativeValue project directory. The venv has its own isolated `Scripts/` folder with no conflicts. `refresh_data()` in edgar_screener.py now detects the QV venv and uses its Python interpreter when launching the pipeline subprocess.

### What was learned
- The tool injection pattern works cleanly: Python fetches real data → formatted as a `[CONTEXT]` block → prepended to the prompt → LLM reasons over grounded facts instead of hallucinating. Same pattern scales to any external data source.
- Ticker detection in natural language is genuinely hard. Even a "require uppercase" heuristic isn't enough — `ARE` is both a common English verb and a real REIT ticker (Alexandria Real Estate). Blocklists of function words are necessary.
- Python subprocess `cwd` is not enough for projects that rely on relative imports — you also need `PYTHONPATH` set to the `src/` directory.
- When `pip install` fails on Windows due to file locks, creating a fresh venv is cleaner than fighting the global environment. The venv gets its own `Scripts/` with no pre-existing lock conflicts.
- Always check `.pyc` files in `__pycache__` when debugging missing modules — they're evidence of what *used to* be there before someone archived it.

**Tool: lighting (`phase2-tool-use/tools/lighting.py`)**
- RGB lighting effects on the Corsair K70 keyboard while local GPU inference is running
- Cycles through the full HSV color spectrum at 400 deg/s, 30 fps
- Implemented as a subprocess (not a thread) — openrgb-python's TCP socket only flushes to hardware from the Python main thread; daemon threads silently do nothing
- `inference_start()` spawns the subprocess, `inference_stop()` terminates it and restores lights to off
- Requires OpenRGB running with SDK Server enabled (port 6742); gracefully silent no-op if OpenRGB isn't running

### What broke (continued)

**Full QV pipeline only ran through Step 4 (metrics).**
`run_all.py` ends after computing `metrics.csv`. The actual screened portfolio (`quantitative_value_portfolio.csv`) requires a separate script (`quantitative_value.py`) that adds market pricing data, computes enterprise values, runs risk screening, and filters to the cheapest / highest quality stocks. The `/refresh` command was only calling `run_all.py`, so the screened portfolio was never regenerated.

Fix: updated `refresh_data()` to run `quantitative_value.py` as a second step after `run_all.py`.

**`metrics.csv` has no `ticker` column — only `cik`.**
`companies.csv` has the ticker → CIK mapping, but `quantitative_value.py` expected `ticker` to already be in `metrics_df`. Every place that tried `metrics_df['ticker']` raised `KeyError`.

Fix: join `metrics.csv` with `companies.csv` on `cik` before creating the screener. Also deduplicate on `cik` first — `companies.csv` maps multiple tickers to one CIK (e.g., GOOGL and GOOG both map to CIK 1652044), and a naive merge explodes the row count.

**DefeatBeta WSL path was wrong.**
`defeatbeta_bridge.py` used `$HOME/defeatbeta_env/bin/python3` as the default Python path. When passed to WSL via subprocess, `$HOME` was expanded by the Windows shell to `/c/Users/benpa`, but the actual environment is at `/root/defeatbeta_env` (WSL runs as root). Fix: hardcode `/root/defeatbeta_env/bin/python3`.

**`defeatbeta_bridge.py` relative path broke when running outside `src/`.**
`bridge_dir` defaulted to `Path("../data/defeatbeta_bridge")`. When `quantitative_value.py` is run from the project root, this resolved to `~/data/defeatbeta_bridge` (wrong). Fix: use `Path(__file__).parent.parent / "data" / "defeatbeta_bridge"` — absolute, relative to the source file.

**Same issue with `market_data.py` cache path.**
`cache_dir = Path("data/market_cache")` resolved to `src/data/market_cache/` when run from `src/`, but `data/market_cache/` when run from project root. Fix: `Path(__file__).parent.parent / "data" / "market_cache"`.

**`price()` returns OHLCV — no market cap.**
The bridge script called `ticker.price()` and tried `getattr(latest, 'market_cap', None)`. Price data rows don't carry market cap, so all market_caps were NaN. Without market cap, enterprise value couldn't be computed, so EV/EBIT was NaN for every company, and the value composite was all NaN — zero stocks passed the screen.

Fix: call `ticker.market_capitalization()` separately to get the current market cap. The method returns a DataFrame with `market_capitalization` and `shares_outstanding` columns.

**Em-dash `—` in bridge script caused `SyntaxError: Non-UTF-8 code` in WSL.**
The Python source code written by `create_wsl_fetch_script()` contained an em-dash in a comment. When the Windows side writes a `\x97` byte (cp1252 em-dash) into a .py file and WSL Python reads it as UTF-8, it fails with `SyntaxError: Non-UTF-8 code starting with '\x97'`. Fix: replace `—` with `-` in all embedded WSL script comments.

**Negative EV/EBIT ranked as "cheapest."**
Companies with negative enterprise value (cash > market cap + debt) but positive EBIT get EV/EBIT < 0. The percentile ranker treats the most negative values as "cheapest" (rank = 0). This caused tiny micro-caps with structurally odd balance sheets to dominate the top of the screen.

Fix: null out non-positive EV ratio values before computing percentile ranks. A company with negative EV/EBIT is not "cheap" by the QV methodology — it's either a data artifact or an edge case that shouldn't be valued this way. Also added a pre-rank filter requiring positive EBIT.

**`save_market_data_cache` was commented out.**
The market data fetch (DefeatBeta for 3,000 tickers, ~20 min) ran every single screen because results were never cached. The cache would have been populated with fresh data, making subsequent runs instant. Fix: uncomment the save call.

### What was learned
- The tool injection pattern works cleanly: Python fetches real data → formatted as a `[CONTEXT]` block → prepended to the prompt → LLM reasons over grounded facts instead of hallucinating. Same pattern scales to any external data source.
- Ticker detection in natural language is genuinely hard. Even a "require uppercase" heuristic isn't enough — `ARE` is both a common English verb and a real REIT ticker (Alexandria Real Estate). Blocklists of function words are necessary.
- Python subprocess `cwd` is not enough for projects that rely on relative imports — you also need `PYTHONPATH` set to the `src/` directory.
- When `pip install` fails on Windows due to file locks, creating a fresh venv is cleaner than fighting the global environment. The venv gets its own `Scripts/` with no pre-existing lock conflicts.
- Always check `.pyc` files in `__pycache__` when debugging missing modules — they're evidence of what *used to* be there before someone archived it.
- openrgb-python's TCP socket only flushes to hardware from the Python main thread. Running it in a daemon thread silently does nothing — no errors, no visual output. Subprocess is the correct pattern.
- `defeatbeta_api.data.ticker.Ticker.price()` returns OHLCV only. Market cap requires a separate call to `Ticker.market_capitalization()`. A naive "get it from the price DataFrame" will always return NaN.
- Any time Python source code is being generated by Python (e.g., a subprocess script as a string literal), check every non-ASCII character. An em-dash `—` stored as cp1252 `\x97` will cause a `SyntaxError: Non-UTF-8 code` when WSL Python tries to parse it as UTF-8.
- Use `Path(__file__)` for any relative paths in library modules — `Path("relative/path")` breaks when the calling code runs from a different working directory.
- For percentile-ranked screens, non-positive ratios must be nulled before ranking. A ratio of -600 is the most "negative" and would rank as "cheapest," which is nonsensical and produces garbage output.

### Files created / modified
- `enkidu.py` — main REPL entry point; added lighting integration, simplified `/refresh`
- `phase2-tool-use/router.py` — routing logic (LOCAL vs CLOUD)
- `phase2-tool-use/tools/system_info.py` — hardware context tool
- `phase2-tool-use/tools/edgar_screener.py` — financial data tool; fixed ticker detection, refresh pipeline, metrics fallback
- `phase2-tool-use/tools/lighting.py` — RGB keyboard animation during local inference
- `QuantitativeValue/src/quantitative_value.py` — added ticker join, positive EBIT filter, non-positive ratio filter, portfolio CSV save, openpyxl install
- `QuantitativeValue/src/defeatbeta_bridge.py` — fixed WSL python path, bridge dir, market_cap fetch, em-dash encoding
- `QuantitativeValue/src/market_data.py` — fixed cache dir to use absolute path

### Final pipeline state
- EDGAR data: 181,344 rows, 9,867 companies, refreshed April 12 2026
- Market data: 3,005 tickers with April 2026 prices + market caps (DefeatBeta)
- Screened portfolio: **360 stocks** passing QV filters (positive EBIT, quality ≥ 50th percentile, value composite ≤ 30th percentile)
- Enkidu can answer: "top N undervalued stocks", specific ticker lookups (portfolio + full universe fallback)

---

## Phase 3 — Agentic Orchestration

**Date:** April 12–13, 2026 | **Status:** ✅ Complete

### Architecture Decision: Telegram over iMessage

The original Phase 3 plan referenced Discord. The updated direction is a **Telegram bot** accessible from iPhone.

iMessage was considered — it would be ideal for native iPhone integration. The problem: iMessage has no official API. The only working solutions (BlueBubbles, AirMessage) require a Mac running as a relay server 24/7. No Mac available. Telegram is the correct call: first-class iPhone app, official Bot API, Python SDK (`pyTelegramBotAPI`), and the de facto standard for self-hosted personal bots.

### Phase 3 Vision (co-authored with Gemma 4)

At the end of Phase 2, Gemma 4 was asked to help design Phase 3 with guidance on the goals. It produced a structured architecture document identifying four layers:

1. **Agentic Infrastructure** — ReAct pattern (Reason → Act → Observe loop), Pydantic-driven output validation, self-correction on `ValidationError`
2. **Quantitative Engine** — Python sandbox tool for arithmetic (pandas/numpy/scipy inside a subprocess), structured EDGAR query interface
3. **Self-Evolving Layer** — HMM regime detection (identify hidden market states from observable signals), RL strategy optimization (deferred to Phase 4/5 — needs backtesting infrastructure first)
4. **Grand Synthesis** — closed-loop system where LLM provides reasoning, HMM provides market context, Python sandbox provides mathematical truth

### What Was Built

**ReAct agent loop (`phase3-agents/enkidu_agent.py`)**
- Full Reason → Act → Observe loop replacing single-shot prompt injection
- Pydantic `AgentStep` schema validates every LLM output — unknown tool names, malformed JSON, and missing fields are caught and fed back for self-correction
- JSON fence stripping + regex extraction handles LLMs that wrap output in markdown blocks
- `max_tokens` set to 2048 — critical: 1024 was too low and caused truncated JSON that burned iterations on self-correction instead of actual reasoning
- Best-effort fallback on iteration limit: rather than hard-failing, the agent makes one final call to summarize what it already observed
- CapEx derivation hint in edgar_screener description: `CapEx = cfo - fcf` (no direct CapEx field in EDGAR data)

**Tool registry (`phase3-agents/tools/registry.py`)**
- Registers tools by name with description + parameter schema injected into the system prompt
- Phase 2 tools loaded by absolute file path to avoid naming collision between `phase3-agents/tools/` and `phase2-tool-use/tools/`

**Python sandbox (`phase3-agents/tools/python_sandbox.py`)**
- Subprocess-based Python execution with 10-second timeout
- Gives the agent exact arithmetic: CAGR, blended metrics, ratio comparisons

**Telegram bot (`phase3-agents/telegram_interface.py`)**
- Long-polling via pyTelegramBotAPI (avoids anyio/Windows TLS incompatibility in python-telegram-bot v21+)
- Single authorized user (TELEGRAM_ALLOWED_USER_ID in .env)
- Live step updates: placeholder message edited in-place as agent calls tools
- Commands: `/start`, `/help`, `/stats`, `/refresh`
- `interval=3` on infinity_polling prevents tight reconnect loops that trigger Telegram rate-limiting
- Custom `_TLS12Adapter` forces TLS 1.2 to work around Windows TLS 1.3 handshake resets (WinError 10054)

**HMM regime detector (`phase3-agents/tools/regime_detector.py`)**
- GaussianHMM (hmmlearn) trained on 10 years of SPY daily data via yfinance
- 3 features: weekly log return, 30-day rolling volatility, price / 200-day MA ratio
- Features StandardScaler-normalized before fitting (required for numerical stability with `diag` covariance)
- 4 hidden states labeled by mean return ranking: Expansion, Recovery, Contraction, Crisis
- Model cached to `regime_model.pkl` — reloads in milliseconds; auto-retrains after 7 days
- `get_regime_context()` injected into every system prompt — Enkidu is always regime-aware
- Screening guidance per regime: Crisis → "favor cash-rich, low-debt names"; Contraction → "tighten value filters, prioritize high F-Score"

**Windows startup automation**
- OpenRGB scheduled task: launches with `--server --startminimized` at logon — no more manual launch
- Enkidu Telegram bot scheduled task: launches `telegram_interface.py` at logon with 3 auto-restarts

**RGB lighting fix**
- `inference_stop()` now restores soft blue `RGBColor(0, 60, 180)` instead of black — lights stay on as idle indicator

### What Broke

**`anthropic` and `pyTelegramBotAPI` not installed in system Python.**
Both packages were missing from the Python environment running `telegram_interface.py`. Added both to `phase3-agents/requirements.txt`.

**WinError 10054 — TLS handshake reset on startup.**
pyTelegramBotAPI's initial `get_me()` call got reset with `ConnectionResetError: [WinError 10054]`. This is a Windows Schannel TLS 1.3 issue. `session.verify = False` fixes certificate errors but not TCP resets. Fix: custom `_TLS12Adapter(HTTPAdapter)` that forces TLS 1.2 via `create_urllib3_context(ssl_minimum_version=TLSv1_2)`.

**409 Conflict — multiple bot instances.**
Force-killing the Python process left Telegram in a `getUpdates` long-polling state. The next instance hit 409: "Conflict: terminated by other getUpdates request." Fix: kill cleanly and wait ~30 seconds before restarting.

**HMM convergence failure with `covariance_type="full"`.**
Training failed with `LinAlgError: 3-th leading minor not positive definite`. Full covariance matrices are numerically unstable when features have different scales. Fix: switch to `covariance_type="diag"` + `StandardScaler` normalization. Also: delete stale `.pkl` from failed runs before retrying.

**Agent iteration limit hit on multi-tool queries.**
First live query hit MAX_ITERATIONS=8 without completing. Causes: (1) `max_tokens=1024` too low — truncated JSON burned iterations, (2) no `CapEx = cfo - fcf` hint. Fix: raise to 2048, add derivation hint.

### What Was Learned

- **`max_tokens` matters for agentic loops.** Each iteration needs enough tokens to complete a full JSON object with reasoning + tool call. Use 2048+.
- **Tool descriptions are prompt engineering.** The registry description is injected into the system prompt. Specific beats vague — "CapEx = cfo - fcf" produces correct tool use; "look up stocks" does not.
- **Windows TLS is fragile.** Force TLS 1.2 via a custom `HTTPAdapter` for any service that resets TLS 1.3 connections. `verify=False` is not enough.
- **HMM numerical stability requires scaling.** Always normalize before fitting, and use `diag` covariance unless you have a specific reason for `full`.
- **Scheduled tasks beat manual startup.** Windows Task Scheduler with `RestartCount=3` means the bot is always running.
- **Don't hammer Telegram with reconnects.** `infinity_polling` with no interval retries instantly; after ~5 rapid reconnects Telegram starts rate-limiting. `interval=3` fixes this.

### Build Order (Actual)

| Step | Component | Status |
|------|-----------|--------|
| 3.1 | Telegram bot skeleton | ✅ Done |
| 3.2 | ReAct loop | ✅ Done |
| 3.3 | Pydantic validation + self-correction | ✅ Done |
| 3.4 | Python sandbox | ✅ Done |
| 3.5 | Multi-step tool chains | ✅ Done — tested live |
| 3.6 | Session memory (in-session) | ✅ Done — message history grows through session |
| 3.7 | HMM regime detection | ✅ Done — injected into every system prompt |
| 3.8 | RL optimization | ⏭ Deferred — needs backtesting infrastructure (Phase 4/5) |

### Files Created

- `phase3-agents/enkidu_agent.py` — ReAct loop core
- `phase3-agents/telegram_interface.py` — Telegram bot + TLS fix
- `phase3-agents/tools/registry.py` — tool registration + dispatch
- `phase3-agents/tools/python_sandbox.py` — subprocess code execution
- `phase3-agents/tools/regime_detector.py` — HMM market regime inference
- `phase3-agents/requirements.txt` — pyTelegramBotAPI, pydantic, anthropic

### Files Modified

- `phase2-tool-use/tools/lighting.py` — `inference_stop()` restores soft blue instead of black

---

## Phase 4 — Persistent Memory + RAG

**Date:** April 13, 2026 | **Status:** ✅ Complete

### Vision

Two complementary memory systems:

1. **Conversation memory** — ChromaDB + SQLite so Enkidu remembers past conversations across sessions. Past context retrieved via semantic similarity and prepended to the system prompt.
2. **Document + codebase RAG** — Index local documents (JOURNEY.md, research notes, financial model outputs, the Enkidu codebase itself) into ChromaDB so Enkidu can cite your own prior work. Inspired by Matthew Busel's approach of indexing 1.2M lines of code across 15 projects into a local vector DB.

### Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Vector store | ChromaDB (PersistentClient) | Local, no server required, good Python SDK |
| Embeddings | nomic-embed-text via Ollama | Local, free, 768-dim, strong retrieval quality |
| Conversation history | SQLite | Zero infrastructure, fast, already on every machine |
| Bridge pattern | Subprocess + dedicated `.venv` | Keeps heavy deps (chromadb, onnxruntime) out of phase3 env |

### What Was Built

**`phase4-memory/memory_store.py`** — dual-write conversation store:
- SQLite `memory.db` for structured history (id, timestamp, user_msg, asst_msg)
- ChromaDB `chroma_db/conversations` collection for semantic search
- `save_exchange()` — writes to both; `retrieve_context(query, k=3)` — cosine similarity < 0.5 filter
- `get_recent_exchanges(n=5)` — for `/history` command; `memory_stats()` — for `/stats`

**`phase4-memory/document_indexer.py`** — codebase RAG:
- Indexes `.py`, `.md`, `.txt`, `.rst`, `.toml`, `.yaml`, `.yml`, `.env.example` files
- 800-char chunks, 150-char overlap; SHA256 chunk IDs make indexing idempotent
- Skips `.git`, `.venv`, `__pycache__`, `data`, `archive`, hidden dirs
- ChromaDB `chroma_db/documents` collection with cosine distance < 0.45 relevance filter
- First full index: **712 chunks from 49 files** in the Enkidu repo

**`phase4-memory/memory_bridge.py`** — subprocess CLI bridge:
- Commands: `save`, `retrieve`, `search_docs`, `stats`, `reindex`
- Phase 3 calls it via subprocess using `phase4-memory/.venv/Scripts/python.exe`
- Prevents chromadb/onnxruntime from being imported into the phase3 environment

**Integrations into Phase 3:**

- `enkidu_agent.py` — `_build_system_prompt()` now calls `_call_memory_bridge("retrieve", user_message)` and injects the result into the system prompt as `{memory}` context block. After each final answer, saves the exchange asynchronously in a daemon thread via `_call_memory_bridge("save", ...)`.
- `tools/registry.py` — registered two new agent tools:
  - `recall_memory` — semantic search over past conversation history
  - `search_docs` — semantic search over the indexed codebase + docs
- `telegram_interface.py` — `/history` command (last 5 exchanges with timestamps); `/stats` now shows memory + document index counts

### What Broke

**`[WinError 2] .exe -> .exe.deleteme` on pip install** — The running bot process locked `Scripts/` in system Python, preventing pip from installing chromadb. Fixed: kill all Python processes before installing. Solution: create a dedicated venv (`phase4-memory/.venv`) so the bot's system Python Scripts/ is never affected by Phase 4 installs.

**`UnicodeEncodeError: 'charmap' codec can't encode character`** — Windows cp1252 console can't print em-dashes and other non-ASCII characters in indexed source files. Appeared in both `document_indexer.py` test and `memory_bridge.py` stdout. Fixed: `io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")` at the top of `memory_bridge.py`; ASCII-escape workaround in the `document_indexer.py` test print.

**`_call_memory_bridge` unreferenced in `enkidu_agent.py`** — IDE noted the import was unused after the initial scaffold. Prompted wiring in both the system prompt injection and the post-answer save call.

### What Was Learned

**Subprocess bridge pattern** — the cleanest way to isolate heavy ML deps (chromadb installs onnxruntime, huggingface-hub, etc.) from a lightweight bot process. Adds ~50–200ms latency per memory call, which is negligible vs. the multi-second Claude API calls.

**Idempotent chunking via content hashing** — using `SHA256(source_path + char_offset)` as chunk IDs means you can re-run the indexer at any time without duplicating chunks. Essential for a live codebase that evolves weekly.

**Dual-store design** — SQLite for chronological retrieval (`/history`, recent context) and ChromaDB for semantic similarity retrieval. They serve different query patterns and complement each other. The SQLite store costs essentially nothing; the vector store costs ~1MB per 1000 chunks.

**cosine distance thresholds** — conversations: < 0.5 (more lenient, short text); documents: < 0.45 (tighter, avoids noisy code chunks that match superficially). These were tuned empirically on the first real queries.

### Build Order

| Step | Component | Notes |
|------|-----------|-------|
| 4.1 | Create `phase4-memory/.venv`, install chromadb + requests | Isolated from phase3 env |
| 4.2 | `memory_store.py` — SQLite + ChromaDB conversation store | Core dual-write store |
| 4.3 | `document_indexer.py` — chunk + embed codebase | 712 chunks, 49 files |
| 4.4 | `memory_bridge.py` — subprocess CLI bridge | 5 commands |
| 4.5 | Wire into `enkidu_agent.py` — system prompt injection + async save | Memory-augmented agent |
| 4.6 | Register `recall_memory` + `search_docs` tools in `registry.py` | Agent can explicitly search memory |
| 4.7 | Add `/history` + enhanced `/stats` to `telegram_interface.py` | Surface memory to user |
| 4.8 | Fix Windows Unicode in `memory_bridge.py` stdout | UTF-8 wrapper |

---

## Phase 5 — Signal Integrity, Backtesting, and Proactive Intelligence

**Date:** April 13, 2026 | **Status:** ✅ Complete

### Vision

Phase 4 gave Enkidu memory. Phase 5 gives it credibility and initiative. Three pillars:

1. **Signal Integrity** — fix the QV screener so its output is actually trustworthy: sector classification, market cap gates, staleness filters, and quality flags
2. **Backtesting** — timestamp every QV signal and track whether picks have alpha vs. SPY over 30/90/180/365-day horizons. "Was I right?" layer.
3. **Proactive Intelligence** — Enkidu pushes insights to Telegram without being asked: price dip alerts, ranking changes, weekly performance summaries

The framing that drove these decisions: "I am not trying to be great. I want to be one of the greats."

---

### Pillar 1 — Signal Integrity

**Problem:** The QV screener had several silent failure modes:
- Financials and utilities (banks, REITs, insurers, utilities) were in the main ranking but shouldn't be — EV/EBIT is meaningless for regulated/balance-sheet-driven businesses
- Stale data: HMC (Honda) appeared with 2014 financials due to no freshness filter
- The Piotroski F-Score showed all companies at 2–3/9 because 7 of 9 components (roa_growth, leverage, liquidity, shares, margin, turnover) were silently zeroing out due to missing YoY data in the pipeline
- Micro-caps and net-loss companies passed through with no warning

**What was built (`phase5-intelligence/sector_classifier.py`):**
- Fetches SIC codes from `https://data.sec.gov/submissions/CIK{cik}.json` for all 360 screened companies
- SIC range → sector mapping with `screen_treatment`: include / separate / exclude
- Key separated sectors: Banking (6000–6199), Credit (6200–6299), Insurance (6300–6499), Real Estate (6500–6552), REITs (6730–6799), Utilities (4900–4941)
- Outputs `C:\Users\benpa\QuantitativeValue\data\processed\sectors.csv` — 360 companies, 43 in separate-screen categories
- Respects SEC rate limit (~8 req/sec with 0.12s delay)

**What was changed in `edgar_screener.py`:**
- `_attach_sectors(df)` — joins sector/screen_treatment onto portfolio DataFrame via CIK
- `_quality_flags(row)` — returns warning flags: NET LOSS, MICRO-CAP, NEG FCF, HIGH DEBT
- `get_top_stocks()` updated with 6 ordered quality gates:
  1. `ebit > 0`
  2. `revenue > 1M`
  3. `market_cap_final >= 100M`
  4. `period_end >= 24 months ago` (staleness filter — eliminates HMC 2014 data)
  5. `f_roa_positive == 1` AND `f_cfo_positive == 1` (the two F-Score components with real data)
  6. `screen_treatment == "include"` (sector filter — excludes banks, REITs, utilities)
- Result: 116 companies pass all gates from the 360-stock universe

**F-Score workaround:** Rather than fixing the underlying pipeline bug (requires a full 2-hour EDGAR rerun), the broken composite `f_score >= 4` gate was replaced with individual component checks for the two components that DO have real data. The remaining 7 components are flagged for a future pipeline fix.

---

### Pillar 2 — Backtesting Engine

**What was built:**

**`phase5-intelligence/signal_logger.py`:**
- SQLite `signals.db` with `signal_snapshots` table — one row per (date, ticker, rank)
- `log_snapshot(n=25)` — idempotent: skips if already logged today; mirrors `get_top_stocks()` quality gates
- `get_snapshot(date)` — returns picks for a given date (or most recent)
- `list_snapshots()` — all recorded dates
- First real snapshot: 25 picks logged 2026-04-13 (TK, PAGP, M, UPBD, ABG, IMPP, DXC, AN, NUTX, AMWD, ODD, GLP, WLKP, RJET, RMR, HPQ, SLVM, PRG, INGM, LEA, DVA, HTLM, CPB, BBY, VSNT)

**`phase5-intelligence/performance_tracker.py`:**
- `update_returns(verbose)` — for every logged snapshot, fetches entry price + exit price at each horizon via yfinance, computes return vs. SPY benchmark, stores in `return_records` table
- Horizons: 30 / 90 / 180 / 365 calendar days
- Handles in-progress positions: uses current price if horizon hasn't elapsed; uses actual exit price once it has
- `performance_report()` — full formatted report by horizon: avg return, avg SPY, avg alpha, win rate, beat-SPY rate, top/bottom 5 picks
- `performance_summary()` — one-liner: "QV signal performance: 30d: +X.X% alpha, XX% beat SPY"
- Return tracking is live but maturing — meaningful data will accumulate over 30–365 day horizons

---

### Pillar 3 — Proactive Intelligence

**What was built:**

**`phase5-intelligence/alert_engine.py`:**
- `alert_price_dip(threshold=-0.05)` — checks current top-25 picks for 5%+ drops from signal-date entry price; a dip is a potential buying opportunity
- `alert_ranking_diff()` — diffs two most recent snapshots; reports new entries and exits from top-25
- `alert_performance()` — weekly performance summary; skips if returns are still maturing
- `run_all_alerts()` — runs all three, sends non-empty results to Telegram
- Same `_TLSAdapter` (ssl.create_default_context) as the main bot — works on Windows without WinError 10054

**New Telegram commands (added to `telegram_interface.py`):**
- `/performance` — calls `performance_tracker.update_returns()` + `performance_report()` live
- `/watchlist` — shows current QV top-15 picks with sector, EV/EBIT, and quality flags

**New agent tools (added to `registry.py`):**
- `qv_performance` — agent can query signal track record; returns summary or full report depending on query
- `qv_snapshot` — agent can return the current ranked watchlist from `signal_logger.get_snapshot()`

---

### What Broke

**F-Score gate eliminated 100% of companies.**
The `f_score >= 4` gate was applied before checking whether the individual components had real data. All 360 companies scored 2–3/9 because 7/9 components defaulted to zero from missing YoY historical data in the pipeline. This produced an empty output with no error — a silent failure. Fix: replace composite gate with `f_roa_positive == 1 AND f_cfo_positive == 1`.

**PRAGMA table_info wrong column index.**
`signal_logger.get_snapshot()` used `d[0]` to extract column names from `PRAGMA table_info`. That returns the column ID integer (0, 1, 2...), not the name. Column names are at index `d[1]`. All `get_snapshot()` results were dicts with integer keys. Fix: `cols = [d[1] for d in ...]`.

**HMC (Honda) stale 2014 data ranked highly.**
Honda's most recent SEC EDGAR filing in the screened portfolio was from 2014. No staleness filter existed, so 12-year-old financials were treated as current and ranked near the top. Fix: `period_end >= today - 730 days` filter in `get_top_stocks()`.

**WinError 10054 TLS reset — regression.**
The TLS fix from Phase 3 (create_urllib3_context forcing TLS 1.2) stopped working after a urllib3 version change. New approach: replace `create_urllib3_context()` with `ssl.create_default_context()` in `_TLSAdapter.init_poolmanager`. Also switched to `long_polling_timeout=0` (short-polling) to eliminate long-lived TCP connections that Windows Schannel resets.

---

### What Was Learned

- **Silent failures are the worst kind.** A gate that eliminates 100% of rows with no log output looks exactly like a gate that eliminates 0%. Always print the row count before and after each filter step.
- **PRAGMA table_info index off-by-one** is a classic SQLite trap. Always verify which index is which before using fetchall() results as dict keys.
- **Backtesting requires a "was I right?" timestamp.** Without daily logging of the actual picks at the exact time they were generated, there's no way to compute honest returns. Log first; compute returns later. Even one real snapshot is worth more than a thousand simulated ones.
- **Proactive alerting changes the tool's character.** A system that only answers questions is a search engine. A system that sends you a price dip alert at 7am without being asked is an analyst.
- **ssl.create_default_context() vs create_urllib3_context()**: The stdlib context works with Telegram's servers; urllib3's internal context builder does not. This is a Windows-specific incompatibility that is hard to debug because both contexts appear to succeed in raw socket tests.

---

### Build Order

| Step | Component | Notes |
|------|-----------|-------|
| 5.1 | `sector_classifier.py` — SIC code fetch + sectors.csv | 360 companies, 43 separated |
| 5.2 | `edgar_screener.py` — quality gates + flags | 116 pass all gates |
| 5.3 | `signal_logger.py` — snapshot logging + SQLite | First snapshot: 2026-04-13 |
| 5.4 | `performance_tracker.py` — return computation vs SPY | Live, maturing over time |
| 5.5 | `alert_engine.py` — proactive Telegram alerts | price_dip, ranking_diff, performance |
| 5.6 | `registry.py` — register qv_performance + qv_snapshot | Agent tools wired in |
| 5.7 | `telegram_interface.py` — /performance + /watchlist commands | Live on restart |
| 5.8 | Windows Task Scheduler — daily signal_logger + weekly alert_engine | Scheduled automation |

---

---

## Phase 6 — RGB Lighting, Web Search, and Bot Stability

**Date:** April 14, 2026 | **Status:** ✅ Complete

### What Was Built

#### RGB Lighting (`phase2-tool-use/tools/lighting.py`)

Two independent lighting backends that react to Enkidu's inference state:

**Corsair iCUE SDK (`cuesdk`):**
- `initialize()` — takes exclusive SDK control at bot startup, sets all keys to soft blue (0, 60, 180)
- `inference_start()` — sets keyboard deep purple (120, 0, 200) while Enkidu is thinking
- `inference_stop()` — returns to idle blue
- Control release → iCUE Rain preset approach was abandoned (keyboard went white); static color during inference is more reliable

**Alienware Aurora R15 (LightFX):**
- AWCC SDK DLL loaded from `C:\Program Files\Alienware\...\AlienFX SDK\DLLs\x64\LightFX.dll` (not the System32 stub — that does nothing on AWCC 5+)
- Idle: solid blue via `LFX_Light(LFX_ALL, packed_dword)`
- Inference: galaxy swirl animation thread — all 75 Aurora R15 lights individually via `LFX_SetLightColor`, with counter-rotating rainbow hue bands, traveling brightness sine wave, and sparkle shimmer. Falls back to zone sweep if `LFX_SetLightColor` is unsupported.

**Key animation parameters (tuned interactively):**
- `ROTATE_HZ=1.1`, `CONTRA_HZ=2.5`, `HUE_WRAPS=4` — hue motion
- `PULSE_HZ=3.5`, `B_MID=180`, `B_AMP=75`, `WAVE_LIGHTS=5` — brightness pulse
- `SHIMMER_HZ=1.4` — sparkle flashes at shimmer > 0.92

**Wired into the agent:**
- `inference_start()` / `inference_stop()` called in `run_agent()` try/finally — every query lights up both devices
- `initialize()` called at Telegram bot startup

#### Web Search (`phase3-agents/tools/web_search.py`)

Two public functions fed by a Tavily primary / DuckDuckGo fallback chain:

**`search(query, max_results=6)`** — formatted observation for the Claude ReAct tool loop. Returns Tavily's extracted page content + synthesized `answer` field, or DDG snippets if Tavily is unavailable.

**`search_context(query, max_results=5)`** — compact context block injected into Gemma's system prompt before every query. Returns `None` on failure so Gemma degrades gracefully.

Tavily (`search_depth="advanced"`) extracts full page text — not just 150-char snippets. The `answer` field gives Gemma a one-sentence synthesis before the raw results, matching how a human would brief an analyst.

**Routing:**
- All Gemma (local GPU) queries now pre-fetch web context before calling Ollama
- `web_search` registered as a Claude ReAct tool (financial queries that need live prices can call it explicitly)
- Routing keywords `"search the web"`, `"search online"`, `"search internet"` push to the Claude loop

**Setup:** add `TAVILY_API_KEY=tvly-...` to `.env`. DDG is the automatic fallback with no config needed.

#### Bot Stability (`phase3-agents/telegram_interface.py`)

Multiple fixes applied over the course of the session:

| Fix | Problem | Solution |
|-----|---------|----------|
| `_safe_send()` helper | Bare `bot.send_message()` in handler threw `ConnectionError`, killed the worker pool | Wrapped in try/except; swallows failures silently |
| `_handle_message_inner()` | Any uncaught exception in the handler crashed `infinity_polling` | Moved body to inner function, outer handler catches all exceptions |
| TLS session caching | New TCP + TLS handshake on every poll → frequent WinError 10054 resets | `_patched_session` now caches session; only creates new one on `reset=True` |
| `none_stop` → `non_stop` | Deprecated kwarg warning from telebot | Renamed |
| Duplicate `non_stop` kwarg | `infinity_polling` passes `non_stop=True` internally; passing it again → TypeError crash loop | Removed from our `infinity_polling()` call |
| TeleBot log noise | ConnectionReset errors logged at ERROR level every ~30 min despite auto-recovery | `logging.getLogger("TeleBot").setLevel(logging.WARNING)` |
| UTF-8 subprocess | Memory bridge subprocess output with emoji/Unicode caused `cp1252` decode crash in reader thread | `encoding="utf-8", errors="replace"` added to `subprocess.run()` in `registry.py` |

### What Broke

**Keyboard went white during inference.** Releasing iCUE SDK control so "Rain" would play caused the keyboard to go white — no background layer active without SDK control. Fix: keep exclusive control and set a static color (deep purple) during inference instead.

**AlienFX calls succeeded (return 0) but did nothing.** Was using `LFX_SetLightColor` with a struct pointer — the correct zone-sweep API is `LFX_Light(LFX_ALL, packed_dword)`. The AWCC SDK sample was the source of truth.

**AlienFX still silent even with correct API.** Was loading `System32\LightFX.dll` — that's a stub that does nothing on AWCC 5+. Fix: load the full SDK DLL from the AWCC installation directory.

**AlienFX still silent.** "Go Dark" mode in AWCC suppresses all LightFX output. Fix: turn off Go Dark in AWCC settings.

**iCUE: 0 devices detected.** K70 had "Device Memory Mode" enabled — when DMM is on, the keyboard runs from onboard memory and is invisible to the SDK. Fix: disable DMM in iCUE device settings.

**`duckduckgo_search` package renamed.** The package was renamed to `ddgs` mid-session. Updated imports to `from ddgs import DDGS`.

**Gemma denied having web access** even after web search was wired in. Two causes: (1) `_needs_web()` heuristic was too narrow — queries like "what programs are available at AB Tech" matched no keywords; (2) system prompt didn't tell Gemma the results were live. Fix: removed the keyword gate entirely (always search for Gemma queries); added explicit IMPORTANT note in system prompt that results were fetched live.

**`TAVILY_API_KEY` not in `.env`** — key appeared saved in IDE but wasn't persisted. Confirmed missing with `grep`. User re-saved and confirmed.

**409 Conflict on bot restart.** Two Python processes polling Telegram simultaneously. Fix: `taskkill //F //IM python.exe //T` before every restart.

### What Was Learned

**`LFX_Light(LFX_ALL, packed_dword)` is the correct zone API.** The LightFX SDK uses a packed 32-bit DWORD: `(brightness << 24) | (r << 16) | (g << 8) | b`. Individual light control uses `LFX_SetLightColor(device, light_index, &LFX_COLOR_struct)`.

**AWCC "Go Dark" is a global override.** It completely suppresses all LightFX output — even correct API calls with the right DLL return success but produce no visible output. Not documented.

**Always search, don't try to predict.** Keyword-gating web search misses too many valid queries. A 0.5s DuckDuckGo call costs nothing and never hurts. The heuristic approach was abandoned in favor of always augmenting Gemma's context.

**Telebot's `infinity_polling` forwards `non_stop=True` to `polling()` internally.** Passing it again as a kwarg causes a `TypeError: multiple values for keyword argument` crash loop — telebot retries every 3 seconds, flooding the log.

**Session caching matters for TLS.** Creating a new `requests.Session()` on every poll meant a fresh TLS handshake every second. WinError 10054 was happening because the handshake itself was failing, not the long-poll. Caching the session reduced resets from every few seconds to every ~30 minutes (ISP keepalive timeout).

### Build Order

| Step | Component | Notes |
|------|-----------|-------|
| 6.1 | `lighting.py` — Corsair iCUE SDK backend | idle blue, deep purple during inference |
| 6.2 | `lighting.py` — AlienFX LightFX backend | DLL search order, zone API, idle blue |
| 6.3 | `lighting.py` — galaxy swirl animation thread | 75 per-light, sine waves, shimmer |
| 6.4 | Wire lighting into `enkidu_agent.py` + `telegram_interface.py` | every Telegram query lights up |
| 6.5 | `web_search.py` — DDG search_context + search | initial implementation |
| 6.6 | Register `web_search` tool in `registry.py` | Claude can call it in ReAct loop |
| 6.7 | Wire `search_context` into `_run_local()` Gemma path | all Gemma queries web-augmented |
| 6.8 | Upgrade to Tavily primary / DDG fallback | full page extraction + direct answer |
| 6.9 | Add `TAVILY_API_KEY` to `.env` | confirmed with `python -c "import os; print(os.environ.get('TAVILY_API_KEY'))"` |
| 6.10 | Bot stability — `_safe_send`, handler isolation, session caching | no more crash loops |
| 6.11 | Suppress TeleBot log noise, fix `non_stop` kwarg, fix UTF-8 subprocess | clean logs |

*This log will be updated as each phase progresses.*
