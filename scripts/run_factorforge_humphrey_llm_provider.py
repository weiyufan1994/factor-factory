#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests


BLOCK_PROVIDER_FAILED = "BLOCK_HUMPHREY_FORMAL_LLM_PROVIDER_FAILED"
BLOCK_PROVIDER_REQUEST_CONTRACT = "BLOCK_HUMPHREY_FORMAL_LLM_PROVIDER_REQUEST_CONTRACT_INVALID"
BLOCK_UNSUPPORTED_API = "BLOCK_HUMPHREY_FORMAL_LLM_PROVIDER_UNSUPPORTED_API"
DEFAULT_CONFIG = Path("/home/ubuntu/.openclaw/openclaw.json")
SUPPORTED_PROVIDER_APIS = {"openai-completions", "anthropic-messages"}
PROVIDER_REQUEST_CONTRACT_VERSION = "factorforge_formal_llm_provider_request_v1"
STANDARD_DIRECT_CODE_OUTPUT_COLUMNS = ["ts_code", "trade_date", "factor_value"]


class UnsupportedProviderApi(RuntimeError):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def read_request() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise RuntimeError("empty stdin bridge request")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("bridge request must be a JSON object")
    return payload


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(encoded)


def resolve_provider_request(request: dict[str, Any], *, version: str) -> dict[str, Any]:
    raw = request.get("formal_llm_provider_request")
    if not isinstance(raw, dict):
        raise RuntimeError(f"{BLOCK_PROVIDER_REQUEST_CONTRACT}: formal_llm_provider_request object is required")
    contract = raw
    step = "step1" if version == "factorforge_step1_llm_bridge_v1" else "step2"
    contract_version = str(contract.get("contract_version") or "").strip()
    if contract_version != PROVIDER_REQUEST_CONTRACT_VERSION:
        raise RuntimeError(
            f"{BLOCK_PROVIDER_REQUEST_CONTRACT}: unsupported contract_version={contract_version!r}"
        )
    provider_name = str(contract.get("provider") or "").strip()
    model = str(contract.get("model") or "").strip()
    if not provider_name:
        raise RuntimeError(f"{BLOCK_PROVIDER_REQUEST_CONTRACT}: provider is required")
    if not model:
        raise RuntimeError(f"{BLOCK_PROVIDER_REQUEST_CONTRACT}: model is required")
    resolved = {
        "contract_version": contract_version,
        "step": str(contract.get("step") or step),
        "provider": provider_name,
        "model": model,
        "provider_source": str(contract.get("provider_source") or "bridge_request"),
        "model_source": str(contract.get("model_source") or "bridge_request"),
    }
    if contract.get("temperature") is not None:
        resolved["temperature"] = contract.get("temperature")
    resolved["request_hash"] = stable_hash(resolved)
    return resolved


def read_openclaw_provider(provider_name: str) -> dict[str, Any]:
    config_path = Path(os.getenv("FACTORFORGE_OPENCLAW_CONFIG", str(DEFAULT_CONFIG))).expanduser()
    if not config_path.exists():
        raise RuntimeError(f"OpenClaw config missing: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    provider = ((config.get("models") or {}).get("providers") or {}).get(provider_name)
    if not isinstance(provider, dict):
        raise RuntimeError(f"provider not found in OpenClaw config: {provider_name}")
    provider_api = str(provider.get("api") or "").strip()
    if provider_api not in SUPPORTED_PROVIDER_APIS:
        raise UnsupportedProviderApi(f"{BLOCK_UNSUPPORTED_API}: provider={provider_name} api={provider_api}")
    if not provider.get("baseUrl") or not provider.get("apiKey"):
        raise RuntimeError(f"provider {provider_name} missing baseUrl/apiKey")
    return provider


def resolved_temperature(provider_request: dict[str, Any]) -> float:
    raw = provider_request.get("temperature")
    if raw is None:
        raw = os.getenv("FACTORFORGE_FORMAL_LLM_TEMPERATURE", "0.1")
    return float(raw)


def openai_chat_completion(
    *,
    provider: dict[str, Any],
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = str(provider["baseUrl"]).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    timeout = int(os.getenv("FACTORFORGE_FORMAL_LLM_TIMEOUT_SECONDS", "240"))
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {provider['apiKey']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:1000]}")
    body = resp.json()
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM response missing choices: {body}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"LLM response empty content: {body}")
    return content


