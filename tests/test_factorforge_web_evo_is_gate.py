from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.console.web_factor_proof import (
    _trusted_calendar_snapshot,
    finalize_web_factor_proof,
    materialize_web_evo_is_checkpoint,
    prepare_web_factor_proof,
    resolve_web_evo_execution_gate,
    validate_web_evo_is_checkpoint,
    web_factor_proof_paths,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from scripts.run_factorforge_ultimate import enforce_evo_post_oos_no_revision
from scripts.run_factorforge_ultimate import _evo_pre_oos_executor_block_token


REPORT_ID = "WEB_EVO_IS_TEST"
INCIDENT_INSTALLATION_ID = "web-evo-is-incident-test"


def _incident_trust_root(root: Path) -> Path:
    trust = root.parent / ".web-evo-is-incident-trust"
    ensure_runtime_trust_store(
        trust,
        installation_id=INCIDENT_INSTALLATION_ID,
    )
    return trust


def _materialize_checkpoint(root: Path, plan: dict) -> dict:
    return materialize_web_evo_is_checkpoint(
        workspace_root=root,
        plan=plan,
        incident_trust_root=_incident_trust_root(root),
        incident_installation_id=INCIDENT_INSTALLATION_ID,
    )


def _plan(calendar_dates: list[str]) -> tuple[dict, list[str], list[str]]:
    is_dates = [
        value
        for value in calendar_dates
        if "2023-01-01" <= value <= "2023-06-30"
    ]
    oos_dates = [
        value
        for value in calendar_dates
        if "2024-01-01" <= value <= "2024-06-30"
    ][:82]
    plan = {
        "identity": {
            "job_id": "job_evois12345",
            "report_id": REPORT_ID,
            "factor_id": "WEB_EVO_IS_FACTOR",
            "research_id": "web_evo_is_test",
        },
        "evidence_policy": {
            "is_start": is_dates[0],
            "is_end": is_dates[-1],
            "oos_start": oos_dates[0],
            "oos_end": oos_dates[-1],
            "purge_days": 5,
            "embargo_days": 5,
            "transaction_cost_bps": 30.0,
            "cost_model_id": "factorforge_step4_turnover_30bps_v1",
            "universe_id": "evo_is_test_universe",
            "investability_mask_id": "evo_is_test_mask",
            "trial_budget": 3,
        },
        "economic_mechanism": {"claim_class": "liquidity_rent"},
        "hypotheses": [
            {
                "kind": "preferred",
                "hypothesis_id": "preferred_mechanism",
                "claim": "registered EVO IS test",
                "expected_signature": "positive controlled ordering",
                "falsification_tests": ["rank IC sign", "long-side sign"],
                "kill_criteria": ["registered signature fails"],
            },
            {
                "kind": "null",
                "hypothesis_id": "null_alias",
                "claim": "alias null",
                "expected_signature": "ordering vanishes",
                "falsification_tests": ["alias control", "sign control"],
                "kill_criteria": ["null dominates"],
            },
            {
                "kind": "alternative",
                "hypothesis_id": "alternative_mechanism",
                "claim": "mechanism-distinct alternative",
                "expected_signature": "different conditional ordering",
                "falsification_tests": ["conditional test", "boundary test"],
                "kill_criteria": ["alternative fails"],
            },
        ],
        "research_object": {"formula_or_law": "close"},
        "data_plan": {"daily_fields": ["close"]},
    }
    return plan, is_dates, oos_dates


def _verifier_reference(root: Path, name: str) -> dict:
    path = root / "objects" / "evidence" / f"{name}.json"
    payload = {
        "verifier_status": "PASS",
        "verifier_id": "test_host_checkpoint_verifier_v1",
        "verifier_source_sha256": "1" * 64,
        "dataset_snapshot_hash": "2" * 64,
        "window_hash": "3" * 64,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        **payload,
    }


def _write_evo_protocol(root: Path, *, state: str = "PREDICTIONS_FROZEN") -> None:
    protocol = root / "objects" / "research_protocol"
    protocol.mkdir(parents=True, exist_ok=True)
    (protocol / f"research_conjecture__{REPORT_ID}.json").write_text(
        json.dumps({"epistemic_evolution": {"enabled": True}}),
        encoding="utf-8",
    )
    freeze_ref = _verifier_reference(root, "prediction_freeze")
    lifecycle = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="PREDICTIONS_FROZEN",
        evidence_refs=[freeze_ref],
    )
    transition_path = {
        "PREDICTIONS_FROZEN": [],
        "NO_QUALIFIED_CONTRADICTION": ["NO_QUALIFIED_CONTRADICTION"],
        "QUALIFIED_CONTRADICTION": ["QUALIFIED_CONTRADICTION"],
        "MINIMAL_MECHANISM_DELTA": [
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
        ],
        "NO_DERIVED_LAW": ["QUALIFIED_CONTRADICTION", "NO_DERIVED_LAW"],
        "TRANSFER_RECORDED": [
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
            "TRANSFER_RECORDED",
        ],
        "COLD_START_RECORDED": [
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
            "COLD_START_RECORDED",
        ],
    }[state]
    if transition_path:
        trust = ensure_runtime_trust_store(
            root / ".host-trust",
            installation_id="web-evo-is-test",
        )
        organization_root = "objects/research_organization/WEB_EVO_IS_TEST"
        plan_path = root / "identity" / "research_organization_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "identity": {"report_id": REPORT_ID},
                    "workspace_policy": {"organization_root": organization_root},
                }
            ),
            encoding="utf-8",
        )
        runtime_state = {
            "identity": {"report_id": REPORT_ID},
            "authority": {
                "signed_adapter_receipts_required": True,
                "trust_manifest": trust.public_manifest,
            },
        }
        runtime_state["state_sha256"] = stable_hash(runtime_state)
        runtime_path = root / organization_root / "runtime" / "runtime_state.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(runtime_state), encoding="utf-8")
        for sequence, next_state in enumerate(transition_path, start=2):
            transition_ref = _verifier_reference(
                root, f"transition_{next_state.lower()}"
            )
            receipt = trust.sign(
                "host_admission",
                {
                    "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
                    "report_id": REPORT_ID,
                    "sequence": sequence,
                    "from_state": lifecycle["current_state"],
                    "to_state": next_state,
                    "lifecycle_parent_sha256": stable_hash(lifecycle),
                    "evidence_refs_sha256": stable_hash([transition_ref]),
                    "trust_manifest_sha256": trust.public_manifest[
                        "manifest_sha256"
                    ],
                    "authority_scope": (
                        "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
                    ),
                    "oos_accessed": False,
                },
            )
            receipt_path = (
                epistemic_evolution_lifecycle_path(root, REPORT_ID).parent
                / f"lifecycle_transition_receipt__{sequence:04d}.json"
            )
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            lifecycle = build_epistemic_evolution_lifecycle(
                report_id=REPORT_ID,
                to_state=next_state,
                evidence_refs=[transition_ref],
                actor_receipt_ref={
                    "path": receipt_path.relative_to(root).as_posix(),
                    "sha256": sha256_file(receipt_path),
                    "receipt_id": receipt["receipt_id"],
                    "trust_manifest_sha256": trust.public_manifest[
                        "manifest_sha256"
                    ],
                },
                existing=lifecycle,
            )
            transition_snapshot = epistemic_evolution_lifecycle_snapshot_path(
                root,
                REPORT_ID,
                len(lifecycle["events"]),
            )
            transition_snapshot.parent.mkdir(parents=True, exist_ok=True)
            transition_snapshot.write_text(json.dumps(lifecycle), encoding="utf-8")
    path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lifecycle), encoding="utf-8")
    snapshot = epistemic_evolution_lifecycle_snapshot_path(
        root,
        REPORT_ID,
        len(lifecycle["events"]),
    )
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(lifecycle), encoding="utf-8")


