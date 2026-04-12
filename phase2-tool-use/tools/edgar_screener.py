"""
edgar_screener.py — SEC EDGAR financial data tool

Queries the QuantitativeValue processed datasets to answer financial and
investment questions about public companies.

This tool does NOT re-implement the EDGAR pipeline — it queries the data
that the QV pipeline already processed. Refreshing that data is a separate
operation handled by refresh_data() (Enkidu's /refresh command).

Data sources (all from quant-value/data/processed/ or QV_PATH/data/processed/):
    quantitative_value_portfolio.csv — screened stocks with full QV metrics
    metrics.csv                      — 181K+ rows of computed financial ratios
    companies.csv                    — 9,867 companies universe (ticker/CIK mapping)

Path resolution (in priority order):
    1. QV_PATH env var in .env  → useful when data lives in a separate project
    2. phase2-tool-use/quant-value/  → bundled copy inside the Enkidu repo (default)

Pattern (same as all Enkidu tools):
    1. Python fetches/filters real data
    2. Data injected into prompt as [EDGAR CONTEXT]
    3. LLM interprets and explains — it never touches the data directly

Requires:
    - pandas (pip install pandas)
    - scipy (for QV screening pipeline)
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

# Bundled QV source tree lives alongside this file in the Enkidu repo:
#   phase2-tool-use/quant-value/   ← src/, config/, docs/ are in git
#   phase2-tool-use/quant-value/data/  ← data is NOT in git (gitignored)
#
# QV_PATH in .env overrides this — useful when data lives elsewhere
# (e.g. Ben's existing QuantitativeValue project at C:\Users\benpa\QuantitativeValue)

_BUNDLED_QV = Path(__file__).parent.parent / "quant-value"


def get_qv_path() -> Optional[Path]:
    """
    Resolve the QuantitativeValue project root.
    Priority: QV_PATH env var → bundled quant-value/ directory.
    """
    raw = os.getenv("QV_PATH")
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    # Fall back to the bundled copy inside the Enkidu repo
    if _BUNDLED_QV.exists():
        return _BUNDLED_QV
    return None


def get_src_path() -> Optional[Path]:
    """Return the QV Python source directory (where run_all.py lives)."""
    qv = get_qv_path()
    return qv / "src" if qv else None


def get_processed_path() -> Optional[Path]:
    qv = get_qv_path()
    return qv / "data" / "processed" if qv else None


def get_cache_path() -> Optional[Path]:
    qv = get_qv_path()
    return qv / "data" / "raw" / "companyfacts" if qv else None


# --- Data loading ---

def load_portfolio() -> Optional[pd.DataFrame]:
    """
    Load the screened portfolio CSV if it exists, otherwise derive a
    'portfolio' from metrics.csv (most recent annual period per ticker,
    sorted by ev_ebit). The pipeline no longer generates the portfolio CSV
    directly — this fallback keeps everything working with fresh data.
    """
    p = get_processed_path()
    if not p:
        return None

    # Prefer pre-screened portfolio CSV if present
    path = p / "quantitative_value_portfolio.csv"
    if path.exists():
        return pd.read_csv(path, low_memory=False)

    # Derive from metrics.csv: join with companies to get tickers,
    # then take the most recent annual period per company.
    metrics   = load_metrics()
    companies = load_companies()
    if metrics is None:
        return None

    df = metrics.copy()

    # Attach ticker via CIK join
    if companies is not None and "cik" in df.columns and "cik" in companies.columns:
        df = df.merge(companies[["cik", "ticker"]], on="cik", how="left")

    # Annual periods only
    if "frequency" in df.columns:
        annual = df[df["frequency"] == "annual"]
        if not annual.empty:
            df = annual

    # Most recent period per ticker
    if "period_end" in df.columns:
        df = df.sort_values("period_end", ascending=False)

    if "ticker" in df.columns:
        df = df.drop_duplicates(subset=["ticker"], keep="first")

    # Drop rows with no valuation data
    if "ev_ebit" in df.columns:
        df = df[df["ev_ebit"].notna() & (df["ev_ebit"] > 0)]

    return df.reset_index(drop=True)


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
    Return the top N stocks ranked by fundamental quality.
    Uses ROA as primary sort (best proxy for quality without market prices).
    Falls back gracefully to whatever valuation columns exist.
    """
    df = load_portfolio()
    if df is None:
        return None

    # Pick best available sort column
    for sort_col in ["value_composite", "ev_ebit", "roa"]:
        if sort_col in df.columns:
            break

    cols = [c for c in ["ticker", "period_end", "roa", "roe", "ebit",
                         "fcf", "gross_margin", "operating_margin",
                         "debt_to_equity", "accrual_ratio",
                         "value_composite", "ev_ebit"]
            if c in df.columns]

    # Require positive EBIT and meaningful revenue to filter out junk
    if "ebit" in df.columns:
        df = df[df["ebit"] > 0]
    if "revenue" in df.columns:
        df = df[df["revenue"] > 1_000_000]

    if sort_col == "roa":
        return df.nlargest(n, sort_col)[cols].reset_index(drop=True)
    else:
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
        # metrics.csv has cik but no ticker — join with companies to enable ticker lookup
        if "ticker" not in df.columns:
            companies = load_companies()
            if companies is not None:
                comp_dedup = companies.drop_duplicates(subset="cik", keep="first")[["cik", "ticker"]]
                df = df.merge(comp_dedup, on="cik", how="left")
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
        "ticker":           "ticker",
        "period_end":       "period_end",
        "revenue":          "revenue",
        "ebit":             "ebit",
        "net_income":       "net_income",
        "cfo":              "cfo",
        "fcf":              "fcf",
        "total_assets":     "total_assets",
        "total_equity":     "total_equity",
        "roa":              "roa",
        "roe":              "roe",
        "gross_margin":     "gross_margin",
        "operating_margin": "operating_margin",
        "net_margin":       "net_margin",
        "fcf_margin":       "fcf_margin",
        "debt_to_equity":   "debt_to_equity",
        "debt_to_assets":   "debt_to_assets",
        "current_ratio":    "current_ratio",
        "accrual_ratio":    "accrual_ratio",
        # kept for backwards compat if old portfolio CSV is present
        "value_composite":  "value_composite",
        "ev_ebit":          "ev_ebit",
        "f_score":          "f_score",
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

    # Sort by best available quality metric
    for sort_col in ["value_composite", "ev_ebit", "roa"]:
        if sort_col in df.columns:
            break

    cols = [c for c in ["ticker", "period_end", "roa", "roe", "ebit",
                         "fcf", "debt_to_equity", "gross_margin",
                         "value_composite", "ev_ebit", "f_score"]
            if c in df.columns]

    if sort_col == "roa":
        return df.nlargest(n, sort_col)[cols].reset_index(drop=True)
    else:
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

    # Specific ticker lookup — only treat a word as a ticker if it is:
    #   (a) already uppercase in the original query (user deliberately wrote DUK), OR
    #   (b) followed by 's (possessive: "DUK's earnings")
    # This prevents common words like "cash", "top", "are" from being mis-detected.
    import re

    # English words that happen to match the ticker pattern (2-5 uppercase alpha chars)
    # but are almost never intentional ticker references when someone types in ALL CAPS
    _NOT_TICKERS = {
        "ARE", "IS", "THE", "AND", "BUT", "FOR", "NOT", "CAN", "DID", "HAS",
        "HAD", "HER", "HIM", "HIS", "HOW", "ITS", "LET", "MAY", "OUR", "OUT",
        "OWN", "PUT", "SAY", "SHE", "TOO", "USE", "WAS", "WHO", "WHY", "YET",
        "YOU", "ALL", "ANY", "FEW", "HIM", "ONE", "OWN", "TOP", "TWO", "YES",
        "ALSO", "BEEN", "FROM", "HAVE", "JUST", "LIKE", "MORE", "MOST", "ONLY",
        "OVER", "SAME", "SOME", "SUCH", "THAN", "THAT", "THEM", "THEN", "THEY",
        "THIS", "VERY", "WELL", "WERE", "WHAT", "WHEN", "WITH", "WILL", "YOUR",
    }

    ticker_candidates = set()

    # Pattern (a): uppercase-only words 2-5 chars, not at sentence start after punctuation
    for word in query.split():
        clean = word.strip("?.,!'\"()").rstrip("'s").rstrip("'s")
        if 2 <= len(clean) <= 5 and clean.isupper() and clean.isalpha() and clean not in _NOT_TICKERS:
            ticker_candidates.add(clean)

    # Pattern (b): word immediately followed by 's or 's (possessive signals deliberate ticker)
    possessives = re.findall(r"\b([A-Za-z]{2,5})['\u2019]s\b", query)
    for p in possessives:
        ticker_candidates.add(p.upper())

    for candidate in ticker_candidates:
        summary = get_ticker_summary(candidate)
        if summary:
            lines.append(f"Ticker: {candidate}")
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
            lines.append("Stocks with F-Score >= 7 and Debt/Equity <= 1.0:")
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
    """Return how old the underlying metrics data is."""
    p = get_processed_path()
    if not p:
        return "unknown"
    # Check portfolio CSV first, fall back to metrics.csv
    for filename in ("quantitative_value_portfolio.csv", "metrics.csv"):
        path = p / filename
        if path.exists():
            break
    else:
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
            "market_data_fetch":  "~40m (DefeatBeta ~3k tickers)",
            "qv_screening":       _fmt_time(300),
        },
        "total": _fmt_time(fetch_seconds + 1800 + 2700),  # +45min for market data
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
        return {"status": "error", "message": "QV path not found — set QV_PATH in .env or ensure phase2-tool-use/quant-value/ exists"}

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

    # Resolve script locations — prefer get_src_path() which handles bundled vs external
    src = get_src_path()
    if src is None:
        return {"status": "error", "message": "QV source directory not found"}

    run_all = src / "run_all.py"
    if not run_all.exists():
        return {"status": "error", "message": f"run_all.py not found at {run_all}"}

    # Use the QV project's own venv if present (has edgartools + heavy deps)
    # Check both the external project root and the bundled location
    qv_venv_python = qv / ".venv" / "Scripts" / "python.exe"
    python_exe = str(qv_venv_python) if qv_venv_python.exists() else sys.executable

    src_dir = str(src)
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    start = time.time()

    # Step 1: EDGAR fetch + fundamentals + metrics (run_all.py)
    cmd = [python_exe, str(run_all)]
    if force_redownload:
        cmd.append("--refresh")

    try:
        proc = subprocess.run(cmd, cwd=src_dir, env=env, capture_output=False, text=True)
        if proc.returncode != 0:
            result["status"] = "failed"
            result["elapsed"] = _fmt_time(int(time.time() - start))
            result["returncode"] = proc.returncode
            result["stage"] = "run_all"
            return result
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        return result

    # Step 2: QV screening + market data (quantitative_value.py → saves portfolio CSV)
    qv_script = src / "quantitative_value.py"
    if qv_script.exists():
        try:
            proc2 = subprocess.run(
                [python_exe, str(qv_script)],
                cwd=src_dir, env=env, capture_output=False, text=True,
            )
            result["qv_returncode"] = proc2.returncode
        except Exception as e:
            result["qv_error"] = str(e)

    elapsed = time.time() - start
    result["status"] = "success"
    result["elapsed"] = _fmt_time(int(elapsed))
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
    import re
    q = query.lower()
    if any(kw in q for kw in TRIGGER_KEYWORDS):
        return True
    # Also trigger if the query contains an uppercase ticker-like word (2-5 alpha chars)
    # or a possessive like DUK's — so "how does DUK compare to peers" routes here
    for word in query.split():
        clean = word.strip("?.,!'\"()")
        if 2 <= len(clean) <= 5 and clean.isupper() and clean.isalpha():
            return True
    if re.search(r"\b[A-Za-z]{2,5}['\u2019]s\b", query):
        return True
    return False


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
