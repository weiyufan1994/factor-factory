#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_kernel_composition_offline import (
    compose_epistemic_kernel_candidate,
    validate_epistemic_kernel_composition,
)
from factor_factory.research_org.contracts import strict_json_loads


MAX_INPUT_BYTES = 32 * 1024 * 1024
HEX_32_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
OUTPUT_ROOT_PREFIX = "factor-forge-epistemic-kernel-local-run-"
OUTPUT_ROOT_SUFFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PROTECTED_ROOT_NAMES = frozenset(
    {
        "knowledge",
        "factor_research",
        "oos",
        "canonical",
        "runtime",
        "deploy",
    }
)
CLI_DIAGNOSIS_FIELDS = {
    "stage2_manifest_path",
    "fixture_json_path",
    "assertion_dependency_json_path",
}
INPUT_FIELDS = {
    "source_text",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
    "phase_policy_candidate",
    "retrieval_corpus_objects",
    "real_knowledge_inputs",
    "session_scope_secret_hex",
    "diagnosis_inputs",
}


class OfflineCandidateCliError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise OfflineCandidateCliError(reason)


def _load_input(path: Path) -> dict[str, Any]:
    _require(path.is_absolute(), "input:absolute_path_required")
    _require(path.is_file() and not path.is_symlink(), "input:regular_file_required")
    raw = path.read_bytes()
    _require(0 < len(raw) <= MAX_INPUT_BYTES, "input:size")
    payload = strict_json_loads(raw, label="epistemic-kernel-input")
    return _validate_input_payload(payload)


def _validate_input_payload(payload: Any) -> dict[str, Any]:
    _require(isinstance(payload, dict), "input:object_required")
    _require(set(payload) == INPUT_FIELDS, "input:closed_fields")
    _require(
        isinstance(payload["source_text"], str) and bool(payload["source_text"].strip()),
        "input.source_text:nonempty",
    )
    return payload


def validate_epistemic_kernel_input_payload(payload: Any) -> dict[str, Any]:
    """Validate the closed, explicit input object used by the offline kernel.

    This public spelling lets the Ultimate shadow adapter reuse the exact same
    input contract without importing a private helper or silently widening it.
    The returned object is the caller object after validation; no defaults or
    inferred research semantics are added.
    """

    return _validate_input_payload(payload)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _same_physical_identity(left: Path, right: Path) -> bool:
    left_stat = left.stat()
    right_stat = right.stat()
    return (left_stat.st_dev, left_stat.st_ino) == (
        right_stat.st_dev,
        right_stat.st_ino,
    )


def _name_is_protected(name: str) -> bool:
    lowered = name.casefold()
    components = {part for part in re.split(r"[^a-z0-9]+", lowered) if part}
    return bool(components & PROTECTED_ROOT_NAMES) or any(
        token in lowered or token.replace("_", "-") in lowered
        for token in PROTECTED_ROOT_NAMES
    )


def _protected_roots(expected_parent: Path) -> tuple[Path, ...]:
    candidates = {
        REPO_ROOT,
        *(REPO_ROOT / name for name in PROTECTED_ROOT_NAMES),
    }
    for child in expected_parent.iterdir():
        if _name_is_protected(child.name):
            candidates.add(child)
    resolved: set[Path] = set()
    for candidate in candidates:
        if candidate.exists() or candidate.is_symlink():
            try:
                resolved.add(candidate.resolve(strict=True))
            except (FileNotFoundError, RuntimeError, OSError) as exc:
                raise OfflineCandidateCliError(
                    f"output_root:protected_root_resolution_failed:{candidate}"
                ) from exc
    return tuple(sorted(resolved, key=str))


