"""
enkidu_agent.py — ReAct agent loop (Phase 3 core)

Replaces the single-shot prompt injection of enkidu.py with a multi-step
Reason → Act → Observe loop. The LLM reasons about which tools to call,
calls them, observes the results, and loops until it produces a final answer.

Pattern: ReAct (Yao et al., 2022)
    https://arxiv.org/abs/2210.03629

At each step the LLM outputs one of two JSON shapes:

    Tool call:
        {
          "thought": "I need to look up NUE before I can compare.",
          "action": "edgar_screener",
          "action_input": {"query": "NUE"}
        }

    Final answer:
        {
          "thought": "I have all the data I need.",
          "final_answer": "NUE trades at 6.2x EV/EBIT..."
        }

When the LLM outputs malformed JSON or an unknown tool name, the validation
error is fed back as a user turn so the agent can self-correct before giving up.

Usage:
    from enkidu_agent import run_agent

    answer = run_agent(
        "Compare NUE and CLF on EV/EBIT",
        on_step=lambda msg: print(msg),   # optional progress callback
    )
"""

import os
import re
import sys
import json
from typing import Callable, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator, ValidationError

load_dotenv()

# Lighting can crash some environments due native SDK/DLL interactions.
# Keep it opt-in so chat reliability is never blocked by RGB control.
_ENABLE_LIGHTING = os.environ.get("ENKIDU_ENABLE_LIGHTING", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

# Pull tool registry from phase3-agents/tools/
_tools_path = os.path.join(os.path.dirname(__file__), "tools")
if _tools_path not in sys.path:
    sys.path.insert(0, _tools_path)

from registry import TOOLS, dispatch, tool_descriptions, get_regime, _call_memory_bridge  # noqa: E402

# Optional RGB lighting — phase2-tool-use/tools/lighting.py
# Disabled by default for stability; enable with ENKIDU_ENABLE_LIGHTING=1.
if _ENABLE_LIGHTING:
    _lighting_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "phase2-tool-use", "tools"))
    if _lighting_path not in sys.path:
        sys.path.insert(0, _lighting_path)
    try:
        from lighting import inference_start as _lighting_start, inference_stop as _lighting_stop
    except Exception:
        def _lighting_start():
            pass

        def _lighting_stop():
            pass
else:
    def _lighting_start():
        pass

    def _lighting_stop():
        pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 8

# Sonnet is better cost/quality for agentic loops than Opus.
# It produces reliable structured JSON and handles multi-step reasoning well.
CLAUDE_MODEL = "claude-sonnet-4-6"

# Local Ollama inference — used for general queries that don't need tools.
# Backward compatible with older .env files that use OLLAMA_HOST.
OLLAMA_URL = os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
_FORCE_LOCAL_ONLY = os.environ.get("ENKIDU_FORCE_LOCAL_ONLY", "0").strip().lower() in {
    "1", "true", "yes", "on"
}


# ---------------------------------------------------------------------------
# Pydantic schema — every LLM output is validated against this
# ---------------------------------------------------------------------------

class AgentStep(BaseModel):
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict] = None
    final_answer: Optional[str] = None

    @field_validator("action")
    @classmethod
    def action_must_be_registered(cls, v):
        if v is not None and v not in TOOLS:
            known = ", ".join(TOOLS.keys())
            raise ValueError(f"Unknown tool '{v}'. Registered tools: {known}")
        return v


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are Enkidu, an AI assistant with access to financial data tools and a Python sandbox.

You reason step by step using the ReAct pattern. At each step output ONLY a JSON object — \
no prose before or after, no markdown fences.

When you need to call a tool:
{{
  "thought": "what you need and why",
  "action": "tool_name",
  "action_input": {{"param": "value"}}
}}

When you have enough information to answer the user:
{{
  "thought": "I have everything I need.",
  "final_answer": "your complete, specific answer"
}}

Available tools:
{tools}

Market context (injected automatically — do not call market_regime unless user asks for detail):
{regime}

{memory}

