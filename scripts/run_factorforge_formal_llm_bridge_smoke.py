#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RID = "FORMAL_LLM_BRIDGE_SMOKE"
SAMPLE_DIRECT_CODE_SOURCE = """import numpy as np
import pandas as pd


def compute_factor(daily_df: pd.DataFrame | None = None, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        raise ValueError("daily_df is required")
    df = daily_df.copy()
    required = {"ts_code", "trade_date", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"daily_df missing required columns: {missing}")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["factor_value"] = df.groupby("ts_code", sort=False)["close"].pct_change()
    out = df[["ts_code", "trade_date", "factor_value"]].replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=["factor_value"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
"""


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cmd(cmd: list[str], *, factorforge_root: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(factorforge_root)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)


def tail(text: str, n: int = 3000) -> str:
    return text[-n:]


def case_step1_provider_missing(root: Path) -> dict[str, Any]:
    out_dir = root / "objects" / "raw_llm" / "FORMAL_PROVIDER_MISSING" / "step1"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            "FORMAL_PROVIDER_MISSING",
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--out-dir",
            str(out_dir),
        ],
        factorforge_root=root,
    )
    token = "BLOCK_STEP1_LLM_PROVIDER_UNAVAILABLE" in (proc.stdout + proc.stderr)
    raw_files = list(out_dir.glob("step1_*_raw.json")) if out_dir.exists() else []
    return {
        "case": "step1_provider_missing_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "raw_files": [str(p) for p in raw_files],
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(proc.returncode != 0 and token and not raw_files),
    }


def case_prepare_no_raw_blocks(root: Path) -> dict[str, Any]:
    no_raw_root = root / "no_raw_case"
    no_raw_root.mkdir(parents=True, exist_ok=True)
    report_id = "FORMAL_NO_RAW"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(no_raw_root),
            "--report-id",
            report_id,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--end-step",
            "3a",
            "--write-report",
        ],
        factorforge_root=no_raw_root,
    )
    token = "BLOCK_FORMAL_STEP1_LLM_OUTPUT_REQUIRED" in (proc.stdout + proc.stderr)
    runtime_context = no_raw_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    return {
        "case": "prepare_no_raw_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "runtime_context_exists": runtime_context.exists(),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(proc.returncode != 0 and token and not runtime_context.exists()),
    }


def case_step1_fixture(root: Path) -> dict[str, Any]:
    out_dir = root / "objects" / "raw_llm" / RID / "step1"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            RID,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--out-dir",
            str(out_dir),
            "--provider",
            "fixture",
            "--write-report",
        ],
        factorforge_root=root,
    )
    expected = [
        "step1_primary_raw.json",
        "step1_challenger_raw.json",
        "step1_chief_raw.json",
        "step1_llm_bridge_report.json",
    ]
    payloads: dict[str, Any] = {}
    for name in expected:
        path = out_dir / name
        if path.exists():
            payloads[name] = read_json(path)
    report = payloads.get("step1_llm_bridge_report.json") or {}
    ok = bool(
        proc.returncode == 0
        and all((out_dir / name).exists() for name in expected)
        and report.get("provider") == "fixture"
        and report.get("report_id") == RID
        and report.get("pdf_sha256")
        and report.get("raw_outputs", {}).get("primary", {}).get("prompt_hash")
        and report.get("raw_outputs", {}).get("primary", {}).get("parsed_json_valid") is True
    )
    return {
        "case": "step1_fixture_raw_outputs",
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "out_dir": str(out_dir),
        "ok": ok,
    }


