"""
orator_client.py — HTTP client for the Orator macro data API.

Orator is Ben's Railway-deployed macroeconomic platform covering FRED, BEA,
EIA, CBOE, BIS, Treasury, World Bank, ECB, and more.  This module is imported
by registry.py and registered as the `orator_macro` and `orator_snapshot` tools.

All functions return strings (not dicts) so they slot directly into the
Mithrandir tool registry as observations.

ORATOR_URL env var must be set to the Railway deployment URL.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("mithrandir.tools.orator")

_BASE = os.environ.get("ORATOR_URL", "").rstrip("/")
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)


def _get(path: str, params: dict | None = None) -> dict | list | str:
    """GET a path on Orator. Returns parsed JSON or an error string."""
    if not _BASE:
        return "[orator_client] ORATOR_URL not set — add it to .env"
    url = f"{_BASE}{path}"
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return f"[orator_client] Timeout fetching {url}"
    except httpx.HTTPStatusError as e:
        return f"[orator_client] HTTP {e.response.status_code} from {url}"
    except Exception as e:
        return f"[orator_client] Error: {e}"


def _latest(series_list: list[dict]) -> str:
    """Extract the latest value from a list of {date, value} observations."""
    if not series_list:
        return "N/A"
    last = series_list[-1]
    return f"{last.get('value', 'N/A')} ({last.get('date', '')})"


# ---------------------------------------------------------------------------
# Per-endpoint fetchers — adapted to actual Orator response schemas
# ---------------------------------------------------------------------------

def get_recession_signals() -> str:
    """Fetch Orator's recession composite and all component signals."""
    data = _get("/api/recession-signals")
    if isinstance(data, str):
        return data
    try:
        composite = data.get("composite_score", "?")
        stagflation = data.get("stagflation_score", "?")
        lines = [
            "=== Recession Signals ===",
            f"Composite risk score : {composite:.3f}  (0=none, 1=full)",
            f"Stagflation pressure : {stagflation:.3f}",
        ]

        # Categorise signals
        signals: list[dict] = data.get("signals", [])
        by_cat: dict[str, list[dict]] = {}
        for s in signals:
            cat = s.get("category", "other")
            by_cat.setdefault(cat, []).append(s)

        for cat, sigs in sorted(by_cat.items()):
            lines.append(f"\n{cat.upper()}:")
            for s in sigs:
                flag = "⚠" if s.get("triggered") else "·"
                val = s.get("value")
                val_str = f"{val:.2f}" if isinstance(val, (int, float)) and val is not None else str(val)
                sev = s.get("severity", "normal")
                lines.append(f"  {flag} {s.get('label','?'):<35} {val_str:<10} [{sev}]")

        return "\n".join(lines)
    except Exception as e:
        return f"[orator_client] Failed to parse recession signals: {e}"


def get_yield_curve() -> str:
    """Fetch yield curve shape — 2/10 spread and key maturities from latest date."""
    data = _get("/api/spreads")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        t10y2y = series.get("T10Y2Y", [])
        t10y3m = series.get("T10Y3M", [])
        t10y1y = series.get("T10Y1Y", [])

        lines = ["=== Yield Curve ==="]
        if t10y2y:
            v = t10y2y[-1]["value"]
            lines.append(f"10Y-2Y spread : {v:+.2f}%  [{'INVERTED' if v < 0 else 'positive'}]")
        if t10y3m:
            v = t10y3m[-1]["value"]
            lines.append(f"10Y-3M spread : {v:+.2f}%  [{'INVERTED' if v < 0 else 'positive'}]")
        if t10y1y:
            v = t10y1y[-1]["value"]
            lines.append(f"10Y-1Y spread : {v:+.2f}%")

        # Note: post-inversion unwind is in recession signals
        return "\n".join(lines)
    except Exception as e:
        return f"[orator_client] Failed to parse yield curve: {e}"


def get_credit_conditions() -> str:
    """Fetch credit spread conditions: IG/HY spreads, financial conditions index."""
    data = _get("/api/credit-conditions")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        metadata: list[dict] = data.get("metadata", [])
        label_map = {m["id"]: m["label"] for m in metadata}
        lines = ["=== Credit Conditions ==="]
        for sid, obs in series.items():
            if obs:
                label = label_map.get(sid, sid)
                latest = obs[-1]
                lines.append(f"  {label:<45} {latest['value']:.2f}  ({latest['date']})")
        return "\n".join(lines) if len(lines) > 1 else "Credit conditions data unavailable"
    except Exception as e:
        return f"[orator_client] Failed to parse credit conditions: {e}"


def get_markets_overview() -> str:
    """Fetch VIX, equity market levels, and key market indicators."""
    data = _get("/api/markets")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        metadata: list[dict] = data.get("metadata", [])
        label_map = {m["id"]: m["label"] for m in metadata}
        lines = ["=== Markets ==="]
        for sid, obs in series.items():
            if obs:
                label = label_map.get(sid, sid)
                latest = obs[-1]
                lines.append(f"  {label:<40} {latest['value']:.2f}  ({latest['date']})")
        return "\n".join(lines) if len(lines) > 1 else "Markets data unavailable"
    except Exception as e:
        return f"[orator_client] Failed to parse markets: {e}"


