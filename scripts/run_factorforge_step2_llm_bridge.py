#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BLOCK_PROVIDER = "BLOCK_STEP2_LLM_PROVIDER_UNAVAILABLE"
BLOCK_PROVIDER_FAILED = "BLOCK_STEP2_LLM_PROVIDER_FAILED"
VERSION = "factorforge_step2_llm_bridge_v1"
BLOCK_STEP1_CONTEXT = "BLOCK_STEP2_STEP1_CONTEXT_REQUIRED"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def source_context(root: Path, report_id: str) -> dict[str, Any]:
    aim = read_json_if_exists(root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json")
    raw_step1 = root / "objects" / "raw_llm" / report_id / "step1"
    chief = read_json_if_exists(raw_step1 / "step1_chief_raw.json")
    primary = read_json_if_exists(raw_step1 / "step1_primary_raw.json")
    challenger = read_json_if_exists(raw_step1 / "step1_challenger_raw.json")
    return {
        "alpha_idea_master_present": bool(aim),
        "alpha_idea_master": aim,
        "step1_raw_present": bool(primary and challenger and chief),
        "step1_primary_raw": primary,
        "step1_challenger_raw": challenger,
        "step1_chief_raw": chief,
    }


def fixture_primary(report_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
    required_inputs = ["close", "volume", "amount", "total_mv", "ret20", "vol20", "turn20"]
    return {
        "report_id": report_id,
        "factor_id": "CPV",
        "route": "primary",
        "raw_formula_text": "CPV = zscore(mean(corr(minute_close, minute_volume), 20)) + zscore(trend(corr(minute_close, minute_volume), 20))",
        "operators": ["corr", "mean", "std", "trend", "zscore", "neutralize"],
        "required_inputs": required_inputs,
        "implementation_mode": "direct_code",
        "implementation_contract": {
            "implementation_mode": "direct_code",
            "required_fields": required_inputs,
            "function_name": "compute_factor",
            "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
        },
        "mechanism_math_contract": fixture_mechanism_math_contract(),
        "time_series_steps": [
            "daily intraday price-volume correlation",
            "20-day rolling mean/std/trend over the correlation series",
        ],
        "cross_sectional_steps": ["neutralize market cap, Ret20, Turn20, Vol20", "cross-sectional zscore"],
        "preprocessing": ["exclude suspended and insufficient-history securities"],
        "normalization": ["cross-sectional zscore"],
        "neutralization": ["market cap", "Ret20", "Turn20", "Vol20"],
        "rebalance_frequency": "monthly",
        "explicit_items": ["price-volume correlation", "20-day rolling features"],
        "inferred_items": ["Pearson correlation assumed in fixture smoke"],
        "ambiguities": ["minute frequency and correlation type require production LLM confirmation"],
        "_llm_bridge_provenance": {**provenance, "role": "primary"},
    }


def fixture_mechanism_math_contract() -> dict[str, Any]:
    return {
        "contract_version": "factorforge_mechanism_math_contract_v1",
        "math_model_status": "specified",
        "model_family": "price_volume_microstructure",
        "math_toolkits": ["statistics", "microstructure_model", "time_series_and_filtering"],
        "economic_mechanism": "Price-volume dependence estimates crowding, attention, and transient impact decay.",
        "state_or_object": "intraday price-volume dependence state for each stock",
        "observable_inputs": ["close", "volume", "amount", "ret20", "vol20", "turn20"],
        "factor_as_estimator": "rolling estimator of price-volume correlation level, dispersion, and trend",
        "target_functional": "E[r_{i,t+1:t+h} | F_t, price_volume_dependence_state]",
        "process_hypothesis": "Crowded price-volume resonance decays or reverses when liquidity demand is exhausted.",
        "latent_state": "crowding and attention-pressure state",
        "observable_estimator": "20-day rolling mean, volatility, and trend of intraday price-volume correlation",
        "conditional_distribution_hypothesis": "future returns shift lower when resonance is high and transient impact is crowded",
        "relationship_shape": "monotone negative after neutralization of size and recent return controls",
        "monotonicity_claim": "higher CPV fixture values should not be promoted unless long-side evidence supports the declared direction",
        "information_set": {
            "filtration": "market data available up to the rebalance decision time",
            "uses_future_information": False,
            "lag_or_delay_required": "use only completed intraday and daily observations before rebalance",
            "notes": "fixture smoke only; production extraction must restate the report-specific filtration",
        },
        "necessary_conditions": [
            "price-volume dependence is not solely a data-cleaning artifact",
            "neutralization does not erase the economically relevant state",
        ],
        "expected_metric_signature": {
            "long_side": "risk-adjusted return improves for the economically favored side",
            "turnover": "turnover remains low enough for the signal horizon",
        },
        "metric_signature_match": "unknown_before_step4",
        "revision_operators": [
            {
                "operator_name": "adjust_dependence_window",
                "revision_target_math_object": "lag_window",
                "math_change": "change the rolling dependence window while preserving the same estimator family",
                "expected_effects": ["lower noise if the original window is too short", "slower reaction if too long"],
                "forbidden_interpretation": "do not repair by changing portfolio expression or short-leg adoption",
            }
        ],
        "falsification_tests": [
            "reject if dependence features have no stable relation to long-side risk-adjusted returns",
            "reject if evidence is explained by future leakage or data availability mismatch",
        ],
        "mechanism_falsification_tests": [
            "ablate the trend and dispersion components",
            "test whether the signal survives liquidity and volatility controls",
        ],
        "kill_criteria": [
            "validator detects future-looking fields",
            "Step4/5 evidence shows no defensible long-side signal after costs",
        ],
        "classification_evidence": {
            "formula_text": "corr(minute_close, minute_volume) rolling mean/std/trend",
            "reason": "fixture raw spec uses explicit price-volume correlation dependence",
        },
    }


def fixture_challenger(report_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
    payload = fixture_primary(report_id, provenance)
    payload["route"] = "challenger"
    payload["inferred_items"] = ["challenger fixture preserves ambiguity rather than resolving frequency"]
    payload["_llm_bridge_provenance"] = {**provenance, "role": "challenger"}
    return payload


def fixture_auditor(report_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "factor_id": "CPV",
        "consistency_score": 0.86,
        "matches_core_driver": True,
        "mismatch_points": [],
        "missing_steps": [],
        "distortion_risks": ["Fixture provider cannot replace production PDF extraction."],
        "recommendation": "proceed",
        "_llm_bridge_provenance": {**provenance, "role": "auditor"},
    }


def validate_raw(path: Path, required: list[str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parsed = False
    error = None
    try:
        payload = json.loads(text)
        parsed = all(payload.get(key) not in (None, "", []) for key in required)
    except Exception as exc:  # noqa: BLE001 - record raw validation status for audit.
        error = f"{type(exc).__name__}: {exc}"
    return {
        "path": str(path),
        "raw_response_sha256": sha256_text(text),
        "parsed_json_valid": parsed,
        "validation_error": error,
    }


def role_prompt(role: str) -> str:
    if role == "primary":
        return (
            "You are the Step2 primary spec extraction agent. Given Step1 context and the report provenance, "
            "extract factor_spec_raw JSON with report_id, factor_id, raw_formula_text or direct/hybrid contract, "
            "operators, required_inputs, implementation_mode, implementation_contract, ambiguities, and inferred_items. "
            "Select implementation_mode from the executable structure, not from source type. Choose hybrid only when "
            "you can provide a complete hybrid_contract with parseable operator_subgraph.formula_ir, nonempty custom_blocks, "
            "and formula/custom block identity. If the report describes a natural-language or custom smart-money calculation "
            "that cannot be represented as legal hybrid, choose direct_code and provide a direct_code implementation contract."
        )
    if role == "challenger":
        return (
            "You are the Step2 challenger spec extraction agent. Independently challenge the primary interpretation and "
            "output factor_spec_raw JSON with the same required fields, preserving disagreements and ambiguities. "
            "Do not default pdf_report to hybrid; require executable hybrid structure or use direct_code."
        )
    return (
        "You are the Step2 consistency auditor. Compare alpha_idea_master, primary factor_spec_raw, and challenger "
        "factor_spec_raw. Output JSON with report_id, factor_id, consistency_score, matches_core_driver, "
        "mismatch_points, missing_steps, distortion_risks, and recommendation."
    )


def run_command_provider(command: str, request: dict[str, Any]) -> str:
    proc = subprocess.run(
        shlex.split(command),
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{BLOCK_PROVIDER_FAILED}: role={request.get('role')} rc={proc.returncode} stderr={proc.stderr[-1000:]}")
    return proc.stdout.strip()


def write_command_failure_report(
    args: argparse.Namespace,
    root: Path,
    out_dir: Path,
    *,
    created_at_utc: str,
    role_paths: dict[str, Path],
    prompt_context_hash: str,
    failed_role: str,
    error: str,
) -> None:
    raw_outputs: dict[str, Any] = {}
    for role, path in role_paths.items():
        if not path.exists():
            continue
        if role == "auditor":
            required = ["report_id", "factor_id", "consistency_score", "recommendation"]
        else:
            required = ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]
        raw_outputs[role] = {
            **validate_raw(path, required),
            "prompt_name": f"step2_{role}_formal_extraction",
            "prompt_hash": sha256_text(role_prompt(role)),
        }
    write_json(
        out_dir / "step2_llm_bridge_report.json",
        {
            "version": VERSION,
            "report_id": args.report_id,
            "verdict": "BLOCK",
            "block_reason": f"{BLOCK_PROVIDER_FAILED}: role={failed_role}: {error}",
            "provider": "command",
            "model": os.getenv("FACTORFORGE_STEP2_LLM_MODEL", "external-command"),
            "temperature": os.getenv("FACTORFORGE_STEP2_LLM_TEMPERATURE", "provider_default"),
            "created_at_utc": created_at_utc,
            "fixture_only": False,
            "formal_llm_extraction": False,
            "input_context": {
                "factorforge_root": str(root),
                "prompt_context_hash": prompt_context_hash,
            },
            "raw_outputs": raw_outputs,
        },
    )


def build_command(args: argparse.Namespace, root: Path, out_dir: Path) -> dict[str, Any]:
    ctx = source_context(root, args.report_id)
    if not ctx["step1_raw_present"]:
        raise SystemExit(f"{BLOCK_STEP1_CONTEXT}: Step2 bridge requires Step1 context before formal extraction")
    command = os.getenv("FACTORFORGE_STEP2_LLM_COMMAND")
    if not command:
        raise SystemExit(f"{BLOCK_PROVIDER}: FACTORFORGE_STEP2_LLM_COMMAND is required for --provider command")

    created = now_utc()
    role_paths = {
        "primary": out_dir / "step2_primary_raw.json",
        "challenger": out_dir / "step2_challenger_raw.json",
        "auditor": out_dir / "step2_auditor_raw.json",
    }
    prior_outputs: dict[str, Any] = {}
    prompt_context_hash = stable_hash(ctx)
    for role in ["primary", "challenger", "auditor"]:
        prompt = role_prompt(role)
        prompt_name = f"step2_{role}_formal_extraction"
        request = {
            "version": VERSION,
            "role": role,
            "report_id": args.report_id,
            "factorforge_root": str(root),
            "prompt_name": prompt_name,
            "prompt_hash": sha256_text(prompt),
            "prompt": prompt,
            "step1_context": ctx,
            "prior_outputs": prior_outputs,
        }
        response_text = run_command_provider(command, request)
        path = role_paths[role]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response_text + "\n", encoding="utf-8")
        try:
            prior_outputs[role] = json.loads(response_text)
        except json.JSONDecodeError as exc:
            write_command_failure_report(
                args,
                root,
                out_dir,
                created_at_utc=created,
                role_paths=role_paths,
                prompt_context_hash=prompt_context_hash,
                failed_role=role,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise SystemExit(f"{BLOCK_PROVIDER_FAILED}: role={role} {type(exc).__name__}: {exc}") from exc

    return {
        "version": VERSION,
        "report_id": args.report_id,
        "provider": "command",
        "model": os.getenv("FACTORFORGE_STEP2_LLM_MODEL", "external-command"),
        "temperature": os.getenv("FACTORFORGE_STEP2_LLM_TEMPERATURE", "provider_default"),
        "created_at_utc": created,
        "fixture_only": False,
        "formal_llm_extraction": True,
        "input_context": {
            "alpha_idea_master_present": ctx["alpha_idea_master_present"],
            "step1_raw_present": ctx["step1_raw_present"],
            "prompt_context_hash": prompt_context_hash,
        },
        "raw_outputs": {
            "primary": {
                **validate_raw(role_paths["primary"], ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]),
                "prompt_name": "step2_primary_formal_extraction",
                "prompt_hash": sha256_text(role_prompt("primary")),
            },
            "challenger": {
                **validate_raw(role_paths["challenger"], ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]),
                "prompt_name": "step2_challenger_formal_extraction",
                "prompt_hash": sha256_text(role_prompt("challenger")),
            },
            "auditor": {
                **validate_raw(role_paths["auditor"], ["report_id", "factor_id", "consistency_score", "recommendation"]),
                "prompt_name": "step2_auditor_formal_extraction",
                "prompt_hash": sha256_text(role_prompt("auditor")),
            },
        },
    }


def build_fixture(args: argparse.Namespace, root: Path, out_dir: Path) -> dict[str, Any]:
    ctx = source_context(root, args.report_id)
    if not ctx["step1_raw_present"]:
        raise SystemExit(f"{BLOCK_STEP1_CONTEXT}: Step2 bridge requires Step1 context before fixture extraction")
    prompt_context_hash = stable_hash(ctx)
    created = now_utc()
    base_provenance = {
        "version": VERSION,
        "report_id": args.report_id,
        "provider": "fixture",
        "model": "fixture-step2-llm-bridge",
        "temperature": 0,
        "prompt_name": "step2_spec_extraction_fixture",
        "prompt_hash": prompt_context_hash,
        "created_at_utc": created,
        "fixture_only": True,
        "formal_production_provider": False,
        "alpha_idea_master_present": ctx["alpha_idea_master_present"],
        "step1_raw_present": ctx["step1_raw_present"],
    }
    primary_path = out_dir / "step2_primary_raw.json"
    challenger_path = out_dir / "step2_challenger_raw.json"
    auditor_path = out_dir / "step2_auditor_raw.json"
    write_json(primary_path, fixture_primary(args.report_id, base_provenance))
    write_json(challenger_path, fixture_challenger(args.report_id, base_provenance))
    write_json(auditor_path, fixture_auditor(args.report_id, base_provenance))
    return {
        "version": VERSION,
        "report_id": args.report_id,
        "provider": "fixture",
        "model": "fixture-step2-llm-bridge",
        "temperature": 0,
        "created_at_utc": created,
        "fixture_only": True,
        "formal_llm_extraction": False,
        "input_context": {
            "alpha_idea_master_present": ctx["alpha_idea_master_present"],
            "step1_raw_present": ctx["step1_raw_present"],
            "prompt_context_hash": prompt_context_hash,
        },
        "raw_outputs": {
            "primary": {
                **validate_raw(primary_path, ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]),
                "prompt_name": "step2_spec_extraction_fixture",
                "prompt_hash": prompt_context_hash,
            },
            "challenger": {
                **validate_raw(challenger_path, ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]),
                "prompt_name": "step2_challenger_spec_extraction_fixture",
                "prompt_hash": prompt_context_hash,
            },
            "auditor": {
                **validate_raw(auditor_path, ["report_id", "factor_id", "consistency_score", "recommendation"]),
                "prompt_name": "step2_consistency_auditor_fixture",
                "prompt_hash": prompt_context_hash,
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--factorforge-root")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--provider", default=os.getenv("FACTORFORGE_STEP2_LLM_PROVIDER"))
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()

    root = Path(args.factorforge_root or os.getenv("FACTORFORGE_ROOT") or REPO_ROOT).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    if args.provider not in {"fixture", "command"}:
        print(f"{BLOCK_PROVIDER}: configure a real Step2 LLM provider or use --provider fixture for smoke only", file=sys.stderr)
        return 1

    try:
        if args.provider == "command":
            report = build_command(args, root, out_dir)
        else:
            report = build_fixture(args, root, out_dir)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - provider bridge must report failure without writing success.
        print(f"{BLOCK_PROVIDER_FAILED}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_json(out_dir / "step2_llm_bridge_report.json", report)
    if args.write_report:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"RESULT: PASS step2 fixture raw outputs written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
