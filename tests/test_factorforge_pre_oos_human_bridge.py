from __future__ import annotations

import base64
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
import pandas as pd
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import factor_factory.evo_child_materialization_ticket as child_ticket
import factor_factory.oos_exposure_incident as incident_module
import factor_factory.pre_oos_human_bridge as bridge_module
import tests.test_factorforge_evo_transfer_use_orchestrator as transfer_fixtures
from factor_factory.console.web_factor_proof import prepare_web_factor_proof
from factor_factory.console.web_research_plan import (
    build_step1_payloads,
    build_web_evaluation_contract,
    validate_plan,
    write_web_research_packet,
)
from factor_factory.evo_child_execution import expected_evo_child_execution_trials
from factor_factory.evo_child_materialization_ticket import (
    WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET,
    public_child_materialization_ticket_path,
    validate_public_child_materialization_ticket,
)
from factor_factory.evo_child_preregistration import (
    child_metric_verifier_spec_path,
    child_preregistration_receipt_path,
    child_web_research_plan_path,
    materialize_evo_child_preregistration,
    project_evo_child_metric_verifier_spec,
    project_evo_child_search_identities,
    project_evo_child_search_trial_ledger,
    project_evo_child_threshold_registration,
    validate_evo_child_preregistration_receipt,
)
from factor_factory.evo_execution_addendum import execution_addendum_path
from factor_factory.evo_oos import (
    allocate_fresh_child_oos,
    build_and_allocate_fresh_child_oos,
    build_oos_registry_allocation_prefix,
    child_control_paths,
    consume_oos_allocation_for_release,
)
from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
    materialize_evo_v2_stage,
)
from factor_factory.evo_transfer_use_orchestrator import (
    orchestrate_evo_v2_transfer_use,
)
from factor_factory.evo_v2 import (
    artifact_sha256,
    evo_v2_paths,
    stable_json_hash,
    with_content_hash,
)
from factor_factory.evo_v2 import (
    canonical_json_bytes as evo_canonical_json_bytes,
)
from factor_factory.formula.parser import parse_formula
from factor_factory.human_approval import (
    HUMAN_APPROVAL_DECISION,
    HUMAN_APPROVAL_RECEIPT_VERSION,
    HUMAN_APPROVAL_TRUST_VERSION,
    canonical_json_bytes,
    sha256_file,
    stable_hash,
)
from factor_factory.oos_exposure_incident import (
    build_oos_exposure_incident,
    oos_exposure_incident_path,
    prepare_oos_exposure_incident_host_private,
    register_oos_exposure_incident_host_private,
    write_oos_exposure_incident_create_only,
)
from factor_factory.pre_oos_human_bridge import (
    PRE_OOS_CHILD_HANDOFF_VERSION,
    WAITING_PRE_OOS_TRANSFER,
    PreOosHumanBridgeError,
    materialize_pre_oos_human_bridge as _materialize_pre_oos_human_bridge,
    pre_oos_child_handoff_path,
    pre_oos_child_intent_path,
    pre_oos_human_approval_path,
    validate_pre_oos_child_handoff,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_policy_v2,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_obligation_verifier import stable_hash as host_hash
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
    load_runtime_trust_store,
)
from factor_factory.research_release import (
    METRIC_THRESHOLD_REGISTRATION_VERSION,
    METRIC_VERIFIER_SPEC_VERSION,
    SEARCH_TRIAL_LEDGER_VERSION,
    evaluation_contract_hash,
)
from factor_factory.research_release import (
    stable_hash as release_hash,
)
from factor_factory.research_workspace import (
    build_workspace_manifest,
    create_required_dirs,
    write_workspace_manifest,
)
from factor_factory.revision_council.pre_oos_outcome import (
    materialize_pre_oos_council_outcome,
)
from scripts.run_factorforge_research_protocol_smoke import (
    valid_approaches,
    valid_conjecture,
    valid_state,
)
from tests.test_factorforge_console_web_research_plan import (
    _fill_plan as _fill_parent_web_plan,
)
from tests.test_factorforge_console_web_research_plan import (
    _request as _parent_web_request,
)
from tests.test_factorforge_console_web_research_plan import (
    _write_catalog as _write_parent_web_catalog,
)
from tests.evo_child_authoring_fixtures import (
    admit_signed_evo_child_authoring_fixture,
)
from tests.test_factorforge_evo_transfer_use_orchestrator import (
    _cold_inputs as _formal_cold_inputs,
)
from tests.test_factorforge_evo_transfer_use_orchestrator import (
    _found_inputs as _formal_found_inputs,
)
from tests.test_factorforge_evo_transfer_use_orchestrator import (
    _write_execution_tests,
)
from tests.test_factorforge_evo_v2 import REPORT_ID, _as_cold_start, _build_bundle
from tests.test_factorforge_pre_oos_council_outcome import _fixture

REPO_ROOT = Path(__file__).resolve().parents[1]
CHILD_ID = f"{REPORT_ID}__EVO_CHILD_001"
INSTALLATION_ID = "council-test-installation-001"


def materialize_pre_oos_human_bridge(**kwargs):
    """Test caller supplies the incident registry pair explicitly."""

    kwargs.setdefault("incident_trust_root", kwargs["host_trust_root"])
    kwargs.setdefault("incident_installation_id", kwargs["installation_id"])
    return _materialize_pre_oos_human_bridge(**kwargs)


def _load_child_materializer_module():
    path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evo_child_materializer_under_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host_trust_root(root: Path) -> Path:
    return root.parent / f".{root.name}-host-private-trust"


def _admissions_root(root: Path) -> Path:
    return root.parent / f".{root.name}-researcher-memory-evo-v2"


def _host_manifest_pin(root: Path) -> str:
    manifest = workspace_runtime_trust_manifest(root, report_id=REPORT_ID)
    assert manifest is not None
    return str(manifest["manifest_sha256"])


def _write_handwritten_child_controls(
    root: Path, *, execution_addendum: dict | None
) -> None:
    """Deliberately incomplete legacy fixture used only by the attack test."""

    controls = child_control_paths(root, CHILD_ID)
    trials = expected_evo_child_execution_trials(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        execution_addendum=execution_addendum,
    )
    ledger = {
        "version": "factorforge_search_trial_ledger_v1",
        "search_status": "FROZEN",
        "report_id": CHILD_ID,
        "factor_id": "factor_evo_child_001",
        "freeze_sequence": 10,
        "trial_count": len(trials),
        "trials": trials,
        "trial_set_sha256": stable_json_hash(trials),
        "candidate_space_sha256": stable_json_hash({"scope": "frozen_evo_child"}),
        "selected_hypothesis_sha256": stable_json_hash(
            {"scope": "host_approved_revision"}
        ),
    }
    threshold_path = controls["threshold_registration"]
    metric_spec = {
        "version": METRIC_VERIFIER_SPEC_VERSION,
        "verification_scope": "production",
        "report_id": CHILD_ID,
        "factor_id": "factor_evo_child_001",
        "research_id": "research_evo_child_001",
        "claim_class": "information_rent",
        "cost_policy_id": "a_share_cost_v1",
        "panel": {
            "date_column": "trade_date",
            "asset_column": "code",
            "signal_column": "factor_value",
            "forward_return_column": "future_return_1d",
        },
        "window_contract": {
            "evaluation_window_role": "OOS_FINAL",
            "oos_window": "2026-04-01/2026-09-30",
            "search_trial_ledger_ref": controls["search_trial_ledger"]
            .relative_to(root)
            .as_posix(),
        },
        "label_contract": {
            "version": "factorforge_daily_return_label_contract_v1",
            "signal_date_column": "trade_date",
            "forward_return_column": "future_return_1d",
        },
        "portfolio": {"annualization_factor": 252},
        "fama_macbeth": {"newey_west_lags": 3},
        "bucket_monotonicity": {
            "bucket_count": 10,
            "expected_direction": "ascending",
        },
        "threshold_registration_ref": threshold_path.relative_to(root).as_posix(),
    }
    metric_spec["window_hash"] = release_hash(metric_spec["window_contract"])
    _write_json(child_metric_verifier_spec_path(root, CHILD_ID), metric_spec)
    for name, payload in {
        "research_state": {
            "contract_version": "factorforge_evo_child_research_state_projection_v1",
            "report_id": CHILD_ID,
            "state": "PREREGISTERED_NOT_EXECUTED",
        },
        "research_conjecture": {
            "contract_version": "factorforge_evo_child_conjecture_projection_v1",
            "report_id": CHILD_ID,
            "state": "PREREGISTERED_NOT_EXECUTED",
        },
        "approach_registry": {
            "contract_version": "factorforge_evo_child_approach_registry_projection_v1",
            "report_id": CHILD_ID,
            "state": "FROZEN",
        },
        "search_trial_ledger": ledger,
    }.items():
        _write_json(controls[name], payload)
    _write_json(
        threshold_path,
        {
            "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
            "registration_status": "LOCKED",
            "report_id": CHILD_ID,
            "factor_id": metric_spec["factor_id"],
            "claim_class": metric_spec["claim_class"],
            "verification_scope": "production",
            "window_hash": release_hash(metric_spec["window_contract"]),
            "evaluation_contract_hash": evaluation_contract_hash(metric_spec),
            "label_contract_hash": release_hash(metric_spec["label_contract"]),
            "registered_before_evaluation": True,
            "search_trial_ledger_ref": controls["search_trial_ledger"]
            .relative_to(root)
            .as_posix(),
            "search_trial_ledger_sha256": sha256_file(controls["search_trial_ledger"]),
        },
    )


