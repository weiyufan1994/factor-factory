from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import factor_factory.evo_execution_addendum as addendum
from factor_factory.evo_v2 import canonical_json_bytes, evo_v2_paths, sha256_file
from factor_factory.research_org.runtime_trust import load_runtime_trust_store
from factor_factory.evo_memory_runtime import protected_contract_hashes
from factor_factory.evo_child_execution import verifier_source_bundle
from factor_factory.researcher_memory import (
    build_evo_v2_memory_admission,
    persist_evo_v2_memory_admission,
)
from tests.test_factorforge_evo_transfer_use_orchestrator import (
    INSTALLATION_ID,
    _found_inputs,
    _prepare_minimal,
)
from tests.test_factorforge_evo_v2 import REPORT_ID


def _write(path: Path, payload: dict) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))
    return {"path": path.relative_to(path.parents[1]).as_posix(), "sha256": sha256_file(path)}


def _fixture(tmp_path: Path) -> tuple[Path, object, dict, dict, dict, dict, list[dict]]:
    root = tmp_path / "workspace"
    trust_root, _minimal_sha, _staging_sha, artifacts = _prepare_minimal(root)
    transfer_path, use_path, decision_path, change_path = _found_inputs(
        root, trust_root, artifacts
    )
    transfer = json.loads(transfer_path.read_text())
    use = json.loads(use_path.read_text())
    decision = json.loads(decision_path.read_text())
    change = json.loads(change_path.read_text())
    trust = load_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    plan = json.loads(
        (root / addendum.FROZEN_WEB_RESEARCH_PLAN_PATH).read_text(encoding="utf-8")
    )
    change["protected_contracts"] = protected_contract_hashes(
        plan=plan,
        worktree=Path(__file__).resolve().parents[1],
    )
    # Rebuild the Host-signed receipt after replacing fixture placeholder hashes.
    from factor_factory.researcher_memory import build_evo_v2_transfer_use_change_receipt
    change = build_evo_v2_transfer_use_change_receipt(
        workspace=root,
        transfer_bundle=transfer,
        transfer_receipt=use,
        before_research_plan_ref=change["before_research_plan_ref"],
        after_research_plan_ref=change["after_research_plan_ref"],
        mapping_uses=change["mapping_uses"],
        protected_contracts=protected_contract_hashes(
            plan=plan,
            worktree=Path(__file__).resolve().parents[1],
        ),
        trust_store=trust,
    )
    (root / "inputs/change.json").write_bytes(canonical_json_bytes(change))

    # The execution addendum consumes already admitted canonical core objects.
    # The staging/lifecycle integration is exercised by the orchestrator suite.
    paths = evo_v2_paths(root, REPORT_ID)
    paths["experience_transfer_bundle"].write_bytes(canonical_json_bytes(transfer))
    paths["transfer_use_receipt"].write_bytes(canonical_json_bytes(use))
    bundle_ref = {
        "path": paths["experience_transfer_bundle"].relative_to(root).as_posix(),
        "sha256": sha256_file(paths["experience_transfer_bundle"]),
    }
    use_ref = {
        "path": paths["transfer_use_receipt"].relative_to(root).as_posix(),
        "sha256": sha256_file(paths["transfer_use_receipt"]),
    }
    admission = build_evo_v2_memory_admission(
        workspace=root,
        experience_transfer_bundle_ref=bundle_ref,
        transfer_use_receipt_ref=use_ref,
        review_decision_receipt=decision,
        trust_store=trust,
        transfer_use_change_receipt=change,
    )
    private = persist_evo_v2_memory_admission(
        root=trust_root.parent / "researcher-memory-evo-v2",
        admission=admission,
        repo_root=Path(__file__).resolve().parents[1],
        workspace=root,
        trust_store=trust,
    )
    private_ref = {
        key: private[key]
        for key in (
            "admission_id",
            "admission_sha256",
            "relative_path",
            "file_sha256",
            "semantic_authority",
        )
    }
    after_plan = json.loads(
        (root / change["after_research_plan_ref"]["path"]).read_text()
    )
    text_by_id = {
        item["test_id"]: item["text"] for item in after_plan["registered_tests"]
    }
    mappings = {
        item["mapping_id"]: item for item in transfer["transfer_mappings"]
    }
    change_uses = {
        item["mapping_id"]: item for item in change["mapping_uses"]
    }
    tests: list[dict] = []
    for index, use_item in enumerate(use["uses"]):
        mapping = mappings[use_item["mapping_id"]]
        evidence_path = root / "support" / f"execution_evidence_{index}.json"
        evidence_payload = {
            "contract_version": "factorforge_evo_execution_evidence_obligation_v1",
            "test_id": use_item["generated_test_id"],
            "evidence_kind": "VERIFIER_CONTRACT",
            "artifact_contract": addendum.EVO_CHILD_RESULT_CONTRACT_VERSION,
            "verifier_id": addendum.EVO_CHILD_RESULT_VERIFIER_ID,
            "verifier_contract_version": (
                addendum.EVO_CHILD_RESULT_VERIFIER_CONTRACT_VERSION
            ),
            "verifier_source_bundle_sha256": verifier_source_bundle()[
                "source_bundle_sha256"
            ],
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
            "status": addendum.REGISTERED_STATUS,
        }
        from factor_factory.evo_v2 import stable_json_hash
        evidence_payload["content_sha256"] = stable_json_hash(evidence_payload)
        evidence_path.write_bytes(canonical_json_bytes(evidence_payload))
        evidence_relative = evidence_path.relative_to(root).as_posix()
        tests.append(
            {
                "test_id": use_item["generated_test_id"],
                "mapping_id": use_item["mapping_id"],
                "disposition": use_item["disposition"],
                "research_effect": use_item["research_effect"],
                "generated_question_ids": change_uses[use_item["mapping_id"]]["generated_question_ids"],
                "statement": text_by_id[use_item["generated_test_id"]],
                "source_distinguishing_test": mapping["distinguishing_test"],
                "transferred_prediction": mapping["transferred_prediction"],
                "execution_stage": "FRESH_CHILD_PURGED_IS",
                "implementation_mode": "FORMULA_DIAGNOSTIC" if index == 0 else "EVIDENCE_OBLIGATION",
                "formula_or_law": "open" if index == 0 else None,
                "signal_column": f"evo_diagnostic__{use_item['generated_test_id']}" if index == 0 else None,
                "expected_signature": "diagnostic-only predicted signature",
                "falsifier": "registered diagnostic does not discriminate the rival",
                "required_evidence": [evidence_relative],
                "mechanism_prediction_ids": ["delta_pred_tail_interaction"] if index < 2 else [],
                "economic_signature_ids": ["econ_signature_constraint"] if index == 0 else [],
                "multiple_testing_family": "diagnostic_only_no_acceptance",
                "affects_acceptance": False,
                "information_set": "PURGED_IS_ONLY",
                "current_factor_evidence": False,
                "status": addendum.REGISTERED_STATUS,
            }
        )
    return root, trust, transfer, use, change, private_ref, tests


