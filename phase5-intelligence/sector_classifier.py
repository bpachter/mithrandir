"""
sector_classifier.py — SIC-based sector classification for the QV universe

Fetches SIC codes from the EDGAR submissions API (data.sec.gov) for each CIK
in the screened universe, maps them to human-readable sector names, and
persists a sectors.csv alongside the other processed data files.

Why this matters:
  EV/EBIT comparisons are ONLY valid within a sector. A bank trading at
  0.05x EV/EBIT is not "cheaper" than a manufacturer at 8x — they're
  fundamentally different businesses. Mixing them in a single ranking
  produces nonsense results.

Sector exclusions from the default screen:
  FINANCIAL: Banks, insurance, REITs — use P/B, ROE, NIM instead of EV/EBIT
  UTILITY:   Electric, gas, water — high debt is structural, not distress
  REIT:      FFO-based, not earnings-based

Usage:
    # Classify the screened portfolio (fast, ~30s for 360 companies)
    python sector_classifier.py

    # Classify the full universe (slow, ~30min for 9000+ companies)
    python sector_classifier.py --full

    # Just print the current sector breakdown
    python sector_classifier.py --stats
"""

import os
import sys
import time
import logging
import argparse
import requests
import pandas as pd
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_QV_SRC = _HERE.parent / "phase2-tool-use" / "quant-value" / "src"

# Data directory — same pattern as edgar_screener.py
def _get_processed_path() -> Optional[Path]:
    """Locate the processed data directory via the QV config."""
    try:
        if str(_QV_SRC) not in sys.path:
            sys.path.insert(0, str(_QV_SRC))
        from config import get_data_paths
        paths = get_data_paths()
        return Path(paths.get("processed_dir", ""))
    except Exception:
        # Fallback: look in known location
        fallback = Path.home() / "QuantitativeValue" / "data" / "processed"
        return fallback if fallback.exists() else None

EDGAR_API = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_HEADERS = {"User-Agent": "Mithrandir-Research ben@mithrandir.local"}
REQUEST_DELAY = 0.12   # ~8 req/sec — well under SEC's 10/sec rate limit

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("mithrandir.sector")

# ---------------------------------------------------------------------------
# SIC → Sector mapping
# ---------------------------------------------------------------------------

# SIC codes are 4-digit integers. We map ranges to clean sector names.
# Source: https://www.sec.gov/info/edgar/siccodes.htm

SIC_SECTORS = [
    # (sic_min, sic_max, sector_name, screen_treatment)
    # screen_treatment: "include" | "exclude" | "separate"
    (100,   999,  "Agriculture",         "include"),
    (1000,  1099, "Metal Mining",        "include"),
    (1200,  1299, "Coal Mining",         "include"),
    (1300,  1399, "Oil & Gas",           "include"),
    (1400,  1499, "Mining",              "include"),
    (1500,  1799, "Construction",        "include"),
    (2000,  3999, "Manufacturing",       "include"),
    (4000,  4899, "Transportation",      "include"),
    (4900,  4941, "Utility",             "separate"),  # high debt is structural
    (4942,  4999, "Communications",      "include"),
    (5000,  5199, "Wholesale Trade",     "include"),
    (5200,  5999, "Retail Trade",        "include"),
    (6000,  6199, "Banking",             "separate"),  # different metrics
    (6200,  6299, "Credit",              "separate"),
    (6300,  6499, "Insurance",           "separate"),
    (6500,  6552, "Real Estate",         "separate"),
    (6700,  6726, "Holding Companies",   "separate"),
    (6726,  6726, "Investment Offices",  "separate"),
    (6730,  6799, "Investment Trusts",   "separate"),  # REITs
    (7000,  7389, "Services",            "include"),
    (7370,  7379, "Technology Services", "include"),
    (7389,  7999, "Entertainment",       "include"),
    (8000,  8099, "Healthcare",          "include"),
    (8100,  8742, "Professional Svcs",   "include"),
    (8742,  8999, "Consulting",          "include"),
    (9000,  9999, "Government",          "exclude"),   # typically not investable
]

def sic_to_sector(sic: Optional[int]) -> tuple[str, str]:
    """
    Map a SIC code to (sector_name, screen_treatment).
    Returns ("Unknown", "include") if SIC is None or unmapped.
    """
    if sic is None:
        return "Unknown", "include"
    for lo, hi, name, treatment in SIC_SECTORS:
        if lo <= sic <= hi:
            return name, treatment
    return "Other", "include"


# ---------------------------------------------------------------------------
# EDGAR fetcher
# ---------------------------------------------------------------------------

