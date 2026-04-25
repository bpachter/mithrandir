"""
dev_tools.py — Mithrandir Dev Orchestration Engine

Manages a queue of AI-driven development tasks. Each task is delegated to
Claude (via the Anthropic SDK), which acts as a code-writing subagent.
Progress is streamed to connected WebSocket clients in real time, and
Mithrandir narrates progress to the user in the chat panel in parallel.

Task lifecycle:
    queued → running → done | failed | needs_review

Each completed task carries a list of FilePatch objects representing
suggested file changes. The user approves or rejects them from DevPanel.

Security:
    - All file reads/writes are scoped to PROJECT_ROOTS.
    - Path traversal is blocked by strict prefix checking.
    - Command execution is NOT supported here — use approval-gated
      terminal calls via the agent loop instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("mithrandir.dev")

# ---------------------------------------------------------------------------
# Project registry — add new apps here as they are created
# ---------------------------------------------------------------------------

_DESKTOP = Path("C:/Users/benpa/OneDrive/Desktop")

PROJECT_ROOTS: dict[str, Path] = {
    "mithrandir":   _DESKTOP / "Mithrandir",
    "avalon":   _DESKTOP / "avalon",
    "orator":   _DESKTOP / "orator",       # will exist when built
    "longinus": _DESKTOP / "longinus",
    "zeus":     _DESKTOP / "zeus",
    "babylon":  _DESKTOP / "babylon",
    "aristotle": _DESKTOP / "aristotle",
}

# Directories to skip when building file trees
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", ".next", "build", ".mypy_cache", ".pytest_cache",
}

# File extensions the IDE panel can display as text
_TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".md", ".txt", ".env", ".example", ".sh", ".ps1",
    ".css", ".html", ".sql", ".csv", ".ini", ".cfg", ".env.example",
}

# ---------------------------------------------------------------------------
# Security — sensitive file gating
# ---------------------------------------------------------------------------

# Password required to view sensitive files in the IDE panel
_DEV_PASSWORD = "antifragile"

# Hidden dotfiles to show in the file tree (all other dotfiles are hidden)
_SHOW_HIDDEN = {".env", ".env.example", ".gitignore", ".gitkeep", ".dockerignore"}

# Dotfiles that can be read by name (their suffix is empty, so they bypass _TEXT_EXTS)
_READABLE_DOTFILES = {".env", ".env.example", ".env.local", ".gitignore", ".gitkeep", ".dockerignore"}


def _is_sensitive(name: str) -> bool:
    """Return True if this file requires _DEV_PASSWORD to view its contents."""
    lower = name.lower()
    if lower in {".env", ".env.local", ".env.production", ".env.staging", ".env.development"}:
        return True
    if lower.endswith((".pem", ".key", ".pfx", ".p12", ".pkcs12")):
        return True
    if lower in {"credentials.json", "service_account.json", "id_rsa", "id_ed25519"}:
        return True
    return False

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FilePatch:
    path: str             # workspace-relative path
    original: str         # original file contents (empty if new file)
    proposed: str         # proposed new contents
    status: str = "pending"   # pending | accepted | rejected

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DevEvent:
    kind: str             # log | patch_ready | status | error | narration
    ts: float = field(default_factory=time.time)
    message: str = ""
    data: Any = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ts": self.ts, "message": self.message, "data": self.data}


@dataclass
class DevTask:
    id: str
    goal: str
    project: str
    status: str               # queued | running | done | failed | needs_review
    created_at: float
    updated_at: float
    events: list[dict] = field(default_factory=list)
    patches: list[dict] = field(default_factory=list)
    error: str = ""
    context_files: list[str] = field(default_factory=list)   # paths user wants included

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# In-memory task store
# ---------------------------------------------------------------------------

_tasks: dict[str, DevTask] = {}
_tasks_lock = threading.Lock()

# Persistence path
_TASKS_LOG = Path(__file__).parent / "dev_tasks.jsonl"


def _persist_task(task: DevTask) -> None:
    try:
        with open(_TASKS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(task.to_dict()) + "\n")
    except Exception as e:
        logger.warning(f"Failed to persist task {task.id}: {e}")


def create_task(goal: str, project: str, context_files: list[str] | None = None) -> DevTask:
    task = DevTask(
        id=str(uuid.uuid4())[:8],
        goal=goal,
        project=project.lower(),
        status="queued",
        created_at=time.time(),
        updated_at=time.time(),
        context_files=context_files or [],
    )
    with _tasks_lock:
        _tasks[task.id] = task
    _persist_task(task)
    _broadcast_event(task.id, DevEvent(kind="status", message="queued"))
    return task


def get_task(task_id: str) -> Optional[DevTask]:
    with _tasks_lock:
        return _tasks.get(task_id)


def list_tasks(project: str | None = None) -> list[DevTask]:
    with _tasks_lock:
        tasks = list(_tasks.values())
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    if project:
        tasks = [t for t in tasks if t.project == project.lower()]
    return tasks


def _update_task(task_id: str, **kwargs) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            for k, v in kwargs.items():
                setattr(task, k, v)
            task.updated_at = time.time()


def _append_event(task_id: str, event: DevEvent) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task.events.append(event.to_dict())
            task.updated_at = time.time()
    _broadcast_event(task_id, event)


def _append_patch(task_id: str, patch: FilePatch) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task.patches.append(patch.to_dict())
            task.updated_at = time.time()


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------

# asyncio queue per subscriber; main.py registers/unregisters via helpers
_ws_subscribers: list[asyncio.Queue] = []
_ws_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe_ws() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _ws_lock:
        _ws_subscribers.append(q)
    return q


def unsubscribe_ws(q: asyncio.Queue) -> None:
    with _ws_lock:
        try:
            _ws_subscribers.remove(q)
        except ValueError:
            pass


def _broadcast_event(task_id: str, event: DevEvent) -> None:
    payload = {"task_id": task_id, **event.to_dict()}
    with _ws_lock:
        subs = list(_ws_subscribers)
    for q in subs:
        try:
            if _loop and _loop.is_running():
                _loop.call_soon_threadsafe(q.put_nowait, payload)
            else:
                q.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # slow consumer; drop


# ---------------------------------------------------------------------------
# Git utilities
# ---------------------------------------------------------------------------

def get_git_diff(project: str) -> dict:
    """Return git diff --stat and full diff for a project."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root or not root.exists():
        return {"error": f"Project '{project}' not found or path does not exist."}
    try:
        stat = subprocess.check_output(
            ["git", "diff", "--stat"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10,
        )
        diff = subprocess.check_output(
            ["git", "diff"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10,
        )
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10,
        )
        return {"stat": stat.strip(), "diff": diff.strip(), "status": status.strip()}
    except subprocess.TimeoutExpired:
        return {"error": "git diff timed out"}
    except Exception as e:
        return {"error": str(e)}


def git_status_summary(project: str) -> dict:
    """Return current branch, short status, and ahead/behind count."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root or not root.exists():
        return {"error": f"Project '{project}' not found or path does not exist."}
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10,
        ).strip()
        return {"branch": branch, "status": status}
    except subprocess.TimeoutExpired:
        return {"error": "git status timed out"}
    except Exception as e:
        return {"error": str(e)}


def git_commit_push(project: str, message: str, push: bool = True) -> dict:
    """Stage all changes, commit, and optionally push to origin."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root or not root.exists():
        return {"error": f"Project '{project}' not found or path does not exist."}
    try:
        subprocess.check_output(
            ["git", "add", "-A"],
            cwd=root, text=True, stderr=subprocess.STDOUT, timeout=30,
        )
        commit_out = subprocess.check_output(
            ["git", "commit", "-m", message],
            cwd=root, text=True, stderr=subprocess.STDOUT, timeout=30,
        )
        if push:
            push_out = subprocess.check_output(
                ["git", "push"],
                cwd=root, text=True, stderr=subprocess.STDOUT, timeout=90,
            )
            return {"ok": True, "output": commit_out.strip() + "\n" + push_out.strip()}
        return {"ok": True, "output": commit_out.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": e.output or str(e)}
    except subprocess.TimeoutExpired:
        return {"error": "git operation timed out"}
    except Exception as e:
        return {"error": str(e)}


def git_pull(project: str) -> dict:
    """Pull latest changes from origin for a project."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root or not root.exists():
        return {"error": f"Project '{project}' not found or path does not exist."}
    try:
        result = subprocess.check_output(
            ["git", "pull"],
            cwd=root, text=True, stderr=subprocess.STDOUT, timeout=90,
        )
        return {"ok": True, "output": result.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": e.output or str(e)}
    except subprocess.TimeoutExpired:
        return {"error": "git pull timed out"}
    except Exception as e:
        return {"error": str(e)}


def get_file_tree(project: str, sub_path: str = "") -> dict:
    """Return a JSON-serialisable file tree for the project root (or subdir)."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root or not root.exists():
        return {"error": f"Project '{project}' not found."}

    base = root if not sub_path else root / sub_path
    base = base.resolve()
    # Prevent traversal outside project root
    if not str(base).startswith(str(root.resolve())):
        return {"error": "Path traversal not allowed."}

    def _walk(path: Path, depth: int = 0) -> list[dict]:
        if depth > 6:
            return []
        entries = []
        try:
            for item in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if item.name.startswith(".") and item.name not in _SHOW_HIDDEN:
                    continue
                if item.is_dir():
                    if item.name in _SKIP_DIRS:
                        continue
                    entries.append({"name": item.name, "type": "dir", "children": _walk(item, depth + 1)})
                else:
                    entries.append({
                        "name": item.name,
                        "type": "file",
                        "ext": item.suffix,
                        "sensitive": _is_sensitive(item.name),
                    })
        except PermissionError:
            pass
        return entries

    return {"project": project, "root": str(base), "tree": _walk(base)}


def read_file_contents(project: str, rel_path: str, password: str = "") -> dict:
    """Read a file from a project. Sensitive files require _DEV_PASSWORD."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root:
        return {"error": f"Unknown project: {project}"}

    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        return {"error": "Path traversal not allowed."}
    if not target.exists():
        return {"error": f"File not found: {rel_path}"}
    # Gate sensitive files behind the dev password
    if _is_sensitive(target.name) and password != _DEV_PASSWORD:
        return {"error": "password_required", "message": "This file requires the dev password to view."}
    if target.suffix not in _TEXT_EXTS and target.name not in _READABLE_DOTFILES:
        return {"error": f"Binary or unsupported file type: {target.suffix}"}
    try:
        contents = target.read_text(encoding="utf-8", errors="replace")
        return {"path": str(target), "rel_path": rel_path, "contents": contents}
    except Exception as e:
        return {"error": str(e)}


def apply_patch(project: str, rel_path: str, proposed: str) -> dict:
    """Write proposed file contents to disk (after user approval in UI)."""
    root = PROJECT_ROOTS.get(project.lower())
    if not root:
        return {"error": f"Unknown project: {project}"}

    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        return {"error": "Path traversal not allowed."}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proposed, encoding="utf-8")
        logger.info(f"Patch applied: {target}")
        return {"ok": True, "path": str(target)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Claude dev delegation
# ---------------------------------------------------------------------------

def _build_file_context(project: str, context_files: list[str]) -> str:
    """Read requested context files and format them for the prompt."""
    parts = []
    for rel in context_files[:8]:   # cap at 8 files
        result = read_file_contents(project, rel)
        if "contents" in result:
            parts.append(f"=== {rel} ===\n{result['contents']}\n")
    return "\n".join(parts) if parts else ""


_DEV_SYSTEM_PROMPT = """\
You are a senior software engineer working inside the Mithrandir development system.
Mithrandir is a local AI assistant with an RTX 4090. You are given a development task
for one of several applications in the portfolio (Orator, Avalon, Longinus, Zeus,
Babylon, Aristotle, Mithrandir itself).

Your responsibilities:
1. Understand the task and the existing code context provided.
2. Propose concrete, working code changes.
3. Format all file changes using the exact patch format below.

PATCH FORMAT — use this for EVERY file you create or modify:
<patch file="relative/path/from/project/root">
<original>
...exact original content (empty string for new files)...
</original>
<proposed>
...complete new file content...
</proposed>
</patch>

Rules:
- Provide the COMPLETE file content in <proposed>, not just the diff.
- If creating a new file, leave <original> empty.
- Explain what you're doing in plain text BEFORE each patch block.
- Be specific. Don't add features not requested.
- If you need information you don't have (e.g. an API key, a schema), say so clearly.
"""


def _parse_patches(text: str) -> list[FilePatch]:
    """Extract FilePatch objects from Claude's structured output."""
    patches = []
    pattern = re.compile(
        r'<patch\s+file="([^"]+)">\s*<original>(.*?)</original>\s*<proposed>(.*?)</proposed>\s*</patch>',
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        patches.append(FilePatch(
            path=m.group(1).strip(),
            original=m.group(2).strip(),
            proposed=m.group(3).strip(),
        ))
    return patches


def run_task_sync(task_id: str) -> None:
    """
    Execute a dev task synchronously (call from a thread pool).
    Streams DevEvents throughout and populates patches on completion.
    """
    task = get_task(task_id)
    if not task:
        return

    _update_task(task_id, status="running")
    _append_event(task_id, DevEvent(kind="status", message="running"))
    _append_event(task_id, DevEvent(kind="log", message=f"Starting task: {task.goal}"))

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _update_task(task_id, status="failed", error="ANTHROPIC_API_KEY not set")
        _append_event(task_id, DevEvent(kind="error", message="ANTHROPIC_API_KEY not set"))
        return

    # Build context
    file_ctx = ""
    if task.context_files:
        _append_event(task_id, DevEvent(kind="log", message=f"Reading {len(task.context_files)} context file(s)..."))
        file_ctx = _build_file_context(task.project, task.context_files)

    # Build prompt
    project_desc = f"Project: {task.project}"
    user_msg = f"{project_desc}\n\nTask:\n{task.goal}"
    if file_ctx:
        user_msg += f"\n\nExisting code context:\n{file_ctx}"

    _append_event(task_id, DevEvent(kind="log", message="Delegating to Claude subagent..."))

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        model = os.environ.get("CLAUDE_SUBAGENT_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"

        # Use streaming so we can emit progress events as text arrives
        full_text = ""
        with client.messages.stream(
            model=model,
            max_tokens=8000,
            system=_DEV_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text += chunk
                # Emit a log event every ~200 chars so the UI shows progress
                if len(full_text) % 200 < len(chunk) + 5:
                    preview = full_text[-120:].replace("\n", " ").strip()
                    _append_event(task_id, DevEvent(kind="log", message=f"…{preview}"))

        _append_event(task_id, DevEvent(kind="log", message="Claude response complete. Parsing patches..."))

        patches = _parse_patches(full_text)
        if patches:
            for p in patches:
                _append_patch(task_id, p)
                _append_event(task_id, DevEvent(
                    kind="patch_ready",
                    message=f"Patch ready: {p.path}",
                    data=p.to_dict(),
                ))
            _update_task(task_id, status="needs_review")
            _append_event(task_id, DevEvent(
                kind="status",
                message=f"needs_review — {len(patches)} file(s) to review",
            ))
        else:
            # No patches — pure analysis or explanation response
            _append_event(task_id, DevEvent(
                kind="narration",
                message=full_text,
            ))
            _update_task(task_id, status="done")
            _append_event(task_id, DevEvent(kind="status", message="done"))

    except Exception as e:
        logger.error(f"Dev task {task_id} failed: {e}")
        _update_task(task_id, status="failed", error=str(e))
        _append_event(task_id, DevEvent(kind="error", message=str(e)))