def test_host_signed_execution_addendum_binds_tests_but_not_execution(
    tmp_path: Path,
) -> None:
    root, trust, transfer, use, change, private_ref, tests = _fixture(tmp_path)
    result = addendum.materialize_evo_execution_addendum(
        workspace_root=root,
        report_id=REPORT_ID,
        transfer_bundle=transfer,
        transfer_use_receipt=use,
        change_receipt=change,
        change_receipt_ref={
            "path": "inputs/change.json",
            "sha256": sha256_file(root / "inputs/change.json"),
        },
        private_admission_ref=private_ref,
        execution_tests=tests,
        execution_target="FRESH_CHILD_PURGED_IS",
        trust_store=trust,
        admissions_root=trust.root.parent / "researcher-memory-evo-v2",
    )
    assert result["verdict"] == "PASS"
    assert result["execution_completed"] is False
    assert result["payload"]["authority"]["child_execution_allowed"] is False
    assert result["payload"]["execution_binding"]["registered_test_count"] == 3
    assert addendum.load_and_validate_evo_execution_addendum(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_store=trust,
        private_admission_ref=private_ref,
        admissions_root=trust.root.parent / "researcher-memory-evo-v2",
    )[1] == []


def test_missing_mapping_or_protected_drift_is_rejected(tmp_path: Path) -> None:
    root, trust, transfer, use, change, private_ref, tests = _fixture(tmp_path)
    change_ref = {"path": "inputs/change.json", "sha256": sha256_file(root / "inputs/change.json")}
    with pytest.raises(addendum.EvoExecutionAddendumError, match="mapping_order|test_id_order"):
        addendum.build_evo_execution_addendum(
            workspace_root=root,
            report_id=REPORT_ID,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change,
            change_receipt_ref=change_ref,
            private_admission_ref=private_ref,
            execution_tests=tests[:-1],
            execution_target="FRESH_CHILD_PURGED_IS",
            trust_store=trust,
            admissions_root=trust.root.parent / "researcher-memory-evo-v2",
        )
    forged = copy.deepcopy(change)
    forged["protected_contracts"]["unchanged"] = False
    with pytest.raises(addendum.EvoExecutionAddendumError, match="protected_contracts"):
        addendum.build_evo_execution_addendum(
            workspace_root=root,
            report_id=REPORT_ID,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=forged,
            change_receipt_ref=change_ref,
            private_admission_ref=private_ref,
            execution_tests=tests,
            execution_target="FRESH_CHILD_PURGED_IS",
            trust_store=trust,
            admissions_root=trust.root.parent / "researcher-memory-evo-v2",
        )


