#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BLOCK_UNAVAILABLE = "BLOCK_FORMAL_GEMINI_BRIDGE_UNAVAILABLE"
BLOCK_FAILED = "BLOCK_FORMAL_GEMINI_BRIDGE_FAILED"
PROVIDER_REQUEST_CONTRACT_VERSION = "factorforge_formal_llm_provider_request_v1"
PROVIDER_API = "gemini-generate-content"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_request() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise RuntimeError("empty stdin bridge request")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("bridge request must be a JSON object")
    return payload


def api_key() -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(f"{BLOCK_UNAVAILABLE}: GEMINI_API_KEY or GOOGLE_API_KEY is required")
    return key


def resolve_model(request: dict[str, Any]) -> tuple[str, str]:
    provider_request = request.get("formal_llm_provider_request")
    request_model = None
    request_source = None
    if isinstance(provider_request, dict):
        contract_version = str(provider_request.get("contract_version") or "").strip()
        if contract_version and contract_version != PROVIDER_REQUEST_CONTRACT_VERSION:
            raise RuntimeError(f"{BLOCK_FAILED}: unsupported provider_request contract_version={contract_version!r}")
        request_model = str(provider_request.get("model") or "").strip() or None
        request_source = str(provider_request.get("model_source") or "formal_llm_provider_request")
    env_model = str(os.getenv("FACTORFORGE_STEP1_LLM_MODEL") or "").strip()
    if request_model:
        return request_model, request_source or "formal_llm_provider_request"
    if env_model:
        return env_model, "FACTORFORGE_STEP1_LLM_MODEL"
    raise RuntimeError(f"{BLOCK_UNAVAILABLE}: FACTORFORGE_STEP1_LLM_MODEL or formal_llm_provider_request.model is required")


def resolve_provider(request: dict[str, Any]) -> tuple[str, str]:
    provider_request = request.get("formal_llm_provider_request")
    if isinstance(provider_request, dict) and provider_request.get("provider"):
        return str(provider_request["provider"]), str(provider_request.get("provider_source") or "formal_llm_provider_request")
    provider = os.getenv("FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER") or os.getenv("FACTORFORGE_FORMAL_LLM_PROVIDER") or "google"
    return str(provider), "environment_or_default_google"


def pdf_payload(request: dict[str, Any]) -> tuple[Path, bytes, str]:
    raw_path = str(request.get("pdf_path") or "").strip()
    if not raw_path:
        raise RuntimeError(f"{BLOCK_FAILED}: request.pdf_path is required")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise RuntimeError(f"{BLOCK_FAILED}: pdf_path does not exist: {path}")
    data = path.read_bytes()
    actual_sha = sha256_bytes(data)
    expected_sha = str(request.get("pdf_sha256") or "").strip()
    if expected_sha and expected_sha != actual_sha:
        raise RuntimeError(f"{BLOCK_FAILED}: pdf_sha256 mismatch expected={expected_sha} actual={actual_sha}")
    return path, data, actual_sha


def temperature(request: dict[str, Any]) -> float:
    provider_request = request.get("formal_llm_provider_request")
    if isinstance(provider_request, dict) and provider_request.get("temperature") is not None:
        return float(provider_request["temperature"])
    raw = os.getenv("FACTORFORGE_STEP1_LLM_TEMPERATURE") or os.getenv("FACTORFORGE_FORMAL_LLM_TEMPERATURE")
    return float(raw) if raw is not None else 0.1


def build_prompt(request: dict[str, Any], *, pdf_sha256: str) -> str:
    role = str(request.get("role") or "")
    report_id = str(request.get("report_id") or "")
    prompt = str(request.get("prompt") or "")
    prior_outputs = request.get("prior_outputs") or {}
    return (
        f"{prompt}\n\n"
        "Return strict JSON only. Do not wrap the JSON in markdown fences. "
        "Do not use fixture, template, or synthetic content. Preserve report-specific evidence and uncertainty.\n\n"
        f"Role: {role}\n"
        f"Report ID: {report_id}\n"
        f"PDF sha256: {pdf_sha256}\n\n"
        f"Prior outputs:\n{json.dumps(prior_outputs, ensure_ascii=False, indent=2)}"
    )


