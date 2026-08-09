from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from factor_factory.miner.common import normalize_catalog_entries, read_json, utc_now, workspace_path, write_json, write_markdown
from factor_factory.miner.template_registry import load_template_registry


KNOWN_OPERATORS: list[dict[str, Any]] = [
    {"operator_id": "rank", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "cross-sectional rank"},
    {"operator_id": "zscore", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "standardization"},
    {"operator_id": "return", "source_module": "factor_factory.formula.operators", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "path return primitive"},
    {"operator_id": "skew", "source_module": "factor_factory.data_api.flow_distribution_moments", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "distribution moment"},
    {"operator_id": "kurtosis", "source_module": "factor_factory.data_api.flow_distribution_moments", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "distribution moment"},
    {"operator_id": "sum", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "aggregation"},
    {"operator_id": "divide", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "ratio"},
    {"operator_id": "weighted_mean", "source_module": "factor_factory.data_api.intraday_operator_kernels", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "volume/amount weighted aggregation"},
    {"operator_id": "weighted_sum", "source_module": "factor_factory.data_api.intraday_operator_kernels", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "weighted aggregation"},
    {"operator_id": "price_location", "source_module": "factor_factory.data_api.value_occupation", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "range location"},
    {"operator_id": "range", "source_module": "factor_factory.data_api.intraday_operator_kernels", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "high-low range"},
    {"operator_id": "square", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "power transform"},
    {"operator_id": "sign", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "sign transform"},
    {"operator_id": "delta", "source_module": "factor_factory.formula.operators", "input_grain": "daily", "supported_for_batch_screen": True, "notes": "time delta"},
    {"operator_id": "decay", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "decay weighting"},
    {"operator_id": "distance", "source_module": "factor_factory.data_api.value_occupation", "input_grain": "state", "supported_for_batch_screen": True, "notes": "state distance"},
    {"operator_id": "bucket", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "bucket assignment"},
    {"operator_id": "residualize", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "cross-sectional residualization"},
    {"operator_id": "multiply", "source_module": "factor_factory.formula.operators", "input_grain": "panel", "supported_for_batch_screen": True, "notes": "interaction"},
    {"operator_id": "segment_return", "source_module": "factor_factory.data_api.daily_technical_state", "input_grain": "minute", "supported_for_batch_screen": True, "notes": "open/close segment return"},
]


def _operator_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in KNOWN_OPERATORS:
        row = dict(raw)
        source_available = importlib.util.find_spec(str(row["source_module"])) is not None
        row["source_available"] = source_available
        row["supported_for_batch_screen"] = bool(row.get("supported_for_batch_screen")) and source_available
        if not source_available:
            row["notes"] = f"{row.get('notes', '')}; source_module_missing"
        rows.append(row)
    return rows


def _dataset_id(entry: dict[str, Any]) -> str:
    return str(entry.get("dataset_id") or entry.get("id") or entry.get("name") or "")


def _fields(entry: dict[str, Any]) -> list[str]:
    fields = entry.get("columns", entry.get("fields", entry.get("schema")))
    if isinstance(fields, dict):
        return [str(key) for key in fields.keys()]
    if isinstance(fields, list):
        out: list[str] = []
        for item in fields:
            if isinstance(item, dict):
                out.append(str(item.get("name") or item.get("field") or ""))
            else:
                out.append(str(item))
        return [item for item in out if item]
    return []


