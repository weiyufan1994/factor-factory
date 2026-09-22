from __future__ import annotations

import base64
import copy
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import factor_factory.epistemic_ultimate_source_first_bridge as bridge
from factor_factory.epistemic_ultimate_source_first_bridge import (
    EXPECTED_ATTESTATION,
    OVERLAY_SCHEMA_ID,
    SourceFirstAdvisoryBridgeError,
    validate_agent_source_first_overlay,
)
from factor_factory.research_workspace import (
    build_workspace_manifest,
    default_workspace_root,
    workspace_manifest_path,
    write_workspace_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = (
    REPO_ROOT / "examples" / "factorforge_epistemic_kernel_wavelet_demo_input.json"
)
CLI = REPO_ROOT / "scripts" / "run_factorforge_epistemic_source_first_advisory.py"
VALIDATOR_CLI = (
    REPO_ROOT / "scripts" / "validate_factorforge_epistemic_source_first_advisory.py"
)
REPORT_ID = "source-first-bridge-test"
build_agent_managed_kernel_input = bridge._build_agent_managed_kernel_input_with_context
run_source_first_advisory_bridge = bridge._run_source_first_advisory_bridge_with_context
validate_source_first_advisory_package = (
    bridge._validate_source_first_advisory_package_with_context
)


def _overlay(report_id: str = REPORT_ID) -> dict:
    source = json.loads(EXAMPLE_INPUT.read_text(encoding="utf-8"))
    return {
        "schema_id": OVERLAY_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": report_id,
        "agent_source_only_attestation": dict(EXPECTED_ATTESTATION),
        "source_text": source["source_text"],
        "source_lineage": source["source_lineage"],
        "author_claims": source["author_claims"],
        "analyst_notes": source["analyst_notes"],
        "selected_semantic_body": source["selected_semantic_body"],
        "formalization_provenance": source["formalization_provenance"],
        "pre_a0_predictions": source["pre_a0_predictions"],
    }


def _workspace(tmp_path: Path, report_id: str = REPORT_ID) -> Path:
    factorforge_root = tmp_path / "factorforge-root"
    factorforge_root.mkdir()
    workspace = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id="source-first-bridge-factor",
        research_id="source-first-bridge-research",
    ).resolve()
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id="source-first-bridge-factor",
        research_id="source-first-bridge-research",
        root_report_id=report_id,
    )
    write_workspace_manifest(workspace_manifest_path(workspace), manifest)
    return workspace


def _write_overlay(workspace: Path, payload: dict) -> Path:
    path = workspace / bridge.INPUT_PARENT_NAME / "source-first-overlay.json"
    path.parent.mkdir(mode=0o700)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def _factorforge_root(workspace: Path) -> Path:
    return workspace.parents[2]


def test_closed_overlay_keeps_research_semantics_agent_owned() -> None:
    overlay = validate_agent_source_first_overlay(_overlay(), report_id=REPORT_ID)

    assert overlay["agent_source_only_attestation"] == EXPECTED_ATTESTATION
    assert "real_knowledge_inputs" not in overlay
    assert "retrieval_corpus_objects" not in overlay
    assert "session_scope_secret_hex" not in overlay
    assert "diagnosis_inputs" not in overlay


@pytest.mark.parametrize(
    "encoded",
    [
        lambda raw: raw,
        lambda raw: raw.hex().encode("ascii"),
        lambda raw: base64.b64encode(raw),
        lambda raw: base64.b64encode(raw).rstrip(b"="),
        lambda raw: base64.urlsafe_b64encode(raw),
        lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"="),
    ],
)
def test_secret_absence_guard_covers_raw_hex_and_base64_variants(encoded) -> None:
    raw_secret = bytes.fromhex("ab" * 32)
    assert bridge._secret_absent(
        [encoded(raw_secret)],
        {"session_scope_secret_hex": raw_secret.hex()},
    ) is False


