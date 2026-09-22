from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from factor_factory.epistemic_binding import (
    _atomic_publish_directory_noreplace_at,
    _entry_exists_at,
    _open_absolute_directory_fd,
)
from factor_factory.epistemic_host_bootstrap_b0b import (
    _create_staging_directory,
    _stable_file_row,
    _validate_staging_closure,
)
from factor_factory.epistemic_host_bootstrap_expectation_proposal import (
    E1_R13_SCHEMA_BUNDLE_RAW_SHA256,
)
from factor_factory.research_org.contracts import (
    strict_json_loads,
    write_workspace_json_once,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256

SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"

R14_MANIFEST_RAW_SHA256 = (
    "ed6ae69cd63062febfc055939c65bbcf233b02f1d6b42abf207fd086f1a53fc5"
)
R14_MANIFEST_CONTENT_SHA256 = (
    "72773e5e2348d63c7a555a1b0f510e593567dbfa078d9f6442c82f820350b34e"
)
R14_ARTIFACT_COMMITMENT_SHA256 = (
    "7c1be90b46a0d931358105df68214e9974938c5062819637558465cf196ad3b6"
)
R14_PACKET_ID = "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R14"
R14_REVIEW_MANIFEST_RAW_SHA256 = (
    "f53bea0acd279f03e9bce9bc707e747b5e7f300e48c1247444011b507d5d85aa"
)
H1_MANIFEST_RAW_SHA256 = (
    "818a3755aa4e580f70d9b3b8305f9ac293554c251d386b4a45d11e7af6268951"
)
H1_REVIEW_MANIFEST_RAW_SHA256 = (
    "70da6cd804a885b5c807d66746bd7572f23710c014d19b1ce8b729f7a14b9431"
)

CONTRACT_SCHEMA_ID = (
    "factorforge_epistemic_candidate_definition_derivation_contract_s1_v1"
)
DEFINITION_SCHEMA_ID = "factorforge_epistemic_candidate_definition_bytes_s1_v1"
BYTES_MANIFEST_SCHEMA_ID = (
    "factorforge_epistemic_candidate_definition_bytes_manifest_s1_v1"
)
GENERATION_SCHEMA_ID = "factorforge_epistemic_candidate_definition_generation_v1"
REPORT_SCHEMA_ID = "factorforge_epistemic_candidate_definition_generation_report_s1_v1"
PACKET_SCHEMA_ID = "factorforge_epistemic_candidate_definition_generation_packet_s1_v1"
PACKET_ID = "FF_EPISTEMIC_CANDIDATE_DEFINITION_GENERATION_S1_20260828_R1"

CONTRACT_CONTENT_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_DERIVATION_CONTRACT_V1"
DEFINITION_ROW_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_ROW_V1"
DEFINITION_ROW_MANIFEST_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_ROW_MANIFEST_V1"
DEFINITION_CONTENT_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_BYTES_V1"
DEFINITION_FILE_ROW_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_FILE_ROW_V1"
DEFINITION_BYTES_MANIFEST_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_BYTES_MANIFEST_V1"
DEFINITION_BYTES_MANIFEST_CONTENT_DOMAIN = (
    "FF_E1_S1_CANDIDATE_DEFINITION_BYTES_MANIFEST_CONTENT_V1"
)
GENERATION_BASIS_DOMAIN = "FF_E1_CANDIDATE_DEFINITION_GENERATION_SUCCESSOR_BASIS_V1"
GENERATION_CONTENT_DOMAIN = "FF_E1_CANDIDATE_DEFINITION_GENERATION_CONTENT_V1"
REPORT_CONTENT_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_GENERATION_REPORT_V1"
PACKET_ARTIFACT_MANIFEST_DOMAIN = (
    "FF_E1_S1_CANDIDATE_DEFINITION_PACKET_ARTIFACT_MANIFEST_V1"
)
PACKET_CONTENT_DOMAIN = "FF_E1_S1_CANDIDATE_DEFINITION_PACKET_V1"

R14_GENERATION_BASIS_FIELDS = (
    "predecessor_stage1b_schema_raw_sha256",
    "predecessor_b0b1_r2_manifest_raw_sha256",
    "predecessor_e1_r3_manifest_raw_sha256",
    "predecessor_e1_r4_manifest_raw_sha256",
    "predecessor_e1_r4_packet_content_sha256",
    "predecessor_e1_r5_manifest_raw_sha256",
    "predecessor_e1_r5_packet_content_sha256",
    "predecessor_e1_r6_manifest_raw_sha256",
    "predecessor_e1_r6_packet_content_sha256",
    "predecessor_e1_r7_manifest_raw_sha256",
    "predecessor_e1_r7_packet_content_sha256",
    "predecessor_e1_r8_manifest_raw_sha256",
    "predecessor_e1_r8_packet_content_sha256",
    "predecessor_e1_r9_manifest_raw_sha256",
    "predecessor_e1_r9_packet_content_sha256",
    "e1_r9_review_manifest_raw_sha256",
    "e1_r9_review_manifest_content_sha256",
    "e1_r9_review_artifact_manifest_commitment_sha256",
    "e1_r9_review_aggregate_verdict",
    "e1_r9_review_is_revision_dependency_not_authority",
    "predecessor_e1_r10_manifest_raw_sha256",
    "predecessor_e1_r10_packet_content_sha256",
    "e1_r10_review_manifest_raw_sha256",
    "e1_r10_review_manifest_content_sha256",
    "e1_r10_review_artifact_manifest_commitment_sha256",
    "e1_r10_review_aggregate_verdict",
    "e1_r10_review_is_revision_dependency_not_authority",
    "predecessor_e1_r11_manifest_raw_sha256",
    "predecessor_e1_r11_packet_content_sha256",
    "e1_r11_review_manifest_raw_sha256",
    "e1_r11_review_manifest_content_sha256",
    "e1_r11_review_artifact_manifest_commitment_sha256",
    "e1_r11_review_aggregate_verdict",
    "e1_r11_review_is_revision_dependency_not_authority",
    "predecessor_e1_r12_manifest_raw_sha256",
    "predecessor_e1_r12_packet_content_sha256",
    "e1_r12_review_manifest_raw_sha256",
    "e1_r12_review_manifest_content_sha256",
    "e1_r12_review_artifact_manifest_commitment_sha256",
    "e1_r12_review_aggregate_verdict",
    "e1_r12_review_is_revision_dependency_not_authority",
    "predecessor_e1_r13_manifest_raw_sha256",
    "predecessor_e1_r13_packet_content_sha256",
    "e1_r13_review_manifest_raw_sha256",
    "e1_r13_review_manifest_content_sha256",
    "e1_r13_review_artifact_manifest_commitment_sha256",
    "e1_r13_review_aggregate_verdict",
    "e1_r13_review_is_revision_dependency_not_authority",
    "e1_r14_packet_manifest_raw_sha256",
    "e1_r14_packet_content_sha256",
    "candidate_definition_generation_target_id",
    "candidate_definition_generation_target_content_sha256",
    "semantic_derivation_registry_content_sha256",
    "semantic_derivation_manifest_sha256",
    "closed_materialization_design_manifest_sha256",
    "expectation_proposal_content_sha256",
    "candidate_assignment_manifest_sha256",
    "selected_branch_manifest_sha256",
    "branch_selection_target_manifest_sha256",
    "e1_r13_closed_schema_bundle_artifact_raw_sha256",
    "closed_predecessor_count",
    "review_dependency_count",
)


class CandidateDefinitionGenerationError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(";".join(reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise CandidateDefinitionGenerationError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise CandidateDefinitionGenerationError(
            [f"{label}:expected={expected!r}:actual={actual!r}"]
        )


def _with_content_sha(payload: dict[str, Any], *, domain: str) -> dict[str, Any]:
    _require("content_sha256" not in payload, f"content_sha_already_present:{domain}")
    result = dict(payload)
    result["content_sha256"] = framed_sha256(domain, payload)
    return result


def _strict_object(path: Path) -> tuple[dict[str, Any], bytes]:
    before = path.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"unsafe_source_file:{path}",
    )
    raw = path.read_bytes()
    after = path.lstat()
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"source_changed_during_read:{path}",
    )
    payload = strict_json_loads(raw, label=str(path))
    _require(isinstance(payload, dict), f"json_object_required:{path}")
    return payload, raw


def _sha256_file(path: Path) -> tuple[int, str]:
    before = path.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"unsafe_source_file:{path}",
    )
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    after = path.lstat()
    _require_equal(size, before.st_size, f"source_size_changed:{path}")
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"source_changed_during_hash:{path}",
    )
    return size, digest.hexdigest()


