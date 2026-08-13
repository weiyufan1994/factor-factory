from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

import factor_factory.evo_child_preregistration as prereg
from factor_factory.evo_child_authoring import evo_child_authoring_paths
from factor_factory.console.web_factor_proof import (
    _trusted_calendar_snapshot,
    prepare_web_factor_proof,
)
from factor_factory.console.web_research_plan import build_web_evaluation_contract
from factor_factory.evo_child_execution import (
    EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND,
    validate_frozen_child_execution_ledger,
)
from factor_factory.console.web_factor_proof import default_web_decision_rules
from factor_factory.evo_oos import (
    OOS_ALLOCATION_VERSION,
    OOS_HOST_AUTHORITY,
    child_control_paths,
)
from factor_factory.evo_v2 import (
    canonical_json_bytes,
    stable_json_hash,
    with_content_hash,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_policy_v2,
    validate_protocol_bundle,
)
from factor_factory.research_release import (
    METRIC_VERIFIER_SPEC_VERSION,
    METRIC_THRESHOLD_REGISTRATION_VERSION,
    SEARCH_TRIAL_LEDGER_VERSION,
    evaluation_contract_hash,
    stable_hash,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from scripts.run_factorforge_research_protocol_smoke import (
    valid_approaches,
    valid_conjecture,
    valid_state,
)


PARENT = "PARENT_EVO_REPORT"
CHILD = "PARENT_EVO_REPORT__EVO_CHILD_001"
FACTOR = "SMOKE_FACTOR"
RESEARCH = "smoke_research"
FORMULA_HASH = "c" * 64
DATASET_HASH = "d" * 64
PARENT_ARTIFACT_HASH = "b" * 64
HOST_TRUST_PIN = "e" * 64


@pytest.fixture(autouse=True)
def _incident_host_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path / "host-incident-trust"
    ensure_runtime_trust_store(
        trust_root,
        installation_id="child-prereg-test",
    )
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT",
        str(trust_root),
    )
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID",
        "child-prereg-test",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _authoring_admission_path(root: Path) -> Path:
    return evo_child_authoring_paths(root, CHILD)["admission"]


def _ref(root: Path, path: Path, payload: dict | None = None) -> dict[str, str]:
    output = {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if payload is not None and "content_sha256" in payload:
        output["content_sha256"] = payload["content_sha256"]
    return output


def _base_ledger(conjecture: dict | None = None) -> dict:
    trials = [
        {
            "trial_id": "child_primary_trial_001",
            "status": "REGISTERED_NOT_EVALUATED",
            "hypothesis_id": "preferred_flow_constraint",
        }
    ]
    if conjecture is None:
        conjecture = valid_conjecture()
        conjecture.update({"report_id": CHILD, "factor_id": FACTOR})
        conjecture["identity"]["formula_hash"] = FORMULA_HASH
    search_identity = prereg.project_evo_child_search_identities(conjecture)
    return {
        "version": SEARCH_TRIAL_LEDGER_VERSION,
        "search_status": "FROZEN",
        "report_id": CHILD,
        "factor_id": FACTOR,
        "freeze_sequence": 10,
        "trial_count": len(trials),
        "trials": trials,
        "trial_set_sha256": stable_json_hash(trials),
        "candidate_space_sha256": search_identity["candidate_space_sha256"],
        "selected_hypothesis_sha256": search_identity[
            "selected_hypothesis_sha256"
        ],
    }


def _addendum(root: Path) -> tuple[Path, dict]:
    test = {
        "test_id": "transfer_test_001",
        "implementation_mode": "FORMULA_DIAGNOSTIC",
        "execution_stage": "FRESH_CHILD_PURGED_IS",
        "information_set": "PURGED_IS_ONLY",
        "multiple_testing_family": "diagnostic_only_no_acceptance",
        "affects_acceptance": False,
    }
    payload = with_content_hash(
        {
            "contract_version": "factorforge_evo_execution_addendum_v1",
            "report_id": PARENT,
            "execution_tests": [test],
        }
    )
    path = root / "objects/evo_v2" / PARENT / "execution_addendum.json"
    _write_json(path, payload)
    return path, payload


def _semantic_inputs(root: Path) -> tuple[dict, dict, dict]:
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, {"workspace": "child_preregistration_test"})
    state = valid_state()
    state.update(
        {
            "report_id": CHILD,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
            "budget_used": {"trials_used": 1, "trial_budget": 20},
        }
    )
    conjecture = valid_conjecture()
    conjecture.update(
        {
            "report_id": CHILD,
            "factor_id": FACTOR,
            "epistemic_evolution": epistemic_evolution_policy_v2(),
        }
    )
    conjecture["identity"].update(
        {
            "research_id": RESEARCH,
            "workspace_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "parent_artifact_sha256": PARENT_ARTIFACT_HASH,
            "formula_hash": FORMULA_HASH,
            "data_catalog_snapshot_sha256": DATASET_HASH,
        }
    )
    conjecture["evidence_policy"].update(
        {"trials_used": 1, "trial_budget": 20}
    )
    approaches = valid_approaches()
    approaches["report_id"] = CHILD
    return state, conjecture, approaches