def test_partial_publish_leaves_no_truncated_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "execution_addendum.json"
    payload = {"value": "x" * 512}
    real = addendum.os.write
    calls = 0

    def interrupted(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real(fd, data[:13])
        raise OSError("interrupted")

    monkeypatch.setattr(addendum.os, "write", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        addendum._write_once(tmp_path, target, payload)
    assert not target.exists()
    monkeypatch.setattr(addendum.os, "write", real)
    assert addendum._write_once(tmp_path, target, payload) is True
    assert target.read_bytes() == canonical_json_bytes(payload)


def test_output_ancestor_symlink_cannot_write_outside_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "objects").mkdir()
    (root / "objects" / "evo_v2").symlink_to(outside, target_is_directory=True)
    target = addendum.execution_addendum_path(root, "REPORT_X")

    with pytest.raises(
        addendum.EvoExecutionAddendumError,
        match="unsafe_output_parent|unsafe_output_path",
    ):
        addendum._write_once(root, target, {"probe": "outside"})

    assert not (outside / "REPORT_X" / "execution_addendum.json").exists()


def test_fake_private_ref_constant_formula_and_unbound_evidence_fail(
    tmp_path: Path,
) -> None:
    root, trust, transfer, use, change, private_ref, tests = _fixture(tmp_path)
    change_ref = {"path": "inputs/change.json", "sha256": sha256_file(root / "inputs/change.json")}

    fake_private = dict(private_ref)
    fake_private["admission_id"] = "evo2_admission_not_present"
    with pytest.raises(addendum.EvoExecutionAddendumError, match="private_admission_readback"):
        addendum.build_evo_execution_addendum(
            workspace_root=root,
            report_id=REPORT_ID,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change,
            change_receipt_ref=change_ref,
            private_admission_ref=fake_private,
            execution_tests=tests,
            execution_target="FRESH_CHILD_PURGED_IS",
            trust_store=trust,
            admissions_root=trust.root.parent / "researcher-memory-evo-v2",
        )

    constant = copy.deepcopy(tests)
    constant[0]["formula_or_law"] = "1"
    with pytest.raises(addendum.EvoExecutionAddendumError, match="formula_diagnostic"):
        addendum.build_evo_execution_addendum(
            workspace_root=root,
            report_id=REPORT_ID,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change,
            change_receipt_ref=change_ref,
            private_admission_ref=private_ref,
            execution_tests=constant,
            execution_target="FRESH_CHILD_PURGED_IS",
            trust_store=trust,
            admissions_root=trust.root.parent / "researcher-memory-evo-v2",
        )

    unbound = copy.deepcopy(tests)
    unbound[0]["required_evidence"] = ["support/not_present.json"]
    with pytest.raises(addendum.EvoExecutionAddendumError, match="required_evidence"):
        addendum.build_evo_execution_addendum(
            workspace_root=root,
            report_id=REPORT_ID,
            transfer_bundle=transfer,
            transfer_use_receipt=use,
            change_receipt=change,
            change_receipt_ref=change_ref,
            private_admission_ref=private_ref,
            execution_tests=unbound,
            execution_target="FRESH_CHILD_PURGED_IS",
            trust_store=trust,
            admissions_root=trust.root.parent / "researcher-memory-evo-v2",
        )
