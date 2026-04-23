"""
registry.py — Tool registration and dispatch for the ReAct agent loop.

Each tool has:
    name:        identifier the LLM uses in the "action" field
    description: what it does (shown verbatim in the system prompt)
    parameters:  dict of {param_name: description} (shown in system prompt)
    fn:          callable — takes **kwargs, returns str observation

Add new tools by calling register(). The registry is read at agent startup
to build the tool section of the system prompt.
"""

import os
import sys
import time
import json
import re
import logging
import subprocess
import importlib.util
from typing import Callable

_telem_logger = logging.getLogger("enkidu.telemetry")

# In-memory telemetry ring buffer (last 200 tool call records)
_TELEMETRY: list[dict] = []
_TELEM_MAX = 200

_CLAUDE_SUBAGENT_CALL_TIMES: list[float] = []


def _estimate_tokens(text: str) -> int:
    """Rough token estimator for routing and delegation policy."""
    return max(1, len(text) // 4)


def _claude_subagent_allowlist() -> list[str]:
    raw = os.environ.get(
        "ENKIDU_CLAUDE_SUBAGENT_ALLOWLIST",
        "long context,document analysis,multi-file,codebase synthesis,second opinion,validation,refactor",
    )
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _claude_subagent_threshold() -> int:
    raw = os.environ.get("ENKIDU_CLAUDE_SUBAGENT_TOKEN_THRESHOLD", "9000")
    try:
        return max(1000, int(raw))
    except Exception:
        return 9000


def _claude_subagent_rate_window_sec() -> int:
    raw = os.environ.get("ENKIDU_CLAUDE_SUBAGENT_WINDOW_SEC", "60")
    try:
        return max(10, int(raw))
    except Exception:
        return 60


def _claude_subagent_rate_max_calls() -> int:
    raw = os.environ.get("ENKIDU_CLAUDE_SUBAGENT_MAX_CALLS", "6")
    try:
        return max(1, int(raw))
    except Exception:
        return 6


def _claude_subagent_audit_path() -> str:
    default_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "claude_subagent_audit.jsonl")
    )
    return os.environ.get("ENKIDU_CLAUDE_SUBAGENT_AUDIT_LOG", default_path)


def _audit_claude_subagent(event: dict) -> None:
    """Write one JSON line per delegation decision/result for observability."""
    try:
        path = _claude_subagent_audit_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception:
        # Never break agent execution on logging failures
        pass


def _claude_subagent_gate(task: str, context: str) -> tuple[bool, str, dict]:
    """Deterministic gate to keep Gemma local as primary orchestrator."""
    lower_task = (task or "").lower()
    tokens_task = _estimate_tokens(task or "")
    tokens_ctx = _estimate_tokens(context or "")
    tokens_total = tokens_task + tokens_ctx

    metadata = {
        "task_tokens": tokens_task,
        "context_tokens": tokens_ctx,
        "total_tokens": tokens_total,
        "token_threshold": _claude_subagent_threshold(),
    }

    force = os.environ.get("ENKIDU_CLAUDE_SUBAGENT_FORCE", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if force:
        return True, "forced_by_env", metadata

    # Rate limit protection
    now = time.time()
    window = _claude_subagent_rate_window_sec()
    max_calls = _claude_subagent_rate_max_calls()
    cutoff = now - window
    while _CLAUDE_SUBAGENT_CALL_TIMES and _CLAUDE_SUBAGENT_CALL_TIMES[0] < cutoff:
        _CLAUDE_SUBAGENT_CALL_TIMES.pop(0)
    if len(_CLAUDE_SUBAGENT_CALL_TIMES) >= max_calls:
        return False, f"rate_limited_{max_calls}_per_{window}s", metadata

    if tokens_total >= _claude_subagent_threshold():
        return True, "long_context_threshold", metadata

    allowlist = _claude_subagent_allowlist()
    for phrase in allowlist:
        if phrase and re.search(re.escape(phrase), lower_task):
            return True, f"allowlist_match:{phrase}", metadata

    return False, "below_threshold_and_not_allowlisted", metadata

def _record_telemetry(name: str, latency_ms: float, success: bool, error: str = ""):
    record = {
        "tool": name,
        "ts": time.time(),
        "latency_ms": round(latency_ms, 1),
        "success": success,
        "error": error,
    }
    _TELEMETRY.append(record)
    if len(_TELEMETRY) > _TELEM_MAX:
        _TELEMETRY.pop(0)
    if not success:
        _telem_logger.warning(f"Tool '{name}' failed in {latency_ms:.0f}ms: {error}")

# Phase 4 memory bridge — subprocess so we don't need chromadb in the phase3 env
_PHASE4_PYTHON = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "phase4-memory", ".venv", "Scripts", "python.exe")
)
_MEMORY_BRIDGE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "phase4-memory", "memory_bridge.py")
)

