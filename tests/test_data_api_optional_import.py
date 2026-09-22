from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_data_api_boundary_imports_without_optional_provider_and_fails_on_access() -> None:
    """Offline planning imports must not require the external provider wheel."""
    code = r'''
import importlib.abc
import sys

class HideIndependentDataApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "factorforge_data_api" or fullname.startswith("factorforge_data_api."):
            raise ModuleNotFoundError("masked optional provider", name="factorforge_data_api")
        return None

sys.meta_path.insert(0, HideIndependentDataApi())
import factor_factory.data_api as data_api

assert callable(data_api.default_catalog_path)
assert callable(data_api.fetch_data_api_dataset)
assert callable(data_api.resolve_data_api_dataset)
try:
    data_api.default_catalog_path()
except ModuleNotFoundError as exc:
    assert exc.name is None
    assert "factorforge_data_api" in str(exc)
    assert "Install/configure" in str(exc)
else:
    raise AssertionError("optional provider access unexpectedly succeeded")
try:
    data_api.DataApiClient
except ModuleNotFoundError as exc:
    assert "factorforge_data_api" in str(exc)
else:
    raise AssertionError("lazy DataApiClient access unexpectedly succeeded")
try:
    data_api.not_an_export
except AttributeError:
    pass
else:
    raise AssertionError("unknown data_api attribute did not raise AttributeError")
'''
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_data_api_boundary_does_not_relabel_nested_provider_import_errors() -> None:
    code = r'''
import importlib.abc
import importlib.machinery
import sys

class BrokenProviderLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        raise ModuleNotFoundError("provider nested dependency missing", name="provider_nested_dependency")

class BrokenProviderFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "factorforge_data_api":
            return importlib.machinery.ModuleSpec(fullname, BrokenProviderLoader(), is_package=True)
        return None

sys.meta_path.insert(0, BrokenProviderFinder())
import factor_factory.data_api as data_api
try:
    data_api.resolve_data_api_dataset("clean_daily_bar")
except ModuleNotFoundError as exc:
    assert exc.name == "provider_nested_dependency"
    assert "Install/configure" not in str(exc)
else:
    raise AssertionError("nested provider import error was hidden")
'''
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
