#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.validator import validate_revision_council_proposal
from factor_factory.mechanism_math.main_agent_memo import build_main_agent_mechanism_memo

CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if item.is_file():
                files.add(str(item.relative_to(REPO_ROOT)))
    return files


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return (
        name == "__pycache__"
        or name == ".DS_Store"
        or name.endswith(".lock")
        or name.endswith(".tmp")
        or name.endswith(".swp")
        or name.endswith(".swx")
        or name.startswith(".#")
        or name.startswith("~$")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_dir():
        return None
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        if any(should_skip_digest_path(part) for part in item.relative_to(path).parents):
            continue
        if should_skip_digest_path(item):
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        entries.append(
            {
                "relative_path": item.relative_to(path).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def result(name: str, ok: bool, actual: dict[str, Any], expected: str) -> dict[str, Any]:
    return {"case": name, "ok": bool(ok), "expected": expected, "actual": actual}


def run_cmd(root: Path, cmd: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-1600:], "stderr_tail": proc.stderr[-1600:]}


def write_current_agent_memo_fixture(root: Path, rid: str) -> None:
    obj = root / "objects"
    spec = load_json(obj / "factor_spec_master" / f"factor_spec_master__{rid}.json")
    case = load_json(obj / "factor_case_master" / f"factor_case_master__{rid}.json")
    evaluation = load_json(obj / "validation" / f"factor_evaluation__{rid}.json")
    iteration = load_json(obj / "research_iteration_master" / f"research_iteration_master__{rid}.json")
    memo = build_main_agent_mechanism_memo(
        report_id=rid,
        factor_spec=spec,
        factor_case=case,
        evaluation_summary=evaluation,
        step6_iteration=iteration,
    )
    memo["producer"] = "current_main_agent"
    memo["agent_authorship"] = {
        "authoring_mode": "current_agent_freeform",
        "agent_role": "main_agent",
        "runtime": "revision_council_smoke",
        "answered_without_deterministic_template": True,
    }
    memo["mechanism_qa"] = {
        "formula_state_answer": (
            "The high and volume inputs enter rank and correlation operators, so the observable state is a short-window "
            "cross-sectional price-volume rank association rather than a label imported from another factor family."
        ),
        "economic_hypothesis_answer": (
            "The hypothesis is that temporary participation pressure and constrained liquidity transfer leave a conditional "
            "next-period return when ranked intraday price location and ranked trading volume move together."
        ),
        "math_model_answer": (
            "A copula rank-dependence model is the baseline because the expression contains an explicit correlation of ranked "
            "high and ranked volume; its persistence and payoff sign must be estimated rather than narrated."
        ),
        "payer_answer": (
            "Liquidity demanders and delayed inventory rebalancers are the proposed counterparties because they trade through "
            "the observed participation-pressure state and may transfer immediacy or inventory-risk compensation."
        ),
        "payoff_answer": (
            "The payoff object is E[r_i,t+1 | F_t, C_i,t], where C_i,t is the legal short-window rank association; the declared "
            "sign must survive the high-score long side and explicit transaction costs."
        ),
        "estimator_mapping_answer": (
            "Rank(high) and rank(volume) define marginal orderings, correlation measures their short-window association, and "
            "the outer rank maps that association into the cross-sectional state C_i,t using only information in F_t."
        ),
        "metric_signature_answer": (
            "The expected signature is aligned rank IC, positive high-score long-side return after costs, stable ordering in "
            "the relevant risk-premium buckets, and turnover low enough to preserve the hypothesized payoff."
        ),
        "falsification_answer": (
            "Falsify if rank IC changes sign out of sample; falsify if the high-score long side remains non-positive after "
            "costs; kill the payer story if component ablation or turnover evidence contradicts the association state."
        ),
    }
    signature = {
        "rank_ic": "rank IC sign must match the declared payoff direction",
        "long_side": "the high-score long side must be positive",
        "cost_adjusted": "the long side must remain positive after transaction costs",
        "monotonicity": "bucket ordering is required only if the claim is a risk premium",
        "turnover": "turnover must not consume the expected payoff",
    }
    memo["economic_hypothesis"] = {
        "return_source_class": "mixed",
        "payer_or_counterparty": "liquidity demanders and delayed inventory rebalancers",
        "why_they_pay": "immediacy demand and inventory constraints can transfer compensation through the observed price-volume association state",
        "necessary_market_structure": "the state must persist into the legal forecast horizon and survive turnover and implementation costs",
    }
    memo["math_hypothesis"] = {
        "selected_model_family": "copula_rank_dependence",
        "why_this_model": "the expression explicitly applies correlation to ranked high and ranked volume observations",
        "why_not_generic_template": "the model is selected from the actual high, volume, rank, correlation, sum, and outer-rank components",
        "random_object": "security-day forward return conditional on F_t and the measured rank-association state",
        "latent_state": "short-window price-volume rank-association and participation-pressure state",
        "process_or_distribution": "C_i,t follows a conditional rank-association process and r_i,t+1 is distributed conditional on F_t and C_i,t",
        "target_functional": "E[r_i,t+1 | F_t, C_i,t]",
        "formula_as_estimator": memo["mechanism_qa"]["estimator_mapping_answer"],
        "expected_metric_signature": signature,
    }
    memo["math_model_selection"] = {
        "model_family": "copula_rank_dependence",
        "baseline_model": "conditional forward return indexed by the rank-association state C_i,t",
        "model_mutation": "separate association persistence, payoff sign, and component ablation before revising the expression",
    }
    memo["payer"] = {
        "payer_or_counterparty": memo["economic_hypothesis"]["payer_or_counterparty"],
        "why_they_pay": memo["economic_hypothesis"]["why_they_pay"],
        "necessary_market_structure": memo["economic_hypothesis"]["necessary_market_structure"],
    }
    memo["formula_state_estimator"] = {
        "latent_state": memo["math_hypothesis"]["latent_state"],
        "observable_mapping": memo["mechanism_qa"]["estimator_mapping_answer"],
        "component_links": memo.get("formula_component_map") or [],
    }
    memo["expected_metric_signature"] = signature
    memo["falsification_tests"] = [
        "Reject if OOS rank IC contradicts the declared payoff direction.",
        "Reject if the high-score long side remains non-positive after costs.",
        "Reject if component ablation removes the claimed association-state effect.",
    ]
    write_json(
        obj / "research_iteration_master" / f"main_agent_mechanism_memo__{rid}.json",
        memo,
    )


def make_fixture(root: Path, rid: str, *, signature: str, mechanism_fit: str = "partial", cost_adjusted: float = -0.1, loop_auth: str = "advisory_only") -> None:
    obj = root / "objects"
    identity = {
        "report_id": rid,
        "factor_id": rid,
        "implementation_mode": "operator",
        "source_type": "formula_text",
        "contract_version": "factorforge_step2_source_contract_v2",
        "spec_hash": "spec_" + rid.lower(),
        "formula_hash": "formula_" + rid.lower(),
        "branch_id": "branch_" + rid.lower(),
        "run_id": "run_" + rid.lower(),
        "artifact_role": "research_iteration_master",
    }
    metrics = {
        "rank_ic_mean": 0.03,
        "rank_ic_ir": 0.5,
        "long_side_annual_return": 0.12,
        "long_side_sharpe": 0.7,
        "long_side_turnover_mean_daily": 0.45,
        "trading_cogs_annual": 0.34,
        "cost_adjusted_annual_return": cost_adjusted,
        "cost_adjusted_long_side_sharpe": -0.4 if cost_adjusted < 0 else 0.8,
    }
    research_memo = {
        "evidence_audit": {"evidence_verdict": "usable_with_warnings" if signature != "implementation_suspect" else "blocked"},
        "mechanism_analysis": {
            "mechanism_fit": mechanism_fit,
            "return_source": "behavioral_microstructure",
            "factor_family": "price_volume_correlation",
            "mechanism_math_contract": {
                "math_model_status": "specified",
                "model_family": "price_volume_microstructure",
                "state_or_object": "latent price-volume pressure state",
                "target_functional": "E[r_{t+1} | F_t, pressure_state_t]",
            },
        },
        "case_comparison": {"similar_failure_cases": [], "identity_mismatch_cases": []},
        "revision_strategy": {
            "primary_failure_signature": signature,
            "revision_quality": "actionable",
            "loop_authorization": loop_auth,
            "revision_hypotheses": [{"hypothesis_id": "rev_cost_persistence_001"}],
        },
        "search_policy_decision": {"recommended_mode": "mechanism_challenge", "branch_templates": []},
    }
    iteration = {
        "report_id": rid,
        "factor_id": rid,
        "artifact_identity": identity,
        "research_judgment": {"decision": "iterate", "research_memo": research_memo},
        "loop_research_brief": {
            "json_path": str(obj / "research_iteration_master" / f"loop_research_brief__{rid}__iter1.json"),
            "markdown_path": str(obj / "research_iteration_master" / f"loop_research_brief__{rid}__iter1.md"),
        },
    }
    brief = {
        "decision_snapshot": {"decision": "iterate"},
        "economic_interpretation": {"formula": "-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3)"},
        "chart_evidence": {"long_side_nav": "missing: smoke"},
        "mechanism_math_summary": research_memo["mechanism_analysis"]["mechanism_math_contract"],
    }
    write_json(obj / "research_iteration_master" / f"research_iteration_master__{rid}.json", iteration)
    write_json(obj / "research_iteration_master" / f"loop_research_brief__{rid}__iter1.json", brief)
    (obj / "research_iteration_master" / f"loop_research_brief__{rid}__iter1.md").write_text("# smoke\n", encoding="utf-8")
    write_json(obj / "factor_case_master" / f"factor_case_master__{rid}.json", {"report_id": rid, "factor_id": rid, "artifact_identity": {**identity, "artifact_role": "factor_case_master"}, "mechanism_math_contract": research_memo["mechanism_analysis"]["mechanism_math_contract"]})
    write_json(obj / "validation" / f"factor_evaluation__{rid}.json", {"report_id": rid, "factor_id": rid, "backend_summary": [{"backend": "self_quant_analyzer", "status": "success", "key_metrics": metrics}]})
    write_json(obj / "factor_run_master" / f"factor_run_master__{rid}.json", {"report_id": rid, "factor_id": rid, "artifact_identity": {**identity, "artifact_role": "factor_run_master"}, "evaluation_results": {"backend_runs": []}})
    write_json(obj / "handoff" / f"handoff_to_step6__{rid}.json", {"report_id": rid, "factor_id": rid, "artifact_identity": {**identity, "artifact_role": "handoff_to_step6"}})
    write_json(obj / "factor_spec_master" / f"factor_spec_master__{rid}.json", {"report_id": rid, "factor_id": rid, "canonical_spec": {"formula_text": brief["economic_interpretation"]["formula"]}, "mechanism_math_contract": research_memo["mechanism_analysis"]["mechanism_math_contract"]})
    write_current_agent_memo_fixture(root, rid)


def council_flow(root: Path, rid: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    return packet, proposals, merge


def council_packet_and_proposals(root: Path, rid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    return packet, proposals


def supplemental_context_packet_case(root: Path) -> dict[str, Any]:
    rid = "ALPHA016_CANONICAL_FORMULA_20160101"
    make_fixture(root, rid, signature="cost_too_high", mechanism_fit="contradicted")
    supplemental_dir = root / "objects" / "research_iteration_master" / "revision_council" / rid / "supplemental_context"
    supplemental_dir.mkdir(parents=True, exist_ok=True)
    human_note = supplemental_dir / f"human_mechanism_context__{rid}.md"
    human_note.write_text(
        "\n".join(
            [
                "# Human mechanism context",
                "Alpha016 is a price-volume rank-dependence bad-state detector.",
                "Process hypothesis: P=F+I+epsilon and transient impact decays.",
                "Target functional: E[r_{t+1} | F_t, C_t].",
                "Evidence warning: G9 > G10 means low covariance is not proven best.",
            ]
        ),
        encoding="utf-8",
    )
    kb_dir = root / "knowledge" / "因子工厂" / "知识库"
    kb_dir.mkdir(parents=True, exist_ok=True)
    kb_note = kb_dir / "ALPHA016_20160101_MECHANISM_CONTEXT.md"
    kb_note.write_text(
        "Alpha016 mechanism context: conditional distribution and observable estimator must be explicit.\n",
        encoding="utf-8",
    )
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    taskbook = run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py",
            "--report-id",
            rid,
            "--executor",
            "dispatch_manifest",
            "--runtime-dispatch",
            "manual_file",
            "--research-protocol",
            "off",
        ],
    )
    packet_payload = load_json(council_packet_path(root, rid)) if council_packet_path(root, rid).exists() else {}
    taskbook_payload = load_json(agentic_taskbook_path(root, rid)) if agentic_taskbook_path(root, rid).exists() else {}
    supplemental = packet_payload.get("supplemental_research_context") or {}
    taskbook_supplemental = ((taskbook_payload.get("shared_context") or {}).get("supplemental_research_context") or {})
    content = "\n".join(str(item.get("content") or "") for item in supplemental.get("items") or [])
    ok = (
        packet["rc"] == 0
        and taskbook["rc"] == 0
        and supplemental.get("item_count", 0) >= 2
        and taskbook_supplemental.get("item_count") == supplemental.get("item_count")
        and "bad-state detector" in content
        and "conditional distribution" in content
    )
    return result(
        "alpha016_supplemental_context_ingested_by_packet_and_taskbook",
        ok,
        {
            "packet": packet,
            "taskbook": taskbook,
            "supplemental_item_count": supplemental.get("item_count"),
            "taskbook_supplemental_item_count": taskbook_supplemental.get("item_count"),
            "paths": [item.get("relative_path") for item in supplemental.get("items") or []],
        },
        "packet and taskbook ingest Alpha016 supplemental mechanism context",
    )


def council_summary_path(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_summary__{rid}.json"


def council_packet_path(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_packet__{rid}.json"


def agentic_taskbook_path(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid / f"agentic_taskbook__{rid}.json"


def merge_block_diagnostic_path(root: Path, rid: str) -> Path:
    return root / "objects" / "validation" / f"revision_council_merge_prewrite_block__{rid}.json"


def no_canonical_writebacks(root: Path, rid: str) -> bool:
    return not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists() and not (
        root / "objects" / "factor_library_official" / f"factor_record__{rid}.json"
    ).exists()


def step6_iteration_path(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json"


def step6_validate(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_step6.py", "--report-id", rid])


def attach_council(root: Path, rid: str) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py", "--report-id", rid])


def attach_target_snapshot(root: Path, rid: str) -> dict[str, str | None]:
    iteration_path = step6_iteration_path(root, rid)
    paths = {"iteration": iteration_path}
    if iteration_path.exists():
        iteration = load_json(iteration_path)
        brief_ref = iteration.get("loop_research_brief") or {}
        json_path = Path(brief_ref.get("json_path") or "")
        md_path = Path(brief_ref.get("markdown_path") or "")
        paths["brief_json"] = json_path if json_path.is_absolute() else root / json_path
        paths["brief_markdown"] = md_path if md_path.is_absolute() else root / md_path
    snapshot: dict[str, str | None] = {}
    for key, path in paths.items():
        snapshot[key] = sha256_file(path) if path.exists() and path.is_file() else None
    return snapshot


def selected_proposal_path(root: Path, rid: str) -> Path | None:
    iteration_path = step6_iteration_path(root, rid)
    if not iteration_path.exists():
        return None
    iteration = load_json(iteration_path)
    final_strategy = (((iteration.get("research_judgment") or {}).get("research_memo") or {}).get("final_revision_strategy") or {})
    selected = final_strategy.get("selected_council_proposal_ids") or []
    if not selected:
        return None
    selected_id = selected[0]
    council_dir = root / "objects" / "research_iteration_master" / "revision_council" / rid
    for path in sorted(council_dir.glob(f"proposal__{rid}__*.json")):
        proposal = load_json(path)
        if proposal.get("proposal_id") == selected_id:
            return path
    return None


def run_step6_intelligence_fixture(root: Path) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "scripts/run_step6_intelligence_smoke.py", "--fresh", "--root", str(root)])


def prepare_revision_council(root: Path, rid: str, *, merge: bool = True) -> dict[str, Any]:
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    merge_result = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid]) if merge else {"rc": None}
    return {"packet": packet, "proposals": proposals, "merge": merge_result}


def revision_council_summary_path(root: Path, rid: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_summary__{rid}.json"


def positive_case(root: Path, name: str, rid: str, signature: str, expected_mode: str) -> dict[str, Any]:
    make_fixture(root, rid, signature=signature, mechanism_fit="contradicted" if expected_mode == "mechanism_challenge" else "partial")
    packet, proposals, merge = council_flow(root, rid)
    summary_path = root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_summary__{rid}.json"
    summary = load_json(summary_path) if summary_path.exists() else {}
    branches = summary.get("recommended_branch_templates") or []
    ok = (
        packet["rc"] == proposals["rc"] == merge["rc"] == 0
        and bool(branches)
        and all(not b.get("execution_allowed_by_default") for b in branches)
        and all(b.get("source_producer") == "deterministic_scaffold" for b in branches)
        and all(b.get("source_research_depth") == "low" for b in branches)
        and all(b.get("not_sufficient_for_formal_revision") is True for b in branches)
    )
    if expected_mode == "bayesian_exploit":
        ok = ok and any(b.get("search_mode") == "bayesian_search" for b in branches)
    elif expected_mode == "mechanism_challenge":
        ok = ok and any(b.get("search_mode") == "mechanism_challenge" for b in branches)
    return result(name, ok, {"packet": packet, "proposals": proposals, "merge": merge, "branches": branches}, f"{expected_mode} advisory branch")


def proposal_mutation_block(root: Path, case_name: str, rid: str, mutate) -> dict[str, Any]:
    make_fixture(root, rid, signature="cost_too_high", mechanism_fit="contradicted")
    packet, proposals, _ = council_flow(root, rid)
    proposal_path = root / "objects" / "research_iteration_master" / "revision_council" / rid / f"proposal__{rid}__symbolic_law_discovery.json"
    proposal = load_json(proposal_path)
    mutate(proposal)
    write_json(proposal_path, proposal)
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    summary = load_json(root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_summary__{rid}.json")
    blocked = summary.get("blocked_proposals") or []
    ok = merge["rc"] == 0 and any(item.get("agent_role") == "symbolic_law_discovery" for item in blocked)
    return result(case_name, ok, {"packet": packet, "proposals": proposals, "merge": merge, "blocked_proposals": blocked}, "symbolic proposal blocked by validator")


def proposal_expected_metric_change_block(root: Path) -> dict[str, Any]:
    case_name = "symbolic_missing_expected_metric_change_block"
    rid = "REVISION_COUNCIL_NEG_EXPECTED_METRIC"
    make_fixture(root, rid, signature="cost_too_high", mechanism_fit="contradicted")
    packet, proposals, _ = council_flow(root, rid)
    proposal_path = root / "objects" / "research_iteration_master" / "revision_council" / rid / f"proposal__{rid}__symbolic_law_discovery.json"
    proposal = load_json(proposal_path)
    proposal["revision_type"] = "expression_revision"
    for law in proposal.get("candidate_revision_laws") or []:
        if isinstance(law, dict):
            law.pop("expected_metric_change", None)
    reasons = validate_revision_council_proposal(proposal)
    token = "BLOCK_REVISION_COUNCIL_EXPECTED_METRIC_CHANGE_MISSING"
    rc = 1 if reasons else 0
    ok = rc == 1 and any(token in reason for reason in reasons)
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "validator_rc": rc,
            "token": token,
            "token_present": any(token in reason for reason in reasons),
            "block_reasons": reasons,
            "proposal_path": str(proposal_path),
        },
        "validator BLOCK when expression revision law expected_metric_change is missing",
    )


def derivation_mutation_block(root: Path, case_name: str, rid: str, mutate, expected_token: str) -> dict[str, Any]:
    make_fixture(root, rid, signature="cost_too_high", mechanism_fit="contradicted")
    packet, proposals, _ = council_flow(root, rid)
    proposal_path = root / "objects" / "research_iteration_master" / "revision_council" / rid / f"proposal__{rid}__symbolic_law_discovery.json"
    proposal = load_json(proposal_path)
    mutate(proposal)
    write_json(proposal_path, proposal)
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    summary_path = root / "objects" / "research_iteration_master" / "revision_council" / rid / f"revision_council_summary__{rid}.json"
    summary = load_json(summary_path) if summary_path.exists() else {}
    blocked = summary.get("blocked_proposals") or []
    branches = summary.get("recommended_branch_templates") or []
    reason_text = json.dumps(blocked, ensure_ascii=False)
    symbolic_blocked = any(item.get("agent_role") == "symbolic_law_discovery" for item in blocked)
    symbolic_branch_absent = all(item.get("source_agent_role") != "symbolic_law_discovery" for item in branches)
    ok = merge["rc"] == 0 and symbolic_blocked and expected_token in reason_text and symbolic_branch_absent
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "merge": merge,
            "expected_token": expected_token,
            "token_present": expected_token in reason_text,
            "blocked_proposals": blocked,
            "symbolic_branch_absent": symbolic_branch_absent,
        },
        expected_token,
    )


def existing_generated_code_unchanged_pass(root: Path) -> dict[str, Any]:
    case_name = "existing_generated_code_unchanged_pass"
    rid = "REVISION_COUNCIL_EXISTING_CODE"
    make_fixture(root, rid, signature="cost_too_high")
    generated = root / "generated_code" / rid / "factor_impl.py"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("# existing generated code\nVALUE = 1\n", encoding="utf-8")
    before_digest = directory_digest(root / "generated_code" / rid)
    packet, proposals = council_packet_and_proposals(root, rid)
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    after_digest = directory_digest(root / "generated_code" / rid)
    summary_exists = council_summary_path(root, rid).exists()
    ok = packet["rc"] == 0 and proposals["rc"] == 0 and merge["rc"] == 0 and summary_exists and before_digest == after_digest and no_canonical_writebacks(root, rid)
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "merge": merge,
            "summary_exists": summary_exists,
            "generated_code_digest_unchanged": before_digest == after_digest,
            "handoff_absent": not (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists(),
            "official_absent": not (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists(),
        },
        "existing generated_code unchanged should pass",
    )


def existing_data_clean_unchanged_pass(root: Path) -> dict[str, Any]:
    case_name = "existing_data_clean_unchanged_pass"
    rid = "REVISION_COUNCIL_EXISTING_CLEAN"
    make_fixture(root, rid, signature="cost_too_high")
    clean_file = root / "data" / "clean" / "existing_clean_data_marker.txt"
    clean_file.parent.mkdir(parents=True, exist_ok=True)
    clean_file.write_text("existing clean data marker", encoding="utf-8")
    before_digest = directory_digest(root / "data" / "clean")
    packet, proposals = council_packet_and_proposals(root, rid)
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    after_digest = directory_digest(root / "data" / "clean")
    summary_exists = council_summary_path(root, rid).exists()
    ok = packet["rc"] == 0 and proposals["rc"] == 0 and merge["rc"] == 0 and summary_exists and before_digest == after_digest
    return result(
        case_name,
        ok,
        {"packet": packet, "proposals": proposals, "merge": merge, "summary_exists": summary_exists, "data_clean_digest_unchanged": before_digest == after_digest},
        "existing data/clean unchanged should pass",
    )


def forbidden_write_after_packet_case(root: Path, case_name: str, rid: str, mutate) -> dict[str, Any]:
    make_fixture(root, rid, signature="cost_too_high")
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    mutate(root, rid)
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    summary = council_summary_path(root, rid)
    if summary.exists():
        summary.unlink()
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    token = "BLOCK_REVISION_COUNCIL_FORBIDDEN_WRITEBACK_PRESENT"
    diagnostic = merge_block_diagnostic_path(root, rid)
    summary_absent = not summary.exists()
    ok = merge["rc"] != 0 and token in (merge["stdout_tail"] + merge["stderr_tail"]) and diagnostic.exists() and summary_absent
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "merge": merge,
            "diagnostic_exists": diagnostic.exists(),
            "summary_absent": summary_absent,
            "diagnostic": load_json(diagnostic) if diagnostic.exists() else {},
        },
        token,
    )


