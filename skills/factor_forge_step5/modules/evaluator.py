from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
from typing import Any, Dict, List


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


def collect_backend_runs(frm: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = frm.get("evaluation_results") or {}
    backend_runs = results.get("backend_runs") or []
    return [item for item in backend_runs if isinstance(item, dict)]


def _extract_key_metrics(payload: Dict[str, Any], run_item: Dict[str, Any]) -> Dict[str, Any]:
    metric_candidates = [
        payload.get("ic_summary") if isinstance(payload.get("ic_summary"), dict) else None,
        payload.get("group_backtest_summary") if isinstance(payload.get("group_backtest_summary"), dict) else None,
        payload.get("long_side_performance") if isinstance(payload.get("long_side_performance"), dict) else None,
        payload.get("native_backtest_metrics") if isinstance(payload.get("native_backtest_metrics"), dict) else None,
        payload.get("stub_backtest_metrics") if isinstance(payload.get("stub_backtest_metrics"), dict) else None,
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
        "metric_period",
        "annualization_factor",
        "long_side_mean_return_daily",
        "long_side_annual_return",
        "long_side_return_std_daily",
        "long_side_annual_volatility",
        "long_side_sharpe",
        "long_side_max_drawdown",
        "long_side_recovery_days",
        "long_side_turnover_mean_daily",
        "trading_cogs_daily",
        "trading_cogs_annual",
        "cost_adjusted_return_daily",
        "cost_adjusted_annual_return",
        "cost_adjusted_long_side_sharpe",
        "cost_adjusted_long_side_max_drawdown",
        "cost_adjusted_long_side_recovery_days",
        "result_interpretation",
        "top_decile_mean_return",
        "bottom_decile_mean_return",
        "long_short_spread_mean",
        "long_short_spread_std",
        "long_short_spread_ir",
        "long_short_final_nav",
        "group_member_count_min",
        "group_member_count_median",
        "group_member_count_max",
        "final_account",
        "mean_return",
        "nonzero_value_rows",
        "nonzero_turnover_rows",
    ]
    return {key: merged.get(key) for key in wanted if key in merged}


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    except Exception:
        return None


def _read_csv_table(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    csv_path = Path(path)
    if not csv_path.exists() or csv_path.stat().st_size <= 0:
        return None
    try:
        return pd.read_csv(csv_path)
    except Exception:
        return None


def _numeric_frame_is_finite(frame: pd.DataFrame, skip_columns: set[str] | None = None) -> bool:
    skip = skip_columns or set()
    numeric = frame[[col for col in frame.columns if col not in skip]].apply(pd.to_numeric, errors='coerce')
    return bool(not numeric.empty and numeric.notna().all().all() and numeric.map(math.isfinite).all().all())


def _validate_nav_table(path: str | None, expected_value_columns: int, table_name: str) -> list[Dict[str, Any]]:
    issues: list[Dict[str, Any]] = []
    frame = _read_csv_table(path)
    if frame is None or frame.empty:
        return [_issue('BLOCK', 'NAV_TABLE_UNREADABLE', f'{table_name} is missing, empty, or unreadable.', {'path': path})]
    value_columns = [col for col in frame.columns if col not in {'trade_date', 'datetime', 'date'}]
    if len(value_columns) != expected_value_columns:
        issues.append(_issue('BLOCK', 'NAV_TABLE_COLUMN_COUNT_MISMATCH', f'{table_name} has wrong number of value columns.', {'path': path, 'columns': value_columns}))
        return issues
    values = frame[value_columns].apply(pd.to_numeric, errors='coerce')
    if values.isna().any().any() or not values.map(math.isfinite).all().all():
        issues.append(_issue('BLOCK', 'NAV_TABLE_NONFINITE_VALUES', f'{table_name} contains NaN or infinite values.', {'path': path}))
        return issues
    first = values.iloc[0]
    if not ((first - 1.0).abs() <= 1e-6).all():
        issues.append(_issue('BLOCK', 'NAV_TABLE_NOT_NORMALIZED', f'{table_name} must start at 1.0 for every NAV series.', {'path': path, 'first_values': first.to_dict()}))
    if (values <= 0).any().any():
        issues.append(_issue('BLOCK', 'NAV_TABLE_NONPOSITIVE_VALUES', f'{table_name} contains non-positive NAV values.', {'path': path}))
    if (values > 1_000_000).any().any():
        issues.append(_issue('BLOCK', 'NAV_TABLE_EXPLOSIVE_VALUES', f'{table_name} contains explosively large NAV values.', {'path': path}))
    return issues


def _validate_return_table(path: str | None, expected_value_columns: int, table_name: str) -> list[Dict[str, Any]]:
    frame = _read_csv_table(path)
    if frame is None or frame.empty:
        return [_issue('BLOCK', 'RETURN_TABLE_UNREADABLE', f'{table_name} is missing, empty, or unreadable.', {'path': path})]
    value_columns = [col for col in frame.columns if col not in {'trade_date', 'datetime', 'date'}]
    if len(value_columns) != expected_value_columns:
        return [_issue('BLOCK', 'RETURN_TABLE_COLUMN_COUNT_MISMATCH', f'{table_name} has wrong number of value columns.', {'path': path, 'columns': value_columns})]
    values = frame[value_columns].apply(pd.to_numeric, errors='coerce')
    if values.isna().any().any() or not values.map(math.isfinite).all().all():
        return [_issue('BLOCK', 'RETURN_TABLE_NONFINITE_VALUES', f'{table_name} contains NaN or infinite values.', {'path': path})]
    return []


def _issue(severity: str, code: str, message: str, evidence: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "evidence": evidence or {},
    }


def build_step4_quality_gate(payloads: List[Dict[str, Any]], frm: Dict[str, Any]) -> Dict[str, Any]:
    """Detect obvious Step4 artifact/metric bugs before Step5 archives a case.

    This is not alpha judgment. It only catches execution evidence that is too
    malformed to hand to Step6 as research evidence.
    """
    issues: List[Dict[str, Any]] = []
    self_quant_seen = False

    if frm.get("run_status") in {"success", "partial"} and not payloads:
        issues.append(_issue("BLOCK", "NO_BACKEND_PAYLOADS", "Step4 has no backend payloads despite material run outputs."))

    for item in payloads:
        backend = item.get("backend")
        status = item.get("status")
        payload = item.get("payload") or {}
        payload_path = item.get("payload_path")

        if status in {"success", "partial"} and not payload:
            issues.append(_issue("BLOCK", "SUCCESS_BACKEND_PAYLOAD_UNREADABLE", "Backend claims success/partial but payload is missing or unreadable.", {"backend": backend, "payload_path": payload_path}))
            continue

        if backend == "self_quant_analyzer":
            self_quant_seen = True
            contract = payload.get("standard_metric_contract") or {}
            if contract:
                for check in contract.get("checks") or []:
                    if check.get("status") == "BLOCK":
                        issues.append(_issue("BLOCK", check.get("code") or "STEP4_STANDARD_CHECK_BLOCK", check.get("message") or "Step4 standard metric contract failed.", {"backend": backend, "check": check}))
                    elif check.get("status") == "WARN":
                        issues.append(_issue("WARN", check.get("code") or "STEP4_STANDARD_CHECK_WARN", check.get("message") or "Step4 standard metric contract warning.", {"backend": backend, "check": check}))
            else:
                issues.append(_issue("BLOCK", "SELF_QUANT_STANDARD_CONTRACT_MISSING", "self_quant_analyzer must emit standard_metric_contract."))

            long_side = payload.get("long_side_performance") or {}
            required_long_side_fields = [
                "long_side_annual_return",
                "long_side_sharpe",
                "long_side_max_drawdown",
                "long_side_recovery_days",
                "long_side_turnover_mean_daily",
                "trading_cogs_daily",
                "cost_adjusted_long_side_sharpe",
            ]
            missing_long_side = [
                key for key in required_long_side_fields
                if _float_or_none(long_side.get(key)) is None
            ]
            if missing_long_side:
                issues.append(_issue(
                    "BLOCK",
                    "LONG_SIDE_RISK_ADJUSTED_EVIDENCE_MISSING",
                    "self_quant_analyzer must emit complete long-side Sharpe/drawdown/recovery/turnover/cost evidence before Step5 can validate.",
                    {"missing": missing_long_side, "payload_path": payload_path},
                ))
            if long_side.get("metric_period") != "daily" or _float_or_none(long_side.get("annualization_factor")) is None:
                issues.append(_issue(
                    "BLOCK",
                    "LONG_SIDE_METRIC_UNITS_MISSING",
                    "long-side payload must declare metric_period=daily and annualization_factor for annualized Step5/6 decisions.",
                    {"metric_period": long_side.get("metric_period"), "annualization_factor": long_side.get("annualization_factor")},
                ))

            artifacts = payload.get("artifacts") or {}
            required_artifacts = [
                "rank_ic_timeseries_png",
                "pearson_ic_timeseries_png",
                "coverage_by_day_png",
                "quantile_returns_10groups_csv",
                "quantile_nav_10groups_csv",
                "quantile_counts_10groups_csv",
                "quantile_summary_table_csv",
                "long_short_returns_10groups_csv",
                "long_short_nav_10groups_csv",
                "quantile_nav_10groups_png",
                "quantile_counts_10groups_png",
                "long_short_nav_10groups_png",
                "long_side_returns_csv",
                "long_side_nav_csv",
                "long_side_turnover_csv",
                "long_side_nav_png",
                "cost_adjusted_long_side_nav_png",
            ]
            for key in required_artifacts:
                path = artifacts.get(key)
                if not path or not Path(path).exists() or Path(path).stat().st_size <= 0:
                    issues.append(_issue("BLOCK", "SELF_QUANT_REQUIRED_ARTIFACT_MISSING", f"self_quant_analyzer missing required artifact {key}.", {"path": path}))

            issues.extend(_validate_return_table(artifacts.get('quantile_returns_10groups_csv'), 10, 'quantile_returns_10groups_csv'))
            issues.extend(_validate_nav_table(artifacts.get('quantile_nav_10groups_csv'), 10, 'quantile_nav_10groups_csv'))
            issues.extend(_validate_return_table(artifacts.get('long_short_returns_10groups_csv'), 1, 'long_short_returns_10groups_csv'))
            issues.extend(_validate_nav_table(artifacts.get('long_short_nav_10groups_csv'), 1, 'long_short_nav_10groups_csv'))

            counts = _read_csv_table(artifacts.get('quantile_counts_10groups_csv'))
            if counts is None or counts.empty:
                issues.append(_issue('BLOCK', 'DECILE_COUNTS_TABLE_UNREADABLE', 'quantile_counts_10groups_csv is missing, empty, or unreadable.', {'path': artifacts.get('quantile_counts_10groups_csv')}))
            else:
                count_columns = [col for col in counts.columns if col not in {'trade_date', 'datetime', 'date'}]
                count_values = counts[count_columns].apply(pd.to_numeric, errors='coerce')
                if len(count_columns) != 10 or count_values.isna().any().any() or not count_values.map(math.isfinite).all().all() or (count_values <= 0).any().any():
                    issues.append(_issue('BLOCK', 'DECILE_COUNTS_TABLE_MALFORMED', 'quantile_counts_10groups_csv must contain 10 positive finite count columns.', {'path': artifacts.get('quantile_counts_10groups_csv'), 'columns': count_columns}))

            metrics = {}
            for source_key in ("ic_summary", "group_backtest_summary"):
                if isinstance(payload.get(source_key), dict):
                    metrics.update(payload[source_key])
            rank_ic = _float_or_none(metrics.get("rank_ic_mean"))
            pearson_ic = _float_or_none(metrics.get("pearson_ic_mean"))
            ls_nav = _float_or_none(metrics.get("long_short_final_nav"))
            group_min = _float_or_none(metrics.get("group_member_count_min"))

            if rank_ic is None or abs(rank_ic) > 0.95:
                issues.append(_issue("BLOCK", "RANK_IC_IMPLAUSIBLE", "rank_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.", {"rank_ic_mean": rank_ic}))
            if pearson_ic is None or abs(pearson_ic) > 0.95:
                issues.append(_issue("BLOCK", "PEARSON_IC_IMPLAUSIBLE", "pearson_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.", {"pearson_ic_mean": pearson_ic}))
            if ls_nav is not None and (ls_nav <= 0 or ls_nav > 1_000_000):
                issues.append(_issue("BLOCK", "LONG_SHORT_NAV_IMPLAUSIBLE", "long-short NAV is non-positive or explosively large; suspect return/NAV calculation bug.", {"long_short_final_nav": ls_nav}))
            elif ls_nav is not None and ls_nav > 100:
                issues.append(_issue("WARN", "LONG_SHORT_NAV_EXTREME", "long-short NAV is extremely high; Step6 must inspect short-leg dominance, costs, and compounding assumptions.", {"long_short_final_nav": ls_nav}))
            if group_min is not None and group_min <= 0:
                issues.append(_issue("BLOCK", "DECILE_EMPTY_GROUP", "At least one decile group is empty; quantile backtest is malformed.", {"group_member_count_min": group_min}))

        if backend == "qlib_backtest" and status == "success":
            artifacts = payload.get("artifacts") or {}
            for key in ["portfolio_value_timeseries_png", "benchmark_vs_strategy_png", "turnover_timeseries_png"]:
                path = artifacts.get(key)
                if not path or not Path(path).exists() or Path(path).stat().st_size <= 0:
                    issues.append(_issue("BLOCK", "QLIB_REQUIRED_ARTIFACT_MISSING", f"qlib_backtest missing required artifact {key}.", {"path": path}))

    if not self_quant_seen and frm.get("run_status") in {"success", "partial"}:
        issues.append(_issue("BLOCK", "SELF_QUANT_BACKEND_MISSING", "Step4 must run self_quant_analyzer before Step5 can close a case."))

    blocking = [item for item in issues if item["severity"] == "BLOCK"]
    warnings = [item for item in issues if item["severity"] == "WARN"]
    return {
        "verdict": "BLOCK" if blocking else "WARN" if warnings else "PASS",
        "blocking_issue_count": len(blocking),
        "warning_issue_count": len(warnings),
        "issues": issues,
        "bug_hypotheses": [
            item["message"] for item in blocking
        ],
        "rerun_required": bool(blocking),
        "next_action": "Fix the Step4 implementation/evaluator bug and rerun Step4 before Step5/6." if blocking else "Step4 evidence may proceed to Step6 research judgment.",
    }


def read_backend_payloads(backend_runs: List[Dict[str, Any]], report_id: str, workspace_root: str | Path) -> List[Dict[str, Any]]:
    root = Path(workspace_root)
    ff_root = _resolve_factorforge_root(root)
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
                "warnings": (payload or {}).get("warnings") or [],
            }
        )

    eval_dir = ff_root / "evaluations" / report_id
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
                    "warnings": payload.get("warnings") or [],
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
    quality_gate = build_step4_quality_gate(payloads, frm)

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
                "warnings": item.get("warnings") or [],
            }
            for item in payloads
        ],
        "warnings": list(
            dict.fromkeys(
                list(frm.get("key_warnings") or [])
                + [item.get("message") for item in quality_gate.get("issues") or [] if item.get("severity") == "WARN"]
                + [
                    warning
                    for item in payloads
                    for warning in (item.get("warnings") or [])
                    if warning
                ]
            )
        ),
        "step4_quality_gate": quality_gate,
        "failure_reason": frm.get("failure_reason"),
        "source_paths": [
            bundle["paths"].get("factor_run_master"),
            bundle["paths"].get("handoff_to_step5"),
            *[item.get("payload_path") for item in payloads if item.get("payload_path")],
        ],
    }
    return evaluation
