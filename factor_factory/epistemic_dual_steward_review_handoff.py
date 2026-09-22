from __future__ import annotations

import gc
import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from factor_factory.epistemic_binding import (
    _atomic_publish_directory_noreplace_at,
    _entry_exists_at,
    _open_absolute_directory_fd,
)
from factor_factory.epistemic_candidate_definition_generation import (
    H1_MANIFEST_RAW_SHA256,
    H1_REVIEW_MANIFEST_RAW_SHA256,
    R14_MANIFEST_RAW_SHA256,
    R14_REVIEW_MANIFEST_RAW_SHA256,
    validate_candidate_definition_packet,
)
from factor_factory.epistemic_host_bootstrap_b0b import (
    _create_staging_directory,
    _stable_file_row,
    _validate_staging_closure,
)
from factor_factory.research_org.contracts import (
    strict_json_loads,
    write_workspace_json_once,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256

SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"

CANDIDATE_PACKET_ID = "FF_EPISTEMIC_CANDIDATE_DEFINITION_GENERATION_S1_20260828_R1"
CANDIDATE_PACKET_MANIFEST_RAW_SHA256 = (
    "920da81934f27a051ff5f7ae3e102205bf8e3f91ed937de356f16e6cf0648bc5"
)
CANDIDATE_PACKET_CONTENT_SHA256 = (
    "afa31002f35cafaf9b8ce09d6f1d7a7f0f2ece61bf65329a8ce0d4ebc6fc0567"
)
R2_HANDOFF_PACKET_MANIFEST_RAW_SHA256 = (
    "96bc581d7196e011f42f38ae971dc56c3fcefc470a92fa8456a2616776c64553"
)
R2_HANDOFF_PACKET_CONTENT_SHA256 = (
    "771d467dd15799134f4a421d7bda9609a803ba4167fbab891c9cc041b6851892"
)
R14_HANDOFF_RAW_SHA256 = (
    "5de5a4bde65475542ce5edda3bbf52d587839c82961f1301375af9c8713ec779"
)
R14_HANDOFF_CONTENT_SHA256 = (
    "9df5f5a676fb6229239945e4fe2f897b3c1216cd540cc9367d1d834c22cda849"
)
R14_SCHEMA_BUNDLE_RAW_SHA256 = (
    "d36c62ec5b2732682f81ae5d334bf0c315d1285fc3f6e112bbad3f41abb5273c"
)
R14_SCHEMA_BUNDLE_CONTENT_SHA256 = (
    "58a970be5f16d8448898487af2dcc64aa4b407c95f48a9053056009ff6ac84bb"
)
R14_CLOSED_REVIEW_TARGET_SHA256 = (
    "c83b95a534c598e05c06e9ba740020dc98f02e9905db7b5268f1beaf18dc8a7e"
)

PACKET_ID = "FF_EPISTEMIC_DUAL_STEWARD_REVIEW_HANDOFF_S1_20260829_R3"
CONTRACT_SCHEMA_ID = "factorforge_epistemic_unsigned_review_handoff_contract_s1_v1"
REQUEST_SCHEMA_ID = "factorforge_epistemic_unsigned_steward_review_request_exact2_s1_v1"
REQUEST_OBJECT_SCHEMA_ID = "factorforge_epistemic_unsigned_steward_review_request_s1_v1"
READBACK_SCHEMA_ID = "factorforge_epistemic_local_git_delivery_readback_s1_v1"
REPORT_SCHEMA_ID = "factorforge_epistemic_review_handoff_validation_report_s1_v1"
PACKET_SCHEMA_ID = "factorforge_epistemic_dual_steward_review_handoff_packet_s1_v1"

CONTRACT_CONTENT_DOMAIN = "FF_E1_S1_UNSIGNED_STEWARD_REVIEW_HANDOFF_CONTRACT_V1"
REQUEST_ID_DOMAIN = "FF_E1_S1_UNSIGNED_STEWARD_REVIEW_REQUEST_ID_V1"
REQUEST_CONTENT_DOMAIN = "FF_E1_S1_UNSIGNED_STEWARD_REVIEW_REQUEST_CONTENT_V1"
REPOSITORY_HANDLE_DOMAIN = "FF_E1_S1_LOCAL_REPOSITORY_HANDLE_V1"
REPOSITORY_OBSERVATION_DOMAIN = "FF_E1_S1_LOCAL_REPOSITORY_OBSERVATION_V1"
SEPARATION_MATRIX_DOMAIN = "FF_E1_S1_LOCAL_REPOSITORY_SEPARATION_MATRIX_V1"
READBACK_CONTENT_DOMAIN = "FF_E1_S1_LOCAL_GIT_DELIVERY_READBACK_V1"
REPORT_CONTENT_DOMAIN = "FF_E1_S1_REVIEW_HANDOFF_VALIDATION_REPORT_V1"
PACKET_ARTIFACT_MANIFEST_DOMAIN = "FF_E1_S1_REVIEW_HANDOFF_PACKET_ARTIFACT_MANIFEST_V1"
PACKET_CONTENT_DOMAIN = "FF_E1_S1_REVIEW_HANDOFF_PACKET_V1"

CANDIDATE_SUBTREE = f"candidates/{CANDIDATE_PACKET_ID}"
CANDIDATE_BRANCH = "candidate/r14-expectation-definition-s1-r1"

ROLE_ROWS = (
    {
        "ordinal": 0,
        "steward_role": "ontology_steward",
        "future_git_repository_role": "ONTOLOGY_DEFINITION_REPOSITORY",
        "current_local_candidate_role": "LOCAL_ONTOLOGY_DELIVERY_CANDIDATE",
        "signature_profile_id": "FFSIGN_EXPECTATION_ONTOLOGY_STEWARD_DECISION_V1",
        "trust_domain_id": "ONTOLOGY_DEFINITION_STEWARD_TRUST_DOMAIN",
    },
    {
        "ordinal": 1,
        "steward_role": "reference_steward",
        "future_git_repository_role": "REFERENCE_DEFINITION_REPOSITORY",
        "current_local_candidate_role": "LOCAL_REFERENCE_DELIVERY_CANDIDATE",
        "signature_profile_id": "FFSIGN_EXPECTATION_REFERENCE_STEWARD_DECISION_V1",
        "trust_domain_id": "REFERENCE_DEFINITION_STEWARD_TRUST_DOMAIN",
    },
)

EXPECTED_SOURCE_FILES = (
    (
        "00_candidate_definition_derivation_contract.json",
        "DEFINITION_DERIVATION_CONTRACT",
    ),
    ("01_closed_candidate_definition_bytes.schema.json", "CLOSED_DEFINITION_SCHEMA"),
    ("02_candidate_definition.json", "CANDIDATE_DEFINITION_BYTES"),
    ("03_definition_bytes_manifest.json", "DEFINITION_BYTES_MANIFEST"),
    ("04_candidate_definition_generation.json", "R14_GENERATION_SUCCESSOR"),
    ("05_generation_validation_report.json", "LOCAL_VALIDATION_REPORT"),
    ("packet_manifest.json", "CANDIDATE_PACKET_MANIFEST"),
)

ALLOWED_GIT_COMMANDS = {
    "cat-file",
    "fsck",
    "ls-tree",
    "merge-base",
    "remote",
    "rev-list",
    "rev-parse",
    "status",
}


class DualStewardReviewHandoffError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(";".join(reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise DualStewardReviewHandoffError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise DualStewardReviewHandoffError(
            [f"{label}:expected={expected!r}:actual={actual!r}"]
        )


def _with_content_sha(payload: dict[str, Any], *, domain: str) -> dict[str, Any]:
    _require("content_sha256" not in payload, f"content_sha_already_present:{domain}")
    result = dict(payload)
    result["content_sha256"] = framed_sha256(domain, payload)
    return result


def _verify_content(payload: dict[str, Any], *, domain: str, label: str) -> None:
    core = dict(payload)
    actual = core.pop("content_sha256", None)
    _require_equal(actual, framed_sha256(domain, core), f"{label}_content_sha256")


def _strict_object(path: Path) -> tuple[dict[str, Any], bytes]:
    path = Path(path).resolve(strict=True)
    before = path.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"unsafe_json_source:{path.name}",
    )
    raw = path.read_bytes()
    after = path.lstat()
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"source_changed_during_read:{path.name}",
    )
    payload = strict_json_loads(raw, label=str(path))
    _require(isinstance(payload, dict), f"json_object_required:{path.name}")
    return payload, raw


def _sha256_file(path: Path) -> tuple[int, str]:
    path = Path(path).resolve(strict=True)
    before = path.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"unsafe_file_source:{path.name}",
    )
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    after = path.lstat()
    _require_equal(size, before.st_size, f"file_size_changed:{path.name}")
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"source_changed_during_hash:{path.name}",
    )
    return size, digest.hexdigest()