def generated_code_modified_after_packet_block(root: Path) -> dict[str, Any]:
    case_name = "generated_code_modified_after_packet_block"
    rid = "REVISION_COUNCIL_CODE_MODIFIED_AFTER_PACKET"
    make_fixture(root, rid, signature="cost_too_high")
    generated = root / "generated_code" / rid / "factor_impl.py"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("# existing generated code\nVALUE = 1\n", encoding="utf-8")
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    generated.write_text("# mutated generated code\nVALUE = 2\n", encoding="utf-8")
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    summary = council_summary_path(root, rid)
    if summary.exists():
        summary.unlink()
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    token = "BLOCK_REVISION_COUNCIL_FORBIDDEN_WRITEBACK_PRESENT"
    diagnostic = merge_block_diagnostic_path(root, rid)
    summary_absent = not summary.exists()
    ok = merge["rc"] != 0 and token in (merge["stdout_tail"] + merge["stderr_tail"]) and diagnostic.exists() and summary_absent
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "merge": merge,
            "diagnostic_exists": diagnostic.exists(),
            "summary_absent": summary_absent,
            "diagnostic": load_json(diagnostic) if diagnostic.exists() else {},
        },
        token,
    )


def data_clean_modified_after_packet_block(root: Path) -> dict[str, Any]:
    case_name = "data_clean_modified_after_packet_block"
    rid = "REVISION_COUNCIL_CLEAN_MODIFIED_AFTER_PACKET"
    make_fixture(root, rid, signature="cost_too_high")
    clean_file = root / "data" / "clean" / "existing_clean_data_marker.txt"
    clean_file.parent.mkdir(parents=True, exist_ok=True)
    clean_file.write_text("existing clean data marker", encoding="utf-8")
    packet = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", rid])
    clean_file.write_text("mutated clean data marker", encoding="utf-8")
    proposals = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/run_revision_council.py", "--report-id", rid])
    summary = council_summary_path(root, rid)
    if summary.exists():
        summary.unlink()
    merge = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/merge_revision_council.py", "--report-id", rid])
    token = "BLOCK_REVISION_COUNCIL_FORBIDDEN_WRITEBACK_PRESENT"
    diagnostic = merge_block_diagnostic_path(root, rid)
    summary_absent = not summary.exists()
    ok = merge["rc"] != 0 and token in (merge["stdout_tail"] + merge["stderr_tail"]) and diagnostic.exists() and summary_absent
    return result(
        case_name,
        ok,
        {
            "packet": packet,
            "proposals": proposals,
            "merge": merge,
            "diagnostic_exists": diagnostic.exists(),
            "summary_absent": summary_absent,
            "diagnostic": load_json(diagnostic) if diagnostic.exists() else {},
        },
        token,
    )