def _verify_content(payload: dict[str, Any], *, domain: str, label: str) -> None:
    core = dict(payload)
    actual = core.pop("content_sha256", None)
    _require_equal(actual, framed_sha256(domain, core), f"{label}_content_sha256")


def load_and_verify_r14_packet(manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest, raw = _strict_object(manifest_path)
    _require_equal(
        hashlib.sha256(raw).hexdigest(),
        R14_MANIFEST_RAW_SHA256,
        "r14_manifest_raw_sha256",
    )
    _require_equal(manifest.get("packet_id"), R14_PACKET_ID, "r14_packet_id")
    _verify_content(
        manifest,
        domain="FF_B0B_EXPECTATION_PROPOSAL_PACKET_V1",
        label="r14_manifest",
    )
    _require_equal(
        manifest.get("content_sha256"),
        R14_MANIFEST_CONTENT_SHA256,
        "r14_manifest_content",
    )
    rows = manifest.get("ordered_artifacts")
    _require(isinstance(rows, list) and len(rows) == 7, "r14_exact7_artifacts")
    parent = manifest_path.parent
    resolved: dict[str, dict[str, Any]] = {}
    raw_digests: list[str] = []
    expected_ordinals = list(range(7))
    _require_equal(
        [row.get("ordinal") for row in rows], expected_ordinals, "r14_artifact_ordinals"
    )
    for row in rows:
        name = row.get("path")
        _require(
            isinstance(name, str)
            and name not in {"", ".", ".."}
            and Path(name).name == name,
            "r14_artifact_path_invalid",
        )
        artifact_path = parent / name
        size, digest = _sha256_file(artifact_path)
        _require_equal(size, row.get("bytes"), f"r14_artifact_bytes:{name}")
        _require_equal(digest, row.get("sha256"), f"r14_artifact_sha:{name}")
        raw_digests.append(digest)
        if row.get("role") in {
            "SEMANTIC_DERIVATION_REGISTRY",
            "EXPECTATION_PROPOSAL",
            "CANDIDATE_DEFINITION_GENERATION_TARGET",
            "DUAL_GIT_HANDOFF",
        }:
            payload, payload_raw = _strict_object(artifact_path)
            _require_equal(
                hashlib.sha256(payload_raw).hexdigest(),
                digest,
                f"r14_loaded_sha:{name}",
            )
            resolved[str(row["role"])] = payload
    recomputed = hashlib.sha256(
        b"FF_B0B_EXPECTATION_PROPOSAL_ARTIFACT_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(value) for value in raw_digests)
    ).hexdigest()
    _require_equal(
        recomputed,
        manifest.get("artifact_manifest_commitment_sha256"),
        "r14_artifact_commitment",
    )
    _require_equal(
        recomputed, R14_ARTIFACT_COMMITMENT_SHA256, "r14_frozen_artifact_commitment"
    )
    _require_equal(
        set(resolved),
        {
            "SEMANTIC_DERIVATION_REGISTRY",
            "EXPECTATION_PROPOSAL",
            "CANDIDATE_DEFINITION_GENERATION_TARGET",
            "DUAL_GIT_HANDOFF",
        },
        "r14_required_artifacts",
    )
    semantic = resolved["SEMANTIC_DERIVATION_REGISTRY"]
    proposal = resolved["EXPECTATION_PROPOSAL"]
    target = resolved["CANDIDATE_DEFINITION_GENERATION_TARGET"]
    handoff = resolved["DUAL_GIT_HANDOFF"]
    _verify_content(
        semantic,
        domain="FF_B0B_EXPECTATION_SEMANTIC_DERIVATION_REGISTRY_V1",
        label="semantic_registry",
    )
    _verify_content(
        proposal,
        domain="FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_V1",
        label="expectation_proposal",
    )
    _verify_content(
        target,
        domain="FF_E1_CANDIDATE_DEFINITION_GENERATION_TARGET_V1",
        label="definition_target",
    )
    _verify_content(
        handoff,
        domain="FF_B0B_EXPECTATION_DUAL_GIT_HANDOFF_V1",
        label="dual_git_handoff",
    )
    _require_equal(
        handoff.get("definition_generation_target_content_sha256"),
        target.get("content_sha256"),
        "handoff_target_join",
    )
    _require_equal(
        handoff.get("successor_order", [None])[0],
        "R14_PACKET_RAW_SHA256_BOUND_CANDIDATE_DEFINITION_GENERATION",
        "handoff_candidate_generation_is_gate0",
    )
    _require_equal(
        handoff["closed_steward_contract_refs"].get(
            "candidate_definition_generation_successor_schema_pointer"
        ),
        "/schemas/candidate_definition_generation_successor",
        "handoff_generation_schema_pointer",
    )
    for key, expected in (
        ("future_candidate_definition_generation_id", None),
        ("future_candidate_definition_generation_content_sha256", None),
        ("approved", False),
        ("signed", False),
        ("is_definition", False),
        ("may_activate", False),
        ("may_materialize_or_execute", False),
        ("authority_effect", AUTHORITY_EFFECT),
    ):
        _require_equal(target.get(key), expected, f"r14_target_boundary:{key}")
    resolved["PACKET_MANIFEST"] = manifest
    return resolved


def compile_generation_basis(source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = source["PACKET_MANIFEST"]
    target = source["CANDIDATE_DEFINITION_GENERATION_TARGET"]
    handoff = source["DUAL_GIT_HANDOFF"]
    target_basis = target["generation_target_basis"]
    review_target = handoff["closed_review_target"]
    basis: dict[str, Any] = {
        "predecessor_stage1b_schema_raw_sha256": target_basis[
            "source_stage1b_schema_raw_sha256"
        ],
        "predecessor_b0b1_r2_manifest_raw_sha256": target_basis[
            "source_b0b1_r2_manifest_raw_sha256"
        ],
        "predecessor_e1_r3_manifest_raw_sha256": target_basis[
            "predecessor_e1_r3_manifest_raw_sha256"
        ],
    }
    for revision in range(4, 9):
        basis[f"predecessor_e1_r{revision}_manifest_raw_sha256"] = target_basis[
            f"predecessor_e1_r{revision}_manifest_raw_sha256"
        ]
        basis[f"predecessor_e1_r{revision}_packet_content_sha256"] = review_target[
            f"predecessor_e1_r{revision}_packet_content_sha256"
        ]
    basis["predecessor_e1_r9_manifest_raw_sha256"] = target_basis[
        "predecessor_e1_r9_manifest_raw_sha256"
    ]
    basis["predecessor_e1_r9_packet_content_sha256"] = target_basis[
        "predecessor_e1_r9_packet_content_sha256"
    ]
    for revision in range(9, 14):
        if revision >= 10:
            basis[f"predecessor_e1_r{revision}_manifest_raw_sha256"] = target_basis[
                f"predecessor_e1_r{revision}_manifest_raw_sha256"
            ]
            basis[f"predecessor_e1_r{revision}_packet_content_sha256"] = target_basis[
                f"predecessor_e1_r{revision}_packet_content_sha256"
            ]
        for suffix in (
            "manifest_raw_sha256",
            "manifest_content_sha256",
            "artifact_manifest_commitment_sha256",
            "aggregate_verdict",
            "is_revision_dependency_not_authority",
        ):
            key = f"e1_r{revision}_review_{suffix}"
            basis[key] = target_basis[key]
    basis.update(
        {
            "e1_r14_packet_manifest_raw_sha256": R14_MANIFEST_RAW_SHA256,
            "e1_r14_packet_content_sha256": manifest["content_sha256"],
            "candidate_definition_generation_target_id": target[
                "candidate_definition_generation_target_id"
            ],
            "candidate_definition_generation_target_content_sha256": target[
                "content_sha256"
            ],
            "semantic_derivation_registry_content_sha256": source[
                "SEMANTIC_DERIVATION_REGISTRY"
            ]["content_sha256"],
            "semantic_derivation_manifest_sha256": source[
                "SEMANTIC_DERIVATION_REGISTRY"
            ]["semantic_derivation_manifest_sha256"],
            "closed_materialization_design_manifest_sha256": source[
                "SEMANTIC_DERIVATION_REGISTRY"
            ]["closed_materialization_design_manifest_sha256"],
            "expectation_proposal_content_sha256": source["EXPECTATION_PROPOSAL"][
                "content_sha256"
            ],
            "candidate_assignment_manifest_sha256": source["EXPECTATION_PROPOSAL"][
                "candidate_assignment_manifest_sha256"
            ],
            "selected_branch_manifest_sha256": target[
                "selected_branch_manifest_sha256"
            ],
            "branch_selection_target_manifest_sha256": target[
                "branch_selection_target_manifest_sha256"
            ],
            "e1_r13_closed_schema_bundle_artifact_raw_sha256": (
                E1_R13_SCHEMA_BUNDLE_RAW_SHA256
            ),
            "closed_predecessor_count": 13,
            "review_dependency_count": 5,
        }
    )
    _require_equal(
        set(basis), set(R14_GENERATION_BASIS_FIELDS), "generation_basis_fields"
    )
    return basis


def compile_derivation_contract(source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target = source["CANDIDATE_DEFINITION_GENERATION_TARGET"]
    handoff = source["DUAL_GIT_HANDOFF"]
    core = {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "contract_status": "CANDIDATE_CONSTRUCTION_SUCCESSOR__EXTERNAL_REVIEW_REQUIRED",
        "direct_predecessor_manifest_raw_sha256": R14_MANIFEST_RAW_SHA256,
        "direct_predecessor_packet_content_sha256": R14_MANIFEST_CONTENT_SHA256,
        "candidate_definition_generation_target_id": target[
            "candidate_definition_generation_target_id"
        ],
        "candidate_definition_generation_target_content_sha256": target[
            "content_sha256"
        ],
        "closed_review_target_sha256": handoff["closed_review_target_sha256"],
        "under_specification_closed": {
            "r14_fields_requiring_unique_derivation": [
                "/definition_bytes_manifest_sha256",
                "/definition_content_sha256",
            ],
            "caller_selected_digest_allowed": False,
            "ambient_default_allowed": False,
            "definition_bytes_manifest_is_exact1": True,
            "definition_content_must_equal_compiled_exact160_content": True,
        },
        "normative_digest_profiles": [
            {
                "ordinal": 0,
                "profile_id": DEFINITION_ROW_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||RFC8785_INTEGER_ONLY(row_without_candidate_definition_row_sha256))",
            },
            {
                "ordinal": 1,
                "profile_id": DEFINITION_ROW_MANIFEST_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||CONCAT(ordered_candidate_definition_row_sha256_as_raw32))",
            },
            {
                "ordinal": 2,
                "profile_id": DEFINITION_CONTENT_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||RFC8785_INTEGER_ONLY(definition_without_content_sha256))",
            },
            {
                "ordinal": 3,
                "profile_id": DEFINITION_FILE_ROW_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||RFC8785_INTEGER_ONLY(file_row_without_file_row_sha256))",
            },
            {
                "ordinal": 4,
                "profile_id": DEFINITION_BYTES_MANIFEST_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||CONCAT(exact1_ordered_file_row_sha256_as_raw32))",
            },
            {
                "ordinal": 5,
                "profile_id": DEFINITION_BYTES_MANIFEST_CONTENT_DOMAIN,
                "formula": "SHA256(UTF8(domain)||0x00||RFC8785_INTEGER_ONLY(manifest_without_content_sha256))",
            },
        ],
        "r14_normative_profile_refs": {
            "generation_schema_pointer": "/schemas/candidate_definition_generation_successor",
            "generation_basis_profile_id": GENERATION_BASIS_DOMAIN,
            "generation_id_profile_id": "FF_E1_CANDIDATE_DEFINITION_GENERATION_ID_V1",
            "generation_content_profile_id": GENERATION_CONTENT_DOMAIN,
            "formula_mirror_authoritative": False,
            "r14_remains_authoritative": True,
        },
        "ordered_compilation_steps": [
            "VERIFY_FROZEN_R14_MANIFEST_AND_EXACT7_ARTIFACT_HASHES",
            "JOIN_EXACT160_TARGET_PROPOSAL_AND_SEMANTIC_ROWS",
            "RECOMPUTE_EXACT160_DEFINITION_ROWS_AND_MANIFEST",
            "COMPILE_R14_EXACT62_GENERATION_BASIS_AND_ID",
            "COMPILE_CANDIDATE_DEFINITION_CONTENT",
            "SERIALIZE_DEFINITION_ONCE_AS_RFC8785_UTF8_PLUS_LF",
            "COMPILE_EXACT1_DEFINITION_BYTES_MANIFEST",
            "COMPILE_R14_EXACT20_GENERATION_SUCCESSOR",
            "VALIDATE_NO_SIGNATURE_ACTIVATION_EXECUTION_OR_AUTHORITY_UPLIFT",
        ],
        "alternate_or_reject_branch_requires_new_successor": True,
        "same_blob_must_be_binary_copied_to_both_independent_repositories": True,
        "external_design_review_required_before_steward_decision_admission": True,
        "steward_decision_or_signature_present": False,
        "host_authorization_present": False,
        "canonical_write_allowed": False,
        "oos_allowed": False,
        "skill_rag_runtime_allowed": False,
        "materialization_or_execution_allowed": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=CONTRACT_CONTENT_DOMAIN)


