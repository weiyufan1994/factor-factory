#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context

COMPARISON_VERSION = "factorforge_branch_comparison_v1"
TOKEN_MATERIALIZATION_MISSING = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_MATERIALIZATION_MISSING"
TOKEN_SELECTED_INVALID = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SELECTED_CHILD_INVALID"
TOKEN_METRICS_MISSING = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_METRICS_MISSING"
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[WRITE] {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_path(root: Path, parent_report_id: str, loop_index: int) -> Path:
    return root / "objects" / "runtime_context" / f"multibranch_child_materialization__{parent_report_id}__loop{loop_index:02d}.json"


def comparison_path(root: Path, parent_report_id: str, loop_index: int) -> Path:
    return root / "objects" / "research_iteration_master" / f"branch_comparison__{parent_report_id}__loop{loop_index:02d}.json"


def comparison_md_path(root: Path, parent_report_id: str, loop_index: int) -> Path:
    return root / "objects" / "research_iteration_master" / f"branch_comparison__{parent_report_id}__loop{loop_index:02d}.md"


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


def normalized_metrics(root: Path, report_id: str) -> dict[str, float]:
    evaluation = load_json(root / "objects" / "validation" / f"factor_evaluation__{report_id}.json")
    raw = collect_key_metrics(evaluation)
    metrics: dict[str, float] = {}
    missing: list[str] = []
    for key in REQUIRED_METRICS:
        value = numeric_metric(raw, key)
        if value is None:
            missing.append(key)
        else:
            metrics[key] = value
    if missing:
        raise ValueError(f"{TOKEN_METRICS_MISSING}:{report_id}:{','.join(missing)}")
    return metrics


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


def import_validator():
    validator_path = REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "validate_branch_comparison.py"
    spec = importlib.util.spec_from_file_location("validate_branch_comparison", validator_path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load validate_branch_comparison.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(root: Path, parent_report_id: str, loop_index: int, selected_child: str, *, why: str, learned: str) -> dict[str, Any]:
    aggregate = aggregate_path(root, parent_report_id, loop_index)
    if not aggregate.exists():
        raise ValueError(f"{TOKEN_MATERIALIZATION_MISSING}:{aggregate}")
    materialization = load_json(aggregate)
    if materialization.get("status") != "PASS":
        raise ValueError(f"{TOKEN_MATERIALIZATION_MISSING}:status")
    children_raw = materialization.get("children")
    if not isinstance(children_raw, list) or len(children_raw) < 2:
        raise ValueError(f"{TOKEN_MATERIALIZATION_MISSING}:children")
    child_ids = {str(child.get("child_report_id") or "") for child in children_raw if isinstance(child, dict)}
    if selected_child not in child_ids:
        raise ValueError(f"{TOKEN_SELECTED_INVALID}:{selected_child}")

    parent_metrics = normalized_metrics(root, parent_report_id)
    children: list[dict[str, Any]] = []
    for raw in children_raw:
        child = raw if isinstance(raw, dict) else {}
        child_id = str(child.get("child_report_id") or "")
        metrics = normalized_metrics(root, child_id)
        delta = metric_delta(parent_metrics, metrics)
        children.append(
            {
                "child_report_id": child_id,
                "branch_role": child.get("branch_role"),
                "branch_index": child.get("branch_index"),
                "law_id": child.get("law_id"),
                "formula_hash": child.get("child_formula_hash"),
                "metrics": metrics,
                "metric_delta_vs_parent": delta,
                "branch_outcome": branch_outcome(delta),
                "materialization_report_path": child.get("materialization_report_path"),
                "executable_revision_spec_path": child.get("executable_revision_spec_path"),
            }
        )

    payload = {
        "contract_version": COMPARISON_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent_report_id,
        "loop_index": loop_index,
        "branch_group_id": materialization.get("branch_group_id"),
        "source_multibranch_materialization_path": str(aggregate),
        "source_multibranch_materialization_sha256": sha256_file(aggregate),
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "parent_metrics": parent_metrics,
        "children": children,
        "main_agent_selection": {
            "selected_next_parent_child_report_id": selected_child,
            "why": why,
            "what_was_learned_from_exploration": learned,
        },
    }
    validator = import_validator()
    validation = validator.validate_payload(payload)
    if validation:
        raise ValueError(";".join(validation))
    out = comparison_path(root, parent_report_id, loop_index)
    write_json(out, payload)
    write_markdown(comparison_md_path(root, parent_report_id, loop_index), payload)
    return payload


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Branch Comparison",
        "",
        f"- parent_report_id: `{payload.get('parent_report_id')}`",
        f"- branch_group_id: `{payload.get('branch_group_id')}`",
        f"- selected_next_parent_child_report_id: `{payload.get('main_agent_selection', {}).get('selected_next_parent_child_report_id')}`",
        "",
        "## Children",
    ]
    for child in payload.get("children") or []:
        lines.extend(
            [
                "",
                f"### {child.get('child_report_id')}",
                f"- role: `{child.get('branch_role')}`",
                f"- law_id: `{child.get('law_id')}`",
                f"- outcome: `{child.get('branch_outcome')}`",
                f"- rank_ic_delta: `{child.get('metric_delta_vs_parent', {}).get('rank_ic_mean', {}).get('delta')}`",
                f"- cost_adjusted_delta: `{child.get('metric_delta_vs_parent', {}).get('cost_adjusted_annual_return', {}).get('delta')}`",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[WRITE] {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Factor Forge multibranch branch comparison artifact.")
    parser.add_argument("--parent-report-id", required=True)
    parser.add_argument("--loop-index", type=int, default=1)
    parser.add_argument("--selected-next-parent-child-report-id", required=True)
    parser.add_argument("--factorforge-root", default=None)
    parser.add_argument("--why", default="Selected as the next exploitation path after comparing branch evidence.")
    parser.add_argument("--what-learned-from-exploration", default="Sibling branch results are preserved for the next Council and must constrain future derivations.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ctx = resolve_factorforge_context(args.factorforge_root)
        payload = build(
            ctx.factorforge_root,
            args.parent_report_id,
            args.loop_index,
            args.selected_next_parent_child_report_id,
            why=args.why,
            learned=args.what_learned_from_exploration,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps({"status": "PASS", "path": str(comparison_path(ctx.factorforge_root, args.parent_report_id, args.loop_index)), "branch_group_id": payload.get("branch_group_id")}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
