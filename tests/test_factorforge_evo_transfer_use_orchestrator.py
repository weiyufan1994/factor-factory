from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import factor_factory.evo_transfer_use_orchestrator as orchestrator
from factor_factory.console.web_research_plan import write_web_research_packet
from factor_factory.evo_child_execution import verifier_source_bundle
from factor_factory.evo_execution_addendum import (
    EVO_CHILD_RESULT_CONTRACT_VERSION,
    EVO_CHILD_RESULT_VERIFIER_CONTRACT_VERSION,
    EVO_CHILD_RESULT_VERIFIER_ID,
    execution_addendum_path,
)
from factor_factory.evo_memory_runtime import protected_contract_hashes
from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    materialize_evo_v2_stage,
    staging_manifest_path,
)
from factor_factory.evo_v2 import (
    artifact_sha256,
    canonical_json_bytes,
    sha256_file,
    with_content_hash,
)
from factor_factory.research_conjecture import epistemic_evolution_lifecycle_path
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import load_runtime_trust_store
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from factor_factory.researcher_memory import (
    build_evo_v2_transfer_use_change_receipt,
)
from factor_factory.researcher_memory_review import (
    build_evo_v2_memory_review_projection,
)
from tests.test_factorforge_console_web_research_plan import (
    _fill_plan,
    _request,
    _write_catalog,
)
from tests.test_factorforge_evo_v2 import REPORT_ID, _as_cold_start
from tests.test_factorforge_evo_v2_staging import _write_lifecycle
from tests.test_factorforge_researcher_memory_evo_v2 import (
    _completed_cold_start_search,
    _completed_review_decision,
    _transfer_use_change_receipt,
)
from tests.test_revision_council_evo_v2 import _proposal_and_payload

INSTALLATION_ID = "evo-staging-test-installation-001"
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts/orchestrate_factorforge_evo_transfer_use.py"


def _write_canonical(path: Path, payload: dict) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))
    return {
        "path": path.relative_to(path.parents[1]).as_posix(),
        "sha256": sha256_file(path),
    }


def _refresh(payload: dict) -> None:
    payload.pop("content_sha256", None)
    payload.update(with_content_hash(payload))