def anthropic_messages_completion(
    *,
    provider: dict[str, Any],
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = str(provider["baseUrl"]).rstrip("/")
    if base_url.endswith("/v1/messages") or base_url.endswith("/messages"):
        url = base_url
    elif base_url.endswith("/v1"):
        url = f"{base_url}/messages"
    else:
        url = f"{base_url}/v1/messages"
    system_parts = [str(item.get("content") or "") for item in messages if item.get("role") == "system"]
    user_messages = [
        {"role": item.get("role") if item.get("role") in {"user", "assistant"} else "user", "content": str(item.get("content") or "")}
        for item in messages
        if item.get("role") != "system"
    ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": user_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_parts:
        payload["system"] = "\n\n".join(part for part in system_parts if part)
    timeout = int(os.getenv("FACTORFORGE_FORMAL_LLM_TIMEOUT_SECONDS", "240"))
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {provider['apiKey']}",
            "X-Api-Key": str(provider["apiKey"]),
            "anthropic-version": os.getenv("FACTORFORGE_ANTHROPIC_VERSION", "2023-06-01"),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:1000]}")
    body = resp.json()
    content = body.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        if parts:
            return "\n".join(parts)
    raise RuntimeError(f"LLM response missing anthropic text content: {body}")


def provider_completion(
    *,
    provider: dict[str, Any],
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    provider_api = str(provider.get("api") or "").strip()
    if provider_api == "openai-completions":
        return openai_chat_completion(provider=provider, model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if provider_api == "anthropic-messages":
        return anthropic_messages_completion(provider=provider, model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
    raise UnsupportedProviderApi(f"{BLOCK_UNSUPPORTED_API}: api={provider_api}")


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError("LLM output JSON root must be object")
    return payload


def pdf_text(pdf_path: str) -> str:
    path = Path(pdf_path).expanduser()
    if not path.exists():
        raise RuntimeError(f"pdf not found: {path}")
    proc = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed rc={proc.returncode}: {proc.stderr[-1000:]}")
    text = proc.stdout.strip()
    if not text:
        raise RuntimeError(f"pdftotext returned empty text for {path}")
    max_chars = int(os.getenv("FACTORFORGE_FORMAL_PDF_TEXT_MAX_CHARS", "140000"))
    if len(text) > max_chars:
        head = max_chars * 2 // 3
        tail = max_chars - head
        text = text[:head] + "\n\n[...PDF TEXT TRUNCATED FOR CONTEXT BUDGET...]\n\n" + text[-tail:]
    return text


def request_pdf_sha256(request: dict[str, Any]) -> Any:
    direct = request.get("pdf_sha256")
    if direct:
        return direct
    context = request.get("step1_context")
    if not isinstance(context, dict):
        return None
    for key in ["step1_chief_raw", "step1_primary_raw", "step1_challenger_raw"]:
        raw = context.get(key)
        if not isinstance(raw, dict):
            continue
        provenance = raw.get("_llm_bridge_provenance")
        if isinstance(provenance, dict) and provenance.get("pdf_sha256"):
            return provenance.get("pdf_sha256")
    return None


def enrich_provenance(
    payload: dict[str, Any],
    request: dict[str, Any],
    *,
    provider_name: str,
    model: str,
    provider_request: dict[str, Any],
) -> dict[str, Any]:
    provenance = {
        "provider_wrapper": "run_factorforge_humphrey_llm_provider.py",
        "provider": provider_name,
        "provider_api": request.get("_provider_api"),
        "model": model,
        "model_source": provider_request.get("model_source"),
        "provider_source": provider_request.get("provider_source"),
        "provider_request_contract_version": provider_request.get("contract_version"),
        "provider_request_hash": provider_request.get("request_hash"),
        "role": request.get("role"),
        "report_id": request.get("report_id"),
        "prompt_name": request.get("prompt_name"),
        "prompt_hash": request.get("prompt_hash"),
        "pdf_sha256": request_pdf_sha256(request),
        "formal_llm_extraction": True,
        "fixture_only": False,
        "request_version": request.get("version"),
    }
    payload["_llm_bridge_provenance"] = {**(payload.get("_llm_bridge_provenance") or {}), **provenance}
    return payload


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = [f"{key}: {json.dumps(val, ensure_ascii=False, sort_keys=True)}" for key, val in value.items()]
    else:
        items = [value]

    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
        else:
            text = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if text:
            out.append(text)
    return out


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


def normalize_step2_payload(payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    role = str(request.get("role") or "")
    if role not in {"primary", "challenger"}:
        return payload

    nested = payload.get("factor_spec_raw")
    if isinstance(nested, dict):
        outer_provenance = payload.get("_llm_bridge_provenance")
        payload = dict(nested)
        if isinstance(outer_provenance, dict) and "_llm_bridge_provenance" not in payload:
            payload["_llm_bridge_provenance"] = outer_provenance

    for key in [
        "operators",
        "required_inputs",
        "time_series_steps",
        "cross_sectional_steps",
        "preprocessing",
        "normalization",
        "neutralization",
        "explicit_items",
        "inferred_items",
        "ambiguities",
        "implementation_assumptions",
    ]:
        if key in payload:
            payload[key] = _as_text_list(payload.get(key))

    contract = payload.get("implementation_contract")
    if not isinstance(contract, dict):
        contract = {}

    mode = str(payload.get("implementation_mode") or "").strip()
    contract_mode = str(contract.get("implementation_mode") or contract.get("mode") or "").strip()
    if not mode and contract_mode in {"operator", "direct_code", "hybrid"}:
        payload["implementation_mode"] = contract_mode
        mode = contract_mode

    if mode == "direct_code":
        contract.setdefault("implementation_mode", "direct_code")
        contract.setdefault("mode", "direct_code")
        contract.setdefault("required_fields", payload.get("required_inputs") or [])
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

    return payload


def _direct_code_source_contract_failure(payload: dict[str, Any]) -> str | None:
    if str(payload.get("implementation_mode") or "").strip() != "direct_code":
        return None
    contract = _direct_code_contract(payload)
    source = str(contract.get("source_code") or "").strip()
    if not source:
        return "direct_code implementation_mode requires implementation_contract.code_contract.source_code"
    normalized_source = source if source.endswith("\n") else source + "\n"
    if contract.get("code_hash") != sha256_text(normalized_source):
        return "direct_code code_contract.code_hash missing or mismatched"
    if not contract.get("function_name") and not contract.get("entrypoint"):
        return "direct_code code_contract.function_name/entrypoint missing"
    if not _as_list(contract.get("required_fields")) and not _as_list(payload.get("required_inputs")):
        return "direct_code code_contract.required_fields or required_inputs missing"
    output_schema = contract.get("output_schema")
    if not isinstance(output_schema, dict) or not _as_list(output_schema.get("columns")):
        return "direct_code code_contract.output_schema.columns missing"
    columns = [str(col) for col in _as_list(output_schema.get("columns"))]
    missing_columns = [col for col in STANDARD_DIRECT_CODE_OUTPUT_COLUMNS if col not in columns]
    if missing_columns:
        return f"direct_code code_contract.output_schema.columns missing standard columns: {missing_columns}"
    source_derivation = contract.get("source_derivation")
    if not isinstance(source_derivation, dict) or source_derivation.get("not_fallback") is not True:
        return "direct_code code_contract.source_derivation.not_fallback=true missing"
    return None


def _complete_hybrid_contract(payload: dict[str, Any]) -> bool:
    contract = payload.get("implementation_contract")
    if not isinstance(contract, dict):
        return False
    operator_subgraph = contract.get("operator_subgraph")
    if not isinstance(operator_subgraph, dict):
        return False
    formula_ir = operator_subgraph.get("formula_ir")
    custom_blocks = contract.get("custom_blocks")
    return bool(
        contract.get("hybrid_contract_version") == "factorforge_hybrid_implementation_contract_v1"
        and isinstance(formula_ir, dict)
        and formula_ir.get("parse_status") == "success"
        and isinstance(custom_blocks, list)
        and custom_blocks
        and contract.get("formula_hash")
        and contract.get("custom_block_hash")
        and contract.get("hybrid_hash")
    )


def _invalid_step2_hybrid(payload: dict[str, Any], request: dict[str, Any]) -> bool:
    role = str(request.get("role") or "")
    if role not in {"primary", "challenger"}:
        return False
    return str(payload.get("implementation_mode") or "").strip() == "hybrid" and not _complete_hybrid_contract(payload)


def _invalid_step2_direct_code(payload: dict[str, Any], request: dict[str, Any]) -> str | None:
    role = str(request.get("role") or "")
    if role not in {"primary", "challenger"}:
        return None
    return _direct_code_source_contract_failure(payload)


def repair_step2_payload(
    *,
    provider: dict[str, Any],
    model: str,
    temperature: float,
    request: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    role = str(request.get("role") or "")
    repair_prompt = (
        "Your previous Step2 raw JSON declared implementation_mode='hybrid' without a complete executable "
        "Factor Forge hybrid contract. Return corrected Step2 raw JSON only, with fields at the top level. "
        "Do not wrap inside factor_spec_raw. If you cannot provide all hybrid fields "
        "(hybrid_contract_version=factorforge_hybrid_implementation_contract_v1, operator_subgraph.formula_ir.parse_status='success', "
        "non-empty custom_blocks, formula_hash, custom_block_hash, hybrid_hash), choose implementation_mode='direct_code'. "
        "For minute sorting + top cumulative volume + VWAP ratio algorithms, use implementation_mode='direct_code' by default. "
        "Do not attempt hybrid unless the full executable hybrid contract is truly complete. "
        "If you choose direct_code, you must provide implementation_contract.code_contract.source_code with entrypoint/function_name, "
        "imports/dependencies, required_fields, input_schema, output_schema, and source_derivation.not_fallback=true. "
        "Do not invent code_hash; the bridge will compute code_hash from source_code. "
        "The direct_code output_schema must be exactly or at least {'columns': ['ts_code', 'trade_date', 'factor_value']}; "
        "do not return an empty output_schema, a dtype-only output_schema, or output_schema nested outside code_contract. "
        "Do not use direct_code without source_code. "
        "Preserve report-specific formulas, required_inputs, ambiguities, and mechanism contracts. "
        "Do not use fixture or template content."
    )
    messages = [
        {
            "role": "system",
            "content": "You are a Factor Forge formal Step2 extraction provider. Output strict JSON only.",
        },
        {
            "role": "user",
            "content": (
                f"Role: {role}\n"
                f"Report ID: {request.get('report_id')}\n"
                f"Correction requirement:\n{repair_prompt}\n\n"
                f"Previous invalid raw JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]
    raw = provider_completion(
        provider=provider,
        model=model,
        messages=messages,
        max_tokens=int(os.getenv("FACTORFORGE_STEP2_LLM_REPAIR_MAX_TOKENS", "8000")),
        temperature=temperature,
    )
    repaired = normalize_step2_payload(extract_json_object(raw), request)
    if _invalid_step2_hybrid(repaired, request):
        raise RuntimeError("Step2 LLM returned incomplete hybrid_contract after repair")
    direct_failure = _invalid_step2_direct_code(repaired, request)
    if direct_failure:
        raise RuntimeError(f"Step2 LLM returned incomplete direct_code contract after repair: {direct_failure}")
    repaired.setdefault("_llm_bridge_provider_repairs", []).append(
        {
            "repair": "invalid_hybrid_contract_reasked_llm",
            "reason": "implementation_mode=hybrid requires complete executable hybrid_contract",
        }
    )
    return repaired


def step1_messages(request: dict[str, Any], *, model: str) -> tuple[list[dict[str, str]], int]:
    role = str(request.get("role") or "")
    prompt = str(request.get("prompt") or "")
    prior = request.get("prior_outputs") or {}
    text = pdf_text(str(request.get("pdf_path") or ""))
    if role in {"primary", "challenger"}:
        extra = (
            "You are producing formal Step1 raw extraction. Return JSON only. "
            "In addition to the requested intake schema, preserve report-specific evidence, formulas, implementation clues, "
            "and unresolved ambiguities. Do not use fixture or template language."
        )
        user = {
            "role": "user",
            "content": (
                f"{prompt}\n\n{extra}\n\n"
                f"Report ID: {request.get('report_id')}\n"
                f"PDF sha256: {request.get('pdf_sha256')}\n\n"
                f"PDF TEXT:\n{text}"
            ),
        }
    elif role == "chief":
        user = {
            "role": "user",
            "content": (
                f"{prompt}\n\n"
                "Return JSON only. Use the primary/challenger raw outputs and the PDF text. "
                "You must include market_process_thesis.what_must_be_true and what_would_break_it. "
                "Derive them from report-specific raw evidence; if the evidence is insufficient, leave fields missing so validation blocks. "
                "Do not write generic placeholder assumptions.\n\n"
                f"Report ID: {request.get('report_id')}\n"
                f"PDF sha256: {request.get('pdf_sha256')}\n\n"
                f"PRIMARY/CHALLENGER RAW:\n{json.dumps(prior, ensure_ascii=False, indent=2)}\n\n"
                f"PDF TEXT:\n{text}"
            ),
        }
    else:
        raise RuntimeError(f"unsupported Step1 role: {role}")
    return [
        {"role": "system", "content": "You are a Factor Forge formal PDF/LLM extraction provider. Output strict JSON only."},
        user,
    ], int(os.getenv("FACTORFORGE_STEP1_LLM_MAX_TOKENS", "12000"))


def step2_messages(request: dict[str, Any], *, model: str) -> tuple[list[dict[str, str]], int]:
    role = str(request.get("role") or "")
    prompt = str(request.get("prompt") or "")
    context = request.get("step1_context") or {}
    prior = request.get("prior_outputs") or {}
    if not context.get("step1_raw_present"):
        raise RuntimeError("Step2 provider requires fresh Step1 raw context")
    if role in {"primary", "challenger"}:
        role_extra = (
            "Extract executable factor spec raw JSON. Select implementation_mode from executable structure only. "
            "Return the factor spec fields at the top level; do not wrap them inside factor_spec_raw. "
            "Use direct_code for natural-language/custom smart-money algorithms unless you can provide a complete hybrid_contract. "
            "For minute sorting + top cumulative volume + VWAP ratio algorithms, implementation_mode must be direct_code unless "
            "you can provide the complete executable hybrid contract. "
            "Never default pdf_report to hybrid. Include required_inputs, operators, time_series_steps, cross_sectional_steps, "
            "implementation_contract, raw_formula_text, explicit_items, inferred_items, ambiguities, and mechanism contracts when supported. "
            "If you choose direct_code, implementation_contract.code_contract is mandatory and must include source_code, "
            "function_name/entrypoint=compute_factor, imports/dependencies, required_fields, input_schema, output_schema, "
            "source_derivation.not_fallback=true. Do not invent code_hash; the bridge will compute code_hash from source_code. "
            "and report-derived implementation notes. For the Kaiyuan smart-money factor preserve the PDF mechanics "
            "S=|R|/ln(V), S sorting, top-20-percent cumulative volume selection, and VWAPsmart/VWAPall semantics in the source contract. "
            "The direct_code output_schema must include {'columns': ['ts_code', 'trade_date', 'factor_value']}; do not return "
            "empty output_schema, dtype-only output_schema, or output_schema nested outside implementation_contract.code_contract."
        )
    elif role == "auditor":
        role_extra = (
            "Audit primary and challenger Step2 raw specs. Return JSON only with report_id, factor_id, consistency_score, "
            "matches_core_driver, mismatch_points, missing_steps, distortion_risks, and recommendation."
        )
    else:
        raise RuntimeError(f"unsupported Step2 role: {role}")
    user = {
        "role": "user",
        "content": (
            f"{prompt}\n\n{role_extra}\n\n"
            f"Report ID: {request.get('report_id')}\n"
            f"STEP1 CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
            f"PRIOR STEP2 OUTPUTS:\n{json.dumps(prior, ensure_ascii=False, indent=2)}"
        ),
    }
    return [
        {"role": "system", "content": "You are a Factor Forge formal Step2 extraction provider. Output strict JSON only."},
        user,
    ], int(os.getenv("FACTORFORGE_STEP2_LLM_MAX_TOKENS", "12000"))


def main() -> int:
    try:
        request = read_request()
        role = str(request.get("role") or "")
        version = str(request.get("version") or "")
        provider_request = resolve_provider_request(request, version=version)
        provider_name = str(provider_request["provider"])
        model = str(provider_request["model"])
        temperature = resolved_temperature(provider_request)
        provider = read_openclaw_provider(provider_name)
        request["_provider_api"] = str(provider.get("api") or "")
        if version == "factorforge_step1_llm_bridge_v1":
            messages, max_tokens = step1_messages(request, model=model)
        elif version == "factorforge_step2_llm_bridge_v1":
            messages, max_tokens = step2_messages(request, model=model)
        else:
            raise RuntimeError(f"unsupported bridge request version: {version}")
        eprint(f"[factorforge-provider] role={role} provider={provider_name} api={provider.get('api')} model={model} prompt_hash={request.get('prompt_hash')}")
        raw = provider_completion(provider=provider, model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        payload = extract_json_object(raw)
        if version == "factorforge_step2_llm_bridge_v1":
            payload = normalize_step2_payload(payload, request)
            if _invalid_step2_hybrid(payload, request) or _invalid_step2_direct_code(payload, request):
                eprint("[factorforge-provider] invalid Step2 hybrid contract returned; asking model for corrected raw JSON")
                payload = repair_step2_payload(provider=provider, model=model, temperature=temperature, request=request, payload=payload)
            direct_failure = _invalid_step2_direct_code(payload, request)
            if direct_failure:
                raise RuntimeError(direct_failure)
        payload = enrich_provenance(payload, request, provider_name=provider_name, model=model, provider_request=provider_request)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except UnsupportedProviderApi as exc:
        eprint(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - provider command reports cleanly to bridge stderr.
        eprint(f"{BLOCK_PROVIDER_FAILED}: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
