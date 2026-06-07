#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.parser import parse_formula
from factor_factory.artifact_identity import stable_hash
from factor_factory.runtime_context import resolve_factorforge_context

SYNTHESIS_VERSION = "factorforge_main_agent_council_synthesis_v1"
APPROVAL_VERSION = "factorforge_main_agent_council_synthesis_approval_v1"
TOKEN_SYNTHESIS_MISSING = "BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING"
TOKEN_SUMMARY_MISSING = "BLOCK_FACTORFORGE_COUNCIL_SYNTHESIS_APPROVAL_COUNCIL_SUMMARY_MISSING"
TOKEN_ITERATION_MISSING = "BLOCK_FACTORFORGE_COUNCIL_SYNTHESIS_APPROVAL_ITERATION_MISSING"
TOKEN_PARENT_FORMULA_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_PARENT_FORMULA_MISSING"
TOKEN_CHILD_FORMULA_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_CHILD_FORMULA_MISSING"
TOKEN_SELECTED_LAW_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_SELECTED_LAW_MISSING"
TOKEN_METRIC_SIGNATURE_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_METRIC_SIGNATURE_MISSING"
TOKEN_FALSIFICATION_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FALSIFICATION_MISSING"
TOKEN_KILL_CRITERIA_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_KILL_CRITERIA_MISSING"
TOKEN_ORCHESTRATOR_MISMATCH = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_ORCHESTRATOR_MISMATCH"
TOKEN_DIRECT_CODE_CONTRACT_MISSING = "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_DIRECT_CODE_CONTRACT_MISSING"
VALID_PRIMARY_FAILURE_SIGNATURES = {
    "cost_too_high",
    "long_side_negative",
    "non_monotonic",
    "unstable_regime",
    "implementation_suspect",
    "mechanism_unclear",
    "same_factor_identity_mismatch",
    "none",
}
REQUIRED_REVISION_FORBIDDEN_CHANGES = [
    "no_portfolio_expression_repair",
    "no_short_leg_adoption",
    "no_decile_trading",
    "no_shared_clean_data_mutation",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[WRITE] {path}")


def read_text_if_exists(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def restore_text_snapshot(path: Path, text: str | None) -> None:
    if text is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_token(value: Any) -> str:
    text = str(value or "revision").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:64] or "revision"


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) and bool(value) else []


def nonempty_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) and bool(value) else {}


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def synthesis_path_for(root: Path, report_id: str, raw: str | None = None) -> Path:
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else root / path
    return council_dir(root, report_id) / f"main_agent_council_synthesis__{report_id}.json"


def factor_spec_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"


def iteration_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"


def handoff_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def approval_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_council_synthesis_approval__{report_id}.json"


