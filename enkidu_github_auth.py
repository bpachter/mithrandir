"""Legacy GitHub auth alias for backward compatibility."""

from mithrandir_github_auth import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    from pathlib import Path

    runpy.run_path(str(Path(__file__).with_name("mithrandir_github_auth.py")), run_name="__main__")
