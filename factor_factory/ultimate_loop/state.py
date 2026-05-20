from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from factor_factory.ultimate_loop.proof import load_json_if_exists


@dataclass(frozen=True)
class LoopState:
    outcome: str
    proof_status: str
    can_continue: bool
    stop_reason: str
    decision: str | None = None
    loop_authorization: str | None = None
    revision_needed: bool | None = None
    council_status: str | None = None
    official_record_exists: bool = False
    handoff_to_step3b_exists: bool = False
    prewrite_block_exists: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_token(value: Any) -> str:
    text = str(value or "revision").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:64] or "revision"


def next_child_report_id(parent_report_id: str, child_ordinal: int, revision_id: str | None = None) -> str:
    suffix = _safe_token(revision_id or "revision")
    child_suffix = f"__LOOP{child_ordinal:02d}__{suffix.upper()}"
    max_report_id_len = 120
    if len(parent_report_id) + len(child_suffix) <= max_report_id_len:
        return f"{parent_report_id}{child_suffix}"
    parent_digest = hashlib.sha256(parent_report_id.encode("utf-8")).hexdigest()[:10]
    parent_budget = max_report_id_len - len(child_suffix) - len(parent_digest) - 2
    if parent_budget < 24:
        suffix = suffix[:32]
        child_suffix = f"__LOOP{child_ordinal:02d}__{suffix.upper()}"
        parent_budget = max_report_id_len - len(child_suffix) - len(parent_digest) - 2
    short_parent = parent_report_id[: max(24, parent_budget)].rstrip("_")
    return f"{short_parent}__{parent_digest}{child_suffix}"


def _iteration_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"


def _wrapper_proof_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json"


def _handoff_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def _official_record_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json"


def _prewrite_block_exists(root: Path, report_id: str) -> bool:
    validation = root / "objects" / "validation"
    if not validation.exists():
        return False
    patterns = [
        f"*prewrite*{report_id}*.json",
        f"*block*{report_id}*.json",
    ]
    matches = []
    for pattern in patterns:
        matches.extend(validation.glob(pattern))
    if not matches:
        return False
    wrapper_proof = load_json_if_exists(_wrapper_proof_path(root, report_id))
    if wrapper_proof.get("status") == "PASS":
        return False
    return True


def _research_memo(iteration: dict[str, Any]) -> dict[str, Any]:
    memo = ((iteration.get("research_judgment") or {}).get("research_memo") or {})
    return memo if isinstance(memo, dict) else {}


def _decision(iteration: dict[str, Any]) -> str | None:
    raw = iteration.get("decision")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    research_judgment = iteration.get("research_judgment") or {}
    raw = research_judgment.get("decision")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _revision_strategy(iteration: dict[str, Any]) -> dict[str, Any]:
    memo = _research_memo(iteration)
    for key in ("final_revision_strategy", "revision_strategy"):
        value = memo.get(key)
        if isinstance(value, dict):
            return value
    value = iteration.get("revision_strategy")
    return value if isinstance(value, dict) else {}


def _evidence_blocked(iteration: dict[str, Any]) -> bool:
    memo = _research_memo(iteration)
    evidence = memo.get("evidence_audit") or {}
    cases = memo.get("case_comparison") or {}
    return evidence.get("evidence_verdict") == "blocked" or cases.get("case_comparison_verdict") == "blocked"


def _council_status(root: Path, report_id: str, iteration: dict[str, Any]) -> str | None:
    ref = iteration.get("revision_council_ref")
    if isinstance(ref, dict) and ref.get("enabled") is True:
        status = ref.get("status")
        if isinstance(status, str) and status:
            return status
    proof = load_json_if_exists(_wrapper_proof_path(root, report_id))
    council = proof.get("revision_council")
    if isinstance(council, dict):
        status = council.get("status")
        if isinstance(status, str) and status:
            return status
    return None


