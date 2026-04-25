"""
startup_lighting.py — Mithrandir idle lighting at Windows logon

Sets the Alienware tower and Corsair keyboard to idle blue and keeps
them there.  Run at logon via Task Scheduler (see install_startup_lighting.bat).

- Corsair iCUE: holds exclusive SDK control so the keyboard stays blue.
- AlienFX:      sets idle blue on the tower; re-applies every 30 s in case
                Alienware Command Center briefly takes the colors back.

Runs silently in the background.  The Mithrandir bot will call
lighting.inference_start() / inference_stop() to override these colors
during inference — that still works because both processes share the same
SDK connection state; the bot overrides our colors, then we restore them
on the next 30-second tick.
"""

import sys
import time
import signal
import logging

# ── Point Python at the Mithrandir package so we can reuse lighting.py ──────────
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(_HERE, "phase2-tool-use", "tools")
sys.path.insert(0, _TOOLS)
sys.path.insert(0, _HERE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_HERE, "startup_lighting.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("startup_lighting")

# ── Import lighting backend ──────────────────────────────────────────────────
try:
    import lighting
except ImportError as exc:
    log.error(f"Could not import lighting module from {_TOOLS}: {exc}")
    sys.exit(1)

# ── Graceful shutdown ────────────────────────────────────────────────────────
_running = True

def _shutdown(signum, frame):
    global _running
    log.info("Shutdown signal received — releasing lighting control.")
    _running = False

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


def _wait_for_icue(timeout_s: int = 120) -> bool:
    """
    Poll until iCUE SDK connects or timeout expires.
    iCUE can take 30–90 s to fully start after logon.
    Returns True if connection succeeded.
    """
    log.info(f"Waiting for iCUE SDK (up to {timeout_s}s)…")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _running:
        # Force a fresh SDK connection attempt by resetting the singleton.
        with lighting._sdk_lock:
            lighting._sdk = None
        sdk = lighting._get_sdk()
        if sdk is not None:
            devices = lighting._get_devices(sdk)
            if devices:
                log.info(f"iCUE SDK connected — {len(devices)} device(s) found.")
                return True
        log.info("iCUE not ready yet, retrying in 10 s…")
        time.sleep(10)
    log.warning("iCUE SDK never became available — keyboard color skipped.")
    return False


def main():
    # Tower: leave entirely to AWCC — no LightFX calls at idle.

    # Keyboard: wait for iCUE, then release Corsair SDK control so iCUE
    # runs its own theme.  The Mithrandir bot takes over both devices during
    # inference and releases them again when it finishes.
    icue_ok = _wait_for_icue(timeout_s=120)
    if icue_ok:
        lighting._corsair_release_control()
        log.info("Corsair control released — iCUE running its own theme.")
    else:
        log.warning("iCUE never came up; keyboard theme unchanged.")

    log.info("Startup lighting done — AWCC and iCUE own idle state.")


if __name__ == "__main__":
    main()