def _write_parent_web_authority(root: Path) -> dict:
    """Materialize the real parent Web plan/proof authority for child prereg."""

    plan_path = root / "identity/web_research_plan.json"
    if plan_path.is_file():
        # The formal FOUND transfer fixture already materializes the canonical
        # Web intake.  Reuse it exactly: writing a second request here would
        # conflict with the append-only conversation-ledger authority.
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        manifest = build_workspace_manifest(
            repo_root=REPO_ROOT,
            factorforge_root=root.parent,
            factor_id="negative_pv_shape",
            research_id="research_001",
            root_report_id=REPORT_ID,
            implementation_mode="operator",
        )
        manifest["workspace_root"] = str(root)
        manifest["paths"] = {
            "objects_root": str(root / "objects"),
            "runs_root": str(root / "runs"),
            "evaluations_root": str(root / "evaluations"),
            "step3_runtime_root": str(root / "step3_runtime"),
            "knowledge_root": str(root / "knowledge"),
            "knowledge_canonical_root": str(root / "knowledge/canonical"),
            "knowledge_human_root": str(root / "knowledge/human_readable"),
            "knowledge_export_manifest_root": str(root / "knowledge/export_manifest"),
            "council_root": str(root / "council"),
            "branch_comparison_root": str(root / "branch_comparison"),
            "logs_root": str(root / "logs"),
            "tmp_root": str(root / "tmp"),
        }
        create_required_dirs(root)
        write_workspace_manifest(root / "manifest.json", manifest)
        catalog_root = root / "parent_web_catalog"
        catalog_root.mkdir(parents=True, exist_ok=True)
        catalog = _write_parent_web_catalog(catalog_root)
        request = _parent_web_request()
        request.update(
            {
                "job_id": "job_e0c0c0ffee",
                "factor_id": "negative_pv_shape",
                "research_id": "research_001",
                "report_id": REPORT_ID,
                "sample_start": "2020-01-01",
                "sample_end": "2025-12-31",
            }
        )
        snapshot = copy.deepcopy(request["conversation_snapshot"])
        snapshot["job_id"] = request["job_id"]
        snapshot.pop("sha256", None)
        snapshot["sha256"] = stable_json_hash(snapshot)
        request["conversation_snapshot"] = snapshot
        request["conversation_snapshot_sha256"] = snapshot["sha256"]
        write_web_research_packet(
            workspace=root,
            worktree=REPO_ROOT,
            request=request,
            catalogs=[catalog],
        )
        plan = _fill_parent_web_plan(root)
    _, formula_ir = validate_plan(plan, workspace=root)
    knowledge_summary = json.loads(
        (root / "identity/factor_knowledge_summary.json").read_text(
            encoding="utf-8"
        )
    )
    step1 = build_step1_payloads(
        plan,
        formula_ir=formula_ir,
        knowledge_summary=knowledge_summary,
    )
    step1_paths = {
        "aim": root
        / "objects/alpha_idea_master"
        / f"alpha_idea_master__{REPORT_ID}.json",
        "primary": root
        / "objects/validation"
        / f"report_map_validation__{REPORT_ID}__alpha_thesis.json",
        "challenger": root
        / "objects/validation"
        / f"report_map_validation__{REPORT_ID}__challenger_alpha_thesis.json",
        "report_map": root
        / "objects/report_maps"
        / f"report_map__{REPORT_ID}__primary.json",
    }
    for name, path in step1_paths.items():
        _write_json(path, step1[name])
    step2_dir = REPO_ROOT / "skills/factor-forge-step2/scripts"
    step2_env = os.environ.copy()
    step2_env["FACTORFORGE_ROOT"] = str(root)
    step2_env["PYTHONPATH"] = os.pathsep.join(
        [str(step2_dir), str(REPO_ROOT), step2_env.get("PYTHONPATH", "")]
    )
    step2 = subprocess.run(
        [
            sys.executable,
            "-c",
            "from run_step2 import run_step2; " f"run_step2({REPORT_ID!r})",
        ],
        cwd=REPO_ROOT,
        env=step2_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert step2.returncode == 0, step2.stdout + step2.stderr
    trust_root = _host_trust_root(root)
    ensure_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    prepare_web_factor_proof(
        workspace_root=root,
        plan=plan,
        incident_trust_root=trust_root,
        incident_installation_id=INSTALLATION_ID,
    )

    parent_conjecture_path = (
        root / "objects/research_protocol" / f"research_conjecture__{REPORT_ID}.json"
    )
    parent_conjecture = json.loads(parent_conjecture_path.read_text(encoding="utf-8"))
    parent_conjecture.update(
        {
            "report_id": REPORT_ID,
            "factor_id": plan["identity"]["factor_id"],
            "claim_class": plan["economic_mechanism"]["claim_class"],
            "evaluation_contract": build_web_evaluation_contract(plan),
        }
    )
    parent_conjecture["identity"].update(
        {
            "research_id": plan["identity"]["research_id"],
            "workspace_manifest_sha256": sha256_file(root / "manifest.json"),
        }
    )
    for field in (
        "is_start",
        "is_end",
        "oos_start",
        "oos_end",
        "purge_days",
        "embargo_days",
        "trial_budget",
        "multiple_testing_policy",
        "forward_horizon",
        "transaction_cost_bps",
        "cost_model_id",
        "impact_model_id",
        "capacity_model_id",
        "universe_id",
        "investability_mask_id",
    ):
        parent_conjecture["evidence_policy"][field] = plan["evidence_policy"][field]
    _write_json(parent_conjecture_path, parent_conjecture)
    # A cold parent has no earlier research-protocol state/route files.  Child
    # authoring is deliberately authorized only from a complete, validator-
    # clean parent protocol, so materialize the non-empirical controls that the
    # formal Web intake freezes.  Never overwrite a FOUND branch's controls.
    parent_state_path = (
        root
        / "objects/research_protocol"
        / f"research_state__{REPORT_ID}.json"
    )
    if not parent_state_path.exists() and not parent_state_path.is_symlink():
        parent_state = valid_state()
        parent_state.update(
            {
                "report_id": REPORT_ID,
                "factor_id": plan["identity"]["factor_id"],
                "research_id": plan["identity"]["research_id"],
            }
        )
        _write_json(parent_state_path, parent_state)
    parent_approaches_path = (
        root
        / "objects/research_protocol"
        / f"approach_registry__{REPORT_ID}.json"
    )
    if (
        not parent_approaches_path.exists()
        and not parent_approaches_path.is_symlink()
    ):
        parent_approaches = valid_approaches()
        parent_approaches["report_id"] = REPORT_ID
        _write_json(parent_approaches_path, parent_approaches)
    return plan


def _materialize_ready_child_preregistration(root: Path) -> dict:
    """Run the actual Host-authorized preregistration transaction."""

    parent_plan = json.loads(
        (root / "identity/web_research_plan.json").read_text(encoding="utf-8")
    )
    parent_conjecture = json.loads(
        (
            root
            / "objects/research_protocol"
            / f"research_conjecture__{REPORT_ID}.json"
        ).read_text(encoding="utf-8")
    )
    handoff = json.loads(
        pre_oos_child_handoff_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    allocation = json.loads(
        (
            root / "objects/research_protocol" / f"evo_oos_allocation__{CHILD_ID}.json"
        ).read_text(encoding="utf-8")
    )
    selected = handoff["selected_revision"]
    state = valid_state()
    state.update(
        {
            "report_id": CHILD_ID,
            "factor_id": "negative_pv_shape",
            "research_id": "research_001",
            "budget_used": {"trials_used": 1, "trial_budget": 20},
        }
    )
    conjecture = valid_conjecture()
    conjecture.update(
        {
            "report_id": CHILD_ID,
            "factor_id": "negative_pv_shape",
            "claim_class": parent_plan["economic_mechanism"]["claim_class"],
            "epistemic_evolution": epistemic_evolution_policy_v2(),
        }
    )
    conjecture["identity"].update(
        {
            "research_id": "research_001",
            "workspace_manifest_sha256": sha256_file(root / "manifest.json"),
            "data_catalog_snapshot_sha256": parent_conjecture["identity"][
                "data_catalog_snapshot_sha256"
            ],
            "parent_artifact_sha256": handoff["pre_oos_root_synthesis_ref"]["sha256"],
            "formula_hash": selected["child_formula_hash"],
        }
    )
    conjecture["evidence_policy"].update(
        {
            field: parent_plan["evidence_policy"][field]
            for field in (
                "is_start",
                "is_end",
                "purge_days",
                "embargo_days",
                "trial_budget",
                "multiple_testing_policy",
                "forward_horizon",
                "transaction_cost_bps",
                "cost_model_id",
                "impact_model_id",
                "capacity_model_id",
                "universe_id",
                "investability_mask_id",
            )
        }
    )
    conjecture["evidence_policy"].update(
        {
            "trials_used": 1,
            "oos_start": allocation["oos_window"]["start"],
            "oos_end": allocation["oos_window"]["end"],
            "sealed_oos_token_hash": allocation["sealed_token_sha256"],
        }
    )
    approaches = valid_approaches()
    approaches["report_id"] = CHILD_ID
    conjecture["hypotheses"] = copy.deepcopy(parent_plan["hypotheses"])
    child_plan = copy.deepcopy(parent_plan)
    child_plan["identity"]["report_id"] = CHILD_ID
    child_plan["research_object"]["formula_or_law"] = selected["child_formula"]
    child_plan["hypotheses"] = copy.deepcopy(conjecture["hypotheses"])
    child_plan["research_object"]["hypothesis"] = next(
        item["claim"]
        for item in conjecture["hypotheses"]
        if item["kind"] == "preferred"
    )
    child_plan["routes"] = copy.deepcopy(approaches["routes"])
    child_plan["evidence_policy"]["oos_start"] = allocation["oos_window"]["start"]
    child_plan["evidence_policy"]["oos_end"] = allocation["oos_window"]["end"]
    child_plan["measurement_program"]["observation_and_estimation"][
        "executable_formula_projection"
    ] = selected["child_formula"]
    child_plan["measurement_program"]["implementation"]["components"][0][
        "implementation_binding"
    ] = "negate(minus(divide(pre_close, open), 1.0))"
    conjecture["evaluation_contract"] = build_web_evaluation_contract(child_plan)

    preferred_hypothesis_id = next(
        item["hypothesis_id"]
        for item in conjecture["hypotheses"]
        if item["kind"] == "preferred"
    )
    trials = [
        {
            "trial_id": "child_primary_trial_001",
            "status": "REGISTERED_NOT_EVALUATED",
            "hypothesis_id": preferred_hypothesis_id,
        }
    ]
    identities = project_evo_child_search_identities(conjecture)
    base_ledger = {
        "version": SEARCH_TRIAL_LEDGER_VERSION,
        "search_status": "FROZEN",
        "report_id": CHILD_ID,
        "factor_id": "negative_pv_shape",
        "freeze_sequence": 10,
        "trial_count": 1,
        "trials": trials,
        "trial_set_sha256": stable_json_hash(trials),
        "candidate_space_sha256": identities["candidate_space_sha256"],
        "selected_hypothesis_sha256": identities["selected_hypothesis_sha256"],
    }
    pin = _host_manifest_pin(root)
    authoring = admit_signed_evo_child_authoring_fixture(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        semantic_bundle={
            "research_state": state,
            "research_conjecture": conjecture,
            "approach_registry": approaches,
            "base_search_trial_ledger": base_ledger,
            "agent_authored_child_web_research_plan": child_plan,
        },
        expected_host_trust_manifest_sha256=pin,
        trust_root=_host_trust_root(root),
        installation_id=INSTALLATION_ID,
    )
    ledger = project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        base_search_trial_ledger=base_ledger,
        expected_host_trust_manifest_sha256=pin,
    )
    metric_spec = project_evo_child_metric_verifier_spec(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        research_conjecture=conjecture,
        expected_host_trust_manifest_sha256=pin,
    )
    threshold = project_evo_child_threshold_registration(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        research_conjecture=conjecture,
        search_trial_ledger=ledger,
        metric_verifier_spec=metric_spec,
        expected_host_trust_manifest_sha256=pin,
    )
    return materialize_evo_child_preregistration(
        workspace_root=root,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        research_state=state,
        research_conjecture=conjecture,
        approach_registry=approaches,
        base_search_trial_ledger=base_ledger,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=child_plan,
        agent_authoring_admission=authoring["admission_ref"]["path"],
        expected_host_trust_manifest_sha256=pin,
        incident_trust_root=_host_trust_root(root),
        incident_installation_id=INSTALLATION_ID,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_parent_daily_authority(root: Path) -> None:
    inputs = root / "runs" / REPORT_ID / "frozen_inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    daily = inputs / "daily.csv"
    evaluation = inputs / "evaluation_daily.parquet"
    signal = inputs / "signal_daily.parquet"
    meta = inputs / "daily_input_meta.json"
    daily.write_text(
        "instrument,date,close\n000001.SZ,2026-01-02,10.0\n",
        encoding="utf-8",
    )
    evaluation.write_bytes(b"PAR1-frozen-evaluation-daily")
    signal.write_bytes(b"PAR1-frozen-signal-daily")
    _write_json(
        meta,
        {
            "contract_version": "factorforge_test_daily_input_meta_v1",
            "report_id": REPORT_ID,
            "evaluation_daily_sha256": sha256_file(evaluation),
            "signal_daily_sha256": sha256_file(signal),
        },
    )
    relative = lambda path: path.relative_to(root).as_posix()
    _write_json(
        root / f"objects/data_prep_master/data_prep_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "local_input_paths": {
                "daily_df_csv": relative(daily),
                "evaluation_daily_df_parquet": relative(evaluation),
                "signal_daily_df_parquet": relative(signal),
                "daily_input_meta_json": relative(meta),
            },
        },
    )