def _write_shared_panel(
    root: Path,
    calendar_dates: list[str],
    *,
    is_dates: list[str],
    oos_dates: list[str],
    compact_dates: bool = False,
) -> None:
    all_dates = [
        value
        for value in calendar_dates
        if is_dates[0] <= value <= oos_dates[-1]
    ]
    rows = []
    for date_index, signal_date in enumerate(all_dates[:-2]):
        for asset_index in range(12):
            forward_return = (
                0.001 + asset_index * 0.0001
                + 0.0002 * math.sin(date_index + asset_index)
            )
            rows.append(
                {
                    "trade_date": (
                        signal_date.replace("-", "")
                        if compact_dates
                        else signal_date
                    ),
                    "code": f"{asset_index:06d}.SZ",
                    "factor_value": float(asset_index),
                    "future_return_1d": forward_return,
                    "label_start_date": (
                        all_dates[date_index + 1].replace("-", "")
                        if compact_dates
                        else all_dates[date_index + 1]
                    ),
                    "label_end_date": (
                        all_dates[date_index + 2].replace("-", "")
                        if compact_dates
                        else all_dates[date_index + 2]
                    ),
                    "label_start_price": 100.0,
                    "label_end_price": 100.0 * (1.0 + forward_return),
                    "pct_chg": 0.01 * math.sin(date_index + asset_index),
                    "turnover_rate": 0.5 + asset_index * 0.02,
                    "ln_mcap_free": 8.0 + asset_index * 0.05,
                    "volume_ratio": 0.8 + asset_index * 0.01,
                }
            )
    run_root = root / "runs" / REPORT_ID
    run_root.mkdir(parents=True)
    panel_path = run_root / f"merged_signal_return__{REPORT_ID}.parquet"
    pd.DataFrame(rows).to_parquet(panel_path, index=False)
    context = {
        "paths": {"merged_signal_return_parquet": str(panel_path)},
        "artifacts": {"merged_signal_return": {"sha256": sha256_file(panel_path)}},
    }
    (run_root / f"shared_evaluation_context__{REPORT_ID}.json").write_text(
        json.dumps(context), encoding="utf-8"
    )


