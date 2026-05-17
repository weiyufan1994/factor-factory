#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_tmp_root(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve()) if path.exists() else str(path)
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def tail(text: str, limit: int = 6000) -> str:
    return text[-limit:] if len(text) > limit else text


def run(command: list[str], *, root: Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        "command": command,
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def snapshot_repo_canonical() -> set[str]:
    roots = [
        REPO_ROOT / "objects",
        REPO_ROOT / "runs",
        REPO_ROOT / "evaluations",
        REPO_ROOT / "generated_code",
        REPO_ROOT / "archive",
        REPO_ROOT / "factorforge",
        REPO_ROOT / "data" / "clean",
    ]
    files: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                files.add(str(path.relative_to(REPO_ROOT)))
    return files


def canonical_pollution(before: set[str]) -> dict[str, Any]:
    after = snapshot_repo_canonical()
    added = [
        item for item in sorted(after - before)
        if "ULTIMATE_LOOP_SMOKE" in item
        or "factorforge_ultimate_loop_phase_m" in item
        or "STEP6_INTEL_" in item
    ]
    return {"polluted": bool(added), "new_files": added}


def setup_step6_fixtures(root: Path) -> dict[str, Any]:
    return run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_step6_intelligence_smoke.py"),
            "--fresh",
            "--root",
            str(root),
        ],
        root=root,
    )


def loop_command(root: Path, report_id: str, *, start_step: str = "6", max_loops: int = 10, council_mode: str = "off", executor: str = "none", adapter: str = "none") -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py"),
        "--report-id",
        report_id,
        "--start-step",
        start_step,
        "--max-loops",
        str(max_loops),
        "--council-mode",
        council_mode,
        "--agentic-council-executor",
        executor,
        "--agentic-dispatch-adapter",
        adapter,
        "--factorforge-root",
        str(root),
    ]


def proof_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_loop_report__{report_id}.json"


def brief_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"ultimate_loop_brief__{report_id}.md"


def load_proof(root: Path, report_id: str) -> dict[str, Any]:
    path = proof_path(root, report_id)
    return read_json(path) if path.exists() else {}