def _prepare_minimal(root: Path) -> tuple[Path, str, str, dict[str, dict]]:
    proposal, _payload, artifacts = _proposal_and_payload(root)
    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    feedback = materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_FEEDBACK,
        expected_lifecycle_parent_sha256=qualified[0],
        expected_lifecycle_content_sha256=qualified[1],
        expected_staging_content_sha256="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    minimal = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
        ],
    )
    materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_COUNCIL_OUTCOME,
        expected_lifecycle_parent_sha256=minimal[0],
        expected_lifecycle_content_sha256=minimal[1],
        expected_staging_content_sha256=feedback["staging_manifest"]["content_sha256"],
        council_proposal=proposal,
    )
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    manifest = json.loads(
        staging_manifest_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    private_inside = root / "host-private-trust"
    private_outside = root.parent / f"{root.name}-host-state" / "research-org-trust"
    private_outside.parent.mkdir(parents=True, exist_ok=True)
    private_inside.rename(private_outside)
    return (
        private_outside,
        stable_hash(lifecycle),
        manifest["content_sha256"],
        artifacts,
    )


def _cold_inputs(
    root: Path,
    state_root: Path,
    trust_root: Path,
    artifacts: dict[str, dict],
) -> tuple[Path, Path, Path]:
    state_root.mkdir(parents=True, exist_ok=True)
    trust = load_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    cold = _as_cold_start(artifacts, root)
    receipt, _request = _completed_cold_start_search(
        tmp_path=state_root,
        workspace=root,
        transfer=cold["experience_transfer_bundle"],
        trust_store=trust,
    )
    receipt_path = root / "inputs" / "cold_start_search_receipt.json"
    receipt_ref = _write_canonical(receipt_path, receipt)
    transfer = cold["experience_transfer_bundle"]
    transfer["retrieval_policy"]["retrieval_evidence_refs"] = [receipt_ref]
    _refresh(transfer)
    use = cold["transfer_use_receipt"]
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    _refresh(use)
    transfer_path = root / "inputs" / "experience_transfer_bundle.json"
    use_path = root / "inputs" / "transfer_use_receipt.json"
    _write_canonical(transfer_path, transfer)
    _write_canonical(use_path, use)
    return transfer_path, use_path, receipt_path


def _run_cold(
    root: Path,
    trust_root: Path,
    minimal_sha: str,
    staging_sha: str,
    transfer_path: Path,
    use_path: Path,
    cold_receipt_path: Path,
) -> dict:
    return orchestrator.orchestrate_evo_v2_transfer_use(
        workspace_root=root,
        report_id=REPORT_ID,
        expected_minimal_lifecycle_sha256=minimal_sha,
        expected_staging_content_sha256=staging_sha,
        experience_transfer_bundle_path=transfer_path,
        transfer_use_receipt_path=use_path,
        cold_start_search_receipt_path=cold_receipt_path,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )


def _found_inputs(
    root: Path,
    trust_root: Path,
    artifacts: dict[str, dict],
) -> tuple[Path, Path, Path, Path]:
    trust = load_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    transfer = artifacts["experience_transfer_bundle"]
    use = artifacts["transfer_use_receipt"]
    relative = orchestrator.evo_v2_relative_paths(REPORT_ID)
    projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=transfer,
        transfer_use_receipt=use,
        experience_transfer_bundle_ref={
            "path": relative["experience_transfer_bundle"],
            "sha256": artifact_sha256(transfer),
        },
        transfer_use_receipt_ref={
            "path": relative["transfer_use_receipt"],
            "sha256": artifact_sha256(use),
        },
        trust_store=trust,
        source_workspace=None,
    )
    decision = _completed_review_decision(
        tmp_path=trust_root.parent,
        workspace=root,
        projection=projection,
        artifacts=artifacts,
        trust_store=trust,
    )
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=root.parent / f".{root.name}-formal-plan-runtime",
        factor_id=str(transfer["artifact_identity"]["factor_id"]),
        research_id=str(transfer["artifact_identity"]["research_id"]),
        root_report_id=REPORT_ID,
        implementation_mode="operator",
    )
    write_workspace_manifest(root / "manifest.json", manifest)
    request = _request()
    request.update(
        {
            "factor_id": transfer["artifact_identity"]["factor_id"],
            "research_id": transfer["artifact_identity"]["research_id"],
            "report_id": REPORT_ID,
        }
    )
    catalog_root = root.parent / f".{root.name}-formal-plan-catalog"
    catalog_root.mkdir(parents=True, exist_ok=True)
    catalog = _write_catalog(catalog_root)
    write_web_research_packet(
        workspace=root,
        worktree=REPO_ROOT,
        request=request,
        catalogs=[catalog],
    )
    plan = _fill_plan(root)
    lifecycle_path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    prepared_lifecycle = lifecycle_path.read_bytes()
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(root),
            "--plan",
            str(root / "identity/web_research_plan.json"),
            "--allow-preformal-contract-smoke",
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "FACTORFORGE_STATE_CATALOG": str(catalog),
            "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT": str(trust_root),
            "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID": INSTALLATION_ID,
        },
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    # Formal Web materialization initializes a frozen lifecycle. This fixture has
    # already advanced through the independently Host-signed pre-OOS Council path,
    # so restore that exact current-state payload before transfer orchestration.
    lifecycle_path.write_bytes(prepared_lifecycle)
    initial_change = _transfer_use_change_receipt(
        workspace=root,
        artifacts=artifacts,
        trust_store=trust,
    )
    change = build_evo_v2_transfer_use_change_receipt(
        workspace=root,
        transfer_bundle=transfer,
        transfer_receipt=use,
        before_research_plan_ref=initial_change["before_research_plan_ref"],
        after_research_plan_ref=initial_change["after_research_plan_ref"],
        mapping_uses=initial_change["mapping_uses"],
        protected_contracts=protected_contract_hashes(
            plan=plan,
            worktree=REPO_ROOT,
        ),
        trust_store=trust,
    )
    paths = [
        root / "inputs" / name
        for name in ("transfer.json", "use.json", "review.json", "change.json")
    ]
    for path, payload in zip(paths, (transfer, use, decision, change), strict=True):
        _write_canonical(path, payload)
    return tuple(paths)  # type: ignore[return-value]


