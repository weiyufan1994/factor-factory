from __future__ import annotations

import ast
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import (
    strict_json_loads,
    write_workspace_json_once,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


B0_PLAN_SCHEMA_ID = "factorforge_epistemic_host_bootstrap_b0_plan_v1"
B0_SKELETON_SCHEMA_ID = (
    "factorforge_epistemic_host_bootstrap_b0_obligation_skeleton_v1"
)
B0_REPORT_SCHEMA_ID = "factorforge_epistemic_host_bootstrap_b0_report_v1"
B0_IMPLEMENTATION_INVENTORY_SCHEMA_ID = (
    "factorforge_epistemic_host_bootstrap_b0_implementation_inventory_v1"
)
B0_PACKET_SCHEMA_ID = "factorforge_epistemic_host_bootstrap_b0_packet_manifest_v1"
SCHEMA_VERSION = "1.0.0"

PARTIAL_STATUS = "PARTIAL_B0_CANDIDATE__NOT_REVIEW_ELIGIBLE"
EXECUTION_MODE = "SYNTHETIC_OFFLINE_ONLY"
AUTHORITY_EFFECT = "NONE"

STAGE1B_MANIFEST_RELATIVE = (
    "docs/contracts/"
    "factorforge-epistemic-host-readback-stage1b0-packet-manifest-v1.json"
)
STAGE1B_MANIFEST_SHA256 = (
    "24b107f16b95cba65ee59ce9f51baad4debef4763c9b67214c315f8cc2df9089"
)
STAGE1B_MANIFEST_BYTES = 7976

R2_MANIFEST_SHA256 = (
    "f5eba271b673631f99b5308561915578a58839b8f38dcbf5f2407d0f514d998f"
)
R2_MANIFEST_BYTES = 15235
O0_MANIFEST_SHA256 = (
    "97e17598bd216add44d7cdf64551356f2ac0d0060696ef5757882aca15392309"
)
O0_MANIFEST_BYTES = 9953
O0_PRIME_MANIFEST_SHA256 = (
    "55c44b4ff4740603f972674b286edd71223edeaac2bfae8650cc27e1454a1aa0"
)
O0_PRIME_MANIFEST_BYTES = 10190

EXPECTED_STAGE1B_ARTIFACTS = (
    (
        "docs/contracts/factorforge-epistemic-host-readback-closed-schema-bundle-v1.json",
        3768126,
        "43d33b4499a82e69183cc5f0f8f3df116fb97545c892f44f098b9b81cac8e316",
    ),
    (
        "docs/contracts/factorforge-epistemic-host-readback-meta-registry-v1.json",
        38456,
        "124ca2b64a3100580e4025f1810fa52eaa89a977621c5ddbeb28e73336bc5a80",
    ),
    (
        "docs/contracts/factorforge-epistemic-host-readback-meta-contract-v1.zh-CN.md",
        49600,
        "763fb1665cb99d4fac218b14ccf9e8371bcd234b3aa31fecde5706438a8d20ba",
    ),
    (
        "docs/contracts/factorforge-epistemic-host-readback-stage1b0-review-checklist-v1.zh-CN.md",
        17195,
        "7b76eae7f6e8493eff41a1debdc59c537cb7313aa91a35f980c5f415a1973748",
    ),
)

EXPECTED_TRUST_DOMAIN_ROLE_MAPPING = {
    "HOST_READBACK_CONTROL_TRUST_DOMAIN": [
        "deployment_readback_session_grant",
        "deployment_readback_target_content_provenance",
        "deployment_readback_attestation",
    ],
    "INDEPENDENT_BINDING_VERIFIER_TRUST_DOMAIN": [
        "deployment_verification_target_content_provenance",
        "deployment_binding_independent_verifier",
    ],
    "EXTERNAL_DEPLOYMENT_AUTHORIZATION_TRUST_DOMAIN": [
        "external_phase_authorization"
    ],
    "EXTERNAL_ISOLATION_ATTESTATION_TRUST_DOMAIN": [
        "external_isolation_attestation"
    ],
}

EXPECTED_KEY_BINDING_FIELDS = [
    "key_role",
    "key_id",
    "algorithm",
    "principal_opaque_hash",
    "context_opaque_hash",
    "capability_opaque_hash",
    "public_key_der_sha256",
]

EXPECTED_CONTROL_ROLE_IDS = [
    "FF_DEPLOYMENT_READBACK_SESSION_ISSUER_V1",
    "FF_DEPLOYMENT_READBACK_TARGET_COLLECTOR_V1",
    "FF_DEPLOYMENT_READBACK_ATTESTATION_ISSUER_V1",
    "FF_DEPLOYMENT_VERIFICATION_TARGET_AUTHOR_V1",
    "FF_DEPLOYMENT_BINDING_INDEPENDENT_VERIFIER_V1",
]

EXPECTED_PERMISSION_KEYS = [
    "live_host_discovery",
    "live_host_readback",
    "live_key_generation",
    "live_signature_generation",
    "host_cas",
    "operational_evidence",
    "canonical_memory",
    "oos",
    "skill",
    "rag_runtime",
    "runtime",
    "deployment",
]

EXPECTED_ACTUAL_KEYS = [
    "recipient_binding",
    "trust_manifests",
    "key_bindings",
    "nonrevocation_heads",
    "phase_authorization_receipts",
    "challenge",
    "readback_target",
    "host_attestation_receipt",
    "verification_target",
    "verification_receipt",
    "effective_snapshot",
]

EXPECTED_IMPLEMENTATION_FILES = [
    "factor_factory/research_org/rfc8785_canonical.py",
    "factor_factory/epistemic_host_bootstrap.py",
    "factor_factory/research_org/contracts.py",
    "scripts/build_factorforge_epistemic_host_bootstrap_b0.py",
    "tests/test_factorforge_rfc8785_canonicalization.py",
    "tests/test_factorforge_epistemic_host_bootstrap.py",
]

EXPECTED_IMPLEMENTATION_IMPORTS = {
    "factor_factory/research_org/rfc8785_canonical.py": [
        "__future__",
        "collections.abc",
        "hashlib",
        "typing",
    ],
    "factor_factory/epistemic_host_bootstrap.py": [
        "__future__",
        "ast",
        "dataclasses",
        "factor_factory.research_org.contracts",
        "factor_factory.research_org.rfc8785_canonical",
        "hashlib",
        "os",
        "pathlib",
        "re",
        "stat",
        "typing",
    ],
    "factor_factory/research_org/contracts.py": [
        "__future__",
        "collections.abc",
        "contextlib",
        "factor_factory.research_workspace",
        "fcntl",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "typing",
        "uuid",
    ],
    "scripts/build_factorforge_epistemic_host_bootstrap_b0.py": [
        "__future__",
        "argparse",
        "factor_factory.epistemic_host_bootstrap",
        "json",
        "pathlib",
        "sys",
    ],
    "tests/test_factorforge_rfc8785_canonicalization.py": [
        "__future__",
        "factor_factory.research_org.rfc8785_canonical",
        "hashlib",
        "pytest",
    ],
    "tests/test_factorforge_epistemic_host_bootstrap.py": [
        "__future__",
        "copy",
        "factor_factory.epistemic_host_bootstrap",
        "hashlib",
        "json",
        "pathlib",
        "pytest",
    ],
}

EXPECTED_TOP_LEVEL_CALLABLES = {
    "factor_factory/research_org/rfc8785_canonical.py": [
        "RFC8785CanonicalizationError",
        "_string",
        "_utf16_sort_key",
        "_serialize",
        "canonicalize",
        "framed_sha256",
    ],
    "factor_factory/epistemic_host_bootstrap.py": [
        "EpistemicHostBootstrapError",
        "FrozenBootstrapContracts",
        "_sha256",
        "_read_exact_file",
        "_json_object",
        "_require_equal",
        "_dependency",
        "_validate_stage1b",
        "_validate_o0_prime_directory",
        "load_frozen_bootstrap_contracts",
        "validate_frozen_bootstrap_contracts",
        "_pointer",
        "_mandatory_skeleton",
        "_with_content_sha",
        "compile_b0_bootstrap_plan",
        "compile_b0_obligation_skeleton",
        "assert_sanitized_candidate",
        "validate_b0_bootstrap_plan",
        "validate_b0_obligation_skeleton",
        "_dotted_name",
        "_analyze_implementation_surface",
        "build_b0_implementation_inventory",
        "validate_b0_implementation_inventory",
        "build_b0_validation_report",
        "_file_row",
        "write_b0_candidate_bundle",
    ],
    "factor_factory/research_org/contracts.py": [
        "ResearchOrganizationError",
        "stable_json_hash",
        "content_hash",
        "with_content_hash",
        "validate_content_hash",
        "validate_identity_value",
        "normalize_workspace_relative_path",
        "_validated_relative_parts",
        "_open_absolute_directory_fd",
        "_open_workspace_parent_fd",
        "_read_stable_file_at",
        "read_workspace_bytes",
        "_reject_duplicate_pairs",
        "_reject_non_finite_json",
        "_validate_json_shape",
        "strict_json_loads",
        "read_workspace_json",
        "_json_bytes",
        "_write_workspace_bytes",
        "write_workspace_json",
        "write_workspace_json_once",
        "workspace_file_lock",
        "sha256_file",
        "private_reasoning_paths",
    ],
    "scripts/build_factorforge_epistemic_host_bootstrap_b0.py": ["main"],
    "tests/test_factorforge_rfc8785_canonicalization.py": [
        "test_integer_only_jcs_canonicalizes_utf16_order_and_escapes",
        "test_jcs_safe_integer_and_domain_framing_are_deterministic",
        "test_jcs_profile_rejects_values_that_could_canonicalize_ambiguously",
        "test_domain_must_be_nonempty_and_nul_free",
    ],
    "tests/test_factorforge_epistemic_host_bootstrap.py": [
        "_read_json",
        "_frozen_lineage_paths",
        "_unit_contracts",
        "_loaded_contracts",
        "test_compile_plan_is_closed_synthetic_only_and_non_authorizing",
        "test_compiler_reconstructs_exact_170_vector_skeleton_without_expectations",
        "test_plan_and_skeleton_tamper_fail_closed",
        "test_source_vector_removal_or_duplicate_blocks_compilation",
        "test_validation_report_derives_every_pass_and_blocks_tamper",
        "test_bundle_is_create_only_exact5_and_contains_no_private_material",
        "test_manifest_bound_lineage_loader_passes_current_frozen_packets",
    ],
}

FORBIDDEN_IMPLEMENTATION_IMPORT_ROOTS = {
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
FORBIDDEN_IMPLEMENTATION_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "os.fork",
    "os.popen",
    "os.system",
}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_VECTOR_RE = re.compile(r"[A-Z][A-Z0-9_]{0,255}\Z")
PRIVATE_URI_RE = re.compile(
    r"^(?:file|https?|ftp|s3|gs|ssh|scp|nfs|smb|postgres(?:ql)?|mysql|mongodb):",
    re.IGNORECASE,
)
JSON_POINTER_RE = re.compile(r"/(?:[^/~]|~[01])+(?:/(?:[^/~]|~[01])+)*\Z")
FORBIDDEN_OUTPUT_KEYS = {
    "private_key",
    "private_key_bytes",
    "private_path",
    "secret",
    "secret_value",
    "credential",
    "credentials",
    "access_token",
    "refresh_token",
    "api_key",
    "canonical_payload",
    "canonical_memory_payload",
    "oos_locator",
    "oos_path",
    "public_key",
    "public_key_bytes",
}


class EpistemicHostBootstrapError(RuntimeError):
    def __init__(self, reasons: list[str] | tuple[str, ...] | set[str]) -> None:
        self.reasons = tuple(sorted({str(reason) for reason in reasons if reason}))
        super().__init__(";".join(self.reasons or ("UNSPECIFIED_B0_FAILURE",)))


@dataclass(frozen=True)
class FrozenBootstrapContracts:
    repo_root: Path
    stage1b_manifest: dict[str, Any]
    meta_registry: dict[str, Any]
    schema_bundle: dict[str, Any]
    r2_manifest: dict[str, Any]
    o0_manifest: dict[str, Any]
    o0_prime_manifest: dict[str, Any]
    o0_prime_verdict: dict[str, Any]
    r2_manifest_path: Path | None = None
    o0_manifest_path: Path | None = None
    o0_prime_manifest_path: Path | None = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_exact_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    candidate = Path(path)
    before = candidate.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_size != expected_bytes
    ):
        raise EpistemicHostBootstrapError([f"unsafe_or_wrong_file:{candidate.name}"])
    descriptor = os.open(
        candidate,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        raw = bytearray()
        while len(raw) <= expected_bytes:
            chunk = os.read(descriptor, min(1024 * 1024, expected_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(raw) != expected_bytes
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or _sha256(bytes(raw)) != expected_sha256
    ):
        raise EpistemicHostBootstrapError([f"identity_mismatch:{candidate.name}"])
    return bytes(raw)


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    payload = strict_json_loads(raw, label=label)
    if not isinstance(payload, dict):
        raise EpistemicHostBootstrapError([f"json_object_required:{label}"])
    return payload


def _require_equal(actual: Any, expected: Any, reason: str) -> None:
    if actual != expected:
        raise EpistemicHostBootstrapError([reason])


def _dependency(manifest: dict[str, Any], ordinal: int) -> dict[str, Any]:
    rows = manifest.get("ordered_dependencies")
    if not isinstance(rows, list) or ordinal >= len(rows):
        raise EpistemicHostBootstrapError([f"dependency_missing:{ordinal}"])
    row = rows[ordinal]
    if not isinstance(row, dict) or row.get("ordinal") != ordinal:
        raise EpistemicHostBootstrapError([f"dependency_invalid:{ordinal}"])
    return row


def _validate_stage1b(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_raw = _read_exact_file(
        repo_root / STAGE1B_MANIFEST_RELATIVE,
        expected_bytes=STAGE1B_MANIFEST_BYTES,
        expected_sha256=STAGE1B_MANIFEST_SHA256,
    )
    manifest = _json_object(manifest_raw, label="stage1b_manifest")
    _require_equal(manifest.get("artifact_count"), 4, "stage1b_artifact_count")
    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 4:
        raise EpistemicHostBootstrapError(["stage1b_artifact_rows"])
    loaded: dict[str, bytes] = {}
    for ordinal, (relative, byte_count, digest) in enumerate(EXPECTED_STAGE1B_ARTIFACTS):
        row = rows[ordinal]
        expected_row = {
            "ordinal": ordinal,
            "path": relative,
            "bytes": byte_count,
            "sha256": digest,
        }
        _require_equal(row, expected_row, f"stage1b_artifact_row:{ordinal}")
        loaded[relative] = _read_exact_file(
            repo_root / relative,
            expected_bytes=byte_count,
            expected_sha256=digest,
        )
    schema_path = EXPECTED_STAGE1B_ARTIFACTS[0][0]
    meta_path = EXPECTED_STAGE1B_ARTIFACTS[1][0]
    schema = _json_object(loaded[schema_path], label="stage1b_schema_bundle")
    meta = _json_object(loaded[meta_path], label="stage1b_meta_registry")
    return manifest, meta, schema


def _validate_o0_prime_directory(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("ordered_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise EpistemicHostBootstrapError(["o0_prime_artifacts"])
    expected_names = {"packet_manifest.json"}
    loaded: dict[str, bytes] = {}
    for ordinal, row in enumerate(artifacts):
        if not isinstance(row, dict) or row.get("ordinal") != ordinal:
            raise EpistemicHostBootstrapError([f"o0_prime_artifact_row:{ordinal}"])
        relative = row.get("path")
        if not isinstance(relative, str) or "/" in relative or relative in {"", ".", ".."}:
            raise EpistemicHostBootstrapError([f"o0_prime_artifact_path:{ordinal}"])
        expected_names.add(relative)
        loaded[relative] = _read_exact_file(
            manifest_path.parent / relative,
            expected_bytes=int(row.get("bytes", -1)),
            expected_sha256=str(row.get("sha256", "")),
        )
    actual_names = {entry.name for entry in manifest_path.parent.iterdir()}
    _require_equal(actual_names, expected_names, "o0_prime_directory_closure")
    verdict_row = artifacts[0]
    verdict = _json_object(loaded[str(verdict_row["path"])], label="o0_prime_verdict")
    expected = {
        "review_verdict": "DESIGN_ONLY_GO",
        "p0_count": 0,
        "p1_count": 0,
        "reviewed_o0_manifest_sha256": O0_MANIFEST_SHA256,
        "reviewed_o0_manifest_bytes": O0_MANIFEST_BYTES,
        "signed": False,
        "may_satisfy_o0_design_review_lineage": True,
        "may_satisfy_operating_or_host_authority": False,
        "may_close_o_or_satisfy_any_operational_row": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    for key, value in expected.items():
        _require_equal(verdict.get(key), value, f"o0_prime_verdict:{key}")
    return verdict


def load_frozen_bootstrap_contracts(
    *,
    stage1b_repo_root: Path,
    r2_manifest_path: Path,
    o0_manifest_path: Path,
    o0_prime_manifest_path: Path,
) -> FrozenBootstrapContracts:
    repo_root = Path(stage1b_repo_root).resolve(strict=True)
    r2_path = Path(r2_manifest_path).resolve(strict=True)
    o0_path = Path(o0_manifest_path).resolve(strict=True)
    o0_prime_path = Path(o0_prime_manifest_path).resolve(strict=True)
    stage1b, meta, schema = _validate_stage1b(repo_root)
    r2 = _json_object(
        _read_exact_file(
            r2_path,
            expected_bytes=R2_MANIFEST_BYTES,
            expected_sha256=R2_MANIFEST_SHA256,
        ),
        label="r2_manifest",
    )
    o0 = _json_object(
        _read_exact_file(
            o0_path,
            expected_bytes=O0_MANIFEST_BYTES,
            expected_sha256=O0_MANIFEST_SHA256,
        ),
        label="o0_manifest",
    )
    o0_prime = _json_object(
        _read_exact_file(
            o0_prime_path,
            expected_bytes=O0_PRIME_MANIFEST_BYTES,
            expected_sha256=O0_PRIME_MANIFEST_SHA256,
        ),
        label="o0_prime_manifest",
    )
    o0_dep = _dependency(o0, 0)
    _require_equal(o0_dep.get("sha256"), R2_MANIFEST_SHA256, "o0_to_r2_sha")
    _require_equal(o0_dep.get("bytes"), R2_MANIFEST_BYTES, "o0_to_r2_bytes")
    o0_prime_dep = _dependency(o0_prime, 0)
    _require_equal(
        o0_prime_dep.get("sha256"), O0_MANIFEST_SHA256, "o0_prime_to_o0_sha"
    )
    _require_equal(
        o0_prime_dep.get("bytes"), O0_MANIFEST_BYTES, "o0_prime_to_o0_bytes"
    )
    state = o0_prime.get("current_state_projection")
    if not isinstance(state, dict):
        raise EpistemicHostBootstrapError(["o0_prime_state"])
    expected_state = {
        "o0_design_review_lineage_satisfied": True,
        "o_actual_closed": False,
        "operational_predecessor_satisfied_count": 0,
        "host_control_plane_recipient_binding_present": False,
        "host_readback_performed": False,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    for key, value in expected_state.items():
        _require_equal(state.get(key), value, f"o0_prime_state:{key}")
    verdict = _validate_o0_prime_directory(o0_prime_path, o0_prime)
    return FrozenBootstrapContracts(
        repo_root=repo_root,
        stage1b_manifest=stage1b,
        meta_registry=meta,
        schema_bundle=schema,
        r2_manifest=r2,
        o0_manifest=o0,
        o0_prime_manifest=o0_prime,
        o0_prime_verdict=verdict,
        r2_manifest_path=r2_path,
        o0_manifest_path=o0_path,
        o0_prime_manifest_path=o0_prime_path,
    )


def validate_frozen_bootstrap_contracts(
    contracts: FrozenBootstrapContracts,
) -> FrozenBootstrapContracts:
    paths = (
        contracts.r2_manifest_path,
        contracts.o0_manifest_path,
        contracts.o0_prime_manifest_path,
    )
    if any(path is None for path in paths):
        raise EpistemicHostBootstrapError(["frozen_lineage_source_paths_unbound"])
    reloaded = load_frozen_bootstrap_contracts(
        stage1b_repo_root=contracts.repo_root,
        r2_manifest_path=paths[0],
        o0_manifest_path=paths[1],
        o0_prime_manifest_path=paths[2],
    )
    for field in (
        "stage1b_manifest",
        "meta_registry",
        "schema_bundle",
        "r2_manifest",
        "o0_manifest",
        "o0_prime_manifest",
        "o0_prime_verdict",
    ):
        _require_equal(
            getattr(contracts, field),
            getattr(reloaded, field),
            f"frozen_lineage_object_mismatch:{field}",
        )
    return reloaded


def _pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise EpistemicHostBootstrapError(["invalid_json_pointer"])
    current = document
    for encoded in pointer.split("/")[1:]:
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise EpistemicHostBootstrapError([f"pointer_array_token:{token}"])
            index = int(token)
            if index >= len(current):
                raise EpistemicHostBootstrapError([f"pointer_array_bounds:{token}"])
            current = current[index]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise EpistemicHostBootstrapError([f"pointer_unresolved:{token}"])
    return current


def _mandatory_skeleton(contracts: FrozenBootstrapContracts) -> dict[str, Any]:
    bundle = contracts.schema_bundle
    contract = bundle.get(
        "x-factorforge-semantic-mandatory-conformance-obligation-contract"
    )
    if not isinstance(contract, dict):
        raise EpistemicHostBootstrapError(["mandatory_contract_missing"])
    sources = contract.get("source_contract_order")
    if not isinstance(sources, list) or len(sources) != 5:
        raise EpistemicHostBootstrapError(["mandatory_source_count"])
    expected_counts = [10, 36, 50, 43, 31]
    expected_bases = [0, 10, 46, 96, 139]
    rows: list[dict[str, Any]] = []
    seen_vectors: set[str] = set()
    for source_ordinal, source in enumerate(sources):
        if not isinstance(source, dict):
            raise EpistemicHostBootstrapError([f"mandatory_source:{source_ordinal}"])
        expected_count = expected_counts[source_ordinal]
        expected_base = expected_bases[source_ordinal]
        _require_equal(
            source.get("source_contract_ordinal"),
            source_ordinal,
            f"mandatory_source_ordinal:{source_ordinal}",
        )
        _require_equal(
            source.get("exact_vector_count"),
            expected_count,
            f"mandatory_source_count:{source_ordinal}",
        )
        _require_equal(
            source.get("global_obligation_ordinal_base"),
            expected_base,
            f"mandatory_source_base:{source_ordinal}",
        )
        vectors = _pointer(bundle, str(source.get("source_json_pointer", "")))
        if not isinstance(vectors, list) or len(vectors) != expected_count:
            raise EpistemicHostBootstrapError([f"mandatory_vector_count:{source_ordinal}"])
        for vector_ordinal, vector in enumerate(vectors):
            if not isinstance(vector, str) or not SAFE_VECTOR_RE.fullmatch(vector):
                raise EpistemicHostBootstrapError([f"mandatory_vector_name:{source_ordinal}"])
            if vector in seen_vectors:
                raise EpistemicHostBootstrapError([f"mandatory_vector_duplicate:{vector}"])
            seen_vectors.add(vector)
            rows.append(
                {
                    "global_obligation_ordinal": expected_base + vector_ordinal,
                    "source_contract_ordinal": source_ordinal,
                    "source_contract_id": source.get("source_contract_id"),
                    "source_json_pointer": source.get("source_json_pointer"),
                    "source_vector_ordinal": vector_ordinal,
                    "vector_name": vector,
                    "owning_rule_ordinal": source.get("owning_rule_ordinal"),
                    "owning_rule_id": source.get("owning_rule_id"),
                    "expected_verdict": None,
                    "expected_public_reason_code": None,
                    "case_id": None,
                    "case_content_sha256": None,
                    "execution_status": "NOT_EXECUTED",
                }
            )
    _require_equal(len(rows), 170, "mandatory_total")
    _require_equal(
        [row["global_obligation_ordinal"] for row in rows],
        list(range(170)),
        "mandatory_global_ordinals",
    )
    core = {
        "schema_id": B0_SKELETON_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "source_schema_bundle_sha256": EXPECTED_STAGE1B_ARTIFACTS[0][2],
        "mandatory_contract_sha256": framed_sha256(
            "FF_SEMANTIC_MANDATORY_CONFORMANCE_OBLIGATION_CONTRACT_V1", contract
        ),
        "vector_count": 170,
        "minimum_distinct_case_count": 261,
        "rows": rows,
        "expectations_bound": False,
        "cases_materialized_count": 0,
        "executed_obligation_count": 0,
        "execution_mode": EXECUTION_MODE,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(
        core,
        domain="FF_B0_OFFLINE_HOST_BOOTSTRAP_OBLIGATION_SKELETON_V1",
    )


def _with_content_sha(payload: dict[str, Any], *, domain: str) -> dict[str, Any]:
    output = dict(payload)
    output.pop("content_sha256", None)
    output["content_sha256"] = framed_sha256(domain, output)
    return output


def compile_b0_bootstrap_plan(contracts: FrozenBootstrapContracts) -> dict[str, Any]:
    meta = contracts.meta_registry
    trust = meta.get("trust_bootstrap_contract")
    if not isinstance(trust, dict):
        raise EpistemicHostBootstrapError(["trust_bootstrap_contract"])
    _require_equal(
        trust.get("exact_domain_key_role_mapping"),
        EXPECTED_TRUST_DOMAIN_ROLE_MAPPING,
        "trust_domain_role_mapping",
    )
    _require_equal(
        trust.get("required_key_roles"),
        [role for roles in EXPECTED_TRUST_DOMAIN_ROLE_MAPPING.values() for role in roles],
        "key_role_order",
    )
    _require_equal(
        trust.get("required_per_key_fields"),
        EXPECTED_KEY_BINDING_FIELDS,
        "key_binding_fields",
    )
    control_roles = meta.get("control_plane_roles")
    if not isinstance(control_roles, list) or [
        row.get("role_id") if isinstance(row, dict) else None for row in control_roles
    ] != EXPECTED_CONTROL_ROLE_IDS:
        raise EpistemicHostBootstrapError(["control_role_universe"])
    role_projection = [
        {
            "ordinal": ordinal,
            "role_id": row["role_id"],
            "may_hold_control_action_signing_key": bool(
                row.get("may_hold_control_action_signing_key")
            ),
            "may_hold_content_provenance_key": bool(
                row.get("may_hold_content_provenance_key")
            ),
            "deployment_binding": None,
        }
        for ordinal, row in enumerate(control_roles)
    ]
    mandatory = meta.get("closed_schema_bundle", {}).get(
        "mandatory_conformance_exact_counts"
    )
    _require_equal(
        mandatory,
        {
            "source_vector_counts": [10, 36, 50, 43, 31],
            "source_global_ordinal_bases": [0, 10, 46, 96, 139],
            "mandatory_obligation_count": 170,
            "global_obligation_ordinal_range": [0, 169],
            "minimum_distinct_case_count": 261,
        },
        "mandatory_count_contract",
    )
    implementation_gates = meta.get("implementation_gates")
    authority_ceiling = meta.get("authority_ceiling")
    if not isinstance(implementation_gates, dict) or not isinstance(
        authority_ceiling, dict
    ):
        raise EpistemicHostBootstrapError(["authority_boundary"])
    if any(
        value is True
        for key, value in implementation_gates.items()
        if key.endswith("authorized")
    ):
        raise EpistemicHostBootstrapError(["stage1b_design_authority_uplift"])
    if any(value is not False for value in authority_ceiling.values()):
        raise EpistemicHostBootstrapError(["stage1b_authority_ceiling"])
    sanitized = meta.get("sanitized_output_allowlist")
    if not isinstance(sanitized, dict):
        raise EpistemicHostBootstrapError(["sanitized_output_allowlist"])
    core = {
        "schema_id": B0_PLAN_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "stage_id": "B0_OFFLINE_HOST_BOOTSTRAP_CONFORMANCE_CANDIDATE",
        "status": PARTIAL_STATUS,
        "execution_mode": EXECUTION_MODE,
        "source_contracts": [
            {
                "ordinal": 0,
                "role": "FROZEN_R2_AUTHORIZATION_BINDING_DESIGN_MANIFEST",
                "bytes": R2_MANIFEST_BYTES,
                "sha256": R2_MANIFEST_SHA256,
            },
            {
                "ordinal": 1,
                "role": "FROZEN_O0_HANDOFF_DESIGN_MANIFEST",
                "bytes": O0_MANIFEST_BYTES,
                "sha256": O0_MANIFEST_SHA256,
            },
            {
                "ordinal": 2,
                "role": "FROZEN_O0_PRIME_DESIGN_REVIEW_MANIFEST",
                "bytes": O0_PRIME_MANIFEST_BYTES,
                "sha256": O0_PRIME_MANIFEST_SHA256,
            },
            {
                "ordinal": 3,
                "role": "FROZEN_STAGE1B0_META_DESIGN_MANIFEST",
                "bytes": STAGE1B_MANIFEST_BYTES,
                "sha256": STAGE1B_MANIFEST_SHA256,
            },
        ],
        "trust_domain_role_mapping": [
            {
                "ordinal": ordinal,
                "trust_domain": domain,
                "key_roles": roles,
            }
            for ordinal, (domain, roles) in enumerate(
                EXPECTED_TRUST_DOMAIN_ROLE_MAPPING.items()
            )
        ],
        "required_key_binding_fields": EXPECTED_KEY_BINDING_FIELDS,
        "required_out_of_band_pins": trust.get("required_out_of_band_pins"),
        "control_plane_roles": role_projection,
        "control_plane_sod": meta.get("control_plane_sod"),
        "sanitized_output_policy": sanitized,
        "mandatory_conformance": {
            **mandatory,
            "discovered_obligation_count": 170,
            "expectations_bound": False,
            "materialized_case_count": 0,
            "executed_obligation_count": 0,
        },
        "actuals": {key: None for key in EXPECTED_ACTUAL_KEYS},
        "permissions": {key: False for key in EXPECTED_PERMISSION_KEYS},
        "review_eligible": False,
        "signed": False,
        "live_ceremony_authorized": False,
        "authority_ceiling": authority_ceiling,
        "authority_effect": AUTHORITY_EFFECT,
    }
    output = _with_content_sha(
        core,
        domain="FF_B0_OFFLINE_HOST_BOOTSTRAP_PLAN_V1",
    )
    assert_sanitized_candidate(output)
    return output


def compile_b0_obligation_skeleton(
    contracts: FrozenBootstrapContracts,
) -> dict[str, Any]:
    output = _mandatory_skeleton(contracts)
    assert_sanitized_candidate(output)
    return output


def assert_sanitized_candidate(payload: Any) -> None:
    stack: list[tuple[Any, str]] = [(payload, "$")]
    while stack:
        value, pointer = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in FORBIDDEN_OUTPUT_KEYS:
                    raise EpistemicHostBootstrapError([f"forbidden_output_key:{pointer}/{key}"])
                stack.append((child, f"{pointer}/{key}"))
        elif isinstance(value, list):
            stack.extend((child, f"{pointer}/{index}") for index, child in enumerate(value))
        elif isinstance(value, str):
            is_json_pointer = pointer.endswith("/source_json_pointer") and bool(
                JSON_POINTER_RE.fullmatch(value)
            )
            if (
                (value.startswith(("/", "~/", "../")) and not is_json_pointer)
                or PRIVATE_URI_RE.match(value)
                or "-----BEGIN" in value
                or value.startswith(("sk-", "AKIA", "Bearer "))
            ):
                raise EpistemicHostBootstrapError([f"forbidden_output_value:{pointer}"])


def validate_b0_bootstrap_plan(
    payload: dict[str, Any],
    *,
    contracts: FrozenBootstrapContracts,
) -> None:
    expected = compile_b0_bootstrap_plan(contracts)
    _require_equal(payload, expected, "b0_plan_closed_equality")
    assert_sanitized_candidate(payload)


def validate_b0_obligation_skeleton(
    payload: dict[str, Any],
    *,
    contracts: FrozenBootstrapContracts,
) -> None:
    expected = compile_b0_obligation_skeleton(contracts)
    _require_equal(payload, expected, "b0_skeleton_closed_equality")
    assert_sanitized_candidate(payload)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _analyze_implementation_surface(relative: str, raw: bytes) -> dict[str, Any]:
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=relative)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise EpistemicHostBootstrapError(
            [f"implementation_ast_parse_failure:{relative}:{type(exc).__name__}"]
        ) from exc
    imports: set[str] = set()
    forbidden_hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted in FORBIDDEN_IMPLEMENTATION_CALLS or (
                dotted is not None
                and dotted.startswith(("os.exec", "os.spawn", "os.posix_spawn"))
            ):
                forbidden_hits.add(f"call:{dotted}")
    for module in imports:
        root = module.split(".", 1)[0]
        if root in FORBIDDEN_IMPLEMENTATION_IMPORT_ROOTS:
            forbidden_hits.add(f"import:{module}")
    observed_imports = sorted(imports)
    expected_imports = EXPECTED_IMPLEMENTATION_IMPORTS.get(relative)
    _require_equal(
        observed_imports,
        expected_imports,
        f"implementation_import_allowlist_mismatch:{relative}",
    )
    top_level_callables = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    _require_equal(
        top_level_callables,
        EXPECTED_TOP_LEVEL_CALLABLES.get(relative),
        f"implementation_export_allowlist_mismatch:{relative}",
    )
    _require_equal(
        sorted(forbidden_hits),
        [],
        f"forbidden_implementation_surface:{relative}",
    )
    return {
        "ast_parse": "PASS",
        "exact_import_allowlist": "PASS",
        "exact_top_level_callable_allowlist": "PASS",
        "forbidden_network_crypto_dynamic_execution_hits": [],
        "observed_import_modules": observed_imports,
        "observed_top_level_callables": top_level_callables,
        "surface_verdict": "PASS",
    }


def build_b0_implementation_inventory(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for ordinal, relative in enumerate(EXPECTED_IMPLEMENTATION_FILES):
        path = root / relative
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 0 < metadata.st_size <= 4 * 1024 * 1024
        ):
            raise EpistemicHostBootstrapError(
                [f"unsafe_implementation_file:{relative}"]
            )
        raw = path.read_bytes()
        if len(raw) != metadata.st_size:
            raise EpistemicHostBootstrapError(
                [f"changed_implementation_file:{relative}"]
            )
        rows.append(
            {
                "ordinal": ordinal,
                "logical_path": relative,
                "bytes": len(raw),
                "sha256": _sha256(raw),
                "surface_analysis": _analyze_implementation_surface(relative, raw),
            }
        )
    core = {
        "schema_id": B0_IMPLEMENTATION_INVENTORY_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "implementation_scope": "OFFLINE_CONTRACT_COMPILER_AND_SKELETON_ONLY",
        "surface_validation_profile_id": (
            "FF_B0_EXACT_AST_IMPORT_TOP_LEVEL_CALLABLE_ALLOWLIST_V1"
        ),
        "file_count": len(rows),
        "ordered_files": rows,
        "live_host_adapter_present": False,
        "live_signer_present": False,
        "live_key_generation_present": False,
        "network_adapter_present": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    output = _with_content_sha(
        core,
        domain="FF_B0_OFFLINE_HOST_BOOTSTRAP_IMPLEMENTATION_INVENTORY_V1",
    )
    assert_sanitized_candidate(output)
    return output


def validate_b0_implementation_inventory(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> None:
    expected = build_b0_implementation_inventory(repo_root)
    _require_equal(payload, expected, "b0_implementation_inventory_closed_equality")
    _require_equal(
        [
            payload["live_host_adapter_present"],
            payload["live_signer_present"],
            payload["live_key_generation_present"],
            payload["network_adapter_present"],
        ],
        [False, False, False, False],
        "b0_live_surface_absence",
    )
    assert_sanitized_candidate(payload)


def build_b0_validation_report(
    *,
    contracts: FrozenBootstrapContracts,
    plan: dict[str, Any],
    skeleton: dict[str, Any],
    implementation_inventory: dict[str, Any],
) -> dict[str, Any]:
    reloaded = validate_frozen_bootstrap_contracts(contracts)
    validate_b0_bootstrap_plan(plan, contracts=reloaded)
    validate_b0_obligation_skeleton(skeleton, contracts=reloaded)
    validate_b0_implementation_inventory(
        implementation_inventory,
        repo_root=reloaded.repo_root,
    )
    _require_equal(len(plan["required_out_of_band_pins"]), 25, "pin_count")
    _require_equal(
        plan["actuals"],
        {key: None for key in EXPECTED_ACTUAL_KEYS},
        "actuals_not_all_null",
    )
    _require_equal(
        plan["permissions"],
        {key: False for key in EXPECTED_PERMISSION_KEYS},
        "permissions_not_all_false",
    )
    predicates = [
        (
            "FROZEN_LINEAGE_IDENTITY",
            "re-read exact R2/O0/O0-prime/Stage1B bytes and SHA-256",
        ),
        (
            "STAGE1B_EXACT4_ARTIFACT_CLOSURE",
            "_validate_stage1b exact ordered artifact rows and stable file reads",
        ),
        (
            "O0_TO_R2_CROSS_EQUALITY",
            "load_frozen_bootstrap_contracts dependency ordinal 0 equality",
        ),
        (
            "O0_PRIME_TO_O0_CROSS_EQUALITY",
            "load_frozen_bootstrap_contracts dependency ordinal 0 equality",
        ),
        (
            "O0_PRIME_DESIGN_REVIEW_GO_ZERO_ZERO",
            "_validate_o0_prime_directory closed verdict predicate",
        ),
        (
            "EXACT4_TRUST_DOMAIN",
            "validate_b0_bootstrap_plan closed compiler equality",
        ),
        (
            "EXACT7_KEY_ROLE_3_2_1_1_MAPPING",
            "validate_b0_bootstrap_plan closed compiler equality",
        ),
        (
            "EXACT5_CONTROL_ROLE_PROJECTION",
            "validate_b0_bootstrap_plan closed compiler equality",
        ),
        (
            "EXACT25_OUT_OF_BAND_PIN_FIELD_UNIVERSE",
            "closed plan equality plus explicit exact25 predicate",
        ),
        (
            "SANITIZED_CANDIDATE_PROJECTION",
            "plan, skeleton, inventory sanitizer predicates",
        ),
        (
            "MANDATORY_SOURCE_VECTOR_10_36_50_43_31",
            "validate_b0_obligation_skeleton closed compiler equality",
        ),
        (
            "MANDATORY_GLOBAL_ORDINAL_0_THROUGH_169",
            "validate_b0_obligation_skeleton closed compiler equality",
        ),
        (
            "ALL_ACTUALS_NULL",
            "explicit exact11 actuals equality predicate",
        ),
        (
            "ALL_PERMISSIONS_FALSE",
            "explicit exact12 permissions equality predicate",
        ),
        (
            "NO_LIVE_ADAPTER_OR_CRYPTO",
            "exact file hash plus AST import/callable/forbidden-call surface predicates",
        ),
    ]
    core = {
        "schema_id": B0_REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "stage_id": "B0_OFFLINE_HOST_BOOTSTRAP_CONFORMANCE_CANDIDATE",
        "status": PARTIAL_STATUS,
        "execution_mode": EXECUTION_MODE,
        "plan_content_sha256": plan["content_sha256"],
        "obligation_skeleton_content_sha256": skeleton["content_sha256"],
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
        "mandatory_obligation_discovered_count": 170,
        "mandatory_obligation_executed_count": 0,
        "minimum_distinct_case_count": 261,
        "materialized_case_count": 0,
        "fixture_only": True,
        "signed": False,
        "semantic_validation_receipt": False,
        "review_eligible": False,
        "live_ready": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    output = _with_content_sha(
        core,
        domain="FF_B0_OFFLINE_HOST_BOOTSTRAP_VALIDATION_REPORT_V1",
    )
    assert_sanitized_candidate(output)
    return output


def _file_row(path: Path, *, ordinal: int, role: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "ordinal": ordinal,
        "role": role,
        "path": path.name,
        "bytes": len(raw),
        "sha256": _sha256(raw),
    }


def write_b0_candidate_bundle(
    output_root: Path,
    *,
    plan: dict[str, Any],
    skeleton: dict[str, Any],
    report: dict[str, Any],
    implementation_inventory: dict[str, Any],
) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists() or root.is_symlink():
        raise EpistemicHostBootstrapError(["output_root_must_not_exist"])
    root.mkdir(parents=True, mode=0o700)
    root = root.resolve(strict=True)
    root.chmod(0o700)
    write_workspace_json_once(root, "00_b0_bootstrap_plan.json", plan)
    write_workspace_json_once(root, "01_b0_obligation_skeleton.json", skeleton)
    write_workspace_json_once(root, "02_b0_validation_report.json", report)
    write_workspace_json_once(
        root,
        "03_b0_implementation_inventory.json",
        implementation_inventory,
    )
    rows = [
        _file_row(root / "00_b0_bootstrap_plan.json", ordinal=0, role="B0_BOOTSTRAP_PLAN"),
        _file_row(
            root / "01_b0_obligation_skeleton.json",
            ordinal=1,
            role="B0_OBLIGATION_SKELETON",
        ),
        _file_row(
            root / "02_b0_validation_report.json",
            ordinal=2,
            role="B0_VALIDATION_REPORT",
        ),
        _file_row(
            root / "03_b0_implementation_inventory.json",
            ordinal=3,
            role="B0_IMPLEMENTATION_INVENTORY",
        ),
    ]
    manifest_core = {
        "schema_id": B0_PACKET_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": "FF_EPISTEMIC_HOST_BOOTSTRAP_B0_OFFLINE_CANDIDATE_20260828_R2",
        "manifest_status": PARTIAL_STATUS,
        "artifact_count": 4,
        "ordered_artifacts": rows,
        "source_contracts": plan["source_contracts"],
        "candidate_integrity_profile": {
            "profile_id": "LOCAL_NONAUTHORITATIVE_CANDIDATE_INTEGRITY_ONLY",
            "scope": "MANIFEST_AND_EXACT4_ARTIFACTS",
            "authority_effect": AUTHORITY_EFFECT,
            "may_satisfy_host_or_operating_authority": False,
            "content_digest_profile": {
                "canonicalization": "RFC8785_INTEGER_ONLY_ACCEPTED_JSON_PROFILE",
                "framing": "UTF8_DOMAIN_THEN_NUL_THEN_CANONICAL_JSON",
                "formula": (
                    "SHA256(UTF8(domain)||0x00||"
                    "RFC8785_INTEGER_ONLY(payload_without_content_sha256))"
                ),
                "domains_by_role": {
                    "B0_BOOTSTRAP_PLAN": "FF_B0_OFFLINE_HOST_BOOTSTRAP_PLAN_V1",
                    "B0_OBLIGATION_SKELETON": (
                        "FF_B0_OFFLINE_HOST_BOOTSTRAP_OBLIGATION_SKELETON_V1"
                    ),
                    "B0_VALIDATION_REPORT": (
                        "FF_B0_OFFLINE_HOST_BOOTSTRAP_VALIDATION_REPORT_V1"
                    ),
                    "B0_IMPLEMENTATION_INVENTORY": (
                        "FF_B0_OFFLINE_HOST_BOOTSTRAP_IMPLEMENTATION_INVENTORY_V1"
                    ),
                    "PACKET_MANIFEST": (
                        "FF_B0_OFFLINE_HOST_BOOTSTRAP_PACKET_MANIFEST_V1"
                    ),
                },
            },
            "artifact_manifest_commitment_profile": {
                "domain": "FF_B0_OFFLINE_HOST_BOOTSTRAP_ARTIFACT_MANIFEST_V1",
                "framing": "UTF8_DOMAIN_THEN_NUL_THEN_ORDERED_BINARY_SHA256",
                "formula": (
                    "SHA256(UTF8(domain)||0x00||"
                    "CONCAT(ordered_artifact_raw_sha256_binary_32_bytes))"
                ),
            },
        },
        "review_eligible": False,
        "live_ceremony_authorized": False,
        "implementation_scope": "OFFLINE_CONTRACT_COMPILER_AND_SKELETON_ONLY",
        "operational_predecessor_satisfied_count": 0,
        "permissions_opened_count": 0,
        "authority_effect": AUTHORITY_EFFECT,
    }
    artifact_commitment = hashlib.sha256(
        b"FF_B0_OFFLINE_HOST_BOOTSTRAP_ARTIFACT_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in rows)
    ).hexdigest()
    manifest_core["artifact_manifest_commitment_sha256"] = artifact_commitment
    manifest = _with_content_sha(
        manifest_core,
        domain="FF_B0_OFFLINE_HOST_BOOTSTRAP_PACKET_MANIFEST_V1",
    )
    assert_sanitized_candidate(manifest)
    write_workspace_json_once(root, "packet_manifest.json", manifest)
    return manifest