def _calendar_dates() -> list[str]:
    start = date(2025, 1, 1)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(365)]


def _parent_metric_spec() -> dict:
    window = {
        "evaluation_window_role": "OOS_FINAL",
        "oos_window": "2025-01-01/2025-12-31",
        "observed_start_date": "2025-01-01",
        "observed_end_date": "2025-12-29",
        "minimum_periods": 60,
        "oos_release_token_hash": "9" * 64,
        "forward_return_horizon": "t+1 close to t+2 close",
        "forward_return_horizon_days": 1,
        "sample_frequency": "daily",
        "signal_timestamp": "t close",
        "execution_timestamp": "t+1 close",
        "label_start_timestamp": "t+1 close",
        "label_end_timestamp": "t+2 close",
        "forward_return_formula": "label_end_price/label_start_price-1",
        "path_is_disjoint": True,
        "universe_id": "a_share_investable_core",
        "investability_mask_id": "tradability_risk_flags_daily",
        "search_frozen_before_oos_release": True,
        "return_convention": "simple_return",
        "search_trial_ledger_ref": (
            f"objects/research_protocol/search_trial_ledger__{PARENT}.json"
        ),
        "oos_release_manifest_ref": (
            f"objects/research_protocol/oos_release_manifest__{PARENT}.json"
        ),
    }
    return {
        "version": METRIC_VERIFIER_SPEC_VERSION,
        "verification_scope": "production",
        "report_id": PARENT,
        "factor_id": FACTOR,
        "research_id": RESEARCH,
        "claim_class": "information_rent",
        "cost_policy_id": "a_share_cost_v1",
        "research_windows": {
            "is_window": "2020-01-01/2024-12-31",
            "oos_window": "2025-01-01/2025-12-31",
        },
        "panel": {
            "date_column": "trade_date",
            "asset_column": "code",
            "signal_column": "factor_value",
            "forward_return_column": "future_return_1d",
            "control_columns": ["pct_chg"],
            "source_control_columns": ["pct_chg"],
            "diagnostic_signal_columns": {},
        },
        "label_contract": {
            "version": "factorforge_daily_return_label_contract_v1",
            "signal_date_column": "trade_date",
            "forward_return_column": "future_return_1d",
            "label_start_timestamp": "t+1 close",
            "label_end_timestamp": "t+2 close",
        },
        "window_contract": window,
        "portfolio": {
            "annualization_factor": 252,
            "long_quantile": 0.1,
            "cost_bps_per_turnover": 10.0,
            "other_annual_costs": 0.0,
        },
        "fama_macbeth": {"newey_west_lags": 3},
        "bucket_monotonicity": {
            "bucket_count": 10,
            "expected_direction": "ascending",
        },
        "threshold_registration_ref": (
            f"objects/research_protocol/threshold_registration__{PARENT}.json"
        ),
        "window_hash": stable_hash(window),
    }


