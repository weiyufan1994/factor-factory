#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_evidence import sha256_file
from factor_factory.research_org.director import load_research_organization_plan
from factor_factory.research_org.contracts import stable_json_hash
from factor_factory.research_org.runtime import validate_research_organization_runtime


ROLE_IDS = ("portfolio_manager", "risk_officer", "execution_capacity")
ROLE_DECISIONS = {"CANARY_REJECT", "CANARY_ITERATE", "CANARY_BLOCK"}
ROLE_FINDING_CODES = {
    "portfolio_manager": {
        "ORDERING_SIGNAL_PRESENT",
        "ORDERING_SIGNAL_ABSENT",
        "ABSOLUTE_LONG_GATE_FAIL",
        "RELATIVE_BENCHMARK_GATE_FAIL",
        "BUCKET_MONOTONICITY_FAIL",
        "COMPONENT_INCREMENTALITY_FAIL",
        "SAMPLE_SCOPE_BLOCK",
    },
    "risk_officer": {
        "SHARPE_GATE_FAIL",
        "DRAWDOWN_GATE_FAIL",
        "BREADTH_GATE_PASS",
        "EXCLUSION_GATE_PASS",
        "SAMPLE_SCOPE_BLOCK",
        "RISK_GATE_PASS",
    },
    "execution_capacity": {
        "TURNOVER_COST_DOMINATES",
        "CAPACITY_UNPROVEN",
        "EXECUTION_TIMING_BOUND",
        "TRANSACTION_COST_BOUND",
        "SAMPLE_SCOPE_BLOCK",
        "EXECUTION_GATE_PASS",
    },
}

