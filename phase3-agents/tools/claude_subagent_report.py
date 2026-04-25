"""Generate a delegation audit summary from claude_subagent JSONL events.

Usage:
  python phase3-agents/tools/claude_subagent_report.py
  python phase3-agents/tools/claude_subagent_report.py --window 7d
  python phase3-agents/tools/claude_subagent_report.py --window all --json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def _default_log_path() -> Path:
    here = Path(__file__).resolve()
    # phase3-agents/tools -> phase3-agents/claude_subagent_audit.jsonl
    default = here.parent.parent / "claude_subagent_audit.jsonl"
    configured = os.environ.get("MITHRANDIR_CLAUDE_SUBAGENT_AUDIT_LOG", "").strip()
    return Path(configured) if configured else default


def _window_to_seconds(window: str) -> int:
    w = (window or "24h").strip().lower()
    if w == "all":
        return 10 * 365 * 24 * 3600

    if len(w) < 2:
        raise ValueError("window must look like 60m, 24h, 7d, or all")

    n = int(w[:-1])
    unit = w[-1]
    if unit == "s":
        return n
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 24 * 3600
    raise ValueError("window unit must be one of s/m/h/d or all")


def build_summary(log_path: Path, window_seconds: int) -> dict:
    now = time.time()
    cutoff = now - window_seconds

    total = 0
    allowed = 0
    blocked = 0
    errors = 0
    reasons: dict[str, int] = {}
    models: dict[str, int] = {}

    if not log_path.exists():
        return {
            "log": str(log_path),
            "window_seconds": window_seconds,
            "events": 0,
            "allowed": 0,
            "blocked": 0,
            "errors": 0,
            "allowed_pct": 0.0,
            "blocked_pct": 0.0,
            "reasons": {},
            "models": {},
            "note": "log_not_found",
        }

    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue

            ts = float(evt.get("ts", 0.0) or 0.0)
            if ts and ts < cutoff:
                continue

            total += 1
            if bool(evt.get("allowed", False)):
                allowed += 1
            else:
                blocked += 1

            if evt.get("error"):
                errors += 1

            reason = str(evt.get("reason", "unknown"))
            reasons[reason] = reasons.get(reason, 0) + 1

            model = str(evt.get("model", ""))
            if model:
                models[model] = models.get(model, 0) + 1

    return {
        "log": str(log_path),
        "window_seconds": window_seconds,
        "events": total,
        "allowed": allowed,
        "blocked": blocked,
        "errors": errors,
        "allowed_pct": round((100.0 * allowed / total), 2) if total else 0.0,
        "blocked_pct": round((100.0 * blocked / total), 2) if total else 0.0,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)),
        "models": dict(sorted(models.items(), key=lambda kv: kv[1], reverse=True)),
    }


def print_human(summary: dict) -> None:
    print("Claude Subagent Delegation Report")
    print(f"  Log: {summary['log']}")
    print(f"  Window: {summary['window_seconds']}s")
    print(f"  Events: {summary['events']}")
    print(f"  Allowed: {summary['allowed']} ({summary['allowed_pct']}%)")
    print(f"  Blocked: {summary['blocked']} ({summary['blocked_pct']}%)")
    print(f"  Errors: {summary['errors']}")

    reasons = summary.get("reasons", {})
    if reasons:
        print("  Top reasons:")
        for reason, count in list(reasons.items())[:8]:
            print(f"    - {reason}: {count}")

    models = summary.get("models", {})
    if models:
        print("  Models:")
        for model, count in list(models.items())[:4]:
            print(f"    - {model}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize claude_subagent audit log")
    parser.add_argument("--window", default="24h", help="Window like 60m, 24h, 7d, or all")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human text")
    args = parser.parse_args()

    seconds = _window_to_seconds(args.window)
    summary = build_summary(_default_log_path(), seconds)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_human(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