def test_source_compiles_before_canonical_knowledge_is_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    original_compile = bridge.compile_source_first_kernel_session_candidate
    original_resolve = bridge._canonical_real_knowledge_inputs

    def compile_spy(**kwargs: object) -> dict:
        events.append("source-first")
        return original_compile(**kwargs)

    def resolve_spy(repo_root: Path) -> dict:
        events.append("knowledge-resolution")
        return original_resolve(repo_root)

    monkeypatch.setattr(
        bridge, "compile_source_first_kernel_session_candidate", compile_spy
    )
    monkeypatch.setattr(bridge, "_canonical_real_knowledge_inputs", resolve_spy)

    kernel_input, preflight = build_agent_managed_kernel_input(
        _overlay(),
        report_id=REPORT_ID,
        repo_root=REPO_ROOT,
        secret_factory=lambda _: "1" * 64,
    )

    assert events == ["source-first", "knowledge-resolution"]
    assert preflight["source_compiled_before_knowledge_resolution"] is True
    assert kernel_input["retrieval_corpus_objects"] is None
    assert kernel_input["diagnosis_inputs"] is None
    assert kernel_input["session_scope_secret_hex"] == "1" * 64
    assert kernel_input["real_knowledge_inputs"] == {
        "node_index_path": str(
            (REPO_ROOT / bridge.EXPECTED_REAL_KNOWLEDGE_PATHS["node_index_path"])
            .resolve()
        ),
        "edge_index_path": str(
            (REPO_ROOT / bridge.EXPECTED_REAL_KNOWLEDGE_PATHS["edge_index_path"])
            .resolve()
        ),
        "taxonomy_path": str(
            (REPO_ROOT / bridge.EXPECTED_REAL_KNOWLEDGE_PATHS["taxonomy_path"])
            .resolve()
        ),
        "top_k_per_lane": 3,
    }


def test_false_pre_retrieval_claim_blocks_before_knowledge_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay = _overlay()
    overlay["agent_source_only_attestation"][
        "knowledge_or_case_retrieval_consulted"
    ] = True
    knowledge_resolved = False

    def forbidden(_: Path) -> dict:
        nonlocal knowledge_resolved
        knowledge_resolved = True
        raise AssertionError("knowledge resolver must not run")

    monkeypatch.setattr(bridge, "_canonical_real_knowledge_inputs", forbidden)
    with pytest.raises(
        SourceFirstAdvisoryBridgeError,
        match="source_only_attestation_required",
    ):
        build_agent_managed_kernel_input(
            overlay,
            report_id=REPORT_ID,
            repo_root=REPO_ROOT,
            secret_factory=lambda _: "1" * 64,
        )
    assert knowledge_resolved is False


def test_ineligible_source_blocks_before_knowledge_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay = _overlay()
    overlay["source_lineage"]["selection_lineage_claim"] = "UNKNOWN"
    knowledge_resolved = False
    secret_minted = False

    def forbidden(_: Path) -> dict:
        nonlocal knowledge_resolved
        knowledge_resolved = True
        raise AssertionError("knowledge resolver must not run")

    monkeypatch.setattr(bridge, "_canonical_real_knowledge_inputs", forbidden)

    def forbidden_secret(_: int) -> str:
        nonlocal secret_minted
        secret_minted = True
        raise AssertionError("secret must not be minted")

    with pytest.raises(Exception):
        build_agent_managed_kernel_input(
            overlay,
            report_id=REPORT_ID,
            repo_root=REPO_ROOT,
            secret_factory=forbidden_secret,
        )
    assert knowledge_resolved is False
    assert secret_minted is False


