from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

import factor_factory.evo_child_preregistration as child_prereg
import factor_factory.evo_data_boundary as evo_data_boundary
from factor_factory.console.web_research_plan import (
    BLOCK_PLAN_IDENTITY_INVALID,
    WebResearchPlanError,
    build_web_evaluation_contract,
    resolve_report_scoped_web_research_plan,
    validate_authorized_evo_child_web_research_plan,
    write_web_research_packet,
)
from factor_factory.console.web_factor_proof import (
    _build_oos_panel,
    project_host_private_sealed_oos_panel,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.formula.parser import parse_formula
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from scripts import materialize_factorforge_web_evo_is_checkpoint as checkpoint_cli
from scripts import finalize_factorforge_web_factor_proof as finalizer_cli
from scripts import run_factorforge_ultimate as ultimate_wrapper


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT = "WEB_PARENT"
CHILD = "WEB_PARENT__EVO_CHILD_001"
HOST_PIN = "e" * 64


def test_evo_agent_execution_env_strips_data_credentials() -> None:
    isolated = ultimate_wrapper.evo_agent_execution_env(
        {
            "AWS_ACCESS_KEY_ID": "secret",
            "AWS_SESSION_TOKEN": "secret",
            "S3_ENDPOINT_URL": "https://example.invalid",
            "FACTORFORGE_DATA_API_TOKEN": "secret",
            "FACTORFORGE_DATA_CATALOG_PATH": "/private/catalog.json",
            "FACTORFORGE_READONLY_LEASE": "secret",
            ultimate_wrapper.OOS_HOST_TRUST_ROOT_ENV: "/host/private/trust",
            ultimate_wrapper.OOS_HOST_INSTALLATION_ID_ENV: "host-installation",
            ultimate_wrapper.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: (
                "/host/private/container-state"
            ),
            ultimate_wrapper.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job-id",
            "OPENAI_API_KEY": "secret",
            "CUSTOM_PASSWORD": "secret",
            "MODEL_TOKEN": "secret",
            "SESSION_COOKIE": "secret",
            "PATH": "/usr/bin",
        }
    )

    assert isolated == {
        "PATH": "/usr/bin",
        "AWS_EC2_METADATA_DISABLED": "true",
        "FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY": "DENY",
    }


def test_host_private_finalizer_output_redaction_is_proof_safe() -> None:
    trust_root = "/host/private/research-org-trust"
    installation_id = "host-installation-secret"
    redacted = ultimate_wrapper.redact_denied_values(
        f"failed at {trust_root} for {installation_id}",
        [trust_root, installation_id],
    )
    assert trust_root not in redacted
    assert installation_id not in redacted
    assert redacted.count("[HOST_PRIVATE]") == 2


def _workspace(tmp_path: Path) -> Path:
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=tmp_path / "factorforge",
        factor_id="WEB_FACTOR",
        research_id="web_research",
        root_report_id=PARENT,
        active_report_id=CHILD,
        implementation_mode="operator",
    )
    root = Path(manifest["workspace_root"])
    write_workspace_manifest(root / "manifest.json", manifest)
    return root


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_report_scoped_child_plan_requires_pin_and_never_aliases_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    parent_path = root / "identity/web_research_plan.json"
    parent_bytes = b'{"immutable":"parent"}\n'
    parent_path.parent.mkdir(parents=True, exist_ok=True)
    parent_path.write_bytes(parent_bytes)
    child_path = (
        root
        / "objects/research_protocol"
        / f"web_research_plan__{CHILD}.json"
    )
    child_plan = {
        "identity": {
            "report_id": CHILD,
            "factor_id": "WEB_FACTOR",
            "research_id": "web_research",
        }
    }
    _write_json(child_path, child_plan)
    allocation = {
        "report_id": CHILD,
        "sealed_token_sha256": "a" * 64,
        "oos_window": {"start": "2026-01-01", "end": "2026-03-31"},
    }

    def strict_resolver(**kwargs):
        assert kwargs == {
            "workspace_root": root,
            "parent_report_id": PARENT,
            "child_report_id": CHILD,
            "expected_host_trust_manifest_sha256": HOST_PIN,
        }
        return {
            "verdict": "PASS",
            "plan_path": child_path,
            "raw_plan": child_plan,
            "allocation": allocation,
            "projection": {},
            "receipt": {},
        }

    monkeypatch.setattr(
        child_prereg,
        "validate_and_resolve_evo_child_web_research_plan_structural",
        strict_resolver,
    )
    resolved = resolve_report_scoped_web_research_plan(
        root,
        report_id=CHILD,
        expected_host_trust_manifest_sha256=HOST_PIN,
        plan_path=child_path,
    )
    assert resolved["is_evo_child"] is True
    assert resolved["plan_path"] == child_path
    assert resolved["plan"] == child_plan
    assert resolved["allocation"] == allocation
    assert parent_path.read_bytes() == parent_bytes

    with pytest.raises(WebResearchPlanError, match=BLOCK_PLAN_IDENTITY_INVALID):
        resolve_report_scoped_web_research_plan(root, report_id=CHILD)
    with pytest.raises(
        WebResearchPlanError,
        match="explicit web research plan path does not match report authority",
    ):
        resolve_report_scoped_web_research_plan(
            root,
            report_id=CHILD,
            expected_host_trust_manifest_sha256=HOST_PIN,
            plan_path=parent_path,
        )


