#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
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


def case_step2_command_direct_code_missing_source_blocks(root: Path) -> dict[str, Any]:
    case_root = root / "step2_command_missing_source_case"
    report_id = "FORMAL_STEP2_COMMAND_MISSING_SOURCE"
    step1, _ = _generate_fixture_raw(case_root, report_id)
    provider = case_root / "bad_step2_missing_source_provider.py"
    provider.write_text(
        """import json, sys
req = json.loads(sys.stdin.read())
role = req.get("role")
if role in {"primary", "challenger"}:
    out = {
        "report_id": req.get("report_id"),
        "factor_id": "BAD_DIRECT_CODE",
        "raw_formula_text": "custom direct-code algorithm without source",
        "operators": ["custom_direct_code"],
        "required_inputs": ["close"],
        "implementation_mode": "direct_code",
        "implementation_contract": {
            "implementation_mode": "direct_code",
            "code_contract": {
                "function_name": "compute_factor",
                "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
                "required_fields": ["close"],
                "source_derivation": {"derivation": "bad_missing_source", "not_fallback": True}
            }
        },
        "_llm_bridge_provenance": {"provider": "command-smoke-bad", "formal_llm_extraction": True, "fixture_only": False}
    }
else:
    out = {
        "report_id": req.get("report_id"),
        "factor_id": "BAD_DIRECT_CODE",
        "consistency_score": 0.9,
        "matches_core_driver": True,
        "mismatch_points": [],
        "missing_steps": [],
        "distortion_risks": [],
        "recommendation": "proceed"
    }
print(json.dumps(out, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    out_dir = case_root / "objects" / "raw_llm" / report_id / "step2"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(case_root),
            "--out-dir",
            str(out_dir),
            "--provider",
            "command",
            "--write-report",
        ],
        factorforge_root=case_root,
        extra_env={"FACTORFORGE_STEP2_LLM_COMMAND": f"{sys.executable} {provider}"},
    )
    report_path = out_dir / "step2_llm_bridge_report.json"
    report = read_json(report_path) if report_path.exists() else {}
    primary_report = ((report.get("raw_outputs") or {}).get("primary") or {})
    text = proc.stdout + proc.stderr + json.dumps(report, ensure_ascii=False)
    token = "BLOCK_STEP2_LLM_DIRECT_CODE_SOURCE_CONTRACT_MISSING" in text
    runtime_context = case_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    return {
        "case": "step2_command_direct_code_missing_source_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "step1_raw_dir": str(step1),
        "report_path": str(report_path),
        "report_exists": report_path.exists(),
        "primary_parsed_json_valid": primary_report.get("parsed_json_valid"),
        "primary_validation_error": primary_report.get("validation_error"),
        "runtime_context_exists": runtime_context.exists(),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(
            proc.returncode != 0
            and token
            and report.get("verdict") == "BLOCK"
            and primary_report.get("parsed_json_valid") is False
            and "BLOCK_STEP2_LLM_DIRECT_CODE_SOURCE_CONTRACT_MISSING" in str(primary_report.get("validation_error") or "")
            and not runtime_context.exists()
        ),
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
        "source_derivation": {
            "derivation": "source_code_preserved_from_formal_step2_raw_direct_code_contract",
            "not_fallback": True,
            "fixture_only": True,
        },
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


def _write_command_provider(root: Path) -> Path:
    provider = root / "fresh_command_provider.py"
    provider.write_text(
        f"""#!/usr/bin/env python3
import copy
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path({str(ROOT)!r})
SOURCE = {SAMPLE_DIRECT_CODE_SOURCE!r}


def provenance(req, role):
    return {{
        "provider": "command-smoke-fresh",
        "model": "command-smoke-model",
        "role": role,
        "report_id": req.get("report_id"),
        "prompt_hash": req.get("prompt_hash"),
        "pdf_sha256": req.get("pdf_sha256") or "smoke-pdf-sha",
        "formal_llm_extraction": True,
        "fixture_only": False,
        "source_derivation": "fresh_command_provider_smoke",
    }}


def step1_intake(req, role):
    payload = json.loads((ROOT / "fixtures" / "step1" / "sample_intake_response.json").read_text(encoding="utf-8"))
    payload["report_id"] = req.get("report_id")
    payload["_llm_bridge_provenance"] = provenance(req, role)
    payload.setdefault("final_factor", {{}})["name"] = "聪明钱因子2.0"
    payload["final_factor"]["assembly_steps"] = [
        "计算分钟收益率绝对值与成交量对数比 S=|R|/ln(V)",
        "按 S 对分钟成交切片排序",
        "选取累计成交量 top20% 的聪明钱分钟",
        "计算 VWAPsmart/VWAPall 作为日度聪明钱强度",
    ]
    payload["final_factor"]["economic_logic"] = "聪明钱成交切片可能代表信息优势交易或约束驱动订单流。"
    payload["final_factor"]["behavioral_logic"] = "慢反应流动性提供者和噪声交易者可能为信息优势订单流支付价格冲击成本。"
    payload["final_factor"]["what_must_be_true"] = [
        "S=|R|/ln(V) 能够区分信息含量更高的分钟成交切片。",
        "top20% 累计成交量对应的 VWAPsmart 相对 VWAPall 对未来收益分布有可检验关系。",
    ]
    return payload


def step1_chief(req):
    must = [
        "S=|R|/ln(V) 必须能识别信息含量更高或冲击更强的分钟成交。",
        "VWAPsmart/VWAPall 必须与后续收益的条件分布变化相关，而不是纯粹成交量噪声。",
    ]
    breaks = [
        "S 排序选出的 top20% 成交切片不稳定或不可复现。",
        "VWAPsmart/VWAPall 与未来收益无关或方向在样本外反转。",
    ]
    return {{
        "report_id": req.get("report_id"),
        "final_factor": {{
            "name": "聪明钱因子2.0",
            "assembly_steps": [
                "计算 S=|R|/ln(V)",
                "按 S 排序并选取累计成交量 top20%",
                "计算 VWAPsmart/VWAPall",
            ],
            "accepted_subfactor_names": ["smart_money_vwap_ratio"],
            "direction": "positive_if_smart_vwap_strength_predicts_return",
            "alpha_strength": "requires_step4_validation",
            "alpha_source": "kaiyuan smart money v2 PDF",
            "economic_logic": "信息优势或约束驱动订单流在分钟成交中留下可观测价格冲击。",
            "behavioral_logic": "噪声交易者、慢反应流动性提供者或被动调仓需求为信息优势订单流支付短期价格冲击成本。",
            "causal_chain": "高信息分钟切片 -> VWAPsmart/VWAPall 状态 -> 后续收益分布变化",
            "what_must_be_true": must,
            "what_would_break_it": breaks,
            "key_implementation_risks": ["分钟数据字段与成交量口径必须一致"],
        }},
        "market_process_thesis": {{
            "market_phenomenon": "聪明钱分钟成交切片反映信息优势订单流或约束驱动冲击。",
            "economic_hypothesis": "S 排序识别高信息成交切片，VWAPsmart/VWAPall 估计该状态并预测未来收益分布。",
            "return_source_family": "information_advantage",
            "payer_or_counterparty": "噪声交易者、慢反应流动性提供者或被动调仓交易者",
            "why_they_pay": "他们在信息优势订单流或约束交易压力下以不利价格成交。",
            "what_must_be_true": must,
            "what_would_break_it": breaks,
        }},
        "what_must_be_true": must,
        "mechanism_assumptions": must,
        "logic_provenance_summary": {{
            "merge_mode": "fresh_command_provider_smoke",
            "derived_from": ["PDF formula S=|R|/ln(V)", "S sorting", "top20% cumulative volume", "VWAPsmart/VWAPall"],
        }},
        "assembly_path": ["S=|R|/ln(V)", "S排序", "top20% cumulative volume", "VWAPsmart/VWAPall"],
        "unresolved_ambiguities": ["正式生产 LLM 需确认分钟成交量字段和排序方向。"],
        "chief_decision_summary": "Use smart-money VWAP ratio as the report-specific factor idea.",
        "chief_confidence": "medium",
        "chief_rationale": "Both extraction routes preserve the same formula mechanics.",
        "_llm_bridge_provenance": provenance(req, "chief"),
    }}


def step2_raw(req, role):
    required = ["ts_code", "trade_date", "close"]
    code_contract = {{
        "code_contract_version": "factorforge_direct_code_contract_v1",
        "function_name": "compute_factor",
        "entrypoint": "compute_factor",
        "source_code": SOURCE,
        "code_hash": hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
        "imports": ["numpy", "pandas"],
        "dependencies": ["numpy", "pandas"],
        "input_schema": {{"daily_df": required}},
        "output_schema": {{"columns": ["ts_code", "trade_date", "factor_value"]}},
        "required_fields": required,
        "source_derivation": {{
            "derivation": "source_code_preserved_from_formal_step2_raw_direct_code_contract",
            "not_fallback": True,
            "fixture_only": False,
        }},
    }}
    return {{
        "report_id": req.get("report_id"),
        "factor_id": "SMART_MONEY_V2",
        "route": role,
        "raw_formula_text": "smart_money_v2 = VWAPsmart / VWAPall using S=|R|/ln(V), S sorting, and top20% cumulative volume",
        "operators": ["custom_direct_code"],
        "required_inputs": required,
        "implementation_mode": "direct_code",
        "implementation_contract": {{
            "implementation_mode": "direct_code",
            "mode": "direct_code",
            "required_fields": required,
            "function_name": "compute_factor",
            "code_contract": code_contract,
            "output_schema": {{"columns": ["ts_code", "trade_date", "factor_value"]}},
        }},
        "time_series_steps": ["estimate smart-money state from completed market observations"],
        "cross_sectional_steps": ["rank or compare smart-money strength cross-sectionally after construction"],
        "preprocessing": ["validate price and volume fields before implementation"],
        "normalization": [],
        "neutralization": [],
        "explicit_items": ["S=|R|/ln(V)", "S sorting", "top20% cumulative volume", "VWAPsmart/VWAPall"],
        "inferred_items": ["direct_code selected because the custom smart-money algorithm is not a pure Formula-IR expression"],
        "ambiguities": ["production LLM must confirm minute-data field mapping before worker execution"],
        "_llm_bridge_provenance": provenance(req, role),
    }}


def auditor(req):
    return {{
        "report_id": req.get("report_id"),
        "factor_id": "SMART_MONEY_V2",
        "consistency_score": 0.93,
        "matches_core_driver": True,
        "mismatch_points": [],
        "missing_steps": [],
        "distortion_risks": ["minute data field mapping requires production confirmation"],
        "recommendation": "proceed",
        "_llm_bridge_provenance": provenance(req, "auditor"),
    }}


req = json.loads(sys.stdin.read())
role = req.get("role")
version = req.get("version")
if version == "factorforge_step1_llm_bridge_v1":
    if role in {{"primary", "challenger"}}:
        out = step1_intake(req, role)
    else:
        out = step1_chief(req)
elif version == "factorforge_step2_llm_bridge_v1":
    if role in {{"primary", "challenger"}}:
        out = step2_raw(req, role)
    else:
        out = auditor(req)
else:
    raise SystemExit("unsupported request")
print(json.dumps(out, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    provider.chmod(0o755)
    return provider


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_provider_mock_server(root: Path) -> Path:
    server = root / "humphrey_provider_mock_server.py"
    server.write_text(
        """#!/usr/bin/env python3
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
MODE = sys.argv[2]


def response_json():
    return {
        "report_id": "HUMPHREY_PROVIDER_MOCK",
        "final_factor": {
            "name": "mock factor",
            "assembly_steps": ["mock formula extraction"],
            "economic_logic": "mock economic hypothesis",
            "behavioral_logic": "mock behavior",
            "what_must_be_true": ["mock condition"],
            "what_would_break_it": ["mock falsification"],
        },
        "market_process_thesis": {
            "market_phenomenon": "mock phenomenon",
            "economic_hypothesis": "mock economic hypothesis",
            "return_source_family": "information_advantage",
            "payer_or_counterparty": "mock counterparty",
            "why_they_pay": "mock reason",
            "what_must_be_true": ["mock condition"],
            "what_would_break_it": ["mock falsification"],
        },
        "what_must_be_true": ["mock condition"],
        "mechanism_assumptions": ["mock condition"],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length") or "0")
        self.rfile.read(length)
        if MODE == "malformed":
            body = {"unexpected": "shape"}
        elif self.path.endswith("/chat/completions"):
            body = {"choices": [{"message": {"content": json.dumps(response_json(), ensure_ascii=False)}}]}
        elif self.path.endswith("/messages"):
            body = {"content": [{"type": "text", "text": json.dumps(response_json(), ensure_ascii=False)}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
""",
        encoding="utf-8",
    )
    server.chmod(0o755)
    return server


def _write_openclaw_config(path: Path, *, provider_name: str, api: str, base_url: str) -> None:
    payload = {
        "models": {
            "providers": {
                provider_name: {
                    "api": api,
                    "baseUrl": base_url,
                    "apiKey": "mock-key",
                }
            }
        }
    }
    _write_raw_json(path, payload)


def _humphrey_provider_request() -> dict[str, Any]:
    return {
        "version": "factorforge_step2_llm_bridge_v1",
        "role": "auditor",
        "report_id": "HUMPHREY_PROVIDER_MOCK",
        "prompt_name": "mock_step2_auditor_prompt",
        "prompt_hash": "mock_prompt_hash",
        "prompt": "Return JSON only.",
        "step1_context": {
            "step1_raw_present": True,
            "step1_primary_raw": {"report_id": "HUMPHREY_PROVIDER_MOCK"},
            "step1_chief_raw": {"report_id": "HUMPHREY_PROVIDER_MOCK"},
        },
        "prior_outputs": {},
    }


def _run_humphrey_provider_case(
    root: Path,
    *,
    case_name: str,
    provider_api: str,
    server_mode: str = "ok",
    expect_rc: int = 0,
    expected_token: str | None = None,
) -> dict[str, Any]:
    case_root = root / case_name
    case_root.mkdir(parents=True, exist_ok=True)
    provider_name = f"{case_name}_provider"
    port = _free_port()
    server = _write_provider_mock_server(case_root)
    proc_server = subprocess.Popen(
        [sys.executable, str(server), str(port), server_mode],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)
    try:
        config = case_root / "openclaw.json"
        _write_openclaw_config(config, provider_name=provider_name, api=provider_api, base_url=f"http://127.0.0.1:{port}")
        proc = subprocess.run(
            [sys.executable, "scripts/run_factorforge_humphrey_llm_provider.py"],
            cwd=ROOT,
            input=json.dumps(_humphrey_provider_request(), ensure_ascii=False),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "FACTORFORGE_OPENCLAW_CONFIG": str(config),
                "FACTORFORGE_FORMAL_LLM_PROVIDER": provider_name,
                "FACTORFORGE_STEP1_LLM_MODEL": "mock-model",
                "FACTORFORGE_STEP2_LLM_MODEL": "mock-model",
                "FACTORFORGE_FORMAL_LLM_TIMEOUT_SECONDS": "5",
            },
        )
    finally:
        proc_server.terminate()
        try:
            proc_server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc_server.kill()
    parsed: dict[str, Any] = {}
    parse_error = None
    if proc.returncode == 0:
        try:
            parsed = json.loads(proc.stdout)
        except Exception as exc:  # noqa: BLE001 - smoke diagnostic
            parse_error = f"{type(exc).__name__}: {exc}"
    provenance = parsed.get("_llm_bridge_provenance") if isinstance(parsed, dict) else {}
    token_present = expected_token in (proc.stdout + proc.stderr) if expected_token else True
    ok = bool(
        proc.returncode == expect_rc
        and token_present
        and (
            expect_rc != 0
            or (
                isinstance(parsed, dict)
                and parsed.get("report_id") == "HUMPHREY_PROVIDER_MOCK"
                and isinstance(provenance, dict)
                and provenance.get("provider") == provider_name
                and provenance.get("provider_api") == provider_api
                and provenance.get("model") == "mock-model"
                and provenance.get("formal_llm_extraction") is True
                and provenance.get("fixture_only") is False
                and parse_error is None
            )
        )
    )
    return {
        "case": case_name,
        "rc": proc.returncode,
        "expected_rc": expect_rc,
        "provider_api": provider_api,
        "token_present": token_present,
        "parsed_json": bool(parsed),
        "parse_error": parse_error,
        "provenance": provenance if isinstance(provenance, dict) else {},
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": ok,
    }


def case_humphrey_provider_openai_completions_mock(root: Path) -> dict[str, Any]:
    return _run_humphrey_provider_case(
        root,
        case_name="humphrey_provider_openai_completions_mock",
        provider_api="openai-completions",
    )


def case_humphrey_provider_anthropic_messages_mock(root: Path) -> dict[str, Any]:
    return _run_humphrey_provider_case(
        root,
        case_name="humphrey_provider_anthropic_messages_mock",
        provider_api="anthropic-messages",
    )


def case_humphrey_provider_unsupported_api_blocks(root: Path) -> dict[str, Any]:
    return _run_humphrey_provider_case(
        root,
        case_name="humphrey_provider_unsupported_api_blocks",
        provider_api="unsupported-api",
        expect_rc=1,
        expected_token="BLOCK_HUMPHREY_FORMAL_LLM_PROVIDER_UNSUPPORTED_API",
    )


def case_humphrey_provider_malformed_response_blocks(root: Path) -> dict[str, Any]:
    return _run_humphrey_provider_case(
        root,
        case_name="humphrey_provider_malformed_response_blocks",
        provider_api="openai-completions",
        server_mode="malformed",
        expect_rc=1,
        expected_token="BLOCK_HUMPHREY_FORMAL_LLM_PROVIDER_FAILED",
    )


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


def case_command_fresh_kaiyuan_chain_passes(root: Path) -> dict[str, Any]:
    case_root = root / "kaiyuan_command_fresh_case"
    case_root.mkdir(parents=True, exist_ok=True)
    report_id = "kaiyuan_20200209_smart_money_v2"
    provider = _write_command_provider(case_root)
    command = f"{sys.executable} {provider}"
    step1 = case_root / "objects" / "raw_llm" / report_id / "step1"
    step2 = case_root / "objects" / "raw_llm" / report_id / "step2"
    env = {
        "FACTORFORGE_STEP1_LLM_COMMAND": command,
        "FACTORFORGE_STEP2_LLM_COMMAND": command,
        "FACTORFORGE_STEP1_LLM_MODEL": "command-smoke-model",
        "FACTORFORGE_STEP2_LLM_MODEL": "command-smoke-model",
    }
    step1_proc = run_cmd(
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
            "command",
            "--write-report",
        ],
        factorforge_root=case_root,
        extra_env=env,
    )
    step2_proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(case_root),
            "--out-dir",
            str(step2),
            "--provider",
            "command",
            "--write-report",
        ],
        factorforge_root=case_root,
        extra_env=env,
    )
    prepare_proc = run_cmd(
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
            str(step2 / "step2_primary_raw.json"),
            "--step2-challenger-raw",
            str(step2 / "step2_challenger_raw.json"),
            "--step2-auditor-raw",
            str(step2 / "step2_auditor_raw.json"),
            "--end-step",
            "3a",
            "--write-report",
        ],
        factorforge_root=case_root,
    )
    runtime_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    if prepare_proc.returncode == 0:
        runtime_proc = run_cmd(
            [
                sys.executable,
                "scripts/build_factorforge_runtime_context.py",
                "--report-id",
                report_id,
                "--factorforge-root",
                str(case_root),
                "--write",
            ],
            factorforge_root=case_root,
        )
    report_path = case_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    report = read_json(report_path) if report_path.exists() else {}
    spec_path = case_root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    spec = read_json(spec_path) if spec_path.exists() else {}
    alpha_path = case_root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json"
    alpha = read_json(alpha_path) if alpha_path.exists() else {}
    primary_raw = read_json(step2 / "step2_primary_raw.json") if (step2 / "step2_primary_raw.json").exists() else {}
    code_contract = ((spec.get("implementation_contract") or {}).get("code_contract") or {})
    raw_code_contract = ((primary_raw.get("implementation_contract") or {}).get("code_contract") or {})
    runtime_context = case_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    discipline = alpha.get("research_discipline") or {}
    mpt = discipline.get("market_process_thesis") or {}
    ok = bool(
        step1_proc.returncode == 0
        and step2_proc.returncode == 0
        and prepare_proc.returncode == 0
        and runtime_proc.returncode == 0
        and report.get("verdict") == "ACCEPT"
        and (report.get("validators") or {}).get("step1", {}).get("rc") == 0
        and (report.get("validators") or {}).get("step2", {}).get("rc") == 0
        and (report.get("validators") or {}).get("step3", {}).get("rc") == 0
        and report.get("workflow_may_dispatch_worker") is True
        and report.get("worker_started") is False
        and report.get("runtime_context_written") is False
        and runtime_context.exists()
        and spec.get("report_id") == report_id
        and (spec.get("artifact_identity") or {}).get("report_id") == report_id
        and spec.get("implementation_mode") == "direct_code"
        and bool((spec.get("canonical_spec") or {}).get("formula_text"))
        and bool((spec.get("canonical_spec") or {}).get("required_inputs"))
        and bool((spec.get("thesis") or {}).get("alpha_thesis"))
        and bool((spec.get("mechanism_math_contract") or {}).get("observable_inputs"))
        and bool(code_contract.get("source_code") and code_contract.get("code_hash"))
        and bool(raw_code_contract.get("source_code") and raw_code_contract.get("code_hash"))
        and bool(discipline.get("what_must_be_true"))
        and bool(mpt.get("what_must_be_true"))
    )
    return {
        "case": "command_fresh_kaiyuan_direct_code_chain_passes",
        "step1_rc": step1_proc.returncode,
        "step2_rc": step2_proc.returncode,
        "prepare_rc": prepare_proc.returncode,
        "runtime_context_rc": runtime_proc.returncode,
        "prepare_report": str(report_path),
        "raw_step1_dir": str(step1),
        "raw_step2_dir": str(step2),
        "validate_step1_rc": (report.get("validators") or {}).get("step1", {}).get("rc"),
        "validate_step2_rc": (report.get("validators") or {}).get("step2", {}).get("rc"),
        "validate_step3_rc": (report.get("validators") or {}).get("step3", {}).get("rc"),
        "implementation_mode": spec.get("implementation_mode"),
        "raw_code_hash_present": bool(raw_code_contract.get("code_hash")),
        "spec_code_hash_present": bool(code_contract.get("code_hash")),
        "prepare_runtime_context_written": report.get("runtime_context_written"),
        "new_runtime_context_written": runtime_context.exists(),
        "worker_started": report.get("worker_started"),
        "workflow_may_dispatch_worker": report.get("workflow_may_dispatch_worker"),
        "stdout_tail": tail(prepare_proc.stdout),
        "stderr_tail": tail(prepare_proc.stderr),
        "ok": ok,
    }


