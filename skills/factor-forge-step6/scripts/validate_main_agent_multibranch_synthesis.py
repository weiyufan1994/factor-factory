#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.parser import parse_formula
from factor_factory.artifact_identity import stable_hash
from factor_factory.runtime_context import resolve_factorforge_context

CONTRACT_VERSION = "factorforge_main_agent_multibranch_synthesis_v1"

TOKEN_MISSING = "BLOCK_FACTORFORGE_MULTIBRANCH_SYNTHESIS_MISSING"
TOKEN_CONTRACT = "BLOCK_FACTORFORGE_MULTIBRANCH_CONTRACT_INVALID"
TOKEN_MARKDOWN = "BLOCK_FACTORFORGE_MULTIBRANCH_MARKDOWN_MISSING"
TOKEN_TOO_MANY = "BLOCK_FACTORFORGE_MULTIBRANCH_TOO_MANY_BRANCHES"
TOKEN_EXPLOIT_COUNT = "BLOCK_FACTORFORGE_MULTIBRANCH_EXPLOIT_BRANCH_COUNT"
TOKEN_FIELD = "BLOCK_FACTORFORGE_MULTIBRANCH_BRANCH_FIELD_MISSING"
TOKEN_DUP_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_DUPLICATE_FORMULA_HASH"
TOKEN_PARENT_REPEAT = "BLOCK_FACTORFORGE_MULTIBRANCH_PARENT_FORMULA_REPEATED"
TOKEN_FORBIDDEN_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_FORBIDDEN_FORMULA_HASH"
TOKEN_FORBIDDEN_RULE = "BLOCK_FACTORFORGE_MULTIBRANCH_FORBIDDEN_REVISION_RULE"
TOKEN_NO_DIVERSITY = "BLOCK_FACTORFORGE_MULTIBRANCH_NO_MECHANISM_DIVERSITY"
TOKEN_PARSE = "BLOCK_FACTORFORGE_MULTIBRANCH_FORMULA_PARSE_FAILED"
TOKEN_BRANCH_PERMISSION = "BLOCK_FACTORFORGE_MULTIBRANCH_BRANCH_PERMISSION_UNSAFE"
TOKEN_DIRECT_CODE_CONTRACT = "BLOCK_FACTORFORGE_MULTIBRANCH_DIRECT_CODE_CONTRACT_MISSING"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) and bool(value) else []


def nonempty_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) and bool(value) else {}