def test_report_scoped_child_plan_propagates_strict_tamper_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)

    def reject_tamper(**_kwargs):
        raise child_prereg.EvoChildPreregistrationError(
            ["BLOCK_FACTORFORGE_EVO_CHILD_PREREGISTRATION_INVALID:tampered"]
        )

    monkeypatch.setattr(
        child_prereg,
        "validate_and_resolve_evo_child_web_research_plan_structural",
        reject_tamper,
    )
    with pytest.raises(WebResearchPlanError, match="tampered"):
        resolve_report_scoped_web_research_plan(
            root,
            report_id=CHILD,
            expected_host_trust_manifest_sha256=HOST_PIN,
        )


def test_full_agent_authored_child_plan_accepts_fresh_oos_and_preserves_parent(
    tmp_path: Path,
) -> None:
    helper_spec = importlib.util.spec_from_file_location(
        "web_plan_fixture_under_test",
        REPO_ROOT / "tests/test_factorforge_console_web_research_plan.py",
    )
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    workspace = helper._workspace(tmp_path)
    catalog = helper._write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=REPO_ROOT,
        request=helper._request(),
        catalogs=[catalog],
    )
    parent = helper._fill_plan(workspace)
    parent_path = workspace / "identity/web_research_plan.json"
    parent_bytes = parent_path.read_bytes()
    child_report_id = "WEB_REPORT__EVO_CHILD_001"
    child = copy.deepcopy(parent)
    child["identity"]["report_id"] = child_report_id
    child["research_object"]["hypothesis"] = next(
        item["claim"]
        for item in child["hypotheses"]
        if item.get("kind") == "preferred"
    )
    child["evidence_policy"]["oos_start"] = "2026-01-05"
    child["evidence_policy"]["oos_end"] = "2026-03-31"
    formula = child["research_object"]["formula_or_law"]
    formula_hash = parse_formula(formula)["formula_hash"]
    allocation = {
        "report_id": child_report_id,
        "sealed_token_sha256": "a" * 64,
        "oos_window": {"start": "2026-01-05", "end": "2026-03-31"},
    }
    conjecture = {
        "report_id": child_report_id,
        "factor_id": child["identity"]["factor_id"],
        "identity": {
            "research_id": child["identity"]["research_id"],
            "formula_hash": formula_hash,
        },
        "hypotheses": copy.deepcopy(child["hypotheses"]),
        "claim_class": child["economic_mechanism"]["claim_class"],
        "evaluation_contract": build_web_evaluation_contract(child),
        "evidence_policy": {
            **copy.deepcopy(child["evidence_policy"]),
            "sealed_oos_token_hash": allocation["sealed_token_sha256"],
        },
    }
    approaches = {"routes": copy.deepcopy(child["routes"])}
    validated = validate_authorized_evo_child_web_research_plan(
        workspace=workspace,
        parent_plan=parent,
        child_plan=child,
        parent_report_id="WEB_REPORT",
        child_report_id=child_report_id,
        research_conjecture=conjecture,
        approach_registry=approaches,
        fresh_oos_allocation=allocation,
        selected_formula=formula,
        selected_formula_hash=formula_hash,
    )
    assert validated["status"] == "PASS"
    assert parent_path.read_bytes() == parent_bytes

    tampered = copy.deepcopy(child)
    tampered["evidence_policy"]["oos_end"] = "2026-04-01"
    with pytest.raises(WebResearchPlanError, match="child_plan_fresh_oos_binding"):
        validate_authorized_evo_child_web_research_plan(
            workspace=workspace,
            parent_plan=parent,
            child_plan=tampered,
            parent_report_id="WEB_REPORT",
            child_report_id=child_report_id,
            research_conjecture=conjecture,
            approach_registry=approaches,
            fresh_oos_allocation=allocation,
            selected_formula=formula,
            selected_formula_hash=formula_hash,
        )

