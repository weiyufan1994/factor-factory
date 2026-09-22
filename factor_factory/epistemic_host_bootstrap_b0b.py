from __future__ import annotations

import ast
import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from factor_factory.epistemic_binding import (
    _atomic_publish_directory_noreplace_at,
    _entry_exists_at,
    _open_absolute_directory_fd,
)
from factor_factory.epistemic_host_bootstrap import (
    AUTHORITY_EFFECT,
    EXPECTED_STAGE1B_ARTIFACTS,
    FrozenBootstrapContracts,
    compile_b0_obligation_skeleton,
    validate_frozen_bootstrap_contracts,
)
from factor_factory.research_org.contracts import (
    strict_json_loads,
    write_workspace_json_once,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


B0B_GAP_LEDGER_SCHEMA_ID = (
    "factorforge_epistemic_host_bootstrap_b0b_expectation_gap_ledger_v1"
)
B0B_LAYOUT_SCHEMA_ID = (
    "factorforge_epistemic_host_bootstrap_b0b_exact261_layout_scaffold_v1"
)
B0B_REPORT_SCHEMA_ID = (
    "B0_B_LOCAL_NONAUTHORITATIVE_SEMANTIC_CONFORMANCE_CANDIDATE_REPORT_V1"
)
B0B_IMPLEMENTATION_INVENTORY_SCHEMA_ID = (
    "factorforge_epistemic_host_bootstrap_b0b_implementation_inventory_v1"
)
B0B_PLAN_SCHEMA_ID = "factorforge_epistemic_host_bootstrap_b0b_plan_v1"
B0B_PACKET_SCHEMA_ID = "factorforge_epistemic_host_bootstrap_b0b_packet_manifest_v1"
SCHEMA_VERSION = "1.0.0"

B0B_STATUS = "B0_B1_SCAFFOLD_COMPLETE__EXPECTATION_AUTHORITY_UNBOUND_BLOCKING"
B0B_EXECUTION_MODE = "SYNTHETIC_OFFLINE_SCAFFOLD_ONLY"
B0B_LOCAL_INTEGRITY_PROFILE_ID = (
    "LOCAL_NONAUTHORITATIVE_CANDIDATE_INTEGRITY_ONLY"
)

B0A_R2_MANIFEST_BYTES = 3710
B0A_R2_MANIFEST_SHA256 = (
    "308051b8f15be4afa71a899d7b4d751b13b5db44c6df62b5fe75f712cc2f4260"
)
B0A_R2_PACKET_ID = "FF_EPISTEMIC_HOST_BOOTSTRAP_B0_OFFLINE_CANDIDATE_20260828_R2"
STAGE1B_SCHEMA_BUNDLE_SHA256 = EXPECTED_STAGE1B_ARTIFACTS[0][2]

MANDATORY_OWNER_RULE_ORDINALS = (6, 11, 16, 27, 31)
EXTRA_PASS_RULE_ORDINALS = (11, 16, 27, 31)
MANDATORY_SOURCE_COUNTS = (10, 36, 50, 43, 31)
MANDATORY_SOURCE_BASES = (0, 10, 46, 96, 139)
RULE6_EXPECTATIONS = (
    ("PASS", "NONE"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
    ("BLOCKED", "KEY_UNIVERSE_INCOMPLETE"),
    ("FAIL", "KEY_PURPOSE_OR_AUTHORITY_COLLISION"),
)

B0B_BLOCKING_CONDITIONS = (
    "DUAL_GIT_APPROVED_EXPECTATION_ASSIGNMENT_UNBOUND",
    "ONTOLOGY_STEWARD_APPROVAL_UNBOUND",
    "REFERENCE_STEWARD_APPROVAL_UNBOUND",
    "OS_SEALED_DEFINITION_ACTIVATION_UNBOUND",
    "PROTECTED_FIXTURE_SCHEMAS_AND_BYTES_UNBOUND",
    "PINNED_NONCALLER_SEMANTIC_ENGINE_UNBOUND",
    "FORMAL_DEFINITION_PREFLIGHT_AND_SEMANTIC_RECEIPT_UNBOUND",
)

EXPECTED_B0B_IMPLEMENTATION_FILES = (
    "factor_factory/epistemic_host_bootstrap_b0b.py",
    "scripts/build_factorforge_epistemic_host_bootstrap_b0b.py",
    "tests/test_factorforge_epistemic_host_bootstrap_b0b.py",
)
EXPECTED_B0B_DEPENDENCY_FILES = (
    "factor_factory/epistemic_host_bootstrap.py",
    "factor_factory/epistemic_binding.py",
    "factor_factory/research_org/contracts.py",
    "factor_factory/research_org/rfc8785_canonical.py",
)

EXPECTED_B0B_IMPORTS = {
    "factor_factory/epistemic_host_bootstrap_b0b.py": [
        "__future__",
        "ast",
        "factor_factory.epistemic_binding",
        "factor_factory.epistemic_host_bootstrap",
        "factor_factory.research_org.contracts",
        "factor_factory.research_org.rfc8785_canonical",
        "hashlib",
        "os",
        "pathlib",
        "secrets",
        "stat",
        "typing",
    ],
    "scripts/build_factorforge_epistemic_host_bootstrap_b0b.py": [
        "__future__",
        "argparse",
        "factor_factory.epistemic_host_bootstrap",
        "factor_factory.epistemic_host_bootstrap_b0b",
        "json",
        "pathlib",
        "sys",
    ],
    "tests/test_factorforge_epistemic_host_bootstrap_b0b.py": [
        "__future__",
        "copy",
        "factor_factory.epistemic_host_bootstrap",
        "factor_factory.epistemic_host_bootstrap_b0b",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "pytest",
        "stat",
    ],
}

EXPECTED_B0B_TOP_LEVEL_CALLABLES = {
    "factor_factory/epistemic_host_bootstrap_b0b.py": [
        "EpistemicHostBootstrapB0BError",
        "_require_equal",
        "_with_content_sha",
        "_rule_rows",
        "_extract_rule6_expectations",
        "_validate_b0a_r2_manifest",
        "compile_b0b_plan",
        "compile_b0b_expectation_gap_ledger",
        "compile_b0b_exact261_layout_scaffold",
        "validate_b0b_plan",
        "validate_b0b_expectation_gap_ledger",
        "validate_b0b_exact261_layout_scaffold",
        "require_b0b_execution_authority",
        "_dotted_name",
        "_analyze_b0b_surface",
        "build_b0b_implementation_inventory",
        "validate_b0b_implementation_inventory",
        "build_b0b_validation_report",
        "_stable_file_row",
        "_create_staging_directory",
        "_validate_staging_closure",
        "write_b0b_candidate_bundle",
    ],
    "scripts/build_factorforge_epistemic_host_bootstrap_b0b.py": ["main"],
    "tests/test_factorforge_epistemic_host_bootstrap_b0b.py": [
        "_frozen_contracts",
        "_compile_all",
        "test_gap_ledger_exact170_and_only_rule6_expectations_are_bound",
        "test_exact261_layout_is_closed_and_nonmaterialized",
        "test_tamper_and_execution_attempts_fail_closed",
        "test_local_report_is_predicate_derived_and_non_authorizing",
        "test_b0b_packet_atomic_publish_exact6",
        "test_b0b_implementation_surface_is_closed",
    ],
}

FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "boto3",
    "botocore",
    "cryptography",
    "grpc",
    "http",
    "httpx",
    "keyring",
    "nacl",
    "paramiko",
    "requests",
    "socket",
    "ssl",
    "subprocess",
    "urllib",
}
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "os.fork",
    "os.popen",
    "os.system",
}