BLOCK_CANARY_INPUT_INVALID = "BLOCK_CANARY_INPUT_INVALID"
BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID = (
    "BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID"
)
BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED = (
    "BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED"
)
BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID = (
    "BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID"
)
BLOCK_CANARY_STALE_LEGACY_CERTIFICATE_INVALIDATED = (
    "BLOCK_CANARY_STALE_LEGACY_CERTIFICATE_INVALIDATED"
)
STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY = (
    "STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY"
)
LEGACY_INVALIDATION_INDEX_VERSION = (
    "factorforge_small_batch_canary_negative_invalidation_index_v1"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_ORG_ROLES = {
    "research_director",
    "knowledge_librarian",
    "data_liaison",
    "quant_implementation",
    "validation_evidence",
    "independent_council",
}


class CanaryClosureError(ValueError):
    """A fail-closed small-batch canary contract violation."""


def _fail(code: str, reason: str) -> CanaryClosureError:
    return CanaryClosureError(f"{code}:{reason}")


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_json") from exc
    if not isinstance(value, dict):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_object")
    return value


def _resolve_file(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_path")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    if candidate.is_symlink():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_symlink")
    try:
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_missing") from exc
    if not path.is_file():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_not_file")
    return path


def _canonical_input_file(value: Path | str, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_symlink")
    try:
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_missing") from exc
    if not path.is_file():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_not_file")
    return path


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_sha256")
    return value


def _require_file_hash(path: Path, expected: object, *, label: str) -> str:
    digest = _require_sha256(expected, label=label)
    if sha256_file(path) != digest:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_hash_mismatch")
    return digest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def legacy_invalidation_index_path(workspace: Path | str) -> Path:
    root = Path(workspace).expanduser().resolve(strict=True)
    return (
        root
        / "tmp"
        / "small_batch_canary_closure"
        / "stale_legacy_invalidation_index_v1.json"
    )


def _workspace_relative_file(workspace: Path, value: Path, *, label: str) -> tuple[Path, str]:
    if value.is_symlink():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_symlink")
    try:
        resolved = value.expanduser().resolve(strict=True)
        relative = resolved.relative_to(workspace)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_outside_workspace") from exc
    if not resolved.is_file() or ".." in relative.parts:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, f"{label}_unsafe")
    return resolved, relative.as_posix()


def _write_create_only(path: Path, payload: bytes) -> bool:
    """Publish bytes once using a hard-link create, never replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            "index_symlink",
        )
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise _fail(
                BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
                "create_only_conflict",
            )
        return False
    temporary = path.parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise _fail(
                BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
                "create_only_race_conflict",
            )
        return False
    finally:
        temporary.unlink(missing_ok=True)
    return True


def validate_role_result(payload: dict[str, Any], role_id: str) -> list[str]:
    reasons: list[str] = []
    expected = {
        "contract_version",
        "role_id",
        "status",
        "evidence_scope",
        "finding_codes",
        "decision",
        "public_rationale",
        "production_authority",
    }
    if set(payload) != expected:
        reasons.append("shape")
    if payload.get("contract_version") != "factorforge_small_batch_post_execution_role_v1":
        reasons.append("contract_version")
    if payload.get("role_id") != role_id:
        reasons.append("role_id")
    if payload.get("status") != "PASS":
        reasons.append("status")
    if payload.get("evidence_scope") != "small_batch_canary_only":
        reasons.append("evidence_scope")
    findings = payload.get("finding_codes")
    if (
        not isinstance(findings, list)
        or not findings
        or role_id not in ROLE_FINDING_CODES
        or any(item not in ROLE_FINDING_CODES[role_id] for item in findings)
    ):
        reasons.append("finding_codes")
    if payload.get("decision") not in ROLE_DECISIONS:
        reasons.append("decision")
    rationale = payload.get("public_rationale")
    if not isinstance(rationale, str) or not 20 <= len(rationale) <= 1200:
        reasons.append("public_rationale")
    if payload.get("production_authority") is not False:
        reasons.append("production_authority")
    return reasons


def validate_council_result(
    payload: dict[str, Any], role_bindings: list[dict[str, str]]
) -> list[str]:
    reasons: list[str] = []
    expected = {
        "contract_version",
        "role_id",
        "status",
        "evidence_scope",
        "reviewed_role_bindings",
        "terminal_decision",
        "formal_factor_verdict",
        "production_eligible",
        "official_promotion_allowed",
        "public_rationale",
    }
    if set(payload) != expected:
        reasons.append("shape")
    if payload.get("contract_version") != "factorforge_small_batch_investment_council_v1":
        reasons.append("contract_version")
    if payload.get("role_id") != "independent_investment_council":
        reasons.append("role_id")
    if payload.get("status") != "PASS":
        reasons.append("status")
    if payload.get("evidence_scope") != "small_batch_canary_only":
        reasons.append("evidence_scope")
    if payload.get("reviewed_role_bindings") != role_bindings:
        reasons.append("reviewed_role_bindings")
    if payload.get("terminal_decision") not in ROLE_DECISIONS:
        reasons.append("terminal_decision")
    if payload.get("formal_factor_verdict") != "NOT_ISSUED":
        reasons.append("formal_factor_verdict")
    if payload.get("production_eligible") is not False:
        reasons.append("production_eligible")
    if payload.get("official_promotion_allowed") is not False:
        reasons.append("official_promotion_allowed")
    rationale = payload.get("public_rationale")
    if not isinstance(rationale, str) or not 20 <= len(rationale) <= 1600:
        reasons.append("public_rationale")
    return reasons


def validate_provisional_sample_bundle(
    *,
    metrics_path: Path,
    panel_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Replay the immutable v4-style sample bindings without writing state."""

    metrics_path = _canonical_input_file(metrics_path, label="metrics")
    panel_path = _canonical_input_file(panel_path, label="panel")
    manifest_path = _canonical_input_file(
        manifest_path, label="pre_metric_manifest"
    )
    metrics = _load_object(metrics_path, label="metrics")
    manifest = _load_object(manifest_path, label="pre_metric_manifest")

    if metrics.get("status") != "PROVISIONAL_NON_FORMAL_SAMPLE":
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_scope")
    if metrics.get("formal_factor_verdict") != "NOT_ISSUED":
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_formal_factor_verdict")
    factor_id = metrics.get("factor_id")
    formula_hash = metrics.get("formula_hash")
    if not isinstance(factor_id, str) or not factor_id:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_factor_id")
    _require_sha256(formula_hash, label="metrics_formula")

    if (
        manifest.get("contract_version")
        != "factorforge_provisional_sample_manifest_v1"
        or manifest.get("status") != "FROZEN_BEFORE_METRICS"
        or manifest.get("authority")
        != "NON_FORMAL_CANARY_ONLY_NO_FACTOR_VERDICT"
        or manifest.get("factor_id") != factor_id
        or manifest.get("formula_hash") != formula_hash
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "manifest_identity_or_scope")
    manifest_without_hash = dict(manifest)
    claimed_content_hash = manifest_without_hash.pop("content_sha256", None)
    if (
        _require_sha256(claimed_content_hash, label="manifest_content")
        != stable_json_hash(manifest_without_hash)
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "manifest_content_hash_mismatch")

    panel_ref = metrics.get("panel")
    if not isinstance(panel_ref, Mapping) or set(panel_ref) != {"path", "sha256"}:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_panel_ref")
    declared_panel = _resolve_file(panel_ref.get("path"), label="metrics_panel")
    if declared_panel != panel_path:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "panel_path_mismatch")
    panel_sha256 = _require_file_hash(
        panel_path, panel_ref.get("sha256"), label="panel"
    )

    replay = metrics.get("replay")
    if not isinstance(replay, Mapping):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_replay")
    declared_manifest = _resolve_file(
        replay.get("pre_metric_manifest_path"), label="metrics_manifest"
    )
    if declared_manifest != manifest_path:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "manifest_path_mismatch")
    manifest_sha256 = _require_file_hash(
        manifest_path,
        replay.get("pre_metric_manifest_sha256"),
        label="pre_metric_manifest",
    )
    if not (
        metrics_path.parent == panel_path.parent == manifest_path.parent
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "sample_bundle_directory")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, Mapping):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "manifest_inputs")
    resolved_inputs: dict[str, Path] = {}
    for key in ("source", "spec", "trusted_calendar", "runner"):
        path = _resolve_file(inputs.get(f"{key}_path"), label=f"manifest_{key}")
        _require_file_hash(path, inputs.get(f"{key}_sha256"), label=f"manifest_{key}")
        resolved_inputs[key] = path
    engine_sources = inputs.get("engine_source_sha256")
    if not isinstance(engine_sources, Mapping) or not engine_sources:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "manifest_engine_sources")
    for relative, expected in engine_sources.items():
        engine_path = _resolve_file(relative, label="manifest_engine_source")
        try:
            engine_path.relative_to(REPO_ROOT)
        except ValueError as exc:
            raise _fail(
                BLOCK_CANARY_INPUT_INVALID, "manifest_engine_source_outside_repo"
            ) from exc
        _require_file_hash(engine_path, expected, label=f"engine_source:{relative}")

    source_ref = metrics.get("source")
    if not isinstance(source_ref, Mapping):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_source_ref")
    if (
        _resolve_file(source_ref.get("path"), label="metrics_source")
        != resolved_inputs["source"]
        or source_ref.get("sha256") != inputs.get("source_sha256")
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "metrics_source_binding")
    for replay_key, input_key in (
        ("runner_sha256", "runner_sha256"),
        ("spec_sha256", "spec_sha256"),
        ("trusted_calendar_sha256", "trusted_calendar_sha256"),
    ):
        if replay.get(replay_key) != inputs.get(input_key):
            raise _fail(BLOCK_CANARY_INPUT_INVALID, f"metrics_{replay_key}_binding")

    frozen = manifest.get("frozen_parameters")
    reported_frozen = metrics.get("frozen_before_metrics")
    if not isinstance(frozen, Mapping) or not isinstance(reported_frozen, Mapping):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "frozen_parameters")
    date_keys = (
        "formal_oos_end",
        "read_start",
        "score_start",
        "pseudo_holdout_start",
        "read_end",
    )
    try:
        dates = {key: int(frozen[key]) for key in date_keys}
    except (KeyError, TypeError, ValueError) as exc:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "frozen_dates") from exc
    if not (
        dates["formal_oos_end"] < dates["read_start"]
        <= dates["score_start"]
        < dates["pseudo_holdout_start"]
        <= dates["read_end"]
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "frozen_date_order")
    for key in date_keys:
        if str(reported_frozen.get(key) or "") != str(dates[key]):
            raise _fail(BLOCK_CANARY_INPUT_INVALID, f"reported_frozen_{key}")
    if (
        reported_frozen.get("cost_one_way") != frozen.get("cost_one_way")
        or reported_frozen.get("portfolio") != frozen.get("portfolio")
        or frozen.get("label")
        != "calendar-aligned close_t_plus_1_to_close_t_plus_2"
        or reported_frozen.get("label")
        != "calendar-aligned close_t_plus_2 / close_t_plus_1 - 1"
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "frozen_evaluation_contract")

    return {
        "status": "PREFLIGHT_VALIDATED_ONLY",
        "factor_id": factor_id,
        "formula_hash": formula_hash,
        "formal_factor_verdict": "NOT_ISSUED",
        "metrics_path": str(metrics_path),
        "metrics_sha256": sha256_file(metrics_path),
        "panel_path": str(panel_path),
        "panel_sha256": panel_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
    }