def test_child_fresh_start_is_step3b_but_resume_cas_wins() -> None:
    assert ultimate_wrapper._required_web_start_step(
        resume_step=None,
        is_evo_child=True,
    ) == "3b"
    assert ultimate_wrapper._required_web_start_step(
        resume_step=None,
        is_evo_child=False,
    ) == "3"
    assert ultimate_wrapper._required_web_start_step(
        resume_step="4",
        is_evo_child=True,
    ) == "4"


def test_child_materializer_projects_fresh_web_evaluation_authority() -> None:
    script_path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    spec = importlib.util.spec_from_file_location(
        "child_web_materializer_under_test",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluation = {
        "version": "factorforge_web_evaluation_contract_v2",
        "transaction_cost_bps": 30.0,
    }
    windows = {
        "is_start": "2020-01-01",
        "is_end": "2024-12-31",
        "oos_start": "2026-01-01",
        "oos_end": "2026-03-31",
    }
    common = {
        "plan_ref": f"objects/research_protocol/web_research_plan__{CHILD}.json",
        "plan_sha256": "b" * 64,
        "evaluation_contract": evaluation,
        "research_windows": windows,
    }
    factor_spec = module.bind_child_web_runtime_contract(
        {"canonical_spec": {}}, kind="factor_spec_master", **common
    )
    data_prep = module.bind_child_web_runtime_contract(
        {}, kind="data_prep_master", **common
    )
    handoff = module.bind_child_web_runtime_contract(
        {}, kind="handoff_to_step4", **common
    )
    assert factor_spec["evaluation_contract"] == evaluation
    assert factor_spec["canonical_spec"]["evaluation_contract"] == evaluation
    assert data_prep["research_windows"] == windows
    assert handoff["web_research_plan_ref"] == common["plan_ref"]
    assert handoff["web_research_plan_sha256"] == common["plan_sha256"]


def test_child_materializer_projects_every_daily_alias_and_is_only_queries(
    tmp_path: Path,
) -> None:
    script_path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    spec = importlib.util.spec_from_file_location(
        "child_web_data_boundary_under_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    local_inputs: dict[str, str] = {}
    for key in module._CHILD_WEB_DAILY_PATH_KEYS:
        suffix = ".parquet" if key.endswith("parquet") else ".csv"
        source = tmp_path / f"parent__{key}{suffix}"
        source.write_bytes(b"fixture")
        local_inputs[key] = str(source)
    parent = {
        "local_input_paths": {
            **local_inputs,
            "minute_df_parquet": str(tmp_path / "forbidden-minute.parquet"),
            "input_mode": "minute_and_daily",
        },
        "sample_window": {"start": "2020-01-01", "end": "2026-03-31"},
        "minute_derived_state_requirements": [{"dataset_id": "minute_state"}],
        "step4_data_contract": {
            "full_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                },
                "daily_basic": {
                    "dataset": "daily_basic",
                    "start_date": "20200101",
                    "end_date": "20260331",
                },
                "minute_bar": {
                    "dataset": "minute_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                },
            },
            "sample_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                }
            },
            "minute_derived_state_requirements": [{"dataset_id": "minute_state"}],
        },
    }
    assert set(module.resolved_daily_sources(tmp_path, parent)) == set(
        module._CHILD_WEB_DAILY_PATH_KEYS
    )
    targets = module.planned_target_paths(tmp_path, PARENT, CHILD, parent)
    daily_targets = {
        targets[f"child_daily_input_{key}"]
        for key in module._CHILD_WEB_DAILY_PATH_KEYS
    }
    assert len(daily_targets) == len(module._CHILD_WEB_DAILY_PATH_KEYS)
    projected = module.project_child_pre_release_data_access(
        copy.deepcopy(parent),
        {
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "2026-01-01",
            "oos_end": "2026-03-31",
        },
    )
    assert projected["sample_window"] == {
        "start": "2020-01-01",
        "end": "2024-12-31",
    }
    assert projected["local_input_paths"]["input_mode"] == "daily_only"
    assert not any(
        projected["local_input_paths"].get(key)
        for key in module._CHILD_WEB_DAILY_PATH_KEYS
    )
    assert "minute_df_parquet" not in projected["local_input_paths"]
    assert projected["minute_derived_state_requirements"] == []
    full_queries = projected["step4_data_contract"]["full_queries"]
    assert set(full_queries) == {"clean_daily_bar", "daily_basic"}
    assert {query["end_date"] for query in full_queries.values()} == {"20241231"}


def test_original_parent_evo_boundary_clamps_before_fetch_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location(
        "step4_parent_evo_boundary_under_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "resolve_evo_pre_release_research_windows",
        lambda _report_id, _dpm, **_kwargs: {
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "2026-01-01",
            "oos_end": "2026-03-31",
            "purge_days": 1,
            "embargo_days": 1,
        },
    )
    dpm = {
        "local_input_paths": {"input_mode": "minute_and_daily"},
        "step4_data_contract": {
            "version": "factorforge_step4_data_contract_v1",
            "formal_factor_values_owner": "Step4",
            "data_api_package": "factorforge_data_api",
            "full_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                },
                "minute_bar": {
                    "dataset": "minute_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                },
            },
        },
    }
    handoff: dict = {}
    module.apply_evo_pre_release_data_boundary(PARENT, dpm, handoff)
    module.validate_pre_release_step4_data_access(dpm, handoff)
    queries = dpm["step4_data_contract"]["full_queries"]
    assert set(queries) == {"clean_daily_bar"}
    assert queries["clean_daily_bar"]["end_date"] == "20241231"
    assert dpm["local_input_paths"]["input_mode"] == "daily_only"

    calls: list[tuple[str, str, str]] = []

    class Result:
        status = "ready"
        blocked_reason = None
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20241230",
                    "close": 10.0,
                }
            ]
        )

        @staticmethod
        def to_metadata() -> dict:
            return {"status": "ready"}

    def fake_fetch(dataset: str, **kwargs):
        calls.append((dataset, kwargs["start"], kwargs["end"]))
        return Result()

    monkeypatch.setattr(module, "fetch_data_api_dataset", fake_fetch)
    monkeypatch.setenv(
        "FACTORFORGE_BACKTEST_BASE_CACHE_ROOT", str(tmp_path / "cache")
    )
    monkeypatch.setenv("FACTORFORGE_DISABLE_CLEAN_DAILY_LOCAL_PARQUET", "1")
    module.materialize_step4_data_inputs_from_contract(
        PARENT, dpm["step4_data_contract"], tmp_path / "run"
    )
    assert calls == [("clean_daily_bar", "20200101", "20241231")]

    attacked = copy.deepcopy(dpm)
    attacked["step4_data_contract"]["full_queries"]["alternate_state"] = {
        "dataset": "alternate_state",
        "start_date": "20200101",
        "end_date": "20241231",
    }
    with pytest.raises(SystemExit, match="PRE_RELEASE_DATA_ACCESS_INVALID"):
        module.validate_pre_release_step4_data_access(attacked, handoff)