def _lifecycle_parent(payload: dict) -> str:
    events = payload["events"]
    parent = {
        "contract_version": payload["contract_version"],
        "report_id": payload["report_id"],
        "current_state": events[-2]["to_state"],
        "events": events[:-1],
        "host_authority": payload["host_authority"],
    }
    parent["content_sha256"] = host_hash(parent)
    return host_hash(parent)


def _append_lifecycle(root: Path, to_state: str, evidence_ref: dict) -> dict:
    path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    existing = json.loads(path.read_text(encoding="utf-8"))
    trust = load_runtime_trust_store(
        _host_trust_root(root),
        installation_id="council-test-installation-001",
    )
    manifest = workspace_runtime_trust_manifest(root, report_id=REPORT_ID)
    assert manifest is not None
    sequence = len(existing["events"]) + 1
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": sequence,
            "from_state": existing["current_state"],
            "to_state": to_state,
            "lifecycle_parent_sha256": host_hash(existing),
            "evidence_refs_sha256": host_hash([evidence_ref]),
            "trust_manifest_sha256": manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    receipt_path = path.parent / f"lifecycle_transition_receipt__{sequence:04d}.json"
    _write_json(receipt_path, receipt)
    receipt_ref = {
        "path": receipt_path.relative_to(root).as_posix(),
        "sha256": sha256_file(receipt_path),
        "receipt_id": receipt["receipt_id"],
        "trust_manifest_sha256": manifest["manifest_sha256"],
    }
    updated = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state=to_state,
        evidence_refs=[evidence_ref],
        existing=existing,
        actor_receipt_ref=receipt_ref,
    )
    _write_json(path, updated)
    return updated


def _prepare_minimal(root: Path) -> tuple[dict, dict, dict, dict]:
    synthesis, synthesis_path = _fixture(root)
    inside_trust = root / "host-private-trust"
    outside_trust = _host_trust_root(root)
    if inside_trust.exists():
        inside_trust.rename(outside_trust)
    outcome = materialize_pre_oos_council_outcome(
        workspace_root=root,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    lifecycle_path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    qualified = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    feedback = json.loads(
        evo_v2_paths(root, REPORT_ID)["feedback_ledger"].read_text(encoding="utf-8")
    )
    feedback_stage = materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_FEEDBACK,
        expected_lifecycle_parent_sha256=_lifecycle_parent(qualified),
        expected_lifecycle_content_sha256=qualified["content_sha256"],
        expected_staging_content_sha256="ABSENT",
        feedback_ledger=feedback,
    )
    minimal = _append_lifecycle(
        root, "MINIMAL_MECHANISM_DELTA", outcome["evidence_ref"]
    )
    selected_ref = synthesis["evidence_bindings"]["selected_proposal_ref"]
    selected_result = json.loads(
        (root / selected_ref["path"]).read_text(encoding="utf-8")
    )
    council_stage = materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_COUNCIL_OUTCOME,
        expected_lifecycle_parent_sha256=host_hash(qualified),
        expected_lifecycle_content_sha256=minimal["content_sha256"],
        expected_staging_content_sha256=feedback_stage["staging_manifest"][
            "content_sha256"
        ],
        council_proposal=selected_result,
    )
    _write_json(
        root / f"objects/factor_spec_master/factor_spec_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "artifact_identity": {"implementation_mode": "operator"},
            "canonical_spec": {"formula_text": "close"},
        },
    )
    _write_parent_daily_authority(root)
    return synthesis, selected_result, minimal, council_stage


