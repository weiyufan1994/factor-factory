from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.epistemic_ultimate_shadow import (
    AUTHORITY_EFFECT,
    DIAGNOSIS_INPUT_PARENT_NAME,
    EpistemicUltimateShadowError,
    HOOK_FAILURE,
    HOOK_STEP1,
    ISOLATION_POLICY,
    REQUEST_PARENT_NAME,
    REQUEST_SCHEMA_ID,
    capture_failure_artifact_snapshot,
    run_ultimate_epistemic_shadow,
    validate_native_factor_workspace,
    validate_ultimate_epistemic_shadow_package,
)
from factor_factory.research_workspace import (
    build_workspace_manifest,
    default_workspace_root,
    workspace_manifest_path,
    write_workspace_manifest,
)
from scripts import run_factorforge_ultimate as ultimate
from scripts import build_factorforge_epistemic_shadow_request as request_builder


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = (
    REPO_ROOT / "examples" / "factorforge_epistemic_kernel_wavelet_demo_input.json"
)
DIAGNOSIS_SOURCES = (
    REPO_ROOT / "tests" / "fixtures" / "epistemic_shadow" / "stage2_manifest.json",
    REPO_ROOT / "tests" / "fixtures" / "epistemic_shadow" / "diagnosis_fixture.json",
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "epistemic_shadow"
    / "assertion_dependency_dag.json",
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path


def _reseal_shadow_receipt(path: Path, payload: dict) -> None:
    import factor_factory.epistemic_ultimate_shadow as module

    core = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = module.framed_sha256(module.RESULT_DOMAIN, core)
    _write_json(path, payload)


def _kernel_input(*, real_retrieval: bool = False) -> dict:
    payload = json.loads(EXAMPLE_INPUT.read_text(encoding="utf-8"))
    payload["diagnosis_inputs"] = None
    if not real_retrieval:
        payload["retrieval_corpus_objects"] = None
        payload["real_knowledge_inputs"] = None
        payload["session_scope_secret_hex"] = None
    else:
        # The checked-in example is historical; a replay must use this
        # checkout's public graph, not the example author's absolute path.
        root = REPO_ROOT / "knowledge" / "因子工厂"
        payload["real_knowledge_inputs"].update({
            "node_index_path": str(root / "graph/factor_knowledge_nodes.jsonl"),
            "edge_index_path": str(root / "graph/factor_knowledge_edges.jsonl"),
            "taxonomy_path": str(root / "taxonomy/factor_taxonomy_v1.json"),
        })
    return payload


def _request(report_id: str, *, real_retrieval: bool = False) -> dict:
    return {
        "schema_id": REQUEST_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": report_id,
        "hook": HOOK_STEP1,
        "kernel_input_candidate": _kernel_input(real_retrieval=real_retrieval),
        "derivation_ledger": [
            {
                "ordinal": ordinal,
                "target_pointer": f"/kernel_input_candidate/{name}",
                "derivation_class": "CALLER_SUPPLIED_PRE_RETRIEVAL_CANDIDATE",
                "source_artifact_role": None,
                "source_pointer": None,
                "source_value_sha256": None,
            }
            for ordinal, name in enumerate(
                (
                    "source_text",
                    "source_lineage",
                    "author_claims",
                    "analyst_notes",
                    "selected_semantic_body",
                    "formalization_provenance",
                    "pre_a0_predictions",
                    "phase_policy_candidate",
                )
            )
        ],
        "diagnosis_target_scope": None,
        "isolation_policy": dict(ISOLATION_POLICY),
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }


def _native_workspace(tmp_path: Path, report_id: str) -> Path:
    factorforge_root = tmp_path / "factorforge-root"
    factorforge_root.mkdir(parents=True, exist_ok=True)
    workspace = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id="factor-shadow-test",
        research_id="research-shadow-test",
    ).resolve()
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id="factor-shadow-test",
        research_id="research-shadow-test",
        root_report_id=report_id,
    )
    write_workspace_manifest(workspace_manifest_path(workspace), manifest)
    return workspace


def _workspace(tmp_path: Path, report_id: str) -> tuple[Path, Path, Path]:
    workspace = _native_workspace(tmp_path, report_id)
    alpha = _write_json(
        workspace
        / "objects"
        / "alpha_idea_master"
        / f"alpha_idea_master__{report_id}.json",
        {
            "contract_version": "factorforge.step1.alpha_idea_master.v2",
            "report_id": report_id,
            "factor_id": "factor-shadow-test",
            "producer": "step12_hypothesis_intake",
            "source_type": "natural_language_hypothesis",
            "artifact_identity": {"report_id": report_id},
            "final_factor": {
                "economic_logic": "约束持有者支付流动性冲击成本。"
            },
        },
    )
    manifest = _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / f"factorforge_runtime_manifest__{report_id}.json",
        {
            "contract_version": "factorforge_runtime_context_v2",
            "report_id": report_id,
            "factor_id": "factor-shadow-test",
            "research_id": "research-shadow-test",
            "factor_workspace": str(workspace.resolve()),
            "repo_root": str(REPO_ROOT.resolve()),
            "objects": {"alpha_idea_master": str(alpha.resolve())},
        },
    )
    request = _write_json(
        workspace / REQUEST_PARENT_NAME / "step1-shadow-request.json",
        _request(report_id),
    )
    return workspace.resolve(), manifest.resolve(), request.resolve()


