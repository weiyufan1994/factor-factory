#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TAIL_LIMIT = 8000
BRANCH_ID = "main"
CONTRACT_VERSION = "factorforge_step2_source_contract_v2"
SOURCE_TYPES = {
    "operator": "paper_canonical_formula",
    "hybrid": "natural_language_hypothesis",
    "direct_code": "natural_language_hypothesis",
}
PRODUCERS = {
    "operator": "step12_canonical_formula_intake",
    "hybrid": "step12_hypothesis_intake",
    "direct_code": "step12_hypothesis_intake",
}
REPO_CANONICAL_DIRS = [
    REPO_ROOT / "objects",
    REPO_ROOT / "runs",
    REPO_ROOT / "evaluations",
    REPO_ROOT / "generated_code",
    REPO_ROOT / "archive",
    REPO_ROOT / "factorforge" / "objects",
    REPO_ROOT / "factorforge" / "runs",
    REPO_ROOT / "factorforge" / "evaluations",
    REPO_ROOT / "factorforge" / "generated_code",
    REPO_ROOT / "factorforge" / "archive",
]


def stable_hash(data: Any) -> str:
    from factor_factory.artifact_identity import stable_hash as _stable_hash

    return _stable_hash(data)


def build_spec_hash(master: dict[str, Any]) -> str:
    from factor_factory.artifact_identity import build_spec_hash as _build_spec_hash

    return _build_spec_hash(master)


def build_artifact_identity(**kwargs: Any) -> dict[str, Any]:
    from factor_factory.artifact_identity import build_artifact_identity as _build_artifact_identity

    return _build_artifact_identity(**kwargs)


def parse_formula(formula_text: str, available_columns: list[str] | None = None) -> dict[str, Any]:
    from factor_factory.formula.parser import parse_formula as _parse_formula

    return _parse_formula(formula_text, available_columns)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def tail(text: str, limit: int = TAIL_LIMIT) -> str:
    return text[-limit:] if len(text) > limit else text


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def command_string(command: list[str]) -> str:
    return " ".join(str(item) for item in command)


def run_capture(command: list[str], *, factorforge_root: Path | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    if factorforge_root is not None:
        env["FACTORFORGE_ROOT"] = str(factorforge_root)
    env.pop("FACTORFORGE_ALLOW_DIRECT_STEP", None)
    env.pop("FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF", None)
    started = utc_now()
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        "command": command,
        "command_string": command_string(command),
        "rc": proc.returncode,
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def repo_canonical_pollution(start_epoch: float) -> dict[str, Any]:
    paths: list[str] = []
    for root in REPO_CANONICAL_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime >= start_epoch:
                    paths.append(str(path))
            except FileNotFoundError:
                continue
    return {
        "scope": "repo_canonical_roots",
        "clean": not paths,
        "paths": sorted(paths)[:100],
        "truncated": len(paths) > 100,
        "checked_roots": [str(p) for p in REPO_CANONICAL_DIRS],
    }


def relative_to_root(path: Path, factorforge_root: Path) -> str:
    return str(path.relative_to(factorforge_root))


def make_fixture_csv(path: Path, *, include_future: bool = False, include_hybrid_fields: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "pct_chg",
    ]
    if include_hybrid_fields:
        fieldnames.extend(["is_tradable", "custom_scale", "universe_flag"])
    if include_future:
        fieldnames.append("future_return")
    rows: list[dict[str, Any]] = []
    for date_idx in range(1, 9):
        for code_idx, code in enumerate(["000001.SZ", "000002.SZ", "000003.SZ"]):
            base = 10.0 + date_idx + code_idx
            row = {
                "ts_code": code,
                "trade_date": f"202601{date_idx:02d}",
                "open": round(base, 4),
                "high": round(base + 0.8 + code_idx * 0.1, 4),
                "low": round(base - 0.5, 4),
                "close": round(base + 0.2 * ((date_idx + code_idx) % 3), 4),
                "vol": 1000 + date_idx * 10 + code_idx * 100,
                "amount": 10000 + date_idx * 100 + code_idx * 500,
                "pct_chg": round(0.001 * (date_idx - code_idx), 6),
            }
            if include_hybrid_fields:
                row["is_tradable"] = 1 if (date_idx + code_idx) % 2 else 0
                row["custom_scale"] = 1.25
                row["universe_flag"] = 1 if code_idx != 2 else 0
            if include_future:
                row["future_return"] = 0.03
            rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def base_research_fields(factor_id: str) -> dict[str, Any]:
    return {
        "thesis": {
            "alpha_thesis": f"{factor_id} synthetic acceptance thesis",
            "target_prediction": "next-period long-side excess return",
            "economic_mechanism": "Synthetic acceptance fixture; no production research claim.",
        },
        "math_discipline_review": {
            "step1_random_object": "synthetic_acceptance_fixture",
            "target_statistic": "long-side risk-adjusted return",
            "information_set_legality": "uses current and historical fields only",
            "expected_failure_modes": ["contract or identity mismatch should block"],
        },
        "learning_and_innovation": {
            "similar_case_lessons_imported": [],
            "innovative_idea_seeds": ["acceptance smoke only"],
            "reuse_instruction_for_future_agents": ["Do not treat synthetic smoke as factor evidence."],
        },
        "research_contract": {
            "target_statistic": "long-side risk-adjusted return",
            "economic_mechanism": "Synthetic acceptance fixture; no production research claim.",
            "expected_failure_modes": ["synthetic acceptance smoke may fail if contract is incomplete"],
            "innovative_idea_seeds": ["acceptance smoke only"],
            "reuse_instruction_for_future_agents": ["Do not treat synthetic smoke as factor evidence."],
            "producer": "step12_hypothesis_intake",
        },
    }


def step2_context_for_hash(report_id: str, factor_id: str) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "factor_id": factor_id,
        "alpha_thesis": f"{factor_id} synthetic acceptance thesis",
        "target_statistic": "long-side risk-adjusted return",
        "economic_mechanism": "Synthetic acceptance fixture; no production research claim.",
        "expected_failure_modes": ["synthetic acceptance smoke may fail if contract is incomplete"],
        "step1_random_object": "synthetic_acceptance_fixture",
        "information_set_legality": "uses current and historical fields only",
        "similar_case_lessons_imported": [],
        "innovative_idea_seeds": ["acceptance smoke only"],
        "reuse_instruction_for_future_agents": ["Do not treat synthetic smoke as factor evidence."],
        "implementation_invariants": [
            "Step3B implementation must preserve the Step2 target statistic and economic mechanism.",
            "Any proxy, sign flip, window change, neutralization, or operator substitution must be recorded as a research-motivated approximation.",
            "Code generation must not optimize metrics by changing the thesis silently.",
        ],
        "source_refs": {
            "factor_spec_master": f"factor_spec_master__{report_id}.json",
            "handoff_to_step3": None,
        },
        "producer": "step3b_from_step2_research_contract",
    }


