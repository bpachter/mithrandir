"""Legacy Open WebUI bridge alias for backward compatibility."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("mithrandir_openwebui_bridge.py")), run_name="__main__")
