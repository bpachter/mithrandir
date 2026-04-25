# Phase 2 — Tool Use and Routing Logic

**Status: Complete**

![Routing decision in the REPL](../assets/phase2-routing-decision.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 2” -->

> **Plain English:** A language model is just a text predictor — it doesn't actually *know* what your GPU temperature is or what stocks are cheap today. This phase teaches Mithrandir to **look things up first, then answer.** It also adds a traffic cop ("the router") that decides which model handles each question — the free local Gemma for most things, paid Claude only when the question really needs the extra horsepower.

A Python orchestrator that routes queries between local Gemma and Claude API, and runs tools that inject real context — financial data, system stats, RGB lighting — before sending to the model.

---

## Architecture

```
User query
    ↓
mithrandir.py REPL
    ↓
router.py — LOCAL or CLOUD?
    ↓
Tool pipeline (triggered by query keywords)
    ├── system_info.py    → GPU/CPU/RAM stats via nvidia-smi + psutil
    ├── edgar_screener.py → EDGAR financial data + QV portfolio context
    └── lighting.py       → RGB keyboard animation while GPU runs
    ↓
LOCAL: Gemma 4 26B via Ollama (~144 tok/s, RTX 4090)
  or
CLOUD: Claude claude-opus-4-6 via Anthropic API
    ↓
Response streamed to terminal
```

---

## Components

### `router.py` — Routing Logic

Classifies each query as LOCAL (Gemma) or CLOUD (Claude) based on:

| Signal | → Local | → Cloud |
|--------|---------|---------|
| Token count | < 500 tokens | > 500 tokens |
| Keywords | "what is", "list", "define" | "analyze", "compare", "explain in depth" |
| Tools needed | No | Yes |
| Explicit override | `/local` command | `/cloud` command |
| Default | Yes | — |

Bias is intentionally toward local — free, private, and fast enough for most queries at 144 tok/s.

Run standalone to inspect routing decisions:
```bash
python phase2-tool-use/router.py
```

---

### `tools/system_info.py` — Hardware Context

Injects real-time hardware stats into the prompt when you ask about performance, memory, or GPU state.

**Triggers:** queries containing "gpu", "vram", "cpu", "ram", "memory", "temperature", "utilization"

**Injects:** nvidia-smi output (GPU name, VRAM used/total, utilization, temperature) + psutil RAM stats

---

![EDGAR tool returning a QV portfolio answer](../assets/phase2-qv-portfolio.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 2” -->

### `tools/edgar_screener.py` — Financial Data Tool

Injects EDGAR financial context when you ask about stocks or companies. Backed by the bundled QV pipeline at `quant-value/`.

**Triggers:** financial keywords ("stock", "earnings", "ebitda", "portfolio", etc.) or uppercase tickers (e.g. `AAPL`, `NUE`)

**Injects:**
- For screened stocks: QV portfolio rank, EV multiples, quality score, value composite
- For non-screened tickers: raw EDGAR metrics (revenue, assets, liabilities, EBIT)
- For portfolio queries: top 10 screened stocks with full metrics

**Data sources:**
- EDGAR fundamentals: 181K+ rows, 9,867 companies, from SEC filings via `edgartools`
- Market data: DefeatBeta (primary, via WSL) + yfinance (fallback)
- Screened portfolio: 360 stocks passing the QV filter (positive EBIT, quality ≥ 50th pct, value ≤ 30th pct)

See [quant-value/README.md](./quant-value/README.md) for full pipeline details.

---

![RGB keyboard during inference](../assets/phase2-rgb-inference.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 2” -->

### `tools/lighting.py` — RGB Keyboard Animation

Runs a rainbow sweep across the keyboard (OpenRGB) while local GPU inference is active. Visual indicator that Gemma is working.

**Requirements:** OpenRGB installed with SDK server enabled on port 6742. Must be opened manually each session.

**Pattern:** Spawns a subprocess running `lighting_worker.py` at query start; sends SIGTERM when the response completes.

**Note:** Only the keyboard zone is reliably supported — other Dell/Alienware lighting zones require ACPI-level control outside OpenRGB's scope. RGB tuning is deprioritized; this is a nice-to-have.

---

### `quant-value/` — Quantitative Value Pipeline

A full quant value stock screening pipeline bundled with Mithrandir. Fetches EDGAR filings for ~9,867 companies, computes financial metrics, and scores them on quality + value.

See [quant-value/README.md](./quant-value/README.md) for the full guide.

---

## Files

```
phase2-tool-use/
├── README.md              # This file
├── router.py              # LOCAL vs CLOUD routing logic
├── tools/
│   ├── __init__.py
│   ├── system_info.py     # GPU/CPU/RAM context injection
│   ├── edgar_screener.py  # EDGAR financial data tool
│   └── lighting.py        # RGB keyboard animation
└── quant-value/           # Quantitative Value pipeline (see its own README)
    ├── README.md
    ├── requirements.txt
    ├── src/               # Python pipeline source (17 modules)
    ├── config/            # settings.json + tickers.txt
    ├── docs/              # QV methodology documentation
    └── data/              # NOT in git — GB-scale EDGAR + market data
```

---

## Phase 2 Learnings

See [JOURNEY.md](../JOURNEY.md) for the full unfiltered log — including the path resolution bugs, em-dash encoding error in WSL, DefeatBeta market cap extraction fix, and negative EV/EBIT ranking problem.
