"""Run the server-side Mithrandir voice installer from the voice-training folder."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    server_script = Path(__file__).resolve().parents[1] / "phase6-ui" / "server" / "install_mithrandir_voice.py"
    runpy.run_path(str(server_script), run_name="__main__")