def _call_memory_bridge(*args, timeout: int = 15) -> str:
    """Call memory_bridge.py via the phase4 venv. Returns stdout or error string."""
    if not os.path.exists(_PHASE4_PYTHON):
        return "[memory unavailable — phase4 venv not found]"
    try:
        result = subprocess.run(
            [_PHASE4_PYTHON, _MEMORY_BRIDGE] + list(args),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "[memory timeout]"
    except Exception as e:
        return f"[memory error: {e}]"


def _load_phase2_module(module_name: str):
    """
    Load a module from phase2-tool-use/tools/ by absolute file path.

    This avoids the naming collision between phase3-agents/tools/ (this package)
    and phase2-tool-use/tools/ — both are named 'tools', so sys.path insertion
    would shadow one or the other. Loading by path sidesteps the issue entirely.
    """
    _phase2_tools = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "phase2-tool-use", "tools")
    )
    file_path = os.path.join(_phase2_tools, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(f"phase2_{module_name}", file_path)
    mod = importlib.util.module_from_spec(spec)
    # edgar_screener imports from its own package — add phase2-tool-use to path first
    _phase2_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "phase2-tool-use")
    )
    if _phase2_root not in sys.path:
        sys.path.insert(0, _phase2_root)
    spec.loader.exec_module(mod)
    return mod


_system_info_mod = _load_phase2_module("system_info")
_edgar_mod = _load_phase2_module("edgar_screener")

_system_info_context = _system_info_mod.get_context
_edgar_context = _edgar_mod.get_context


# --- Registry store ---

TOOLS: dict[str, dict] = {}


def register(name: str, description: str, parameters: dict, fn: Callable):
    """Register a tool. Overwrites any existing tool with the same name."""
    TOOLS[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "fn": fn,
    }


def dispatch(name: str, max_retries: int = 2, retry_delay: float = 1.0, **kwargs) -> str:
    """
    Call a registered tool by name with automatic retry and telemetry.

    - Retries up to max_retries times on transient errors (timeout, network, I/O).
    - Records latency and success/failure to the in-memory telemetry buffer.
    - Returns an error string (not an exception) so the agent can reason about failures.
    """
    if name not in TOOLS:
        known = ", ".join(TOOLS.keys())
        err = f"Error: unknown tool '{name}'. Available tools: {known}"
        _record_telemetry(name, 0, False, err)
        return err

    last_error = ""
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        try:
            result = TOOLS[name]["fn"](**kwargs)
            latency = (time.monotonic() - t0) * 1000
            _record_telemetry(name, latency, True)
            return result
        except TypeError as e:
            latency = (time.monotonic() - t0) * 1000
            err = f"Error: wrong arguments for tool '{name}': {e}"
            _record_telemetry(name, latency, False, str(e))
            return err  # Argument errors are not transient — don't retry
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            last_error = str(e)
            _record_telemetry(name, latency, False, last_error)
            if attempt < max_retries:
                _telem_logger.info(f"Tool '{name}' attempt {attempt + 1} failed, retrying in {retry_delay}s: {e}")
                time.sleep(retry_delay)
            # Escalate delay on each retry
            retry_delay = min(retry_delay * 2, 10.0)

    return f"Error running tool '{name}' (after {max_retries + 1} attempts): {last_error}"


