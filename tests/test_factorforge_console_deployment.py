from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_catalog_refresh_module():
    path = REPO_ROOT / "scripts" / "refresh_factorforge_console_catalog.py"
    spec = importlib.util.spec_from_file_location("console_catalog_refresh_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_catalog_contract_accepts_production_integer_schema_version():
    module = _load_catalog_refresh_module()
    datasets = module._validate_catalog_payload(
        {
            "schema_version": 1,
            "datasets": [{"dataset_id": "clean_daily_bar"}],
        }
    )
    assert datasets[0]["dataset_id"] == "clean_daily_bar"

    with pytest.raises(RuntimeError, match="catalog contract"):
        module._validate_catalog_payload(
            {"schema_version": True, "datasets": [{"dataset_id": "clean_daily_bar"}]}
        )


def test_container_data_api_bridge_loads_only_pinned_subpackage(tmp_path):
    runtime = tmp_path / "runtime-data-api"
    runtime.mkdir()
    (runtime / "__init__.py").write_text(
        """
class DataApiClient: pass
class DataCatalogNotFound(Exception): pass
class DataQuery: pass
class DataQueryInvalid(Exception): pass
__all__ = ['DataApiClient', 'DataCatalogNotFound', 'DataQuery', 'DataQueryInvalid']
""".lstrip(),
        encoding="utf-8",
    )
    bridge = REPO_ROOT / "deploy" / "factorforge-console" / "data-api-bridge"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(bridge)
    environment["FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT"] = str(runtime)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from factorforge_data_api import DataApiClient; "
            "assert DataApiClient.__module__ == '_factorforge_console_data_api_runtime'",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert probe.returncode == 0, probe.stderr