def replay_current_preformal_organization(
    *,
    workspace: Path,
    org_validation_path: Path,
    org_private_root: Path,
    trust_root: Path,
    installation_id: str,
    factor_id: str,
) -> dict[str, Any]:
    """Require an exact current formal replay of the seven-role organization."""

    org_validation_path = _canonical_input_file(
        org_validation_path, label="org_validation"
    )
    stored = _load_object(org_validation_path, label="org_validation")
    try:
        current = validate_research_organization_runtime(
            workspace=workspace.expanduser().resolve(strict=True),
            require_complete=True,
            private_root=org_private_root.expanduser().resolve(strict=True),
            trust_root=trust_root.expanduser().resolve(strict=True),
            installation_id=installation_id,
            require_formal=True,
        )
        plan = load_research_organization_plan(
            workspace.expanduser().resolve(strict=True)
        )
    except Exception as exc:  # The current runtime validator is the authority.
        raise _fail(
            BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID,
            f"current_validator:{type(exc).__name__}",
        ) from exc
    if stable_json_hash(current) != stable_json_hash(stored):
        raise _fail(
            BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID,
            "stored_projection_drift",
        )
    identity = plan.get("identity") if isinstance(plan, Mapping) else None
    execution_policy = (
        plan.get("execution_policy") if isinstance(plan, Mapping) else None
    )
    role_plan = plan.get("role_plan") if isinstance(plan, Mapping) else None
    required_roles = (
        role_plan.get("required_roles") if isinstance(role_plan, Mapping) else None
    )
    role_states = current.get("role_states")
    if (
        not isinstance(identity, Mapping)
        or identity.get("factor_id") != factor_id
        or not isinstance(execution_policy, Mapping)
        or execution_policy.get("single_agent_fallback") is not False
        or not isinstance(required_roles, list)
        or len(required_roles) != 7
        or len(set(required_roles)) != 7
        or not _REQUIRED_ORG_ROLES.issubset(set(required_roles))
        or not isinstance(role_states, Mapping)
        or set(role_states) != set(required_roles)
        or any(status != "PASS" for status in role_states.values())
        or current.get("verdict") != "PASS"
        or current.get("lifecycle") != "COMPLETE"
        or current.get("task_count") != 7
        or current.get("result_count") != 7
        or current.get("receipt_count") != 6
        or current.get("session_count") != 6
        or current.get("formal_independence_verified") is not True
        or current.get("runtime_assurance")
        != "signed_specialist_runtime_complete_host_director_external"
    ):
        raise _fail(
            BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID,
            "seven_role_formal_identity_or_assurance",
        )
    return {
        "status": "CURRENT_ORG_REPLAY_VALIDATED_ONLY",
        "identity": dict(identity),
        "runtime_id": current.get("runtime_id"),
        "validation_path": str(org_validation_path),
        "validation_sha256": sha256_file(org_validation_path),
        "session_count": current.get("session_count"),
        "formal_factor_verdict": "NOT_ISSUED",
    }