def get_telemetry(n: int = 50) -> list[dict]:
    """Return the last n telemetry records."""
    return list(_TELEMETRY[-n:])


def tool_descriptions() -> str:
    """
    Format all registered tools for injection into the system prompt.
    Example output:
        - edgar_screener(query: str): Look up financial data...
        - python_sandbox(code: str): Execute Python code...
    """
    lines = []
    for tool in TOOLS.values():
        params = ", ".join(f"{k}: {v}" for k, v in tool["parameters"].items())
        lines.append(f"- {tool['name']}({params}): {tool['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in tool registrations
# ---------------------------------------------------------------------------

def _edgar_tool(query: str) -> str:
    return _edgar_context(query)


def _system_tool(query: str = "") -> str:
    # system_info takes no args — query is accepted but ignored
    return _system_info_context()


register(
    name="edgar_screener",
    description=(
        "Look up financial data for stocks from SEC EDGAR and the QV screened portfolio. "
        "Use for: specific ticker lookups (e.g. 'NUE', 'CLF'), top undervalued stocks, "
        "QV portfolio rankings, EV/EBIT ratios, FCF yield, Piotroski F-Score, debt ratios, "
        "and general questions about screened companies. "
        "NOTE: CapEx is not a direct field — derive it as CapEx = cfo - fcf (both fields are available). "
        "To compare a stock to sector peers, call this tool once per ticker."
    ),
    parameters={
        "query": "str — a question or ticker symbol, e.g. 'NUE' or 'top 10 undervalued stocks'"
    },
    fn=_edgar_tool,
)

register(
    name="system_info",
    description=(
        "Get real-time GPU temperature, VRAM usage, CPU load, and RAM stats "
        "from the local machine running Enkidu."
    ),
    parameters={
        "query": "str — optional context string, e.g. 'gpu temperature'"
    },
    fn=_system_tool,
)

# regime_detector lives in the same directory as this file
_regime_path = os.path.join(os.path.dirname(__file__), "regime_detector.py")
_regime_spec = importlib.util.spec_from_file_location("regime_detector", _regime_path)
_regime_mod = importlib.util.module_from_spec(_regime_spec)
_regime_spec.loader.exec_module(_regime_mod)
_get_regime_context = _regime_mod.get_regime_context
get_regime = _regime_mod.get_regime

register(
    name="market_regime",
    description=(
        "Get the current market regime detected by a Hidden Markov Model trained on SPY. "
        "Returns one of: Expansion, Recovery, Contraction, Crisis — plus confidence, "
        "weekly return, 30-day volatility, and price vs 200MA. "
        "Use when the user asks about market conditions, regime, or how to adjust screening."
    ),
    parameters={
        "query": "str — optional, e.g. 'current regime' or 'market conditions'"
    },
    fn=lambda query="": _get_regime_context(),
)

# python_sandbox lives in the same directory as this file
_sandbox_mod = _load_phase2_module.__func__ if hasattr(_load_phase2_module, '__func__') else None
_sandbox_path = os.path.join(os.path.dirname(__file__), "python_sandbox.py")
_sandbox_spec = importlib.util.spec_from_file_location("python_sandbox", _sandbox_path)
_sandbox_mod = importlib.util.module_from_spec(_sandbox_spec)
_sandbox_spec.loader.exec_module(_sandbox_mod)
_run_python = _sandbox_mod.run_python

register(
    name="python_sandbox",
    description=(
        "Execute Python code in a subprocess and return stdout/stderr. "
        "Use for: exact arithmetic, CAGR/IRR/NPV calculations, portfolio statistics, "
        "ratio comparisons, descriptive stats, DCF models, or any computation where "
        "you need precise numbers rather than estimates. "
        "numpy, pandas, scipy, and all installed packages are available. "
        "Runs with a 10-second timeout. Print results — return values are not shown."
    ),
    parameters={
        "code": "str — valid Python source code; use print() to output results"
    },
    fn=lambda code: _run_python(code),
)

# ---------------------------------------------------------------------------
# Phase 5 — backtesting + performance tracking
# ---------------------------------------------------------------------------

_phase5_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "phase5-intelligence")
)

