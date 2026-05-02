# Chronos Forward-Looking Pipeline

This folder contains a lightweight ingestion pipeline to discover recent model releases and stage them for review before merging into the canonical dataset.

## What It Produces

- Output file: `chronos/data/llm_releases_candidates.csv`
- Freshness file: `chronos/data/llm_releases_freshness.json`
- Purpose: candidate rows only (not auto-merged into `llm_releases_2020_present.csv`)

## Sources Included

- OpenRouter model index API (`https://openrouter.ai/api/v1/models`)
- Anthropic API release notes (`https://platform.claude.com/docs/en/release-notes/api`)
- Google Gemini API changelog (`https://ai.google.dev/gemini-api/docs/changelog`)

Source metadata is configured in `chronos/pipeline/sources.json`.

## Run

From the repository root:

```bash
python chronos/pipeline/update_chronos_candidates.py
```

Optional arguments:

```bash
python chronos/pipeline/update_chronos_candidates.py --since 2025-01-01
python chronos/pipeline/update_chronos_candidates.py --output chronos/data/llm_releases_candidates.csv
python chronos/pipeline/update_chronos_candidates.py --freshness-output chronos/data/llm_releases_freshness.json
```

The freshness file includes generated timestamp, source extraction counts, and a simple freshness status.

## Automation

- Weekly refresh runs every Friday at 15:00 UTC via GitHub Actions workflow:
	- `.github/workflows/chronos-weekly-refresh.yml`
- You can also run it on demand with `workflow_dispatch` from the Actions tab.

## Recommended Workflow

1. Run the script to refresh candidate rows.
2. Review `chronos/data/llm_releases_candidates.csv` for quality and duplicates.
3. Manually merge approved rows into `chronos/data/llm_releases_2020_present.csv`.
4. Deploy Chronos site updates.

## Notes

- The pipeline uses only Python standard library modules.
- It deduplicates against existing canonical rows using `(lab_name, model_name, release_date)`.
- It filters to rows on or after `--since`.