def council_dir(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def default_synthesis_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.json"


def default_markdown_path(root: Path, report_id: str) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.md"


def factor_spec_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"


def resolve_path(root: Path, raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def parent_formula_hash(root: Path, report_id: str) -> str | None:
    spec = load_json(factor_spec_path(root, report_id))
    canonical = spec.get("canonical_spec") if isinstance(spec.get("canonical_spec"), dict) else {}
    formula = nonempty_str(canonical.get("formula_text"))
    if not formula:
        return None
    parsed = parse_formula(formula)
    return str(parsed.get("formula_hash") or "") if parsed.get("parse_status") == "success" else None


def prior_memory(root: Path, report_id: str, synthesis: dict[str, Any]) -> dict[str, Any]:
    embedded = synthesis.get("prior_revision_memory")
    if isinstance(embedded, dict) and embedded:
        return embedded
    packet_path = council_dir(root, report_id) / f"revision_council_packet__{report_id}.json"
    packet = load_json(packet_path)
    packet_prior = packet.get("prior_revision_memory")
    return packet_prior if isinstance(packet_prior, dict) else {}


def branch_formula_or_law(branch: dict[str, Any]) -> str:
    return (
        nonempty_str(branch.get("child_formula"))
        or nonempty_str(branch.get("child_formula_or_law"))
        or nonempty_str(branch.get("direct_code_law"))
        or nonempty_str(branch.get("formula_law"))
    )


def branch_implementation_mode(branch: dict[str, Any]) -> str:
    explicit = nonempty_str(branch.get("implementation_mode"))
    if explicit:
        return explicit
    if isinstance(branch.get("direct_code_revision_contract"), dict) and branch["direct_code_revision_contract"]:
        return "direct_code"
    if isinstance(branch.get("hybrid_revision_contract"), dict) and branch["hybrid_revision_contract"]:
        return "hybrid"
    return "operator"


def branch_revision_hash(branch: dict[str, Any]) -> tuple[str | None, str | None, str]:
    law_text = branch_formula_or_law(branch)
    if not law_text:
        return None, None
    implementation_mode = branch_implementation_mode(branch)
    if implementation_mode in {"direct_code", "hybrid"}:
        contract_key = "direct_code_revision_contract" if implementation_mode == "direct_code" else "hybrid_revision_contract"
        contract = branch.get(contract_key)
        if not isinstance(contract, dict) or not contract:
            contract = branch.get("direct_code_revision_contract")
        if not isinstance(contract, dict) or not contract:
            return None, TOKEN_DIRECT_CODE_CONTRACT, implementation_mode
        return stable_hash(
            {
                "hash_role": f"{implementation_mode}_multibranch_code_law_hash",
                "implementation_mode": implementation_mode,
                "child_formula_or_law": law_text,
                "revision_contract": contract,
            }
        ), None, implementation_mode
    parsed = parse_formula(law_text)
    if parsed.get("parse_status") != "success":
        return None, json.dumps(parsed.get("parse_errors") or [], ensure_ascii=False), implementation_mode
    return str(parsed.get("formula_hash") or ""), None, implementation_mode


def mechanism_diversity_ok(branch: dict[str, Any], exploit: dict[str, Any]) -> bool:
    role = branch.get("branch_role")
    if role != "exploration":
        return True
    diff = nonempty_str(branch.get("how_it_differs_from_exploit"))
    if not diff:
        return False
    branch_economic = nonempty_str(branch.get("economic_mechanism_link"))
    branch_math = nonempty_str(branch.get("math_model_link"))
    exploit_economic = nonempty_str(exploit.get("economic_mechanism_link"))
    exploit_math = nonempty_str(exploit.get("math_model_link"))
    difference_class = nonempty_str(branch.get("mechanism_difference_class")).lower()
    if branch_economic.lower() == exploit_economic.lower() and branch_math.lower() == exploit_math.lower():
        return False
    if difference_class in {"parameter_tuning", "window_tuning", "bandwidth_tuning"}:
        return False
    text = " ".join(
        [
            diff,
            branch_economic,
            branch_math,
            difference_class,
        ]
    ).lower()
    exploit_text = " ".join(
        [
            nonempty_str(exploit.get("economic_mechanism_link")),
            nonempty_str(exploit.get("math_model_link")),
        ]
    ).lower()
    if text and text == exploit_text:
        return False
    mechanism_terms = {
        "state",
        "latent",
        "estimator",
        "participation",
        "imbalance",
        "pressure",
        "conditioning",
        "conditioned",
        "payoff",
        "process",
        "diffusion",
        "jump",
        "threshold",
        "interaction",
        "horizon",
        "information",
        "counterparty",
        "flow",
        "shock",
    }
    parameter_only_terms = {"parameter", "window", "lookback", "length", "smooth", "smoothing", "bandwidth", "tune", "tuning"}
    has_mechanism_term = any(term in text for term in mechanism_terms)
    parameter_only = any(term in text for term in parameter_only_terms) and not has_mechanism_term
    return has_mechanism_term and not parameter_only


def validate(root: Path, report_id: str, synthesis_path: Path, markdown_path: Path | None) -> dict[str, Any]:
    reasons: list[str] = []
    branch_hashes: dict[str, str] = {}
    if not synthesis_path.exists():
        return {"result": "BLOCK", "block_reasons": [TOKEN_MISSING], "synthesis_path": str(synthesis_path)}
    synthesis = load_json(synthesis_path)
    if synthesis.get("contract_version") != CONTRACT_VERSION:
        reasons.append(TOKEN_CONTRACT)
    if synthesis.get("report_id") != report_id:
        reasons.append(TOKEN_CONTRACT)
    if synthesis.get("canonical_write_permission") is not False:
        reasons.append(TOKEN_CONTRACT)
    if synthesis.get("execution_allowed_by_default") is not False:
        reasons.append(TOKEN_CONTRACT)
    if synthesis.get("human_approval_required") is not True:
        reasons.append(TOKEN_CONTRACT)
    if markdown_path is not None and not markdown_path.exists():
        reasons.append(TOKEN_MARKDOWN)

    selected = synthesis.get("selected_branches")
    branches = selected if isinstance(selected, list) else []
    if not branches:
        reasons.append(TOKEN_FIELD)
    if len(branches) > 3:
        reasons.append(TOKEN_TOO_MANY)
    exploit_branches = [b for b in branches if isinstance(b, dict) and b.get("branch_role") == "exploit"]
    exploration_branches = [b for b in branches if isinstance(b, dict) and b.get("branch_role") == "exploration"]
    if len(exploit_branches) != 1:
        reasons.append(TOKEN_EXPLOIT_COUNT)
    if len(exploration_branches) > 2:
        reasons.append(TOKEN_TOO_MANY)

    parent_hash = parent_formula_hash(root, report_id)
    prior = prior_memory(root, report_id, synthesis)
    forbidden_hashes = {str(item) for item in (prior.get("forbidden_repeat_formula_hashes") or []) if str(item).strip()}
    forbidden_rules = {str(item) for item in (prior.get("forbidden_repeat_revision_rules") or []) if str(item).strip()}
    required_fields = [
        "branch_role",
        "law_id",
        "why_selected",
        "economic_mechanism_link",
        "math_model_link",
        "expected_metric_signature",
        "falsification_tests",
        "kill_criteria",
        "source_agent_roles",
    ]
    seen_hashes: dict[str, str] = {}
    for idx, raw in enumerate(branches):
        branch = raw if isinstance(raw, dict) else {}
        missing = []
        if branch.get("canonical_write_permission") is True:
            reasons.append(f"{TOKEN_BRANCH_PERMISSION}:branch[{idx}]:canonical_write_permission")
        if branch.get("execution_allowed_by_default") is True:
            reasons.append(f"{TOKEN_BRANCH_PERMISSION}:branch[{idx}]:execution_allowed_by_default")
        if branch.get("human_approval_required") is False:
            reasons.append(f"{TOKEN_BRANCH_PERMISSION}:branch[{idx}]:human_approval_required")
        for field in required_fields:
            value = branch.get(field)
            if field in {"expected_metric_signature"}:
                ok = bool(nonempty_dict(value))
            elif field in {"falsification_tests", "kill_criteria", "source_agent_roles"}:
                ok = bool(nonempty_list(value))
            else:
                ok = bool(nonempty_str(value))
            if not ok:
                missing.append(field)
        if not branch_formula_or_law(branch):
            missing.append("child_formula")
        implementation_mode = branch_implementation_mode(branch)
        if implementation_mode not in {"operator", "direct_code", "hybrid"}:
            missing.append("implementation_mode")
        if implementation_mode in {"direct_code", "hybrid"}:
            contract_key = "direct_code_revision_contract" if implementation_mode == "direct_code" else "hybrid_revision_contract"
            contract = branch.get(contract_key)
            if not isinstance(contract, dict) or not contract:
                contract = branch.get("direct_code_revision_contract")
            if not isinstance(contract, dict) or not contract:
                missing.append(contract_key)
        role = branch.get("branch_role")
        if role not in {"exploit", "exploration"}:
            missing.append("branch_role")
        if role == "exploration" and not nonempty_str(branch.get("how_it_differs_from_exploit")):
            missing.append("how_it_differs_from_exploit")
        if missing:
            reasons.append(f"{TOKEN_FIELD}:branch[{idx}]:" + ",".join(sorted(set(missing))))
        law_id = nonempty_str(branch.get("law_id"))
        if law_id and law_id in forbidden_rules:
            reasons.append(f"{TOKEN_FORBIDDEN_RULE}:branch[{idx}]")
        formula_hash, parse_error, implementation_mode = branch_revision_hash(branch)
        if parse_error:
            token = TOKEN_DIRECT_CODE_CONTRACT if parse_error == TOKEN_DIRECT_CODE_CONTRACT else TOKEN_PARSE
            reasons.append(f"{token}:branch[{idx}]")
            continue
        if formula_hash:
            branch_hashes[law_id or f"branch_{idx}"] = formula_hash
            if parent_hash and formula_hash == parent_hash:
                reasons.append(f"{TOKEN_PARENT_REPEAT}:branch[{idx}]")
            if formula_hash in forbidden_hashes:
                reasons.append(f"{TOKEN_FORBIDDEN_HASH}:branch[{idx}]")
            if formula_hash in seen_hashes:
                reasons.append(f"{TOKEN_DUP_HASH}:branch[{idx}]")
            seen_hashes[formula_hash] = law_id or f"branch_{idx}"
    if exploit_branches and exploration_branches:
        exploit = exploit_branches[0]
        for branch in exploration_branches:
            if not mechanism_diversity_ok(branch, exploit):
                reasons.append(TOKEN_NO_DIVERSITY)
                break

    result = "PASS" if not reasons else "BLOCK"
    return {
        "result": result,
        "report_id": report_id,
        "synthesis_path": str(synthesis_path),
        "markdown_path": str(markdown_path) if markdown_path else None,
        "block_reasons": sorted(set(reasons)),
        "branch_count": len(branches),
        "exploit_branch_count": len(exploit_branches),
        "exploration_branch_count": len(exploration_branches),
        "branch_formula_hashes": branch_hashes,
        "parent_formula_hash": parent_hash,
        "forbidden_repeat_formula_hashes": sorted(forbidden_hashes),
        "forbidden_repeat_revision_rules": sorted(forbidden_rules),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate main-agent multi-branch Council synthesis.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--synthesis-path")
    parser.add_argument("--markdown-path")
    parser.add_argument("--allow-missing-markdown", action="store_true")
    args = parser.parse_args()
    ctx = resolve_factorforge_context()
    root = ctx.factorforge_root
    synthesis_path = resolve_path(root, args.synthesis_path, default_synthesis_path(root, args.report_id))
    markdown_path = None if args.allow_missing_markdown else resolve_path(root, args.markdown_path, default_markdown_path(root, args.report_id))
    payload = validate(root, args.report_id, synthesis_path, markdown_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