def _identity(
    report_id: str, *, role: str, producer: str, factor_id: str = "factor-shadow-test"
) -> dict:
    return {
        "report_id": report_id,
        "factor_id": factor_id,
        "source_type": "natural_language_hypothesis",
        "implementation_mode": "operator",
        "contract_version": "factorforge_step2_source_contract_v2",
        "producer": producer,
        "upstream_producer": "step12_hypothesis_intake",
        "formula_hash": "a" * 64,
        "code_hash": "b" * 64,
        "code_contract_hash": None,
        "custom_block_hash": None,
        "hybrid_hash": None,
        "spec_hash": "c" * 64,
        "branch_id": "main",
        "run_id": "run_001",
        "parent_run_id": None,
        "created_at_utc": "2026-08-31T00:00:00Z",
        "artifact_role": role,
    }


def _failure_workspace(
    tmp_path: Path, report_id: str
) -> tuple[Path, Path, Path, Path]:
    workspace, manifest_path, _ = _workspace(tmp_path, report_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    objects = manifest["objects"]
    specs = (
        (
            "factor_spec_master",
            workspace / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
            {
                "contract_version": "factorforge_step2_source_contract_v2",
                "report_id": report_id,
                "factor_id": "factor-shadow-test",
                "producer": "step12_hypothesis_intake",
                "source_type": "natural_language_hypothesis",
                "artifact_identity": _identity(
                    report_id,
                    role="factor_spec_master",
                    producer="step12_hypothesis_intake",
                ),
            },
        ),
        (
            "factor_run_master",
            workspace / "objects" / "factor_run_master" / f"factor_run_master__{report_id}.json",
            {
                "report_id": report_id,
                "factor_id": "factor-shadow-test",
                "producer": "step4",
                "artifact_identity": _identity(
                    report_id, role="factor_run_master", producer="step4"
                ),
            },
        ),
        (
            "factor_evaluation",
            workspace / "objects" / "validation" / f"factor_evaluation__{report_id}.json",
            {
                "report_id": report_id,
                "factor_id": "factor-shadow-test",
                "artifact_identity": _identity(
                    report_id, role="factor_evaluation", producer="step5"
                ),
            },
        ),
        (
            "factor_case_master",
            workspace / "objects" / "factor_case_master" / f"factor_case_master__{report_id}.json",
            {
                "report_id": report_id,
                "factor_id": "factor-shadow-test",
                "created_by_step": "step5",
                "artifact_identity": _identity(
                    report_id, role="factor_case_master", producer="step5"
                ),
            },
        ),
        (
            "handoff_to_step6",
            workspace / "objects" / "handoff" / f"handoff_to_step6__{report_id}.json",
            {
                "report_id": report_id,
                "factor_id": "factor-shadow-test",
                "created_by_step": "step5",
                "artifact_identity": _identity(
                    report_id, role="handoff_to_step6", producer="step5"
                ),
            },
        ),
    )
    for key, path, payload in specs:
        objects[key] = str(_write_json(path, payload).resolve())
    _write_json(manifest_path, manifest)

    diagnosis_root = workspace / DIAGNOSIS_INPUT_PARENT_NAME
    diagnosis_root.mkdir(parents=True)
    copied = []
    for ordinal, source in enumerate(DIAGNOSIS_SOURCES):
        target = diagnosis_root / f"input-{ordinal}.json"
        target.write_bytes(source.read_bytes())
        copied.append(target.resolve())
    kernel = _kernel_input()
    kernel["diagnosis_inputs"] = {
        "stage2_manifest_path": str(copied[0]),
        "fixture_json_path": str(copied[1]),
        "assertion_dependency_json_path": str(copied[2]),
    }
    request_payload = _request(report_id)
    request_payload["hook"] = HOOK_FAILURE
    request_payload["kernel_input_candidate"] = kernel
    request_payload["diagnosis_target_scope"] = {
        "target_report_id": report_id,
        "target_factor_id": "factor-shadow-test",
        "linkage_status": (
            "CALLER_CLAIMED_CURRENT_FACTOR_TARGET__NOT_INDEPENDENTLY_VERIFIED"
        ),
    }
    request = _write_json(
        workspace / REQUEST_PARENT_NAME / "failure-shadow-request.json",
        request_payload,
    )
    proof = _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json",
        {
            "contract_version": "factorforge_ultimate_wrapper_v1",
            "report_id": report_id,
            "factor_id": "factor-shadow-test",
            "research_id": "research-shadow-test",
            "factor_workspace": str(workspace),
            "active_root": str(workspace),
            "manifest_path": str(manifest_path),
            "start_step": "5",
            "end_step": "5",
            "requested_steps": ["5"],
            "dry_run": False,
            "status": "PASS",
            "failure": None,
            "formal_proof_eligible": True,
            "current_formal_authority_verified": True,
            "proof_semantics": "formal_execution_proof",
            "formal_command_contract": {
                "required_command_names": ["run_step5", "validate_step5"],
                "executed_command_names": ["run_step5", "validate_step5"],
                "satisfied": True,
            },
            "commands": [
                {"name": "run_step5", "status": "PASS", "returncode": 0},
                {"name": "validate_step5", "status": "PASS", "returncode": 0},
            ],
            "web_research_preflight": None,
            "evo_v2_execution_gate": None,
            "web_resume_start_step": None,
            "evo_child_command_recovery": None,
            "web_oos_recovery": {
                "recovery_required": False,
                "allowed_execution": "NORMAL",
                "artifact_refs": [],
                "finalization_receipt_present": False,
            },
            "evo_child_agent_execution_container": {
                "required": False,
                "status": "NOT_APPLICABLE",
            },
        },
    )
    return workspace, manifest_path, request.resolve(), proof.resolve()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure_snapshot(manifest: Path, report_id: str) -> dict:
    return capture_failure_artifact_snapshot(
        manifest_path=manifest,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )


