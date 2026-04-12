"""
edgar_screener.py — SEC EDGAR financial data tool

Queries the QuantitativeValue processed datasets to answer financial and
investment questions about public companies.

This tool does NOT re-implement the EDGAR pipeline — it queries the data
that already exists in the QuantitativeValue project. Refreshing that data
is a separate operation handled by refresh_data().

Data sources (all from QuantitativeValue/data/processed/):
    quantitative_value_portfolio.csv — 1,295 screened stocks with full metrics
    metrics.csv                      — 186K rows of computed financial ratios
    companies.csv                    — 9,689 companies universe (ticker/CIK mapping)
    franchise_power_metrics.csv      — 8-year quality scores

Pattern (same as all Enkidu tools):
    1. Python fetches/filters real data
    2. Data injected into prompt as [EDGAR CONTEXT]
    3. LLM interprets and explains — it never touches the data directly

Requires:
    - QV_PATH set in .env pointing to your QuantitativeValue project root
    - pandas (pip install pandas)
"""

import os
import sys
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# --- Path resolution ---

def get_qv_path() -> Optional[Path]:
    """Get the QuantitativeValue project path from environment."""
    raw = os.getenv("QV_PATH")
    if not raw:
        return None
    p = Path(raw)
    return p if p.exists() else None


def get_processed_path() -> Optional[Path]:
    qv = get_qv_path()
    return qv / "data" / "processed" if qv else None


def get_cache_path() -> Optional[Path]:
    qv = get_qv_path()
    return qv / "data" / "raw" / "companyfacts" if qv else None


# --- Data loading ---

def load_portfolio() -> Optional[pd.DataFrame]:
    """Load the screened portfolio (1,295 stocks with all metrics)."""
    p = get_processed_path()
    if not p:
        return None
    path = p / "quantitative_value_portfolio.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


def load_metrics() -> Optional[pd.DataFrame]:
    """Load full metrics dataset (186K rows — all companies, all periods)."""
    p = get_processed_path()
    if not p:
        return None
    path = p / "metrics.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


def load_companies() -> Optional[pd.DataFrame]:
    """Load the company universe (ticker/CIK mapping)."""
    p = get_processed_path()
    if not p:
        return None
    path = p / "companies.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


# --- Query functions ---

def get_top_stocks(n: int = 10) -> Optional[pd.DataFrame]:
    """
    Return the top N stocks by value composite score.
    value_composite is an average of EV/EBIT, EV/Revenue, EV/FCF percentile ranks
    where lower = cheaper/better value.
    """
    df = load_portfolio()
    if df is None:
        return None
    sort_col = "value_composite" if "value_composite" in df.columns else "ev_ebit"
    cols = [c for c in ["ticker", "value_composite", "quality_score", "f_score",
                         "ev_ebit", "debt_to_equity", "roa", "p_franchise_power"]
            if c in df.columns]
    return df.nsmallest(n, sort_col)[cols].reset_index(drop=True)


def get_ticker_summary(ticker: str) -> Optional[dict]:
    """Return a summary of key metrics for a specific ticker."""
    df = load_portfolio()
    if df is None:
        # Fall back to full metrics if ticker not in screened portfolio
        df = load_metrics()
    if df is None:
        return None

    ticker = ticker.upper()
    row = df[df["ticker"].str.upper() == ticker]

    # If not in screened portfolio, fall back to full metrics dataset
    if row.empty:
        df = load_metrics()
        if df is None:
            return None
        # metrics has many rows per company — take the most recent annual period
        company_rows = df[df["ticker"].str.upper() == ticker]
        if company_rows.empty:
            return None
        annual = company_rows[company_rows.get("frequency", pd.Series()) == "annual"] if "frequency" in company_rows.columns else company_rows
        row = (annual if not annual.empty else company_rows).sort_values("period_end", ascending=False).head(1)

    if row.empty:
        return None

    row = row.iloc[0]

    # Pull the most relevant columns — gracefully skip missing ones
    fields = {
        "ticker": "ticker",
        "period_end": "period_end",
        "piotroski_f_score": "f_score",
        "value_composite": "value_composite",
        "quality_score": "quality_score",
        "franchise_power_pct": "p_franchise_power",
        "financial_strength_pct": "p_financial_strength",
        "ev_ebit": "ev_ebit",
        "ev_revenue": "ev_revenue",
        "debt_to_equity": "debt_to_equity",
        "roa": "roa",
        "roe": "roe",
        "gross_margin": "gross_margin",
        "operating_margin": "operating_margin",
        "revenue": "revenue",
        "ebit": "ebit",
        "net_income": "net_income",
        "total_assets": "total_assets",
        "total_debt": "total_debt",
        "cfo": "cfo",
        "fcf": "fcf",
        "8yr_roa": "8yr_roa",
        "8yr_roc": "8yr_roc",
    }

    result = {}
    for label, col in fields.items():
        if col in row.index and pd.notna(row[col]):
            result[label] = row[col]

    return result if result else None