def _compile_definition_rows(
    source: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    semantic_rows = source["SEMANTIC_DERIVATION_REGISTRY"]["semantic_derivation_rows"]
    proposal_rows = source["EXPECTATION_PROPOSAL"]["candidate_assignment_rows"]
    selected_rows = source["CANDIDATE_DEFINITION_GENERATION_TARGET"][
        "selected_branch_rows"
    ]
    _require_equal(
        (len(semantic_rows), len(proposal_rows), len(selected_rows)),
        (160, 160, 160),
        "exact160_source_rows",
    )
    rows: list[dict[str, Any]] = []
    for ordinal, (semantic, proposal, selected) in enumerate(
        zip(semantic_rows, proposal_rows, selected_rows, strict=True)
    ):
        selected_branch = semantic["closed_branch_universe"][0]
        _require_equal(
            selected["selection_ordinal"], ordinal, f"selection_ordinal:{ordinal}"
        )
        _require_equal(
            proposal["proposal_ordinal"], ordinal, f"proposal_ordinal:{ordinal}"
        )
        _require_equal(
            selected["global_obligation_ordinal"],
            proposal["global_obligation_ordinal"],
            f"global_ordinal_join:{ordinal}",
        )
        _require_equal(
            selected["semantic_derivation_row_sha256"],
            semantic["semantic_derivation_row_sha256"],
            f"semantic_row_join:{ordinal}",
        )
        _require_equal(
            selected["candidate_assignment_row_sha256"],
            proposal["candidate_assignment_row_sha256"],
            f"assignment_row_join:{ordinal}",
        )
        _require_equal(
            selected["selected_candidate_branch_id"],
            proposal["selected_candidate_branch_id"],
            f"selected_branch_join:{ordinal}",
        )
        exact_join_pairs = (
            (
                selected["selected_candidate_branch_id"],
                selected_branch["branch_id"],
                "selected_branch_id",
            ),
            (
                selected["selected_candidate_branch_content_sha256"],
                selected_branch["content_sha256"],
                "selected_branch_content",
            ),
            (
                selected["selected_materialization_design_content_sha256"],
                selected_branch["materialization_design"]["content_sha256"],
                "selected_materialization_design",
            ),
            (
                proposal["source_contract_ordinal"],
                semantic["source_contract_ordinal"],
                "source_contract_ordinal",
            ),
            (
                proposal["source_contract_id"],
                semantic["source_contract_id"],
                "source_contract_id",
            ),
            (
                proposal["source_json_pointer"],
                semantic["source_json_pointer"],
                "source_json_pointer",
            ),
            (
                proposal["source_vector_ordinal"],
                semantic["source_vector_ordinal"],
                "source_vector_ordinal",
            ),
            (proposal["vector_name"], semantic["vector_name"], "vector_name"),
            (
                proposal["owning_rule_ordinal"],
                semantic["owning_rule_ordinal"],
                "owning_rule_ordinal",
            ),
            (proposal["owning_rule_id"], semantic["owning_rule_id"], "owning_rule_id"),
            (
                proposal["candidate_verdict"],
                selected_branch["candidate_verdict"],
                "candidate_verdict",
            ),
            (
                proposal["candidate_public_reason_code"],
                selected_branch["candidate_public_reason_code"],
                "candidate_public_reason_code",
            ),
            (
                proposal["selected_resolution_class"],
                selected_branch["resolution_class"],
                "resolution_class",
            ),
            (
                proposal["selected_target_kind"],
                selected_branch["target_kind"],
                "target_kind",
            ),
            (
                proposal["selected_target_selector"],
                selected_branch["target_selector"],
                "target_selector",
            ),
            (
                proposal["selected_target_kind"],
                semantic["target_kind"],
                "semantic_target_kind",
            ),
            (
                proposal["selected_target_selector"],
                semantic["target_selector"],
                "semantic_target_selector",
            ),
            (
                proposal["normative_rule_pointer"],
                semantic["normative_rule_pointer"],
                "normative_rule_pointer",
            ),
            (
                proposal["normative_vector_pointer"],
                semantic["normative_vector_pointer"],
                "normative_vector_pointer",
            ),
            (
                proposal["public_classification_basis"],
                selected_branch["semantic_clause"],
                "semantic_clause",
            ),
            (
                proposal["branch_selection_review_state"],
                semantic["branch_selection_review_state"],
                "branch_selection_review_state",
            ),
            (
                proposal["input_availability_sensitivity"],
                semantic["input_availability_sensitivity"],
                "input_availability_sensitivity",
            ),
        )
        for actual, expected, join_name in exact_join_pairs:
            _require_equal(actual, expected, f"exact160_join:{join_name}:{ordinal}")
        _require_equal(
            semantic["selected_candidate_branch_id"],
            selected_branch["branch_id"],
            f"semantic_selected_branch_id:{ordinal}",
        )
        _require_equal(
            semantic["selected_candidate_verdict"],
            selected_branch["candidate_verdict"],
            f"semantic_selected_verdict:{ordinal}",
        )
        _require_equal(
            semantic["selected_candidate_public_reason_code"],
            selected_branch["candidate_public_reason_code"],
            f"semantic_selected_reason:{ordinal}",
        )
        _require_equal(
            semantic["selected_candidate_resolution_class"],
            selected_branch["resolution_class"],
            f"semantic_selected_resolution:{ordinal}",
        )
        selected_core = {
            key: value
            for key, value in selected.items()
            if key != "selection_row_sha256"
        }
        _require_equal(
            selected["selection_row_sha256"],
            framed_sha256("FF_E1_CANDIDATE_DEFINITION_SELECTION_ROW_V1", selected_core),
            f"selected_row_digest:{ordinal}",
        )
        proposal_core = {
            key: value
            for key, value in proposal.items()
            if key != "candidate_assignment_row_sha256"
        }
        _require_equal(
            proposal["candidate_assignment_row_sha256"],
            framed_sha256(
                "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_ROW_V1", proposal_core
            ),
            f"proposal_row_digest:{ordinal}",
        )
        core = {
            "definition_ordinal": ordinal,
            "global_obligation_ordinal": proposal["global_obligation_ordinal"],
            "source_contract_ordinal": proposal["source_contract_ordinal"],
            "source_contract_id": proposal["source_contract_id"],
            "source_json_pointer": proposal["source_json_pointer"],
            "source_vector_ordinal": proposal["source_vector_ordinal"],
            "vector_name": proposal["vector_name"],
            "owning_rule_ordinal": proposal["owning_rule_ordinal"],
            "owning_rule_id": proposal["owning_rule_id"],
            "candidate_verdict": proposal["candidate_verdict"],
            "candidate_public_reason_code": proposal["candidate_public_reason_code"],
            "branch_selection_review_state": proposal["branch_selection_review_state"],
            "input_availability_sensitivity": proposal[
                "input_availability_sensitivity"
            ],
            "semantic_derivation_row_sha256": selected[
                "semantic_derivation_row_sha256"
            ],
            "candidate_assignment_row_sha256": selected[
                "candidate_assignment_row_sha256"
            ],
            "selected_candidate_branch_id": selected["selected_candidate_branch_id"],
            "selected_candidate_branch_content_sha256": selected[
                "selected_candidate_branch_content_sha256"
            ],
            "selected_materialization_design_content_sha256": selected[
                "selected_materialization_design_content_sha256"
            ],
            "selected_resolution_class": proposal["selected_resolution_class"],
            "selected_target_kind": proposal["selected_target_kind"],
            "selected_target_selector": proposal["selected_target_selector"],
            "normative_rule_pointer": proposal["normative_rule_pointer"],
            "normative_vector_pointer": proposal["normative_vector_pointer"],
            "public_classification_basis": proposal["public_classification_basis"],
        }
        core["candidate_definition_row_sha256"] = framed_sha256(
            DEFINITION_ROW_DOMAIN, core
        )
        rows.append(core)
    selected_manifest = hashlib.sha256(
        b"FF_E1_CANDIDATE_DEFINITION_SELECTION_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(row["selection_row_sha256"]) for row in selected_rows)
    ).hexdigest()
    _require_equal(
        selected_manifest,
        source["CANDIDATE_DEFINITION_GENERATION_TARGET"][
            "selected_branch_manifest_sha256"
        ],
        "selected_branch_manifest_recomputed",
    )
    assignment_manifest = hashlib.sha256(
        b"FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["candidate_assignment_row_sha256"])
            for row in proposal_rows
        )
    ).hexdigest()
    _require_equal(
        assignment_manifest,
        source["EXPECTATION_PROPOSAL"]["candidate_assignment_manifest_sha256"],
        "candidate_assignment_manifest_recomputed",
    )
    _validate_branch_selection_targets(source)
    manifest = hashlib.sha256(
        DEFINITION_ROW_MANIFEST_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(
            bytes.fromhex(row["candidate_definition_row_sha256"]) for row in rows
        )
    ).hexdigest()
    return rows, manifest


