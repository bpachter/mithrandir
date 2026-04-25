"""
signal_logger.py — Record QV rankings with timestamps for backtesting

Every time this runs it saves a snapshot of the current top-N QV picks
to a SQLite database. The performance_tracker then pulls historical prices
to compute what return those picks generated.

This is the "was I right?" layer. Without it, the QV model is just a story.

Usage:
    python signal_logger.py              # Log current top 25 picks
    python signal_logger.py --show       # Print recent snapshots
    python signal_logger.py --list       # List all snapshot dates
"""

import os
import sys
import sqlite3
import argparse
import datetime
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_MITHRANDIR = _HERE.parent
_TOOLS_PATH = _MITHRANDIR / "phase2-tool-use" / "tools"
_QV_SRC = _MITHRANDIR / "phase2-tool-use" / "quant-value" / "src"

for p in [str(_TOOLS_PATH), str(_QV_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# DB lives alongside other intelligence data
_DB_PATH = _HERE / "signals.db"

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_dt TEXT NOT NULL,          -- ISO date when signal was logged
            ticker      TEXT NOT NULL,
            rank        INTEGER NOT NULL,       -- 1 = top pick
            sector      TEXT,
            ebit        REAL,
            net_income  REAL,
            fcf         REAL,
            roa         REAL,
            operating_margin REAL,
            debt_to_equity   REAL,
            market_cap  REAL,
            ev_ebit     REAL,
            value_composite  REAL,
            quality_flags    TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS return_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_dt   TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            price_entry   REAL,          -- price on snapshot_dt (or next trading day)
            price_current REAL,          -- most recent price
            price_exit    REAL,          -- price at horizon (if reached)
            horizon_days  INTEGER,       -- holding period in calendar days
            return_pct    REAL,          -- (price_exit or price_current - price_entry) / price_entry
            spy_return_pct REAL,         -- SPY return over same period (benchmark)
            alpha_pct     REAL,          -- return_pct - spy_return_pct
            last_updated  TEXT,
            UNIQUE(snapshot_dt, ticker, horizon_days)
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_snapshot(n: int = 25) -> dict:
    """
    Record the current top-N QV picks to the signals database.

    Returns:
        dict with keys: snapshot_dt, tickers_logged, already_exists
    """
    from edgar_screener import load_portfolio, _attach_sectors, _quality_flags
    import datetime, pandas as pd

    today = datetime.date.today().isoformat()

    conn = _get_conn()
    # Check if we already logged today
    existing = conn.execute(
        "SELECT COUNT(*) FROM signal_snapshots WHERE snapshot_dt = ?", (today,)
    ).fetchone()[0]

    if existing > 0:
        conn.close()
        return {"snapshot_dt": today, "tickers_logged": 0, "already_exists": True}

    # Load portfolio and apply quality gates (same as edgar_screener.get_top_stocks)
    df = load_portfolio()
    if df is None:
        conn.close()
        return {"snapshot_dt": today, "tickers_logged": 0, "error": "no portfolio data"}

    df = _attach_sectors(df)

    # Quality gates (mirrors get_top_stocks)
    df = df[df["ebit"] > 0]
    df = df[df["revenue"] > 1_000_000] if "revenue" in df.columns else df
    mcap_col = next((c for c in ["market_cap_final", "market_cap"] if c in df.columns), None)
    if mcap_col:
        df = df[df[mcap_col].fillna(0) >= 100_000_000]
    cutoff = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()
    df = df[df["period_end"] >= cutoff] if "period_end" in df.columns else df
    if "f_roa_positive" in df.columns:
        df = df[df["f_roa_positive"] == 1]
    if "f_cfo_positive" in df.columns:
        df = df[df["f_cfo_positive"] == 1]
    df = df[df["screen_treatment"] == "include"]

    # Sort and take top N
    sort_col = next((c for c in ["value_composite", "ev_ebit"] if c in df.columns), None)
    if sort_col == "value_composite" or sort_col == "ev_ebit":
        top = df.nsmallest(n, sort_col).reset_index(drop=True)
    else:
        conn.close()
        return {"snapshot_dt": today, "tickers_logged": 0, "error": "no sort column"}

    rows = []
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        flags = _quality_flags(row)
        mcap = row.get(mcap_col) if mcap_col else None
        rows.append((
            today,
            str(row.get("ticker", "")),
            rank,
            str(row.get("sector", "")),
            _safe_float(row.get("ebit")),
            _safe_float(row.get("net_income")),
            _safe_float(row.get("fcf")),
            _safe_float(row.get("roa")),
            _safe_float(row.get("operating_margin")),
            _safe_float(row.get("debt_to_equity")),
            _safe_float(mcap),
            _safe_float(row.get("ev_ebit")),
            _safe_float(row.get("value_composite")),
            flags,
        ))

    conn.executemany("""
        INSERT INTO signal_snapshots
        (snapshot_dt, ticker, rank, sector, ebit, net_income, fcf, roa,
         operating_margin, debt_to_equity, market_cap, ev_ebit, value_composite, quality_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()

    return {"snapshot_dt": today, "tickers_logged": len(rows), "already_exists": False}


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Read back
# ---------------------------------------------------------------------------

def get_snapshot(date: str | None = None) -> list[dict]:
    """
    Return signals for a given date (ISO string) or the most recent snapshot.
    """
    conn = _get_conn()
    if date is None:
        row = conn.execute(
            "SELECT snapshot_dt FROM signal_snapshots ORDER BY snapshot_dt DESC LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            return []
        date = row[0]

    rows = conn.execute(
        "SELECT * FROM signal_snapshots WHERE snapshot_dt = ? ORDER BY rank",
        (date,)
    ).fetchall()
    cols = [d[1] for d in conn.execute("PRAGMA table_info(signal_snapshots)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def list_snapshots() -> list[str]:
    """Return all snapshot dates in the database."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT snapshot_dt FROM signal_snapshots ORDER BY snapshot_dt DESC"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=25, help="Number of top picks to log (default: 25)")
    parser.add_argument("--show", action="store_true", help="Show most recent snapshot")
    parser.add_argument("--list", action="store_true", help="List all snapshot dates")
    args = parser.parse_args()

    if args.list:
        dates = list_snapshots()
        if dates:
            print(f"Signal snapshots ({len(dates)} dates):")
            for d in dates:
                snaps = get_snapshot(d)
                print(f"  {d}: {len(snaps)} picks")
        else:
            print("No snapshots yet.")
        sys.exit(0)

    if args.show:
        snaps = get_snapshot()
        if snaps:
            print(f"Snapshot: {snaps[0]['snapshot_dt']} ({len(snaps)} picks)\n")
            for s in snaps:
                flags = f"  [{s['quality_flags']}]" if s['quality_flags'] else ""
                print(f"  #{s['rank']:2d}  {s['ticker']:<6} {s['sector']:<20} "
                      f"EV/EBIT: {s['ev_ebit']:.2f}  "
                      f"VC: {s['value_composite']:.1f}{flags}")
        else:
            print("No snapshots yet.")
        sys.exit(0)

    result = log_snapshot(n=args.n)
    if result.get("already_exists"):
        print(f"Already logged today ({result['snapshot_dt']}). Use --show to view.")
    elif result.get("error"):
        print(f"Error: {result['error']}")
    else:
        print(f"Logged {result['tickers_logged']} picks for {result['snapshot_dt']}")
        print("Run with --show to view, or run performance_tracker.py to compute returns.")