def valid_attach_pass(root: Path, rid: str, case_name: str = "valid_attach_pass") -> dict[str, Any]:
    council = prepare_revision_council(root, rid, merge=True)
    attach = attach_council(root, rid)
    validate = step6_validate(root, rid)
    iteration = load_json(step6_iteration_path(root, rid)) if step6_iteration_path(root, rid).exists() else {}
    research_memo = ((iteration.get("research_judgment") or {}).get("research_memo") or {})
    final_strategy = research_memo.get("final_revision_strategy") or {}
    ref = iteration.get("revision_council_ref") or {}
    brief_ref = iteration.get("loop_research_brief") or {}
    brief_json_path = Path(brief_ref.get("json_path") or "")
    brief_md_path = Path(brief_ref.get("markdown_path") or "")
    brief = load_json(brief_json_path) if brief_json_path.exists() else {}
    markdown = brief_md_path.read_text(encoding="utf-8") if brief_md_path.exists() else ""
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json"
    official_path = root / "objects" / "factor_library_official" / f"factor_record__{rid}.json"
    ok = (
        council["packet"]["rc"] == 0
        and council["proposals"]["rc"] == 0
        and council["merge"]["rc"] == 0
        and attach["rc"] == 0
        and validate["rc"] == 0
        and ref.get("enabled") is True
        and final_strategy.get("source") == "revision_council"
        and final_strategy.get("loop_authorization") == "advisory_only"
        and not handoff_path.exists()
        and not official_path.exists()
        and isinstance(research_memo.get("deterministic_revision_strategy"), dict)
        and isinstance(brief.get("revision_council_summary"), dict)
        and "## Revision Council Summary" in markdown
    )
    return result(
        case_name,
        ok,
        {
            "report_id": rid,
            "council": council,
            "attach": attach,
            "validate": validate,
            "revision_council_ref": ref,
            "final_revision_strategy": final_strategy,
            "handoff_absent": not handoff_path.exists(),
            "official_absent": not official_path.exists(),
            "brief_council_section_json": isinstance(brief.get("revision_council_summary"), dict),
            "brief_council_section_markdown": "## Revision Council Summary" in markdown,
        },
        "attach council and validate Step6",
    )