def validate_synthesis(root: Path, report_id: str, synthesis_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not synthesis_path.exists():
        block(TOKEN_SYNTHESIS_MISSING, {"report_id": report_id, "synthesis_path": str(synthesis_path)})
    synthesis = load_json(synthesis_path)
    if synthesis.get("contract_version") != SYNTHESIS_VERSION or synthesis.get("report_id") != report_id:
        block(
            TOKEN_ORCHESTRATOR_MISMATCH,
            {
                "report_id": report_id,
                "synthesis_path": str(synthesis_path),
                "contract_version": synthesis.get("contract_version"),
                "synthesis_report_id": synthesis.get("report_id"),
            },
        )
    if synthesis.get("canonical_write_permission") is not False:
        block(TOKEN_ORCHESTRATOR_MISMATCH, {"reason": "canonical_write_permission_must_be_false", "synthesis_path": str(synthesis_path)})
    if synthesis.get("execution_allowed_by_default") is not False:
        block(TOKEN_ORCHESTRATOR_MISMATCH, {"reason": "execution_allowed_by_default_must_be_false", "synthesis_path": str(synthesis_path)})
    if synthesis.get("human_approval_required") is not True:
        block(TOKEN_ORCHESTRATOR_MISMATCH, {"reason": "human_approval_required_must_be_true", "synthesis_path": str(synthesis_path)})
    selected = synthesis.get("selected_revision")
    if not isinstance(selected, dict):
        block(TOKEN_CHILD_FORMULA_MISSING, {"reason": "selected_revision_missing", "synthesis_path": str(synthesis_path)})
    if not nonempty_str(selected.get("law_id")):
        block(TOKEN_SELECTED_LAW_MISSING, {"synthesis_path": str(synthesis_path)})
    if not child_formula_or_law(selected):
        block(TOKEN_CHILD_FORMULA_MISSING, {"synthesis_path": str(synthesis_path)})
    if not nonempty_dict(selected.get("expected_metric_signature")):
        block(TOKEN_METRIC_SIGNATURE_MISSING, {"synthesis_path": str(synthesis_path)})
    if not nonempty_list(selected.get("falsification_tests")):
        block(TOKEN_FALSIFICATION_MISSING, {"synthesis_path": str(synthesis_path)})
    if not nonempty_list(selected.get("kill_criteria")):
        block(TOKEN_KILL_CRITERIA_MISSING, {"synthesis_path": str(synthesis_path)})
    summary_path = council_dir(root, report_id) / f"revision_council_summary__{report_id}.json"
    if not summary_path.exists():
        block(TOKEN_SUMMARY_MISSING, {"report_id": report_id, "summary_path": str(summary_path)})
    return synthesis, selected


def child_formula_or_law(selected: dict[str, Any]) -> str:
    return (
        nonempty_str(selected.get("child_formula"))
        or nonempty_str(selected.get("child_formula_or_law"))
        or nonempty_str(selected.get("direct_code_law"))
        or nonempty_str(selected.get("formula_law"))
    )


def parent_implementation_mode(root: Path, report_id: str, selected: dict[str, Any] | None = None) -> str:
    if selected:
        explicit = nonempty_str(selected.get("implementation_mode"))
        if explicit:
            return explicit
        if isinstance(selected.get("direct_code_revision_contract"), dict) and selected["direct_code_revision_contract"]:
            return "direct_code"
    path = factor_spec_path(root, report_id)
    spec = load_json(path) if path.exists() else {}
    identity = spec.get("artifact_identity") if isinstance(spec.get("artifact_identity"), dict) else {}
    mode = nonempty_str(identity.get("implementation_mode")) or nonempty_str(spec.get("implementation_mode"))
    contract = spec.get("implementation_contract") if isinstance(spec.get("implementation_contract"), dict) else {}
    return mode or nonempty_str(contract.get("mode")) or nonempty_str(contract.get("implementation_mode")) or "operator"


def parent_formula_and_hash(root: Path, report_id: str) -> tuple[str, str]:
    path = factor_spec_path(root, report_id)
    spec = load_json(path) if path.exists() else {}
    canonical = spec.get("canonical_spec") if isinstance(spec.get("canonical_spec"), dict) else {}
    formula = nonempty_str(canonical.get("formula_text"))
    if not formula:
        block(TOKEN_PARENT_FORMULA_MISSING, {"report_id": report_id, "factor_spec_path": str(path)})
    parsed = parse_formula(formula)
    if parsed.get("parse_status") != "success":
        return formula, stable_hash(
            {
                "hash_role": "parent_formula_audit_hash",
                "formula_text": formula,
                "parse_status": "not_formula_ir_parent",
                "parse_errors": parsed.get("parse_errors") or [],
            }
        )
    return formula, str(parsed.get("formula_hash") or "")


def child_formula_hash(child_formula: str, parent_hash: str, implementation_mode: str, selected: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if implementation_mode in {"direct_code", "hybrid"}:
        contract_key = "direct_code_revision_contract" if implementation_mode == "direct_code" else "hybrid_revision_contract"
        contract = selected.get(contract_key)
        if not isinstance(contract, dict) or not contract:
            contract = selected.get("direct_code_revision_contract")
        if not isinstance(contract, dict) or not contract:
            block(TOKEN_DIRECT_CODE_CONTRACT_MISSING, {"implementation_mode": implementation_mode, "child_formula_or_law": child_formula})
        child_hash = stable_hash(
            {
                "hash_role": f"{implementation_mode}_child_code_law_hash",
                "implementation_mode": implementation_mode,
                "child_formula_or_law": child_formula,
                "revision_contract": contract,
            }
        )
        if child_hash == parent_hash:
            block("BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT", {"child_formula_hash": child_hash})
        return None, child_hash
    parsed = parse_formula(child_formula)
    if parsed.get("parse_status") != "success":
        block("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED", {"formula": child_formula, "errors": parsed.get("parse_errors") or []})
    child_hash = str(parsed.get("formula_hash") or "")
    if child_hash == parent_hash:
        block("BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT", {"child_formula_hash": child_hash})
    return parsed, child_hash


def selected_proposal_ids(summary: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for branch in summary.get("recommended_branch_templates") or []:
        if not isinstance(branch, dict):
            continue
        proposal_id = branch.get("source_proposal_id")
        if isinstance(proposal_id, str) and proposal_id and proposal_id not in ids:
            ids.append(proposal_id)
    return ids


def proposal_count(root: Path, report_id: str) -> int:
    directory = council_dir(root, report_id)
    proposal_files = list(directory.glob(f"proposal__{report_id}__*.json"))
    agent_results = list((directory / "agent_results").glob(f"agent_result__{report_id}__*.json"))
    return len(proposal_files) + len(agent_results)


def synthesis_revision_hypothesis(selected: dict[str, Any], implementation_mode: str) -> dict[str, Any]:
    expected = selected.get("expected_metric_signature") if isinstance(selected.get("expected_metric_signature"), dict) else {}
    expected_changes = [
        f"{key}: {value}"
        for key, value in expected.items()
        if isinstance(key, str) and str(value).strip()
    ]
    falsification = selected.get("falsification_tests") if isinstance(selected.get("falsification_tests"), list) else []
    kill = selected.get("kill_criteria") if isinstance(selected.get("kill_criteria"), list) else []
    expression_change = nonempty_str(selected.get("formula_mutation_description")) or f"Apply selected Council synthesis law {selected.get('law_id')}"
    math_change = nonempty_str(selected.get("math_model_link")) or nonempty_str(selected.get("economic_mechanism_link"))
    return {
        "hypothesis_id": safe_token(selected.get("law_id")),
        "hypothesis": nonempty_str(selected.get("why_selected")) or f"Test selected Council synthesis law {selected.get('law_id')}.",
        "mechanism_target": nonempty_str(selected.get("economic_mechanism_link")) or "Refine the factor mechanism while preserving the parent economic direction.",
        "revision_model_layer": "observable_estimator",
        "revision_target_math_object": "estimator_kernel",
        "expression_change": expression_change,
        "math_change": math_change or expression_change,
        "expected_metric_effect": expected_changes[:],
        "math_falsification_tests": falsification[:],
        "implementation_mode_preference": implementation_mode if implementation_mode in {"operator", "hybrid", "direct_code"} else "unknown",
        "expected_metric_change": expected_changes[:],
        "falsification_tests": falsification[:],
        "risk_of_overfit": "medium",
        "kill_criteria": kill[:],
        "why_not_portfolio_fix": "The failure is in the expression-level state estimator and math mechanism, so the revision must change Step3B factor construction rather than portfolio weights, long-short adoption, or decile trading.",
        "forbidden_changes": REQUIRED_REVISION_FORBIDDEN_CHANGES[:],
    }


def build_revision_council_ref(root: Path, report_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    branches = summary.get("recommended_branch_templates") if isinstance(summary.get("recommended_branch_templates"), list) else []
    valid_agent = summary.get("valid_agent_results") if isinstance(summary.get("valid_agent_results"), list) else []
    candidate = summary.get("candidate_proposals") if isinstance(summary.get("candidate_proposals"), list) else []
    blocked = summary.get("blocked_proposals") if isinstance(summary.get("blocked_proposals"), list) else []
    blocked_agent = summary.get("blocked_agent_results") if isinstance(summary.get("blocked_agent_results"), list) else []
    return {
        "enabled": True,
        "mode": "agentic" if valid_agent else "scaffold",
        "status": "completed",
        "packet_path": str(council_dir(root, report_id) / f"revision_council_packet__{report_id}.json"),
        "summary_path": str(council_dir(root, report_id) / f"revision_council_summary__{report_id}.json"),
        "proposal_count": proposal_count(root, report_id),
        "valid_proposal_count": len(valid_agent) + len(candidate),
        "blocked_proposal_count": len(blocked) + len(blocked_agent),
        "recommended_branch_count": len(branches),
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
    }


def load_base_handoff(root: Path, report_id: str, iteration: dict[str, Any]) -> dict[str, Any]:
    active = handoff_path(root, report_id)
    if active.exists():
        return load_json(active)
    archived = council_dir(root, report_id) / f"provisional_step3b_handoff_disabled_by_council__{report_id}.json"
    if archived.exists():
        return load_json(archived)
    parent_identity = iteration.get("source_case_identity") if isinstance(iteration.get("source_case_identity"), dict) else {}
    return {
        "report_id": report_id,
        "factor_id": iteration.get("factor_id"),
        "trigger": "main_agent_council_synthesis_approval",
        "parent_identity": parent_identity,
        "new_branch_id": f"{parent_identity.get('branch_id') or 'main'}_iter_{int(iteration.get('iteration_no') or 1):03d}",
        "parent_run_id": parent_identity.get("run_id"),
        "revision_reason": ((iteration.get("research_judgment") or {}).get("thesis")),
        "revision_target": parent_identity.get("implementation_mode"),
        "must_preserve": ["source_type", "factor_id", "original_formula_or_hypothesis"],
        "forbidden_changes": ["portfolio expression", "decile trading", "short-side adoption"],
        "research_judgment": iteration.get("research_judgment") or {},
        "knowledge_writeback": iteration.get("knowledge_writeback") or {},
        "source_case_identity": parent_identity,
        "created_at_utc": iteration.get("created_at_utc") or utc_now(),
        "producer": "main_agent_council_synthesis_approval",
    }


def approve_iteration(
    *,
    root: Path,
    report_id: str,
    iteration: dict[str, Any],
    summary: dict[str, Any],
    synthesis_path: Path,
    synthesis: dict[str, Any],
    selected: dict[str, Any],
    parent_formula: str,
    parent_hash: str,
    child_hash: str,
    implementation_mode: str,
    approval_source: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = json.loads(json.dumps(iteration))
    research_judgment = updated.setdefault("research_judgment", {})
    research_memo = research_judgment.setdefault("research_memo", {})
    final = research_memo.get("final_revision_strategy")
    if not isinstance(final, dict):
        final = research_memo.get("council_revision_strategy") if isinstance(research_memo.get("council_revision_strategy"), dict) else {}
    final = dict(final or {})
    selected_ids = final.get("selected_council_proposal_ids")
    if not isinstance(selected_ids, list) or not selected_ids:
        selected_ids = selected_proposal_ids(summary)
    primary_failure_signature = final.get("primary_failure_signature")
    if primary_failure_signature not in VALID_PRIMARY_FAILURE_SIGNATURES:
        primary_failure_signature = "cost_too_high"
    revision_hypotheses = final.get("revision_hypotheses")
    if not isinstance(revision_hypotheses, list) or not revision_hypotheses:
        revision_hypotheses = [synthesis_revision_hypothesis(selected, implementation_mode)]
    final.update(
        {
            "source": "revision_council",
            "revision_needed": True,
            "primary_failure_signature": primary_failure_signature,
            "revision_hypotheses": revision_hypotheses,
            "revision_quality": "actionable",
            "loop_authorization": "approved_for_step3b_handoff",
            "requires_human_approval_before_code_change": True,
            "approval_required_before_step3b": True,
            "approval_source": approval_source,
            "approved_at_utc": utc_now(),
            "orchestrator_synthesis_path": str(synthesis_path),
            "orchestrator_synthesis_sha256": sha256_file(synthesis_path),
            "selected_executable_revision_law_id": selected.get("law_id"),
            "selected_child_formula": child_formula_or_law(selected),
            "selected_child_formula_hash": child_hash,
            "parent_formula_hash": parent_hash,
            "implementation_mode": implementation_mode,
            "selected_council_proposal_ids": selected_ids,
            "expected_metric_signature": selected.get("expected_metric_signature"),
            "falsification_tests": selected.get("falsification_tests"),
            "kill_criteria": selected.get("kill_criteria"),
            "formula_mutation_description": selected.get("formula_mutation_description"),
        }
    )
    research_memo["final_revision_strategy"] = final
    research_memo["revision_strategy"] = dict(final)
    if not isinstance(updated.get("revision_council_ref"), dict) or updated.get("revision_council_ref", {}).get("enabled") is not True:
        updated["revision_council_ref"] = build_revision_council_ref(root, report_id, summary)
    loop_action = updated.setdefault("loop_action", {})
    if isinstance(loop_action, dict):
        loop_action["should_modify_step3b"] = True
        targets = loop_action.get("modification_targets")
        if not isinstance(targets, list):
            targets = []
        target_text = selected.get("formula_mutation_description") or f"Apply selected Council synthesis law {selected.get('law_id')}"
        if target_text not in targets:
            targets.append(target_text)
        loop_action["modification_targets"] = targets
        loop_action["loop_authorization"] = "approved_for_step3b_handoff"
        loop_action["orchestrator_synthesis_path"] = str(synthesis_path)

    handoff = load_base_handoff(root, report_id, updated)
    law_token = safe_token(selected.get("law_id"))
    handoff.update(
        {
            "report_id": report_id,
            "trigger": "main_agent_council_synthesis_approval",
            "revision_id": law_token,
            "revision_hypothesis_id": law_token,
            "new_branch_id": law_token,
            "loop_authorization": "approved_for_step3b_handoff",
            "authorization": "approved_for_step3b_handoff",
            "status": "approved_for_step3b_handoff",
            "orchestrator_synthesis_path": str(synthesis_path),
            "main_agent_council_synthesis_path": str(synthesis_path),
            "approval_source": approval_source,
            "approved_at_utc": utc_now(),
            "parent_formula": parent_formula,
            "parent_formula_hash": parent_hash,
            "selected_revision": {
                "revision_id": law_token,
                "law_id": selected.get("law_id"),
                "implementation_mode": implementation_mode,
                "child_formula": child_formula_or_law(selected),
                "child_formula_hash": child_hash,
                "direct_code_revision_contract": selected.get("direct_code_revision_contract"),
                "formula_mutation_description": selected.get("formula_mutation_description"),
                "expected_metric_signature": selected.get("expected_metric_signature"),
                "falsification_tests": selected.get("falsification_tests"),
                "kill_criteria": selected.get("kill_criteria"),
                "orchestrator_synthesis_path": str(synthesis_path),
            },
            "executable_revision_spec": {
                "implementation_mode": implementation_mode,
                "revision_type": "formula_mutation" if implementation_mode == "operator" else f"{implementation_mode}_mutation",
                "child_formula": child_formula_or_law(selected),
                "selected_revision_law_id": selected.get("law_id"),
                "direct_code_revision_contract": selected.get("direct_code_revision_contract"),
                "expected_metric_signature": selected.get("expected_metric_signature"),
                "falsification_tests": selected.get("falsification_tests"),
                "kill_criteria": selected.get("kill_criteria"),
            },
            "research_judgment": updated.get("research_judgment") or handoff.get("research_judgment") or {},
            "producer": "main_agent_council_synthesis_approval",
        }
    )
    return updated, handoff


def resolve_under_root(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def loop_brief_paths(root: Path, iteration: dict[str, Any]) -> tuple[Path | None, Path | None]:
    ref = iteration.get("loop_research_brief") if isinstance(iteration.get("loop_research_brief"), dict) else {}
    return resolve_under_root(root, ref.get("json_path")), resolve_under_root(root, ref.get("markdown_path"))


def update_loop_brief_council_section(root: Path, report_id: str, iteration: dict[str, Any], summary: dict[str, Any]) -> None:
    json_path, md_path = loop_brief_paths(root, iteration)
    selected_ids = selected_proposal_ids(summary)
    brief_payload = {
        "enabled": True,
        "mode": "agentic" if summary.get("valid_agent_results") else "scaffold",
        "status": "completed",
        "selected_proposals": selected_ids,
        "recommended_branches": summary.get("recommended_branch_templates") or [],
        "why_no_automatic_step3b_handoff": "Council output required main-agent synthesis approval before Step3B handoff activation.",
        "human_approval_required": True,
        "approved_by_main_agent_synthesis": True,
    }
    if json_path and json_path.exists():
        data = load_json(json_path)
        data["revision_council_summary"] = brief_payload
        write_json(json_path, data)
    if md_path and md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        section = "\n".join(
            [
                "## Revision Council Summary",
                "",
                "- Status: completed",
                f"- Selected proposal ids: {', '.join(selected_ids) if selected_ids else 'none'}",
                "- Why no automatic Step3B handoff: Council output required main-agent synthesis approval before Step3B handoff activation.",
                "- Main-agent synthesis approval: true",
                "",
            ]
        )
        if "## Revision Council Summary" in text:
            text = text.split("## Revision Council Summary", 1)[0].rstrip() + "\n\n" + section
        else:
            text = text.rstrip() + "\n\n" + section
        md_path.write_text(text, encoding="utf-8")


def run_validate_step6(root: Path, report_id: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(
        [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", report_id],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    return {
        "command": [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", report_id],
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve a main-agent Council synthesis as the executable Step3B revision bridge.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factorforge-root", default=None)
    parser.add_argument("--synthesis-path", default=None)
    parser.add_argument("--approval-source", default="current_main_agent_default_approval")
    parser.add_argument("--skip-validate-step6", action="store_true")
    args = parser.parse_args()

    ctx = resolve_factorforge_context(args.factorforge_root)
    root = ctx.factorforge_root
    rid = args.report_id
    synthesis_path = synthesis_path_for(root, rid, args.synthesis_path)
    synthesis, selected = validate_synthesis(root, rid, synthesis_path)
    summary_path = council_dir(root, rid) / f"revision_council_summary__{rid}.json"
    summary = load_json(summary_path)
    iter_path = iteration_path(root, rid)
    if not iter_path.exists():
        block(TOKEN_ITERATION_MISSING, {"report_id": rid, "iteration_path": str(iter_path)})
    iteration = load_json(iter_path)
    parent_formula, parent_hash = parent_formula_and_hash(root, rid)
    implementation_mode = parent_implementation_mode(root, rid, selected)
    _, child_hash = child_formula_hash(child_formula_or_law(selected), parent_hash, implementation_mode, selected)
    out_handoff = handoff_path(root, rid)
    brief_json_path, brief_md_path = loop_brief_paths(root, iteration)
    rollback_snapshot = {
        "iteration": read_text_if_exists(iter_path),
        "handoff": read_text_if_exists(out_handoff),
        "brief_json": read_text_if_exists(brief_json_path) if brief_json_path else None,
        "brief_md": read_text_if_exists(brief_md_path) if brief_md_path else None,
    }
    updated_iteration, handoff = approve_iteration(
        root=root,
        report_id=rid,
        iteration=iteration,
        summary=summary,
        synthesis_path=synthesis_path,
        synthesis=synthesis,
        selected=selected,
        parent_formula=parent_formula,
        parent_hash=parent_hash,
        child_hash=child_hash,
        implementation_mode=implementation_mode,
        approval_source=args.approval_source,
    )
    update_loop_brief_council_section(root, rid, updated_iteration, summary)
    write_json(iter_path, updated_iteration)
    write_json(out_handoff, handoff)
    approval = {
        "approval_version": APPROVAL_VERSION,
        "created_at_utc": utc_now(),
        "report_id": rid,
        "approval_source": args.approval_source,
        "synthesis_path": str(synthesis_path),
        "synthesis_sha256": sha256_file(synthesis_path),
        "handoff_to_step3b_path": str(out_handoff),
        "iteration_path": str(iter_path),
        "selected_law_id": selected.get("law_id"),
        "implementation_mode": implementation_mode,
        "parent_formula_hash": parent_hash,
        "child_formula_hash": child_hash,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_recorded": True,
    }
    validate_result: dict[str, Any] | None = None
    if not args.skip_validate_step6:
        validate_result = run_validate_step6(root, rid)
        approval["validate_step6"] = validate_result
        if validate_result["rc"] != 0:
            restore_text_snapshot(iter_path, rollback_snapshot["iteration"])
            restore_text_snapshot(out_handoff, rollback_snapshot["handoff"])
            if brief_json_path:
                restore_text_snapshot(brief_json_path, rollback_snapshot["brief_json"])
            if brief_md_path:
                restore_text_snapshot(brief_md_path, rollback_snapshot["brief_md"])
            approval["rolled_back_active_writes"] = True
            write_json(approval_path(root, rid), approval)
            print(json.dumps({"result": "BLOCK", "approval": approval}, ensure_ascii=False, indent=2))
            return int(validate_result["rc"] or 1)
    write_json(approval_path(root, rid), approval)
    print(json.dumps({"result": "PASS", "approval": approval}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