def _qv_performance(query: str = "") -> str:
    """Call performance_tracker for a summary of signal returns."""
    try:
        spec = importlib.util.spec_from_file_location(
            "performance_tracker",
            os.path.join(_phase5_path, "performance_tracker.py")
        )
        mod = importlib.util.module_from_spec(spec)
        # Ensure phase2 tools are available
        _phase2_tools = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "phase2-tool-use", "tools")
        )
        if _phase2_tools not in sys.path:
            sys.path.insert(0, _phase2_tools)
        if _phase5_path not in sys.path:
            sys.path.insert(0, _phase5_path)
        spec.loader.exec_module(mod)

        if any(kw in query.lower() for kw in ["full", "detail", "report"]):
            return mod.performance_report()
        else:
            return mod.performance_summary()
    except Exception as e:
        return f"Performance data unavailable: {e}"


def _qv_signal_snapshot(query: str = "") -> str:
    """Return the most recent QV signal snapshot."""
    try:
        if _phase5_path not in sys.path:
            sys.path.insert(0, _phase5_path)
        spec = importlib.util.spec_from_file_location(
            "signal_logger",
            os.path.join(_phase5_path, "signal_logger.py")
        )
        mod = importlib.util.module_from_spec(spec)
        _phase2_tools = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "phase2-tool-use", "tools")
        )
        if _phase2_tools not in sys.path:
            sys.path.insert(0, _phase2_tools)
        spec.loader.exec_module(mod)

        snaps = mod.get_snapshot()
        if not snaps:
            return "No signal snapshots yet. The logger runs daily to record picks."

        lines = [f"QV signal snapshot ({snaps[0]['snapshot_dt']}, {len(snaps)} picks):"]
        for s in snaps:
            flags = f"  [{s['quality_flags']}]" if s.get('quality_flags') else ""
            lines.append(
                f"  #{s['rank']:2d}  {s['ticker']:<6} {s.get('sector',''):<20} "
                f"EV/EBIT: {s.get('ev_ebit', 0):.2f}  VC: {s.get('value_composite', 0):.1f}{flags}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Signal snapshot unavailable: {e}"


register(
    name="qv_performance",
    description=(
        "Get the track record of QV stock-picking signals. Shows average returns, "
        "alpha vs SPY, and win rate across 30/90/180/365-day horizons. "
        "Use when the user asks 'how has the QV model performed?', 'what's our alpha?', "
        "or 'show me the backtesting results'. Returns 'full report' when asked for details."
    ),
    parameters={
        "query": "str — e.g. 'performance summary', 'full report', 'how has the model done'"
    },
    fn=_qv_performance,
)

register(
    name="qv_snapshot",
    description=(
        "Show the most recent QV signal snapshot — the current ranked watchlist of "
        "top undervalued stocks with quality flags and sector labels. "
        "Use when the user asks 'what's on the current watchlist?', "
        "'show me the QV picks', or 'what were the top picks logged?'"
    ),
    parameters={
        "query": "str — optional context, e.g. 'current watchlist'"
    },
    fn=_qv_signal_snapshot,
)

def _rl_optimize(query: str = "") -> str:
    """Run or report the RL parameter optimizer."""
    try:
        if _phase5_path not in sys.path:
            sys.path.insert(0, _phase5_path)
        spec = importlib.util.spec_from_file_location(
            "rl_optimizer",
            os.path.join(_phase5_path, "rl_optimizer.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        q = query.lower()
        apply = any(kw in q for kw in ["apply", "save", "use", "update"])
        regime = any(kw in q for kw in ["regime", "market"])
        n_trials = 50

        # Extract trial count if specified (e.g. "200 trials")
        import re as _re
        m = _re.search(r'(\d+)\s*trials?', q)
        if m:
            n_trials = min(int(m.group(1)), 500)

        params = mod.run_optimizer(n_trials=n_trials, use_regime=regime, apply=apply)

        lines = ["QV Screening Parameters (RL-optimized):"]
        for k, v in params.items():
            default_v = mod._DEFAULT_PARAMS[k]
            tag = " ← changed" if abs(float(v) - float(default_v)) > 0.5 else ""
            lines.append(f"  {k}: {v}  (default: {default_v}){tag}")
        if apply:
            lines.append(f"\nSaved to: {mod._BEST_PARAMS}")
        return "\n".join(lines)
    except Exception as e:
        return f"RL optimizer error: {e}"


register(
    name="rl_optimize",
    description=(
        "Run the RL-style parameter optimizer for the QV screener. "
        "Searches for the optimal combination of risk thresholds, quality gates, "
        "and value filters to maximize risk-adjusted alpha. "
        "Use when the user asks 'optimize the screener', 'tune the QV parameters', "
        "'what are the best screening thresholds', or 'run the RL optimizer'. "
        "Add 'apply' to save the result. Add 'regime' to factor in current market conditions."
    ),
    parameters={
        "query": "str — e.g. 'optimize with regime', 'run 200 trials and apply', 'optimize screener'"
    },
    fn=_rl_optimize,
)

register(
    name="recall_memory",
    description=(
        "Search past conversations for context relevant to the current query. "
        "Returns semantically similar exchanges from prior sessions. "
        "Use when the user references something from a past conversation, or when "
        "grounding the answer in prior discussed data would be helpful."
    ),
    parameters={
        "query": "str — what to search for in past conversations, e.g. 'DUK capital expenditure'"
    },
    fn=lambda query: _call_memory_bridge("retrieve", query),
)

register(
    name="search_docs",
    description=(
        "Search the indexed local knowledge base (JOURNEY.md, Enkidu codebase, research notes) "
        "for relevant context. Use when the user asks about how something was built, why a "
        "decision was made, or references project history or documentation."
    ),
    parameters={
        "query": "str — what to search for, e.g. 'why did DUK fail the QV screen'"
    },
    fn=lambda query: _call_memory_bridge("search_docs", query),
)

# ---------------------------------------------------------------------------
# Web search (DuckDuckGo — no API key required)
# ---------------------------------------------------------------------------

_web_search_path = os.path.join(os.path.dirname(__file__), "web_search.py")
_web_spec = importlib.util.spec_from_file_location("web_search", _web_search_path)
_web_mod = importlib.util.module_from_spec(_web_spec)
_web_spec.loader.exec_module(_web_mod)

register(
    name="web_search",
    description=(
        "Search the live web via DuckDuckGo and return the top results. "
        "Use for: current events, real-time news, factual questions about people/places/things, "
        "anything that requires up-to-date information not available in financial tools. "
        "Do NOT use for stock data (use edgar_screener) or local system info (use system_info)."
    ),
    parameters={
        "query": "str — the search query, e.g. 'latest Fed interest rate decision 2025'"
    },
    fn=lambda query: _web_mod.search(query),
)

# ---------------------------------------------------------------------------
# CUDA / RTX 4090 / Gemma4 reference docs
# ---------------------------------------------------------------------------

_cuda_docs_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "phase7-ui", "server", "cuda_docs.py")
)

def _cuda_reference(query: str = "") -> str:
    """Keyword search over the local CUDA/hardware/Gemma4 reference docs."""
    try:
        spec = importlib.util.spec_from_file_location("cuda_docs", _cuda_docs_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.search_docs(query, max_results=4)
    except Exception as e:
        return f"cuda_reference unavailable: {e}"


register(
    name="cuda_reference",
    description=(
        "Look up RTX 4090 hardware specs, CUDA execution model details, memory hierarchy, "
        "performance optimization tips, Gemma4 architecture facts, and LLM inference tuning "
        "from the local reference database. "
        "Use when the user asks about: GPU clock speeds, VRAM bandwidth, warp execution, "
        "CUDA cores, tensor cores, Flash Attention, KV cache sizing, roofline model, "
        "SM occupancy, memory coalescing, Gemma4 MoE routing, quantization trade-offs, "
        "or any other hardware/CUDA/inference topic. "
        "Also use proactively when you see anomalous GPU stats (high temp, low utilization, "
        "high power) to suggest relevant optimizations."
    ),
    parameters={
        "query": "str — topic to look up, e.g. 'KV cache VRAM usage' or 'warp divergence'"
    },
    fn=_cuda_reference,
)

# ---------------------------------------------------------------------------
# Claude subagent (optional specialist delegation)
# ---------------------------------------------------------------------------

def _claude_subagent(task: str, context: str = "", max_tokens: int = 1200) -> str:
    """
    Delegate a narrowly scoped heavy task to Claude while Enkidu remains orchestrator.

    This is intentionally synchronous and stateless: one task in, one result out.
    """
    enabled = os.environ.get("ENKIDU_CLAUDE_SUBAGENT_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if not enabled:
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": False,
            "reason": "disabled",
            "task_head": (task or "")[:240],
        })
        return "claude_subagent disabled by ENKIDU_CLAUDE_SUBAGENT_ENABLED"

    allowed, reason, gate_meta = _claude_subagent_gate(task, context)
    if not allowed:
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": False,
            "reason": reason,
            "task_head": (task or "")[:240],
            **gate_meta,
        })
        return (
            f"claude_subagent gate blocked delegation ({reason}). "
            "Continue locally with available tools or narrow the task."
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": False,
            "reason": "missing_api_key",
            "task_head": (task or "")[:240],
            **gate_meta,
        })
        return "claude_subagent unavailable: ANTHROPIC_API_KEY not set"

    try:
        from anthropic import Anthropic
    except Exception as e:
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": False,
            "reason": "sdk_import_failed",
            "error": str(e),
            "task_head": (task or "")[:240],
            **gate_meta,
        })
        return f"claude_subagent unavailable: anthropic SDK import failed: {e}"

    model = os.environ.get("CLAUDE_SUBAGENT_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"
    try:
        mt = int(max_tokens)
    except Exception:
        mt = 1200
    mt = max(200, min(mt, 4096))

    sys_prompt = (
        "You are a specialist subagent called by Enkidu. "
        "Return concise, factual output for the requested task only. "
        "Do not roleplay as the top-level assistant."
    )
    user_prompt = (
        f"Task:\n{task}\n\n"
        f"Context (may be partial):\n{context}\n\n"
        "Output requirements:\n"
        "- Focus only on the task.\n"
        "- If evidence is missing, say exactly what is missing.\n"
        "- Prefer structured headings only when useful."
    )

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=mt,
            system=sys_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        _CLAUDE_SUBAGENT_CALL_TIMES.append(time.time())
        text = response.content[0].text if response.content else ""
        out = (text or "").strip() or "claude_subagent returned empty output"
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": True,
            "reason": reason,
            "model": model,
            "max_tokens": mt,
            "task_head": (task or "")[:240],
            "output_chars": len(out),
            **gate_meta,
        })
        return out
    except Exception as e:
        _audit_claude_subagent({
            "ts": time.time(),
            "tool": "claude_subagent",
            "allowed": True,
            "reason": reason,
            "model": model,
            "max_tokens": mt,
            "task_head": (task or "")[:240],
            "error": str(e),
            **gate_meta,
        })
        return f"claude_subagent error: {e}"