def _metadata(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("metadata")
    return value if isinstance(value, dict) else {}


def _qa(entry: dict[str, Any]) -> str:
    metadata = _metadata(entry)
    return str(entry.get("qa_verdict") or metadata.get("qa_verdict") or metadata.get("reviewer_verdict") or "unknown")


def _coverage(entry: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(entry)
    value = entry.get("coverage") or metadata.get("coverage") or {
        "start": metadata.get("start") or metadata.get("start_date"),
        "end": metadata.get("end") or metadata.get("end_date"),
    }
    return value if isinstance(value, dict) else {}


def _lookahead(entry: dict[str, Any]) -> str:
    metadata = _metadata(entry)
    value = entry.get("lookahead_policy") or metadata.get("lookahead_policy")
    if value:
        return str(value)
    if str(metadata.get("no_future_intraday_minutes")).lower() == "true":
        return "no_future_intraday_minutes"
    return "unknown"


def _miner_use(dataset_id: str) -> str:
    if dataset_id in {"minute_bar", "clean_daily_bar"}:
        return "direct_input"
    if dataset_id in {"cheap_screen_panel", "forward_return_panel"}:
        return "label_panel"
    if dataset_id in {"daily_basic", "tradability_risk_flags_daily"}:
        return "control_panel"
    if dataset_id.startswith("intraday_") or dataset_id.endswith("_state_v1") or dataset_id.endswith("_state_v2"):
        return "state_datamart"
    return "unsupported"


def _read_catalogs(catalog_paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    catalog_payloads: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    for raw in catalog_paths:
        path = Path(raw).expanduser()
        if not path.exists():
            catalog_payloads.append({"path_or_uri": str(path), "status": "catalog_missing"})
            continue
        payload = read_json(path)
        entries = normalize_catalog_entries(payload)
        catalog_payloads.append({"path_or_uri": str(path), "status": "loaded", "dataset_count": len(entries)})
        for entry in entries:
            dataset_id = _dataset_id(entry)
            if not dataset_id:
                continue
            datasets.append(
                {
                    "dataset_id": dataset_id,
                    "fields": _fields(entry),
                    "coverage": _coverage(entry),
                    "qa_status": _qa(entry),
                    "lookahead_policy": _lookahead(entry),
                    "materialized_root": str(entry.get("uri") or entry.get("materialized_root") or ""),
                    "miner_use": _miner_use(dataset_id),
                }
            )
    return catalog_payloads, datasets


def _dataset_quality_issues(dataset: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    qa_status = str(dataset.get("qa_status") or "unknown").upper()
    if qa_status != "ACCEPT":
        issues.append(f"{dataset['dataset_id']}:qa_status={dataset.get('qa_status')}")
    coverage = dataset.get("coverage") if isinstance(dataset.get("coverage"), dict) else {}
    if not coverage.get("start") or not coverage.get("end"):
        issues.append(f"{dataset['dataset_id']}:coverage_missing")
    dataset_id = str(dataset.get("dataset_id") or "")
    if (dataset_id == "minute_bar" or dataset_id.startswith("intraday_")) and dataset.get("lookahead_policy") == "unknown":
        issues.append(f"{dataset_id}:lookahead_policy_missing")
    return issues


def build_capability_inventory(*, campaign_id: str, workspace_root: Path, catalog_paths: list[Path] | None = None) -> dict[str, Any]:
    catalog_paths = list(catalog_paths or [])
    catalogs, datasets = _read_catalogs(catalog_paths)
    dataset_by_id = {row["dataset_id"]: row for row in datasets}
    operators = _operator_inventory()
    operator_by_id = {row["operator_id"]: row for row in operators}
    support: list[dict[str, Any]] = []
    for template in load_template_registry():
        missing_datasets = [ds for ds in template.get("required_datasets", []) if ds not in dataset_by_id]
        missing_fields: list[str] = []
        dataset_quality_issues: list[str] = []
        for ds in template.get("required_datasets", []):
            dataset = dataset_by_id.get(ds, {})
            fields = set(dataset.get("fields", []))
            if fields:
                missing_fields.extend([f"{ds}.{field}" for field in template.get("required_fields", []) if field not in fields])
            if dataset:
                dataset_quality_issues.extend(_dataset_quality_issues(dataset))
        missing_operators = [
            op
            for op in template.get("operator_dependencies", [])
            if op not in operator_by_id or not operator_by_id[op].get("supported_for_batch_screen")
        ]
        if missing_datasets:
            status = "needs_data"
        elif missing_operators:
            status = "needs_operator"
        elif missing_fields or dataset_quality_issues:
            status = "partial"
        else:
            status = "ready"
        support.append(
            {
                "template_id": template["template_id"],
                "support_status": status,
                "missing_datasets": missing_datasets,
                "missing_fields": missing_fields,
                "missing_operators": missing_operators,
                "dataset_quality_issues": dataset_quality_issues,
            }
        )
    inventory = {
        "version": "factorforge_miner_capability_inventory_v1",
        "campaign_id": campaign_id,
        "generated_at_utc": utc_now(),
        "data_api_catalogs": catalogs,
        "datasets": datasets,
        "operators": operators,
        "template_support": support,
    }
    write_json(workspace_path(workspace_root, "objects", "miner_capability_inventory.json", campaign_id=campaign_id), inventory)
    lines = [
        "# Miner Capability Inventory",
        "",
        f"campaign_id: `{campaign_id}`",
        "",
        "## Template Support",
        "",
        "| template_id | status | missing datasets | missing operators |",
        "|---|---|---|---|",
    ]
    for row in support:
        lines.append(
            f"| `{row['template_id']}` | `{row['support_status']}` | `{', '.join(row['missing_datasets'])}` | `{', '.join(row['missing_operators'])}` |"
        )
    write_markdown(workspace_path(workspace_root, "docs", "miner_capability_inventory.md", campaign_id=campaign_id), "\n".join(lines))
    return inventory