class EpistemicHostBootstrapB0BError(RuntimeError):
    def __init__(self, reasons: list[str] | tuple[str, ...] | set[str]) -> None:
        self.reasons = tuple(sorted({str(reason) for reason in reasons if reason}))
        super().__init__(";".join(self.reasons or ("UNSPECIFIED_B0B_FAILURE",)))


def _require_equal(actual: Any, expected: Any, reason: str) -> None:
    if actual != expected:
        raise EpistemicHostBootstrapB0BError([reason])


def _with_content_sha(payload: dict[str, Any], *, domain: str) -> dict[str, Any]:
    result = dict(payload)
    result.pop("content_sha256", None)
    result["content_sha256"] = framed_sha256(domain, result)
    return result


def _rule_rows(contracts: FrozenBootstrapContracts) -> list[dict[str, Any]]:
    requirements = contracts.schema_bundle.get(
        "x-factorforge-semantic-rule-design-requirements"
    )
    if not isinstance(requirements, dict):
        raise EpistemicHostBootstrapB0BError(["semantic_rule_requirements_missing"])
    rows = requirements.get("rules")
    if not isinstance(rows, list) or len(rows) != 34:
        raise EpistemicHostBootstrapB0BError(["semantic_rule_exact34_required"])
    result: list[dict[str, Any]] = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EpistemicHostBootstrapB0BError([f"semantic_rule_row:{ordinal}"])
        _require_equal(row.get("ordinal"), ordinal, f"semantic_rule_ordinal:{ordinal}")
        for field in ("rule_id", "false_reason", "unresolved_reason"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise EpistemicHostBootstrapB0BError(
                    [f"semantic_rule_field:{ordinal}:{field}"]
                )
        result.append(row)
    semantic_result = contracts.schema_bundle.get("$defs", {}).get(
        "semantic_rule_result", {}
    )
    enum = semantic_result.get("properties", {}).get("rule_id", {}).get("enum")
    _require_equal(
        [row["rule_id"] for row in result],
        enum,
        "semantic_rule_enum_order_mismatch",
    )
    return result


def _extract_rule6_expectations(
    contracts: FrozenBootstrapContracts,
) -> list[dict[str, str | int]]:
    definition = contracts.schema_bundle.get("$defs", {}).get(
        "mandatory_conformance_obligation"
    )
    if not isinstance(definition, dict):
        raise EpistemicHostBootstrapB0BError(["mandatory_obligation_def_missing"])
    source_branches = definition.get("oneOf")
    if not isinstance(source_branches, list) or len(source_branches) != 5:
        raise EpistemicHostBootstrapB0BError(["mandatory_source_exact5_oneof"])
    branch = source_branches[0]
    if not isinstance(branch, dict):
        raise EpistemicHostBootstrapB0BError(["rule6_source_branch_missing"])
    source_contract = contracts.schema_bundle[
        "x-factorforge-semantic-mandatory-conformance-obligation-contract"
    ]["source_contract_order"][0]
    outer_properties = branch.get("properties")
    if not isinstance(outer_properties, dict):
        raise EpistemicHostBootstrapB0BError(["rule6_outer_properties_missing"])
    outer_expected = {
        "source_contract_ordinal": source_contract["source_contract_ordinal"],
        "source_contract_id": source_contract["source_contract_id"],
        "source_json_pointer": source_contract["source_json_pointer"],
        "owning_rule_ordinal": source_contract["owning_rule_ordinal"],
        "owning_rule_id": source_contract["owning_rule_id"],
    }
    for field, value in outer_expected.items():
        _require_equal(
            outer_properties.get(field, {}).get("const"),
            value,
            f"rule6_outer_binding:{field}",
        )
    _require_equal(
        outer_properties.get("source_vector_ordinal"),
        {"minimum": 0, "maximum": 9},
        "rule6_outer_ordinal_range",
    )
    inner_branches = branch.get("oneOf")
    if not isinstance(inner_branches, list) or len(inner_branches) != 10:
        raise EpistemicHostBootstrapB0BError(["rule6_exact10_oneof"])
    source_vectors = contracts.schema_bundle[
        "x-factorforge-semantic-rule-design-requirements"
    ]["rules"][6]["conformance_vector_set"]
    if not isinstance(source_vectors, list) or len(source_vectors) != 10:
        raise EpistemicHostBootstrapB0BError(["rule6_exact10_source_vectors"])
    extracted: list[dict[str, str | int]] = []
    for ordinal, inner in enumerate(inner_branches):
        if not isinstance(inner, dict) or set(inner) != {"properties"}:
            raise EpistemicHostBootstrapB0BError([f"rule6_inner_shape:{ordinal}"])
        properties = inner.get("properties")
        if not isinstance(properties, dict) or set(properties) != {
            "source_vector_ordinal",
            "vector_name",
            "expected_verdict",
            "expected_public_reason_code",
        }:
            raise EpistemicHostBootstrapB0BError(
                [f"rule6_inner_properties:{ordinal}"]
            )
        vector_ordinal = properties["source_vector_ordinal"].get("const")
        vector_name = properties["vector_name"].get("const")
        verdict = properties["expected_verdict"].get("const")
        reason = properties["expected_public_reason_code"].get("const")
        _require_equal(vector_ordinal, ordinal, f"rule6_inner_ordinal:{ordinal}")
        _require_equal(vector_name, source_vectors[ordinal], f"rule6_vector:{ordinal}")
        _require_equal(
            (verdict, reason),
            RULE6_EXPECTATIONS[ordinal],
            f"rule6_mirror_expectation:{ordinal}",
        )
        extracted.append(
            {
                "source_vector_ordinal": ordinal,
                "vector_name": vector_name,
                "expected_verdict": verdict,
                "expected_public_reason_code": reason,
            }
        )
    return extracted


def _validate_b0a_r2_manifest(manifest_path: Path) -> dict[str, Any]:
    candidate = Path(manifest_path)
    metadata = candidate.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size != B0A_R2_MANIFEST_BYTES
    ):
        raise EpistemicHostBootstrapB0BError(["b0a_r2_manifest_identity"])
    descriptor = os.open(
        candidate,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        raw = bytearray()
        while len(raw) <= B0A_R2_MANIFEST_BYTES:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, B0A_R2_MANIFEST_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(raw) != B0A_R2_MANIFEST_BYTES
        or hashlib.sha256(raw).hexdigest() != B0A_R2_MANIFEST_SHA256
        or (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise EpistemicHostBootstrapB0BError(["b0a_r2_manifest_hash_or_race"])
    payload = strict_json_loads(bytes(raw), label="b0a_r2_manifest")
    if not isinstance(payload, dict):
        raise EpistemicHostBootstrapB0BError(["b0a_r2_manifest_object"])
    expected = {
        "packet_id": B0A_R2_PACKET_ID,
        "manifest_status": "PARTIAL_B0_CANDIDATE__NOT_REVIEW_ELIGIBLE",
        "review_eligible": False,
        "live_ceremony_authorized": False,
        "operational_predecessor_satisfied_count": 0,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    for key, value in expected.items():
        _require_equal(payload.get(key), value, f"b0a_r2_state:{key}")
    return payload


def compile_b0b_plan(
    contracts: FrozenBootstrapContracts,
    *,
    b0a_r2_manifest_path: Path,
) -> dict[str, Any]:
    frozen = validate_frozen_bootstrap_contracts(contracts)
    _validate_b0a_r2_manifest(b0a_r2_manifest_path)
    mandatory_contract = frozen.schema_bundle[
        "x-factorforge-semantic-mandatory-conformance-obligation-contract"
    ]
    core = {
        "schema_id": B0B_PLAN_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "stage_id": "B0_B1_EXPECTATION_AUTHORITY_AND_EXACT261_SCAFFOLD",
        "status": B0B_STATUS,
        "execution_mode": B0B_EXECUTION_MODE,
        "source_contracts": [
            {
                "ordinal": 0,
                "role": "B0_A_R2_OFFLINE_CANDIDATE_MANIFEST",
                "bytes": B0A_R2_MANIFEST_BYTES,
                "sha256": B0A_R2_MANIFEST_SHA256,
            },
            {
                "ordinal": 1,
                "role": "FROZEN_STAGE1B_CLOSED_SCHEMA_BUNDLE",
                "bytes": EXPECTED_STAGE1B_ARTIFACTS[0][1],
                "sha256": STAGE1B_SCHEMA_BUNDLE_SHA256,
            },
        ],
        "mandatory_obligation_contract_sha256": framed_sha256(
            "FF_SEMANTIC_MANDATORY_CONFORMANCE_OBLIGATION_CONTRACT_V1",
            mandatory_contract,
        ),
        "mandatory_obligation_count": 170,
        "rule6_frozen_expectation_count": 10,
        "dual_git_expectation_unbound_count": 160,
        "exact_case_layout_slot_count": 261,
        "candidate_materialized_case_count": 0,
        "candidate_obligation_executed_count": 0,
        "formal_mandatory_obligation_executed_count": 0,
        "formal_preflight_satisfied": False,
        "is_semantic_validation_receipt": False,
        "may_satisfy_adjudicative_pass": False,
        "may_satisfy_host_or_operating_authority": False,
        "blocking_conditions": list(B0B_BLOCKING_CONDITIONS),
        "permissions": {
            "authoritative_expectation_binding": False,
            "case_materialization": False,
            "semantic_execution": False,
            "formal_preflight": False,
            "semantic_receipt": False,
            "live_host": False,
            "key_generation": False,
            "signature_generation": False,
            "host_cas": False,
            "canonical_memory": False,
            "oos": False,
            "skill_or_rag_runtime": False,
            "deployment": False,
        },
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain="FF_B0B_SCAFFOLD_PLAN_V1")


def compile_b0b_expectation_gap_ledger(
    contracts: FrozenBootstrapContracts,
) -> dict[str, Any]:
    frozen = validate_frozen_bootstrap_contracts(contracts)
    skeleton = compile_b0_obligation_skeleton(frozen)
    rules = _rule_rows(frozen)
    rule6_expectations = _extract_rule6_expectations(frozen)
    rows: list[dict[str, Any]] = []
    for source in range(5):
        _require_equal(
            sum(
                row["source_contract_ordinal"] == source
                for row in skeleton["rows"]
            ),
            MANDATORY_SOURCE_COUNTS[source],
            f"mandatory_source_count:{source}",
        )
    for source_row in skeleton["rows"]:
        source_ordinal = source_row["source_contract_ordinal"]
        vector_ordinal = source_row["source_vector_ordinal"]
        owner = rules[source_row["owning_rule_ordinal"]]
        if source_ordinal == 0:
            rule6_expectation = rule6_expectations[vector_ordinal]
            _require_equal(
                rule6_expectation["vector_name"],
                source_row["vector_name"],
                f"rule6_skeleton_vector:{vector_ordinal}",
            )
            expected_verdict = rule6_expectation["expected_verdict"]
            reason = rule6_expectation["expected_public_reason_code"]
            expectation_state = "FROZEN_BY_STAGE1B_RULE6"
            allowed_pairs = [
                {"expected_verdict": expected_verdict, "public_reason_code": reason}
            ]
        else:
            expected_verdict = None
            reason = None
            expectation_state = "DUAL_GIT_EXPECTATION_UNBOUND"
            allowed_pairs = [
                {
                    "expected_verdict": "FAIL",
                    "public_reason_code": owner["false_reason"],
                },
                {
                    "expected_verdict": "BLOCKED",
                    "public_reason_code": owner["unresolved_reason"],
                },
            ]
        rows.append(
            {
                "global_obligation_ordinal": source_row[
                    "global_obligation_ordinal"
                ],
                "source_contract_ordinal": source_ordinal,
                "source_contract_id": source_row["source_contract_id"],
                "source_json_pointer": source_row["source_json_pointer"],
                "source_vector_ordinal": vector_ordinal,
                "vector_name": source_row["vector_name"],
                "owning_rule_ordinal": source_row["owning_rule_ordinal"],
                "owning_rule_id": source_row["owning_rule_id"],
                "expectation_state": expectation_state,
                "expected_verdict": expected_verdict,
                "expected_public_reason_code": reason,
                "allowed_expectation_pairs": allowed_pairs,
                "input_fixture_bundle_ref": None,
                "resolver_fixture_manifest_ref": None,
                "trusted_time_fixture": None,
                "mutation_pointer_manifest_ref": None,
                "expected_public_output_sha256": None,
                "expected_result_basis_sha256": None,
                "case_materialized": False,
                "execution_status": "NOT_EXECUTED",
            }
        )
    _require_equal(
        [row["global_obligation_ordinal"] for row in rows],
        list(range(170)),
        "mandatory_global_ordinals",
    )
    core = {
        "schema_id": B0B_GAP_LEDGER_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "status": B0B_STATUS,
        "source_schema_bundle_sha256": STAGE1B_SCHEMA_BUNDLE_SHA256,
        "mandatory_obligation_contract_sha256": skeleton[
            "mandatory_contract_sha256"
        ],
        "row_count": 170,
        "frozen_expectation_count": 10,
        "unbound_expectation_count": 160,
        "rows": rows,
        "expectation_authority": {
            "authority_state": "UNBOUND_BLOCKING",
            "dual_git_approved_definition_generation": None,
            "ontology_steward_approval_ref": None,
            "reference_steward_approval_ref": None,
            "os_sealed_activation_ref": None,
            "runtime_caller_may_assign_expectations": False,
        },
        "candidate_materialized_case_count": 0,
        "candidate_obligation_executed_count": 0,
        "formal_mandatory_obligation_executed_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core,
        domain="FF_B0B_EXPECTATION_GAP_LEDGER_V1",
    )


def compile_b0b_exact261_layout_scaffold(
    contracts: FrozenBootstrapContracts,
    *,
    gap_ledger: dict[str, Any],
) -> dict[str, Any]:
    frozen = validate_frozen_bootstrap_contracts(contracts)
    validate_b0b_expectation_gap_ledger(gap_ledger, contracts=frozen)
    rules = _rule_rows(frozen)
    slots: list[dict[str, Any]] = []
    for row in gap_ledger["rows"]:
        slots.append(
            {
                "case_ordinal": row["global_obligation_ordinal"],
                "case_class": "MANDATORY",
                "rule_ordinal": row["owning_rule_ordinal"],
                "rule_id": row["owning_rule_id"],
                "global_obligation_ordinal": row["global_obligation_ordinal"],
                "required_verdict_class": (
                    row["expected_verdict"]
                    if row["expected_verdict"] is not None
                    else "UNBOUND_FAIL_OR_BLOCKED"
                ),
                "case_id": None,
                "case_content_sha256": None,
                "materialized": False,
                "execution_status": "NOT_EXECUTED",
            }
        )
    for rule_ordinal in EXTRA_PASS_RULE_ORDINALS:
        slots.append(
            {
                "case_ordinal": len(slots),
                "case_class": "NON_MANDATORY_EXTRA_PASS",
                "rule_ordinal": rule_ordinal,
                "rule_id": rules[rule_ordinal]["rule_id"],
                "global_obligation_ordinal": None,
                "required_verdict_class": "PASS",
                "case_id": None,
                "case_content_sha256": None,
                "materialized": False,
                "execution_status": "NOT_EXECUTED",
            }
        )
    other_rule_ordinals = [
        ordinal
        for ordinal in range(34)
        if ordinal not in MANDATORY_OWNER_RULE_ORDINALS
    ]
    _require_equal(len(other_rule_ordinals), 29, "nonmandatory_rule_count")
    for rule_ordinal in other_rule_ordinals:
        for verdict in ("PASS", "FAIL", "BLOCKED"):
            slots.append(
                {
                    "case_ordinal": len(slots),
                    "case_class": "NON_MANDATORY_RULE_TRIPLET",
                    "rule_ordinal": rule_ordinal,
                    "rule_id": rules[rule_ordinal]["rule_id"],
                    "global_obligation_ordinal": None,
                    "required_verdict_class": verdict,
                    "case_id": None,
                    "case_content_sha256": None,
                    "materialized": False,
                    "execution_status": "NOT_EXECUTED",
                }
            )
    _require_equal(len(slots), 261, "exact261_slot_count")
    _require_equal(
        [row["case_ordinal"] for row in slots],
        list(range(261)),
        "exact261_case_ordinals",
    )
    core = {
        "schema_id": B0B_LAYOUT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "status": B0B_STATUS,
        "layout_authority": "CANDIDATE_PROPOSAL_REQUIRES_DUAL_GIT_APPROVAL",
        "slot_count": 261,
        "mandatory_slot_count": 170,
        "mandatory_owner_extra_pass_slot_count": 4,
        "other_rule_triplet_slot_count": 87,
        "minimum_pass_slot_count": 34,
        "unbound_mandatory_fail_or_blocked_slot_count": 160,
        "slots": slots,
        "materialized_case_count": 0,
        "executed_case_count": 0,
        "formal_preflight_satisfied": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core,
        domain="FF_B0B_EXACT261_LAYOUT_SCAFFOLD_V1",
    )


def validate_b0b_plan(
    payload: dict[str, Any],
    *,
    contracts: FrozenBootstrapContracts,
    b0a_r2_manifest_path: Path,
) -> None:
    expected = compile_b0b_plan(
        contracts,
        b0a_r2_manifest_path=b0a_r2_manifest_path,
    )
    _require_equal(payload, expected, "b0b_plan_closed_equality")


def validate_b0b_expectation_gap_ledger(
    payload: dict[str, Any],
    *,
    contracts: FrozenBootstrapContracts,
) -> None:
    expected = compile_b0b_expectation_gap_ledger(contracts)
    _require_equal(payload, expected, "b0b_gap_ledger_closed_equality")


def validate_b0b_exact261_layout_scaffold(
    payload: dict[str, Any],
    *,
    contracts: FrozenBootstrapContracts,
    gap_ledger: dict[str, Any],
) -> None:
    expected = compile_b0b_exact261_layout_scaffold(
        contracts,
        gap_ledger=gap_ledger,
    )
    _require_equal(payload, expected, "b0b_layout_closed_equality")


def require_b0b_execution_authority(
    *,
    gap_ledger: dict[str, Any],
    layout: dict[str, Any],
) -> None:
    del gap_ledger, layout
    raise EpistemicHostBootstrapB0BError(
        ["B0B_EXPECTATION_FIXTURE_EXECUTION_AUTHORITY_UNBOUND"]
    )


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _analyze_b0b_surface(relative: str, raw: bytes) -> dict[str, Any]:
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=relative)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise EpistemicHostBootstrapB0BError(
            [f"b0b_ast_parse:{relative}:{type(exc).__name__}"]
        ) from exc
    imports: set[str] = set()
    forbidden: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted in FORBIDDEN_CALLS or (
                dotted is not None
                and dotted.startswith(("os.exec", "os.spawn", "os.posix_spawn"))
            ):
                forbidden.add(f"call:{dotted}")
    for module in imports:
        if module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
            forbidden.add(f"import:{module}")
    observed_imports = sorted(imports)
    _require_equal(
        observed_imports,
        EXPECTED_B0B_IMPORTS.get(relative),
        f"b0b_import_allowlist:{relative}",
    )
    top_level = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    _require_equal(
        top_level,
        EXPECTED_B0B_TOP_LEVEL_CALLABLES.get(relative),
        f"b0b_callable_allowlist:{relative}",
    )
    _require_equal(sorted(forbidden), [], f"b0b_forbidden_surface:{relative}")
    return {
        "ast_parse": "PASS",
        "exact_import_allowlist": "PASS",
        "exact_top_level_callable_allowlist": "PASS",
        "forbidden_network_crypto_dynamic_execution_hits": [],
        "observed_import_modules": observed_imports,
        "observed_top_level_callables": top_level,
        "surface_verdict": "PASS",
    }


def build_b0b_implementation_inventory(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for ordinal, relative in enumerate(EXPECTED_B0B_IMPLEMENTATION_FILES):
        path = root / relative
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 4 * 1024 * 1024
        ):
            raise EpistemicHostBootstrapB0BError(
                [f"unsafe_b0b_implementation_file:{relative}"]
            )
        raw = path.read_bytes()
        after = path.lstat()
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise EpistemicHostBootstrapB0BError(
                [f"changed_b0b_implementation_file:{relative}"]
            )
        rows.append(
            {
                "ordinal": ordinal,
                "logical_path": relative,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "surface_analysis": _analyze_b0b_surface(relative, raw),
            }
        )
    dependency_rows: list[dict[str, Any]] = []
    for ordinal, relative in enumerate(EXPECTED_B0B_DEPENDENCY_FILES):
        path = root / relative
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 8 * 1024 * 1024
        ):
            raise EpistemicHostBootstrapB0BError(
                [f"unsafe_b0b_dependency_file:{relative}"]
            )
        raw = path.read_bytes()
        after = path.lstat()
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise EpistemicHostBootstrapB0BError(
                [f"changed_b0b_dependency_file:{relative}"]
            )
        dependency_rows.append(
            {
                "ordinal": ordinal,
                "logical_path": relative,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    core = {
        "schema_id": B0B_IMPLEMENTATION_INVENTORY_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "implementation_scope": "B0_B1_OFFLINE_SCAFFOLD_ONLY",
        "file_count": len(rows),
        "ordered_files": rows,
        "dependency_file_count": len(dependency_rows),
        "ordered_dependencies": dependency_rows,
        "network_adapter_present": False,
        "live_host_adapter_present": False,
        "semantic_engine_present": False,
        "fixture_materializer_present": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core,
        domain="FF_B0B_IMPLEMENTATION_INVENTORY_V1",
    )


def validate_b0b_implementation_inventory(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> None:
    expected = build_b0b_implementation_inventory(repo_root)
    _require_equal(payload, expected, "b0b_implementation_inventory_closed_equality")


def build_b0b_validation_report(
    *,
    contracts: FrozenBootstrapContracts,
    b0a_r2_manifest_path: Path,
    plan: dict[str, Any],
    gap_ledger: dict[str, Any],
    layout: dict[str, Any],
    implementation_inventory: dict[str, Any],
) -> dict[str, Any]:
    frozen = validate_frozen_bootstrap_contracts(contracts)
    validate_b0b_plan(
        plan,
        contracts=frozen,
        b0a_r2_manifest_path=b0a_r2_manifest_path,
    )
    validate_b0b_expectation_gap_ledger(gap_ledger, contracts=frozen)
    validate_b0b_exact261_layout_scaffold(
        layout,
        contracts=frozen,
        gap_ledger=gap_ledger,
    )
    validate_b0b_implementation_inventory(
        implementation_inventory,
        repo_root=frozen.repo_root,
    )
    predicates = [
        (
            "FROZEN_B0A_R2_AND_STAGE1B_LINEAGE",
            "stable re-read of exact B0-A R2 and frozen Stage1B lineage",
        ),
        (
            "EXACT34_RULE_UNIVERSE",
            "rule rows and semantic_rule_result enum closed equality",
        ),
        (
            "EXACT170_SOURCE_BIJECTION",
            "source counts 10/36/50/43/31 and global ordinals 0..169",
        ),
        (
            "RULE6_EXACT10_EXPECTATIONS",
            "frozen oneOf PASS/FAIL/BLOCKED mapping closed equality",
        ),
        (
            "OTHER160_EXPECTATIONS_REMAIN_UNBOUND",
            "closed ledger null expectations with exact allowed reason pairs",
        ),
        (
            "EXACT261_LAYOUT",
            "170 mandatory plus 4 extra PASS plus 29 ordered triplets",
        ),
        (
            "ZERO_CASE_MATERIALIZATION_AND_EXECUTION",
            "all slots unmaterialized/not executed and formal counts zero",
        ),
        (
            "OFFLINE_IMPLEMENTATION_SURFACE",
            "exact file hashes plus AST import/callable/forbidden-call predicates",
        ),
    ]
    core = {
        "schema_id": B0B_REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "status": B0B_STATUS,
        "local_structural_verdict": "LOCAL_CANDIDATE_SCAFFOLD_PASS",
        "blocking_verdict": "BLOCKED_EXPECTATION_AUTHORITY_UNBOUND",
        "plan_content_sha256": plan["content_sha256"],
        "expectation_gap_ledger_content_sha256": gap_ledger["content_sha256"],
        "exact261_layout_content_sha256": layout["content_sha256"],
        "implementation_inventory_content_sha256": implementation_inventory[
            "content_sha256"
        ],
        "structural_checks": [
            {
                "ordinal": ordinal,
                "predicate_id": predicate_id,
                "evidence_basis": evidence_basis,
                "verdict": "PASS",
            }
            for ordinal, (predicate_id, evidence_basis) in enumerate(predicates)
        ],
        "structural_check_count": len(predicates),
        "blocking_conditions": [
            {
                "ordinal": ordinal,
                "condition_id": condition,
                "state": "UNBOUND_BLOCKING",
            }
            for ordinal, condition in enumerate(B0B_BLOCKING_CONDITIONS)
        ],
        "candidate_layout_slot_count": 261,
        "candidate_materialized_case_count": 0,
        "candidate_obligation_executed_count": 0,
        "formal_mandatory_obligation_executed_count": 0,
        "formal_preflight_satisfied": False,
        "is_semantic_validation_receipt": False,
        "may_satisfy_adjudicative_pass": False,
        "may_satisfy_host_or_operating_authority": False,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core,
        domain="FF_B0B_LOCAL_NONAUTHORITATIVE_SCAFFOLD_REPORT_V1",
    )


def _stable_file_row(path: Path, *, ordinal: int, role: str) -> dict[str, Any]:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise EpistemicHostBootstrapB0BError([f"unsafe_staged_file:{path.name}"])
    raw = path.read_bytes()
    after = path.lstat()
    if (
        len(raw) != before.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise EpistemicHostBootstrapB0BError([f"staged_file_changed:{path.name}"])
    return {
        "ordinal": ordinal,
        "role": role,
        "path": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _create_staging_directory(parent_descriptor: int) -> str:
    for _ in range(16):
        name = f".factorforge-b0b-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
            return name
        except FileExistsError:
            continue
    raise EpistemicHostBootstrapB0BError(["b0b_staging_name_exhausted"])


def _validate_staging_closure(
    staging_descriptor: int,
    *,
    expected_names: set[str],
) -> None:
    try:
        names = set(os.listdir(staging_descriptor))
    except OSError as exc:
        raise EpistemicHostBootstrapB0BError(["b0b_staging_list_failed"]) from exc
    _require_equal(names, expected_names, "b0b_staging_closure")
    for name in names:
        metadata = os.stat(name, dir_fd=staging_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise EpistemicHostBootstrapB0BError([f"b0b_staged_entry:{name}"])


def write_b0b_candidate_bundle(
    output_root: Path,
    *,
    plan: dict[str, Any],
    gap_ledger: dict[str, Any],
    layout: dict[str, Any],
    report: dict[str, Any],
    implementation_inventory: dict[str, Any],
) -> dict[str, Any]:
    root = Path(output_root)
    if not root.is_absolute() or root.name in {"", ".", ".."} or ".." in root.parts:
        raise EpistemicHostBootstrapB0BError(["b0b_output_root_invalid"])
    parent = root.parent.resolve(strict=True)
    parent_descriptor = _open_absolute_directory_fd(parent)
    staging_descriptor: int | None = None
    try:
        if _entry_exists_at(parent_descriptor, root.name):
            raise EpistemicHostBootstrapB0BError(["b0b_output_root_exists"])
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
        pinned_staging = os.fstat(staging_descriptor)
        if (
            not stat.S_ISDIR(pinned_staging.st_mode)
            or stat.S_IMODE(pinned_staging.st_mode) & 0o077
        ):
            raise EpistemicHostBootstrapB0BError(["b0b_staging_not_private"])
        artifacts = (
            ("00_b0b_plan.json", "B0B_PLAN", plan),
            ("01_b0b_expectation_gap_ledger.json", "B0B_EXPECTATION_GAP_LEDGER", gap_ledger),
            ("02_b0b_exact261_layout_scaffold.json", "B0B_EXACT261_LAYOUT", layout),
            ("03_b0b_validation_report.json", "B0B_VALIDATION_REPORT", report),
            (
                "04_b0b_implementation_inventory.json",
                "B0B_IMPLEMENTATION_INVENTORY",
                implementation_inventory,
            ),
        )
        for name, _, payload in artifacts:
            write_workspace_json_once(staging_root, name, payload)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role, _) in enumerate(artifacts)
        ]
        artifact_commitment = hashlib.sha256(
            b"FF_B0B_SCAFFOLD_ARTIFACT_MANIFEST_V1\x00"
            + b"".join(bytes.fromhex(row["sha256"]) for row in rows)
        ).hexdigest()
        manifest_core = {
            "schema_id": B0B_PACKET_SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "packet_id": "FF_EPISTEMIC_HOST_BOOTSTRAP_B0_B1_SCAFFOLD_20260828_R2",
            "manifest_status": B0B_STATUS,
            "artifact_count": 5,
            "ordered_artifacts": rows,
            "source_contracts": plan["source_contracts"],
            "candidate_integrity_profile": {
                "profile_id": B0B_LOCAL_INTEGRITY_PROFILE_ID,
                "scope": "MANIFEST_AND_EXACT5_ARTIFACTS",
                "authority_effect": AUTHORITY_EFFECT,
                "may_satisfy_host_or_operating_authority": False,
                "content_digest_formula": (
                    "SHA256(UTF8(domain)||0x00||"
                    "RFC8785_INTEGER_ONLY(payload_without_content_sha256))"
                ),
                "content_digest_domains_by_role": {
                    "B0B_PLAN": "FF_B0B_SCAFFOLD_PLAN_V1",
                    "B0B_EXPECTATION_GAP_LEDGER": (
                        "FF_B0B_EXPECTATION_GAP_LEDGER_V1"
                    ),
                    "B0B_EXACT261_LAYOUT": (
                        "FF_B0B_EXACT261_LAYOUT_SCAFFOLD_V1"
                    ),
                    "B0B_VALIDATION_REPORT": (
                        "FF_B0B_LOCAL_NONAUTHORITATIVE_SCAFFOLD_REPORT_V1"
                    ),
                    "B0B_IMPLEMENTATION_INVENTORY": (
                        "FF_B0B_IMPLEMENTATION_INVENTORY_V1"
                    ),
                    "PACKET_MANIFEST": "FF_B0B_SCAFFOLD_PACKET_MANIFEST_V1",
                },
                "artifact_commitment_domain": (
                    "FF_B0B_SCAFFOLD_ARTIFACT_MANIFEST_V1"
                ),
                "artifact_commitment_formula": (
                    "SHA256(UTF8(domain)||0x00||"
                    "CONCAT(ordered_artifact_raw_sha256_binary_32_bytes))"
                ),
            },
            "artifact_manifest_commitment_sha256": artifact_commitment,
            "candidate_layout_slot_count": 261,
            "candidate_materialized_case_count": 0,
            "candidate_obligation_executed_count": 0,
            "formal_mandatory_obligation_executed_count": 0,
            "formal_preflight_satisfied": False,
            "review_eligible": False,
            "live_ceremony_authorized": False,
            "is_semantic_validation_receipt": False,
            "may_satisfy_adjudicative_pass": False,
            "permissions_opened_count": 0,
            "authority_effect": AUTHORITY_EFFECT,
        }
        manifest = _with_content_sha(
            manifest_core,
            domain="FF_B0B_SCAFFOLD_PACKET_MANIFEST_V1",
        )
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        expected_names = {"packet_manifest.json", *(name for name, _, _ in artifacts)}
        _validate_staging_closure(
            staging_descriptor,
            expected_names=expected_names,
        )
        current = os.stat(
            staging_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _require_equal(
            (current.st_dev, current.st_ino),
            (pinned_staging.st_dev, pinned_staging.st_ino),
            "b0b_staging_identity_changed",
        )
        if _entry_exists_at(parent_descriptor, root.name):
            raise EpistemicHostBootstrapB0BError(["b0b_output_root_race"])
        os.fsync(staging_descriptor)
        _atomic_publish_directory_noreplace_at(
            parent_descriptor,
            staging_name,
            root.name,
        )
        os.fsync(parent_descriptor)
        return manifest
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        os.close(parent_descriptor)
