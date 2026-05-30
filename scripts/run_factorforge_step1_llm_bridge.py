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

BLOCK_PROVIDER = "BLOCK_STEP1_LLM_PROVIDER_UNAVAILABLE"
BLOCK_PROVIDER_FAILED = "BLOCK_STEP1_LLM_PROVIDER_FAILED"
BLOCK_PROVIDER_ROUTING = "BLOCK_STEP1_PROVIDER_ROUTING_MISMATCH"
VERSION = "factorforge_step1_llm_bridge_v1"
PROVIDER_REQUEST_CONTRACT_VERSION = "factorforge_formal_llm_provider_request_v1"
STEP1_ALLOWED_PROVIDER_TOKENS = ("gemini", "google")
STEP1_REQUIRED_MODEL_TOKENS = ("gemini",)

from skills.factor_forge_step1.modules.report_ingestion.intake.pdf_skill_client import PdfSkillClient
from skills.factor_forge_step1.modules.report_ingestion.intake.pdf_skill_prompts import build_step1_report_intake_prompt
from scripts.factorforge_formal_run_manifest import load_required_manifest, validate_manifest


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def formal_llm_provider_request() -> dict[str, Any]:
    provider = os.getenv("FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER") or os.getenv("FACTORFORGE_FORMAL_LLM_PROVIDER")
    model = os.getenv("FACTORFORGE_STEP1_LLM_MODEL")
    payload: dict[str, Any] = {
        "contract_version": PROVIDER_REQUEST_CONTRACT_VERSION,
        "step": "step1",
        "provider_source": (
            "FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER"
            if os.getenv("FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER")
            else "FACTORFORGE_FORMAL_LLM_PROVIDER"
            if provider
            else "provider_wrapper_default"
        ),
        "model_source": "FACTORFORGE_STEP1_LLM_MODEL" if model else "provider_wrapper_default",
    }
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    temperature = os.getenv("FACTORFORGE_STEP1_LLM_TEMPERATURE") or os.getenv("FACTORFORGE_FORMAL_LLM_TEMPERATURE")
    if temperature:
        payload["temperature"] = temperature
    return payload


def assert_step1_provider_routing(provider_request: dict[str, Any]) -> None:
    provider = str(provider_request.get("provider") or "").strip()
    model = str(provider_request.get("model") or "").strip()
    provider_norm = provider.lower()
    model_norm = model.lower()
    provider_ok = bool(provider_norm and any(token in provider_norm for token in STEP1_ALLOWED_PROVIDER_TOKENS))
    model_ok = bool(model_norm and any(token in model_norm for token in STEP1_REQUIRED_MODEL_TOKENS))
    if provider_ok and model_ok:
        return
    raise SystemExit(
        f"{BLOCK_PROVIDER_ROUTING}: Step1 formal PDF extraction/chief merge requires Gemini provider/model; "
        f"provider={provider or 'NOT_SET'} model={model or 'NOT_SET'}"
    )


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


def resolve_report_pdf(raw: str) -> tuple[Path, dict[str, Any]]:
    candidate = resolve_path(raw)
    if candidate.suffix.lower() == ".json" and candidate.exists():
        manifest = read_json(candidate)
        for key in ["local_pdf_path", "report_pdf", "pdf_path", "local_cache_path"]:
            value = manifest.get(key)
            if isinstance(value, str) and value:
                pdf = Path(value).expanduser()
                if not pdf.is_absolute():
                    pdf = (candidate.parent / pdf).resolve()
                if pdf.exists():
                    return pdf, {
                        "input_type": "manifest",
                        "manifest_path": str(candidate),
                        "manifest_sha256": sha256_file(candidate),
                        "manifest_pdf_key": key,
                    }
        s3_uri = manifest.get("s3_uri") or manifest.get("s3_url") or manifest.get("uri")
        raise SystemExit(f"BLOCK_REPORT_PDF_NOT_LOCAL: manifest has no local PDF path; s3_uri={s3_uri}")
    return candidate, {"input_type": "local_pdf"}


