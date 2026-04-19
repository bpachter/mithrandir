"""
scripts/bootstrap.py — Enkidu guided setup for Windows.

Checks and fixes the environment step by step so a fresh machine can
reach "first message" in under 30 minutes. Run once before first launch.

Usage:
    python scripts/bootstrap.py              # interactive guided setup
    python scripts/bootstrap.py --check      # check-only, no installs
    python scripts/bootstrap.py --yes        # auto-confirm all prompts
    python scripts/bootstrap.py --skip-ollama  # skip Docker/Ollama setup
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent

# ── Terminal colors ───────────────────────────────────────────────────────────
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {CYAN}→{RESET}  {msg}")
def note(msg):  print(f"     {GRAY}{msg}{RESET}")
def header(msg): print(f"\n{BOLD}{CYAN}  {msg}{RESET}\n  {'─' * 50}")


def _ask(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        print(f"  {GRAY}(auto-yes){RESET} {prompt}")
        return True
    ans = input(f"  {CYAN}?{RESET}  {prompt} [y/N] ").strip().lower()
    return ans in ("y", "yes")


def _run(cmd: list[str], cwd: Path | None = None, capture: bool = True) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, cwd=cwd,
            capture_output=capture,
            text=True, encoding="utf-8", errors="replace",
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"
    except Exception as e:
        return 1, str(e)


# ── Step 1: Python version ────────────────────────────────────────────────────
def check_python(check_only: bool, auto_yes: bool) -> bool:
    header("Step 1 — Python version")
    ver = sys.version_info
    if ver < (3, 10):
        fail(f"Python {ver.major}.{ver.minor} detected — Enkidu requires Python 3.10+")
        info("Download Python 3.11+ from https://python.org/downloads")
        return False
    ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    return True


# ── Step 2: .env file ─────────────────────────────────────────────────────────
def check_env(check_only: bool, auto_yes: bool) -> bool:
    header("Step 2 — Environment configuration (.env)")
    env_path = _ROOT / ".env"
    example_path = _ROOT / ".env.example"

    if not env_path.exists():
        warn(".env not found")
        if not check_only and _ask("Copy .env.example → .env?", auto_yes):
            import shutil
            shutil.copy(example_path, env_path)
            ok(".env created from template")
            info("IMPORTANT: Edit .env and fill in ANTHROPIC_API_KEY before starting")
        else:
            fail("Cannot start without .env")
            return False

    # Parse .env
    env_vars = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    issues = []
    if not env_vars.get("ANTHROPIC_API_KEY") or env_vars.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-..."):
        issues.append("ANTHROPIC_API_KEY is not set — add your key from console.anthropic.com")
    if not env_vars.get("OLLAMA_HOST"):
        warn("OLLAMA_HOST not set — defaulting to http://localhost:11434")
    if env_vars.get("TELEGRAM_BOT_TOKEN", "").startswith("<"):
        note("TELEGRAM_BOT_TOKEN not configured — Telegram interface will be disabled")

    if issues:
        for i in issues:
            fail(i)
        info(f"Edit {env_path} to fix the above")
        if not check_only:
            input(f"\n  Press Enter after editing .env to continue... ")
        return False

    ok(".env configured")
    return True


# ── Step 3: Core Python packages ──────────────────────────────────────────────
def check_core_deps(check_only: bool, auto_yes: bool) -> bool:
    header("Step 3 — Core Python packages")
    required = [
        ("anthropic", "anthropic>=0.94.0"),
        ("dotenv", "python-dotenv"),
        ("requests", "requests"),
        ("psutil", "psutil"),
        ("pydantic", "pydantic>=2.0"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn[standard]"),
    ]
    missing = []
    for pkg, spec in required:
        try:
            __import__(pkg)
            ok(f"{spec}")
        except ImportError:
            warn(f"{spec} — NOT installed")
            missing.append(spec)

    if missing:
        if not check_only and _ask(f"Install {len(missing)} missing package(s)?", auto_yes):
            info(f"Running: pip install {' '.join(missing)}")
            code, out = _run([sys.executable, "-m", "pip", "install"] + missing)
            if code == 0:
                ok("Packages installed")
            else:
                fail(f"pip install failed:\n{out}")
                return False
        elif check_only:
            fail(f"{len(missing)} packages missing")
            return False

    ok("All core packages present")
    return True


# ── Step 4: UI packages (phase6) ──────────────────────────────────────────────
def check_ui_deps(check_only: bool, auto_yes: bool) -> bool:
    header("Step 4 — UI server packages")
    req_file = _ROOT / "phase6-ui" / "server" / "requirements.txt"
    if not req_file.exists():
        warn("phase6-ui/server/requirements.txt not found — skipping")
        return True

    missing_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True, text=True
    )
    # Just install from requirements.txt
    if not check_only and _ask("Install/update phase6-ui/server requirements?", auto_yes):
        code, out = _run([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
        if code == 0:
            ok("UI server packages installed")
        else:
            warn(f"Some UI packages failed (voice may be degraded):\n{out[:300]}")
    else:
        ok("Skipped UI packages (run manually if voice is broken)")
    return True


# ── Step 5: Node.js + npm (for React frontend) ────────────────────────────────
def check_node(check_only: bool, auto_yes: bool) -> bool:
    header("Step 5 — Node.js (React frontend)")
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        warn("Node.js / npm not found — UI client won't build")
        info("Install Node.js 18+ from https://nodejs.org")
        note("The React frontend can still be served from the pre-built dist/ folder.")
        return True  # non-critical — dist/ may already exist

    code, ver = _run(["node", "--version"])
    ok(f"Node.js {ver.strip()}")

    client_dir = _ROOT / "phase6-ui" / "client"
    if not (client_dir / "node_modules").exists():
        if not check_only and _ask("Run npm install in phase6-ui/client?", auto_yes):
            code, out = _run(["npm", "install"], cwd=client_dir, capture=False)
            if code != 0:
                warn("npm install returned non-zero — check output above")
        else:
            note("Skipped npm install — run manually: cd phase6-ui/client && npm install")
    else:
        ok("node_modules present")

    dist_dir = client_dir / "dist"
    if not dist_dir.exists():
        if not check_only and _ask("Build React frontend now (npm run build)?", auto_yes):
            code, out = _run(["npm", "run", "build"], cwd=client_dir, capture=False)
            if code == 0:
                ok("Frontend built to dist/")
            else:
                warn("Build failed — use dev server (npm run dev) instead")
        else:
            note("Skipped build — run: cd phase6-ui/client && npm run build")

    return True


# ── Step 6: Ollama / Docker ───────────────────────────────────────────────────
def check_ollama(check_only: bool, auto_yes: bool, skip: bool) -> bool:
    header("Step 6 — Ollama (local inference)")
    if skip:
        note("Skipped (--skip-ollama). Enkidu will use Claude cloud fallback.")
        return True

    import requests as req
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        r = req.get(f"{ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            ok(f"Ollama running at {ollama_url}")
            model = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
            if not any(model in m for m in models):
                warn(f"Model '{model}' not found. Available: {models[:3]}")
                if not check_only and _ask(f"Pull {model} now? (this downloads ~14 GB)", auto_yes):
                    info(f"Running: ollama pull {model}")
                    _run(["ollama", "pull", model], capture=False)
            else:
                ok(f"Model '{model}' ready")
            return True
    except Exception:
        pass

    warn(f"Ollama not reachable at {ollama_url}")
    docker = shutil.which("docker")
    if docker:
        if not check_only and _ask("Start Ollama via Docker Compose?", auto_yes):
            compose_dir = _ROOT / "phase1-local-inference"
            code, out = _run(["docker", "compose", "up", "-d"], cwd=compose_dir, capture=False)
            ok("Docker Compose started") if code == 0 else warn(f"docker compose failed: {out}")
    else:
        info("Install Docker Desktop: https://docker.com/products/docker-desktop")
        info("Then run: cd phase1-local-inference && docker compose up -d")
        note("Enkidu will fall back to Claude cloud API without local inference.")

    return True  # non-critical — Claude fallback exists


# ── Step 7: Memory bridge (phase4) ───────────────────────────────────────────
def check_memory(check_only: bool, auto_yes: bool) -> bool:
    header("Step 7 — Memory bridge (phase4 ChromaDB)")
    phase4 = _ROOT / "phase4-memory"
    venv_python = phase4 / ".venv" / "Scripts" / "python.exe"

    if not venv_python.exists():
        warn("phase4 venv not found — memory will be disabled")
        if not check_only and _ask("Create phase4 venv and install chromadb?", auto_yes):
            code, out = _run([sys.executable, "-m", "venv", ".venv"], cwd=phase4)
            if code != 0:
                fail(f"venv creation failed: {out}")
                return True  # non-critical

            info("Installing chromadb (this may take 2-3 minutes)...")
            code, out = _run(
                [str(venv_python), "-m", "pip", "install", "chromadb", "onnxruntime"],
                cwd=phase4, capture=False,
            )
            ok("chromadb installed") if code == 0 else warn(f"install failed: {out[:200]}")
        else:
            note("Memory disabled — conversations won't be remembered between sessions.")
    else:
        ok("phase4 venv present")

    return True


# ── Step 8: Run health check ──────────────────────────────────────────────────
def run_final_health():
    header("Step 8 — Final health check")
    code, out = _run([sys.executable, str(_ROOT / "enkidu_health.py"), "--no-parallel"])
    print(out)
    return code == 0


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Enkidu bootstrap setup for Windows")
    parser.add_argument("--check", action="store_true", help="Check only, no installs")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm all prompts")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip Docker/Ollama setup")
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}  Enkidu Bootstrap Setup{RESET}")
    print(f"  Python: {sys.executable}")
    print(f"  Root:   {_ROOT}")
    if args.check:
        print(f"  Mode:   check-only (no changes)\n")
    elif args.yes:
        print(f"  Mode:   auto-yes (unattended install)\n")

    steps = [
        ("python",    lambda: check_python(args.check, args.yes)),
        ("env",       lambda: check_env(args.check, args.yes)),
        ("core_deps", lambda: check_core_deps(args.check, args.yes)),
        ("ui_deps",   lambda: check_ui_deps(args.check, args.yes)),
        ("node",      lambda: check_node(args.check, args.yes)),
        ("ollama",    lambda: check_ollama(args.check, args.yes, args.skip_ollama)),
        ("memory",    lambda: check_memory(args.check, args.yes)),
    ]

    all_ok = True
    for name, fn in steps:
        try:
            if not fn():
                all_ok = False
        except KeyboardInterrupt:
            print(f"\n\n  {YELLOW}Setup interrupted.{RESET}\n")
            sys.exit(1)
        except Exception as e:
            warn(f"Step '{name}' raised an error: {e}")

    if not args.check:
        run_final_health()

    print(f"\n{'─' * 54}")
    if all_ok:
        print(f"\n  {GREEN}{BOLD}Setup complete!{RESET}")
        print(f"\n  Start Enkidu:  {CYAN}python scripts\\start.py{RESET}")
        print(f"  Or via batch:  {CYAN}scripts\\start.bat{RESET}\n")
    else:
        print(f"\n  {YELLOW}Setup finished with warnings.{RESET}")
        print(f"  Fix the issues above, then run:")
        print(f"  {CYAN}python scripts\\start.py{RESET}\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