def get_labor() -> str:
    """Fetch labor market indicators: unemployment, payrolls, Sahm rule."""
    data = _get("/api/labor")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        metadata: list[dict] = data.get("metadata", [])
        label_map = {m["id"]: m["label"] for m in metadata}
        lines = ["=== Labor Market ==="]
        for sid, obs in series.items():
            if obs:
                label = label_map.get(sid, sid)
                latest = obs[-1]
                lines.append(f"  {label:<45} {latest['value']:.2f}  ({latest['date']})")
        return "\n".join(lines) if len(lines) > 1 else "Labor data unavailable"
    except Exception as e:
        return f"[orator_client] Failed to parse labor: {e}"


def get_inflation() -> str:
    """Fetch inflation indicators: CPI, core CPI, PCE, breakevens."""
    data = _get("/api/inflation")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        metadata: list[dict] = data.get("metadata", [])
        label_map = {m["id"]: m["label"] for m in metadata}
        lines = ["=== Inflation ==="]
        for sid, obs in series.items():
            if obs:
                label = label_map.get(sid, sid)
                latest = obs[-1]
                lines.append(f"  {label:<45} {latest['value']:.2f}  ({latest['date']})")
        return "\n".join(lines) if len(lines) > 1 else "Inflation data unavailable"
    except Exception as e:
        return f"[orator_client] Failed to parse inflation: {e}"


def get_volatility() -> str:
    """Fetch VIX, VVIX, SKEW, and volatility term structure."""
    data = _get("/api/volatility")
    if isinstance(data, str):
        return data
    try:
        series = data.get("series", {})
        metadata: list[dict] = data.get("metadata", [])
        label_map = {m["id"]: m["label"] for m in metadata}
        lines = ["=== Volatility ==="]
        for sid, obs in series.items():
            if obs:
                label = label_map.get(sid, sid)
                latest = obs[-1]
                lines.append(f"  {label:<40} {latest['value']:.2f}  ({latest['date']})")
        return "\n".join(lines) if len(lines) > 1 else "Volatility data unavailable"
    except Exception as e:
        return f"[orator_client] Failed to parse volatility: {e}"


# ---------------------------------------------------------------------------
# Snapshot endpoint (Phase 3 — /api/snapshot built in Orator)
# ---------------------------------------------------------------------------

def get_daily_snapshot() -> str:
    """Fetch Orator's condensed daily macro snapshot (single-call summary)."""
    data = _get("/api/snapshot")
    if isinstance(data, str):
        return data
    try:
        lines = [
            "=== Orator Daily Macro Snapshot ===",
            f"Date              : {data.get('date', '?')}",
            f"Recession risk    : {data.get('recession_label', '?')} (composite {data.get('recession_composite', '?'):.3f})",
            f"Stagflation score : {data.get('stagflation_score', 0.0):.3f}",
            f"2/10 spread       : {data.get('yield_curve_spread_2_10', '?'):+.2f}%  [{'INVERTED' if data.get('yield_curve_inverted') else 'positive'}]",
            f"VIX               : {data.get('vix', '?'):.1f}  [{data.get('vix_regime', '?')}]",
            f"HY spread         : {data.get('hy_spread', '?'):.0f}bps",
            f"Unemployment      : {data.get('unemployment', '?'):.1f}%",
            f"CPI YoY           : {data.get('cpi_yoy', '?'):.1f}%",
            f"Fed funds rate    : {data.get('fed_funds_rate', '?'):.2f}%",
        ]
        top_sigs = data.get("top_signals", [])
        if top_sigs:
            lines.append("\nTop signals:")
            for s in top_sigs:
                lines.append(f"  · {s.get('name','?'):<35} {s.get('value','?')}  [{s.get('state','?')}]")
        narrative = data.get("narrative", "")
        if narrative:
            lines.append(f"\nNarrative:\n{narrative}")
        return "\n".join(lines)
    except Exception as e:
        return f"[orator_client] Failed to parse snapshot: {e}"


# ---------------------------------------------------------------------------
# Composite context (used by the `orator_macro` tool)
# ---------------------------------------------------------------------------

def get_macro_context(query: str = "") -> str:
    """
    Fetch a composite macro view: recession signals + yield curve + credit +
    markets + labor summary. The query string is used to decide focus.
    Always includes the recession composite — highest signal.
    """
    q = (query or "").lower()

    parts = [get_recession_signals()]

    if any(kw in q for kw in ["yield", "curve", "treasury", "rate", "rates", "inversion", "spread"]):
        parts.append(get_yield_curve())
    if any(kw in q for kw in ["credit", "spread", "hy", "ig", "junk", "bond", "delinquency"]):
        parts.append(get_credit_conditions())
    if any(kw in q for kw in ["vix", "volatility", "market", "equity", "stock", "skew"]):
        parts.append(get_markets_overview())
        parts.append(get_volatility())
    if any(kw in q for kw in ["labor", "jobs", "unemployment", "payroll", "sahm", "claims"]):
        parts.append(get_labor())
    if any(kw in q for kw in ["inflation", "cpi", "pce", "breakeven", "prices", "stagflation"]):
        parts.append(get_inflation())

    # Default: include yield curve + markets overview if no keyword matched
    if len(parts) == 1:
        parts.append(get_yield_curve())
        parts.append(get_markets_overview())

    return "\n\n".join(parts)
