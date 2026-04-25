# Phase 7 — Data Center Siting Selection

> **Status:** Scaffold (alpha). Factor framework + scoring engine in place; ingest modules are stubs that document their public source and expected schema.

A quantitative siting engine for **hyperscale AI data centers**. Ingests publicly available infrastructure, climate, regulatory, and economic datasets, scores every candidate parcel (or H3 hex) against the factors hyperscalers actually optimize, and emits a **single composite score 0–10** (10 = best).

This is the spiritual successor to `phase2-tool-use/quant-value` — same philosophy (transparent multi-factor model, percentile-ranked composites, every input traceable to a public source), applied to physical infrastructure instead of equities.

---

## Why this exists

The 2024–2027 AI build-out is power-constrained, not chip-constrained. Hyperscalers (Microsoft, Google, Meta, Amazon, Oracle, xAI, CoreWeave, Crusoe) are racing for sites that combine:

1. **Power** — multi-hundred-MW capacity with a credible path to GW-scale, ideally behind-the-meter or with firm transmission rights.
2. **Network** — long-haul fiber on at least two diverse routes, low latency to major peering hubs.
3. **Water** — for evaporative or hybrid cooling, where climate doesn't permit air-only.
4. **Permitting velocity** — jurisdictions that will actually issue the permits inside 18 months.
5. **Tax structure** — sales/use exemptions on equipment, property tax abatements, depreciation treatment.
6. **Climate** — low wet-bulb, low severe-weather risk, high free-cooling hours.

Most of the inputs are **public** (FERC, EIA, FCC, USGS, NOAA, NASS, county GIS portals, state PUC dockets). Nobody has stitched them together into a single open, transparent siting score. That's what this phase does.

---

## Composite score (0–10)

For every candidate site `s`:

$$
\text{Score}(s) = 10 \cdot \sum_{f \in F} w_f \cdot \tilde{x}_{f,s}
$$

where:

- $F$ = factor set (see below).
- $\tilde{x}_{f,s} \in [0, 1]$ = factor `f`'s normalized sub-score for site `s` (1 = best in cohort).
- $w_f \in [0,1]$, $\sum_f w_f = 1$ — weights configurable per archetype (`training`, `inference`, `mixed`).

Default weights live in [config/weights.json](config/weights.json) and reflect a **training-cluster archetype** (power-dominant). Inference and mixed archetypes will lean more on latency and tax respectively.

Hard "kill" criteria (zoning forbids, FEMA 100-yr floodplain inside parcel, no fiber within 25 mi, etc.) clamp the composite to 0 regardless of weighted sum — see [src/score.py](src/score.py).

### Factor catalog

