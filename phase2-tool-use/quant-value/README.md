# Quantitative Value Pipeline

A stock screening pipeline based on the methodology from *Quantitative Value* (Wesley Gray & Tobias Carlisle). Fetches SEC EDGAR financial data for ~9,867 public companies, computes quality and value metrics, and produces a ranked portfolio of the most undervalued high-quality stocks.

This pipeline is bundled with Mithrandir and powers the `edgar_screener.py` tool — when you ask Mithrandir about stocks, it queries this data.

---

## What It Does

1. **Fetches EDGAR fundamentals** — downloads SEC filings for ~9,867 companies via `edgartools`, extracts income statement + balance sheet + cash flow metrics
2. **Fetches market data** — pulls current prices and market caps via DefeatBeta (WSL) with yfinance as fallback
3. **Computes quality scores** — Piotroski F-Score (as quality proxy; Franchise Power module available but requires separate run)
4. **Computes value composites** — EV/EBIT, EV/EBITDA, P/B, P/FCF — nulled out when non-positive, ranked by percentile
5. **Screens the universe** — keeps stocks with positive EBIT, quality ≥ 50th percentile, value composite ≤ 30th percentile
6. **Outputs a portfolio CSV** — ~360 stocks saved to `data/processed/quantitative_value_portfolio.csv`

Mithrandir's `/refresh` command runs both pipeline stages and regenerates this file.

---

## Methodology

### Quality Screen

| Metric | Source | Threshold |
|--------|--------|-----------|
| Piotroski F-Score (1-9) | EDGAR fundamentals | ≥ 50th percentile of universe |
| EBIT | EDGAR income statement | Must be positive (pre-filter) |

Franchise Power (8-year ROIC trend, R&D amortization) is implemented in `src/franchise_power.py` but requires a separate run. F-Score is the active quality proxy.

### Value Composite

Composed of up to four multiples, each percentile-ranked across the universe:

| Multiple | Numerator | Denominator | Notes |
|----------|-----------|-------------|-------|
| EV/EBIT | Enterprise Value | EBIT | Core multiple; non-positive values excluded |
| EV/EBITDA | Enterprise Value | EBITDA | Non-positive values excluded |
| P/Book | Market Cap | Book Value | Non-positive excluded |
| P/FCF | Market Cap | Free Cash Flow | Non-positive excluded |

**Enterprise Value** = market_cap + total_debt − cash_and_equivalents

Value composite = average percentile rank across available multiples. Lower is cheaper.

### Screen Criteria

| Filter | Threshold |
|--------|-----------|
| EBIT | > 0 |
| Quality score | ≥ 50th percentile |
| Value composite | ≤ 30th percentile |

Result: ~360 stocks from the ~9,867-company EDGAR universe (as of last refresh).

---

## Known Limitations

- **Foreign-listed companies** (MUFG, ASML, KYOCF, etc.) have incorrect EV calculations — EDGAR stores fundamentals in native currency (JPY, EUR) but market cap from DefeatBeta is in USD. FX conversion is not yet implemented. These companies may appear artificially cheap or expensive.
- **Franchise Power not active** — `franchise_power.py` requires a full 8-year history compute. F-Score is used as the quality proxy instead. Run `franchise_power.py` separately to get true franchise power scores.
- **Market data coverage** — DefeatBeta covers ~3,005 tickers from the screened universe. Companies without market data are excluded from EV-based multiples.

---

## Setup

### 1. Create the venv

The QV pipeline has heavier dependencies (edgartools, scipy) that conflict with the main Mithrandir environment. Install into a dedicated venv:

```bash
cd phase2-tool-use/quant-value
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

### 2. Configure data directory

By default, the pipeline creates `phase2-tool-use/quant-value/data/` on first run. If you have an existing data directory (e.g., from the standalone QuantitativeValue repo), set `QV_PATH` in your `.env`:

```env
QV_PATH=C:\Users\yourname\QuantitativeValue
```

The `edgar_screener.py` tool checks `QV_PATH` first, then falls back to the bundled `data/` directory.

### 3. Configure DefeatBeta (market data)

DefeatBeta runs in WSL. The bridge expects the Python environment at `/root/defeatbeta_env/bin/python3`. If your path is different, set it in `src/defeatbeta_bridge.py`:

```python
wsl_python_path: str = "/root/defeatbeta_env/bin/python3"
```

See `docs/DEFEATBETA_WSL_SETUP.md` for the full WSL setup guide.

---

## Running the Pipeline

### Full refresh (both stages)

From Mithrandir's REPL:
```
> /refresh
```

Or manually:
```bash
# Stage 1: EDGAR fetch + metrics (~2 hours)
cd phase2-tool-use/quant-value
.venv/Scripts/python src/run_all.py

# Stage 2: QV screen + portfolio CSV (~20 minutes with fresh market data)
.venv/Scripts/python src/quantitative_value.py
```

### Refresh market data only

If you have recent EDGAR data and only need updated prices:
```bash
.venv/Scripts/python src/market_data.py
```

---

## Source Files

| File | Purpose |
|------|---------|
| `run_all.py` | Stage 1 entry point — fetches EDGAR, computes metrics |
| `edgar_fetch.py` | Downloads SEC filings via edgartools |
| `compute_metrics.py` | Extracts income/balance sheet/cash flow metrics |
| `parse_fundamentals.py` | Parses raw EDGAR data into normalized rows |
| `ttm_calculator.py` | Computes trailing-twelve-month figures |
| `entity_classifier.py` | Filters out non-operating entities (REITs, ETFs, SPACs) |
| `quantitative_value.py` | Stage 2 — QV screen, scoring, portfolio output |
| `market_data.py` | Market cap + price fetching (DefeatBeta + yfinance) |
| `defeatbeta_bridge.py` | WSL subprocess bridge for DefeatBeta API calls |
| `franchise_power.py` | 8-year quality metrics (run separately) |
| `risk_screening.py` | Financial distress filters (Altman Z-Score) |
| `portfolio_manager.py` | Portfolio construction utilities |
| `quarterly_refresh.py` | Scheduled refresh logic |
| `excel_database.py` | Excel export of metrics database |
| `alphavantage_provider.py` | Alpha Vantage market data provider (unused; DefeatBeta is primary) |
| `universe_fixed.py` | Ticker universe management |
| `config.py` | Pipeline configuration and paths |

---

## Data Directory Structure

```
data/                          # NOT in git — GB-scale
├── raw/                       # Raw EDGAR filing downloads
│   └── company_facts/         # Per-CIK JSON files from SEC EDGAR
├── processed/
│   ├── companies.csv          # CIK ↔ ticker ↔ name mapping
│   ├── metrics.csv            # 181K+ rows of financial metrics
│   └── quantitative_value_portfolio.csv  # QV screened portfolio (~360 stocks)
└── market_cache/
    └── market_data_cache.csv  # Cached prices + market caps (~3,005 tickers)
```

---

## Documentation

| Doc | Contents |
|-----|---------|
| `docs/QUANTITATIVE_VALUE_MODEL.md` | Full methodology write-up |
| `docs/DATABASE_COLUMNS_GUIDE.md` | Column definitions for metrics.csv |
| `docs/DEFEATBETA_WSL_SETUP.md` | DefeatBeta installation + WSL bridge setup |
| `docs/QUANTITATIVE_VALUE_IMPLEMENTATION_COMPLETE.md` | Implementation status + gap analysis |
| `docs/QV_MODEL_GAP_ANALYSIS.md` | Gaps between book methodology and current implementation |
