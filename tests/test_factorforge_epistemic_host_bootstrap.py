from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from factor_factory.epistemic_host_bootstrap import (
    AUTHORITY_EFFECT,
    EXECUTION_MODE,
    EXPECTED_ACTUAL_KEYS,
    EXPECTED_PERMISSION_KEYS,
    EXPECTED_STAGE1B_ARTIFACTS,
    EXPECTED_TRUST_DOMAIN_ROLE_MAPPING,
    FrozenBootstrapContracts,
    EpistemicHostBootstrapError,
    build_b0_implementation_inventory,
    build_b0_validation_report,
    compile_b0_bootstrap_plan,
    compile_b0_obligation_skeleton,
    load_frozen_bootstrap_contracts,
    validate_b0_bootstrap_plan,
    validate_b0_obligation_skeleton,
    write_b0_candidate_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT.parent


def _read_json(relative: str) -> dict:
    payload = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _frozen_lineage_paths() -> tuple[Path, Path, Path]:
    return (
        PROJECTS_ROOT
        / (
            "factor-forge-epistemic-graph-v2-p1a-authorization-binding-"
            "successor-r2-20260827/packet_manifest.json"
        ),
        PROJECTS_ROOT
        / (
            "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
            "o0-20260827/packet_manifest.json"
        ),
        PROJECTS_ROOT
        / (
            "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
            "o0-prime-review-20260828/packet_manifest.json"
        ),
    )


def _unit_contracts() -> FrozenBootstrapContracts:
    return FrozenBootstrapContracts(
        repo_root=REPO_ROOT,
        stage1b_manifest=_read_json(
            "docs/contracts/"
            "factorforge-epistemic-host-readback-stage1b0-packet-manifest-v1.json"
        ),
        meta_registry=_read_json(EXPECTED_STAGE1B_ARTIFACTS[1][0]),
        schema_bundle=_read_json(EXPECTED_STAGE1B_ARTIFACTS[0][0]),
        r2_manifest={},
        o0_manifest={},
        o0_prime_manifest={},
        o0_prime_verdict={},
    )


def _loaded_contracts() -> FrozenBootstrapContracts:
    r2, o0, o0_prime = _frozen_lineage_paths()
    if not all(path.is_file() for path in (r2, o0, o0_prime)):
        pytest.skip("local manifest-bound lineage is not staged")
    return load_frozen_bootstrap_contracts(
        stage1b_repo_root=REPO_ROOT,
        r2_manifest_path=r2,
        o0_manifest_path=o0,
        o0_prime_manifest_path=o0_prime,
    )


def test_compile_plan_is_closed_synthetic_only_and_non_authorizing() -> None:
    contracts = _unit_contracts()
    plan = compile_b0_bootstrap_plan(contracts)
    validate_b0_bootstrap_plan(plan, contracts=contracts)
    assert plan["execution_mode"] == EXECUTION_MODE
    assert plan["status"] == "PARTIAL_B0_CANDIDATE__NOT_REVIEW_ELIGIBLE"
    assert plan["review_eligible"] is False
    assert plan["live_ceremony_authorized"] is False
    assert plan["signed"] is False
    assert plan["authority_effect"] == AUTHORITY_EFFECT
    assert plan["permissions"] == {key: False for key in EXPECTED_PERMISSION_KEYS}
    assert plan["actuals"] == {key: None for key in EXPECTED_ACTUAL_KEYS}
    assert [row["trust_domain"] for row in plan["trust_domain_role_mapping"]] == list(
        EXPECTED_TRUST_DOMAIN_ROLE_MAPPING
    )
    assert [len(row["key_roles"]) for row in plan["trust_domain_role_mapping"]] == [
        3,
        2,
        1,
        1,
    ]
    assert len(plan["required_out_of_band_pins"]) == 25


def test_compiler_reconstructs_exact_170_vector_skeleton_without_expectations() -> None:
    contracts = _unit_contracts()
    skeleton = compile_b0_obligation_skeleton(contracts)
    validate_b0_obligation_skeleton(skeleton, contracts=contracts)
    rows = skeleton["rows"]
    assert len(rows) == 170
    assert [row["global_obligation_ordinal"] for row in rows] == list(range(170))
    assert len({row["vector_name"] for row in rows}) == 170
    assert [
        sum(row["source_contract_ordinal"] == source for row in rows)
        for source in range(5)
    ] == [10, 36, 50, 43, 31]
    assert all(row["expected_verdict"] is None for row in rows)
    assert all(row["case_id"] is None for row in rows)
    assert all(row["execution_status"] == "NOT_EXECUTED" for row in rows)
    assert skeleton["executed_obligation_count"] == 0
    assert skeleton["cases_materialized_count"] == 0


def test_plan_and_skeleton_tamper_fail_closed() -> None:
    contracts = _unit_contracts()
    plan = compile_b0_bootstrap_plan(contracts)
    tampered_plan = copy.deepcopy(plan)
    tampered_plan["permissions"]["live_host_readback"] = True
    with pytest.raises(EpistemicHostBootstrapError, match="b0_plan_closed_equality"):
        validate_b0_bootstrap_plan(tampered_plan, contracts=contracts)
    skeleton = compile_b0_obligation_skeleton(contracts)
    tampered_skeleton = copy.deepcopy(skeleton)
    tampered_skeleton["rows"][0]["execution_status"] = "PASS"
    with pytest.raises(EpistemicHostBootstrapError, match="b0_skeleton_closed_equality"):
        validate_b0_obligation_skeleton(tampered_skeleton, contracts=contracts)


def test_source_vector_removal_or_duplicate_blocks_compilation() -> None:
    contracts = _unit_contracts()
    schema = copy.deepcopy(contracts.schema_bundle)
    vector_path = schema["x-factorforge-semantic-rule-design-requirements"]["rules"][
        6
    ]["conformance_vector_set"]
    vector_path[-1] = vector_path[0]
    broken = FrozenBootstrapContracts(
        **{**contracts.__dict__, "schema_bundle": schema}
    )
    with pytest.raises(EpistemicHostBootstrapError):
        compile_b0_obligation_skeleton(broken)


def test_validation_report_derives_every_pass_and_blocks_tamper() -> None:
    contracts = _loaded_contracts()
    plan = compile_b0_bootstrap_plan(contracts)
    skeleton = compile_b0_obligation_skeleton(contracts)
    implementation_inventory = build_b0_implementation_inventory(REPO_ROOT)
    report = build_b0_validation_report(
        contracts=contracts,
        plan=plan,
        skeleton=skeleton,
        implementation_inventory=implementation_inventory,
    )
    assert report["structural_check_count"] == 15
    assert all(
        set(row) == {"ordinal", "predicate_id", "evidence_basis", "verdict"}
        and row["verdict"] == "PASS"
        for row in report["structural_checks"]
    )
    assert report["mandatory_obligation_discovered_count"] == 170
    assert report["mandatory_obligation_executed_count"] == 0
    assert report["minimum_distinct_case_count"] == 261
    assert report["materialized_case_count"] == 0
    assert report["semantic_validation_receipt"] is False
    assert report["review_eligible"] is False
    assert report["live_ready"] is False
    assert report["signed"] is False
    assert report["authority_effect"] == AUTHORITY_EFFECT
    tampered_plan = copy.deepcopy(plan)
    tampered_plan["permissions"]["live_host_readback"] = True
    with pytest.raises(EpistemicHostBootstrapError, match="b0_plan_closed_equality"):
        build_b0_validation_report(
            contracts=contracts,
            plan=tampered_plan,
            skeleton=skeleton,
            implementation_inventory=implementation_inventory,
        )
    tampered_skeleton = copy.deepcopy(skeleton)
    tampered_skeleton["rows"][0]["execution_status"] = "PASS"
    with pytest.raises(EpistemicHostBootstrapError, match="b0_skeleton_closed_equality"):
        build_b0_validation_report(
            contracts=contracts,
            plan=plan,
            skeleton=tampered_skeleton,
            implementation_inventory=implementation_inventory,
        )
    tampered_inventory = copy.deepcopy(implementation_inventory)
    tampered_inventory["ordered_files"][0]["surface_analysis"][
        "observed_import_modules"
    ].append("socket")
    with pytest.raises(
        EpistemicHostBootstrapError,
        match="b0_implementation_inventory_closed_equality",
    ):
        build_b0_validation_report(
            contracts=contracts,
            plan=plan,
            skeleton=skeleton,
            implementation_inventory=tampered_inventory,
        )


def test_bundle_is_create_only_exact5_and_contains_no_private_material(
    tmp_path: Path,
) -> None:
    contracts = _loaded_contracts()
    plan = compile_b0_bootstrap_plan(contracts)
    skeleton = compile_b0_obligation_skeleton(contracts)
    implementation_inventory = build_b0_implementation_inventory(REPO_ROOT)
    report = build_b0_validation_report(
        contracts=contracts,
        plan=plan,
        skeleton=skeleton,
        implementation_inventory=implementation_inventory,
    )
    root = tmp_path / "b0-candidate"
    manifest = write_b0_candidate_bundle(
        root,
        plan=plan,
        skeleton=skeleton,
        report=report,
        implementation_inventory=implementation_inventory,
    )
    assert manifest["artifact_count"] == 4
    assert manifest["review_eligible"] is False
    assert manifest["live_ceremony_authorized"] is False
    assert manifest["operational_predecessor_satisfied_count"] == 0
    assert manifest["permissions_opened_count"] == 0
    assert manifest["authority_effect"] == AUTHORITY_EFFECT
    assert manifest["candidate_integrity_profile"]["profile_id"] == (
        "LOCAL_NONAUTHORITATIVE_CANDIDATE_INTEGRITY_ONLY"
    )
    assert {path.name for path in root.iterdir()} == {
        "00_b0_bootstrap_plan.json",
        "01_b0_obligation_skeleton.json",
        "02_b0_validation_report.json",
        "03_b0_implementation_inventory.json",
        "packet_manifest.json",
    }
    for row in manifest["ordered_artifacts"]:
        raw = (root / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        lowered = raw.lower()
        assert b"private_key" not in lowered
        assert b"-----begin" not in lowered
    with pytest.raises(EpistemicHostBootstrapError, match="output_root_must_not_exist"):
        write_b0_candidate_bundle(
            root,
            plan=plan,
            skeleton=skeleton,
            report=report,
            implementation_inventory=implementation_inventory,
        )


def test_manifest_bound_lineage_loader_passes_current_frozen_packets() -> None:
    contracts = _loaded_contracts()
    assert compile_b0_bootstrap_plan(contracts)["source_contracts"][2][
        "sha256"
    ] == "55c44b4ff4740603f972674b286edd71223edeaac2bfae8650cc27e1454a1aa0"
