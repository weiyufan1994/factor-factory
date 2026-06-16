from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_DEPENDENCY_CONTRACT_VERSION = "factorforge_state_dependency_contract_v1"
STATE_RESOLUTION_VERSION = "factorforge_state_resolution_v1"
DATA_REQUEST_VERSION = "factorforge_data_request_v1"
STATE_DATAMART_REUSE_VERSION = "factorforge_state_datamart_reuse_v1"
REVISION_DATA_PLAN_VERSION = "factorforge_revision_data_plan_v1"

BLOCK_STATE_DEPENDENCY_UNDECLARED = "BLOCK_FACTORFORGE_STATE_DEPENDENCY_UNDECLARED"
BLOCK_STATE_RESOLUTION_MISSING = "BLOCK_FACTORFORGE_STATE_RESOLUTION_MISSING"
BLOCK_STATE_DATAMART_MISSING = "BLOCK_FACTORFORGE_STATE_DATAMART_MISSING"
BLOCK_STATE_DATAMART_QA_NOT_ACCEPTED = "BLOCK_FACTORFORGE_STATE_DATAMART_QA_NOT_ACCEPTED"
BLOCK_STATE_SCHEMA_VERSION_MISMATCH = "BLOCK_FACTORFORGE_STATE_SCHEMA_VERSION_MISMATCH"
BLOCK_STATE_COVERAGE_INSUFFICIENT = "BLOCK_FACTORFORGE_STATE_COVERAGE_INSUFFICIENT"
BLOCK_STATE_LOOKAHEAD_CONTRACT_MISSING = "BLOCK_FACTORFORGE_STATE_LOOKAHEAD_CONTRACT_MISSING"
BLOCK_DATA_REQUEST_REQUIRED = "BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED"
BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN = "BLOCK_FACTORFORGE_RAW_MINUTE_FULL_WINDOW_FORBIDDEN"
BLOCK_STATE_REUSE_PROVENANCE_MISSING = "BLOCK_FACTORFORGE_STATE_REUSE_PROVENANCE_MISSING"
BLOCK_REVISION_DATA_PLAN_MISSING = "BLOCK_FACTORFORGE_REVISION_DATA_PLAN_MISSING"
BLOCK_REVISION_DATA_PLAN_INVALID = "BLOCK_FACTORFORGE_REVISION_DATA_PLAN_INVALID"


