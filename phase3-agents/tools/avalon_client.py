"""
avalon_client.py — HTTP client for the Avalon datacenter siting API.

Avalon is Ben's Railway-deployed site selection platform covering power
transmission, fiber, gas pipeline, seismic risk, water, permitting climate,
and 14 scoring factors.  This module is imported by registry.py and registered
as the `avalon_siting` tool.

AVALON_URL env var must point to the Railway deployment URL.

Note: Avalon already calls Mithrandir's Ollama for AI narratives — this
creates the *reverse* link so Mithrandir can also query Avalon's scoring engine.
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx

logger = logging.getLogger("mithrandir.tools.avalon")

_BASE = os.environ.get("AVALON_URL", "").rstrip("/")
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)


def _get(path: str, params: dict | None = None) -> dict | list | str:
    if not _BASE:
        return "[avalon_client] AVALON_URL not set — add it to .env"
    url = f"{_BASE}{path}"
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return f"[avalon_client] Timeout fetching {url}"
    except httpx.HTTPStatusError as e:
        return f"[avalon_client] HTTP {e.response.status_code} from {url}: {e.response.text[:200]}"
    except Exception as e:
        return f"[avalon_client] Error: {e}"


def _post(path: str, body: dict) -> dict | str:
    if not _BASE:
        return "[avalon_client] AVALON_URL not set — add it to .env"
    url = f"{_BASE}{path}"
    try:
        resp = httpx.post(url, json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return f"[avalon_client] Timeout posting to {url}"
    except httpx.HTTPStatusError as e:
        return f"[avalon_client] HTTP {e.response.status_code} from {url}: {e.response.text[:300]}"
    except Exception as e:
        return f"[avalon_client] Error: {e}"


# ---------------------------------------------------------------------------
# Health / reachability
# ---------------------------------------------------------------------------

def check_health() -> str:
    data = _get("/api/health")
    if isinstance(data, str):
        return data
    return f"Avalon: {data.get('status', 'unknown')}  version={data.get('version', '?')}"


# ---------------------------------------------------------------------------
# Factor catalog
# ---------------------------------------------------------------------------

def get_factors() -> str:
    """Return the Avalon factor catalog — scoring factors with weights."""
    data = _get("/api/siting/factors")
    if isinstance(data, str):
        return data
    try:
        lines = ["=== Avalon Factor Catalog ==="]
        factors = data.get("factors", data)
        if isinstance(factors, dict):
            for name, info in sorted(factors.items()):
                weight = info.get("weight", info.get("w", "?"))
                desc = info.get("description", info.get("desc", ""))
                lines.append(f"  {name:<30} weight={weight}  {desc}")
        elif isinstance(factors, list):
            for f in factors:
                name = f.get("name", f.get("id", "?"))
                weight = f.get("weight", f.get("w", "?"))
                desc = f.get("description", f.get("desc", ""))
                lines.append(f"  {name:<30} weight={weight}  {desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"[avalon_client] Failed to parse factors: {e}"


# ---------------------------------------------------------------------------
# Site scoring
# ---------------------------------------------------------------------------

def score_site(lat: float, lon: float, archetype: str = "hyperscale") -> str:
    """Score a candidate datacenter site by lat/lon coordinates."""
    body = {"lat": lat, "lon": lon, "archetype": archetype}
    data = _post("/api/siting/score", body)
    if isinstance(data, str):
        return data
    try:
        lines = [
            "=== Avalon Site Score ===",
            f"Location  : {lat:.4f}°N, {lon:.4f}°E  (archetype: {archetype})",
        ]

        composite = data.get("composite") or data.get("total_score") or data.get("score")
        if composite is not None:
            lines.append(f"Composite : {float(composite):.2f} / 10")

        # Factor breakdown
        factors = data.get("factors") or data.get("factor_scores") or {}
        if isinstance(factors, dict) and factors:
            lines.append("Factors:")
            for fname, fdata in sorted(factors.items()):
                if isinstance(fdata, dict):
                    raw = fdata.get("raw") or fdata.get("score") or fdata.get("value", "?")
                    scaled = fdata.get("scaled") or fdata.get("weighted", "")
                    lines.append(f"  {fname:<30} raw={raw}  scaled={scaled}")
                else:
                    lines.append(f"  {fname:<30} {fdata}")

        # AI narrative
        summary = (
            data.get("overall_summary")
            or data.get("summary")
            or data.get("narrative")
            or data.get("ai_narrative", "")
        )
        if summary:
            lines.append(f"\nAI Summary:\n{summary}")

        return "\n".join(lines)
    except Exception as e:
        return f"[avalon_client] Failed to parse score response: {e}\nRaw: {json.dumps(data)[:400]}"


# ---------------------------------------------------------------------------
# Sample / top sites
# ---------------------------------------------------------------------------

def get_sample_sites(archetype: str = "hyperscale", limit: int = 5) -> str:
    """Return top-scored sample sites for a given archetype."""
    data = _get("/api/siting/sample", params={"archetype": archetype, "limit": limit})
    if isinstance(data, str):
        return data
    try:
        sites = data.get("sites", data) if isinstance(data, dict) else data
        if not isinstance(sites, list):
            return f"[avalon_client] Unexpected sample sites format: {type(sites)}"
        lines = [f"=== Avalon Top {archetype.title()} Sites (limit={limit}) ==="]
        for i, site in enumerate(sites[:limit], 1):
            name = site.get("name") or site.get("site_id") or f"Site {i}"
            score = site.get("composite") or site.get("total_score") or site.get("score", "?")
            state = site.get("state", "")
            lat = site.get("lat", "")
            lon = site.get("lon", "")
            score_str = f"{float(score):.2f}/10" if isinstance(score, (int, float)) else str(score)
            lines.append(f"  #{i:2d}  {name:<30} {state:<4}  Score: {score_str:<9}  [{lat}, {lon}]")
        return "\n".join(lines)
    except Exception as e:
        return f"[avalon_client] Failed to parse sample sites: {e}"


# ---------------------------------------------------------------------------
# State-level summary
# ---------------------------------------------------------------------------

def get_states_summary() -> str:
    """Return state-level datacenter siting summary from Avalon."""
    data = _get("/api/siting/states")
    if isinstance(data, str):
        return data
    try:
        states = data.get("states", data) if isinstance(data, dict) else data
        if isinstance(states, list):
            lines = ["=== Avalon State Summary ==="]
            # Sort by score descending
            sorted_states = sorted(
                states,
                key=lambda s: float(s.get("composite", s.get("score", 0)) or 0),
                reverse=True,
            )
            for s in sorted_states[:20]:
                name = s.get("name") or s.get("state", "?")
                score = s.get("composite") or s.get("score", "?")
                score_str = f"{float(score):.2f}/10" if isinstance(score, (int, float)) else str(score)
                lines.append(f"  {name:<25} {score_str}")
            return "\n".join(lines)
        return json.dumps(data, indent=2)[:3000]
    except Exception as e:
        return f"[avalon_client] Failed to parse states: {e}"


# ---------------------------------------------------------------------------
# Dispatch — plain-language routing
# ---------------------------------------------------------------------------

def query_siting(query: str = "") -> str:
    """Route a plain-language siting query to the appropriate Avalon endpoint."""
    q = (query or "").lower()

    # Parse lat/lon if present
    lat_match = re.search(r"lat(?:itude)?[\s:=]+([+-]?\d+\.?\d*)", q)
    lon_match = re.search(r"lon(?:gitude)?[\s:=]+([+-]?\d+\.?\d*)", q)

    # Archetype parsing
    archetype = "hyperscale"
    if "colocation" in q or "colo" in q:
        archetype = "colocation"
    elif "enterprise" in q:
        archetype = "enterprise"
    elif "edge" in q:
        archetype = "edge"

    if lat_match and lon_match:
        return score_site(float(lat_match.group(1)), float(lon_match.group(1)), archetype)

    if any(kw in q for kw in ["top sites", "best sites", "sample", "candidates", "ranked"]):
        return get_sample_sites(archetype)

    if any(kw in q for kw in ["factor", "weight", "catalog", "criteria", "how does avalon score"]):
        return get_factors()

    if any(kw in q for kw in ["state", "states", "which states", "by state"]):
        return get_states_summary()

    if any(kw in q for kw in ["health", "status", "up"]):
        return check_health()

    # Default: sample sites + factor overview
    return get_sample_sites(archetype) + "\n\n" + get_factors()
