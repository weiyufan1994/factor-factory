#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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
PROVIDER_REQUEST_CONTRACT_VERSION = "factorforge_formal_llm_provider_request_v1"
BLOCK_STEP1_CONTEXT = "BLOCK_STEP2_STEP1_CONTEXT_REQUIRED"
BLOCK_DIRECT_CODE_RAW = "BLOCK_STEP2_LLM_DIRECT_CODE_SOURCE_CONTRACT_MISSING"
BLOCK_DIRECT_CODE_PERFORMANCE_RISK = "BLOCK_DIRECT_CODE_PERFORMANCE_RISK"
BLOCK_PROVIDER_ROUTING = "BLOCK_STEP2_PROVIDER_ROUTING_MISMATCH"
STANDARD_DIRECT_CODE_OUTPUT_COLUMNS = ["ts_code", "trade_date", "factor_value"]
DIRECT_CODE_PERFORMANCE_PROFILE_VERSION = "factorforge_direct_code_performance_contract_v1"
DEFAULT_STEP2_ALLOWED_PROVIDER_TOKENS = ["minimax", "deepseek"]
DEFAULT_STEP2_ALLOWED_MODEL_TOKENS = ["minimax", "deepseek"]

from scripts.factorforge_formal_run_manifest import load_required_manifest, validate_manifest


class CommandProviderError(RuntimeError):
    def __init__(self, *, role: str, rc: int, stderr_tail: str) -> None:
        self.role = role
        self.rc = rc
        self.stderr_tail = stderr_tail
        super().__init__(f"{BLOCK_PROVIDER_FAILED}: role={role} rc={rc} stderr={stderr_tail}")


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


def formal_llm_provider_request() -> dict[str, Any]:
    provider = os.getenv("FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER") or os.getenv("FACTORFORGE_FORMAL_LLM_PROVIDER")
    model = os.getenv("FACTORFORGE_STEP2_LLM_MODEL")
    payload: dict[str, Any] = {
        "contract_version": PROVIDER_REQUEST_CONTRACT_VERSION,
        "step": "step2",
        "provider_source": (
            "FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER"
            if os.getenv("FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER")
            else "FACTORFORGE_FORMAL_LLM_PROVIDER"
            if provider
            else "provider_wrapper_default"
        ),
        "model_source": "FACTORFORGE_STEP2_LLM_MODEL" if model else "provider_wrapper_default",
    }
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    temperature = os.getenv("FACTORFORGE_STEP2_LLM_TEMPERATURE") or os.getenv("FACTORFORGE_FORMAL_LLM_TEMPERATURE")
    if temperature:
        payload["temperature"] = temperature
    return payload


def _csv_tokens(env_name: str, default: list[str]) -> list[str]:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def assert_step2_provider_routing(provider_request: dict[str, Any]) -> None:
    provider = str(provider_request.get("provider") or "").strip()
    model = str(provider_request.get("model") or "").strip()
    provider_norm = provider.lower()
    model_norm = model.lower()
    allowed_providers = _csv_tokens(
        "FACTORFORGE_STEP2_ALLOWED_FORMAL_LLM_PROVIDERS",
        DEFAULT_STEP2_ALLOWED_PROVIDER_TOKENS,
    )
    allowed_models = _csv_tokens(
        "FACTORFORGE_STEP2_ALLOWED_LLM_MODELS",
        DEFAULT_STEP2_ALLOWED_MODEL_TOKENS,
    )
    provider_ok = bool(provider_norm and any(token in provider_norm for token in allowed_providers))
    model_ok = bool(model_norm and any(token in model_norm for token in allowed_models))
    if provider_ok and model_ok:
        return
    raise SystemExit(
        f"{BLOCK_PROVIDER_ROUTING}: Step2 formal factor spec/direct_code requires an allowed provider/model; "
        f"provider={provider or 'NOT_SET'} model={model or 'NOT_SET'} "
        f"allowed_provider_tokens={allowed_providers} allowed_model_tokens={allowed_models}"
    )


