"""
inference_bench.py — Phase 1 benchmark

Sends the same prompt to both local Gemma (via Ollama) and Claude API,
measures latency and throughput, and prints a side-by-side comparison.

Usage:
    python inference_bench.py

Requirements:
    - Ollama container running with gemma4:26b pulled
    - .env file with ANTHROPIC_API_KEY in the project root
"""

import os
import time
import json
import requests
from dotenv import load_dotenv
from anthropic import Anthropic

# Load .env from the project root (one level up from this file)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = "gemma4:26b"

# The same prompt sent to both models for a fair comparison
BENCHMARK_PROMPT = (
    "Explain how a transformer neural network works. "
    "Be thorough but concise. Aim for about 200 words."
)


def bench_ollama(prompt: str) -> dict:
    """
    Call Ollama's streaming API and measure:
    - Time to first token (how long before the model starts responding)
    - Total generation time
    - Tokens per second (from Ollama's own stats)
    - Total tokens generated

    Ollama streams NDJSON — each line is a JSON object.
    The final line (done=true) contains timing stats in nanoseconds.
    """
    url = f"{OLLAMA_URL}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True}

    print(f"\n{'='*60}")
    print(f"LOCAL — {OLLAMA_MODEL} via Ollama")
    print(f"{'='*60}")

    start = time.perf_counter()
    first_token_time = None
    full_response = []
    final_stats = {}

    try:
        with requests.post(url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)

                # Capture time to first token on the first non-empty response
                if first_token_time is None and chunk.get("response"):
                    first_token_time = time.perf_counter() - start
                    print(f"[First token at {first_token_time:.2f}s]\n")

                if chunk.get("response"):
                    print(chunk["response"], end="", flush=True)
                    full_response.append(chunk["response"])

                # The final chunk (done=True) contains Ollama's built-in timing stats
                if chunk.get("done"):
                    final_stats = chunk

    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to Ollama. Is the container running?")
        print(f"       Expected Ollama at: {OLLAMA_URL}")
        return {}
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out after 120 seconds.")
        return {}

    total_time = time.perf_counter() - start

    # Ollama reports eval_duration in nanoseconds and eval_count in tokens
    eval_tokens = final_stats.get("eval_count", 0)
    eval_duration_ns = final_stats.get("eval_duration", 1)
    tokens_per_sec = eval_tokens / (eval_duration_ns / 1e9) if eval_duration_ns else 0

    return {
        "model": OLLAMA_MODEL,
        "provider": "local (Ollama)",
        "time_to_first_token_s": round(first_token_time, 3) if first_token_time else None,
        "total_time_s": round(total_time, 3),
        "tokens_generated": eval_tokens,
        "tokens_per_sec": round(tokens_per_sec, 1),
        "response": "".join(full_response),
    }


def bench_claude(prompt: str) -> dict:
    """
    Call Claude API with streaming and measure the same metrics.
    Claude's streaming chunks don't include per-token timing, so we
    measure wall-clock time to first token and total time ourselves.
    Token counts come from the final message_delta usage event.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nSkipping Claude benchmark — ANTHROPIC_API_KEY not set in .env")
        return {}

    client = Anthropic(api_key=api_key)
    model = "claude-opus-4-6"

    print(f"\n{'='*60}")
    print(f"CLOUD — {model} via Anthropic API")
    print(f"{'='*60}")

    start = time.perf_counter()
    first_token_time = None
    full_response = []
    output_tokens = 0

    try:
        with client.messages.stream(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                if first_token_time is None and text:
                    first_token_time = time.perf_counter() - start
                    print(f"[First token at {first_token_time:.2f}s]\n")
                print(text, end="", flush=True)
                full_response.append(text)

            # Final message has usage stats
            final_msg = stream.get_final_message()
            output_tokens = final_msg.usage.output_tokens

    except Exception as e:
        print(f"ERROR calling Claude API: {e}")
        return {}

    total_time = time.perf_counter() - start
    tokens_per_sec = output_tokens / total_time if total_time > 0 else 0

    return {
        "model": model,
        "provider": "cloud (Anthropic API)",
        "time_to_first_token_s": round(first_token_time, 3) if first_token_time else None,
        "total_time_s": round(total_time, 3),
        "tokens_generated": output_tokens,
        "tokens_per_sec": round(tokens_per_sec, 1),
        "response": "".join(full_response),
    }


def print_comparison(local: dict, cloud: dict):
    """Print a side-by-side summary table of the two results."""
    print(f"\n\n{'='*60}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"Prompt: {BENCHMARK_PROMPT[:80]}...")
    print()

    rows = [
        ("Model", "model"),
        ("Provider", "provider"),
        ("Time to first token", "time_to_first_token_s"),
        ("Total time", "total_time_s"),
        ("Tokens generated", "tokens_generated"),
        ("Tokens / second", "tokens_per_sec"),
    ]

    col_w = 24
    print(f"{'Metric':<{col_w}} {'Local':<{col_w}} {'Cloud':<{col_w}}")
    print("-" * (col_w * 3))

    for label, key in rows:
        local_val = str(local.get(key, "N/A"))
        cloud_val = str(cloud.get(key, "N/A"))
        # Add units where helpful
        if key in ("time_to_first_token_s", "total_time_s"):
            local_val = f"{local_val}s" if local_val != "N/A" else local_val
            cloud_val = f"{cloud_val}s" if cloud_val != "N/A" else cloud_val
        elif key == "tokens_per_sec":
            local_val = f"{local_val} tok/s" if local_val != "N/A" else local_val
            cloud_val = f"{cloud_val} tok/s" if cloud_val != "N/A" else cloud_val
        print(f"{label:<{col_w}} {local_val:<{col_w}} {cloud_val:<{col_w}}")

    print()
    print("NOTE: Claude API times include network round-trip to Anthropic's servers.")
    print("      Local times are purely GPU compute — no network involved.")


if __name__ == "__main__":
    print(f"Benchmark prompt:\n{BENCHMARK_PROMPT}\n")
    print("Running benchmarks — this may take a minute on first run")
    print("(first inference loads the model into VRAM)\n")

    local_results = bench_ollama(BENCHMARK_PROMPT)
    cloud_results = bench_claude(BENCHMARK_PROMPT)

    if local_results or cloud_results:
        print_comparison(local_results, cloud_results)