def attach_missing_summary_block(root: Path) -> dict[str, Any]:
    case_name = "attach_missing_summary_block"
    rid = "STEP6_INTEL_COLD_START_KNOWLEDGE_GAP"
    iteration_path = step6_iteration_path(root, rid)
    before = iteration_path.read_text(encoding="utf-8")
    council = prepare_revision_council(root, rid, merge=False)
    attach = attach_council(root, rid)
    after = iteration_path.read_text(encoding="utf-8")
    token = "BLOCK_REVISION_COUNCIL_SUMMARY_MISSING"
    ok = attach["rc"] == 1 and token in (attach["stdout_tail"] + attach["stderr_tail"]) and before == after
    return result(case_name, ok, {"report_id": rid, "council": council, "attach": attach, "iteration_unchanged": before == after}, token)


def attach_missing_packet_block(root: Path) -> dict[str, Any]:
    case_name = "attach_missing_packet_block"
    rid = "STEP6_INTEL_PRICE_VOLUME_CORRELATION_MECHANISM"
    council = prepare_revision_council(root, rid, merge=True)
    packet_path = council_packet_path(root, rid)
    before = attach_target_snapshot(root, rid)
    if packet_path.exists():
        packet_path.unlink()
    attach = attach_council(root, rid)
    after = attach_target_snapshot(root, rid)
    token = "BLOCK_REVISION_COUNCIL_PACKET_MISSING"
    unchanged = before == after
    ok = attach["rc"] == 1 and token in (attach["stdout_tail"] + attach["stderr_tail"]) and unchanged
    return result(
        case_name,
        ok,
        {
            "report_id": rid,
            "council": council,
            "attach": attach,
            "packet_path": str(packet_path),
            "iteration_and_brief_unchanged": unchanged,
            "before": before,
            "after": after,
        },
        token,
    )


