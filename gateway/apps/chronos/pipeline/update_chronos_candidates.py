from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CANONICAL_CSV = DATA_DIR / "llm_releases_2020_present.csv"
CANDIDATE_CSV = DATA_DIR / "llm_releases_candidates.csv"
FRESHNESS_JSON = DATA_DIR / "llm_releases_freshness.json"
SOURCES_JSON = Path(__file__).resolve().parent / "sources.json"

CSV_COLUMNS = [
    "lab_name",
    "model_name",
    "release_date",
    "context_window_tokens",
    "input_cost_usd_per_1m",
    "output_cost_usd_per_1m",
    "throughput_tokens_per_sec",
    "swe_bench_verified_pct",
    "mmlu_pct",
    "weights",
    "status",
    "source_url",
    "notes",
]

DATE_RE = re.compile(r"\b([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b")


def http_get_text(url: str, timeout_sec: int = 25, retries: int = 2) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "chronos-pipeline/1.0",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        },
    )
    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as ex:
            last_error = ex
            if attempt >= retries:
                break
            # Small exponential backoff to reduce transient source outages.
            time.sleep(1.5 ** (attempt + 1))

    if last_error:
        raise last_error
    raise RuntimeError("HTTP fetch failed without an explicit error")


def http_get_json(url: str) -> dict:
    return json.loads(http_get_text(url))


def parse_date_header(text: str) -> Optional[str]:
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def clean_text_for_scan(raw: str) -> str:
    # Flatten HTML and markdown-ish spacing for regex scanning.
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", no_tags)


def normalize_model_label(model_id: str, fallback_name: str = "") -> str:
    if fallback_name:
        return " ".join(fallback_name.split())
    return model_id.replace("~", "").replace("/", " ").replace("-", " ")


def infer_lab_from_id(model_id: str) -> str:
    provider = model_id.split("/", 1)[0].lower().lstrip("~")
    mapping = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google DeepMind",
        "x-ai": "xAI",
        "meta-llama": "Meta AI",
        "mistralai": "Mistral AI",
        "qwen": "Alibaba",
        "deepseek": "DeepSeek",
        "moonshotai": "Moonshot AI",
        "nvidia": "NVIDIA",
        "cohere": "Cohere",
    }
    return mapping.get(provider, provider.replace("-", " ").title())


def infer_weights(model_id: str, name: str = "") -> str:
    pid = model_id.lower()
    n = name.lower()
    open_hints = ["llama", "gemma", "qwen", "deepseek", "open", "oss", "ministral", "mistral small"]
    if any(h in pid or h in n for h in open_hints):
        return "open"
    return "closed"


def existing_keys(path: Path) -> set:
    keys = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = (
                (r.get("lab_name") or "").strip().lower(),
                (r.get("model_name") or "").strip().lower(),
                (r.get("release_date") or "").strip(),
            )
            if all(key):
                keys.add(key)
    return keys


def make_row(
    lab_name: str,
    model_name: str,
    release_date: str,
    source_url: str,
    notes: str,
    status: str = "active",
    weights: str = "closed",
) -> Dict[str, str]:
    return {
        "lab_name": lab_name,
        "model_name": model_name,
        "release_date": release_date,
        "context_window_tokens": "N/A",
        "input_cost_usd_per_1m": "N/A",
        "output_cost_usd_per_1m": "N/A",
        "throughput_tokens_per_sec": "N/A",
        "swe_bench_verified_pct": "N/A",
        "mmlu_pct": "N/A",
        "weights": weights,
        "status": status,
        "source_url": source_url,
        "notes": notes,
    }