def classify_loop_state(
    root: Path,
    report_id: str,
    wrapper_rc: int,
    *,
    max_reached: bool = False,
) -> dict[str, Any]:
    iteration = load_json_if_exists(_iteration_path(root, report_id))
    decision = _decision(iteration)
    revision = _revision_strategy(iteration)
    loop_authorization = revision.get("loop_authorization")
    revision_needed = revision.get("revision_needed")
    council_status = _council_status(root, report_id, iteration)
    handoff_exists = _handoff_path(root, report_id).exists()
    official_exists = _official_record_path(root, report_id).exists()
    prewrite_blocked = _prewrite_block_exists(root, report_id)

    if wrapper_rc != 0:
        return LoopState(
            outcome="failed",
            proof_status="FAIL",
            can_continue=False,
            stop_reason="ultimate_wrapper_failed",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    wrapper_proof = load_json_if_exists(_wrapper_proof_path(root, report_id))
    main_agent_memo = wrapper_proof.get("main_agent_mechanism_memo") if isinstance(wrapper_proof.get("main_agent_mechanism_memo"), dict) else {}
    if wrapper_proof.get("status") == "PAUSED" and main_agent_memo.get("status") == "awaiting_main_agent_mechanism_memo":
        return LoopState(
            outcome="awaiting_main_agent_mechanism_memo",
            proof_status="PAUSED",
            can_continue=False,
            stop_reason="awaiting_main_agent_mechanism_memo",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if prewrite_blocked or _evidence_blocked(iteration):
        return LoopState(
            outcome="blocked",
            proof_status="FAIL",
            can_continue=False,
            stop_reason="step6_prewrite_or_evidence_block",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if decision == "iterate" and loop_authorization == "approved_for_step3b_handoff" and handoff_exists:
        return LoopState(
            outcome="iterate",
            proof_status="RUNNING",
            can_continue=True,
            stop_reason="approved_step3b_handoff_available",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=True,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if council_status == "awaiting_agent_results":
        return LoopState(
            outcome="awaiting_agent_results",
            proof_status="PAUSED",
            can_continue=False,
            stop_reason="revision_council_awaiting_agent_results",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if decision == "promote_official" and official_exists:
        return LoopState(
            outcome="promoted",
            proof_status="PASS",
            can_continue=False,
            stop_reason="official_promotion_record_exists",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=True,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if decision == "reject":
        return LoopState(
            outcome="rejected",
            proof_status="PASS",
            can_continue=False,
            stop_reason="step6_decision_reject",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if max_reached:
        return LoopState(
            outcome="max_loops_reached",
            proof_status="PASS",
            can_continue=False,
            stop_reason="max_loops_reached",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if decision == "needs_human_review":
        return LoopState(
            outcome="awaiting_agent_results",
            proof_status="PAUSED",
            can_continue=False,
            stop_reason="step6_needs_human_review",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    if decision == "iterate":
        if loop_authorization == "approved_for_step3b_handoff" and not handoff_exists:
            return LoopState(
                outcome="blocked",
                proof_status="FAIL",
                can_continue=False,
                stop_reason="BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING",
                decision=decision,
                loop_authorization=loop_authorization,
                revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
                council_status=council_status,
                official_record_exists=official_exists,
                handoff_to_step3b_exists=False,
                prewrite_block_exists=prewrite_blocked,
            ).to_dict()
        return LoopState(
            outcome="exhausted",
            proof_status="PASS",
            can_continue=False,
            stop_reason="iterate_without_authorized_step3b_handoff",
            decision=decision,
            loop_authorization=loop_authorization,
            revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
            council_status=council_status,
            official_record_exists=official_exists,
            handoff_to_step3b_exists=handoff_exists,
            prewrite_block_exists=prewrite_blocked,
        ).to_dict()

    return LoopState(
        outcome="exhausted",
        proof_status="PASS",
        can_continue=False,
        stop_reason="no_continuation_condition",
        decision=decision,
        loop_authorization=loop_authorization,
        revision_needed=revision_needed if isinstance(revision_needed, bool) else None,
        council_status=council_status,
        official_record_exists=official_exists,
        handoff_to_step3b_exists=handoff_exists,
        prewrite_block_exists=prewrite_blocked,
    ).to_dict()


def approved_child_revision_from_handoff(root: Path, report_id: str, child_ordinal: int) -> dict[str, Any]:
    path = _handoff_path(root, report_id)
    if not path.exists():
        return {"ok": False, "block_reason": "BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING", "handoff_path": str(path)}
    handoff = load_json_if_exists(path)
    iteration = load_json_if_exists(_iteration_path(root, report_id))
    revision = _revision_strategy(iteration)
    authorization = handoff.get("loop_authorization") or handoff.get("authorization") or handoff.get("status")
    iteration_authorization = revision.get("loop_authorization")
    if authorization not in {"approved_for_step3b_handoff", "approved"} and iteration_authorization != "approved_for_step3b_handoff":
        return {
            "ok": False,
            "block_reason": "BLOCK_FACTORFORGE_LOOP_CHILD_REVISION_NOT_APPROVED",
            "handoff_path": str(path),
            "authorization": authorization,
            "iteration_authorization": iteration_authorization,
        }
    revision_id = (
        handoff.get("revision_hypothesis_id")
        or handoff.get("revision_id")
        or handoff.get("new_branch_id")
        or (handoff.get("selected_revision") or {}).get("revision_id")
        or (handoff.get("revision_strategy") or {}).get("revision_hypothesis_id")
        or "revision"
    )
    child_report_id = handoff.get("child_report_id") or next_child_report_id(report_id, child_ordinal, str(revision_id))
    if child_report_id == report_id:
        return {
            "ok": False,
            "block_reason": "BLOCK_FACTORFORGE_LOOP_CHILD_REPORT_ID_COLLISION",
            "handoff_path": str(path),
            "child_report_id": child_report_id,
        }
    return {
        "ok": True,
        "handoff_path": str(path),
        "revision_id": str(revision_id),
        "child_report_id": str(child_report_id),
        "authorization": authorization,
    }