def _resolve_output_root(output_root: Path, allowed_parent: Path) -> Path:
    _require(output_root.is_absolute(), "output_root:absolute_path_required")
    _require(allowed_parent.is_absolute(), "allowed_parent:absolute_path_required")
    expected_parent = REPO_ROOT.parent
    _require(
        expected_parent.is_dir() and not expected_parent.is_symlink(),
        "output_root:repo_parent_must_be_real_directory",
    )
    expected_parent = expected_parent.resolve(strict=True)
    _require(
        allowed_parent.is_dir() and not allowed_parent.is_symlink(),
        "allowed_parent:existing_regular_directory_required",
    )
    parent = allowed_parent.resolve(strict=True)
    _require(
        parent == expected_parent
        and _same_physical_identity(parent, expected_parent),
        "allowed_parent:must_equal_repo_root_parent",
    )
    _require(
        output_root.parent == expected_parent,
        "output_root:direct_child_of_repo_parent_required",
    )
    _require(
        output_root.name.startswith(OUTPUT_ROOT_PREFIX),
        "output_root:required_prefix",
    )
    suffix = output_root.name.removeprefix(OUTPUT_ROOT_PREFIX)
    _require(
        OUTPUT_ROOT_SUFFIX_RE.fullmatch(suffix) is not None,
        "output_root:invalid_suffix",
    )
    _require(
        not _name_is_protected(output_root.name),
        "output_root:protected_name_forbidden",
    )
    target = output_root.resolve(strict=False)
    _require(target.parent == expected_parent, "output_root:physical_parent_mismatch")
    _require(not output_root.exists() and not output_root.is_symlink(), "output_root:create_only")
    _require(
        output_root.parent.resolve(strict=True) == expected_parent,
        "output_root:unsafe_parent",
    )
    for protected in _protected_roots(expected_parent):
        _require(
            not _is_within(target, protected),
            f"output_root:protected_root_or_descendant:{protected}",
        )
    return target


def _verify_created_output_root(target: Path, expected_parent: Path) -> None:
    target_lstat = target.lstat()
    _require(stat.S_ISDIR(target_lstat.st_mode), "output_root:created_root_not_directory")
    _require(not target.is_symlink(), "output_root:created_root_symlink")
    resolved = target.resolve(strict=True)
    _require(resolved == target, "output_root:created_root_alias")
    _require(resolved.parent == expected_parent, "output_root:created_root_parent_mismatch")
    _require(
        _same_physical_identity(resolved.parent, expected_parent),
        "output_root:created_root_parent_identity_mismatch",
    )
    for protected in _protected_roots(expected_parent):
        _require(
            not _is_within(resolved, protected)
            and not _same_physical_identity(resolved, protected),
            f"output_root:created_root_protected_alias:{protected}",
        )


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_bounded_raw_json(path_value: Any, *, label: str) -> bytes:
    _require(isinstance(path_value, str), f"{label}:path_string_required")
    path = Path(path_value)
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    _require(path.is_file() and not path.is_symlink(), f"{label}:regular_file_required")
    raw = path.read_bytes()
    _require(0 < len(raw) <= MAX_INPUT_BYTES, f"{label}:size")
    strict_json_loads(raw, label=label)
    return raw


def _absolute_regular_json_path(path_value: Any, *, label: str) -> Path:
    _require(isinstance(path_value, str), f"{label}:path_string_required")
    path = Path(path_value)
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    _require(path.is_file() and not path.is_symlink(), f"{label}:regular_file_required")
    _require(0 < path.stat().st_size <= MAX_INPUT_BYTES, f"{label}:size")
    return path


def _write_once_at(output_dir_fd: int, name: str, payload: bytes) -> None:
    _require(
        bool(name) and name not in {".", ".."} and "/" not in name,
        "publish:relative_leaf_name_required",
    )
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=output_dir_fd,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(name, dir_fd=output_dir_fd)
        except FileNotFoundError:
            pass
        raise


def _fd_identity(descriptor: int) -> tuple[int, int]:
    value = os.fstat(descriptor)
    return value.st_dev, value.st_ino