def _parent_contracts(root: Path) -> dict:
    plan_path = root / "identity/web_research_plan.json"
    parent_conjecture_path = (
        root / f"objects/research_protocol/research_conjecture__{PARENT}.json"
    )
    spec_path = (
        root / f"objects/research_protocol/metric_verifier_spec__{PARENT}.json"
    )
    threshold_path = (
        root / f"objects/research_protocol/threshold_registration__{PARENT}.json"
    )
    preregistration_path = (
        root
        / f"objects/research_protocol/web_factor_proof_preregistration__{PARENT}.json"
    )
    plan = {"identity": {"report_id": PARENT}}
    parent_conjecture = valid_conjecture()
    parent_conjecture.update({"report_id": PARENT, "factor_id": FACTOR})
    parent_conjecture["identity"].update(
        {
            "research_id": RESEARCH,
            "data_catalog_snapshot_sha256": DATASET_HASH,
        }
    )
    spec = _parent_metric_spec()
    rules = default_web_decision_rules("information_rent")
    threshold = {
        "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
        "registration_status": "LOCKED",
        "report_id": PARENT,
        "factor_id": FACTOR,
        "decision_rules": rules,
    }
    for path, payload in (
        (plan_path, plan),
        (parent_conjecture_path, parent_conjecture),
        (spec_path, spec),
        (threshold_path, threshold),
        (preregistration_path, {"status": "LOCKED"}),
    ):
        _write_json(path, payload)
    return {
        "plan": plan,
        "plan_path": plan_path,
        "research_conjecture": parent_conjecture,
        "research_conjecture_path": parent_conjecture_path,
        "metric_verifier_spec": spec,
        "metric_verifier_spec_path": spec_path,
        "threshold_registration": threshold,
        "threshold_registration_path": threshold_path,
        "web_preregistration_path": preregistration_path,
        "calendar_dates": _calendar_dates(),
        "source_file_sha256s": {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                plan_path,
                parent_conjecture_path,
                spec_path,
                threshold_path,
                preregistration_path,
            )
        },
    }