def test_shadow_builds_exact3_idempotently_without_mutating_official_artifact(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_SOURCE_FIRST_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    alpha = next((workspace / "objects" / "alpha_idea_master").iterdir())
    before = (alpha.stat().st_ino, alpha.stat().st_mtime_ns, _sha(alpha))

    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )
    replay = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )

    assert replay == receipt
    assert sorted(path.name for path in receipt.parent.iterdir()) == [
        "00_kernel_candidate.json",
        "01_chief_advisory.json",
        "02_shadow_receipt.json",
    ]
    result = json.loads(receipt.read_text(encoding="utf-8"))
    assert result["artifact_status"] == (
        "SHADOW_OBSERVATION_COMPLETE__NO_AUTHORITY_EFFECT"
    )
    assert result["authority_effect"] == "NONE"
    assert result["candidate_only"] is True
    assert result["consumer_policy"]["forbidden_consumers"] == [
        "STEP2",
        "STEP3",
        "STEP4",
        "STEP5",
        "STEP6",
    ]
    assert all(value is False for value in result["execution_boundary"].values())
    assert result["formal_pipeline_effect"] == {
        "factor_verdict_contributor": False,
        "formal_command_contract_changed": False,
        "formal_proof_eligibility_contributor": False,
        "operating_contract_delta_activated": False,
    }
    assert before == (alpha.stat().st_ino, alpha.stat().st_mtime_ns, _sha(alpha))


def test_new_package_fsyncs_parent_and_replays_final_exact3_after_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_FINAL_REPLAY_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    import factor_factory.epistemic_ultimate_shadow as module

    renamed = False
    fsync_after_rename: list[tuple[int, int]] = []
    reads_after_rename: list[str] = []
    original_rename = module.os.rename
    original_fsync = module.os.fsync
    original_read_at = module._read_at

    def rename_spy(*args, **kwargs):
        nonlocal renamed
        result = original_rename(*args, **kwargs)
        renamed = True
        return result

    def fsync_spy(descriptor: int) -> None:
        if renamed:
            metadata = os.fstat(descriptor)
            fsync_after_rename.append((metadata.st_dev, metadata.st_ino))
        original_fsync(descriptor)

    def read_spy(directory_fd: int, name: str) -> bytes:
        assert renamed
        reads_after_rename.append(name)
        return original_read_at(directory_fd, name)

    monkeypatch.setattr(module.os, "rename", rename_spy)
    monkeypatch.setattr(module.os, "fsync", fsync_spy)
    monkeypatch.setattr(module, "_read_at", read_spy)

    receipt = module.run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )

    output_parent = receipt.parent.parent
    parent_metadata = output_parent.stat()
    assert (parent_metadata.st_dev, parent_metadata.st_ino) in fsync_after_rename
    assert reads_after_rename[:3] == [
        "00_kernel_candidate.json",
        "01_chief_advisory.json",
        "02_shadow_receipt.json",
    ]


def test_publisher_rejects_final_entry_swap_during_closure_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_FINAL_ENTRY_SWAP_001"
    workspace = _native_workspace(tmp_path, report_id)
    import factor_factory.epistemic_ultimate_shadow as module

    _, workspace_binding, _ = module.validate_native_factor_workspace(
        workspace=workspace,
        repo_root=REPO_ROOT,
    )
    run_id = "shadow_final_entry_swap_test"
    payloads = {
        "00_kernel_candidate.json": b'{"candidate":true}\n',
        "01_chief_advisory.json": b'{"advisory":true}\n',
        "02_shadow_receipt.json": b'{"receipt":true}\n',
    }
    swapped = False
    original_read_at = module._read_at

    def swap_then_read(directory_fd: int, name: str) -> bytes:
        nonlocal swapped
        if not swapped:
            final = workspace / module.OUTPUT_PARENT_NAME / run_id
            detached = final.with_name("detached_original")
            final.rename(detached)
            final.mkdir(mode=0o700)
            for artifact_name, artifact_bytes in payloads.items():
                (final / artifact_name).write_bytes(artifact_bytes)
            swapped = True
        return original_read_at(directory_fd, name)

    monkeypatch.setattr(module, "_read_at", swap_then_read)

    with pytest.raises(
        EpistemicUltimateShadowError,
        match="final_entry_identity_mismatch|final_entry_replaced_during_replay",
    ):
        module._publish_package(
            workspace=workspace,
            run_id=run_id,
            payloads=payloads,
            before_receipt=lambda: None,
            after_receipt=lambda: None,
            expected_workspace_device=workspace_binding["workspace_device"],
            expected_workspace_inode=workspace_binding["workspace_inode"],
        )

    assert swapped is True


def test_shadow_package_validator_rejects_hardlinked_output(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_OUTPUT_HARDLINK_001"
    _, manifest, request = _workspace(tmp_path, report_id)
    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )
    os.link(
        receipt.parent / "00_kernel_candidate.json",
        tmp_path / "external-shadow-output-link.json",
    )
    with pytest.raises(
        EpistemicUltimateShadowError,
        match="package_artifact_physical_identity",
    ):
        validate_ultimate_epistemic_shadow_package(receipt)