def stable_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_direct_code_output_schema(code_contract: dict[str, Any]) -> dict[str, Any]:
    output_schema = code_contract.get("output_schema")
    if not isinstance(output_schema, dict):
        output_schema = {}
    columns = [str(col) for col in _as_list(output_schema.get("columns")) if str(col).strip()]
    for column in STANDARD_DIRECT_CODE_OUTPUT_COLUMNS:
        if column not in columns:
            columns.append(column)
    output_schema["columns"] = columns
    return output_schema


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
    source_code = """import numpy as np
import pandas as pd


def compute_factor(daily_df: pd.DataFrame | None = None, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        raise ValueError("daily_df is required")
    required = {"ts_code", "trade_date", "close"}
    missing = sorted(required - set(daily_df.columns))
    if missing:
        raise ValueError(f"daily_df missing required columns: {missing}")
    df = daily_df[["ts_code", "trade_date", "close"]].copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["factor_value"] = df.groupby("ts_code", sort=False)["close"].pct_change()
    out = df[["ts_code", "trade_date", "factor_value"]].replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=["factor_value"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
"""
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
            "code_contract": {
                "code_contract_version": "factorforge_direct_code_contract_v1",
                "function_name": "compute_factor",
                "entrypoint": "compute_factor",
                "source_code": source_code,
                "code_hash": sha256_text(source_code),
                "imports": ["numpy", "pandas"],
                "dependencies": ["numpy", "pandas"],
                "input_schema": {"daily_df": required_inputs},
                "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
                "required_fields": required_inputs,
                "source_derivation": {
                    "derivation": "source_code_preserved_from_formal_step2_raw_direct_code_contract",
                    "not_fallback": True,
                    "fixture_only": True,
                },
            },
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


def _direct_code_contract(payload: dict[str, Any]) -> dict[str, Any]:
    contract = payload.get("implementation_contract")
    if not isinstance(contract, dict):
        return {}
    code_contract = contract.get("code_contract")
    if isinstance(code_contract, dict):
        return code_contract
    for key in ["code_contract", "direct_code_contract"]:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return candidate
    return {}


def _attribute_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Attribute):
        return [*_attribute_chain(node.value), node.attr]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Call):
        return [*_attribute_chain(node.func), "()"]
    if isinstance(node, ast.Subscript):
        return _attribute_chain(node.value)
    return []


def _call_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _receiver_chain_contains_call(node: ast.AST, name: str) -> bool:
    chain = _attribute_chain(node)
    return name in chain and "()" in chain


def _call_has_keyword_value(node: ast.Call, keyword: str, value: Any) -> bool:
    for kw in node.keywords:
        if kw.arg != keyword:
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value == value:
            return True
    return False


def _call_has_positional_value(node: ast.Call, index: int, value: Any) -> bool:
    if len(node.args) <= index:
        return False
    arg = node.args[index]
    return isinstance(arg, ast.Constant) and arg.value == value


def _is_groupby_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "groupby"


def _is_groupby_apply_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "apply" and _receiver_chain_contains_call(node.func.value, "groupby")


def _for_iter_uses_groupby(node: ast.For) -> bool:
    return any(_is_groupby_call(child) for child in ast.walk(node.iter))


def _groupby_alias_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not _is_groupby_call(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _for_iter_uses_groupby_alias(node: ast.For, aliases: set[str]) -> bool:
    return isinstance(node.iter, ast.Name) and node.iter.id in aliases


def _contains_call_attr(node: ast.AST, attr: str) -> bool:
    return any(_call_attr(child) == attr for child in ast.walk(node))


def _contains_nested_for(node: ast.For) -> bool:
    for child in node.body:
        if any(isinstance(grandchild, ast.For) for grandchild in ast.walk(child)):
            return True
    return False


def _is_range_len_loop(node: ast.For) -> bool:
    call = node.iter
    if not isinstance(call, ast.Call):
        return False
    if not isinstance(call.func, ast.Name) or call.func.id != "range" or not call.args:
        return False
    first = call.args[0]
    return isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "len"


def build_direct_code_performance_profile(source: str) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "version": DIRECT_CODE_PERFORMANCE_PROFILE_VERSION,
        "slow_patterns": [],
        "preferred_backend_markers": [],
    }
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        profile["slow_patterns"].append("python_syntax_error")
        profile["syntax_error"] = f"{exc.msg} line={exc.lineno}"
        return profile

    slow: set[str] = set()
    preferred: set[str] = set()
    groupby_aliases = _groupby_alias_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attr = _call_attr(node)
            chain = _attribute_chain(node.func)
            if chain and chain[0] in {"np", "numpy", "pl", "polars"}:
                preferred.add(chain[0])
            if attr in {"to_numpy", "transform", "where", "clip", "fillna", "merge", "assign", "pct_change", "diff", "shift"}:
                preferred.add(f"pandas_{attr}")
            if attr in {"iterrows", "itertuples"}:
                slow.add("pandas_row_iteration")
            if attr == "apply" and (
                _call_has_keyword_value(node, "axis", 1) or _call_has_positional_value(node, 1, 1)
            ):
                slow.add("pandas_row_apply")
            if _is_groupby_apply_call(node):
                slow.add("pandas_groupby_apply")
        if isinstance(node, ast.For):
            if _for_iter_uses_groupby(node) or _for_iter_uses_groupby_alias(node, groupby_aliases):
                slow.add("pandas_groupby_iteration")
            if _contains_nested_for(node):
                slow.add("nested_python_for_loop")
            if _contains_call_attr(node, "sort_values"):
                slow.add("sort_values_inside_loop")
            if _contains_call_attr(node, "append"):
                slow.add("list_append_inside_loop")
            if _is_range_len_loop(node):
                slow.add("range_len_loop")
    profile["slow_patterns"] = sorted(slow)
    profile["preferred_backend_markers"] = sorted(preferred)
    return profile