def _legacy_certificate_ref(workspace: Path, certificate_path: Path) -> dict[str, str]:
    path, relative = _workspace_relative_file(
        workspace, certificate_path, label="legacy_certificate"
    )
    certificate = _load_object(path, label="legacy_certificate")
    receipt_id = _require_sha256(
        certificate.get("receipt_id"), label="legacy_certificate_receipt"
    )
    closure_id = certificate.get("closure_id")
    preformal = certificate.get("preformal_organization")
    if (
        not isinstance(closure_id, str)
        or re.fullmatch(r"small_batch_closure_[a-f0-9]{16}", closure_id) is None
        or certificate.get("status") != "COMPLETE"
        or certificate.get("terminal_decision") not in ROLE_DECISIONS
        or certificate.get("formal_factor_verdict") != "NOT_ISSUED"
        or not isinstance(preformal, Mapping)
        or not isinstance(preformal.get("runtime_id"), str)
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "legacy_certificate_shape")
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "receipt_id": receipt_id,
        "closure_id": closure_id,
        "legacy_terminal_decision": str(certificate["terminal_decision"]),
        "legacy_runtime_id": str(preformal["runtime_id"]),
    }


def _negative_invalidation_authority() -> dict[str, Any]:
    return {
        "scope": "NEGATIVE_ONLY",
        "formal_factor_verdict": "NOT_ISSUED",
        "certificate_acceptance_authority": False,
        "factor_verdict_authority": False,
        "permanent_for_bound_certificate_identity": True,
    }


