from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
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
from factor_factory.epistemic_source_first_offline import read_stable_regular_bytes
from factor_factory.research_org.contracts import strict_json_loads, write_workspace_json_once
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"
MAX_JSON_BYTES = 16 * 1024 * 1024

FIXTURE_SCHEMA_ID = "factorforge_offline_failure_diagnosis_fixture_v1"
ASSERTION_DAG_FIXTURE_SCHEMA_ID = (
    "factorforge_offline_failure_diagnosis_assertion_dependency_dag_v1"
)
STAGE2_BINDING_SCHEMA_ID = "factorforge_detached_stage2_retrieval_input_binding_v1"
INTAKE_SCHEMA_ID = "factorforge_closed_synthetic_diagnosis_intake_v1"
HYPOTHESIS_SCHEMA_ID = "factorforge_frozen_hypothesis_mismatch_candidate_v1"
RIVAL_SCHEMA_ID = "factorforge_material_rival_registry_candidate_v1"
PARTITION_SCHEMA_ID = "factorforge_generation_confirmation_partition_plan_v1"
TEST_SCHEMA_ID = "factorforge_distinguishing_test_registry_candidate_v1"
LAYER_SCHEMA_ID = "factorforge_layer_assessment_plan_candidate_v1"
ADVISORY_SCHEMA_ID = "factorforge_exploit_explore_dirac_advisory_candidate_v1"
TERMINAL_SCHEMA_ID = "factorforge_diagnosis_planner_terminal_candidate_v1"
REPORT_SCHEMA_ID = "factorforge_failure_diagnosis_offline_replay_report_v1"
PACKET_SCHEMA_ID = "factorforge_failure_diagnosis_offline_candidate_packet_v1"

STAGE2_PACKET_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CANDIDATE_PACKET_V1"
STAGE2_PACKET_ARTIFACT_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PACKET_ARTIFACT_MANIFEST_V1"

STAGE2_BINDING_DOMAIN = "FF_FAILURE_DIAGNOSIS_STAGE2_INPUT_BINDING_V1"
INTAKE_DOMAIN = "FF_FAILURE_DIAGNOSIS_SYNTHETIC_INTAKE_V1"
HYPOTHESIS_DOMAIN = "FF_FAILURE_DIAGNOSIS_HYPOTHESIS_MISMATCH_V1"
RIVAL_ROW_DOMAIN = "FF_FAILURE_DIAGNOSIS_RIVAL_ROW_V1"
RIVAL_DOMAIN = "FF_FAILURE_DIAGNOSIS_RIVAL_REGISTRY_V1"
PARTITION_MEMBER_DOMAIN = "FF_FAILURE_DIAGNOSIS_PARTITION_MEMBER_V1"
PARTITION_DOMAIN = "FF_FAILURE_DIAGNOSIS_PARTITION_PLAN_V1"
TEST_ROW_DOMAIN = "FF_FAILURE_DIAGNOSIS_TEST_ROW_V1"
TEST_DOMAIN = "FF_FAILURE_DIAGNOSIS_TEST_REGISTRY_V1"
LAYER_ROW_DOMAIN = "FF_FAILURE_DIAGNOSIS_LAYER_ROW_V1"
MATERIAL_SCOPE_ROW_DOMAIN = "FF_FAILURE_DIAGNOSIS_MATERIAL_SCOPE_ROW_V1"
MATERIAL_DAG_EDGE_DOMAIN = "FF_FAILURE_DIAGNOSIS_MATERIAL_DAG_EDGE_V1"
LAYER_DOMAIN = "FF_FAILURE_DIAGNOSIS_LAYER_PLAN_V1"
BRANCH_ROW_DOMAIN = "FF_FAILURE_DIAGNOSIS_BRANCH_ADVISORY_ROW_V1"
FUTURE_QUESTION_DOMAIN = "FF_FAILURE_DIAGNOSIS_FUTURE_QUESTION_V1"
ADVISORY_DOMAIN = "FF_FAILURE_DIAGNOSIS_ADVISORY_V1"
TERMINAL_DOMAIN = "FF_FAILURE_DIAGNOSIS_PLANNER_TERMINAL_V1"
REPORT_DOMAIN = "FF_FAILURE_DIAGNOSIS_REPLAY_REPORT_V1"
PACKET_ARTIFACT_DOMAIN = "FF_FAILURE_DIAGNOSIS_PACKET_ARTIFACT_MANIFEST_V1"
PACKET_DOMAIN = "FF_FAILURE_DIAGNOSIS_CANDIDATE_PACKET_V1"

PACKET_ID = "FF_FAILURE_DIAGNOSIS_PLANNER_STANDALONE_OFFLINE_PROTOTYPE_20260829_R3"
R2_REVISION_PREDECESSOR_RAW_SHA256 = (
    "335f05da19b53f202a98344d006157dcf1f59b69226745acb3a88ffd2de86362"
)
R2_REVISION_PREDECESSOR_CONTENT_SHA256 = (
    "1846ba3b02f2388b38a649e3182d8135f186b1b1481129aa7fae60d6db4a7f0d"
)

DIAGNOSIS_PATH = "POST_RESULT_EXPLORATORY_PATH"
EVIDENCE_BRANCH = "PURGED_IS_PRE_OOS_SYNTHETIC_CANDIDATE_ONLY"
CASE_CLASSES = {
    "SYNTHETIC_DIAGNOSIS_PLAN_CANDIDATE",
    "QUARANTINED_DIAGNOSIS_PLAN_CANDIDATE",
}
LAYER_IDS = tuple(f"L{i}" for i in range(10))
LAYER_NAMES = (
    "AUTHORITY_PROVENANCE",
    "INFORMATION_TIME_LEGALITY",
    "IMPLEMENTATION_FIDELITY",
    "MEASUREMENT_VALIDITY",
    "STATISTICAL_IDENTIFIABILITY",
    "SELECTION_ALIAS_EXPOSURE",
    "MATHEMATICAL_DYNAMICS",
    "ECONOMIC_GAME",
    "TRADING_ECONOMICS",
    "PORTABILITY_REGIME",
)
RIVAL_ROLES = {
    "PREFERRED_MECHANISM",
    "MECHANISM_DISTINCT_ALTERNATIVE",
    "NULL_OR_ALIAS",
}
ASSERTION_PARTITIONS = {
    "SURVIVAL_TEST_TARGET",
    "FAILURE_TEST_TARGET",
    "UNTESTED",
    "UNIDENTIFIABLE",
}
SIGNATURE_DIMENSIONS = (
    "direction",
    "cross_sectional_shape",
    "horizon_pattern",
    "state_interaction",
    "alias_behavior",
    "missingness_behavior",
    "cost_capacity_behavior",
)
VALIDITY_STATES = {
    "SYNTHETIC_TESTABLE",
    "QUARANTINED",
    "ABSENT",
}
LANE_DISPOSITIONS = {
    "PROPOSED_CANDIDATES",
    "ABSTAINED_WITH_REASON",
    "NO_ADMISSIBLE_CURRENT_CONJECTURE",
    "BLOCKED_BY_VALIDITY",
}
CURRENT_EVO_HARD_GATES = (
    ("V0_EVIDENCE_IDENTITY", "L0"),
    ("V1_DATA_INTEGRITY", "L0"),
    ("V2_INFORMATION_SET_LEGALITY", "L1"),
    ("V3_EVALUATION_SEMANTICS", "L2"),
    ("V4_IMPLEMENTATION_FIDELITY", "L2"),
    ("M0_OBSERVATION_EQUATION_IDENTIFICATION", "L3"),
    ("M1_MEASUREMENT_INFORMATION_LOSS", "L3"),
    ("S0_STATISTICAL_POWER_AND_MULTIPLICITY", "L4"),
    ("M2_ALIAS_AND_CONTROL", "L5"),
)

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
LOCAL_ID_RE = re.compile(r"[a-z][a-z0-9-]{2,95}\Z")
TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]{1,95}\Z")
URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,15}://")
ABSOLUTE_PATH_RE = re.compile(r"(?:^|\s)(?:/[^\s]+|~/[^\s]+|[A-Za-z]:\\[^\s]+)")
FORBIDDEN_PRODUCTION_TEXT_RE = re.compile(
    r"\b(?:sharpe|nav|pnl|oos|backtest|production|promotion|qualified contradiction|"
    r"host receipt|canonical memory|live runtime|deployment|information coefficient)\b|"
    r"夏普|净值|样本外|正式晋升|正式录用|生产回测|主机回执|规范记忆|线上运行|部署",
    re.IGNORECASE,
)


class FailureDiagnosisOfflineError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(";".join(self.reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise FailureDiagnosisOfflineError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise FailureDiagnosisOfflineError(
            [f"{label}:expected={expected!r}:actual={actual!r}"]
        )


def _closed_mapping(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require_equal(set(value), expected, f"{label}:closed_fields")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{label}:array_required",
    )
    return value


def _boolean(value: Any, label: str) -> bool:
    _require(isinstance(value, bool), f"{label}:boolean_required")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int = 1_000_000) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label}:integer_required")
    _require(minimum <= value <= maximum, f"{label}:out_of_range")
    return value


def _local_id(value: Any, label: str) -> str:
    _require(isinstance(value, str), f"{label}:string_required")
    result = unicodedata.normalize("NFKC", value.strip())
    _require(LOCAL_ID_RE.fullmatch(result) is not None, f"{label}:local_id_required")
    return result


def _token(value: Any, label: str) -> str:
    _require(isinstance(value, str), f"{label}:string_required")
    result = unicodedata.normalize("NFKC", value.strip())
    _require(TOKEN_RE.fullmatch(result) is not None, f"{label}:closed_token_required")
    return result


def _semantic_text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label}:nonempty_text")
    result = unicodedata.normalize("NFKC", value.strip())
    _require("\x00" not in result, f"{label}:nul_forbidden")
    _require(len(result.encode("utf-8")) <= 4096, f"{label}:too_large")
    _require(URI_RE.search(result) is None, f"{label}:uri_forbidden")
    _require(ABSOLUTE_PATH_RE.search(result) is None, f"{label}:absolute_path_forbidden")
    _require(
        FORBIDDEN_PRODUCTION_TEXT_RE.search(result) is None,
        f"{label}:production_or_authority_claim_forbidden",
    )
    return result


def _sha256(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label}:sha256")
    return value


def _with_content_sha(payload: Mapping[str, Any], *, domain: str) -> dict[str, Any]:
    _require("content_sha256" not in payload, f"{domain}:content_sha_already_present")
    result = dict(payload)
    result["content_sha256"] = framed_sha256(domain, result)
    return result


def _verify_content(payload: Mapping[str, Any], *, domain: str, label: str) -> None:
    _require("content_sha256" in payload, f"{label}:content_sha_missing")
    core = {key: value for key, value in payload.items() if key != "content_sha256"}
    _require_equal(payload["content_sha256"], framed_sha256(domain, core), f"{label}:content_sha")


