#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


BLOCK_UNAVAILABLE = "BLOCK_FORMAL_GEMINI_BRIDGE_UNAVAILABLE"
BLOCK_FAILED = "BLOCK_FORMAL_GEMINI_BRIDGE_FAILED"
BRIDGE_VERSION = "factorforge_step1_llm_bridge_v1"
PROVIDER_REQUEST_CONTRACT_VERSION = "factorforge_formal_llm_provider_request_v1"
OPENCLAW_PDF_TOOL_REQUEST_VERSION = "factorforge_openclaw_pdf_tool_request_v1"
PROVIDER_API = "openclaw-pdf-tool"


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
        raise RuntimeError(f"{BLOCK_UNAVAILABLE}: empty stdin bridge request")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{BLOCK_FAILED}: bridge request must be a JSON object")
    return payload


def resolve_provider_request(request: dict[str, Any]) -> dict[str, Any]:
    raw = request.get("formal_llm_provider_request")
    if not isinstance(raw, dict):
        raise RuntimeError(f"{BLOCK_FAILED}: formal_llm_provider_request object is required")
    contract_version = str(raw.get("contract_version") or "").strip()
    if contract_version != PROVIDER_REQUEST_CONTRACT_VERSION:
        raise RuntimeError(f"{BLOCK_FAILED}: unsupported provider_request contract_version={contract_version!r}")
    provider = str(raw.get("provider") or os.getenv("FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER") or "").strip()
    model = str(raw.get("model") or os.getenv("FACTORFORGE_STEP1_LLM_MODEL") or "").strip()
    if not provider:
        raise RuntimeError(f"{BLOCK_FAILED}: provider is required")
    if not model:
        raise RuntimeError(f"{BLOCK_FAILED}: model is required")
    return {
        "contract_version": contract_version,
        "step": str(raw.get("step") or "step1"),
        "provider": provider,
        "model": model,
        "provider_source": str(raw.get("provider_source") or "formal_llm_provider_request"),
        "model_source": str(raw.get("model_source") or "formal_llm_provider_request"),
        "temperature": raw.get("temperature"),
        "request_hash": stable_hash(raw),
    }


def pdf_payload(request: dict[str, Any]) -> tuple[Path, str]:
    raw_path = str(request.get("pdf_path") or "").strip()
    if not raw_path:
        raise RuntimeError(f"{BLOCK_FAILED}: request.pdf_path is required")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise RuntimeError(f"{BLOCK_FAILED}: pdf_path does not exist: {path}")
    actual_sha = sha256_bytes(path.read_bytes())
    expected_sha = str(request.get("pdf_sha256") or "").strip()
    if expected_sha and expected_sha != actual_sha:
        raise RuntimeError(f"{BLOCK_FAILED}: pdf_sha256 mismatch expected={expected_sha} actual={actual_sha}")
    return path, actual_sha


def tool_command() -> str:
    command = os.getenv("FACTORFORGE_OPENCLAW_PDF_TOOL_COMMAND") or os.getenv("OPENCLAW_PDF_TOOL_COMMAND")
    if not command:
        raise RuntimeError(
            f"{BLOCK_UNAVAILABLE}: FACTORFORGE_OPENCLAW_PDF_TOOL_COMMAND is required to call the OpenClaw pdf tool"
        )
    return command


def build_pdf_tool_request(request: dict[str, Any], provider_request: dict[str, Any], pdf_path: Path, pdf_sha256: str) -> dict[str, Any]:
    return {
        "version": OPENCLAW_PDF_TOOL_REQUEST_VERSION,
        "tool": "pdf",
        "role": request.get("role"),
        "report_id": request.get("report_id"),
        "pdf": str(pdf_path),
        "pdf_sha256": pdf_sha256,
        "prompt": request.get("prompt"),
        "prior_outputs": request.get("prior_outputs") or {},
        "model": provider_request["model"],
        "provider": provider_request["provider"],
        "prompt_name": request.get("prompt_name"),
        "prompt_hash": request.get("prompt_hash"),
        "response_contract": "strict_step1_raw_json_stdout_only",
    }