def run_loop_case(root: Path, name: str, report_id: str, expected_outcome: str, *, max_loops: int = 10, council_mode: str = "off", executor: str = "none", adapter: str = "none", extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    proc = run(
        loop_command(root, report_id, max_loops=max_loops, council_mode=council_mode, executor=executor, adapter=adapter),
        root=root,
        extra_env=extra_env,
    )
    proof = load_proof(root, report_id)
    p_path = proof_path(root, report_id)
    b_path = brief_path(root, report_id)
    ok = (
        p_path.exists()
        and b_path.exists()
        and proof.get("final_outcome") == expected_outcome
        and (proc["rc"] == 0 if proof.get("status") in {"PASS", "PAUSED"} else proc["rc"] != 0)
    )
    return {
        "case": name,
        "report_id": report_id,
        "rc": proc["rc"],
        "expected_outcome": expected_outcome,
        "final_outcome": proof.get("final_outcome"),
        "status": proof.get("status"),
        "stop_reason": proof.get("stop_reason"),
        "proof_path": str(p_path),
        "brief_path": str(b_path),
        "proof_exists": p_path.exists(),
        "brief_exists": b_path.exists(),
        "stdout_tail": proc["stdout_tail"],
        "stderr_tail": proc["stderr_tail"],
        "ok": ok,
    }


def run_wrapper_failure_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    proc = run(
        loop_command(root, report_id, council_mode="agentic", executor="none"),
        root=root,
    )
    proof = load_proof(root, report_id)
    output = proc["stdout_tail"] + proc["stderr_tail"]
    ok = proc["rc"] != 0 and proof.get("final_outcome") == "failed" and (
        "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED" in output
        or proof.get("stop_reason") == "ultimate_wrapper_failed"
    )
    return {
        "case": "loop_wrapper_failure_blocks",
        "report_id": report_id,
        "rc": proc["rc"],
        "final_outcome": proof.get("final_outcome"),
        "stop_reason": proof.get("stop_reason"),
        "token_present": "BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED" in output,
        "ok": ok,
    }


def run_child_missing_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    proc = run(
        loop_command(root, report_id, max_loops=10, council_mode="off"),
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_LOOP_TEST_DELETE_HANDOFF_AFTER_WRAPPER": "1"},
    )
    proof = load_proof(root, report_id)
    ok = proc["rc"] != 0 and proof.get("stop_reason") == "BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING"
    return {
        "case": "loop_child_revision_missing_blocks",
        "report_id": report_id,
        "rc": proc["rc"],
        "final_outcome": proof.get("final_outcome"),
        "stop_reason": proof.get("stop_reason"),
        "ok": ok,
    }


def run_child_isolation_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    parent_code = root / "generated_code" / report_id
    parent_code.mkdir(parents=True, exist_ok=True)
    marker = parent_code / "parent_marker.py"
    marker.write_text("# parent marker\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    parent_handoff = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    parent_official = root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json"
    proc = run(loop_command(root, report_id, max_loops=2, council_mode="off"), root=root)
    proof = load_proof(root, report_id)
    iterations = proof.get("iterations") or []
    first = iterations[0] if iterations else {}
    child_iter = iterations[1] if len(iterations) > 1 else {}
    child_id = first.get("child_report_id")
    child_code = root / "generated_code" / str(child_id)
    child_wrapper_rc = ((child_iter.get("wrapper_command") or {}).get("rc"))
    child_wrapper_proof = Path(str(child_iter.get("wrapper_proof_path") or ""))
    materialization_rc = first.get("materialization_rc")
    after = marker.read_text(encoding="utf-8") if marker.exists() else ""
    parent_handoff_payload = read_json(parent_handoff) if parent_handoff.exists() else {}
    parent_not_overwritten_by_child = (
        (not parent_handoff.exists() or parent_handoff_payload.get("report_id") == report_id)
        and not parent_official.exists()
        and (not child_id or not any(parent_code.rglob(f"*{child_id}*")))
    )
    ok = (
        proc["rc"] == 0
        and proof.get("status") != "FAIL"
        and isinstance(child_id, str)
        and child_id.startswith(f"{report_id}__LOOP01__")
        and child_id != report_id
        and materialization_rc == 0
        and child_wrapper_rc == 0
        and child_wrapper_proof.exists()
        and child_code.exists()
        and before == after
        and parent_not_overwritten_by_child
    )
    return {
        "case": "loop_child_report_id_isolation",
        "report_id": report_id,
        "rc": proc["rc"],
        "proof_status": proof.get("status"),
        "child_report_id": child_id,
        "materialization_rc": materialization_rc,
        "materialized_artifact_paths": first.get("materialized_artifact_paths"),
        "child_wrapper_rc": child_wrapper_rc,
        "child_wrapper_proof_path": str(child_wrapper_proof),
        "child_wrapper_proof_exists": child_wrapper_proof.exists(),
        "child_generated_code_exists": child_code.exists(),
        "parent_generated_code_unchanged": before == after,
        "parent_not_overwritten_by_child": parent_not_overwritten_by_child,
        "final_outcome": proof.get("final_outcome"),
        "ok": ok,
    }


def run_child_materialization_target_exists_case(root: Path) -> dict[str, Any]:
    from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff

    report_id = "STEP6_INTEL_HIGH_TURNOVER_REVISION"
    write_step3_input_fixture(root, report_id)
    child = approved_child_revision_from_handoff(root, report_id, 1)
    child_id = str(child.get("child_report_id") or f"{report_id}__LOOP01__MAIN_ITER_002")
    existing_target = root / "objects" / "factor_spec_master" / f"factor_spec_master__{child_id}.json"
    existing_target.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {
        "report_id": child_id,
        "sentinel": "preexisting_child_target_must_not_be_clobbered",
    }
    write_json(existing_target, sentinel)
    before = existing_target.read_text(encoding="utf-8")
    proc = run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
            "--parent-report-id",
            report_id,
            "--child-report-id",
            child_id,
            "--factorforge-root",
            str(root),
        ],
        root=root,
        extra_env={"FACTORFORGE_ULTIMATE_RUN": "1"},
    )
    after = existing_target.read_text(encoding="utf-8")
    output = proc["stdout_tail"] + proc["stderr_tail"]
    materialization_report = root / "objects" / "runtime_context" / f"child_revision_materialization__{report_id}__{child_id}.json"
    ok = (
        proc["rc"] == 1
        and "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS" in output
        and before == after
        and not materialization_report.exists()
    )
    return {
        "case": "loop_child_materialization_target_exists_blocks",
        "report_id": report_id,
        "child_report_id": child_id,
        "rc": proc["rc"],
        "token_present": "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS" in output,
        "existing_artifact_unchanged": before == after,
        "materialization_report_absent": not materialization_report.exists(),
        "ok": ok,
    }