def test_trusted_prefetch_receipt_is_report_local_and_tamper_evident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location(
        "step4_prefetch_receipt_under_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_dir = tmp_path / "runs" / PARENT
    data_dir = run_dir / "step4_data_inputs"
    data_dir.mkdir(parents=True)
    daily_path = data_dir / "bounded.parquet"
    pd.DataFrame(
        [
            {"ts_code": "A", "trade_date": "20241230", "close": 10.0},
            {"ts_code": "B", "trade_date": "20241230", "close": 20.0},
        ]
    ).to_parquet(daily_path, index=False)
    windows = {
        "is_start": "2020-01-01",
        "is_end": "2024-12-31",
        "oos_start": "2026-01-01",
        "oos_end": "2026-03-31",
        "purge_days": 1,
        "embargo_days": 1,
    }
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "formal_factor_values_owner": "Step4",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20200101",
                "end_date": "20241231",
            }
        },
    }
    dpm = {"research_windows": windows, "step4_data_contract": contract}
    handoff: dict = {}
    monkeypatch.setattr(
        module,
        "materialize_step4_data_inputs_from_contract",
        lambda *_args, **kwargs: (
            {"input_mode": "daily_only", "daily_df_parquet": str(daily_path)},
            {"source": "trusted", "queries": contract["full_queries"]},
        ),
    )
    monkeypatch.setattr(
        module,
        "validate_trusted_calendar_snapshot",
        lambda: {
            "dates": ["20241230"],
            "snapshot_id": "test-calendar",
            "raw_file_sha256": "a" * 64,
            "open_dates_sha256": "b" * 64,
        },
    )
    receipt = module.materialize_evo_pre_release_data_receipt(
        report_id=PARENT,
        dpm=dpm,
        handoff=handoff,
        run_dir=run_dir,
    )
    assert receipt["authority"] == (
        "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION"
    )
    local_inputs, profile = module.validate_evo_pre_release_data_receipt(
        report_id=PARENT,
        dpm=dpm,
        handoff=handoff,
        run_dir=run_dir,
    )
    assert local_inputs["daily_df_parquet"] == str(daily_path)
    frame = pd.read_parquet(daily_path)
    frame.loc[0, "close"] = 999.0
    frame.to_parquet(daily_path, index=False)
    with pytest.raises(SystemExit, match="artifact_use_replay"):
        module.validate_evo_pre_release_artifacts_after_read(
            run_dir=run_dir,
            local_inputs=local_inputs,
            research_windows=windows,
            contract=contract,
            expected_artifacts=profile["_evo_receipt_artifacts"],
        )
    with pytest.raises(SystemExit, match="artifact_replay"):
        module.validate_evo_pre_release_data_receipt(
            report_id=PARENT,
            dpm=dpm,
            handoff=handoff,
            run_dir=run_dir,
        )