def run_openclaw_pdf_tool(tool_request: dict[str, Any]) -> str:
    proc = subprocess.run(
        shlex.split(tool_command()),
        input=json.dumps(tool_request, ensure_ascii=False),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{BLOCK_FAILED}: OpenClaw pdf tool rc={proc.returncode} stderr={proc.stderr[-1200:]}")
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError(f"{BLOCK_FAILED}: OpenClaw pdf tool returned empty stdout")
    if proc.stderr.strip():
        eprint(proc.stderr.strip()[-1200:])
    return output


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError(f"{BLOCK_FAILED}: OpenClaw pdf tool output JSON root must be object")
    return payload


def extract_raw_payload(tool_output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = extract_json_object(tool_output)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    content = payload.get("content")
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                text_parts.append(item["text"])
            elif isinstance(item, str) and item.strip():
                text_parts.append(item)
        if text_parts:
            return extract_json_object("\n".join(text_parts)), details
    if isinstance(payload.get("text"), str) and payload["text"].strip():
        return extract_json_object(payload["text"]), details
    return payload, details


def add_provenance(
    payload: dict[str, Any],
    request: dict[str, Any],
    provider_request: dict[str, Any],
    *,
    pdf_sha256: str,
    tool_request_hash: str,
    tool_details: dict[str, Any],
) -> dict[str, Any]:
    provenance = payload.get("_llm_bridge_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance.update(
        {
            "provider_wrapper": "run_factorforge_openclaw_pdf_step1_provider.py",
            "provider": "openclaw_pdf_tool",
            "provider_api": PROVIDER_API,
            "underlying_provider": provider_request["provider"],
            "model": provider_request["model"],
            "model_source": provider_request.get("model_source"),
            "role": request.get("role"),
            "report_id": request.get("report_id"),
            "prompt_name": request.get("prompt_name"),
            "prompt_hash": request.get("prompt_hash"),
            "pdf_sha256": pdf_sha256,
            "formal_llm_extraction": True,
            "fixture_only": False,
            "source_derivation": "openclaw_pdf_tool/gemini",
            "provider_request_contract_version": PROVIDER_REQUEST_CONTRACT_VERSION,
            "provider_request_hash": provider_request.get("request_hash"),
            "openclaw_pdf_tool_request_version": OPENCLAW_PDF_TOOL_REQUEST_VERSION,
            "openclaw_pdf_tool_request_hash": tool_request_hash,
            "openclaw_pdf_tool_details": tool_details,
        }
    )
    payload["_llm_bridge_provenance"] = provenance
    payload["provider"] = "openclaw_pdf_tool"
    existing_source = payload.get("source_derivation")
    if not isinstance(existing_source, dict):
        payload["source_derivation"] = {
            "source": "openclaw_pdf_tool/gemini",
            "provider": "openclaw_pdf_tool",
            "underlying_provider": provider_request["provider"],
            "model": provider_request["model"],
            "not_fallback": True,
            "pdf_sha256": pdf_sha256,
        }
    return payload


def main() -> int:
    try:
        request = read_request()
        if request.get("version") != BRIDGE_VERSION:
            raise RuntimeError(f"{BLOCK_FAILED}: unsupported bridge request version={request.get('version')!r}")
        role = str(request.get("role") or "")
        if role not in {"primary", "challenger", "chief"}:
            raise RuntimeError(f"{BLOCK_FAILED}: unsupported Step1 role={role!r}")
        provider_request = resolve_provider_request(request)
        pdf_path, pdf_sha256 = pdf_payload(request)
        tool_request = build_pdf_tool_request(request, provider_request, pdf_path, pdf_sha256)
        tool_request_hash = stable_hash(tool_request)
        eprint(
            "[factorforge-openclaw-pdf-step1] "
            f"role={role} report_id={request.get('report_id')} model={provider_request['model']} "
            f"pdf={pdf_path} pdf_sha256={pdf_sha256}"
        )
        raw_payload, tool_details = extract_raw_payload(run_openclaw_pdf_tool(tool_request))
        raw_payload = add_provenance(
            raw_payload,
            request,
            provider_request,
            pdf_sha256=pdf_sha256,
            tool_request_hash=tool_request_hash,
            tool_details=tool_details,
        )
        sys.stdout.write(json.dumps(raw_payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except Exception as exc:  # noqa: BLE001 - command provider must return explicit BLOCK on stderr only.
        message = str(exc)
        if not message.startswith("BLOCK_"):
            message = f"{BLOCK_FAILED}: {type(exc).__name__}: {message}"
        eprint(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
