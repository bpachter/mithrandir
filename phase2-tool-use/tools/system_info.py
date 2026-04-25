"""
system_info.py — local hardware context tool

Fetches real-time system stats (GPU, CPU, RAM) and returns them as a
formatted string that can be prepended to a prompt as context.

This is the pattern for all Mithrandir tools:
    1. Python fetches real data from the environment
    2. Data is injected into the prompt as [SYSTEM CONTEXT]
    3. The LLM reasons over the provided data — it never touches hardware directly

Requires:
    - psutil (pip install psutil)
    - nvidia-smi in PATH (included with NVIDIA drivers on Windows)
"""

import subprocess
import psutil


def get_gpu_stats() -> dict:
    """
    Query nvidia-smi for real-time GPU stats.
    Returns empty dict if nvidia-smi is unavailable.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,clocks.current.graphics,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}

        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 7:
            return {}

        return {
            "name": parts[0],
            "temperature_c": int(parts[1]),
            "utilization_pct": int(parts[2]),
            "memory_used_mb": int(parts[3]),
            "memory_total_mb": int(parts[4]),
            "clock_mhz": int(parts[5]),
            "power_draw_w": parts[6],
        }

    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return {}


def get_system_stats() -> dict:
    """
    Query CPU and RAM usage via psutil.
    """
    ram = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=0.5)

    return {
        "cpu_pct": cpu_pct,
        "ram_used_gb": round(ram.used / (1024 ** 3), 1),
        "ram_total_gb": round(ram.total / (1024 ** 3), 1),
        "ram_pct": ram.percent,
    }


def get_context() -> str:
    """
    Returns a formatted context block to prepend to a prompt.
    The LLM receives this as factual grounding — it can answer
    questions about current system state without guessing.
    """
    gpu = get_gpu_stats()
    sys_stats = get_system_stats()

    lines = ["[SYSTEM CONTEXT — real-time hardware data]"]

    if gpu:
        mem_used_gb = round(gpu["memory_used_mb"] / 1024, 1)
        mem_total_gb = round(gpu["memory_total_mb"] / 1024, 1)
        lines += [
            f"GPU:          {gpu['name']}",
            f"GPU temp:     {gpu['temperature_c']}°C",
            f"GPU usage:    {gpu['utilization_pct']}%",
            f"VRAM:         {mem_used_gb}GB used / {mem_total_gb}GB total",
            f"GPU clock:    {gpu['clock_mhz']} MHz",
            f"Power draw:   {gpu['power_draw_w']}W",
        ]
    else:
        lines.append("GPU:          nvidia-smi unavailable")

    lines += [
        f"CPU usage:    {sys_stats['cpu_pct']}%",
        f"RAM:          {sys_stats['ram_used_gb']}GB used / {sys_stats['ram_total_gb']}GB total ({sys_stats['ram_pct']}%)",
    ]

    return "\n".join(lines)


# Keywords that signal a system info query — used by mithrandir.py to decide whether to call this tool
TRIGGER_KEYWORDS = [
    "gpu", "vram", "temperature", "temp", "cpu", "ram", "memory",
    "system", "hardware", "performance", "utilization", "watt",
    "power", "clock", "benchmark", "hot", "degrees",
]


def should_fetch(query: str) -> bool:
    """Returns True if the query is likely asking about local hardware."""
    q = query.lower()
    return any(kw in q for kw in TRIGGER_KEYWORDS)


# --- Quick test ---
if __name__ == "__main__":
    print(get_context())