class StateReuseBlock(RuntimeError):
    def __init__(self, token: str, message: str) -> None:
        self.token = token
        super().__init__(f"{token}: {message}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_id(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    return text or "unknown"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_state_dependency_contract(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if isinstance(payload.get("state_dependency_contract"), dict):
        payload = payload["state_dependency_contract"]
    return payload


def validate_state_dependency_contract(contract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not contract:
        return [f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: empty contract"]
    if contract.get("contract_version") != STATE_DEPENDENCY_CONTRACT_VERSION:
        failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: contract_version")
    datasets = contract.get("required_datasets")
    if not isinstance(datasets, list):
        failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: required_datasets")
        return failures
    for idx, item in enumerate(datasets):
        if not isinstance(item, dict):
            failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: required_datasets[{idx}]")
            continue
        if not item.get("dataset_id"):
            failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: required_datasets[{idx}].dataset_id")
        if item.get("required_fields") is not None and not isinstance(item.get("required_fields"), list):
            failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: required_datasets[{idx}].required_fields")
    if contract.get("allowed_missing_behavior", "block") != "block":
        failures.append(f"{BLOCK_STATE_DEPENDENCY_UNDECLARED}: allowed_missing_behavior must be block")
    if contract.get("raw_minute_full_window_allowed") is not False:
        failures.append(f"{BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN}: raw_minute_full_window_allowed must be false")
    return failures


def _catalog_entries(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = catalog.get("datasets", catalog)
    if isinstance(raw, dict):
        return {
            str(dataset_id): dict(entry)
            for dataset_id, entry in raw.items()
            if isinstance(entry, dict)
        }
    if isinstance(raw, list):
        result: dict[str, dict[str, Any]] = {}
        for entry in raw:
            if isinstance(entry, dict) and entry.get("dataset_id"):
                result[str(entry["dataset_id"])] = dict(entry)
        return result
    return {}


def _date_value(raw: Any) -> str | None:
    if raw is None:
        return None
    text = re.sub(r"[^0-9]", "", str(raw))
    return text or None


def _coverage(entry: dict[str, Any]) -> dict[str, Any]:
    raw = entry.get("coverage") if isinstance(entry.get("coverage"), dict) else {}
    return {
        "start": _date_value(raw.get("start") or entry.get("start")),
        "end": _date_value(raw.get("end") or entry.get("end")),
    }


def _required_window(dataset: dict[str, Any]) -> dict[str, Any]:
    raw = dataset.get("window") if isinstance(dataset.get("window"), dict) else {}
    return {
        "start": _date_value(raw.get("start") or dataset.get("start")),
        "end": _date_value(raw.get("end") or dataset.get("end")),
    }


def _coverage_ok(entry: dict[str, Any], requirement: dict[str, Any]) -> bool:
    coverage = _coverage(entry)
    window = _required_window(requirement)
    if window.get("start") and (not coverage.get("start") or coverage["start"] > window["start"]):
        return False
    if window.get("end") and (not coverage.get("end") or coverage["end"] < window["end"]):
        return False
    return True


def _schema_fields(entry: dict[str, Any]) -> set[str]:
    raw_schema = entry.get("schema")
    if isinstance(raw_schema, list):
        fields: set[str] = set()
        for item in raw_schema:
            if isinstance(item, str):
                fields.add(item)
            elif isinstance(item, dict) and item.get("name"):
                fields.add(str(item["name"]))
        return fields
    raw_fields = entry.get("fields")
    if isinstance(raw_fields, list):
        return {str(item) for item in raw_fields if item}
    return set()


def _qa_accepted(entry: dict[str, Any]) -> bool:
    value = entry.get("qa_verdict") or entry.get("verdict") or entry.get("latest_reviewer_verdict")
    return str(value or "").upper() == "ACCEPT"


def _lookahead_present(entry: dict[str, Any]) -> bool:
    return bool(entry.get("lookahead_policy") or entry.get("no_future_intraday_minutes") is True)


def _schema_version_ok(entry: dict[str, Any], requirement: dict[str, Any]) -> bool:
    required = requirement.get("schema_version")
    if not required:
        return True
    return str(entry.get("schema_version") or "") == str(required)


def _fields_present(entry: dict[str, Any], requirement: dict[str, Any]) -> bool:
    required = {str(item) for item in (requirement.get("required_fields") or [])}
    if not required:
        return True
    return required.issubset(_schema_fields(entry))


def _entry_path(entry: dict[str, Any]) -> str | None:
    return (
        entry.get("catalog_entry_path")
        or entry.get("catalog_path")
        or entry.get("path")
    )


def _materialized_root(entry: dict[str, Any]) -> str | None:
    return (
        entry.get("materialized_root")
        or entry.get("output_root")
        or entry.get("root")
        or entry.get("source_uri")
    )


def build_data_request(
    *,
    missing_dataset: dict[str, Any],
    report_id: str,
    factor_id: str | None,
    research_id: str | None,
    reason: str = "state_datamart_missing",
) -> dict[str, Any]:
    dataset_id = str(missing_dataset.get("dataset_id") or "unknown_state")
    return {
        "contract_version": DATA_REQUEST_VERSION,
        "request_id": f"data_request__{safe_id(report_id)}__{safe_id(dataset_id)}",
        "request_type": reason,
        "dataset_id": dataset_id,
        "required_schema_version": missing_dataset.get("schema_version"),
        "required_fields": list(missing_dataset.get("required_fields") or []),
        "required_coverage": _required_window(missing_dataset),
        "parameters": dict(missing_dataset.get("parameters") or {}),
        "lookahead_policy_required": bool(missing_dataset.get("lookahead_policy_required")),
        "consumer": {
            "factor_id": factor_id,
            "research_id": research_id,
            "report_id": report_id,
        },
        "status": "requested",
        "production_execution_allowed": False,
        "created_at_utc": utc_now(),
    }


def resolve_state_dependencies(
    *,
    contract: dict[str, Any],
    catalog: dict[str, Any],
    report_id: str,
    factor_id: str | None = None,
    research_id: str | None = None,
    dependency_contract_path: str | None = None,
    catalog_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures = validate_state_dependency_contract(contract)
    if failures:
        return {
            "contract_version": STATE_RESOLUTION_VERSION,
            "report_id": report_id,
            "factor_id": factor_id,
            "research_id": research_id,
            "resolved_at_utc": utc_now(),
            "dependency_contract_path": dependency_contract_path,
            "catalog_source": catalog_source or {},
            "reuse_hits": [],
            "missing_state_variables": [],
            "data_requests": [],
            "data_request_ids": [],
            "blocked": True,
            "blocker_token": failures[0].split(":", 1)[0],
            "failures": failures,
        }
    entries = _catalog_entries(catalog)
    reuse_hits: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    data_requests: list[dict[str, Any]] = []
    failures = []
    for requirement in contract.get("required_datasets") or []:
        dataset_id = str(requirement.get("dataset_id") or "")
        entry = entries.get(dataset_id)
        reason = None
        token = None
        if not entry or entry.get("deprecated") is True:
            token = BLOCK_STATE_DATAMART_MISSING
            reason = "state_datamart_missing"
        elif not _schema_version_ok(entry, requirement):
            token = BLOCK_STATE_SCHEMA_VERSION_MISMATCH
            reason = "state_schema_version_mismatch"
        elif not _fields_present(entry, requirement):
            token = BLOCK_STATE_SCHEMA_VERSION_MISMATCH
            reason = "state_required_fields_missing"
        elif requirement.get("qa_required") is True and not _qa_accepted(entry):
            token = BLOCK_STATE_DATAMART_QA_NOT_ACCEPTED
            reason = "state_datamart_qa_not_accepted"
        elif not _coverage_ok(entry, requirement):
            token = BLOCK_STATE_COVERAGE_INSUFFICIENT
            reason = "state_coverage_insufficient"
        elif requirement.get("lookahead_policy_required") is True and not _lookahead_present(entry):
            token = BLOCK_STATE_LOOKAHEAD_CONTRACT_MISSING
            reason = "state_lookahead_contract_missing"
        if token:
            item = dict(requirement)
            item["blocker_token"] = token
            item["reason"] = reason
            missing.append(item)
            failures.append(f"{token}: {dataset_id} {reason}")
            if contract.get("data_request_on_missing") is True:
                data_requests.append(
                    build_data_request(
                        missing_dataset=requirement,
                        report_id=report_id,
                        factor_id=factor_id,
                        research_id=research_id,
                        reason=str(reason),
                    )
                )
            continue
        coverage = _coverage(entry)
        fields = requirement.get("required_fields") or []
        reuse_hits.append(
            {
                "dataset_id": dataset_id,
                "schema_version": entry.get("schema_version"),
                "catalog_entry_path": _entry_path(entry),
                "qa_path": entry.get("qa_path"),
                "qa_verdict": entry.get("qa_verdict") or entry.get("verdict"),
                "coverage": coverage,
                "required_fields": fields,
                "required_fields_present": True,
                "lookahead_policy_present": _lookahead_present(entry),
                "materialized_root": _materialized_root(entry),
            }
        )
    blocked = bool(failures)
    blocker_token = None
    if blocked:
        if data_requests:
            blocker_token = BLOCK_DATA_REQUEST_REQUIRED
        else:
            blocker_token = failures[0].split(":", 1)[0]
    return {
        "contract_version": STATE_RESOLUTION_VERSION,
        "report_id": report_id,
        "factor_id": factor_id,
        "research_id": research_id,
        "resolved_at_utc": utc_now(),
        "dependency_contract_path": dependency_contract_path,
        "catalog_source": catalog_source or {},
        "reuse_hits": reuse_hits,
        "missing_state_variables": missing,
        "data_requests": data_requests,
        "data_request_ids": [request["request_id"] for request in data_requests],
        "blocked": blocked,
        "blocker_token": blocker_token,
        "failures": failures,
    }


def write_resolution_outputs(
    *,
    resolution: dict[str, Any],
    state_resolution_path: Path,
    data_request_dir: Path | None = None,
) -> list[Path]:
    written = [write_json(state_resolution_path, resolution)]
    if data_request_dir:
        for request in resolution.get("data_requests") or []:
            request_path = Path(data_request_dir) / f"{safe_id(request.get('request_id'))}.json"
            written.append(write_json(request_path, request))
    return written


def load_state_resolution(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("contract_version") != STATE_RESOLUTION_VERSION:
        raise StateReuseBlock(BLOCK_STATE_RESOLUTION_MISSING, f"unsupported state_resolution contract at {path}")
    return payload


def require_state_resolution_ready(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    if not path.exists():
        raise StateReuseBlock(BLOCK_STATE_RESOLUTION_MISSING, str(path))
    resolution = load_state_resolution(path)
    if resolution.get("blocked") is True:
        token = str(resolution.get("blocker_token") or BLOCK_DATA_REQUEST_REQUIRED)
        raise StateReuseBlock(token, f"state resolution blocked: {path}")
    if not resolution.get("reuse_hits"):
        raise StateReuseBlock(BLOCK_STATE_REUSE_PROVENANCE_MISSING, f"no reuse_hits in {path}")
    return resolution


def build_step4_state_reuse_provenance(
    *,
    state_resolution_path: Path,
    bounded_smoke: bool = False,
    raw_minute_full_window_scan: bool = False,
) -> dict[str, Any]:
    resolution = require_state_resolution_ready(state_resolution_path)
    return {
        "contract_version": STATE_DATAMART_REUSE_VERSION,
        "state_resolution_path": str(Path(state_resolution_path).expanduser()),
        "reuse_hit": bool(resolution.get("reuse_hits")),
        "datasets": [
            {
                "dataset_id": item.get("dataset_id"),
                "schema_version": item.get("schema_version"),
                "fields_read": item.get("required_fields") or [],
                "materialized_root": item.get("materialized_root"),
            }
            for item in (resolution.get("reuse_hits") or [])
            if isinstance(item, dict)
        ],
        "raw_minute_full_window_scan": bool(raw_minute_full_window_scan),
        "bounded_smoke": bool(bounded_smoke),
    }


def _looks_like_raw_minute_path(raw: Any) -> bool:
    text = str(raw or "").lower()
    normalized = text.replace("\\", "/")
    if not normalized:
        return False
    raw_markers = ("/raw/", "raw_", "raw-", "tushares/分钟数据", "stk_mins_1min", "minute/raw")
    minute_markers = ("minute", "mins_1min", "分钟", "1min", "intraday")
    return any(marker in normalized for marker in raw_markers) and any(marker in normalized for marker in minute_markers)


def assert_no_raw_minute_full_window_scan(
    *,
    input_paths: list[Path | str],
    production: bool,
    explicit_data_production_context: bool = False,
) -> None:
    if not production or explicit_data_production_context:
        return
    offenders = [str(path) for path in input_paths if _looks_like_raw_minute_path(path)]
    if offenders:
        raise StateReuseBlock(
            BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN,
            "production Step4 must consume ACCEPT state datamarts, not raw minute roots: "
            + ", ".join(offenders),
        )


def validate_revision_data_plan(plan: dict[str, Any]) -> list[str]:
    if not plan:
        return [f"{BLOCK_REVISION_DATA_PLAN_MISSING}: revision_data_plan"]
    failures: list[str] = []
    if plan.get("contract_version") != REVISION_DATA_PLAN_VERSION:
        failures.append(f"{BLOCK_REVISION_DATA_PLAN_INVALID}: contract_version")
    if plan.get("new_state_required") is True and plan.get("data_request_required") is not True:
        failures.append(f"{BLOCK_DATA_REQUEST_REQUIRED}: new_state_required without data_request_required")
    if plan.get("portfolio_only_revision") is True and plan.get("factor_value_recompute_required") is True and not plan.get("override_reason"):
        failures.append(f"{BLOCK_REVISION_DATA_PLAN_INVALID}: portfolio_only_revision recompute requires override_reason")
    if plan.get("raw_minute_full_window_allowed") is True and plan.get("data_api_production_context") is not True:
        failures.append(f"{BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN}: revision_data_plan raw_minute_full_window_allowed")
    return failures


def portfolio_only_revision_allows_skip(plan: dict[str, Any]) -> bool:
    return (
        plan.get("contract_version") == REVISION_DATA_PLAN_VERSION
        and plan.get("portfolio_only_revision") is True
        and plan.get("factor_value_recompute_required") is False
        and not validate_revision_data_plan(plan)
    )
