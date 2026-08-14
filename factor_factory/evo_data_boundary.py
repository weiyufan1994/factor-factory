from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import stat
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.formula.semantics import (
    max_formula_ir_lookback,
    requires_cross_sectional_sample,
)
from factor_factory.research_org.contracts import (
    ResearchOrganizationError,
    read_workspace_bytes,
    strict_json_loads,
)


BLOCK_EVO_DATA_BOUNDARY = (
    "BLOCK_FACTORFORGE_EVO_PRE_RELEASE_DATA_BOUNDARY_INVALID"
)
BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING = (
    "BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING"
)
BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID = (
    "BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID"
)
CLOSED_DATA_API_RESOLUTION_VERSION = (
    "factorforge_step3a_closed_sample_data_resolution_v1"
)
ALLOWED_PRE_RELEASE_DAILY_DATASETS = frozenset(
    {"clean_daily_bar", "daily_basic", "moneyflow"}
)
FORBIDDEN_PRE_RELEASE_LOCAL_INPUTS = frozenset(
    {
        "minute_df_parquet",
        "minute_df_csv",
        "minute_streaming_query",
        "minute_input_meta_json",
        "state_df_parquet",
        "state_df_csv",
    }
)
PRE_RELEASE_DAILY_PATH_KEYS = (
    "daily_df_parquet",
    "daily_df_csv",
    "daily_df_csv_sample",
    "evaluation_daily_df_parquet",
    "evaluation_daily_df_csv",
    "signal_daily_df_parquet",
    "signal_daily_df_csv",
)
_AGENT_EXECUTION_ISOLATION_ACTIVE = False
_FORBIDDEN_EVIDENCE_FIELD_TOKENS = (
    "outcome",
    "label",
    "target",
    "forward",
)
_CLEAN_DAILY_BASE_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "pct_chg",
]
_CLEAN_DAILY_DERIVED_FIELDS = {"volume", "returns", "return", "ret", "vwap"}
_MONEYFLOW_SIGNAL_FIELDS = {
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
    "net_mf_amount",
}


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def canonical_clean_daily_query_fields(
    required_fields: list[str] | None,
    formula_ir: Mapping[str, Any] | None,
) -> list[str]:
    """Canonical physical clean-daily fields shared by Step3 producer/replay."""

    formula = formula_ir if isinstance(formula_ir, Mapping) else {}
    resolved = (
        formula.get("resolved_fields")
        if isinstance(formula.get("resolved_fields"), Mapping)
        else {}
    )
    fields = list(_CLEAN_DAILY_BASE_FIELDS)
    for candidate in required_fields or []:
        logical = str(candidate).strip().lower()
        if not logical:
            continue
        field = str(resolved.get(logical) or logical).strip().lower()
        if (
            field in _CLEAN_DAILY_DERIVED_FIELDS
            or re.fullmatch(r"adv\d+", field)
            or field in _MONEYFLOW_SIGNAL_FIELDS
            or field in {"ts_code", "trade_date"}
        ):
            continue
        if field not in fields:
            fields.append(field)
    return fields


def _formula_required_daily_fields(fsm: Mapping[str, Any]) -> list[str]:
    canonical = (
        fsm.get("canonical_spec")
        if isinstance(fsm.get("canonical_spec"), Mapping)
        else {}
    )
    formula_ir = (
        canonical.get("formula_ir")
        if isinstance(canonical.get("formula_ir"), Mapping)
        else {}
    )
    implementation = (
        fsm.get("implementation_contract")
        if isinstance(fsm.get("implementation_contract"), Mapping)
        else {}
    )
    code_contract = (
        implementation.get("code_contract")
        if isinstance(implementation.get("code_contract"), Mapping)
        else {}
    )
    candidates = (
        list(formula_ir.get("required_fields") or [])
        + list(canonical.get("required_inputs") or [])
        + list(code_contract.get("required_fields") or [])
        + list(implementation.get("required_fields") or [])
        + list(fsm.get("required_inputs") or [])
    )
    return list(
        dict.fromkeys(
            str(field).strip().lower()
            for field in candidates
            if str(field).strip()
        )
    )


def canonical_step3_sample_query(
    *,
    fsm: Mapping[str, Any],
    research_windows: Mapping[str, Any],
) -> dict[str, Any]:
    """Replay the exact bounded clean-daily query selected by Step3A."""

    canonical = (
        fsm.get("canonical_spec")
        if isinstance(fsm.get("canonical_spec"), Mapping)
        else {}
    )
    formula_ir = (
        canonical.get("formula_ir")
        if isinstance(canonical.get("formula_ir"), Mapping)
        else {}
    )
    evaluation = (
        fsm.get("evaluation_contract")
        if isinstance(fsm.get("evaluation_contract"), Mapping)
        else {}
    )
    controls = [
        str(field).strip().lower()
        for field in (evaluation.get("proof_control_columns") or [])
        if str(field).strip()
    ]
    logical_fields = [*_formula_required_daily_fields(fsm), *controls]
    _assert_non_outcome_fields(
        logical_fields, label="canonical_step3_sample_query.logical"
    )
    fields = canonical_clean_daily_query_fields(
        logical_fields,
        formula_ir,
    )
    _assert_non_outcome_fields(
        fields, label="canonical_step3_sample_query.physical"
    )
    max_lookback = max_formula_ir_lookback(dict(formula_ir))
    calendar_days = (
        220
        if max_lookback <= 0
        else max(220, min(int(max_lookback * 1.7) + 60, 900))
    )
    start = datetime.strptime(
        compact_date(research_windows.get("is_start")), "%Y%m%d"
    )
    frozen_end = datetime.strptime(
        compact_date(research_windows.get("is_end")), "%Y%m%d"
    )
    end = min(frozen_end, start + timedelta(days=calendar_days))
    return {
        "dataset": "clean_daily_bar",
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "universe": (
            "a_share_all"
            if requires_cross_sectional_sample(dict(formula_ir))
            else ["000001.SZ", "000002.SZ"]
        ),
        "fields": fields,
        "frequency": "daily",
    }