| # | Factor | Sub-score driver | Public source(s) |
|---|--------|------------------|------------------|
| 1 | `power_transmission` | Distance to nearest ≥230 kV line, substation MW headroom, interconnection queue position | EIA-860, FERC Form 715, HIFLD Transmission Lines, ISO/RTO queues (PJM, ERCOT, MISO, SPP, CAISO, NYISO, ISO-NE) |
| 2 | `power_cost` | Wholesale LMP avg + industrial retail $/kWh + PPA availability | EIA-861, ISO/RTO LMP feeds, state PUC tariffs |
| 3 | `power_carbon` | Generation mix carbon intensity (gCO₂/kWh) on the local balancing authority | EIA-930, EPA eGRID |
| 4 | `gas_pipeline` | Distance to interstate transmission pipelines (≥20") and laterals; firm transport availability | EIA Natural Gas Pipeline GIS, FERC pipeline filings, HIFLD pipelines |
| 5 | `fiber` | Long-haul fiber route count within 5 mi, route diversity (≥2 directions), distance to nearest carrier-neutral peering | FCC Form 477 broadband, HIFLD long-haul fiber, PeeringDB IXPs, state DOT fiber inventories |
| 6 | `water` | Surface-water + reclaimed-water availability (gpd), aquifer stress, drought-monitor 5-yr trend | USGS NWIS, NOAA Drought Monitor, EPA WaterSense, state water-rights DBs |
| 7 | `climate` | ASHRAE wet-bulb p99, free-cooling hours/yr, cooling degree days | NOAA NCEI, ASHRAE TMY |
| 8 | `hazard` | Floodplain %, seismic PGA, wildfire WUI, hurricane wind zone, tornado climatology | FEMA NFHL, USGS seismic hazard maps, USFS WHP, NOAA SPC |
| 9 | `land_zoning` | Parcel-size adequacy, allowed-use match (M-1/M-2/industrial), brownfield availability, slope | County parcel GIS, EPA brownfields, USGS 3DEP DEM |
| 10 | `tax_incentives` | State sales/use exemption on DC equipment (yes/scaled), property tax abatement years, opportunity zone | State commerce dept tax codes, IRS opportunity-zone shapefile |
| 11 | `permitting` | County track record (avg permit-to-COD months, recent DC builds, moratorium presence) | County permit portals, state PUC dockets, news graph |
| 12 | `latency` | Great-circle ms to top-10 internet exchanges, hyperscaler region presence | PeeringDB, hyperscaler region maps |
| 13 | `labor` | Skilled construction labor pool, electrician density, IT workforce within 50 mi | BLS QCEW, OEWS, ACS commuting flows |
| 14 | `community` | Recent siting approvals/denials, moratorium/anti-DC ordinance presence, noise ordinance strictness | County minutes scrape, state PUC dockets, local news graph |

Every sub-score is defined in [src/factors/](src/factors/) and documented in [docs/METHODOLOGY.md](docs/METHODOLOGY.md). Every public source is documented with refresh cadence in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

---

## Output

Two artefacts per run:

1. `data/processed/sites_scored.parquet` — every candidate hex/parcel with all 14 sub-scores, the composite, the active weights, the kill-criteria flags, and source-data timestamps (provenance).
2. `data/processed/top_sites.geojson` — top-N composite sites with full attribute table, ready for UI map overlay.

The Phase 6 UI consumes these via two new endpoints — see [phase6-ui/server/main.py](../phase6-ui/server/main.py) once the routes are wired in.

---

## Quick start

```bash
cd phase7-datacenter-siting
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Score a CSV of candidate sites (lat,lon,parcel_id,acres) using default weights
.venv\Scripts\python -m src.cli score --input config/sample_sites.csv --out data/processed/

# Run the full ingest pipeline (slow — months of data, GB-scale)
.venv\Scripts\python -m src.cli ingest --all

# Refresh just one factor (e.g., transmission)
.venv\Scripts\python -m src.cli ingest --factor power_transmission
```

---

## Architecture

```
phase7-datacenter-siting/
├── config/
│   ├── weights.json           # Factor weights per archetype
│   ├── kill_criteria.json     # Hard disqualifiers
│   └── sample_sites.csv       # Hand-picked candidate sites for smoke testing
├── src/
│   ├── cli.py                 # `score` + `ingest` commands
│   ├── config.py              # Paths, archetypes, env wiring
│   ├── geo.py                 # H3 hex utils, CRS, distance helpers
│   ├── score.py               # Composite scorer + kill-criteria gate
│   ├── normalize.py           # Percentile-rank + monotone-clip normalizers
│   ├── provenance.py          # Source/timestamp tagging on every value
│   ├── factors/               # One sub-score module per factor
│   │   ├── __init__.py
│   │   ├── power_transmission.py
│   │   ├── power_cost.py
│   │   ├── power_carbon.py
│   │   ├── gas_pipeline.py
│   │   ├── fiber.py
│   │   ├── water.py
│   │   ├── climate.py
│   │   ├── hazard.py
│   │   ├── land_zoning.py
│   │   ├── tax_incentives.py
│   │   ├── permitting.py
│   │   ├── latency.py
│   │   ├── labor.py
│   │   └── community.py
│   └── ingest/                # One scraper per public source
│       ├── __init__.py
│       ├── hifld.py           # HIFLD Open Data (transmission, pipelines, fiber)
│       ├── eia.py             # EIA-860/861/930 + state energy data
│       ├── ferc.py            # FERC Form 715, queue scrapes
│       ├── iso_queues.py      # PJM/ERCOT/MISO/SPP/CAISO/NYISO/ISO-NE queues
│       ├── fcc.py             # FCC Form 477 broadband
│       ├── peeringdb.py       # IX + facility data
│       ├── usgs.py            # NWIS water + 3DEP elevation + seismic
│       ├── noaa.py            # NCEI climate + drought monitor
│       ├── fema.py            # NFHL floodplains
│       ├── epa.py             # eGRID + brownfields
│       ├── irs.py             # Opportunity zones
│       ├── bls.py             # QCEW + OEWS
│       └── county_gis.py      # Per-county parcel/zoning scrape registry
├── data/                      # Gitignored (GB-scale)
│   ├── raw/
│   ├── interim/
│   └── processed/
├── docs/
│   ├── METHODOLOGY.md
│   ├── DATA_SOURCES.md
│   └── ARCHETYPES.md
└── requirements.txt
```

---

## Roadmap inside this phase

- [x] Factor catalog + weights + kill criteria
- [x] Scorer skeleton (`src/score.py`)
- [x] CLI skeleton (`src/cli.py`)
- [x] One ingest stub per public source (documented + signature-ready)
- [ ] First end-to-end run on Texas (ERCOT) — known hyperscaler hot zone
- [ ] H3 hex grid (res 7, ~5 km²) over CONUS
- [ ] Wire FastAPI endpoints + Phase 6 UI map view (Mapbox / MapLibre)
- [ ] Backtest: do our top-decile hexes overlap with real 2023–2025 announced builds?
- [ ] Add Canada (CAISO/AESO + BC Hydro + Quebec) for cold-climate cohort
- [ ] Add behind-the-meter generation overlay (gas turbines, SMR queue)

See [../ROADMAP.md](../ROADMAP.md) for the full Mithrandir roadmap.