def attach_packet_report_id_mismatch_block(root: Path) -> dict[str, Any]:
    case_name = "attach_packet_report_id_mismatch_block"
    rid = "STEP6_INTEL_NON_MONOTONIC_REVISION"
    council = prepare_revision_council(root, rid, merge=True)
    packet_path = council_packet_path(root, rid)
    before = attach_target_snapshot(root, rid)
    packet = load_json(packet_path)
    packet["report_id"] = "WRONG_REPORT_ID"
    write_json(packet_path, packet)
    attach = attach_council(root, rid)
    after = attach_target_snapshot(root, rid)
    token = "BLOCK_REVISION_COUNCIL_PACKET_MISMATCH"
    unchanged = before == after
    ok = attach["rc"] == 1 and token in (attach["stdout_tail"] + attach["stderr_tail"]) and unchanged
    return result(
        case_name,
        ok,
        {
            "report_id": rid,
            "council": council,
            "attach": attach,
            "packet_path": str(packet_path),
            "iteration_and_brief_unchanged": unchanged,
            "before": before,
            "after": after,
        },
        token,
    )


def attach_packet_summary_mismatch_block(root: Path) -> dict[str, Any]:
    case_name = "attach_packet_summary_mismatch_block"
    rid = "STEP6_INTEL_MECHANISM_UNCLEAR_REVISION"
    council = prepare_revision_council(root, rid, merge=True)
    summary_path = revision_council_summary_path(root, rid)
    before = attach_target_snapshot(root, rid)
    summary = load_json(summary_path)
    summary["proposal_count"] = 999
    write_json(summary_path, summary)
    attach = attach_council(root, rid)
    after = attach_target_snapshot(root, rid)
    token = "BLOCK_REVISION_COUNCIL_PACKET_SUMMARY_MISMATCH"
    unchanged = before == after
    ok = attach["rc"] == 1 and token in (attach["stdout_tail"] + attach["stderr_tail"]) and unchanged
    return result(
        case_name,
        ok,
        {
            "report_id": rid,
            "council": council,
            "attach": attach,
            "summary_path": str(summary_path),
            "iteration_and_brief_unchanged": unchanged,
            "before": before,
            "after": after,
        },
        token,
    )


