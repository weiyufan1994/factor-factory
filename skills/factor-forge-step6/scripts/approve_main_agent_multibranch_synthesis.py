#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.parser import parse_formula
from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.ultimate_loop.state import next_child_report_id

APPROVAL_VERSION = "factorforge_main_agent_multibranch_synthesis_approval_v1"
SINGLE_SYNTHESIS_VERSION = "factorforge_main_agent_council_synthesis_v1"
MULTIBRANCH_VERSION = "factorforge_main_agent_multibranch_synthesis_v1"
TOKEN_SOURCE_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED"
TOKEN_APPROVAL_INVALID = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_INVALID"
TOKEN_CHILD_COLLISION = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_ID_COLLISION"
TOKEN_DUP_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE"


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


def safe_token(value: Any) -> str:
    text = str(value or "branch").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:64] or "branch"


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def synthesis_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.json"


def markdown_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.md"


def approval_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis_approval__{report_id}.json"


def adapter_dir(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / "multibranch_materialization"


def adapter_synthesis_path(root: Path, report_id: str, branch_index: int, law_id: str) -> Path:
    return adapter_dir(root, report_id) / f"main_agent_council_synthesis__{report_id}__branch{branch_index:02d}__{safe_token(law_id)}.json"


def research_iteration_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"


def handoff_to_step3b_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def formula_hash(formula: str) -> str:
    parsed = parse_formula(formula)
    if parsed.get("parse_status") != "success":
        raise ValueError("BLOCK_FACTORFORGE_MULTIBRANCH_FORMULA_PARSE_FAILED: " + "; ".join(parsed.get("parse_errors") or []))
    return str(parsed.get("formula_hash") or "")


def import_validator():
    validator_path = REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "validate_main_agent_multibranch_synthesis.py"
    spec = importlib.util.spec_from_file_location("validate_main_agent_multibranch_synthesis", validator_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"{TOKEN_APPROVAL_INVALID}: cannot load validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_multibranch(root: Path, report_id: str, src: Path, md: Path) -> dict[str, Any]:
    module = import_validator()
    validation = module.validate(root, report_id, src, md)
    if validation.get("result") != "PASS":
        print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
    return validation


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def selected_revision_from_branch(branch: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_id": branch.get("law_id"),
        "child_formula": branch.get("child_formula"),
        "why_selected": branch.get("why_selected"),
        "formula_mutation_description": branch.get("formula_mutation_description")
        or branch.get("why_selected")
        or f"Apply multibranch law {branch.get('law_id')}.",
        "economic_mechanism_link": branch.get("economic_mechanism_link"),
        "math_model_link": branch.get("math_model_link"),
        "expected_metric_signature": branch.get("expected_metric_signature") or {},
        "falsification_tests": branch.get("falsification_tests") or [],
        "kill_criteria": branch.get("kill_criteria") or [],
        "source_agent_roles": branch.get("source_agent_roles") or [],
    }


def write_adapter_synthesis(
    *,
    path: Path,
    parent_report_id: str,
    synthesis: dict[str, Any],
    branch: dict[str, Any],
    branch_context: dict[str, Any],
) -> None:
    payload = {
        "contract_version": SINGLE_SYNTHESIS_VERSION,
        "report_id": parent_report_id,
        "created_at_utc": utc_now(),
        "producer": "main_agent_multibranch_approval_adapter",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "source_multibranch_synthesis_path": branch_context["source_multibranch_synthesis_path"],
        "source_multibranch_synthesis_sha256": branch_context["source_multibranch_synthesis_sha256"],
        "branch_context": branch_context,
        "prior_revision_memory": synthesis.get("prior_revision_memory") or {},
        "consensus_summary": synthesis.get("consensus_summary"),
        "disagreement_summary": synthesis.get("disagreement_summary"),
        "selected_revision": selected_revision_from_branch(branch),
    }
    write_json(path, payload)


def activate_multibranch_materialization_handoff(root: Path, report_id: str, approval_payload: dict[str, Any]) -> dict[str, Any]:
    iteration_path = research_iteration_path(root, report_id)
    iteration = load_json(iteration_path)
    if not iteration:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: research_iteration_master missing")
    judgment = iteration.setdefault("research_judgment", {})
    if not isinstance(judgment, dict):
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: research_judgment invalid")
    memo = judgment.setdefault("research_memo", {})
    if not isinstance(memo, dict):
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: research_memo invalid")
    revision_strategy = memo.setdefault("revision_strategy", {})
    if not isinstance(revision_strategy, dict):
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: revision_strategy invalid")
    final_revision_strategy = memo.setdefault("final_revision_strategy", {})
    if not isinstance(final_revision_strategy, dict):
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: final_revision_strategy invalid")
    for target in (revision_strategy, final_revision_strategy):
        target["revision_needed"] = True
        target["loop_authorization"] = "approved_for_step3b_handoff"
        target["authorization_source"] = "main_agent_multibranch_synthesis_approval"
        target["branch_group_id"] = approval_payload.get("branch_group_id")
    write_json(iteration_path, iteration)

    branch_group_id = str(approval_payload.get("branch_group_id") or f"{report_id}__MULTIBRANCH")
    path = handoff_to_step3b_path(root, report_id)
    if path.exists():
        return {
            "research_iteration_path": str(iteration_path),
            "handoff_to_step3b_path": str(path),
            "reused_existing_handoff": True,
        }

    handoff = {
        "report_id": report_id,
        "status": "approved_for_step3b_handoff",
        "loop_authorization": "approved_for_step3b_handoff",
        "revision_id": branch_group_id,
        "new_branch_id": branch_group_id,
        "parent_identity": {"report_id": report_id, "run_id": f"{report_id}__multibranch_parent"},
        "parent_run_id": f"{report_id}__multibranch_parent",
        "approval_mode": "main_agent_multibranch_synthesis",
        "main_agent_multibranch_synthesis_approval_path": str(approval_path(root, report_id)),
        "branch_group_id": branch_group_id,
        "selected_branch_count": approval_payload.get("selected_branch_count"),
        "selected_branches": [
            {
                "branch_index": branch.get("branch_index"),
                "branch_role": branch.get("branch_role"),
                "law_id": branch.get("law_id"),
                "child_report_id": branch.get("child_report_id"),
                "child_formula_hash": branch.get("child_formula_hash"),
                "adapter_synthesis_path": branch.get("adapter_synthesis_path"),
                "adapter_synthesis_sha256": branch.get("adapter_synthesis_sha256"),
            }
            for branch in approval_payload.get("selected_branches") or []
            if isinstance(branch, dict)
        ],
    }
    write_json(path, handoff)
    return {"research_iteration_path": str(iteration_path), "handoff_to_step3b_path": str(path), "reused_existing_handoff": False}


def approve(root: Path, report_id: str, *, loop_index: int, approval_source: str) -> dict[str, Any]:
    src = synthesis_path(root, report_id)
    md = markdown_path(root, report_id)
    validation = validate_multibranch(root, report_id, src, md)
    if validation.get("result") != "PASS":
        return {"ok": False, "validation": validation}

    synthesis = load_json(src)
    if synthesis.get("contract_version") != MULTIBRANCH_VERSION:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: invalid contract_version")
    source_sha = sha256_file(src)
    approval = approval_path(root, report_id)
    if approval.exists():
        existing = load_json(approval)
        if existing.get("source_multibranch_synthesis_sha256") != source_sha:
            raise ValueError(f"{TOKEN_SOURCE_CHANGED}: existing approval does not match current synthesis")

    branches = synthesis.get("selected_branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError(f"{TOKEN_APPROVAL_INVALID}: selected_branches missing")
    branch_group_id = f"{report_id}__LOOP{loop_index:02d}__MULTIBRANCH"
    child_ids: set[str] = set()
    child_hashes: set[str] = set()
    approved_branches: list[dict[str, Any]] = []
    for idx, raw in enumerate(branches):
        branch = raw if isinstance(raw, dict) else {}
        law_id = nonempty_str(branch.get("law_id"))
        branch_role = nonempty_str(branch.get("branch_role"))
        child_formula = nonempty_str(branch.get("child_formula"))
        child_hash = formula_hash(child_formula)
        if child_hash in child_hashes:
            raise ValueError(f"{TOKEN_DUP_HASH}:branch[{idx}]")
        child_hashes.add(child_hash)
        child_report_id = next_child_report_id(report_id, loop_index, f"{branch_role}_{law_id}")
        if child_report_id == report_id or child_report_id in child_ids:
            raise ValueError(f"{TOKEN_CHILD_COLLISION}:branch[{idx}]")
        child_ids.add(child_report_id)
        adapter_path = adapter_synthesis_path(root, report_id, idx, law_id)
        branch_context = {
            "parent_report_id": report_id,
            "child_report_id": child_report_id,
            "law_id": law_id,
            "branch_role": branch_role,
            "branch_index": idx,
            "branch_group_id": branch_group_id,
            "source_multibranch_synthesis_path": str(src),
            "source_multibranch_synthesis_sha256": source_sha,
            "sibling_branch_count": len(branches),
        }
        write_adapter_synthesis(
            path=adapter_path,
            parent_report_id=report_id,
            synthesis=synthesis,
            branch=branch,
            branch_context=branch_context,
        )
        adapter_sha = sha256_file(adapter_path)
        approved_branches.append(
            {
                "branch_index": idx,
                "branch_role": branch_role,
                "law_id": law_id,
                "child_report_id": child_report_id,
                "child_formula": child_formula,
                "child_formula_hash": child_hash,
                "adapter_synthesis_path": str(adapter_path),
                "adapter_synthesis_sha256": adapter_sha,
                "branch_context": branch_context,
            }
        )

    payload = {
        "contract_version": APPROVAL_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": report_id,
        "source_multibranch_synthesis_path": str(src),
        "source_multibranch_synthesis_sha256": source_sha,
        "branch_group_id": branch_group_id,
        "approval_source": approval_source,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "selected_branch_count": len(approved_branches),
        "selected_branches": approved_branches,
        "validation": validation,
    }
    write_json(approval, payload)
    activated = activate_multibranch_materialization_handoff(root, report_id, payload)
    payload["activated_materialization_handoff"] = activated
    write_json(approval, payload)
    return {"ok": True, "approval_path": str(approval), "approval": payload}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Approve a validated main-agent multibranch synthesis for guarded materialization.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--loop-index", type=int, default=1)
    ap.add_argument("--approval-source", default="manual_main_agent")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ctx = resolve_factorforge_context(args.factorforge_root)
        result = approve(ctx.factorforge_root, args.report_id, loop_index=args.loop_index, approval_source=args.approval_source)
    except ValueError as exc:
        print(str(exc))
        return 1
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
