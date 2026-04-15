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
import subprocess
import importlib.util
from typing import Callable

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


def dispatch(name: str, **kwargs) -> str:
    """
    Call a registered tool by name. Returns the observation string.
    Returns an error message (not an exception) if the tool is unknown or fails,
    so the agent can reason about the failure rather than crashing.
    """
    if name not in TOOLS:
        known = ", ".join(TOOLS.keys())
        return f"Error: unknown tool '{name}'. Available tools: {known}"
    try:
        return TOOLS[name]["fn"](**kwargs)
    except TypeError as e:
        return f"Error: wrong arguments for tool '{name}': {e}"
    except Exception as e:
        return f"Error running tool '{name}': {e}"


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
        "Execute Python code and return stdout. Use for arithmetic, CAGR calculations, "
        "ratio comparisons, portfolio statistics, or any computation where you need "
        "exact numbers rather than estimates. Has access to math, statistics, and numpy."
    ),
    parameters={
        "code": "str — valid Python code to execute"
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
