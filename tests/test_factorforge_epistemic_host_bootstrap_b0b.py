from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from factor_factory.epistemic_host_bootstrap import load_frozen_bootstrap_contracts
from factor_factory.epistemic_host_bootstrap_b0b import (
    B0A_R2_MANIFEST_SHA256,
    B0B_STATUS,
    EpistemicHostBootstrapB0BError,
    _extract_rule6_expectations,
    build_b0b_implementation_inventory,
    build_b0b_validation_report,
    compile_b0b_exact261_layout_scaffold,
    compile_b0b_expectation_gap_ledger,
    compile_b0b_plan,
    require_b0b_execution_authority,
    validate_b0b_exact261_layout_scaffold,
    validate_b0b_expectation_gap_ledger,
    write_b0b_candidate_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT.parent
R2_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-authorization-binding-"
    "successor-r2-20260827/packet_manifest.json"
)
O0_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
    "o0-20260827/packet_manifest.json"
)
O0_PRIME_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
    "o0-prime-review-20260828/packet_manifest.json"
)
B0A_R2_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-b0-offline-candidate-"
    "r2-20260828/packet_manifest.json"
)


def _frozen_contracts():
    required = (R2_MANIFEST, O0_MANIFEST, O0_PRIME_MANIFEST, B0A_R2_MANIFEST)
    if not all(path.is_file() for path in required):
        pytest.skip("manifest-bound B0-B predecessor lineage is not staged")
    assert hashlib.sha256(B0A_R2_MANIFEST.read_bytes()).hexdigest() == (
        B0A_R2_MANIFEST_SHA256
    )
    return load_frozen_bootstrap_contracts(
        stage1b_repo_root=REPO_ROOT,
        r2_manifest_path=R2_MANIFEST,
        o0_manifest_path=O0_MANIFEST,
        o0_prime_manifest_path=O0_PRIME_MANIFEST,
    )


def _compile_all():
    contracts = _frozen_contracts()
    plan = compile_b0b_plan(
        contracts,
        b0a_r2_manifest_path=B0A_R2_MANIFEST,
    )
    gap = compile_b0b_expectation_gap_ledger(contracts)
    layout = compile_b0b_exact261_layout_scaffold(contracts, gap_ledger=gap)
    inventory = build_b0b_implementation_inventory(REPO_ROOT)
    report = build_b0b_validation_report(
        contracts=contracts,
        b0a_r2_manifest_path=B0A_R2_MANIFEST,
        plan=plan,
        gap_ledger=gap,
        layout=layout,
        implementation_inventory=inventory,
    )
    return contracts, plan, gap, layout, inventory, report


def test_gap_ledger_exact170_and_only_rule6_expectations_are_bound() -> None:
    contracts = _frozen_contracts()
    ledger = compile_b0b_expectation_gap_ledger(contracts)
    assert ledger["row_count"] == 170
    assert ledger["frozen_expectation_count"] == 10
    assert ledger["unbound_expectation_count"] == 160
    assert [row["global_obligation_ordinal"] for row in ledger["rows"]] == list(
        range(170)
    )
    assert [
        sum(row["source_contract_ordinal"] == source for row in ledger["rows"])
        for source in range(5)
    ] == [10, 36, 50, 43, 31]
    assert ledger["rows"][0]["expected_verdict"] == "PASS"
    assert ledger["rows"][0]["expected_public_reason_code"] == "NONE"
    assert ledger["rows"][8]["expected_verdict"] == "BLOCKED"
    assert ledger["rows"][8]["expected_public_reason_code"] == (
        "KEY_UNIVERSE_INCOMPLETE"
    )
    assert all(
        row["expected_verdict"] is None
        and row["expected_public_reason_code"] is None
        and row["expectation_state"] == "DUAL_GIT_EXPECTATION_UNBOUND"
        and len(row["allowed_expectation_pairs"]) == 2
        for row in ledger["rows"][10:]
    )
    assert ledger["expectation_authority"]["authority_state"] == (
        "UNBOUND_BLOCKING"
    )
    mutation_paths = (
        ("source_vector_ordinal", 1),
        ("vector_name", "DRIFTED_VECTOR"),
        ("expected_verdict", "BLOCKED"),
        ("expected_public_reason_code", "KEY_UNIVERSE_INCOMPLETE"),
    )
    for field, drifted_value in mutation_paths:
        tampered = copy.deepcopy(contracts)
        branch = tampered.schema_bundle["$defs"][
            "mandatory_conformance_obligation"
        ]["oneOf"][0]["oneOf"][0]["properties"]
        branch[field]["const"] = drifted_value
        with pytest.raises(EpistemicHostBootstrapB0BError):
            _extract_rule6_expectations(tampered)