def test_bridge_runs_before_alpha_master_and_publishes_candidate_only_package(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    assert not (workspace / "objects" / "alpha_idea_master").exists()

    receipt_path = run_source_first_advisory_bridge(
        workspace=workspace,
        overlay_path=overlay_path,
        report_id=REPORT_ID,
        repo_root=REPO_ROOT,
        expected_factorforge_root=_factorforge_root(workspace),
        secret_factory=lambda _: "2" * 64,
    )

    package = receipt_path.parent
    assert sorted(path.name for path in package.iterdir()) == [
        "00_kernel_candidate.json",
        "01_chief_advisory.json",
        "02_shadow_receipt.json",
    ]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    advisory = json.loads(
        (package / "01_chief_advisory.json").read_text(encoding="utf-8")
    )
    all_bytes = b"".join(path.read_bytes() for path in package.iterdir())

    assert receipt["formal_pipeline_effect"][
        "operating_contract_delta_activated"
    ] is True
    assert receipt["rag_configuration"]["user_configuration_required"] is False
    assert receipt["ordering_guards"][
        "retrieval_executed_only_after_blind_seed"
    ] is True
    assert receipt["candidate_only"] is True
    assert receipt["signed"] is False
    assert receipt["authority_effect"] == "NONE"
    assert receipt["execution_boundary"] == {
        "formal_artifacts_written": False,
        "official_registry_written": False,
        "canonical_memory_or_oos_accessed": False,
        "diagnostic_tests_executed": False,
        "promotion_or_qualification_performed": False,
        "network_access_performed": False,
    }
    assert advisory["knowledge_priors"]["may_rewrite_source_understanding_or_blind_seed"] is False
    assert advisory["exploit_and_explore"]["zero_candidate_or_abstention_allowed"] is True
    assert advisory["exploit_and_explore"]["dummy_branch_required"] is False
    assert b"2" * 64 not in all_bytes
    assert not (workspace / "objects" / "alpha_idea_master").exists()


def test_cli_requires_no_rag_path_or_session_secret() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--help",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--node-index" not in " ".join(completed.args)
    assert "--session-secret" not in " ".join(completed.args)
    assert "--expected-factorforge-root" not in completed.stdout
    assert "--expected-factorforge-root" not in CLI.read_text(encoding="utf-8")
    assert "repo_root=" not in CLI.read_text(encoding="utf-8")


def test_public_operating_api_has_no_root_or_secret_injection_seam() -> None:
    assert set(inspect.signature(bridge.run_source_first_advisory_bridge).parameters) == {
        "workspace",
        "overlay_path",
        "report_id",
    }
    assert set(
        inspect.signature(bridge.validate_source_first_advisory_package).parameters
    ) == {"receipt_path"}
    assert "_run_source_first_advisory_bridge_with_context" not in bridge.__all__
    assert "_validate_source_first_advisory_package_with_context" not in bridge.__all__


def test_validator_cli_emits_exact_validated_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary,
) -> None:
    from scripts import validate_factorforge_epistemic_source_first_advisory as cli

    expected = '{"unicode":"小波","validated":true}\n'.encode("utf-8")
    monkeypatch.setattr(
        cli,
        "validate_source_first_advisory_package",
        lambda **_: bridge.ValidatedSourceFirstAdvisoryPackage(
            receipt={},
            chief_advisory_raw=expected,
        ),
    )

    assert cli.main(["--receipt", str(tmp_path / "unused-receipt.json")]) == 0
    captured = capsysbinary.readouterr()
    assert captured.out == expected
    assert captured.err == b""


def test_report_mismatch_and_extra_rag_field_are_rejected() -> None:
    with pytest.raises(SourceFirstAdvisoryBridgeError, match="report_id"):
        validate_agent_source_first_overlay(_overlay("other"), report_id=REPORT_ID)

    overlay = copy.deepcopy(_overlay())
    overlay["real_knowledge_inputs"] = {"caller_selected": True}
    with pytest.raises(SourceFirstAdvisoryBridgeError, match="closed_fields"):
        validate_agent_source_first_overlay(overlay, report_id=REPORT_ID)


def test_overlay_mutation_before_publication_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())

    def attack_publish(**kwargs: object) -> Path:
        overlay_path.write_text("{}\n", encoding="utf-8")
        kwargs["before_receipt"]()
        raise AssertionError("snapshot replay should have blocked")

    monkeypatch.setattr(bridge, "_publish_package", attack_publish)
    with pytest.raises(
        SourceFirstAdvisoryBridgeError, match="overlay_snapshot_drift"
    ):
        run_source_first_advisory_bridge(
            workspace=workspace,
            overlay_path=overlay_path,
            report_id=REPORT_ID,
            repo_root=REPO_ROOT,
            expected_factorforge_root=_factorforge_root(workspace),
            secret_factory=lambda _: "3" * 64,
        )