def test_evo_moneyflow_receipt_never_refetches_in_agent_phase(
    tmp_path: Path,
) -> None:
    script_path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location(
        "step4_moneyflow_receipt_under_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[str] = []

    def forbidden_fetch(*_args, **_kwargs):
        calls.append("fetch")
        raise AssertionError("EVO Agent phase attempted a second Data API fetch")

    local_inputs = {
        "input_mode": "alternative_daily_plus_clean_daily",
        "daily_df_parquet": str(tmp_path / "bounded-clean.parquet"),
        "evaluation_daily_df_parquet": str(tmp_path / "bounded-clean.parquet"),
        "signal_daily_df_parquet": str(tmp_path / "bounded-moneyflow.parquet"),
        "formula_input_dataset": "moneyflow",
    }
    resolved, profile = module.materialize_step4_contract_inputs_if_required(
        report_id=PARENT,
        contract={"full_queries": {"moneyflow": {"dataset": "moneyflow"}}},
        run_dir=tmp_path / "runs" / PARENT,
        local_inputs=local_inputs,
        force_contract_inputs=False,
        evo_pre_release=True,
        existing_profile={"source": "validated_receipt"},
        materializer=forbidden_fetch,
    )

    assert calls == []
    assert resolved == local_inputs
    assert profile == {"source": "validated_receipt"}


def test_pre_release_projection_scrubs_host_source_locations() -> None:
    payload = {
        "local_input_paths": {
            "input_mode": "daily_only",
            "daily_input_meta_json": "/home/ubuntu/private/meta.json",
            "daily_df_csv_sample": "s3://secret/full-history.csv",
            "unknown_snapshot_path": "/srv/full-history.parquet",
            "daily_io_contract": {
                "version": "factorforge_step3a_daily_io_contract_v1",
                "csv_path": "/srv/full-history.csv",
                "csv_sample_path": "s3://secret/sample.csv",
                "metadata_uri": "s3://secret/meta.json",
            },
        },
        "data_sources": [
            {
                "name": "clean_daily_bar",
                "kind": "data_api",
                "path": "s3://private-bucket/full.parquet",
                "normalized_dataset": "clean_daily_bar",
                "fields": ["close"],
            }
        ],
        "coverage_checks": [
            {"status": "ready", "catalog_path": "/home/ubuntu/private/catalog.json"}
        ],
        "step4_data_contract": {
            "catalog_path": "/home/ubuntu/private/catalog.json",
            "full_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20200101",
                    "end_date": "20260331",
                    "catalog_path": "/home/ubuntu/private/catalog.json",
                }
            },
        },
    }
    projected = evo_data_boundary.project_pre_release_data_access(
        payload,
        {
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "2026-01-01",
            "oos_end": "2026-03-31",
            "purge_days": 1,
            "embargo_days": 1,
        },
    )
    serialized = json.dumps(projected, sort_keys=True)
    assert "s3://" not in serialized
    assert "/home/ubuntu/private" not in serialized
    assert "/srv/full-history" not in serialized
    assert "unknown_snapshot_path" not in serialized
    assert projected["local_input_paths"]["daily_io_contract"]["csv_path"] is None
    assert (
        projected["local_input_paths"]["daily_io_contract"]["csv_sample_path"]
        is None
    )
    assert "metadata_uri" not in projected["local_input_paths"]["daily_io_contract"]
    assert "catalog_path" not in projected["step4_data_contract"]