register(
    name="claude_subagent",
    description=(
        "Delegate a heavy or long-context subtask to Claude while Enkidu remains the primary "
        "local orchestrator. Use ONLY when local reasoning is likely insufficient, such as: "
        "very long documents, dense multi-file synthesis, or high-precision second-opinion tasks. "
        "Keep delegated tasks narrow and include only necessary context."
    ),
    parameters={
        "task": "str — narrowly scoped task for Claude to perform",
        "context": "str — optional supporting context excerpt",
        "max_tokens": "int — optional output budget (200-4096, default 1200)",
    },
    fn=_claude_subagent,
)


def _claude_subagent_stats(query: str = "") -> str:
    """Summarize delegation audit events from the JSONL log."""
    path = _claude_subagent_audit_path()
    if not os.path.exists(path):
        return f"claude_subagent_stats: no audit log found at {path}"

    lower = (query or "").lower()
    # Default window: 24h. Supports examples like: "last 60m", "last 7d", "all"
    if "all" in lower:
        window_seconds = 10 * 365 * 24 * 3600
    else:
        window_seconds = 24 * 3600
        m = re.search(r"(\d+)\s*([smhd])", lower)
        if m:
            n = max(1, int(m.group(1)))
            unit = m.group(2)
            if unit == "s":
                window_seconds = n
            elif unit == "m":
                window_seconds = n * 60
            elif unit == "h":
                window_seconds = n * 3600
            elif unit == "d":
                window_seconds = n * 24 * 3600

    now = time.time()
    cutoff = now - window_seconds

    total = 0
    allowed = 0
    blocked = 0
    errors = 0
    reasons: dict[str, int] = {}
    models: dict[str, int] = {}

    try:
        with open(path, "r", encoding="utf-8") as f:
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
                is_allowed = bool(evt.get("allowed", False))
                if is_allowed:
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
    except Exception as e:
        return f"claude_subagent_stats: failed to read audit log: {e}"

    if total == 0:
        return (
            f"claude_subagent_stats: no events in window ({window_seconds}s). "
            f"Log path: {path}"
        )

    allowed_pct = 100.0 * allowed / total
    blocked_pct = 100.0 * blocked / total

    top_reasons = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:6]
    top_models = sorted(models.items(), key=lambda kv: kv[1], reverse=True)[:3]

    lines = [
        "Claude subagent delegation stats:",
        f"  Window: last {window_seconds}s",
        f"  Log: {path}",
        f"  Events: {total}",
        f"  Allowed: {allowed} ({allowed_pct:.1f}%)",
        f"  Blocked: {blocked} ({blocked_pct:.1f}%)",
        f"  Errors: {errors}",
    ]

    if top_reasons:
        lines.append("  Top reasons:")
        for reason, count in top_reasons:
            lines.append(f"    - {reason}: {count}")

    if top_models:
        lines.append("  Models used:")
        for model, count in top_models:
            lines.append(f"    - {model}: {count}")

    return "\n".join(lines)


