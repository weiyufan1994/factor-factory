from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "scripts" / "build_factorforge_epistemic_kernel_offline_candidate.py"
EXAMPLE_INPUT = REPO_ROOT / "examples" / "factorforge_epistemic_kernel_wavelet_demo_input.json"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "epistemic_kernel_publisher_security_test",
        CLI_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    payload = json.loads(EXAMPLE_INPUT.read_text(encoding="utf-8"))
    payload["retrieval_corpus_objects"] = []
    payload["real_knowledge_inputs"] = None
    payload["diagnosis_inputs"] = None
    return payload


def _replayed_candidate() -> dict:
    return {
        "schema_id": "factorforge_epistemic_kernel_composition_offline_candidate_v1",
        "schema_version": "1.0.0",
        "artifact_status": "RUNNABLE_OFFLINE_CANDIDATE__NOT_PRODUCTION_ACTIVATED",
        "session_id": "publisher-security-session-001",
        "stage_outputs": {"source_first": {}, "retrieval": {}, "diagnosis": None},
        "chief_research_advisory": {
            "advisory_kind": "FACTOR_FORGE_STEP1_RESEARCH_BRAIN_SIDECAR",
            "advisory_only": True,
        },
        "lineage_guards": {},
        "execution_summary": {
            "source_first_executed": True,
            "retrieval_executed": True,
            "diagnosis_planner_executed": False,
            "diagnostic_tests_executed": False,
            "network_or_ambient_discovery_performed": False,
            "canonical_write_performed": False,
            "oos_access_performed": False,
            "production_activation_performed": False,
        },
        "candidate_only": True,
        "signed": False,
        "authority_effect": "NONE",
        "content_sha256": "2" * 64,
    }


@pytest.fixture
def publisher_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_cli_module()
    expected_parent = tmp_path / "projects"
    fake_repo = expected_parent / "factor-factory-test-repo"
    for relative in ("knowledge", "factor_research", "deploy", "runtime", "canonical", "oos"):
        (fake_repo / relative).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "REPO_ROOT", fake_repo.resolve())
    replayed = _replayed_candidate()

    def compose_stub(**_kwargs):
        return copy.deepcopy(replayed)

    def validate_stub(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "compose_epistemic_kernel_candidate", compose_stub)
    monkeypatch.setattr(module, "validate_epistemic_kernel_composition", validate_stub)
    return module, expected_parent.resolve(), fake_repo.resolve()


def _valid_output(module, expected_parent: Path, suffix: str) -> Path:
    return expected_parent / f"{module.OUTPUT_ROOT_PREFIX}{suffix}"


def test_output_root_is_exact_prefixed_direct_sibling_and_create_only(
    publisher_environment,
) -> None:
    module, expected_parent, fake_repo = publisher_environment
    valid = _valid_output(module, expected_parent, "valid-001")
    assert module._resolve_output_root(valid, expected_parent) == valid

    invalid_cases = [
        (expected_parent / "wrong-prefix", expected_parent),
        (_valid_output(module, fake_repo, "inside-repo"), expected_parent),
        (_valid_output(module, fake_repo / "knowledge", "inside-knowledge"), expected_parent),
        (_valid_output(module, fake_repo / "factor_research", "inside-factor-research"), expected_parent),
        (_valid_output(module, fake_repo / "oos", "inside-oos"), expected_parent),
        (_valid_output(module, fake_repo / "canonical", "inside-canonical"), expected_parent),
        (_valid_output(module, fake_repo / "runtime", "inside-runtime"), expected_parent),
        (_valid_output(module, fake_repo / "deploy", "inside-deploy"), expected_parent),
        (_valid_output(module, expected_parent, "runtime"), expected_parent),
    ]
    for output_root, allowed_parent in invalid_cases:
        with pytest.raises(module.OfflineCandidateCliError):
            module._resolve_output_root(output_root, allowed_parent)

    wrong_parent = expected_parent.parent
    with pytest.raises(
        module.OfflineCandidateCliError,
        match="allowed_parent:must_equal_repo_root_parent",
    ):
        module._resolve_output_root(
            _valid_output(module, wrong_parent, "wrong-parent"),
            wrong_parent,
        )

    valid.mkdir()
    with pytest.raises(module.OfflineCandidateCliError, match="create_only"):
        module._resolve_output_root(valid, expected_parent)


def test_output_root_rejects_symlink_aliases_to_protected_roots(
    publisher_environment,
) -> None:
    module, expected_parent, fake_repo = publisher_environment
    target_alias = _valid_output(module, expected_parent, "alias-001")
    target_alias.symlink_to(fake_repo / "knowledge", target_is_directory=True)
    with pytest.raises(module.OfflineCandidateCliError):
        module._resolve_output_root(target_alias, expected_parent)

    parent_alias = expected_parent.parent / "projects-alias"
    parent_alias.symlink_to(expected_parent, target_is_directory=True)
    with pytest.raises(module.OfflineCandidateCliError):
        module._resolve_output_root(
            _valid_output(module, parent_alias, "parent-alias"),
            parent_alias,
        )


