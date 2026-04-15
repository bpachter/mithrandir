"""
lighting.py — RGB lighting effects for Enkidu

Controls two separate lighting systems:

1. Corsair iCUE SDK (cuesdk) — Corsair K70 and any other iCUE devices.
   Strategy: hold exclusive SDK control during idle (showing soft blue);
   RELEASE control during inference so iCUE resumes its active preset
   (set "Rain" as your active iCUE theme — it plays automatically while
   Enkidu is thinking, then our idle blue returns when it's done).

   Requirements:
       pip install cuesdk
       iCUE 5 running with SDK enabled (iCUE → Settings → Enable SDK)
       Python must be approved: on first run, click Approve in the iCUE
       system-tray notification that pops up.

2. Alienware LightFX (AlienFX) — Aurora R15 chassis lights.
   Sets idle blue on inference_stop(); leaves the ACC theme running
   during inference (ACC manages the tower while Enkidu is thinking).

   Requirements:
       LightFX.dll present (installed by Alienware Command Center;
       typically at C:\\Windows\\System32\\LightFX.dll)

Both backends are independent — if one is unavailable the other still works.

Public API:
    initialize()       — take Corsair control + set idle blue at bot startup
    inference_start()  — release Corsair control → iCUE Rain plays
    inference_stop()   — take Corsair control back + set idle blue everywhere
"""

import ctypes
import math
import os
import time
import threading
import logging
from typing import Optional

logger = logging.getLogger("enkidu.lighting")