def test_parent_dpm_window_cannot_override_canonical_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "factorforge"
    _write_json(
        root / f"objects/research_protocol/research_conjecture__{PARENT}.json",
        {"epistemic_evolution": {"enabled": True}},
    )
    _write_json(
        root / f"objects/evo_v2/{PARENT}/lifecycle.json",
        {"current_state": "PREDICTIONS_FROZEN"},
    )
    _write_json(
        root / "identity/web_research_plan.json",
        {
            "identity": {"report_id": PARENT},
            "evidence_policy": {
                "is_start": "2020-01-01",
                "is_end": "2024-12-31",
                "oos_start": "2026-01-01",
                "oos_end": "2026-03-31",
                "purge_days": 1,
                "embargo_days": 1,
            },
        },
    )
    monkeypatch.setattr(
        evo_data_boundary,
        "validate_epistemic_evolution_lifecycle",
        lambda *_args, **_kwargs: [],
    )
    tampered = {
        "research_windows": {
            "is_start": "2020-01-01",
            "is_end": "2026-03-31",
            "oos_start": "2026-04-01",
            "oos_end": "2026-06-30",
            "purge_days": 1,
            "embargo_days": 1,
        }
    }
    with pytest.raises(ValueError, match="data_prep.research_windows"):
        evo_data_boundary.resolve_evo_pre_release_research_windows(
            workspace_root=root,
            report_id=PARENT,
            data_prep=tampered,
        )


def test_child_boundary_uses_strict_prereg_plan_and_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "factorforge"
    _write_json(
        root / f"objects/research_protocol/research_conjecture__{CHILD}.json",
        {"epistemic_evolution": {"enabled": True}},
    )
    _write_json(
        root / f"objects/evo_v2/{CHILD}/lifecycle.json",
        {"current_state": "PREDICTIONS_FROZEN"},
    )
    _write_json(
        root / "identity/web_research_plan.json",
        {"identity": {"report_id": PARENT}},
    )
    child_plan = {
        "identity": {"report_id": CHILD},
        "evidence_policy": {
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "STALE_PARENT_VALUE",
            "oos_end": "STALE_PARENT_VALUE",
            "purge_days": 1,
            "embargo_days": 1,
        },
    }
    monkeypatch.setattr(
        evo_data_boundary,
        "validate_epistemic_evolution_lifecycle",
        lambda *_args, **_kwargs: [],
    )
    calls: list[dict] = []

    def strict_resolver(**kwargs):
        calls.append(kwargs)
        return {
            "raw_plan": child_plan,
            "allocation": {
                "oos_window": {"start": "2026-01-01", "end": "2026-03-31"}
            },
        }

    monkeypatch.setattr(
        child_prereg,
        "validate_and_resolve_evo_child_web_research_plan_structural",
        strict_resolver,
    )
    expected = {
        "is_start": "2020-01-01",
        "is_end": "2024-12-31",
        "oos_start": "2026-01-01",
        "oos_end": "2026-03-31",
        "purge_days": 1,
        "embargo_days": 1,
    }
    assert evo_data_boundary.resolve_evo_pre_release_research_windows(
        workspace_root=root,
        report_id=CHILD,
        data_prep={"research_windows": expected},
        expected_host_trust_manifest_sha256=HOST_PIN,
    ) == expected
    assert calls == [
        {
            "workspace_root": root.resolve(),
            "parent_report_id": PARENT,
            "child_report_id": CHILD,
            "expected_host_trust_manifest_sha256": HOST_PIN,
        }
    ]
    with pytest.raises(ValueError, match="child_external_host_trust_pin"):
        evo_data_boundary.resolve_evo_pre_release_research_windows(
            workspace_root=root,
            report_id=CHILD,
            data_prep={"research_windows": expected},
        )


def test_checkpoint_cli_serializes_report_scoped_child_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    trust_root = tmp_path / "host-private-trust"
    trust_root.mkdir(mode=0o700)
    child_path = root / f"objects/research_protocol/web_research_plan__{CHILD}.json"
    plan = {"identity": {"report_id": CHILD}}
    allocation = {"sealed_token_sha256": "a" * 64}
    monkeypatch.setattr(
        checkpoint_cli,
        "parse_args",
        lambda: argparse.Namespace(
            workspace_root=str(root),
            report_id=CHILD,
            plan_path=str(child_path),
            expected_host_trust_manifest_sha256=HOST_PIN,
            host_trust_root=str(trust_root),
            installation_id="child-web-runtime-test",
        ),
    )
    monkeypatch.setattr(
        checkpoint_cli,
        "oos_exposure_private_registry_guard",
        lambda *_args, **_kwargs: contextlib.nullcontext(object()),
    )
    monkeypatch.setattr(
        checkpoint_cli,
        "resolve_report_scoped_web_research_plan",
        lambda *_args, **_kwargs: {
            "plan": plan,
            "allocation": allocation,
        },
    )
    monkeypatch.setattr(
        checkpoint_cli,
        "validate_materialized_web_research",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        checkpoint_cli,
        "materialize_web_evo_is_checkpoint",
        lambda **kwargs: {
            "status": "PASS",
            "report_id": kwargs["plan"]["identity"]["report_id"],
            "token": kwargs["oos_release_token_hash"],
        },
    )
    assert checkpoint_cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "report_id": CHILD,
        "status": "PASS",
        "token": "a" * 64,
    }