def _validate_branch_selection_targets(source: dict[str, dict[str, Any]]) -> None:
    semantic_rows = source["SEMANTIC_DERIVATION_REGISTRY"]["semantic_derivation_rows"]
    target = source["CANDIDATE_DEFINITION_GENERATION_TARGET"]
    actual_targets = target["branch_selection_target_rows"]
    expected_targets: list[dict[str, Any]] = []
    for semantic in semantic_rows:
        if semantic["branch_selection_review_state"] != "REVIEW_REQUIRED":
            continue
        _require_equal(
            len(semantic["closed_branch_universe"]),
            2,
            f"review_required_exact2_branches:{semantic['global_obligation_ordinal']}",
        )
        current, alternate = semantic["closed_branch_universe"]
        core = {
            "branch_selection_ordinal": len(expected_targets),
            "global_obligation_ordinal": semantic["global_obligation_ordinal"],
            "source_contract_ordinal": semantic["source_contract_ordinal"],
            "source_vector_ordinal": semantic["source_vector_ordinal"],
            "semantic_derivation_row_sha256": semantic[
                "semantic_derivation_row_sha256"
            ],
            "current_selected_branch_id": current["branch_id"],
            "current_selected_branch_content_sha256": current["content_sha256"],
            "alternate_branch_id": alternate["branch_id"],
            "alternate_branch_content_sha256": alternate["content_sha256"],
        }
        core["branch_selection_target_row_sha256"] = framed_sha256(
            "FF_E1_BRANCH_SELECTION_TARGET_ROW_V1", core
        )
        expected_targets.append(core)
    _require_equal(len(expected_targets), 10, "derived_exact10_branch_targets")
    _require_equal(
        actual_targets, expected_targets, "branch_selection_targets_closed_equality"
    )
    manifest = hashlib.sha256(
        b"FF_E1_BRANCH_SELECTION_TARGET_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["branch_selection_target_row_sha256"])
            for row in expected_targets
        )
    ).hexdigest()
    _require_equal(
        manifest,
        target["branch_selection_target_manifest_sha256"],
        "branch_selection_target_manifest_recomputed",
    )


