"""
mithrandir_health.py — Unified health checker for all Mithrandir subsystems.

Checks:
  - Ollama (local inference)
  - Memory bridge (ChromaDB / SQLite)
  - Voice workers (Whisper STT, TTS chain)
  - FastAPI server (web socket + REST)
  - Telegram bot token validity
  - Environment / API keys
  - QV data freshness

Each check returns a HealthResult with status, latency, and optional fix hint.
Used by:
  - `python mithrandir_check.py`           (startup self-test CLI)
  - GET /api/health/detailed            (FastAPI endpoint)
  - CI benchmark suite                 (non-zero exit on critical failure)

Exit codes when run as __main__:
  0 — all critical checks pass
  1 — one or more critical checks failed
"""

from __future__ import annotations

import os
import sys
import time
import json
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env", override=True)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class HealthResult:
    name: str
    status: str        # "ok" | "warn" | "fail" | "skip"
    latency_ms: Optional[float] = None
    detail: str = ""
    fix: str = ""
    critical: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "detail": self.detail,
            "fix": self.fix,
            "critical": self.critical,
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_env() -> HealthResult:
    """Verify required environment variables are set."""
    required = ["ANTHROPIC_API_KEY"]
    optional_warn = ["TELEGRAM_BOT_TOKEN", "TAVILY_API_KEY"]
    missing_required = [k for k in required if not os.environ.get(k, "").strip() or os.environ[k].startswith("sk-ant-...")]
    missing_optional = [k for k in optional_warn if not os.environ.get(k, "").strip() or os.environ[k].startswith("<")]

    if missing_required:
        return HealthResult(
            name="env",
            status="fail",
            detail=f"Missing required env vars: {', '.join(missing_required)}",
            fix="Copy .env.example → .env and fill in ANTHROPIC_API_KEY",
        )
    if missing_optional:
        return HealthResult(
            name="env",
            status="warn",
            detail=f"Optional env vars not set: {', '.join(missing_optional)}",
            fix="Set these in .env to enable Telegram and web search",
            critical=False,
        )
    return HealthResult(name="env", status="ok", detail="All required env vars present")


def check_ollama() -> HealthResult:
    """Ping Ollama API and verify the configured model is loaded."""
    import requests
    url = os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
    t0 = time.monotonic()
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        latency = (time.monotonic() - t0) * 1000
        if r.status_code != 200:
            return HealthResult(
                name="ollama",
                status="fail",
                latency_ms=latency,
                detail=f"HTTP {r.status_code} from {url}/api/tags",
                fix="Run: docker compose up -d (phase1-local-inference/) or start Ollama",
            )
        tags = r.json().get("models", [])
        model_names = [m.get("name", "") for m in tags]
        if not any(model in n for n in model_names):
            return HealthResult(
                name="ollama",
                status="warn",
                latency_ms=latency,
                detail=f"Ollama running but model '{model}' not found. Available: {model_names[:3]}",
                fix=f"Run: ollama pull {model}",
                critical=False,
            )
        return HealthResult(name="ollama", status="ok", latency_ms=latency, detail=f"Model '{model}' loaded")
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="ollama",
            status="fail",
            latency_ms=latency,
            detail=f"Cannot reach Ollama at {url}: {e}",
            fix="Start Docker Desktop and run: docker compose up -d",
            critical=False,  # Claude fallback exists
        )


