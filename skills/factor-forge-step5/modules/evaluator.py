from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


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


def collect_backend_runs(frm: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = frm.get("evaluation_results") or {}
    backend_runs = results.get("backend_runs") or []
    return [item for item in backend_runs if isinstance(item, dict)]


def _extract_key_metrics(payload: Dict[str, Any], run_item: Dict[str, Any]) -> Dict[str, Any]:
    metric_candidates = [
        payload.get("summary") if isinstance(payload.get("summary"), dict) else None,
        payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None,
        run_item.get("summary") if isinstance(run_item.get("summary"), dict) else None,
    ]
    merged: Dict[str, Any] = {}
    for candidate in metric_candidates:
        if isinstance(candidate, dict):
            merged.update(candidate)

    wanted = [
        "rank_ic_mean",
        "rank_ic_std",
        "rank_ic_ir",
        "pearson_ic_mean",
        "pearson_ic_std",
        "pearson_ic_ir",
        "annual_return",
        "max_drawdown",
        "sharpe",
        "turnover_mean",
    ]
    return {key: merged.get(key) for key in wanted if key in merged}


def read_backend_payloads(backend_runs: List[Dict[str, Any]], report_id: str, workspace_root: str | Path) -> List[Dict[str, Any]]:
    root = Path(workspace_root)
    payloads: List[Dict[str, Any]] = []
    seen = set()

    for item in backend_runs:
        payload_path = item.get("payload_path")
        payload = None
        if payload_path and Path(payload_path).exists():
            payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
            seen.add(str(Path(payload_path).resolve()))
        payloads.append(
            {
                "backend": item.get("backend") or item.get("name"),
                "status": item.get("status"),
                "payload_path": payload_path,
                "payload": payload,
                "key_metrics": _extract_key_metrics(payload or {}, item),
                "artifact_paths": item.get("artifact_paths") or [],
            }
        )

    eval_dir = root / "factorforge" / "evaluations" / report_id
    if eval_dir.exists():
        for payload_file in eval_dir.glob("**/evaluation_payload.json"):
            resolved = str(payload_file.resolve())
            if resolved in seen:
                continue
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
            payloads.append(
                {
                    "backend": payload_file.parent.name,
                    "status": payload.get("status") or "unknown",
                    "payload_path": str(payload_file),
                    "payload": payload,
                    "key_metrics": _extract_key_metrics(payload, {}),
                    "artifact_paths": payload.get("artifact_paths") or [],
                }
            )

    return payloads


def build_factor_evaluation(bundle: Dict[str, Any]) -> Dict[str, Any]:
    frm = bundle["objects"].get("factor_run_master") or {}
    report_id = bundle["report_id"]
    factor_id = frm.get("factor_id")
    backend_runs = collect_backend_runs(frm)
    payloads = read_backend_payloads(backend_runs, report_id=report_id, workspace_root=bundle["workspace_root"])
    diag = _get_diagnostic_summary(frm)

    artifact_ready = frm.get("run_status") != "failed" and bool(
        [p for p in (frm.get("output_paths") or []) if Path(p).exists()]
    )

    evaluation = {
        "report_id": report_id,
        "factor_id": factor_id,
        "evaluation_status": None,
        "artifact_ready": artifact_ready,
        "run_status": frm.get("run_status"),
        "coverage_summary": {
            "row_count": diag.get("row_count"),
            "date_count": diag.get("date_count"),
            "ticker_count": diag.get("ticker_count"),
            "coverage_ratio": diag.get("coverage_ratio"),
            "sample_window_actual": diag.get("sample_window_actual") or frm.get("sample_window_actual"),
        },
        "backend_summary": [
            {
                "backend": item.get("backend"),
                "status": item.get("status"),
                "payload_path": item.get("payload_path"),
                "key_metrics": item.get("key_metrics") or {},
                "artifact_paths": item.get("artifact_paths") or [],
            }
            for item in payloads
        ],
        "warnings": list(frm.get("key_warnings") or []),
        "failure_reason": frm.get("failure_reason"),
        "source_paths": [
            bundle["paths"].get("factor_run_master"),
            bundle["paths"].get("handoff_to_step5"),
            *[item.get("payload_path") for item in payloads if item.get("payload_path")],
        ],
    }
    return evaluation