def filter_by_criteria(
    min_f_score: int = None,
    max_ev_ebit: float = None,
    max_debt_to_equity: float = None,
    n: int = 15
) -> Optional[pd.DataFrame]:
    """Filter the portfolio by user-defined criteria."""
    df = load_portfolio()
    if df is None:
        return None

    if min_f_score is not None and "f_score" in df.columns:
        df = df[df["f_score"] >= min_f_score]
    if max_ev_ebit is not None and "ev_ebit" in df.columns:
        df = df[df["ev_ebit"] <= max_ev_ebit]
    if max_debt_to_equity is not None and "debt_to_equity" in df.columns:
        df = df[df["debt_to_equity"] <= max_debt_to_equity]

    sort_col = "value_composite" if "value_composite" in df.columns else "ev_ebit"
    cols = [c for c in ["ticker", "value_composite", "f_score", "ev_ebit",
                         "debt_to_equity", "roa", "quality_score", "p_franchise_power"]
            if c in df.columns]
    return df.nsmallest(n, sort_col)[cols].reset_index(drop=True)


# --- Context formatting ---

def format_dataframe(df: pd.DataFrame) -> str:
    """Format a DataFrame as a clean text table for LLM context."""
    return df.to_string(index=False, float_format=lambda x: f"{x:.2f}")


def get_context(query: str) -> str:
    """
    Main entry point for enkidu.py.
    Detects what the query is asking for and returns the appropriate context block.
    """
    qv = get_qv_path()
    if not qv:
        return "[EDGAR CONTEXT]\nQV_PATH not set in .env — Edgar screener unavailable.\nSet QV_PATH to your QuantitativeValue project directory."

    portfolio = load_portfolio()
    if portfolio is None:
        return "[EDGAR CONTEXT]\nPortfolio data not found. Run a data refresh first."

    query_lower = query.lower()
    lines = ["[EDGAR CONTEXT — QuantitativeValue screened portfolio]",
             f"Data last modified: {_get_data_age()}",
             f"Universe: {len(portfolio)} screened stocks\n"]

    # Specific ticker lookup
    for word in query.upper().split():
        word = word.strip("?.,!").upper()
        if 2 <= len(word) <= 5 and word.isalpha():
            summary = get_ticker_summary(word)
            if summary:
                lines.append(f"Ticker: {word}")
                for k, v in summary.items():
                    if isinstance(v, float):
                        lines.append(f"  {k}: {v:.4f}")
                    else:
                        lines.append(f"  {k}: {v}")
                return "\n".join(lines)

    # Top stocks request
    if any(kw in query_lower for kw in ["top", "best", "rank", "highest", "screen"]):
        n = 10
        for word in query_lower.split():
            if word.isdigit():
                n = int(word)
                break
        top = get_top_stocks(n)
        if top is not None:
            lines.append(f"Top {n} stocks by overall rank:")
            lines.append(format_dataframe(top))

    # Filtered query
    elif any(kw in query_lower for kw in ["cheap", "value", "low debt", "quality", "strong"]):
        filtered = filter_by_criteria(min_f_score=7, max_debt_to_equity=1.0, n=10)
        if filtered is not None:
            lines.append("Stocks with F-Score ≥ 7 and Debt/Equity ≤ 1.0:")
            lines.append(format_dataframe(filtered))

    # General portfolio stats
    else:
        lines += [
            "Portfolio summary:",
            f"  Avg Piotroski F-Score:    {portfolio['f_score'].mean():.1f}" if "f_score" in portfolio.columns else "",
            f"  Median EV/EBIT:           {portfolio['ev_ebit'].median():.1f}" if "ev_ebit" in portfolio.columns else "",
            f"  Avg ROA:                  {portfolio['roa'].mean():.3f}" if "roa" in portfolio.columns else "",
            f"  Avg Quality Score:        {portfolio['quality_score'].mean():.3f}" if "quality_score" in portfolio.columns else "",
        ]

    return "\n".join(l for l in lines if l)


def _get_data_age() -> str:
    """Return how old the portfolio data is."""
    p = get_processed_path()
    if not p:
        return "unknown"
    path = p / "quantitative_value_portfolio.csv"
    if not path.exists():
        return "file not found"
    mtime = path.stat().st_mtime
    age_days = (time.time() - mtime) / 86400
    if age_days < 1:
        return "today"
    elif age_days < 7:
        return f"{int(age_days)} days ago"
    elif age_days < 30:
        return f"{int(age_days / 7)} weeks ago"
    else:
        return f"{int(age_days / 30)} months ago"


# --- Refresh ---

