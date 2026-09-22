from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from factor_factory.evo_oos import (
    BLOCK_OOS_ALLOCATION,
    OOS_ALLOCATION_AUTHORITY_SECURE,
    OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
    OOS_ALLOCATION_VERSION,
    OOS_HOST_AUTHORITY,
    _allocate_fresh_child_oos,
    build_oos_registry_allocation_prefix,
    consume_oos_allocation_for_release,
    oos_allocation_path,
    oos_registry_path,
    validate_fresh_child_oos_allocation,
    validate_oos_registry,
)
from factor_factory.evo_oos import (
    stable_hash as oos_hash,
)
from factor_factory.human_approval import (
    BLOCK_HUMAN_APPROVAL,
    HUMAN_APPROVAL_DECISION,
    HUMAN_APPROVAL_RECEIPT_VERSION,
    HUMAN_APPROVAL_TRUST_VERSION,
    canonical_json_bytes,
    sha256_file,
    stable_hash,
    validate_external_human_approval_receipt,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_approval_script():
    path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py"
    )
    spec = importlib.util.spec_from_file_location("evo_human_approval_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_multibranch_approval_script():
    path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evo_multibranch_approval_under_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_ultimate_loop():
    path = REPO_ROOT / "scripts/run_factorforge_ultimate_loop.py"
    spec = importlib.util.spec_from_file_location("evo_ultimate_loop_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _human_fixture(root: Path) -> tuple[dict, dict, dict[str, Path]]:
    private = Ed25519PrivateKey.generate()
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = __import__("hashlib").sha256(raw_public).hexdigest()
    trust_unsigned = {
        "contract_version": HUMAN_APPROVAL_TRUST_VERSION,
        "keys": {
            key_id: {
                "algorithm": "Ed25519",
                "public_key_b64": base64.b64encode(raw_public).decode("ascii"),
                "status": "ACTIVE",
            }
        },
    }
    trust = {**trust_unsigned, "content_sha256": stable_hash(trust_unsigned)}
    paths = {
        "synthesis": root / "objects/council/synthesis.json",
        "delta": root / "objects/evo_v2/PARENT/mechanism_delta.json",
        "backprojection": root / "objects/evo_v2/PARENT/economic_backprojection.json",
    }
    _write_json(paths["synthesis"], {"selected": "law_one"})
    _write_json(paths["delta"], {"minimal_extension": {"delta_id": "delta_one"}})
    _write_json(paths["backprojection"], {"delta_id": "delta_one"})
    allocation_path = root / "objects/research_protocol/evo_oos_allocation__CHILD.json"
    allocation = _allocation(root)
    _registry(root, allocation)
    relative = lambda path: path.relative_to(root).as_posix()
    receipt_unsigned = {
        "contract_version": HUMAN_APPROVAL_RECEIPT_VERSION,
        "report_id": "PARENT",
        "run_id": "parent_run_001",
        "decision": HUMAN_APPROVAL_DECISION,
        "synthesis": {
            "path": relative(paths["synthesis"]),
            "sha256": sha256_file(paths["synthesis"]),
        },
        "selected_law": {
            "law_id": "law_one",
            "law_or_formula_hash": "1" * 64,
            "child_formula_hash": "2" * 64,
        },
        "mechanism_delta": {
            "path": relative(paths["delta"]),
            "sha256": sha256_file(paths["delta"]),
            "delta_id": "delta_one",
        },
        "economic_backprojection": {
            "path": relative(paths["backprojection"]),
            "sha256": sha256_file(paths["backprojection"]),
            "delta_id": "delta_one",
        },
        "child_intent": {
            "action": "MATERIALIZE_AND_TEST_FRESH_OOS_CHILD",
            "child_report_id": "CHILD",
            "child_formula_hash": "2" * 64,
            "fresh_sealed_oos_required": True,
            "reuse_parent_ancestor_or_sibling_oos_allowed": False,
            "oos_allocation_id": "allocation_child_001",
            "oos_allocation_ref": "objects/research_protocol/evo_oos_allocation__CHILD.json",
            "oos_allocation_sha256": sha256_file(allocation_path),
            "oos_registry_prefix_ref": build_oos_registry_allocation_prefix(
                root=root,
                allocation_id="allocation_child_001",
                report_id="CHILD",
            ),
        },
        "issued_at_utc": "2026-08-12T06:00:00Z",
        "issuer": {
            "kind": "external_human",
            "human_id": "human_owner_001",
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
    return receipt, trust, paths


def _validate_human(
    root: Path, receipt: dict, trust: dict, paths: dict[str, Path]
) -> list[str]:
    return validate_external_human_approval_receipt(
        receipt,
        trust_manifest=trust,
        workspace_root=root,
        report_id="PARENT",
        run_id="parent_run_001",
        synthesis_path=paths["synthesis"],
        selected_law_id="law_one",
        selected_law_hash="1" * 64,
        child_formula_hash="2" * 64,
        mechanism_delta_path=paths["delta"],
        economic_backprojection_path=paths["backprojection"],
    )


def test_external_human_receipt_binds_all_evo_child_surfaces(tmp_path: Path) -> None:
    receipt, trust, paths = _human_fixture(tmp_path)
    assert _validate_human(tmp_path, receipt, trust, paths) == []


def test_agent_or_runtime_issuer_cannot_self_authorize(tmp_path: Path) -> None:
    receipt, trust, paths = _human_fixture(tmp_path)
    receipt["issuer"]["kind"] = "runtime_adapter"
    reasons = _validate_human(tmp_path, receipt, trust, paths)
    assert any("issuer_not_external_human" in reason for reason in reasons)
    assert any("receipt_id" in reason or "signature" in reason for reason in reasons)


def test_approval_bridge_requires_out_of_band_trust_manifest_pin(
    tmp_path: Path,
) -> None:
    module = _load_approval_script()
    receipt, trust, paths = _human_fixture(tmp_path)
    trust_path = tmp_path / "identity/human_approval_trust.json"
    receipt_path = tmp_path / "identity/human_approval_receipt.json"
    _write_json(trust_path, trust)
    _write_json(receipt_path, receipt)
    loaded, loaded_path = module.load_and_validate_external_approval(
        root=tmp_path,
        report_id="PARENT",
        run_id="parent_run_001",
        receipt_path_raw=receipt_path.relative_to(tmp_path).as_posix(),
        synthesis_path=paths["synthesis"],
        selected={"law_id": "law_one", "law_or_formula_hash": "1" * 64},
        child_hash="2" * 64,
        expected_trust_manifest_sha256=sha256_file(trust_path),
    )
    assert loaded["issuer"]["kind"] == "external_human"
    assert loaded_path == receipt_path

    try:
        module.load_and_validate_external_approval(
            root=tmp_path,
            report_id="PARENT",
            run_id="parent_run_001",
            receipt_path_raw=receipt_path.relative_to(tmp_path).as_posix(),
            synthesis_path=paths["synthesis"],
            selected={"law_id": "law_one", "law_or_formula_hash": "1" * 64},
            child_hash="2" * 64,
            expected_trust_manifest_sha256="0" * 64,
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("mismatched trust-manifest pin was accepted")


def test_ultimate_loop_contains_no_automatic_human_approval_bridge() -> None:
    source = (REPO_ROOT / "scripts/run_factorforge_ultimate_loop.py").read_text(
        encoding="utf-8"
    )
    assert "def synthesis_approval_command" not in source
    assert "def multibranch_synthesis_approval_command" not in source
    assert '"--approval-source",\n        "ultimate_loop_auto_bridge"' not in source
    assert (
        '"--approval-source",\n        "ultimate_loop_auto_multibranch_bridge"'
        not in source
    )
    assert "WAITING_EXTERNAL_HUMAN_APPROVAL" in source


def test_multibranch_auto_issuer_is_rejected_before_any_write(tmp_path: Path) -> None:
    module = _load_multibranch_approval_script()
    try:
        module.approve(
            tmp_path,
            "PARENT",
            loop_index=1,
            approval_source="ultimate_loop_auto_multibranch_bridge",
        )
    except ValueError as exc:
        assert module.TOKEN_EXTERNAL_HUMAN_REQUIRED in str(exc)
    else:
        raise AssertionError("multibranch automatic approval issuer was accepted")
    assert not list(tmp_path.rglob("*.json"))


def test_evo_multibranch_cannot_resume_from_legacy_manual_approval(
    tmp_path: Path,
) -> None:
    loop = _load_ultimate_loop()
    report_id = "PARENT"
    council = (
        tmp_path / "objects/research_iteration_master/revision_council" / report_id
    )
    synthesis_path = council / f"main_agent_multibranch_synthesis__{report_id}.json"
    _write_json(synthesis_path, {"report_id": report_id})
    _write_json(
        council / f"main_agent_multibranch_synthesis_approval__{report_id}.json",
        {
            "contract_version": "factorforge_main_agent_multibranch_synthesis_approval_v1",
            "parent_report_id": report_id,
            "source_multibranch_synthesis_sha256": sha256_file(synthesis_path),
            "approval_source": "manual_main_agent",
            "human_approval_required": True,
            "execution_allowed_by_default": False,
            "selected_branch_count": 1,
            "selected_branches": [{"child_report_id": "CHILD"}],
        },
    )
    _write_json(
        tmp_path / f"objects/research_protocol/research_conjecture__{report_id}.json",
        {"epistemic_evolution": {"enabled": True}},
    )
    assert loop.multibranch_manual_approval_ready(tmp_path, report_id) is False


def test_receipt_replay_after_synthesis_or_delta_mutation_fails(tmp_path: Path) -> None:
    receipt, trust, paths = _human_fixture(tmp_path)
    _write_json(paths["synthesis"], {"selected": "mutated"})
    _write_json(paths["delta"], {"minimal_extension": {"delta_id": "delta_two"}})
    reasons = _validate_human(tmp_path, receipt, trust, paths)
    assert f"{BLOCK_HUMAN_APPROVAL}:synthesis_sha256" in reasons
    assert f"{BLOCK_HUMAN_APPROVAL}:mechanism_delta_sha256" in reasons
    assert f"{BLOCK_HUMAN_APPROVAL}:delta_binding" in reasons


def test_receipt_replay_after_oos_registry_truncation_fails(tmp_path: Path) -> None:
    receipt, trust, paths = _human_fixture(tmp_path)
    registry_path = (
        tmp_path / receipt["child_intent"]["oos_registry_prefix_ref"]["path"]
    )
    _write_json(registry_path, {"events": []})
    reasons = _validate_human(tmp_path, receipt, trust, paths)
    assert any("child_oos_registry_prefix" in reason for reason in reasons)


def _allocation(root: Path, report_id: str = "CHILD") -> dict:
    unsigned = {
        "contract_version": OOS_ALLOCATION_VERSION,
        "allocation_id": "allocation_child_001",
        "report_id": report_id,
        "parent_report_id": "PARENT",
        "lineage_root_report_id": "PARENT",
        "dataset_snapshot_sha256": "a" * 64,
        "oos_window": {"start": "2026-01-01", "end": "2026-03-31"},
        "sealed_token_sha256": "b" * 64,
        "release_state": "SEALED_UNRELEASED",
        "consumed": False,
        "host_authority": OOS_HOST_AUTHORITY,
        "allocation_authority_mode": "LEGACY_TEST_ONLY_DIRECT_HASH_INPUT",
    }
    return {**unsigned, "content_sha256": oos_hash(unsigned)}


def _registry(root: Path, allocation: dict) -> dict:
    trust_root = _oos_trust_root(root)
    ensure_runtime_trust_store(trust_root, installation_id="test-oos-host")
    source = root / "identity" / "allocation_authority_source.json"
    _write_json(source, {"source": "test_fixture"})
    build_authority = {
        "contract_version": OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
        "allocation_id": allocation["allocation_id"],
        "report_id": allocation["report_id"],
        "parent_report_id": allocation["parent_report_id"],
        "selected_revision": {
            "child_formula": "close",
            "child_formula_hash": "d" * 64,
        },
        "authority_refs": {
            "test_source": {
                "path": source.relative_to(root).as_posix(),
                "sha256": sha256_file(source),
            }
        },
        "calendar_authority": {
            "snapshot_id": "test-calendar",
            "open_dates_sha256": "1" * 64,
            "raw_file_sha256": "2" * 64,
            "registry_sha256": "3" * 64,
            "registry_git_commit": "test-commit",
            "registry_git_blob": "test-blob",
        },
        "universe_binding": {
            "universe_id": "test-universe",
            "investability_mask_id": "test-mask",
        },
        "oos_window": allocation["oos_window"],
        "sealed_token_sha256": allocation["sealed_token_sha256"],
        "sealed_carrier_sha256": "c" * 64,
        "dataset_snapshot_sha256": allocation["dataset_snapshot_sha256"],
        "projection_row_count": 1,
        "projection_period_count": 60,
    }
    _allocate_fresh_child_oos(
        workspace_root=root,
        allocation_id=allocation["allocation_id"],
        report_id=allocation["report_id"],
        parent_report_id=allocation["parent_report_id"],
        lineage_root_report_id=allocation["lineage_root_report_id"],
        dataset_snapshot_sha256=allocation["dataset_snapshot_sha256"],
        oos_start=allocation["oos_window"]["start"],
        oos_end=allocation["oos_window"]["end"],
        sealed_token_sha256=allocation["sealed_token_sha256"],
        sealed_carrier_sha256="c" * 64,
        build_authority_sha256=oos_hash(build_authority),
        build_authority=build_authority,
        allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_SECURE,
        expected_registry_sha256=None,
        trust_root=trust_root,
        installation_id="test-oos-host",
    )
    return json.loads(oos_registry_path(root).read_text(encoding="utf-8"))


def _oos_trust_root(root: Path) -> Path:
    return root.parent / f".{root.name}-oos-host-trust"


def test_fresh_oos_registry_accepts_one_unconsumed_disjoint_allocation(
    tmp_path: Path,
) -> None:
    allocation = _allocation(tmp_path)
    registry = _registry(tmp_path, allocation)
    assert validate_oos_registry(registry, workspace_root=tmp_path) == []
    assert (
        validate_fresh_child_oos_allocation(
            root=tmp_path,
            parent_report_id="PARENT",
            child_report_id="CHILD",
            allocation_id="allocation_child_001",
            allocation_ref=oos_allocation_path(tmp_path, "CHILD")
            .relative_to(tmp_path)
            .as_posix(),
            incident_trust_root=_oos_trust_root(tmp_path),
            incident_installation_id="test-oos-host",
        )
        == []
    )


def test_fresh_oos_current_validator_requires_host_incident_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allocation = _allocation(tmp_path)
    _registry(tmp_path, allocation)
    for name in (
        "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT",
        "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID",
        "FACTORFORGE_OOS_HOST_TRUST_ROOT",
        "FACTORFORGE_OOS_HOST_INSTALLATION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    reasons = validate_fresh_child_oos_allocation(
        root=tmp_path,
        parent_report_id="PARENT",
        child_report_id="CHILD",
        allocation_id="allocation_child_001",
        allocation_ref=oos_allocation_path(tmp_path, "CHILD")
        .relative_to(tmp_path)
        .as_posix(),
    )
    assert any("incident_host_context_required" in reason for reason in reasons)


def test_parent_released_same_dataset_window_blocks_child(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    registry = _registry(tmp_path, allocation)
    _write_json(
        tmp_path / "objects/research_protocol/oos_release_manifest__PARENT.json",
        {
            "release_status": "RELEASED",
            "report_id": "PARENT",
            "dataset_snapshot_hash": allocation["dataset_snapshot_sha256"],
            "oos_window": copy.deepcopy(allocation["oos_window"]),
            "oos_release_token_hash": "c" * 64,
        },
    )
    reasons = validate_fresh_child_oos_allocation(
        root=tmp_path,
        parent_report_id="PARENT",
        child_report_id="CHILD",
        allocation_id="allocation_child_001",
        allocation_ref=oos_allocation_path(tmp_path, "CHILD")
        .relative_to(tmp_path)
        .as_posix(),
        incident_trust_root=_oos_trust_root(tmp_path),
        incident_installation_id="test-oos-host",
    )
    assert (
        f"{BLOCK_OOS_ALLOCATION}:ancestor_or_sibling_dataset_window_reused" in reasons
    )


def test_registry_hash_chain_mutation_fails_closed(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    registry = _registry(tmp_path, allocation)
    registry["events"][0]["sealed_token_sha256"] = "d" * 64
    reasons = validate_oos_registry(registry, workspace_root=tmp_path)
    assert any(reason.endswith(":hash") for reason in reasons)
    assert f"{BLOCK_OOS_ALLOCATION}:registry_hash" in reasons


def test_consumed_allocation_cannot_start_child_step3b(tmp_path: Path) -> None:
    allocation = _allocation(tmp_path)
    _registry(tmp_path, allocation)
    evidence_path = (
        tmp_path / "objects/research_protocol/oos_release_manifest__CHILD.json"
    )
    ledger_path = tmp_path / "objects/research_protocol/search_trial_ledger__CHILD.json"
    threshold_path = (
        tmp_path / "objects/research_protocol/threshold_registration__CHILD.json"
    )
    _write_json(ledger_path, {"report_id": "CHILD", "status": "FROZEN"})
    _write_json(threshold_path, {"report_id": "CHILD", "status": "LOCKED"})
    release = {
        "version": "factorforge_oos_release_manifest_v1",
        "release_status": "RELEASED",
        "report_id": "CHILD",
        "factor_id": "FACTOR_A",
        "release_sequence": 30,
        "search_trial_ledger_ref": ledger_path.relative_to(tmp_path).as_posix(),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "threshold_registration_ref": threshold_path.relative_to(tmp_path).as_posix(),
        "threshold_registration_sha256": sha256_file(threshold_path),
        "dataset_snapshot_hash": allocation["dataset_snapshot_sha256"],
        "window_hash": "c" * 64,
        "evaluation_contract_hash": "d" * 64,
        "oos_window": "2026-01-01/2026-03-31",
        "observed_start_date": "2026-01-01",
        "observed_end_date": "2026-03-31",
        "observed_period_count": 60,
        "oos_release_token_hash": allocation["sealed_token_sha256"],
    }
    release["release_manifest_sha256"] = oos_hash(release)
    _write_json(evidence_path, release)
    consume_oos_allocation_for_release(
        workspace_root=tmp_path,
        report_id="CHILD",
        release_manifest_path=evidence_path,
        incident_trust_root=_oos_trust_root(tmp_path),
        incident_installation_id="test-oos-host",
    )
    registry = json.loads(oos_registry_path(tmp_path).read_text(encoding="utf-8"))
    assert validate_oos_registry(registry, workspace_root=tmp_path) == []
    reasons = validate_fresh_child_oos_allocation(
        root=tmp_path,
        parent_report_id="PARENT",
        child_report_id="CHILD",
        allocation_id="allocation_child_001",
        allocation_ref=oos_allocation_path(tmp_path, "CHILD")
        .relative_to(tmp_path)
        .as_posix(),
        incident_trust_root=_oos_trust_root(tmp_path),
        incident_installation_id="test-oos-host",
    )
    assert f"{BLOCK_OOS_ALLOCATION}:allocation_not_available" in reasons
