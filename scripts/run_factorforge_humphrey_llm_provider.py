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
DEFAULT_CONFIG = Path("/home/ubuntu/.openclaw/openclaw.json")
DEFAULT_PROVIDER = "modelstudio"
DEFAULT_STEP1_MODEL = "qwen3.5-plus"
DEFAULT_STEP2_MODEL = "qwen3.5-plus"


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


def read_openclaw_provider(provider_name: str) -> dict[str, Any]:
    config_path = Path(os.getenv("FACTORFORGE_OPENCLAW_CONFIG", str(DEFAULT_CONFIG))).expanduser()
    if not config_path.exists():
        raise RuntimeError(f"OpenClaw config missing: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    provider = ((config.get("models") or {}).get("providers") or {}).get(provider_name)
    if not isinstance(provider, dict):
        raise RuntimeError(f"provider not found in OpenClaw config: {provider_name}")
    if provider.get("api") != "openai-completions":
        raise RuntimeError(f"provider {provider_name} is not openai-completions; api={provider.get('api')}")
    if not provider.get("baseUrl") or not provider.get("apiKey"):
        raise RuntimeError(f"provider {provider_name} missing baseUrl/apiKey")
    return provider


def openai_chat_completion(*, provider: dict[str, Any], model: str, messages: list[dict[str, str]], max_tokens: int) -> str:
    base_url = str(provider["baseUrl"]).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(os.getenv("FACTORFORGE_FORMAL_LLM_TEMPERATURE", "0.1")),
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


def enrich_provenance(payload: dict[str, Any], request: dict[str, Any], *, provider_name: str, model: str) -> dict[str, Any]:
    provenance = {
        "provider_wrapper": "run_factorforge_humphrey_llm_provider.py",
        "provider": provider_name,
        "model": model,
        "role": request.get("role"),
        "report_id": request.get("report_id"),
        "prompt_name": request.get("prompt_name"),
        "prompt_hash": request.get("prompt_hash"),
        "pdf_sha256": request.get("pdf_sha256"),
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
        contract.setdefault("function_name", "compute_factor")
        contract.setdefault("required_fields", payload.get("required_inputs") or [])
        payload["implementation_contract"] = contract

    return payload


def step1_messages(request: dict[str, Any]) -> tuple[list[dict[str, str]], int, str]:
    role = str(request.get("role") or "")
    model = os.getenv("FACTORFORGE_STEP1_LLM_MODEL", DEFAULT_STEP1_MODEL)
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
    ], int(os.getenv("FACTORFORGE_STEP1_LLM_MAX_TOKENS", "12000")), model


def step2_messages(request: dict[str, Any]) -> tuple[list[dict[str, str]], int, str]:
    role = str(request.get("role") or "")
    model = os.getenv("FACTORFORGE_STEP2_LLM_MODEL", DEFAULT_STEP2_MODEL)
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
            "Never default pdf_report to hybrid. Include required_inputs, operators, time_series_steps, cross_sectional_steps, "
            "implementation_contract, raw_formula_text, explicit_items, inferred_items, ambiguities, and mechanism contracts when supported."
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
    ], int(os.getenv("FACTORFORGE_STEP2_LLM_MAX_TOKENS", "12000")), model


def main() -> int:
    try:
        request = read_request()
        role = str(request.get("role") or "")
        version = str(request.get("version") or "")
        provider_name = os.getenv("FACTORFORGE_FORMAL_LLM_PROVIDER", DEFAULT_PROVIDER)
        provider = read_openclaw_provider(provider_name)
        if version == "factorforge_step1_llm_bridge_v1":
            messages, max_tokens, model = step1_messages(request)
        elif version == "factorforge_step2_llm_bridge_v1":
            messages, max_tokens, model = step2_messages(request)
        else:
            raise RuntimeError(f"unsupported bridge request version: {version}")
        eprint(f"[factorforge-provider] role={role} provider={provider_name} model={model} prompt_hash={request.get('prompt_hash')}")
        raw = openai_chat_completion(provider=provider, model=model, messages=messages, max_tokens=max_tokens)
        payload = extract_json_object(raw)
        if version == "factorforge_step2_llm_bridge_v1":
            payload = normalize_step2_payload(payload, request)
        payload = enrich_provenance(payload, request, provider_name=provider_name, model=model)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except Exception as exc:  # noqa: BLE001 - provider command reports cleanly to bridge stderr.
        eprint(f"{BLOCK_PROVIDER_FAILED}: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