def compile_candidate_definition(
    source: dict[str, dict[str, Any]],
    *,
    contract: dict[str, Any],
    generation_basis: dict[str, Any],
) -> dict[str, Any]:
    target = source["CANDIDATE_DEFINITION_GENERATION_TARGET"]
    proposal = source["EXPECTATION_PROPOSAL"]
    semantic = source["SEMANTIC_DERIVATION_REGISTRY"]
    rows, row_manifest = _compile_definition_rows(source)
    basis_sha = framed_sha256(GENERATION_BASIS_DOMAIN, generation_basis)
    generation_id = f"ffexpdef::{basis_sha}"
    core = {
        "schema_id": DEFINITION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "definition_status": "CANDIDATE_DEFINITION__NOT_STEWARD_APPROVED",
        "construction_contract_content_sha256": contract["content_sha256"],
        "r14_packet_manifest_raw_sha256": R14_MANIFEST_RAW_SHA256,
        "r14_packet_content_sha256": R14_MANIFEST_CONTENT_SHA256,
        "candidate_definition_generation_target_id": target[
            "candidate_definition_generation_target_id"
        ],
        "candidate_definition_generation_target_content_sha256": target[
            "content_sha256"
        ],
        "candidate_definition_generation_basis_sha256": basis_sha,
        "candidate_definition_generation_id": generation_id,
        "semantic_derivation_registry_content_sha256": semantic["content_sha256"],
        "semantic_derivation_manifest_sha256": semantic[
            "semantic_derivation_manifest_sha256"
        ],
        "expectation_proposal_content_sha256": proposal["content_sha256"],
        "candidate_assignment_manifest_sha256": proposal[
            "candidate_assignment_manifest_sha256"
        ],
        "selected_branch_manifest_sha256": target["selected_branch_manifest_sha256"],
        "branch_selection_target_manifest_sha256": target[
            "branch_selection_target_manifest_sha256"
        ],
        "closed_materialization_design_manifest_sha256": semantic[
            "closed_materialization_design_manifest_sha256"
        ],
        "definition_row_count": 160,
        "definition_rows": rows,
        "definition_row_manifest_sha256": row_manifest,
        "branch_selection_review_target_count": 10,
        "branch_selection_review_targets": target["branch_selection_target_rows"],
        "candidate_fail_count": proposal["candidate_fail_count"],
        "candidate_blocked_count": proposal["candidate_blocked_count"],
        "branch_selection_review_required_count": proposal[
            "branch_selection_review_required_count"
        ],
        "input_availability_sensitive_row_count": proposal[
            "input_availability_sensitive_row_count"
        ],
        "current_exact160_selection_frozen_for_review": True,
        "alternate_or_reject_requires_new_successor": True,
        "steward_decision_count": 0,
        "active": False,
        "signed": False,
        "candidate_only": True,
        "may_activate": False,
        "may_materialize_or_execute": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=DEFINITION_CONTENT_DOMAIN)