@pytest.mark.parametrize("path_form", ["parent_traversal", "absolute"])
def test_shadow_package_validator_never_follows_receipt_path_outside_workspace(
    tmp_path: Path, path_form: str
) -> None:
    report_id = f"RPT_SHADOW_RECEIPT_TRAVERSAL_{path_form.upper()}_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )
    outside = _write_json(workspace.parent / "protected.json", {"protected": True})
    metadata = outside.stat()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["request_binding"] = {
        "relative_path": (
            "../protected.json"
            if path_form == "parent_traversal"
            else str(outside.resolve())
        ),
        "bytes": metadata.st_size,
        "raw_sha256": _sha(outside),
        "device": str(metadata.st_dev),
        "inode": str(metadata.st_ino),
        "mtime_ns": str(metadata.st_mtime_ns),
        "link_count": metadata.st_nlink,
    }
    _reseal_shadow_receipt(receipt, payload)

    with pytest.raises(
        EpistemicUltimateShadowError,
        match="absolute_binding_forbidden|noncanonical_relative_path",
    ):
        validate_ultimate_epistemic_shadow_package(receipt)


def test_shadow_package_validator_requires_official_canonical_role_path(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_RECEIPT_ROLE_PATH_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )
    alternate = _write_json(
        workspace / "objects" / "alpha_idea_master" / "alternate.json",
        {"candidate": True},
    )
    metadata = alternate.stat()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    binding = payload["official_artifact_bindings"][0]
    binding.update(
        {
            "relative_path": str(alternate.relative_to(workspace)),
            "bytes": metadata.st_size,
            "raw_sha256": _sha(alternate),
            "device": str(metadata.st_dev),
            "inode": str(metadata.st_ino),
            "mtime_ns": str(metadata.st_mtime_ns),
            "link_count": metadata.st_nlink,
        }
    )
    import factor_factory.epistemic_ultimate_shadow as module

    payload["official_artifact_binding_commitment"] = module.framed_sha256(
        module.ARTIFACT_BINDING_DOMAIN,
        payload["official_artifact_bindings"],
    )
    _reseal_shadow_receipt(receipt, payload)

    with pytest.raises(
        EpistemicUltimateShadowError,
        match="official_artifact_path_replay",
    ):
        validate_ultimate_epistemic_shadow_package(receipt)


