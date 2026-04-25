"""Legacy voice-installer alias for backward compatibility."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("install_mithrandir_voice.py")), run_name="__main__")