def _authorization(
    root: Path,
    *,
    found: bool,
) -> dict:
    authorization_path = (
        root
        / "objects/research_protocol"
        / f"evo_child_materialization_ticket__{CHILD}__authorization.json"
    )
    _write_json(authorization_path, {"test_authorization": True})
    handoff = {
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "parent_identity": {
            "report_id": PARENT,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
            "run_id": "parent_run_001",
        },
        "pre_oos_root_synthesis_ref": {
            "path": "objects/research_iteration_master/root_synthesis.json",
            "sha256": PARENT_ARTIFACT_HASH,
        },
        "selected_revision": {
            "law_id": "minimal_delta_law_001",
            "child_formula": "close",
            "child_formula_hash": FORMULA_HASH,
        },
    }
    handoff_path = root / "objects/handoff" / f"handoff_to_step3b__{PARENT}.json"
    _write_json(handoff_path, handoff)
    allocation = with_content_hash(
        {
            "contract_version": OOS_ALLOCATION_VERSION,
            "allocation_id": "allocation_child_001",
            "report_id": CHILD,
            "parent_report_id": PARENT,
            "lineage_root_report_id": PARENT,
            "dataset_snapshot_sha256": DATASET_HASH,
            "oos_window": {"start": "2025-01-01", "end": "2025-12-31"},
            "sealed_token_sha256": "a" * 64,
            "sealed_carrier_sha256": "9" * 64,
            "build_authority_sha256": "8" * 64,
            "release_state": "SEALED_UNRELEASED",
            "consumed": False,
            "host_authority": OOS_HOST_AUTHORITY,
            "allocation_authority_mode": "HOST_PRIVATE_CARRIER_DERIVED",
        }
    )
    allocation_path = (
        root
        / "objects/research_protocol"
        / f"evo_oos_allocation__{CHILD}.json"
    )
    _write_json(allocation_path, allocation)
    addendum_path: Path | None = None
    addendum: dict | None = None
    if found:
        addendum_path, addendum = _addendum(root)
    ticket = {
        "memory_state": (
            "ADMISSIBLE_MEMORY_FOUND"
            if found
            else "COLD_START_NO_ADMISSIBLE_MEMORY"
        ),
        "selected_revision": {"child_formula_hash": FORMULA_HASH},
    }
    parent_contracts = _parent_contracts(root)
    parent_contracts["calendar"] = {
        "dates": list(parent_contracts["calendar_dates"]),
        "open_dates_sha256": "1" * 64,
        "raw_file_sha256": "2" * 64,
        "registry_sha256": "3" * 64,
        "registry_git_commit": "test-calendar-commit",
        "registry_git_blob": "test-calendar-blob",
        "snapshot_id": "test-calendar-snapshot",
    }
    execution_verifier_bundle = prereg.verifier_source_bundle()
    repository_root = Path(prereg.__file__).resolve().parents[1]
    source_paths = [
        authorization_path,
        handoff_path,
        allocation_path,
        *list(parent_contracts["source_file_sha256s"]),
        *[
            repository_root / item["path"]
            for item in execution_verifier_bundle["source_refs"]
        ],
    ]
    if addendum_path is not None:
        source_paths.append(addendum_path)
    return {
        "ticket": ticket,
        "authorization_path": authorization_path,
        "handoff": handoff,
        "handoff_path": handoff_path,
        "allocation": allocation,
        "allocation_path": allocation_path,
        "execution_addendum": addendum,
        "execution_addendum_path": addendum_path,
        "parent_contracts": parent_contracts,
        "execution_verifier_source_bundle": execution_verifier_bundle,
        "expected_host_trust_manifest_sha256": HOST_TRUST_PIN,
        "source_file_sha256s": {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
    }


def _threshold(ledger: dict, metric_spec: dict, authorization: dict) -> dict:
    rules = default_web_decision_rules("information_rent")
    assert rules == authorization["parent_contracts"]["threshold_registration"][
        "decision_rules"
    ]
    return {
        "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
        "registration_status": "LOCKED",
        "report_id": CHILD,
        "factor_id": FACTOR,
        "claim_class": "information_rent",
        "verification_scope": "production",
        "window_hash": stable_hash(metric_spec["window_contract"]),
        "evaluation_contract_hash": evaluation_contract_hash(metric_spec),
        "label_contract_hash": stable_hash(metric_spec["label_contract"]),
        "registered_before_evaluation": True,
        "registration_sequence": ledger["freeze_sequence"] + 1,
        "search_trial_ledger_ref": (
            f"objects/research_protocol/search_trial_ledger__{CHILD}.json"
        ),
        "search_trial_ledger_sha256": hashlib.sha256(
            canonical_json_bytes(ledger)
        ).hexdigest(),
        "decision_rules": rules,
        "rule_set_sha256": stable_json_hash(rules),
    }


def _child_plan(conjecture: dict, approaches: dict) -> dict:
    preferred = next(
        item for item in conjecture["hypotheses"] if item.get("kind") == "preferred"
    )
    return {
        "identity": {
            "job_id": "job_child_test01",
            "report_id": CHILD,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
        },
        "research_object": {
            "factor_name": FACTOR,
            "formula_or_law": "close",
            "hypothesis": preferred["claim"],
        },
        "economic_mechanism": {"claim_class": conjecture["claim_class"]},
        "hypotheses": copy.deepcopy(conjecture["hypotheses"]),
        "routes": copy.deepcopy(approaches["routes"]),
        "evidence_policy": {
            "oos_start": conjecture["evidence_policy"]["oos_start"],
            "oos_end": conjecture["evidence_policy"]["oos_end"],
        },
    }


def _full_fixture(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    found: bool = True,
) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    root.mkdir(parents=True, exist_ok=True)
    state, conjecture, approaches = _semantic_inputs(root)
    authorization = _authorization(root, found=found)
    def authorized(**kwargs):
        assert kwargs["expected_host_trust_manifest_sha256"] == HOST_TRUST_PIN
        return authorization

    monkeypatch.setattr(prereg, "_authorization_context", authorized)
    monkeypatch.setattr(prereg, "formal_oos_incident_reasons", lambda **_kwargs: [])
    import factor_factory.console.web_factor_proof as web_proof
    import factor_factory.console.web_research_plan as web_plan

    monkeypatch.setattr(
        web_plan,
        "validate_authorized_evo_child_web_research_plan",
        lambda **kwargs: {
            "status": "PASS",
            "web_research_plan_sha256": stable_json_hash(kwargs["child_plan"]),
        },
    )

    def project_proof(**kwargs):
        path = (
            root
            / "objects/research_protocol"
            / f"web_factor_proof_preregistration__{CHILD}.json"
        )
        return {
            "preregistration_path": path,
            "preregistration": {
                "version": "factorforge_web_factor_proof_preregistration_v1",
                "status": "LOCKED",
                "report_id": CHILD,
                "plan_sha256": stable_json_hash(kwargs["plan"]),
            },
            "component_artifacts": [],
        }

    monkeypatch.setattr(
        web_proof,
        "project_web_factor_proof_preregistration_from_frozen_controls",
        project_proof,
    )
    monkeypatch.setattr(
        web_proof,
        "validate_web_factor_proof_preregistration",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        web_proof,
        "validate_web_factor_proof_preregistration_structural",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    base = _base_ledger(conjecture)
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        execution_addendum=authorization["execution_addendum"],
    )
    metric_spec = prereg._project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        conjecture=conjecture,
        authorization=authorization,
    )
    threshold = _threshold(ledger, metric_spec, authorization)
    authoring_paths = evo_child_authoring_paths(root, CHILD)
    child_plan = _child_plan(conjecture, approaches)
    semantic_bundle = {
        "research_state": state,
        "research_conjecture": conjecture,
        "approach_registry": approaches,
        "base_search_trial_ledger": base,
        "agent_authored_child_web_research_plan": child_plan,
    }
    _write_json(authoring_paths["semantic_bundle"], semantic_bundle)
    _write_json(
        authoring_paths["admission"],
        {"test_only_fixture": "host_countersigned_authoring_admission"},
    )

    def validated_authoring(**kwargs):
        supplied = kwargs.get("agent_authoring_admission")
        if supplied is None or isinstance(supplied, dict):
            raise prereg.EvoChildPreregistrationError(
                [
                    prereg._token(
                        "agent_authoring_admission_canonical_path_required"
                    )
                ]
            )
        supplied_path = Path(supplied)
        if not supplied_path.is_absolute():
            supplied_path = root / supplied_path
        if supplied_path.resolve() != authoring_paths["admission"].resolve():
            raise prereg.EvoChildPreregistrationError(
                [prereg._token("agent_authoring_admission_test_path")]
            )
        return {
            "admission_path": authoring_paths["admission"],
            "semantic_bundle": semantic_bundle,
            "semantic_bundle_path": authoring_paths["semantic_bundle"],
            "source_file_sha256s": {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (
                    authoring_paths["admission"],
                    authoring_paths["semantic_bundle"],
                )
            },
        }

    monkeypatch.setattr(prereg, "_validated_agent_authoring", validated_authoring)
    return (
        state,
        conjecture,
        approaches,
        base,
        metric_spec,
        threshold,
        authorization,
    )