def _workspace(tmp_path: Path) -> tuple[Path, dict, list[str], list[str]]:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, is_dates, oos_dates = _plan(calendar["dates"])
    _write_evo_protocol(root)
    prepare_web_factor_proof(
        workspace_root=root,
        plan=plan,
        incident_trust_root=_incident_trust_root(root),
        incident_installation_id=INCIDENT_INSTALLATION_ID,
    )
    _write_shared_panel(
        root,
        calendar["dates"],
        is_dates=is_dates,
        oos_dates=oos_dates,
    )
    return root, plan, is_dates, oos_dates


def test_evo_checkpoint_contains_only_purged_is_and_never_qualifies(
    tmp_path: Path,
) -> None:
    root, plan, is_dates, oos_dates = _workspace(tmp_path)

    with pytest.raises(ValueError, match="incident Host context required"):
        materialize_web_evo_is_checkpoint(
            workspace_root=root,
            plan=plan,
        )
    result = _materialize_checkpoint(root, plan)

    assert result["status"] == "PASS"
    assert result["uses_oos"] is False
    paths = web_factor_proof_paths(root, REPORT_ID)
    panel = pd.read_parquet(paths["evo_is_panel"])
    report = json.loads(paths["evo_is_diagnostics"].read_text(encoding="utf-8"))
    assert panel["trade_date"].max() == is_dates[-8]
    assert panel["label_end_date"].max() == is_dates[-6]
    assert panel["label_end_date"].max() < oos_dates[0]
    assert report["qualification"] == {
        "status": "HOST_REVIEW_REQUIRED",
        "qualified_contradiction": None,
        "automatic_qualification_allowed": False,
        "required_next_artifact": "objects/evo_v2/<report_id>/feedback_ledger.json",
    }
    assert report["factor_verdict"] == "NOT_ISSUED"
    assert not paths["release"].exists()
    assert not paths["panel"].exists()
    assert not paths["finalization"].exists()