register(
    name="claude_subagent_stats",
    description=(
        "Summarize local audit logs for Claude delegation decisions. "
        "Use this to tune Gemma-first routing policy and observe allowed/blocked rates. "
        "Query examples: 'last 60m', 'last 7d', 'all'."
    ),
    parameters={
        "query": "str — optional window selector, e.g. 'last 60m', 'last 24h', or 'all'",
    },
    fn=lambda query="": _claude_subagent_stats(query),
)

# ---------------------------------------------------------------------------
# dev_delegate — kick off a code-writing task in the Enkidu Dev system
# ---------------------------------------------------------------------------

def _dev_delegate(goal: str, project: str, context_files: str = "") -> str:
    """
    Create a dev task that delegates code writing to Claude and streams
    progress to the Enkidu DevPanel. Returns the task ID for tracking.
    """
    try:
        import importlib.util as _ilu
        import sys as _sys
        _dev_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "phase6-ui", "server", "dev_tools.py")
        )
        spec = _ilu.spec_from_file_location("dev_tools", _dev_path)
        mod = _ilu.module_from_spec(spec)
        _sys.modules["dev_tools"] = mod   # required: @dataclass resolves cls.__module__ via sys.modules
        spec.loader.exec_module(mod)
    except Exception as e:
        return f"dev_delegate unavailable: {e}"

    files = [f.strip() for f in context_files.split(",") if f.strip()] if context_files else []

    known = list(mod.PROJECT_ROOTS.keys())
    if project.lower() not in known:
        return (
            f"Unknown project '{project}'. Known projects: {', '.join(known)}. "
            "Use one of these exact names."
        )

    task = mod.create_task(goal=goal, project=project.lower(), context_files=files)

    # Fire and forget in a background thread — non-blocking so the agent can continue
    import threading
    t = threading.Thread(target=mod.run_task_sync, args=(task.id,), daemon=True)
    t.start()

    return (
        f"Dev task created (id={task.id}). "
        f"Project: {project}. Status: queued → running.\n"
        f"I will narrate progress here as Claude works. "
        f"Open the Dev panel in Enkidu's UI to see live changes and approve patches."
    )


