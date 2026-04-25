"""
web_search.py — Web search for Mithrandir

Primary:  Tavily API (purpose-built for LLM agents — returns full extracted
          page content, not just snippets). Requires TAVILY_API_KEY in .env.

Fallback: DuckDuckGo (ddgs package, no API key, snippet-only results).
          Used automatically if Tavily key is missing or rate-limited.

Two public functions:
    search(query, max_results=6) -> str
        Formatted observation string for the Claude ReAct agent.

    search_context(query, max_results=5) -> str | None
        Compact context block injected into Gemma's system prompt.
        Returns None on complete failure.
"""

import os
import logging

logger = logging.getLogger("mithrandir.web_search")

_MAX_CONTENT_CHARS = 600   # per-result content cap for Tavily full-text
_MAX_SNIPPET_CHARS = 300   # per-result cap for DDG snippets


# ---------------------------------------------------------------------------
# Tavily (primary)
# ---------------------------------------------------------------------------

def _tavily_search(query: str, max_results: int, include_answer: bool = True) -> list[dict] | None:
    """
    Returns a list of result dicts, or None if Tavily is unavailable.
    Each dict has: title, url, content (full extracted text), score.
    Also returns a synthetic 'answer' entry if Tavily provides one.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None, None
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        resp = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=False,
        )
        results = resp.get("results", [])
        answer = resp.get("answer")
        return results, answer
    except Exception as e:
        logger.debug(f"Tavily search failed: {e}")
        return None, None


def _format_tavily(results: list, answer: str | None, query: str) -> str:
    lines = [f"Web search results for: {query}\n"]
    if answer:
        lines.append(f"Summary: {answer}\n")
    for i, r in enumerate(results, 1):
        title   = r.get("title", "").strip()
        url     = r.get("url", "")
        content = (r.get("content") or "").strip()
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"[{i}] {title}\n{content}\n{url}\n")
    return "\n".join(lines).strip()


def _format_tavily_context(results: list, answer: str | None, query: str) -> str:
    lines = ["[Web search results — use these to answer accurately:]"]
    if answer:
        lines.append(f"Direct answer: {answer}")
    for i, r in enumerate(results, 1):
        title   = r.get("title", "").strip()
        url     = r.get("url", "")
        content = (r.get("content") or "").strip()
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"\n[{i}] {title}\n{content}\n{url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DuckDuckGo (fallback)
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int) -> list[dict] | None:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        logger.debug(f"DDG search failed: {e}")
        return None


def _format_ddg(results: list, query: str) -> str:
    lines = [f"Web search results for: {query} [via DuckDuckGo]\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        body  = (r.get("body") or r.get("snippet", "")).strip()
        url   = r.get("href") or r.get("url", "")
        if len(body) > _MAX_SNIPPET_CHARS:
            body = body[:_MAX_SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"[{i}] {title}\n{body}\n{url}\n")
    return "\n".join(lines).strip()


def _format_ddg_context(results: list) -> str:
    lines = ["[Web search results — use these to answer accurately:]"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        body  = (r.get("body") or r.get("snippet", "")).strip()
        url   = r.get("href") or r.get("url", "")
        if len(body) > _MAX_SNIPPET_CHARS:
            body = body[:_MAX_SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"\n[{i}] {title}\n{body}\n{url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search(query: str, max_results: int = 6) -> str:
    """
    Search the web and return formatted results for the Claude ReAct agent.
    Tries Tavily first, falls back to DuckDuckGo.
    """
    results, answer = _tavily_search(query, max_results)
    if results:
        logger.debug(f"web_search: Tavily returned {len(results)} results")
        return _format_tavily(results, answer, query)

    logger.debug("web_search: Tavily unavailable, trying DDG")
    ddg = _ddg_search(query, max_results)
    if ddg:
        return _format_ddg(ddg, query)

    return f"No web results found for: {query}"


def search_context(query: str, max_results: int = 5) -> str | None:
    """
    Search the web and return a compact context block for Gemma's system prompt.
    Returns None on complete failure so the caller skips injection gracefully.
    """
    results, answer = _tavily_search(query, max_results)
    if results:
        logger.debug(f"search_context: Tavily returned {len(results)} results")
        return _format_tavily_context(results, answer, query)

    logger.debug("search_context: Tavily unavailable, trying DDG")
    ddg = _ddg_search(query, max_results)
    if ddg:
        return _format_ddg_context(ddg)

    return None