def compile_exact_instance_schema(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": DEFINITION_SCHEMA_ID,
        "title": "R14-bound exact160 candidate definition bytes (candidate only)",
        "type": "object",
        "required": sorted(definition),
        "properties": {key: {"const": value} for key, value in definition.items()},
        "additionalProperties": False,
        "x-factorforge-direct-predecessor-manifest-raw-sha256": (
            R14_MANIFEST_RAW_SHA256
        ),
        "x-factorforge-authority-effect": AUTHORITY_EFFECT,
        "x-factorforge-external-design-review-required": True,
    }


def _definition_serialized_bytes(definition: dict[str, Any]) -> bytes:
    from factor_factory.research_org.rfc8785_canonical import canonicalize

    return canonicalize(definition) + b"\n"


def compile_definition_bytes_manifest(
    definition: dict[str, Any],
    *,
    definition_raw: bytes,
) -> dict[str, Any]:
    file_core = {
        "ordinal": 0,
        "role": "R14_BOUND_EXACT160_CANDIDATE_DEFINITION_BYTES",
        "path": "02_candidate_definition.json",
        "bytes": len(definition_raw),
        "sha256": hashlib.sha256(definition_raw).hexdigest(),
        "content_sha256": definition["content_sha256"],
        "schema_id": DEFINITION_SCHEMA_ID,
        "serialization_profile_id": "RFC8785_INTEGER_ONLY_UTF8_PLUS_SINGLE_LF_V1",
    }
    file_row = dict(file_core)
    file_row["file_row_sha256"] = framed_sha256(DEFINITION_FILE_ROW_DOMAIN, file_core)
    manifest_sha = hashlib.sha256(
        DEFINITION_BYTES_MANIFEST_DOMAIN.encode("utf-8")
        + b"\x00"
        + bytes.fromhex(file_row["file_row_sha256"])
    ).hexdigest()
    core = {
        "schema_id": BYTES_MANIFEST_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "manifest_status": "EXACT1_CANDIDATE_DEFINITION_BYTES__NOT_APPROVED",
        "candidate_definition_generation_id": definition[
            "candidate_definition_generation_id"
        ],
        "construction_contract_content_sha256": definition[
            "construction_contract_content_sha256"
        ],
        "definition_file_count": 1,
        "ordered_definition_files": [file_row],
        "definition_bytes_manifest_sha256": manifest_sha,
        "same_raw_bytes_required_in_both_git_repositories": True,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=DEFINITION_BYTES_MANIFEST_CONTENT_DOMAIN)


def compile_candidate_generation(
    *,
    generation_basis: dict[str, Any],
    definition: dict[str, Any],
    bytes_manifest: dict[str, Any],
) -> dict[str, Any]:
    basis_sha = framed_sha256(GENERATION_BASIS_DOMAIN, generation_basis)
    generation_id = f"ffexpdef::{basis_sha}"
    _require_equal(
        definition["candidate_definition_generation_id"],
        generation_id,
        "definition_generation_id_join",
    )
    core = {
        "schema_id": GENERATION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "generation_status": "CANDIDATE_GENERATION__NOT_STEWARD_APPROVED",
        "generation_basis": generation_basis,
        "generation_basis_sha256": basis_sha,
        "candidate_definition_generation_id": generation_id,
        "definition_bytes_manifest_sha256": bytes_manifest[
            "definition_bytes_manifest_sha256"
        ],
        "definition_content_sha256": definition["content_sha256"],
        "allowed_predecessor_binding_count": 13,
        "review_dependency_count": 5,
        "contains_steward_decision_or_signature_ref": False,
        "contains_os_activation_ref": False,
        "contains_materialization_or_execution_ref": False,
        "active": False,
        "signed": False,
        "candidate_only": True,
        "may_activate": False,
        "may_materialize_or_execute": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=GENERATION_CONTENT_DOMAIN)


def validate_compiled_objects(
    source: dict[str, dict[str, Any]],
    *,
    contract: dict[str, Any],
    schema: dict[str, Any],
    definition: dict[str, Any],
    definition_raw: bytes,
    bytes_manifest: dict[str, Any],
    generation: dict[str, Any],
) -> None:
    from jsonschema import Draft202012Validator

    _verify_content(contract, domain=CONTRACT_CONTENT_DOMAIN, label="contract")
    expected_basis = compile_generation_basis(source)
    expected_definition = compile_candidate_definition(
        source, contract=contract, generation_basis=expected_basis
    )
    _require_equal(definition, expected_definition, "definition_closed_equality")
    _require_equal(
        definition_raw, _definition_serialized_bytes(definition), "definition_raw_bytes"
    )
    expected_manifest = compile_definition_bytes_manifest(
        definition, definition_raw=definition_raw
    )
    _require_equal(bytes_manifest, expected_manifest, "bytes_manifest_closed_equality")
    expected_generation = compile_candidate_generation(
        generation_basis=expected_basis,
        definition=definition,
        bytes_manifest=bytes_manifest,
    )
    _require_equal(generation, expected_generation, "generation_closed_equality")
    _require_equal(
        set(generation),
        {
            "schema_id",
            "schema_version",
            "generation_status",
            "generation_basis",
            "generation_basis_sha256",
            "candidate_definition_generation_id",
            "definition_bytes_manifest_sha256",
            "definition_content_sha256",
            "allowed_predecessor_binding_count",
            "review_dependency_count",
            "contains_steward_decision_or_signature_ref",
            "contains_os_activation_ref",
            "contains_materialization_or_execution_ref",
            "active",
            "signed",
            "candidate_only",
            "may_activate",
            "may_materialize_or_execute",
            "authority_effect",
            "content_sha256",
        },
        "r14_generation_exact20_fields",
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(definition)


def compile_validation_report(
    *,
    contract: dict[str, Any],
    definition: dict[str, Any],
    bytes_manifest: dict[str, Any],
    generation: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        "R14_MANIFEST_RAW_AND_CONTENT_SHA256",
        "R14_EXACT7_ARTIFACT_BYTES_SHA256_AND_COMMITMENT",
        "STRICT_JSON_AND_CONTENT_DIGESTS",
        "EXACT160_TARGET_PROPOSAL_SEMANTIC_JOIN",
        "EXACT160_DEFINITION_ROW_DIGEST_AND_MANIFEST",
        "EXACT10_BRANCH_SELECTION_TARGET_BINDING",
        "R14_EXACT62_GENERATION_BASIS",
        "R14_GENERATION_BASIS_ID_AND_CONTENT_DIGESTS",
        "EXACT1_DEFINITION_BYTES_MANIFEST",
        "CLOSED_EXACT_INSTANCE_DEFINITION_SCHEMA",
        "NO_STEWARD_SIGNATURE_ACTIVATION_EXECUTION_OR_AUTHORITY_UPLIFT",
    ]
    core = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_status": "LOCAL_CONSTRUCTION_VALIDATION_PASS__NOT_AUTHORITY",
        "construction_contract_content_sha256": contract["content_sha256"],
        "candidate_definition_generation_id": generation[
            "candidate_definition_generation_id"
        ],
        "candidate_definition_generation_content_sha256": generation["content_sha256"],
        "definition_content_sha256": definition["content_sha256"],
        "definition_bytes_manifest_sha256": bytes_manifest[
            "definition_bytes_manifest_sha256"
        ],
        "ordered_check_count": len(checks),
        "ordered_checks": [
            {"ordinal": ordinal, "check_id": check, "result": "PASS"}
            for ordinal, check in enumerate(checks)
        ],
        "external_design_review_present": False,
        "ontology_steward_decision_present": False,
        "reference_steward_decision_present": False,
        "os_sealed_activation_present": False,
        "host_authorization_present": False,
        "fixture_or_crypto_execution_performed": False,
        "oos_accessed": False,
        "skill_rag_runtime_accessed": False,
        "canonical_memory_accessed_or_written": False,
        "runtime_or_deployment_performed": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REPORT_CONTENT_DOMAIN)


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