def annotate_for_step3b_hash(source: str, report_id: str, factor_id: str) -> str:
    context = step2_context_for_hash(report_id, factor_id)
    lines = [
        "# STEP2_RESEARCH_CONTEXT:",
        f"# target_statistic: {context.get('target_statistic')}",
        f"# economic_mechanism: {context.get('economic_mechanism')}",
        f"# expected_failure_modes: {context.get('expected_failure_modes')}",
        "# implementation_guardrail: Preserve the Step2 thesis unless a revision loop explicitly changes it.",
    ]
    return "\n".join(lines) + "\n\n" + source


def data_prep_payload(report_id: str, factor_id: str, fixture_csv: Path | None = None) -> dict[str, Any]:
    columns = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg", "is_tradable", "custom_scale", "universe_flag"]
    payload = {
        "report_id": report_id,
        "factor_id": factor_id,
        "producer": "acceptance_smoke_fixture",
        "feasibility": "ready",
        "available_columns": columns,
        "field_mappings": {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "vol",
            "vol": "vol",
            "amount": "amount",
            "pct_chg": "pct_chg",
            "is_tradable": "is_tradable",
            "custom_scale": "custom_scale",
            "universe_flag": "universe_flag",
        },
        "local_input_paths": {},
        "sample_window": {"start": "20260101", "end": "20260108"},
        "data_sources": ["synthetic_acceptance_fixture"],
    }
    if fixture_csv is not None:
        payload["local_input_paths"] = {
            "input_mode": "daily_only",
            "daily_df_csv": str(fixture_csv),
        }
    return payload