def validate_legacy_invalidation_index(
    *, workspace: Path | str, index_path: Path | str | None = None
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve(strict=True)
    canonical_path = legacy_invalidation_index_path(root)
    candidate = Path(index_path).expanduser() if index_path is not None else canonical_path
    if candidate.is_symlink():
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            "index_symlink",
        )
    path = candidate.resolve(strict=True)
    if path != canonical_path or canonical_path.is_symlink():
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            "noncanonical_index_path",
        )
    try:
        index = _load_object(path, label="legacy_invalidation_index")
    except CanaryClosureError as exc:
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            str(exc),
        ) from exc
    expected_fields = {
        "contract_version",
        "status",
        "invalidation_reason",
        "created_at_utc",
        "workspace_plan_ref",
        "current_org_replay",
        "certificates",
        "authority",
        "content_sha256",
    }
    without_hash = dict(index)
    claimed_hash = without_hash.pop("content_sha256", None)
    certificates = index.get("certificates")
    replay = index.get("current_org_replay")
    plan_ref = index.get("workspace_plan_ref")
    if (
        set(index) != expected_fields
        or index.get("contract_version") != LEGACY_INVALIDATION_INDEX_VERSION
        or index.get("status") != "CLOSED_NEGATIVE_INVALIDATION"
        or index.get("invalidation_reason")
        != STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
        or index.get("authority") != _negative_invalidation_authority()
        or _require_sha256(claimed_hash, label="invalidation_index_content")
        != stable_json_hash(without_hash)
        or not isinstance(index.get("created_at_utc"), str)
        or not index.get("created_at_utc")
        or not isinstance(replay, Mapping)
        or set(replay)
        != {
            "status",
            "reason",
            "validator_contract",
            "failure_class",
            "failure_sha256",
        }
        or replay.get("status") != "INVALID"
        or replay.get("reason") != STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
        or replay.get("validator_contract")
        != "validate_research_organization_runtime(require_complete=True,require_formal=True)"
        or not isinstance(replay.get("failure_class"), str)
        or _SHA256.fullmatch(str(replay.get("failure_sha256") or "")) is None
        or not isinstance(plan_ref, Mapping)
        or set(plan_ref) != {"path", "sha256"}
        or plan_ref.get("path") != "identity/research_organization_plan.json"
        or not isinstance(certificates, list)
        or not certificates
    ):
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            "closed_shape",
        )
    plan_path = root / str(plan_ref["path"])
    _require_file_hash(plan_path, plan_ref.get("sha256"), label="index_plan")
    expected_certificate_fields = {
        "path",
        "sha256",
        "receipt_id",
        "closure_id",
        "legacy_terminal_decision",
        "legacy_runtime_id",
    }
    normalized: list[dict[str, str]] = []
    for entry in certificates:
        if not isinstance(entry, Mapping) or set(entry) != expected_certificate_fields:
            raise _fail(
                BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
                "certificate_entry_shape",
            )
        resolved, relative = _workspace_relative_file(
            root, root / str(entry.get("path") or ""), label="indexed_certificate"
        )
        actual = _legacy_certificate_ref(root, resolved)
        if dict(entry) != actual or relative != entry.get("path"):
            raise _fail(
                BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
                "certificate_entry_binding",
            )
        normalized.append(actual)
    if (
        normalized != sorted(normalized, key=lambda item: item["path"])
        or len({item["path"] for item in normalized}) != len(normalized)
        or len({item["receipt_id"] for item in normalized}) != len(normalized)
        or len({item["closure_id"] for item in normalized}) != len(normalized)
    ):
        raise _fail(
            BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
            "certificate_entry_order_or_uniqueness",
        )
    return index


