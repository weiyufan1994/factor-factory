"""Container-only compatibility bridge for the pinned Data API package."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


_MODULE_NAME = "_factorforge_console_data_api_runtime"


def _load_runtime_package():
    configured = os.environ.get("FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT", "")
    if not configured:
        raise RuntimeError("FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT is required")
    package_root = Path(configured).expanduser().resolve(strict=True)
    entrypoint = package_root / "__init__.py"
    if package_root.is_symlink() or entrypoint.is_symlink() or not entrypoint.is_file():
        raise RuntimeError("pinned Data API package root is invalid")
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        entrypoint,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("pinned Data API package cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_runtime = _load_runtime_package()

for _name in getattr(_runtime, "__all__", ()):
    globals()[_name] = getattr(_runtime, _name)

__all__ = list(getattr(_runtime, "__all__", ()))


def __getattr__(name: str):
    return getattr(_runtime, name)
