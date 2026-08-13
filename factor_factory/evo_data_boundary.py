from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
)


BLOCK_EVO_DATA_BOUNDARY = (
    "BLOCK_FACTORFORGE_EVO_PRE_RELEASE_DATA_BOUNDARY_INVALID"
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
    for key in PRE_RELEASE_DAILY_PATH_KEYS:
        safe_ref = _safe_workspace_relative_ref(source.get(key))
        if safe_ref:
            projected[key] = safe_ref
    projected["input_mode"] = (
        "alternative_daily_plus_clean_daily"
        if any(
            projected.get(key)
            for key in ("signal_daily_df_parquet", "signal_daily_df_csv")
        )
        else "daily_only"
    )
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
    full_csv = projected.get("daily_df_csv")
    sample_csv = projected.get("daily_df_csv_sample")
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
    payload["data_api_resolution"] = {
        "status": "HOST_PRIVATE_FETCH_AUTHORITY_REDACTED"
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
    "FORBIDDEN_PRE_RELEASE_LOCAL_INPUTS",
    "PRE_RELEASE_DAILY_PATH_KEYS",
    "compact_date",
    "install_agent_execution_isolation",
    "end_agent_execution_isolation",
    "project_pre_release_data_access",
    "resolve_evo_pre_release_research_windows",
]