def test_external_factorforge_root_binding_cannot_be_self_declared(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    alternate = tmp_path / "alternate-root"
    alternate.mkdir()

    with pytest.raises(
        SourceFirstAdvisoryBridgeError,
        match="manifest_external_equality",
    ):
        run_source_first_advisory_bridge(
            workspace=workspace,
            overlay_path=overlay_path,
            report_id=REPORT_ID,
            repo_root=REPO_ROOT,
            expected_factorforge_root=alternate.resolve(),
            secret_factory=lambda _: "4" * 64,
        )


def test_retry_reuses_private_attempt_and_exact_same_package(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    calls = 0

    def one_shot_secret(_: int) -> str:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("retry must not mint another secret")
        return "5" * 64

    kwargs = {
        "workspace": workspace,
        "overlay_path": overlay_path,
        "report_id": REPORT_ID,
        "repo_root": REPO_ROOT,
        "expected_factorforge_root": _factorforge_root(workspace),
        "secret_factory": one_shot_secret,
    }
    first = run_source_first_advisory_bridge(**kwargs)
    second = run_source_first_advisory_bridge(**kwargs)

    assert first == second
    assert calls == 1
    output_root = workspace / bridge.OUTPUT_PARENT_NAME
    assert [path.name for path in output_root.iterdir()] == [first.parent.name]
    attempt_files = list(
        (workspace / bridge.INPUT_PARENT_NAME).glob("bridge_attempt_*.json")
    )
    assert len(attempt_files) == 1
    assert attempt_files[0].stat().st_mode & 0o777 == 0o600


def test_retry_does_not_leak_attempt_file_descriptors(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    kwargs = {
        "workspace": workspace,
        "overlay_path": overlay_path,
        "report_id": REPORT_ID,
        "repo_root": REPO_ROOT,
        "expected_factorforge_root": _factorforge_root(workspace),
        "secret_factory": lambda _: "7" * 64,
    }
    run_source_first_advisory_bridge(**kwargs)
    before = len(os.listdir("/dev/fd"))
    for _ in range(6):
        run_source_first_advisory_bridge(**kwargs)
    after = len(os.listdir("/dev/fd"))

    assert after == before


def test_knowledge_snapshot_change_creates_new_content_addressed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    original_snapshot = bridge._canonical_knowledge_snapshot(REPO_ROOT)
    active_snapshot = copy.deepcopy(original_snapshot)
    monkeypatch.setattr(
        bridge,
        "_canonical_knowledge_snapshot",
        lambda _: copy.deepcopy(active_snapshot),
    )
    secrets_by_attempt = iter(["9" * 64, "a" * 64])
    kwargs = {
        "workspace": workspace,
        "overlay_path": overlay_path,
        "report_id": REPORT_ID,
        "repo_root": REPO_ROOT,
        "expected_factorforge_root": _factorforge_root(workspace),
        "secret_factory": lambda _: next(secrets_by_attempt),
    }

    first = run_source_first_advisory_bridge(**kwargs)
    active_snapshot["content_sha256"] = "f" * 64
    second = run_source_first_advisory_bridge(**kwargs)

    assert first != second
    assert len(list((workspace / bridge.OUTPUT_PARENT_NAME).glob("shadow_*"))) == 2
    assert len(
        list((workspace / bridge.INPUT_PARENT_NAME).glob("bridge_attempt_*.json"))
    ) == 2


def test_invalid_source_leaves_no_attempt_state(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    overlay = _overlay()
    overlay["source_lineage"]["selection_lineage_claim"] = "UNKNOWN"
    overlay_path = _write_overlay(workspace, overlay)

    with pytest.raises(Exception):
        run_source_first_advisory_bridge(
            workspace=workspace,
            overlay_path=overlay_path,
            report_id=REPORT_ID,
            repo_root=REPO_ROOT,
            expected_factorforge_root=_factorforge_root(workspace),
            secret_factory=lambda _: "8" * 64,
        )

    assert not list(
        (workspace / bridge.INPUT_PARENT_NAME).glob("bridge_attempt_*.json")
    )


def test_validator_rebuilds_package_before_advisory_consumption(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    overlay_path = _write_overlay(workspace, _overlay())
    root = _factorforge_root(workspace)
    receipt_path = run_source_first_advisory_bridge(
        workspace=workspace,
        overlay_path=overlay_path,
        report_id=REPORT_ID,
        repo_root=REPO_ROOT,
        expected_factorforge_root=root,
        secret_factory=lambda _: "6" * 64,
    )

    validated = validate_source_first_advisory_package(
        receipt_path=receipt_path,
        repo_root=REPO_ROOT,
        expected_factorforge_root=root,
    )
    assert validated.receipt["run_id"] == receipt_path.parent.name
    assert validated.chief_advisory_raw == (
        receipt_path.parent / "01_chief_advisory.json"
    ).read_bytes()

    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR_CLI),
            "--help",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    validator_source = VALIDATOR_CLI.read_text(encoding="utf-8")
    assert "--expected-factorforge-root" not in completed.stdout
    assert "repo_root=" not in validator_source
    assert "sys.stdout.buffer.write(validated.chief_advisory_raw)" in validator_source
    assert "validated.chief_advisory_raw.decode" not in validator_source

    advisory_path = receipt_path.parent / "01_chief_advisory.json"
    advisory_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SourceFirstAdvisoryBridgeError):
        validate_source_first_advisory_package(
            receipt_path=receipt_path,
            repo_root=REPO_ROOT,
            expected_factorforge_root=root,
        )


def test_combined_handoff_uses_only_protected_public_apis(monkeypatch, tmp_path):
    receipt = tmp_path / "unused-receipt.json"
    expected = bridge.ValidatedSourceFirstAdvisoryPackage(
        receipt={"authority_effect": "NONE"}, chief_advisory_raw=b'{"prior":true}\n'
    )
    events = []

    def run(**kwargs):
        events.append(("run", kwargs))
        return receipt

    def validate(**kwargs):
        events.append(("validate", kwargs))
        return expected

    monkeypatch.setattr(bridge, "run_source_first_advisory_bridge", run)
    monkeypatch.setattr(bridge, "validate_source_first_advisory_package", validate)
    args = dict(workspace=tmp_path, overlay_path=tmp_path / "source.json", report_id=REPORT_ID)
    result = bridge.run_and_validate_source_first_advisory(**args)
    assert result is expected
    assert events == [("run", args), ("validate", {"receipt_path": receipt})]
    assert set(inspect.signature(bridge.run_and_validate_source_first_advisory).parameters) == set(args)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stage", ["run", "validate"])
def test_combined_handoff_does_not_fall_back_on_failure(monkeypatch, tmp_path, stage):
    calls = []

    def run(**kwargs):
        calls.append("run")
        if stage == "run":
            raise SourceFirstAdvisoryBridgeError("source-invalid")
        return tmp_path / "unused-receipt.json"

    def validate(**kwargs):
        calls.append("validate")
        raise SourceFirstAdvisoryBridgeError("replay-invalid")

    monkeypatch.setattr(bridge, "run_source_first_advisory_bridge", run)
    monkeypatch.setattr(bridge, "validate_source_first_advisory_package", validate)
    with pytest.raises(SourceFirstAdvisoryBridgeError):
        bridge.run_and_validate_source_first_advisory(
            workspace=tmp_path, overlay_path=tmp_path / "source.json", report_id=REPORT_ID
        )
    assert calls == (["run"] if stage == "run" else ["run", "validate"])


def test_combined_cli_emits_exact_verified_bytes_and_preserves_legacy(monkeypatch, capsys, tmp_path):
    from scripts import run_factorforge_epistemic_source_first_advisory as cli

    raw = '{ "advisory": "先验", "authority_effect": "NONE" }\n'.encode()
    validated = bridge.ValidatedSourceFirstAdvisoryPackage(receipt={}, chief_advisory_raw=raw)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(cli, "run_and_validate_source_first_advisory", lambda **kwargs: validated)
    monkeypatch.setattr(cli, "run_source_first_advisory_bridge", lambda **kwargs: receipt)
    args = ["--factor-workspace", str(tmp_path), "--source-first-overlay", str(tmp_path / "overlay.json"), "--report-id", REPORT_ID]
    assert cli.main([*args, "--emit-validated-advisory"]) == 0
    assert capsys.readouterr().out.encode() == raw
    assert cli.main(args) == 0
    assert capsys.readouterr().out == f"{receipt}\n"
    assert list(tmp_path.iterdir()) == []


def test_combined_cli_failure_has_no_advisory_stdout(monkeypatch, capsys, tmp_path):
    from scripts import run_factorforge_epistemic_source_first_advisory as cli

    def fail(**kwargs):
        raise SourceFirstAdvisoryBridgeError("synthetic-replay-drift")

    monkeypatch.setattr(cli, "run_and_validate_source_first_advisory", fail)
    args = ["--factor-workspace", str(tmp_path), "--source-first-overlay", str(tmp_path / "overlay.json"), "--report-id", REPORT_ID, "--emit-validated-advisory"]
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "synthetic-replay-drift" in captured.err


def test_combined_handoff_real_replay_and_idempotency(monkeypatch, tmp_path):
    workspace = _workspace(tmp_path)
    overlay = _write_overlay(workspace, _overlay())
    root = _factorforge_root(workspace)
    monkeypatch.setattr(bridge, "run_source_first_advisory_bridge", lambda **kwargs: run_source_first_advisory_bridge(
        **kwargs, repo_root=REPO_ROOT, expected_factorforge_root=root,
        secret_factory=lambda _: "9" * 64,
    ))
    monkeypatch.setattr(bridge, "validate_source_first_advisory_package", lambda **kwargs: validate_source_first_advisory_package(
        **kwargs, repo_root=REPO_ROOT, expected_factorforge_root=root,
    ))
    args = dict(workspace=workspace, overlay_path=overlay, report_id=REPORT_ID)
    first = bridge.run_and_validate_source_first_advisory(**args)
    second = bridge.run_and_validate_source_first_advisory(**args)
    assert first == second
    assert len(list((workspace / bridge.OUTPUT_PARENT_NAME).iterdir())) == 1
    assert not list(workspace.rglob("alpha_idea_master*"))
    assert not list(workspace.rglob("factor_proof_certificate*"))
