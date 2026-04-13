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
import importlib.util
from typing import Callable


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
