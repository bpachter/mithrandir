"""
scripts/start.py — One-command Enkidu launcher with readiness checks.

Starts:
  1. FastAPI backend (phase6-ui/server/main.py)
  2. React dev server (phase6-ui/client) — or skips if dist/ exists
  3. Runs a readiness probe loop until the backend is healthy
  4. Prints the URLs and optionally opens the browser

Usage:
    python scripts/start.py               # start everything
    python scripts/start.py --no-browser  # don't auto-open browser
    python scripts/start.py --backend-only  # skip React dev server
    python scripts/start.py --port 8080   # use a different port

Environment:
    Reads .env from the project root.
    ENKIDU_FORCE_LOCAL_ONLY=1 skips Ollama availability warning.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_procs: list[subprocess.Popen] = []


def _cleanup(*_):
    print(f"\n  {YELLOW}Shutting down Enkidu...{RESET}")
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    print(f"  {GREEN}Done.{RESET}\n")
    sys.exit(0)


def _wait_ready(url: str, label: str, timeout: float = 60.0) -> bool:
    """Poll url until it returns 200 or timeout."""
    import urllib.request
    import urllib.error
    t0 = time.monotonic()
    dots = 0
    while time.monotonic() - t0 < timeout:
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            if resp.status == 200:
                elapsed = (time.monotonic() - t0)
                print(f"\r  {GREEN}✓{RESET}  {label} ready ({elapsed:.1f}s)        ")
                return True
        except Exception:
            pass
        print(f"\r  {CYAN}…{RESET}  Waiting for {label}{'.' * (dots % 4)}   ", end="", flush=True)
        dots += 1
        time.sleep(1.0)
    print(f"\r  {RED}✗{RESET}  {label} did not become ready after {timeout:.0f}s")
    return False


def _start_backend(port: int) -> subprocess.Popen:
    server_dir = _ROOT / "phase6-ui" / "server"
    python = sys.executable
    cmd = [python, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)]
    print(f"  {CYAN}→{RESET}  Starting backend on port {port}...")
    p = subprocess.Popen(
        cmd,
        cwd=str(server_dir),
        # Log to file — don't clutter the terminal
        stdout=open(server_dir / "server.log", "a", encoding="utf-8"),
        stderr=open(server_dir / "stderr.log", "a", encoding="utf-8"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    return p


def _start_frontend(dev: bool) -> subprocess.Popen | None:
    client_dir = _ROOT / "phase6-ui" / "client"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if not (client_dir / "node_modules").exists():
        print(f"  {YELLOW}⚠{RESET}  node_modules missing — run: cd phase6-ui/client && npm install")
        return None
    print(f"  {CYAN}→{RESET}  Starting React dev server on port 5173...")
    p = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=str(client_dir),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    return p


def _pre_flight():
    """Quick readiness advisory before starting (non-blocking)."""
    print(f"\n  {BOLD}Pre-flight checks{RESET}")
    import urllib.request
    import urllib.error
    # Ollama
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=3)
        print(f"  {GREEN}✓{RESET}  Ollama reachable at {ollama_url}")
    except Exception:
        print(f"  {YELLOW}⚠{RESET}  Ollama not reachable at {ollama_url} — will use Claude fallback")
    # API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-..."):
        print(f"  {RED}✗{RESET}  ANTHROPIC_API_KEY not set — cloud routing disabled")
    else:
        print(f"  {GREEN}✓{RESET}  ANTHROPIC_API_KEY configured")


def main():
    parser = argparse.ArgumentParser(description="Start Enkidu")
    parser.add_argument("--port", type=int, default=8000, help="Backend port (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--backend-only", action="store_true", help="Skip React dev server")
    parser.add_argument("--health-check", action="store_true", help="Run health check before starting")
    args = parser.parse_args()

    # Load .env
    from pathlib import Path as _P
    env_path = _ROOT / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)

    signal.signal(signal.SIGINT,  _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    print(f"\n{BOLD}{CYAN}  Enkidu{RESET}  Starting up…\n")

    if args.health_check:
        print(f"  Running health check...\n")
        code = subprocess.call([sys.executable, str(_ROOT / "enkidu_health.py")])
        if code != 0:
            print(f"\n  {YELLOW}Health check found issues. Continue anyway? {RESET}", end="")
            if input("[y/N] ").strip().lower() not in ("y", "yes"):
                sys.exit(1)

    _pre_flight()

    print(f"\n  {BOLD}Starting services{RESET}")

    # Backend
    backend = _start_backend(args.port)
    _procs.append(backend)

    # Frontend (skip if dist/ exists and user didn't explicitly request dev)
    dist_dir = _ROOT / "phase6-ui" / "client" / "dist"
    if not args.backend_only:
        frontend = _start_frontend(dev=True)
        if frontend:
            _procs.append(frontend)

    # Readiness probe
    print()
    backend_ready = _wait_ready(f"http://localhost:{args.port}/api/health", "Backend", timeout=60)

    if not backend_ready:
        print(f"\n  {RED}Backend failed to start.{RESET}")
        print(f"  Check logs: phase6-ui/server/server.log")
        _cleanup()
        sys.exit(1)

    frontend_url = "http://localhost:5173" if not args.backend_only else f"http://localhost:{args.port}"
    if not args.backend_only:
        _wait_ready("http://localhost:5173", "Frontend", timeout=30)

    # First-run UX
    print(f"""
  ┌─────────────────────────────────────────────────────┐
  │  Enkidu is ready                                    │
  │                                                     │
  │  UI:      {frontend_url:<41} │
  │  Backend: http://localhost:{args.port}/api/health{' ' * (14 - len(str(args.port)))} │
  │  Docs:    http://localhost:{args.port}/docs{' ' * (19 - len(str(args.port)))} │
  │                                                     │
  │  Try: "What can you do?"  or  "Show me the top 5   │
  │        undervalued stocks" or click the mic icon.  │
  │                                                     │
  │  Ctrl+C to stop.                                   │
  └─────────────────────────────────────────────────────┘
""")

    # Auto-open browser
    if not args.no_browser:
        try:
            import webbrowser
            webbrowser.open(frontend_url)
        except Exception:
            pass

    # Keep running — wait for processes
    try:
        while True:
            for p in _procs:
                if p.poll() is not None:
                    print(f"\n  {RED}✗{RESET}  A process exited unexpectedly (code {p.returncode})")
                    print(f"  Check logs in phase6-ui/server/")
            time.sleep(2)
    except KeyboardInterrupt:
        _cleanup()


if __name__ == "__main__":
    main()