def case_prepare_runs_formal_bridges_and_writes_runtime_context(root: Path) -> dict[str, Any]:
    case_root = root / "prepare_bridge_wiring_case"
    case_root.mkdir(parents=True, exist_ok=True)
    report_id = "kaiyuan_smart_money_RTA_22"
    provider = _write_command_provider(case_root)
    command = f"{sys.executable} {provider}"
    env = {
        "FACTORFORGE_STEP1_LLM_COMMAND": command,
        "FACTORFORGE_STEP2_LLM_COMMAND": command,
        "FACTORFORGE_STEP1_LLM_MODEL": "command-smoke-model",
        "FACTORFORGE_STEP2_LLM_MODEL": "command-smoke-model",
    }
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
            "--run-formal-llm-bridges",
            "--formal-llm-provider",
            "command",
            "--write-runtime-context",
            "--end-step",
            "3a",
            "--write-report",
        ],
        factorforge_root=case_root,
        extra_env=env,
    )
    report_path = case_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    report = read_json(report_path) if report_path.exists() else {}
    step1 = case_root / "objects" / "raw_llm" / report_id / "step1"
    step2 = case_root / "objects" / "raw_llm" / report_id / "step2"
    step1_primary = read_json(step1 / "step1_primary_raw.json") if (step1 / "step1_primary_raw.json").exists() else {}
    step1_chief = read_json(step1 / "step1_chief_raw.json") if (step1 / "step1_chief_raw.json").exists() else {}
    step2_primary = read_json(step2 / "step2_primary_raw.json") if (step2 / "step2_primary_raw.json").exists() else {}
    spec_path = case_root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    spec = read_json(spec_path) if spec_path.exists() else {}
    raw_code_contract = ((step2_primary.get("implementation_contract") or {}).get("code_contract") or {})
    spec_code_contract = ((spec.get("implementation_contract") or {}).get("code_contract") or {})
    runtime_context = case_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    bridge_meta = report.get("formal_llm_bridges") or {}
    ok = bool(
        proc.returncode == 0
        and report.get("verdict") == "ACCEPT"
        and (report.get("validators") or {}).get("step1", {}).get("rc") == 0
        and (report.get("validators") or {}).get("step2", {}).get("rc") == 0
        and (report.get("validators") or {}).get("step3", {}).get("rc") == 0
        and report.get("runtime_context_written") is True
        and report.get("worker_started") is False
        and report.get("worker_dispatch_status") == "not_dispatched_by_prepare"
        and runtime_context.exists()
        and (bridge_meta.get("step1") or {}).get("generated") is True
        and (bridge_meta.get("step2") or {}).get("generated") is True
        and step1_primary.get("report_id") == report_id
        and step1_chief.get("report_id") == report_id
        and step2_primary.get("report_id") == report_id
        and bool((step1_primary.get("_llm_bridge_provenance") or {}).get("prompt_hash"))
        and bool((step1_primary.get("_llm_bridge_provenance") or {}).get("pdf_sha256"))
        and bool(raw_code_contract.get("source_code") and raw_code_contract.get("code_hash"))
        and bool(raw_code_contract.get("required_fields") and raw_code_contract.get("output_schema"))
        and bool(spec_code_contract.get("source_code") and spec_code_contract.get("code_hash"))
        and spec.get("implementation_mode") == "direct_code"
    )
    return {
        "case": "prepare_runs_formal_bridges_and_writes_runtime_context",
        "rc": proc.returncode,
        "prepare_report": str(report_path),
        "raw_step1_dir": str(step1),
        "raw_step2_dir": str(step2),
        "validate_step1_rc": (report.get("validators") or {}).get("step1", {}).get("rc"),
        "validate_step2_rc": (report.get("validators") or {}).get("step2", {}).get("rc"),
        "validate_step3_rc": (report.get("validators") or {}).get("step3", {}).get("rc"),
        "runtime_context_written": report.get("runtime_context_written"),
        "new_runtime_context_written": runtime_context.exists(),
        "worker_started": report.get("worker_started"),
        "step1_bridge_generated": (bridge_meta.get("step1") or {}).get("generated"),
        "step2_bridge_generated": (bridge_meta.get("step2") or {}).get("generated"),
        "raw_report_id_matches": bool(
            step1_primary.get("report_id") == report_id
            and step1_chief.get("report_id") == report_id
            and step2_primary.get("report_id") == report_id
        ),
        "raw_code_hash_present": bool(raw_code_contract.get("code_hash")),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": ok,
    }