def _evidence_missing(label: str) -> ValueError:
    return ValueError(f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:{label}")


def _evidence_invalid(label: str) -> ValueError:
    return ValueError(f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID}:{label}")


def _read_stable_regular_json_for_evidence(
    path: Path, *, label: str
) -> tuple[dict[str, Any], str]:
    """Stable Host read for a frozen JSON file outside the workspace."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _evidence_missing(label) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > 64 * 1024 * 1024
        ):
            raise _evidence_invalid(f"{label}.unsafe_file")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        path_after = os.stat(path, follow_symlinks=False)
        identities = {
            (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            for item in (before, after, path_after)
        }
        if len(identities) != 1 or len(raw) != before.st_size:
            raise _evidence_invalid(f"{label}.unstable_read")
        payload = strict_json_loads(raw, label=label)
    except (OSError, ResearchOrganizationError) as exc:
        raise _evidence_invalid(label) from exc
    finally:
        os.close(descriptor)
    if not isinstance(payload, dict):
        raise _evidence_invalid(label)
    return payload, hashlib.sha256(raw).hexdigest()


def _read_workspace_json_for_evidence(
    workspace: Path,
    relative: str,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        raw = read_workspace_bytes(workspace, relative)
        payload = strict_json_loads(raw, label=label)
    except (OSError, ResearchOrganizationError) as exc:
        raise _evidence_invalid(label) from exc
    if not isinstance(payload, dict):
        raise _evidence_invalid(label)
    return payload, hashlib.sha256(raw).hexdigest()


def _deny_sensitive_projection(value: Any, *, key: str = "") -> None:
    lowered_key = key.lower()
    harmless_contract_paths = {
        "performance_path",
        "audit_path",
        "csv_path",
        "csv_sample_path",
    }
    if any(
        token in lowered_key
        for token in (
            "path",
            "uri",
            "credential",
            "secret",
            "token",
            "password",
            "outcome",
            "label",
            "target",
            "forward",
        )
    ) and lowered_key not in harmless_contract_paths:
        raise _evidence_invalid(f"projection.forbidden_key.{key}")
    if isinstance(value, Mapping):
        for item_key, item_value in value.items():
            _deny_sensitive_projection(item_value, key=str(item_key))
    elif isinstance(value, list):
        for item in value:
            _deny_sensitive_projection(item, key=key)
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            "://" in lowered
            or "amazonaws.com" in lowered
            or lowered.startswith("/")
            or "aws_access_key" in lowered
            or "aws_session_token" in lowered
        ):
            raise _evidence_invalid("projection.forbidden_value")


def _assert_non_outcome_fields(fields: list[str], *, label: str) -> None:
    forbidden = sorted(
        field
        for field in fields
        if any(
            token in field.strip().lower()
            for token in _FORBIDDEN_EVIDENCE_FIELD_TOKENS
        )
    )
    if forbidden:
        raise _evidence_invalid(f"{label}.forbidden_fields")


def _catalog_entries(payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw = payload.get("datasets", payload)
    if isinstance(raw, Mapping):
        return [
            (str(name), dict(item))
            for name, item in raw.items()
            if isinstance(item, Mapping)
        ]
    if isinstance(raw, list):
        return [
            (str(item.get("dataset_id") or ""), dict(item))
            for item in raw
            if isinstance(item, Mapping) and item.get("dataset_id")
        ]
    return []


def _catalog_item(
    payload: Mapping[str, Any], dataset_id: str, *, label: str
) -> dict[str, Any]:
    matches = [item for name, item in _catalog_entries(payload) if name == dataset_id]
    if len(matches) != 1:
        raise _evidence_missing(label)
    return matches[0]


def _closed_catalog_binding(
    *,
    factorforge_root: Path,
    catalog_path: Path,
    dataset_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    summary, summary_sha256 = _read_workspace_json_for_evidence(
        factorforge_root,
        "identity/data_catalog_summary.json",
        label="catalog_summary",
    )
    if summary.get("version") != "factorforge_web_data_catalog_summary_v2":
        raise _evidence_invalid("catalog_summary.version")
    if not catalog_path.is_file() or catalog_path.is_symlink():
        raise _evidence_missing("approved_catalog")
    catalog_payload, catalog_sha256 = _read_stable_regular_json_for_evidence(
        catalog_path, label="approved_catalog"
    )
    catalog_entry = _catalog_item(
        catalog_payload,
        dataset_id,
        label=f"approved_catalog.{dataset_id}",
    )
    if catalog_entry.get("status", "ready") != "ready":
        raise _evidence_missing(f"approved_catalog.{dataset_id}.status")
    matching_summaries = [
        item
        for item in (summary.get("catalogs") or [])
        if isinstance(item, dict)
        and item.get("catalog_sha256") == catalog_sha256
    ]
    if len(matching_summaries) != 1:
        raise _evidence_invalid("catalog_summary.catalog_sha256")
    summary_entries = [
        item
        for item in (matching_summaries[0].get("entries") or [])
        if isinstance(item, dict) and item.get("name") == dataset_id
    ]
    if len(summary_entries) != 1:
        raise _evidence_missing(f"catalog_summary.{dataset_id}")
    summary_entry = summary_entries[0]
    if summary_entry.get("catalog_membership") != "active_catalog_member":
        raise _evidence_invalid(f"catalog_summary.{dataset_id}.membership")
    admission = summary.get("active_catalog_admission")
    if (
        not isinstance(admission, dict)
        or admission.get("verdict") != "PASS"
        or admission.get("catalog_sha256") != catalog_sha256
    ):
        raise _evidence_invalid("catalog_summary.active_catalog_admission")
    pit = summary_entry.get("host_information_policy_attestation")
    if (
        not isinstance(pit, dict)
        or pit.get("version")
        != "factorforge_host_information_policy_attestation_v1"
        or pit.get("verdict") != "PASS"
        or pit.get("future_observations_excluded") is not True
    ):
        raise _evidence_missing(f"catalog_summary.{dataset_id}.pit")
    metadata = (
        catalog_entry.get("metadata")
        if isinstance(catalog_entry.get("metadata"), dict)
        else {}
    )
    policy = (
        catalog_entry.get("daily_filter_policy")
        or catalog_entry.get("policy")
        or metadata.get("daily_filter_policy")
        or metadata.get("policy")
        or {}
    )
    if dataset_id == "clean_daily_bar" and (
        not isinstance(policy, dict)
        or policy.get("drop_suspended") is not True
        or policy.get("drop_limit_events") is not True
    ):
        raise _evidence_missing("clean_daily_bar.daily_filter_policy")
    summary_columns = summary_entry.get("columns")
    if not isinstance(summary_columns, list) or not all(
        isinstance(item, str) and item for item in summary_columns
    ):
        raise _evidence_missing(f"catalog_summary.{dataset_id}.columns")
    binding = {
        "summary_version": summary["version"],
        "summary_sha256": summary_sha256,
        "catalog_sha256": catalog_sha256,
        "catalog_membership": summary_entry.get("catalog_membership"),
        "active_admission_verdict": admission.get("verdict"),
    }
    closed_pit = {
        key: pit.get(key)
        for key in (
            "version",
            "verdict",
            "rule_id",
            "formation_time",
            "future_observations_excluded",
        )
    }
    closed_filter = {
        key: policy.get(key)
        for key in (
            "drop_suspended",
            "drop_limit_events",
            "invalid_days_do_not_enter_window",
            "minimum_effective_days",
        )
        if key in policy
    }
    _deny_sensitive_projection(closed_pit)
    _deny_sensitive_projection(closed_filter)
    return binding, closed_pit, closed_filter, list(summary_columns)


def _normal_evidence_query(
    raw: Any,
    *,
    dataset_id: str,
    research_windows: Mapping[str, Any],
    bounded_sample: bool = True,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _evidence_missing(f"{dataset_id}.sample_query")
    dataset = str(raw.get("dataset") or raw.get("dataset_id") or dataset_id)
    if dataset != dataset_id:
        raise _evidence_invalid(f"{dataset_id}.sample_query.dataset")
    start = compact_date(raw.get("start_date") or raw.get("start"))
    end = compact_date(raw.get("end_date") or raw.get("end"))
    is_start = compact_date(research_windows.get("is_start"))
    is_end = compact_date(research_windows.get("is_end"))
    try:
        for value in (start, end, is_start, is_end):
            datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise _evidence_invalid(f"{dataset_id}.sample_query.date") from exc
    if not is_start <= start <= end <= is_end:
        raise _evidence_invalid(f"{dataset_id}.sample_query.window")
    if bounded_sample and (
        datetime.strptime(end, "%Y%m%d")
        - datetime.strptime(start, "%Y%m%d")
    ).days > 900:
        raise _evidence_invalid(f"{dataset_id}.sample_query.not_bounded")
    fields = raw.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(item, str) or not item.strip() for item in fields)
    ):
        raise _evidence_missing(f"{dataset_id}.sample_query.fields")
    universe = raw.get("universe")
    if not (
        isinstance(universe, str)
        and universe.strip()
        or isinstance(universe, (list, tuple))
        and universe
        and all(isinstance(item, str) and item.strip() for item in universe)
    ):
        raise _evidence_invalid(f"{dataset_id}.sample_query.universe")
    frequency = str(raw.get("frequency") or "daily")
    if frequency != "daily":
        raise _evidence_invalid(f"{dataset_id}.sample_query.frequency")
    normalized_fields = list(dict.fromkeys(item.strip() for item in fields))
    _assert_non_outcome_fields(
        normalized_fields, label=f"{dataset_id}.sample_query"
    )
    return {
        "dataset": dataset_id,
        "start_date": start,
        "end_date": end,
        "universe": (
            universe
            if isinstance(universe, str)
            else [str(item) for item in universe]
        ),
        "fields": normalized_fields,
        "frequency": frequency,
    }


def _safe_local_artifact(
    local_inputs: Mapping[str, Any], *, workspace_root: Path
) -> tuple[str, str]:
    raw = local_inputs.get("daily_df_parquet") or local_inputs.get("daily_df_csv")
    relative = _safe_workspace_relative_ref(raw)
    if relative is None:
        raise _evidence_missing("sample_artifact.path")
    del workspace_root
    suffix = Path(relative).suffix.lower()
    if suffix not in {".parquet", ".csv"}:
        raise _evidence_invalid("sample_artifact.format")
    return relative, suffix.removeprefix(".")


def _normal_frame_dates(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if value is None:
            raise _evidence_invalid("sample_artifact.trade_date_null")
        if hasattr(value, "strftime"):
            text = value.strftime("%Y%m%d")
        else:
            text = str(value).strip()
            if re.fullmatch(r"\d{8}\.0", text):
                text = text[:8]
        text = compact_date(text)
        try:
            datetime.strptime(text, "%Y%m%d")
        except ValueError as exc:
            raise _evidence_invalid("sample_artifact.trade_date_invalid") from exc
        normalized.append(text)
    return normalized


def _closed_io_contract(local_inputs: Mapping[str, Any]) -> dict[str, Any]:
    source = local_inputs.get("daily_io_contract")
    if not isinstance(source, Mapping):
        raise _evidence_missing("sample_artifact.io_contract")
    allowed = {
        "version",
        "formal_evidence_format",
        "performance_path",
        "audit_path",
        "csv_output_policy",
        "csv_rows_written",
        "parquet_rows_written",
        "csv_sample_strategy",
        "full_csv_available",
        "schema_parity_required",
        "value_parity_required",
        "csv_required_for_audit",
        "parquet_required_for_performance",
        "sample_schema_parity",
        "full_csv_absent_validated",
        "full_csv_absence_reason",
    }
    projected = {
        key: json.loads(json.dumps(value))
        for key, value in source.items()
        if key in allowed
    }
    sort_source = source.get("sort_contract") or local_inputs.get("sort_contract")
    if not isinstance(sort_source, Mapping):
        raise _evidence_missing("sample_artifact.sort_contract")
    sort_allowed = {
        "version",
        "sorted_by",
        "row_count",
        "key_dtype",
        "source",
        "data_hash",
        "schema",
        "duplicate_key_check",
        "sample_sortedness_check",
    }
    projected["sort_contract"] = {
        key: json.loads(json.dumps(value))
        for key, value in sort_source.items()
        if key in sort_allowed
    }
    # The closed Step3 proof binds exactly one consumer artifact.  If the
    # canonical Parquet exists, CSV audit files remain Host/workspace evidence
    # but are not exposed as unhashed Agent inputs.
    if local_inputs.get("daily_df_parquet"):
        projected.update(
            {
                "formal_evidence_format": "parquet",
                "performance_path": "parquet",
                "audit_path": "none",
                "csv_output_policy": "no_csv",
                "csv_rows_written": 0,
                "csv_sample_strategy": "none",
                "full_csv_available": False,
                "schema_parity_required": False,
                "value_parity_required": False,
                "csv_required_for_audit": False,
                "parquet_required_for_performance": True,
                "sample_schema_parity": None,
                "full_csv_absent_validated": True,
                "full_csv_absence_reason": "evo_pre_release_projection",
            }
        )
        projected.pop("csv_path", None)
        projected.pop("csv_sample_path", None)
    return projected


def _closed_derived_lineage(
    *,
    local_inputs: Mapping[str, Any],
    logical_fields: list[str],
    physical_query_fields: list[str],
    source_schema: list[str],
    local_schema: list[str],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    contract = local_inputs.get("derived_field_contract")
    if not isinstance(contract, Mapping):
        raise _evidence_missing("sample_artifact.derived_field_contract")
    if (
        contract.get("version") != "factorforge_derived_field_contract_v1"
        or contract.get("validation_result") != "PASS"
        or contract.get("report_local_only") is not True
        or contract.get("clean_data_mutation") is not False
    ):
        raise _evidence_invalid("sample_artifact.derived_field_contract")
    raw_specs = contract.get("derived_fields")
    if not isinstance(raw_specs, Mapping):
        raise _evidence_invalid("sample_artifact.derived_field_contract.fields")
    physical = set(physical_query_fields)
    source_columns = set(source_schema)
    local_columns = set(local_schema)
    used_specs: dict[str, dict[str, Any]] = {}

    def physical_leaves(field: str, trail: frozenset[str]) -> set[str]:
        if field in physical:
            if field not in source_columns or field not in local_columns:
                raise _evidence_missing(f"derived_lineage.physical_source.{field}")
            return {field}
        if field in trail:
            raise _evidence_invalid(f"derived_lineage.cycle.{field}")
        spec = raw_specs.get(field)
        if not isinstance(spec, Mapping):
            raise _evidence_missing(f"derived_lineage.{field}")
        sources = spec.get("sources")
        allowed = {
            "operator",
            "sources",
            "rule",
            "source_units",
            "output_unit",
            "leakage_policy",
            "lookback_window",
            "rank_scope",
        }
        closed_spec = {
            key: json.loads(json.dumps(value))
            for key, value in spec.items()
            if key in allowed
        }
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) and item for item in sources)
            or not closed_spec.get("rule")
            or not isinstance(closed_spec.get("source_units"), Mapping)
            or not closed_spec.get("output_unit")
            or closed_spec.get("leakage_policy") != "no future data"
        ):
            raise _evidence_invalid(f"derived_lineage.contract.{field}")
        adv_match = re.fullmatch(r"adv(\d+)", field)
        if adv_match and (
            isinstance(closed_spec.get("lookback_window"), bool)
            or not isinstance(closed_spec.get("lookback_window"), int)
            or closed_spec.get("lookback_window") != int(adv_match.group(1))
        ):
            raise _evidence_invalid(f"derived_lineage.lookback.{field}")
        if field not in local_columns:
            raise _evidence_missing(f"derived_lineage.local_field.{field}")
        used_specs[field] = closed_spec
        leaves: set[str] = set()
        for source in sources:
            leaves.update(physical_leaves(source, trail | {field}))
        return leaves

    def validate_standard_semantics(field: str, leaves: set[str]) -> None:
        adv_match = re.fullmatch(r"adv(\d+)", field)
        spec = used_specs.get(field)
        sources = spec.get("sources") if isinstance(spec, Mapping) else None
        if adv_match:
            window = int(adv_match.group(1))
            source = sources[0] if isinstance(sources, list) and sources else None
            if (
                spec.get("operator") != "mean"
                or not isinstance(sources, list)
                or len(sources) != 1
                or source not in {"vol", "volume"}
                or spec.get("rule") != f"rolling_mean({source},{window})"
                or leaves != {"vol"}
            ):
                raise _evidence_invalid(f"derived_lineage.semantics.{field}")
        elif field == "volume" and (
            spec.get("operator") != "alias"
            or sources != ["vol"]
            or spec.get("rule") != "alias(volume <- vol)"
            or leaves != {"vol"}
        ):
            raise _evidence_invalid("derived_lineage.semantics.volume")
        elif field == "returns" and (
            spec.get("operator") != "alias"
            or sources != ["pct_chg"]
            or spec.get("rule") != "pct_chg / 100"
            or leaves != {"pct_chg"}
        ):
            raise _evidence_invalid("derived_lineage.semantics.returns")
        elif field == "vwap":
            volume_source = (
                sources[1]
                if isinstance(sources, list) and len(sources) == 2
                else None
            )
            if (
                spec.get("operator") != "divide"
                or sources not in (["amount", "vol"], ["amount", "volume"])
                or spec.get("rule") != f"amount / {volume_source}"
                or leaves != {"amount", "vol"}
            ):
                raise _evidence_invalid("derived_lineage.semantics.vwap")

    physical_sources: dict[str, list[str]] = {}
    for field in logical_fields:
        if field in physical:
            continue
        leaves = physical_leaves(field, frozenset())
        physical_sources[field] = sorted(leaves)
    # Validate every recursively retained standard alias, not only the
    # top-level logical requirements.  E.g. producer-shaped ADV20 retains
    # volume<-vol beneath adv20<-volume; both nodes are independently bound.
    for field in list(used_specs):
        validate_standard_semantics(
            field,
            physical_leaves(field, frozenset()),
        )
    return (
        {
            "version": contract.get("version"),
            "validation_result": contract.get("validation_result"),
            "report_local_only": contract.get("report_local_only"),
            "clean_data_mutation": contract.get("clean_data_mutation"),
            "derived_fields": {
                key: used_specs[key] for key in sorted(used_specs)
            },
        },
        physical_sources,
    )


def _validate_derived_warmup(
    *,
    frame: Any,
    logical_fields: list[str],
    derived_lineage: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    specs = derived_lineage.get("derived_fields")
    if not isinstance(specs, Mapping):
        raise _evidence_invalid("derived_warmup.lineage")
    checks: dict[str, dict[str, Any]] = {}
    for field in logical_fields:
        spec = specs.get(field)
        if not isinstance(spec, Mapping):
            raise _evidence_missing(f"derived_warmup.lineage.{field}")
        lookback = spec.get("lookback_window")
        if lookback is None:
            lookback = 1
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
            raise _evidence_invalid(f"derived_warmup.lookback.{field}")
        allowed_prefix = lookback - 1
        total_warmup_nulls = 0
        total_valid = 0
        tickers = 0
        for _ticker, group in frame.groupby("ts_code", sort=False):
            tickers += 1
            values = group[field]
            try:
                import pandas as pd

                numeric = pd.to_numeric(values, errors="coerce")
            except Exception as exc:  # noqa: BLE001 - deterministic local frame.
                raise _evidence_invalid(f"derived_warmup.numeric.{field}") from exc
            raw_null = values.isna().reset_index(drop=True)
            numeric = numeric.reset_index(drop=True)
            nonfinite_nonnull = [
                index
                for index, (is_null, value) in enumerate(
                    zip(raw_null.tolist(), numeric.tolist())
                )
                if not is_null
                and (value is None or not math.isfinite(float(value)))
            ]
            if nonfinite_nonnull:
                raise _evidence_invalid(f"derived_warmup.non_finite.{field}")
            warmup_prefix = raw_null.iloc[:allowed_prefix]
            if re.fullmatch(r"adv\d+", field) and (
                len(warmup_prefix) != allowed_prefix
                or not bool(warmup_prefix.all())
            ):
                raise _evidence_invalid(
                    f"derived_warmup.prefix_pattern.{field}"
                )
            post_warmup = raw_null.iloc[allowed_prefix:]
            if post_warmup.any():
                raise _evidence_invalid(f"derived_warmup.post_warmup_null.{field}")
            warmup_nulls = int(warmup_prefix.sum())
            valid_samples = int((~raw_null.iloc[allowed_prefix:]).sum())
            if valid_samples < 1:
                raise _evidence_invalid(f"derived_warmup.no_valid_sample.{field}")
            total_warmup_nulls += warmup_nulls
            total_valid += valid_samples
        if tickers < 1 or total_valid < 1:
            raise _evidence_invalid(f"derived_warmup.no_valid_sample.{field}")
        checks[field] = {
            "policy": "per_ticker_prefix_only",
            "lookback_window": lookback,
            "allowed_warmup_prefix_rows_per_ticker": allowed_prefix,
            "warmup_null_count": total_warmup_nulls,
            "post_warmup_null_count": 0,
            "post_warmup_non_finite_count": 0,
            "valid_sample_count": total_valid,
            "ticker_count": tickers,
        }
    return checks


def _stable_local_sample_facts(
    *,
    local_inputs: Mapping[str, Any],
    workspace_root: Path,
    query: Mapping[str, Any],
    required_fields: list[str],
    source_schema: list[str],
) -> dict[str, Any]:
    relative, artifact_format = _safe_local_artifact(
        local_inputs, workspace_root=workspace_root
    )
    try:
        raw = read_workspace_bytes(
            workspace_root.expanduser().resolve(strict=True),
            relative,
            max_bytes=256 * 1024 * 1024,
        )
        if not raw:
            raise _evidence_invalid("sample_artifact.size_bound")
        import pandas as pd

        buffer = io.BytesIO(raw)
        frame = (
            pd.read_parquet(buffer)
            if artifact_format == "parquet"
            else pd.read_csv(buffer)
        )
    except (OSError, ResearchOrganizationError) as exc:
        raise _evidence_invalid("sample_artifact.unsafe_read") from exc
    except Exception as exc:  # noqa: BLE001 - local bounded evidence read.
        raise _evidence_invalid("sample_artifact.read") from exc
    digest = hashlib.sha256(raw).hexdigest()
    columns = [str(item) for item in frame.columns]
    if len(columns) != len(set(columns)):
        raise _evidence_invalid("sample_artifact.duplicate_columns")
    _assert_non_outcome_fields(columns, label="sample_artifact.schema")
    physical_query_fields = list(query.get("fields", []))
    derived_logical_fields = [
        field for field in required_fields if field not in physical_query_fields
    ]
    required_columns = [
        "ts_code",
        "trade_date",
        *physical_query_fields,
        *required_fields,
    ]
    missing = sorted(set(required_columns) - set(columns))
    if missing:
        raise _evidence_missing("sample_artifact.fields:" + ",".join(missing))
    if frame.empty:
        raise _evidence_missing("sample_artifact.empty")
    if len(frame) > 10_000_000:
        raise _evidence_invalid("sample_artifact.row_bound")
    dates = _normal_frame_dates(frame["trade_date"].tolist())
    query_start = compact_date(query.get("start_date"))
    query_end = compact_date(query.get("end_date"))
    observed_start, observed_end = min(dates), max(dates)
    if observed_start < query_start or observed_end > query_end:
        raise _evidence_invalid("sample_artifact.query_window")
    derived_lineage = None
    derived_physical_sources: dict[str, list[str]] = {}
    derived_warmup_checks: dict[str, dict[str, Any]] = {}
    if derived_logical_fields:
        derived_lineage, derived_physical_sources = _closed_derived_lineage(
            local_inputs=local_inputs,
            logical_fields=derived_logical_fields,
            physical_query_fields=physical_query_fields,
            source_schema=source_schema,
            local_schema=columns,
        )
        derived_warmup_checks = _validate_derived_warmup(
            frame=frame,
            logical_fields=derived_logical_fields,
            derived_lineage=derived_lineage,
        )
    checked_fields = list(dict.fromkeys([*physical_query_fields, *required_fields]))
    for field in physical_query_fields:
        numeric = pd.to_numeric(frame[field], errors="coerce")
        if numeric.isna().any() or not numeric.map(
            lambda value: math.isfinite(float(value))
        ).all():
            raise _evidence_invalid(f"sample_artifact.non_finite.{field}")
    null_counts = {field: int(frame[field].isna().sum()) for field in checked_fields}
    key_null_counts = {
        "ts_code": int(frame["ts_code"].isna().sum()),
        "trade_date": int(frame["trade_date"].isna().sum()),
    }
    duplicate_key_count = int(
        frame[["ts_code", "trade_date"]].duplicated().sum()
    )
    physical_null_counts = {
        field: null_counts[field] for field in physical_query_fields
    }
    if any(physical_null_counts.values()) or any(key_null_counts.values()):
        raise _evidence_invalid("sample_artifact.required_nulls")
    if duplicate_key_count:
        raise _evidence_invalid("sample_artifact.duplicate_keys")
    observed_symbols = set(frame["ts_code"].astype(str))
    query_universe = query.get("universe")
    if isinstance(query_universe, list) and observed_symbols != set(query_universe):
        raise _evidence_invalid("sample_artifact.universe_membership")
    schema_payload = {
        "columns": columns,
        "dtypes": {name: str(frame[name].dtype) for name in columns},
    }
    io_contract = _closed_io_contract(local_inputs)
    sort_contract = io_contract.get("sort_contract") or {}
    key_frame = frame[["ts_code", "trade_date"]].astype(str).reset_index(drop=True)
    key_order_sha256 = hashlib.sha256(
        key_frame.to_csv(index=False).encode("utf-8")
    ).hexdigest()
    expected_sorted = key_frame.sort_values(
        ["ts_code", "trade_date"]
    ).reset_index(drop=True)
    if (
        io_contract.get("version")
        != "factorforge_step3a_daily_io_contract_v1"
        or sort_contract.get("version") != "factorforge_sort_contract_v1"
        or sort_contract.get("sorted_by") != ["ts_code", "trade_date"]
        or sort_contract.get("row_count") != int(len(frame))
        or sort_contract.get("source") != "step3a_local_input"
        or not isinstance(sort_contract.get("key_dtype"), Mapping)
        or not sort_contract["key_dtype"].get("ts_code")
        or not sort_contract["key_dtype"].get("trade_date")
        or sort_contract.get("data_hash") != key_order_sha256
        or sort_contract.get("duplicate_key_check") is not True
        or sort_contract.get("sample_sortedness_check") is not True
        or not key_frame.equals(expected_sorted)
    ):
        raise _evidence_invalid("sample_artifact.io_sort_contract")
    if (
        artifact_format == "parquet"
        and io_contract.get("parquet_rows_written") != int(len(frame))
    ):
        raise _evidence_invalid("sample_artifact.io_row_count")
    facts = {
        "sample_artifact": {
            "path": relative,
            "sha256": digest,
            "size_bytes": len(raw),
            "format": artifact_format,
        },
        "schema": {
            **schema_payload,
            "schema_sha256": _stable_hash(schema_payload),
            "date_column": "trade_date",
            "symbol_column": "ts_code",
        },
        "coverage": {
            "row_count": int(len(frame)),
            "date_count": len(set(dates)),
            "ticker_count": int(frame["ts_code"].astype(str).nunique()),
            "observed_start": observed_start,
            "observed_end": observed_end,
            "required_field_null_counts": null_counts,
            "key_null_counts": key_null_counts,
            "duplicate_key_count": duplicate_key_count,
        },
        "io_contract": io_contract,
    }
    if derived_lineage is not None:
        facts["derived_field_lineage"] = derived_lineage
        facts["derived_physical_sources"] = derived_physical_sources
        facts["derived_field_warmup_checks"] = derived_warmup_checks
    return facts


def _closed_sample_read_metadata(
    raw: Any,
    *,
    dataset_id: str,
    research_windows: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _evidence_missing(f"{dataset_id}.sample_read_metadata")
    status = str(raw.get("status") or "")
    if status != "ready":
        raise _evidence_missing(f"{dataset_id}.sample_read_status")
    if str(raw.get("dataset_id") or dataset_id) != dataset_id:
        raise _evidence_invalid(f"{dataset_id}.sample_read_dataset")
    query = _normal_evidence_query(
        raw.get("query") or raw.get("request"),
        dataset_id=dataset_id,
        research_windows=research_windows,
    )
    coverage = raw.get("coverage")
    if not isinstance(coverage, Mapping):
        raise _evidence_missing(f"{dataset_id}.sample_read_coverage")
    closed_coverage: dict[str, int] = {}
    for key in ("row_count", "date_count", "ticker_count"):
        value = coverage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise _evidence_missing(f"{dataset_id}.sample_read_coverage.{key}")
        closed_coverage[key] = value
    schema = raw.get("schema")
    if not isinstance(schema, Mapping) or not isinstance(schema.get("columns"), list):
        raise _evidence_missing(f"{dataset_id}.sample_read_schema")
    columns = [str(item) for item in schema.get("columns") or []]
    if not columns or len(columns) != len(set(columns)):
        raise _evidence_invalid(f"{dataset_id}.sample_read_schema.columns")
    resolved = raw.get("resolved_fields")
    resolved = dict(resolved) if isinstance(resolved, Mapping) else {}
    return {
        "dataset_id": dataset_id,
        "status": status,
        "query": query,
        "coverage": closed_coverage,
        "schema": {
            "columns": columns,
            "date_column": schema.get("date_column"),
            "symbol_column": schema.get("symbol_column"),
            "schema_hash": schema.get("schema_hash"),
        },
        "resolved_fields": {
            str(key): str(value)
            for key, value in resolved.items()
            if isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
        },
    }


def build_closed_pre_release_data_resolution(
    *,
    source_resolution: Mapping[str, Any],
    local_inputs: Mapping[str, Any],
    research_windows: Mapping[str, Any],
    workspace_root: Path,
    factorforge_root: Path,
    required_fields: list[str],
    report_id: str,
    factor_id: str,
    expected_sample_query: Mapping[str, Any],
    step4_data_contract: Mapping[str, Any],
    primary_dataset: str = "clean_daily_bar",
) -> dict[str, Any]:
    """Build non-secret Step3 proof from the already-fetched local IS sample.

    This performs no Data API or remote read. The frozen IS window, actual
    sample query window, and observed artifact window remain separate facts.
    """

    if primary_dataset != "clean_daily_bar":
        raise _evidence_invalid("primary_dataset.unsupported")
    if not report_id or not factor_id:
        raise _evidence_missing("identity")
    resolution = source_resolution.get(primary_dataset)
    if not isinstance(resolution, Mapping):
        raise _evidence_missing(f"{primary_dataset}.resolution")
    if str(resolution.get("status") or "") != "ready":
        raise _evidence_missing(f"{primary_dataset}.resolution_status")
    required = list(dict.fromkeys(str(item).strip().lower() for item in required_fields))
    if not required or any(not item for item in required):
        raise _evidence_missing("formula_required_fields")
    frozen_windows = {
        key: research_windows.get(key)
        for key in (
            "is_start",
            "is_end",
            "oos_start",
            "oos_end",
            "purge_days",
            "embargo_days",
        )
    }
    is_start = compact_date(frozen_windows["is_start"])
    is_end = compact_date(frozen_windows["is_end"])
    oos_start = compact_date(frozen_windows["oos_start"])
    oos_end = compact_date(frozen_windows["oos_end"])
    if not is_start <= is_end < oos_start <= oos_end:
        raise _evidence_invalid("frozen_window_order")
    if type(frozen_windows["purge_days"]) is not int or type(
        frozen_windows["embargo_days"]
    ) is not int:
        raise _evidence_invalid("frozen_window_purge_embargo")
    if frozen_windows["purge_days"] < 0 or frozen_windows["embargo_days"] < 0:
        raise _evidence_invalid("frozen_window_purge_embargo")
    sample_read = _closed_sample_read_metadata(
        resolution.get("sample_read"),
        dataset_id=primary_dataset,
        research_windows=frozen_windows,
    )
    resolved_query = _normal_evidence_query(
        resolution.get("request") or resolution.get("query"),
        dataset_id=primary_dataset,
        research_windows=frozen_windows,
    )
    if resolved_query != sample_read["query"]:
        raise _evidence_invalid(f"{primary_dataset}.resolved_fetch_query_mismatch")
    canonical_sample_query = _normal_evidence_query(
        expected_sample_query,
        dataset_id=primary_dataset,
        research_windows=frozen_windows,
    )
    if resolved_query != canonical_sample_query:
        raise _evidence_invalid(f"{primary_dataset}.canonical_sample_query")
    if not isinstance(step4_data_contract, Mapping):
        raise _evidence_missing("step4_data_contract")
    full_queries = step4_data_contract.get("full_queries")
    full_query = (
        full_queries.get(primary_dataset)
        if isinstance(full_queries, Mapping)
        else None
    )
    full_query = _normal_evidence_query(
        full_query,
        dataset_id=primary_dataset,
        research_windows=frozen_windows,
        bounded_sample=False,
    )
    if (
        full_query["start_date"] != is_start
        or full_query["end_date"] != is_end
        or full_query["universe"] != "a_share_all"
        or full_query["fields"] != canonical_sample_query["fields"]
        or full_query["frequency"] != canonical_sample_query["frequency"]
    ):
        raise _evidence_invalid("step4_data_contract.full_query_contract")
    catalog_raw = resolution.get("catalog_path")
    if not isinstance(catalog_raw, str) or not catalog_raw:
        raise _evidence_missing(f"{primary_dataset}.catalog_path")
    catalog_path = Path(catalog_raw).expanduser()
    if not catalog_path.is_absolute():
        raise _evidence_invalid(f"{primary_dataset}.catalog_path")
    catalog_binding, pit, catalog_filter, catalog_columns = _closed_catalog_binding(
        factorforge_root=factorforge_root.expanduser().resolve(strict=True),
        catalog_path=catalog_path,
        dataset_id=primary_dataset,
    )
    if not set(sample_read["query"]["fields"]).issubset(catalog_columns):
        raise _evidence_invalid(f"{primary_dataset}.query_fields_not_in_catalog")
    local_facts = _stable_local_sample_facts(
        local_inputs=local_inputs,
        workspace_root=workspace_root,
        query=sample_read["query"],
        required_fields=required,
        source_schema=sample_read["schema"]["columns"],
    )
    if sample_read["coverage"] != {
        key: local_facts["coverage"][key]
        for key in ("row_count", "date_count", "ticker_count")
    }:
        raise _evidence_invalid(f"{primary_dataset}.sample_read_coverage_replay")
    source_schema_required = {
        "ts_code",
        "trade_date",
        *sample_read["query"]["fields"],
    }
    if not source_schema_required.issubset(sample_read["schema"]["columns"]):
        raise _evidence_invalid(
            f"{primary_dataset}.sample_read_schema_query_fields"
        )
    raw_resolved: dict[str, str] = {}
    for candidate in (
        resolution.get("resolved_fields"),
        sample_read.get("resolved_fields"),
    ):
        if isinstance(candidate, Mapping):
            raw_resolved.update(
                {
                    str(key).lower(): str(value)
                    for key, value in candidate.items()
                    if isinstance(key, str)
                    and key
                    and isinstance(value, str)
                    and value
                }
            )
    resolved_fields: dict[str, str] = {}
    physical_source_fields: dict[str, list[str]] = {}
    derived_logical_fields: list[str] = []
    for field in required:
        resolved = raw_resolved.get(field)
        if resolved is None and field in sample_read["query"]["fields"]:
            resolved = field
        if (
            resolved in sample_read["query"]["fields"]
            and resolved in sample_read["schema"]["columns"]
            and resolved in local_facts["schema"]["columns"]
        ):
            resolved_fields[field] = resolved
            physical_source_fields[field] = [resolved]
            continue
        if field not in local_facts["schema"]["columns"]:
            raise _evidence_missing(f"{primary_dataset}.resolved_field.{field}")
        resolved_fields[field] = field
        derived_logical_fields.append(field)
    derived_lineage = None
    if derived_logical_fields:
        derived_lineage = local_facts.get("derived_field_lineage")
        derived_sources = local_facts.get("derived_physical_sources")
        if not isinstance(derived_lineage, Mapping) or not isinstance(
            derived_sources, Mapping
        ):
            raise _evidence_invalid("derived_lineage.replay")
        physical_source_fields.update(derived_sources)
    artifact_required = {
        "ts_code",
        "trade_date",
        *required,
        *resolved_fields.values(),
    }
    if not artifact_required.issubset(local_facts["schema"]["columns"]):
        raise _evidence_missing(
            f"{primary_dataset}.sample_artifact.resolved_fields"
        )
    if (
        catalog_filter.get("drop_suspended") is not True
        or catalog_filter.get("drop_limit_events") is not True
    ):
        raise _evidence_missing("clean_daily_bar.daily_filter_policy")
    dataset_proof = {
        "dataset_id": primary_dataset,
        "status": "ready",
        "catalog_identity": catalog_binding,
        "frozen_is_window": {
            "start": is_start,
            "end": is_end,
        },
        "actual_fetch_query": sample_read["query"],
        "observed_artifact_window": {
            "start": local_facts["coverage"]["observed_start"],
            "end": local_facts["coverage"]["observed_end"],
        },
        "required_fields": required,
        "resolved_fields": resolved_fields,
        "physical_source_fields": physical_source_fields,
        "source_read_metadata": sample_read,
        "schema": local_facts["schema"],
        "coverage": local_facts["coverage"],
        "daily_filter_policy": catalog_filter,
        "point_in_time_policy": pit,
        "sample_artifact": local_facts["sample_artifact"],
        "io_contract": local_facts["io_contract"],
        "sample_integrity_checks": {
            "scope": "step3a_report_local_actual_fetch_sample",
            "required_fields_complete": True,
            "key_nulls_absent": True,
            "duplicate_keys_absent": True,
        },
        "local_artifact_replay": {
            "scope": "workspace_local_stable_read_of_data_api_sample",
            "remote_worker_read_performed": False,
            "query_sha256": _stable_hash(sample_read["query"]),
            "artifact_sha256": local_facts["sample_artifact"]["sha256"],
            "result_counts": {
                key: local_facts["coverage"][key]
                for key in ("row_count", "date_count", "ticker_count")
            },
        },
        "observed_rows_within_frozen_is": True,
        "canonical_data_mutated": False,
        "formal_dataset_qa": False,
        "full_is_calendar_coverage": False,
        "formal_factor_values": False,
        "step4_full_is_receipt_required": True,
    }
    if derived_lineage is not None:
        dataset_proof["derived_field_lineage"] = dict(derived_lineage)
        dataset_proof["derived_field_warmup_checks"] = local_facts[
            "derived_field_warmup_checks"
        ]
    closed = {
        "contract_version": CLOSED_DATA_API_RESOLUTION_VERSION,
        "status": "closed_is_sample_evidence_ready",
        "identity": {"report_id": report_id, "factor_id": factor_id},
        "primary_dataset": primary_dataset,
        "snapshot_source": "data_api_clean_daily_bar",
        "research_windows": frozen_windows,
        "canonical_step3_sample_query": canonical_sample_query,
        "step4_data_contract": {
            "version": step4_data_contract.get("version"),
            "full_query": full_query,
            "sha256": _stable_hash(step4_data_contract),
        },
        primary_dataset: dataset_proof,
    }
    projection_without_workspace_ref = json.loads(json.dumps(closed))
    projection_without_workspace_ref[primary_dataset]["sample_artifact"].pop(
        "path", None
    )
    _deny_sensitive_projection(projection_without_workspace_ref)
    return closed


def validate_closed_pre_release_data_resolution(
    projection: Any,
    *,
    research_windows: Mapping[str, Any],
    workspace_root: Path,
    factorforge_root: Path,
    catalog_path: Path | None,
    required_fields: list[str],
    report_id: str,
    factor_id: str,
    expected_sample_query: Mapping[str, Any],
    step4_data_contract: Mapping[str, Any],
    expected_artifact_relative: str,
    primary_dataset: str = "clean_daily_bar",
) -> list[str]:
    """Exact-replay a closed Step3 projection from local immutable facts."""

    if not isinstance(projection, dict):
        return [f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:projection"]
    if projection.get("contract_version") != CLOSED_DATA_API_RESOLUTION_VERSION:
        return [
            f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:projection.contract_version"
        ]
    proof = projection.get(primary_dataset)
    if not isinstance(proof, dict):
        return [
            f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:projection.{primary_dataset}"
        ]
    if catalog_path is None:
        return [f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:approved_catalog"]
    artifact = proof.get("sample_artifact")
    source_read = proof.get("source_read_metadata")
    query = proof.get("actual_fetch_query")
    if not all(isinstance(item, dict) for item in (artifact, source_read, query)):
        return [
            f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING}:projection.replay_inputs"
        ]
    if (
        projection.get("identity")
        != {"report_id": report_id, "factor_id": factor_id}
        or projection.get("primary_dataset") != primary_dataset
        or projection.get("snapshot_source") != "data_api_clean_daily_bar"
        or artifact.get("path") != expected_artifact_relative
    ):
        return [
            f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID}:projection.consumer_binding"
        ]
    local_inputs: dict[str, Any] = {
        "daily_io_contract": proof.get("io_contract"),
        "sort_contract": (
            (proof.get("io_contract") or {}).get("sort_contract")
            if isinstance(proof.get("io_contract"), dict)
            else None
        ),
    }
    derived_lineage = proof.get("derived_field_lineage")
    if derived_lineage is not None:
        if not isinstance(derived_lineage, dict):
            return [
                f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID}:"
                "projection.derived_field_lineage"
            ]
        # The producer already projects the minimal non-secret lineage
        # contract. Reuse exactly that closed contract as replay input; the
        # builder independently revalidates its sources/rule/lookback against
        # the local artifact and physical Data API query.
        local_inputs["derived_field_contract"] = json.loads(
            json.dumps(derived_lineage)
        )
    artifact_format = artifact.get("format")
    if artifact_format == "parquet":
        local_inputs["daily_df_parquet"] = artifact.get("path")
    elif artifact_format == "csv":
        local_inputs["daily_df_csv"] = artifact.get("path")
    else:
        return [
            f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID}:sample_artifact.format"
        ]
    reconstructed_resolution = {
        primary_dataset: {
            "dataset_id": primary_dataset,
            "status": "ready",
            "catalog_path": str(catalog_path),
            "request": query,
            "resolved_fields": proof.get("resolved_fields"),
            "sample_read": source_read,
        }
    }
    try:
        replay = build_closed_pre_release_data_resolution(
            source_resolution=reconstructed_resolution,
            local_inputs=local_inputs,
            research_windows=research_windows,
            workspace_root=workspace_root,
            factorforge_root=factorforge_root,
            required_fields=required_fields,
            report_id=report_id,
            factor_id=factor_id,
            expected_sample_query=expected_sample_query,
            step4_data_contract=step4_data_contract,
            primary_dataset=primary_dataset,
        )
    except (OSError, TypeError, ValueError) as exc:
        return [str(exc)]
    return (
        []
        if replay == projection
        else [f"{BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID}:projection.exact_replay"]
    )


def compact_date(value: Any) -> str:
    text = "".join(character for character in str(value or "") if character.isdigit())
    if len(text) != 8:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:date")
    return text


def _scrub_host_source_details(value: Any, *, key: str = "") -> Any:
    sensitive_key = key.lower() in {
        "path",
        "uri",
        "catalog_path",
        "catalog_uri",
        "metadata_uri",
        "materialized_root",
        "source_path",
        "source_uri",
    }
    if sensitive_key:
        return "HOST_PRIVATE_REDACTED"
    if isinstance(value, dict):
        return {
            item_key: _scrub_host_source_details(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_scrub_host_source_details(item) for item in value]
    if isinstance(value, str) and (
        "s3://" in value.lower()
        or "amazonaws.com" in value.lower()
        or value.startswith("/home/ubuntu/")
    ):
        return "HOST_PRIVATE_REDACTED"
    return value


def _read_regular_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{label}.missing_or_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{label}.invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{label}.not_object")
    return payload


def _safe_workspace_relative_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    lowered = text.lower()
    candidate = Path(text).expanduser()
    if (
        candidate.is_absolute()
        or "//" in lowered
        or "://" in lowered
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return None
    return candidate.as_posix()


def _closed_pre_release_local_inputs(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild local inputs without inheriting unknown path/URI authority."""

    projected: dict[str, Any] = {}
    # Expose only the exact primary consumer input. Other daily aliases and CSV
    # audit files remain Host-side workspace evidence unless independently
    # hashed by a later formal receipt.
    primary_key = (
        "daily_df_parquet"
        if _safe_workspace_relative_ref(source.get("daily_df_parquet"))
        else "daily_df_csv"
    )
    primary_ref = _safe_workspace_relative_ref(source.get(primary_key))
    if primary_ref:
        projected[primary_key] = primary_ref
    projected["input_mode"] = "daily_only"
    formula_dataset = str(source.get("formula_input_dataset") or "")
    if formula_dataset in ALLOWED_PRE_RELEASE_DAILY_DATASETS:
        projected["formula_input_dataset"] = formula_dataset
    if projected.get("daily_df_parquet"):
        projected["preferred_daily_format"] = "parquet"
    elif projected.get("daily_df_csv"):
        projected["preferred_daily_format"] = "csv"

    sort_source = source.get("sort_contract")
    if not isinstance(sort_source, dict):
        nested = source.get("daily_io_contract")
        sort_source = (
            nested.get("sort_contract") if isinstance(nested, dict) else None
        )
    if isinstance(sort_source, dict):
        allowed_sort_fields = {
            "version",
            "sorted_by",
            "stable_sort",
            "row_count",
            "key_dtype",
            "source",
            "data_hash",
            "schema",
            "duplicate_key_check",
            "sample_sortedness_check",
        }
        sort_contract = {
            key: json.loads(json.dumps(value))
            for key, value in sort_source.items()
            if key in allowed_sort_fields
        }
        if sort_contract:
            projected["sort_contract"] = sort_contract

    prior_io = source.get("daily_io_contract")
    prior_io = prior_io if isinstance(prior_io, dict) else {}
    full_csv = (
        projected.get("daily_df_csv")
        if not projected.get("daily_df_parquet")
        else None
    )
    sample_csv = None
    if full_csv:
        csv_policy = "full_csv"
        audit_path = "csv"
        projected["audit_daily_format"] = "csv"
    elif sample_csv:
        csv_policy = "sample_csv"
        audit_path = "csv_sample"
        projected["audit_daily_format"] = "csv_sample"
    else:
        csv_policy = "no_csv"
        audit_path = "none"
        projected["audit_daily_format"] = "none"
    daily_io = {
        "version": "factorforge_step3a_daily_io_contract_v1",
        "formal_evidence_format": "parquet",
        "performance_path": "parquet",
        "audit_path": audit_path,
        "csv_output_policy": csv_policy,
        "csv_rows_written": (
            int(prior_io.get("csv_rows_written") or 0)
            if csv_policy != "no_csv"
            else 0
        ),
        "parquet_rows_written": int(prior_io.get("parquet_rows_written") or 0),
        "csv_sample_strategy": (
            str(prior_io.get("csv_sample_strategy") or "none")
            if csv_policy != "no_csv"
            else "none"
        ),
        "full_csv_available": csv_policy == "full_csv",
        "schema_parity_required": csv_policy != "no_csv",
        "value_parity_required": csv_policy == "full_csv",
        "csv_required_for_audit": csv_policy == "full_csv",
        "sample_schema_parity": (
            prior_io.get("sample_schema_parity")
            if csv_policy != "no_csv"
            else None
        ),
        "full_csv_absent_validated": csv_policy != "full_csv",
        "full_csv_absence_reason": (
            None if csv_policy == "full_csv" else "evo_pre_release_projection"
        ),
        "csv_path": full_csv,
        "csv_sample_path": sample_csv,
    }
    if projected.get("sort_contract"):
        daily_io["sort_contract"] = json.loads(
            json.dumps(projected["sort_contract"])
        )
    projected["daily_io_contract"] = daily_io
    derived = source.get("derived_field_contract")
    if isinstance(derived, dict):
        safe_derived = _scrub_host_source_details(derived)
        projected["derived_field_contract"] = json.loads(
            json.dumps(safe_derived)
        )
    cross_sectional = source.get("cross_sectional_sample_contract")
    if isinstance(cross_sectional, dict):
        projected["cross_sectional_sample_contract"] = json.loads(
            json.dumps(_scrub_host_source_details(cross_sectional))
        )
    return projected


def resolve_evo_pre_release_research_windows(
    *,
    workspace_root: Path,
    report_id: str,
    data_prep: dict[str, Any] | None = None,
    expected_host_trust_manifest_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Return the immutable IS boundary for an EVO report, otherwise None."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    conjecture_path = (
        root / "objects" / "research_protocol" / f"research_conjecture__{report_id}.json"
    )
    if not conjecture_path.is_file() or conjecture_path.is_symlink():
        return None
    conjecture = _read_regular_json(conjecture_path, label="research_conjecture")
    if not epistemic_evolution_enabled(conjecture):
        return None
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    lifecycle = _read_regular_json(lifecycle_path, label="evo_lifecycle")
    lifecycle_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
    )
    if lifecycle_reasons:
        raise ValueError(";".join(lifecycle_reasons))

    parent_plan_path = root / "identity" / "web_research_plan.json"
    parent_plan = _read_regular_json(
        parent_plan_path, label="parent_web_research_plan"
    )
    parent_report_id = str((parent_plan.get("identity") or {}).get("report_id") or "")
    allocation: dict[str, Any] | None = None
    if report_id == parent_report_id:
        plan = parent_plan
        plan_label = "parent_web_research_plan"
    else:
        if not expected_host_trust_manifest_sha256:
            raise ValueError(
                f"{BLOCK_EVO_DATA_BOUNDARY}:child_external_host_trust_pin"
            )
        try:
            from factor_factory.evo_child_preregistration import (
                validate_and_resolve_evo_child_web_research_plan_structural,
            )

            child_resolution = (
                validate_and_resolve_evo_child_web_research_plan_structural(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                )
            )
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{BLOCK_EVO_DATA_BOUNDARY}:child_plan_authority:{exc}"
            ) from exc
        plan = dict(child_resolution["raw_plan"])
        allocation = dict(child_resolution["allocation"])
        plan_label = "child_web_research_plan"
    evidence = plan.get("evidence_policy")
    if not isinstance(evidence, dict):
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{plan_label}.evidence_policy")
    windows = {
        "is_start": evidence.get("is_start"),
        "is_end": evidence.get("is_end"),
        "oos_start": (
            (allocation.get("oos_window") or {}).get("start")
            if allocation is not None
            else evidence.get("oos_start")
        ),
        "oos_end": (
            (allocation.get("oos_window") or {}).get("end")
            if allocation is not None
            else evidence.get("oos_end")
        ),
        "purge_days": evidence.get("purge_days"),
        "embargo_days": evidence.get("embargo_days"),
    }
    projected = (data_prep or {}).get("research_windows")
    if projected is not None and projected != windows:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:data_prep.research_windows")
    is_start = compact_date(windows.get("is_start"))
    is_end = compact_date(windows.get("is_end"))
    oos_start = compact_date(windows.get("oos_start"))
    oos_end = compact_date(windows.get("oos_end"))
    if not is_start <= is_end < oos_start <= oos_end:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:window_order")
    if type(windows.get("purge_days")) is not int or type(
        windows.get("embargo_days")
    ) is not int:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:purge_embargo")
    if windows["purge_days"] < 0 or windows["embargo_days"] < 0:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:purge_embargo")
    return windows


