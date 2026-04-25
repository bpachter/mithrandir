# Phase 8 — Local-Only Research Pipeline (Gemma)

This phase standardizes a Kimi-free research workflow using only local Ollama/Gemma
for planning, extraction, and synthesis.

## Goals

- Run discovery, verification, and normalization with local Gemma only.
- Preserve citation quality and conflict tracking through strict contracts.
- Emit deterministic CSV/JSON artifacts that downstream apps can ingest.

## Scope (initial scaffold)

- Common data contracts for:
  - data center siting research rows
  - LLM release-history rows
- Validation-first pipeline stages:
  - target discovery
  - source verification
  - normalization
  - QA/conflict checks
  - export

## Execution model

- Planner/executor: local Gemma via Ollama.
- Tooling: existing Mithrandir registry + domain-specific fetch/parse utilities.
- No external planning model required.

## Runner (now available)

Run from repo root:

```bash
python phase8-local-research/run_pipeline.py --domain datacenter --input-file <path-to-brief.txt>
python phase8-local-research/run_pipeline.py --domain llm --input-file <path-to-brief.txt>
```

Optional flags:

- `--target-count 25`
- `--run-id 20260423_120000`
- `--out-dir phase8-local-research/output`

## Stage outputs

Each run writes stage artifacts under:

- `phase8-local-research/output/<domain>/<run_id>/stage1_discovery.json`
- `phase8-local-research/output/<domain>/<run_id>/stage2_verification.json`
- `phase8-local-research/output/<domain>/<run_id>/stage3_normalization.json`
- `phase8-local-research/output/<domain>/<run_id>/stage4_qa.json`
- `phase8-local-research/output/<domain>/<run_id>/summary.json`

## Export outputs

Datacenter domain:

- `datacenter_research_local_<run_id>.csv`
- `datacenter_research_local_<run_id>.json`
- `avalon_sites_seed_local_<run_id>.csv`

LLM domain:

- `llm_releases_local_<run_id>.csv`
- `llm_releases_local_<run_id>.json`

## Next implementation steps

1. Add a local pipeline runner that chains stage modules.
2. Add source adapters (company PRs, planning docs, utility dockets, model cards).
3. Add CSV emitters for Avalon and model-release dashboards.
4. Add regression fixtures and schema-level tests.