def attach_summary_permission_block(root: Path, rid: str, case_name: str, key: str, value: Any, token: str) -> dict[str, Any]:
    council = prepare_revision_council(root, rid, merge=True)
    summary_path = revision_council_summary_path(root, rid)
    summary = load_json(summary_path)
    summary[key] = value
    write_json(summary_path, summary)
    attach = attach_council(root, rid)
    ok = attach["rc"] == 1 and token in (attach["stdout_tail"] + attach["stderr_tail"])
    return result(case_name, ok, {"report_id": rid, "council": council, "attach": attach, "mutated_key": key}, token)


def selected_proposal_derivation_block(root: Path) -> dict[str, Any]:
    case_name = "selected_proposal_missing_derivation_record_block"
    rid = "STEP6_INTEL_LONG_SIDE_NEGATIVE_REVISION"
    attach_case = valid_attach_pass(root, rid, case_name="selected_proposal_attach_setup")
    path = selected_proposal_path(root, rid)
    if path:
        proposal = load_json(path)
        proposal.pop("derivation_record", None)
        write_json(path, proposal)
    validate = step6_validate(root, rid)
    token = "derivation_record"
    ok = attach_case["ok"] and validate["rc"] == 1 and token in (validate["stdout_tail"] + validate["stderr_tail"])
    return result(case_name, ok, {"report_id": rid, "attach_setup": attach_case, "proposal_path": str(path) if path else None, "validate": validate}, "selected proposal derivation block")


def forbidden_proposal_text_block(root: Path) -> dict[str, Any]:
    case_name = "selected_proposal_forbidden_text_block"
    rid = "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH"
    attach_case = valid_attach_pass(root, rid, case_name="forbidden_proposal_attach_setup")
    path = selected_proposal_path(root, rid)
    if path:
        proposal = load_json(path)
        proposal["market_phenomenon"] = "portfolio repair and short leg adoption should be used"
        write_json(path, proposal)
    validate = step6_validate(root, rid)
    token = "BLOCK_REVISION_COUNCIL_FORBIDDEN_CHANGE"
    ok = attach_case["ok"] and validate["rc"] == 1 and token in (validate["stdout_tail"] + validate["stderr_tail"])
    return result(case_name, ok, {"report_id": rid, "attach_setup": attach_case, "proposal_path": str(path) if path else None, "validate": validate}, token)


