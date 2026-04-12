"""
router.py — Phase 2 query routing logic

Decides whether a query should go to local Gemma (via Ollama) or
Claude API based on estimated complexity.

Design philosophy:
    Start simple. A heuristic router that's wrong 20% of the time
    is still useful — it saves cost and latency on the 80% of queries
    that are genuinely simple. Tune thresholds from real usage data.

Routing tiers:
    LOCAL  — short, factual, or simple queries → Gemma 4 26B (free, fast)
    CLOUD  — complex reasoning, long context, or tool-heavy → Claude API

Signals used to decide (in order of weight):
    1. Token count estimate — long prompts suggest complex tasks
    2. Keyword patterns — words like "analyze", "compare", "explain in depth"
    3. Tool requirement — if tools are needed, route to Claude (better function calling)
    4. Explicit override — caller can force a tier

TODO (after Phase 1 benchmarks):
    - Replace token threshold with a value informed by actual latency data
    - Add confidence-based routing: run Gemma first, if response is low-quality escalate
    - Add cost tracking: log which tier was used and estimated cost per query
"""

import os
from enum import Enum
from dataclasses import dataclass


class RoutingTier(Enum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass
class RoutingDecision:
    tier: RoutingTier
    reason: str
    estimated_tokens: int


# --- Thresholds (tune these after running inference_bench.py) ---

# Queries longer than this are likely complex enough to warrant Claude
# TODO: set based on benchmark results — what token count makes Gemma slow?
TOKEN_THRESHOLD = 500

# Keywords that signal complex reasoning tasks
COMPLEXITY_KEYWORDS = [
    "analyze", "analyse", "compare", "contrast", "evaluate",
    "explain in depth", "step by step", "why does", "how does",
    "what are the implications", "summarize", "critique",
    "pros and cons", "trade-off", "trade off",
]

# Keywords that suggest simple factual lookups — bias toward local
SIMPLE_KEYWORDS = [
    "what is", "who is", "when did", "where is", "define",
    "list", "name", "how many", "what year",
]


def estimate_tokens(text: str) -> int:
    """
    Rough token count estimate without loading a tokenizer.
    Rule of thumb: ~1 token per 4 characters in English text.
    Good enough for routing decisions; not suitable for billing.
    """
    return len(text) // 4


def needs_tools(query: str, tools: list | None = None) -> bool:
    """
    Returns True if this query requires external tool calls.
    Tool use routes to Claude — it has better native function calling
    than Gemma for now. Revisit in Phase 3.
    """
    return tools is not None and len(tools) > 0


def route(query: str, tools: list | None = None, force: RoutingTier | None = None) -> RoutingDecision:
    """
    Decide which inference tier to use for a given query.

    Args:
        query:  The user's input text
        tools:  List of tool definitions to make available (if any)
        force:  Override automatic routing — RoutingTier.LOCAL or RoutingTier.CLOUD

    Returns:
        RoutingDecision with tier, reasoning, and estimated token count
    """
    if force is not None:
        return RoutingDecision(
            tier=force,
            reason=f"forced override: {force.value}",
            estimated_tokens=estimate_tokens(query),
        )

    token_estimate = estimate_tokens(query)
    query_lower = query.lower()

    # Tool use → cloud (Claude handles function calling more reliably)
    if needs_tools(query, tools):
        return RoutingDecision(
            tier=RoutingTier.CLOUD,
            reason="tool use required",
            estimated_tokens=token_estimate,
        )

    # Long context → cloud
    if token_estimate > TOKEN_THRESHOLD:
        return RoutingDecision(
            tier=RoutingTier.CLOUD,
            reason=f"token count ({token_estimate}) exceeds threshold ({TOKEN_THRESHOLD})",
            estimated_tokens=token_estimate,
        )

    # Complexity keywords → cloud
    for keyword in COMPLEXITY_KEYWORDS:
        if keyword in query_lower:
            return RoutingDecision(
                tier=RoutingTier.CLOUD,
                reason=f"complexity keyword detected: '{keyword}'",
                estimated_tokens=token_estimate,
            )

    # Simple keywords → local
    for keyword in SIMPLE_KEYWORDS:
        if query_lower.startswith(keyword):
            return RoutingDecision(
                tier=RoutingTier.LOCAL,
                reason=f"simple query pattern: '{keyword}'",
                estimated_tokens=token_estimate,
            )

    # Default: local (bias toward free/private inference)
    return RoutingDecision(
        tier=RoutingTier.LOCAL,
        reason="default: no complexity signals detected",
        estimated_tokens=token_estimate,
    )


# --- Quick manual test ---
if __name__ == "__main__":
    test_queries = [
        "What is the capital of France?",
        "Analyze the key drivers of inflation in the US economy over the last decade and their policy implications.",
        "List the top 5 S&P 500 companies by market cap.",
        "Compare the Piotroski F-Score and Altman Z-Score as tools for detecting financial distress.",
        "Who is the CEO of Apple?",
        "Explain in depth how transformer attention mechanisms work and why they replaced RNNs.",
    ]

    print(f"{'Query':<60} {'Tier':<8} {'Reason'}")
    print("-" * 100)
    for q in test_queries:
        decision = route(q)
        print(f"{q[:58]:<60} {decision.tier.value:<8} {decision.reason}")