def materialize_stale_legacy_invalidation_index(
    *,
    workspace: Path | str,
    org_private_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    certificate_paths: list[Path | str],
) -> dict[str, Any]:
    """Create one closed negative-only index after current formal replay fails."""

    root = Path(workspace).expanduser().resolve(strict=True)
    paths = [Path(item) for item in certificate_paths]
    if not paths:
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "legacy_certificate_set_empty")
    try:
        validate_research_organization_runtime(
            workspace=root,
            require_complete=True,
            private_root=Path(org_private_root).expanduser().resolve(strict=True),
            trust_root=Path(trust_root).expanduser().resolve(strict=True),
            installation_id=installation_id,
            require_formal=True,
        )
    except Exception as exc:  # A failure is the sole authority for this negative action.
        failure_class = type(exc).__name__
        failure_sha256 = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()
    else:
        raise _fail(
            BLOCK_CANARY_INPUT_INVALID,
            "current_org_replay_did_not_fail",
        )
    refs = sorted(
        (_legacy_certificate_ref(root, path) for path in paths),
        key=lambda item: item["path"],
    )
    if (
        len({item["path"] for item in refs}) != len(refs)
        or len({item["receipt_id"] for item in refs}) != len(refs)
        or len({item["closure_id"] for item in refs}) != len(refs)
    ):
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "legacy_certificate_duplicates")
    plan_path, plan_relative = _workspace_relative_file(
        root,
        root / "identity" / "research_organization_plan.json",
        label="workspace_plan",
    )
    if plan_relative != "identity/research_organization_plan.json":
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "workspace_plan_path")
    index_path = legacy_invalidation_index_path(root)
    existing: dict[str, Any] | None = None
    if index_path.exists() or index_path.is_symlink():
        existing = validate_legacy_invalidation_index(
            workspace=root, index_path=index_path
        )
        if existing.get("certificates") != refs:
            raise _fail(
                BLOCK_CANARY_STALE_LEGACY_INVALIDATION_INDEX_INVALID,
                "closed_index_certificate_set_conflict",
            )
        return {
            "status": "CLOSED_NEGATIVE_INVALIDATION",
            "written": False,
            "index_path": str(index_path),
            "content_sha256": existing["content_sha256"],
            "certificate_count": len(refs),
            "formal_factor_verdict": "NOT_ISSUED",
        }
    index: dict[str, Any] = {
        "contract_version": LEGACY_INVALIDATION_INDEX_VERSION,
        "status": "CLOSED_NEGATIVE_INVALIDATION",
        "invalidation_reason": STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY,
        "created_at_utc": _utc_now(),
        "workspace_plan_ref": {
            "path": "identity/research_organization_plan.json",
            "sha256": sha256_file(plan_path),
        },
        "current_org_replay": {
            "status": "INVALID",
            "reason": STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY,
            "validator_contract": (
                "validate_research_organization_runtime("
                "require_complete=True,require_formal=True)"
            ),
            "failure_class": failure_class,
            "failure_sha256": failure_sha256,
        },
        "certificates": refs,
        "authority": _negative_invalidation_authority(),
    }
    index["content_sha256"] = stable_json_hash(index)
    _write_create_only(index_path, _canonical_bytes(index))
    validated = validate_legacy_invalidation_index(
        workspace=root, index_path=index_path
    )
    return {
        "status": "CLOSED_NEGATIVE_INVALIDATION",
        "written": True,
        "index_path": str(index_path),
        "content_sha256": validated["content_sha256"],
        "certificate_count": len(refs),
        "formal_factor_verdict": "NOT_ISSUED",
    }