def test_found_branch_projects_exact_addendum_trials(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _semantic_inputs(root)
    authorization = _authorization(root, found=True)
    base = _base_ledger()
    original = copy.deepcopy(base)
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        execution_addendum=authorization["execution_addendum"],
    )
    assert base == original
    assert ledger["trial_count"] == 2
    projected = ledger["trials"][-1]
    assert projected["trial_kind"] == EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
    assert projected["trial_id"] == "transfer_test_001"
    assert projected["source_addendum_ref"]["path"] == (
        f"objects/evo_v2/{PARENT}/execution_addendum.json"
    )
    assert projected["affects_acceptance"] is False
    assert validate_frozen_child_execution_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        search_trial_ledger=ledger,
        execution_addendum=authorization["execution_addendum"],
    ) == []


def test_cold_branch_projects_zero_transfer_trials(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    base = _base_ledger()
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        execution_addendum=None,
    )
    assert ledger == base
    assert all(
        item.get("trial_kind") != EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
        for item in ledger["trials"]
    )


@pytest.mark.parametrize("mutation", ["tamper", "extra"])
def test_frozen_child_ledger_rejects_tampered_or_extra_transfer_trials(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _semantic_inputs(root)
    authorization = _authorization(root, found=True)
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=_base_ledger(),
        execution_addendum=authorization["execution_addendum"],
    )
    if mutation == "tamper":
        ledger["trials"][-1]["implementation_mode"] = "TAMPERED"
    else:
        extra = copy.deepcopy(ledger["trials"][-1])
        extra["trial_id"] = "transfer_test_extra_002"
        ledger["trials"].append(extra)
    ledger["trial_count"] = len(ledger["trials"])
    ledger["trial_set_sha256"] = stable_json_hash(ledger["trials"])

    reasons = validate_frozen_child_execution_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        search_trial_ledger=ledger,
        execution_addendum=authorization["execution_addendum"],
    )

    assert any("ledger_evo_trial_projection" in reason for reason in reasons)


def test_child_trial_budget_blocks_base_plus_transfer_overbudget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, _threshold_payload, auth = (
        _full_fixture(root, monkeypatch)
    )
    state["budget_used"] = {"trials_used": 1, "trial_budget": 1}
    conjecture["evidence_policy"]["trials_used"] = 1
    conjecture["evidence_policy"]["trial_budget"] = 1
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        execution_addendum=auth["execution_addendum"],
    )
    identities = prereg.project_evo_child_search_identities(conjecture)
    ledger["candidate_space_sha256"] = identities["candidate_space_sha256"]
    ledger["selected_hypothesis_sha256"] = identities[
        "selected_hypothesis_sha256"
    ]
    threshold = _threshold(ledger, metric_spec, auth)

    reasons = prereg._validate_inputs(
        root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        authorization=auth,
    )

    assert any("trial_budget_binding" in reason for reason in reasons)


