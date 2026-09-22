from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import pandas as pd
import numpy as np

from factor_factory.evo_v2 import canonical_json_bytes, sha256_file, stable_json_hash


EVO_CHILD_EXECUTION_RESULT_VERSION = "factorforge_evo_child_execution_result_v1"
EVO_CHILD_EXECUTION_VERIFIER_ID = (
    "factorforge_evo_child_execution_result_verifier_v1"
)
EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION = (
    "factorforge_evo_child_execution_result_verifier_contract_v1"
)
EVO_TRANSFER_DIAGNOSTIC_CONTRACT_VERSION = (
    "factorforge_evo_transfer_diagnostic_contract_v1"
)
EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND = "EVO_TRANSFER_DIAGNOSTIC"
EVO_TRANSFER_DIAGNOSTIC_STATUS = "REGISTERED_DIAGNOSTIC_NOT_EVALUATED"
EVO_TRANSFER_EXECUTION_RESULT_STATUS = (
    "EXECUTED_DIAGNOSTIC_ONLY_HOST_REVIEW_REQUIRED"
)
BLOCK_EVO_CHILD_EXECUTION = "BLOCK_FACTORFORGE_EVO_CHILD_EXECUTION_INVALID"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,191}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FILES = (
    "factor_factory/evo_child_execution.py",
    "factor_factory/formula/parser.py",
    "factor_factory/formula/evaluator.py",
    "factor_factory/console/web_factor_proof.py",
)
_RESULT_AUTHORITY = {
    "diagnostic_only": True,
    "affects_acceptance": False,
    "expected_signature_adjudicated": False,
    "falsifier_adjudicated": False,
    "host_review_required": True,
    "factor_verdict": "NOT_ISSUED",
    "oos_accessed": False,
    "canonical_memory_write_allowed": False,
    "skill_or_policy_mutation_allowed": False,
}
_EVIDENCE_OBLIGATION_VERSION = "factorforge_evo_execution_evidence_obligation_v1"
_PANEL_PREDICATE_VERSION = "factorforge_evo_panel_predicate_v1"
_PANEL_BASE_COLUMNS = {
    "trade_date",
    "code",
    "future_return_1d",
    "label_start_date",
    "label_end_date",
    "label_start_price",
    "label_end_price",
}
_PREDICATE_METRICS = {
    "ROW_COUNT",
    "NON_NULL_COUNT",
    "NON_NULL_RATIO",
    "MEAN",
    "MEDIAN",
    "STD_POPULATION",
    "MIN",
    "MAX",
}
_COMPARATORS = {"GT", "GE", "LT", "LE", "EQ", "NE"}