def test_evo_checkpoint_replay_rejects_oos_row_injection(tmp_path: Path) -> None:
    root, plan, _is_dates, _oos_dates = _workspace(tmp_path)
    _materialize_checkpoint(root, plan)
    paths = web_factor_proof_paths(root, REPORT_ID)
    panel = pd.read_parquet(paths["evo_is_panel"])
    injected = panel.iloc[[0]].copy()
    injected["trade_date"] = plan["evidence_policy"]["oos_start"]
    pd.concat([panel, injected], ignore_index=True).to_parquet(
        paths["evo_is_panel"], index=False
    )

    with pytest.raises(ValueError, match="IS panel replay mismatch"):
        validate_web_evo_is_checkpoint(root, plan)


def test_evo_checkpoint_pushdown_accepts_step4_compact_trade_dates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    calendar = _trusted_calendar_snapshot()
    plan, is_dates, oos_dates = _plan(calendar["dates"])
    _write_evo_protocol(root)
    prepare_web_factor_proof(
        workspace_root=root,
        plan=plan,
        incident_trust_root=_incident_trust_root(root),
        incident_installation_id=INCIDENT_INSTALLATION_ID,
    )
    _write_shared_panel(
        root,
        calendar["dates"],
        is_dates=is_dates,
        oos_dates=oos_dates,
        compact_dates=True,
    )

    result = _materialize_checkpoint(root, plan)

    assert result["status"] == "PASS"
    panel = pd.read_parquet(web_factor_proof_paths(root, REPORT_ID)["evo_is_panel"])
    assert panel["trade_date"].min() == is_dates[0]
    assert panel["trade_date"].max() == is_dates[-8]


def test_evo_oos_gate_requires_host_no_contradiction_transition(
    tmp_path: Path,
) -> None:
    root, plan, _is_dates, _oos_dates = _workspace(tmp_path)
    _materialize_checkpoint(root, plan)

    waiting = resolve_web_evo_execution_gate(
        workspace_root=root,
        report_id=REPORT_ID,
        plan=plan,
    )
    assert waiting["action"] == "AWAIT_HOST_QUALIFICATION"
    assert waiting["oos_release_allowed"] is False
    with pytest.raises(ValueError, match="OOS release forbidden"):
        finalize_web_factor_proof(
            workspace_root=root,
            plan=plan,
            incident_trust_root=_incident_trust_root(root),
            incident_installation_id=INCIDENT_INSTALLATION_ID,
        )

    _write_evo_protocol(root, state="QUALIFIED_CONTRADICTION")
    qualified = resolve_web_evo_execution_gate(
        workspace_root=root,
        report_id=REPORT_ID,
        plan=plan,
    )
    assert qualified["action"] == "RUN_PRE_OOS_REVISION_COUNCIL"
    assert qualified["step5_step6_allowed"] is False
    assert qualified["council_allowed"] is True
    with pytest.raises(ValueError, match="OOS release forbidden"):
        finalize_web_factor_proof(
            workspace_root=root,
            plan=plan,
            incident_trust_root=_incident_trust_root(root),
            incident_installation_id=INCIDENT_INSTALLATION_ID,
        )

    _write_evo_protocol(root, state="NO_QUALIFIED_CONTRADICTION")
    no_contradiction = resolve_web_evo_execution_gate(
        workspace_root=root,
        report_id=REPORT_ID,
        plan=plan,
    )
    assert no_contradiction["action"] == "RELEASE_ORIGINAL_CANDIDATE_OOS"
    assert no_contradiction["oos_release_allowed"] is True
    assert no_contradiction["step5_step6_allowed"] is True