def extract_openrouter(url: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    payload = http_get_json(url)
    now = dt.datetime.utcnow().date().isoformat()
    allowed_providers = {
        "openai",
        "anthropic",
        "google",
        "x-ai",
        "meta-llama",
        "mistralai",
        "qwen",
        "deepseek",
        "moonshotai",
        "nvidia",
        "cohere",
        "amazon",
        "alibaba",
        "z-ai",
    }

    for item in payload.get("data", []):
        model_id = (item.get("id") or "").strip()
        if not model_id:
            continue

        provider = model_id.split("/", 1)[0].lower().lstrip("~")
        if provider not in allowed_providers:
            continue
        if model_id.startswith("openrouter/"):
            continue
        if "router" in model_id:
            continue

        created = item.get("created")
        if not isinstance(created, int):
            continue

        released = dt.datetime.utcfromtimestamp(created).date().isoformat()
        lab = infer_lab_from_id(model_id)
        model_name = normalize_model_label(model_id, item.get("name") or "")
        expiration = item.get("expiration_date")
        status = "active"
        if isinstance(expiration, str) and expiration and expiration < now:
            status = "deprecated"

        notes = "OpenRouter models API auto-detected."
        if item.get("canonical_slug"):
            notes += f" canonical_slug={item['canonical_slug']}."

        rows.append(
            make_row(
                lab_name=lab,
                model_name=model_name,
                release_date=released,
                source_url=f"https://openrouter.ai/{model_id}",
                notes=notes,
                status=status,
                weights=infer_weights(model_id, model_name),
            )
        )

    return rows


def extract_anthropic_release_notes(url: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    text = http_get_text(url)
    lines = text.splitlines()

    current_date: Optional[str] = None
    model_id_re = re.compile(r"\bclaude-[a-z0-9.-]+(?:-\d{8})?\b", re.IGNORECASE)

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        maybe_date = parse_date_header(line)
        if maybe_date:
            current_date = maybe_date

        if "claude-" not in line.lower():
            continue

        model_ids = model_id_re.findall(line)
        if not model_ids:
            continue

        status = "active"
        low = line.lower()
        if "retired" in low or "retire" in low or "shut down" in low:
            status = "retired"
        elif "deprecat" in low:
            status = "deprecated"

        for mid in model_ids:
            mid_low = mid.lower()
            if not any(k in mid_low for k in ("haiku", "sonnet", "opus")):
                continue
            if not any(ch.isdigit() for ch in mid_low):
                continue
            if any(bad in mid_low for bad in ("api", "code", "bedrock", "vertex", "foundry", "deprecation")):
                continue

            model_name = normalize_model_label(mid)
            rows.append(
                make_row(
                    lab_name="Anthropic",
                    model_name=model_name,
                    release_date=current_date or dt.date.today().isoformat(),
                    source_url=url,
                    notes="Anthropic API release notes extraction.",
                    status=status,
                    weights="closed",
                )
            )

    return rows


def extract_google_changelog(url: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    raw = http_get_text(url)
    text = clean_text_for_scan(raw)

    date_points: List[Tuple[int, str]] = []
    for m in DATE_RE.finditer(text):
        try:
            iso = dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
            date_points.append((m.start(), iso))
        except ValueError:
            continue

    model_re = re.compile(
        r"\b(?:gemini|gemma|imagen|veo|lyria|text-embedding|embedding)-[a-z0-9.-]+\b",
        re.IGNORECASE,
    )

    for m in model_re.finditer(text):
        mid = m.group(0)

        release_date = dt.date.today().isoformat()
        for pos, iso in date_points:
            if pos <= m.start():
                release_date = iso
            else:
                break

        window_start = max(0, m.start() - 180)
        window_end = min(len(text), m.end() + 180)
        ctx = text[window_start:window_end].lower()

        status = "active"
        if "shut down" in ctx or "retired" in ctx:
            status = "retired"
        elif "deprecat" in ctx:
            status = "deprecated"

        rows.append(
            make_row(
                lab_name="Google DeepMind",
                model_name=normalize_model_label(mid),
                release_date=release_date,
                source_url=url,
                notes="Google Gemini API changelog extraction.",
                status=status,
                weights="closed",
            )
        )

    return rows


def filter_and_dedupe(
    rows: Iterable[Dict[str, str]],
    existing: set,
    since_date: dt.date,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()

    for r in rows:
        try:
            rd = dt.datetime.strptime(r["release_date"], "%Y-%m-%d").date()
        except ValueError:
            continue

        if rd < since_date:
            continue

        key = (
            r["lab_name"].strip().lower(),
            r["model_name"].strip().lower(),
            r["release_date"],
        )
        if key in existing or key in seen:
            continue

        seen.add(key)
        out.append(r)

    out.sort(key=lambda r: r["release_date"], reverse=True)
    return out


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_freshness_json(
    path: Path,
    candidates: List[Dict[str, str]],
    source_counts: Dict[str, int],
    since: str,
) -> None:
    now_utc = dt.datetime.utcnow().replace(microsecond=0)
    today_utc = now_utc.date()

    newest_release: Optional[str] = None
    days_since_newest: Optional[int] = None
    freshness_status = "no_recent_candidates"
    has_future_dated_candidates = False

    if candidates:
        newest_release = max(r["release_date"] for r in candidates)
        newest_date = dt.datetime.strptime(newest_release, "%Y-%m-%d").date()
        delta_days = (today_utc - newest_date).days
        has_future_dated_candidates = delta_days < 0
        days_since_newest = max(delta_days, 0)

        if has_future_dated_candidates:
            freshness_status = "fresh_future_dated"
        else:
            freshness_status = "fresh" if days_since_newest <= 7 else "stale"

    payload = {
        "generated_at_utc": f"{now_utc.isoformat()}Z",
        "since": since,
        "candidate_count": len(candidates),
        "newest_candidate_release_date": newest_release,
        "days_since_newest_candidate": days_since_newest,
        "has_future_dated_candidates": has_future_dated_candidates,
        "freshness_status": freshness_status,
        "source_counts": source_counts,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run(output_path: Path, since: str) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    since_date = dt.datetime.strptime(since, "%Y-%m-%d").date()
    existing = existing_keys(CANONICAL_CSV)

    with SOURCES_JSON.open("r", encoding="utf-8") as f:
        config = json.load(f)

    all_rows: List[Dict[str, str]] = []
    source_counts: Dict[str, int] = {}

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue

        name = source.get("name", "unknown")
        url = source.get("url", "")
        if not url:
            continue

        try:
            if name == "openrouter_models_api":
                extracted = extract_openrouter(url)
            elif name == "anthropic_api_release_notes":
                extracted = extract_anthropic_release_notes(url)
            elif name == "google_gemini_changelog":
                extracted = extract_google_changelog(url)
            else:
                extracted = []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as ex:
            print(f"[warn] source={name} failed: {ex}")
            extracted = []

        source_counts[name] = len(extracted)
        all_rows.extend(extracted)

    candidates = filter_and_dedupe(all_rows, existing=existing, since_date=since_date)
    write_csv(output_path, candidates)
    return candidates, source_counts


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Chronos candidate model releases from live sources.")
    p.add_argument(
        "--output",
        default=str(CANDIDATE_CSV),
        help="Output CSV path (default: chronos/data/llm_releases_candidates.csv)",
    )
    p.add_argument(
        "--since",
        default="2025-01-01",
        help="Earliest release date to include (YYYY-MM-DD).",
    )
    p.add_argument(
        "--freshness-output",
        default=str(FRESHNESS_JSON),
        help="Output JSON path for freshness metadata.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    freshness_output = Path(args.freshness_output)

    candidates, counts = run(output_path=output, since=args.since)
    write_freshness_json(
        path=freshness_output,
        candidates=candidates,
        source_counts=counts,
        since=args.since,
    )

    print(f"sources={counts}")
    print(f"wrote={len(candidates)} rows -> {output}")
    print(f"freshness_json={freshness_output}")
    if candidates:
        newest = candidates[0]
        print(
            "newest="
            f"{newest['release_date']} | {newest['lab_name']} | {newest['model_name']}"
        )


if __name__ == "__main__":
    main()
