from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .rules import build_evaluation_summary


PLACEHOLDER_NEXT_ACTIONS = {
    "validated": [
        "Write back durable factor case knowledge",
        "Run robustness extension on wider sample window",
        "Compare against sign-flipped or benchmark variants",
    ],
    "partial": [
        "Fill missing evaluation backend outputs",
        "Repair archive or validation gaps and rerun Step 5",
    ],
    "failed": [
        "Repair Step 4 or upstream handoff before rerunning Step 5",
        "Restore missing run artifacts or evaluation payloads",
    ],
}


def derive_lessons(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> List[str]:
    frm = bundle["objects"].get("factor_run_master") or {}
    lessons: List[str] = []

    for warning in frm.get("key_warnings") or []:
        lessons.append(str(warning))

    for backend in evaluation.get("backend_summary") or []:
        metrics = backend.get("key_metrics") or {}
        rank_ic_ir = metrics.get("rank_ic_ir")
        if isinstance(rank_ic_ir, (int, float)) and rank_ic_ir < 0:
            lessons.append(
                f"Backend {backend.get('backend')} reported negative rank_ic_ir={rank_ic_ir}; signal direction or construction may need review."
            )

    if not lessons:
        lessons.append("Step 5 closed the case using only verified upstream artifacts.")

    deduped: List[str] = []
    seen = set()
    for item in lessons:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def derive_known_limits(bundle: Dict[str, Any], evaluation: Dict[str, Any]) -> List[str]:
    limits: List[str] = []
    for warning in evaluation.get("warnings") or []:
        limits.append(str(warning))
    if not evaluation.get("backend_summary"):
        limits.append("No evaluation backend payload was available at Step 5 aggregation time.")
    return list(dict.fromkeys(limits))


def derive_next_actions(bundle: Dict[str, Any], evaluation: Dict[str, Any], final_status: str) -> List[str]:
    next_actions = list(PLACEHOLDER_NEXT_ACTIONS.get(final_status, []))
    backend_summary = evaluation.get("backend_summary") or []
    if final_status == "partial" and not backend_summary:
        next_actions.insert(0, "Add at least one successful evaluation backend before claiming validated.")
    return list(dict.fromkeys(next_actions))


def build_factor_case_master(
    bundle: Dict[str, Any],
    evaluation: Dict[str, Any],
    archive_paths: List[str],
    final_status: str,
    evaluation_path: str,
) -> Dict[str, Any]:
    frm = bundle["objects"].get("factor_run_master") or {}
    fsm = bundle["objects"].get("factor_spec_master") or {}
    dpm = bundle["objects"].get("data_prep_master") or {}

    case = {
        "report_id": bundle["report_id"],
        "factor_id": frm.get("factor_id"),
        "final_status": final_status,
        "case_stage": "step5_closed",
        "evaluation_summary": build_evaluation_summary(frm, evaluation),
        "factor_profile": {
            "factor_name": fsm.get("factor_name") or fsm.get("name"),
            "factor_family": fsm.get("factor_family") or fsm.get("family"),
            "thesis_summary": fsm.get("thesis_summary") or fsm.get("summary"),
        },
        "data_profile": {
            "sample_window": dpm.get("sample_window") or frm.get("sample_window_actual") or {},
            "universe": dpm.get("universe"),
            "data_sources": dpm.get("data_sources") or dpm.get("sources") or [],
        },
        "evidence": {
            "run_master_path": bundle["paths"].get("factor_run_master"),
            "evaluation_path": evaluation_path,
            "archive_paths": archive_paths,
        },
        "lessons": derive_lessons(bundle, evaluation),
        "next_actions": derive_next_actions(bundle, evaluation, final_status),
        "known_limits": derive_known_limits(bundle, evaluation),
        "created_by_step": "step5",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return case