def test_evo_minimal_delta_waits_for_transfer_before_external_approval(
    tmp_path: Path,
) -> None:
    root, plan, _is_dates, _oos_dates = _workspace(tmp_path)
    _materialize_checkpoint(root, plan)
    _write_evo_protocol(root, state="MINIMAL_MECHANISM_DELTA")

    gate = resolve_web_evo_execution_gate(
        workspace_root=root,
        report_id=REPORT_ID,
        plan=plan,
    )

    assert gate["action"] == "AWAIT_EVO_V2_TRANSFER_AND_USE"
    assert gate["oos_release_allowed"] is False
    assert gate["council_allowed"] is False


def test_pre_oos_council_agentic_executor_policy_is_fail_closed() -> None:
    assert (
        _evo_pre_oos_executor_block_token("agentic", "none")
        == "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED"
    )
    assert (
        _evo_pre_oos_executor_block_token("agentic", "real_agent")
        == "BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED"
    )
    assert (
        _evo_pre_oos_executor_block_token("auto", "local_mock")
        == "BLOCK_EVO_V2_PRE_OOS_COUNCIL_LOCAL_MOCK_FORBIDDEN"
    )
    assert _evo_pre_oos_executor_block_token("auto", "none") is None
    assert (
        _evo_pre_oos_executor_block_token("agentic", "dispatch_manifest")
        is None
    )


def test_evo_oos_gate_rejects_unsigned_self_reported_no_contradiction(
    tmp_path: Path,
) -> None:
    root, plan, _is_dates, _oos_dates = _workspace(tmp_path)
    _materialize_checkpoint(root, plan)
    lifecycle_path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    forged_ref = _verifier_reference(root, "forged_host_transition")
    forged = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="NO_QUALIFIED_CONTRADICTION",
        evidence_refs=[forged_ref],
        actor_receipt_ref=forged_ref,
        existing=lifecycle,
    )
    lifecycle_path.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(ValueError, match="actor_receipt"):
        resolve_web_evo_execution_gate(
            workspace_root=root,
            report_id=REPORT_ID,
            plan=plan,
        )
    with pytest.raises(ValueError, match="actor_receipt"):
        finalize_web_factor_proof(
            workspace_root=root,
            plan=plan,
            incident_trust_root=_incident_trust_root(root),
            incident_installation_id=INCIDENT_INSTALLATION_ID,
        )


def test_post_oos_no_contradiction_archives_provisional_handoff_and_blocks_approved_one(
    tmp_path: Path,
) -> None:
    provisional_root = tmp_path / "provisional"
    provisional = (
        provisional_root
        / "objects"
        / "handoff"
        / f"handoff_to_step3b__{REPORT_ID}.json"
    )
    provisional.parent.mkdir(parents=True, exist_ok=True)
    provisional.write_text(json.dumps({"status": "provisional"}), encoding="utf-8")

    safe = enforce_evo_post_oos_no_revision(provisional_root, REPORT_ID)

    assert safe["status"] == "SAFE_NO_REVISION"
    assert not provisional.exists()
    assert Path(safe["handoff_policy"]["archive_path"]).is_file()

    approved_root = tmp_path / "approved"
    approved = (
        approved_root
        / "objects"
        / "handoff"
        / f"handoff_to_step3b__{REPORT_ID}.json"
    )
    approved.parent.mkdir(parents=True, exist_ok=True)
    approved.write_text(
        json.dumps(
            {
                "loop_authorization": "approved_for_step3b_handoff",
                "main_agent_council_synthesis_path": "objects/council/synthesis.json",
            }
        ),
        encoding="utf-8",
    )

    blocked = enforce_evo_post_oos_no_revision(approved_root, REPORT_ID)

    assert blocked["status"] == "BLOCK"
    assert blocked["active_step3b_handoff"] is True
    assert approved.is_file()