def project_pre_release_data_access(
    payload: dict[str, Any], research_windows: dict[str, Any]
) -> dict[str, Any]:
    """In-place IS-only projection shared by Step3, child materializer and Step4."""

    is_start = compact_date(research_windows.get("is_start"))
    is_end = compact_date(research_windows.get("is_end"))
    if is_start > is_end:
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:window_order")
    payload["sample_window"] = {
        "start": str(research_windows.get("is_start")),
        "end": str(research_windows.get("is_end")),
    }
    payload["research_windows"] = dict(research_windows)
    payload["minute_derived_state_requirements"] = []
    source_local_inputs = payload.get("local_input_paths")
    if source_local_inputs is None:
        source_local_inputs = {}
    if not isinstance(source_local_inputs, dict):
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:local_input_paths")
    payload["local_input_paths"] = _closed_pre_release_local_inputs(
        source_local_inputs
    )
    data_sources = payload.get("data_sources")
    if isinstance(data_sources, list):
        payload["data_sources"] = [
            {
                key: value
                for key, value in item.items()
                if key in {"name", "kind", "fields", "normalized_dataset"}
            }
            for item in data_sources
            if isinstance(item, dict)
        ]
    for key in (
        "primary_dataset",
        "snapshot_source",
        "derived_field_contract",
        "cross_sectional_sample_contract",
    ):
        if key in source_local_inputs:
            payload["local_input_paths"][key] = json.loads(
                json.dumps(_scrub_host_source_details(source_local_inputs[key]))
            )
    source_resolution = payload.get("data_api_resolution")
    if (
        isinstance(source_resolution, dict)
        and source_resolution.get("contract_version")
        == CLOSED_DATA_API_RESOLUTION_VERSION
    ):
        if source_resolution.get("research_windows") != dict(research_windows):
            raise ValueError(
                f"{BLOCK_EVO_DATA_BOUNDARY}:data_api_resolution.research_windows"
            )
        serialized_resolution = json.dumps(
            source_resolution, ensure_ascii=False, sort_keys=True
        ).lower()
        if any(
            token in serialized_resolution
            for token in (
                "s3://",
                "amazonaws.com",
                "/home/ubuntu/",
                "aws_access_key_id",
                "aws_secret_access_key",
                "aws_session_token",
            )
        ):
            raise ValueError(
                f"{BLOCK_EVO_DATA_BOUNDARY}:data_api_resolution.source_authority"
            )
        payload["data_api_resolution"] = json.loads(
            json.dumps(source_resolution)
        )
    else:
        # Do not turn an absent/legacy proof into a ready-looking sentinel.
        # validate_step3 emits the explicit formal-evidence blocker.
        payload["data_api_resolution"] = {
            "contract_version": CLOSED_DATA_API_RESOLUTION_VERSION,
            "status": "sample_data_evidence_missing",
            "research_windows": dict(research_windows),
        }
    for key in ("coverage_checks", "blocked_items", "implementation_notes"):
        if key in payload:
            payload[key] = _scrub_host_source_details(payload[key])

    contract = payload.get("step4_data_contract")
    if contract is None:
        return payload
    if not isinstance(contract, dict):
        raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:step4_data_contract")
    contract["minute_derived_state_requirements"] = []
    contract.pop("catalog_path", None)
    contract.pop("state_catalog_path", None)
    for query_set in ("full_queries", "sample_queries"):
        raw_queries = contract.get(query_set)
        if raw_queries is None:
            continue
        if not isinstance(raw_queries, dict):
            raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{query_set}")
        bounded: dict[str, Any] = {}
        for name, raw_query in raw_queries.items():
            if name == "minute_bar":
                continue
            if name not in ALLOWED_PRE_RELEASE_DAILY_DATASETS:
                raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{query_set}.{name}")
            if not isinstance(raw_query, dict):
                raise ValueError(f"{BLOCK_EVO_DATA_BOUNDARY}:{query_set}.{name}")
            query = json.loads(json.dumps(raw_query))
            query.pop("catalog_path", None)
            query.pop("uri", None)
            query.pop("path", None)
            if str(query.get("dataset") or name) != name:
                raise ValueError(
                    f"{BLOCK_EVO_DATA_BOUNDARY}:{query_set}.{name}.dataset"
                )
            query_start = compact_date(query.get("start_date") or is_start)
            if query_start > is_end:
                raise ValueError(
                    f"{BLOCK_EVO_DATA_BOUNDARY}:{query_set}.{name}.start_date"
                )
            query["start_date"] = query_start
            query["end_date"] = is_end
            bounded[name] = query
        contract[query_set] = bounded
    window_contract = contract.get("research_window_contract")
    if isinstance(window_contract, dict):
        for key in ("requested_end", "query_end", "end"):
            if key in window_contract:
                window_contract[key] = is_end
    return payload