def test_finalizer_cli_uses_report_scoped_child_plan_and_fresh_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    trust_root = tmp_path / "host-private-trust"
    trust_root.mkdir(mode=0o700)
    child_path = root / f"objects/research_protocol/web_research_plan__{CHILD}.json"
    plan = {"identity": {"report_id": CHILD}}
    allocation = {
        "sealed_token_sha256": "c" * 64,
        "dataset_snapshot_sha256": "d" * 64,
        "sealed_carrier_sha256": "e" * 64,
    }
    carrier = tmp_path / "sealed-child-oos.parquet"
    monkeypatch.setattr(
        finalizer_cli,
        "resolve_report_scoped_web_research_plan",
        lambda *_args, **_kwargs: {"plan": plan, "allocation": allocation},
    )
    monkeypatch.setattr(
        finalizer_cli,
        "validate_materialized_web_research",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        finalizer_cli,
        "finalize_web_factor_proof",
        lambda **kwargs: {
            "status": "PASS",
            "report_id": kwargs["plan"]["identity"]["report_id"],
            "token": kwargs["oos_release_token_hash"],
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "finalize_factorforge_web_factor_proof.py",
            "--workspace-root",
            str(root),
            "--report-id",
            CHILD,
            "--plan-path",
            str(child_path),
            "--expected-host-trust-manifest-sha256",
            HOST_PIN,
            "--sealed-oos-carrier",
            str(carrier),
            "--sealed-oos-private-root",
            str(tmp_path),
        ],
    )
    monkeypatch.setenv(
        finalizer_cli.OOS_HOST_TRUST_ROOT_ENV,
        str(trust_root),
    )
    monkeypatch.setenv(
        finalizer_cli.OOS_HOST_INSTALLATION_ID_ENV,
        "child-web-runtime-test",
    )
    monkeypatch.setattr(
        finalizer_cli,
        "oos_exposure_private_registry_guard",
        lambda *_args, **_kwargs: contextlib.nullcontext(object()),
    )
    assert finalizer_cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "report_id": CHILD,
        "status": "PASS",
        "token": "c" * 64,
    }