def test_base_ledger_cannot_self_authorize_evo_trial(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    base = _base_ledger()
    base["trials"][0]["trial_kind"] = EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
    base["trial_set_sha256"] = stable_json_hash(base["trials"])
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="base_ledger_evo_diagnostic_forbidden",
    ):
        prereg._project_evo_child_search_trial_ledger(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            base_search_trial_ledger=base,
            execution_addendum=None,
        )


def test_external_host_trust_pin_is_mandatory_before_workspace_ticket_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="external_host_trust_pin_required",
    ):
        prereg._authorization_context(
            root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256="not-a-sha256",
        )


def test_parent_contract_context_replays_canonical_web_preregistration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    selected = [
        item
        for item in calendar["dates"]
        if "2024-01-01" <= item <= "2024-06-30"
    ][:82]
    plan = {
        "identity": {
            "job_id": "job_parent_contract_001",
            "report_id": PARENT,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
        },
        "evidence_policy": {
            "is_start": "2020-01-01",
            "is_end": "2023-12-31",
            "oos_start": selected[0],
            "oos_end": selected[-1],
            "purge_days": 5,
            "embargo_days": 5,
            "multiple_testing_policy": "BH_FDR",
            "forward_horizon": "1d",
            "transaction_cost_bps": 30.0,
            "cost_model_id": "factorforge_step4_turnover_30bps_v1",
            "impact_model_id": "capacity_impact_v1",
            "capacity_model_id": "adv_participation_v1",
            "universe_id": "proof_test_universe",
            "investability_mask_id": "proof_test_mask",
            "trial_budget": 20,
            "signal_timestamp_policy": "after_close_t",
            "position_entry_policy": "close_t_plus_1",
            "payoff_contract": {
                "exit": "close_t_plus_2",
                "label_expression": "close_t_plus_2/close_t_plus_1-1",
                "return_window": "t_plus_1_close_to_t_plus_2_close",
            },
        },
        "economic_mechanism": {"claim_class": "information_rent"},
        "hypotheses": [
            {
                "kind": "preferred",
                "hypothesis_id": "H1",
                "claim": "canonical parent contract replay",
            }
        ],
        "research_object": {
            "formula_or_law": "close",
            "rebalance_frequency": "daily",
        },
        "data_plan": {
            "daily_fields": ["close"],
            "availability_lags": {"close": "same_day_after_close"},
            "missing_data_policy": "drop_missing",
        },
    }
    prepare_web_factor_proof(workspace_root=root, plan=plan)
    _write_json(root / "identity/web_research_plan.json", plan)
    parent_conjecture = valid_conjecture()
    parent_conjecture.update(
        {
            "report_id": PARENT,
            "factor_id": FACTOR,
            "claim_class": "information_rent",
            "evaluation_contract": build_web_evaluation_contract(plan),
        }
    )
    parent_conjecture["identity"]["research_id"] = RESEARCH
    parent_conjecture["evidence_policy"].update(
        {
            key: value
            for key, value in plan["evidence_policy"].items()
            if key
            in {
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
            }
        }
    )
    _write_json(
        root / f"objects/research_protocol/research_conjecture__{PARENT}.json",
        parent_conjecture,
    )
    context = prereg._parent_contract_context(
        root=root,
        parent_report_id=PARENT,
    )
    assert context["metric_verifier_spec"]["report_id"] == PARENT
    assert context["threshold_registration"]["registration_status"] == "LOCKED"


