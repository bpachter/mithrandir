"""
morning_brief.py — Generates and sends a daily 7am macro + QV brief via Telegram.

Triggered by Windows Task Scheduler (see install_morning_brief.bat).
Aggregates: Orator macro snapshot + QV signal picks + HMM market regime.
Sends a formatted Markdown message to Ben's Telegram chat.

Run directly to test: python morning_brief.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — ensure Mithrandir packages are importable
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
for _p in [
    str(_ROOT / "phase3-agents"),
    str(_ROOT / "phase3-agents" / "tools"),
    str(_ROOT / "phase2-tool-use"),
    str(_ROOT / "phase2-tool-use" / "tools"),
    str(_ROOT / "phase5-intelligence"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)
logger = logging.getLogger("mithrandir.brief")


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------

def _get_orator_snapshot() -> str:
    """Fetch Orator's condensed daily macro snapshot."""
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "orator_client",
            _ROOT / "phase3-agents" / "tools" / "orator_client.py",
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.get_daily_snapshot()
    except Exception as e:
        logger.warning("Orator snapshot unavailable: %s", e)
        return f"[Orator snapshot unavailable: {e}]"


def _get_qv_picks() -> str:
    """Return the most recent QV signal snapshot (top 5 picks)."""
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "signal_logger",
            _ROOT / "phase5-intelligence" / "signal_logger.py",
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)

        snaps = _mod.get_snapshot()
        if not snaps:
            return "No QV picks logged yet."

        dt = snaps[0].get("snapshot_dt", "?")
        lines = [f"Top QV picks (logged {dt}):"]
        for s in snaps[:5]:
            rank = s.get("rank", "?")
            ticker = s.get("ticker", "?")
            sector = s.get("sector", "")[:18]
            ev_ebit = s.get("ev_ebit", 0)
            vc = s.get("value_composite", 0)
            flags = f"  [{s['quality_flags']}]" if s.get("quality_flags") else ""
            lines.append(
                f"  #{rank:>2}  {ticker:<6} {sector:<18}  "
                f"EV/EBIT: {ev_ebit:.1f}  VC: {vc:.1f}{flags}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.warning("QV picks unavailable: %s", e)
        return f"[QV picks unavailable: {e}]"


def _get_regime() -> str:
    """Return current HMM market regime from regime_detector."""
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "regime_detector",
            _ROOT / "phase3-agents" / "tools" / "regime_detector.py",
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.get_regime_context()
    except Exception as e:
        logger.warning("Regime unavailable: %s", e)
        return f"[Market regime unavailable: {e}]"


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def _build_message(macro: str, picks: str, regime: str) -> str:
    """Assemble the Telegram Markdown message. Target: < 2000 chars."""
    ts = time.strftime("%Y-%m-%d %H:%M")
    sections = [
        "🌅 *Mithrandir Morning Brief*",
        "",
        "*📊 Macro Snapshot*",
        "```",
        macro[:900],
        "```",
        "",
        "*📈 Market Regime*",
        "```",
        regime[:400],
        "```",
        "",
        "*🏆 QV Top Picks*",
        "```",
        picks[:500],
        "```",
        "",
        f"_Generated {ts} · Reply in chat for deeper analysis_",
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if not token or not chat_id:
        logger.warning("Telegram not configured — printing to stdout instead.")
        print(message)
        return
    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=15.0,
        )
        resp.raise_for_status()
        logger.info("Morning brief sent via Telegram (chat_id=%s).", chat_id)
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        print(message)  # fallback to stdout so we can debug


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    logger.info("Generating morning brief…")
    macro = _get_orator_snapshot()
    picks = _get_qv_picks()
    regime = _get_regime()
    message = _build_message(macro, picks, regime)
    logger.debug("Brief message (%d chars):\n%s", len(message), message)
    _send_telegram(message)
    logger.info("Morning brief complete.")


if __name__ == "__main__":
    run()