def install_agent_execution_isolation() -> None:
    """Strip cloud authority and deny Python socket access before Agent code."""

    sensitive_prefixes = (
        "AWS_",
        "S3_",
        "FACTORFORGE_DATA_API_",
        "FACTORFORGE_DATA_CATALOG",
        "FACTORFORGE_READONLY_",
    )
    for key in list(os.environ):
        if key.startswith(sensitive_prefixes):
            os.environ.pop(key, None)
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

    global _AGENT_EXECUTION_ISOLATION_ACTIVE
    _AGENT_EXECUTION_ISOLATION_ACTIVE = True

    def deny_network(event: str, _args: tuple[Any, ...]) -> None:
        if not _AGENT_EXECUTION_ISOLATION_ACTIVE:
            return
        if event in {
            "socket.connect",
            "socket.bind",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.posix_spawnp",
            "ctypes.dlopen",
            "ctypes.dlsym",
        }:
            raise PermissionError(
                "BLOCK_FACTORFORGE_AGENT_EXECUTION_EXTERNAL_ACCESS_FORBIDDEN"
            )

    sys.addaudithook(deny_network)


def end_agent_execution_isolation() -> None:
    global _AGENT_EXECUTION_ISOLATION_ACTIVE
    _AGENT_EXECUTION_ISOLATION_ACTIVE = False


__all__ = [
    "ALLOWED_PRE_RELEASE_DAILY_DATASETS",
    "BLOCK_EVO_DATA_BOUNDARY",
    "BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_INVALID",
    "BLOCK_STEP3A_SAMPLE_DATA_EVIDENCE_MISSING",
    "CLOSED_DATA_API_RESOLUTION_VERSION",
    "FORBIDDEN_PRE_RELEASE_LOCAL_INPUTS",
    "PRE_RELEASE_DAILY_PATH_KEYS",
    "build_closed_pre_release_data_resolution",
    "canonical_clean_daily_query_fields",
    "canonical_step3_sample_query",
    "compact_date",
    "install_agent_execution_isolation",
    "end_agent_execution_isolation",
    "project_pre_release_data_access",
    "resolve_evo_pre_release_research_windows",
    "validate_closed_pre_release_data_resolution",
]
