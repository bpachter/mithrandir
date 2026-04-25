"""
tests/benchmark.py — Mithrandir evaluation + regression benchmark runner.

Usage:
    # Full benchmark (all categories)
    python tests/benchmark.py

    # Single category
    python tests/benchmark.py --category routing

    # Single prompt by ID
    python tests/benchmark.py --id identity_01

    # Fail fast (stop on first failure)
    python tests/benchmark.py --fail-fast

    # Output JSON scorecard
    python tests/benchmark.py --json > scorecard.json

    # Latency-only mode (skip content checks)
    python tests/benchmark.py --latency-only

Exit codes:
    0 — all checks passed (or within acceptable thresholds)
    1 — one or more checks failed (CI gate: fail the build)

Scorecard format:
    {
      "run_id": "...",
      "timestamp": "...",
      "version": "7.0.0",
      "summary": {"total": N, "passed": N, "failed": N, "skipped": N, "score": 0.0-1.0},
      "latency": {"p50_ms": ..., "p95_ms": ..., "p99_ms": ...},
      "results": [...]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "phase3-agents"))
sys.path.insert(0, str(_ROOT / "phase3-agents" / "tools"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

_GOLDEN_PATH = Path(__file__).parent / "golden_prompts.json"


def _load_prompts(category: str | None = None, prompt_id: str | None = None) -> list[dict]:
    data = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    prompts = data["prompts"]
    if category:
        prompts = [p for p in prompts if p["category"] == category]
    if prompt_id:
        prompts = [p for p in prompts if p["id"] == prompt_id]
    return prompts


def _run_prompt(prompt_def: dict, latency_only: bool = False) -> dict:
    """Run a single benchmark prompt and return a result dict."""
    prompt_id = prompt_def["id"]
    text = prompt_def["prompt"]
    max_latency = prompt_def.get("max_latency_ms", 60000)

    result = {
        "id": prompt_id,
        "category": prompt_def["category"],
        "prompt": text[:80],
        "routing_expected": prompt_def.get("routing", "either"),
        "latency_ms": None,
        "passed": False,
        "failures": [],
        "response_preview": "",
        "error": None,
    }

    try:
        from mithrandir_agent import run_agent
    except Exception as e:
        result["error"] = f"Could not import mithrandir_agent: {e}"
        result["failures"].append("import_error")
        return result

    t0 = time.monotonic()
    try:
        response = run_agent(text, save_memory=False)
    except Exception as e:
        result["latency_ms"] = (time.monotonic() - t0) * 1000
        result["error"] = str(e)
        result["failures"].append("agent_exception")
        return result

    latency_ms = (time.monotonic() - t0) * 1000
    result["latency_ms"] = round(latency_ms, 1)
    result["response_preview"] = response[:200] if response else ""

    failures = []

    # Latency check
    if latency_ms > max_latency:
        failures.append(f"latency_exceeded: {latency_ms:.0f}ms > {max_latency}ms")

    if not latency_only and response:
        resp_lower = response.lower()

        # must_contain — ALL must appear
        for phrase in prompt_def.get("must_contain", []):
            if phrase.lower() not in resp_lower:
                failures.append(f"missing_required: '{phrase}'")

        # must_contain_any — at least one must appear
        any_phrases = prompt_def.get("must_contain_any", [])
        if any_phrases and not any(p.lower() in resp_lower for p in any_phrases):
            failures.append(f"missing_any_of: {any_phrases}")

        # must_not_contain — none may appear
        for phrase in prompt_def.get("must_not_contain", []):
            if phrase.lower() in resp_lower:
                failures.append(f"forbidden_phrase: '{phrase}'")

    result["failures"] = failures
    result["passed"] = len(failures) == 0
    return result


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * p / 100)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def run_benchmark(
    category: str | None = None,
    prompt_id: str | None = None,
    latency_only: bool = False,
    fail_fast: bool = False,
    as_json: bool = False,
) -> int:
    """Run the full benchmark. Returns exit code (0=pass, 1=fail)."""
    prompts = _load_prompts(category, prompt_id)
    if not prompts:
        print("No prompts matched the filter.")
        return 1

    run_id = str(uuid.uuid4())[:8]
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = []
    latencies = []

    colors = {
        "pass":  "\033[32m",
        "fail":  "\033[31m",
        "skip":  "\033[90m",
        "reset": "\033[0m",
    }

    if not as_json:
        print(f"\n  Mithrandir Benchmark  run={run_id}  {timestamp}")
        print("  " + "─" * 60)

    for i, p in enumerate(prompts):
        if not as_json:
            print(f"  [{i+1}/{len(prompts)}] {p['id']:<30} ", end="", flush=True)

        result = _run_prompt(p, latency_only=latency_only)
        results.append(result)

        if result["latency_ms"] is not None:
            latencies.append(result["latency_ms"])

        if not as_json:
            if result["error"]:
                print(f"{colors['fail']}ERROR{colors['reset']}  {result['error'][:60]}")
            elif result["passed"]:
                lat = f"{result['latency_ms']:.0f}ms" if result["latency_ms"] else "?"
                print(f"{colors['pass']}PASS{colors['reset']}   {lat}")
            else:
                lat = f"{result['latency_ms']:.0f}ms" if result["latency_ms"] else "?"
                print(f"{colors['fail']}FAIL{colors['reset']}   {lat}")
                for f in result["failures"]:
                    print(f"             {colors['fail']}→ {f}{colors['reset']}")
                if result.get("response_preview"):
                    print(f"             Response: {result['response_preview'][:100]}")

        if fail_fast and not result["passed"]:
            if not as_json:
                print("\n  Fail-fast: stopping on first failure.")
            break

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"] and not r.get("error"))
    errors = sum(1 for r in results if r.get("error"))
    total = len(results)
    score = round(passed / total, 3) if total else 0.0

    scorecard = {
        "run_id": run_id,
        "timestamp": timestamp,
        "version": "7.0.0",
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "score": score,
        },
        "latency": {
            "p50_ms": round(_percentile(latencies, 50), 1),
            "p95_ms": round(_percentile(latencies, 95), 1),
            "p99_ms": round(_percentile(latencies, 99), 1),
            "max_ms": round(max(latencies), 1) if latencies else 0,
        },
        "results": results,
    }

    # Save scorecard to disk for trendline tracking
    scores_dir = _ROOT / "tests" / "scorecards"
    scores_dir.mkdir(exist_ok=True)
    scorecard_path = scores_dir / f"scorecard_{run_id}_{timestamp.replace(':', '-')}.json"
    scorecard_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

    if as_json:
        print(json.dumps(scorecard, indent=2))
    else:
        print(f"\n  Results: {passed}/{total} passed  score={score:.1%}")
        print(f"  Latency: p50={scorecard['latency']['p50_ms']:.0f}ms  p95={scorecard['latency']['p95_ms']:.0f}ms")
        print(f"  Scorecard saved: {scorecard_path.name}\n")

        if score < 1.0:
            print(f"  {colors['fail']}✗ {failed + errors} test(s) failed.{colors['reset']}\n")
        else:
            print(f"  {colors['pass']}✓ All tests passed.{colors['reset']}\n")

    # CI gate: fail if score < 0.85 (allows 1 flaky test in a 15-prompt suite)
    return 0 if score >= 0.85 else 1


def show_trendline(n: int = 10):
    """Print the last n scorecard summaries as a trendline table."""
    scores_dir = _ROOT / "tests" / "scorecards"
    if not scores_dir.exists():
        print("No scorecards yet.")
        return
    files = sorted(scores_dir.glob("scorecard_*.json"), reverse=True)[:n]
    if not files:
        print("No scorecards yet.")
        return
    print(f"\n  Mithrandir Score Trendline (last {len(files)} runs)")
    print("  " + "─" * 60)
    print(f"  {'Timestamp':<22} {'Score':>7} {'Pass':>5} {'Total':>6} {'p50ms':>7} {'p95ms':>7}")
    for f in reversed(files):
        try:
            sc = json.loads(f.read_text(encoding="utf-8"))
            ts = sc.get("timestamp", "?")[:19]
            s = sc["summary"]
            l = sc["latency"]
            bar = "█" * int(s["score"] * 10)
            print(f"  {ts:<22} {s['score']:>6.1%} {s['passed']:>5} {s['total']:>6} {l['p50_ms']:>6.0f} {l['p95_ms']:>6.0f}  {bar}")
        except Exception:
            continue
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mithrandir benchmark runner")
    parser.add_argument("--category", help="Filter by category (routing, identity, tool_use, ...)")
    parser.add_argument("--id", dest="prompt_id", help="Run a single prompt by ID")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output JSON scorecard")
    parser.add_argument("--latency-only", action="store_true", help="Skip content checks, measure latency only")
    parser.add_argument("--trendline", action="store_true", help="Show score trendline and exit")
    args = parser.parse_args()

    if args.trendline:
        show_trendline()
        sys.exit(0)

    exit_code = run_benchmark(
        category=args.category,
        prompt_id=args.prompt_id,
        latency_only=args.latency_only,
        fail_fast=args.fail_fast,
        as_json=args.as_json,
    )
    sys.exit(exit_code)