def case_step1_command_bad_json_writes_failure_report(root: Path) -> dict[str, Any]:
    provider = root / "bad_step1_provider.py"
    provider.write_text("import sys\nsys.stdin.read()\nprint('not-json')\n", encoding="utf-8")
    out_dir = root / "objects" / "raw_llm" / "FORMAL_BAD_JSON_PROVIDER" / "step1"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            "FORMAL_BAD_JSON_PROVIDER",
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--out-dir",
            str(out_dir),
            "--provider",
            "command",
            "--write-report",
        ],
        factorforge_root=root,
        extra_env={"FACTORFORGE_STEP1_LLM_COMMAND": f"{sys.executable} {provider}"},
    )
    report_path = out_dir / "step1_llm_bridge_report.json"
    report = read_json(report_path) if report_path.exists() else {}
    primary = (report.get("raw_outputs") or {}).get("primary") or {}
    token = "BLOCK_STEP1_LLM_PROVIDER_FAILED" in (proc.stdout + proc.stderr)
    ok = bool(
        proc.returncode != 0
        and token
        and report_path.exists()
        and report.get("verdict") == "BLOCK"
        and report.get("provider") == "command"
        and primary.get("parsed_json_valid") is False
        and primary.get("raw_response_sha256")
        and primary.get("validation_error")
    )
    return {
        "case": "step1_command_bad_json_writes_failure_report",
        "rc": proc.returncode,
        "token_present": token,
        "report_path": str(report_path),
        "report_exists": report_path.exists(),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": ok,
    }


def case_step2_provider_missing(root: Path) -> dict[str, Any]:
    out_dir = root / "objects" / "raw_llm" / "FORMAL_STEP2_PROVIDER_MISSING" / "step2"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            "FORMAL_STEP2_PROVIDER_MISSING",
            "--factorforge-root",
            str(root),
            "--out-dir",
            str(out_dir),
        ],
        factorforge_root=root,
    )
    token = "BLOCK_STEP2_LLM_PROVIDER_UNAVAILABLE" in (proc.stdout + proc.stderr)
    raw_files = list(out_dir.glob("step2_*_raw.json")) if out_dir.exists() else []
    return {
        "case": "step2_provider_missing_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "raw_files": [str(p) for p in raw_files],
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(proc.returncode != 0 and token and not raw_files),
    }


def case_step2_alpha_only_blocks(root: Path) -> dict[str, Any]:
    alpha_only_root = root / "alpha_only_step2_case"
    report_id = "FORMAL_STEP2_ALPHA_ONLY"
    alpha_path = alpha_only_root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json"
    alpha_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_path.write_text(
        json.dumps({"report_id": report_id, "final_factor": {"name": "ALPHA_ONLY"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    out_dir = alpha_only_root / "objects" / "raw_llm" / report_id / "step2"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(alpha_only_root),
            "--out-dir",
            str(out_dir),
            "--provider",
            "fixture",
            "--write-report",
        ],
        factorforge_root=alpha_only_root,
    )
    token = "BLOCK_STEP2_STEP1_CONTEXT_REQUIRED" in (proc.stdout + proc.stderr)
    raw_files = list(out_dir.glob("step2_*_raw.json")) if out_dir.exists() else []
    return {
        "case": "step2_alpha_only_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "raw_files": [str(p) for p in raw_files],
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(proc.returncode != 0 and token and not raw_files),
    }


def case_step2_fixture(root: Path) -> dict[str, Any]:
    out_dir = root / "objects" / "raw_llm" / RID / "step2"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            RID,
            "--factorforge-root",
            str(root),
            "--out-dir",
            str(out_dir),
            "--provider",
            "fixture",
            "--write-report",
        ],
        factorforge_root=root,
    )
    expected = [
        "step2_primary_raw.json",
        "step2_challenger_raw.json",
        "step2_auditor_raw.json",
        "step2_llm_bridge_report.json",
    ]
    report = read_json(out_dir / "step2_llm_bridge_report.json") if (out_dir / "step2_llm_bridge_report.json").exists() else {}
    ok = bool(
        proc.returncode == 0
        and all((out_dir / name).exists() for name in expected)
        and report.get("provider") == "fixture"
        and report.get("report_id") == RID
        and report.get("raw_outputs", {}).get("primary", {}).get("prompt_hash")
        and report.get("raw_outputs", {}).get("auditor", {}).get("parsed_json_valid") is True
    )
    return {
        "case": "step2_fixture_raw_outputs",
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "out_dir": str(out_dir),
        "ok": ok,
    }