def fetch_sic(cik: int, session: requests.Session) -> Optional[dict]:
    """
    Fetch SIC code and description for a CIK from EDGAR submissions API.
    Returns dict with keys: cik, sic, sic_description, name
    Returns None on failure.
    """
    cik_str = str(int(cik)).zfill(10)
    url = EDGAR_API.format(cik=cik_str)
    try:
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            sic = d.get("sic")
            return {
                "cik": int(cik),
                "sic": int(sic) if sic else None,
                "sic_description": d.get("sicDescription", ""),
                "name": d.get("name", ""),
            }
        elif r.status_code == 404:
            return {"cik": int(cik), "sic": None, "sic_description": "", "name": ""}
        else:
            logger.warning(f"CIK {cik}: HTTP {r.status_code}")
            return None
    except Exception as e:
        logger.debug(f"CIK {cik}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def build_sectors_csv(full_universe: bool = False, force_refresh: bool = False) -> pd.DataFrame:
    """
    Build or update sectors.csv by fetching SIC codes from EDGAR.

    Args:
        full_universe: If True, classify all 9000+ companies in companies.csv.
                       If False (default), only classify the screened portfolio.
        force_refresh: If True, re-fetch even for already-classified CIKs.

    Returns:
        DataFrame with columns: cik, sic, sic_description, sector, screen_treatment, name
    """
    processed = _get_processed_path()
    if not processed:
        raise RuntimeError("Cannot locate processed data directory")

    companies_path = processed / "companies.csv"
    sectors_path = processed / "sectors.csv"
    portfolio_path = processed / "quantitative_value_portfolio.csv"

    companies = pd.read_csv(companies_path)

    # Decide which CIKs to classify
    if full_universe:
        target_ciks = set(companies["cik"].dropna().astype(int))
        logger.info(f"Full universe mode: {len(target_ciks)} CIKs to classify")
    else:
        # Prioritize screened portfolio
        target_ciks = set()
        if portfolio_path.exists():
            portfolio = pd.read_csv(portfolio_path)
            port_tickers = set(portfolio["ticker"].str.upper()) if "ticker" in portfolio.columns else set()
            port_companies = companies[companies["ticker"].isin(port_tickers)]
            target_ciks = set(port_companies["cik"].dropna().astype(int))
            logger.info(f"Portfolio mode: {len(target_ciks)} CIKs in screened portfolio")
        if not target_ciks:
            # Fallback: top 500 by CIK (they tend to be larger companies)
            target_ciks = set(companies["cik"].dropna().astype(int).head(500))
            logger.info(f"Fallback mode: classifying top 500 CIKs")

    # Load existing sectors cache
    if sectors_path.exists() and not force_refresh:
        existing = pd.read_csv(sectors_path)
        already_classified = set(existing["cik"].dropna().astype(int))
        missing_ciks = target_ciks - already_classified
        logger.info(f"Already classified: {len(already_classified)}, need to fetch: {len(missing_ciks)}")
    else:
        existing = pd.DataFrame()
        missing_ciks = target_ciks
        logger.info(f"Building sectors.csv from scratch: {len(missing_ciks)} CIKs")

    if not missing_ciks:
        logger.info("All target CIKs already classified — returning cached data")
        return existing

    # Fetch SIC codes for missing CIKs
    session = requests.Session()
    session.headers.update(EDGAR_HEADERS)

    results = []
    total = len(missing_ciks)
    for i, cik in enumerate(sorted(missing_ciks)):
        if i % 50 == 0:
            logger.info(f"Progress: {i}/{total} ({100*i//total}%)")
        result = fetch_sic(cik, session)
        if result:
            sector, treatment = sic_to_sector(result["sic"])
            result["sector"] = sector
            result["screen_treatment"] = treatment
            results.append(result)
        time.sleep(REQUEST_DELAY)

    if not results:
        logger.warning("No results fetched")
        return existing

    new_rows = pd.DataFrame(results)
    combined = pd.concat([existing, new_rows], ignore_index=True) if not existing.empty else new_rows
    combined = combined.drop_duplicates(subset=["cik"], keep="last")
    combined.to_csv(sectors_path, index=False)
    logger.info(f"Saved {len(combined)} classified companies to {sectors_path}")

    return combined


def get_sector(cik: int, sectors_df: Optional[pd.DataFrame] = None) -> tuple[str, str]:
    """
    Get (sector, screen_treatment) for a CIK.
    Falls back to "Unknown" / "include" if not classified.
    """
    if sectors_df is None:
        processed = _get_processed_path()
        if processed:
            path = processed / "sectors.csv"
            if path.exists():
                sectors_df = pd.read_csv(path)

    if sectors_df is None or sectors_df.empty:
        return "Unknown", "include"

    match = sectors_df[sectors_df["cik"] == cik]
    if match.empty:
        return "Unknown", "include"

    row = match.iloc[0]
    return row.get("sector", "Unknown"), row.get("screen_treatment", "include")


def load_sectors() -> Optional[pd.DataFrame]:
    """Load sectors.csv if it exists. Returns None if not yet built."""
    processed = _get_processed_path()
    if not processed:
        return None
    path = processed / "sectors.csv"
    return pd.read_csv(path) if path.exists() else None


def sector_stats(sectors_df: Optional[pd.DataFrame] = None) -> str:
    """Return a formatted breakdown of sector distribution."""
    if sectors_df is None:
        sectors_df = load_sectors()
    if sectors_df is None or sectors_df.empty:
        return "No sector data available. Run: python sector_classifier.py"

    lines = ["Sector breakdown:"]
    by_sector = sectors_df.groupby(["sector", "screen_treatment"]).size().reset_index(name="count")
    by_sector = by_sector.sort_values("count", ascending=False)
    for _, row in by_sector.iterrows():
        flag = " [SEPARATE SCREEN]" if row["screen_treatment"] == "separate" else ""
        flag += " [EXCLUDED]" if row["screen_treatment"] == "exclude" else ""
        lines.append(f"  {row['sector']}: {row['count']}{flag}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SIC-based sector classifications for QV universe")
    parser.add_argument("--full", action="store_true", help="Classify full universe (slow, ~30min)")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch all, ignoring cache")
    parser.add_argument("--stats", action="store_true", help="Print sector breakdown and exit")
    args = parser.parse_args()

    if args.stats:
        print(sector_stats())
        sys.exit(0)

    df = build_sectors_csv(full_universe=args.full, force_refresh=args.refresh)
    print(sector_stats(df))
