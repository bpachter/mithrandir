"""Paths, archetypes, env wiring for Phase 7."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MITHRANDIR_ROOT = ROOT.parent
load_dotenv(MITHRANDIR_ROOT / ".env", override=False)

CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.environ.get("DCSITE_DATA", ROOT / "data")).resolve()
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR):
    d.mkdir(parents=True, exist_ok=True)

Archetype = Literal["training", "inference", "mixed"]
DEFAULT_ARCHETYPE: Archetype = "training"

FACTOR_NAMES: tuple[str, ...] = (
    "power_transmission",
    "power_cost",
    "power_carbon",
    "gas_pipeline",
    "fiber",
    "water",
    "climate",
    "hazard",
    "land_zoning",
    "tax_incentives",
    "permitting",
    "latency",
    "labor",
    "community",
)


def load_weights(archetype: Archetype = DEFAULT_ARCHETYPE) -> dict[str, float]:
    """Return factor weights for the requested archetype, validated to sum to ~1.0."""
    raw = json.loads((CONFIG_DIR / "weights.json").read_text())
    if archetype not in raw["archetypes"]:
        raise ValueError(f"unknown archetype: {archetype!r}")
    weights = {
        k: float(v)
        for k, v in raw["archetypes"][archetype].items()
        if not k.startswith("_")
    }
    missing = set(FACTOR_NAMES) - set(weights)
    if missing:
        raise ValueError(f"weights.json missing factors for {archetype}: {missing}")
    s = sum(weights.values())
    if abs(s - 1.0) > 1e-3:
        raise ValueError(f"{archetype} weights sum to {s:.4f}, expected 1.0")
    return weights


def load_kill_criteria() -> dict[str, dict]:
    """Return the kill-criteria config as a flat dict keyed by criterion name."""
    raw = json.loads((CONFIG_DIR / "kill_criteria.json").read_text())
    return raw["criteria"]