def _source_row(
    path: Path, *, ordinal: int, role: str, expected_sha: str
) -> dict[str, Any]:
    size, digest = _sha256_file(path.resolve(strict=True))
    _require_equal(digest, expected_sha, f"source_dependency_sha:{role}")
    return {
        "ordinal": ordinal,
        "role": role,
        "bytes": size,
        "sha256": digest,
        "is_operating_authority": False,
        "may_authorize_steward_or_host_action": False,
    }


def compile_packet_manifest(
    *,
    artifact_rows: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    definition: dict[str, Any],
    bytes_manifest: dict[str, Any],
    generation: dict[str, Any],
) -> dict[str, Any]:
    _require_equal(
        [row["ordinal"] for row in artifact_rows],
        list(range(6)),
        "packet_artifact_ordinals",
    )
    _require_equal(
        [row["ordinal"] for row in dependencies],
        list(range(4)),
        "packet_dependency_ordinals",
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
        "manifest_status": "CANDIDATE_DEFINITION_GENERATED__EXTERNAL_REVIEW_AND_ALL_OPERATING_AUTHORITY_UNBOUND_BLOCKING",
        "direct_predecessor_manifest_raw_sha256": R14_MANIFEST_RAW_SHA256,
        "artifact_count": 6,
        "ordered_artifacts": artifact_rows,
        "artifact_manifest_commitment_sha256": artifact_commitment,
        "source_contract_count": 4,
        "ordered_source_contracts": dependencies,
        "candidate_definition_generation_id": generation[
            "candidate_definition_generation_id"
        ],
        "candidate_definition_generation_content_sha256": generation["content_sha256"],
        "definition_content_sha256": definition["content_sha256"],
        "definition_bytes_manifest_sha256": bytes_manifest[
            "definition_bytes_manifest_sha256"
        ],
        "exact160_definition_row_count": 160,
        "exact10_branch_selection_review_target_count": 10,
        "local_workspace_action_description": "R14_BOUND_CANDIDATE_DEFINITION_GENERATION_AND_LOCAL_GIT_LANDING_PREPARATION_ONLY",
        "owner_instruction_provenance_state": "CHAT_CONTEXT_ONLY__NONAUTHORITY",
        "owner_instruction_ref": None,
        "owner_instruction_sha256": None,
        "owner_instruction_may_satisfy_any_contract_gate": False,
        "external_design_review_present": False,
        "dual_git_remote_repository_binding_present": False,
        "ontology_steward_signed_decision_present": False,
        "reference_steward_signed_decision_present": False,
        "os_sealed_activation_present": False,
        "host_authorization_present": False,
        "fixture_or_crypto_execution_allowed": False,
        "oos_allowed": False,
        "skill_rag_runtime_allowed": False,
        "canonical_memory_read_or_write_allowed": False,
        "runtime_or_deployment_allowed": False,
        "signed": False,
        "candidate_only": True,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PACKET_CONTENT_DOMAIN)