class EvoChildExecutionError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(item) for item in reasons if str(item)))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_CHILD_EXECUTION}:{reason}"


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _within_without_symlinks(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _safe_parent(root: Path, path: Path) -> None:
    if not _within_without_symlinks(root, path):
        raise EvoChildExecutionError([_token(f"unsafe_output_path:{path.name}")])
    relative = path.parent.relative_to(root)
    current = root
    for part in relative.parts:
        candidate = current / part
        if candidate.exists() and (candidate.is_symlink() or not candidate.is_dir()):
            raise EvoChildExecutionError(
                [_token(f"unsafe_output_parent:{candidate.name}")]
            )
        if not candidate.exists():
            candidate.mkdir()
        current = candidate
    if not _within_without_symlinks(root, path):
        raise EvoChildExecutionError([_token(f"unsafe_output_path:{path.name}")])


def _load_object(path: Path, *, canonical: bool = False) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvoChildExecutionError([_token(f"missing_or_unsafe:{path.name}")])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildExecutionError([_token(f"invalid_json:{path.name}")]) from exc
    if not isinstance(payload, dict):
        raise EvoChildExecutionError([_token(f"object_required:{path.name}")])
    if canonical and path.read_bytes() != canonical_json_bytes(payload):
        raise EvoChildExecutionError([_token(f"noncanonical_json:{path.name}")])
    return payload


def _content_sha256(payload: Mapping[str, Any]) -> str:
    declared = payload.get("content_sha256")
    if declared is None:
        return stable_json_hash(dict(payload))
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not _is_sha256(declared) or declared != stable_json_hash(unsigned):
        raise EvoChildExecutionError([_token("content_sha256")])
    return str(declared)


def _object_ref(root: Path, path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    if not _within_without_symlinks(root, path):
        raise EvoChildExecutionError([_token(f"unsafe_ref:{path.name}")])
    resolved = path.resolve(strict=True)
    return {
        "path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "content_sha256": _content_sha256(payload),
    }


def _resolve_ref(
    root: Path,
    reference: Any,
    *,
    label: str,
    expected_path: Path | None = None,
) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    if not isinstance(reference, Mapping) or set(reference) not in (
        {"path", "sha256"},
        {"path", "sha256", "content_sha256"},
        {"path", "sha256", "semantic_sha256"},
    ):
        return None, None, [_token(f"{label}_ref_shape")]
    raw = reference.get("path")
    if (
        not isinstance(raw, str)
        or "\\" in raw
        or not _is_sha256(reference.get("sha256"))
    ):
        return None, None, [_token(f"{label}_ref_values")]
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        return None, None, [_token(f"{label}_ref_path")]
    path = root.joinpath(*relative.parts)
    if expected_path is not None and path.resolve(strict=False) != expected_path.resolve(
        strict=False
    ):
        return None, None, [_token(f"{label}_canonical_path")]
    if (
        not _within_without_symlinks(root, path)
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != reference.get("sha256")
    ):
        return None, None, [_token(f"{label}_readback")]
    try:
        payload = _load_object(path)
    except EvoChildExecutionError as exc:
        return None, None, exc.reasons
    if "content_sha256" in reference:
        try:
            observed = _content_sha256(payload)
        except EvoChildExecutionError as exc:
            return None, None, exc.reasons
        if observed != reference.get("content_sha256"):
            return None, None, [_token(f"{label}_content_sha256")]
    if "semantic_sha256" in reference and stable_json_hash(payload) != reference.get(
        "semantic_sha256"
    ):
        return None, None, [_token(f"{label}_semantic_sha256")]
    return path, payload, []


def verifier_source_bundle(
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    root = (
        Path(repository_root).expanduser().resolve(strict=True)
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    )
    refs: list[dict[str, str]] = []
    for relative in _SOURCE_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise EvoChildExecutionError([_token(f"verifier_source_missing:{relative}")])
        refs.append({"path": relative, "sha256": sha256_file(path)})
    core = {
        "verifier_id": EVO_CHILD_EXECUTION_VERIFIER_ID,
        "verifier_contract_version": EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION,
        "source_refs": refs,
    }
    return {**core, "source_bundle_sha256": stable_json_hash(core)}


def supported_evidence_obligation(
    payload: Mapping[str, Any],
    *,
    repository_root: Path | str | None = None,
) -> bool:
    try:
        bundle = verifier_source_bundle(repository_root)
    except (OSError, EvoChildExecutionError):
        return False
    predicate = payload.get("predicate")
    if not isinstance(predicate, Mapping) or set(predicate) != {
        "contract_version",
        "metric",
        "column",
        "comparator",
        "threshold",
        "min_observations",
    }:
        return False
    metric = predicate.get("metric")
    column = predicate.get("column")
    if (
        predicate.get("contract_version") != _PANEL_PREDICATE_VERSION
        or metric not in _PREDICATE_METRICS
        or predicate.get("comparator") not in _COMPARATORS
        or not isinstance(predicate.get("threshold"), (int, float))
        or isinstance(predicate.get("threshold"), bool)
        or not np.isfinite(float(predicate.get("threshold")))
        or not isinstance(predicate.get("min_observations"), int)
        or isinstance(predicate.get("min_observations"), bool)
        or int(predicate.get("min_observations")) < 1
        or (metric == "ROW_COUNT" and column is not None)
        or (
            metric != "ROW_COUNT"
            and (not isinstance(column, str) or not column.strip())
        )
    ):
        return False
    return (
        payload.get("contract_version") == _EVIDENCE_OBLIGATION_VERSION
        and
        payload.get("evidence_kind") == "VERIFIER_CONTRACT"
        and payload.get("artifact_contract")
        == EVO_CHILD_EXECUTION_RESULT_VERSION
        and payload.get("verifier_id") == EVO_CHILD_EXECUTION_VERIFIER_ID
        and payload.get("verifier_contract_version")
        == EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION
        and payload.get("verifier_source_bundle_sha256")
        == bundle["source_bundle_sha256"]
        and payload.get("input_role") == "EVO_PURGED_IS_PANEL"
        and payload.get("information_set") == "PURGED_IS_ONLY"
    )


def validate_evidence_obligation_contract(
    payload: Any,
    *,
    test_id: str,
    available_panel_columns: Sequence[str],
    repository_root: Path | str | None = None,
) -> list[str]:
    fields = {
        "contract_version",
        "test_id",
        "evidence_kind",
        "artifact_contract",
        "verifier_id",
        "verifier_contract_version",
        "verifier_source_bundle_sha256",
        "input_role",
        "predicate",
        "information_set",
        "status",
        "content_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        return ["evidence_obligation.fields"]
    reasons: list[str] = []
    if payload.get("test_id") != test_id:
        reasons.append("evidence_obligation.test_id")
    if not supported_evidence_obligation(payload, repository_root=repository_root):
        reasons.append("evidence_obligation.unsupported_verifier_contract")
    predicate = payload.get("predicate")
    if isinstance(predicate, Mapping):
        metric = predicate.get("metric")
        column = predicate.get("column")
        if metric != "ROW_COUNT" and column not in set(available_panel_columns):
            reasons.append("evidence_obligation.predicate.column")
    if payload.get("status") != "PREREGISTERED_AND_BOUND_NOT_EVALUATED":
        reasons.append("evidence_obligation.status")
    unsigned = dict(payload)
    declared = unsigned.pop("content_sha256", None)
    if declared != stable_json_hash(unsigned):
        reasons.append("evidence_obligation.content_sha256")
    return reasons


def execution_addendum_path(root: Path, parent_report_id: str) -> Path:
    return root / "objects" / "evo_v2" / parent_report_id / "execution_addendum.json"


def evo_child_execution_result_path(root: Path, child_report_id: str) -> Path:
    return (
        root
        / "runs"
        / child_report_id
        / f"evo_child_execution_result__{child_report_id}.json"
    )


def evo_child_execution_panel_path(root: Path, child_report_id: str) -> Path:
    return (
        root
        / "runs"
        / child_report_id
        / f"evo_child_purged_is_panel__{child_report_id}.parquet"
    )


def _addendum_ref(root: Path, parent_report_id: str, addendum: Mapping[str, Any]) -> dict[str, str]:
    return _object_ref(root, execution_addendum_path(root, parent_report_id), addendum)


def build_evo_child_execution_trial(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    execution_addendum: Mapping[str, Any],
    execution_test: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    test_id = execution_test.get("test_id")
    if not _safe_id(parent_report_id) or not _safe_id(child_report_id) or not _safe_id(
        test_id
    ):
        raise EvoChildExecutionError([_token("trial_identity")])
    addendum_ref = _addendum_ref(root, parent_report_id, execution_addendum)
    return {
        "trial_id": test_id,
        "trial_kind": EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND,
        "status": EVO_TRANSFER_DIAGNOSTIC_STATUS,
        "source_parent_report_id": parent_report_id,
        "source_child_report_id": child_report_id,
        "source_addendum_ref": addendum_ref,
        "source_addendum_content_sha256": execution_addendum.get("content_sha256"),
        "source_test_sha256": stable_json_hash(dict(execution_test)),
        "implementation_mode": execution_test.get("implementation_mode"),
        "execution_target": execution_test.get("execution_stage"),
        "information_set": execution_test.get("information_set"),
        "multiple_testing_family": execution_test.get("multiple_testing_family"),
        "affects_acceptance": False,
        "verifier_id": EVO_CHILD_EXECUTION_VERIFIER_ID,
        "verifier_contract_version": EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION,
        "verifier_source_bundle_sha256": verifier_source_bundle()[
            "source_bundle_sha256"
        ],
    }


def expected_evo_child_execution_trials(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    execution_addendum: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if execution_addendum is None:
        return []
    return [
        build_evo_child_execution_trial(
            workspace_root=workspace_root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            execution_addendum=execution_addendum,
            execution_test=item,
        )
        for item in execution_addendum.get("execution_tests") or []
        if isinstance(item, Mapping)
    ]


def validate_frozen_child_execution_ledger(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    search_trial_ledger: Mapping[str, Any],
    execution_addendum: Mapping[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if (
        search_trial_ledger.get("version") != "factorforge_search_trial_ledger_v1"
        or search_trial_ledger.get("search_status") != "FROZEN"
        or search_trial_ledger.get("report_id") != child_report_id
        or not isinstance(search_trial_ledger.get("trials"), list)
    ):
        return [_token("ledger_shape_or_identity")]
    trials = list(search_trial_ledger.get("trials") or [])
    if search_trial_ledger.get("trial_count") != len(trials):
        reasons.append(_token("ledger_trial_count"))
    if search_trial_ledger.get("trial_set_sha256") != stable_json_hash(trials):
        reasons.append(_token("ledger_trial_set_sha256"))
    try:
        expected = expected_evo_child_execution_trials(
            workspace_root=workspace_root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            execution_addendum=execution_addendum,
        )
    except (OSError, EvoChildExecutionError) as exc:
        return [
            *reasons,
            _token(
                "expected_trial_projection:"
                + (";".join(exc.reasons) if isinstance(exc, EvoChildExecutionError) else type(exc).__name__)
            ),
        ]
    observed = [
        item
        for item in trials
        if isinstance(item, Mapping)
        and item.get("trial_kind") == EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
    ]
    if observed != expected:
        reasons.append(_token("ledger_evo_trial_projection"))
    expected_ids = [item["trial_id"] for item in expected]
    if any(
        isinstance(item, Mapping)
        and item.get("trial_kind") != EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
        and item.get("trial_id") in expected_ids
        for item in trials
    ):
        reasons.append(_token("ledger_trial_id_collision"))
    all_ids = [item.get("trial_id") for item in trials if isinstance(item, Mapping)]
    if any(not _safe_id(value) for value in all_ids) or len(all_ids) != len(set(all_ids)):
        reasons.append(_token("ledger_trial_ids"))
    return list(dict.fromkeys(reasons))


def build_evo_transfer_diagnostic_contract(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    public_ticket: Mapping[str, Any],
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    if public_ticket.get("ticket_state") != "MATERIALIZATION_READY":
        raise EvoChildExecutionError([_token("ready_ticket_required")])
    bindings = public_ticket.get("bindings")
    controls = bindings.get("child_controls") if isinstance(bindings, Mapping) else None
    refs = controls.get("refs") if isinstance(controls, Mapping) else None
    if not isinstance(refs, Mapping):
        raise EvoChildExecutionError([_token("ticket_child_controls")])
    resolved: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name in ("search_trial_ledger", "threshold_registration"):
        path, payload, reasons = _resolve_ref(root, refs.get(name), label=name)
        if reasons or path is None or payload is None:
            raise EvoChildExecutionError(reasons or [_token(f"{name}_ref")])
        resolved[name] = (path, payload)
    ledger_path, ledger = resolved["search_trial_ledger"]
    threshold_path, threshold = resolved["threshold_registration"]
    addendum_ref = bindings.get("execution_addendum_ref")
    addendum: dict[str, Any] | None = None
    if public_ticket.get("memory_state") == "ADMISSIBLE_MEMORY_FOUND":
        path, payload, reasons = _resolve_ref(
            root,
            addendum_ref,
            label="execution_addendum",
            expected_path=execution_addendum_path(root, parent_report_id),
        )
        if reasons or path is None or payload is None:
            raise EvoChildExecutionError(reasons or [_token("execution_addendum_ref")])
        addendum = payload
    elif addendum_ref is not None:
        raise EvoChildExecutionError([_token("cold_addendum_forbidden")])
    ledger_reasons = validate_frozen_child_execution_ledger(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        search_trial_ledger=ledger,
        execution_addendum=addendum,
    )
    if ledger_reasons:
        raise EvoChildExecutionError(ledger_reasons)
    expected_ledger_ref = ledger_path.relative_to(root).as_posix()
    if (
        threshold.get("report_id") != child_report_id
        or threshold.get("search_trial_ledger_ref") != expected_ledger_ref
        or threshold.get("search_trial_ledger_sha256") != sha256_file(ledger_path)
    ):
        raise EvoChildExecutionError([_token("threshold_ledger_binding")])
    tests = list(addendum.get("execution_tests") or []) if addendum else []
    test_ids = [str(item.get("test_id") or "") for item in tests]
    ticket_path = (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_materialization_ticket__{child_report_id}__ready.json"
    )
    contract = {
        "contract_version": EVO_TRANSFER_DIAGNOSTIC_CONTRACT_VERSION,
        "state": (
            "BOUND_NOT_EVALUATED"
            if addendum is not None
            else "COLD_START_NO_TRANSFER_TESTS"
        ),
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "memory_state": public_ticket.get("memory_state"),
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
        "formal_transfer_use_orchestration_ref": dict(
            bindings["formal_transfer_use_orchestration_ref"]
        ),
        "execution_addendum_ref": dict(addendum_ref) if addendum_ref else None,
        "frozen_web_research_plan_ref": (
            dict(addendum["frozen_web_research_plan_ref"]) if addendum else None
        ),
        "ordered_test_ids": test_ids,
        "execution_tests_sha256": stable_json_hash(tests),
        "source_test_sha256s": [stable_json_hash(item) for item in tests],
        "search_trial_ledger_ref": dict(refs["search_trial_ledger"]),
        "threshold_registration_ref": dict(refs["threshold_registration"]),
        "parent_data_prep_ref": dict(bindings["parent_data_prep_ref"]),
        "frozen_daily_input_refs": {
            key: dict(value)
            for key, value in sorted(
                dict(bindings["frozen_daily_input_refs"]).items()
            )
        },
        "public_materialization_ticket_ref": _object_ref(
            root, ticket_path, public_ticket
        ),
        "result_contract_version": EVO_CHILD_EXECUTION_RESULT_VERSION,
        "result_verifier_id": EVO_CHILD_EXECUTION_VERIFIER_ID,
        "result_verifier_contract_version": (
            EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION
        ),
        "verifier_source_bundle": verifier_source_bundle(),
        "result_receipt_required": addendum is not None,
        "authority": {
            "diagnostic_only": True,
            "affects_acceptance": False,
            "factor_verdict": "NOT_ISSUED",
            "oos_access_allowed": False,
            "child_execution_authorized_by_contract": False,
            "canonical_memory_write_allowed": False,
        },
    }
    return {**contract, "contract_sha256": stable_json_hash(contract)}


def validate_evo_transfer_diagnostic_contract(
    payload: Any,
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> list[str]:
    if not isinstance(payload, Mapping):
        return [_token("diagnostic_contract_object")]
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
        from factor_factory.evo_child_materialization_ticket import (
            validate_public_child_materialization_ticket,
        )

        ticket, reasons = validate_public_child_materialization_ticket(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            require_materialization_ready=True,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        if ticket is None or reasons:
            return [
                _token(f"ready_ticket:{reason}") for reason in reasons
            ] or [_token("ready_ticket")]
        expected = build_evo_transfer_diagnostic_contract(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            public_ticket=ticket,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
    except (OSError, ValueError, KeyError, TypeError, EvoChildExecutionError) as exc:
        if isinstance(exc, EvoChildExecutionError):
            return exc.reasons
        return [_token(f"diagnostic_contract_replay:{type(exc).__name__}")]
    return [] if dict(payload) == expected else [_token("diagnostic_contract_projection")]


def _date_filters(date_type: Any, column: str, lower: str, upper: str) -> Any:
    import pyarrow as pa

    if pa.types.is_string(date_type) or pa.types.is_large_string(date_type):
        return [
            [(column, ">=", lower), (column, "<=", upper)],
            [
                (column, ">=", lower.replace("-", "")),
                (column, "<=", upper.replace("-", "")),
            ],
        ]
    if pa.types.is_integer(date_type):
        return [
            (column, ">=", int(lower.replace("-", ""))),
            (column, "<=", int(upper.replace("-", ""))),
        ]
    if pa.types.is_timestamp(date_type) or pa.types.is_date(date_type):
        return [(column, ">=", pd.Timestamp(lower)), (column, "<=", pd.Timestamp(upper))]
    raise EvoChildExecutionError([_token("unsupported_trade_date_storage")])


def _derive_purged_is_panel(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    addendum: Mapping[str, Any],
    diagnostic_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    import pyarrow.parquet as pq
    from factor_factory.console.web_factor_proof import (
        _evo_is_window_contract,
        _expected_label_dates,
        _trusted_calendar_snapshot,
    )

    plan_path, plan, reasons = _resolve_ref(
        root,
        addendum.get("frozen_web_research_plan_ref"),
        label="frozen_web_research_plan",
        expected_path=root / "identity" / "web_research_plan.json",
    )
    if reasons or plan_path is None or plan is None:
        raise EvoChildExecutionError(reasons or [_token("frozen_plan")])
    if (plan.get("identity") or {}).get("report_id") != parent_report_id:
        raise EvoChildExecutionError([_token("frozen_plan_parent_identity")])
    context_path = (
        root
        / "runs"
        / child_report_id
        / f"shared_evaluation_context__{child_report_id}.json"
    )
    context = _load_object(context_path)
    merged_raw = (context.get("paths") or {}).get(
        "evo_transfer_diagnostic_panel_parquet"
    )
    merged_path = Path(str(merged_raw or "")).expanduser()
    if not merged_path.is_absolute():
        merged_path = root / merged_path
    artifact = (context.get("artifacts") or {}).get(
        "evo_transfer_diagnostic_panel"
    ) or {}
    expected_hash = artifact.get("sha256") or artifact.get("file_sha256")
    if (
        not _within_without_symlinks(root, merged_path)
        or merged_path.is_symlink()
        or not merged_path.is_file()
        or not _is_sha256(expected_hash)
        or sha256_file(merged_path) != expected_hash
    ):
        raise EvoChildExecutionError([_token("shared_context_panel_binding")])
    formula_tests = [
        item
        for item in addendum.get("execution_tests") or []
        if isinstance(item, Mapping)
        and item.get("implementation_mode") == "FORMULA_DIAGNOSTIC"
    ]
    diagnostic_columns = [str(item["signal_column"]) for item in formula_tests]
    columns = [
        "trade_date",
        "code",
        "future_return_1d",
        "label_start_date",
        "label_end_date",
        "label_start_price",
        "label_end_price",
        *diagnostic_columns,
    ]
    schema = pq.ParquetFile(merged_path).schema_arrow
    missing = [column for column in columns if column not in schema.names]
    if missing:
        raise EvoChildExecutionError(
            [_token("shared_context_columns:" + ",".join(missing))]
        )
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    window, expected_dates = _evo_is_window_contract(
        plan, calendar_dates=list(calendar["dates"])
    )
    filters = _date_filters(
        schema.field("trade_date").type,
        "trade_date",
        expected_dates[0],
        expected_dates[-1],
    )
    frame = pd.read_parquet(merged_path, columns=columns, filters=filters)
    for column in ("trade_date", "label_start_date", "label_end_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
    frame = frame[frame["trade_date"].isin(expected_dates)].copy()
    base_columns = columns[:7]
    if frame.empty or frame[base_columns].isna().any(axis=None):
        raise EvoChildExecutionError([_token("purged_is_base_values")])
    if frame.duplicated(["trade_date", "code"]).any():
        raise EvoChildExecutionError([_token("purged_is_duplicate_keys")])

    # Never trust a diagnostic column merely because Step4 emitted a column
    # with the expected name.  Signal formulas and payoff labels may use two
    # distinct Host-frozen snapshots, so bind each typed role independently.
    frozen_daily_refs = diagnostic_contract.get("frozen_daily_input_refs")
    if not isinstance(frozen_daily_refs, Mapping):
        raise EvoChildExecutionError([_token("signed_daily_input_refs")])
    def typed_daily_snapshot(role: str) -> tuple[Path, dict[str, Any]]:
        raw_path = context.get(f"{role}_daily_input_path")
        raw_hash = context.get(f"{role}_daily_input_hash")
        path = Path(str(raw_path or "")).expanduser()
        if not path.is_absolute():
            path = root / path
        suffix = path.suffix.lower()
        preferred = (
            f"{role}_daily_df_parquet" if suffix == ".parquet" else
            f"{role}_daily_df_csv" if suffix == ".csv" else ""
        )
        fallback = "daily_df_parquet" if suffix == ".parquet" else "daily_df_csv"
        key = preferred if preferred in frozen_daily_refs else fallback
        signed = frozen_daily_refs.get(key)
        if (
            suffix not in {".parquet", ".csv"}
            or not _within_without_symlinks(root, path)
            or path.is_symlink()
            or not path.is_file()
            or not _is_sha256(raw_hash)
            or sha256_file(path) != raw_hash
            or not isinstance(signed, Mapping)
            or signed.get("sha256") != raw_hash
        ):
            raise EvoChildExecutionError([_token(f"frozen_{role}_daily_input_binding")])
        return path, dict(signed)

    evaluation_daily_path, signed_evaluation_ref = typed_daily_snapshot("evaluation")
    signal_daily_path, signed_signal_ref = typed_daily_snapshot("signal")
    evaluation_daily = (
        pd.read_parquet(evaluation_daily_path)
        if evaluation_daily_path.suffix.lower() == ".parquet"
        else pd.read_csv(evaluation_daily_path)
    )
    daily = (
        pd.read_parquet(signal_daily_path)
        if signal_daily_path.suffix.lower() == ".parquet"
        else pd.read_csv(signal_daily_path)
    )
    from factor_factory.formula.evaluator import evaluate_formula_frame
    from factor_factory.formula.parser import parse_formula

    daily = daily.copy()
    daily["trade_date"] = pd.to_datetime(
        daily["trade_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    if daily.duplicated(["ts_code", "trade_date"]).any():
        raise EvoChildExecutionError([_token("frozen_daily_duplicate_keys")])
    evaluation_daily = evaluation_daily.copy()
    evaluation_daily["trade_date"] = pd.to_datetime(
        evaluation_daily["trade_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    if evaluation_daily.duplicated(["ts_code", "trade_date"]).any():
        raise EvoChildExecutionError([_token("frozen_evaluation_daily_duplicate_keys")])
    expected_panel_keys = daily[
        daily["trade_date"].isin(expected_dates)
    ][["trade_date", "ts_code"]].rename(columns={"ts_code": "code"})
    expected_panel_keys = expected_panel_keys.merge(
        pd.DataFrame(
            [
                {
                    "trade_date": signal_date,
                    "label_start_date": label_dates[0],
                    "label_end_date": label_dates[1],
                }
                for signal_date, label_dates in _expected_label_dates(
                    list(calendar["dates"]), expected_dates
                ).items()
            ]
        ),
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    label_price_keys = evaluation_daily[["ts_code", "trade_date", "close"]].rename(
        columns={"ts_code": "code"}
    )
    eligible_expected_keys = expected_panel_keys.merge(
        label_price_keys.rename(
            columns={"trade_date": "label_start_date", "close": "__start"}
        ),
        on=["code", "label_start_date"],
        how="inner",
        validate="many_to_one",
    ).merge(
        label_price_keys.rename(
            columns={"trade_date": "label_end_date", "close": "__end"}
        ),
        on=["code", "label_end_date"],
        how="inner",
        validate="many_to_one",
    )[["trade_date", "code"]]
    observed_keys = frame[["trade_date", "code"]]
    if (
        len(observed_keys) != len(eligible_expected_keys)
        or not observed_keys.sort_values(["trade_date", "code"]).reset_index(drop=True).equals(
            eligible_expected_keys.sort_values(["trade_date", "code"]).reset_index(drop=True)
        )
    ):
        raise EvoChildExecutionError([_token("purged_is_instrument_date_coverage")])
    for test in formula_tests:
        signal_column = str(test["signal_column"])
        formula_ir = parse_formula(
            str(test["formula_or_law"]),
            available_columns=[str(column) for column in daily.columns],
        )
        if formula_ir.get("parse_status") != "success":
            raise EvoChildExecutionError(
                [_token(f"formula_reparse:{test.get('test_id')}")]
            )
        recomputed = evaluate_formula_frame(
            formula_ir,
            daily,
            engine="optimized",
        ).rename(
            columns={"ts_code": "code", "factor_value": "__expected_signal"}
        )
        recomputed["trade_date"] = pd.to_datetime(
            recomputed["trade_date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        recomputed = recomputed[
            recomputed["trade_date"].isin(expected_dates)
        ][["trade_date", "code", "__expected_signal"]]
        compared = frame[["trade_date", "code", signal_column]].merge(
            recomputed,
            on=["trade_date", "code"],
            how="left",
            validate="one_to_one",
        )
        observed_values = pd.to_numeric(compared[signal_column], errors="coerce")
        expected_values = pd.to_numeric(
            compared["__expected_signal"], errors="coerce"
        )
        if not np.allclose(
            observed_values.to_numpy(dtype=float),
            expected_values.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
        ):
            raise EvoChildExecutionError(
                [_token(f"formula_signal_recompute:{test.get('test_id')}")]
            )
    labels = _expected_label_dates(list(calendar["dates"]), expected_dates)
    expected_start = frame["trade_date"].map(
        lambda value: labels.get(value, (None, None))[0]
    )
    expected_end = frame["trade_date"].map(
        lambda value: labels.get(value, (None, None))[1]
    )
    if (
        (frame["label_start_date"] != expected_start)
        | (frame["label_end_date"] != expected_end)
    ).any():
        raise EvoChildExecutionError([_token("purged_is_label_calendar")])
    if (
        pd.to_datetime(frame["label_end_date"], utc=True)
        >= pd.Timestamp(window["oos_start"], tz="UTC")
    ).any():
        raise EvoChildExecutionError([_token("purged_is_oos_exposure")])
    calculated = (
        pd.to_numeric(frame["label_end_price"], errors="coerce")
        / pd.to_numeric(frame["label_start_price"], errors="coerce")
        - 1.0
    )
    observed = pd.to_numeric(frame["future_return_1d"], errors="coerce")
    error = (calculated - observed).abs()
    if error.isna().any() or float(error.max()) > 1e-12:
        raise EvoChildExecutionError([_token("purged_is_return_reconciliation")])
    daily_close = evaluation_daily[["ts_code", "trade_date", "close"]].copy().rename(
        columns={"ts_code": "code"}
    )
    daily_close["close"] = pd.to_numeric(daily_close["close"], errors="coerce")
    start_prices = daily_close.rename(
        columns={
            "trade_date": "label_start_date",
            "close": "__raw_label_start_price",
        }
    )
    end_prices = daily_close.rename(
        columns={
            "trade_date": "label_end_date",
            "close": "__raw_label_end_price",
        }
    )
    raw_reconciled = frame.merge(
        start_prices,
        on=["code", "label_start_date"],
        how="left",
        validate="many_to_one",
    ).merge(
        end_prices,
        on=["code", "label_end_date"],
        how="left",
        validate="many_to_one",
    )
    observed_start = pd.to_numeric(
        raw_reconciled["label_start_price"], errors="coerce"
    )
    observed_end = pd.to_numeric(
        raw_reconciled["label_end_price"], errors="coerce"
    )
    raw_start = pd.to_numeric(
        raw_reconciled["__raw_label_start_price"], errors="coerce"
    )
    raw_end = pd.to_numeric(
        raw_reconciled["__raw_label_end_price"], errors="coerce"
    )
    if (
        raw_start.isna().any()
        or raw_end.isna().any()
        or not np.allclose(
            observed_start.to_numpy(dtype=float),
            raw_start.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
            equal_nan=False,
        )
        or not np.allclose(
            observed_end.to_numpy(dtype=float),
            raw_end.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
            equal_nan=False,
        )
    ):
        raise EvoChildExecutionError([_token("purged_is_raw_close_reconciliation")])
    frame = frame.sort_values(["trade_date", "code"]).reset_index(drop=True)
    observed_dates = sorted(frame["trade_date"].unique().tolist())
    if any(value not in expected_dates for value in observed_dates):
        raise EvoChildExecutionError([_token("purged_is_date_membership")])
    source = {
        "shared_context_ref": _object_ref(root, context_path, context),
        "source_panel_ref": {
            "path": merged_path.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(merged_path),
        },
        "frozen_signal_daily_input_ref": {
            "path": signal_daily_path.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(signal_daily_path),
            "signed_parent_snapshot_ref": signed_signal_ref,
        },
        "frozen_evaluation_daily_input_ref": {
            "path": evaluation_daily_path.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(evaluation_daily_path),
            "signed_parent_snapshot_ref": signed_evaluation_ref,
        },
        "frozen_web_research_plan_ref": dict(
            addendum["frozen_web_research_plan_ref"]
        ),
    }
    coverage = {
        **window,
        "observed_signal_dates": observed_dates,
        "observed_signal_period_count": len(observed_dates),
        "coverage_ratio": len(observed_dates) / len(expected_dates),
        "coverage_status": (
            "COMPLETE"
            if observed_dates == expected_dates
            else "INCOMPLETE_HOST_REVIEW_REQUIRED"
        ),
        "return_reconciliation_max_abs_error": float(error.max()),
    }
    return frame, coverage, source


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) and result not in (float("inf"), float("-inf")) else None


def _formula_result(frame: pd.DataFrame, test: Mapping[str, Any]) -> dict[str, Any]:
    signal_column = str(test["signal_column"])
    values = pd.to_numeric(frame[signal_column], errors="coerce")
    returns = pd.to_numeric(frame["future_return_1d"], errors="coerce")
    daily_rank_ic: list[float] = []
    eligible_rows = 0
    eligible_dates = 0
    for _date, group in frame.assign(
        __signal=values, __return=returns
    ).groupby("trade_date", sort=True):
        eligible = group[["__signal", "__return"]].dropna()
        if len(eligible) < 3:
            continue
        eligible_rows += len(eligible)
        eligible_dates += 1
        if eligible["__signal"].nunique() < 2 or eligible["__return"].nunique() < 2:
            continue
        value = eligible["__signal"].rank().corr(eligible["__return"].rank())
        if pd.notna(value):
            daily_rank_ic.append(float(value))
    series = pd.Series(daily_rank_ic, dtype="float64")
    return {
        "row_count": int(len(frame)),
        "signal_non_null_count": int(values.notna().sum()),
        "signal_coverage_ratio": float(values.notna().mean()) if len(frame) else 0.0,
        "eligible_row_count": int(eligible_rows),
        "eligible_date_count": int(eligible_dates),
        "rank_ic_observation_count": int(len(daily_rank_ic)),
        "rank_ic_mean": _finite(series.mean()) if len(series) else None,
        "rank_ic_std_population": _finite(series.std(ddof=0)) if len(series) else None,
        "positive_rank_ic_fraction": (
            float((series > 0).mean()) if len(series) else None
        ),
    }


def _compare(observed: float, comparator: str, threshold: float) -> bool:
    if comparator == "GT":
        return observed > threshold
    if comparator == "GE":
        return observed >= threshold
    if comparator == "LT":
        return observed < threshold
    if comparator == "LE":
        return observed <= threshold
    if comparator == "EQ":
        return observed == threshold
    if comparator == "NE":
        return observed != threshold
    raise EvoChildExecutionError([_token("predicate_comparator")])


def _execute_panel_predicate(
    frame: pd.DataFrame,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    predicate = payload["predicate"]
    metric = str(predicate["metric"])
    column = predicate.get("column")
    if metric == "ROW_COUNT":
        observation_count = len(frame)
        observed = float(len(frame))
    else:
        values = pd.to_numeric(frame[str(column)], errors="coerce").dropna()
        observation_count = len(values)
        if metric == "NON_NULL_COUNT":
            observed = float(len(values))
        elif metric == "NON_NULL_RATIO":
            observed = float(len(values) / len(frame)) if len(frame) else 0.0
        elif metric == "MEAN":
            observed = float(values.mean()) if len(values) else float("nan")
        elif metric == "MEDIAN":
            observed = float(values.median()) if len(values) else float("nan")
        elif metric == "STD_POPULATION":
            observed = float(values.std(ddof=0)) if len(values) else float("nan")
        elif metric == "MIN":
            observed = float(values.min()) if len(values) else float("nan")
        elif metric == "MAX":
            observed = float(values.max()) if len(values) else float("nan")
        else:
            raise EvoChildExecutionError([_token("predicate_metric")])
    minimum = int(predicate["min_observations"])
    if observation_count < minimum or not np.isfinite(observed):
        raise EvoChildExecutionError([_token("predicate_insufficient_observations")])
    threshold = float(predicate["threshold"])
    return {
        "predicate_contract": dict(predicate),
        "observation_count": int(observation_count),
        "observed_value": observed,
        "predicate_comparison_result": _compare(
            observed, str(predicate["comparator"]), threshold
        ),
        "interpretation": "HOST_REVIEW_REQUIRED_NOT_AUTOMATIC_EVIDENCE_JUDGMENT",
    }


def _test_results(
    *,
    root: Path,
    frame: pd.DataFrame,
    addendum: Mapping[str, Any],
) -> list[dict[str, Any]]:
    bundle = verifier_source_bundle()
    results: list[dict[str, Any]] = []
    required_refs = addendum.get("required_evidence_refs") or {}
    for test in addendum.get("execution_tests") or []:
        mode = test.get("implementation_mode")
        evidence: dict[str, dict[str, Any]] = {}
        evidence_payloads: list[dict[str, Any]] = []
        available_columns = [str(column) for column in frame.columns]
        for key in test.get("required_evidence") or []:
            reference = required_refs.get(key)
            path, payload, reasons = _resolve_ref(
                root,
                reference,
                label=f"required_evidence:{test.get('test_id')}",
                expected_path=root / key,
            )
            if reasons or path is None or payload is None:
                raise EvoChildExecutionError(reasons or [_token("required_evidence")])
            obligation_reasons = validate_evidence_obligation_contract(
                payload,
                test_id=str(test.get("test_id") or ""),
                available_panel_columns=available_columns,
            )
            if obligation_reasons:
                raise EvoChildExecutionError(
                    [_token(reason) for reason in obligation_reasons]
                )
            evidence[key] = dict(reference)
            evidence_payloads.append(payload)
        if mode == "FORMULA_DIAGNOSTIC":
            observed = _formula_result(frame, test)
            observed["required_evidence_predicate_results"] = [
                _execute_panel_predicate(frame, payload)
                for payload in evidence_payloads
            ]
            if (
                observed["eligible_date_count"] < 3
                or observed["rank_ic_observation_count"] < 3
                or observed["signal_non_null_count"] < 9
            ):
                raise EvoChildExecutionError(
                    [_token(f"formula_insufficient_coverage:{test.get('test_id')}")]
                )
            status = "FORMULA_DIAGNOSTIC_EXECUTED_HOST_REVIEW_REQUIRED"
        else:
            observed = {
                "bound_evidence_count": len(evidence),
                "bound_evidence_refs_sha256": stable_json_hash(evidence),
                "predicate_results": [
                    _execute_panel_predicate(frame, payload)
                    for payload in evidence_payloads
                ],
            }
            status = "TYPED_EVIDENCE_PREDICATE_EXECUTED_HOST_REVIEW_REQUIRED"
        results.append(
            {
                "test_id": test.get("test_id"),
                "source_test_sha256": stable_json_hash(test),
                "implementation_mode": mode,
                "formula_or_law": test.get("formula_or_law"),
                "formula_ir_sha256": (
                    stable_json_hash(test.get("formula_or_law"))
                    if mode == "FORMULA_DIAGNOSTIC"
                    else None
                ),
                "signal_column": test.get("signal_column"),
                "verifier_id": EVO_CHILD_EXECUTION_VERIFIER_ID,
                "verifier_contract_version": (
                    EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION
                ),
                "verifier_source_bundle_sha256": bundle["source_bundle_sha256"],
                "required_evidence_refs": evidence,
                "observed_metrics": observed,
                "expected_signature": test.get("expected_signature"),
                "falsifier": test.get("falsifier"),
                "adjudication": "HOST_REVIEW_REQUIRED_NOT_AUTOMATICALLY_INFERRED",
                "execution_status": status,
            }
        )
    return results


def _result_payload(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    diagnostic_contract: Mapping[str, Any],
    addendum: Mapping[str, Any],
    panel_path: Path,
    frame: pd.DataFrame,
    window: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    if window.get("coverage_status") != "COMPLETE":
        raise EvoChildExecutionError([_token("purged_is_incomplete_coverage")])
    test_results = _test_results(root=root, frame=frame, addendum=addendum)
    core = {
        "contract_version": EVO_CHILD_EXECUTION_RESULT_VERSION,
        "verifier_id": EVO_CHILD_EXECUTION_VERIFIER_ID,
        "verifier_contract_version": EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "diagnostic_contract_sha256": diagnostic_contract.get("contract_sha256"),
        "diagnostic_contract": dict(diagnostic_contract),
        "execution_addendum_ref": dict(
            diagnostic_contract["execution_addendum_ref"]
        ),
        "search_trial_ledger_ref": dict(
            diagnostic_contract["search_trial_ledger_ref"]
        ),
        "threshold_registration_ref": dict(
            diagnostic_contract["threshold_registration_ref"]
        ),
        "source": dict(source),
        "purged_is_panel_ref": {
            "path": panel_path.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(panel_path),
        },
        "window_contract": dict(window),
        "test_results": test_results,
        "ordered_test_ids": [item["test_id"] for item in test_results],
        "all_preregistered_tests_accounted": (
            [item["test_id"] for item in test_results]
            == list(diagnostic_contract.get("ordered_test_ids") or [])
        ),
        "execution_completed": True,
        "result_semantics": (
            "REGISTERED_DIAGNOSTICS_EXECUTED_WITHOUT_AUTOMATIC_MECHANISM_OR_FACTOR_JUDGMENT"
        ),
        "authority": dict(_RESULT_AUTHORITY),
        "status": EVO_TRANSFER_EXECUTION_RESULT_STATUS,
    }
    return {**core, "content_sha256": stable_json_hash(core)}


def _atomic_json_once(root: Path, path: Path, payload: Mapping[str, Any]) -> bool:
    expected = canonical_json_bytes(payload)
    _safe_parent(root, path)
    if path.is_file():
        if path.read_bytes() != expected:
            raise EvoChildExecutionError([_token(f"immutable_conflict:{path.name}")])
        return True
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("atomic_write_no_progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if not path.is_file() or path.read_bytes() != expected:
                raise EvoChildExecutionError([_token(f"immutable_conflict:{path.name}")])
            return True
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _atomic_panel_once(root: Path, path: Path, frame: pd.DataFrame) -> bool:
    _safe_parent(root, path)
    if path.is_file():
        observed = pd.read_parquet(path)
        if not observed.equals(frame):
            raise EvoChildExecutionError([_token(f"immutable_conflict:{path.name}")])
        return True
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_parquet(temporary, index=False)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            observed = pd.read_parquet(path)
            if not observed.equals(frame):
                raise EvoChildExecutionError([_token(f"immutable_conflict:{path.name}")])
            return True
        return False
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _execution_lock(root: Path, child_report_id: str) -> Iterator[None]:
    path = evo_child_execution_result_path(root, child_report_id).with_suffix(".lock")
    _safe_parent(root, path)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise EvoChildExecutionError([_token("execution_lock")])
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def materialize_evo_child_execution_result(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    diagnostic_contract: Mapping[str, Any],
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    reasons = validate_evo_transfer_diagnostic_contract(
        diagnostic_contract,
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    if reasons:
        raise EvoChildExecutionError(reasons)
    if diagnostic_contract.get("result_receipt_required") is not True:
        return {
            "verdict": "PASS",
            "status": "COLD_START_NO_TRANSFER_TESTS",
            "execution_completed": False,
            "factor_verdict": "NOT_ISSUED",
        }
    addendum_path = execution_addendum_path(root, parent_report_id)
    addendum = _load_object(addendum_path, canonical=True)
    with _execution_lock(root, child_report_id):
        frame, window, source = _derive_purged_is_panel(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            addendum=addendum,
            diagnostic_contract=diagnostic_contract,
        )
        panel_path = evo_child_execution_panel_path(root, child_report_id)
        panel_replayed = _atomic_panel_once(root, panel_path, frame)
        payload = _result_payload(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            diagnostic_contract=diagnostic_contract,
            addendum=addendum,
            panel_path=panel_path,
            frame=frame,
            window=window,
            source=source,
        )
        result_path = evo_child_execution_result_path(root, child_report_id)
        result_replayed = _atomic_json_once(root, result_path, payload)
        validation = validate_evo_child_execution_result(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            diagnostic_contract=diagnostic_contract,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        if validation:
            raise EvoChildExecutionError(validation)
        return {
            "verdict": "PASS",
            "status": payload["status"],
            "execution_completed": True,
            "factor_verdict": "NOT_ISSUED",
            "result_ref": _object_ref(root, result_path, payload),
            "panel_ref": payload["purged_is_panel_ref"],
            "idempotent_replay": panel_replayed and result_replayed,
        }


def validate_evo_child_execution_result(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    diagnostic_contract: Mapping[str, Any],
    expected_host_trust_manifest_sha256: str,
) -> list[str]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    reasons = validate_evo_transfer_diagnostic_contract(
        diagnostic_contract,
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    if reasons or diagnostic_contract.get("result_receipt_required") is not True:
        return reasons
    result_path = evo_child_execution_result_path(root, child_report_id)
    panel_path = evo_child_execution_panel_path(root, child_report_id)
    try:
        payload = _load_object(result_path, canonical=True)
        observed_panel = pd.read_parquet(panel_path)
        addendum = _load_object(execution_addendum_path(root, parent_report_id), canonical=True)
        expected_panel, window, source = _derive_purged_is_panel(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            addendum=addendum,
            diagnostic_contract=diagnostic_contract,
        )
    except (OSError, ValueError, KeyError, TypeError, EvoChildExecutionError) as exc:
        if isinstance(exc, EvoChildExecutionError):
            return exc.reasons
        return [_token(f"result_readback:{type(exc).__name__}")]
    if not observed_panel.equals(expected_panel):
        reasons.append(_token("purged_is_panel_recompute"))
    expected = _result_payload(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        diagnostic_contract=diagnostic_contract,
        addendum=addendum,
        panel_path=panel_path,
        frame=expected_panel,
        window=window,
        source=source,
    )
    if payload != expected:
        reasons.append(_token("result_exact_recompute"))
    if payload.get("authority") != _RESULT_AUTHORITY:
        reasons.append(_token("result_authority"))
    if payload.get("ordered_test_ids") != diagnostic_contract.get("ordered_test_ids"):
        reasons.append(_token("result_test_accounting"))
    return list(dict.fromkeys(reasons))


def validate_evo_child_execution_gate(
    *,
    workspace_root: Path | str,
    report_id: str,
    factor_run_master: Mapping[str, Any],
    expected_host_trust_manifest_sha256: str | None,
) -> list[str]:
    """Replay the optional EVO diagnostic receipt at every downstream gate.

    Legacy/non-EVO runs carry neither field and remain unchanged.  Once either
    projection appears, both the exact contract and the Step4 execution summary
    become mandatory and the externally pinned Host trust digest is required.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    marker_payloads: list[tuple[str, Mapping[str, Any]]] = [
        ("factor_run_master", factor_run_master),
    ]
    canonical_paths = (
        (
            "factor_spec_master",
            root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        ),
        (
            "handoff_to_step4",
            root / "objects" / "handoff" / f"handoff_to_step4__{report_id}.json",
        ),
        (
            "handoff_to_step5",
            root / "objects" / "handoff" / f"handoff_to_step5__{report_id}.json",
        ),
    )
    for label, path in canonical_paths:
        if path.is_file() and not path.is_symlink():
            try:
                marker_payloads.append((label, _load_object(path)))
            except EvoChildExecutionError as exc:
                return exc.reasons
    contracts = [
        (label, payload.get("evo_transfer_diagnostic_contract"))
        for label, payload in marker_payloads
        if payload.get("evo_transfer_diagnostic_contract") is not None
    ]
    summary = factor_run_master.get("evo_child_execution")
    ready_ticket = (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_materialization_ticket__{report_id}__ready.json"
    )
    authorization_ticket = ready_ticket.with_name(
        f"evo_child_materialization_ticket__{report_id}__authorization.json"
    )
    child_intent = (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_intent__{report_id}.json"
    )
    executable_spec = (
        root
        / "objects"
        / "research_iteration_master"
        / f"executable_revision_spec__{report_id}.json"
    )
    materialization_reports: list[Path] = []
    for path in (root / "objects" / "runtime_context").glob(
        "child_revision_materialization__*.json"
    ):
        if path.is_file() and not path.is_symlink():
            try:
                payload = _load_object(path)
            except EvoChildExecutionError as exc:
                return exc.reasons
            if payload.get("child_report_id") == report_id:
                materialization_reports.append(path)
    payload_child_markers = any(
        payload.get("parent_report_id") is not None
        or payload.get("revision_identity") is not None
        or payload.get("executable_revision_spec_ref") is not None
        for _label, payload in marker_payloads
    )
    durable_child_markers = any(
        path.exists() or path.is_symlink()
        for path in (ready_ticket, authorization_ticket, child_intent, executable_spec)
    ) or bool(materialization_reports)
    if (
        not contracts
        and summary is None
        and not durable_child_markers
        and not payload_child_markers
    ):
        return []
    if len(contracts) != len(marker_payloads):
        return [_token("downstream_canonical_contract_missing")]
    contract = contracts[0][1] if contracts else None
    if any(value != contract for _label, value in contracts[1:]):
        return [_token("downstream_canonical_contract_projection")]
    if not isinstance(contract, Mapping) or not isinstance(summary, Mapping):
        return [_token("downstream_contract_or_summary_missing")]
    if not _is_sha256(expected_host_trust_manifest_sha256):
        return [_token("downstream_external_host_trust_pin_required")]
    parent_report_id = str(contract.get("parent_report_id") or "")
    reasons = validate_evo_transfer_diagnostic_contract(
        contract,
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=report_id,
        expected_host_trust_manifest_sha256=str(
            expected_host_trust_manifest_sha256
        ),
    )
    required = contract.get("result_receipt_required") is True
    if required:
        reasons.extend(
            validate_evo_child_execution_result(
                workspace_root=workspace_root,
                parent_report_id=parent_report_id,
                child_report_id=report_id,
                diagnostic_contract=contract,
                expected_host_trust_manifest_sha256=str(
                    expected_host_trust_manifest_sha256
                ),
            )
        )
        result_path = evo_child_execution_result_path(root, report_id)
        try:
            result_payload = _load_object(result_path, canonical=True)
            expected_ref = _object_ref(root, result_path, result_payload)
        except (OSError, ValueError, EvoChildExecutionError) as exc:
            if isinstance(exc, EvoChildExecutionError):
                reasons.extend(exc.reasons)
            else:
                reasons.append(_token(f"downstream_result_readback:{type(exc).__name__}"))
        else:
            if (
                summary.get("verdict") != "PASS"
                or summary.get("status") != EVO_TRANSFER_EXECUTION_RESULT_STATUS
                or summary.get("execution_completed") is not True
                or summary.get("factor_verdict") != "NOT_ISSUED"
                or summary.get("result_ref") != expected_ref
            ):
                reasons.append(_token("downstream_execution_summary"))
    else:
        expected_cold_summary = {
            "verdict": "PASS",
            "status": "COLD_START_NO_TRANSFER_TESTS",
            "execution_completed": False,
            "factor_verdict": "NOT_ISSUED",
        }
        if dict(summary) != expected_cold_summary:
            reasons.append(_token("downstream_cold_summary"))
    return list(dict.fromkeys(reasons))


__all__ = [
    "BLOCK_EVO_CHILD_EXECUTION",
    "EVO_CHILD_EXECUTION_RESULT_VERSION",
    "EVO_CHILD_EXECUTION_VERIFIER_CONTRACT_VERSION",
    "EVO_CHILD_EXECUTION_VERIFIER_ID",
    "EVO_TRANSFER_DIAGNOSTIC_CONTRACT_VERSION",
    "EVO_TRANSFER_DIAGNOSTIC_STATUS",
    "EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND",
    "EvoChildExecutionError",
    "build_evo_child_execution_trial",
    "build_evo_transfer_diagnostic_contract",
    "evo_child_execution_panel_path",
    "evo_child_execution_result_path",
    "expected_evo_child_execution_trials",
    "materialize_evo_child_execution_result",
    "supported_evidence_obligation",
    "validate_evidence_obligation_contract",
    "validate_evo_child_execution_result",
    "validate_evo_child_execution_gate",
    "validate_evo_transfer_diagnostic_contract",
    "validate_frozen_child_execution_ledger",
    "verifier_source_bundle",
]