def _execution_tests(
    artifacts: dict[str, dict],
    *,
    root: Path | None = None,
) -> list[dict]:
    mappings = {
        item["mapping_id"]: item
        for item in artifacts["experience_transfer_bundle"]["transfer_mappings"]
    }
    tests = []
    for index, use in enumerate(artifacts["transfer_use_receipt"]["uses"]):
        mapping = mappings[use["mapping_id"]]
        test_id = use["generated_test_id"]
        obligation_relative = f"support/evo_v2_execution_obligations/{test_id}.json"
        if root is not None:
            obligation_path = root / obligation_relative
            obligation_path.parent.mkdir(parents=True, exist_ok=True)
            obligation_path.write_bytes(
                canonical_json_bytes(
                    with_content_hash(
                        {
                            "contract_version": (
                                "factorforge_evo_execution_evidence_obligation_v1"
                            ),
                            "test_id": test_id,
                            "evidence_kind": "VERIFIER_CONTRACT",
                            "artifact_contract": EVO_CHILD_RESULT_CONTRACT_VERSION,
                            "verifier_id": EVO_CHILD_RESULT_VERIFIER_ID,
                            "verifier_contract_version": (
                                EVO_CHILD_RESULT_VERIFIER_CONTRACT_VERSION
                            ),
                            "verifier_source_bundle_sha256": verifier_source_bundle(
                                REPO_ROOT
                            )["source_bundle_sha256"],
                            "input_role": "EVO_PURGED_IS_PANEL",
                            "predicate": {
                                "contract_version": "factorforge_evo_panel_predicate_v1",
                                "metric": "ROW_COUNT",
                                "column": None,
                                "comparator": "GE",
                                "threshold": 1,
                                "min_observations": 1,
                            },
                            "information_set": "PURGED_IS_ONLY",
                            "status": "PREREGISTERED_AND_BOUND_NOT_EVALUATED",
                        }
                    )
                )
            )
        tests.append(
            {
                "test_id": test_id,
                "mapping_id": use["mapping_id"],
                "disposition": use["disposition"],
                "research_effect": use["research_effect"],
                "generated_question_ids": [f"question_{use['mapping_id']}"],
                "statement": f"Test from mapping {index}",
                "source_distinguishing_test": mapping["distinguishing_test"],
                "transferred_prediction": mapping["transferred_prediction"],
                "execution_stage": "FRESH_CHILD_PURGED_IS",
                "implementation_mode": (
                    "FORMULA_DIAGNOSTIC" if index == 0 else "EVIDENCE_OBLIGATION"
                ),
                "formula_or_law": "open" if index == 0 else None,
                "signal_column": (f"evo_diagnostic__{test_id}" if index == 0 else None),
                "expected_signature": (
                    mapping["transferred_prediction"]
                    if mapping["transferred_prediction"]
                    != "none; episode supplies a counterexample context"
                    else "the episode remains context only and supplies no acceptance evidence"
                ),
                "falsifier": "the preregistered evidence contradicts this mapping",
                "required_evidence": [obligation_relative],
                "mechanism_prediction_ids": (
                    ["delta_pred_tail_interaction"]
                    if mapping["disposition"]
                    in {"adopted_for_test_only", "challenge_only"}
                    else []
                ),
                "economic_signature_ids": (
                    ["econ_signature_constraint"]
                    if mapping["disposition"] == "adopted_for_test_only"
                    else []
                ),
                "multiple_testing_family": "diagnostic_only_no_acceptance",
                "affects_acceptance": False,
                "information_set": "PURGED_IS_ONLY",
                "current_factor_evidence": False,
                "status": "PREREGISTERED_AND_BOUND_NOT_EVALUATED",
            }
        )
    return tests


def _write_execution_tests(root: Path, artifacts: dict[str, dict]) -> Path:
    path = root / "inputs" / "execution_tests.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(_execution_tests(artifacts, root=root)))
    return path


