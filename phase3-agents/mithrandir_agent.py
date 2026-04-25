"""Public Mithrandir agent entrypoint.

Keep this module import-light so callers can resolve `mithrandir_agent` even when
optional heavy dependencies for the full agent stack are not installed.
"""

from importlib import import_module
from typing import Any


def _impl():
    return import_module("mithrandir_agent_impl")


def run_agent(*args: Any, **kwargs: Any):
    return _impl().run_agent(*args, **kwargs)


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(_impl(), name)