def _allocate_oos(
    root: Path,
    *,
    trust_root: Path | None = None,
    admissions_root: Path | None = None,
) -> None:
    plan = _write_parent_web_authority(root)
    from factor_factory.evo_child_preregistration import _parent_contract_context

    contracts = _parent_contract_context(root=root, parent_report_id=REPORT_ID)
    dates = [
        item
        for item in contracts["calendar"]["dates"]
        if "2026-04-01" <= item <= "2026-09-30"
    ]
    fields = set(plan["data_plan"]["daily_fields"])
    fields.update(
        contracts["metric_verifier_spec"]["panel"].get(
            "source_control_columns", []
        )
    )
    rows = []
    for asset_offset, code in enumerate(("000001.SZ", "000002.SZ")):
        for index, trade_date in enumerate(dates):
            close = 10.0 + asset_offset + index * 0.01
            row = {
                "ts_code": code,
                "trade_date": trade_date,
                "close": close,
                "open": close * 0.999,
                "pre_close": close - 0.01,
                "pct_chg": 0.1,
                "turnover_rate": 1.0,
                "ln_mcap_free": 10.0 + asset_offset,
                "volume_ratio": 1.0,
            }
            rows.append({key: value for key, value in row.items() if key in fields or key in {"ts_code", "trade_date", "close"}})
    private_root = root.parent / f".{root.name}-oos-private"
    private_root.mkdir(mode=0o700)
    carrier = private_root / "sealed-oos-carrier.parquet"
    pd.DataFrame(rows).to_parquet(carrier, index=False)
    carrier.chmod(0o600)
    selected_trust_root = trust_root or _host_trust_root(root)
    selected_admissions_root = admissions_root
    if selected_admissions_root is None:
        candidates = (
            _admissions_root(root),
            selected_trust_root.parent / "researcher-memory-evo-v2",
        )
        selected_admissions_root = next(
            (candidate for candidate in candidates if candidate.is_dir()),
            None,
        )
    build_and_allocate_fresh_child_oos(
        workspace_root=root,
        allocation_id="allocation_evo_child_001",
        report_id=CHILD_ID,
        parent_report_id=REPORT_ID,
        oos_start="2026-04-01",
        oos_end="2026-09-30",
        sealed_oos_carrier_path=carrier,
        sealed_oos_private_root=private_root,
        expected_registry_sha256=None,
        trust_root=selected_trust_root,
        installation_id=INSTALLATION_ID,
        admissions_root=selected_admissions_root,
    )


def _append_unrelated_oos_allocation(root: Path) -> None:
    registry = root / "objects/research_protocol/evo_oos_allocation_registry.json"
    allocate_fresh_child_oos(
        workspace_root=root,
        allocation_id="allocation_evo_child_002",
        report_id=f"{REPORT_ID}__EVO_CHILD_002",
        parent_report_id=REPORT_ID,
        dataset_snapshot_sha256="e" * 64,
        oos_start="2026-07-01",
        oos_end="2026-09-30",
        sealed_token_sha256="f" * 64,
        expected_registry_sha256=sha256_file(registry),
        trust_root=_host_trust_root(root),
        installation_id=INSTALLATION_ID,
        legacy_test_only=True,
    )


def _consume_primary_oos(root: Path) -> None:
    controls = child_control_paths(root, CHILD_ID)
    allocation = json.loads(controls["oos_allocation"].read_text(encoding="utf-8"))
    _write_json(controls["search_trial_ledger"], {"report_id": CHILD_ID})
    _write_json(controls["threshold_registration"], {"report_id": CHILD_ID})
    release = {
        "version": "factorforge_oos_release_manifest_v1",
        "release_status": "RELEASED",
        "report_id": CHILD_ID,
        "factor_id": "factor_evo_child_001",
        "release_sequence": 1,
        "search_trial_ledger_ref": controls["search_trial_ledger"]
        .relative_to(root)
        .as_posix(),
        "search_trial_ledger_sha256": sha256_file(controls["search_trial_ledger"]),
        "threshold_registration_ref": controls["threshold_registration"]
        .relative_to(root)
        .as_posix(),
        "threshold_registration_sha256": sha256_file(
            controls["threshold_registration"]
        ),
        "dataset_snapshot_hash": allocation["dataset_snapshot_sha256"],
        "window_hash": "1" * 64,
        "evaluation_contract_hash": "2" * 64,
        "oos_window": "2026-04-01/2026-09-30",
        "observed_start_date": "2026-04-01",
        "observed_end_date": "2026-09-30",
        "observed_period_count": 60,
        "oos_release_token_hash": allocation["sealed_token_sha256"],
    }
    release["release_manifest_sha256"] = release_hash(release)
    release_path = (
        root / "objects/research_protocol" / f"oos_release_manifest__{CHILD_ID}.json"
    )
    _write_json(release_path, release)
    consume_oos_allocation_for_release(
        workspace_root=root,
        report_id=CHILD_ID,
        release_manifest_path=release_path,
        incident_trust_root=_host_trust_root(root),
        incident_installation_id=INSTALLATION_ID,
    )


def _external_human_receipt(
    root: Path, synthesis: dict, selected_result: dict
) -> tuple[Path, str]:
    _write_parent_web_authority(root)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = __import__("hashlib").sha256(public).hexdigest()
    trust_unsigned = {
        "contract_version": HUMAN_APPROVAL_TRUST_VERSION,
        "keys": {
            key_id: {
                "algorithm": "Ed25519",
                "public_key_b64": base64.b64encode(public).decode("ascii"),
                "status": "ACTIVE",
            }
        },
    }
    trust = {**trust_unsigned, "content_sha256": stable_hash(trust_unsigned)}
    trust_path = root / "identity/human_approval_trust.json"
    _write_json(trust_path, trust)
    paths = evo_v2_paths(root, REPORT_ID)
    delta = json.loads(paths["mechanism_delta"].read_text(encoding="utf-8"))
    selected = synthesis["selected_outcome"]
    child_formula = selected_result["model_to_formula_translation"]["candidate_formula"]
    child_hash = parse_formula(child_formula)["formula_hash"]
    allocation_path = (
        root / "objects/research_protocol" / f"evo_oos_allocation__{CHILD_ID}.json"
    )
    synthesis_path = (
        root
        / "objects/research_iteration_master/revision_council"
        / REPORT_ID
        / f"pre_oos_council_root_synthesis__{REPORT_ID}.json"
    )
    receipt_unsigned = {
        "contract_version": HUMAN_APPROVAL_RECEIPT_VERSION,
        "report_id": REPORT_ID,
        "run_id": delta["artifact_identity"]["run_id"],
        "decision": HUMAN_APPROVAL_DECISION,
        "synthesis": {
            "path": synthesis_path.relative_to(root).as_posix(),
            "sha256": sha256_file(synthesis_path),
        },
        "selected_law": {
            "law_id": selected["law_id"],
            "law_or_formula_hash": selected["law_sha256"],
            "child_formula_hash": child_hash,
        },
        "mechanism_delta": {
            "path": paths["mechanism_delta"].relative_to(root).as_posix(),
            "sha256": sha256_file(paths["mechanism_delta"]),
            "delta_id": selected["delta_id"],
        },
        "economic_backprojection": {
            "path": paths["economic_backprojection"].relative_to(root).as_posix(),
            "sha256": sha256_file(paths["economic_backprojection"]),
            "delta_id": selected["delta_id"],
        },
        "child_intent": {
            "action": "MATERIALIZE_AND_TEST_FRESH_OOS_CHILD",
            "child_report_id": CHILD_ID,
            "child_formula_hash": child_hash,
            "fresh_sealed_oos_required": True,
            "reuse_parent_ancestor_or_sibling_oos_allowed": False,
            "oos_allocation_id": "allocation_evo_child_001",
            "oos_allocation_ref": allocation_path.relative_to(root).as_posix(),
            "oos_allocation_sha256": sha256_file(allocation_path),
            "oos_registry_prefix_ref": build_oos_registry_allocation_prefix(
                root=root,
                allocation_id="allocation_evo_child_001",
                report_id=CHILD_ID,
            ),
        },
        "issued_at_utc": "2026-08-12T08:00:00Z",
        "issuer": {
            "kind": "external_human",
            "human_id": "human_owner_pre_oos_001",
            "key_id": key_id,
        },
    }
    receipt_id = stable_hash(receipt_unsigned)
    signed = {**receipt_unsigned, "receipt_id": receipt_id}
    receipt = {
        **signed,
        "signature": {
            "algorithm": "Ed25519",
            "value_b64": base64.b64encode(
                private.sign(canonical_json_bytes(signed))
            ).decode("ascii"),
        },
    }
    receipt_path = root / "identity/pre_oos_external_human_receipt.json"
    _write_json(receipt_path, receipt)
    return receipt_path, sha256_file(trust_path)