def case_prepare_stale_step1_raw_report_id_blocks(root: Path) -> dict[str, Any]:
    case_root = root / "stale_step1_raw_case"
    case_root.mkdir(parents=True, exist_ok=True)
    stale_id = "kaiyuan_20200209_smart_money_v2"
    report_id = "kaiyuan_smart_money_RTA_22"
    step1, _ = _generate_fixture_raw(case_root, stale_id)
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
            "--end-step",
            "1",
            "--write-report",
        ],
        factorforge_root=case_root,
    )
    report_path = case_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    report = read_json(report_path) if report_path.exists() else {}
    runtime_context = case_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    text = proc.stdout + proc.stderr + json.dumps(report, ensure_ascii=False)
    token = "BLOCK_FORMAL_LLM_RAW_REPORT_ID_MISMATCH" in text
    return {
        "case": "prepare_stale_step1_raw_report_id_blocks",
        "rc": proc.returncode,
        "token_present": token,
        "prepare_report": str(report_path),
        "runtime_context_exists": runtime_context.exists(),
        "worker_started": report.get("worker_started"),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
        "ok": bool(proc.returncode != 0 and token and not runtime_context.exists() and report.get("worker_started") is False),
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
        case_humphrey_provider_openai_completions_mock(root),
        case_humphrey_provider_anthropic_messages_mock(root),
        case_humphrey_provider_unsupported_api_blocks(root),
        case_humphrey_provider_malformed_response_blocks(root),
        case_step2_provider_missing(root),
        case_step2_alpha_only_blocks(root),
        case_step2_command_direct_code_missing_source_blocks(root),
        case_step2_fixture(root),
        case_prepare_chain(root),
        case_step1_underivable_mechanism_blocks(root),
        case_step2_hybrid_missing_contract_blocks(root),
        case_command_fresh_kaiyuan_chain_passes(root),
        case_prepare_runs_formal_bridges_and_writes_runtime_context(root),
        case_prepare_stale_step1_raw_report_id_blocks(root),
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