def validate_candidate_definition_packet(
    packet_manifest_path: Path,
    *,
    r14_manifest_path: Path,
    r14_review_manifest_path: Path,
    h1_manifest_path: Path,
    h1_review_manifest_path: Path,
) -> dict[str, Any]:
    packet_manifest_path = Path(packet_manifest_path).resolve(strict=True)
    _require_equal(
        packet_manifest_path.name, "packet_manifest.json", "packet_manifest_name"
    )
    root = packet_manifest_path.parent
    expected_roles = (
        (
            "00_candidate_definition_derivation_contract.json",
            "DEFINITION_DERIVATION_CONTRACT",
        ),
        (
            "01_closed_candidate_definition_bytes.schema.json",
            "CLOSED_DEFINITION_SCHEMA",
        ),
        ("02_candidate_definition.json", "CANDIDATE_DEFINITION_BYTES"),
        ("03_definition_bytes_manifest.json", "DEFINITION_BYTES_MANIFEST"),
        ("04_candidate_definition_generation.json", "R14_GENERATION_SUCCESSOR"),
        ("05_generation_validation_report.json", "LOCAL_VALIDATION_REPORT"),
    )
    expected_names = {"packet_manifest.json", *(name for name, _ in expected_roles)}
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
    manifest, _ = _strict_object(packet_manifest_path)
    _verify_content(manifest, domain=PACKET_CONTENT_DOMAIN, label="packet_manifest")
    artifact_rows: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    definition_raw = b""
    for ordinal, (name, role) in enumerate(expected_roles):
        path = root / name
        raw = path.read_bytes()
        row = {
            "ordinal": ordinal,
            "role": role,
            "path": name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        artifact_rows.append(row)
        payload = strict_json_loads(raw, label=name)
        _require(isinstance(payload, dict), f"packet_json_object_required:{name}")
        payloads[role] = payload
        if role == "CANDIDATE_DEFINITION_BYTES":
            definition_raw = raw
    _require_equal(
        manifest.get("ordered_artifacts"), artifact_rows, "packet_artifact_rows"
    )
    dependencies = [
        _source_row(
            Path(r14_manifest_path),
            ordinal=0,
            role="R14_DIRECT_NORMATIVE_PREDECESSOR_MANIFEST",
            expected_sha=R14_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(r14_review_manifest_path),
            ordinal=1,
            role="R14_DESIGN_ONLY_REVIEW_DEPENDENCY_MANIFEST",
            expected_sha=R14_REVIEW_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(h1_manifest_path),
            ordinal=2,
            role="H1_READINESS_PREDECESSOR_MANIFEST",
            expected_sha=H1_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(h1_review_manifest_path),
            ordinal=3,
            role="H1_DESIGN_ONLY_REVIEW_DEPENDENCY_MANIFEST",
            expected_sha=H1_REVIEW_MANIFEST_RAW_SHA256,
        ),
    ]
    _require_equal(
        manifest.get("ordered_source_contracts"),
        dependencies,
        "packet_source_contract_rows",
    )
    source = load_and_verify_r14_packet(r14_manifest_path)
    basis = compile_generation_basis(source)
    expected_contract = compile_derivation_contract(source)
    _require_equal(
        payloads["DEFINITION_DERIVATION_CONTRACT"],
        expected_contract,
        "packet_contract_closed_equality",
    )
    expected_definition = compile_candidate_definition(
        source, contract=expected_contract, generation_basis=basis
    )
    _require_equal(
        payloads["CANDIDATE_DEFINITION_BYTES"],
        expected_definition,
        "packet_definition_closed_equality",
    )
    _require_equal(
        definition_raw,
        _definition_serialized_bytes(expected_definition),
        "packet_definition_canonical_raw_bytes",
    )
    expected_schema = compile_exact_instance_schema(expected_definition)
    _require_equal(
        payloads["CLOSED_DEFINITION_SCHEMA"],
        expected_schema,
        "packet_definition_schema_closed_equality",
    )
    expected_bytes_manifest = compile_definition_bytes_manifest(
        expected_definition, definition_raw=definition_raw
    )
    _require_equal(
        payloads["DEFINITION_BYTES_MANIFEST"],
        expected_bytes_manifest,
        "packet_bytes_manifest_closed_equality",
    )
    expected_generation = compile_candidate_generation(
        generation_basis=basis,
        definition=expected_definition,
        bytes_manifest=expected_bytes_manifest,
    )
    _require_equal(
        payloads["R14_GENERATION_SUCCESSOR"],
        expected_generation,
        "packet_generation_closed_equality",
    )
    expected_report = compile_validation_report(
        contract=expected_contract,
        definition=expected_definition,
        bytes_manifest=expected_bytes_manifest,
        generation=expected_generation,
    )
    _require_equal(
        payloads["LOCAL_VALIDATION_REPORT"],
        expected_report,
        "packet_report_closed_equality",
    )
    validate_compiled_objects(
        source,
        contract=expected_contract,
        schema=expected_schema,
        definition=expected_definition,
        definition_raw=definition_raw,
        bytes_manifest=expected_bytes_manifest,
        generation=expected_generation,
    )
    expected_manifest = compile_packet_manifest(
        artifact_rows=artifact_rows,
        dependencies=dependencies,
        definition=expected_definition,
        bytes_manifest=expected_bytes_manifest,
        generation=expected_generation,
    )
    _require_equal(manifest, expected_manifest, "packet_manifest_closed_equality")
    return manifest


def write_candidate_definition_packet(
    output_root: Path,
    *,
    r14_manifest_path: Path,
    r14_review_manifest_path: Path,
    h1_manifest_path: Path,
    h1_review_manifest_path: Path,
) -> dict[str, Any]:
    source = load_and_verify_r14_packet(r14_manifest_path)
    generation_basis = compile_generation_basis(source)
    contract = compile_derivation_contract(source)
    definition = compile_candidate_definition(
        source, contract=contract, generation_basis=generation_basis
    )
    schema = compile_exact_instance_schema(definition)
    definition_raw = _definition_serialized_bytes(definition)
    bytes_manifest = compile_definition_bytes_manifest(
        definition, definition_raw=definition_raw
    )
    generation = compile_candidate_generation(
        generation_basis=generation_basis,
        definition=definition,
        bytes_manifest=bytes_manifest,
    )
    validate_compiled_objects(
        source,
        contract=contract,
        schema=schema,
        definition=definition,
        definition_raw=definition_raw,
        bytes_manifest=bytes_manifest,
        generation=generation,
    )
    report = compile_validation_report(
        contract=contract,
        definition=definition,
        bytes_manifest=bytes_manifest,
        generation=generation,
    )
    dependencies = [
        _source_row(
            Path(r14_manifest_path),
            ordinal=0,
            role="R14_DIRECT_NORMATIVE_PREDECESSOR_MANIFEST",
            expected_sha=R14_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(r14_review_manifest_path),
            ordinal=1,
            role="R14_DESIGN_ONLY_REVIEW_DEPENDENCY_MANIFEST",
            expected_sha=R14_REVIEW_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(h1_manifest_path),
            ordinal=2,
            role="H1_READINESS_PREDECESSOR_MANIFEST",
            expected_sha=H1_MANIFEST_RAW_SHA256,
        ),
        _source_row(
            Path(h1_review_manifest_path),
            ordinal=3,
            role="H1_DESIGN_ONLY_REVIEW_DEPENDENCY_MANIFEST",
            expected_sha=H1_REVIEW_MANIFEST_RAW_SHA256,
        ),
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
        artifacts: list[tuple[str, str, dict[str, Any] | None]] = [
            (
                "00_candidate_definition_derivation_contract.json",
                "DEFINITION_DERIVATION_CONTRACT",
                contract,
            ),
            (
                "01_closed_candidate_definition_bytes.schema.json",
                "CLOSED_DEFINITION_SCHEMA",
                schema,
            ),
            ("02_candidate_definition.json", "CANDIDATE_DEFINITION_BYTES", None),
            (
                "03_definition_bytes_manifest.json",
                "DEFINITION_BYTES_MANIFEST",
                bytes_manifest,
            ),
            (
                "04_candidate_definition_generation.json",
                "R14_GENERATION_SUCCESSOR",
                generation,
            ),
            ("05_generation_validation_report.json", "LOCAL_VALIDATION_REPORT", report),
        ]
        for name, _, payload in artifacts:
            if payload is None:
                _write_bytes_once(staging_root, name, definition_raw)
            else:
                write_workspace_json_once(staging_root, name, payload)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role, _) in enumerate(artifacts)
        ]
        manifest = compile_packet_manifest(
            artifact_rows=rows,
            dependencies=dependencies,
            definition=definition,
            bytes_manifest=bytes_manifest,
            generation=generation,
        )
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        validate_candidate_definition_packet(
            staging_root / "packet_manifest.json",
            r14_manifest_path=r14_manifest_path,
            r14_review_manifest_path=r14_review_manifest_path,
            h1_manifest_path=h1_manifest_path,
            h1_review_manifest_path=h1_review_manifest_path,
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
