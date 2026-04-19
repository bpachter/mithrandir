"""
tests/test_health.py — Fast unit tests for enkidu_health checks.

These tests do NOT call LLMs or external services. They verify:
  - Health check module imports cleanly
  - Each check returns a properly-typed HealthResult
  - The summary aggregation is correct
  - run_all() doesn't raise exceptions

Run with: python -m pytest tests/test_health.py -v
  or:      python tests/test_health.py
"""

import sys
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import enkidu_health as health


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def test_result_type():
    r = health.HealthResult(name="test", status="ok", detail="works")
    d = r.to_dict()
    _assert(d["name"] == "test", "name mismatch")
    _assert(d["status"] == "ok", "status mismatch")
    _assert("latency_ms" in d, "latency_ms missing from dict")


def test_summary_all_ok():
    results = [
        health.HealthResult("a", "ok"),
        health.HealthResult("b", "ok"),
        health.HealthResult("c", "ok"),
    ]
    s = health.summary(results)
    _assert(s["overall"] == "ok", f"expected ok, got {s['overall']}")
    _assert(s["counts"]["ok"] == 3, "ok count wrong")
    _assert(s["critical_failures"] == 0, "should have 0 critical failures")


def test_summary_critical_fail():
    results = [
        health.HealthResult("env", "fail", critical=True),
        health.HealthResult("ollama", "ok"),
    ]
    s = health.summary(results)
    _assert(s["overall"] == "fail", f"expected fail, got {s['overall']}")
    _assert(s["critical_failures"] == 1, "should have 1 critical failure")


def test_summary_warn_only():
    results = [
        health.HealthResult("memory", "warn", critical=False),
        health.HealthResult("env", "ok"),
    ]
    s = health.summary(results)
    _assert(s["overall"] == "warn", f"expected warn, got {s['overall']}")
    _assert(s["critical_failures"] == 0, "no critical failures expected")


def test_check_env_mock(monkeypatch=None):
    """check_env should fail when ANTHROPIC_API_KEY is placeholder."""
    import os
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."
    try:
        r = health.check_env()
        _assert(r.status == "fail", f"expected fail for placeholder key, got {r.status}")
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old
        elif "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]


def test_run_all_returns_list():
    """run_all() must return a list of HealthResult objects without raising."""
    results = health.run_all(parallel=True, timeout=25.0)
    _assert(isinstance(results, list), "run_all must return a list")
    _assert(len(results) == len(health._ALL_CHECKS), "result count must match check count")
    for r in results:
        _assert(isinstance(r, health.HealthResult), f"expected HealthResult, got {type(r)}")
        _assert(r.status in ("ok", "warn", "fail", "skip"), f"invalid status: {r.status}")


def test_summary_json_serializable():
    results = health.run_all(parallel=True, timeout=25.0)
    s = health.summary(results)
    blob = json.dumps(s)
    _assert(isinstance(blob, str), "summary must be JSON-serializable")


_TESTS = [
    test_result_type,
    test_summary_all_ok,
    test_summary_critical_fail,
    test_summary_warn_only,
    test_check_env_mock,
    test_run_all_returns_list,
    test_summary_json_serializable,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"  \033[32m✓\033[0m {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  \033[31m✗\033[0m {fn.__name__}: {e}")
            failed += 1
    print(f"\n  {passed}/{len(_TESTS)} passed\n")
    sys.exit(0 if failed == 0 else 1)