def direct_code_performance_failure(source: str) -> str | None:
    profile = build_direct_code_performance_profile(source)
    slow_patterns = profile.get("slow_patterns") or []
    if slow_patterns:
        return (
            f"{BLOCK_DIRECT_CODE_PERFORMANCE_RISK}: direct_code source uses disallowed slow patterns "
            f"{slow_patterns}; profile={json.dumps(profile, ensure_ascii=False, sort_keys=True)}"
        )
    return None


def normalize_command_raw(payload: dict[str, Any], *, role: str, request: dict[str, Any]) -> dict[str, Any]:
    if role not in {"primary", "challenger"}:
        return payload
    mode = str(payload.get("implementation_mode") or "").strip()
    contract = payload.get("implementation_contract")
    if not isinstance(contract, dict):
        contract = {}
    if mode == "direct_code":
        contract.setdefault("implementation_mode", "direct_code")
        contract.setdefault("mode", "direct_code")
        code_contract = contract.get("code_contract")
        if not isinstance(code_contract, dict):
            code_contract = {}
        source = str(code_contract.get("source_code") or code_contract.get("code") or code_contract.get("custom_source") or "").strip()
        if source:
            source = source if source.endswith("\n") else source + "\n"
            required_inputs = _as_list(payload.get("required_inputs"))
            required_fields = _as_list(code_contract.get("required_fields") or required_inputs)
            has_entrypoint = bool(code_contract.get("function_name") or code_contract.get("entrypoint"))
            imports = _as_list(code_contract.get("imports") or code_contract.get("dependencies") or ["numpy", "pandas"])
            source_derivation = code_contract.get("source_derivation")
            if isinstance(source_derivation, dict) and source_derivation.get("not_fallback") is True:
                source_derivation = {
                    **source_derivation,
                    "derivation": "source_code_preserved_from_formal_step2_raw_direct_code_contract",
                    "provider_source_derivation": source_derivation.get("derivation"),
                }
            code_contract.update(
                {
                    "code_contract_version": code_contract.get("code_contract_version") or "factorforge_direct_code_contract_v1",
                    "source_code": source,
                    "code_hash": sha256_text(source),
                    "imports": imports,
                    "dependencies": _as_list(code_contract.get("dependencies") or imports),
                    "input_schema": code_contract.get("input_schema") or {"daily_df": required_inputs},
                    "output_schema": _normalize_direct_code_output_schema(code_contract)
                    if required_fields and has_entrypoint
                    else code_contract.get("output_schema"),
                    "required_fields": required_fields,
                }
            )
            if source_derivation:
                code_contract["source_derivation"] = source_derivation
        contract["code_contract"] = code_contract
        payload["implementation_contract"] = contract
    provenance = payload.get("_llm_bridge_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance.update(
        {
            "provider": "command",
            "model": os.getenv("FACTORFORGE_STEP2_LLM_MODEL", "external-command"),
            "role": role,
            "report_id": request.get("report_id"),
            "prompt_name": request.get("prompt_name"),
            "prompt_hash": request.get("prompt_hash"),
            "formal_llm_extraction": True,
            "fixture_only": False,
            "request_version": request.get("version"),
        }
    )
    payload["_llm_bridge_provenance"] = provenance
    return payload