def case_prepare_chain(root: Path) -> dict[str, Any]:
    step1 = root / "objects" / "raw_llm" / RID / "step1"
    step2 = root / "objects" / "raw_llm" / RID / "step2"
    _inject_explicit_direct_code_source(step2 / "step2_primary_raw.json")
    _inject_explicit_direct_code_source(step2 / "step2_challenger_raw.json")
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(root),
            "--report-id",
            RID,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--step1-primary-raw",
            str(step1 / "step1_primary_raw.json"),
            "--step1-challenger-raw",
            str(step1 / "step1_challenger_raw.json"),
            "--step1-chief-raw",
            str(step1 / "step1_chief_raw.json"),
            "--step2-primary-raw",
            str(step2 / "step2_primary_raw.json"),
            "--step2-challenger-raw",
            str(step2 / "step2_challenger_raw.json"),
            "--step2-auditor-raw",
            str(step2 / "step2_auditor_raw.json"),
            "--end-step",
            "3a",
            "--write-report",
        ],
        factorforge_root=root,
    )
    report_path = root / "objects" / "validation" / f"formal_artifact_prepare_report__{RID}.json"
    report = read_json(report_path) if report_path.exists() else {}
    alpha_path = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{RID}.json"
    spec_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{RID}.json"
    alpha = read_json(alpha_path) if alpha_path.exists() else {}
    spec = read_json(spec_path) if spec_path.exists() else {}
    discipline = alpha.get("research_discipline") or {}
    mpt = discipline.get("market_process_thesis") or {}
    provenance = discipline.get("what_must_be_true_provenance") or {}
    runtime_context = root / "objects" / "runtime_context" / f"runtime_context__{RID}.json"
    ok = bool(
        proc.returncode == 0
        and report.get("verdict") == "ACCEPT"
        and report.get("validators", {}).get("step1", {}).get("rc") == 0
        and report.get("validators", {}).get("step2", {}).get("rc") == 0
        and report.get("validators", {}).get("step3", {}).get("rc") == 0
        and report.get("canonical_report_id_preserved") is True
        and report.get("formal_artifacts_valid") is True
        and report.get("workflow_may_dispatch_worker") is True
        and report.get("worker_started") is False
        and report.get("worker_dispatch_status") == "not_dispatched_by_prepare"
        and report.get("worker_dispatch_allowed") is True
        and not runtime_context.exists()
        and isinstance(mpt, dict)
        and mpt.get("what_must_be_true")
        and discipline.get("what_must_be_true")
        and (provenance.get("generic_template_used") is False or provenance == {})
        and spec.get("implementation_mode") == "direct_code"
        and (spec.get("artifact_identity") or {}).get("code_contract_hash")
    )
    return {
        "case": "formal_fixture_chain_passes_without_runtime_context",
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "prepare_report": str(report_path),
        "runtime_context_exists": runtime_context.exists(),
        "worker_dispatch_allowed": report.get("worker_dispatch_allowed"),
        "step1_market_process_thesis_present": bool(mpt),
        "step1_what_must_be_true": discipline.get("what_must_be_true"),
        "step2_implementation_mode": spec.get("implementation_mode"),
        "ok": ok,
    }


def _write_raw_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inject_explicit_direct_code_source(raw_path: Path) -> None:
    raw = read_json(raw_path)
    contract = raw.setdefault("implementation_contract", {})
    contract["implementation_mode"] = "direct_code"
    code_contract = contract.setdefault("code_contract", {})
    code_contract.update({
        "code_contract_version": "factorforge_direct_code_contract_v1",
        "function_name": "compute_factor",
        "entrypoint": "compute_factor",
        "source_code": SAMPLE_DIRECT_CODE_SOURCE,
        "code_hash": hashlib.sha256(SAMPLE_DIRECT_CODE_SOURCE.encode("utf-8")).hexdigest(),
        "imports": ["numpy", "pandas"],
        "dependencies": ["numpy", "pandas"],
        "input_schema": {"daily_df": ["ts_code", "trade_date", "close"]},
        "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
        "required_fields": ["ts_code", "trade_date", "close"],
    })
    _write_raw_json(raw_path, raw)