def test_request_builder_creates_closed_candidate_request(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_REQUEST_BUILDER_001"
    workspace = _native_workspace(tmp_path, report_id)
    input_path = _write_json(
        workspace / "candidate_epistemic_shadow_inputs" / "kernel-input.json",
        _kernel_input(),
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_factorforge_epistemic_shadow_request.py"),
            "--factor-workspace",
            str(workspace.resolve()),
            "--report-id",
            report_id,
            "--kernel-input",
            str(input_path.resolve()),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    request_path = Path(completed.stdout.strip())
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["schema_id"] == REQUEST_SCHEMA_ID
    assert payload["hook"] == HOOK_STEP1
    assert len(payload["derivation_ledger"]) == 8
    assert payload["authority_effect"] == "NONE"

    replay = subprocess.run(completed.args, cwd=REPO_ROOT, text=True, capture_output=True)
    assert replay.returncode == 0, replay.stderr
    assert replay.stdout.strip() == completed.stdout.strip()


def test_native_workspace_rejects_symlinked_manifest(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_WORKSPACE_MANIFEST_SYMLINK_001"
    workspace = _native_workspace(tmp_path, report_id)
    manifest = workspace_manifest_path(workspace)
    external = tmp_path / "external-workspace-manifest.json"
    manifest.replace(external)
    manifest.symlink_to(external)
    with pytest.raises(
        EpistemicUltimateShadowError,
        match="direct_nonsymlink_child_required",
    ):
        validate_native_factor_workspace(workspace=workspace, repo_root=REPO_ROOT)


def test_native_workspace_rejects_protected_factorforge_root(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_PROTECTED_ROOT_001"
    factorforge_root = tmp_path / "oos" / "factorforge"
    factorforge_root.mkdir(parents=True)
    workspace = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id="factor-shadow-test",
        research_id="research-shadow-test",
    ).resolve()
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id="factor-shadow-test",
        research_id="research-shadow-test",
        root_report_id=report_id,
    )
    write_workspace_manifest(workspace_manifest_path(workspace), manifest)
    with pytest.raises(
        EpistemicUltimateShadowError,
        match="protected_factorforge_root_forbidden",
    ):
        validate_native_factor_workspace(workspace=workspace, repo_root=REPO_ROOT)


def test_request_builder_rejects_hardlinked_kernel_input(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_REQUEST_HARDLINK_001"
    workspace = _native_workspace(tmp_path, report_id)
    input_path = _write_json(
        workspace / "candidate_epistemic_shadow_inputs" / "kernel-input.json",
        _kernel_input(),
    )
    os.link(input_path, tmp_path / "external-kernel-input-link.json")
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_factorforge_epistemic_shadow_request.py"),
            "--factor-workspace",
            str(workspace.resolve()),
            "--report-id",
            report_id,
            "--kernel-input",
            str(input_path.resolve()),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "kernel_input:hardlink_forbidden" in completed.stderr


def test_request_builder_blocks_symlink_swap_before_fd_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_REQUEST_SWAP_001"
    workspace = _native_workspace(tmp_path, report_id)
    input_path = _write_json(
        workspace / "candidate_epistemic_shadow_inputs" / "kernel-input.json",
        _kernel_input(),
    )
    external_payload = _kernel_input()
    external_payload["source_text"] = "EXTERNAL_BYTES_MUST_NOT_BE_READ"
    external = _write_json(tmp_path / "external-kernel-input.json", external_payload)
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == input_path.name and dir_fd is not None and not swapped:
            swapped = True
            input_path.unlink()
            input_path.symlink_to(external)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(request_builder.os, "open", swap_then_open)
    with pytest.raises(OSError):
        request_builder._read_input(input_path.resolve(strict=False), workspace)
    assert swapped is True


def test_request_builder_rejects_mounted_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_REQUEST_OUTPUT_MOUNT_001"
    workspace = _native_workspace(tmp_path, report_id)
    _, binding, _ = validate_native_factor_workspace(
        workspace=workspace, repo_root=REPO_ROOT
    )
    original_ismount = os.path.ismount

    def mounted(path):
        return Path(path) == workspace / REQUEST_PARENT_NAME or original_ismount(path)

    monkeypatch.setattr(request_builder.os.path, "ismount", mounted)
    with pytest.raises(ValueError, match="output:parent_mount_forbidden"):
        request_builder._publish(
            workspace,
            "shadow_request_" + "a" * 32 + ".json",
            b"{}\n",
            expected_workspace_device=binding["workspace_device"],
            expected_workspace_inode=binding["workspace_inode"],
        )


def test_request_builder_rejects_mounted_diagnosis_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_DIAGNOSIS_MOUNT_001"
    workspace = _native_workspace(tmp_path, report_id)
    diagnosis_root = workspace / DIAGNOSIS_INPUT_PARENT_NAME
    diagnosis_root.mkdir()
    copied = []
    for ordinal, source in enumerate(DIAGNOSIS_SOURCES):
        target = diagnosis_root / f"input-{ordinal}.json"
        target.write_bytes(source.read_bytes())
        copied.append(target.resolve())
    kernel = _kernel_input()
    kernel["diagnosis_inputs"] = {
        "stage2_manifest_path": str(copied[0]),
        "fixture_json_path": str(copied[1]),
        "assertion_dependency_json_path": str(copied[2]),
    }
    input_path = _write_json(
        workspace / "candidate_epistemic_shadow_inputs" / "failure.json", kernel
    )
    original_ismount = os.path.ismount

    def mounted(path):
        return Path(path) == diagnosis_root or original_ismount(path)

    monkeypatch.setattr(request_builder.os.path, "ismount", mounted)
    rc = request_builder.main(
        [
            "--factor-workspace",
            str(workspace),
            "--report-id",
            report_id,
            "--kernel-input",
            str(input_path),
            "--hook",
            HOOK_FAILURE,
            "--diagnosis-target-factor-id",
            "factor-shadow-test",
        ]
    )
    assert rc == 2


def test_request_builder_hashes_diagnosis_target_and_rejects_external_inputs(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_REQUEST_BUILDER_FAILURE_001"
    workspace = _native_workspace(tmp_path, report_id)
    (workspace / DIAGNOSIS_INPUT_PARENT_NAME).mkdir()
    external = tmp_path / "external.json"
    external.write_text("{}\n", encoding="utf-8")
    kernel = _kernel_input()
    kernel["diagnosis_inputs"] = {
        "stage2_manifest_path": str(external.resolve()),
        "fixture_json_path": str(external.resolve()),
        "assertion_dependency_json_path": str(external.resolve()),
    }
    input_path = _write_json(
        workspace / "candidate_epistemic_shadow_inputs" / "failure.json", kernel
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_factorforge_epistemic_shadow_request.py"),
        "--factor-workspace",
        str(workspace.resolve()),
        "--report-id",
        report_id,
        "--kernel-input",
        str(input_path.resolve()),
        "--hook",
        HOOK_FAILURE,
        "--diagnosis-target-factor-id",
        "factor-a",
    ]
    blocked = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    assert blocked.returncode == 2
    assert "outside_dedicated_diagnosis_root" in blocked.stderr

    diagnosis_root = workspace / DIAGNOSIS_INPUT_PARENT_NAME
    safe_paths = []
    for ordinal, source in enumerate(DIAGNOSIS_SOURCES):
        target = diagnosis_root / f"safe-{ordinal}.json"
        target.write_bytes(source.read_bytes())
        safe_paths.append(target.resolve())
    kernel["diagnosis_inputs"] = {
        "stage2_manifest_path": str(safe_paths[0]),
        "fixture_json_path": str(safe_paths[1]),
        "assertion_dependency_json_path": str(safe_paths[2]),
    }
    _write_json(input_path, kernel)
    first = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    replay = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    second_target_command = [*command[:-1], "factor-b"]
    second_target = subprocess.run(
        second_target_command, cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert first.returncode == replay.returncode == second_target.returncode == 0
    assert first.stdout.strip() == replay.stdout.strip()
    assert first.stdout.strip() != second_target.stdout.strip()


def test_real_graph_shadow_does_not_persist_session_secret(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_REAL_GRAPH_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    payload = _request(report_id, real_retrieval=True)
    _write_json(request, payload)

    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        repo_root=REPO_ROOT,
    )

    persisted = b"\n".join(path.read_bytes() for path in receipt.parent.iterdir())
    secret_hex = payload["kernel_input_candidate"]["session_scope_secret_hex"]
    assert secret_hex.encode("ascii") not in persisted
    assert bytes.fromhex(secret_hex) not in persisted


@pytest.mark.parametrize(
    "mutation,match",
    [
        (
            lambda payload: payload.update({"authority_effect": "WRITE"}),
            "request:authority_effect",
        ),
        (
            lambda payload: payload["kernel_input_candidate"].update(
                {"retrieval_corpus_objects": []}
            ),
            "synthetic_corpus_forbidden",
        ),
        (
            lambda payload: payload["derivation_ledger"][0].update(
                {"derivation_class": "DIRECT_COPY"}
            ),
            "direct_copy_requires_source",
        ),
        (
            lambda payload: payload["kernel_input_candidate"].update(
                {"diagnosis_inputs": {}}
            ),
            "diagnosis_forbidden",
        ),
    ],
)
def test_shadow_request_fails_closed(
    tmp_path: Path, mutation, match: str
) -> None:
    report_id = "RPT_SHADOW_NEGATIVE_001"
    _, manifest, request = _workspace(tmp_path, report_id)
    payload = _request(report_id)
    mutation(payload)
    _write_json(request, payload)
    with pytest.raises(EpistemicUltimateShadowError, match=match):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )


def test_request_must_live_in_dedicated_workspace_candidate_root(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_PATH_001"
    workspace, manifest, _ = _workspace(tmp_path, report_id)
    request = _write_json(workspace / "objects" / "bad-request.json", _request(report_id))
    with pytest.raises(EpistemicUltimateShadowError, match="outside_workspace"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )


def test_official_artifact_drift_during_build_blocks_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_DRIFT_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    alpha = next((workspace / "objects" / "alpha_idea_master").iterdir())
    import factor_factory.epistemic_ultimate_shadow as module

    original = module.build_candidate

    def mutate_then_build(payload):
        candidate = original(payload)
        alpha.write_bytes(alpha.read_bytes() + b" ")
        return candidate

    monkeypatch.setattr(module, "build_candidate", mutate_then_build)
    with pytest.raises(EpistemicUltimateShadowError, match="mutated_during_build"):
        module.run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )
    assert not (workspace / "candidate_epistemic_shadow").exists()


def test_official_artifact_hardlink_added_after_admission_blocks_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_POST_ADMISSION_HARDLINK_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    alpha = next((workspace / "objects" / "alpha_idea_master").iterdir())
    import factor_factory.epistemic_ultimate_shadow as module

    original = module.build_candidate

    def link_then_build(payload):
        candidate = original(payload)
        os.link(alpha, tmp_path / "late-alpha-hardlink.json")
        return candidate

    monkeypatch.setattr(module, "build_candidate", link_then_build)
    with pytest.raises(
        EpistemicUltimateShadowError,
        match="official_artifact_mutated_during_build",
    ):
        module.run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )
    assert not (workspace / "candidate_epistemic_shadow").exists()


def test_official_artifact_drift_before_receipt_removes_new_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_RECEIPT_DRIFT_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    import factor_factory.epistemic_ultimate_shadow as module

    calls = 0
    original = module._same_artifact_snapshot

    def pass_build_then_fail_receipt(**kwargs):
        nonlocal calls
        calls += 1
        assert original(**kwargs)
        return calls == 1

    monkeypatch.setattr(module, "_same_artifact_snapshot", pass_build_then_fail_receipt)
    with pytest.raises(EpistemicUltimateShadowError, match="mutated_before_receipt"):
        module.run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )
    output_parent = workspace / "candidate_epistemic_shadow"
    assert output_parent.is_dir()
    assert list(output_parent.iterdir()) == []


def test_manifest_drift_after_receipt_write_never_exposes_final_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_id = "RPT_SHADOW_MANIFEST_POST_RECEIPT_DRIFT_001"
    workspace, manifest, request = _workspace(tmp_path, report_id)
    import factor_factory.epistemic_ultimate_shadow as module

    original_write = module._write_once_at

    def write_then_drift(directory_fd, name, payload):
        original_write(directory_fd, name, payload)
        if name == "02_shadow_receipt.json":
            manifest.write_bytes(manifest.read_bytes() + b" ")

    monkeypatch.setattr(module, "_write_once_at", write_then_drift)
    with pytest.raises(EpistemicUltimateShadowError, match="runtime_manifest_mutated"):
        module.run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_STEP1,
            report_id=report_id,
            repo_root=REPO_ROOT,
        )
    output_parent = workspace / "candidate_epistemic_shadow"
    assert output_parent.is_dir()
    assert list(output_parent.iterdir()) == []


def test_ultimate_shadow_child_environment_strips_formal_and_host_state() -> None:
    env = ultimate.epistemic_shadow_child_env(
        {
            "PATH": "/bin",
            "LANG": "C.UTF-8",
            "FACTORFORGE_OOS_HOST_TRUST_ROOT": "/private/trust",
            "FACTORFORGE_ROOT": "/workspace",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "S3_TOKEN": "secret",
            "API_TOKEN": "secret",
        }
    )
    assert env["PATH"] == "/bin"
    assert env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert not any(key.startswith("FACTORFORGE_") for key in env)
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "S3_TOKEN" not in env
    assert "API_TOKEN" not in env


def test_ultimate_observer_runs_real_credential_free_child(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_CHILD_001"
    _, manifest, request = _workspace(tmp_path, report_id)
    result = ultimate.run_epistemic_shadow_observation(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_STEP1,
        report_id=report_id,
        dry_run=False,
    )
    assert result["status"] == "PASS_CANDIDATE_ONLY"
    assert result["formal_authority_effect"] == "NONE"
    receipt = Path(result["receipt_path"])
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["authority_effect"] == "NONE"


def test_observer_path_normalization_failure_is_total_and_nonblocking() -> None:
    result = ultimate.run_epistemic_shadow_observation(
        manifest_path="~factorforge_nonexistent_user/manifest.json",
        request_path="~factorforge_nonexistent_user/request.json",
        hook=HOOK_STEP1,
        report_id="RPT",
        dry_run=False,
    )
    assert result == {
        "status": "BLOCKED_NONBLOCKING_CHILD_ERROR",
        "hook": HOOK_STEP1,
        "formal_authority_effect": "NONE",
    }


def test_failure_shadow_requires_current_proof_and_candidate_root_exact3(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_FAILURE_001"
    workspace, manifest, request, proof = _failure_workspace(tmp_path, report_id)
    proof_sha = _sha(proof)
    receipt = run_ultimate_epistemic_shadow(
        manifest_path=manifest,
        request_path=request,
        hook=HOOK_FAILURE,
        report_id=report_id,
        repo_root=REPO_ROOT,
        formal_proof_path=proof,
        formal_proof_raw_sha256=proof_sha,
        formal_artifact_snapshot=_failure_snapshot(manifest, report_id),
    )
    result = validate_ultimate_epistemic_shadow_package(receipt)
    assert result["formal_proof_binding"]["raw_sha256"] == proof_sha
    assert len(result["diagnosis_input_bindings"]) == 3
    assert all(
        row["relative_path"].startswith(DIAGNOSIS_INPUT_PARENT_NAME + "/")
        for row in result["diagnosis_input_bindings"]
    )
    candidate = json.loads(
        (receipt.parent / "00_kernel_candidate.json").read_text(encoding="utf-8")
    )
    terminal = candidate["stage_outputs"]["diagnosis"]["agent_visible_projection"][
        "terminal"
    ]
    assert terminal["cause_identified"] is False
    assert terminal["qualification_allowed"] is False

    with pytest.raises(EpistemicUltimateShadowError, match="expected_hash_required"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_artifact_snapshot=_failure_snapshot(manifest, report_id),
        )


def test_failure_shadow_rejects_hardlinked_diagnosis_input(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_DIAGNOSIS_HARDLINK_001"
    workspace, manifest, request, proof = _failure_workspace(tmp_path, report_id)
    snapshot = _failure_snapshot(manifest, report_id)
    first_input = next((workspace / DIAGNOSIS_INPUT_PARENT_NAME).iterdir())
    os.link(first_input, tmp_path / "external-diagnosis-link.json")
    with pytest.raises(EpistemicUltimateShadowError, match="hardlink_forbidden"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_proof_raw_sha256=_sha(proof),
            formal_artifact_snapshot=snapshot,
        )

def test_failure_shadow_rejects_target_mismatch_and_noncanonical_role(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_FAILURE_NEGATIVE_001"
    workspace, manifest, request, proof = _failure_workspace(tmp_path, report_id)
    snapshot = _failure_snapshot(manifest, report_id)
    request_payload = json.loads(request.read_text(encoding="utf-8"))
    request_payload["diagnosis_target_scope"]["target_factor_id"] = "other-factor"
    _write_json(request, request_payload)
    with pytest.raises(EpistemicUltimateShadowError, match="factor_id_mismatch"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_proof_raw_sha256=_sha(proof),
            formal_artifact_snapshot=snapshot,
        )

    request_payload["diagnosis_target_scope"]["target_factor_id"] = "factor-shadow-test"
    _write_json(request, request_payload)
    alpha = workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json"
    alpha_payload = json.loads(alpha.read_text(encoding="utf-8"))
    alpha_payload["contract_version"] = "not.alpha.idea"
    _write_json(alpha, alpha_payload)
    with pytest.raises(EpistemicUltimateShadowError, match="contract_version"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_proof_raw_sha256=_sha(proof),
            formal_artifact_snapshot=snapshot,
        )


def test_failure_shadow_rejects_post_validation_exact6_drift(tmp_path: Path) -> None:
    report_id = "RPT_SHADOW_EXACT6_DRIFT_001"
    workspace, manifest, request, proof = _failure_workspace(tmp_path, report_id)
    snapshot = _failure_snapshot(manifest, report_id)
    evaluation = (
        workspace
        / "objects"
        / "validation"
        / f"factor_evaluation__{report_id}.json"
    )
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["post_validation_mutation"] = True
    _write_json(evaluation, payload)
    with pytest.raises(
        EpistemicUltimateShadowError,
        match="formal_artifact_snapshot:current_exact6_mismatch",
    ):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_proof_raw_sha256=_sha(proof),
            formal_artifact_snapshot=snapshot,
        )


def test_failure_shadow_rejects_cross_artifact_spec_identity_drift(
    tmp_path: Path,
) -> None:
    report_id = "RPT_SHADOW_EXACT6_IDENTITY_DRIFT_001"
    workspace, manifest, request, proof = _failure_workspace(tmp_path, report_id)
    snapshot = _failure_snapshot(manifest, report_id)
    evaluation = (
        workspace
        / "objects"
        / "validation"
        / f"factor_evaluation__{report_id}.json"
    )
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["artifact_identity"]["spec_hash"] = "d" * 64
    _write_json(evaluation, payload)
    with pytest.raises(EpistemicUltimateShadowError, match="coherence:spec_hash"):
        run_ultimate_epistemic_shadow(
            manifest_path=manifest,
            request_path=request,
            hook=HOOK_FAILURE,
            report_id=report_id,
            repo_root=REPO_ROOT,
            formal_proof_path=proof,
            formal_proof_raw_sha256=_sha(proof),
            formal_artifact_snapshot=snapshot,
        )

def test_shadow_observer_failure_is_non_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    def fail(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=2, stdout="", stderr="sensitive")

    monkeypatch.setattr(ultimate.subprocess, "run", fail)
    result = ultimate.run_epistemic_shadow_observation(
        manifest_path=tmp_path / "manifest.json",
        request_path=tmp_path / "request.json",
        hook=HOOK_STEP1,
        report_id="RPT",
        dry_run=False,
    )
    assert result == {
        "status": "BLOCKED_NONBLOCKING",
        "hook": HOOK_STEP1,
        "returncode": 2,
        "formal_authority_effect": "NONE",
    }
    assert "sensitive" not in json.dumps(result)
    assert not any(key.startswith("FACTORFORGE_") for key in captured["env"])


def test_shadow_console_delivery_failure_is_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_pipe(*_args, **_kwargs):
        raise BrokenPipeError("closed console")

    monkeypatch.setattr("builtins.print", broken_pipe)
    ultimate.print_epistemic_shadow_observation(
        {
            "status": "PASS_CANDIDATE_ONLY",
            "hook": HOOK_STEP1,
            "receipt_path": "/candidate/receipt.json",
        }
    )


def _main_args(**overrides):
    values = {
        "epistemic_failure_shadow_request": None,
        "end_step": "5",
        "dry_run": False,
        "report_id": "RPT",
        "factor_workspace": None,
        "manifest": None,
        "proof_output": None,
        "init_factor_workspace": False,
        "factor_id": None,
        "research_id": None,
        "factorforge_root": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_ultimate_default_off_never_calls_shadow_and_preserves_formal_rc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _main_args()
    monkeypatch.setattr(ultimate, "parse_args", lambda: args)
    monkeypatch.setattr(ultimate, "_run_formal_ultimate", lambda _args: 7)
    monkeypatch.setattr(
        ultimate,
        "run_epistemic_shadow_observation",
        lambda **_kwargs: pytest.fail("shadow must remain default-off"),
    )
    assert ultimate.main() == 7


def test_ultimate_shadow_never_overrides_failed_formal_rc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _main_args(epistemic_failure_shadow_request="/tmp/request.json")
    monkeypatch.setattr(ultimate, "parse_args", lambda: args)
    monkeypatch.setattr(ultimate, "_run_formal_ultimate", lambda _args: 9)
    monkeypatch.setattr(
        ultimate,
        "run_epistemic_shadow_observation",
        lambda **_kwargs: pytest.fail("formal failure must suppress post shadow"),
    )
    assert ultimate.main() == 9


def test_shadow_names_never_enter_formal_command_or_host_loop_forwarding() -> None:
    ultimate_source = (REPO_ROOT / "scripts" / "run_factorforge_ultimate.py").read_text(
        encoding="utf-8"
    )
    command_block = ultimate_source.split(
        "commands: list[tuple[str, list[str]]] = []", 1
    )[1].split("prior_proof_archive: str | None = None", 1)[0]
    assert "epistemic_shadow" not in command_block
    assert "epistemic-step1-shadow" not in command_block
    assert "epistemic-failure-shadow" not in command_block
    for relative in (
        "scripts/run_factorforge_ultimate_loop.py",
        "factor_factory/console/run_service.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "epistemic-step1-shadow-request" not in source
        assert "epistemic-failure-shadow-request" not in source


def test_proof_gate_rejects_evo_for_post_step5_shadow(tmp_path: Path) -> None:
    report_id = "RPT_EVO_DENY"
    workspace = tmp_path / "workspace"
    proof = _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json",
        {
            "report_id": report_id,
            "evo_v2_execution_gate": {"enabled": True},
            "commands": [
                {"name": "validate_step5", "status": "PASS", "returncode": 0}
            ],
        },
    )
    assert proof.exists()
    args = _main_args(report_id=report_id, factor_workspace=str(workspace))
    assert (
        ultimate.derive_post_step5_shadow_eligibility(
            args=args,
            proof=json.loads(proof.read_text(encoding="utf-8")),
            proof_path=proof,
            manifest_path=workspace / "objects" / "runtime_context" / "manifest.json",
            factor_workspace=workspace.resolve(),
        )
        is None
    )


def test_current_post_step5_proof_binding_rejects_failed_and_oos_state(
    tmp_path: Path,
) -> None:
    report_id = "RPT_POST_STEP5_PROOF_001"
    workspace, manifest, _, proof_path = _failure_workspace(tmp_path, report_id)
    args = _main_args(
        report_id=report_id,
        factor_workspace=str(workspace),
        epistemic_failure_shadow_request="/unused/request.json",
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    valid = ultimate.derive_post_step5_shadow_eligibility(
        args=args,
        proof=proof,
        proof_path=proof_path,
        manifest_path=manifest,
        factor_workspace=workspace,
    )
    assert valid is not None
    assert valid["raw_sha256"] == _sha(proof_path)

    failed = copy.deepcopy(proof)
    failed["status"] = "FAIL"
    assert (
        ultimate.derive_post_step5_shadow_eligibility(
            args=args,
            proof=failed,
            proof_path=proof_path,
            manifest_path=manifest,
            factor_workspace=workspace,
        )
        is None
    )

    oos = copy.deepcopy(proof)
    oos["web_oos_recovery"]["recovery_required"] = True
    _write_json(proof_path, oos)
    assert (
        ultimate.derive_post_step5_shadow_eligibility(
            args=args,
            proof=oos,
            proof_path=proof_path,
            manifest_path=manifest,
            factor_workspace=workspace,
        )
        is None
    )


def test_post_step5_observer_exception_is_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report_id = "RPT_POST_STEP5_TOTAL_001"
    workspace, manifest, request, proof_path = _failure_workspace(tmp_path, report_id)
    args = _main_args(
        report_id=report_id,
        factor_workspace=str(workspace),
        epistemic_failure_shadow_request=str(request),
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))

    def explode(**_kwargs):
        raise RuntimeError("ordinary shadow failure")

    monkeypatch.setattr(ultimate, "run_epistemic_shadow_observation", explode)
    ultimate.run_post_step5_epistemic_shadow_nonblocking(
        args=args,
        proof=proof,
        proof_path=proof_path,
        manifest_path=manifest,
        factor_workspace=workspace,
        formal_artifact_snapshot=_failure_snapshot(manifest, report_id),
    )
    assert "BLOCKED_NONBLOCKING_CHILD_ERROR" in capsys.readouterr().out