def gemini_url(model: str, key: str) -> str:
    base = os.getenv("FACTORFORGE_GEMINI_API_BASE") or os.getenv("GOOGLE_GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta"
    base = base.rstrip("/")
    if base.endswith(":generateContent"):
        return f"{base}?key={urllib.parse.quote(key)}"
    quoted_model = urllib.parse.quote(model, safe="")
    return f"{base}/models/{quoted_model}:generateContent?key={urllib.parse.quote(key)}"


def call_gemini(*, request: dict[str, Any], model: str, pdf_data: bytes, pdf_sha256: str, key: str) -> dict[str, Any]:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_prompt(request, pdf_sha256=pdf_sha256)},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(pdf_data).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": temperature(request),
            "responseMimeType": "application/json",
        },
    }
    timeout = int(os.getenv("FACTORFORGE_GEMINI_TIMEOUT_SECONDS", os.getenv("FACTORFORGE_FORMAL_LLM_TIMEOUT_SECONDS", "240")))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        gemini_url(model, key),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - explicit configured Gemini endpoint.
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"{BLOCK_FAILED}: Gemini HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{BLOCK_FAILED}: Gemini request failed: {exc}") from exc


def extract_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError(f"{BLOCK_FAILED}: Gemini response missing candidates")
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if isinstance(candidates[0], dict) else []
    texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict) and str(part.get("text") or "").strip()]
    if not texts:
        raise RuntimeError(f"{BLOCK_FAILED}: Gemini response missing text parts")
    return "\n".join(texts)


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        else:
            cleaned = cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError(f"{BLOCK_FAILED}: Gemini output JSON root must be object")
    return payload


def add_provenance(
    payload: dict[str, Any],
    request: dict[str, Any],
    *,
    provider: str,
    provider_source: str,
    model: str,
    model_source: str,
    pdf_sha256: str,
) -> dict[str, Any]:
    provider_request = request.get("formal_llm_provider_request")
    provider_request_hash = stable_hash(provider_request) if isinstance(provider_request, dict) else None
    provenance = payload.get("_llm_bridge_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance.update(
        {
            "provider_wrapper": "run_factorforge_gemini_step1_provider.py",
            "provider": provider,
            "provider_source": provider_source,
            "provider_api": PROVIDER_API,
            "model": model,
            "model_source": model_source,
            "provider_request_contract_version": PROVIDER_REQUEST_CONTRACT_VERSION,
            "provider_request_hash": provider_request_hash,
            "role": request.get("role"),
            "report_id": request.get("report_id"),
            "prompt_name": request.get("prompt_name"),
            "prompt_hash": request.get("prompt_hash"),
            "pdf_sha256": pdf_sha256,
            "formal_llm_extraction": True,
            "fixture_only": False,
            "request_version": request.get("version"),
        }
    )
    payload["_llm_bridge_provenance"] = provenance
    return payload


def main() -> int:
    try:
        request = read_request()
        role = str(request.get("role") or "")
        report_id = str(request.get("report_id") or "")
        if request.get("version") != "factorforge_step1_llm_bridge_v1":
            raise RuntimeError(f"{BLOCK_FAILED}: unsupported bridge request version={request.get('version')!r}")
        if role not in {"primary", "challenger", "chief"}:
            raise RuntimeError(f"{BLOCK_FAILED}: unsupported Step1 role={role!r}")
        provider, provider_source = resolve_provider(request)
        model, model_source = resolve_model(request)
        path, pdf_data, actual_pdf_sha = pdf_payload(request)
        key = api_key()
        eprint(f"[factorforge-gemini-step1] role={role} report_id={report_id} model={model} pdf={path} pdf_sha256={actual_pdf_sha}")
        body = call_gemini(request=request, model=model, pdf_data=pdf_data, pdf_sha256=actual_pdf_sha, key=key)
        payload = extract_json_object(extract_text(body))
        payload = add_provenance(
            payload,
            request,
            provider=provider,
            provider_source=provider_source,
            model=model,
            model_source=model_source,
            pdf_sha256=actual_pdf_sha,
        )
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except Exception as exc:  # noqa: BLE001 - provider command must fail cleanly for bridge.
        text = str(exc)
        if text.startswith(BLOCK_UNAVAILABLE) or text.startswith(BLOCK_FAILED):
            eprint(text)
        else:
            eprint(f"{BLOCK_FAILED}: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