_USE_CORSAIR = os.environ.get("ENKIDU_LIGHTING_CORSAIR", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
_USE_ALIENFX = os.environ.get("ENKIDU_LIGHTING_ALIENFX", "1").strip().lower() in {
    "1", "true", "yes", "on"
}

try:
    from cuesdk import (
        CueSdk,
        CorsairLedColor,
        CorsairSessionState,
        CorsairDeviceFilter,
        CorsairDeviceType,
        CorsairAccessLevel,
    )
    _CUESDK_AVAILABLE = True
except ImportError:
    _CUESDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# AlienFX / LightFX backend (Alienware Aurora R15 chassis lighting)
# ---------------------------------------------------------------------------

class _AlienFXBackend:
    """
    Thin wrapper around LightFX.dll.
    Initialised lazily on first use so that logging is already configured.
    All methods are no-ops if the DLL is not present.
    """

    # Prefer the AWCC-bundled LightFX.dll over the legacy System32 stub.
    # The AWCC SDK x64 DLL actually routes calls to the running AWCC service.
    _DLL_SEARCH_ORDER = [
        r"C:\Program Files\Alienware\Alienware Command Center\AlienFX SDK\DLLs\x64\LightFX.dll",
        r"C:\Program Files\Alienware\Alienware Command Center\AlienFX64.dll",
        "LightFX",   # fallback — System32 stub (may do nothing on AWCC 5+)
    ]

    def __init__(self):
        self._lfx: Optional[ctypes.WinDLL] = None
        self._num_lights: int = 0
        self._dll_path: str = ""
        self._ready = False
        self._attempted = False

    def _ensure_init(self) -> None:
        if self._attempted:
            return
        self._attempted = True
        for dll_path in self._DLL_SEARCH_ORDER:
            try:
                lfx = ctypes.WinDLL(dll_path)
                ret = lfx.LFX_Initialize()
                if ret != 0:
                    logger.debug(f"lighting: {dll_path} LFX_Initialize={ret}, trying next")
                    try:
                        lfx.LFX_Release()
                    except Exception:
                        pass
                    continue

                num_devices = ctypes.c_uint(0)
                lfx.LFX_GetNumDevices(ctypes.byref(num_devices))
                if num_devices.value == 0:
                    logger.debug(f"lighting: {dll_path} — 0 devices, trying next")
                    try:
                        lfx.LFX_Release()
                    except Exception:
                        pass
                    continue

                num_lights = ctypes.c_uint(0)
                lfx.LFX_GetNumLights(0, ctypes.byref(num_lights))
                self._num_lights = num_lights.value
                self._lfx = lfx
                self._dll_path = dll_path
                self._ready = True
                logger.debug(
                    f"lighting: AlienFX ready via {dll_path!r} — {self._num_lights} lights"
                )
                return
            except OSError:
                logger.debug(f"lighting: {dll_path!r} not loadable, trying next")
        logger.debug("lighting: no working LightFX DLL found")

    def set_all(self, r: int, g: int, b: int, brightness: int = 255) -> None:
        """Set all zones to one color using LFX_Light(LFX_ALL, packed_dword)."""
        self._ensure_init()
        if not self._ready or self._lfx is None:
            return
        try:
            packed = (brightness << 24) | (r << 16) | (g << 8) | b
            # Do NOT call LFX_Reset() here — on the AWCC SDK it flushes black
            # to hardware immediately, causing a visible flash before LFX_Update
            # commits our color.  LFX_Light(LFX_ALL) covers every light anyway.
            self._lfx.LFX_Light(0x07FFFFFF, packed)  # LFX_ALL
            self._lfx.LFX_Update()
        except Exception as e:
            logger.debug(f"lighting: AlienFX set_all failed: {e}")

    @property
    def ready(self) -> bool:
        self._ensure_init()
        return self._ready


_alienfw = _AlienFXBackend()


# ---------------------------------------------------------------------------
# Corsair iCUE SDK — shared singleton connection
# ---------------------------------------------------------------------------

_sdk: Optional["CueSdk"] = None
_sdk_lock = threading.Lock()


def _get_sdk() -> Optional["CueSdk"]:
    """Return a connected CueSdk instance, or None if unavailable."""
    global _sdk
    if not _CUESDK_AVAILABLE:
        return None
    with _sdk_lock:
        if _sdk is not None:
            return _sdk
        try:
            sdk = CueSdk()
            connected = threading.Event()

            def _on_state(evt):
                if evt and evt.state == CorsairSessionState.CSS_Connected:
                    connected.set()
                elif evt and evt.state in (
                    CorsairSessionState.CSS_Closed,
                    CorsairSessionState.CSS_Invalid,
                ):
                    connected.clear()

            sdk.connect(_on_state)
            if not connected.wait(timeout=3.0):
                logger.debug("lighting: iCUE SDK did not connect within 3s")
                return None
            _sdk = sdk
            return _sdk
        except Exception as e:
            logger.debug(f"lighting: iCUE SDK init failed: {e}")
            return None


def _get_devices(sdk: "CueSdk") -> list:
    try:
        devices, err = sdk.get_devices(
            CorsairDeviceFilter(device_type_mask=CorsairDeviceType.CDT_All)
        )
        if int(err) != 0 or not devices:
            return []
        return devices
    except Exception as e:
        logger.debug(f"lighting: get_devices failed: {e}")
        return []


def _get_all_leds(sdk: "CueSdk", device_id: str) -> list:
    try:
        leds, _ = sdk.get_led_positions(device_id)
        return [led.id for led in leds] if leds else []
    except Exception:
        return []


def _corsair_take_control_and_set(r: int, g: int, b: int) -> None:
    """Request exclusive control and paint every Corsair LED one color."""
    sdk = _get_sdk()
    if sdk is None:
        return
    devices = _get_devices(sdk)
    if not devices:
        logger.debug("lighting: no Corsair devices found (approved in iCUE?)")
        return
    for d in devices:
        leds = _get_all_leds(sdk, d.device_id)
        if not leds:
            continue
        colors = [CorsairLedColor(id=lid, r=r, g=g, b=b, a=255) for lid in leds]
        try:
            sdk.request_control(d.device_id, CorsairAccessLevel.CAL_ExclusiveLightingControl)
            sdk.set_led_colors(d.device_id, colors)
            logger.debug(f"lighting: Corsair idle blue set on {d.device_id}")
        except Exception as e:
            logger.debug(f"lighting: Corsair set failed on {d.device_id}: {e}")


def _corsair_release_control() -> None:
    """Release exclusive control so iCUE resumes its active preset (Rain)."""
    sdk = _get_sdk()
    if sdk is None:
        return
    for d in _get_devices(sdk):
        try:
            sdk.release_control(d.device_id)
            logger.debug(f"lighting: Corsair control released on {d.device_id} → iCUE Rain")
        except Exception as e:
            logger.debug(f"lighting: Corsair release_control failed: {e}")


# ---------------------------------------------------------------------------
# Idle color + animation constants
# ---------------------------------------------------------------------------

_IDLE_COLOR      = (0, 60, 180)    # soft blue  — Enkidu idle
_THINKING_COLOR  = (120, 0, 200)   # deep purple — Enkidu thinking
_ANIM_SPEED  = 300             # hue degrees per second
_ANIM_DELAY  = 0.04            # seconds per frame (~25 fps)

# Tower rainbow animation thread (runs during inference)
_tower_thread: Optional[threading.Thread] = None
_tower_stop   = threading.Event()


class _LFX_COLOR(ctypes.Structure):
    """Per-light color struct for LFX_SetLightColor (individual LED control)."""
    _fields_ = [
        ("red",        ctypes.c_ubyte),
        ("green",      ctypes.c_ubyte),
        ("blue",       ctypes.c_ubyte),
        ("brightness", ctypes.c_ubyte),
    ]


def _hsv_to_rgb(hue: float) -> tuple:
    """Convert hue (0–360°) at full saturation/value to (R, G, B) 0–255."""
    h = hue % 360
    x = 1 - abs((h / 60) % 2 - 1)
    if   h < 60:  r, g, b = 1, x, 0
    elif h < 120: r, g, b = x, 1, 0
    elif h < 180: r, g, b = 0, 1, x
    elif h < 240: r, g, b = 0, x, 1
    elif h < 300: r, g, b = x, 0, 1
    else:         r, g, b = 1, 0, x
    return int(r * 255), int(g * 255), int(b * 255)


def _tower_rainbow_loop(stop: threading.Event) -> None:
    """
    Galaxy Swirl — controls all 75 Aurora R15 lights individually.

    Each light gets a hue derived from two overlapping sine waves so
    the colours never repeat the same pattern. A second traveling
    brightness wave pulses through the ring/ambient/fan lights at a
    different tempo, creating the impression of depth and motion.

    Falls back gracefully to the simple LFX_Light(LFX_ALL) sweep if
    LFX_SetLightColor is not supported by the current AWCC build.
    """
    _alienfw._ensure_init()
    lfx = _alienfw._lfx
    if lfx is None:
        return

    n   = _alienfw._num_lights          # 75 on Aurora R15
    TAU = 2 * math.pi

    # ── Hue motion ──────────────────────────────────────────────────
    # Slow primary rotation sweeps a rainbow across all lights.
    ROTATE_HZ   = 1.1       # full-spectrum rotations per second
    # A second, faster counter-rotation adds visual complexity.
    CONTRA_HZ   = 2.5
    # How many full rainbows are spread across the 75 lights at once.
    HUE_WRAPS   = 4

    # ── Brightness pulse ────────────────────────────────────────────
    PULSE_HZ    = 3.5        # brightness waves per second
    # Pulse amplitude: how much brightness varies (0-255 range)
    B_MID       = 180        # centre brightness (lower = more contrast in pulse)
    B_AMP       = 75         # ±amplitude (so 105 → 255)
    # Phase lag between adjacent lights creates a traveling wave.
    WAVE_LIGHTS = 5          # one full wave covers this many lights

    # ── Per-light saturation shimmer ────────────────────────────────
    # Occasional lights briefly desaturate (→ white flash), adding
    # a "sparkle" layer on top of the colour sweep.
    SHIMMER_HZ  = 1.4

    start   = time.perf_counter()
    use_per_light = True     # toggled False if LFX_SetLightColor fails

    try:
        while not stop.is_set():
            t = time.perf_counter() - start

            if use_per_light:
                try:
                    # No LFX_Reset() — all 75 lights are set individually below,
                    # so Reset is redundant and would flash black each frame.
                    for i in range(n):
                        frac = i / n  # 0.0 → 1.0 across all lights

                        # Hue: primary sweep + counter-rotation + per-light spread
                        hue = (
                            t * ROTATE_HZ * 360
                            - t * CONTRA_HZ * 360 * frac
                            + frac * 360 * HUE_WRAPS
                        ) % 360
                        r, g, b = _hsv_to_rgb(hue)

                        # Brightness: traveling sine wave
                        wave = math.sin(TAU * (t * PULSE_HZ - frac * WAVE_LIGHTS))
                        brightness = int(B_MID + B_AMP * wave)

                        # Shimmer: desaturate a thin band of lights
                        shimmer = math.sin(TAU * (t * SHIMMER_HZ - frac * 2))
                        if shimmer > 0.92:
                            r = g = b = 255   # brief white flash

                        color = _LFX_COLOR(red=r, green=g, blue=b, brightness=brightness)
                        lfx.LFX_SetLightColor(0, i, ctypes.byref(color))

                    lfx.LFX_Update()

                except Exception:
                    # LFX_SetLightColor not supported — fall back to zone sweep
                    use_per_light = False
                    logger.debug("lighting: per-light failed, falling back to zone sweep")

            if not use_per_light:
                # Zone sweep: simpler but still multi-colour using LFX_ALL
                hue = (t * _ANIM_SPEED) % 360
                r, g, b = _hsv_to_rgb(hue)
                _alienfw.set_all(r, g, b)

            time.sleep(_ANIM_DELAY)

    finally:
        # Don't set a color on exit — just stop calling LFX functions and
        # AWCC naturally reclaims the tower with its own theme.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Call once at bot startup.
    Releases Corsair SDK control so iCUE runs its own theme.
    Tower is left entirely to AWCC — we only take over during inference.
    """
    if _USE_CORSAIR:
        _corsair_release_control()


def inference_start() -> None:
    """
    Signal that Enkidu is thinking.
    - Keyboard: takes iCUE exclusive control → deep purple
    - Tower:    galaxy swirl animation via LightFX (overrides AWCC)
    """
    global _tower_thread

    if _USE_CORSAIR:
        _corsair_take_control_and_set(*_THINKING_COLOR)

    if _USE_ALIENFX and _alienfw.ready and not (_tower_thread and _tower_thread.is_alive()):
        _tower_stop.clear()
        _tower_thread = threading.Thread(
            target=_tower_rainbow_loop,
            args=(_tower_stop,),
            daemon=True,
            name="enkidu-tower-rainbow",
        )
        _tower_thread.start()


def inference_stop() -> None:
    """
    Signal that inference is complete.
    - Tower:    stops animation; AWCC reclaims the tower with its own theme
    - Keyboard: releases iCUE SDK control so iCUE resumes its own theme
    """
    global _tower_thread

    # Stop tower animation — AWCC takes back over naturally once we stop
    # calling LFX functions.
    if _USE_ALIENFX and _tower_thread and _tower_thread.is_alive():
        _tower_stop.set()
        _tower_thread.join(timeout=2.0)
        _tower_thread = None

    # Release Corsair control → iCUE resumes its active preset
    if _USE_CORSAIR:
        _corsair_release_control()


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Enkidu lighting self-test ===")
    print(f"cuesdk      : {'installed' if _CUESDK_AVAILABLE else 'not installed'}")
    _ = _alienfw.ready
    print(f"AlienFX     : {'ready (' + str(_alienfw._num_lights) + ' lights)' if _alienfw._ready else 'not available'}")
    print()

    print("Step 1 — initialize() : keyboard + tower → idle blue")
    initialize()
    time.sleep(4)

    print("Step 2 — inference_start() : keyboard → deep purple, tower → rainbow")
    inference_start()
    time.sleep(8)

    print("Step 3 — inference_stop() : keyboard + tower → idle blue")
    inference_stop()
    time.sleep(3)

    print("Done.")