def check_anthropic_api() -> HealthResult:
    """Verify the Anthropic API key by listing models (no tokens consumed)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-..."):
        return HealthResult(
            name="anthropic_api",
            status="fail",
            detail="ANTHROPIC_API_KEY not set",
            fix="Add ANTHROPIC_API_KEY to .env",
        )
    import requests
    t0 = time.monotonic()
    try:
        r = requests.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=10,
        )
        latency = (time.monotonic() - t0) * 1000
        if r.status_code == 401:
            return HealthResult(
                name="anthropic_api",
                status="fail",
                latency_ms=latency,
                detail="API key rejected (401 Unauthorized)",
                fix="Update ANTHROPIC_API_KEY in .env with a valid key",
            )
        if r.status_code == 200:
            return HealthResult(name="anthropic_api", status="ok", latency_ms=latency, detail="API key valid")
        return HealthResult(
            name="anthropic_api",
            status="warn",
            latency_ms=latency,
            detail=f"Unexpected HTTP {r.status_code}",
            fix="Check Anthropic service status",
            critical=False,
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="anthropic_api",
            status="warn",
            latency_ms=latency,
            detail=f"Network error: {e}",
            fix="Check internet connectivity",
            critical=False,
        )


def check_memory_bridge() -> HealthResult:
    """Test the phase4 memory bridge (ChromaDB subprocess)."""
    phase4_python = _ROOT / "phase4-memory" / ".venv" / "Scripts" / "python.exe"
    memory_bridge = _ROOT / "phase4-memory" / "memory_bridge.py"
    if not phase4_python.exists():
        return HealthResult(
            name="memory_bridge",
            status="warn",
            detail="phase4 venv not found — memory disabled",
            fix="cd phase4-memory && python -m venv .venv && .venv\\Scripts\\pip install chromadb",
            critical=False,
        )
    if not memory_bridge.exists():
        return HealthResult(
            name="memory_bridge",
            status="fail",
            detail="memory_bridge.py not found",
            fix="Check phase4-memory/ directory",
        )
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [str(phase4_python), str(memory_bridge), "ping"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        latency = (time.monotonic() - t0) * 1000
        if result.returncode == 0:
            return HealthResult(name="memory_bridge", status="ok", latency_ms=latency, detail="Memory bridge responsive")
        # Try retrieve as fallback ping
        result2 = subprocess.run(
            [str(phase4_python), str(memory_bridge), "retrieve", "health check"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        latency = (time.monotonic() - t0) * 1000
        if "error" not in result2.stdout.lower() and "traceback" not in result2.stderr.lower():
            return HealthResult(name="memory_bridge", status="ok", latency_ms=latency, detail="Memory bridge responsive")
        return HealthResult(
            name="memory_bridge",
            status="warn",
            latency_ms=latency,
            detail=f"Bridge returned error: {(result2.stderr or result2.stdout)[:200]}",
            fix="Check phase4-memory/.venv and chromadb installation",
            critical=False,
        )
    except subprocess.TimeoutExpired:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="memory_bridge",
            status="warn",
            latency_ms=latency,
            detail="Memory bridge timed out after 15s",
            fix="ChromaDB may be rebuilding index. Retry in 30s.",
            critical=False,
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="memory_bridge",
            status="warn",
            latency_ms=latency,
            detail=f"Memory bridge error: {e}",
            fix="Check phase4-memory/ setup",
            critical=False,
        )


def check_fastapi_server() -> HealthResult:
    """Check if the FastAPI backend is running and responsive."""
    import requests
    t0 = time.monotonic()
    try:
        r = requests.get("http://localhost:8000/api/health", timeout=5)
        latency = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            data = r.json()
            return HealthResult(
                name="fastapi_server",
                status="ok",
                latency_ms=latency,
                detail=f"Backend running (v{data.get('version', '?')})",
                critical=False,
            )
        return HealthResult(
            name="fastapi_server",
            status="warn",
            latency_ms=latency,
            detail=f"HTTP {r.status_code}",
            fix="Restart: cd phase6-ui && start_ui.bat",
            critical=False,
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="fastapi_server",
            status="warn",
            latency_ms=latency,
            detail="Backend not running",
            fix="Start with: phase6-ui\\start_ui.bat",
            critical=False,
        )


def check_voice_workers() -> HealthResult:
    """Verify voice dependencies: faster-whisper and at least one TTS engine."""
    issues = []
    # Check faster-whisper
    try:
        import importlib
        importlib.import_module("faster_whisper")
    except ImportError:
        issues.append("faster-whisper not installed (STT unavailable)")

    # Check TTS options
    tts_available = []
    for pkg, label in [("kokoro", "Kokoro"), ("edge_tts", "edge-tts"), ("pyttsx3", "pyttsx3")]:
        try:
            import importlib
            importlib.import_module(pkg)
            tts_available.append(label)
        except ImportError:
            pass

    # Check F5-TTS worker script
    f5_worker = _ROOT / "phase6-ui" / "server" / "f5tts_worker.py"
    if f5_worker.exists():
        tts_available.insert(0, "F5-TTS")

    if issues and not tts_available:
        return HealthResult(
            name="voice_workers",
            status="fail",
            detail=f"Voice unavailable: {'; '.join(issues)}",
            fix="pip install faster-whisper kokoro edge-tts",
            critical=False,
        )
    if issues:
        return HealthResult(
            name="voice_workers",
            status="warn",
            detail=f"Partial voice: {'; '.join(issues)}. TTS via: {', '.join(tts_available)}",
            fix="pip install faster-whisper",
            critical=False,
        )
    if not tts_available:
        return HealthResult(
            name="voice_workers",
            status="warn",
            detail="No TTS engine found",
            fix="pip install kokoro edge-tts",
            critical=False,
        )
    return HealthResult(
        name="voice_workers",
        status="ok",
        detail=f"TTS engines available: {', '.join(tts_available)}",
        critical=False,
    )


def check_telegram() -> HealthResult:
    """Verify Telegram bot token is set and reachable."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or token.startswith("<"):
        return HealthResult(
            name="telegram",
            status="skip",
            detail="TELEGRAM_BOT_TOKEN not configured",
            fix="Set TELEGRAM_BOT_TOKEN in .env",
            critical=False,
        )
    import requests
    t0 = time.monotonic()
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        latency = (time.monotonic() - t0) * 1000
        if r.status_code == 200 and r.json().get("ok"):
            bot_name = r.json().get("result", {}).get("username", "?")
            return HealthResult(
                name="telegram",
                status="ok",
                latency_ms=latency,
                detail=f"Bot @{bot_name} verified",
                critical=False,
            )
        return HealthResult(
            name="telegram",
            status="fail",
            latency_ms=latency,
            detail=f"Token rejected: {r.text[:100]}",
            fix="Update TELEGRAM_BOT_TOKEN in .env",
            critical=False,
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return HealthResult(
            name="telegram",
            status="warn",
            latency_ms=latency,
            detail=f"Cannot reach Telegram API: {e}",
            fix="Check internet connectivity",
            critical=False,
        )


def check_qv_data() -> HealthResult:
    """Check QV portfolio data freshness."""
    qv_path = os.environ.get("QV_PATH", "")
    if not qv_path:
        return HealthResult(
            name="qv_data",
            status="skip",
            detail="QV_PATH not configured",
            fix="Set QV_PATH in .env to enable financial screener",
            critical=False,
        )
    csv_path = Path(qv_path) / "data" / "processed" / "quantitative_value_portfolio.csv"
    if not csv_path.exists():
        return HealthResult(
            name="qv_data",
            status="warn",
            detail=f"Portfolio CSV not found: {csv_path}",
            fix="Run the QV screener: python phase2-tool-use/quant-value/src/run_all.py",
            critical=False,
        )
    age_hours = (time.time() - csv_path.stat().st_mtime) / 3600
    if age_hours > 72:
        return HealthResult(
            name="qv_data",
            status="warn",
            detail=f"Portfolio CSV is {age_hours:.0f}h old (>72h)",
            fix="Run daily refresh or: python phase2-tool-use/quant-value/src/run_all.py",
            critical=False,
        )
    return HealthResult(
        name="qv_data",
        status="ok",
        detail=f"Portfolio CSV updated {age_hours:.1f}h ago",
        critical=False,
    )


def check_python_deps() -> HealthResult:
    """Verify core Python packages are installed."""
    required = [
        ("anthropic", "pip install anthropic"),
        ("dotenv", "pip install python-dotenv"),
        ("requests", "pip install requests"),
        ("psutil", "pip install psutil"),
        ("pydantic", "pip install pydantic"),
        ("fastapi", "pip install fastapi"),
        ("uvicorn", "pip install uvicorn[standard]"),
    ]
    missing = []
    for pkg, hint in required:
        try:
            import importlib
            importlib.import_module(pkg)
        except ImportError:
            missing.append((pkg, hint))
    if missing:
        pkgs = ", ".join(p for p, _ in missing)
        fix = "; ".join(f for _, f in missing[:3])
        return HealthResult(
            name="python_deps",
            status="fail",
            detail=f"Missing packages: {pkgs}",
            fix=fix,
        )
    return HealthResult(name="python_deps", status="ok", detail="Core packages installed")


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

_ALL_CHECKS = [
    check_env,
    check_python_deps,
    check_anthropic_api,
    check_ollama,
    check_memory_bridge,
    check_fastapi_server,
    check_voice_workers,
    check_telegram,
    check_qv_data,
]


def run_all(parallel: bool = True, timeout: float = 30.0) -> list[HealthResult]:
    """Run all health checks, optionally in parallel. Returns sorted results."""
    results: list[HealthResult] = [None] * len(_ALL_CHECKS)

    if parallel:
        def _run(i, fn):
            try:
                results[i] = fn()
            except Exception as e:
                results[i] = HealthResult(
                    name=fn.__name__.replace("check_", ""),
                    status="fail",
                    detail=f"Check threw exception: {e}",
                    fix="Report this bug",
                )

        threads = [threading.Thread(target=_run, args=(i, fn)) for i, fn in enumerate(_ALL_CHECKS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout)
        # Replace None (timed out) with fail results
        for i, (r, fn) in enumerate(zip(results, _ALL_CHECKS)):
            if r is None:
                results[i] = HealthResult(
                    name=fn.__name__.replace("check_", ""),
                    status="warn",
                    detail="Check timed out",
                    fix="Subsystem may be unresponsive",
                    critical=False,
                )
    else:
        for i, fn in enumerate(_ALL_CHECKS):
            try:
                results[i] = fn()
            except Exception as e:
                results[i] = HealthResult(
                    name=fn.__name__.replace("check_", ""),
                    status="fail",
                    detail=f"Check threw exception: {e}",
                )

    # Sort: fail first, then warn, then ok/skip
    order = {"fail": 0, "warn": 1, "ok": 2, "skip": 3}
    return sorted(results, key=lambda r: order.get(r.status, 99))


def summary(results: list[HealthResult]) -> dict:
    """Aggregate results into a summary dict."""
    counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    critical_failures = [r for r in results if r.status == "fail" and r.critical]
    overall = "ok" if not critical_failures else "degraded" if not any(
        r.status == "fail" and r.critical for r in results
    ) else "fail"
    if critical_failures:
        overall = "fail"
    elif counts["warn"] > 0:
        overall = "warn"
    return {
        "overall": overall,
        "counts": counts,
        "critical_failures": len(critical_failures),
        "checks": [r.to_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mithrandir startup health check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--no-parallel", action="store_true", help="Run checks sequentially")
    parser.add_argument("--check", help="Run a single check by name (e.g. ollama, memory_bridge)")
    args = parser.parse_args()

    if args.check:
        name_map = {fn.__name__.replace("check_", ""): fn for fn in _ALL_CHECKS}
        fn = name_map.get(args.check)
        if not fn:
            print(f"Unknown check '{args.check}'. Options: {', '.join(name_map)}")
            sys.exit(1)
        results = [fn()]
    else:
        results = run_all(parallel=not args.no_parallel)

    if args.json:
        print(json.dumps(summary(results), indent=2))
        sys.exit(0 if not any(r.status == "fail" and r.critical for r in results) else 1)

    # Human-readable output
    icons = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "–"}
    colors = {
        "ok":   "\033[32m",   # green
        "warn": "\033[33m",   # yellow
        "fail": "\033[31m",   # red
        "skip": "\033[90m",   # gray
        "reset": "\033[0m",
    }

    print("\n  Mithrandir Health Check\n  " + "─" * 38)
    for r in results:
        icon = icons.get(r.status, "?")
        color = colors.get(r.status, "")
        reset = colors["reset"]
        lat = f"  ({r.latency_ms:.0f}ms)" if r.latency_ms is not None else ""
        print(f"  {color}{icon}{reset} {r.name:<22} {r.detail}{lat}")
        if r.status in ("fail", "warn") and r.fix:
            print(f"    {colors['skip']}→ {r.fix}{reset}")

    s = summary(results)
    print(f"\n  {s['counts']['ok']} ok  {s['counts']['warn']} warn  {s['counts']['fail']} fail  {s['counts']['skip']} skip\n")

    if s["critical_failures"] > 0:
        print(f"  {colors['fail']}✗ {s['critical_failures']} critical failure(s) — Mithrandir may not start correctly.{colors['reset']}\n")
        sys.exit(1)
    elif s["counts"]["fail"] + s["counts"]["warn"] > 0:
        print(f"  {colors['warn']}⚠ Some optional subsystems are degraded. Core features work.{colors['reset']}\n")
        sys.exit(0)
    else:
        print(f"  {colors['ok']}✓ All systems nominal.{colors['reset']}\n")
        sys.exit(0)