def direct_code_source_contract_failure(payload: dict[str, Any]) -> str | None:
    if str(payload.get("implementation_mode") or "").strip() != "direct_code":
        return None
    contract = _direct_code_contract(payload)
    source = str(contract.get("source_code") or "").strip()
    if not source:
        return f"{BLOCK_DIRECT_CODE_RAW}: implementation_mode=direct_code requires implementation_contract.code_contract.source_code"
    if contract.get("code_hash") != sha256_text(source if source.endswith("\n") else source + "\n"):
        return f"{BLOCK_DIRECT_CODE_RAW}: code_hash missing or does not match source_code"
    if not contract.get("function_name") and not contract.get("entrypoint"):
        return f"{BLOCK_DIRECT_CODE_RAW}: function_name/entrypoint missing"
    if not _as_list(contract.get("required_fields")) and not _as_list(payload.get("required_inputs")):
        return f"{BLOCK_DIRECT_CODE_RAW}: required_inputs/required_fields missing"
    output_schema = contract.get("output_schema")
    if not isinstance(output_schema, dict) or not _as_list(output_schema.get("columns")):
        return f"{BLOCK_DIRECT_CODE_RAW}: output_schema.columns missing"
    columns = [str(col) for col in _as_list(output_schema.get("columns"))]
    missing_columns = [col for col in STANDARD_DIRECT_CODE_OUTPUT_COLUMNS if col not in columns]
    if missing_columns:
        return f"{BLOCK_DIRECT_CODE_RAW}: output_schema.columns missing standard columns: {missing_columns}"
    source_derivation = contract.get("source_derivation")
    if not isinstance(source_derivation, dict) or source_derivation.get("not_fallback") is not True:
        return f"{BLOCK_DIRECT_CODE_RAW}: source_derivation.not_fallback=true required"
    perf_failure = direct_code_performance_failure(source)
    if perf_failure:
        return perf_failure
    return None