def certificate_invalidation_reason(
    *, workspace: Path | str, certificate_path: Path | str
) -> str | None:
    """Return the permanent negative reason for a byte/receipt/closure match."""

    root = Path(workspace).expanduser().resolve(strict=True)
    index_path = legacy_invalidation_index_path(root)
    if not index_path.exists() and not index_path.is_symlink():
        return None
    index = validate_legacy_invalidation_index(
        workspace=root, index_path=index_path
    )
    path = Path(certificate_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise _fail(BLOCK_CANARY_INPUT_INVALID, "certificate_unsafe")
    resolved = path.resolve(strict=True)
    certificate = _load_object(resolved, label="certificate")
    identity = {
        "sha256": sha256_file(resolved),
        "receipt_id": certificate.get("receipt_id"),
        "closure_id": certificate.get("closure_id"),
    }
    for entry in index["certificates"]:
        if all(identity[key] == entry[key] for key in identity):
            return STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
    return None


def validate_canary_preflight(
    *,
    workspace: Path,
    metrics_path: Path,
    panel_path: Path,
    manifest_path: Path,
    org_validation_path: Path,
    org_private_root: Path,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    sample = validate_provisional_sample_bundle(
        metrics_path=metrics_path,
        panel_path=panel_path,
        manifest_path=manifest_path,
    )
    organization = replay_current_preformal_organization(
        workspace=workspace,
        org_validation_path=org_validation_path,
        org_private_root=org_private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        factor_id=str(sample["factor_id"]),
    )
    return {
        "status": "CANARY_SESSION_PREFLIGHT_COMPLETE",
        "sample": sample,
        "preformal_organization": organization,
        "formal_factor_verdict": "NOT_ISSUED",
        "production_eligible": False,
        "official_promotion_allowed": False,
    }


def dispatch_canary_sessions(_preflight: Mapping[str, Any]) -> None:
    """Fail until the trusted runtime owns a sealed post-execution prompt profile.

    The production adapter currently hard-wires the pre-formal Research Org
    prompt.  This script must not patch that function, invoke a local CLI, or
    self-sign an adapter/termination receipt.  Consequently no session and no
    certificate are created here.
    """

    raise CanaryClosureError(
        BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED
        + ":trusted_prompt_profile_and_generic_durable_session_api_missing"
    )


def run_canary_preflight_then_dispatch(
    *,
    workspace: Path,
    metrics_path: Path,
    panel_path: Path,
    manifest_path: Path,
    org_validation_path: Path,
    org_private_root: Path,
    trust_root: Path,
    installation_id: str,
) -> None:
    """Order the two read-only replays before the unavailable session API."""

    preflight = validate_canary_preflight(
        workspace=workspace,
        metrics_path=metrics_path,
        panel_path=panel_path,
        manifest_path=manifest_path,
        org_validation_path=org_validation_path,
        org_private_root=org_private_root,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    dispatch_canary_sessions(preflight)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Govern non-production small-batch closure evidence without "
            "granting a formal factor verdict."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Replay inputs and current organization, then fail closed at the "
            "missing trusted container prompt-profile API."
        ),
    )
    run_parser.add_argument("--workspace-root", required=True)
    run_parser.add_argument("--metrics", required=True)
    run_parser.add_argument("--panel", required=True)
    run_parser.add_argument("--pre-metric-manifest", required=True)
    run_parser.add_argument("--org-validation", required=True)
    run_parser.add_argument("--org-private-root", required=True)
    run_parser.add_argument("--trust-root", required=True)
    run_parser.add_argument("--installation-id", required=True)
    invalidate_parser = subparsers.add_parser(
        "invalidate-stale-legacy",
        help=(
            "Create the canonical negative-only index after current formal "
            "Research Org replay fails. Existing certificates are retained."
        ),
    )
    invalidate_parser.add_argument("--workspace-root", required=True)
    invalidate_parser.add_argument("--org-private-root", required=True)
    invalidate_parser.add_argument("--trust-root", required=True)
    invalidate_parser.add_argument("--installation-id", required=True)
    invalidate_parser.add_argument(
        "--legacy-certificate",
        action="append",
        default=[],
        help="Explicit legacy certificate path; repeat for each closed entry.",
    )
    invalidate_parser.add_argument(
        "--scan-canonical-legacy-root",
        action="store_true",
        help=(
            "Also scan only tmp/small_batch_canary_closure/"
            "small_batch_closure_*/canary_closure_certificate.json."
        ),
    )
    args = parser.parse_args()

    try:
        if args.command == "invalidate-stale-legacy":
            workspace = Path(args.workspace_root).expanduser().resolve(strict=True)
            certificates = [Path(item) for item in args.legacy_certificate]
            if args.scan_canonical_legacy_root:
                certificates.extend(
                    sorted(
                        (
                            workspace
                            / "tmp"
                            / "small_batch_canary_closure"
                        ).glob(
                            "small_batch_closure_*/canary_closure_certificate.json"
                        )
                    )
                )
            # Deduplicate only exact resolved paths; identity duplicates remain
            # a closed-index error rather than being silently collapsed.
            unique: dict[str, Path] = {}
            for candidate in certificates:
                unique[str(candidate.expanduser().resolve(strict=True))] = candidate
            result = materialize_stale_legacy_invalidation_index(
                workspace=workspace,
                org_private_root=Path(args.org_private_root),
                trust_root=Path(args.trust_root),
                installation_id=args.installation_id,
                certificate_paths=list(unique.values()),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            run_canary_preflight_then_dispatch(
                workspace=Path(args.workspace_root),
                metrics_path=Path(args.metrics),
                panel_path=Path(args.panel),
                manifest_path=Path(args.pre_metric_manifest),
                org_validation_path=Path(args.org_validation),
                org_private_root=Path(args.org_private_root),
                trust_root=Path(args.trust_root),
                installation_id=args.installation_id,
            )
    except (CanaryClosureError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
