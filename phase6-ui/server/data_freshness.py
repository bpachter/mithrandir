"""
phase6-ui/server/data_freshness.py — Data freshness audit surface.

Tracks when each data source was last updated and flags stale data.
Every financial answer in Mithrandir can be traced to a source + timestamp.

Freshness categories:
  fresh  — updated within the expected refresh window
  stale  — older than the expected window but still usable
  missing — data file not found

Used by:
  - GET /api/freshness  (dashboard UI)
  - Agent responses (provenance injection)
  - CI benchmark (freshness gate)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / ".env", override=True)


@dataclass
class DataSource:
    name: str
    path: Optional[Path]
    max_age_hours: float          # expected refresh window
    description: str
    source_url: str = ""
    fallback_path: Optional[Path] = None

    @property
    def exists(self) -> bool:
        if self.path and self.path.exists():
            return True
        if self.fallback_path and self.fallback_path.exists():
            return True
        return False

    @property
    def effective_path(self) -> Optional[Path]:
        if self.path and self.path.exists():
            return self.path
        if self.fallback_path and self.fallback_path.exists():
            return self.fallback_path
        return None

    @property
    def mtime(self) -> Optional[float]:
        p = self.effective_path
        return p.stat().st_mtime if p else None

    @property
    def age_hours(self) -> Optional[float]:
        m = self.mtime
        return (time.time() - m) / 3600 if m is not None else None

    @property
    def status(self) -> str:
        if not self.exists:
            return "missing"
        age = self.age_hours
        if age is None:
            return "missing"
        return "fresh" if age <= self.max_age_hours else "stale"

    def to_dict(self) -> dict:
        age = self.age_hours
        mtime = self.mtime
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "age_hours": round(age, 1) if age is not None else None,
            "max_age_hours": self.max_age_hours,
            "last_updated": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))
                if mtime else None
            ),
            "path": str(self.effective_path) if self.effective_path else None,
            "source_url": self.source_url,
        }


def _qv_path() -> Optional[Path]:
    raw = os.environ.get("QV_PATH", "")
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    # Bundled fallback
    bundled = _ROOT / "phase2-tool-use" / "quant-value"
    return bundled if bundled.exists() else None


def _get_sources() -> list[DataSource]:
    qv = _qv_path()
    processed = (qv / "data" / "processed") if qv else None

    return [
        DataSource(
            name="qv_portfolio",
            path=processed / "quantitative_value_portfolio.csv" if processed else None,
            max_age_hours=72,   # refreshed Mon-Fri after market close
            description="QV screened portfolio (top picks with EV/EBIT, F-Score, sector)",
            source_url="https://www.sec.gov/cgi-bin/browse-edgar",
        ),
        DataSource(
            name="qv_metrics",
            path=processed / "metrics.csv" if processed else None,
            max_age_hours=72,
            description="Computed financial ratios for all screened companies",
            source_url="https://data.sec.gov/api/xbrl/companyfacts/",
        ),
        DataSource(
            name="qv_companies",
            path=processed / "companies.csv" if processed else None,
            max_age_hours=168,  # company universe changes slowly (weekly is fine)
            description="Ticker / CIK universe mapping",
            source_url="https://www.sec.gov/files/company_tickers.json",
        ),
        DataSource(
            name="qv_sectors",
            path=processed / "sectors.csv" if processed else None,
            max_age_hours=168,
            description="SIC-based sector classification for screened companies",
        ),
        DataSource(
            name="memory_db",
            path=_ROOT / "phase4-memory" / "memory.db",
            fallback_path=_ROOT / "phase4-memory" / "mithrandir_memory.db",
            max_age_hours=720,  # memory grows over time; no hard staleness
            description="Conversation memory (SQLite exchange log)",
        ),
        DataSource(
            name="signals_db",
            path=_ROOT / "phase5-intelligence" / "signals.db",
            max_age_hours=48,
            description="QV signal log for backtesting (daily picks snapshot)",
        ),
        DataSource(
            name="regime_model",
            path=_ROOT / "phase3-agents" / "tools" / "regime_model.pkl",
            max_age_hours=720,  # HMM model is static unless retrained
            description="Trained HMM market regime model (SPY-based)",
        ),
    ]


def get_freshness_report() -> dict:
    """Return a full freshness report for all data sources."""
    sources = _get_sources()
    records = [s.to_dict() for s in sources]

    counts = {"fresh": 0, "stale": 0, "missing": 0}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    overall = (
        "fresh"   if counts["stale"] == 0 and counts["missing"] == 0 else
        "stale"   if counts["stale"] > 0 else
        "missing"
    )

    # Oldest source that exists
    oldest = max(
        (r for r in records if r["age_hours"] is not None),
        key=lambda r: r["age_hours"],
        default=None,
    )

    return {
        "overall": overall,
        "counts": counts,
        "oldest_hours": oldest["age_hours"] if oldest else None,
        "oldest_source": oldest["name"] if oldest else None,
        "sources": records,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def get_provenance_tag(source_name: str) -> str:
    """
    Return a short provenance string suitable for injecting into agent responses.
    Example: "[Source: SEC EDGAR | Last updated: 2025-07-14T18:30Z | Age: 14.2h]"
    """
    for s in _get_sources():
        if s.name == source_name:
            mtime = s.mtime
            age = s.age_hours
            if mtime and age is not None:
                ts = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(mtime))
                return f"[Source: SEC EDGAR | Last updated: {ts} | Age: {age:.1f}h]"
            return "[Source: SEC EDGAR | Age: unknown]"
    return ""


def get_portfolio_provenance() -> str:
    """Return a compact provenance string for QV portfolio data."""
    for s in _get_sources():
        if s.name == "qv_portfolio":
            age = s.age_hours
            status = s.status
            if age is not None:
                ts_fmt = ""
                if s.mtime:
                    ts_fmt = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(s.mtime))
                flag = "STALE" if status == "stale" else "FRESH"
                return f"[QV data {flag}: updated {ts_fmt} ({age:.0f}h ago) | Source: SEC EDGAR XBRL]"
            if status == "missing":
                return "[QV data MISSING: run the QV pipeline to generate data]"
    return ""


if __name__ == "__main__":
    import json
    report = get_freshness_report()
    print(json.dumps(report, indent=2))