def _read_json_object(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = read_stable_regular_bytes(path, label=label, max_bytes=MAX_JSON_BYTES)
    payload = strict_json_loads(raw, label=str(path))
    _require(isinstance(payload, dict), f"{label}:object_required")
    return raw, payload


def _normalize_signature(value: Any, label: str) -> dict[str, str]:
    raw = _closed_mapping(value, set(SIGNATURE_DIMENSIONS), label)
    return {
        dimension: _token(raw[dimension], f"{label}.{dimension}")
        for dimension in SIGNATURE_DIMENSIONS
    }


def _normalize_text_list(value: Any, label: str, *, min_items: int = 1) -> list[str]:
    rows = [_semantic_text(item, f"{label}[{ordinal}]") for ordinal, item in enumerate(_array(value, label))]
    _require(len(rows) >= min_items, f"{label}:min_items")
    _require_equal(len(set(rows)), len(rows), f"{label}:unique")
    return rows


def _normalize_local_id_list(value: Any, label: str, *, min_items: int = 1) -> list[str]:
    rows = [_local_id(item, f"{label}[{ordinal}]") for ordinal, item in enumerate(_array(value, label))]
    _require(len(rows) >= min_items, f"{label}:min_items")
    _require_equal(len(set(rows)), len(rows), f"{label}:unique")
    return rows


def compile_stage2_input_binding(
    phase_safe_manifest_path: Path,
) -> dict[str, Any]:
    """Project only non-semantic Stage2 provenance into Stage3.

    This binder intentionally never opens any Stage2 artifact.  In particular it
    does not deserialize the A0 selection ledger, returned rows, lanes, scores,
    object identifiers, or sanitized semantic candidates.  A consistent change
    to those response-like payloads therefore cannot change this projection.
    """

    manifest_path = Path(phase_safe_manifest_path)
    manifest_raw, manifest = _read_json_object(
        manifest_path,
        label="stage2.manifest_envelope",
    )
    return _compile_stage2_input_binding_from_manifest_bytes(
        manifest_raw=manifest_raw,
        manifest=manifest,
    )


def compile_stage2_input_binding_from_raw(
    manifest_raw: bytes,
) -> dict[str, Any]:
    """Compile the same closed Stage2 projection from caller-supplied raw bytes.

    The raw-byte entrypoint exists so an outer adapter can bind the exact bytes it
    validated without first materializing a temporary file.  It deliberately shares
    the complete manifest replay below with the stable-path entrypoint.
    """

    _require(type(manifest_raw) is bytes, "stage2.manifest_envelope:bytes_required")
    _require(
        0 < len(manifest_raw) <= MAX_JSON_BYTES,
        "stage2.manifest_envelope:size",
    )
    manifest = strict_json_loads(
        manifest_raw,
        label="stage2.manifest_envelope.raw_bytes",
    )
    _require(
        isinstance(manifest, dict),
        "stage2.manifest_envelope:object_required",
    )
    return _compile_stage2_input_binding_from_manifest_bytes(
        manifest_raw=manifest_raw,
        manifest=manifest,
    )


def _compile_stage2_input_binding_from_manifest_bytes(
    *,
    manifest_raw: bytes,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Closed common compiler for stable-path and explicit-raw Stage2 inputs."""

    manifest = dict(
        _closed_mapping(
            manifest,
            {
                "schema_id",
                "schema_version",
                "packet_id",
                "manifest_status",
                "lineage_mode",
                "factor_forge_successor",
                "direct_predecessor_manifest_raw_sha256",
                "normative_dependency_count",
                "may_satisfy_any_factor_forge_gate",
                "prototype_input_dependency_count",
                "prototype_input_dependencies",
                "phase_projection_content_sha256",
                "private_full_world_sidecar",
                "artifact_count",
                "ordered_artifacts",
                "artifact_manifest_commitment_sha256",
                "compiler_profile",
                "offline_transform_allowed",
                "retrieval_runtime_allowed",
                "opaque_handle_or_signed_zero_hit_mint_allowed",
                "host_or_canonical_memory_allowed",
                "oos_allowed",
                "skill_or_rag_runtime_allowed",
                "network_or_ambient_index_discovery_allowed",
                "canonical_write_or_promotion_allowed",
                "runtime_or_deployment_allowed",
                "steward_or_host_authority_present",
                "permissions_opened_count",
                "candidate_only",
                "signed",
                "authority_effect",
                "content_sha256",
            },
            "stage2.manifest_envelope",
        )
    )
    _verify_content(
        manifest,
        domain=STAGE2_PACKET_DOMAIN,
        label="stage2.manifest_envelope",
    )
    _require_equal(
        manifest["schema_id"],
        "factorforge_phase_safe_offline_candidate_packet_v1",
        "stage2.schema_id",
    )
    _require_equal(manifest["schema_version"], SCHEMA_VERSION, "stage2.schema_version")
    _require_equal(
        manifest["lineage_mode"],
        "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE",
        "stage2.lineage_mode",
    )
    _require_equal(
        manifest["manifest_status"],
        (
            "STANDALONE_OFFLINE_RETRIEVAL_PROTOTYPE_COMPLETE__"
            "ALL_FACTOR_FORGE_AND_OPERATING_AUTHORITY_UNBOUND_BLOCKING"
        ),
        "stage2.manifest_status",
    )
    _require_equal(manifest["factor_forge_successor"], False, "stage2.successor")
    _require_equal(
        manifest["direct_predecessor_manifest_raw_sha256"],
        None,
        "stage2.direct_predecessor",
    )
    _require_equal(manifest["normative_dependency_count"], 0, "stage2.normative_dependencies")
    _require_equal(manifest["may_satisfy_any_factor_forge_gate"], False, "stage2.gate")
    _require_equal(
        manifest["prototype_input_dependency_count"],
        1,
        "stage2.prototype_input_dependency_count",
    )
    prototype_dependencies = _array(
        manifest["prototype_input_dependencies"],
        "stage2.prototype_input_dependencies",
    )
    _require_equal(
        len(prototype_dependencies),
        manifest["prototype_input_dependency_count"],
        "stage2.prototype_input_dependencies_count",
    )
    prototype_dependency = _closed_mapping(
        prototype_dependencies[0],
        {
            "ordinal",
            "role",
            "stage1_packet_id",
            "stage1_manifest_raw_sha256",
            "stage1_manifest_content_sha256",
            "stage1_binding_content_sha256",
            "authority_effect",
        },
        "stage2.prototype_input_dependencies[0]",
    )
    _require_equal(
        prototype_dependency["ordinal"],
        0,
        "stage2.prototype_input_dependency.ordinal",
    )
    _require_equal(
        prototype_dependency["role"],
        "DETACHED_STAGE1_PROTOTYPE_INPUT__NOT_PREDECESSOR",
        "stage2.prototype_input_dependency.role",
    )
    _semantic_text(
        prototype_dependency["stage1_packet_id"],
        "stage2.prototype_input_dependency.stage1_packet_id",
    )
    for key in (
        "stage1_manifest_raw_sha256",
        "stage1_manifest_content_sha256",
        "stage1_binding_content_sha256",
    ):
        _sha256(
            prototype_dependency[key],
            f"stage2.prototype_input_dependency.{key}",
        )
    _require_equal(
        prototype_dependency["authority_effect"],
        AUTHORITY_EFFECT,
        "stage2.prototype_input_dependency.authority_effect",
    )
    _sha256(
        manifest["phase_projection_content_sha256"],
        "stage2.phase_projection_content_sha256",
    )
    sidecar = _closed_mapping(
        manifest["private_full_world_sidecar"],
        {
            "corpus_content_sha256",
            "corpus_manifest_commitment_sha256",
            "phase_response_like_artifact_dependency_allowed",
        },
        "stage2.private_full_world_sidecar",
    )
    _sha256(
        sidecar["corpus_content_sha256"],
        "stage2.private_full_world_sidecar.corpus_content_sha256",
    )
    _sha256(
        sidecar["corpus_manifest_commitment_sha256"],
        "stage2.private_full_world_sidecar.corpus_manifest_commitment_sha256",
    )
    _require_equal(
        sidecar["phase_response_like_artifact_dependency_allowed"],
        False,
        "stage2.private_full_world_sidecar.response_dependency_allowed",
    )
    _require_equal(
        manifest["offline_transform_allowed"],
        True,
        "stage2.offline_transform_allowed",
    )
    for key in (
        "retrieval_runtime_allowed",
        "opaque_handle_or_signed_zero_hit_mint_allowed",
        "host_or_canonical_memory_allowed",
        "oos_allowed",
        "skill_or_rag_runtime_allowed",
        "network_or_ambient_index_discovery_allowed",
        "canonical_write_or_promotion_allowed",
        "runtime_or_deployment_allowed",
        "steward_or_host_authority_present",
        "signed",
    ):
        _require_equal(manifest[key], False, f"stage2.{key}")
    _require_equal(manifest["permissions_opened_count"], 0, "stage2.permissions")
    _require_equal(manifest["candidate_only"], True, "stage2.candidate_only")
    _require_equal(manifest["authority_effect"], AUTHORITY_EFFECT, "stage2.authority")

    artifact_rows = _array(manifest["ordered_artifacts"], "stage2.ordered_artifacts")
    expected_artifact_identity = (
        ("DETACHED_STAGE1_INPUT_BINDING", "00_stage1_input_binding.json"),
        ("CLOSED_SYNTHETIC_QUARANTINED_CORPUS", "01_closed_corpus_bundle.json"),
        ("PHASE_SAFE_RETRIEVAL_PROGRAM", "02_retrieval_program.json"),
        ("SCORED_CANDIDATE_LEDGER", "03_scored_candidate_ledger.json"),
        ("SELECTION_LEDGER", "04_selection_ledger.json"),
        ("REJECTION_ZERO_HIT_LEDGER", "05_rejection_and_zero_hit_ledger.json"),
        ("LOCAL_REPLAY_REPORT", "06_local_replay_report.json"),
    )
    _require_equal(
        manifest["artifact_count"],
        len(expected_artifact_identity),
        "stage2.artifact_count_exact7",
    )
    _require_equal(len(artifact_rows), manifest["artifact_count"], "stage2.artifact_count")
    artifact_hash_bytes: list[bytes] = []
    for ordinal, value in enumerate(artifact_rows):
        row = _closed_mapping(
            value,
            {"ordinal", "role", "path", "bytes", "sha256"},
            f"stage2.ordered_artifacts[{ordinal}]",
        )
        _require_equal(row["ordinal"], ordinal, f"stage2.artifact_ordinal:{ordinal}")
        _require_equal(
            (row["role"], row["path"]),
            expected_artifact_identity[ordinal],
            f"stage2.artifact_identity:{ordinal}",
        )
        _integer(row["bytes"], f"stage2.artifact_bytes:{ordinal}", minimum=1, maximum=MAX_JSON_BYTES)
        artifact_hash_bytes.append(bytes.fromhex(_sha256(row["sha256"], f"stage2.artifact_sha:{ordinal}")))
    expected_commitment = hashlib.sha256(
        STAGE2_PACKET_ARTIFACT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(artifact_hash_bytes)
    ).hexdigest()
    _require_equal(
        manifest["artifact_manifest_commitment_sha256"],
        expected_commitment,
        "stage2.artifact_commitment",
    )
    compiler = _closed_mapping(
        manifest["compiler_profile"],
        {
            "module",
            "bytes",
            "sha256",
            "canonicalization",
            "content_digest_formula",
            "artifact_commitment_formula",
        },
        "stage2.compiler_profile",
    )
    compiler_projection = {
        "module": _semantic_text(compiler["module"], "stage2.compiler.module"),
        "bytes": _integer(
            compiler["bytes"], "stage2.compiler.bytes", minimum=1, maximum=4 * 1024 * 1024
        ),
        "sha256": _sha256(compiler["sha256"], "stage2.compiler.sha256"),
        "canonicalization": _semantic_text(
            compiler["canonicalization"], "stage2.compiler.canonicalization"
        ),
        "content_digest_formula": _semantic_text(
            compiler["content_digest_formula"], "stage2.compiler.content_digest_formula"
        ),
        "artifact_commitment_formula": _semantic_text(
            compiler["artifact_commitment_formula"],
            "stage2.compiler.artifact_commitment_formula",
        ),
    }
    core = {
        "schema_id": STAGE2_BINDING_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "input_role": "DETACHED_STAGE2_IMPLEMENTATION_PROVENANCE_ONLY__NOT_PREDECESSOR",
        "stage2_packet": {
            "packet_id": manifest["packet_id"],
            "schema_id": manifest["schema_id"],
            "lineage_mode": manifest["lineage_mode"],
            "factor_forge_successor": manifest["factor_forge_successor"],
            "manifest_envelope_validated": True,
            "manifest_identity_hashes_bound_into_stage3_projection": False,
        },
        "implementation_provenance_projection": {
            "compiler_profile": compiler_projection,
            "artifact_envelope_count": len(artifact_rows),
            "manifest_envelope_read": bool(manifest_raw),
            "stage2_artifact_payload_bytes_read": 0,
        },
        "semantic_payload_access_policy": {
            "selection_ledger_opened": False,
            "returned_rows_deserialized": False,
            "lane_score_object_or_semantic_candidate_read": False,
            "response_like_artifact_hashes_emitted": False,
            "stage2_artifact_paths_dereferenced": False,
            "changing_a0_returned_semantics_may_change_this_projection": False,
        },
        "cross_phase_semantic_consumption_allowed": False,
        "stage2_manifest_envelope_revalidated_without_artifact_access": True,
        "prototype_dependency_not_normative_predecessor": True,
        "historical_performance_or_outcome_used": False,
        "may_satisfy_any_factor_forge_gate": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=STAGE2_BINDING_DOMAIN)


def _normalize_hypothesis(value: Any, label: str) -> dict[str, str]:
    fields = {
        "economic_hypothesis",
        "estimand",
        "payer",
        "receiver",
        "information_set",
        "mathematical_object",
        "observation_equation",
        "market_outcome_projection",
        "falsifier",
    }
    raw = _closed_mapping(value, fields, label)
    return {field: _semantic_text(raw[field], f"{label}.{field}") for field in sorted(fields)}


def _normalize_assertions(value: Any, label: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for ordinal, item in enumerate(_array(value, label)):
        raw = _closed_mapping(
            item,
            {
                "assertion_id",
                "layer_id",
                "semantics",
                "material",
                "planned_partition",
                "observation_identifiability",
            },
            f"{label}[{ordinal}]",
        )
        assertion_id = _local_id(raw["assertion_id"], f"{label}[{ordinal}].assertion_id")
        _require(assertion_id not in ids, f"{label}:duplicate_assertion_id:{assertion_id}")
        ids.add(assertion_id)
        layer_id = str(raw["layer_id"])
        _require(layer_id in LAYER_IDS[3:], f"{label}[{ordinal}].layer_id")
        partition = str(raw["planned_partition"])
        _require(partition in ASSERTION_PARTITIONS, f"{label}[{ordinal}].planned_partition")
        identifiability = _token(
            raw["observation_identifiability"],
            f"{label}[{ordinal}].observation_identifiability",
        )
        if partition == "UNIDENTIFIABLE":
            _require_equal(
                identifiability,
                "UNIDENTIFIABLE_FROM_CURRENT_OBSERVATION_EQUATION",
                f"{label}[{ordinal}].unidentifiable_reason",
            )
        result.append(
            {
                "ordinal": ordinal,
                "assertion_id": assertion_id,
                "layer_id": layer_id,
                "semantics": _semantic_text(raw["semantics"], f"{label}[{ordinal}].semantics"),
                "material": _boolean(raw["material"], f"{label}[{ordinal}].material"),
                "planned_partition": partition,
                "observation_identifiability": identifiability,
            }
        )
    _require(len(result) >= 1, f"{label}:min_items")
    return result


def _normalize_assertion_dependency_dag(
    value: Any,
    label: str,
    *,
    assertions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    raw = _closed_mapping(value, {"schema_id", "edges"}, label)
    _require_equal(
        raw["schema_id"],
        ASSERTION_DAG_FIXTURE_SCHEMA_ID,
        f"{label}.schema_id",
    )
    assertion_by_id = {row["assertion_id"]: row for row in assertions}
    rows: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    endpoint_pairs: set[tuple[str, str]] = set()
    for ordinal, item in enumerate(_array(raw["edges"], f"{label}.edges")):
        edge = _closed_mapping(
            item,
            {
                "edge_id",
                "prerequisite_assertion_id",
                "dependent_assertion_id",
                "material",
                "criteria_semantics",
            },
            f"{label}.edges[{ordinal}]",
        )
        edge_id = _local_id(edge["edge_id"], f"{label}.edges[{ordinal}].edge_id")
        _require(edge_id not in edge_ids, f"{label}:duplicate_edge_id:{edge_id}")
        edge_ids.add(edge_id)
        prerequisite = _local_id(
            edge["prerequisite_assertion_id"],
            f"{label}.edges[{ordinal}].prerequisite_assertion_id",
        )
        dependent = _local_id(
            edge["dependent_assertion_id"],
            f"{label}.edges[{ordinal}].dependent_assertion_id",
        )
        _require(prerequisite in assertion_by_id, f"{label}:unknown_prerequisite:{prerequisite}")
        _require(dependent in assertion_by_id, f"{label}:unknown_dependent:{dependent}")
        _require(prerequisite != dependent, f"{label}:self_edge:{edge_id}")
        endpoint_pair = (prerequisite, dependent)
        _require(endpoint_pair not in endpoint_pairs, f"{label}:duplicate_endpoint_pair:{edge_id}")
        endpoint_pairs.add(endpoint_pair)
        _require_equal(edge["material"], True, f"{label}.edges[{ordinal}].material")
        prerequisite_layer = assertion_by_id[prerequisite]["layer_id"]
        dependent_layer = assertion_by_id[dependent]["layer_id"]
        _require(
            LAYER_IDS.index(prerequisite_layer) < LAYER_IDS.index(dependent_layer),
            f"{label}:nonforward_or_cyclic_edge:{edge_id}",
        )
        row_core = {
            "ordinal": ordinal,
            "edge_id": edge_id,
            "prerequisite_assertion_id": prerequisite,
            "prerequisite_layer_id": prerequisite_layer,
            "dependent_assertion_id": dependent,
            "dependent_layer_id": dependent_layer,
            "material": True,
            "criteria_semantics": _semantic_text(
                edge["criteria_semantics"],
                f"{label}.edges[{ordinal}].criteria_semantics",
            ),
        }
        rows.append(_with_content_sha(row_core, domain=MATERIAL_DAG_EDGE_DOMAIN))
    _require(len(rows) >= 1, f"{label}.edges:min_items")
    return {
        "schema_id": ASSERTION_DAG_FIXTURE_SCHEMA_ID,
        "edge_count": len(rows),
        "material_edge_count": len(rows),
        "acyclic_by_strict_layer_order": True,
        "edges": rows,
        "edge_manifest_sha256": framed_sha256(
            "FF_FAILURE_DIAGNOSIS_MATERIAL_DAG_MANIFEST_V1",
            [row["content_sha256"] for row in rows],
        ),
    }


def _normalize_rivals(value: Any, label: str, assertion_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    role_counts = {role: 0 for role in RIVAL_ROLES}
    mechanism_by_role: dict[str, set[str]] = {role: set() for role in RIVAL_ROLES}
    for ordinal, item in enumerate(_array(value, label)):
        raw = _closed_mapping(
            item,
            {
                "rival_id",
                "role",
                "target_assertion_ids",
                "target_layer_ids",
                "mechanism_semantics",
                "predicted_signature_candidate",
                "materiality_floor_candidate",
                "falsifier_semantics",
                "distinguishing_test_ids",
            },
            f"{label}[{ordinal}]",
        )
        rival_id = _local_id(raw["rival_id"], f"{label}[{ordinal}].rival_id")
        _require(rival_id not in ids, f"{label}:duplicate_rival_id:{rival_id}")
        ids.add(rival_id)
        role = str(raw["role"])
        _require(role in RIVAL_ROLES, f"{label}[{ordinal}].role")
        role_counts[role] += 1
        target_assertions = _normalize_local_id_list(
            raw["target_assertion_ids"], f"{label}[{ordinal}].target_assertion_ids"
        )
        _require(
            set(target_assertions) <= assertion_ids,
            f"{label}[{ordinal}].unknown_target_assertion",
        )
        target_layers = [str(layer) for layer in _array(raw["target_layer_ids"], f"{label}[{ordinal}].target_layer_ids")]
        _require(len(target_layers) >= 1, f"{label}[{ordinal}].target_layer_ids:min_items")
        _require_equal(len(set(target_layers)), len(target_layers), f"{label}[{ordinal}].target_layer_ids:unique")
        _require(all(layer in LAYER_IDS[3:] for layer in target_layers), f"{label}[{ordinal}].target_layer_ids")
        mechanism = _semantic_text(raw["mechanism_semantics"], f"{label}[{ordinal}].mechanism_semantics")
        mechanism_key = unicodedata.normalize("NFKC", mechanism).casefold()
        mechanism_by_role[role].add(mechanism_key)
        result.append(
            {
                "ordinal": ordinal,
                "rival_id": rival_id,
                "role": role,
                "target_assertion_ids": target_assertions,
                "target_layer_ids": target_layers,
                "mechanism_semantics": mechanism,
                "predicted_signature_candidate": _normalize_signature(
                    raw["predicted_signature_candidate"],
                    f"{label}[{ordinal}].predicted_signature_candidate",
                ),
                "materiality_floor_candidate": _semantic_text(
                    raw["materiality_floor_candidate"],
                    f"{label}[{ordinal}].materiality_floor_candidate",
                ),
                "falsifier_semantics": _semantic_text(
                    raw["falsifier_semantics"], f"{label}[{ordinal}].falsifier_semantics"
                ),
                "distinguishing_test_ids": _normalize_local_id_list(
                    raw["distinguishing_test_ids"],
                    f"{label}[{ordinal}].distinguishing_test_ids",
                ),
            }
        )
    _require(len(result) >= 3, f"{label}:min_three_material_rivals")
    _require(all(count >= 1 for count in role_counts.values()), f"{label}:required_role_closure")
    preferred_semantics = mechanism_by_role["PREFERRED_MECHANISM"]
    _require(
        preferred_semantics.isdisjoint(mechanism_by_role["MECHANISM_DISTINCT_ALTERNATIVE"]),
        f"{label}:alternative_not_mechanism_distinct",
    )
    return result


def _normalize_tests(
    value: Any,
    label: str,
    *,
    rival_ids: set[str],
    assertion_ids: set[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for ordinal, item in enumerate(_array(value, label)):
        raw = _closed_mapping(
            item,
            {
                "test_id",
                "target_assertion_ids",
                "rival_ids",
                "discriminating_question",
                "synthetic_input_roles",
                "statistic_semantics",
                "expected_signature_by_rival",
                "materiality_floor_candidate",
                "correction_law_candidate",
                "missing_data_disposition",
                "nonfinite_disposition",
                "budget_charge_candidate",
            },
            f"{label}[{ordinal}]",
        )
        test_id = _local_id(raw["test_id"], f"{label}[{ordinal}].test_id")
        _require(test_id not in ids, f"{label}:duplicate_test_id:{test_id}")
        ids.add(test_id)
        targets = _normalize_local_id_list(
            raw["target_assertion_ids"], f"{label}[{ordinal}].target_assertion_ids"
        )
        _require(set(targets) <= assertion_ids, f"{label}[{ordinal}].unknown_assertion")
        compared = _normalize_local_id_list(raw["rival_ids"], f"{label}[{ordinal}].rival_ids", min_items=2)
        _require_equal(set(compared), rival_ids, f"{label}[{ordinal}].complete_rival_scope")
        expected_rows: list[dict[str, str]] = []
        expected_seen: set[str] = set()
        signature_seen: set[str] = set()
        for expected_ordinal, expected in enumerate(
            _array(raw["expected_signature_by_rival"], f"{label}[{ordinal}].expected_signature_by_rival")
        ):
            expected_raw = _closed_mapping(
                expected,
                {"rival_id", "signature"},
                f"{label}[{ordinal}].expected_signature_by_rival[{expected_ordinal}]",
            )
            rival_id = _local_id(
                expected_raw["rival_id"],
                f"{label}[{ordinal}].expected_signature_by_rival[{expected_ordinal}].rival_id",
            )
            _require(rival_id not in expected_seen, f"{label}[{ordinal}].duplicate_expected_rival")
            expected_seen.add(rival_id)
            signature = _token(
                expected_raw["signature"],
                f"{label}[{ordinal}].expected_signature_by_rival[{expected_ordinal}].signature",
            )
            signature_seen.add(signature)
            expected_rows.append({"rival_id": rival_id, "signature": signature})
        _require_equal(expected_seen, rival_ids, f"{label}[{ordinal}].expected_rival_closure")
        _require(len(signature_seen) >= 2, f"{label}[{ordinal}].not_discriminating")
        missing = str(raw["missing_data_disposition"])
        nonfinite = str(raw["nonfinite_disposition"])
        _require(missing in {"BLOCK", "INCONCLUSIVE"}, f"{label}[{ordinal}].missing_disposition")
        _require(nonfinite in {"BLOCK", "INCONCLUSIVE"}, f"{label}[{ordinal}].nonfinite_disposition")
        result.append(
            {
                "ordinal": ordinal,
                "test_id": test_id,
                "target_assertion_ids": targets,
                "rival_ids": compared,
                "discriminating_question": _semantic_text(
                    raw["discriminating_question"], f"{label}[{ordinal}].discriminating_question"
                ),
                "synthetic_input_roles": _normalize_text_list(
                    raw["synthetic_input_roles"], f"{label}[{ordinal}].synthetic_input_roles"
                ),
                "statistic_semantics": _semantic_text(
                    raw["statistic_semantics"], f"{label}[{ordinal}].statistic_semantics"
                ),
                "expected_signature_by_rival": sorted(expected_rows, key=lambda row: row["rival_id"]),
                "materiality_floor_candidate": _semantic_text(
                    raw["materiality_floor_candidate"],
                    f"{label}[{ordinal}].materiality_floor_candidate",
                ),
                "correction_law_candidate": _token(
                    raw["correction_law_candidate"],
                    f"{label}[{ordinal}].correction_law_candidate",
                ),
                "missing_data_disposition": missing,
                "nonfinite_disposition": nonfinite,
                "budget_charge_candidate": _integer(
                    raw["budget_charge_candidate"],
                    f"{label}[{ordinal}].budget_charge_candidate",
                    minimum=1,
                    maximum=100,
                ),
            }
        )
    _require(len(result) >= 1, f"{label}:min_items")
    return result


def _normalize_partition_plan(value: Any, label: str) -> dict[str, Any]:
    raw = _closed_mapping(
        value,
        {
            "generation_member_ids",
            "confirmation_member_ids",
            "generation_mask_semantics",
            "confirmation_mask_semantics",
            "reservation_order_candidate",
            "selection_correction_candidate",
            "zero_use_scope_candidate",
            "activation_count_ceiling",
        },
        label,
    )
    generation = _normalize_local_id_list(raw["generation_member_ids"], f"{label}.generation_member_ids")
    confirmation = _normalize_local_id_list(
        raw["confirmation_member_ids"], f"{label}.confirmation_member_ids"
    )
    return {
        "generation_member_ids": sorted(generation),
        "confirmation_member_ids": sorted(confirmation),
        "generation_mask_semantics": _semantic_text(
            raw["generation_mask_semantics"], f"{label}.generation_mask_semantics"
        ),
        "confirmation_mask_semantics": _semantic_text(
            raw["confirmation_mask_semantics"], f"{label}.confirmation_mask_semantics"
        ),
        "reservation_order_candidate": _token(
            raw["reservation_order_candidate"], f"{label}.reservation_order_candidate"
        ),
        "selection_correction_candidate": _token(
            raw["selection_correction_candidate"], f"{label}.selection_correction_candidate"
        ),
        "zero_use_scope_candidate": _normalize_text_list(
            raw["zero_use_scope_candidate"], f"{label}.zero_use_scope_candidate"
        ),
        "activation_count_ceiling": _integer(
            raw["activation_count_ceiling"],
            f"{label}.activation_count_ceiling",
            minimum=1,
            maximum=1,
        ),
    }


def _normalize_trial_controls(value: Any, label: str) -> dict[str, Any]:
    raw = _closed_mapping(
        value,
        {"trial_budget", "multiplicity_policy", "stopping_rule"},
        label,
    )
    return {
        "trial_budget": _integer(raw["trial_budget"], f"{label}.trial_budget", maximum=100),
        "multiplicity_policy": _token(raw["multiplicity_policy"], f"{label}.multiplicity_policy"),
        "stopping_rule": _semantic_text(raw["stopping_rule"], f"{label}.stopping_rule"),
    }


def _normalize_exploit_lane(value: Any, label: str, assertion_ids: set[str]) -> dict[str, Any]:
    raw = _closed_mapping(value, {"disposition", "candidates", "reason"}, label)
    disposition = str(raw["disposition"])
    _require(disposition in LANE_DISPOSITIONS, f"{label}.disposition")
    candidates: list[dict[str, Any]] = []
    ids: set[str] = set()
    for ordinal, item in enumerate(_array(raw["candidates"], f"{label}.candidates")):
        candidate = _closed_mapping(
            item,
            {
                "candidate_id",
                "target_assertion_ids",
                "change_semantics",
                "expected_signature_candidate",
                "kill_criteria",
                "same_parent_hypothesis",
                "preserves_estimand",
                "preserves_economic_hypothesis",
                "preserves_payer",
                "preserves_information_set",
                "portfolio_repair",
            },
            f"{label}.candidates[{ordinal}]",
        )
        candidate_id = _local_id(candidate["candidate_id"], f"{label}.candidates[{ordinal}].candidate_id")
        _require(candidate_id not in ids, f"{label}:duplicate_candidate_id:{candidate_id}")
        ids.add(candidate_id)
        targets = _normalize_local_id_list(
            candidate["target_assertion_ids"], f"{label}.candidates[{ordinal}].target_assertion_ids"
        )
        _require(set(targets) <= assertion_ids, f"{label}.candidates[{ordinal}].unknown_assertion")
        for key in (
            "same_parent_hypothesis",
            "preserves_estimand",
            "preserves_economic_hypothesis",
            "preserves_payer",
            "preserves_information_set",
        ):
            _require_equal(candidate[key], True, f"{label}.candidates[{ordinal}].{key}")
        _require_equal(candidate["portfolio_repair"], False, f"{label}.candidates[{ordinal}].portfolio_repair")
        candidates.append(
            {
                "ordinal": ordinal,
                "candidate_id": candidate_id,
                "target_assertion_ids": targets,
                "change_semantics": _semantic_text(
                    candidate["change_semantics"], f"{label}.candidates[{ordinal}].change_semantics"
                ),
                "expected_signature_candidate": _semantic_text(
                    candidate["expected_signature_candidate"],
                    f"{label}.candidates[{ordinal}].expected_signature_candidate",
                ),
                "kill_criteria": _semantic_text(
                    candidate["kill_criteria"], f"{label}.candidates[{ordinal}].kill_criteria"
                ),
                "same_parent_hypothesis": True,
                "preserves_estimand": True,
                "preserves_economic_hypothesis": True,
                "preserves_payer": True,
                "preserves_information_set": True,
                "portfolio_repair": False,
            }
        )
    reason = raw["reason"]
    if disposition == "PROPOSED_CANDIDATES":
        _require(len(candidates) >= 1, f"{label}:nonempty_candidates_required")
        _require(reason is None, f"{label}:reason_forbidden_when_nonempty")
        normalized_reason = None
    else:
        _require_equal(candidates, [], f"{label}:candidates_forbidden_when_abstaining")
        normalized_reason = _semantic_text(reason, f"{label}.reason")
    return {"disposition": disposition, "candidate_count": len(candidates), "candidates": candidates, "reason": normalized_reason}


def _normalize_explore_lane(
    value: Any,
    label: str,
    assertion_ids: set[str],
    test_ids: set[str],
) -> dict[str, Any]:
    raw = _closed_mapping(value, {"disposition", "candidates", "reason"}, label)
    disposition = str(raw["disposition"])
    _require(disposition in LANE_DISPOSITIONS, f"{label}.disposition")
    candidates: list[dict[str, Any]] = []
    ids: set[str] = set()
    reservation_ids: set[str] = set()
    for ordinal, item in enumerate(_array(raw["candidates"], f"{label}.candidates")):
        candidate = _closed_mapping(
            item,
            {
                "candidate_id",
                "new_hypothesis_identity_reservation_candidate",
                "target_assertion_ids",
                "mechanism_delta_semantics",
                "mathematical_object_candidate",
                "unique_prediction_candidate",
                "complexity_delta_candidate",
                "distinguishing_test_id",
                "kill_criteria",
                "reuses_parent_identity",
                "uses_parent_or_current_oos",
                "portfolio_repair",
            },
            f"{label}.candidates[{ordinal}]",
        )
        candidate_id = _local_id(candidate["candidate_id"], f"{label}.candidates[{ordinal}].candidate_id")
        reservation_id = _local_id(
            candidate["new_hypothesis_identity_reservation_candidate"],
            f"{label}.candidates[{ordinal}].new_hypothesis_identity_reservation_candidate",
        )
        _require(candidate_id not in ids, f"{label}:duplicate_candidate_id:{candidate_id}")
        _require(reservation_id not in reservation_ids, f"{label}:duplicate_reservation_id:{reservation_id}")
        ids.add(candidate_id)
        reservation_ids.add(reservation_id)
        targets = _normalize_local_id_list(
            candidate["target_assertion_ids"], f"{label}.candidates[{ordinal}].target_assertion_ids"
        )
        _require(set(targets) <= assertion_ids, f"{label}.candidates[{ordinal}].unknown_assertion")
        test_id = _local_id(
            candidate["distinguishing_test_id"], f"{label}.candidates[{ordinal}].distinguishing_test_id"
        )
        _require(test_id in test_ids, f"{label}.candidates[{ordinal}].unknown_test")
        for key in ("reuses_parent_identity", "uses_parent_or_current_oos", "portfolio_repair"):
            _require_equal(candidate[key], False, f"{label}.candidates[{ordinal}].{key}")
        candidates.append(
            {
                "ordinal": ordinal,
                "candidate_id": candidate_id,
                "new_hypothesis_identity_reservation_candidate": reservation_id,
                "target_assertion_ids": targets,
                "mechanism_delta_semantics": _semantic_text(
                    candidate["mechanism_delta_semantics"],
                    f"{label}.candidates[{ordinal}].mechanism_delta_semantics",
                ),
                "mathematical_object_candidate": _semantic_text(
                    candidate["mathematical_object_candidate"],
                    f"{label}.candidates[{ordinal}].mathematical_object_candidate",
                ),
                "unique_prediction_candidate": _semantic_text(
                    candidate["unique_prediction_candidate"],
                    f"{label}.candidates[{ordinal}].unique_prediction_candidate",
                ),
                "complexity_delta_candidate": _semantic_text(
                    candidate["complexity_delta_candidate"],
                    f"{label}.candidates[{ordinal}].complexity_delta_candidate",
                ),
                "distinguishing_test_id": test_id,
                "kill_criteria": _semantic_text(
                    candidate["kill_criteria"], f"{label}.candidates[{ordinal}].kill_criteria"
                ),
                "reuses_parent_identity": False,
                "uses_parent_or_current_oos": False,
                "portfolio_repair": False,
            }
        )
    reason = raw["reason"]
    if disposition == "PROPOSED_CANDIDATES":
        _require(len(candidates) >= 1, f"{label}:nonempty_candidates_required")
        _require(reason is None, f"{label}:reason_forbidden_when_nonempty")
        normalized_reason = None
    else:
        _require_equal(candidates, [], f"{label}:candidates_forbidden_when_abstaining")
        normalized_reason = _semantic_text(reason, f"{label}.reason")
    return {"disposition": disposition, "candidate_count": len(candidates), "candidates": candidates, "reason": normalized_reason}


def _normalize_pre_dirac(value: Any, label: str, assertion_ids: set[str], test_ids: set[str]) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    disposition = value.get("disposition")
    if disposition == "NO_DERIVED_LAW_CANDIDATE":
        raw = _closed_mapping(value, {"disposition", "reason"}, label)
        return {
            "disposition": disposition,
            "reason": _semantic_text(raw["reason"], f"{label}.reason"),
        }
    _require_equal(disposition, "PRE_DIRAC_HYPOTHESIS_ONLY", f"{label}.disposition")
    raw = _closed_mapping(
        value,
        {
            "disposition",
            "target_assertion_id",
            "minimal_added_state_or_parameter",
            "zero_extension_recovery_statement",
            "unique_prediction_candidate",
            "economic_backprojection",
            "distinguishing_test_id",
            "complexity_cost_candidate",
        },
        label,
    )
    assertion_id = _local_id(raw["target_assertion_id"], f"{label}.target_assertion_id")
    test_id = _local_id(raw["distinguishing_test_id"], f"{label}.distinguishing_test_id")
    _require(assertion_id in assertion_ids, f"{label}.unknown_assertion")
    _require(test_id in test_ids, f"{label}.unknown_test")
    backprojection_raw = _closed_mapping(
        raw["economic_backprojection"],
        {
            "actor",
            "action",
            "binding_constraint",
            "payer",
            "receiver",
            "observable_proxy_need",
            "negative_control",
            "disappearance_condition",
        },
        f"{label}.economic_backprojection",
    )
    return {
        "disposition": disposition,
        "target_assertion_id": assertion_id,
        "minimal_added_state_or_parameter": _semantic_text(
            raw["minimal_added_state_or_parameter"], f"{label}.minimal_added_state_or_parameter"
        ),
        "zero_extension_recovery_statement": _semantic_text(
            raw["zero_extension_recovery_statement"], f"{label}.zero_extension_recovery_statement"
        ),
        "unique_prediction_candidate": _semantic_text(
            raw["unique_prediction_candidate"], f"{label}.unique_prediction_candidate"
        ),
        "economic_backprojection": {
            key: _semantic_text(backprojection_raw[key], f"{label}.economic_backprojection.{key}")
            for key in sorted(backprojection_raw)
        },
        "distinguishing_test_id": test_id,
        "complexity_cost_candidate": _semantic_text(
            raw["complexity_cost_candidate"], f"{label}.complexity_cost_candidate"
        ),
    }


def compile_synthetic_diagnosis_intake(
    fixture_payload: Mapping[str, Any],
    *,
    fixture_raw_sha256: str,
    assertion_dependency_payload: Mapping[str, Any],
    assertion_dependency_raw_sha256: str,
) -> dict[str, Any]:
    expected = {
        "schema_id",
        "case_class",
        "target_identity_candidate",
        "frozen_hypothesis",
        "signature_candidate",
        "validity_intake",
        "assertions",
        "rivals",
        "tests",
        "partition_plan",
        "trial_controls",
        "exploit_lane",
        "explore_lane",
        "pre_dirac_question_candidate",
    }
    raw = _closed_mapping(fixture_payload, expected, "fixture")
    _require_equal(raw["schema_id"], FIXTURE_SCHEMA_ID, "fixture.schema_id")
    case_class = str(raw["case_class"])
    _require(case_class in CASE_CLASSES, "fixture.case_class")
    identity_raw = _closed_mapping(
        raw["target_identity_candidate"],
        {"hypothesis_candidate_id", "assertion_family_id"},
        "fixture.target_identity_candidate",
    )
    identity = {
        "hypothesis_candidate_id": _local_id(
            identity_raw["hypothesis_candidate_id"],
            "fixture.target_identity_candidate.hypothesis_candidate_id",
        ),
        "assertion_family_id": _local_id(
            identity_raw["assertion_family_id"],
            "fixture.target_identity_candidate.assertion_family_id",
        ),
    }
    hypothesis = _normalize_hypothesis(raw["frozen_hypothesis"], "fixture.frozen_hypothesis")
    signature_raw = _closed_mapping(
        raw["signature_candidate"], {"expected", "observed_synthetic"}, "fixture.signature_candidate"
    )
    signature = {
        "expected": _normalize_signature(signature_raw["expected"], "fixture.signature_candidate.expected"),
        "observed_synthetic": _normalize_signature(
            signature_raw["observed_synthetic"], "fixture.signature_candidate.observed_synthetic"
        ),
    }
    validity_raw = _closed_mapping(
        raw["validity_intake"],
        {
            "provenance_state",
            "information_time_state",
            "implementation_state",
            "metric_values_present",
            "production_identity_present",
        },
        "fixture.validity_intake",
    )
    validity = {
        "provenance_state": str(validity_raw["provenance_state"]),
        "information_time_state": str(validity_raw["information_time_state"]),
        "implementation_state": str(validity_raw["implementation_state"]),
        "metric_values_present": _boolean(
            validity_raw["metric_values_present"], "fixture.validity_intake.metric_values_present"
        ),
        "production_identity_present": _boolean(
            validity_raw["production_identity_present"],
            "fixture.validity_intake.production_identity_present",
        ),
    }
    _require(
        all(validity[key] in VALIDITY_STATES for key in (
            "provenance_state", "information_time_state", "implementation_state"
        )),
        "fixture.validity_intake.closed_states",
    )
    _require_equal(validity["metric_values_present"], False, "fixture.metric_values_forbidden")
    _require_equal(validity["production_identity_present"], False, "fixture.production_identity_forbidden")
    assertions = _normalize_assertions(raw["assertions"], "fixture.assertions")
    assertion_ids = {row["assertion_id"] for row in assertions}
    assertion_dependency_dag = _normalize_assertion_dependency_dag(
        assertion_dependency_payload,
        "assertion_dependency_fixture",
        assertions=assertions,
    )
    rivals = _normalize_rivals(raw["rivals"], "fixture.rivals", assertion_ids)
    rival_ids = {row["rival_id"] for row in rivals}
    tests = _normalize_tests(
        raw["tests"], "fixture.tests", rival_ids=rival_ids, assertion_ids=assertion_ids
    )
    test_ids = {row["test_id"] for row in tests}
    for rival in rivals:
        _require(
            set(rival["distinguishing_test_ids"]) <= test_ids,
            f"fixture.rivals.unknown_test:{rival['rival_id']}",
        )
        _require(
            bool(set(rival["distinguishing_test_ids"])),
            f"fixture.rivals.no_test:{rival['rival_id']}",
        )
    covered_rivals = {rival_id for test in tests for rival_id in test["rival_ids"]}
    _require_equal(covered_rivals, rival_ids, "fixture.tests.material_rival_coverage")
    partition = _normalize_partition_plan(raw["partition_plan"], "fixture.partition_plan")
    trial_controls = _normalize_trial_controls(raw["trial_controls"], "fixture.trial_controls")
    exploit_lane = _normalize_exploit_lane(raw["exploit_lane"], "fixture.exploit_lane", assertion_ids)
    explore_lane = _normalize_explore_lane(
        raw["explore_lane"], "fixture.explore_lane", assertion_ids, test_ids
    )
    pre_dirac = _normalize_pre_dirac(
        raw["pre_dirac_question_candidate"],
        "fixture.pre_dirac_question_candidate",
        assertion_ids,
        test_ids,
    )
    normalized_fixture = {
        "case_class": case_class,
        "target_identity_candidate": identity,
        "frozen_hypothesis": hypothesis,
        "signature_candidate": signature,
        "validity_intake": validity,
        "assertions": assertions,
        "material_assertion_dependency_dag": assertion_dependency_dag,
        "rivals": rivals,
        "tests": tests,
        "partition_plan": partition,
        "trial_controls": trial_controls,
        "exploit_lane": exploit_lane,
        "explore_lane": explore_lane,
        "pre_dirac_question_candidate": pre_dirac,
    }
    core = {
        "schema_id": INTAKE_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "PRIVATE_OFFLINE_SYNTHETIC_DIAGNOSIS_INTAKE_CANDIDATE",
        "planner_mode": "STANDALONE_SYNTHETIC_OR_QUARANTINED_OFFLINE",
        "diagnosis_path": DIAGNOSIS_PATH,
        "evidence_branch": EVIDENCE_BRANCH,
        "fixture_raw_sha256": _sha256(fixture_raw_sha256, "fixture_raw_sha256"),
        "assertion_dependency_fixture_raw_sha256": _sha256(
            assertion_dependency_raw_sha256,
            "assertion_dependency_fixture_raw_sha256",
        ),
        "normalized_fixture": normalized_fixture,
        "observed_numeric_metric_fields_present": False,
        "real_factor_or_asset_identity_present": False,
        "host_oos_canonical_or_runtime_evidence_present": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=INTAKE_DOMAIN)


def compile_hypothesis_mismatch_candidate(intake: Mapping[str, Any]) -> dict[str, Any]:
    fixture = intake["normalized_fixture"]
    expected = fixture["signature_candidate"]["expected"]
    observed = fixture["signature_candidate"]["observed_synthetic"]
    mismatch_rows = [
        {
            "ordinal": ordinal,
            "dimension": dimension,
            "expected_token": expected[dimension],
            "observed_synthetic_token": observed[dimension],
            "mismatch_candidate": expected[dimension] != observed[dimension],
        }
        for ordinal, dimension in enumerate(SIGNATURE_DIMENSIONS)
    ]
    core = {
        "schema_id": HYPOTHESIS_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "FROZEN_SYNTHETIC_HYPOTHESIS_AND_MECHANICAL_MISMATCH_CANDIDATE",
        "intake_content_sha256": intake["content_sha256"],
        "target_identity_candidate": fixture["target_identity_candidate"],
        "frozen_hypothesis": fixture["frozen_hypothesis"],
        "expected_signature_candidate": expected,
        "observed_synthetic_signature_candidate": observed,
        "mechanical_mismatch_vector": mismatch_rows,
        "material_mismatch_candidate_count": sum(
            1 for row in mismatch_rows if row["mismatch_candidate"]
        ),
        "root_cause_interpretation": None,
        "metric_is_not_cause": True,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=HYPOTHESIS_DOMAIN)


def compile_material_rival_registry_candidate(
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    for rival in intake["normalized_fixture"]["rivals"]:
        row_core = {
            **rival,
            "knowledge_role": "CURRENT_BLIND_DERIVATION_PRIMARY",
            "evidence_use": "NONE",
            "synthetic_freeze_order_candidate_only": True,
            "formal_pre_evidence_freeze_claimed": False,
        }
        rows.append(_with_content_sha(row_core, domain=RIVAL_ROW_DOMAIN))
    core = {
        "schema_id": RIVAL_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "MATERIAL_RIVAL_REGISTRY_CANDIDATE__NOT_FORMAL_FREEZE",
        "intake_content_sha256": intake["content_sha256"],
        "hypothesis_content_sha256": hypothesis["content_sha256"],
        "required_role_universe": sorted(RIVAL_ROLES),
        "material_rival_count": len(rows),
        "material_rivals": rows,
        "material_rival_manifest_sha256": framed_sha256(
            "FF_FAILURE_DIAGNOSIS_RIVAL_MANIFEST_V1",
            [row["content_sha256"] for row in rows],
        ),
        "advisory_prior_rows": [],
        "advisory_prior_count": 0,
        "stage2_a0_rows_consumed": False,
        "future_b2_phase_required_for_diagnosis_retrieval": True,
        "historical_performance_used": False,
        "knowledge_prior_can_adjudicate_current_case": False,
        "post_result_rival_addition_allowed": False,
        "future_question_namespace_required_for_new_rivals": True,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=RIVAL_DOMAIN)


def compile_partition_independence_plan_candidate(
    intake: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
) -> dict[str, Any]:
    partition = intake["normalized_fixture"]["partition_plan"]
    generation = partition["generation_member_ids"]
    confirmation = partition["confirmation_member_ids"]
    intersection = sorted(set(generation) & set(confirmation))
    generation_rows = [
        _with_content_sha(
            {"ordinal": ordinal, "member_id": member_id, "partition_role": "EVIDENCE_GENERATION"},
            domain=PARTITION_MEMBER_DOMAIN,
        )
        for ordinal, member_id in enumerate(generation)
    ]
    confirmation_rows = [
        _with_content_sha(
            {"ordinal": ordinal, "member_id": member_id, "partition_role": "UNTOUCHED_CONFIRMATION"},
            domain=PARTITION_MEMBER_DOMAIN,
        )
        for ordinal, member_id in enumerate(confirmation)
    ]
    core = {
        "schema_id": PARTITION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "SYNTHETIC_GENERATION_CONFIRMATION_PARTITION_PLAN_CANDIDATE",
        "intake_content_sha256": intake["content_sha256"],
        "rival_registry_content_sha256": rival_registry["content_sha256"],
        "diagnosis_path": DIAGNOSIS_PATH,
        "generation_partition": {
            "member_count": len(generation_rows),
            "members": generation_rows,
            "mask_semantics": partition["generation_mask_semantics"],
            "member_manifest_sha256": framed_sha256(
                "FF_FAILURE_DIAGNOSIS_GENERATION_MEMBER_MANIFEST_V1",
                [row["content_sha256"] for row in generation_rows],
            ),
        },
        "confirmation_partition": {
            "member_count": len(confirmation_rows),
            "members": confirmation_rows,
            "mask_semantics": partition["confirmation_mask_semantics"],
            "member_manifest_sha256": framed_sha256(
                "FF_FAILURE_DIAGNOSIS_CONFIRMATION_MEMBER_MANIFEST_V1",
                [row["content_sha256"] for row in confirmation_rows],
            ),
        },
        "intersection_member_ids": intersection,
        "synthetic_nonoverlap_candidate_pass": intersection == [],
        "reservation_order_candidate": partition["reservation_order_candidate"],
        "selection_correction_candidate": partition["selection_correction_candidate"],
        "zero_use_scope_candidate": partition["zero_use_scope_candidate"],
        "activation_count_ceiling": partition["activation_count_ceiling"],
        "formal_reservation_receipt_present": False,
        "formal_nonoverlap_receipt_present": False,
        "formal_zero_use_receipt_present": False,
        "formal_selection_correction_receipt_present": False,
        "same_partition_identification_forbidden": True,
        "identified_cause_allowed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PARTITION_DOMAIN)


def compile_distinguishing_test_registry_candidate(
    intake: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
    partition_plan: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    rival_ids = {row["rival_id"] for row in rival_registry["material_rivals"]}
    signature_vectors: dict[str, list[str]] = {rival_id: [] for rival_id in rival_ids}
    for test in intake["normalized_fixture"]["tests"]:
        signatures = {row["rival_id"]: row["signature"] for row in test["expected_signature_by_rival"]}
        _require_equal(set(signatures), rival_ids, f"tests.complete_rival_scope:{test['test_id']}")
        for rival_id in rival_ids:
            signature_vectors[rival_id].append(signatures[rival_id])
        row_core = {
            **test,
            "diagnosis_path": DIAGNOSIS_PATH,
            "result_fields_structurally_absent": True,
            "execution_allowed": False,
            "same_information_set_and_formation_mask_required": True,
            "future_label_membership_mutation_allowed": False,
        }
        rows.append(_with_content_sha(row_core, domain=TEST_ROW_DOMAIN))
    vector_values = {rival_id: tuple(values) for rival_id, values in signature_vectors.items()}
    _require_equal(
        len(set(vector_values.values())),
        len(vector_values),
        "tests.material_rivals_not_jointly_distinguishable",
    )
    controls = intake["normalized_fixture"]["trial_controls"]
    total_charge = sum(row["budget_charge_candidate"] for row in rows)
    applicability_rows = [
        {
            "ordinal": ordinal,
            "test_id": test["test_id"],
            "rival_id": rival_id,
            "applicability": "APPLICABLE",
            "expected_signature": next(
                item["signature"]
                for item in test["expected_signature_by_rival"]
                if item["rival_id"] == rival_id
            ),
        }
        for ordinal, (test, rival_id) in enumerate(
            (test, rival_id) for test in rows for rival_id in sorted(rival_ids)
        )
    ]
    core = {
        "schema_id": TEST_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "DISTINGUISHING_TEST_REGISTRY_CANDIDATE__NOT_EXECUTABLE",
        "intake_content_sha256": intake["content_sha256"],
        "rival_registry_content_sha256": rival_registry["content_sha256"],
        "partition_plan_content_sha256": partition_plan["content_sha256"],
        "registered_test_count": len(rows),
        "registered_tests": rows,
        "test_manifest_sha256": framed_sha256(
            "FF_FAILURE_DIAGNOSIS_TEST_MANIFEST_V1",
            [row["content_sha256"] for row in rows],
        ),
        "applicability_row_count": len(applicability_rows),
        "applicability_rows": applicability_rows,
        "applicability_complete": len(applicability_rows) == len(rows) * len(rival_ids),
        "rival_signature_vectors": [
            {"rival_id": rival_id, "signature_vector": list(vector_values[rival_id])}
            for rival_id in sorted(rival_ids)
        ],
        "all_material_rivals_jointly_distinguishable_in_plan": True,
        "trial_controls": controls,
        "total_budget_charge_candidate": total_charge,
        "budget_plan_feasible": total_charge <= controls["trial_budget"],
        "results_present": False,
        "execution_allowed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=TEST_DOMAIN)


def _material_transitive_prerequisites(
    assertions: Sequence[Mapping[str, Any]],
    dag: Mapping[str, Any],
) -> dict[str, list[str]]:
    assertion_by_id = {row["assertion_id"]: row for row in assertions}
    direct: dict[str, set[str]] = {assertion_id: set() for assertion_id in assertion_by_id}
    for edge in dag["edges"]:
        direct[edge["dependent_assertion_id"]].add(edge["prerequisite_assertion_id"])

    memo: dict[str, set[str]] = {}

    def visit(assertion_id: str) -> set[str]:
        if assertion_id in memo:
            return memo[assertion_id]
        expanded: set[str] = set()
        for prerequisite in direct[assertion_id]:
            expanded.add(prerequisite)
            expanded.update(visit(prerequisite))
        memo[assertion_id] = expanded
        return expanded

    result: dict[str, list[str]] = {}
    for assertion_id in assertion_by_id:
        result[assertion_id] = sorted(
            visit(assertion_id),
            key=lambda prerequisite: (
                LAYER_IDS.index(assertion_by_id[prerequisite]["layer_id"]),
                prerequisite,
            ),
        )
    return result


def compile_layer_assessment_plan_candidate(
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
    test_registry: Mapping[str, Any],
) -> dict[str, Any]:
    fixture = intake["normalized_fixture"]
    validity = fixture["validity_intake"]
    assertions = fixture["assertions"]
    assertion_by_id = {row["assertion_id"]: row for row in assertions}
    material_dag = fixture["material_assertion_dependency_dag"]
    transitive_prerequisites = _material_transitive_prerequisites(assertions, material_dag)
    assertion_test_map: dict[str, list[str]] = {row["assertion_id"]: [] for row in assertions}
    for test in test_registry["registered_tests"]:
        for assertion_id in test["target_assertion_ids"]:
            assertion_test_map[assertion_id].append(test["test_id"])
    layer_rows: list[dict[str, Any]] = []
    validity_by_layer = {
        "L0": validity["provenance_state"],
        "L1": validity["information_time_state"],
        "L2": validity["implementation_state"],
    }
    for ordinal, (layer_id, layer_name) in enumerate(zip(LAYER_IDS, LAYER_NAMES, strict=True)):
        assertion_ids = [row["assertion_id"] for row in assertions if row["layer_id"] == layer_id]
        planned_test_ids = sorted({test_id for assertion_id in assertion_ids for test_id in assertion_test_map[assertion_id]})
        if layer_id in validity_by_layer:
            source_state = validity_by_layer[layer_id]
            assessment_state = (
                "SYNTHETIC_TESTABLE" if source_state == "SYNTHETIC_TESTABLE" else "BLOCKED_BY_UPSTREAM"
            )
        elif any(
            row["layer_id"] == layer_id and row["planned_partition"] == "UNIDENTIFIABLE"
            for row in assertions
        ):
            assessment_state = "UNIDENTIFIABLE_CANDIDATE"
        elif assertion_ids:
            assessment_state = "EVIDENCE_REQUIRED"
        else:
            assessment_state = "UNASSESSED"
        row_core = {
            "ordinal": ordinal,
            "layer_id": layer_id,
            "layer_name": layer_name,
            "assessment_state_candidate": assessment_state,
            "assertion_ids": assertion_ids,
            "material_transitive_prerequisite_assertion_ids": sorted(
                {
                    prerequisite
                    for assertion_id in assertion_ids
                    for prerequisite in transitive_prerequisites[assertion_id]
                },
                key=lambda prerequisite: (
                    LAYER_IDS.index(assertion_by_id[prerequisite]["layer_id"]),
                    prerequisite,
                ),
            ),
            "global_evo_hard_gate_criteria_ids": [
                criteria_id for criteria_id, _ in CURRENT_EVO_HARD_GATES
            ],
            "planned_test_ids": planned_test_ids,
            "formal_assessment_status_present": False,
            "independent_clearance_receipt_present": False,
        }
        layer_rows.append(_with_content_sha(row_core, domain=LAYER_ROW_DOMAIN))
    material_targets = [assertion for assertion in assertions if assertion["material"]]
    scope_row_cores: list[dict[str, Any]] = []
    transitive_pair_count = 0
    global_gate_requirement_count = 0
    for assertion in material_targets:
        target_id = assertion["assertion_id"]
        for prerequisite_id in transitive_prerequisites[target_id]:
            prerequisite = assertion_by_id[prerequisite_id]
            key_core = {
                "target_assertion_id": target_id,
                "scope_kind": "MATERIAL_TRANSITIVE_ASSERTION_PREREQUISITE",
                "required_prerequisite_id": prerequisite_id,
            }
            scope_row_cores.append(
                {
                    "target_assertion_id": target_id,
                    "target_layer_id": assertion["layer_id"],
                    "scope_kind": "MATERIAL_TRANSITIVE_ASSERTION_PREREQUISITE",
                    "required_prerequisite_id": prerequisite_id,
                    "required_prerequisite_layer_id": prerequisite["layer_id"],
                    "receipt_family": "ASSERTION_LAYER_ASSESSMENT_RECEIPT",
                    "receipt_key_sha256": framed_sha256(
                        "FF_FAILURE_DIAGNOSIS_SCOPE_RECEIPT_KEY_V1", key_core
                    ),
                    "requirement": "INDEPENDENT_EXACT_CLEARED_RECEIPT_REQUIRED_FOR_FORMAL_QUALIFICATION",
                    "receipt_selection_law": "EXACT_ONE_LATEST_NONREVOKED_INDEPENDENT_HEAD",
                    "latest_head_required": True,
                    "independent_issuer_required": True,
                    "required_status": "CLEARED",
                    "current_receipt_present": False,
                    "same_trial_control_substitution_allowed": False,
                }
            )
            transitive_pair_count += 1
        for criteria_id, gate_layer_id in CURRENT_EVO_HARD_GATES:
            key_core = {
                "target_assertion_id": target_id,
                "scope_kind": "CURRENT_EVO_GLOBAL_HARD_GATE",
                "required_prerequisite_id": criteria_id,
            }
            scope_row_cores.append(
                {
                    "target_assertion_id": target_id,
                    "target_layer_id": assertion["layer_id"],
                    "scope_kind": "CURRENT_EVO_GLOBAL_HARD_GATE",
                    "required_prerequisite_id": criteria_id,
                    "required_prerequisite_layer_id": gate_layer_id,
                    "receipt_family": "CURRENT_EVO_GATE_CLEARANCE_RECEIPT",
                    "receipt_key_sha256": framed_sha256(
                        "FF_FAILURE_DIAGNOSIS_SCOPE_RECEIPT_KEY_V1", key_core
                    ),
                    "requirement": "INDEPENDENT_EXACT_CLEARED_RECEIPT_REQUIRED_FOR_FORMAL_QUALIFICATION",
                    "receipt_selection_law": "EXACT_ONE_LATEST_NONREVOKED_INDEPENDENT_HEAD",
                    "latest_head_required": True,
                    "independent_issuer_required": True,
                    "required_status": "CLEARED",
                    "current_receipt_present": False,
                    "same_trial_control_substitution_allowed": False,
                }
            )
            global_gate_requirement_count += 1
    scope_row_cores.sort(
        key=lambda row: (
            row["target_assertion_id"],
            0 if row["scope_kind"] == "MATERIAL_TRANSITIVE_ASSERTION_PREREQUISITE" else 1,
            LAYER_IDS.index(row["required_prerequisite_layer_id"]),
            row["required_prerequisite_id"],
        )
    )
    receipt_keys = [row["receipt_key_sha256"] for row in scope_row_cores]
    _require_equal(len(receipt_keys), len(set(receipt_keys)), "layer_plan.scope_keys_unique")
    scope_rows = [
        _with_content_sha(
            {"ordinal": ordinal, **row},
            domain=MATERIAL_SCOPE_ROW_DOMAIN,
        )
        for ordinal, row in enumerate(scope_row_cores)
    ]
    partitions = {
        "survival_test_targets": [],
        "failure_test_targets": [],
        "untested": [],
        "unidentifiable": [],
    }
    partition_key = {
        "SURVIVAL_TEST_TARGET": "survival_test_targets",
        "FAILURE_TEST_TARGET": "failure_test_targets",
        "UNTESTED": "untested",
        "UNIDENTIFIABLE": "unidentifiable",
    }
    for assertion in assertions:
        key = partition_key[assertion["planned_partition"]]
        partitions[key].append(
            {
                "assertion_id": assertion["assertion_id"],
                "layer_id": assertion["layer_id"],
                "current_status": "UNTESTED_CANDIDATE",
                "planned_test_ids": assertion_test_map[assertion["assertion_id"]],
                "observation_identifiability": assertion["observation_identifiability"],
            }
        )
    partition_union = [
        row["assertion_id"] for rows in partitions.values() for row in rows
    ]
    _require_equal(
        sorted(partition_union),
        sorted(assertion_test_map),
        "layer_plan.assertion_partition_exact_union",
    )
    core = {
        "schema_id": LAYER_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "LAYER_ASSESSMENT_AND_ASSERTION_PARTITION_PLAN_CANDIDATE",
        "intake_content_sha256": intake["content_sha256"],
        "hypothesis_content_sha256": hypothesis["content_sha256"],
        "rival_registry_content_sha256": rival_registry["content_sha256"],
        "test_registry_content_sha256": test_registry["content_sha256"],
        "layer_count": len(layer_rows),
        "layer_rows": layer_rows,
        "current_evo_global_hard_gate_rows": [
            {"ordinal": ordinal, "criteria_id": criteria_id, "layer_id": layer_id}
            for ordinal, (criteria_id, layer_id) in enumerate(CURRENT_EVO_HARD_GATES)
        ],
        "material_assertion_dependency_dag": material_dag,
        "material_target_assertion_count": len(material_targets),
        "material_transitive_prerequisite_pair_count": transitive_pair_count,
        "global_hard_gate_requirement_count": global_gate_requirement_count,
        "expanded_material_scope_row_count": len(scope_rows),
        "expanded_material_scope_rows": scope_rows,
        "expanded_material_scope_is_exact_union_of_transitive_dag_and_global_hard_gates": (
            len(scope_rows)
            == transitive_pair_count
            + len(material_targets) * len(CURRENT_EVO_HARD_GATES)
        ),
        "missing_extra_duplicate_or_pruned_scope_disposition": "BLOCK",
        "latest_receipt_selection_law": "EXACT_ONE_LATEST_NONREVOKED_INDEPENDENT_HEAD",
        "assertion_partition_plan": partitions,
        "assertion_partition_is_exact_disjoint_union": len(partition_union) == len(set(partition_union)),
        "latest_independent_assessment_receipts_present": False,
        "all_material_lower_layers_independently_cleared": False,
        "controlled_or_localized_can_substitute_for_cleared": False,
        "qualification_allowed": False,
        "identified_cause_allowed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=LAYER_DOMAIN)


def _future_question_rows(intake: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    explore = intake["normalized_fixture"]["explore_lane"]
    for candidate in explore["candidates"]:
        row_core = {
            "question_id": f"future-question-{candidate['candidate_id']}",
            "source_kind": "LOCAL_BLIND_DERIVATION_CANDIDATE",
            "source_candidate_id": candidate["candidate_id"],
            "question_semantics": candidate["unique_prediction_candidate"],
            "namespace": "FUTURE_QUESTION_ONLY",
            "current_diagnosis_or_revision_writeback_allowed": False,
        }
        rows.append(
            _with_content_sha(
                {"ordinal": len(rows), **row_core},
                domain=FUTURE_QUESTION_DOMAIN,
            )
        )
    return rows


def _branch_rows(lane: Mapping[str, Any], *, lane_name: str) -> list[dict[str, Any]]:
    return [
        _with_content_sha(
            {
                **candidate,
                "lane": lane_name,
                "advisory_only": True,
                "execution_allowed": False,
                "selection_by_performance": False,
            },
            domain=BRANCH_ROW_DOMAIN,
        )
        for candidate in lane["candidates"]
    ]


def compile_exploit_explore_dirac_advisory_candidate(
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
    test_registry: Mapping[str, Any],
    layer_plan: Mapping[str, Any],
) -> dict[str, Any]:
    fixture = intake["normalized_fixture"]
    exploit = fixture["exploit_lane"]
    explore = fixture["explore_lane"]
    exploit_rows = _branch_rows(exploit, lane_name="EXPLOIT")
    explore_rows = _branch_rows(explore, lane_name="EXPLORE")
    future_questions = _future_question_rows(intake)
    pre_dirac = fixture["pre_dirac_question_candidate"]
    core = {
        "schema_id": ADVISORY_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "EXPLOIT_EXPLORE_AND_PRE_DIRAC_ADVISORY_CANDIDATE_ONLY",
        "intake_content_sha256": intake["content_sha256"],
        "hypothesis_content_sha256": hypothesis["content_sha256"],
        "rival_registry_content_sha256": rival_registry["content_sha256"],
        "test_registry_content_sha256": test_registry["content_sha256"],
        "layer_plan_content_sha256": layer_plan["content_sha256"],
        "exploit_lane": {
            "disposition": exploit["disposition"],
            "candidate_count": len(exploit_rows),
            "ordered_candidates": exploit_rows,
            "reason": exploit["reason"],
            "same_parent_hypothesis_required": True,
        },
        "explore_lane": {
            "disposition": explore["disposition"],
            "candidate_count": len(explore_rows),
            "ordered_candidates": explore_rows,
            "reason": explore["reason"],
            "new_lineage_required": True,
        },
        "both_lanes_may_abstain": True,
        "dummy_branch_required": False,
        "branch_selection_by_performance": False,
        "portfolio_expression_repair_allowed": False,
        "future_question_namespace": future_questions,
        "future_question_count": len(future_questions),
        "post_result_new_rival_current_use_allowed": False,
        "stage2_a0_cross_phase_consumption_allowed": False,
        "future_phase_safe_retrieval_handoff": {
            "required_phase_branch": "B2_POSTRESULT_PLAN_SUPPORT",
            "current_prototype_invocation_status": "NOT_INVOKED_STANDALONE_PROTOTYPE",
            "may_implement_only_preexisting_rival_prediction_and_test_intents": True,
            "may_add_current_rival_prediction_or_test_intent": False,
            "post_result_new_explanation_namespace": "FUTURE_QUESTION_ONLY",
        },
        "dirac_eligibility_projection": {
            "dirac_status": "NOT_ELIGIBLE_STANDALONE_PROTOTYPE",
            "host_qualified_contradiction_receipt_present": False,
            "lower_layers_all_cleared": False,
            "formal_delta_allowed": False,
            "pre_dirac_question_candidate": pre_dirac,
        },
        "branch_selection_or_execution_allowed": False,
        "child_identity_or_handoff_allowed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=ADVISORY_DOMAIN)


def compile_planner_terminal_candidate(
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    partition_plan: Mapping[str, Any],
    test_registry: Mapping[str, Any],
    layer_plan: Mapping[str, Any],
    advisory: Mapping[str, Any],
) -> dict[str, Any]:
    fixture = intake["normalized_fixture"]
    validity = fixture["validity_intake"]
    validity_ready = (
        fixture["case_class"] == "SYNTHETIC_DIAGNOSIS_PLAN_CANDIDATE"
        and all(
            validity[key] == "SYNTHETIC_TESTABLE"
            for key in ("provenance_state", "information_time_state", "implementation_state")
        )
    )
    has_unidentifiable = bool(layer_plan["assertion_partition_plan"]["unidentifiable"])
    if not validity_ready:
        disposition = "BLOCKED_VALIDITY_INPUT"
        reasons = ["L0_L2_SYNTHETIC_VALIDITY_NOT_READY"]
    elif not partition_plan["synthetic_nonoverlap_candidate_pass"]:
        disposition = "BLOCKED_PARTITION_INDEPENDENCE"
        reasons = ["GENERATION_CONFIRMATION_MEMBER_OVERLAP"]
    elif has_unidentifiable:
        disposition = "INCONCLUSIVE_UNIDENTIFIABLE_DESIGN"
        reasons = ["OBSERVATION_EQUATION_CANNOT_IDENTIFY_AT_LEAST_ONE_ASSERTION"]
    elif not test_registry["budget_plan_feasible"]:
        disposition = "INCONCLUSIVE_NO_IDENTIFIABLE_DESIGN_WITHIN_BUDGET"
        reasons = ["REGISTERED_TEST_CHARGE_EXCEEDS_TRIAL_BUDGET"]
    else:
        disposition = "PLAN_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW"
        reasons = []
    forbidden = (
        "IDENTIFIED_CAUSE",
        "QUALIFIED_CONTRADICTION",
        "QUALIFICATION_RECOMMENDATION_OR_REQUEST",
        "FORMAL_DIRAC_DELTA",
        "FACTOR_PROMOTE_OR_REJECT_VERDICT",
        "BRANCH_SELECTION_OR_EXECUTION",
        "CODE_OR_FORMULA_HANDOFF",
        "OOS_ACCESS_OR_ALLOCATION",
        "HOST_OR_CANONICAL_WRITE",
        "SKILL_OR_RAG_RUNTIME_MUTATION",
        "RUNTIME_OR_DEPLOYMENT",
    )
    core = {
        "schema_id": TERMINAL_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_DIAGNOSIS_PLANNER_TERMINAL_CANDIDATE__NOT_DIAGNOSIS_OUTCOME",
        "intake_content_sha256": intake["content_sha256"],
        "hypothesis_content_sha256": hypothesis["content_sha256"],
        "partition_plan_content_sha256": partition_plan["content_sha256"],
        "test_registry_content_sha256": test_registry["content_sha256"],
        "layer_plan_content_sha256": layer_plan["content_sha256"],
        "advisory_content_sha256": advisory["content_sha256"],
        "planner_disposition": disposition,
        "review_scope": "PLANNER_DESIGN_REVIEW_ONLY",
        "design_review_may_not_grant_operating_authority": True,
        "design_review_may_not_substitute_for_factor_qualification_review": True,
        "ordered_block_or_inconclusive_reasons": [
            {"ordinal": ordinal, "reason_code": reason}
            for ordinal, reason in enumerate(reasons)
        ],
        "future_formal_diagnosis_terminal_universe": [
            "BLOCKED",
            "INCONCLUSIVE",
            "LAYER_LOCALIZED",
            "SUPPORTED_NOT_IDENTIFIED",
            "NO_IDENTIFIABLE_CAUSE_WITHIN_BUDGET",
        ],
        "cause_identified": False,
        "review_eligible": False,
        "qualification_recommended": False,
        "qualification_allowed": False,
        "formal_dirac_allowed": False,
        "branch_execution_allowed": False,
        "forbidden_output_count": len(forbidden),
        "forbidden_outputs": [
            {"ordinal": ordinal, "output_kind": output_kind}
            for ordinal, output_kind in enumerate(forbidden)
        ],
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=TERMINAL_DOMAIN)


def validate_failure_diagnosis_planner_bundle(
    *,
    stage2_binding: Mapping[str, Any],
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
    partition_plan: Mapping[str, Any],
    test_registry: Mapping[str, Any],
    layer_plan: Mapping[str, Any],
    advisory: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> None:
    _verify_content(stage2_binding, domain=STAGE2_BINDING_DOMAIN, label="bundle.stage2_binding")
    _verify_content(intake, domain=INTAKE_DOMAIN, label="bundle.intake")
    expected_hypothesis = compile_hypothesis_mismatch_candidate(intake)
    _require_equal(hypothesis, expected_hypothesis, "bundle.hypothesis_closed_equality")
    expected_rivals = compile_material_rival_registry_candidate(intake, hypothesis)
    _require_equal(rival_registry, expected_rivals, "bundle.rival_registry_closed_equality")
    expected_partition = compile_partition_independence_plan_candidate(intake, rival_registry)
    _require_equal(partition_plan, expected_partition, "bundle.partition_closed_equality")
    expected_tests = compile_distinguishing_test_registry_candidate(intake, rival_registry, partition_plan)
    _require_equal(test_registry, expected_tests, "bundle.test_registry_closed_equality")
    expected_layers = compile_layer_assessment_plan_candidate(
        intake, hypothesis, rival_registry, test_registry
    )
    _require_equal(layer_plan, expected_layers, "bundle.layer_plan_closed_equality")
    expected_advisory = compile_exploit_explore_dirac_advisory_candidate(
        intake,
        hypothesis,
        rival_registry,
        test_registry,
        layer_plan,
    )
    _require_equal(advisory, expected_advisory, "bundle.advisory_closed_equality")
    expected_terminal = compile_planner_terminal_candidate(
        intake, hypothesis, partition_plan, test_registry, layer_plan, advisory
    )
    _require_equal(terminal, expected_terminal, "bundle.terminal_closed_equality")


def compile_local_replay_report(
    *,
    stage2_binding: Mapping[str, Any],
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    rival_registry: Mapping[str, Any],
    partition_plan: Mapping[str, Any],
    test_registry: Mapping[str, Any],
    layer_plan: Mapping[str, Any],
    advisory: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    validate_failure_diagnosis_planner_bundle(
        stage2_binding=stage2_binding,
        intake=intake,
        hypothesis=hypothesis,
        rival_registry=rival_registry,
        partition_plan=partition_plan,
        test_registry=test_registry,
        layer_plan=layer_plan,
        advisory=advisory,
        terminal=terminal,
    )
    checks = (
        "DETACHED_STAGE2_PROTOTYPE_REVALIDATED_NOT_PROMOTED_TO_PREDECESSOR",
        "SYNTHETIC_OR_QUARANTINED_INPUT_ONLY",
        "METRIC_IS_NOT_CAUSE_AND_NUMERIC_RESULTS_ARE_STRUCTURALLY_ABSENT",
        "EXACT_L0_L9_LAYER_PLAN_PRESENT",
        "CURRENT_EVO_GLOBAL_HARD_GATES_NOT_PRUNED",
        "MATERIAL_ASSERTION_DAG_TRANSITIVE_CLOSURE_UNIONED_WITH_GLOBAL_HARD_GATES",
        "EXACT_ONE_LATEST_NONREVOKED_INDEPENDENT_RECEIPT_HEAD_REQUIRED",
        "LOWER_LAYER_CONTROL_OR_LOCALIZATION_DOES_NOT_SUBSTITUTE_FOR_CLEARANCE",
        "MINIMUM_THREE_MATERIAL_RIVAL_ROLES_CLOSED",
        "ALL_MATERIAL_RIVALS_HAVE_DISTINGUISHING_TESTS",
        "GENERATION_CONFIRMATION_NONOVERLAP_IS_RECOMPUTED",
        "SAME_PARTITION_IDENTIFICATION_IS_FORBIDDEN",
        "RESULT_FIELDS_AND_IDENTIFIED_CAUSE_ARE_STRUCTURALLY_ABSENT",
        "ASSERTION_TEST_TARGET_PARTITION_IS_EXACT_AND_DISJOINT",
        "EXPLOIT_AND_EXPLORE_ALLOW_ZERO_TO_N_AND_ABSTENTION",
        "POST_RESULT_NEW_EXPLANATIONS_ARE_FUTURE_QUESTION_ONLY",
        "DIRAC_IS_NOT_ELIGIBLE_WITHOUT_HOST_QUALIFIED_CONTRADICTION",
        "NO_HOST_OOS_CANONICAL_SKILL_RAG_RUNTIME_OR_DEPLOYMENT_AUTHORITY",
    )
    core = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_status": "LOCAL_OFFLINE_REPLAY_PASS__NOT_OPERATING_OR_DIAGNOSIS_AUTHORITY",
        "artifact_bindings": {
            "stage2_binding_content_sha256": stage2_binding["content_sha256"],
            "intake_content_sha256": intake["content_sha256"],
            "hypothesis_content_sha256": hypothesis["content_sha256"],
            "rival_registry_content_sha256": rival_registry["content_sha256"],
            "partition_plan_content_sha256": partition_plan["content_sha256"],
            "test_registry_content_sha256": test_registry["content_sha256"],
            "layer_plan_content_sha256": layer_plan["content_sha256"],
            "advisory_content_sha256": advisory["content_sha256"],
            "terminal_content_sha256": terminal["content_sha256"],
        },
        "ordered_check_count": len(checks),
        "ordered_checks": [
            {"ordinal": ordinal, "check_id": check, "result": "PASS"}
            for ordinal, check in enumerate(checks)
        ],
        "pure_offline_transform_performed": True,
        "external_io_operation_count_after_explicit_input_read": 0,
        "retrieval_runtime_executed": False,
        "host_or_canonical_memory_accessed": False,
        "oos_accessed": False,
        "skill_or_rag_runtime_invoked_or_mutated": False,
        "network_or_ambient_discovery_performed": False,
        "diagnostic_tests_executed": False,
        "identified_cause_or_qualification_issued": False,
        "branch_or_dirac_execution_performed": False,
        "canonical_write_or_promotion_performed": False,
        "runtime_or_deployment_performed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REPORT_DOMAIN)


def compile_revision_predecessor_binding(
    revision_predecessor_manifest_path: Path,
) -> dict[str, Any]:
    raw, payload = _read_json_object(
        Path(revision_predecessor_manifest_path),
        label="revision_predecessor_manifest",
    )
    _verify_content(payload, domain=PACKET_DOMAIN, label="revision_predecessor_manifest")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    _require_equal(
        raw_sha256,
        R2_REVISION_PREDECESSOR_RAW_SHA256,
        "revision_predecessor.raw_sha256",
    )
    _require_equal(
        payload["content_sha256"],
        R2_REVISION_PREDECESSOR_CONTENT_SHA256,
        "revision_predecessor.content_sha256",
    )
    _require_equal(payload["factor_forge_successor"], False, "revision_predecessor.successor")
    _require_equal(payload["permissions_opened_count"], 0, "revision_predecessor.permissions")
    _require_equal(payload["authority_effect"], AUTHORITY_EFFECT, "revision_predecessor.authority")
    return {
        "revision_predecessor_declared_packet_id": payload["packet_id"],
        "revision_predecessor_manifest_raw_sha256": raw_sha256,
        "revision_predecessor_manifest_content_sha256": payload["content_sha256"],
        "revision_predecessor_is_factor_forge_predecessor": False,
        "revision_predecessor_authority_effect": AUTHORITY_EFFECT,
        "r2_delivery_with_r1_packet_id_collision_acknowledged": True,
        "forward_only_successor_required": True,
    }


def _write_private_bytes_once(root: Path, name: str, payload: bytes) -> None:
    _require("/" not in name and name not in {"", ".", ".."}, "write_bytes:name")
    directory_descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_descriptor,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.fsync(directory_descriptor)
        os.close(directory_descriptor)


def _packet_artifact_spec() -> tuple[tuple[str, str], ...]:
    return (
        ("00_stage2_input_binding.json", "DETACHED_STAGE2_INPUT_BINDING"),
        ("01_closed_synthetic_diagnosis_intake.json", "CLOSED_SYNTHETIC_DIAGNOSIS_INTAKE"),
        ("02_frozen_hypothesis_and_mismatch.json", "FROZEN_HYPOTHESIS_AND_MISMATCH"),
        ("03_material_rival_registry.json", "MATERIAL_RIVAL_REGISTRY"),
        ("04_generation_confirmation_partition_plan.json", "GENERATION_CONFIRMATION_PARTITION_PLAN"),
        ("05_distinguishing_test_registry.json", "DISTINGUISHING_TEST_REGISTRY"),
        ("06_layer_assessment_plan.json", "LAYER_ASSESSMENT_PLAN"),
        ("07_exploit_explore_dirac_advisory.json", "EXPLOIT_EXPLORE_DIRAC_ADVISORY"),
        ("08_planner_terminal_candidate.json", "PLANNER_TERMINAL_CANDIDATE"),
        ("09_local_replay_report.json", "LOCAL_REPLAY_REPORT"),
        ("10_pinned_compiler_source.py", "PINNED_COMPILER_SOURCE"),
    )


def compile_packet_manifest(
    *,
    artifact_rows: Sequence[Mapping[str, Any]],
    stage2_binding: Mapping[str, Any],
    intake: Mapping[str, Any],
    terminal: Mapping[str, Any],
    revision_predecessor_binding: Mapping[str, Any],
    compiler_source_raw: bytes,
) -> dict[str, Any]:
    _require_equal(
        [row["ordinal"] for row in artifact_rows],
        list(range(11)),
        "packet.artifact_ordinals",
    )
    compiler_row = artifact_rows[-1]
    _require_equal(compiler_row["role"], "PINNED_COMPILER_SOURCE", "packet.compiler_role")
    _require_equal(
        compiler_row["sha256"],
        hashlib.sha256(compiler_source_raw).hexdigest(),
        "packet.compiler_artifact_sha256",
    )
    _require_equal(compiler_row["bytes"], len(compiler_source_raw), "packet.compiler_artifact_bytes")
    artifact_commitment = hashlib.sha256(
        PACKET_ARTIFACT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in artifact_rows)
    ).hexdigest()
    loaded_compiler_raw = read_stable_regular_bytes(
        Path(__file__),
        label="failure_diagnosis_offline_compiler_module",
        max_bytes=4 * 1024 * 1024,
    )
    _require_equal(
        compiler_source_raw,
        loaded_compiler_raw,
        "packet.pinned_compiler_must_equal_loaded_module",
    )
    core = {
        "schema_id": PACKET_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": PACKET_ID,
        "manifest_status": (
            "STANDALONE_OFFLINE_DIAGNOSIS_PLANNER_PROTOTYPE_COMPLETE__"
            "ALL_FACTOR_FORGE_DIAGNOSIS_AND_OPERATING_AUTHORITY_UNBOUND_BLOCKING"
        ),
        "lineage_mode": "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE",
        "factor_forge_successor": False,
        "direct_predecessor_manifest_raw_sha256": None,
        "revision_lineage": dict(revision_predecessor_binding),
        "normative_dependency_count": 0,
        "may_satisfy_any_factor_forge_gate": False,
        "prototype_input_dependency_count": 1,
        "prototype_input_dependencies": [
            {
                "ordinal": 0,
                "role": "DETACHED_STAGE2_IMPLEMENTATION_PROVENANCE_ONLY__NOT_PREDECESSOR",
                "stage2_packet_id": stage2_binding["stage2_packet"]["packet_id"],
                "stage2_compiler_sha256": stage2_binding[
                    "implementation_provenance_projection"
                ]["compiler_profile"]["sha256"],
                "stage2_binding_content_sha256": stage2_binding["content_sha256"],
                "stage2_response_semantics_bound": False,
                "authority_effect": AUTHORITY_EFFECT,
            }
        ],
        "planner_input_fixture_bindings": {
            "diagnosis_fixture_raw_sha256": intake["fixture_raw_sha256"],
            "assertion_dependency_fixture_raw_sha256": intake[
                "assertion_dependency_fixture_raw_sha256"
            ],
            "closed_intake_content_sha256": intake["content_sha256"],
            "synthetic_or_quarantined_only": True,
            "authority_effect": AUTHORITY_EFFECT,
        },
        "non_authorizing_contract_context": [
            "FACTORFORGE_FAILURE_DIAGNOSIS_CONTRACT_V1_REVIEW_DRAFT",
            "FACTORFORGE_EPISTEMIC_EVOLUTION_V2_CURRENT_CONTRACT",
            "FACTORFORGE_MECHANISM_CONDITIONED_MEASUREMENT_PROGRAM_V1",
        ],
        "artifact_count": 11,
        "ordered_artifacts": [dict(row) for row in artifact_rows],
        "artifact_manifest_commitment_sha256": artifact_commitment,
        "compiler_profile": {
            "module": "factor_factory/epistemic_failure_diagnosis_offline.py",
            "bytes": len(compiler_source_raw),
            "sha256": hashlib.sha256(compiler_source_raw).hexdigest(),
            "pinned_packet_artifact_path": compiler_row["path"],
            "pinned_packet_artifact_raw_sha256": compiler_row["sha256"],
            "pinned_source_is_exact_loaded_module_bytes": True,
            "historical_validation_requires_pinned_compiler_bytes": True,
            "historical_compiler_is_recoverable_from_packet": True,
            "canonicalization": "RFC8785_INTEGER_ONLY_ACCEPTED_JSON_PROFILE",
            "content_digest_formula": (
                "SHA256(UTF8(domain)||0x00||RFC8785(payload_without_content_sha256))"
            ),
            "artifact_commitment_formula": (
                "SHA256(UTF8(FF_FAILURE_DIAGNOSIS_PACKET_ARTIFACT_MANIFEST_V1)"
                "||0x00||CONCAT(ordered_artifact_raw_sha256_bytes))"
            ),
            "planner_semantics": (
                "L0_L9_EXACT10__MATERIAL_RIVAL_EXACT_CLOSURE__"
                "GENERATION_CONFIRMATION_NONOVERLAP__EXPLOIT_EXPLORE_ZERO_TO_N"
            ),
        },
        "planner_terminal_disposition": terminal["planner_disposition"],
        "offline_transform_allowed": True,
        "diagnostic_test_execution_allowed": False,
        "identified_cause_issuance_allowed": False,
        "host_qualification_or_submission_allowed": False,
        "formal_dirac_allowed": False,
        "branch_selection_or_execution_allowed": False,
        "host_or_canonical_memory_allowed": False,
        "oos_allowed": False,
        "skill_or_rag_runtime_allowed": False,
        "network_or_ambient_discovery_allowed": False,
        "canonical_write_or_promotion_allowed": False,
        "runtime_or_deployment_allowed": False,
        "steward_or_host_authority_present": False,
        "permissions_opened_count": 0,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PACKET_DOMAIN)


def _compile_bundle(
    *,
    stage2_binding: Mapping[str, Any],
    fixture_payload: Mapping[str, Any],
    fixture_raw_sha256: str,
    assertion_dependency_payload: Mapping[str, Any],
    assertion_dependency_raw_sha256: str,
) -> tuple[dict[str, Any], ...]:
    intake = compile_synthetic_diagnosis_intake(
        fixture_payload,
        fixture_raw_sha256=fixture_raw_sha256,
        assertion_dependency_payload=assertion_dependency_payload,
        assertion_dependency_raw_sha256=assertion_dependency_raw_sha256,
    )
    hypothesis = compile_hypothesis_mismatch_candidate(intake)
    rivals = compile_material_rival_registry_candidate(intake, hypothesis)
    partition = compile_partition_independence_plan_candidate(intake, rivals)
    tests = compile_distinguishing_test_registry_candidate(intake, rivals, partition)
    layers = compile_layer_assessment_plan_candidate(intake, hypothesis, rivals, tests)
    advisory = compile_exploit_explore_dirac_advisory_candidate(
        intake, hypothesis, rivals, tests, layers
    )
    terminal = compile_planner_terminal_candidate(
        intake, hypothesis, partition, tests, layers, advisory
    )
    report = compile_local_replay_report(
        stage2_binding=stage2_binding,
        intake=intake,
        hypothesis=hypothesis,
        rival_registry=rivals,
        partition_plan=partition,
        test_registry=tests,
        layer_plan=layers,
        advisory=advisory,
        terminal=terminal,
    )
    return intake, hypothesis, rivals, partition, tests, layers, advisory, terminal, report


def _load_fixture(path: Path) -> tuple[bytes, dict[str, Any]]:
    return _read_json_object(Path(path), label="failure_diagnosis_fixture")


def _load_assertion_dependency_fixture(path: Path) -> tuple[bytes, dict[str, Any]]:
    return _read_json_object(Path(path), label="assertion_dependency_fixture")


def validate_failure_diagnosis_offline_candidate_packet(
    packet_manifest_path: Path,
    *,
    phase_safe_manifest_path: Path,
    diagnosis_fixture_path: Path,
    assertion_dependency_fixture_path: Path,
    revision_predecessor_manifest_path: Path,
) -> dict[str, Any]:
    manifest_path = Path(packet_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    _require_equal(manifest_path.name, "packet_manifest.json", "packet_manifest:name")
    root = manifest_path.parent
    specs = _packet_artifact_spec()
    expected_names = {"packet_manifest.json", *(name for name, _ in specs)}
    actual_names: set[str] = set()
    for path in root.iterdir():
        metadata = path.lstat()
        _require(
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_nlink == 1,
            f"packet_entry:unsafe:{path.name}",
        )
        actual_names.add(path.name)
    _require_equal(actual_names, expected_names, "packet:exact12_closure")
    _, manifest = _read_json_object(manifest_path, label="failure_diagnosis_packet_manifest")
    _verify_content(manifest, domain=PACKET_DOMAIN, label="failure_diagnosis_packet_manifest")
    rows: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    compiler_source_raw: bytes | None = None
    for ordinal, (name, role) in enumerate(specs):
        if role == "PINNED_COMPILER_SOURCE":
            raw = read_stable_regular_bytes(
                root / name,
                label=f"packet_artifact:{name}",
                max_bytes=4 * 1024 * 1024,
                require_private=True,
            )
            compiler_source_raw = raw
            payload = None
        else:
            raw, payload = _read_json_object(root / name, label=f"packet_artifact:{name}")
        rows.append(
            {
                "ordinal": ordinal,
                "role": role,
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        if payload is not None:
            payloads[role] = payload
    _require_equal(manifest["ordered_artifacts"], rows, "packet_manifest:artifact_rows")
    _require_equal(manifest["artifact_count"], 11, "packet_manifest:artifact_count")
    _require(compiler_source_raw is not None, "packet:compiler_source_missing")
    loaded_module_raw = read_stable_regular_bytes(
        Path(__file__),
        label="loaded_failure_diagnosis_compiler",
        max_bytes=4 * 1024 * 1024,
    )
    _require_equal(
        compiler_source_raw,
        loaded_module_raw,
        "packet:pinned_compiler_not_loaded_module",
    )
    stage2_binding = compile_stage2_input_binding(Path(phase_safe_manifest_path))
    _require_equal(
        payloads["DETACHED_STAGE2_INPUT_BINDING"],
        stage2_binding,
        "packet:stage2_binding_closed_equality",
    )
    fixture_raw, fixture_payload = _load_fixture(Path(diagnosis_fixture_path))
    dependency_raw, dependency_payload = _load_assertion_dependency_fixture(
        Path(assertion_dependency_fixture_path)
    )
    bundle = _compile_bundle(
        stage2_binding=stage2_binding,
        fixture_payload=fixture_payload,
        fixture_raw_sha256=hashlib.sha256(fixture_raw).hexdigest(),
        assertion_dependency_payload=dependency_payload,
        assertion_dependency_raw_sha256=hashlib.sha256(dependency_raw).hexdigest(),
    )
    roles = [role for _, role in specs[1:-1]]
    for role, expected_payload in zip(roles, bundle, strict=True):
        _require_equal(payloads[role], expected_payload, f"packet:{role}:closed_equality")
    revision_predecessor_binding = compile_revision_predecessor_binding(
        Path(revision_predecessor_manifest_path)
    )
    expected_manifest = compile_packet_manifest(
        artifact_rows=rows,
        stage2_binding=stage2_binding,
        intake=payloads["CLOSED_SYNTHETIC_DIAGNOSIS_INTAKE"],
        terminal=payloads["PLANNER_TERMINAL_CANDIDATE"],
        revision_predecessor_binding=revision_predecessor_binding,
        compiler_source_raw=compiler_source_raw,
    )
    _require_equal(manifest, expected_manifest, "packet_manifest:closed_equality")
    return manifest


def write_failure_diagnosis_offline_candidate_packet(
    output_root: Path,
    *,
    phase_safe_manifest_path: Path,
    diagnosis_fixture_path: Path,
    assertion_dependency_fixture_path: Path,
    revision_predecessor_manifest_path: Path,
) -> dict[str, Any]:
    stage2_binding = compile_stage2_input_binding(Path(phase_safe_manifest_path))
    fixture_raw, fixture_payload = _load_fixture(Path(diagnosis_fixture_path))
    dependency_raw, dependency_payload = _load_assertion_dependency_fixture(
        Path(assertion_dependency_fixture_path)
    )
    bundle = _compile_bundle(
        stage2_binding=stage2_binding,
        fixture_payload=fixture_payload,
        fixture_raw_sha256=hashlib.sha256(fixture_raw).hexdigest(),
        assertion_dependency_payload=dependency_payload,
        assertion_dependency_raw_sha256=hashlib.sha256(dependency_raw).hexdigest(),
    )
    revision_predecessor_binding = compile_revision_predecessor_binding(
        Path(revision_predecessor_manifest_path)
    )
    compiler_source_raw = read_stable_regular_bytes(
        Path(__file__),
        label="failure_diagnosis_offline_compiler_module",
        max_bytes=4 * 1024 * 1024,
    )
    specs = _packet_artifact_spec()
    json_artifacts = tuple(
        (name, role, payload)
        for (name, role), payload in zip(
            specs[:-1],
            (stage2_binding, *bundle),
            strict=True,
        )
    )
    root = Path(output_root)
    _require(
        root.is_absolute() and root.name not in {"", ".", ".."} and ".." not in root.parts,
        "output_root:invalid",
    )
    parent = root.parent.resolve(strict=True)
    parent_descriptor = _open_absolute_directory_fd(parent)
    staging_descriptor: int | None = None
    try:
        _require(not _entry_exists_at(parent_descriptor, root.name), "output_root:exists")
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
            "staging:not_private",
        )
        for name, _, payload in json_artifacts:
            write_workspace_json_once(staging_root, name, payload)
        compiler_name, compiler_role = specs[-1]
        _write_private_bytes_once(staging_root, compiler_name, compiler_source_raw)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role) in enumerate(specs)
        ]
        terminal = json_artifacts[8][2]
        manifest = compile_packet_manifest(
            artifact_rows=rows,
            stage2_binding=stage2_binding,
            intake=json_artifacts[1][2],
            terminal=terminal,
            revision_predecessor_binding=revision_predecessor_binding,
            compiler_source_raw=compiler_source_raw,
        )
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        validate_failure_diagnosis_offline_candidate_packet(
            staging_root / "packet_manifest.json",
            phase_safe_manifest_path=Path(phase_safe_manifest_path),
            diagnosis_fixture_path=Path(diagnosis_fixture_path),
            assertion_dependency_fixture_path=Path(assertion_dependency_fixture_path),
            revision_predecessor_manifest_path=Path(revision_predecessor_manifest_path),
        )
        _validate_staging_closure(
            staging_descriptor,
            expected_names={"packet_manifest.json", *(row["path"] for row in rows)},
        )
        current = os.stat(staging_name, dir_fd=parent_descriptor, follow_symlinks=False)
        _require_equal(
            (current.st_dev, current.st_ino),
            (pinned.st_dev, pinned.st_ino),
            "staging:identity_changed",
        )
        _require(not _entry_exists_at(parent_descriptor, root.name), "output_root:race")
        os.fsync(staging_descriptor)
        _atomic_publish_directory_noreplace_at(parent_descriptor, staging_name, root.name)
        os.fsync(parent_descriptor)
        return manifest
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        os.close(parent_descriptor)