def test_runtime_signed_cold_start_closes_four_events_and_replays(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    inputs = _cold_inputs(root, trust_root.parent, trust_root, artifacts)

    first = _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    assert first["verdict"] == "PASS"
    assert first["status"] == "ORCHESTRATED"
    assert first["memory_state"] == "COLD_START_NO_ADMISSIBLE_MEMORY"
    assert first["staging_event_count"] == 4
    assert first["authority"]["cold_start_zero_hit_verified"] is True
    assert first["authority"]["preregistered_transfer_tests_bound"] is False
    assert first["authority"]["transfer_test_execution_completed"] is False
    assert first["authority"]["human_approval_granted"] is False
    assert first["authority"]["oos_accessed"] is False
    assert first["authority"]["child_execution_allowed"] is False

    second = _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    assert second["verdict"] == "PASS"
    assert second["status"] == "IDEMPOTENT_REPLAY"
    assert not any(second["actions"].values())


def test_core_record_use_without_execution_addendum_cannot_claim_actual_use(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    with pytest.raises(Exception, match="execution_addendum_required"):
        orchestrator.orchestrate_evo_v2_transfer_use(
            workspace_root=root,
            report_id=REPORT_ID,
            expected_minimal_lifecycle_sha256=minimal_sha,
            expected_staging_content_sha256=staging_sha,
            experience_transfer_bundle_path=transfer_path,
            transfer_use_receipt_path=use_path,
            review_decision_receipt_path=decision_path,
            transfer_use_change_receipt_path=change_path,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
            admissions_root=trust_root.parent / "researcher-memory-evo-v2",
        )
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert lifecycle["current_state"] == "MINIMAL_MECHANISM_DELTA"
    assert (
        len(json.loads(staging_manifest_path(root, REPORT_ID).read_text())["events"])
        == 2
    )


def test_found_branch_materializes_host_bound_preregistered_tests_not_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    tests_path = _write_execution_tests(root, artifacts)
    admissions_root = trust_root.parent / "researcher-memory-evo-v2"
    arguments = {
        "workspace_root": root,
        "report_id": REPORT_ID,
        "expected_minimal_lifecycle_sha256": minimal_sha,
        "expected_staging_content_sha256": staging_sha,
        "experience_transfer_bundle_path": transfer_path,
        "transfer_use_receipt_path": use_path,
        "review_decision_receipt_path": decision_path,
        "transfer_use_change_receipt_path": change_path,
        "execution_tests_path": tests_path,
        "trust_root": trust_root,
        "installation_id": INSTALLATION_ID,
        "admissions_root": admissions_root,
    }
    first = orchestrator.orchestrate_evo_v2_transfer_use(**arguments)
    assert first["verdict"] == "PASS"
    assert first["status"] == "ORCHESTRATED"
    assert first["memory_state"] == "ADMISSIBLE_MEMORY_FOUND"
    assert first["actions"]["execution_addendum_materialized"] is True
    assert first["authority"] == {
        "four_stage_events_exact_readback": True,
        "preregistered_transfer_tests_bound": True,
        "transfer_test_execution_completed": False,
        "transfer_execution_state": "PREREGISTERED_AND_BOUND_NOT_EXECUTED",
        "cold_start_zero_hit_verified": False,
        "human_approval_granted": False,
        "oos_accessed": False,
        "child_execution_allowed": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_memory_write_allowed": False,
        "canonical_factor_write_allowed": False,
        "skill_or_policy_mutation_allowed": False,
    }
    addendum = json.loads(
        execution_addendum_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert addendum["execution_binding"]["state"] == (
        "PREREGISTERED_AND_BOUND_NOT_EVALUATED"
    )
    assert addendum["execution_binding"]["execution_completed"] is False

    second = orchestrator.orchestrate_evo_v2_transfer_use(**arguments)
    assert second["status"] == "IDEMPOTENT_REPLAY"
    assert not any(second["actions"].values())

    forbidden = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{REPORT_ID}.json"
    )
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_bytes(canonical_json_bytes({"later_surface": True}))
    post_human = orchestrator.orchestrate_evo_v2_transfer_use(**arguments)
    assert post_human["status"] == "IDEMPOTENT_REPLAY"
    assert post_human["authority"]["oos_accessed"] is False


def test_incomplete_execution_test_coverage_blocks_formal_found_completion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    tests = _execution_tests(artifacts, root=root)
    tests[0]["mechanism_prediction_ids"] = []
    tests_path = root / "inputs" / "execution_tests.json"
    tests_path.write_bytes(canonical_json_bytes(tests))
    with pytest.raises(
        Exception,
        match="mechanism_prediction_ids.mapping_coverage",
    ):
        orchestrator.orchestrate_evo_v2_transfer_use(
            workspace_root=root,
            report_id=REPORT_ID,
            expected_minimal_lifecycle_sha256=minimal_sha,
            expected_staging_content_sha256=staging_sha,
            experience_transfer_bundle_path=transfer_path,
            transfer_use_receipt_path=use_path,
            review_decision_receipt_path=decision_path,
            transfer_use_change_receipt_path=change_path,
            execution_tests_path=tests_path,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
            admissions_root=trust_root.parent / "researcher-memory-evo-v2",
        )
    assert not execution_addendum_path(root, REPORT_ID).exists()
    assert not orchestrator.transfer_use_orchestration_path(root, REPORT_ID).exists()


def test_crash_after_private_admission_recovers_through_addendum_and_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    tests_path = _write_execution_tests(root, artifacts)
    admissions_root = trust_root.parent / "researcher-memory-evo-v2"
    arguments = {
        "workspace_root": root,
        "report_id": REPORT_ID,
        "expected_minimal_lifecycle_sha256": minimal_sha,
        "expected_staging_content_sha256": staging_sha,
        "experience_transfer_bundle_path": transfer_path,
        "transfer_use_receipt_path": use_path,
        "review_decision_receipt_path": decision_path,
        "transfer_use_change_receipt_path": change_path,
        "execution_tests_path": tests_path,
        "trust_root": trust_root,
        "installation_id": INSTALLATION_ID,
        "admissions_root": admissions_root,
    }
    real_materialize = orchestrator.materialize_evo_execution_addendum

    def crash_before_addendum(**_kwargs: object) -> dict:
        raise RuntimeError("simulated_crash_before_addendum")

    monkeypatch.setattr(
        orchestrator,
        "materialize_evo_execution_addendum",
        crash_before_addendum,
    )
    with pytest.raises(RuntimeError, match="simulated_crash_before_addendum"):
        orchestrator.orchestrate_evo_v2_transfer_use(**arguments)
    assert not execution_addendum_path(root, REPORT_ID).exists()
    assert not orchestrator.transfer_use_orchestration_path(root, REPORT_ID).exists()
    assert len(list((admissions_root / "admissions").glob("*.json"))) == 1

    monkeypatch.setattr(
        orchestrator,
        "materialize_evo_execution_addendum",
        real_materialize,
    )
    recovered = orchestrator.orchestrate_evo_v2_transfer_use(**arguments)
    assert recovered["verdict"] == "PASS"
    assert recovered["status"] == "ORCHESTRATED"
    assert len(list((admissions_root / "admissions").glob("*.json"))) == 1
    assert recovered["authority"]["transfer_test_execution_completed"] is False


def test_rehashed_addendum_cannot_upgrade_registered_tests_to_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    tests_path = _write_execution_tests(root, artifacts)
    admissions_root = trust_root.parent / "researcher-memory-evo-v2"
    arguments = {
        "workspace_root": root,
        "report_id": REPORT_ID,
        "expected_minimal_lifecycle_sha256": minimal_sha,
        "expected_staging_content_sha256": staging_sha,
        "experience_transfer_bundle_path": transfer_path,
        "transfer_use_receipt_path": use_path,
        "review_decision_receipt_path": decision_path,
        "transfer_use_change_receipt_path": change_path,
        "execution_tests_path": tests_path,
        "trust_root": trust_root,
        "installation_id": INSTALLATION_ID,
        "admissions_root": admissions_root,
    }
    assert (
        orchestrator.orchestrate_evo_v2_transfer_use(**arguments)["verdict"] == "PASS"
    )
    path = execution_addendum_path(root, REPORT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_binding"]["execution_completed"] = True
    payload["authority"]["execution_completed"] = True
    payload.pop("content_sha256")
    payload["content_sha256"] = stable_hash(payload)
    path.write_bytes(canonical_json_bytes(payload))

    with pytest.raises(Exception, match="execution_addendum|signature|binding"):
        orchestrator.orchestrate_evo_v2_transfer_use(**arguments)


def test_cold_start_forged_zero_hit_blocks_before_host_transition(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, cold_path = _cold_inputs(
        root, trust_root.parent, trust_root, artifacts
    )
    forged = json.loads(cold_path.read_text(encoding="utf-8"))
    forged["inventory"]["admissible_hit_count"] = 1
    cold_path.write_bytes(canonical_json_bytes(forged))
    transfer = json.loads(transfer_path.read_text(encoding="utf-8"))
    transfer["retrieval_policy"]["retrieval_evidence_refs"][0]["sha256"] = sha256_file(
        cold_path
    )
    _refresh(transfer)
    transfer_path.write_bytes(canonical_json_bytes(transfer))
    use = json.loads(use_path.read_text(encoding="utf-8"))
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    _refresh(use)
    use_path.write_bytes(canonical_json_bytes(use))

    with pytest.raises(Exception, match="cold_start|signature|zero_hit"):
        _run_cold(
            root,
            trust_root,
            minimal_sha,
            staging_sha,
            transfer_path,
            use_path,
            cold_path,
        )
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert lifecycle["current_state"] == "MINIMAL_MECHANISM_DELTA"
    assert (
        len(json.loads(staging_manifest_path(root, REPORT_ID).read_text())["events"])
        == 2
    )


def test_stale_host_cas_and_pre_oos_authority_surfaces_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    inputs = _cold_inputs(root, trust_root.parent, trust_root, artifacts)
    with pytest.raises(Exception, match="minimal_lifecycle_cas_mismatch"):
        _run_cold(root, trust_root, "0" * 64, staging_sha, *inputs)
    with pytest.raises(Exception, match="minimal_staging_cas_mismatch"):
        _run_cold(root, trust_root, minimal_sha, "0" * 64, *inputs)

    forbidden = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{REPORT_ID}.json"
    )
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_bytes(canonical_json_bytes({"forbidden": True}))
    with pytest.raises(Exception, match="human_child_or_oos_surface_present"):
        _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert lifecycle["current_state"] == "MINIMAL_MECHANISM_DELTA"


def test_crash_after_transfer_stage_recovers_without_duplicate_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    inputs = _cold_inputs(root, trust_root.parent, trust_root, artifacts)
    real_materialize = orchestrator.materialize_evo_v2_stage
    crashed = False

    def crash_before_use(**kwargs: object) -> dict:
        nonlocal crashed
        if kwargs.get("stage") == "record-use" and not crashed:
            crashed = True
            raise RuntimeError("simulated_crash_before_record_use")
        return real_materialize(**kwargs)

    monkeypatch.setattr(orchestrator, "materialize_evo_v2_stage", crash_before_use)
    with pytest.raises(RuntimeError, match="simulated_crash_before_record_use"):
        _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    mid = json.loads(staging_manifest_path(root, REPORT_ID).read_text())
    assert [event["stage"] for event in mid["events"]] == [
        "admit-feedback",
        "admit-council-outcome",
        "admit-transfer",
    ]

    monkeypatch.setattr(orchestrator, "materialize_evo_v2_stage", real_materialize)
    recovered = _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    assert recovered["verdict"] == "PASS"
    assert recovered["staging_event_count"] == 4
    final = json.loads(staging_manifest_path(root, REPORT_ID).read_text())
    assert [event["stage"] for event in final["events"]].count("admit-transfer") == 1
    assert [event["stage"] for event in final["events"]].count("record-use") == 1


def test_interrupted_preflight_write_never_publishes_truncated_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "preflight.json"
    payload = {"contract_version": "test_preflight_v1", "value": "x" * 512}
    real_write = orchestrator.os.write
    calls = 0

    def interrupted_write(descriptor: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, data[:17])
        raise OSError("simulated_interrupted_write")

    monkeypatch.setattr(orchestrator.os, "write", interrupted_write)
    with pytest.raises(OSError, match="simulated_interrupted_write"):
        orchestrator._write_once(target, payload)
    assert not target.exists()

    monkeypatch.setattr(orchestrator.os, "write", real_write)
    assert orchestrator._write_once(target, payload) is True
    assert target.read_bytes() == canonical_json_bytes(payload)
    assert orchestrator._write_once(target, payload) is False


def test_retry_cleans_host_owned_truncated_atomic_temporary(tmp_path: Path) -> None:
    target = tmp_path / "preflight.json"
    orphan = tmp_path / ".preflight.json.crashed.tmp"
    orphan.write_bytes(b'{"truncated":')
    orphan.chmod(0o600)
    payload = {"contract_version": "test_preflight_v1", "value": "complete"}

    assert orchestrator._write_once(target, payload) is True
    assert not orphan.exists()
    assert target.read_bytes() == canonical_json_bytes(payload)


def test_interrupted_final_report_publish_recovers_after_four_stage_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    inputs = _cold_inputs(root, trust_root.parent, trust_root, artifacts)
    real_write_once = orchestrator._write_once
    real_os_write = orchestrator.os.write
    interrupted = False

    def interrupt_final(path: Path, payload: dict) -> bool:
        nonlocal interrupted
        if (
            path == orchestrator.transfer_use_orchestration_path(root, REPORT_ID)
            and not interrupted
        ):
            interrupted = True
            calls = 0

            def broken_write(descriptor: int, data: bytes) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_os_write(descriptor, data[:19])
                raise OSError("simulated_final_write_interrupt")

            monkeypatch.setattr(orchestrator.os, "write", broken_write)
            try:
                return real_write_once(path, payload)
            finally:
                monkeypatch.setattr(orchestrator.os, "write", real_os_write)
        return real_write_once(path, payload)

    monkeypatch.setattr(orchestrator, "_write_once", interrupt_final)
    with pytest.raises(OSError, match="simulated_final_write_interrupt"):
        _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    assert not orchestrator.transfer_use_orchestration_path(root, REPORT_ID).exists()
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert lifecycle["current_state"] == "COLD_START_RECORDED"
    assert (
        len(json.loads(staging_manifest_path(root, REPORT_ID).read_text())["events"])
        == 4
    )

    monkeypatch.setattr(orchestrator, "_write_once", real_write_once)
    recovered = _run_cold(root, trust_root, minimal_sha, staging_sha, *inputs)
    assert recovered["verdict"] == "PASS"
    assert recovered["status"] == "ORCHESTRATED"


def test_concurrent_host_cli_uses_one_locked_cas_append(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    trust_root, minimal_sha, staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, cold_path = _cold_inputs(
        root, trust_root.parent, trust_root, artifacts
    )
    command = [
        sys.executable,
        str(CLI),
        "run",
        "--workspace-root",
        str(root),
        "--report-id",
        REPORT_ID,
        "--expected-minimal-lifecycle-sha256",
        minimal_sha,
        "--expected-staging-content-sha256",
        staging_sha,
        "--trust-root",
        str(trust_root),
        "--installation-id",
        INSTALLATION_ID,
        "--experience-transfer-bundle",
        str(transfer_path),
        "--transfer-use-receipt",
        str(use_path),
        "--cold-start-search-receipt",
        str(cold_path),
    ]
    processes = [
        subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    completed = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], completed
    outputs = [json.loads(stdout) for stdout, _stderr in completed]
    assert sorted(item["status"] for item in outputs) == [
        "IDEMPOTENT_REPLAY",
        "ORCHESTRATED",
    ]
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert [event["to_state"] for event in lifecycle["events"]].count(
        "COLD_START_RECORDED"
    ) == 1
    events = json.loads(staging_manifest_path(root, REPORT_ID).read_text())["events"]
    assert len(events) == 4
    assert len({event["event_sha256"] for event in events}) == 4