def test_exact261_layout_is_closed_and_nonmaterialized() -> None:
    contracts = _frozen_contracts()
    ledger = compile_b0b_expectation_gap_ledger(contracts)
    layout = compile_b0b_exact261_layout_scaffold(contracts, gap_ledger=ledger)
    assert layout["slot_count"] == 261
    assert [row["case_ordinal"] for row in layout["slots"]] == list(range(261))
    assert [row["case_class"] for row in layout["slots"][:170]] == [
        "MANDATORY"
    ] * 170
    assert [row["rule_ordinal"] for row in layout["slots"][170:174]] == [
        11,
        16,
        27,
        31,
    ]
    other_rules = [
        ordinal for ordinal in range(34) if ordinal not in {6, 11, 16, 27, 31}
    ]
    assert [
        (
            layout["slots"][174 + index * 3]["rule_ordinal"],
            [
                layout["slots"][174 + index * 3 + offset][
                    "required_verdict_class"
                ]
                for offset in range(3)
            ],
        )
        for index in range(29)
    ] == [(ordinal, ["PASS", "FAIL", "BLOCKED"]) for ordinal in other_rules]
    assert all(not row["materialized"] for row in layout["slots"])
    assert all(row["case_id"] is None for row in layout["slots"])
    assert all(row["execution_status"] == "NOT_EXECUTED" for row in layout["slots"])
    assert layout["formal_preflight_satisfied"] is False


def test_tamper_and_execution_attempts_fail_closed() -> None:
    contracts = _frozen_contracts()
    ledger = compile_b0b_expectation_gap_ledger(contracts)
    layout = compile_b0b_exact261_layout_scaffold(contracts, gap_ledger=ledger)
    tampered_ledger = copy.deepcopy(ledger)
    tampered_ledger["rows"][10]["expected_verdict"] = "FAIL"
    with pytest.raises(
        EpistemicHostBootstrapB0BError,
        match="b0b_gap_ledger_closed_equality",
    ):
        validate_b0b_expectation_gap_ledger(tampered_ledger, contracts=contracts)
    tampered_layout = copy.deepcopy(layout)
    tampered_layout["slots"][0]["materialized"] = True
    with pytest.raises(
        EpistemicHostBootstrapB0BError,
        match="b0b_layout_closed_equality",
    ):
        validate_b0b_exact261_layout_scaffold(
            tampered_layout,
            contracts=contracts,
            gap_ledger=ledger,
        )
    with pytest.raises(
        EpistemicHostBootstrapB0BError,
        match="B0B_EXPECTATION_FIXTURE_EXECUTION_AUTHORITY_UNBOUND",
    ):
        require_b0b_execution_authority(gap_ledger=ledger, layout=layout)