def _complete_transfer_use_low_level_only(
    root: Path,
    minimal: dict,
    *,
    lifecycle_state: str = "TRANSFER_RECORDED",
) -> None:
    evidence_ref = minimal["events"][-1]["evidence_refs"][0]
    transferred = _append_lifecycle(
        root=root,
        to_state=lifecycle_state,
        evidence_ref=evidence_ref,
    )
    support_root = root / "transfer_support"
    bundle = _build_bundle(support_root)
    if lifecycle_state == "COLD_START_RECORDED":
        bundle = _as_cold_start(bundle, support_root)
    shutil.copytree(support_root / "support", root / "support", dirs_exist_ok=True)
    paths = evo_v2_paths(root, REPORT_ID)
    delta = json.loads(paths["mechanism_delta"].read_text(encoding="utf-8"))
    backprojection = json.loads(
        paths["economic_backprojection"].read_text(encoding="utf-8")
    )
    transfer = copy.deepcopy(bundle["experience_transfer_bundle"])
    transfer["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    transfer["economic_backprojection_ref"]["sha256"] = artifact_sha256(backprojection)
    transfer = with_content_hash(transfer)
    staging = json.loads(
        (root / f"objects/evo_v2/{REPORT_ID}/staging_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    transfer_stage = materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_TRANSFER,
        expected_lifecycle_parent_sha256=host_hash(minimal),
        expected_lifecycle_content_sha256=transferred["content_sha256"],
        expected_staging_content_sha256=staging["content_sha256"],
        experience_transfer_bundle=transfer,
    )
    use = copy.deepcopy(bundle["transfer_use_receipt"])
    use["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    use = with_content_hash(use)
    materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_RECORD_USE,
        expected_lifecycle_parent_sha256=host_hash(minimal),
        expected_lifecycle_content_sha256=transferred["content_sha256"],
        expected_staging_content_sha256=transfer_stage["staging_manifest"][
            "content_sha256"
        ],
        transfer_use_receipt=use,
    )


def _complete_transfer_use_formal(
    root: Path,
    minimal: dict,
    *,
    lifecycle_state: str = "TRANSFER_RECORDED",
) -> None:
    lifecycle_sha = host_hash(minimal)
    staging = json.loads(
        (root / f"objects/evo_v2/{REPORT_ID}/staging_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    staging_sha = staging["content_sha256"]
    trust_root = _host_trust_root(root)
    if lifecycle_state == "TRANSFER_RECORDED":
        artifacts = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in evo_v2_paths(root, REPORT_ID).items()
            if name
            in {
                "feedback_ledger",
                "mechanism_delta",
                "economic_backprojection",
                "experience_transfer_bundle",
                "transfer_use_receipt",
            }
            and path.is_file()
        }
        candidate = _build_bundle(root / "formal_transfer_support")
        shutil.copytree(
            root / "formal_transfer_support" / "support",
            root / "support",
            dirs_exist_ok=True,
        )
        transfer = copy.deepcopy(candidate["experience_transfer_bundle"])
        transfer["mechanism_delta_ref"]["sha256"] = artifact_sha256(
            artifacts["mechanism_delta"]
        )
        transfer["economic_backprojection_ref"]["sha256"] = artifact_sha256(
            artifacts["economic_backprojection"]
        )
        transfer = with_content_hash(transfer)
        use = copy.deepcopy(candidate["transfer_use_receipt"])
        use["mechanism_delta_ref"]["sha256"] = artifact_sha256(
            artifacts["mechanism_delta"]
        )
        use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
        use = with_content_hash(use)
        artifacts.update(
            {
                "experience_transfer_bundle": transfer,
                "transfer_use_receipt": use,
            }
        )
        review_state_root = root.parent / f".{root.name}-review-state"
        review_trust_root = review_state_root / "research-org-trust"
        review_state_root.mkdir(parents=True, exist_ok=True)
        if not review_trust_root.exists():
            shutil.copytree(trust_root, review_trust_root)
        original_installation_id = transfer_fixtures.INSTALLATION_ID
        transfer_fixtures.INSTALLATION_ID = INSTALLATION_ID
        try:
            transfer_path, use_path, decision_path, change_path = _formal_found_inputs(
                root,
                review_trust_root,
                artifacts,
            )
        finally:
            transfer_fixtures.INSTALLATION_ID = original_installation_id
        tests_path = _write_execution_tests(root, artifacts)
        result = orchestrate_evo_v2_transfer_use(
            workspace_root=root,
            report_id=REPORT_ID,
            expected_minimal_lifecycle_sha256=lifecycle_sha,
            expected_staging_content_sha256=staging_sha,
            experience_transfer_bundle_path=transfer_path,
            transfer_use_receipt_path=use_path,
            review_decision_receipt_path=decision_path,
            transfer_use_change_receipt_path=change_path,
            execution_tests_path=tests_path,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(root),
        )
    else:
        artifacts = _build_bundle(root)
        canonical = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in evo_v2_paths(root, REPORT_ID).items()
            if name in {"feedback_ledger", "mechanism_delta", "economic_backprojection"}
            and path.is_file()
        }
        transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
        transfer["mechanism_delta_ref"]["sha256"] = artifact_sha256(
            canonical["mechanism_delta"]
        )
        transfer["economic_backprojection_ref"]["sha256"] = artifact_sha256(
            canonical["economic_backprojection"]
        )
        transfer = with_content_hash(transfer)
        use = copy.deepcopy(artifacts["transfer_use_receipt"])
        use["mechanism_delta_ref"]["sha256"] = artifact_sha256(
            canonical["mechanism_delta"]
        )
        use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
        use = with_content_hash(use)
        artifacts.update(canonical)
        artifacts["experience_transfer_bundle"] = transfer
        artifacts["transfer_use_receipt"] = use
        cold_state_root = root.parent / f".{root.name}-cold-state"
        cold_trust_root = cold_state_root / "research-org-trust"
        cold_state_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(trust_root, cold_trust_root)
        original_installation_id = transfer_fixtures.INSTALLATION_ID
        transfer_fixtures.INSTALLATION_ID = INSTALLATION_ID
        try:
            transfer_path, use_path, cold_path = _formal_cold_inputs(
                root,
                cold_state_root,
                cold_trust_root,
                artifacts,
            )
        finally:
            transfer_fixtures.INSTALLATION_ID = original_installation_id
        result = orchestrate_evo_v2_transfer_use(
            workspace_root=root,
            report_id=REPORT_ID,
            expected_minimal_lifecycle_sha256=lifecycle_sha,
            expected_staging_content_sha256=staging_sha,
            experience_transfer_bundle_path=transfer_path,
            transfer_use_receipt_path=use_path,
            cold_start_search_receipt_path=cold_path,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )
    assert result["verdict"] == "PASS"
    assert result["lifecycle_state"] == lifecycle_state


def _approved_ready(root: Path) -> tuple[dict, dict, dict, Path, str]:
    synthesis, result, minimal, _council = _prepare_minimal(root)
    _complete_transfer_use_formal(root, minimal)
    _allocate_oos(root)
    receipt_path, trust_sha = _external_human_receipt(root, synthesis, result)
    approval = materialize_pre_oos_human_bridge(
        workspace_root=root,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(root),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(root),
    )
    return approval, synthesis, result, receipt_path, trust_sha


def test_external_human_pre_oos_bridge_needs_no_step6_iteration(
    tmp_path: Path,
) -> None:
    approval, _synthesis, _result, receipt_path, trust_sha = _approved_ready(tmp_path)
    assert approval["verdict"] == "PASS"
    assert approval["status"] == "EXTERNAL_HUMAN_APPROVED_CHILD_NOT_EXECUTED"
    assert approval["materialization_gate"] == (
        "WAITING_HOST_ATTESTED_CHILD_CONTROL_FREEZE"
    )
    assert approval["public_materialization_ready_ticket_ref"] is None
    assert approval["expected_host_trust_manifest_sha256"] == _host_manifest_pin(
        tmp_path
    )
    authorization_path = public_child_materialization_ticket_path(
        tmp_path,
        CHILD_ID,
        materialization_ready=False,
    )
    assert approval["public_materialization_authorization_ticket_ref"]["path"] == (
        authorization_path.relative_to(tmp_path).as_posix()
    )
    assert not (
        tmp_path
        / f"objects/research_iteration_master/research_iteration_master__{REPORT_ID}.json"
    ).exists()
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    assert handoff["contract_version"] == PRE_OOS_CHILD_HANDOFF_VERSION
    assert handoff["authority"]["child_execution_allowed"] is False
    assert handoff["fresh_oos_child_intent"]["child_report_id"] == CHILD_ID
    assert handoff["formal_transfer_use_orchestration_ref"]["content_sha256"]
    assert handoff["execution_addendum_ref"]["content_sha256"]
    approval_record = json.loads(
        pre_oos_human_approval_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    staging_ref = approval_record["evidence_bindings"]["staging_manifest_ref"]
    assert staging_ref["event_count"] == 4
    assert staging_ref["admit_transfer_event_sha256"]
    assert staging_ref["record_use_event_sha256"]
    assert (
        approval_record["evidence_bindings"]["formal_transfer_use_orchestration_ref"]
        == handoff["formal_transfer_use_orchestration_ref"]
    )
    assert (
        approval_record["evidence_bindings"]["execution_addendum_ref"]
        == handoff["execution_addendum_ref"]
    )
    child_intent = json.loads(
        pre_oos_child_intent_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )
    assert set(child_intent["approval_ref"]) == {
        "path",
        "sha256",
        "content_sha256",
    }
    assert set(child_intent["handoff_ref"]) == {
        "path",
        "sha256",
        "content_sha256",
    }
    assert (
        child_intent["formal_transfer_use_orchestration_ref"]
        == handoff["formal_transfer_use_orchestration_ref"]
    )
    assert child_intent["execution_addendum_ref"] == handoff["execution_addendum_ref"]
    public_ticket, public_reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        handoff=handoff,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert public_reasons == []
    assert public_ticket is not None
    assert public_ticket["ticket_state"] == "NOT_MATERIALIZED"
    assert public_ticket["authority"]["child_execution_allowed"] is False
    assert public_ticket["bindings"]["parent_data_prep_ref"]["content_sha256"]
    assert set(public_ticket["bindings"]["frozen_daily_input_refs"]) == {
        "daily_df_csv",
        "daily_input_meta_json",
        "evaluation_daily_df_parquet",
        "signal_daily_df_parquet",
    }
    replay = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert replay["idempotent_replay"] is True


def test_minimal_state_cannot_form_human_handoff_before_transfer_use(
    tmp_path: Path,
) -> None:
    synthesis, result, _minimal, _council = _prepare_minimal(tmp_path)
    _allocate_oos(tmp_path)
    receipt_path, trust_sha = _external_human_receipt(tmp_path, synthesis, result)
    with pytest.raises(PreOosHumanBridgeError) as captured:
        materialize_pre_oos_human_bridge(
            workspace_root=tmp_path,
            report_id=REPORT_ID,
            human_approval_receipt=receipt_path,
            human_trust_manifest_sha256=trust_sha,
            host_trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
        )
    assert WAITING_PRE_OOS_TRANSFER in captured.value.reasons
    assert not pre_oos_human_approval_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_handoff_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_intent_path(tmp_path, CHILD_ID).exists()


@pytest.mark.parametrize(
    "lifecycle_state",
    ["TRANSFER_RECORDED", "COLD_START_RECORDED"],
)
def test_low_level_four_stage_state_cannot_bypass_formal_transfer_orchestration(
    tmp_path: Path,
    lifecycle_state: str,
) -> None:
    synthesis, result, minimal, _council = _prepare_minimal(tmp_path)
    _complete_transfer_use_low_level_only(
        tmp_path,
        minimal,
        lifecycle_state=lifecycle_state,
    )
    _allocate_oos(tmp_path)
    receipt_path, trust_sha = _external_human_receipt(
        tmp_path,
        synthesis,
        result,
    )
    with pytest.raises(
        PreOosHumanBridgeError,
        match="formal_transfer_use",
    ):
        materialize_pre_oos_human_bridge(
            workspace_root=tmp_path,
            report_id=REPORT_ID,
            human_approval_receipt=receipt_path,
            human_trust_manifest_sha256=trust_sha,
            host_trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
        )
    assert not pre_oos_human_approval_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_handoff_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_intent_path(tmp_path, CHILD_ID).exists()


def test_cold_start_recorded_state_can_form_human_handoff(tmp_path: Path) -> None:
    synthesis, result, minimal, _council = _prepare_minimal(tmp_path)
    _complete_transfer_use_formal(
        tmp_path,
        minimal,
        lifecycle_state="COLD_START_RECORDED",
    )
    _allocate_oos(tmp_path)
    receipt_path, trust_sha = _external_human_receipt(tmp_path, synthesis, result)
    approval = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
    )
    assert approval["lifecycle_state"] == "COLD_START_RECORDED"
    assert approval["status"] == "EXTERNAL_HUMAN_APPROVED_CHILD_NOT_EXECUTED"
    approval_record = json.loads(
        pre_oos_human_approval_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    assert approval_record["evidence_bindings"]["execution_addendum_ref"] is None
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert reasons == []
    assert ticket is not None
    assert ticket["bindings"]["execution_addendum_ref"] is None
    assert ticket["bindings"]["child_controls"]["expected_execution_test_count"] == 0


def test_pre_oos_materializer_uses_handoff_without_step6_iteration(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    _write_json(
        tmp_path / f"objects/alpha_idea_master/alpha_idea_master__{REPORT_ID}.json",
        {"report_id": REPORT_ID},
    )
    environment = os.environ.copy()
    environment["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    command = [
        sys.executable,
        str(
            REPO_ROOT
            / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
        ),
        "--factorforge-root",
        str(tmp_path),
        "--parent-report-id",
        REPORT_ID,
        "--child-report-id",
        CHILD_ID,
        "--incident-trust-root",
        str(_host_trust_root(tmp_path)),
        "--incident-installation-id",
        INSTALLATION_ID,
    ]
    missing_pin = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_pin.returncode == 1
    assert "external_host_trust_pin_required" in missing_pin.stdout
    completed = subprocess.run(
        [
            *command,
            "--expected-host-trust-manifest-sha256",
            _host_manifest_pin(tmp_path),
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 3, completed.stdout + completed.stderr
    assert "WAITING_FACTORFORGE_EVO_CHILD_MATERIALIZATION_TICKET_READY" in (
        completed.stdout
    )
    assert "APPROVED_CHILD_REVISION_MISSING" not in completed.stdout


def test_handoff_tamper_fails_exact_projection_replay(tmp_path: Path) -> None:
    _approved_ready(tmp_path)
    path = pre_oos_child_handoff_path(tmp_path, REPORT_ID)
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["selected_revision"]["child_formula"] = "volume"
    handoff.pop("content_sha256")
    handoff["content_sha256"] = stable_hash(handoff)
    _write_json(path, handoff)
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert validated is None
    assert any("exact_projection" in reason for reason in reasons)


def test_public_ticket_tamper_cannot_replace_host_projection(tmp_path: Path) -> None:
    _approved_ready(tmp_path)
    path = public_child_materialization_ticket_path(
        tmp_path,
        CHILD_ID,
        materialization_ready=False,
    )
    ticket = json.loads(path.read_text(encoding="utf-8"))
    ticket["bindings"]["oos_registry_prefix_ref"]["allocation_event_sha256"] = "0" * 64
    path.write_bytes(evo_canonical_json_bytes(ticket))
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert validated is None
    assert any(
        "ticket_signature" in reason
        or "ticket_shape_or_identity" in reason
        or "ticket_exact_projection" in reason
        for reason in reasons
    )


def test_public_ticket_requires_external_host_trust_pin(tmp_path: Path) -> None:
    _approved_ready(tmp_path)
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
    )
    assert validated is None
    assert any("external_host_trust_pin_required" in reason for reason in reasons)


def test_public_ticket_accepts_valid_registry_append_descendant(tmp_path: Path) -> None:
    _approval, _synthesis, _result, receipt_path, trust_sha = _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    child_ticket.materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        materialization_ready=True,
    )
    _append_unrelated_oos_allocation(tmp_path)
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert reasons == []
    assert ticket is not None
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    materializer_reasons = (
        _load_child_materializer_module().evo_child_control_preflight(
            root=tmp_path,
            parent=REPORT_ID,
            child=CHILD_ID,
            parent_handoff=handoff,
        )
    )
    assert not any("oos_registry_binding" in reason for reason in materializer_reasons)
    replay = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert replay["idempotent_replay"] is True


def test_public_ticket_rejects_consumed_target_allocation(tmp_path: Path) -> None:
    _approved_ready(tmp_path)
    _consume_primary_oos(tmp_path)
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert ticket is None
    assert any("allocation_consumed" in reason for reason in reasons)


@pytest.mark.parametrize(
    "input_key",
    [
        "daily_df_csv",
        "evaluation_daily_df_parquet",
        "signal_daily_df_parquet",
        "daily_input_meta_json",
    ],
)
def test_public_ticket_rejects_frozen_parent_daily_input_tamper(
    tmp_path: Path,
    input_key: str,
) -> None:
    _approved_ready(tmp_path)
    prep = json.loads(
        (
            tmp_path / f"objects/data_prep_master/data_prep_master__{REPORT_ID}.json"
        ).read_text(encoding="utf-8")
    )
    path = tmp_path / prep["local_input_paths"][input_key]
    path.write_bytes(path.read_bytes() + b"tamper")
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert ticket is None
    assert any("ticket_exact_projection" in reason for reason in reasons)


def test_public_ticket_writer_and_lock_reject_symlink_parent_without_external_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    (root / "objects").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "objects/research_protocol").symlink_to(
        outside,
        target_is_directory=True,
    )
    path = public_child_materialization_ticket_path(
        root,
        CHILD_ID,
        materialization_ready=False,
    )
    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match="ticket_output_parent_unsafe",
    ):
        child_ticket._atomic_write_once(root, path, {"sentinel": True})
    with (
        pytest.raises(
            child_ticket.PublicChildMaterializationTicketError,
            match="ticket_output_parent_unsafe",
        ),
        child_ticket._ticket_lock(root, CHILD_ID),
    ):
        raise AssertionError("unreachable")
    assert list(outside.iterdir()) == []


def test_public_ticket_atomic_partial_write_is_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    path = public_child_materialization_ticket_path(
        root,
        CHILD_ID,
        materialization_ready=False,
    )
    payload = {"sentinel": "recoverable"}
    real_write = child_ticket.os.write
    writes = 0

    def partial_then_fail(descriptor: int, data: bytes) -> int:
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(descriptor, data[:17])
        raise OSError("injected_ticket_write_failure")

    monkeypatch.setattr(child_ticket.os, "write", partial_then_fail)
    with pytest.raises(OSError, match="injected_ticket_write_failure"):
        child_ticket._atomic_write_once(root, path, payload)
    assert not path.exists()
    monkeypatch.setattr(child_ticket.os, "write", real_write)
    assert child_ticket._atomic_write_once(root, path, payload) is False
    assert child_ticket._atomic_write_once(root, path, payload) is True


def test_detached_handoff_payload_cannot_bypass_canonical_readback(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    path = pre_oos_child_handoff_path(tmp_path, REPORT_ID)
    handoff = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert validated is None
    assert any("handoff_readback" in reason for reason in reasons)


def test_partial_private_replay_credentials_cannot_fall_back_to_public_ticket(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        admissions_root=_admissions_root(tmp_path),
    )
    assert validated is None
    assert any("partial_private_replay_credentials" in reason for reason in reasons)


def test_found_handoff_replay_requires_canonical_execution_addendum(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    execution_addendum_path(tmp_path, REPORT_ID).unlink()
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert validated is None
    assert any("execution_addendum" in reason for reason in reasons)


def test_child_intent_formal_reference_tamper_blocks_handoff_replay(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    intent_path = pre_oos_child_intent_path(tmp_path, CHILD_ID)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["formal_transfer_use_orchestration_ref"]["sha256"] = "0" * 64
    intent.pop("content_sha256")
    intent["content_sha256"] = stable_hash(intent)
    _write_json(intent_path, intent)
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert validated is None
    assert any("child_intent_exact_projection" in reason for reason in reasons)


def test_public_authorization_replays_but_cannot_claim_materialization_ready(
    tmp_path: Path,
) -> None:
    _approval, _synthesis, _result, receipt_path, trust_sha = _approved_ready(tmp_path)
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    validated, reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        require_materialization_ready=False,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert reasons == []
    assert validated == handoff
    ready, ready_reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert ready is None
    assert any(
        reason.startswith(WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET)
        for reason in ready_reasons
    )
    replay = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert replay["idempotent_replay"] is True
    assert replay["materialization_gate"] == (
        "WAITING_HOST_ATTESTED_CHILD_CONTROL_FREEZE"
    )
    assert len(list(tmp_path.rglob(f"handoff_to_step3b__{REPORT_ID}.json"))) == 1
    assert len(list(tmp_path.rglob(f"pre_oos_human_approval__{REPORT_ID}.json"))) == 1
    assert len(list(tmp_path.rglob(f"evo_child_intent__{CHILD_ID}.json"))) == 1


def test_ready_ticket_rejects_handwritten_controls_without_formal_receipt(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    addendum = json.loads(
        execution_addendum_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    _write_handwritten_child_controls(tmp_path, execution_addendum=addendum)

    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match="child_preregistration_receipt",
    ):
        child_ticket.materialize_public_child_materialization_ticket(
            workspace_root=tmp_path,
            parent_report_id=REPORT_ID,
            child_report_id=CHILD_ID,
            trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
            materialization_ready=True,
        )
    assert not public_child_materialization_ticket_path(
        tmp_path,
        CHILD_ID,
        materialization_ready=True,
    ).exists()


def test_found_ready_ticket_binds_exact_addendum_trials_and_all_child_controls(
    tmp_path: Path,
) -> None:
    _approval, _synthesis, _result, human_receipt, trust_sha = _approved_ready(tmp_path)
    addendum = json.loads(
        execution_addendum_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    prereg = _materialize_ready_child_preregistration(tmp_path)
    assert prereg["verdict"] == "PASS"
    prereg_replay = _materialize_ready_child_preregistration(tmp_path)
    assert prereg_replay["idempotent_replay"] is True
    bridge_replay = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=human_receipt,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
    )
    assert bridge_replay["materialization_gate"] == (
        "PUBLIC_HOST_TICKET_READY_FOR_CHILD_INPUT_MATERIALIZATION"
    )
    assert bridge_replay["public_materialization_ready_ticket_ref"] is not None
    issued = child_ticket.materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        materialization_ready=True,
    )
    assert issued["status"] == "MATERIALIZATION_READY"
    assert issued["idempotent_replay"] is True
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert reasons == []
    assert ticket is not None
    controls = ticket["bindings"]["child_controls"]
    assert set(controls["refs"]) == {
        "research_state",
        "research_conjecture",
        "approach_registry",
        "search_trial_ledger",
        "metric_verifier_spec",
        "threshold_registration",
    }
    assert controls["expected_execution_test_count"] == len(addendum["execution_tests"])
    assert controls["expected_execution_tests_sha256"] == stable_json_hash(
        addendum["execution_tests"]
    )
    ledger = json.loads(
        child_control_paths(tmp_path, CHILD_ID)["search_trial_ledger"].read_text(
            encoding="utf-8"
        )
    )
    child_plan = json.loads(
        child_web_research_plan_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )["web_research_plan"]
    assert ledger["trial_count"] == 1 + len(addendum["execution_tests"])
    assert ledger["trial_count"] <= child_plan["evidence_policy"]["trial_budget"]
    strict_prereg = validate_evo_child_preregistration_receipt(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert controls["preregistration_receipt_ref"] == strict_prereg["receipt_ref"]
    assert (
        controls["child_web_research_plan_ref"]
        == strict_prereg["child_web_research_plan_ref"]
    )
    assert controls["frozen_artifact_count"] == strict_prereg["frozen_artifact_count"]
    assert ticket["authority"]["child_inputs_materialization_allowed"] is True
    assert ticket["authority"]["child_execution_allowed"] is False
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    private_replay, private_reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        require_materialization_ready=True,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert private_reasons == []
    assert private_replay == handoff


def test_ready_ticket_rejects_frozen_ledger_missing_addendum_trials(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    controls = child_control_paths(tmp_path, CHILD_ID)
    ledger = json.loads(controls["search_trial_ledger"].read_text(encoding="utf-8"))
    ledger["trials"] = []
    ledger["trial_count"] = 0
    ledger["trial_set_sha256"] = stable_json_hash([])
    _write_json(controls["search_trial_ledger"], ledger)
    threshold = json.loads(
        controls["threshold_registration"].read_text(encoding="utf-8")
    )
    threshold["search_trial_ledger_sha256"] = sha256_file(
        controls["search_trial_ledger"]
    )
    _write_json(controls["threshold_registration"], threshold)
    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match=(
            "child_preregistration_receipt.*"
            "search_trial_ledger_not_exact_authoring_projection"
        ),
    ):
        child_ticket.materialize_public_child_materialization_ticket(
            workspace_root=tmp_path,
            parent_report_id=REPORT_ID,
            child_report_id=CHILD_ID,
            trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
            materialization_ready=True,
        )


def _bridge_incident_payload(root: Path, *, report_id: str = REPORT_ID) -> dict:
    evidence = root / f"incident-evidence-{report_id.replace(':', '_')}"
    evidence.mkdir(exist_ok=True)
    artifacts: list[Path] = []
    for name in ("source.csv", "panel.parquet", "metrics.json", "runner.py"):
        path = evidence / name
        path.write_text(name, encoding="utf-8")
        artifacts.append(path)
    return build_oos_exposure_incident(
        workspace_root=root,
        report_id=report_id,
        factor_id="negative_pv_shape",
        frozen_oos_start="2026-01-01",
        frozen_oos_end="2026-03-31",
        frozen_oos_release_token_sha256="a" * 64,
        exposed_overlap_start="2026-01-01",
        exposed_overlap_end="2026-01-31",
        exposed_row_count=1,
        exposed_period_count=1,
        source_path=artifacts[0],
        panel_path=artifacts[1],
        metrics_path=artifacts[2],
        runner_path=artifacts[3],
        incident_at="2026-08-13T08:00:00Z",
    )


def _pre_bridge_ready(root: Path) -> tuple[Path, str]:
    synthesis, result, minimal, _council = _prepare_minimal(root)
    _complete_transfer_use_formal(root, minimal)
    _allocate_oos(root)
    return _external_human_receipt(root, synthesis, result)


def test_incident_writer_first_leaves_zero_bridge_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, trust_sha = _pre_bridge_ready(tmp_path)
    payload = _bridge_incident_payload(tmp_path)
    writer_has_guard = threading.Event()
    release_writer = threading.Event()
    bridge_requested_guard = threading.Event()
    writer_errors: list[BaseException] = []
    bridge_errors: list[BaseException] = []

    real_append = incident_module._append_private_incident_event

    def paused_append(**kwargs):
        writer_has_guard.set()
        assert release_writer.wait(5)
        return real_append(**kwargs)

    monkeypatch.setattr(incident_module, "_append_private_incident_event", paused_append)
    real_bridge_guard = bridge_module.oos_exposure_private_registry_guard

    @contextmanager
    def observed_bridge_guard(*args, **kwargs):
        bridge_requested_guard.set()
        with real_bridge_guard(*args, **kwargs) as guard:
            yield guard

    monkeypatch.setattr(
        bridge_module,
        "oos_exposure_private_registry_guard",
        observed_bridge_guard,
    )

    def writer() -> None:
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=tmp_path,
                payload=payload,
                trust_root=_host_trust_root(tmp_path),
                installation_id=INSTALLATION_ID,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    def bridge() -> None:
        try:
            materialize_pre_oos_human_bridge(
                workspace_root=tmp_path,
                report_id=REPORT_ID,
                human_approval_receipt=receipt_path,
                human_trust_manifest_sha256=trust_sha,
                host_trust_root=_host_trust_root(tmp_path),
                installation_id=INSTALLATION_ID,
                admissions_root=_admissions_root(tmp_path),
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            bridge_errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_has_guard.wait(3)
    bridge_thread = threading.Thread(target=bridge)
    bridge_thread.start()
    assert bridge_requested_guard.wait(3)
    assert not pre_oos_human_approval_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_handoff_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_intent_path(tmp_path, CHILD_ID).exists()
    assert not public_child_materialization_ticket_path(
        tmp_path, CHILD_ID, materialization_ready=False
    ).exists()

    release_writer.set()
    writer_thread.join(5)
    bridge_thread.join(5)
    assert not writer_thread.is_alive()
    assert not bridge_thread.is_alive()
    assert writer_errors == []
    assert len(bridge_errors) == 1
    assert isinstance(bridge_errors[0], PreOosHumanBridgeError)
    assert "oos_exposure_incident" in str(bridge_errors[0]).lower()
    assert not pre_oos_human_approval_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_handoff_path(tmp_path, REPORT_ID).exists()
    assert not pre_oos_child_intent_path(tmp_path, CHILD_ID).exists()
    assert not public_child_materialization_ticket_path(
        tmp_path, CHILD_ID, materialization_ready=False
    ).exists()


def test_bridge_first_serializes_projection_then_incident_blocks_current_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, trust_sha = _pre_bridge_ready(tmp_path)
    payload = _bridge_incident_payload(tmp_path)
    ticket_readback_done = threading.Event()
    release_bridge = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    bridge_results: list[dict] = []
    bridge_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []
    real_ticket_materializer = child_ticket.materialize_public_child_materialization_ticket

    def paused_ticket_materializer(**kwargs):
        result = real_ticket_materializer(**kwargs)
        if kwargs.get("materialization_ready") is False:
            ticket_readback_done.set()
            assert release_bridge.wait(5)
        return result

    monkeypatch.setattr(
        child_ticket,
        "materialize_public_child_materialization_ticket",
        paused_ticket_materializer,
    )

    def bridge() -> None:
        try:
            bridge_results.append(
                materialize_pre_oos_human_bridge(
                    workspace_root=tmp_path,
                    report_id=REPORT_ID,
                    human_approval_receipt=receipt_path,
                    human_trust_manifest_sha256=trust_sha,
                    host_trust_root=_host_trust_root(tmp_path),
                    installation_id=INSTALLATION_ID,
                    admissions_root=_admissions_root(tmp_path),
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            bridge_errors.append(exc)

    def writer() -> None:
        writer_started.set()
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=tmp_path,
                payload=payload,
                trust_root=_host_trust_root(tmp_path),
                installation_id=INSTALLATION_ID,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    bridge_thread = threading.Thread(target=bridge)
    bridge_thread.start()
    assert ticket_readback_done.wait(5)
    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_started.wait(2)
    assert not writer_done.wait(0.1)
    assert pre_oos_human_approval_path(tmp_path, REPORT_ID).is_file()
    assert pre_oos_child_handoff_path(tmp_path, REPORT_ID).is_file()
    assert pre_oos_child_intent_path(tmp_path, CHILD_ID).is_file()
    assert public_child_materialization_ticket_path(
        tmp_path, CHILD_ID, materialization_ready=False
    ).is_file()

    release_bridge.set()
    bridge_thread.join(5)
    writer_thread.join(5)
    assert not bridge_thread.is_alive()
    assert not writer_thread.is_alive()
    assert bridge_errors == []
    assert writer_errors == []
    assert len(bridge_results) == 1
    assert bridge_results[0]["verdict"] == "PASS"

    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    structural, structural_reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert structural_reasons == []
    assert structural == handoff
    current, current_reasons = validate_pre_oos_child_handoff(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        handoff=handoff,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
    )
    assert current is None
    assert any("oos_exposure_incident" in reason.lower() for reason in current_reasons)


def test_ready_ticket_explicitly_replays_private_incident_after_public_marker_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    evidence = tmp_path / "incident-evidence"
    evidence.mkdir()
    artifacts = []
    for name in ("source.csv", "panel.parquet", "metrics.json", "runner.py"):
        path = evidence / name
        path.write_text(name, encoding="utf-8")
        artifacts.append(path)
    incident = build_oos_exposure_incident(
        workspace_root=tmp_path,
        report_id=CHILD_ID,
        factor_id="negative_pv_shape",
        frozen_oos_start="2026-01-01",
        frozen_oos_end="2026-03-31",
        frozen_oos_release_token_sha256="a" * 64,
        exposed_overlap_start="2026-01-01",
        exposed_overlap_end="2026-01-31",
        exposed_row_count=1,
        exposed_period_count=1,
        source_path=artifacts[0],
        panel_path=artifacts[1],
        metrics_path=artifacts[2],
        runner_path=artifacts[3],
        incident_at="2026-08-13T08:00:00Z",
    )
    write_oos_exposure_incident_create_only(
        workspace_root=tmp_path,
        payload=incident,
    )
    register_oos_exposure_incident_host_private(
        workspace_root=tmp_path,
        report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
    )
    oos_exposure_incident_path(tmp_path, CHILD_ID).unlink()
    for name in (
        "FACTORFORGE_OOS_EXPOSURE_TRUST_ROOT",
        "FACTORFORGE_OOS_EXPOSURE_INSTALLATION_ID",
        "FACTORFORGE_OOS_HOST_TRUST_ROOT",
        "FACTORFORGE_OOS_HOST_INSTALLATION_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match="private_registry_incident",
    ):
        child_ticket.materialize_public_child_materialization_ticket(
            workspace_root=tmp_path,
            parent_report_id=REPORT_ID,
            child_report_id=CHILD_ID,
            trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
            materialization_ready=True,
        )


@pytest.mark.parametrize(
    "hash_field",
    ["window_hash", "evaluation_contract_hash", "label_contract_hash"],
)
def test_ready_ticket_rejects_threshold_contract_hash_tamper(
    tmp_path: Path,
    hash_field: str,
) -> None:
    _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    threshold_path = child_control_paths(tmp_path, CHILD_ID)["threshold_registration"]
    threshold = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold[hash_field] = "0" * 64
    _write_json(threshold_path, threshold)
    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match="child_preregistration_receipt.*threshold_registration_not_exact_projection",
    ):
        child_ticket.materialize_public_child_materialization_ticket(
            workspace_root=tmp_path,
            parent_report_id=REPORT_ID,
            child_report_id=CHILD_ID,
            trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
            materialization_ready=True,
        )


def test_ready_ticket_exact_replay_rejects_metric_spec_tamper(tmp_path: Path) -> None:
    _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    child_ticket.materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        materialization_ready=True,
    )
    spec_path = child_metric_verifier_spec_path(tmp_path, CHILD_ID)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["label_contract"]["forward_return_column"] = "tampered_future_return"
    _write_json(spec_path, spec)
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert ticket is None
    assert any("child_preregistration_receipt" in reason for reason in reasons)


def test_ready_ticket_public_replay_rejects_child_plan_tamper(
    tmp_path: Path,
) -> None:
    _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    child_ticket.materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(tmp_path),
        materialization_ready=True,
    )
    plan_path = child_web_research_plan_path(tmp_path, CHILD_ID)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["web_research_plan"]["research_object"]["expected_direction"] = "negative"
    _write_json(plan_path, plan)

    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert ticket is None
    assert any("child_preregistration_receipt" in reason for reason in reasons)


def test_bridge_blocks_tampered_preregistration_receipt_instead_of_waiting(
    tmp_path: Path,
) -> None:
    _approval, _synthesis, _result, human_receipt, trust_sha = _approved_ready(tmp_path)
    _materialize_ready_child_preregistration(tmp_path)
    receipt_path = child_preregistration_receipt_path(tmp_path, CHILD_ID)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "TAMPERED"
    _write_json(receipt_path, receipt)

    with pytest.raises(
        child_ticket.PublicChildMaterializationTicketError,
        match="child_preregistration_receipt",
    ):
        materialize_pre_oos_human_bridge(
            workspace_root=tmp_path,
            report_id=REPORT_ID,
            human_approval_receipt=human_receipt,
            human_trust_manifest_sha256=trust_sha,
            host_trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            admissions_root=_admissions_root(tmp_path),
        )
    assert not public_child_materialization_ticket_path(
        tmp_path,
        CHILD_ID,
        materialization_ready=True,
    ).exists()


def test_cold_ready_ticket_requires_zero_evo_transfer_trials(tmp_path: Path) -> None:
    synthesis, result, minimal, _council = _prepare_minimal(tmp_path)
    _complete_transfer_use_formal(
        tmp_path,
        minimal,
        lifecycle_state="COLD_START_RECORDED",
    )
    _allocate_oos(tmp_path)
    receipt_path, trust_sha = _external_human_receipt(tmp_path, synthesis, result)
    materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
    )
    prereg = _materialize_ready_child_preregistration(tmp_path)
    assert prereg["verdict"] == "PASS"
    bridge_replay = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
    )
    assert bridge_replay["materialization_gate"] == (
        "PUBLIC_HOST_TICKET_READY_FOR_CHILD_INPUT_MATERIALIZATION"
    )
    issued = child_ticket.materialize_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        materialization_ready=True,
    )
    assert issued["status"] == "MATERIALIZATION_READY"
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        require_materialization_ready=True,
        expected_host_trust_manifest_sha256=_host_manifest_pin(tmp_path),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    )
    assert reasons == []
    assert ticket is not None
    assert ticket["bindings"]["execution_addendum_ref"] is None
    assert ticket["bindings"]["child_controls"]["expected_execution_test_count"] == 0
    ledger = json.loads(
        child_control_paths(tmp_path, CHILD_ID)["search_trial_ledger"].read_text(
            encoding="utf-8"
        )
    )
    child_plan = json.loads(
        child_web_research_plan_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )["web_research_plan"]
    assert all(
        item.get("trial_kind") != "EVO_TRANSFER_DIAGNOSTIC"
        for item in ledger["trials"]
    )
    assert ledger["trial_count"] == 1
    assert ledger["trial_count"] <= child_plan["evidence_policy"]["trial_budget"]
