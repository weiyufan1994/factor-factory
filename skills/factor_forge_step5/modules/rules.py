from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

VALID_FINAL_STATUS = {"validated", "partial", "failed"}


def _resolve_factorforge_root(root: Path) -> Path:
    if (root / "objects").exists():
        return root
    return root / "factorforge"


def _get_diagnostic_summary(frm: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(frm.get("diagnostic_summary"), dict):
        return frm["diagnostic_summary"]
    summary = {}
    for key in ("row_count", "date_count", "ticker_count", "coverage_ratio"):
        if key in frm:
            summary[key] = frm.get(key)
    if isinstance(frm.get("sample_window_actual"), dict):
        summary["sample_window_actual"] = frm.get("sample_window_actual")
    return summary


def load_step5_inputs(report_id: str, workspace_root: str | Path) -> Dict[str, Any]:
    root = Path(workspace_root)
    ff_root = _resolve_factorforge_root(root)
    obj = ff_root / "objects"

    paths = {
        "factor_run_master": obj / "factor_run_master" / f"factor_run_master__{report_id}.json",
        "handoff_to_step5": obj / "handoff" / f"handoff_to_step5__{report_id}.json",
        "factor_spec_master": obj / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        "data_prep_master": obj / "data_prep_master" / f"data_prep_master__{report_id}.json",
    }

    bundle: Dict[str, Any] = {
        "report_id": report_id,
        "workspace_root": str(root),
        "factorforge_root": str(ff_root),
        "paths": {name: str(path) for name, path in paths.items()},
        "objects": {},
        "missing_optional": [],
    }

    import json

    for name, path in paths.items():
        if path.exists():
            bundle["objects"][name] = json.loads(path.read_text(encoding="utf-8"))
        elif name in {"factor_run_master", "handoff_to_step5"}:
            raise FileNotFoundError(f"required step5 input missing: {path}")
        else:
            bundle["objects"][name] = None
            bundle["missing_optional"].append(name)

    return bundle


def validate_input_consistency(bundle: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    report_id = bundle["report_id"]
    objects = bundle["objects"]

    report_ids = {}
    factor_ids = {}
    for name, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if "report_id" in obj:
            report_ids[name] = obj.get("report_id")
        if "factor_id" in obj:
            factor_ids[name] = obj.get("factor_id")

    for name, rid in report_ids.items():
        if rid != report_id:
            errors.append(f"report_id mismatch in {name}: expected {report_id}, got {rid}")

    distinct_factor_ids = {v for v in factor_ids.values() if v is not None}
    if len(distinct_factor_ids) > 1:
        errors.append(f"factor_id mismatch across inputs: {sorted(distinct_factor_ids)}")

    handoff = objects.get("handoff_to_step5") or {}
    frm = objects.get("factor_run_master") or {}

    ref = handoff.get("factor_run_master_path")
    actual_frm_path = bundle["paths"].get("factor_run_master")
    if ref and actual_frm_path and str(ref) != str(actual_frm_path):
        warnings.append(
            f"handoff_to_step5.factor_run_master_path differs from expected path: {ref} != {actual_frm_path}"
        )

    can_enter = frm.get("can_enter_step5")
    if can_enter is False:
        warnings.append("factor_run_master.can_enter_step5 is false; Step 5 should not claim validated")

    return (len(errors) == 0, errors, warnings)


def determine_final_status(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> str:
    frm = bundle["objects"].get("factor_run_master") or {}
    quality_gate = evaluation.get("step4_quality_gate") or {}
    if quality_gate.get("verdict") == "BLOCK":
        return "failed"

    run_status = frm.get("run_status")
    backend_summary = evaluation.get("backend_summary") or []
    successful_backend_count = sum(1 for item in backend_summary if item.get("status") == "success")
    metric_bundle: Dict[str, Any] = {}
    for item in backend_summary:
        if isinstance(item.get("key_metrics"), dict):
            metric_bundle.update(item["key_metrics"])
    required_long_side = [
        "long_side_annual_return",
        "long_side_annual_volatility",
        "long_side_sharpe",
        "long_side_max_drawdown",
        "long_side_recovery_days",
        "long_side_turnover_mean_daily",
        "trading_cogs_daily",
        "trading_cogs_annual",
        "cost_adjusted_annual_return",
        "cost_adjusted_long_side_sharpe",
    ]
    long_side_evidence_complete = all(metric_bundle.get(key) is not None for key in required_long_side)
    revenue = metric_bundle.get("long_side_annual_return")
    volatility = metric_bundle.get("long_side_annual_volatility")
    drawdown = metric_bundle.get("long_side_max_drawdown")
    trading_cogs_annual = metric_bundle.get("trading_cogs_annual")
    try:
        economic_net_alpha = (
            float(revenue)
            - float(trading_cogs_annual)
            - 0.5 * float(volatility) * float(volatility)
            - 0.03 * (2.0 * abs(float(volatility)))
            - abs(float(drawdown)) / 6.0
        )
    except Exception:
        economic_net_alpha = None
    factor_business_quality_complete = economic_net_alpha is not None
    output_paths = frm.get("output_paths") or []
    existing_outputs = [p for p in output_paths if Path(p).exists()]
    artifact_ready = bool(evaluation.get("artifact_ready"))
    can_enter = frm.get("can_enter_step5")

    if run_status == "failed":
        return "failed"

    if can_enter is False:
        return "failed" if not existing_outputs else "partial"

    if run_status == "partial":
        return "partial"

    if run_status == "success":
        if artifact_ready and existing_outputs and successful_backend_count >= 1 and long_side_evidence_complete and factor_business_quality_complete:
            return "validated"
        return "partial"

    if existing_outputs or successful_backend_count >= 1:
        return "partial"

    return "failed"


def build_evaluation_summary(frm: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    diag = _get_diagnostic_summary(frm)
    backend_summary = evaluation.get("backend_summary") or []
    successful_backend_count = sum(1 for item in backend_summary if item.get("status") == "success")
    return {
        "artifact_ready": bool(evaluation.get("artifact_ready")),
        "row_count": diag.get("row_count"),
        "date_count": diag.get("date_count"),
        "ticker_count": diag.get("ticker_count"),
        "backend_count": len(backend_summary),
        "successful_backend_count": successful_backend_count,
        "step4_quality_gate_verdict": (evaluation.get("step4_quality_gate") or {}).get("verdict"),
        "step4_quality_gate_blocking_issue_count": (evaluation.get("step4_quality_gate") or {}).get("blocking_issue_count"),
    }