def _stable_regular_bytes(path: Path, *, label: str) -> bytes:
    path = Path(path).resolve(strict=True)
    before = path.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"unsafe_regular_file:{label}",
    )
    raw = path.read_bytes()
    after = path.lstat()
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"regular_file_changed_during_read:{label}",
    )
    return raw


def _safe_directory_identity(path: Path, *, label: str) -> dict[str, int]:
    raw_path = Path(path)
    _require(raw_path.is_absolute(), f"absolute_directory_required:{label}")
    resolved = raw_path.resolve(strict=True)
    _require_equal(resolved, raw_path, f"symlink_or_alias_directory:{label}")
    metadata = resolved.lstat()
    _require(
        stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode),
        f"safe_directory_required:{label}",
    )
    return {"device": metadata.st_dev, "inode": metadata.st_ino}


def _git(repo: Path, *args: str, allow_status: tuple[int, ...] = (0,)) -> bytes:
    _require(
        bool(args) and args[0] in ALLOWED_GIT_COMMANDS, "git_command_not_read_only"
    )
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
        env=environment,
    )
    _require(
        completed.returncode in allow_status,
        f"git_read_failed:{args[0]}:{completed.returncode}",
    )
    return completed.stdout


def _resolve_git_path(repo: Path, raw: bytes) -> Path:
    value = raw.decode("utf-8").strip()
    _require(bool(value), "empty_git_path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo / candidate
    return candidate.resolve(strict=True)


def _unresolved_git_path(repo: Path, raw: bytes) -> Path:
    value = raw.decode("utf-8").strip()
    _require(bool(value), "empty_git_path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo / candidate
    return candidate


def _candidate_source_rows(candidate_root: Path) -> list[dict[str, Any]]:
    manifest, manifest_raw = _strict_object(candidate_root / "packet_manifest.json")
    _require_equal(
        manifest.get("packet_id"), CANDIDATE_PACKET_ID, "candidate_packet_id"
    )
    _require_equal(
        hashlib.sha256(manifest_raw).hexdigest(),
        CANDIDATE_PACKET_MANIFEST_RAW_SHA256,
        "candidate_packet_manifest_raw_sha256",
    )
    _require_equal(
        manifest.get("content_sha256"),
        CANDIDATE_PACKET_CONTENT_SHA256,
        "candidate_packet_content_sha256",
    )
    source_rows: list[dict[str, Any]] = []
    artifact_by_path = {
        row["path"]: row for row in manifest.get("ordered_artifacts", [])
    }
    for ordinal, (name, role) in enumerate(EXPECTED_SOURCE_FILES):
        path = candidate_root / name
        _, payload = _strict_object(path)
        if name == "packet_manifest.json":
            expected_bytes = len(manifest_raw)
            expected_sha = CANDIDATE_PACKET_MANIFEST_RAW_SHA256
        else:
            row = artifact_by_path.get(name)
            _require(isinstance(row, dict), f"candidate_artifact_missing:{name}")
            expected_bytes = row.get("bytes")
            expected_sha = row.get("sha256")
        _require_equal(len(payload), expected_bytes, f"candidate_source_bytes:{name}")
        digest = hashlib.sha256(payload).hexdigest()
        _require_equal(digest, expected_sha, f"candidate_source_sha256:{name}")
        source_rows.append(
            {
                "ordinal": ordinal,
                "role": role,
                "path": name,
                "bytes": len(payload),
                "sha256": digest,
            }
        )
    return source_rows


def _candidate_payloads(
    candidate_root: Path, *, source_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    source_by_path = {row["path"]: row for row in source_rows}
    for name, role in EXPECTED_SOURCE_FILES:
        payload, raw = _strict_object(candidate_root / name)
        source = source_by_path[name]
        _require_equal(len(raw), source["bytes"], f"candidate_payload_bytes:{name}")
        _require_equal(
            hashlib.sha256(raw).hexdigest(),
            source["sha256"],
            f"candidate_payload_sha256:{name}",
        )
        payloads[role] = payload
    return payloads


def _load_r14_review_bindings(r14_manifest_path: Path) -> dict[str, Any]:
    manifest, manifest_raw = _strict_object(r14_manifest_path)
    _require_equal(
        hashlib.sha256(manifest_raw).hexdigest(),
        R14_MANIFEST_RAW_SHA256,
        "r14_manifest_raw_sha256",
    )
    _require_equal(
        manifest.get("content_sha256"),
        "72773e5e2348d63c7a555a1b0f510e593567dbfa078d9f6442c82f820350b34e",
        "r14_manifest_content_sha256",
    )
    artifact_by_role = {
        row["role"]: row for row in manifest.get("ordered_artifacts", [])
    }
    handoff_row = artifact_by_role.get("DUAL_GIT_HANDOFF")
    schema_row = artifact_by_role.get("CLOSED_STEWARD_REVIEW_SCHEMA_BUNDLE")
    _require(isinstance(handoff_row, dict), "r14_handoff_row_missing")
    _require(isinstance(schema_row, dict), "r14_schema_bundle_row_missing")
    _require_equal(
        handoff_row.get("sha256"), R14_HANDOFF_RAW_SHA256, "r14_handoff_row_sha"
    )
    _require_equal(
        schema_row.get("sha256"),
        R14_SCHEMA_BUNDLE_RAW_SHA256,
        "r14_schema_bundle_row_sha",
    )
    root = Path(r14_manifest_path).resolve(strict=True).parent
    handoff, handoff_raw = _strict_object(root / handoff_row["path"])
    _require_equal(
        hashlib.sha256(handoff_raw).hexdigest(),
        R14_HANDOFF_RAW_SHA256,
        "r14_handoff_raw_sha",
    )
    _require_equal(
        handoff.get("content_sha256"),
        R14_HANDOFF_CONTENT_SHA256,
        "r14_handoff_content_sha",
    )
    schema_size, schema_sha = _sha256_file(root / schema_row["path"])
    _require_equal(schema_size, schema_row.get("bytes"), "r14_schema_bundle_bytes")
    _require_equal(
        schema_sha, R14_SCHEMA_BUNDLE_RAW_SHA256, "r14_schema_bundle_raw_sha"
    )
    _require_equal(
        manifest.get("closed_steward_review_schema_bundle_content_sha256"),
        R14_SCHEMA_BUNDLE_CONTENT_SHA256,
        "r14_schema_bundle_content_sha",
    )
    return {
        "packet_content_sha256": manifest["content_sha256"],
        "handoff_content_sha256": handoff["content_sha256"],
        "schema_bundle_content_sha256": manifest[
            "closed_steward_review_schema_bundle_content_sha256"
        ],
        "closed_review_target_sha256": handoff["closed_review_target_sha256"],
    }


def _review_target(
    *,
    candidate_payloads: dict[str, dict[str, Any]],
    r14_bindings: dict[str, Any],
) -> dict[str, Any]:
    generation = candidate_payloads["R14_GENERATION_SUCCESSOR"]
    definition = candidate_payloads["CANDIDATE_DEFINITION_BYTES"]
    bytes_manifest = candidate_payloads["DEFINITION_BYTES_MANIFEST"]
    basis = generation["generation_basis"]
    target = {
        "e1_r14_packet_manifest_raw_sha256": R14_MANIFEST_RAW_SHA256,
        "e1_r14_packet_content_sha256": r14_bindings["packet_content_sha256"],
        "r14_handoff_raw_sha256": R14_HANDOFF_RAW_SHA256,
        "r14_handoff_content_sha256": r14_bindings["handoff_content_sha256"],
        "r14_closed_schema_bundle_raw_sha256": R14_SCHEMA_BUNDLE_RAW_SHA256,
        "r14_closed_schema_bundle_content_sha256": r14_bindings[
            "schema_bundle_content_sha256"
        ],
        "closed_review_target_sha256": r14_bindings["closed_review_target_sha256"],
        "candidate_packet_manifest_raw_sha256": CANDIDATE_PACKET_MANIFEST_RAW_SHA256,
        "candidate_packet_content_sha256": candidate_payloads[
            "CANDIDATE_PACKET_MANIFEST"
        ]["content_sha256"],
        "candidate_definition_generation_id": generation[
            "candidate_definition_generation_id"
        ],
        "candidate_definition_generation_basis_sha256": generation[
            "generation_basis_sha256"
        ],
        "candidate_definition_generation_content_sha256": generation["content_sha256"],
        "candidate_definition_generation_target_id": basis[
            "candidate_definition_generation_target_id"
        ],
        "candidate_definition_generation_target_content_sha256": basis[
            "candidate_definition_generation_target_content_sha256"
        ],
        "candidate_definition_raw_sha256": bytes_manifest["ordered_definition_files"][
            0
        ]["sha256"],
        "candidate_definition_content_sha256": definition["content_sha256"],
        "candidate_definition_bytes_manifest_sha256": bytes_manifest[
            "definition_bytes_manifest_sha256"
        ],
        "candidate_assignment_manifest_sha256": definition[
            "candidate_assignment_manifest_sha256"
        ],
        "definition_row_manifest_sha256": definition["definition_row_manifest_sha256"],
        "branch_selection_target_manifest_sha256": definition[
            "branch_selection_target_manifest_sha256"
        ],
        "selected_branch_manifest_sha256": definition[
            "selected_branch_manifest_sha256"
        ],
        "closed_materialization_design_manifest_sha256": definition[
            "closed_materialization_design_manifest_sha256"
        ],
        "semantic_derivation_registry_content_sha256": basis[
            "semantic_derivation_registry_content_sha256"
        ],
        "semantic_derivation_manifest_sha256": definition[
            "semantic_derivation_manifest_sha256"
        ],
        "expectation_proposal_content_sha256": basis[
            "expectation_proposal_content_sha256"
        ],
    }
    _require_equal(
        target["e1_r14_packet_content_sha256"],
        "72773e5e2348d63c7a555a1b0f510e593567dbfa078d9f6442c82f820350b34e",
        "review_target_r14_content",
    )
    _require_equal(
        target["r14_handoff_content_sha256"],
        R14_HANDOFF_CONTENT_SHA256,
        "review_target_handoff_content",
    )
    _require_equal(
        target["r14_closed_schema_bundle_content_sha256"],
        R14_SCHEMA_BUNDLE_CONTENT_SHA256,
        "review_target_schema_bundle_content",
    )
    _require_equal(
        target["closed_review_target_sha256"],
        R14_CLOSED_REVIEW_TARGET_SHA256,
        "review_target_closed_target",
    )
    return target


def compile_handoff_contract(
    *, review_target: dict[str, Any], candidate_source_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    core = {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "contract_status": "UNSIGNED_EXACT2_REVIEW_REQUEST_PREPARATION_ONLY",
        "request_object_schema_id": REQUEST_OBJECT_SCHEMA_ID,
        "request_count": 2,
        "ordered_request_roles": [dict(row) for row in ROLE_ROWS],
        "candidate_source_file_count": 7,
        "ordered_candidate_source_files": candidate_source_rows,
        "review_target": review_target,
        "exact160_review_law": {
            "definition_row_count": 160,
            "definition_ordinals": {"first": 0, "last": 159, "gap_allowed": False},
            "global_obligation_ordinals": {
                "first": 10,
                "last": 169,
                "gap_allowed": False,
            },
            "candidate_fail_count": 99,
            "candidate_blocked_count": 61,
            "row_restatement_in_request_allowed": False,
            "whole_definition_raw_and_content_binding_required": True,
            "missing_reorder_splice_count_or_hash_mismatch_result": "BLOCKED",
        },
        "exact10_branch_review_law": {
            "review_target_count": 10,
            "review_target_ordinals": {"first": 0, "last": 9, "gap_allowed": False},
            "request_may_prefill_disposition": False,
            "future_response_allowed_dispositions": [
                "APPROVE_CURRENT_SELECTED_BRANCH",
                "REQUEST_ALTERNATE_SUCCESSOR",
                "REJECT_ROW",
            ],
            "alternate_or_reject_requires_new_successor": True,
            "target_list_and_manifest_equality_required_across_requests": True,
        },
        "request_response_type_separation": {
            "request_may_use_steward_decision_preimage_schema": False,
            "request_may_use_signed_decision_envelope_schema": False,
            "request_contains_decision_or_signature_instance": False,
            "response_is_external_successor": True,
        },
        "current_external_state": {
            "verified_submission_endpoint_count": 0,
            "remote_repository_binding_count": 0,
            "steward_principal_key_trust_binding_count": 0,
            "steward_signed_decision_count": 0,
            "os_sealed_activation_count": 0,
            "host_authorization_count": 0,
        },
        "git_inspection_mode": "READ_ONLY_PLUMBING__NO_GIT_MUTATION__NO_NETWORK",
        "raw_git_object_graph_law": {
            "git_no_replace_objects_required": True,
            "git_ref_format_required": "files",
            "shallow_repository_allowed": False,
            "legacy_grafts_allowed": False,
            "loose_or_packed_replace_refs_allowed": False,
            "unknown_or_mismatch_result": "BLOCKED",
        },
        "owner_chat_may_satisfy_contract_gate": False,
        "signed": False,
        "candidate_only": True,
        "may_activate": False,
        "may_materialize_or_execute": False,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=CONTRACT_CONTENT_DOMAIN)


def _request_unbound_state() -> dict[str, Any]:
    return {
        "submission_endpoint_ref": None,
        "remote_repository_identity": None,
        "repository_role_binding_receipt_ref": None,
        "git_commit_sha": None,
        "git_parent_commit_sha": None,
        "git_tree_sha": None,
        "git_blob_path": None,
        "git_blob_raw_sha256": None,
        "reviewer_principal_id": None,
        "reviewer_context_id": None,
        "reviewer_capability_id": None,
        "reviewer_installation_id": None,
        "reviewer_key_id": None,
        "reviewer_key_generation": None,
        "trust_binding_receipt_ref": None,
        "trusted_time_evidence_ref": None,
        "nonrevocation_evidence_ref": None,
        "issued_at": None,
        "expires_at": None,
        "nonce": None,
        "branch_selection_disposition_manifest_ref": None,
        "branch_selection_disposition_manifest_sha256": None,
        "decision": None,
        "decision_basis_sha256": None,
        "decision_id_sha256": None,
        "findings": None,
        "signature": None,
        "signed_envelope_ref": None,
        "completed_signed_artifact_sha256": None,
        "profile_activation_ref": None,
        "os_activation_ref": None,
        "host_authorization_ref": None,
    }


def compile_unsigned_requests(
    *, contract: dict[str, Any], review_target: dict[str, Any]
) -> list[dict[str, Any]]:
    processing_order = [
        "RAW_BYTES_HASH_AND_STRICT_JSON_PARSE",
        "CLOSED_SCHEMA_EXACT_ONE_BRANCH",
        "DECISION_PREIMAGE_DIGEST_RECOMPUTATION",
        "SIGNATURE_PROFILE_AND_SIGNATURE_VERIFICATION",
        "TRUSTED_TIME_EXPIRY_AND_NONREVOCATION",
        "GIT_ANCESTRY_AND_BLOB_RAW_BYTES_EQUALITY",
        "CLOSED_REVIEW_TARGET_EQUALITY",
        "DUAL_ROLE_REPOSITORY_PRINCIPAL_CONTEXT_CAPABILITY_INSTALLATION_KEY_INDEPENDENCE",
    ]
    requests: list[dict[str, Any]] = []
    for role in ROLE_ROWS:
        request_id = "ffreviewreq::" + framed_sha256(
            REQUEST_ID_DOMAIN,
            {
                "ordinal": role["ordinal"],
                "steward_role": role["steward_role"],
                "candidate_packet_manifest_raw_sha256": review_target[
                    "candidate_packet_manifest_raw_sha256"
                ],
                "candidate_definition_generation_id": review_target[
                    "candidate_definition_generation_id"
                ],
            },
        )
        core = {
            "schema_id": REQUEST_OBJECT_SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "request_kind": "EXPECTATION_DERIVATION_DEFINITION_REVIEW_REQUEST",
            "request_status": "PREPARED_NOT_SUBMITTED__EXTERNAL_BINDINGS_UNBOUND_BLOCKING",
            "ordinal": role["ordinal"],
            "steward_role": role["steward_role"],
            "future_git_repository_role": role["future_git_repository_role"],
            "current_local_candidate_role": role["current_local_candidate_role"],
            "handoff_contract_content_sha256": contract["content_sha256"],
            "review_target": review_target,
            "review_scope": {
                "definition_row_count": 160,
                "candidate_fail_count": 99,
                "candidate_blocked_count": 61,
                "branch_selection_review_target_count": 10,
                "row_or_target_restatement_present": False,
            },
            "expected_response_contract": {
                "decision_preimage_schema_id": "factorforge_expectation_steward_decision_preimage_v1",
                "signed_decision_envelope_schema_id": "factorforge_expectation_signed_steward_decision_envelope_v1",
                "signature_profile_id": role["signature_profile_id"],
                "required_trust_domain_id": role["trust_domain_id"],
                "signature_verifier_profile_id": "FF_EXPECTATION_STEWARD_SIGNATURE_VERIFIER_V1",
                "allowed_decisions": [
                    "APPROVE_EXACT160_SELECTED_BRANCHES",
                    "REVISE",
                    "REJECT",
                ],
                "admission_validation_order": processing_order,
                "response_is_external_successor": True,
            },
            "current_unbound_state": _request_unbound_state(),
            "submitted": False,
            "reviewed": False,
            "approved": False,
            "is_steward_decision": False,
            "contains_decision_or_signature_instance": False,
            "signed": False,
            "candidate_only": True,
            "may_activate": False,
            "may_materialize_or_execute": False,
            "oos_allowed": False,
            "skill_rag_runtime_allowed": False,
            "canonical_memory_read_or_write_allowed": False,
            "runtime_or_deployment_allowed": False,
            "permissions_opened_count": 0,
            "authority_effect": AUTHORITY_EFFECT,
        }
        requests.append(_with_content_sha(core, domain=REQUEST_CONTENT_DOMAIN))
    return requests


def compile_exact2_request_schema(requests: list[dict[str, Any]]) -> dict[str, Any]:
    _require_equal(len(requests), 2, "request_schema_exact2")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": REQUEST_SCHEMA_ID,
        "title": "Exact2 unsigned steward review requests; never a steward response",
        "oneOf": [{"const": request} for request in requests],
        "x-factorforge-request-count": 2,
        "x-factorforge-request-is-authority-response": False,
        "x-factorforge-authority-effect": AUTHORITY_EFFECT,
    }


def _repo_observation(
    repo_root: Path,
    *,
    role: dict[str, Any],
    source_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], set[tuple[int, int]]]:
    repo_root = Path(repo_root)
    root_identity = _safe_directory_identity(
        repo_root, label=role["current_local_candidate_role"]
    )
    canonical_root = repo_root.resolve(strict=True)
    top = Path(_git(canonical_root, "rev-parse", "--show-toplevel").decode().strip())
    _require_equal(top.resolve(strict=True), canonical_root, "git_top_level")
    git_dir = _resolve_git_path(
        canonical_root, _git(canonical_root, "rev-parse", "--absolute-git-dir")
    )
    common_dir = _resolve_git_path(
        canonical_root, _git(canonical_root, "rev-parse", "--git-common-dir")
    )
    objects_dir = _resolve_git_path(
        canonical_root, _git(canonical_root, "rev-parse", "--git-path", "objects")
    )
    identities = {
        "worktree_root": root_identity,
        "git_dir": _safe_directory_identity(git_dir, label="git_dir"),
        "git_common_dir": _safe_directory_identity(common_dir, label="git_common_dir"),
        "git_objects_dir": _safe_directory_identity(
            objects_dir, label="git_objects_dir"
        ),
    }
    _require_equal(
        _git(canonical_root, "rev-parse", "--is-bare-repository").decode().strip(),
        "false",
        "bare_repository_forbidden",
    )
    _require_equal(
        _git(canonical_root, "rev-parse", "--show-object-format").decode().strip(),
        "sha1",
        "git_object_format",
    )
    _require_equal(
        _git(canonical_root, "rev-parse", "--show-ref-format").decode().strip(),
        "files",
        "git_ref_format",
    )
    _require_equal(
        _git(canonical_root, "rev-parse", "--is-shallow-repository").decode().strip(),
        "false",
        "shallow_repository_forbidden",
    )
    _require_equal(
        _git(canonical_root, "status", "--porcelain=v1", "--untracked-files=all"),
        b"",
        "git_worktree_must_be_clean",
    )
    remotes = [
        line for line in _git(canonical_root, "remote").decode().splitlines() if line
    ]
    _require_equal(remotes, [], "local_only_repository_must_have_zero_remotes")
    alternates = objects_dir / "info" / "alternates"
    _require(not alternates.exists(), "git_object_alternates_forbidden")
    shallow = _unresolved_git_path(
        canonical_root, _git(canonical_root, "rev-parse", "--git-path", "shallow")
    )
    grafts = common_dir / "info" / "grafts"
    loose_replace_refs = common_dir / "refs" / "replace"
    packed_refs = common_dir / "packed-refs"
    _require(not shallow.exists(), "git_shallow_marker_forbidden")
    _require(not grafts.exists(), "git_legacy_grafts_forbidden")
    _require(not loose_replace_refs.exists(), "git_loose_replace_refs_forbidden")
    if packed_refs.exists():
        packed_raw = _stable_regular_bytes(packed_refs, label="packed_refs")
        _require(
            b"refs/replace/" not in packed_raw, "git_packed_replace_refs_forbidden"
        )
    _git(canonical_root, "fsck", "--strict", "--no-progress", "--no-dangling")
    branch = _git(canonical_root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    _require_equal(branch, CANDIDATE_BRANCH, "candidate_branch")
    head = _git(canonical_root, "rev-parse", "HEAD^{commit}").decode().strip()
    tree = _git(canonical_root, "rev-parse", "HEAD^{tree}").decode().strip()
    parent_parts = (
        _git(canonical_root, "rev-list", "--parents", "-n", "1", head).decode().split()
    )
    _require_equal(len(parent_parts), 2, "single_direct_parent_required")
    _require_equal(parent_parts[0], head, "parent_row_head")
    parent = parent_parts[1]
    main = (
        _git(canonical_root, "rev-parse", "refs/heads/main^{commit}").decode().strip()
    )
    _require_equal(parent, main, "candidate_parent_must_equal_main")
    _git(canonical_root, "merge-base", "--is-ancestor", main, head)
    _require_equal(
        _git(canonical_root, "rev-list", "--count", f"{main}..{head}").decode().strip(),
        "1",
        "candidate_commit_distance",
    )
    _require_equal(
        _git(
            canonical_root,
            "ls-tree",
            "-rz",
            "--full-tree",
            parent,
            "--",
            CANDIDATE_SUBTREE,
        ),
        b"",
        "candidate_subtree_must_be_introduced_at_head",
    )
    tree_raw = _git(
        canonical_root, "ls-tree", "-rz", "--full-tree", head, "--", CANDIDATE_SUBTREE
    )
    parsed: dict[str, tuple[str, str, str]] = {}
    for entry in tree_raw.split(b"\x00"):
        if not entry:
            continue
        metadata, path_raw = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        parsed[path_raw.decode()] = (mode, kind, oid)
    expected_full_paths = {f"{CANDIDATE_SUBTREE}/{row['path']}" for row in source_rows}
    _require_equal(set(parsed), expected_full_paths, "candidate_subtree_exact7_closure")
    blob_rows: list[dict[str, Any]] = []
    loose_object_identities: set[tuple[int, int]] = set()
    for source in source_rows:
        full_path = f"{CANDIDATE_SUBTREE}/{source['path']}"
        mode, kind, oid = parsed[full_path]
        _require_equal(mode, "100644", f"candidate_blob_mode:{source['path']}")
        _require_equal(kind, "blob", f"candidate_blob_type:{source['path']}")
        raw = _git(canonical_root, "cat-file", "blob", f"{head}:{full_path}")
        raw_sha = hashlib.sha256(raw).hexdigest()
        _require_equal(
            len(raw), source["bytes"], f"candidate_blob_bytes:{source['path']}"
        )
        _require_equal(
            raw_sha, source["sha256"], f"candidate_blob_sha:{source['path']}"
        )
        loose_object = objects_dir / oid[:2] / oid[2:]
        metadata = loose_object.lstat()
        _require(
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_nlink == 1,
            f"candidate_loose_object_required:{source['path']}",
        )
        object_identity = (metadata.st_dev, metadata.st_ino)
        loose_object_identities.add(object_identity)
        blob_rows.append(
            {
                "ordinal": source["ordinal"],
                "role": source["role"],
                "path": source["path"],
                "git_mode": mode,
                "git_blob_oid": oid,
                "bytes": len(raw),
                "raw_sha256": raw_sha,
                "source_raw_sha256": source["sha256"],
                "source_bytes_equal": True,
                "loose_object_device": metadata.st_dev,
                "loose_object_inode": metadata.st_ino,
                "loose_object_link_count": metadata.st_nlink,
            }
        )
    _require_equal(
        _safe_directory_identity(canonical_root, label="worktree_root_recheck"),
        root_identity,
        "worktree_root_identity_changed",
    )
    _require_equal(
        _safe_directory_identity(git_dir, label="git_dir_recheck"),
        identities["git_dir"],
        "git_dir_identity_changed",
    )
    _require_equal(
        _safe_directory_identity(common_dir, label="git_common_dir_recheck"),
        identities["git_common_dir"],
        "git_common_dir_identity_changed",
    )
    _require_equal(
        _safe_directory_identity(objects_dir, label="git_objects_dir_recheck"),
        identities["git_objects_dir"],
        "git_objects_dir_identity_changed",
    )
    _require_equal(
        _git(canonical_root, "status", "--porcelain=v1", "--untracked-files=all"),
        b"",
        "git_worktree_changed_during_inspection",
    )
    _require_equal(
        _git(canonical_root, "rev-parse", "HEAD^{commit}").decode().strip(),
        head,
        "git_head_changed_during_inspection",
    )
    _require_equal(
        _git(canonical_root, "rev-parse", "HEAD^{tree}").decode().strip(),
        tree,
        "git_tree_changed_during_inspection",
    )
    handle = "localrepo::" + framed_sha256(
        REPOSITORY_HANDLE_DOMAIN,
        {
            "current_local_candidate_role": role["current_local_candidate_role"],
            "root_identity": root_identity,
            "git_dir_identity": identities["git_dir"],
            "object_dir_identity": identities["git_objects_dir"],
        },
    )
    core = {
        "ordinal": role["ordinal"],
        "current_local_candidate_role": role["current_local_candidate_role"],
        "requested_future_git_repository_role": role["future_git_repository_role"],
        "requested_future_role_is_currently_bound": False,
        "local_repository_handle": handle,
        "filesystem_identities": identities,
        "git_object_format": "sha1",
        "git_ref_format": "files",
        "bare": False,
        "shallow_repository": False,
        "branch": branch,
        "head_commit_sha": head,
        "head_tree_sha": tree,
        "direct_parent_commit_sha": parent,
        "main_commit_sha": main,
        "parent_count": 1,
        "main_to_head_commit_count": 1,
        "clean": True,
        "remote_count": 0,
        "object_alternates_present": False,
        "legacy_grafts_present": False,
        "replace_refs_present": False,
        "candidate_subtree": CANDIDATE_SUBTREE,
        "candidate_subtree_introduced_at_head": True,
        "candidate_blob_count": 7,
        "ordered_candidate_blobs": blob_rows,
        "git_author_or_committer_used_as_steward_identity": False,
        "git_commit_signature_used_as_steward_signature": False,
        "remote_repository_binding_present": False,
        "steward_identity_or_decision_present": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core, domain=REPOSITORY_OBSERVATION_DOMAIN
    ), loose_object_identities


def compile_local_git_readback(
    *,
    ontology_repo: Path,
    reference_repo: Path,
    source_rows: list[dict[str, Any]],
    review_target: dict[str, Any],
) -> dict[str, Any]:
    ontology, ontology_objects = _repo_observation(
        ontology_repo, role=ROLE_ROWS[0], source_rows=source_rows
    )
    reference, reference_objects = _repo_observation(
        reference_repo, role=ROLE_ROWS[1], source_rows=source_rows
    )
    left_root = ontology["filesystem_identities"]["worktree_root"]
    right_root = reference["filesystem_identities"]["worktree_root"]
    _require(left_root != right_root, "repository_roots_must_be_distinct")
    for identity_key in ("git_dir", "git_common_dir", "git_objects_dir"):
        _require(
            ontology["filesystem_identities"][identity_key]
            != reference["filesystem_identities"][identity_key],
            f"repository_identity_must_be_distinct:{identity_key}",
        )
    ontology_resolved = Path(ontology_repo).resolve(strict=True)
    reference_resolved = Path(reference_repo).resolve(strict=True)
    common = Path(os.path.commonpath([ontology_resolved, reference_resolved]))
    _require(
        common not in {ontology_resolved, reference_resolved},
        "repository_ancestor_relation_forbidden",
    )
    _require(
        not ontology_objects.intersection(reference_objects),
        "candidate_object_hardlink_overlap",
    )
    left_blobs = ontology["ordered_candidate_blobs"]
    right_blobs = reference["ordered_candidate_blobs"]
    _require_equal(
        [(row["path"], row["git_blob_oid"], row["raw_sha256"]) for row in left_blobs],
        [(row["path"], row["git_blob_oid"], row["raw_sha256"]) for row in right_blobs],
        "cross_repository_exact7_blob_equality",
    )
    _require(
        ontology["head_commit_sha"] != reference["head_commit_sha"],
        "head_commits_must_differ",
    )
    _require(
        ontology["head_tree_sha"] != reference["head_tree_sha"],
        "head_trees_must_differ",
    )
    _require(
        ontology["direct_parent_commit_sha"] != reference["direct_parent_commit_sha"],
        "parent_commits_must_differ",
    )
    separation_core = {
        "repository_root_identity_distinct": True,
        "git_dir_identity_distinct": True,
        "git_common_dir_identity_distinct": True,
        "git_objects_dir_identity_distinct": True,
        "repository_ancestor_relation_absent": True,
        "object_alternates_absent": True,
        "shallow_repository_absent": True,
        "legacy_grafts_absent": True,
        "replace_refs_absent": True,
        "candidate_loose_object_hardlink_overlap_absent": True,
        "head_commit_distinct": True,
        "head_tree_distinct": True,
        "direct_parent_commit_distinct": True,
        "exact7_blob_oid_and_raw_bytes_equal": True,
        "remote_repository_binding_present": False,
        "formal_dual_git_independence_receipt_present": False,
    }
    separation = dict(separation_core)
    separation["matrix_sha256"] = framed_sha256(
        SEPARATION_MATRIX_DOMAIN, separation_core
    )
    core = {
        "schema_id": READBACK_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "receipt_status": "LOCAL_EXACT7_DUAL_REPOSITORY_BYTES_EQUAL__REMOTE_AND_STEWARD_AUTHORITY_UNBOUND_BLOCKING",
        "receipt_kind": "NONAUTHORITATIVE_LOCAL_GIT_DELIVERY_READBACK",
        "candidate_packet_manifest_raw_sha256": review_target[
            "candidate_packet_manifest_raw_sha256"
        ],
        "candidate_packet_content_sha256": review_target[
            "candidate_packet_content_sha256"
        ],
        "candidate_definition_generation_id": review_target[
            "candidate_definition_generation_id"
        ],
        "candidate_definition_generation_content_sha256": review_target[
            "candidate_definition_generation_content_sha256"
        ],
        "repository_observation_count": 2,
        "ordered_repository_observations": [ontology, reference],
        "separation_matrix": separation,
        "absolute_local_paths_serialized": False,
        "git_inspection_was_read_only": True,
        "network_accessed": False,
        "git_mutation_performed": False,
        "may_satisfy_remote_repository_binding": False,
        "may_satisfy_steward_decision_gate": False,
        "steward_signed_decision_count": 0,
        "os_sealed_activation_count": 0,
        "host_authorization_count": 0,
        "signed": False,
        "candidate_only": True,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=READBACK_CONTENT_DOMAIN)


def validate_compiled_handoff(
    *,
    contract: dict[str, Any],
    schema: dict[str, Any],
    requests: list[dict[str, Any]],
    readback: dict[str, Any],
) -> None:
    _verify_content(contract, domain=CONTRACT_CONTENT_DOMAIN, label="handoff_contract")
    _require_equal(len(requests), 2, "exact2_requests")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for request in requests:
        validator.validate(request)
        _verify_content(request, domain=REQUEST_CONTENT_DOMAIN, label="review_request")
        _require_equal(
            request["authority_effect"], AUTHORITY_EFFECT, "request_authority_effect"
        )
        _require_equal(request["signed"], False, "request_signed")
        _require_equal(request["submitted"], False, "request_submitted")
        _require_equal(request["reviewed"], False, "request_reviewed")
        _require_equal(request["approved"], False, "request_approved")
        _require_equal(request["is_steward_decision"], False, "request_is_decision")
        _require_equal(
            set(request["current_unbound_state"].values()),
            {None},
            "request_actual_fields_must_all_be_null",
        )
    _require_equal(
        requests[0]["review_target"],
        requests[1]["review_target"],
        "cross_request_review_target",
    )
    _require_equal(
        [request["steward_role"] for request in requests],
        ["ontology_steward", "reference_steward"],
        "request_role_order",
    )
    _verify_content(
        readback, domain=READBACK_CONTENT_DOMAIN, label="local_git_readback"
    )
    _require_equal(
        readback["authority_effect"], AUTHORITY_EFFECT, "readback_authority_effect"
    )
    _require_equal(readback["signed"], False, "readback_signed")
    _require_equal(
        readback["may_satisfy_remote_repository_binding"], False, "readback_remote_gate"
    )
    _require_equal(
        readback["may_satisfy_steward_decision_gate"], False, "readback_steward_gate"
    )
    _require_equal(readback["permissions_opened_count"], 0, "readback_permissions")


def compile_validation_report(
    *,
    contract: dict[str, Any],
    requests: list[dict[str, Any]],
    readback: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        "CANDIDATE_PACKET_RAW_CONTENT_ARTIFACT_AND_EXACT7_REPLAY",
        "R14_HANDOFF_AND_CLOSED_SCHEMA_BUNDLE_BINDING",
        "EXACT2_REQUEST_ROLE_AND_TARGET_EQUALITY",
        "EXACT160_WHOLE_DEFINITION_BINDING",
        "EXACT10_TARGET_MANIFEST_WITH_ZERO_PREFILLED_DISPOSITIONS",
        "REQUEST_RESPONSE_STRUCTURAL_SEPARATION",
        "ALL_ACTUAL_ENDPOINT_REPOSITORY_REVIEWER_DECISION_AND_SIGNATURE_FIELDS_NULL",
        "TWO_LOCAL_GIT_ROOT_DIR_COMMON_DIR_AND_OBJECT_DIR_IDENTITIES_DISTINCT",
        "EACH_HEAD_SINGLE_PARENT_MAIN_ANCESTRY_AND_CLEAN_WORKTREE",
        "EACH_COMMITTED_CANDIDATE_SUBTREE_EXACT7_AND_SOURCE_BYTES_EQUAL",
        "CROSS_REPOSITORY_EXACT7_BLOB_BYTES_EQUAL_WITHOUT_HARDLINK_OVERLAP",
        "ZERO_REMOTE_ZERO_ALTERNATE_ZERO_GIT_MUTATION_ZERO_NETWORK",
        "RAW_GIT_OBJECT_GRAPH_WITH_REPLACE_SHALLOW_AND_GRAFTS_FORBIDDEN",
        "NO_STEWARD_OS_HOST_OOS_SKILL_RAG_CANONICAL_RUNTIME_OR_DEPLOYMENT_AUTHORITY",
    ]
    core = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_status": "LOCAL_REVIEW_HANDOFF_VALIDATION_PASS__ALL_EXTERNAL_AUTHORITY_UNBOUND_BLOCKING",
        "handoff_contract_content_sha256": contract["content_sha256"],
        "ordered_request_content_sha256": [
            request["content_sha256"] for request in requests
        ],
        "local_git_readback_content_sha256": readback["content_sha256"],
        "ordered_check_count": len(checks),
        "ordered_checks": [
            {"ordinal": ordinal, "check_id": check, "result": "PASS"}
            for ordinal, check in enumerate(checks)
        ],
        "external_submission_performed": False,
        "steward_review_or_decision_performed": False,
        "signature_or_crypto_execution_performed": False,
        "os_activation_performed": False,
        "host_access_or_authorization_performed": False,
        "oos_accessed": False,
        "skill_rag_runtime_accessed": False,
        "canonical_memory_accessed_or_written": False,
        "runtime_or_deployment_performed": False,
        "signed": False,
        "candidate_only": True,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REPORT_CONTENT_DOMAIN)


def _dependency_row(
    path: Path, *, ordinal: int, role: str, expected_sha: str
) -> dict[str, Any]:
    resolved = Path(path).resolve(strict=True)
    metadata = resolved.lstat()
    _require(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_nlink == 1,
        f"unsafe_dependency:{role}",
    )
    size, digest = _sha256_file(resolved)
    _require_equal(digest, expected_sha, f"dependency_sha:{role}")
    return {
        "ordinal": ordinal,
        "role": role,
        "bytes": size,
        "sha256": digest,
        "is_operating_authority": False,
        "may_authorize_external_submission_or_steward_action": False,
    }


def _compile_packet_manifest(
    *,
    artifact_rows: list[dict[str, Any]],
    dependency_rows: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    readback: dict[str, Any],
) -> dict[str, Any]:
    _require_equal(
        [row["ordinal"] for row in artifact_rows], list(range(6)), "artifact_ordinals"
    )
    artifact_commitment = hashlib.sha256(
        PACKET_ARTIFACT_MANIFEST_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in artifact_rows)
    ).hexdigest()
    core = {
        "schema_id": PACKET_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": PACKET_ID,
        "manifest_status": "PORTABLE_REVIEW_REQUEST_PREPARED__LOCAL_REPOSITORY_EVIDENCE_ONLY__ALL_EXTERNAL_AUTHORITY_UNBOUND_BLOCKING",
        "direct_predecessor_candidate_packet_manifest_raw_sha256": CANDIDATE_PACKET_MANIFEST_RAW_SHA256,
        "revision_predecessor_handoff_packet_manifest_raw_sha256": R2_HANDOFF_PACKET_MANIFEST_RAW_SHA256,
        "revision_predecessor_handoff_packet_content_sha256": R2_HANDOFF_PACKET_CONTENT_SHA256,
        "revision_reason": "RAW_GIT_OBJECT_GRAPH_HARDENING__REPLACE_SHALLOW_AND_GRAFTS_FORBIDDEN",
        "artifact_count": 6,
        "ordered_artifacts": artifact_rows,
        "artifact_manifest_commitment_sha256": artifact_commitment,
        "dependency_count": len(dependency_rows),
        "ordered_dependencies": dependency_rows,
        "request_count": 2,
        "ordered_request_content_sha256": [
            request["content_sha256"] for request in requests
        ],
        "local_git_readback_content_sha256": readback["content_sha256"],
        "local_repository_observation_count": 2,
        "verified_external_submission_endpoint_count": 0,
        "remote_repository_binding_count": 0,
        "ontology_steward_signed_decision_count": 0,
        "reference_steward_signed_decision_count": 0,
        "os_sealed_activation_count": 0,
        "host_authorization_count": 0,
        "external_submission_allowed": False,
        "formal_construction_allowed": False,
        "fixture_or_crypto_execution_allowed": False,
        "oos_allowed": False,
        "skill_rag_runtime_allowed": False,
        "canonical_memory_read_or_write_allowed": False,
        "runtime_or_deployment_allowed": False,
        "owner_chat_may_satisfy_contract_gate": False,
        "signed": False,
        "candidate_only": True,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PACKET_CONTENT_DOMAIN)


def _write_bytes_once(root: Path, name: str, payload: bytes) -> Path:
    _require(Path(name).name == name and name not in {"", ".", ".."}, "bad_output_name")
    descriptor = os.open(
        root / name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return root / name


def _compile_all(
    *,
    candidate_manifest_path: Path,
    r14_manifest_path: Path,
    r14_review_manifest_path: Path,
    h1_manifest_path: Path,
    h1_review_manifest_path: Path,
    revision_predecessor_manifest_path: Path,
    ontology_repo: Path,
    reference_repo: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    candidate_manifest_path = Path(candidate_manifest_path).resolve(strict=True)
    candidate_root = candidate_manifest_path.parent
    validate_candidate_definition_packet(
        candidate_manifest_path,
        r14_manifest_path=r14_manifest_path,
        r14_review_manifest_path=r14_review_manifest_path,
        h1_manifest_path=h1_manifest_path,
        h1_review_manifest_path=h1_review_manifest_path,
    )
    gc.collect()
    candidate_source_rows = _candidate_source_rows(candidate_root)
    candidate_payloads = _candidate_payloads(
        candidate_root, source_rows=candidate_source_rows
    )
    r14_bindings = _load_r14_review_bindings(r14_manifest_path)
    review_target = _review_target(
        candidate_payloads=candidate_payloads,
        r14_bindings=r14_bindings,
    )
    generation_raw_sha = next(
        row["sha256"]
        for row in candidate_source_rows
        if row["role"] == "R14_GENERATION_SUCCESSOR"
    )
    review_target["candidate_definition_generation_raw_sha256"] = generation_raw_sha
    contract = compile_handoff_contract(
        review_target=review_target, candidate_source_rows=candidate_source_rows
    )
    requests = compile_unsigned_requests(contract=contract, review_target=review_target)
    schema = compile_exact2_request_schema(requests)
    readback = compile_local_git_readback(
        ontology_repo=ontology_repo,
        reference_repo=reference_repo,
        source_rows=candidate_source_rows,
        review_target=review_target,
    )
    validate_compiled_handoff(
        contract=contract, schema=schema, requests=requests, readback=readback
    )
    report = compile_validation_report(
        contract=contract, requests=requests, readback=readback
    )
    revision_predecessor, revision_predecessor_raw = _strict_object(
        revision_predecessor_manifest_path
    )
    _require_equal(
        hashlib.sha256(revision_predecessor_raw).hexdigest(),
        R2_HANDOFF_PACKET_MANIFEST_RAW_SHA256,
        "r2_revision_predecessor_raw_sha256",
    )
    _require_equal(
        revision_predecessor.get("content_sha256"),
        R2_HANDOFF_PACKET_CONTENT_SHA256,
        "r2_revision_predecessor_content_sha256",
    )
    dependencies = [
        _dependency_row(
            Path(r14_manifest_path),
            ordinal=0,
            role="R14_NORMATIVE_MANIFEST",
            expected_sha=R14_MANIFEST_RAW_SHA256,
        ),
        _dependency_row(
            Path(r14_review_manifest_path),
            ordinal=1,
            role="R14_DESIGN_REVIEW_MANIFEST",
            expected_sha=R14_REVIEW_MANIFEST_RAW_SHA256,
        ),
        _dependency_row(
            Path(h1_manifest_path),
            ordinal=2,
            role="H1_READINESS_MANIFEST",
            expected_sha=H1_MANIFEST_RAW_SHA256,
        ),
        _dependency_row(
            Path(h1_review_manifest_path),
            ordinal=3,
            role="H1_DESIGN_REVIEW_MANIFEST",
            expected_sha=H1_REVIEW_MANIFEST_RAW_SHA256,
        ),
        _dependency_row(
            candidate_manifest_path,
            ordinal=4,
            role="CANDIDATE_DEFINITION_GENERATION_PACKET_MANIFEST",
            expected_sha=CANDIDATE_PACKET_MANIFEST_RAW_SHA256,
        ),
        _dependency_row(
            Path(revision_predecessor_manifest_path),
            ordinal=5,
            role="R2_LOCAL_HANDOFF_REVISION_PREDECESSOR_MANIFEST",
            expected_sha=R2_HANDOFF_PACKET_MANIFEST_RAW_SHA256,
        ),
    ]
    return contract, schema, requests, readback, report, dependencies


def _validate_packet_against_compiled(
    packet_manifest_path: Path,
    *,
    contract: dict[str, Any],
    schema: dict[str, Any],
    requests: list[dict[str, Any]],
    readback: dict[str, Any],
    report: dict[str, Any],
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    packet_manifest_path = Path(packet_manifest_path).resolve(strict=True)
    _require_equal(
        packet_manifest_path.name, "packet_manifest.json", "packet_manifest_name"
    )
    root = packet_manifest_path.parent
    artifacts = [
        (
            "00_unsigned_review_handoff_contract.json",
            "UNSIGNED_REVIEW_HANDOFF_CONTRACT",
            contract,
        ),
        (
            "01_closed_exact2_unsigned_request.schema.json",
            "CLOSED_EXACT2_UNSIGNED_REQUEST_SCHEMA",
            schema,
        ),
        (
            "02_ontology_steward_review_request.json",
            "ONTOLOGY_UNSIGNED_REVIEW_REQUEST",
            requests[0],
        ),
        (
            "03_reference_steward_review_request.json",
            "REFERENCE_UNSIGNED_REVIEW_REQUEST",
            requests[1],
        ),
        (
            "04_local_git_delivery_readback.json",
            "NONAUTHORITATIVE_LOCAL_GIT_READBACK",
            readback,
        ),
        ("05_review_handoff_validation_report.json", "LOCAL_VALIDATION_REPORT", report),
    ]
    expected_names = {"packet_manifest.json", *(name for name, _, _ in artifacts)}
    actual_names: set[str] = set()
    for path in root.iterdir():
        metadata = path.lstat()
        _require(
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_nlink == 1,
            f"unsafe_packet_entry:{path.name}",
        )
        actual_names.add(path.name)
    _require_equal(actual_names, expected_names, "packet_exact7_closure")
    artifact_rows: list[dict[str, Any]] = []
    for ordinal, (name, role, expected_payload) in enumerate(artifacts):
        payload, raw = _strict_object(root / name)
        _require_equal(
            payload, expected_payload, f"packet_artifact_closed_equality:{name}"
        )
        artifact_rows.append(
            {
                "ordinal": ordinal,
                "role": role,
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest, _ = _strict_object(packet_manifest_path)
    _verify_content(manifest, domain=PACKET_CONTENT_DOMAIN, label="packet_manifest")
    expected_manifest = _compile_packet_manifest(
        artifact_rows=artifact_rows,
        dependency_rows=dependencies,
        requests=requests,
        readback=readback,
    )
    _require_equal(manifest, expected_manifest, "packet_manifest_closed_equality")
    return manifest


def validate_dual_steward_review_handoff_packet(
    packet_manifest_path: Path,
    *,
    candidate_manifest_path: Path,
    r14_manifest_path: Path,
    r14_review_manifest_path: Path,
    h1_manifest_path: Path,
    h1_review_manifest_path: Path,
    revision_predecessor_manifest_path: Path,
    ontology_repo: Path,
    reference_repo: Path,
) -> dict[str, Any]:
    contract, schema, requests, readback, report, dependencies = _compile_all(
        candidate_manifest_path=candidate_manifest_path,
        r14_manifest_path=r14_manifest_path,
        r14_review_manifest_path=r14_review_manifest_path,
        h1_manifest_path=h1_manifest_path,
        h1_review_manifest_path=h1_review_manifest_path,
        revision_predecessor_manifest_path=revision_predecessor_manifest_path,
        ontology_repo=ontology_repo,
        reference_repo=reference_repo,
    )
    return _validate_packet_against_compiled(
        packet_manifest_path,
        contract=contract,
        schema=schema,
        requests=requests,
        readback=readback,
        report=report,
        dependencies=dependencies,
    )


def write_dual_steward_review_handoff_packet(
    output_root: Path,
    *,
    candidate_manifest_path: Path,
    r14_manifest_path: Path,
    r14_review_manifest_path: Path,
    h1_manifest_path: Path,
    h1_review_manifest_path: Path,
    revision_predecessor_manifest_path: Path,
    ontology_repo: Path,
    reference_repo: Path,
) -> dict[str, Any]:
    contract, schema, requests, readback, report, dependencies = _compile_all(
        candidate_manifest_path=candidate_manifest_path,
        r14_manifest_path=r14_manifest_path,
        r14_review_manifest_path=r14_review_manifest_path,
        h1_manifest_path=h1_manifest_path,
        h1_review_manifest_path=h1_review_manifest_path,
        revision_predecessor_manifest_path=revision_predecessor_manifest_path,
        ontology_repo=ontology_repo,
        reference_repo=reference_repo,
    )
    artifacts = [
        (
            "00_unsigned_review_handoff_contract.json",
            "UNSIGNED_REVIEW_HANDOFF_CONTRACT",
            contract,
        ),
        (
            "01_closed_exact2_unsigned_request.schema.json",
            "CLOSED_EXACT2_UNSIGNED_REQUEST_SCHEMA",
            schema,
        ),
        (
            "02_ontology_steward_review_request.json",
            "ONTOLOGY_UNSIGNED_REVIEW_REQUEST",
            requests[0],
        ),
        (
            "03_reference_steward_review_request.json",
            "REFERENCE_UNSIGNED_REVIEW_REQUEST",
            requests[1],
        ),
        (
            "04_local_git_delivery_readback.json",
            "NONAUTHORITATIVE_LOCAL_GIT_READBACK",
            readback,
        ),
        ("05_review_handoff_validation_report.json", "LOCAL_VALIDATION_REPORT", report),
    ]
    root = Path(output_root)
    _require(
        root.is_absolute()
        and root.name not in {"", ".", ".."}
        and ".." not in root.parts,
        "output_root_invalid",
    )
    parent = root.parent.resolve(strict=True)
    parent_descriptor = _open_absolute_directory_fd(parent)
    staging_descriptor: int | None = None
    try:
        _require(
            not _entry_exists_at(parent_descriptor, root.name), "output_root_exists"
        )
        staging_name = _create_staging_directory(parent_descriptor)
        staging_root = parent / staging_name
        staging_descriptor = os.open(
            staging_name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        pinned = os.fstat(staging_descriptor)
        _require(
            stat.S_ISDIR(pinned.st_mode) and not stat.S_IMODE(pinned.st_mode) & 0o077,
            "staging_not_private",
        )
        for name, _, payload in artifacts:
            write_workspace_json_once(staging_root, name, payload)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role, _) in enumerate(artifacts)
        ]
        manifest = _compile_packet_manifest(
            artifact_rows=rows,
            dependency_rows=dependencies,
            requests=requests,
            readback=readback,
        )
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        _validate_packet_against_compiled(
            staging_root / "packet_manifest.json",
            contract=contract,
            schema=schema,
            requests=requests,
            readback=readback,
            report=report,
            dependencies=dependencies,
        )
        _validate_staging_closure(
            staging_descriptor,
            expected_names={"packet_manifest.json", *(row["path"] for row in rows)},
        )
        current = os.stat(staging_name, dir_fd=parent_descriptor, follow_symlinks=False)
        _require_equal(
            (current.st_dev, current.st_ino),
            (pinned.st_dev, pinned.st_ino),
            "staging_identity_changed",
        )
        _require(not _entry_exists_at(parent_descriptor, root.name), "output_root_race")
        os.fsync(staging_descriptor)
        _atomic_publish_directory_noreplace_at(
            parent_descriptor, staging_name, root.name
        )
        os.fsync(parent_descriptor)
        return manifest
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        os.close(parent_descriptor)