register(
    name="dev_delegate",
    description=(
        "Delegate a software development task to Claude. Claude will write or modify code "
        "for the specified project (Enkidu, Orator, Avalon, Longinus, Zeus, Babylon, Aristotle). "
        "Results stream live to the Enkidu DevPanel where you can review and approve file changes. "
        "Use this when the user asks to build a feature, fix a bug, create a new component, "
        "refactor code, write tests, or start building a new application in the portfolio."
    ),
    parameters={
        "goal": "str — clear description of what to build or fix",
        "project": "str — target project name, e.g. 'orator', 'avalon', 'enkidu'",
        "context_files": "str — optional comma-separated relative file paths to include as context, e.g. 'src/App.tsx,server/main.py'",
    },
    fn=_dev_delegate,
)


# ---------------------------------------------------------------------------
# dev_read_file / dev_list_files — let the agent inspect any portfolio project
# ---------------------------------------------------------------------------

def _load_dev_tools_module():
    import importlib.util as _ilu
    import sys as _sys
    _dev_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "phase6-ui", "server", "dev_tools.py")
    )
    spec = _ilu.spec_from_file_location("dev_tools", _dev_path)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["dev_tools"] = mod
    spec.loader.exec_module(mod)
    return mod


def _dev_read_file(project: str, path: str) -> str:
    """Read a file from any registered portfolio project. Returns contents or error."""
    try:
        mod = _load_dev_tools_module()
    except Exception as e:
        return f"dev_read_file unavailable: {e}"
    # Use the dev panel password so sensitive files (.env etc.) are still gated
    pw = os.environ.get("ENKIDU_DEV_PASSWORD", "antifragile")
    result = mod.read_file_contents(project.lower(), path, password=pw)
    if "error" in result:
        return f"ERROR: {result['error']}"
    contents = result.get("contents", "")
    if len(contents) > 20000:
        contents = contents[:20000] + f"\n\n... [truncated; file is {len(contents)} chars total]"
    return f"=== {project}/{path} ===\n{contents}"