def _generate_fixture_raw(root: Path, report_id: str) -> tuple[Path, Path]:
    step1 = root / "objects" / "raw_llm" / report_id / "step1"
    step2 = root / "objects" / "raw_llm" / report_id / "step2"
    run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            report_id,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--out-dir",
            str(step1),
            "--provider",
            "fixture",
            "--write-report",
        ],
        factorforge_root=root,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(root),
            "--out-dir",
            str(step2),
            "--provider",
            "fixture",
            "--write-report",
        ],
        factorforge_root=root,
    )
    return step1, step2


def case_step1_underivable_mechanism_blocks(root: Path) -> dict[str, Any]:
    case_root = root / "kaiyuan_missing_step1_case"
    case_root.mkdir(parents=True, exist_ok=True)
    report_id = "KAIYUAN_RTA19_MISSING_MECHANISM"
    step1, _ = _generate_fixture_raw(case_root, report_id)
    chief_path = step1 / "step1_chief_raw.json"
    chief = read_json(chief_path)
    chief.pop("market_process_thesis", None)
    chief.pop("what_must_be_true", None)
    chief.pop("mechanism_assumptions", None)
    ff = chief.get("final_factor") or {}
    for key in [
        "economic_logic",
        "behavioral_logic",
        "causal_chain",
        "what_must_be_true",
        "what_would_break_it",
        "key_implementation_risks",
    ]:
        ff[key] = [] if key.startswith("what_") or key == "key_implementation_risks" else ""
    chief["final_factor"] = ff
    _write_raw_json(chief_path, chief)
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(case_root),
            "--report-id",
            report_id,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--step1-primary-raw",
            str(step1 / "step1_primary_raw.json"),
            "--step1-challenger-raw",
            str(step1 / "step1_challenger_raw.json"),
            "--step1-chief-raw",
            str(chief_path),
            "--end-step",
            "1",
            "--write-report",
        ],
        factorforge_root=case_root,
    )
    report_path = case_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    report = read_json(report_path) if report_path.exists() else {}
    runtime_context = case_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    step1_stdout = (report.get("validators") or {}).get("step1", {}).get("stdout_tail", "")
    ok = bool(
        proc.returncode != 0
        and report.get("verdict") == "BLOCK"
        and (report.get("validators") or {}).get("step1", {}).get("rc") == 1
        and "what_must_be_true missing" in step1_stdout
        and report.get("runtime_context_written") is False
        and report.get("worker_started") is False
        and not runtime_context.exists()
    )
    return {
        "case": "kaiyuan_step1_missing_underivable_mechanism_blocks",
        "rc": proc.returncode,
        "prepare_report": str(report_path),
        "runtime_context_exists": runtime_context.exists(),
        "runtime_context_written": report.get("runtime_context_written"),
        "worker_started": report.get("worker_started"),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": ok,
    }


