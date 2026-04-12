"""
enkidu.py — main entry point

An interactive CLI loop that routes queries to local Gemma (via Ollama)
or Claude API based on complexity, streams the response, and reports
basic performance stats.

Usage:
    python enkidu.py

Commands (type during the session):
    /local   — force next query to local Gemma
    /cloud   — force next query to Claude API
    /stats   — show session stats
    /exit    — quit

Architecture:
    Your query → router → Gemma (local, free, private)
                       └→ Claude (cloud, smarter, costs ~$0.01-0.05/query)
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

# Pull modules from phase2-tool-use/ — sys.path trick handles the hyphen in the folder name
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "phase2-tool-use"))
from router import route, RoutingTier, RoutingDecision
from tools.system_info import get_context as get_system_context, should_fetch as is_system_query

load_dotenv()

# --- Config ---
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = "gemma4:26b"
CLAUDE_MODEL = "claude-opus-4-6"

# ANSI colors — makes the output easier to scan
GREY   = "\033[90m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


# --- Ollama (local) ---

def stream_ollama(prompt: str) -> dict:
    """
    Send a prompt to local Gemma via Ollama's streaming HTTP API.
    Returns performance stats from Ollama's final response chunk.
    """
    url = f"{OLLAMA_URL}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True}

    start = time.perf_counter()
    first_token_time = None

    try:
        with requests.post(url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            final_chunk = {}

            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)

                if first_token_time is None and chunk.get("response"):
                    first_token_time = time.perf_counter() - start

                if chunk.get("response"):
                    print(chunk["response"], end="", flush=True)

                if chunk.get("done"):
                    final_chunk = chunk

    except requests.exceptions.ConnectionError:
        print(f"\n{YELLOW}Could not connect to Ollama at {OLLAMA_URL}{RESET}")
        print(f"{GREY}Is the Docker container running? Try: docker ps{RESET}")
        return {}
    except requests.exceptions.Timeout:
        print(f"\n{YELLOW}Ollama request timed out after 120s{RESET}")
        return {}

    total_time = time.perf_counter() - start
    eval_tokens = final_chunk.get("eval_count", 0)
    eval_ns = final_chunk.get("eval_duration", 1)
    tokens_per_sec = eval_tokens / (eval_ns / 1e9) if eval_ns else 0

    return {
        "tokens": eval_tokens,
        "total_time": round(total_time, 2),
        "tokens_per_sec": round(tokens_per_sec, 1),
        "first_token": round(first_token_time, 2) if first_token_time else None,
    }


# --- Claude (cloud) ---

def stream_claude(prompt: str) -> dict:
    """
    Send a prompt to Claude API with streaming.
    Falls back gracefully if the API key isn't set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"{YELLOW}ANTHROPIC_API_KEY not set in .env — cannot use cloud fallback{RESET}")
        print(f"{GREY}Add your key to .env and restart{RESET}")
        return {}

    # Import here so missing anthropic package doesn't crash local-only usage
    try:
        from anthropic import Anthropic
    except ImportError:
        print(f"{YELLOW}anthropic package not installed — run: pip install anthropic{RESET}")
        return {}

    client = Anthropic(api_key=api_key)
    start = time.perf_counter()
    first_token_time = None
    output_tokens = 0

    try:
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                if first_token_time is None and text:
                    first_token_time = time.perf_counter() - start
                print(text, end="", flush=True)

            final_msg = stream.get_final_message()
            output_tokens = final_msg.usage.output_tokens

    except Exception as e:
        print(f"\n{YELLOW}Claude API error: {e}{RESET}")
        return {}

    total_time = time.perf_counter() - start
    tokens_per_sec = output_tokens / total_time if total_time > 0 else 0

    return {
        "tokens": output_tokens,
        "total_time": round(total_time, 2),
        "tokens_per_sec": round(tokens_per_sec, 1),
        "first_token": round(first_token_time, 2) if first_token_time else None,
    }


# --- Session stats tracker ---

class SessionStats:
    def __init__(self):
        self.queries = 0
        self.local_queries = 0
        self.cloud_queries = 0
        self.total_tokens = 0

    def record(self, tier: RoutingTier, stats: dict):
        self.queries += 1
        self.total_tokens += stats.get("tokens", 0)
        if tier == RoutingTier.LOCAL:
            self.local_queries += 1
        else:
            self.cloud_queries += 1

    def display(self):
        print(f"\n{GREY}--- Session Stats ---")
        print(f"  Queries:       {self.queries}")
        print(f"  Local (free):  {self.local_queries}")
        print(f"  Cloud (paid):  {self.cloud_queries}")
        print(f"  Total tokens:  {self.total_tokens}{RESET}")


# --- Main loop ---

def main():
    session = SessionStats()
    force_tier = None  # Set by /local or /cloud commands

    print(f"\n{CYAN}Enkidu{RESET} — local AI assistant")
    print(f"{GREY}Local model:  {OLLAMA_MODEL} via Ollama")
    print(f"Cloud model:  {CLAUDE_MODEL} via Anthropic API")
    print(f"Commands:     /local  /cloud  /stats  /exit{RESET}\n")

    while True:
        try:
            query = input(f"{CYAN}>{RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{GREY}Goodbye{RESET}")
            break

        if not query:
            continue

        # Handle slash commands
        if query == "/exit":
            session.display()
            print(f"{GREY}Goodbye{RESET}")
            break
        elif query == "/local":
            force_tier = RoutingTier.LOCAL
            print(f"{GREY}Forcing local for next query{RESET}")
            continue
        elif query == "/cloud":
            force_tier = RoutingTier.CLOUD
            print(f"{GREY}Forcing cloud for next query{RESET}")
            continue
        elif query == "/stats":
            session.display()
            continue

        # Route the query
        decision = route(query, force=force_tier)
        force_tier = None  # Reset after use

        tier_label = f"{GREEN}LOCAL{RESET}" if decision.tier == RoutingTier.LOCAL else f"{YELLOW}CLOUD{RESET}"
        print(f"{GREY}[{tier_label}{GREY}] {decision.reason} (~{decision.estimated_tokens} tokens){RESET}\n")

        # Tool: inject real-time system context if the query is hardware-related
        prompt = query
        if is_system_query(query):
            context = get_system_context()
            prompt = f"{context}\n\nUser question: {query}"
            print(f"{GREY}[TOOL] system_info fetched{RESET}\n")

        # Run inference
        if decision.tier == RoutingTier.LOCAL:
            stats = stream_ollama(prompt)
        else:
            stats = stream_claude(prompt)

        # Print stats footer
        if stats:
            print(f"\n{GREY}[{stats['tokens']} tokens | {stats['total_time']}s | {stats['tokens_per_sec']} tok/s]{RESET}\n")
            session.record(decision.tier, stats)
        else:
            print()


if __name__ == "__main__":
    main()
