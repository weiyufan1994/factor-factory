#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context

COMPARISON_VERSION = "factorforge_branch_comparison_v1"
TOKEN_MISSING = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING"
TOKEN_PERMISSION = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_PERMISSION_UNSAFE"
TOKEN_SELECTED = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SELECTED_CHILD_INVALID"
TOKEN_DUPLICATE = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_DUPLICATE"
TOKEN_METRICS = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_METRICS_MISSING"
TOKEN_INVALID = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_INVALID"
TOKEN_SOURCE_CHANGED = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SOURCE_CHANGED"
TOKEN_SOURCE_ARTIFACT_MISMATCH = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SOURCE_ARTIFACT_MISMATCH"

REQUIRED_METRICS = [
    "rank_ic_mean",
    "long_side_annual_return",
    "cost_adjusted_annual_return",
    "turnover",
    "long_side_max_drawdown",
    "long_side_recovery_days",
]
METRIC_ALIASES: dict[str, list[str]] = {
    "rank_ic_mean": ["rank_ic_mean", "rank_ic"],
    "long_side_annual_return": ["long_side_annual_return", "annual_return", "long_annual_return"],
    "cost_adjusted_annual_return": ["cost_adjusted_annual_return", "cost_adjusted_return", "net_annual_return"],
    "turnover": ["turnover", "turnover_mean", "long_side_turnover_mean_daily", "daily_turnover", "turnover_mean_daily"],
    "long_side_max_drawdown": ["long_side_max_drawdown", "max_drawdown", "long_side_mdd", "mdd"],
    "long_side_recovery_days": ["long_side_recovery_days", "recovery_days", "long_side_recovery_time_days"],
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def comparison_path(root: Path, parent_report_id: str, loop_index: int) -> Path:
    return root / "objects" / "research_iteration_master" / f"branch_comparison__{parent_report_id}__loop{loop_index:02d}.json"


def resolve_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def collect_key_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if isinstance(evaluation.get("key_metrics"), dict):
        metrics.update(evaluation["key_metrics"])
    for item in evaluation.get("backend_summary") or []:
        if isinstance(item, dict) and isinstance(item.get("key_metrics"), dict):
            metrics.update(item["key_metrics"])
    if isinstance(evaluation.get("metrics"), dict):
        metrics.update(evaluation["metrics"])
    return metrics


def numeric_metric(metrics: dict[str, Any], key: str) -> float | None:
    for candidate in METRIC_ALIASES.get(key, [key]):
        value = metrics.get(candidate)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def normalized_metrics(root: Path, report_id: str) -> tuple[dict[str, float], list[str]]:
    evaluation_path = root / "objects" / "validation" / f"factor_evaluation__{report_id}.json"
    if not evaluation_path.exists():
        return {}, [f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:factor_evaluation_missing:{report_id}"]
    raw = collect_key_metrics(load_json(evaluation_path))
    metrics: dict[str, float] = {}
    failures: list[str] = []
    for key in REQUIRED_METRICS:
        value = numeric_metric(raw, key)
        if value is None:
            failures.append(f"{TOKEN_METRICS}:{report_id}:{key}")
        else:
            metrics[key] = value
    return metrics, failures


def metric_delta(parent_metrics: dict[str, float], child_metrics: dict[str, float]) -> dict[str, dict[str, float]]:
    return {
        key: {
            "parent": parent_metrics[key],
            "child": child_metrics[key],
            "delta": child_metrics[key] - parent_metrics[key],
        }
        for key in REQUIRED_METRICS
    }


def branch_outcome(delta: dict[str, dict[str, float]]) -> str:
    rank_delta = delta["rank_ic_mean"]["delta"]
    long_delta = delta["long_side_annual_return"]["delta"]
    cost_delta = delta["cost_adjusted_annual_return"]["delta"]
    drawdown_delta = delta["long_side_max_drawdown"]["delta"]
    recovery_delta = delta["long_side_recovery_days"]["delta"]
    core_worse = rank_delta < 0 or long_delta < 0 or cost_delta < 0 or drawdown_delta < 0 or recovery_delta > 0
    core_better = rank_delta > 0 or long_delta > 0 or cost_delta > 0 or drawdown_delta > 0 or recovery_delta < 0
    if core_worse:
        return "falsified"
    if core_better:
        return "improved"
    return "inconclusive"


def same_number(left: Any, right: float) -> bool:
    if not is_number(left):
        return False
    return abs(float(left) - right) <= 1e-12


def validate_payload(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if payload.get("contract_version") != COMPARISON_VERSION:
        failures.append(f"{TOKEN_INVALID}:contract_version")
    if not nonempty(payload.get("parent_report_id")):
        failures.append(f"{TOKEN_INVALID}:parent_report_id")
    if not nonempty(payload.get("branch_group_id")):
        failures.append(f"{TOKEN_INVALID}:branch_group_id")
    if not nonempty(payload.get("source_multibranch_materialization_path")):
        failures.append(f"{TOKEN_INVALID}:source_multibranch_materialization_path")
    if not nonempty(payload.get("source_multibranch_materialization_sha256")):
        failures.append(f"{TOKEN_INVALID}:source_multibranch_materialization_sha256")
    if payload.get("canonical_write_permission") is not False:
        failures.append(f"{TOKEN_PERMISSION}:canonical_write_permission")
    if payload.get("execution_allowed_by_default") is not False:
        failures.append(f"{TOKEN_PERMISSION}:execution_allowed_by_default")
    if payload.get("human_approval_required") is not True:
        failures.append(f"{TOKEN_PERMISSION}:human_approval_required")

    children = payload.get("children")
    if not isinstance(children, list) or len(children) < 2:
        failures.append(f"{TOKEN_INVALID}:children")
        children = []

    selected = payload.get("main_agent_selection") if isinstance(payload.get("main_agent_selection"), dict) else {}
    selected_child = selected.get("selected_next_parent_child_report_id")
    child_ids: set[str] = set()
    formula_hashes: set[str] = set()
    selected_present = False
    for idx, raw in enumerate(children):
        child = raw if isinstance(raw, dict) else {}
        child_id = child.get("child_report_id")
        formula_hash = child.get("formula_hash")
        if not nonempty(child_id) or not nonempty(child.get("branch_role")) or not nonempty(child.get("law_id")):
            failures.append(f"{TOKEN_INVALID}:child[{idx}]:identity")
        if nonempty(child_id):
            if child_id in child_ids:
                failures.append(f"{TOKEN_DUPLICATE}:child_report_id:{child_id}")
            child_ids.add(str(child_id))
            if child_id == selected_child:
                selected_present = True
        if not nonempty(formula_hash):
            failures.append(f"{TOKEN_INVALID}:child[{idx}]:formula_hash")
        elif formula_hash in formula_hashes:
            failures.append(f"{TOKEN_DUPLICATE}:formula_hash:{formula_hash}")
        else:
            formula_hashes.add(str(formula_hash))
        if child.get("branch_outcome") not in {"falsified", "improved", "inconclusive"}:
            failures.append(f"{TOKEN_INVALID}:child[{idx}]:branch_outcome")
        metrics = child.get("metrics") if isinstance(child.get("metrics"), dict) else {}
        deltas = child.get("metric_delta_vs_parent") if isinstance(child.get("metric_delta_vs_parent"), dict) else {}
        for key in REQUIRED_METRICS:
            if not is_number(metrics.get(key)):
                failures.append(f"{TOKEN_METRICS}:child[{idx}]:metrics:{key}")
            delta = deltas.get(key) if isinstance(deltas.get(key), dict) else {}
            if not (is_number(delta.get("parent")) and is_number(delta.get("child")) and is_number(delta.get("delta"))):
                failures.append(f"{TOKEN_METRICS}:child[{idx}]:delta:{key}")

    if not nonempty(selected_child) or not selected_present:
        failures.append(TOKEN_SELECTED)
    if not nonempty(selected.get("why")):
        failures.append(f"{TOKEN_SELECTED}:why")
    if not nonempty(selected.get("what_was_learned_from_exploration")):
        failures.append(f"{TOKEN_SELECTED}:what_was_learned_from_exploration")
    return failures


def validate_source_binding(root: Path, payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    source_path = resolve_path(root, payload.get("source_multibranch_materialization_path"))
    expected_sha = payload.get("source_multibranch_materialization_sha256")
    if source_path is None or not source_path.exists() or not source_path.is_file():
        return [f"{TOKEN_SOURCE_CHANGED}:source_missing"]
    if not nonempty(expected_sha):
        return [f"{TOKEN_SOURCE_CHANGED}:source_sha_missing"]
    actual_sha = sha256_file(source_path)
    if actual_sha != expected_sha:
        failures.append(f"{TOKEN_SOURCE_CHANGED}:source_multibranch_materialization_sha256")
    return failures


def validate_source_artifacts(root: Path, payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    source_path = resolve_path(root, payload.get("source_multibranch_materialization_path"))
    if source_path is None or not source_path.exists() or not source_path.is_file():
        return failures
    materialization = load_json(source_path)
    if materialization.get("status") != "PASS":
        failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:materialization_status")
    if materialization.get("parent_report_id") != payload.get("parent_report_id"):
        failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:parent_report_id")
    if materialization.get("branch_group_id") != payload.get("branch_group_id"):
        failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:branch_group_id")

    parent_report_id = str(payload.get("parent_report_id") or "")
    parent_metrics, metric_failures = normalized_metrics(root, parent_report_id)
    failures.extend(metric_failures)
    payload_parent_metrics = payload.get("parent_metrics") if isinstance(payload.get("parent_metrics"), dict) else {}
    if parent_metrics:
        for key, value in parent_metrics.items():
            if not same_number(payload_parent_metrics.get(key), value):
                failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:parent_metrics:{key}")

    materialized_children = materialization.get("children") if isinstance(materialization.get("children"), list) else []
    materialized_by_id = {
        str(child.get("child_report_id") or ""): child
        for child in materialized_children
        if isinstance(child, dict) and nonempty(child.get("child_report_id"))
    }
    payload_children = payload.get("children") if isinstance(payload.get("children"), list) else []
    payload_child_ids = {
        str(child.get("child_report_id") or "")
        for child in payload_children
        if isinstance(child, dict) and nonempty(child.get("child_report_id"))
    }
    if set(materialized_by_id) != payload_child_ids:
        failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:children_set")

    for idx, raw_child in enumerate(payload_children):
        child = raw_child if isinstance(raw_child, dict) else {}
        child_id = str(child.get("child_report_id") or "")
        materialized = materialized_by_id.get(child_id)
        if not materialized:
            failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:child[{idx}]:materialization_missing")
            continue
        expected_identity = {
            "branch_role": materialized.get("branch_role"),
            "branch_index": materialized.get("branch_index"),
            "law_id": materialized.get("law_id"),
            "formula_hash": materialized.get("child_formula_hash"),
            "materialization_report_path": materialized.get("materialization_report_path"),
            "executable_revision_spec_path": materialized.get("executable_revision_spec_path"),
        }
        for key, expected in expected_identity.items():
            if expected is not None and child.get(key) != expected:
                failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:child[{idx}]:{key}")

        child_metrics, metric_failures = normalized_metrics(root, child_id)
        failures.extend(metric_failures)
        if not parent_metrics or not child_metrics:
            continue
        expected_delta = metric_delta(parent_metrics, child_metrics)
        expected_outcome = branch_outcome(expected_delta)
        if child.get("branch_outcome") != expected_outcome:
            failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:child[{idx}]:branch_outcome")
        child_payload_metrics = child.get("metrics") if isinstance(child.get("metrics"), dict) else {}
        child_payload_delta = child.get("metric_delta_vs_parent") if isinstance(child.get("metric_delta_vs_parent"), dict) else {}
        for key, value in child_metrics.items():
            if not same_number(child_payload_metrics.get(key), value):
                failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:child[{idx}]:metrics:{key}")
        for key, expected in expected_delta.items():
            payload_delta = child_payload_delta.get(key) if isinstance(child_payload_delta.get(key), dict) else {}
            for part in ("parent", "child", "delta"):
                if not same_number(payload_delta.get(part), expected[part]):
                    failures.append(f"{TOKEN_SOURCE_ARTIFACT_MISMATCH}:child[{idx}]:delta:{key}:{part}")
    return failures


def validate(root: Path, parent_report_id: str, loop_index: int, path: Path | None = None) -> dict[str, Any]:
    target = path or comparison_path(root, parent_report_id, loop_index)
    if not target.exists():
        return {"result": "BLOCK", "failures": [TOKEN_MISSING], "path": str(target)}
    payload = load_json(target)
    failures = validate_payload(payload)
    failures.extend(validate_source_binding(root, payload))
    failures.extend(validate_source_artifacts(root, payload))
    return {"result": "PASS" if not failures else "BLOCK", "failures": failures, "path": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Factor Forge branch comparison artifact.")
    parser.add_argument("--parent-report-id", required=True)
    parser.add_argument("--loop-index", type=int, default=1)
    parser.add_argument("--factorforge-root", default=None)
    parser.add_argument("--path", default=None)
    args = parser.parse_args()
    ctx = resolve_factorforge_context(args.factorforge_root)
    result = validate(
        ctx.factorforge_root,
        args.parent_report_id,
        args.loop_index,
        Path(args.path).expanduser() if args.path else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