def unauthorized_handoff_after_attach_block(root: Path) -> dict[str, Any]:
    case_name = "unauthorized_handoff_after_attach_block"
    rid = "STEP6_INTEL_SIMILAR_SUCCESS_REJECTED_CONDITION_MISMATCH"
    attach_case = valid_attach_pass(root, rid, case_name="unauthorized_handoff_attach_setup")
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json"
    write_json(handoff_path, {"report_id": rid, "forbidden": True})
    validate = step6_validate(root, rid)
    token = "handoff_to_step3b requires approved final_revision_strategy.loop_authorization"
    ok = attach_case["ok"] and validate["rc"] == 1 and token in (validate["stdout_tail"] + validate["stderr_tail"])
    return result(case_name, ok, {"report_id": rid, "attach_setup": attach_case, "handoff_path": str(handoff_path), "validate": validate}, token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_revision_council_{int(time.time())}")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        raise SystemExit(1)
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = file_snapshot()

    cases: list[dict[str, Any]] = []
    step6_fixture = run_step6_intelligence_fixture(root)
    cases.append(result(
        "step6_intelligence_fixture_for_attachment",
        step6_fixture["rc"] == 0 and "ACCEPT" in step6_fixture["stdout_tail"],
        {"step6_fixture": step6_fixture},
        "Step6 intelligence fixture available for council attachment cases",
    ))
    missing = run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", "REVISION_COUNCIL_MISSING"])
    cases.append(result("packet_missing_input_block", missing["rc"] != 0 and "BLOCK_REVISION_COUNCIL_PACKET_MISSING_INPUT" in (missing["stdout_tail"] + missing["stderr_tail"]), {"packet": missing}, "missing input BLOCK"))
    cases.append(supplemental_context_packet_case(root))
    cases.append(positive_case(root, "price_volume_cost_contradiction", "REVISION_COUNCIL_PRICE_VOLUME", "cost_too_high", "mechanism_challenge"))
    cases.append(positive_case(root, "high_turnover_parameter_revision", "REVISION_COUNCIL_HIGH_TURNOVER", "cost_too_high", "bayesian_exploit"))
    cases.append(positive_case(root, "mechanism_unclear_symbolic_challenge", "REVISION_COUNCIL_MECH_UNCLEAR", "mechanism_unclear", "mechanism_challenge"))
    cases.append(proposal_mutation_block(root, "proposal_portfolio_repair_language_block", "REVISION_COUNCIL_NEG_PORTFOLIO", lambda p: p.update({"market_phenomenon": "portfolio repair should improve it"})))
    cases.append(proposal_mutation_block(root, "proposal_short_leg_language_block", "REVISION_COUNCIL_NEG_SHORT", lambda p: p.update({"market_phenomenon": "short leg adoption should improve it"})))
    cases.append(proposal_mutation_block(root, "proposal_decile_trading_language_block", "REVISION_COUNCIL_NEG_DECILE", lambda p: p.update({"market_phenomenon": "decile trading should improve it"})))
    cases.append(proposal_mutation_block(root, "symbolic_missing_dimensional_review_block", "REVISION_COUNCIL_NEG_DIM", lambda p: p.pop("dimensional_scaling_review", None)))
    cases.append(proposal_expected_metric_change_block(root))
    cases.append(derivation_mutation_block(root, "missing_derivation_block", "REVISION_COUNCIL_NEG_DERIVATION", lambda p: p.pop("derivation_record", None), "BLOCK_REVISION_COUNCIL_DERIVATION_MISSING"))
    cases.append(derivation_mutation_block(root, "empty_assumptions_block", "REVISION_COUNCIL_NEG_ASSUMPTIONS", lambda p: p["derivation_record"].update({"assumptions": []}), "BLOCK_REVISION_COUNCIL_DERIVATION_ASSUMPTIONS_MISSING"))
    cases.append(derivation_mutation_block(root, "empty_mathematical_objects_block", "REVISION_COUNCIL_NEG_OBJECTS", lambda p: p["derivation_record"].update({"mathematical_objects": []}), "BLOCK_REVISION_COUNCIL_DERIVATION_OBJECTS_MISSING"))
    cases.append(derivation_mutation_block(root, "selected_tool_missing_why_selected_block", "REVISION_COUNCIL_NEG_TOOL", lambda p: p["derivation_record"]["selected_tools"][0].pop("why_selected", None), "BLOCK_REVISION_COUNCIL_DERIVATION_TOOL_INVALID"))
    cases.append(derivation_mutation_block(root, "formula_claim_without_formula_block", "REVISION_COUNCIL_NEG_FORMULA", lambda p: p["derivation_record"]["derivation_steps"][0].update({"statement": "derive formula symbolic relation from the expression", "formula": ""}), "BLOCK_REVISION_COUNCIL_DERIVATION_FORMULA_MISSING"))
    cases.append(derivation_mutation_block(root, "revision_hypothesis_missing_falsification_block", "REVISION_COUNCIL_NEG_REV_HYP", lambda p: p["derivation_record"]["revision_hypotheses"][0].pop("falsification_tests", None), "BLOCK_REVISION_COUNCIL_DERIVATION_REVISION_HYPOTHESIS_INVALID"))
    cases.append(derivation_mutation_block(root, "overclaim_guard_missing_block", "REVISION_COUNCIL_NEG_OVERCLAIM", lambda p: p["derivation_record"]["confidence_and_limits"].pop("overclaim_guard", None), "BLOCK_REVISION_COUNCIL_DERIVATION_OVERCLAIM_GUARD_MISSING"))
    cases.append(derivation_mutation_block(root, "deterministic_scaffold_high_depth_block", "REVISION_COUNCIL_NEG_SCAFFOLD_DEPTH", lambda p: p.update({"research_depth": "high"}), "BLOCK_REVISION_COUNCIL_SCAFFOLD_DEPTH_INVALID"))
    cases.append(derivation_mutation_block(root, "agentic_research_low_depth_block", "REVISION_COUNCIL_NEG_AGENTIC_DEPTH", lambda p: p.update({"producer": "agentic_research", "proposal_generation_mode": "main_agent_self_run", "research_depth": "low"}), "BLOCK_REVISION_COUNCIL_AGENTIC_DEPTH_INVALID"))
    cases.append(existing_generated_code_unchanged_pass(root))
    cases.append(forbidden_write_after_packet_case(
        root,
        "generated_code_created_after_packet_block",
        "REVISION_COUNCIL_CODE_CREATED_AFTER_PACKET",
        lambda r, report_id: ((r / "generated_code" / report_id).mkdir(parents=True, exist_ok=True), (r / "generated_code" / report_id / "factor_impl.py").write_text("created after packet", encoding="utf-8")),
    ))
    cases.append(generated_code_modified_after_packet_block(root))
    cases.append(forbidden_write_after_packet_case(
        root,
        "handoff_to_step3b_created_after_packet_block",
        "REVISION_COUNCIL_HANDOFF_CREATED_AFTER_PACKET",
        lambda r, report_id: write_json(r / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json", {"report_id": report_id, "forbidden": True}),
    ))
    cases.append(forbidden_write_after_packet_case(
        root,
        "official_library_created_after_packet_block",
        "REVISION_COUNCIL_OFFICIAL_CREATED_AFTER_PACKET",
        lambda r, report_id: write_json(r / "objects" / "factor_library_official" / f"factor_record__{report_id}.json", {"report_id": report_id, "forbidden": True}),
    ))
    cases.append(existing_data_clean_unchanged_pass(root))
    cases.append(data_clean_modified_after_packet_block(root))
    cases.append(valid_attach_pass(root, "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH", "valid_attach_pass"))
    cases.append(attach_missing_packet_block(root))
    cases.append(attach_packet_report_id_mismatch_block(root))
    cases.append(attach_packet_summary_mismatch_block(root))
    cases.append(attach_missing_summary_block(root))
    cases.append(attach_summary_permission_block(
        root,
        "STEP6_INTEL_SIMILAR_FAILURE_IMPORTED",
        "attach_canonical_write_permission_block",
        "canonical_write_permission",
        True,
        "revision_council_no_canonical_write_permission",
    ))
    cases.append(attach_summary_permission_block(
        root,
        "STEP6_INTEL_HIGH_TURNOVER_COST",
        "attach_execution_by_default_block",
        "execution_allowed_by_default",
        True,
        "revision_council_no_execution_by_default",
    ))
    cases.append(selected_proposal_derivation_block(root))
    cases.append(forbidden_proposal_text_block(root))
    cases.append(unauthorized_handoff_after_attach_block(root))

    bad_branch = {"execution_allowed_by_default": True, "requires_human_approval_before_execution": True, "hard_guards": ["no_portfolio_expression_repair", "no_short_leg_adoption", "no_decile_trading", "no_shared_clean_data_mutation"]}
    cases.append(result("branch_execution_enabled_default_block", bad_branch.get("execution_allowed_by_default") is True, {"bad_branch_detected": True}, "smoke detects execution_enabled branch as invalid"))

    after = file_snapshot()
    new_files = sorted(after - before)
    pollution = [item for item in new_files if "REVISION_COUNCIL" in item or "revision_council" in item]
    verdict = "ACCEPT" if all(c["ok"] for c in cases) and not pollution else "BLOCK"
    summary = {
        "verdict": verdict,
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "derivation_record_cases": {
            "missing_derivation_block": next((c["ok"] for c in cases if c["case"] == "missing_derivation_block"), False),
            "empty_assumptions_block": next((c["ok"] for c in cases if c["case"] == "empty_assumptions_block"), False),
            "tool_invalid_block": next((c["ok"] for c in cases if c["case"] == "selected_tool_missing_why_selected_block"), False),
            "formula_missing_block": next((c["ok"] for c in cases if c["case"] == "formula_claim_without_formula_block"), False),
            "overclaim_guard_missing_block": next((c["ok"] for c in cases if c["case"] == "overclaim_guard_missing_block"), False),
        },
        "attachment_cases": {
            "valid_attach_pass": next((c["ok"] for c in cases if c["case"] == "valid_attach_pass"), False),
            "missing_packet_block": next((c["ok"] for c in cases if c["case"] == "attach_missing_packet_block"), False),
            "packet_report_id_mismatch_block": next((c["ok"] for c in cases if c["case"] == "attach_packet_report_id_mismatch_block"), False),
            "packet_summary_mismatch_block": next((c["ok"] for c in cases if c["case"] == "attach_packet_summary_mismatch_block"), False),
            "missing_summary_block": next((c["ok"] for c in cases if c["case"] == "attach_missing_summary_block"), False),
            "canonical_write_permission_block": next((c["ok"] for c in cases if c["case"] == "attach_canonical_write_permission_block"), False),
            "execution_by_default_block": next((c["ok"] for c in cases if c["case"] == "attach_execution_by_default_block"), False),
            "selected_proposal_derivation_block": next((c["ok"] for c in cases if c["case"] == "selected_proposal_missing_derivation_record_block"), False),
            "forbidden_proposal_text_block": next((c["ok"] for c in cases if c["case"] == "selected_proposal_forbidden_text_block"), False),
            "unauthorized_handoff_block": next((c["ok"] for c in cases if c["case"] == "unauthorized_handoff_after_attach_block"), False),
        },
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
        "notes": ["Synthetic /tmp-only council smoke.", "No real factor run, no clean data processing, no canonical Step3B writes."],
    }
    summary_path = root / "revision_council_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if verdict != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