def test_local_report_is_predicate_derived_and_non_authorizing() -> None:
    _, plan, gap, layout, inventory, report = _compile_all()
    assert plan["status"] == B0B_STATUS
    assert report["local_structural_verdict"] == "LOCAL_CANDIDATE_SCAFFOLD_PASS"
    assert report["blocking_verdict"] == "BLOCKED_EXPECTATION_AUTHORITY_UNBOUND"
    assert report["structural_check_count"] == 8
    assert all(row["verdict"] == "PASS" for row in report["structural_checks"])
    assert len(report["blocking_conditions"]) == 7
    assert report["candidate_layout_slot_count"] == 261
    assert report["candidate_materialized_case_count"] == 0
    assert report["candidate_obligation_executed_count"] == 0
    assert report["formal_mandatory_obligation_executed_count"] == 0
    assert report["formal_preflight_satisfied"] is False
    assert report["is_semantic_validation_receipt"] is False
    assert report["may_satisfy_adjudicative_pass"] is False
    assert report["may_satisfy_host_or_operating_authority"] is False
    assert report["signed"] is False
    assert report["authority_effect"] == "NONE"
    tampered = copy.deepcopy(gap)
    tampered["rows"][46], tampered["rows"][47] = (
        tampered["rows"][47],
        tampered["rows"][46],
    )
    with pytest.raises(EpistemicHostBootstrapB0BError):
        build_b0b_validation_report(
            contracts=_frozen_contracts(),
            b0a_r2_manifest_path=B0A_R2_MANIFEST,
            plan=plan,
            gap_ledger=tampered,
            layout=layout,
            implementation_inventory=inventory,
        )


def test_b0b_packet_atomic_publish_exact6(tmp_path: Path) -> None:
    _, plan, gap, layout, inventory, report = _compile_all()
    output = tmp_path / "b0b-packet"
    manifest = write_b0b_candidate_bundle(
        output,
        plan=plan,
        gap_ledger=gap,
        layout=layout,
        report=report,
        implementation_inventory=inventory,
    )
    assert os.fspath(output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    expected_names = {
        "00_b0b_plan.json",
        "01_b0b_expectation_gap_ledger.json",
        "02_b0b_exact261_layout_scaffold.json",
        "03_b0b_validation_report.json",
        "04_b0b_implementation_inventory.json",
        "packet_manifest.json",
    }
    assert {path.name for path in output.iterdir()} == expected_names
    assert manifest["artifact_count"] == 5
    assert manifest["candidate_layout_slot_count"] == 261
    assert manifest["candidate_materialized_case_count"] == 0
    assert manifest["candidate_obligation_executed_count"] == 0
    assert manifest["review_eligible"] is False
    assert manifest["live_ceremony_authorized"] is False
    assert manifest["permissions_opened_count"] == 0
    assert manifest["authority_effect"] == "NONE"
    for path in output.iterdir():
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_nlink == 1
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        json.loads(path.read_text(encoding="utf-8"))
    for row in manifest["ordered_artifacts"]:
        raw = (output / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    commitment = hashlib.sha256(
        b"FF_B0B_SCAFFOLD_ARTIFACT_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["sha256"])
            for row in manifest["ordered_artifacts"]
        )
    ).hexdigest()
    assert commitment == manifest["artifact_manifest_commitment_sha256"]
    with pytest.raises(EpistemicHostBootstrapB0BError, match="b0b_output_root_exists"):
        write_b0b_candidate_bundle(
            output,
            plan=plan,
            gap_ledger=gap,
            layout=layout,
            report=report,
            implementation_inventory=inventory,
        )


def test_b0b_implementation_surface_is_closed() -> None:
    inventory = build_b0b_implementation_inventory(REPO_ROOT)
    assert inventory["file_count"] == 3
    assert inventory["dependency_file_count"] == 4
    assert len(inventory["ordered_dependencies"]) == 4
    assert inventory["network_adapter_present"] is False
    assert inventory["live_host_adapter_present"] is False
    assert inventory["semantic_engine_present"] is False
    assert inventory["fixture_materializer_present"] is False
    assert all(
        row["surface_analysis"]["surface_verdict"] == "PASS"
        and not row["surface_analysis"][
            "forbidden_network_crypto_dynamic_execution_hits"
        ]
        for row in inventory["ordered_files"]
    )
