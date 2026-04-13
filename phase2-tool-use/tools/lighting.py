"""
lighting.py — RGB lighting effects for Enkidu

Cycles the keyboard through the full color spectrum while local GPU
inference is running. Implemented as a subprocess (not a thread) because
openrgb-python's socket calls only flush to hardware from the main thread.

If OpenRGB isn't running, all calls are silent no-ops.

Requirements:
    - OpenRGB running with SDK Server enabled (port 6742)
    - pip install openrgb-python
"""

import sys
import subprocess
import time
from typing import Optional

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor
    _OPENRGB_AVAILABLE = True
except ImportError:
    _OPENRGB_AVAILABLE = False


# --- Animation subprocess script ---
# Runs as its own process so it owns the main thread and the TCP socket works.

_ANIMATION_SCRIPT = """
import time, sys
try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor
except ImportError:
    sys.exit(0)

def hsv(h):
    h = h % 360
    c = 1.0
    x = c * (1 - abs((h / 60) % 2 - 1))
    if   h < 60:  r,g,b = c,x,0
    elif h < 120: r,g,b = x,c,0
    elif h < 180: r,g,b = 0,c,x
    elif h < 240: r,g,b = 0,x,c
    elif h < 300: r,g,b = x,0,c
    else:         r,g,b = c,0,x
    return RGBColor(int(r*255), int(g*255), int(b*255))

try:
    client = OpenRGBClient(name="Enkidu-anim")
except Exception:
    sys.exit(0)

devices = [d for d in client.devices
           if any(m.name.lower() == "direct" for m in d.modes)]

for d in devices:
    try:
        d.set_mode("Direct")
    except Exception:
        pass

speed = 400   # degrees per second
delay = 0.03  # seconds between frames

start = time.perf_counter()
while True:
    t = time.perf_counter() - start
    color = hsv(t * speed)
    for d in devices:
        try:
            d.set_color(color)
        except Exception:
            pass
    time.sleep(delay)
"""

# --- State ---

_proc: Optional[subprocess.Popen] = None


# --- Public API ---

def inference_start():
    """Launch the animation subprocess. No-op if OpenRGB isn't reachable."""
    global _proc

    if not _OPENRGB_AVAILABLE:
        return
    if _proc and _proc.poll() is None:
        return  # already running

    _proc = subprocess.Popen(
        [sys.executable, "-c", _ANIMATION_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def inference_stop():
    """Kill the animation subprocess and restore lights to off."""
    global _proc

    if _proc:
        _proc.terminate()
        try:
            _proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _proc.kill()
        _proc = None

    # Restore lights to idle color via a fresh connection
    if not _OPENRGB_AVAILABLE:
        return
    try:
        client = OpenRGBClient(name="Enkidu-restore")
        idle = RGBColor(0, 60, 180)  # soft blue — Enkidu idle state
        for device in client.devices:
            try:
                device.set_color(idle)
            except Exception:
                pass
    except Exception:
        pass


# --- Quick test ---
if __name__ == "__main__":
    print("Starting rainbow animation for 10 seconds...")
    inference_start()
    time.sleep(10)
    print("Stopping...")
    inference_stop()
    print("Done.")