def write_step3_input_fixture(root: Path, report_id: str) -> None:
    from factor_factory.formula.parser import parse_formula
    from factor_factory.mechanism_math.classifier import build_mechanism_math_contract

    spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    if spec_path.exists():
        spec = read_json(spec_path)
        formula = ((spec.get("canonical_spec") or {}).get("formula_text")) or "rank(close + volume)"
        formula_ir = parse_formula(formula)
        spec.setdefault("canonical_spec", {})
        spec["canonical_spec"]["formula_ir"] = formula_ir
        spec["canonical_spec"]["required_inputs"] = formula_ir.get("required_fields") or spec["canonical_spec"].get("required_inputs") or []
        spec["canonical_spec"]["operators"] = formula_ir.get("operator_set") or spec["canonical_spec"].get("operators") or []
        spec["implementation_mode"] = (spec.get("artifact_identity") or {}).get("implementation_mode") or "operator"
        spec["source_type"] = (spec.get("artifact_identity") or {}).get("source_type") or "natural_language_hypothesis"
        spec["implementation_contract"] = {
            "mode": "operator",
            "formula_ir": formula_ir,
            "formula_hash": formula_ir.get("formula_hash"),
            "operator_set": formula_ir.get("operator_set") or [],
            "required_fields": formula_ir.get("required_fields") or [],
        }
        spec["research_contract"] = {
            "target_statistic": "next-period long-side expected return conditional on a price-volume pressure signal",
            "economic_mechanism": "price and volume co-movement proxies persistent buying pressure that may survive costs if slow enough",
            "expected_failure_modes": [
                "turnover too high relative to gross signal",
                "signal disappears after smoothing",
            ],
            "reuse_instruction_for_future_agents": [
                "Preserve the long-side thesis and test cost-adjusted evidence after expression revisions.",
            ],
        }
        spec["learning_and_innovation"] = {
            "reuse_instruction_for_future_agents": [
                "Do not repair this factor through portfolio, short-leg, or decile trading changes.",
            ],
            "innovative_idea_seeds": ["test smoothing as an estimator-kernel revision"],
        }
        spec["math_discipline_review"] = {
            "target_statistic": "E[r_{t+1} | F_t, price_volume_pressure_t]",
            "step1_random_object": "cross-sectional equity return",
            "information_set_legality": "uses current and historical price-volume fields only",
            "expected_failure_modes": ["cost drag", "non-persistent pressure state"],
        }
        spec["mechanism_math_contract"] = build_mechanism_math_contract(
            {
                "formula_text": formula,
                "required_inputs": formula_ir.get("required_fields") or spec["canonical_spec"].get("required_inputs") or [],
                "operators": formula_ir.get("operator_set") or spec["canonical_spec"].get("operators") or [],
            }
        )
        write_json(spec_path, spec)

    daily = root / "runs" / report_id / "step3a_local_inputs" / f"daily_input__{report_id}.csv"
    daily.parent.mkdir(parents=True, exist_ok=True)
    dates = [
        "2020-01-02",
        "2020-01-03",
        "2020-01-06",
        "2020-01-07",
        "2020-01-08",
        "2020-01-09",
        "2020-01-10",
        "2020-01-13",
    ]
    tickers = [f"{idx:06d}.SZ" for idx in range(1, 21)]
    with daily.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "volume",
                "amount",
                "pct_chg",
                "returns",
            ],
        )
        writer.writeheader()
        for d_idx, date in enumerate(dates):
            for t_idx, ticker in enumerate(tickers):
                score = t_idx - 9.5
                close = 10.0 + d_idx * 0.18 + t_idx * 0.08 + (d_idx % 3) * 0.03
                volume = 1200 + d_idx * 37 + t_idx * 23
                rank_perturbation = 0.0018 * (((t_idx + d_idx * 3) % 5) - 2)
                returns = 0.0014 * score + rank_perturbation + 0.0006 * d_idx
                writer.writerow(
                    {
                        "ts_code": ticker,
                        "trade_date": date,
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.3,
                        "close": close,
                        "vol": volume,
                        "volume": volume,
                        "amount": close * volume,
                        "pct_chg": returns * 100,
                        "returns": returns,
                    }
                )
    prep = {
        "report_id": report_id,
        "factor_id": "SMOKE_PRICE_VOLUME",
        "producer": "ultimate_loop_smoke_fixture",
        "feasibility": "ready",
        "available_columns": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "volume", "amount", "pct_chg", "returns"],
        "field_mappings": {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "vol": "vol",
            "amount": "amount",
            "pct_chg": "pct_chg",
            "returns": "returns",
        },
        "field_mapping": {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "returns": "returns",
        },
        "local_input_paths": {
            "input_mode": "daily_only",
            "daily_df_csv": str(daily),
        },
        "sample_window": {"start": "2020-01-02", "end": "2020-01-13"},
        "data_sources": ["synthetic_ultimate_loop_fixture"],
    }
    write_json(root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json", prep)
    write_json(root / "objects" / "data_prep_master" / f"qlib_adapter_config__{report_id}.json", {"report_id": report_id, "adapter_ready": True})


def run_aggregate_brief_case(root: Path) -> dict[str, Any]:
    report_id = "STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED"
    path = brief_path(root, report_id)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    required = [
        "### Economic Interpretation",
        "### Mechanism Math",
        "### Metrics",
        "### Council",
        "### Decision",
        "### Next Action",
    ]
    ok = path.exists() and all(token in text for token in required)
    return {
        "case": "loop_aggregate_brief_written",
        "report_id": report_id,
        "brief_path": str(path),
        "brief_exists": path.exists(),
        "required_sections_present": all(token in text for token in required),
        "ok": ok,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Phase M Factor Forge Ultimate loop smoke.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--fresh", action="store_true")
    return ap.parse_args()


def case_root(base: Path, name: str) -> Path:
    return base / name


def run_with_fresh_fixture(base: Path, name: str, runner) -> dict[str, Any]:
    root = case_root(base, name)
    setup = setup_step6_fixtures(root)
    if setup["rc"] != 0:
        return {
            "case": name,
            "case_root": str(root),
            "fixture_setup": setup,
            "ok": False,
        }
    result = runner(root)
    result["case_root"] = str(root)
    result["fixture_setup_rc"] = setup["rc"]
    return result


def referenced_artifacts_exist(cases: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[str] = []
    for case in cases:
        for key in ("proof_path", "brief_path", "child_wrapper_proof_path"):
            raw = case.get(key)
            if raw and not Path(str(raw)).exists():
                missing.append(str(raw))
    return {"ok": not missing, "missing": missing}


def main() -> int:
    args = parse_args()
    root = Path(args.root or (Path("/tmp") / f"factorforge_ultimate_loop_phase_m_{datetime.now().strftime('%Y%m%d_%H%M%S')}")).expanduser()
    if not is_tmp_root(root):
        print(f"BLOCK_NON_TMP_FACTORFORGE_ROOT: {root}")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    before = snapshot_repo_canonical()
    cases: list[dict[str, Any]] = [
        run_with_fresh_fixture(
            root,
            "loop_promote_stops",
            lambda r: run_loop_case(r, "loop_promote_stops", "STEP6_INTEL_VALID_PROMOTE_NO_REVISION_NEEDED", "promoted", max_loops=10, council_mode="off"),
        ),
        run_with_fresh_fixture(
            root,
            "loop_reject_stops",
            lambda r: run_loop_case(r, "loop_reject_stops", "STEP6_INTEL_LONG_SIDE_NEGATIVE_REVISION", "rejected", max_loops=10, council_mode="off"),
        ),
        run_with_fresh_fixture(
            root,
            "loop_awaiting_agent_results_pauses",
            lambda r: run_loop_case(
                r,
                "loop_awaiting_agent_results_pauses",
                "STEP6_INTEL_ALPHA013_LIKE_ADVISORY_MECHANISM_CHALLENGE_BRANCH",
                "awaiting_agent_results",
                max_loops=10,
                council_mode="agentic",
                executor="dispatch_manifest",
                adapter="manual_file",
            ),
        ),
        run_with_fresh_fixture(
            root,
            "loop_max_10_stops",
            lambda r: run_loop_case(r, "loop_max_10_stops", "STEP6_INTEL_HIGH_TURNOVER_REVISION", "max_loops_reached", max_loops=1, council_mode="off"),
        ),
        run_with_fresh_fixture(root, "loop_wrapper_failure_blocks", run_wrapper_failure_case),
        run_with_fresh_fixture(root, "loop_child_report_id_isolation", run_child_isolation_case),
        run_with_fresh_fixture(root, "loop_child_materialization_target_exists_blocks", run_child_materialization_target_exists_case),
        run_with_fresh_fixture(root, "loop_child_revision_missing_blocks", run_child_missing_case),
    ]
    cases.append(run_aggregate_brief_case(case_root(root, "loop_promote_stops")))

    pollution = canonical_pollution(before)
    referenced = referenced_artifacts_exist(cases)
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) and referenced["ok"] and not pollution["polluted"] else "BLOCK"
    summary = {
        "contract_version": "factorforge_ultimate_loop_smoke_v1",
        "created_at_utc": utc_now(),
        "factorforge_root": str(root),
        "root_is_tmp": True,
        "verdict": verdict,
        "cases": cases,
        "referenced_artifacts": referenced,
        "canonical_pollution": pollution,
    }
    summary_path = root / "objects" / "runtime_context" / "ultimate_loop_smoke_summary.json"
    write_json(summary_path, summary)
    print(f"verdict={verdict}")
    print(f"summary={summary_path}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
