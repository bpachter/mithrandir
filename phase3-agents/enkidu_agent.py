"""Legacy Phase 3 agent alias for backward compatibility."""

from importlib import import_module
from typing import Any


def _impl():
    return import_module("mithrandir_agent")


def run_agent(*args: Any, **kwargs: Any):
    return _impl().run_agent(*args, **kwargs)


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(_impl(), name)
