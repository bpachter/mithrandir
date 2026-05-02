"""
repo_watcher.py — Monitor other repos on this machine for agent activity.

Two modes:
  snapshot        — instant read: recent commits, status, recently changed files,
                    diff stat. Fits cleanly in the 1600-char observation window.
  poll_until_idle — blocks until the repo goes quiet (no new commits + no file
                    modifications for idle_secs), then returns a change summary.
                    Use when the user says "tell me when the agent is done."

After either mode, Mithrandir can call dev_read_file / dev_list_files to inspect
specific changed files before synthesizing its answer.
"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path


# ── Repo aliases ──────────────────────────────────────────────────────────────

_DESKTOP = Path("C:/Users/benpa/OneDrive/Desktop")

_ALIASES: dict[str, Path] = {
    "avalon":      _DESKTOP / "avalon",
    "orator":      _DESKTOP / "orator",
    "mithrandir":  _DESKTOP / "Mithrandir",
    "longinus":    _DESKTOP / "longinus",
    "zeus":        _DESKTOP / "zeus",
    "babylon":     _DESKTOP / "babylon",
    "aristotle":   _DESKTOP / "aristotle",
    "chronos":     _DESKTOP / "chronos",
    "aegis":       _DESKTOP / "aegis",
}


def _resolve(repo: str) -> Path | None:
    key = repo.strip().lower()
    if key in _ALIASES:
        p = _ALIASES[key]
    else:
        p = Path(repo)
    if p.is_dir() and (p / ".git").is_dir():
        return p
    return None


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path, timeout: int = 12) -> str:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return (r.stdout or r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return f"[git timeout after {timeout}s]"
    except Exception as e:
        return f"[git error: {e}]"


def _head_sha(cwd: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd)


# ── File recency ──────────────────────────────────────────────────────────────

_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache"}


def _recent_files(root: Path, window_secs: int) -> list[tuple[str, int]]:
    """(relative_path, seconds_ago) for files modified within window_secs."""
    now = time.time()
    cutoff = now - window_secs
    out: list[tuple[str, int]] = []
    try:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _SKIP]
            for fn in files:
                fp = os.path.join(dirpath, fn)
                try:
                    mt = os.stat(fp).st_mtime
                    if mt >= cutoff:
                        rel = os.path.relpath(fp, root)
                        out.append((rel, int(now - mt)))
                except OSError:
                    pass
    except Exception:
        pass
    return sorted(out, key=lambda x: x[1])


# ── Agent activity detection ──────────────────────────────────────────────────

def _activity(root: Path) -> dict:
    """Quick signals that an agent is actively working in this repo."""
    recent30 = _recent_files(root, 30)
    commits5m = [l for l in _git(["log", "--oneline", "--since=5 minutes ago"], root).splitlines() if l.strip()]
    status_lines = [l for l in _git(["status", "--porcelain"], root).splitlines() if l.strip()]
    youngest = recent30[0][1] if recent30 else None
    return {
        "active": bool(commits5m or recent30 or status_lines),
        "commits_5m": len(commits5m),
        "files_30s": len(recent30),
        "youngest_secs": youngest,
        "uncommitted": len(status_lines),
        "has_claude": (root / ".claude").is_dir(),
    }


# ── snapshot ──────────────────────────────────────────────────────────────────

def _snapshot(root: Path, since_sha: str = "") -> str:
    name = root.name
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    act = _activity(root)

    lines: list[str] = [f"=== {name} snapshot ({ts}) ==="]

    # Agent status line
    if act["active"]:
        parts = []
        if act["commits_5m"]:
            parts.append(f"{act['commits_5m']} commits/5m")
        if act["youngest_secs"] is not None:
            parts.append(f"file modified {act['youngest_secs']}s ago")
        if act["uncommitted"]:
            parts.append(f"{act['uncommitted']} uncommitted")
        lines.append(f"AGENT: active — {', '.join(parts)}")
    else:
        lines.append("AGENT: idle (no recent commits or file changes)")

    if act["has_claude"]:
        lines.append(".claude/ present (Claude Code project)")

    lines.append("")

    # Recent commits — most useful for understanding what was built
    log = _git(["log", "--format=%h  %ar  %s", "-10"], root)
    lines.append("Recent commits:")
    if log and not log.startswith("["):
        for l in log.splitlines()[:10]:
            lines.append(f"  {l}")
    else:
        lines.append("  (none)")

    lines.append("")

    # Git status (uncommitted work in progress)
    status = _git(["status", "--short"], root)
    if status and not status.startswith("["):
        lines.append("Working tree:")
        for l in status.splitlines()[:12]:
            lines.append(f"  {l}")
    else:
        lines.append("Working tree: clean")

    lines.append("")

    # Recently modified files (last 2 min) — shows what the agent is touching right now
    recent = _recent_files(root, 120)
    if recent:
        lines.append("Modified last 2min:")
        for rel, age in recent[:8]:
            lines.append(f"  {rel}  ({age}s ago)")
        if len(recent) > 8:
            lines.append(f"  ... +{len(recent) - 8} more")
        lines.append("")

    # Diff stat
    base = since_sha if since_sha else "HEAD~5"
    diff = _git(["diff", f"{base}..HEAD", "--stat"], root)
    label = f"since {since_sha[:8]}" if since_sha else "last 5 commits"
    lines.append(f"Diff stat ({label}):")
    if diff and not diff.startswith("["):
        for l in diff.splitlines()[:15]:
            lines.append(f"  {l}")
    else:
        lines.append("  (clean or no base)")

    lines.append("")
    lines.append("Use dev_read_file to inspect specific changed files.")

    return "\n".join(lines)


# ── poll_until_idle ───────────────────────────────────────────────────────────

def _poll_until_idle(root: Path, max_wait: int, idle_secs: int) -> str:
    max_wait  = max(30,  min(max_wait,  600))
    idle_secs = max(20,  min(idle_secs, 120))
    poll_interval = 8

    name = root.name
    start_sha  = _head_sha(root)
    t_start    = time.time()
    t_last_act = t_start
    last_sha   = start_sha
    new_commits: list[str] = []

    log_lines: list[str] = [
        f"Monitoring {name} (max {max_wait}s, idle threshold {idle_secs}s)"
    ]

    finish = "timeout"

    while True:
        elapsed = time.time() - t_start
        if elapsed > max_wait:
            log_lines.append(f"  [{int(elapsed)}s] max_wait reached")
            break

        # New commits?
        cur_sha = _head_sha(root)
        if cur_sha != last_sha and not cur_sha.startswith("["):
            raw = _git(["log", "--format=%h  %s", f"{last_sha}..HEAD"], root)
            for line in raw.splitlines():
                if line.strip():
                    new_commits.append(line.strip())
                    log_lines.append(f"  [{int(elapsed)}s] commit: {line.strip()}")
            last_sha = cur_sha
            t_last_act = time.time()

        # File activity?
        if _recent_files(root, poll_interval + 2):
            t_last_act = time.time()

        idle = time.time() - t_last_act
        if idle >= idle_secs:
            log_lines.append(f"  [{int(elapsed)}s] idle for {int(idle)}s — done")
            finish = "idle"
            break

        time.sleep(poll_interval)

    total = int(time.time() - t_start)
    lines: list[str] = [
        f"=== {name} watch complete — {total}s, reason: {finish} ===",
        "",
    ]

    if new_commits:
        lines.append(f"Commits landed ({len(new_commits)}):")
        for c in new_commits:
            lines.append(f"  {c}")
    else:
        lines.append("No new commits during watch.")

    lines.append("")

    # File-level diff stat from start → end
    if start_sha and not start_sha.startswith("["):
        stat = _git(["diff", f"{start_sha}..HEAD", "--stat"], root)
        if stat and not stat.startswith("["):
            lines.append("Files changed since watch began:")
            for l in stat.splitlines()[:20]:
                lines.append(f"  {l}")
            lines.append("")

    lines.append("Monitor log:")
    lines.extend(log_lines[:25])
    lines.append("")
    lines.append("Use dev_read_file to inspect specific changed files for bug analysis.")

    return "\n".join(lines)


# ── public entry point ────────────────────────────────────────────────────────

def watch_repo(
    repo: str,
    action: str = "snapshot",
    since_sha: str = "",
    max_wait: int = 300,
    idle_secs: int = 45,
) -> str:
    """
    Monitor a repo on this machine for agent activity.

    action='snapshot'       — immediate state report (fast)
    action='poll_until_idle'— block until the agent goes quiet, then summarise
    """
    root = _resolve(repo)
    if root is None:
        known = ", ".join(_ALIASES)
        return (
            f"Repo '{repo}' not found. Known aliases: {known}. "
            "Or supply an absolute path to a git repository."
        )

    action = action.strip().lower()

    if action == "snapshot":
        return _snapshot(root, since_sha=since_sha)
    if action in ("poll_until_idle", "poll", "monitor", "wait"):
        return _poll_until_idle(root, max_wait=max_wait, idle_secs=idle_secs)

    return f"Unknown action '{action}'. Use 'snapshot' or 'poll_until_idle'."