def test_publish_replays_validates_derives_manifest_and_drops_secret(
    publisher_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, expected_parent, _ = publisher_environment
    payload = _payload()
    candidate = module.build_candidate(payload)
    calls = 0
    original_validator = module.validate_epistemic_kernel_composition

    def validating_spy(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_validator(*args, **kwargs)

    monkeypatch.setattr(module, "validate_epistemic_kernel_composition", validating_spy)
    output = _valid_output(module, expected_parent, "publish-001")
    manifest_path = module.publish_candidate(
        candidate=candidate,
        input_payload=payload,
        output_root=output,
        allowed_parent=expected_parent,
    )

    assert calls == 1
    assert manifest_path == output / "packet_manifest.json"
    assert sorted(path.name for path in output.iterdir()) == [
        "00_epistemic_kernel_candidate.json",
        "01_chief_research_advisory.json",
        "packet_manifest.json",
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    execution = candidate["execution_summary"]
    assert manifest["manifest_status"] == candidate["artifact_status"]
    assert manifest["source_candidate_content_sha256"] == candidate["content_sha256"]
    assert manifest["candidate_only"] is candidate["candidate_only"]
    assert manifest["signed"] is candidate["signed"]
    assert manifest["authority_effect"] == candidate["authority_effect"]
    assert manifest["canonical_write_or_oos_access_performed"] is bool(
        execution["canonical_write_performed"] or execution["oos_access_performed"]
    )
    assert manifest["input_or_session_secret_persisted"] is False
    replay_scope = manifest["publisher_time_replay_scope"]
    assert replay_scope["status"] == "PASS"
    assert replay_scope["scope"] == "PUBLISHER_TIME_ONLY__NON_SELF_CONTAINED"
    assert replay_scope["standalone_replay_claimed"] is False
    assert replay_scope["session_secret_persisted"] is False
    assert replay_scope["required_external_dependency_categories"] == [
        "ORIGINAL_INPUT_PAYLOAD",
        "SOURCE_AND_LINEAGE_INPUTS",
        "RETRIEVAL_CORPUS_OR_REAL_KNOWLEDGE_INPUTS",
        "OPTIONAL_DIAGNOSIS_SOURCE_BYTES",
        "COMPOSITION_IMPLEMENTATION_AND_VALIDATOR_CODE",
        "SCHEMAS_AND_CONTRACT_IMPLEMENTATION_DEPENDENCIES",
    ]
    assert all(manifest["replay_validation"].values())

    secret_hex = payload["session_scope_secret_hex"]
    secret = bytes.fromhex(secret_hex)
    persisted = b"\n".join(path.read_bytes() for path in output.iterdir())
    for needle in (
        secret,
        secret_hex.encode("ascii"),
        secret_hex.upper().encode("ascii"),
        base64.b64encode(secret),
    ):
        assert needle not in persisted


@pytest.mark.parametrize("mutation", ["injected_secret", "stale_content_hash"])
def test_publish_rejects_injected_or_stale_candidate_before_creating_root(
    publisher_environment,
    mutation: str,
) -> None:
    module, expected_parent, _ = publisher_environment
    payload = _payload()
    candidate = module.build_candidate(payload)
    tampered = copy.deepcopy(candidate)
    if mutation == "injected_secret":
        tampered["caller_injected_secret"] = payload["session_scope_secret_hex"]
    else:
        tampered["content_sha256"] = "0" * 64
    output = _valid_output(module, expected_parent, mutation)

    with pytest.raises(
        module.OfflineCandidateCliError,
        match="candidate_replay_mismatch",
    ):
        module.publish_candidate(
            candidate=tampered,
            input_payload=payload,
            output_root=output,
            allowed_parent=expected_parent,
        )
    assert not output.exists()


def test_composition_validator_failure_occurs_before_any_write(
    publisher_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, expected_parent, _ = publisher_environment
    payload = _payload()
    candidate = module.build_candidate(payload)
    output = _valid_output(module, expected_parent, "validator-failure")

    def reject(*_args, **_kwargs):
        raise module.OfflineCandidateCliError("test:composition_validator_rejected")

    monkeypatch.setattr(module, "validate_epistemic_kernel_composition", reject)
    with pytest.raises(
        module.OfflineCandidateCliError,
        match="composition_validator_rejected",
    ):
        module.publish_candidate(
            candidate=candidate,
            input_payload=payload,
            output_root=output,
            allowed_parent=expected_parent,
        )
    assert not output.exists()


def test_concurrent_output_entry_replacement_never_writes_protected_root(
    publisher_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, expected_parent, fake_repo = publisher_environment
    payload = _payload()
    candidate = module.build_candidate(payload)
    output = _valid_output(module, expected_parent, "replacement-race")
    displaced = expected_parent / f"{output.name}-displaced"
    protected = fake_repo / "knowledge"
    original_write = module._write_once_at
    replaced = False

    def replace_then_write(output_dir_fd: int, name: str, data: bytes) -> None:
        nonlocal replaced
        if not replaced:
            replaced = True
            output.rename(displaced)
            output.symlink_to(protected, target_is_directory=True)
        original_write(output_dir_fd, name, data)

    monkeypatch.setattr(module, "_write_once_at", replace_then_write)
    with pytest.raises(
        module.OfflineCandidateCliError,
        match="output_entry_(identity_drift|not_directory|drift)",
    ):
        module.publish_candidate(
            candidate=candidate,
            input_payload=payload,
            output_root=output,
            allowed_parent=expected_parent,
        )

    assert replaced is True
    assert output.is_symlink()
    assert list(protected.iterdir()) == []
    assert list(displaced.iterdir()) == []