def test_pre_release_shared_context_physically_contains_only_purged_is(
    tmp_path: Path,
) -> None:
    script_path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("step4_purged_is_under_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dates = pd.bdate_range("2026-01-05", periods=10).strftime("%Y-%m-%d").tolist()
    rows = [
        {"ts_code": code, "trade_date": day, "close": 10.0 + index, "signal": index}
        for code in ("A", "B")
        for index, day in enumerate(dates)
    ]
    daily = pd.DataFrame(rows)
    factor = daily[["ts_code", "trade_date", "signal"]].copy()
    daily_path = tmp_path / "daily.parquet"
    factor_path = tmp_path / "factor.parquet"
    daily.to_parquet(daily_path, index=False)
    factor.to_parquet(factor_path, index=False)
    module.validate_trusted_calendar_snapshot = lambda: {"dates": dates}
    context = module.build_shared_evaluation_context(
        report_id=CHILD,
        factor_id="WEB_FACTOR",
        implementation_mode_decision={"implementation_mode": "operator"},
        base_identity={"spec_hash": "a" * 64, "code_hash": "b" * 64},
        run_dir=tmp_path / "run",
        factor_df=factor,
        daily_df=daily,
        signal_col="signal",
        factor_parquet_path=factor_path,
        daily_input_path=daily_path,
        target_window={"start": dates[0], "end": dates[-1]},
        effective_target_window={"start": dates[0], "end": dates[-1]},
        evaluation_contract={
            "version": "factorforge_web_evaluation_contract_v2",
            "label_policy": {},
            "proof_control_columns": [],
            "diagnostic_trials": [],
        },
        pre_release_research_windows={
            "is_start": dates[0],
            "is_end": dates[6],
            "oos_start": dates[7],
            "oos_end": dates[9],
            "purge_days": 1,
            "embargo_days": 1,
        },
    )
    allowed_end = dates[3]
    for key in (
        "factor_signal_parquet",
        "daily_forward_returns_parquet",
        "merged_signal_return_parquet",
    ):
        frame = pd.read_parquet(context["paths"][key])
        observed = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d")
        assert observed.max() <= allowed_end
        assert not observed.isin(dates[7:]).any()


def test_nqc_sealed_carrier_recomputes_oos_and_binds_both_hashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    dates = pd.bdate_range("2026-01-05", periods=5).strftime("%Y-%m-%d").tolist()
    private_root = tmp_path / "host-private"
    private_root.mkdir(mode=0o700)
    carrier = private_root / "host-private-oos.parquet"
    pd.DataFrame(
        [
            {"ts_code": code, "trade_date": day, "close": 10.0 + index}
            for code in ("A", "B")
            for index, day in enumerate(dates)
        ]
    ).to_parquet(carrier, index=False)
    carrier.chmod(0o600)
    plan = {
        "research_object": {"formula_or_law": "close"},
        "data_plan": {"daily_fields": ["close"]},
        "measurement_program": {
            "search_policy": {
                "registered_diagnostic_trials": [
                    {"trial_id": "trial_1", "formula_or_law": "-close"}
                ]
            }
        },
    }
    spec = {
        "panel": {
            "date_column": "trade_date",
            "asset_column": "code",
            "signal_column": "factor_value",
            "forward_return_column": "future_return_1d",
            "source_control_columns": [],
            "control_columns": [],
            "diagnostic_signal_columns": {
                "trial_1": "diagnostic__trial_1"
            },
        },
        "label_contract": {
            "label_start_date_column": "label_start_date",
            "label_end_date_column": "label_end_date",
            "label_start_price_column": "label_start_price",
            "label_end_price_column": "label_end_price",
        },
        "window_contract": {
            "observed_start_date": dates[0],
            "observed_end_date": dates[2],
        },
    }
    output = root / "objects/evidence/oos.parquet"
    private_projection = private_root / "derived-projection.parquet"
    projected = project_host_private_sealed_oos_panel(
        workspace_root=root,
        report_id=CHILD,
        metric_verifier_spec=spec,
        calendar={"dates": dates},
        private_output_path=private_projection,
        plan=plan,
        sealed_oos_carrier_path=carrier,
        sealed_oos_private_root=private_root,
        expected_sealed_carrier_sha256=sha256_file(carrier),
    )
    panel_sha = projected["panel_sha256"]
    assert projected["authority_status"] == "HOST_PRIVATE_PROJECTION_NOT_RELEASED"
    assert not output.exists()
    private_projection.unlink()
    with pytest.raises(ValueError, match="Agent-visible"):
        project_host_private_sealed_oos_panel(
            workspace_root=root,
            report_id=CHILD,
            metric_verifier_spec=spec,
            calendar={"dates": dates},
            private_output_path=private_projection,
            plan=plan,
            sealed_oos_carrier_path=carrier,
            sealed_oos_private_root=private_root,
            sealed_oos_agent_visible_roots=[tmp_path],
            expected_sealed_carrier_sha256=sha256_file(carrier),
        )
    accepted = _build_oos_panel(
        root=root,
        report_id=CHILD,
        spec=spec,
        calendar={"dates": dates},
        output=output,
        plan=plan,
        sealed_oos_carrier_path=carrier,
        sealed_oos_private_root=private_root,
        expected_sealed_carrier_sha256=sha256_file(carrier),
        expected_dataset_snapshot_sha256=panel_sha,
    )
    assert accepted["source_panel_ref"] == "HOST_PRIVATE_SEALED_OOS_CARRIER"
    assert accepted["panel_sha256"] == panel_sha
    output.unlink()
    with pytest.raises(ValueError, match="sealed carrier snapshot mismatch"):
        _build_oos_panel(
            root=root,
            report_id=CHILD,
            spec=spec,
            calendar={"dates": dates},
            output=output,
            plan=plan,
            sealed_oos_carrier_path=carrier,
            sealed_oos_private_root=private_root,
            expected_sealed_carrier_sha256="0" * 64,
            expected_dataset_snapshot_sha256=panel_sha,
        )
    assert not output.exists()
    with pytest.raises(ValueError, match="derived OOS panel snapshot mismatch"):
        _build_oos_panel(
            root=root,
            report_id=CHILD,
            spec=spec,
            calendar={"dates": dates},
            output=output,
            plan=plan,
            sealed_oos_carrier_path=carrier,
            sealed_oos_private_root=private_root,
            expected_sealed_carrier_sha256=sha256_file(carrier),
            expected_dataset_snapshot_sha256="0" * 64,
        )
    assert not output.exists()