Rules:
- Output ONLY valid JSON. No markdown. No commentary outside the JSON.
- Call tools when you need data you don't have. Do not guess numbers.
- After each tool observation, decide: do you need more data or can you answer?
- Be specific — cite actual figures from tool results in your final answer.
- If asked to compare two stocks, call edgar_screener for each one separately.
- Use python_sandbox for any arithmetic (CAGR, blended metrics, ratios, etc.).
- Let the market regime inform your screening commentary (e.g. tighten filters in Contraction/Crisis).
- If memory context is provided above, use it to give more grounded, personalized answers.
- Maximum {max_iter} iterations. If you hit the limit, give your best answer with what you have.
"""


def _build_system_prompt(user_message: str = "") -> str:
    try:
        regime_info = get_regime()
        regime_block = (
            f"Current market regime: {regime_info['regime']} "
            f"(confidence: {regime_info['confidence']:.0%}, as of {regime_info['as_of']}). "
            f"SPY weekly return: {regime_info['weekly_return']:+.2%}, "
            f"30d volatility: {regime_info['volatility_30d']:.2%}, "
            f"price vs 200MA: {regime_info['price_vs_200ma']:.3f}x."
        )
    except Exception:
        regime_block = "Market regime: unavailable."

    memory_block = ""
    if user_message:
        retrieved = _call_memory_bridge("retrieve", user_message, timeout=10)
        if retrieved and not retrieved.startswith("["):
            memory_block = retrieved

    return _SYSTEM_TEMPLATE.format(
        tools=tool_descriptions(),
        max_iter=MAX_ITERATIONS,
        regime=regime_block,
        memory=memory_block,
    )


# ---------------------------------------------------------------------------
# JSON parsing + validation
# ---------------------------------------------------------------------------

def _parse_step(raw: str) -> tuple[Optional[AgentStep], Optional[str]]:
    """
    Parse and validate a raw LLM response string.

    Returns:
        (AgentStep, None)    on success
        (None, error_msg)    on failure — error_msg is fed back to the LLM
    """
    # Strip markdown code fences if the LLM wraps output in ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # If the LLM included prose before the JSON, try to extract just the JSON
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return None, (
            f"Your output was not valid JSON: {e}\n"
            f"Your output (first 300 chars): {raw[:300]}\n"
            f"Output ONLY a JSON object with no surrounding text."
        )

    try:
        step = AgentStep(**data)
    except ValidationError as e:
        errors = "; ".join(err["msg"] for err in e.errors())
        return None, (
            f"JSON schema error: {errors}\n"
            f"Available tools: {', '.join(TOOLS.keys())}\n"
            f"Try again with a valid action or final_answer."
        )

    return step, None


# ---------------------------------------------------------------------------
# Routing — local GPU vs Claude
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Web search augmentation for Gemma (local path)
# ---------------------------------------------------------------------------

def _web_augment(query: str, on_step=None) -> str | None:
    """
    Run a DuckDuckGo search and return a compact context string for Gemma.
    Returns None if search fails or is unnecessary.
    """
    try:
        _web_path = os.path.join(os.path.dirname(__file__), "tools", "web_search.py")
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("web_search_tool", _web_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.search_context(query, max_results=4)
    except Exception:
        return None


# Keywords that signal the agent needs a tool call.
# Anything matching → Claude ReAct loop.
# No match → Ollama direct call (faster, free, private).
_TOOL_KEYWORDS = [
    # Financial data (edgar_screener)
    "stock", "stocks", "ticker", "portfolio", "screener",
    "undervalued", "overvalued", "valuation",
    "ev/ebit", "p/e", "p/b", "fcf", "free cash flow", "ebit", "revenue", "earnings",
    "market cap", "piotroski", "f-score", "dividend",
    "debt", "qv", "quantitative value", "balance sheet",
    "top 5", "top 10", "top 15", "top 20", "top 25",
    "best stocks", "cheap stocks", "buy", "sector",
    # System info
    "gpu", "cpu", "ram", "vram", "temperature", "system stats",
    "memory usage", "load average",
    # Market regime
    "regime", "market condition", "bull market", "bear market",
    "expansion", "contraction", "crisis", "recovery", "spy",
    # Computation
    "calculate", "compute", "cagr", "compound", "annualized",
    # QV signal / performance
    "performance", "alpha", "backtesting", "track record",
    "signal return", "how has the model", "watchlist", "picks",
    "snapshot", "ranking",
    # Memory / docs
    "remember", "last time", "previous conversation",
    "past conversation", "search docs", "history",
    # Explicit web search request → Claude handles it with the web_search tool
    "search the web", "search online", "search internet", "look up online",
    "browse", "find online",
]

# All-caps words that look like tickers but aren't (common English, tech terms)
_TICKER_BLOCKLIST = {
    "I", "A", "OK", "TV", "AI", "API", "URL", "PC", "USB", "ID",
    "NO", "SO", "GO", "DO", "BE", "IS", "IT", "AM", "PM",
    "US", "UK", "EU", "UN",
    "THE", "AND", "OR", "FOR", "IN", "ON", "AT", "TO", "OF",
    "GPU", "CPU", "RAM",  # handled by keyword list above
}

_TICKER_RE = re.compile(r'\b[A-Z]{2,5}\b')


def _needs_tools(query: str) -> bool:
    """
    Return True if this query should go through the Claude ReAct loop.
    False means the query can be answered by Gemma directly.

    Conservative: when in doubt, returns True (routes to Claude).
    The cost of an unnecessary Claude call is low; the cost of answering
    a financial query with Gemma's parametric knowledge is high (stale data).
    """
    lower = query.lower()

    for kw in _TOOL_KEYWORDS:
        if kw in lower:
            return True

    # Uppercase words that look like stock tickers (2–5 letters, not in blocklist)
    for match in _TICKER_RE.findall(query):
        if match not in _TICKER_BLOCKLIST:
            return True

    return False


def _build_local_system_prompt(user_message: str = "", web_context: str | None = None) -> str:
    """
    Simpler system prompt for direct Gemma calls — no JSON schema, no tool list.
    Includes regime context, memory, and optional live web search results.
    """
    try:
        regime_info = get_regime()
        regime_block = (
            f"Current market regime: {regime_info['regime']} "
            f"(confidence: {regime_info['confidence']:.0%}). "
            f"SPY weekly return: {regime_info['weekly_return']:+.2%}, "
            f"30d volatility: {regime_info['volatility_30d']:.2%}."
        )
    except Exception:
        regime_block = ""

    memory_block = ""
    if user_message:
        retrieved = _call_memory_bridge("retrieve", user_message, timeout=10)
        if retrieved and not retrieved.startswith("["):
            memory_block = f"\nRelevant past context:\n{retrieved}"

    parts = [
        "You are Enkidu, a personal AI assistant built by Ben and running locally on his machine "
        "(an NVIDIA RTX 4090 GPU, Windows 11). You are powered by Gemma 4 26B via Ollama. "
        "You are not running on Google's servers or any cloud infrastructure — you run entirely "
        "on Ben's home hardware. Ben built you as a privacy-first local assistant.\n"
        "\n"
        "Respond in plain prose. Do not use bullet points, headers, or markdown formatting "
        "unless the user specifically asks for a list or structured output. "
        "Write like a knowledgeable friend giving a real answer, not like a corporate FAQ. "
        "Match the depth of your answer to the complexity of the question: short questions "
        "get concise answers, complex or personal questions get thorough, nuanced responses. "
        "Never pad with filler phrases like 'Great question!' or 'Certainly!'. "
        "If you don't know something, say so directly."
    ]
    if web_context:
        parts.append(
            f"\n{web_context}\n"
            "IMPORTANT: The web search results above were fetched live from the internet "
            "right now, before this conversation turn. You DO have access to current web "
            "information via this pre-search mechanism. Use these results to give an accurate, "
            "up-to-date answer. Synthesize the information — do not copy snippets verbatim. "
            "Cite sources naturally only if it adds value (e.g. 'according to their website...'). "
            "If the results don't contain what's needed, say so and suggest where to look."
        )
    if regime_block:
        parts.append(f"\nMarket context (for reference only — do not mention unless relevant): {regime_block}")
    if memory_block:
        parts.append(memory_block)

    return "\n".join(parts)


def _run_local(query: str, on_step: Optional[Callable[[str], None]] = None, save_memory: bool = True, prior_messages: Optional[list] = None) -> Optional[str]:
    """
    Send a query directly to Ollama with streaming enabled.

    Streams tokens as they arrive and calls on_step() with partial output
    every ~1.5 seconds so the Telegram placeholder message updates live.

    Returns the complete response string, or None if Ollama is unreachable
    (caller falls back to Claude).

    Timeouts:
        connect=90s  — allows cold model load from disk (~18GB, takes 30-60s)
        read=300s    — maximum time for the full streamed response
    """
    import requests as _req
    import time as _time

    if on_step:
        on_step(f"Running on local GPU ({OLLAMA_MODEL})...")

    # Always fetch live web results to ground Gemma's answer in current info.
    # DDG is ~0.5s and free; if the search fails or returns nothing, web_context
    # is None and Gemma falls back to its parametric knowledge gracefully.
    if on_step:
        on_step("Searching the web...")
    web_context = _web_augment(query)

    system = _build_local_system_prompt(query, web_context=web_context)

    try:
        resp = _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    *(prior_messages or []),
                    {"role": "user", "content": query},
                ],
                "stream": True,
            },
            stream=True,
            timeout=(180, 300),  # (connect, read) — 3 min for cold 26B model load
        )
        resp.raise_for_status()

        tokens: list[str] = []
        last_edit = 0.0

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            token = chunk.get("message", {}).get("content", "")
            if token:
                tokens.append(token)

                # Rate-limited Telegram update — show tail of partial response
                now = _time.monotonic()
                if on_step and now - last_edit >= 1.5 and len(tokens) > 5:
                    partial = "".join(tokens)
                    preview = partial[-300:] if len(partial) > 300 else partial
                    on_step(preview)
                    last_edit = now

            if chunk.get("done"):
                break

        answer = "".join(tokens).strip()
        if not answer:
            return None

        # Save to memory asynchronously (skip when caller owns the save)
        if save_memory:
            try:
                import threading
                threading.Thread(
                    target=_call_memory_bridge,
                    args=("save", query, answer),
                    daemon=True,
                ).start()
            except Exception:
                pass

        return answer

    except Exception as e:
        import logging
        logging.getLogger("enkidu.agent").warning(f"Ollama unavailable: {e}")
        return None


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def run_agent(
    user_message: str,
    on_step: Optional[Callable[[str], None]] = None,
    save_memory: bool = True,
    prior_messages: Optional[list] = None,
) -> str:
    """
    Run the ReAct loop for a single user message.

    Args:
        user_message: The user's query text
        on_step:      Optional callback — called with a short status string
                      at each loop iteration (for live Telegram progress updates)
        save_memory:  If False, skip saving to memory (caller handles it).
                      Use False from Telegram so the interface can capture the
                      exchange ID for rating buttons.

    Returns:
        The agent's final answer as a plain string.
        Never raises — errors are returned as readable strings.
    """
    _lighting_start()
    try:
        return _run_agent_inner(user_message, on_step=on_step, save_memory=save_memory, prior_messages=prior_messages)
    finally:
        _lighting_stop()


def _run_agent_inner(
    user_message: str,
    on_step: Optional[Callable[[str], None]] = None,
    save_memory: bool = True,
    prior_messages: Optional[list] = None,
) -> str:
    # --- Routing decision ---
    if _FORCE_LOCAL_ONLY:
        if on_step:
            on_step(f"Routing: forced local GPU ({OLLAMA_MODEL})")
        result = _run_local(user_message, on_step=on_step, save_memory=save_memory, prior_messages=prior_messages)
        if result is not None:
            return result
        return (
            "Error: local mode is forced but Ollama is unavailable. "
            "Start Ollama or disable ENKIDU_FORCE_LOCAL_ONLY."
        )

    if not _needs_tools(user_message):
        if on_step:
            on_step(f"Routing: local GPU ({OLLAMA_MODEL})")
        result = _run_local(user_message, on_step=on_step, save_memory=save_memory, prior_messages=prior_messages)
        if result is not None:
            return result
        # Ollama unreachable — fall through to Claude
        if on_step:
            on_step("Local GPU unavailable, falling back to cloud...")
    elif on_step:
        on_step("Routing: cloud tool mode (query requires tools/live data)")

    try:
        from anthropic import Anthropic
    except ImportError:
        return "Error: anthropic package not installed. Run: pip install anthropic"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY not set in .env"

    client = Anthropic(api_key=api_key)
    system_prompt = _build_system_prompt(user_message)

    # Message history for the LLM — grows as the loop runs.
    # Prepend prior exchange if continuing a conversation.
    messages = [*(prior_messages or []), {"role": "user", "content": user_message}]

    for iteration in range(MAX_ITERATIONS):

        # --- Call the LLM ---
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )
        except Exception as e:
            return f"Claude API error: {e}"

        raw = response.content[0].text

        # --- Parse and validate ---
        step, error = _parse_step(raw)

        if error:
            # Self-correction: append the bad output + error, then retry
            if on_step:
                on_step("⚠️ Fixing malformed output, retrying...")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": error})
            continue

        # --- Final answer ---
        if step.final_answer:
            # Persist to memory asynchronously (skip when caller owns the save)
            if save_memory:
                try:
                    import threading
                    threading.Thread(
                        target=_call_memory_bridge,
                        args=("save", user_message, step.final_answer),
                        daemon=True,
                    ).start()
                except Exception:
                    pass
            return step.final_answer

        # --- Tool call ---
        if step.action and step.action_input is not None:
            tool_name = step.action
            tool_args = step.action_input

            if on_step:
                on_step(f"🔧 Calling `{tool_name}`...")

            observation = dispatch(tool_name, **tool_args)

            # Truncate very long observations so they don't consume the context window
            if len(observation) > 3000:
                observation = observation[:3000] + "\n[...truncated]"

            if on_step:
                on_step(f"📊 Got result from `{tool_name}`, reasoning...")

            # Append this turn to history
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"[OBSERVATION from {tool_name}]\n"
                    f"{observation}\n\n"
                    f"Continue reasoning. Output your next JSON step."
                ),
            })

        else:
            # Valid schema but neither final_answer nor action+action_input
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "Your JSON is missing required fields. "
                    "Include either 'action' + 'action_input' to call a tool, "
                    "or 'final_answer' to respond to the user."
                ),
            })

    # Reached MAX_ITERATIONS — ask Claude to summarize what it has rather than hard-failing
    try:
        messages.append({
            "role": "user",
            "content": (
                "You've reached the iteration limit. Based on everything you've observed so far, "
                "give your best answer to the user's original question. "
                "Output JSON with only 'thought' and 'final_answer' fields."
            ),
        })
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        step, _ = _parse_step(response.content[0].text)
        if step and step.final_answer:
            return step.final_answer
    except Exception:
        pass

    return (
        "I reached my reasoning limit without completing an answer. "
        "Try rephrasing or breaking this into a simpler question."
    )


# ---------------------------------------------------------------------------
# CLI test mode — run directly to verify the agent works before Telegram
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    query = " ".join(_sys.argv[1:]) if len(_sys.argv) > 1 else "What are the top 5 undervalued stocks right now?"

    print(f"Query: {query}\n")
    print("-" * 60)

    def _print_step(msg: str):
        print(f"  {msg}")

    answer = run_agent(query, on_step=_print_step)

    print("-" * 60)
    print(f"\n{answer}\n")
