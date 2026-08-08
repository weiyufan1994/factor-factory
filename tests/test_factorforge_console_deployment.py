from __future__ import annotations

import importlib.util
import io
import json
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
from .catalog import resolve_default_catalog_path
class DataApiClient: pass
class DataCatalogNotFound(Exception): pass
class DataQuery: pass
class DataQueryInvalid(Exception): pass
__all__ = ['DataApiClient', 'DataCatalogNotFound', 'DataQuery', 'DataQueryInvalid', 'resolve_default_catalog_path']
""".lstrip(),
        encoding="utf-8",
    )
    (runtime / "catalog.py").write_text(
        "def resolve_default_catalog_path(): return 'pinned-catalog'\n",
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
            "from factorforge_data_api.catalog import resolve_default_catalog_path; "
            "assert DataApiClient.__module__ == '_factorforge_console_data_api_runtime'; "
            "assert resolve_default_catalog_path() == 'pinned-catalog'",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert probe.returncode == 0, probe.stderr


def test_catalog_fetch_is_bound_to_head_version_and_etag() -> None:
    module = _load_catalog_refresh_module()
    payload = b'{"schema_version":1,"datasets":[{"dataset_id":"clean_daily_bar"}]}'

    class Client:
        def __init__(self, *, response_version: str = "version-7") -> None:
            self.get_request = None
            self.response_version = response_version

        def head_object(self, **kwargs):
            return {"ETag": '"' + "a" * 32 + '"', "VersionId": "version-7"}

        def get_object(self, **kwargs):
            self.get_request = kwargs
            return {
                "ETag": '"' + "a" * 32 + '"',
                "VersionId": self.response_version,
                "Body": io.BytesIO(payload),
            }

    client = Client()
    data, _head = module._fetch_catalog_object(client)
    assert data == payload
    assert client.get_request["VersionId"] == "version-7"
    assert "IfMatch" not in client.get_request

    with pytest.raises(RuntimeError, match="changed between HEAD and GET"):
        module._fetch_catalog_object(Client(response_version="version-8"))


def test_deployment_permissions_and_global_s3_denies_are_fail_closed() -> None:
    web_unit = (REPO_ROOT / "deploy/factorforge-console/factorforge-console.service").read_text()
    runner_unit = (
        REPO_ROOT / "deploy/factorforge-console/factorforge-console-runner.service"
    ).read_text()
    broker_unit = (
        REPO_ROOT / "deploy/factorforge-console/factorforge-console-model-broker.service"
    ).read_text()
    caddy_unit = (
        REPO_ROOT / "deploy/factorforge-console/factorforge-console-caddy.service"
    ).read_text()
    network_script = (
        REPO_ROOT / "deploy/factorforge-console/configure-container-network.sh"
    ).read_text()
    policy = json.loads(
        (
            REPO_ROOT / "deploy/factorforge-console/iam-s3-readonly-policy.json.template"
        ).read_text()
    )

    assert "ReadWritePaths=/var/lib/factorforge-console/ledger" in web_unit
    assert "ReadOnlyPaths=/var/lib/factorforge-console/state/public" in web_unit
    assert "/var/lib/factorforge-console/secret-scan" in broker_unit
    assert "/run/factorforge-console-model-broker/denied-secrets" not in broker_unit
    assert "--mode web" in web_unit and "--mode worker" in runner_unit
    assert "Wants=network-online.target factorforge-console.service" in caddy_unit
    assert "Requires=factorforge-console.service" not in caddy_unit
    assert "--catalog" not in web_unit and "--catalog" not in runner_unit
    assert "FACTORFORGE_DATA_CATALOGS=" in (
        REPO_ROOT / "deploy/factorforge-console/factorforge-console.env.example"
    ).read_text(encoding="utf-8")
    assert "com.docker.network.bridge.name" in network_script
    assert '--gateway "${expected_gateway}"' in network_script
    assert "FF_CONSOLE_HOST" in network_script
    assert (
        'iptables -w 5 -I INPUT 1 -i "${BRIDGE_NAME}" -s "${NETWORK_SUBNET}" '
        '-j "${host_chain}"'
    ) in network_script
    assert (
        'iptables -w 5 -A "${host_chain}" -i "${BRIDGE_NAME}" '
        '-s "${NETWORK_SUBNET}" -j REJECT'
    ) in network_script
    assert "-j REJECT" in network_script
    host_requirements = (
        REPO_ROOT / "deploy/factorforge-console/requirements-host.txt"
    ).read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "matplotlib==3.10.8" in host_requirements
    assert "pyarrow==25.0.0" in host_requirements
    assert "scipy==1.16.3" in host_requirements
    assert "cryptography==46.0.7" in host_requirements
    assert 'cryptography>=46,<47' in pyproject
    assert 'scipy>=1.15,<1.16; python_version < \'3.11\'' in pyproject
    assert 'scipy>=1.16; python_version >= \'3.11\'' in pyproject
    assert (
        "ExecStartPre=/opt/factorforge-console/venv/bin/python -c "
        '"import cryptography, matplotlib, pyarrow, pyarrow.fs, scipy; '
        "assert cryptography.__version__ == '46.0.7'; "
        "assert matplotlib.__version__ == '3.10.8'; "
        "assert pyarrow.__version__ == '25.0.0'; "
        "assert scipy.__version__ == '1.16.3'\""
    ) in runner_unit

    statements = {item["Sid"]: item for item in policy["Statement"]}
    assert statements["DenyAnyS3UseOutsideDedicatedEndpoint"]["Resource"] == "*"
    assert statements["DenyMutationEvenIfAnotherPolicyIsAttached"]["Resource"] == "*"
    assert statements["DenyBucketDiscoveryOutsideApprovedBucket"]["Effect"] == "Deny"
    assert statements["DenyObjectReadOutsidePilotInputs"]["Effect"] == "Deny"
    assert statements["DenyListOutsidePilotPrefixes"]["Effect"] == "Deny"
    policy_text = json.dumps(policy, sort_keys=True)
    assert "tushares/" not in policy_text
    assert "yufan-data-lake/factorforge/*" not in policy_text
    assert "factorforge/data/catalog/data_catalog.json" in policy_text
    assert "factorforge/datamart/clean_daily_bar/v1/*" in policy_text


def test_agent_image_uses_a_resolvable_pinned_s3_dependency_set() -> None:
    dockerfile = (
        REPO_ROOT / "deploy/factorforge-console/Dockerfile.agent"
    ).read_text(encoding="utf-8")

    for requirement in (
        "aiobotocore==3.9.0",
        "boto3==1.43.56",
        "botocore==1.43.56",
        "s3fs==2026.7.0",
    ):
        assert requirement in dockerfile
