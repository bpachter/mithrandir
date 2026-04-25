"""
alert_engine.py — Proactive intelligence alerts via Telegram

Runs scheduled scans and pushes notifications when conditions are met.
Designed to be called from Windows Task Scheduler (daily, weekly).

Alerts:
  price_dip   — Any watched stock down 5%+ from its signal-date entry price
  ranking_diff — New entries/exits in the top-25 QV ranking vs last snapshot
  performance  — Weekly performance summary (returns vs SPY)

Usage:
    python alert_engine.py price_dip          # Check for price dips
    python alert_engine.py ranking_diff       # Check for ranking changes
    python alert_engine.py performance        # Weekly perf summary
    python alert_engine.py all                # Run all alerts
"""

import os
import sys
import datetime
import requests
import logging
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
_MITHRANDIR = _HERE.parent
_TOOLS_PATH = _MITHRANDIR / "phase2-tool-use" / "tools"
_PHASE4 = _MITHRANDIR / "phase4-memory"

for p in [str(_TOOLS_PATH), str(_HERE)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(str(_MITHRANDIR / ".env"))

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("mithrandir.alerts")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")

# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> bool:
    """Send a message to the authorized user via the Mithrandir bot."""
    if not BOT_TOKEN or not ALLOWED_USER_ID:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USER_ID not set")
        return False
    try:
        import ssl
        from requests.adapters import HTTPAdapter

        class _TLS(HTTPAdapter):
            def init_poolmanager(self, *a, **kw):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                kw["ssl_context"] = ctx
                super().init_poolmanager(*a, **kw)

        s = requests.Session()
        s.verify = False
        s.mount("https://", _TLS())

        r = s.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ALLOWED_USER_ID, "text": text},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Price utilities
# ---------------------------------------------------------------------------

def _current_price(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf
        import warnings
        warnings.filterwarnings("ignore")
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return None
        val = hist["Close"].iloc[-1]
        if hasattr(val, "item"):
            val = val.item()
        return float(val) if val == val else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Alert: Price dip
# ---------------------------------------------------------------------------

def alert_price_dip(dip_threshold: float = -0.05) -> str:
    """
    Check if any current top-25 picks are down significantly from their
    signal-date entry price. A dip alert is a potential buying opportunity.
    """
    from signal_logger import get_snapshot, list_snapshots

    snapshots = list_snapshots()
    if not snapshots:
        return "No signal snapshots yet."

    latest = get_snapshot(snapshots[0])
    if not latest:
        return "No picks in latest snapshot."

    dips = []
    for pick in latest[:25]:
        ticker = pick["ticker"]
        entry_price = pick.get("entry_price_cached")  # might not exist yet

        # If we don't have cached entry price, fetch it
        if not entry_price:
            from performance_tracker import _fetch_price
            entry_price = _fetch_price(ticker, pick["snapshot_dt"])

        if not entry_price:
            continue

        current = _current_price(ticker)
        if current is None:
            continue

        change = (current - entry_price) / entry_price
        if change <= dip_threshold:
            dips.append({
                "ticker": ticker,
                "sector": pick.get("sector", ""),
                "rank": pick["rank"],
                "entry": entry_price,
                "current": current,
                "change_pct": change,
            })

    if not dips:
        return ""

    lines = [f"PRICE DIP ALERT — {datetime.date.today().isoformat()}",
             f"{len(dips)} QV picks down {abs(dip_threshold):.0%}+ from signal date:\n"]
    for d in sorted(dips, key=lambda x: x["change_pct"]):
        lines.append(
            f"  #{d['rank']:2d} {d['ticker']:<6} {d['sector']:<20} "
            f"Entry: ${d['entry']:.2f}  Now: ${d['current']:.2f}  "
            f"Change: {d['change_pct']:+.1%}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alert: Ranking diff
# ---------------------------------------------------------------------------

def alert_ranking_diff() -> str:
    """
    Compare the two most recent snapshots and report new entries and exits
    from the top-25 ranking.
    """
    from signal_logger import list_snapshots, get_snapshot

    dates = list_snapshots()
    if len(dates) < 2:
        return ""  # Need at least 2 snapshots to diff

    current_snaps = get_snapshot(dates[0])
    previous_snaps = get_snapshot(dates[1])

    current_tickers = {s["ticker"] for s in current_snaps}
    previous_tickers = {s["ticker"] for s in previous_snaps}

    new_entries = current_tickers - previous_tickers
    exits = previous_tickers - current_tickers

    if not new_entries and not exits:
        return ""

    lines = [f"RANKING UPDATE — {dates[0]} vs {dates[1]}"]

    if new_entries:
        lines.append(f"\nNew entries ({len(new_entries)}):")
        for snap in current_snaps:
            if snap["ticker"] in new_entries:
                lines.append(
                    f"  #{snap['rank']:2d} {snap['ticker']:<6} {snap['sector']:<20} "
                    f"EV/EBIT: {snap['ev_ebit']:.2f}  VC: {snap['value_composite']:.1f}"
                    + (f"  [{snap['quality_flags']}]" if snap['quality_flags'] else "")
                )

    if exits:
        lines.append(f"\nDropped out ({len(exits)}): {', '.join(sorted(exits))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alert: Performance summary
# ---------------------------------------------------------------------------

def alert_performance() -> str:
    """Weekly performance summary for /performance Telegram command."""
    from performance_tracker import performance_summary
    summary = performance_summary()
    if "maturing" in summary or "No return" in summary:
        return ""
    return f"WEEKLY PERFORMANCE UPDATE\n{summary}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_all_alerts():
    """Run all alerts and send non-empty results to Telegram."""
    sent = 0

    for fn, name in [
        (alert_ranking_diff, "ranking_diff"),
        (alert_price_dip, "price_dip"),
        (alert_performance, "performance"),
    ]:
        try:
            msg = fn()
            if msg:
                logger.info(f"Alert '{name}' fired — sending to Telegram")
                _send_telegram(msg)
                sent += 1
            else:
                logger.info(f"Alert '{name}': no conditions met")
        except Exception as e:
            logger.error(f"Alert '{name}' failed: {e}")

    return sent


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "all":
        count = run_all_alerts()
        print(f"Ran all alerts — {count} sent to Telegram")

    elif sys.argv[1] == "price_dip":
        msg = alert_price_dip()
        print(msg if msg else "No dips detected.")
        if msg:
            _send_telegram(msg)

    elif sys.argv[1] == "ranking_diff":
        msg = alert_ranking_diff()
        print(msg if msg else "No ranking changes.")
        if msg:
            _send_telegram(msg)

    elif sys.argv[1] == "performance":
        msg = alert_performance()
        print(msg if msg else "Returns still maturing.")
        if msg:
            _send_telegram(msg)

    else:
        print(f"Unknown command: {sys.argv[1]}")
        print("Usage: alert_engine.py [all|price_dip|ranking_diff|performance]")