def write_common_objects(factorforge_root: Path, report_id: str, spec: dict[str, Any], prep: dict[str, Any]) -> None:
    write_json(factorforge_root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json", spec)
    write_json(factorforge_root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json", prep)


def build_operator_spec(report_id: str, factor_id: str, formula: str, *, run_id: str) -> dict[str, Any]:
    ir = parse_formula(formula)
    canonical_spec = {
        "formula_text": formula,
        "formula_ir": ir,
        "required_inputs": ir.get("required_fields") or [],
        "operators": ir.get("operator_set") or [],
        "time_series_steps": [],
        "cross_sectional_steps": [],
        "preprocessing": [],
        "normalization": "none",
        "neutralization": "none",
        "rebalance_frequency": "daily",
    }
    implementation_contract = {
        "mode": "operator",
        "formula_ir": ir,
        "formula_hash": ir.get("formula_hash"),
        "operator_set": ir.get("operator_set") or [],
        "required_fields": ir.get("required_fields") or [],
    }
    fields = base_research_fields(factor_id)
    master = {
        "report_id": report_id,
        "factor_id": factor_id,
        "source_type": SOURCE_TYPES["operator"],
        "producer": PRODUCERS["operator"],
        "upstream_producer": PRODUCERS["operator"],
        "contract_version": CONTRACT_VERSION,
        "implementation_mode": "operator",
        "canonical_spec": canonical_spec,
        "implementation_contract": implementation_contract,
        **fields,
    }
    spec_hash = build_spec_hash(master)
    master["artifact_identity"] = build_artifact_identity(
        report_id=report_id,
        factor_id=factor_id,
        source_type=master["source_type"],
        implementation_mode="operator",
        contract_version=CONTRACT_VERSION,
        producer=master["producer"],
        upstream_producer=master["upstream_producer"],
        spec_hash=spec_hash,
        branch_id=BRANCH_ID,
        run_id=run_id,
        artifact_role="factor_spec_master",
        formula_hash=ir.get("formula_hash"),
    )
    master["spec_hash"] = spec_hash
    master["formula_hash"] = ir.get("formula_hash")
    return master


def custom_block_hash(block: dict[str, Any]) -> str:
    normalized = dict(block)
    source = str(normalized.get("source_code") or "")
    normalized["source_code"] = source
    normalized.pop("custom_block_hash", None)
    return stable_hash({"source_code": source, "contract": normalized})


def build_hybrid_spec(report_id: str, factor_id: str, *, source_code: str, run_id: str) -> dict[str, Any]:
    formula = "rank(delta(close, 1))"
    ir = parse_formula(formula)
    block = {
        "name": "tradable_universe_mask",
        "purpose": "Acceptance smoke custom block.",
        "function_name": "apply_custom_block",
        "input_schema": {"columns": ["ts_code", "trade_date", "operator_value", "is_tradable"]},
        "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
        "required_fields": ["is_tradable"],
        "forbidden_patterns": [
            r"shift\s*\(\s*-\d+",
            r"\bfuture_return\b",
            r"\bnext_return\b",
            r"\blabel\b",
            r"\btarget\b",
        ],
        "source_code": source_code,
    }
    block["custom_block_hash"] = custom_block_hash(block)
    custom_hash = stable_hash([{"name": block["name"], "custom_block_hash": block["custom_block_hash"]}])
    boundary = {
        "operator_outputs": ["operator_value"],
        "custom_inputs": ["ts_code", "trade_date", "operator_value", "is_tradable"],
        "custom_outputs": ["factor_value"],
        "protected_operator_outputs": ["operator_value"],
        "allow_operator_output_overwrite": False,
    }
    hybrid_hash = stable_hash({
        "formula_hash": ir.get("formula_hash"),
        "custom_block_hash": custom_hash,
        "boundary": boundary,
    })
    implementation_contract = {
        "mode": "hybrid",
        "hybrid_contract_version": "factorforge_hybrid_contract_v1",
        "operator_subgraph": {
            "formula_text": formula,
            "formula_ir_version": ir.get("formula_ir_version"),
            "formula_ir": ir,
            "operator_set": ir.get("operator_set") or [],
            "required_fields": ir.get("required_fields") or [],
            "resolved_fields": ir.get("resolved_fields") or {},
            "formula_hash": ir.get("formula_hash"),
        },
        "custom_blocks": [block],
        "boundary": boundary,
        "formula_hash": ir.get("formula_hash"),
        "custom_block_hash": custom_hash,
        "hybrid_hash": hybrid_hash,
    }
    canonical_spec = {
        "formula_text": formula,
        "formula_ir": ir,
        "custom_blocks": [block],
        "required_inputs": ["close", "is_tradable"],
        "operators": ir.get("operator_set") or [],
    }
    fields = base_research_fields(factor_id)
    master = {
        "report_id": report_id,
        "factor_id": factor_id,
        "source_type": SOURCE_TYPES["hybrid"],
        "producer": PRODUCERS["hybrid"],
        "upstream_producer": PRODUCERS["hybrid"],
        "contract_version": CONTRACT_VERSION,
        "implementation_mode": "hybrid",
        "canonical_spec": canonical_spec,
        "implementation_contract": implementation_contract,
        **fields,
    }
    spec_hash = build_spec_hash(master)
    master["artifact_identity"] = build_artifact_identity(
        report_id=report_id,
        factor_id=factor_id,
        source_type=master["source_type"],
        implementation_mode="hybrid",
        contract_version=CONTRACT_VERSION,
        producer=master["producer"],
        upstream_producer=master["upstream_producer"],
        spec_hash=spec_hash,
        branch_id=BRANCH_ID,
        run_id=run_id,
        artifact_role="factor_spec_master",
        formula_hash=ir.get("formula_hash"),
        custom_block_hash=custom_hash,
        hybrid_hash=hybrid_hash,
    )
    master["spec_hash"] = spec_hash
    master["formula_hash"] = ir.get("formula_hash")
    master["custom_block_hash"] = custom_hash
    master["hybrid_hash"] = hybrid_hash
    return master


def build_direct_code_spec(report_id: str, factor_id: str, *, source_code: str, run_id: str) -> dict[str, Any]:
    code_contract = {
        "code_contract_version": "factorforge_direct_code_contract_v1",
        "function_name": "compute_factor",
        "input_schema": {"daily_df": ["ts_code", "trade_date", "open", "close"]},
        "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
        "required_fields": ["open", "close"],
        "information_set_rules": ["no future fields"],
        "forbidden_patterns": [
            r"shift\s*\(\s*-\d+",
            r"\bfuture_return\b",
            r"\bnext_return\b",
            r"\blabel\b",
            r"\btarget\b",
            r"\bfuture_",
            r"\blookahead\b",
        ],
        "source_code": source_code,
    }
    implementation_contract = {
        "mode": "direct_code",
        "code_contract": code_contract,
    }
    canonical_spec = {
        "source_code": source_code,
        "required_inputs": ["open", "close"],
        "formula_text": "direct_code_contract",
    }
    fields = base_research_fields(factor_id)
    master = {
        "report_id": report_id,
        "factor_id": factor_id,
        "source_type": SOURCE_TYPES["direct_code"],
        "producer": PRODUCERS["direct_code"],
        "upstream_producer": PRODUCERS["direct_code"],
        "contract_version": CONTRACT_VERSION,
        "implementation_mode": "direct_code",
        "canonical_spec": canonical_spec,
        "implementation_contract": implementation_contract,
        **fields,
    }
    code_contract_hash = stable_hash(code_contract)
    code_hash = hashlib.sha256(annotate_for_step3b_hash(source_code, report_id, factor_id).encode("utf-8")).hexdigest()
    spec_hash = build_spec_hash(master)
    master["artifact_identity"] = build_artifact_identity(
        report_id=report_id,
        factor_id=factor_id,
        source_type=master["source_type"],
        implementation_mode="direct_code",
        contract_version=CONTRACT_VERSION,
        producer=master["producer"],
        upstream_producer=master["upstream_producer"],
        spec_hash=spec_hash,
        branch_id=BRANCH_ID,
        run_id=run_id,
        artifact_role="factor_spec_master",
        code_contract_hash=code_contract_hash,
        code_hash=code_hash,
    )
    master["spec_hash"] = spec_hash
    master["code_contract_hash"] = code_contract_hash
    master["code_hash"] = code_hash
    return master


def ultimate_command(factorforge_root: Path, report_id: str, start_step: str, end_step: str, proof_path: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--factorforge-root",
        str(factorforge_root),
        "--report-id",
        report_id,
        "--start-step",
        start_step,
        "--end-step",
        end_step,
        "--skip-researcher-packets",
        "--proof-output",
        str(proof_path),
    ]


def validator_result_from_proof(proof_path: Path) -> dict[str, Any]:
    if not proof_path.exists():
        return {"status": "missing_proof"}
    try:
        proof = load_json(proof_path)
    except Exception as exc:
        return {"status": "unreadable_proof", "error": str(exc)}
    commands = proof.get("commands") or []
    validators = [cmd for cmd in commands if str(cmd.get("name") or "").startswith("validate_")]
    if validators:
        item = validators[-1]
        return {
            "status": item.get("status"),
            "name": item.get("name"),
            "rc": item.get("returncode"),
            "stdout_tail": tail(item.get("stdout_tail") or "", 2000),
            "stderr_tail": tail(item.get("stderr_tail") or "", 2000),
        }
    if commands:
        item = commands[-1]
        return {
            "status": "not_run_due_to_prior_failure",
            "last_command": item.get("name"),
            "last_rc": item.get("returncode"),
        }
    return {"status": "no_commands"}


@dataclass(frozen=True)
class Expected:
    result: str
    token: str | None = None


def classify_result(run: dict[str, Any], expected: Expected, proof_path: Path) -> dict[str, Any]:
    text = (run.get("stdout_tail") or "") + "\n" + (run.get("stderr_tail") or "")
    if proof_path.exists():
        try:
            text += "\n" + json.dumps(load_json(proof_path), ensure_ascii=False)
        except Exception:
            pass
    if expected.result == "PASS":
        ok = run["rc"] == 0
    else:
        ok = run["rc"] != 0 and (expected.token is None or expected.token in text)
    return {
        "status": "PASS" if ok else "FAIL",
        "observed_rc": run["rc"],
        "matched_expected_token": bool(expected.token and expected.token in text),
    }


def finalize_case(
    *,
    case_name: str,
    report_id: str | None,
    factorforge_root: Path,
    run: dict[str, Any],
    expected: Expected,
    proof_path: Path | None,
    started_epoch: float,
    extra_actual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proof = proof_path or Path("")
    actual = classify_result(run, expected, proof) if proof_path else {
        "status": "PASS" if (run["rc"] == 0 if expected.result == "PASS" else run["rc"] != 0) else "FAIL",
        "observed_rc": run["rc"],
        "matched_expected_token": None,
    }
    if expected.result == "BLOCK" and report_id:
        block_artifacts = block_artifact_observation(factorforge_root, report_id)
        actual["block_artifact_observation"] = block_artifacts
        if block_artifacts["factor_values_exist"] or block_artifacts["unexpected_writeback_exists"]:
            actual["status"] = "FAIL"
    if extra_actual:
        actual.update(extra_actual)
    pollution = repo_canonical_pollution(started_epoch)
    if not pollution["clean"]:
        actual["status"] = "FAIL"
    return {
        "case": case_name,
        "report_id": report_id,
        "command": run.get("command_string"),
        "rc": run.get("rc"),
        "stdout_tail": run.get("stdout_tail"),
        "stderr_tail": run.get("stderr_tail"),
        "expected_result": {
            "result": expected.result,
            "required_token": expected.token,
        },
        "actual_result": actual,
        "proof_path": str(proof_path) if proof_path else None,
        "validator_result": validator_result_from_proof(proof) if proof_path else {"status": "not_applicable"},
        "canonical_pollution_result": pollution,
        "factorforge_root": str(factorforge_root),
    }


def block_artifact_observation(root: Path, report_id: str) -> dict[str, Any]:
    factor_values = [
        root / "runs" / report_id / f"factor_values__{report_id}.parquet",
        root / "runs" / report_id / f"factor_values__{report_id}.csv",
    ]
    unexpected_writebacks = [
        root / "archive" / report_id,
        root / "objects" / "factor_library_all" / f"factor_record__{report_id}.json",
        root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json",
        root / "objects" / "research_knowledge_base" / f"knowledge_record__{report_id}.json",
        root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json",
    ]
    return {
        "factor_values_exist": any(path.exists() for path in factor_values),
        "factor_values_paths": [str(path) for path in factor_values if path.exists()],
        "unexpected_writeback_exists": any(path.exists() for path in unexpected_writebacks),
        "unexpected_writeback_paths": [str(path) for path in unexpected_writebacks if path.exists()],
    }


def case_step3b_operator_alpha013(root: Path, summaries: Path) -> dict[str, Any]:
    case = "operator_alpha013"
    rid = "SMOKE_OPERATOR_ALPHA013"
    run_id = f"{rid}__run"
    fixture = root / "synthetic_inputs" / f"{rid}.csv"
    make_fixture_csv(fixture)
    spec = build_operator_spec(
        rid,
        "Alpha013",
        "(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))",
        run_id=run_id,
    )
    write_common_objects(root, rid, spec, data_prep_payload(rid, "Alpha013", fixture))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("PASS"), proof_path=proof, started_epoch=started)


def case_unsupported_operator(root: Path, summaries: Path) -> dict[str, Any]:
    case = "unsupported_operator_block"
    rid = "SMOKE_UNSUPPORTED_OPERATOR"
    spec = build_operator_spec(rid, "UnsupportedOperator", "unknown_operator(high, 3)", run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "UnsupportedOperator", None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_UNSUPPORTED_FORMULA_SYNTAX"), proof_path=proof, started_epoch=started)


SAFE_HYBRID_BLOCK = """def apply_custom_block(operator_df, daily_df):
    merged = operator_df.merge(
        daily_df[["ts_code", "trade_date", "is_tradable"]],
        on=["ts_code", "trade_date"],
        how="left",
    )
    out = merged[["ts_code", "trade_date"]].copy()
    out["factor_value"] = merged["operator_value"].where(merged["is_tradable"].fillna(0).astype(bool))
    return out
"""


LEAKY_HYBRID_BLOCK = """def apply_custom_block(operator_df, daily_df):
    merged = operator_df.merge(daily_df[["ts_code", "trade_date"]], on=["ts_code", "trade_date"], how="left")
    out = merged[["ts_code", "trade_date"]].copy()
    out["factor_value"] = daily_df["future_return"].shift(-1)
    return out
"""


OVERWRITE_HYBRID_BLOCK = """def apply_custom_block(operator_df, daily_df):
    merged = operator_df.merge(
        daily_df[["ts_code", "trade_date", "is_tradable"]],
        on=["ts_code", "trade_date"],
        how="left",
    )
    merged["operator_value"] = 0.0
    out = merged[["ts_code", "trade_date"]].copy()
    out["factor_value"] = merged["operator_value"]
    return out
"""


def case_hybrid_safe(root: Path, summaries: Path) -> dict[str, Any]:
    case = "hybrid_safe"
    rid = "SMOKE_HYBRID_SAFE"
    fixture = root / "synthetic_inputs" / f"{rid}.csv"
    make_fixture_csv(fixture)
    spec = build_hybrid_spec(rid, "HybridSafe", source_code=SAFE_HYBRID_BLOCK, run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "HybridSafe", fixture))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("PASS"), proof_path=proof, started_epoch=started)


def case_hybrid_leakage(root: Path, summaries: Path) -> dict[str, Any]:
    case = "hybrid_leakage_block"
    rid = "SMOKE_HYBRID_LEAKAGE"
    spec = build_hybrid_spec(rid, "HybridLeakage", source_code=LEAKY_HYBRID_BLOCK, run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "HybridLeakage", None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_HYBRID_CUSTOM_BLOCK_LEAKAGE_PATTERN"), proof_path=proof, started_epoch=started)


def case_hybrid_overwrite(root: Path, summaries: Path) -> dict[str, Any]:
    case = "hybrid_overwrite_block"
    rid = "SMOKE_HYBRID_OVERWRITE"
    spec = build_hybrid_spec(rid, "HybridOverwrite", source_code=OVERWRITE_HYBRID_BLOCK, run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "HybridOverwrite", None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_HYBRID_OPERATOR_OUTPUT_OVERWRITE"), proof_path=proof, started_epoch=started)


def case_hybrid_hash_mismatch(root: Path, summaries: Path, *, case: str, rid: str, mismatch: str) -> dict[str, Any]:
    spec = build_hybrid_spec(rid, f"Hybrid{mismatch.title()}Mismatch", source_code=SAFE_HYBRID_BLOCK, run_id=f"{rid}__run")
    bad = f"bad_{mismatch}_hash_for_acceptance"
    if mismatch == "formula":
        spec["implementation_contract"]["formula_hash"] = bad
        spec["artifact_identity"]["formula_hash"] = bad
    elif mismatch == "custom":
        spec["implementation_contract"]["custom_blocks"][0]["custom_block_hash"] = bad
        spec["implementation_contract"]["custom_block_hash"] = bad
        spec["artifact_identity"]["custom_block_hash"] = bad
    elif mismatch == "hybrid":
        spec["implementation_contract"]["hybrid_hash"] = bad
        spec["artifact_identity"]["hybrid_hash"] = bad
    else:
        raise ValueError(mismatch)
    write_common_objects(root, rid, spec, data_prep_payload(rid, spec["factor_id"], None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_HYBRID_HASH_MISMATCH"), proof_path=proof, started_epoch=started)


def case_hybrid_formula_hash_mismatch(root: Path, summaries: Path) -> dict[str, Any]:
    return case_hybrid_hash_mismatch(root, summaries, case="hybrid_formula_hash_mismatch_block", rid="SMOKE_HYBRID_FORMULA_HASH_MISMATCH", mismatch="formula")


def case_hybrid_custom_hash_mismatch(root: Path, summaries: Path) -> dict[str, Any]:
    return case_hybrid_hash_mismatch(root, summaries, case="hybrid_custom_hash_mismatch_block", rid="SMOKE_HYBRID_CUSTOM_HASH_MISMATCH", mismatch="custom")


def case_hybrid_hybrid_hash_mismatch(root: Path, summaries: Path) -> dict[str, Any]:
    return case_hybrid_hash_mismatch(root, summaries, case="hybrid_hybrid_hash_mismatch_block", rid="SMOKE_HYBRID_HYBRID_HASH_MISMATCH", mismatch="hybrid")


SAFE_DIRECT_CODE = """from __future__ import annotations

def compute_factor(daily_df, minute_df=None):
    out = daily_df[["ts_code", "trade_date"]].copy()
    out["factor_value"] = daily_df["close"] / daily_df["open"] - 1.0
    return out
"""


UNSAFE_DIRECT_CODE = """from __future__ import annotations

def compute_factor(daily_df, minute_df=None):
    out = daily_df[["ts_code", "trade_date"]].copy()
    out["factor_value"] = daily_df["future_return"].shift(-1)
    return out
"""


def unsafe_direct_code_for_column(column: str) -> str:
    return f'''from __future__ import annotations

def compute_factor(daily_df, minute_df=None):
    out = daily_df[["ts_code", "trade_date"]].copy()
    out["factor_value"] = daily_df["{column}"]
    return out
'''


def case_direct_code_safe(root: Path, summaries: Path) -> dict[str, Any]:
    case = "direct_code_safe"
    rid = "SMOKE_DIRECT_CODE_SAFE"
    spec = build_direct_code_spec(rid, "DirectCodeSafe", source_code=SAFE_DIRECT_CODE, run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "DirectCodeSafe", None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("PASS"), proof_path=proof, started_epoch=started)


def case_direct_code_future_return_shift(root: Path, summaries: Path) -> dict[str, Any]:
    case = "direct_code_future_return_shift_block"
    rid = "SMOKE_DIRECT_CODE_UNSAFE"
    spec = build_direct_code_spec(rid, "DirectCodeUnsafe", source_code=UNSAFE_DIRECT_CODE, run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, "DirectCodeUnsafe", None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_DIRECT_CODE_LEAKAGE_PATTERN"), proof_path=proof, started_epoch=started)


def case_direct_code_forbidden_column(root: Path, summaries: Path, *, case: str, rid: str, column: str) -> dict[str, Any]:
    spec = build_direct_code_spec(rid, f"DirectCode{column.title().replace('_', '')}", source_code=unsafe_direct_code_for_column(column), run_id=f"{rid}__run")
    write_common_objects(root, rid, spec, data_prep_payload(rid, spec["factor_id"], None))
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "3b", "3b", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "BLOCK_DIRECT_CODE_LEAKAGE_PATTERN"), proof_path=proof, started_epoch=started)


def case_direct_code_label(root: Path, summaries: Path) -> dict[str, Any]:
    return case_direct_code_forbidden_column(root, summaries, case="direct_code_label_block", rid="SMOKE_DIRECT_CODE_LABEL", column="label")


def case_direct_code_target(root: Path, summaries: Path) -> dict[str, Any]:
    return case_direct_code_forbidden_column(root, summaries, case="direct_code_target_block", rid="SMOKE_DIRECT_CODE_TARGET", column="target")


def case_direct_code_next_return(root: Path, summaries: Path) -> dict[str, Any]:
    return case_direct_code_forbidden_column(root, summaries, case="direct_code_next_return_block", rid="SMOKE_DIRECT_CODE_NEXT_RETURN", column="next_return")


def case_step4_all_skipped(root: Path, summaries: Path) -> dict[str, Any]:
    case = "step4_all_skipped_block"
    rid = "SMOKE_STEP4_ALL_SKIPPED"
    spec = build_operator_spec(rid, "Step4Skipped", "rank(high)", run_id=f"{rid}__run")
    prep = data_prep_payload(rid, "Step4Skipped", None)
    write_common_objects(root, rid, spec, prep)
    write_json(root / "objects" / "handoff" / f"handoff_to_step4__{rid}.json", {
        "report_id": rid,
        "factor_id": "Step4Skipped",
        "artifact_identity": {**spec["artifact_identity"], "artifact_role": "handoff_to_step4", "producer": "acceptance_smoke_fixture"},
        "implementation_mode": "operator",
        "step3b_ready": False,
        "execution_mode": "operator",
        "local_input_paths": {},
        "first_run_outputs": {"status": "pending", "no_first_run_reason": "acceptance_missing_factor_values"},
        "evaluation_plan": {"backends": [{"name": "self_quant_analyzer", "mode": "quick"}, {"name": "qlib_backtest", "mode": "default"}]},
    })
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "4", "4", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    validation_path = root / "objects" / "validation" / f"factor_run_validation_revision__{rid}.json"
    issue_codes: list[str] = []
    if validation_path.exists():
        issue_codes = [str(item.get("code")) for item in (load_json(validation_path).get("issues") or []) if isinstance(item, dict)]
    result = finalize_case(
        case_name=case,
        report_id=rid,
        factorforge_root=root,
        run=run,
        expected=Expected("BLOCK", "RESULT: FAIL"),
        proof_path=proof,
        started_epoch=started,
        extra_actual={"step4_issue_codes": issue_codes},
    )
    if "BLOCK_NO_SUCCESSFUL_BACKEND" in issue_codes and result["rc"] != 0 and result["canonical_pollution_result"]["clean"]:
        result["actual_result"]["status"] = "PASS"
    return result


def factor_run_master(root: Path, report_id: str, factor_id: str, *, run_id: str, bad: bool = True) -> dict[str, Any]:
    spec = build_operator_spec(report_id, factor_id, "rank(high)", run_id=run_id)
    write_common_objects(root, report_id, spec, data_prep_payload(report_id, factor_id, None))
    identity = {**spec["artifact_identity"], "artifact_role": "factor_run_master", "producer": "acceptance_smoke_fixture"}
    return {
        "report_id": report_id,
        "factor_id": factor_id,
        "artifact_identity": identity,
        "producer": "acceptance_smoke_fixture",
        "run_status": "failed" if bad else "success",
        "can_enter_step5": False if bad else True,
        "output_paths": [],
        "evaluation_results": {
            "backend_runs": [
                {"backend": "self_quant_analyzer", "status": "skipped", "payload_path": None},
                {"backend": "qlib_backtest", "status": "skipped", "payload_path": None},
            ]
        },
        "implementation_mode_decision": {},
        "diagnostic_summary": {"row_count": 0, "date_count": 0, "ticker_count": 0},
    }


def case_step5_bad_provenance(root: Path, summaries: Path) -> dict[str, Any]:
    case = "step5_bad_provenance_no_archive"
    rid = "SMOKE_STEP5_BAD_PROVENANCE"
    frm = factor_run_master(root, rid, "Step5Bad", run_id=f"{rid}__run", bad=True)
    write_json(root / "objects" / "factor_run_master" / f"factor_run_master__{rid}.json", frm)
    write_json(root / "objects" / "handoff" / f"handoff_to_step5__{rid}.json", {
        "report_id": rid,
        "factor_id": "Step5Bad",
        "factor_run_master_path": str(root / "objects" / "factor_run_master" / f"factor_run_master__{rid}.json"),
        "artifact_identity": {**frm["artifact_identity"], "artifact_role": "handoff_to_step5", "producer": "acceptance_smoke_fixture"},
    })
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "5", "5", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    archive_dir = root / "archive" / rid
    case_path = root / "objects" / "factor_case_master" / f"factor_case_master__{rid}.json"
    extra = {
        "archive_created": archive_dir.exists(),
        "archive_output_absent": not archive_dir.exists(),
        "handoff_to_step6_exists": (root / "objects" / "handoff" / f"handoff_to_step6__{rid}.json").exists(),
        "handoff_to_step6_absent": not (root / "objects" / "handoff" / f"handoff_to_step6__{rid}.json").exists(),
        "case_path_exists": case_path.exists(),
        "case_final_status": load_json(case_path).get("final_status") if case_path.exists() else None,
        "case_archive_status": load_json(case_path).get("archive_status") if case_path.exists() else None,
        "prewrite_diagnostic_exists": (root / "objects" / "validation" / f"step5_prewrite_block__{rid}.json").exists(),
    }
    result = finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("BLOCK", "STEP5_PREWRITE_BLOCK"), proof_path=proof, started_epoch=started, extra_actual=extra)
    if not extra["handoff_to_step6_absent"] or not extra["archive_output_absent"]:
        result["actual_result"]["status"] = "FAIL"
    if extra["case_path_exists"] and not (extra["case_final_status"] == "failed" and extra["case_archive_status"] == "skipped"):
        result["actual_result"]["status"] = "FAIL"
    return result


def case_step6_bad_provenance(root: Path, summaries: Path) -> dict[str, Any]:
    case = "step6_bad_provenance_no_writeback"
    rid = "SMOKE_STEP6_BAD_PROVENANCE"
    frm = factor_run_master(root, rid, "Step6Bad", run_id=f"{rid}__run", bad=True)
    case_identity = {**frm["artifact_identity"], "artifact_role": "factor_case_master", "producer": "acceptance_smoke_fixture"}
    bad_case = {
        "report_id": rid,
        "factor_id": "Step6Bad",
        "final_status": "failed",
        "artifact_identity": case_identity,
        "evidence_identity": {},
        "implementation_mode_decision": {},
        "evidence_quality": {
            "identity_chain_verified": False,
            "mode_decision_present": False,
            "self_quant_required_and_present": False,
            "long_side_metrics_present": False,
            "step4_has_successful_backend": False,
        },
    }
    evaluation = {
        "report_id": rid,
        "factor_id": "Step6Bad",
        "evaluation_status": "failed",
        "artifact_identity": {**frm["artifact_identity"], "artifact_role": "factor_evaluation", "producer": "acceptance_smoke_fixture"},
        "evidence_identity": {},
        "backend_summary": [],
        "evidence_quality": bad_case["evidence_quality"],
    }
    write_json(root / "objects" / "factor_run_master" / f"factor_run_master__{rid}.json", frm)
    write_json(root / "objects" / "factor_case_master" / f"factor_case_master__{rid}.json", bad_case)
    write_json(root / "objects" / "validation" / f"factor_evaluation__{rid}.json", evaluation)
    write_json(root / "objects" / "handoff" / f"handoff_to_step6__{rid}.json", {
        "report_id": rid,
        "factor_id": "Step6Bad",
        "artifact_identity": {**case_identity, "artifact_role": "handoff_to_step6", "producer": "acceptance_smoke_fixture"},
        "evidence_identity": {},
        "implementation_mode_decision": {},
        "factor_case_master_path": str(root / "objects" / "factor_case_master" / f"factor_case_master__{rid}.json"),
        "factor_evaluation_path": str(root / "objects" / "validation" / f"factor_evaluation__{rid}.json"),
    })
    proof = summaries / "proofs" / f"{case}.json"
    cmd = ultimate_command(root, rid, "6", "6", proof)
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    text = (run.get("stdout_tail") or "") + "\n" + (run.get("stderr_tail") or "")
    extra = {
        "research_iteration_exists": (root / "objects" / "research_iteration_master" / f"research_iteration_master__{rid}.json").exists(),
        "handoff_to_step3b_exists": (root / "objects" / "handoff" / f"handoff_to_step3b__{rid}.json").exists(),
        "library_all_exists": (root / "objects" / "factor_library_all" / f"factor_record__{rid}.json").exists(),
        "library_official_exists": (root / "objects" / "factor_library_official" / f"factor_record__{rid}.json").exists(),
        "knowledge_exists": (root / "objects" / "research_knowledge_base" / f"knowledge_record__{rid}.json").exists(),
        "prewrite_diagnostic_exists": (root / "objects" / "validation" / f"step6_prewrite_block__{rid}.json").exists(),
        "awaiting_main_agent_mechanism_memo": "AWAITING_MAIN_AGENT_MECHANISM_MEMO" in text,
    }
    result = finalize_case(case_name=case, report_id=rid, factorforge_root=root, run=run, expected=Expected("PASS"), proof_path=proof, started_epoch=started, extra_actual=extra)
    forbidden = [
        "research_iteration_exists",
        "handoff_to_step3b_exists",
        "library_all_exists",
        "library_official_exists",
        "knowledge_exists",
    ]
    if any(extra[key] for key in forbidden) or not extra["awaiting_main_agent_mechanism_memo"]:
        result["actual_result"]["status"] = "FAIL"
    return result


def case_installed_cmp(root: Path, summaries: Path) -> dict[str, Any]:
    case = "installed_cmp"
    installed_raw = os.environ.get("FACTORFORGE_INSTALLED_SKILLS_ROOT")
    if installed_raw:
        installed_root = Path(installed_raw).expanduser()
    else:
        ec2_skill_root = Path("/home/ubuntu/.openclaw/workspace/skills")
        installed_root = ec2_skill_root if ec2_skill_root.exists() else Path.home() / ".codex" / "skills"
    pairs = [
        ("skills/factor-forge-step2/scripts/run_step2.py", str(installed_root / "factor-forge-step2" / "scripts" / "run_step2.py")),
        ("skills/factor-forge-step2/scripts/validate_step2.py", str(installed_root / "factor-forge-step2" / "scripts" / "validate_step2.py")),
        ("skills/factor-forge-step3/scripts/run_step3b.py", str(installed_root / "factor-forge-step3" / "scripts" / "run_step3b.py")),
        ("skills/factor-forge-step3/scripts/validate_step3b.py", str(installed_root / "factor-forge-step3" / "scripts" / "validate_step3b.py")),
        ("skills/factor-forge-step3/SKILL.md", str(installed_root / "factor-forge-step3" / "SKILL.md")),
    ]
    script = " && ".join(f"cmp {src} {dst}" for src, dst in pairs)
    cmd = ["bash", "-lc", script]
    started = time.time()
    run = run_capture(cmd, factorforge_root=root)
    return finalize_case(case_name=case, report_id=None, factorforge_root=root, run=run, expected=Expected("PASS"), proof_path=None, started_epoch=started, extra_actual={"cmp_pairs": pairs})


CASE_FUNCS = {
    "operator_alpha013": case_step3b_operator_alpha013,
    "unsupported_operator_block": case_unsupported_operator,
    "hybrid_safe": case_hybrid_safe,
    "hybrid_leakage_block": case_hybrid_leakage,
    "hybrid_overwrite_block": case_hybrid_overwrite,
    "hybrid_formula_hash_mismatch_block": case_hybrid_formula_hash_mismatch,
    "hybrid_custom_hash_mismatch_block": case_hybrid_custom_hash_mismatch,
    "hybrid_hybrid_hash_mismatch_block": case_hybrid_hybrid_hash_mismatch,
    "direct_code_safe": case_direct_code_safe,
    "direct_code_future_return_shift_block": case_direct_code_future_return_shift,
    "direct_code_label_block": case_direct_code_label,
    "direct_code_target_block": case_direct_code_target,
    "direct_code_next_return_block": case_direct_code_next_return,
    "step4_all_skipped_block": case_step4_all_skipped,
    "step5_bad_provenance_no_archive": case_step5_bad_provenance,
    "step6_bad_provenance_no_writeback": case_step6_bad_provenance,
    "installed_cmp": case_installed_cmp,
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Factor Forge acceptance smoke in an isolated /tmp FACTORFORGE_ROOT.")
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--summary-output", default=None)
    ap.add_argument("--cases", nargs="*", choices=sorted(CASE_FUNCS), default=list(CASE_FUNCS))
    ap.add_argument("--fresh", action="store_true", help="Remove the chosen /tmp smoke root before running.")
    ap.add_argument("--allow-non-tmp-root", action="store_true", help="Debug only. Runs are not acceptance eligible.")
    return ap.parse_args()


def verdict_for_cases(cases: list[dict[str, Any]]) -> str:
    if any(not item["canonical_pollution_result"]["clean"] for item in cases):
        return "BLOCK"
    failed = [item for item in cases if item["actual_result"].get("status") != "PASS"]
    if not failed:
        return "ACCEPT"
    return "BLOCK"


def is_tmp_acceptance_root(root: Path) -> bool:
    text = str(root)
    return text == "/tmp" or text.startswith("/tmp/")


def main() -> int:
    args = parse_args()
    root = Path(args.factorforge_root or f"/tmp/factorforge_acceptance_{timestamp()}").expanduser()
    root_policy = {
        "factorforge_root": str(root),
        "is_tmp": is_tmp_acceptance_root(root),
        "enforced": True,
        "allow_non_tmp_root": bool(args.allow_non_tmp_root),
    }
    acceptance_eligible = root_policy["is_tmp"] and not args.allow_non_tmp_root
    if not root_policy["is_tmp"] and not args.allow_non_tmp_root:
        summary_path = (
            Path(args.summary_output).expanduser()
            if args.summary_output
            else Path(f"/tmp/factorforge_acceptance_root_policy_block_{timestamp()}.json")
        )
        summary = {
            "contract_version": "factorforge_acceptance_smoke_v1",
            "factorforge_root": str(root),
            "repo_root": str(REPO_ROOT),
            "started_at_utc": utc_now(),
            "finished_at_utc": utc_now(),
            "cases": [],
            "verdict": "BLOCK",
            "acceptance_eligible": False,
            "root_policy": root_policy,
            "failure": "BLOCK_NON_TMP_FACTORFORGE_ROOT",
            "policy": {
                "formal_entrypoint": "scripts/run_factorforge_ultimate.py",
                "clean_data_processed": False,
                "production_factor_run": False,
            },
        }
        write_json(summary_path, summary)
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT: acceptance smoke requires /tmp FACTORFORGE_ROOT")
        print(f"[SUMMARY] {summary_path}")
        print("[VERDICT] BLOCK")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    summaries = root / "acceptance_summaries"
    summaries.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary_output).expanduser().resolve() if args.summary_output else summaries / "acceptance_summary.json"
    harness_started_epoch = time.time()

    results: list[dict[str, Any]] = []
    for name in args.cases:
        try:
            result = CASE_FUNCS[name](root, summaries)
        except Exception as exc:
            pollution = repo_canonical_pollution(harness_started_epoch)
            result = {
                "case": name,
                "report_id": None,
                "command": None,
                "rc": None,
                "stdout_tail": "",
                "stderr_tail": repr(exc),
                "expected_result": {},
                "actual_result": {"status": "FAIL", "exception": repr(exc)},
                "proof_path": None,
                "validator_result": {"status": "not_run"},
                "canonical_pollution_result": pollution,
                "factorforge_root": str(root),
            }
        results.append(result)
        write_json(summaries / "cases" / f"{name}.json", result)
        print(f"[CASE] {name} status={result['actual_result'].get('status')} rc={result.get('rc')}")

    verdict = verdict_for_cases(results)
    if not acceptance_eligible:
        verdict = "BLOCK"
    summary = {
        "contract_version": "factorforge_acceptance_smoke_v1",
        "factorforge_root": str(root),
        "repo_root": str(REPO_ROOT),
        "started_at_utc": datetime.fromtimestamp(harness_started_epoch, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "finished_at_utc": utc_now(),
        "cases": results,
        "case_summary_dir": str(summaries / "cases"),
        "verdict": verdict,
        "acceptance_eligible": acceptance_eligible,
        "root_policy": root_policy,
        "canonical_pollution_result": repo_canonical_pollution(harness_started_epoch),
        "policy": {
            "formal_entrypoint": "scripts/run_factorforge_ultimate.py",
            "clean_data_processed": False,
            "production_factor_run": False,
        },
    }
    write_json(summary_path, summary)
    print(f"[SUMMARY] {summary_path}")
    print(f"[VERDICT] {verdict}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