def test_threshold_projection_is_unique_and_registration_follows_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    del state, approaches
    ledger = prereg.project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    projected = prereg.project_evo_child_threshold_registration(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_conjecture=conjecture,
        search_trial_ledger=ledger,
        metric_verifier_spec=metric_spec,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert projected == threshold
    assert projected["registration_sequence"] == ledger["freeze_sequence"] + 1


def test_agent_authored_child_plan_is_frozen_and_parent_semantic_copy_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    del state
    ledger = prereg.project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    child_plan = _child_plan(conjecture, approaches)
    projection = prereg.project_evo_child_web_research_plan(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_conjecture=conjecture,
        approach_registry=approaches,
        search_trial_ledger=ledger,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=child_plan,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert projection["web_research_plan"] == child_plan
    assert projection["parent_web_research_plan_ref"]["path"] == (
        "identity/web_research_plan.json"
    )
    assert projection["child_bindings"]["selected_revision"]["child_formula"] == (
        "close"
    )

    import factor_factory.console.web_research_plan as web_plan

    def reject_stale(**kwargs):
        if kwargs["child_plan"].get("hypotheses") != conjecture["hypotheses"]:
            raise web_plan.WebResearchPlanError(
                web_plan.BLOCK_PLAN_INVALID,
                ["child_plan_conjecture_hypotheses"],
            )
        return {"status": "PASS"}

    monkeypatch.setattr(
        web_plan, "validate_authorized_evo_child_web_research_plan", reject_stale
    )
    stale = copy.deepcopy(child_plan)
    stale["hypotheses"] = [{"kind": "preferred", "claim": "stale parent"}]
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="child_plan_conjecture_hypotheses",
    ):
        prereg.project_evo_child_web_research_plan(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_conjecture=conjecture,
            approach_registry=approaches,
            search_trial_ledger=ledger,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=stale,
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


@pytest.mark.parametrize("found", [True, False])
def test_materializes_closed_child_controls_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    found: bool,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _authorization_data = (
        _full_fixture(root, monkeypatch, found=found)
    )
    result = prereg.materialize_evo_child_preregistration(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_state=state,
        research_conjecture=conjecture,
        approach_registry=approaches,
        base_search_trial_ledger=base,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
        agent_authoring_admission=_authoring_admission_path(root),
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert result["verdict"] == "PASS"
    assert result["authority"]["child_execution_allowed"] is False
    assert result["authority"]["factor_verdict"] == "NOT_ISSUED"
    controls = child_control_paths(root, CHILD)
    assert all(controls[name].is_file() for name in (
        "research_state",
        "research_conjecture",
        "approach_registry",
        "search_trial_ledger",
        "threshold_registration",
    ))
    assert prereg.child_metric_verifier_spec_path(root, CHILD).is_file()
    assert prereg.child_web_research_plan_path(root, CHILD).is_file()
    assert validate_protocol_bundle(
        root=root,
        report_id=CHILD,
        stage="pre_council",
    )["verdict"] == "PASS"
    strict = prereg.validate_evo_child_preregistration_receipt_structural(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert strict["verdict"] == "PASS"
    assert strict["authority"]["current_formal_authority_verified"] is False
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="incident_host_context_required",
    ):
        prereg.validate_evo_child_preregistration_receipt(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    current = prereg.validate_evo_child_preregistration_receipt(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        incident_trust_root=tmp_path / "host-incident-trust",
        incident_installation_id="child-prereg-test",
    )
    assert current["authority"]["current_formal_authority_verified"] is True
    resolved = prereg.validate_and_resolve_evo_child_web_research_plan_structural(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert resolved["authority"]["current_formal_authority_verified"] is False
    assert resolved["raw_plan"] == _child_plan(conjecture, approaches)
    replay = prereg.materialize_evo_child_preregistration(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_state=state,
        research_conjecture=conjecture,
        approach_registry=approaches,
        base_search_trial_ledger=base,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
        agent_authoring_admission=_authoring_admission_path(root),
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert replay["idempotent_replay"] is True


def test_strict_receipt_replay_rejects_handwritten_controls_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    del base
    controls = child_control_paths(root, CHILD)
    ledger = prereg.project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=_base_ledger(conjecture),
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    for path, payload in (
        (controls["research_state"], state),
        (controls["research_conjecture"], conjecture),
        (controls["approach_registry"], approaches),
        (controls["search_trial_ledger"], ledger),
        (prereg.child_metric_verifier_spec_path(root, CHILD), metric_spec),
        (controls["threshold_registration"], threshold),
    ):
        _write_json(path, payload)
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="source_missing_or_unsafe:child_web_research_plan",
    ):
        prereg.validate_evo_child_preregistration_receipt_structural(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_stale_threshold_ledger_hash_blocks_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _authorization_data = (
        _full_fixture(root, monkeypatch)
    )
    threshold["search_trial_ledger_sha256"] = "0" * 64
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="threshold_identity_or_ledger_binding",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    controls = child_control_paths(root, CHILD)
    assert not controls["research_state"].exists()


def test_arbitrary_threshold_contract_hash_blocks_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    threshold["window_hash"] = "f" * 64
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="threshold_contract_hash_projection",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    assert not child_control_paths(root, CHILD)["research_state"].exists()


def test_detached_metric_spec_drift_blocks_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    metric_spec["portfolio"]["cost_bps_per_turnover"] = 0.0
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="metric_verifier_spec_not_exact_projection",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_search_identity_hash_drift_blocks_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    base["candidate_space_sha256"] = "f" * 64
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="search_identity_projection",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_base_trial_cannot_embed_empirical_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, _threshold_payload, auth = (
        _full_fixture(root, monkeypatch)
    )
    base["trials"][0]["metrics"] = {"rank_ic": 1.0}
    base["trial_set_sha256"] = stable_json_hash(base["trials"])
    ledger = prereg._project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        base_search_trial_ledger=base,
        execution_addendum=auth["execution_addendum"],
    )
    threshold = _threshold(ledger, metric_spec, auth)
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="base_trial_preregistration_semantics",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_parent_protected_source_change_blocks_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, auth = (
        _full_fixture(root, monkeypatch)
    )
    auth["parent_contracts"]["metric_verifier_spec_path"].write_text(
        "{}\n", encoding="utf-8"
    )
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="source_file_changed:metric_verifier_spec",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    assert not child_control_paths(root, CHILD)["research_state"].exists()


def test_child_cannot_rewrite_parent_decision_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    threshold["decision_rules"] = copy.deepcopy(threshold["decision_rules"])
    threshold["decision_rules"][0]["threshold"] = 0.01
    threshold["rule_set_sha256"] = stable_json_hash(threshold["decision_rules"])
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="threshold_protected_decision_rules",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_read_only_validator_has_no_write_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    result = prereg.validate_evo_child_preregistration_inputs(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_state=state,
        research_conjecture=conjecture,
        approach_registry=approaches,
        base_search_trial_ledger=base,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
        agent_authoring_admission=_authoring_admission_path(root),
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert result["verdict"] == "PASS"
    assert result["writes_performed"] is False
    assert not child_control_paths(root, CHILD)["research_state"].exists()


def test_formal_validation_rejects_direct_semantic_mappings_without_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _ = (
        _full_fixture(root, monkeypatch)
    )
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="agent_authoring_admission_canonical_path_required",
    ):
        prereg.validate_evo_child_preregistration_inputs(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(
                conjecture, approaches
            ),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_child_identity_drift_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _authorization_data = (
        _full_fixture(root, monkeypatch)
    )
    conjecture["identity"]["formula_hash"] = "9" * 64
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="child_formula_hash",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )


def test_symlink_control_parent_cannot_write_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _authorization_data = (
        _full_fixture(root, monkeypatch)
    )
    protocol = root / "objects/research_protocol"
    allocation_path = _authorization_data["allocation_path"]
    allocation = allocation_path.read_bytes()
    for path in list(protocol.iterdir()):
        path.unlink()
    protocol.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    protocol.symlink_to(outside, target_is_directory=True)
    # Retain the pre-authorized OOS allocation at the same lexical path so the
    # test reaches the writer's ancestor-symlink guard without allowing an
    # external write by the writer itself.
    (outside / allocation_path.name).write_bytes(allocation)
    with pytest.raises(
        prereg.EvoChildPreregistrationError,
        match="unsafe_ref|unsafe_output_parent|source_file_changed",
    ):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    assert [path.name for path in outside.iterdir()] == [allocation_path.name]


def test_partial_publish_recovers_without_threshold_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    state, conjecture, approaches, base, metric_spec, threshold, _authorization_data = (
        _full_fixture(root, monkeypatch)
    )
    real_link = prereg.os.link
    calls = 0

    def fail_fourth(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected_preregistration_publish_failure")
        return real_link(*args, **kwargs)

    monkeypatch.setattr(prereg.os, "link", fail_fourth)
    with pytest.raises(OSError, match="injected_preregistration_publish_failure"):
        prereg.materialize_evo_child_preregistration(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            research_state=state,
            research_conjecture=conjecture,
            approach_registry=approaches,
            base_search_trial_ledger=base,
            metric_verifier_spec=metric_spec,
            threshold_registration=threshold,
            agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
            agent_authoring_admission=_authoring_admission_path(root),
            expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
        )
    assert not child_control_paths(root, CHILD)["threshold_registration"].exists()
    monkeypatch.setattr(prereg.os, "link", real_link)
    recovered = prereg.materialize_evo_child_preregistration(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        research_state=state,
        research_conjecture=conjecture,
        approach_registry=approaches,
        base_search_trial_ledger=base,
        metric_verifier_spec=metric_spec,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=_child_plan(conjecture, approaches),
        agent_authoring_admission=_authoring_admission_path(root),
        expected_host_trust_manifest_sha256=HOST_TRUST_PIN,
    )
    assert recovered["verdict"] == "PASS"
    assert child_control_paths(root, CHILD)["threshold_registration"].is_file()