def _assert_output_entry_identity(
    *, parent_dir_fd: int, output_name: str, output_dir_fd: int
) -> None:
    try:
        entry = os.stat(output_name, dir_fd=parent_dir_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise OfflineCandidateCliError("publish:output_entry_drift") from exc
    _require(stat.S_ISDIR(entry.st_mode), "publish:output_entry_not_directory")
    _require(
        (entry.st_dev, entry.st_ino) == _fd_identity(output_dir_fd),
        "publish:output_entry_identity_drift",
    )


def _assert_publish_identities(
    *,
    parent_dir_fd: int,
    expected_parent: Path,
    output_name: str,
    output_dir_fd: int,
) -> None:
    current_parent = expected_parent.stat()
    _require(
        _fd_identity(parent_dir_fd)
        == (current_parent.st_dev, current_parent.st_ino),
        "publish:parent_identity_drift",
    )
    _assert_output_entry_identity(
        parent_dir_fd=parent_dir_fd,
        output_name=output_name,
        output_dir_fd=output_dir_fd,
    )


def _composition_inputs(input_payload: dict[str, Any]) -> dict[str, Any]:
    input_payload = _validate_input_payload(input_payload)
    source_inputs = {
        "source_bytes": input_payload["source_text"].encode("utf-8"),
        "source_lineage": input_payload["source_lineage"],
        "author_claims": input_payload["author_claims"],
        "analyst_notes": input_payload["analyst_notes"],
        "selected_semantic_body": input_payload["selected_semantic_body"],
        "formalization_provenance": input_payload["formalization_provenance"],
        "pre_a0_predictions": input_payload["pre_a0_predictions"],
        "phase_policy_candidate": input_payload["phase_policy_candidate"],
    }
    corpus = input_payload["retrieval_corpus_objects"]
    real_knowledge = input_payload["real_knowledge_inputs"]
    _require(
        not (corpus is not None and real_knowledge is not None),
        "input.retrieval:synthetic_and_real_modes_are_mutually_exclusive",
    )
    secret_hex = input_payload["session_scope_secret_hex"]
    if corpus is None and real_knowledge is None:
        _require(secret_hex is None, "input.session_scope_secret:forbidden_without_retrieval")
        secret = None
    else:
        _require(
            corpus is None or isinstance(corpus, list),
            "input.retrieval_corpus_objects:array_required",
        )
        _require(
            real_knowledge is None or isinstance(real_knowledge, dict),
            "input.real_knowledge_inputs:object_required",
        )
        _require(
            isinstance(secret_hex, str) and HEX_32_RE.fullmatch(secret_hex) is not None,
            "input.session_scope_secret_hex:exact32_bytes",
        )
        secret = bytes.fromhex(secret_hex)
    diagnosis = input_payload["diagnosis_inputs"]
    _require(diagnosis is None or isinstance(diagnosis, dict), "input.diagnosis_inputs")
    if diagnosis is not None:
        _require(
            set(diagnosis) == CLI_DIAGNOSIS_FIELDS,
            "input.diagnosis_inputs:closed_fields",
        )
        diagnosis = {
            "stage2_manifest_path": _absolute_regular_json_path(
                diagnosis["stage2_manifest_path"],
                label="input.diagnosis_inputs.stage2_manifest_path",
            ),
            "fixture_raw_bytes": _read_bounded_raw_json(
                diagnosis["fixture_json_path"],
                label="input.diagnosis_inputs.fixture_json_path",
            ),
            "assertion_dependency_raw_bytes": _read_bounded_raw_json(
                diagnosis["assertion_dependency_json_path"],
                label="input.diagnosis_inputs.assertion_dependency_json_path",
            ),
        }
    return {
        "source_inputs": source_inputs,
        "retrieval_corpus_objects": corpus,
        "real_knowledge_inputs": real_knowledge,
        "session_scope_secret": secret,
        "diagnosis_inputs": diagnosis,
    }


def epistemic_kernel_composition_inputs(
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Project a validated CLI object into the composition API's exact inputs."""

    return _composition_inputs(input_payload)


def build_candidate(input_payload: dict[str, Any]) -> dict[str, Any]:
    return compose_epistemic_kernel_candidate(
        **_composition_inputs(input_payload),
    )


def _secret_needles(input_payload: dict[str, Any]) -> tuple[bytes, ...]:
    secret_hex = input_payload["session_scope_secret_hex"]
    if secret_hex is None:
        return ()
    secret = bytes.fromhex(secret_hex)
    return tuple(
        value
        for value in {
            secret,
            secret_hex.encode("ascii"),
            secret_hex.lower().encode("ascii"),
            secret_hex.upper().encode("ascii"),
            base64.b64encode(secret),
        }
        if value
    )


def _original_secret_persisted(
    *, input_payload: dict[str, Any], payloads: list[tuple[str, bytes]]
) -> bool:
    for needle in _secret_needles(input_payload):
        for _, payload in payloads:
            if needle in payload:
                return True
    return False


def _assert_original_secret_not_persisted(
    *, input_payload: dict[str, Any], payloads: list[tuple[str, bytes]]
) -> bool:
    persisted = _original_secret_persisted(
        input_payload=input_payload,
        payloads=payloads,
    )
    _require(not persisted, "publish:session_secret_persisted")
    return persisted


def _replay_and_validate_candidate(
    *, candidate: dict[str, Any], input_payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bool]]:
    _require(isinstance(candidate, dict), "publish:candidate_object_required")
    composition_inputs = _composition_inputs(input_payload)
    replayed = compose_epistemic_kernel_candidate(
        **composition_inputs,
    )
    exact_object_equality = candidate == replayed
    _require(exact_object_equality, "publish:candidate_replay_mismatch")
    exact_canonical_bytes_equality = _json_bytes(candidate) == _json_bytes(replayed)
    _require(
        exact_canonical_bytes_equality,
        "publish:candidate_canonical_bytes_mismatch",
    )
    validate_epistemic_kernel_composition(
        candidate,
        **composition_inputs,
    )
    return replayed, {
        "caller_candidate_exactly_equals_rebuilt_candidate": exact_object_equality,
        "caller_candidate_canonical_bytes_equal_rebuilt_candidate": (
            exact_canonical_bytes_equality
        ),
        "composition_validator_passed": True,
    }


def _manifest_from_replay(
    *,
    replayed_candidate: dict[str, Any],
    replay_validation: dict[str, bool],
    artifacts: list[tuple[str, bytes]],
    input_payload: dict[str, Any],
) -> bytes:
    execution = replayed_candidate["execution_summary"]
    persisted_payloads = list(artifacts)
    secret_persisted = _assert_original_secret_not_persisted(
        input_payload=input_payload,
        payloads=persisted_payloads,
    )
    canonical_or_oos = bool(
        execution["canonical_write_performed"] or execution["oos_access_performed"]
    )
    manifest_core = {
        "schema_id": "factorforge_epistemic_kernel_offline_delivery_manifest_v1",
        "schema_version": "1.0.0",
        "manifest_status": replayed_candidate["artifact_status"],
        "session_id": replayed_candidate["session_id"],
        "source_candidate_content_sha256": replayed_candidate["content_sha256"],
        "ordered_artifacts": [
            {
                "ordinal": ordinal,
                "path": name,
                "bytes": len(payload),
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
            }
            for ordinal, (name, payload) in enumerate(artifacts)
        ],
        "replay_validation": {
            **replay_validation,
            "original_session_secret_scan_passed": not secret_persisted,
        },
        "publisher_time_replay_scope": {
            "status": "PASS",
            "scope": "PUBLISHER_TIME_ONLY__NON_SELF_CONTAINED",
            "standalone_replay_claimed": False,
            "required_external_dependency_categories": [
                "ORIGINAL_INPUT_PAYLOAD",
                "SOURCE_AND_LINEAGE_INPUTS",
                "RETRIEVAL_CORPUS_OR_REAL_KNOWLEDGE_INPUTS",
                "OPTIONAL_DIAGNOSIS_SOURCE_BYTES",
                "COMPOSITION_IMPLEMENTATION_AND_VALIDATOR_CODE",
                "SCHEMAS_AND_CONTRACT_IMPLEMENTATION_DEPENDENCIES",
            ],
            "session_secret_persisted": secret_persisted,
        },
        "input_or_session_secret_persisted": secret_persisted,
        "canonical_write_or_oos_access_performed": canonical_or_oos,
        "candidate_only": replayed_candidate["candidate_only"],
        "signed": replayed_candidate["signed"],
        "authority_effect": replayed_candidate["authority_effect"],
    }
    manifest = dict(manifest_core)
    manifest["content_sha256"] = hashlib.sha256(_json_bytes(manifest_core)).hexdigest()
    manifest_bytes = _json_bytes(manifest)
    _assert_original_secret_not_persisted(
        input_payload=input_payload,
        payloads=[*persisted_payloads, ("packet_manifest.json", manifest_bytes)],
    )
    return manifest_bytes


def publish_candidate(
    *,
    candidate: dict[str, Any],
    input_payload: dict[str, Any],
    output_root: Path,
    allowed_parent: Path,
) -> Path:
    target = _resolve_output_root(output_root, allowed_parent)
    replayed_candidate, replay_validation = _replay_and_validate_candidate(
        candidate=candidate,
        input_payload=input_payload,
    )
    candidate_bytes = _json_bytes(replayed_candidate)
    advisory_bytes = _json_bytes(replayed_candidate["chief_research_advisory"])
    artifacts = [
        ("00_epistemic_kernel_candidate.json", candidate_bytes),
        ("01_chief_research_advisory.json", advisory_bytes),
    ]
    manifest_bytes = _manifest_from_replay(
        replayed_candidate=replayed_candidate,
        replay_validation=replay_validation,
        artifacts=artifacts,
        input_payload=input_payload,
    )
    expected_parent = REPO_ROOT.parent.resolve(strict=True)
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    output_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_dir_fd = os.open(expected_parent, parent_flags)
    output_dir_fd: int | None = None
    created = False
    try:
        _require(
            _fd_identity(parent_dir_fd)
            == (expected_parent.stat().st_dev, expected_parent.stat().st_ino),
            "publish:parent_identity_drift",
        )
        os.mkdir(target.name, mode=0o700, dir_fd=parent_dir_fd)
        created = True
        output_dir_fd = os.open(target.name, output_flags, dir_fd=parent_dir_fd)
        _assert_publish_identities(
            parent_dir_fd=parent_dir_fd,
            expected_parent=expected_parent,
            output_name=target.name,
            output_dir_fd=output_dir_fd,
        )
        for name, payload in artifacts:
            _assert_publish_identities(
                parent_dir_fd=parent_dir_fd,
                expected_parent=expected_parent,
                output_name=target.name,
                output_dir_fd=output_dir_fd,
            )
            _write_once_at(output_dir_fd, name, payload)
            _assert_publish_identities(
                parent_dir_fd=parent_dir_fd,
                expected_parent=expected_parent,
                output_name=target.name,
                output_dir_fd=output_dir_fd,
            )
        _assert_publish_identities(
            parent_dir_fd=parent_dir_fd,
            expected_parent=expected_parent,
            output_name=target.name,
            output_dir_fd=output_dir_fd,
        )
        _write_once_at(output_dir_fd, "packet_manifest.json", manifest_bytes)
        _assert_publish_identities(
            parent_dir_fd=parent_dir_fd,
            expected_parent=expected_parent,
            output_name=target.name,
            output_dir_fd=output_dir_fd,
        )
        _require(
            _fd_identity(parent_dir_fd)
            == (expected_parent.stat().st_dev, expected_parent.stat().st_ino),
            "publish:parent_identity_drift",
        )
        return target / "packet_manifest.json"
    except Exception:
        # The root was absent before this process.  Remove only files created by this
        # function, then the empty root; never touch a pre-existing directory.
        if output_dir_fd is not None:
            for name in (
                "packet_manifest.json",
                "01_chief_research_advisory.json",
                "00_epistemic_kernel_candidate.json",
            ):
                try:
                    os.unlink(name, dir_fd=output_dir_fd)
                except FileNotFoundError:
                    pass
        if created and output_dir_fd is not None:
            try:
                _assert_output_entry_identity(
                    parent_dir_fd=parent_dir_fd,
                    output_name=target.name,
                    output_dir_fd=output_dir_fd,
                )
                os.rmdir(target.name, dir_fd=parent_dir_fd)
            except (OSError, OfflineCandidateCliError):
                pass
        raise
    finally:
        if output_dir_fd is not None:
            os.close(output_dir_fd)
        os.close(parent_dir_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a runnable, local-only Factor Forge epistemic kernel candidate."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--allowed-output-parent", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _load_input(args.input)
        candidate = build_candidate(payload)
        manifest = publish_candidate(
            candidate=candidate,
            input_payload=payload,
            output_root=args.output_root,
            allowed_parent=args.allowed_output_parent,
        )
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