def fixture_intake(report_id: str, role: str, provenance: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(REPO_ROOT / "fixtures" / "step1" / "sample_intake_response.json")
    payload["report_id"] = report_id
    payload["_llm_bridge_provenance"] = {**provenance, "role": role}
    if role == "challenger":
        payload.setdefault("ambiguities", []).append("fixture challenger confirms frequency ambiguity remains unresolved")
    return payload


def fixture_chief(report_id: str, provenance: dict[str, Any]) -> dict[str, Any]:
    what_must_be_true = [
        "分钟价量相关性必须反映交易拥挤、注意力或短期冲击状态，而不是纯粹数据噪声。",
        "拥挤交易者或追涨交易者必须在价量共振过强后承担短期反转成本。",
    ]
    what_would_break_it = [
        "价量相关性特征在中性化后无法解释截面收益排序。",
        "分钟频率或相关系数口径与研报定义不一致。",
    ]
    return {
        "report_id": report_id,
        "final_factor": {
            "name": "CPV",
            "assembly_steps": [
                "计算过去20日分钟价量相关系数均值",
                "计算过去20日分钟价量相关系数标准差",
                "计算价量相关系数时间趋势项",
                "做横截面中性化与ZScore标准化",
                "合成为CPV",
            ],
            "accepted_subfactor_names": ["PV_corr_avg", "PV_corr_std", "PV_corr_trend"],
            "direction": "Negative",
            "alpha_strength": "fixture_smoke_only",
            "alpha_source": "fixture_provider",
            "key_implementation_risks": ["分钟频率和相关系数类型需正式研报确认"],
            "economic_logic": "价量相关性异常代表交易拥挤、注意力和短期冲击衰减的组合状态。",
            "economic_logic_provenance": "fixture",
            "behavioral_logic": "追涨和拥挤交易者可能为过强价量共振支付短期反转成本。",
            "behavioral_logic_provenance": "fixture",
            "causal_chain": "分钟价量依赖 -> 拥挤/冲击状态 -> 截面收益排序差异",
            "causal_chain_provenance": "fixture",
            "what_must_be_true": what_must_be_true,
            "what_would_break_it": what_would_break_it,
            "rejected_subfactor_details": [],
        },
        "market_process_thesis": {
            "market_phenomenon": "分钟价量依赖显示拥挤/短期冲击状态",
            "economic_hypothesis": "价量相关性异常代表交易拥挤、注意力和短期冲击衰减的组合状态。",
            "return_source_family": "market_structure_arbitrage",
            "payer_or_counterparty": "追涨和拥挤交易者",
            "why_they_pay": "追涨和拥挤交易者可能为过强价量共振支付短期反转成本。",
            "what_must_be_true": what_must_be_true,
            "what_would_break_it": what_would_break_it,
        },
        "what_must_be_true": what_must_be_true,
        "mechanism_assumptions": what_must_be_true,
        "logic_provenance_summary": {
            "merge_mode": "fixture_llm_bridge",
            "note": "Fixture provider output for smoke tests only; not formal production extraction.",
        },
        "assembly_path": [
            "计算过去20日分钟价量相关系数均值",
            "计算过去20日分钟价量相关系数标准差",
            "计算价量相关系数时间趋势项",
            "做横截面中性化与ZScore标准化",
            "合成为CPV",
        ],
        "unresolved_ambiguities": ["分钟频率未明确", "相关系数类型未明确"],
        "chief_decision_summary": "Use CPV as the canonical fixture factor while preserving implementation ambiguities.",
        "chief_confidence": "medium",
        "chief_rationale": "Primary and challenger fixture routes agree on the core price-volume dependence driver.",
        "_llm_bridge_provenance": {**provenance, "role": "chief"},
    }


def validation_record(report_id: str, role: str, path: Path, prompt_name: str, prompt_hash: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parsed = False
    error = None
    try:
        if role in {"primary", "challenger"}:
            PdfSkillClient().parse_response(report_id, text)
        else:
            payload = json.loads(text)
            parsed = bool(isinstance(payload.get("final_factor"), dict) and payload["final_factor"].get("name"))
        if role in {"primary", "challenger"}:
            parsed = True
    except Exception as exc:  # noqa: BLE001 - report validation status, do not hide bridge failure.
        error = f"{type(exc).__name__}: {exc}"
    return {
        "path": str(path),
        "prompt_name": prompt_name,
        "prompt_hash": prompt_hash,
        "raw_response_sha256": sha256_text(text),
        "parsed_json_valid": parsed,
        "validation_error": error,
    }


def challenger_prompt() -> str:
    return (
        build_step1_report_intake_prompt()
        + "\n\nRole override: you are the challenger reader. Independently identify missing subfactors, formulas, "
        "implementation clues, and ambiguities. Output only the same JSON schema."
    )


def chief_prompt() -> str:
    return (
        "You are the Step1 chief merge agent. Inputs are primary and challenger report-intake JSON. "
        "Output only JSON matching the chief decision structure required by merge_to_alpha_idea_master: "
        "final_factor, logic_provenance_summary, assembly_path, unresolved_ambiguities, "
        "chief_decision_summary, chief_confidence, chief_rationale, market_process_thesis, "
        "what_must_be_true, economic_hypothesis_candidates, preferred_economic_hypothesis, "
        "alternative_return_source_tests, primary_mathematical_model, formula_as_observable_estimator, "
        "and either economic_hypothesis or mechanism_assumptions. "
        "market_process_thesis must include market_phenomenon, economic_hypothesis, return_source_family, "
        "payer_or_counterparty, why_they_pay, what_must_be_true, what_would_break_it, "
        "and alternative_return_source_tests. "
        "Do not default every factor to a stochastic process; choose the primary mathematical model from the economic hypothesis, "
        "then use stochastic process, Ito calculus, linear algebra, optimization, information theory, or causal tests only as "
        "benchmark tools for projection, diagnostic, derivation, or falsification when justified. "
        "Do not invent generic template assumptions; if the raw report does not support a field, leave it missing so validation blocks."
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
    report_pdf: Path,
    pdf_meta: dict[str, Any],
    out_dir: Path,
    *,
    created_at_utc: str,
    role_paths: dict[str, Path],
    prompts: dict[str, tuple[str, str]],
    failed_role: str,
    error: str,
) -> None:
    raw_outputs: dict[str, Any] = {}
    for role, path in role_paths.items():
        if path.exists():
            prompt_name, prompt = prompts[role]
            raw_outputs[role] = validation_record(args.report_id, role, path, prompt_name, sha256_text(prompt))
    write_json(
        out_dir / "step1_llm_bridge_report.json",
        {
            "version": VERSION,
            "report_id": args.report_id,
            "verdict": "BLOCK",
            "block_reason": f"{BLOCK_PROVIDER_FAILED}: role={failed_role}: {error}",
            "pdf_path": str(report_pdf),
            "pdf_sha256": sha256_file(report_pdf),
            "pdf_metadata": pdf_meta,
            "provider": "command",
            "model": os.getenv("FACTORFORGE_STEP1_LLM_MODEL", "external-command"),
            "temperature": os.getenv("FACTORFORGE_STEP1_LLM_TEMPERATURE", "provider_default"),
            "created_at_utc": created_at_utc,
            "fixture_only": False,
            "formal_llm_extraction": False,
            "raw_outputs": raw_outputs,
        },
    )


def build_command(args: argparse.Namespace, report_pdf: Path, pdf_meta: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    command = os.getenv("FACTORFORGE_STEP1_LLM_COMMAND")
    if not command:
        raise SystemExit(f"{BLOCK_PROVIDER}: FACTORFORGE_STEP1_LLM_COMMAND is required for --provider command")
    provider_request = formal_llm_provider_request()
    _, manifest = load_required_manifest(args.run_manifest)
    validate_manifest(
        manifest,
        report_id=args.report_id,
        report_pdf=report_pdf,
        step="step1",
        provider_request=provider_request,
        expected_out_dir=out_dir,
    )
    assert_step1_provider_routing(provider_request)

    created = now_utc()
    prompts = {
        "primary": ("step1_report_intake_primary", build_step1_report_intake_prompt()),
        "challenger": ("step1_report_intake_challenger", challenger_prompt()),
        "chief": ("step1_chief_merge", chief_prompt()),
    }
    role_paths = {
        "primary": out_dir / "step1_primary_raw.json",
        "challenger": out_dir / "step1_challenger_raw.json",
        "chief": out_dir / "step1_chief_raw.json",
    }
    prior_outputs: dict[str, Any] = {}
    for role in ["primary", "challenger", "chief"]:
        prompt_name, prompt = prompts[role]
        request = {
            "version": VERSION,
            "role": role,
            "report_id": args.report_id,
            "pdf_path": str(report_pdf),
            "pdf_sha256": sha256_file(report_pdf),
            "pdf_metadata": pdf_meta,
            "prompt_name": prompt_name,
            "prompt_hash": sha256_text(prompt),
            "prompt": prompt,
            "prior_outputs": prior_outputs,
            "formal_llm_provider_request": provider_request,
        }
        response_text = run_command_provider(command, request)
        path = role_paths[role]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response_text + "\n", encoding="utf-8")
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            write_command_failure_report(
                args,
                report_pdf,
                pdf_meta,
                out_dir,
                created_at_utc=created,
                role_paths=role_paths,
                prompts=prompts,
                failed_role=role,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise SystemExit(f"{BLOCK_PROVIDER_FAILED}: role={role} {type(exc).__name__}: {exc}") from exc
        prior_outputs[role] = payload

    return {
        "version": VERSION,
        "report_id": args.report_id,
        "pdf_path": str(report_pdf),
        "pdf_sha256": sha256_file(report_pdf),
        "pdf_metadata": pdf_meta,
        "provider": "command",
        "model": os.getenv("FACTORFORGE_STEP1_LLM_MODEL", "external-command"),
        "temperature": os.getenv("FACTORFORGE_STEP1_LLM_TEMPERATURE", "provider_default"),
        "created_at_utc": created,
        "fixture_only": False,
        "formal_llm_extraction": True,
        "raw_outputs": {
            "primary": validation_record(args.report_id, "primary", role_paths["primary"], prompts["primary"][0], sha256_text(prompts["primary"][1])),
            "challenger": validation_record(args.report_id, "challenger", role_paths["challenger"], prompts["challenger"][0], sha256_text(prompts["challenger"][1])),
            "chief": validation_record(args.report_id, "chief", role_paths["chief"], prompts["chief"][0], sha256_text(prompts["chief"][1])),
        },
    }


def build_fixture(args: argparse.Namespace, report_pdf: Path, pdf_meta: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    prompt = build_step1_report_intake_prompt()
    prompt_hash = sha256_text(prompt)
    created = now_utc()
    base_provenance = {
        "version": VERSION,
        "report_id": args.report_id,
        "pdf_path": str(report_pdf),
        "pdf_sha256": sha256_file(report_pdf),
        "pdf_metadata": pdf_meta,
        "provider": "fixture",
        "model": "fixture-step1-llm-bridge",
        "temperature": 0,
        "prompt_name": "step1_report_intake_fixture",
        "prompt_hash": prompt_hash,
        "created_at_utc": created,
        "fixture_only": True,
        "formal_production_provider": False,
    }
    primary_path = out_dir / "step1_primary_raw.json"
    challenger_path = out_dir / "step1_challenger_raw.json"
    chief_path = out_dir / "step1_chief_raw.json"
    write_json(primary_path, fixture_intake(args.report_id, "primary", base_provenance))
    write_json(challenger_path, fixture_intake(args.report_id, "challenger", base_provenance))
    write_json(chief_path, fixture_chief(args.report_id, base_provenance))
    return {
        "version": VERSION,
        "report_id": args.report_id,
        "pdf_path": str(report_pdf),
        "pdf_sha256": sha256_file(report_pdf),
        "pdf_metadata": pdf_meta,
        "provider": "fixture",
        "model": "fixture-step1-llm-bridge",
        "temperature": 0,
        "created_at_utc": created,
        "fixture_only": True,
        "formal_llm_extraction": False,
        "raw_outputs": {
            "primary": validation_record(args.report_id, "primary", primary_path, "step1_report_intake_fixture", prompt_hash),
            "challenger": validation_record(args.report_id, "challenger", challenger_path, "step1_report_intake_fixture", prompt_hash),
            "chief": validation_record(args.report_id, "chief", chief_path, "step1_chief_merge_fixture", sha256_text("step1_chief_merge_fixture")),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--report-pdf", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--provider", default=os.getenv("FACTORFORGE_STEP1_LLM_PROVIDER"))
    ap.add_argument("--run-manifest", default=os.getenv("FACTORFORGE_FORMAL_RUN_MANIFEST"))
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()

    try:
        report_pdf, pdf_meta = resolve_report_pdf(args.report_pdf)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not report_pdf.exists():
        print(f"BLOCK_REPORT_PDF_MISSING: {report_pdf}", file=sys.stderr)
        return 1

    if args.provider not in {"fixture", "command"}:
        print(f"{BLOCK_PROVIDER}: configure a real Step1 PDF/LLM provider or use --provider fixture for smoke only", file=sys.stderr)
        return 1

    try:
        if args.provider == "command":
            report = build_command(args, report_pdf, pdf_meta, out_dir)
        else:
            report = build_fixture(args, report_pdf, pdf_meta, out_dir)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - provider bridge must report failure without writing success.
        print(f"{BLOCK_PROVIDER_FAILED}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    report_path = out_dir / "step1_llm_bridge_report.json"
    write_json(report_path, report)
    if args.write_report:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"RESULT: PASS step1 fixture raw outputs written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