def _dev_list_files(project: str, sub_path: str = "") -> str:
    """List files in a portfolio project (or subdirectory)."""
    try:
        mod = _load_dev_tools_module()
    except Exception as e:
        return f"dev_list_files unavailable: {e}"
    result = mod.get_file_tree(project.lower(), sub_path)
    if "error" in result:
        return f"ERROR: {result['error']}"

    def _flatten(nodes, prefix=""):
        lines = []
        for n in nodes:
            full = f"{prefix}{n['name']}"
            if n["type"] == "dir":
                lines.append(f"{full}/")
                if n.get("children"):
                    lines.extend(_flatten(n["children"], full + "/"))
            else:
                lock = " 🔒" if n.get("sensitive") else ""
                lines.append(f"{full}{lock}")
        return lines

    files = _flatten(result.get("tree", []))
    if not files:
        return f"(no files found in {project}/{sub_path})"
    if len(files) > 200:
        files = files[:200] + [f"... [{len(files)} total — truncated]"]
    return "\n".join(files)


register(
    name="dev_read_file",
    description=(
        "Read the contents of a file from any portfolio project (enkidu, avalon, orator, longinus, "
        "zeus, babylon, aristotle). Use this when the user asks about code in a specific project "
        "or you need to understand existing code before delegating with dev_delegate. "
        "Sensitive files (.env, keys, credentials) are accessible via the configured dev password."
    ),
    parameters={
        "project": "str — project name, e.g. 'orator', 'avalon', 'enkidu'",
        "path": "str — relative path within the project, e.g. 'server/main.py'",
    },
    fn=_dev_read_file,
)


register(
    name="dev_list_files",
    description=(
        "List the files and directories in a portfolio project. Use this to discover what code "
        "exists in a project before reading specific files with dev_read_file. "
        "Optional sub_path narrows the listing to a subdirectory."
    ),
    parameters={
        "project": "str — project name, e.g. 'orator', 'avalon', 'enkidu'",
        "sub_path": "str — optional subdirectory relative to project root",
    },
    fn=_dev_list_files,
)