def validate_raw(path: Path, required: list[str], *, enforce_direct_code_contract: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parsed = False
    error = None
    try:
        payload = json.loads(text)
        parsed = all(payload.get(key) not in (None, "", []) for key in required)
        if parsed and enforce_direct_code_contract:
            error = direct_code_source_contract_failure(payload)
            parsed = error is None
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
            "and formula/custom block identity. If the report describes minute sorting + top cumulative volume + VWAP ratio, "
            "or any natural-language or custom smart-money calculation "
            "that cannot be represented as legal hybrid, choose direct_code and provide implementation_contract.code_contract "
            "with source_code, function_name/entrypoint=compute_factor, dependencies/imports, required_fields, input_schema, output_schema, "
            "and source_derivation.not_fallback=true. Do not invent code_hash; the bridge will compute code_hash from source_code. "
            "Do not choose direct_code without source_code. "
            "Direct_code source_code must be high-performance and validator-safe: prefer NumPy, Polars, or vectorized pandas; "
            "do not use for-loop iteration over pandas groupby objects, groupby.apply, row apply/apply(axis=1), iterrows, "
            "itertuples, nested Python loops over rows/tickers/dates/minutes, list append inside loops, or sort_values inside loops. "
            "Sort once globally or use vectorized group operations; never sort each group inside a Python loop. "
            "For direct_code, output_schema must include {'columns': ['ts_code', 'trade_date', 'factor_value']}; do not return "
            "an empty output_schema, dtype-only output_schema, or output_schema nested outside implementation_contract.code_contract."
        )
    if role == "challenger":
        return (
            "You are the Step2 challenger spec extraction agent. Independently challenge the primary interpretation and "
            "output factor_spec_raw JSON with the same required fields, preserving disagreements and ambiguities. "
            "Do not default pdf_report to hybrid; require executable hybrid structure or use direct_code with "
            "implementation_contract.code_contract.source_code, compute_factor entrypoint, output_schema.columns "
            "['ts_code', 'trade_date', 'factor_value'], and source_derivation.not_fallback=true. Direct_code source_code must "
            "avoid pandas groupby iteration, groupby.apply, row apply, iterrows/itertuples, nested Python loops, list append "
            "inside loops, and sort_values inside loops."
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
        raise CommandProviderError(
            role=str(request.get("role") or ""),
            rc=proc.returncode,
            stderr_tail=proc.stderr[-1000:],
        )
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
    rc: int | None = None,
    stderr_tail: str = "",
    block_token: str = BLOCK_PROVIDER_FAILED,
    provider_request: dict[str, Any] | None = None,
) -> None:
    provider_request = provider_request if isinstance(provider_request, dict) else {}
    provider_request_hash = str(provider_request.get("request_hash") or stable_hash(provider_request)) if provider_request else None
    provider_request_version = str(provider_request.get("contract_version") or "") if provider_request else None
    raw_outputs: dict[str, Any] = {}
    for role, path in role_paths.items():
        if not path.exists():
            continue
        if role == "auditor":
            required = ["report_id", "factor_id", "consistency_score", "recommendation"]
        else:
            required = ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]
        raw_outputs[role] = {
            **validate_raw(path, required, enforce_direct_code_contract=role in {"primary", "challenger"}),
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
            "block_token": block_token,
            "role": failed_role,
            "failed_role": failed_role,
            "rc": rc,
            "stderr_tail": stderr_tail,
            "provider": "command",
            "model": os.getenv("FACTORFORGE_STEP2_LLM_MODEL", "external-command"),
            "temperature": os.getenv("FACTORFORGE_STEP2_LLM_TEMPERATURE", "provider_default"),
            "provider_request_contract_version": provider_request_version,
            "provider_request_hash": provider_request_hash,
            "worker_started": False,
            "runtime_context_written": False,
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
    provider_request = formal_llm_provider_request()
    _, manifest = load_required_manifest(args.run_manifest)
    validate_manifest(
        manifest,
        report_id=args.report_id,
        factorforge_root=root,
        step="step2",
        provider_request=provider_request,
        expected_out_dir=out_dir,
    )
    assert_step2_provider_routing(provider_request)

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
            "formal_llm_provider_request": provider_request,
        }
        try:
            response_text = run_command_provider(command, request)
        except CommandProviderError as exc:
            write_command_failure_report(
                args,
                root,
                out_dir,
                created_at_utc=created,
                role_paths=role_paths,
                prompt_context_hash=prompt_context_hash,
                failed_role=role,
                error=str(exc),
                rc=exc.rc,
                stderr_tail=exc.stderr_tail,
                block_token=BLOCK_PROVIDER_FAILED,
                provider_request=request.get("formal_llm_provider_request"),
            )
            raise SystemExit(str(exc)) from exc
        path = role_paths[role]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response_text + "\n", encoding="utf-8")
        try:
            parsed = json.loads(response_text)
            if not isinstance(parsed, dict):
                raise ValueError("provider output JSON root must be object")
            parsed = normalize_command_raw(parsed, role=role, request=request)
            path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            validation = validate_raw(
                path,
                ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"]
                if role in {"primary", "challenger"}
                else ["report_id", "factor_id", "consistency_score", "recommendation"],
                enforce_direct_code_contract=role in {"primary", "challenger"},
            )
            if validation.get("parsed_json_valid") is not True:
                error = validation.get("validation_error") or "raw validation failed"
                write_command_failure_report(
                    args,
                    root,
                    out_dir,
                    created_at_utc=created,
                    role_paths=role_paths,
                    prompt_context_hash=prompt_context_hash,
                    failed_role=role,
                    error=str(error),
                    rc=1,
                    stderr_tail=str(error),
                    block_token=(
                        BLOCK_DIRECT_CODE_RAW
                        if str(error).startswith(BLOCK_DIRECT_CODE_RAW)
                        else BLOCK_DIRECT_CODE_PERFORMANCE_RISK
                        if str(error).startswith(BLOCK_DIRECT_CODE_PERFORMANCE_RISK)
                        else BLOCK_PROVIDER_FAILED
                    ),
                    provider_request=request.get("formal_llm_provider_request"),
                )
                raise SystemExit(f"{BLOCK_PROVIDER_FAILED}: role={role} {error}")
            prior_outputs[role] = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            write_command_failure_report(
                args,
                root,
                out_dir,
                created_at_utc=created,
                role_paths=role_paths,
                prompt_context_hash=prompt_context_hash,
                failed_role=role,
                error=f"{type(exc).__name__}: {exc}",
                rc=1,
                stderr_tail=f"{type(exc).__name__}: {exc}",
                block_token=BLOCK_PROVIDER_FAILED,
                provider_request=request.get("formal_llm_provider_request"),
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
                **validate_raw(role_paths["primary"], ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"], enforce_direct_code_contract=True),
                "prompt_name": "step2_primary_formal_extraction",
                "prompt_hash": sha256_text(role_prompt("primary")),
            },
            "challenger": {
                **validate_raw(role_paths["challenger"], ["report_id", "factor_id", "raw_formula_text", "operators", "required_inputs", "implementation_mode"], enforce_direct_code_contract=True),
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
    ap.add_argument("--run-manifest", default=os.getenv("FACTORFORGE_FORMAL_RUN_MANIFEST"))
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