def case_step2_hybrid_missing_contract_blocks(root: Path) -> dict[str, Any]:
    case_root = root / "hybrid_missing_contract_case"
    case_root.mkdir(parents=True, exist_ok=True)
    report_id = "KAIYUAN_RTA19_BAD_HYBRID"
    step1, step2 = _generate_fixture_raw(case_root, report_id)
    primary_path = step2 / "step2_primary_raw.json"
    challenger_path = step2 / "step2_challenger_raw.json"
    for raw_path in [primary_path, challenger_path]:
        raw = read_json(raw_path)
        raw["implementation_mode"] = "hybrid"
        raw["implementation_contract"] = {
            "implementation_mode": "hybrid",
            "operator_subgraph": {},
            "custom_blocks": [],
        }
        raw.pop("custom_blocks", None)
        _write_raw_json(raw_path, raw)
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(case_root),
            "--report-id",
            report_id,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--step1-primary-raw",
            str(step1 / "step1_primary_raw.json"),
            "--step1-challenger-raw",
            str(step1 / "step1_challenger_raw.json"),
            "--step1-chief-raw",
            str(step1 / "step1_chief_raw.json"),
            "--step2-primary-raw",
            str(primary_path),
            "--step2-challenger-raw",
            str(challenger_path),
            "--step2-auditor-raw",
            str(step2 / "step2_auditor_raw.json"),
            "--end-step",
            "2",
            "--write-report",
        ],
        factorforge_root=case_root,
    )
    report_path = case_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    report = read_json(report_path) if report_path.exists() else {}
    step2_stdout = (report.get("validators") or {}).get("step2", {}).get("stdout_tail", "")
    step2_stderr = (report.get("validators") or {}).get("step2", {}).get("stderr_tail", "")
    text = step2_stdout + step2_stderr + proc.stdout + proc.stderr
    ok = bool(
        proc.returncode != 0
        and report.get("verdict") == "BLOCK"
        and (report.get("validators") or {}).get("step2", {}).get("rc") == 1
        and "BLOCK_INVALID_HYBRID_CONTRACT" in text
        and report.get("runtime_context_written") is False
        and report.get("worker_started") is False
    )
    return {
        "case": "step2_hybrid_mode_missing_hybrid_contract_blocks",
        "rc": proc.returncode,
        "validate_rc": (report.get("validators") or {}).get("step2", {}).get("rc"),
        "token_present": "BLOCK_INVALID_HYBRID_CONTRACT" in text,
        "runtime_context_written": report.get("runtime_context_written"),
        "worker_started": report.get("worker_started"),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": ok,
    }


def case_prepare_existing_runtime_context_blocks_dispatch(root: Path) -> dict[str, Any]:
    runtime_dir = root / "objects" / "runtime_context"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / f"runtime_context__{RID}.json"
    runtime_path.write_text(json.dumps({"report_id": RID, "preexisting": True}, ensure_ascii=False), encoding="utf-8")
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(root),
            "--report-id",
            RID,
            "--report-pdf",
            "fixtures/step2/sample_report_stub.pdf",
            "--end-step",
            "3a",
            "--validate-existing-only",
            "--write-report",
        ],
        factorforge_root=root,
    )
    report_path = root / "objects" / "validation" / f"formal_artifact_prepare_report__{RID}.json"
    report = read_json(report_path) if report_path.exists() else {}
    ok = bool(
        proc.returncode == 0
        and report.get("verdict") == "ACCEPT"
        and report.get("formal_artifacts_valid") is True
        and report.get("workflow_may_dispatch_worker") is False
        and report.get("worker_dispatch_allowed") is False
        and report.get("worker_started") is False
        and report.get("worker_dispatch_status") == "not_dispatched_by_prepare"
        and report.get("runtime_context_written") is True
    )
    runtime_path.unlink(missing_ok=True)
    return {
        "case": "prepare_existing_runtime_context_blocks_dispatch",
        "rc": proc.returncode,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "prepare_report": str(report_path),
        "ok": ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/factorforge_formal_llm_bridge_smoke")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    cases = [
        case_prepare_no_raw_blocks(root),
        case_step1_provider_missing(root),
        case_step1_fixture(root),
        case_step1_command_bad_json_writes_failure_report(root),
        case_step2_provider_missing(root),
        case_step2_alpha_only_blocks(root),
        case_step2_fixture(root),
        case_prepare_chain(root),
        case_step1_underivable_mechanism_blocks(root),
        case_step2_hybrid_missing_contract_blocks(root),
        case_prepare_existing_runtime_context_blocks_dispatch(root),
    ]
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) else "BLOCK"
    summary = {
        "version": "factorforge_formal_llm_bridge_smoke_v1",
        "report_id": RID,
        "verdict": verdict,
        "runtime_context_written": (root / "objects" / "runtime_context" / f"runtime_context__{RID}.json").exists(),
        "worker_started": False,
        "cases": cases,
    }
    out = root / "objects" / "validation" / "formal_llm_bridge_smoke_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