def estimate_refresh_time(force_redownload: bool = False) -> dict:
    """
    Estimate how long a data refresh will take before starting.

    Args:
        force_redownload: True = wipe cached JSONs and re-fetch from EDGAR
                          False = keep cached JSONs, just reprocess

    Returns:
        Dict with time estimates per stage and total
    """
    cache = get_cache_path()
    cached_count = len(list(cache.glob("*.json"))) if cache and cache.exists() else 0
    total_companies = 9689  # known universe size

    if force_redownload:
        # Must re-fetch all companies from EDGAR
        companies_to_fetch = total_companies
    else:
        # Only fetch companies not already cached
        companies_to_fetch = total_companies - cached_count

    # EDGAR fetch estimate (8 req/s max, 5s pause per 50-company batch)
    fetch_seconds = 0
    if companies_to_fetch > 0:
        fetch_seconds = math.ceil(companies_to_fetch / 8)           # network time
        batch_pauses = math.ceil(companies_to_fetch / 50) * 5       # batch delays
        fetch_seconds += batch_pauses

    estimates = {
        "cached_json_files": cached_count,
        "companies_to_fetch": companies_to_fetch,
        "stages": {
            "edgar_fetch":        _fmt_time(fetch_seconds),
            "parse_fundamentals": _fmt_time(600),
            "compute_metrics":    _fmt_time(300),
            "risk_screening":     _fmt_time(300),
            "franchise_power":    _fmt_time(300),
            "qv_screening":       _fmt_time(300),
        },
        "total": _fmt_time(fetch_seconds + 1800),
    }
    return estimates


def _fmt_time(seconds: int) -> str:
    if seconds < 60:
        return f"~{seconds}s"
    return f"~{seconds // 60}m {seconds % 60}s"


def refresh_data(force_redownload: bool = False, dry_run: bool = False) -> dict:
    """
    Refresh the QuantitativeValue data pipeline.

    Args:
        force_redownload: If True, wipes all cached JSON files and re-fetches
                          everything from EDGAR (longer but gets latest data).
                          If False, keeps existing cached JSONs and just
                          reruns the processing pipeline (faster).
        dry_run:          If True, show estimate only — don't actually run.

    Returns:
        Dict with status and timing info
    """
    qv = get_qv_path()
    if not qv:
        return {"status": "error", "message": "QV_PATH not set in .env"}

    estimate = estimate_refresh_time(force_redownload)

    result = {
        "mode": "full re-download" if force_redownload else "reprocess cached data",
        "cached_json_files": estimate["cached_json_files"],
        "companies_to_fetch": estimate["companies_to_fetch"],
        "time_estimate": estimate,
    }

    if dry_run:
        result["status"] = "dry_run"
        return result

    # Wipe cached JSONs if forced re-download
    if force_redownload:
        cache = get_cache_path()
        if cache and cache.exists():
            shutil.rmtree(cache)
            cache.mkdir(parents=True)

        # Also wipe processed CSVs so they get rebuilt cleanly
        processed = get_processed_path()
        if processed and processed.exists():
            for csv in processed.glob("*.csv"):
                csv.unlink()

    # Run the pipeline
    run_all = qv / "src" / "run_all.py"
    if not run_all.exists():
        return {"status": "error", "message": f"run_all.py not found at {run_all}"}

    cmd = [sys.executable, str(run_all)]
    if force_redownload:
        cmd.append("--refresh")

    start = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(qv / "src"), capture_output=False, text=True)
        elapsed = time.time() - start
        result["status"] = "success" if proc.returncode == 0 else "failed"
        result["elapsed"] = _fmt_time(int(elapsed))
        result["returncode"] = proc.returncode
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)

    return result


# --- Trigger keywords for enkidu.py ---

TRIGGER_KEYWORDS = [
    "stock", "ticker", "piotroski", "f-score", "f score", "edgar",
    "10-k", "10k", "filing", "fundamental", "portfolio", "screener",
    "screen", "value investing", "ev/ebit", "ebit", "enterprise value",
    "debt to equity", "roa", "roe", "earnings", "revenue", "balance sheet",
    "cash flow", "franchise power", "beneish", "m-score", "distress",
    "altman", "shareholder", "equity", "liabilities", "assets",
    "top stocks", "best stocks", "cheap stocks", "undervalued",
]


def should_fetch(query: str) -> bool:
    """Returns True if the query is likely asking about financial/stock data."""
    q = query.lower()
    return any(kw in q for kw in TRIGGER_KEYWORDS)


# --- CLI test ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--estimate":
        force = "--force" in sys.argv
        est = estimate_refresh_time(force_redownload=force)
        print(f"\nRefresh estimate ({'full re-download' if force else 'reprocess only'})")
        print(f"Cached JSON files: {est['cached_json_files']}")
        print(f"Companies to fetch: {est['companies_to_fetch']}")
        print("\nStage estimates:")
        for stage, t in est["stages"].items():
            print(f"  {stage:<25} {t}")
        print(f"\n  {'TOTAL':<25} {est['total']}")

    elif len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        summary = get_ticker_summary(ticker)
        if summary:
            print(f"\n{ticker} summary:")
            for k, v in summary.items():
                print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
        else:
            print(f"{ticker} not found in portfolio")

    else:
        print(get_context("top 10 stocks"))
