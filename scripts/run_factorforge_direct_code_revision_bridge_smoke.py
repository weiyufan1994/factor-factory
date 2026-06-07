#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_fixture(root: Path) -> tuple[str, str]:
    if root.exists():
        shutil.rmtree(root)
    report_id = "DC_PARENT"
    child_id = "DC_PARENT__LOOP01__PERSISTENT_FLOW_STATE"
    source_code = "def compute_factor(daily_df=None, minute_df=None):\n    return daily_df\n"
    for rel in [
        "objects/factor_spec_master",
        "objects/research_iteration_master/revision_council/DC_PARENT",
        "objects/research_iteration_master",
        "objects/handoff",
        "objects/alpha_idea_master",
        "objects/data_prep_master",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)

    write_json(
        root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        {
            "report_id": report_id,
            "factor_id": "intraday_moneyflow",
            "implementation_mode": "direct_code",
            "artifact_identity": {
                "report_id": report_id,
                "factor_id": "intraday_moneyflow",
                "implementation_mode": "direct_code",
                "branch_id": "main",
                "source_type": "canonical_formula",
            },
            "canonical_spec": {"formula_text": "Compute pre-14:50 signed amount imbalance from minute_bar."},
            "implementation_contract": {
                "mode": "direct_code",
                "code_contract": {"source_code": source_code},
            },
        },
    )
    write_json(root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json", {"report_id": report_id})
    write_json(
        root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json",
        {"report_id": report_id, "local_input_paths": {}},
    )
    write_json(
        root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json",
        {
            "report_id": report_id,
            "factor_id": "intraday_moneyflow",
            "decision": "iterate",
            "research_judgment": {"research_memo": {"final_revision_strategy": {"revision_needed": True}}},
            "source_case_identity": {
                "report_id": report_id,
                "factor_id": "intraday_moneyflow",
                "implementation_mode": "direct_code",
                "branch_id": "main",
                "run_id": "run_001",
            },
        },
    )
    council_dir = root / "objects" / "research_iteration_master" / "revision_council" / report_id
    write_json(
        council_dir / f"revision_council_summary__{report_id}.json",
        {
            "report_id": report_id,
            "valid_agent_results": [{"task_id": "flow_state"}],
            "recommended_branch_templates": [{"source_proposal_id": "flow_state"}],
        },
    )
    write_json(
        council_dir / f"main_agent_council_synthesis__{report_id}.json",
        {
            "contract_version": "factorforge_main_agent_council_synthesis_v1",
            "report_id": report_id,
            "producer": "direct_code_revision_bridge_smoke",
            "canonical_write_permission": False,
            "execution_allowed_by_default": False,
            "human_approval_required": True,
            "selected_revision": {
                "law_id": "persistent_flow_state",
                "implementation_mode": "direct_code",
                "child_formula": "Estimate persistent pre-14:50 informed flow state from minute_bar with smoothing and cost penalty.",
                "direct_code_revision_contract": {
                    "target_function": "compute_factor",
                    "formula_law": "posterior persistent flow state minus churn penalty",
                    "required_fields": ["ts_code", "trade_date", "trade_time", "open", "close", "amount"],
                    "code_mutation_scope": ["state_features", "smoothing", "cost_penalty"],
                    "source_code": source_code,
                },
                "expected_metric_signature": {"rank_ic_mean": "increase", "turnover": "decrease"},
                "falsification_tests": ["cost_adjusted_return_not_improved"],
                "kill_criteria": ["rank_ic_mean<=0"],
            },
        },
    )
    return report_id, child_id


def run_command(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, env=env, text=True, capture_output=True)


def assert_success(proc: subprocess.CompletedProcess[str], label: str) -> None:
    if proc.returncode != 0:
        raise AssertionError(f"{label} failed rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


def load_step3b_module():
    module_path = REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / "run_step3b.py"
    spec = importlib.util.spec_from_file_location("run_step3b_direct_code_bridge_smoke", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(os.environ.get("FACTORFORGE_DIRECT_CODE_BRIDGE_SMOKE_ROOT", "/tmp/factorforge_direct_code_revision_bridge_smoke"))
    report_id, child_id = build_fixture(root)
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)

    approval = run_command(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(root),
            "--skip-validate-step6",
        ],
        env,
    )
    assert_success(approval, "approval")
    if "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED" in approval.stderr + approval.stdout:
        raise AssertionError("approval still tried Formula-IR parse for direct_code parent/child")

    env["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    materialize = run_command(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py",
            "--parent-report-id",
            report_id,
            "--child-report-id",
            child_id,
            "--factorforge-root",
            str(root),
        ],
        env,
    )
    assert_success(materialize, "materialize")

    child_spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{child_id}.json"
    exe_path = root / "objects" / "research_iteration_master" / f"executable_revision_spec__{child_id}.json"
    child_spec = json.loads(child_spec_path.read_text(encoding="utf-8"))
    exe = json.loads(exe_path.read_text(encoding="utf-8"))
    assert exe["implementation_mode"] == "direct_code"
    assert exe["child_formula_ir"] is None
    assert exe["direct_code_revision_contract"]["target_function"] == "compute_factor"
    assert child_spec["implementation_mode"] == "direct_code"
    assert child_spec["canonical_spec"]["formula_ir"] is None
    assert child_spec["implementation_contract"]["mode"] == "direct_code"

    step3b = load_step3b_module()
    step3b.OBJ = root / "objects"
    updated, revision_spec = step3b.apply_executable_revision_spec(child_id, child_spec, child_spec_path)
    assert revision_spec["implementation_mode"] == "direct_code"
    assert updated["implementation_mode"] == "direct_code"
    assert updated["canonical_spec"]["formula_ir"] is None
    assert updated["implementation_contract"]["direct_code_revision_contract"]["target_function"] == "compute_factor"

    ultimate_loop_source = (REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py").read_text(encoding="utf-8")
    for token in ("awaiting_main_agent_council_synthesis", "completed_council_requires_main_agent_synthesis"):
        if token not in ultimate_loop_source:
            raise AssertionError(f"missing ultimate loop token: {token}")

    print(
        json.dumps(
            {
                "verdict": "ACCEPT",
                "approval_no_formula_ir_parse_block": True,
                "materialized_direct_code_child": True,
                "step3b_direct_code_child_apply": True,
                "ultimate_loop_awaiting_synthesis_tokens": True,
                "fixture_root": str(root),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
