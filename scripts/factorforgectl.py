#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.run_control import (
    FactorForgeBlock,
    active_run_for_report,
    assert_active_identity,
    block_payload,
    current_repo_sha,
    default_registry_path,
    load_active_registry,
    pass_payload,
    proof_ledger_path,
    resolve_path,
    utc_now,
    write_active_registry,
    write_proof_ledger,
)
from factor_factory.ssm_control import (
    describe_ec2_instance,
    describe_ssm_instance,
    get_command_invocation,
    send_worker_command,
    start_ec2_instance,
    stop_ec2_instance,
    wait_ec2_instance_state,
)
from scripts.factorforge_run_registry import (
    allocate_formal_run_root,
    assert_formal_run_root_allowed,
)

BLOCK_WORKER_COMMAND_FAILED = "BLOCK_WORKER_COMMAND_FAILED"
BLOCK_WORKER_SSM_TIMEOUT = "BLOCK_WORKER_SSM_TIMEOUT"
BLOCK_WORKER_READINESS_FAILED = "BLOCK_WORKER_READINESS_FAILED"
BLOCK_WORKER_RUNTIME_CONTEXT_INVALID = "BLOCK_WORKER_RUNTIME_CONTEXT_INVALID"
BLOCK_WORKER_ARTIFACT_SYNC_REQUIRED = "BLOCK_WORKER_ARTIFACT_SYNC_REQUIRED"
BLOCK_WORKER_ARTIFACT_SYNC_FAILED = "BLOCK_WORKER_ARTIFACT_SYNC_FAILED"
BLOCK_WORKER_ARTIFACT_SYNC_S3_URI_REQUIRED = "BLOCK_WORKER_ARTIFACT_SYNC_S3_URI_REQUIRED"
BLOCK_WORKER_LIFECYCLE_FAILED = "BLOCK_WORKER_LIFECYCLE_FAILED"
BLOCK_WORKER_STOP_REQUIRES_USER_ACCEPTANCE = "BLOCK_WORKER_STOP_REQUIRES_USER_ACCEPTANCE"
BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP = "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP"
BLOCK_STEP1_TASK_PACKET_MISSING = "BLOCK_AGENT_TOOL_STEP1_TASK_PACKET_MISSING"
BLOCK_STEP1_TASK_PACKET_INVALID = "BLOCK_AGENT_TOOL_STEP1_TASK_PACKET_INVALID"
BLOCK_STEP1_RAW_INVALID = "BLOCK_AGENT_TOOL_STEP1_RAW_INVALID"
BLOCK_LOCAL_REPORT_PDF_REQUIRED = "BLOCK_LOCAL_REPORT_PDF_REQUIRED"
BLOCK_LOCAL_PREPARE_FAILED = "BLOCK_FACTORFORGE_LOCAL_PREPARE_FAILED"
BLOCK_ACTIVE_RUN_REPO_SHA_MISMATCH = "BLOCK_ACTIVE_RUN_REPO_SHA_MISMATCH"
BLOCK_FORMAL_LLM_FIXTURE_FORBIDDEN = "BLOCK_FORMAL_LLM_FIXTURE_FORBIDDEN"
AGENT_TOOL_TASK_VERSION = "factorforge_step1_agent_tool_task_packet_v1"
AGENT_TOOL_PROVIDER = "openclaw_pdf_tool"
AGENT_TOOL_MODEL = "google/gemini-3.1-pro-preview"


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def registry_path(args: argparse.Namespace) -> Path:
    requested = getattr(args, "sub_registry", None) or getattr(args, "registry", None)
    return resolve_path(requested) if requested else default_registry_path().expanduser()


def load_run(args: argparse.Namespace) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = registry_path(args)
    registry = load_active_registry(path)
    run = active_run_for_report(registry, args.report_id)
    requested_root = Path(args.artifact_root).expanduser() if getattr(args, "artifact_root", None) else None
    assert_active_identity(run, report_id=args.report_id, artifact_root=requested_root)
    return path, registry, run


def update_run(path: Path, registry: dict[str, Any], report_id: str, run: dict[str, Any]) -> None:
    registry.setdefault("active_runs", {})[report_id] = run
    write_active_registry(path, registry)


def default_archive_root(report_id: str) -> Path:
    base = Path(os.getenv("FACTORFORGE_PRODUCTION_RUN_ARCHIVE_ROOT", "/var/lib/factorforge/artifacts")).expanduser()
    return base / report_id


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"missing JSON file: {path}", payload={"path": str(path)}) from exc
    except json.JSONDecodeError as exc:
        raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"invalid JSON file: {path}: {exc}", payload={"path": str(path)}) from exc
    if not isinstance(payload, dict):
        raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"JSON payload is not an object: {path}", payload={"path": str(path)})
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_pdf_input(args: argparse.Namespace, run: dict[str, Any]) -> Path:
    raw = getattr(args, "report_pdf", None)
    report_pdf = run.get("report_pdf") if isinstance(run.get("report_pdf"), dict) else {}
    if not raw:
        for key in ("local_path", "local_pdf_path", "report_pdf", "pdf_path", "local_cache_path", "manifest_path"):
            value = report_pdf.get(key)
            if isinstance(value, str) and value.strip():
                raw = value
                break
    if not raw:
        raise FactorForgeBlock(
            BLOCK_LOCAL_REPORT_PDF_REQUIRED,
            "run-local requires an explicit local PDF path or local PDF manifest; S3 URI alone is not enough for local Step1/2/3A",
            payload={"report_pdf": report_pdf},
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.exists():
        raise FactorForgeBlock(BLOCK_LOCAL_REPORT_PDF_REQUIRED, f"local PDF path does not exist: {path}", payload={"report_pdf": str(path)})
    return path


def cmd_init_run(args: argparse.Namespace) -> int:
    path = registry_path(args)
    registry = load_active_registry(path)
    archive_root = Path(args.archive_root).expanduser() if args.archive_root else default_archive_root(args.report_id)
    root, manifest = allocate_formal_run_root(
        report_id=args.report_id,
        pdf_sha256=args.report_pdf_sha256,
        step_scope=args.step_scope,
        archive_root=archive_root,
        repo_sha=args.repo_sha or current_repo_sha(),
        step1_provider=args.step1_provider,
        step1_model=args.step1_model,
        step2_provider=args.step2_provider,
        step2_model=args.step2_model,
    )
    run = {
        "report_id": args.report_id,
        "run_id": manifest["run_id"],
        "artifact_root": str(root),
        "repo_sha": manifest["repo_sha"],
        "status": "CREATED",
        "current_step": "step1",
        "report_pdf": {
            "s3_uri": args.report_pdf_s3,
            "sha256": args.report_pdf_sha256,
            "local_path": args.report_pdf_local,
        },
        "providers": manifest.get("steps", {}),
        "steps": {},
        "formal_run_manifest": str(root / "formal_run_manifest.json"),
    }
    registry.setdefault("active_runs", {})[args.report_id] = run
    write_active_registry(path, registry)
    payload = pass_payload(report_id=args.report_id, run=run, command="init-run", registry=str(path), formal_run_manifest=run["formal_run_manifest"])
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def agent_tool_task_packet_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "agent_tool_tasks" / report_id / "step1_openclaw_pdf_task_packet.json"


def raw_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    provenance = payload.get("_llm_bridge_provenance")
    if isinstance(provenance, dict):
        return provenance
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        return provenance
    return payload


def load_step1_task_packet(root: Path, report_id: str, run: dict[str, Any], explicit_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = resolve_path(explicit_path) if explicit_path else agent_tool_task_packet_path(root, report_id)
    if not path.exists():
        raise FactorForgeBlock(BLOCK_STEP1_TASK_PACKET_MISSING, f"missing Step1 agent-tool task packet: {path}", payload={"task_packet": str(path)})
    packet = read_json(path)
    mismatches: list[str] = []
    if packet.get("version") != AGENT_TOOL_TASK_VERSION:
        mismatches.append(f"version expected={AGENT_TOOL_TASK_VERSION} actual={packet.get('version')}")
    if packet.get("report_id") != report_id:
        mismatches.append(f"report_id expected={report_id} actual={packet.get('report_id')}")
    packet_root = packet.get("factorforge_root")
    if packet_root and resolve_path(packet_root) != root:
        mismatches.append(f"factorforge_root expected={root} actual={resolve_path(packet_root)}")
    run_pdf_sha = ((run.get("report_pdf") or {}).get("sha256") or "").strip()
    packet_pdf_sha = str(packet.get("pdf_sha256") or "").strip()
    if run_pdf_sha and packet_pdf_sha != run_pdf_sha:
        mismatches.append(f"pdf_sha256 expected={run_pdf_sha} actual={packet_pdf_sha or 'MISSING'}")
    agent_tool = packet.get("agent_tool") if isinstance(packet.get("agent_tool"), dict) else {}
    if agent_tool.get("provider") != AGENT_TOOL_PROVIDER:
        mismatches.append(f"agent_tool.provider expected={AGENT_TOOL_PROVIDER} actual={agent_tool.get('provider')}")
    if agent_tool.get("model") != AGENT_TOOL_MODEL:
        mismatches.append(f"agent_tool.model expected={AGENT_TOOL_MODEL} actual={agent_tool.get('model')}")
    roles = packet.get("roles")
    if not isinstance(roles, list) or len(roles) != 3:
        mismatches.append("roles must contain primary/challenger/chief")
    else:
        role_names = {role.get("role") for role in roles if isinstance(role, dict)}
        if role_names != {"primary", "challenger", "chief"}:
            mismatches.append(f"roles expected=primary/challenger/chief actual={sorted(str(item) for item in role_names)}")
        for role in roles:
            if not isinstance(role, dict) or not str(role.get("prompt_hash") or "").strip():
                mismatches.append(f"role prompt_hash missing: {role}")
    if mismatches:
        raise FactorForgeBlock(BLOCK_STEP1_TASK_PACKET_INVALID, "; ".join(mismatches[:8]), payload={"task_packet": str(path)})
    return path, packet


def validate_step1_raw_from_packet(root: Path, report_id: str, packet: dict[str, Any]) -> list[dict[str, Any]]:
    pdf_hash = str(packet.get("pdf_sha256") or "").strip()
    raw_records: list[dict[str, Any]] = []
    for role_item in packet["roles"]:
        role = str(role_item["role"])
        path = resolve_path(role_item.get("target_raw_path") or (root / "objects" / "raw_llm" / report_id / "step1" / f"step1_{role}_raw.json"))
        if not path.exists():
            raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"missing {role} raw: {path}", payload={"role": role, "path": str(path)})
        if not (path == root or str(path).startswith(str(root) + os.sep)):
            raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"{role} raw path is outside artifact_root: {path}", payload={"role": role, "path": str(path)})
        payload = read_json(path)
        provenance = raw_provenance(payload)
        required = {
            "report_id": report_id,
            "role": role,
            "provider": AGENT_TOOL_PROVIDER,
            "model": AGENT_TOOL_MODEL,
            "pdf_sha256": pdf_hash,
            "prompt_hash": str(role_item["prompt_hash"]),
            "source_derivation": "agent_tool_formal_route",
        }
        mismatches = []
        for key, expected in required.items():
            actual = str(provenance.get(key) or "").strip()
            if actual != expected:
                mismatches.append(f"{key} expected={expected} actual={actual or 'MISSING'}")
        if not str(provenance.get("created_at_utc") or "").strip():
            mismatches.append("created_at_utc missing")
        if mismatches:
            raise FactorForgeBlock(BLOCK_STEP1_RAW_INVALID, f"role={role} raw provenance mismatch: {mismatches[:8]}", payload={"role": role, "path": str(path)})
        raw_records.append(
            {
                "role": role,
                "path": str(path),
                "prompt_hash": str(role_item["prompt_hash"]),
                "raw_response_sha256": sha256_file(path),
            }
        )
    return raw_records


def cmd_resume_step1(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    task_path, packet = load_step1_task_packet(root, args.report_id, run, args.task_packet)
    raw_records = validate_step1_raw_from_packet(root, args.report_id, packet)
    run["status"] = "STEP1_READY"
    run["current_step"] = "step2"
    run.setdefault("steps", {})["step1"] = {
        "status": "PASS",
        "provider": AGENT_TOOL_PROVIDER,
        "model": AGENT_TOOL_MODEL,
        "source_derivation": "agent_tool_formal_route",
        "task_packet": str(task_path),
        "raw_outputs": raw_records,
        "completed_at_utc": utc_now(),
    }
    update_run(path, registry, args.report_id, run)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="resume-step1",
        step1_status="PASS",
        current_step=run.get("current_step"),
        task_packet=str(task_path),
        raw_outputs=raw_records,
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _, _, run = load_run(args)
    payload = pass_payload(report_id=args.report_id, run=run, command="status", run_status=run.get("status"), current_step=run.get("current_step"), steps=run.get("steps", {}))
    print_json(payload)
    return 0


def cmd_proof(args: argparse.Namespace) -> int:
    _, _, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    assert_formal_run_root_allowed(root)
    existing = root / "objects" / "proof" / f"proof_ledger__{args.report_id}.json"
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="proof",
        run_status=run.get("status"),
        current_step=run.get("current_step"),
        proof_ledger=str(existing) if existing.exists() else None,
        proof_ledger_exists=existing.exists(),
        steps=run.get("steps", {}),
    )
    if not existing.exists():
        proof = write_proof_ledger(root, args.report_id, payload)
        payload["proof_ledger"] = str(proof)
        payload["proof_ledger_exists"] = True
    print_json(payload)
    return 0


def read_optional_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    info: dict[str, Any] = {"path": str(path), "exists": path.exists(), "json_ok": False}
    if not path.exists():
        return None, info
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info
    if not isinstance(payload, dict):
        info["error"] = f"JSON payload is {type(payload).__name__}, expected object"
        return None, info
    info["json_ok"] = True
    return payload, info


def summarize_prepare_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    validators = report.get("validators") if isinstance(report.get("validators"), dict) else {}
    summary: dict[str, Any] = {}
    for name in ("step1", "step2", "step3"):
        item = validators.get(name) if isinstance(validators.get(name), dict) else {}
        summary[name] = {
            "rc": item.get("rc"),
            "verdict": item.get("verdict") or item.get("result"),
            "block_token": item.get("block_token"),
        }
    return {
        "verdict": report.get("verdict"),
        "runtime_context_written": report.get("runtime_context_written"),
        "formal_artifacts_valid": report.get("formal_artifacts_valid"),
        "canonical_report_id_preserved": report.get("canonical_report_id_preserved"),
        "validators": summary,
    }


def recover_block_next_action(run: dict[str, Any], *, report_id: str, root: Path, mismatches: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if mismatches:
        return "BLOCK_ACTIVE_RUN_IDENTITY_UNSAFE", [
            f"python3 scripts/factorforgectl.py init-run --report-id {report_id} ...",
        ]
    status = str(run.get("status") or "")
    current_step = str(run.get("current_step") or "")
    steps = run.get("steps") if isinstance(run.get("steps"), dict) else {}
    step1_status = (steps.get("step1") if isinstance(steps.get("step1"), dict) else {}).get("status")
    step2_status = (steps.get("step2") if isinstance(steps.get("step2"), dict) else {}).get("status")
    step3a_status = (steps.get("step3a") if isinstance(steps.get("step3a"), dict) else {}).get("status")
    if status == "CREATED" and current_step == "step1":
        return "READY_FOR_STEP1_TASK_PACKET", [
            f"python3 scripts/factorforgectl.py run-local --report-id {report_id} --start-step 1 --end-step 1",
        ]
    if status == "BLOCK_AGENT_TOOL_STEP1_REQUIRED" or step1_status == "WAITING_FOR_AGENT_TOOL_RAW":
        return "WAITING_FOR_AGENT_TOOL_STEP1_RAW", [
            "Use OpenClaw tools.pdf against the current task packet only",
            f"python3 scripts/factorforgectl.py resume-step1 --report-id {report_id}",
        ]
    if status == "STEP1_READY" or current_step == "step2":
        return "READY_FOR_STEP2_3A", [
            f"python3 scripts/factorforgectl.py run-local --report-id {report_id} --start-step 2 --end-step 3a --formal-llm-provider command",
        ]
    if step1_status == "PASS" and step2_status == "PASS" and step3a_status == "PASS" and bool(run.get("runtime_context_written")):
        return "READY_FOR_WORKER_PREFLIGHT", [
            f"python3 scripts/factorforgectl.py check-worker --report-id {report_id} --start-step 3b --end-step 5",
        ]
    if status in {"WORKER_PREFLIGHT_READY", "WORKER_ARTIFACT_SYNC_DRY_RUN_READY", "WORKER_DRY_RUN_READY"}:
        return "READY_FOR_USER_WORKER_AUTHORIZATION", [
            f"python3 scripts/factorforgectl.py start-worker --report-id {report_id} --worker-instance-id <instance_id> --poll",
            f"python3 scripts/factorforgectl.py sync-worker-artifacts --report-id {report_id} --worker-instance-id <instance_id> --artifact-sync-s3-uri <s3_uri> --poll",
            f"python3 scripts/factorforgectl.py run-worker --report-id {report_id} --worker-instance-id <instance_id> --start-step 3b --end-step 5 --poll",
        ]
    return "BLOCK_LOCAL_STEPS_INCOMPLETE", [
        f"python3 scripts/factorforgectl.py status --report-id {report_id}",
        f"python3 scripts/factorforgectl.py run-local --report-id {report_id} --start-step 2 --end-step 3a --formal-llm-provider command",
    ]


def cmd_recover_block(args: argparse.Namespace) -> int:
    path, _, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    manifest_path = resolve_path(run.get("formal_run_manifest") or (root / "formal_run_manifest.json"))
    prepare_path = prepare_report_path(root, args.report_id)
    proof_path = proof_ledger_path(root, args.report_id)
    ctx_path = runtime_context_path(root, args.report_id)
    manifest, manifest_info = read_optional_json(manifest_path)
    prepare_report, prepare_info = read_optional_json(prepare_path)
    _, proof_info = read_optional_json(proof_path)
    runtime_context, runtime_info = read_optional_json(ctx_path)

    mismatches: list[dict[str, Any]] = []

    def mismatch(name: str, expected: Any, actual: Any) -> None:
        mismatches.append({"name": name, "expected": expected, "actual": actual})

    current_sha = current_repo_sha()
    registry_sha = str(run.get("repo_sha") or "")
    if registry_sha and registry_sha != current_sha:
        mismatch("registry_repo_sha_matches_current_head", registry_sha, current_sha)
    if not root.exists():
        mismatch("active_artifact_root_exists", True, False)
    if not manifest:
        mismatch("active_manifest_exists_and_parses", True, manifest_info)
    else:
        if manifest.get("report_id") != args.report_id:
            mismatch("manifest_report_id_matches", args.report_id, manifest.get("report_id"))
        if manifest.get("run_id") != run.get("run_id"):
            mismatch("manifest_run_id_matches_registry", run.get("run_id"), manifest.get("run_id"))
        if manifest.get("repo_sha") != run.get("repo_sha"):
            mismatch("manifest_repo_sha_matches_registry", run.get("repo_sha"), manifest.get("repo_sha"))
    if runtime_context and runtime_context.get("report_id") != args.report_id:
        mismatch("runtime_context_report_id_matches", args.report_id, runtime_context.get("report_id"))
    diagnosis, allowed_next_commands = recover_block_next_action(run, report_id=args.report_id, root=root, mismatches=mismatches)
    payload = pass_payload(
        report_id=args.report_id,
        command="recover-block",
        readonly=True,
        active_registry=str(path),
        run=run,
        diagnosis=diagnosis,
        active_artifact_root=str(root),
        authoritative_sources={
            "active_registry": str(path),
            "formal_run_manifest": manifest_info,
            "formal_artifact_prepare_report": prepare_info,
            "proof_ledger": proof_info,
            "runtime_context": runtime_info,
        },
        prepare_report_summary=summarize_prepare_report(prepare_report),
        identity_mismatches=mismatches,
        allowed_next_commands=allowed_next_commands,
        forbidden_actions=[
            "do not show/find/scan old artifact roots",
            "do not read non-active roots unless the user explicitly asks for deprecated evidence",
            "do not patch registry, manifest, raw LLM JSON, or runtime_context",
            "do not skip preflight or use --allow-deterministic-debug for production factor-mining",
            "do not start or stop worker from recover-block",
        ],
    )
    payload["control_verdict"] = "BLOCK" if diagnosis.startswith("BLOCK_") else "PASS"
    print_json(payload)
    return 0


def normalize_local_step(step: str) -> str:
    key = step.strip().lower().replace("_", "").replace("-", "")
    aliases = {"1": "1", "step1": "1", "2": "2", "step2": "2", "3": "3a", "3a": "3a", "step3": "3a", "step3a": "3a", "6": "6", "step6": "6"}
    if key not in aliases:
        raise FactorForgeBlock(BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP, f"unsupported local step: {step}")
    return aliases[key]


def prepare_report_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"


def default_step_raw_paths(root: Path, report_id: str, step: str) -> dict[str, Path]:
    base = root / "objects" / "raw_llm" / report_id / step
    if step == "step1":
        return {
            "primary": base / "step1_primary_raw.json",
            "challenger": base / "step1_challenger_raw.json",
            "chief": base / "step1_chief_raw.json",
        }
    return {
        "primary": base / "step2_primary_raw.json",
        "challenger": base / "step2_challenger_raw.json",
        "auditor": base / "step2_auditor_raw.json",
    }


def run_prepare_command(cmd: list[str], *, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)


def default_step2_llm_command() -> str:
    existing = os.getenv("FACTORFORGE_STEP2_LLM_COMMAND")
    if existing:
        return existing
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(ROOT / 'scripts' / 'run_factorforge_humphrey_llm_provider.py'))}"


def block_token_from_text(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("BLOCK_"):
            return stripped.split(":", 1)[0]
    return BLOCK_LOCAL_PREPARE_FAILED


def update_run_after_prepare_accept(path: Path, registry: dict[str, Any], report_id: str, run: dict[str, Any], *, end: str, report: dict[str, Any] | None) -> None:
    run["status"] = "LOCAL_STEPS_READY"
    run["current_step"] = "step3b" if end == "3a" else {"1": "step2", "2": "step3a"}.get(end, end)
    steps = run.setdefault("steps", {})
    if end in {"1", "2", "3a"}:
        steps.setdefault("step1", {})["status"] = "PASS"
    if end in {"2", "3a"}:
        steps.setdefault("step2", {})["status"] = "PASS"
    if end == "3a":
        steps.setdefault("step3a", {})["status"] = "PASS"
        run["runtime_context_written"] = bool((report or {}).get("runtime_context_written"))
    if report:
        run["last_prepare_report"] = str(prepare_report_path(resolve_path(run["artifact_root"]), report_id))
        run["last_prepare_verdict"] = report.get("verdict")
        run["validators"] = report.get("validators")
    update_run(path, registry, report_id, run)


def cmd_run_local(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    start = normalize_local_step(args.start_step)
    end = normalize_local_step(args.end_step)
    registry_repo_sha = str(run.get("repo_sha") or "")
    actual_repo_sha = current_repo_sha()
    if registry_repo_sha and registry_repo_sha != actual_repo_sha:
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_REPO_SHA_MISMATCH,
            f"active run repo_sha mismatch: registry={registry_repo_sha} current={actual_repo_sha}; start a fresh run",
            payload={"registry_repo_sha": registry_repo_sha, "current_repo_sha": actual_repo_sha},
        )
    if args.formal_llm_provider == "fixture" and not args.allow_deterministic_debug:
        raise FactorForgeBlock(
            BLOCK_FORMAL_LLM_FIXTURE_FORBIDDEN,
            "fixture Step2 provider requires --allow-deterministic-debug and is forbidden for factor-mining production runs",
            payload={"formal_llm_provider": args.formal_llm_provider},
        )
    root = resolve_path(run["artifact_root"])
    report_pdf = report_pdf_input(args, run)
    manifest = run.get("formal_run_manifest") or str(root / "formal_run_manifest.json")
    cmd = [
        sys.executable,
        "scripts/prepare_factorforge_formal_artifacts.py",
        "--factorforge-root",
        str(root),
        "--report-id",
        args.report_id,
        "--report-pdf",
        str(report_pdf),
        "--run-manifest",
        str(manifest),
        "--end-step",
        "1" if end == "1" else ("2" if end == "2" else "3a"),
        "--write-report",
    ]
    if start == "1":
        cmd.extend(["--run-formal-llm-bridges", "--formal-llm-provider", "agent_tool"])
    else:
        step1 = default_step_raw_paths(root, args.report_id, "step1")
        cmd.extend(
            [
                "--step1-primary-raw",
                str(step1["primary"]),
                "--step1-challenger-raw",
                str(step1["challenger"]),
                "--step1-chief-raw",
                str(step1["chief"]),
                "--run-formal-llm-bridges",
                "--formal-llm-provider",
                args.formal_llm_provider,
            ]
        )
        if end == "3a":
            cmd.append("--write-runtime-context")
        if args.allow_deterministic_debug:
            cmd.append("--allow-deterministic-debug")

    providers = run.get("providers") if isinstance(run.get("providers"), dict) else {}
    step1_provider = providers.get("step1") if isinstance(providers.get("step1"), dict) else {}
    step2_provider = providers.get("step2") if isinstance(providers.get("step2"), dict) else {}
    env_overrides = {
        "FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER": str(step1_provider.get("provider") or AGENT_TOOL_PROVIDER),
        "FACTORFORGE_STEP1_LLM_MODEL": str(step1_provider.get("model") or AGENT_TOOL_MODEL),
        "FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER": str(step2_provider.get("provider") or "deepseek"),
        "FACTORFORGE_STEP2_LLM_MODEL": str(step2_provider.get("model") or "deepseek-chat"),
    }
    if start != "1" and args.formal_llm_provider == "command":
        env_overrides["FACTORFORGE_STEP2_LLM_COMMAND"] = default_step2_llm_command()
    proc = run_prepare_command(cmd, env_overrides=env_overrides)
    text = proc.stdout + proc.stderr
    if proc.returncode != 0:
        token = block_token_from_text(text)
        extra: dict[str, Any] = {"prepare_rc": proc.returncode, "stderr_tail": proc.stderr[-2000:], "stdout_tail": proc.stdout[-2000:]}
        if token == "BLOCK_AGENT_TOOL_STEP1_REQUIRED":
            task_path = agent_tool_task_packet_path(root, args.report_id)
            run["status"] = token
            run["current_step"] = "step1"
            run.setdefault("steps", {})["step1"] = {
                "status": "WAITING_FOR_AGENT_TOOL_RAW",
                "task_packet": str(task_path),
            }
            update_run(path, registry, args.report_id, run)
            extra["task_packet"] = str(task_path)
        payload = block_payload(token, text.strip()[-2000:], report_id=args.report_id, **extra)
        if token == "BLOCK_AGENT_TOOL_STEP1_REQUIRED":
            proof = write_proof_ledger(root, args.report_id, payload)
            payload["proof_ledger"] = str(proof)
        print_json(payload)
        return 1

    report = read_json(prepare_report_path(root, args.report_id)) if prepare_report_path(root, args.report_id).exists() else None
    update_run_after_prepare_accept(path, registry, args.report_id, run, end=end, report=report)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="run-local",
        requested_steps=[start, end],
        prepare_rc=proc.returncode,
        prepare_report=str(prepare_report_path(root, args.report_id)),
        prepare_verdict=(report or {}).get("verdict"),
        runtime_context_written=bool((report or {}).get("runtime_context_written")),
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def normalize_worker_step(step: str) -> str:
    key = step.strip().lower().replace("_", "").replace("-", "")
    aliases = {"3b": "3b", "step3b": "3b", "4": "4", "step4": "4", "5": "5", "step5": "5"}
    if key not in aliases:
        raise FactorForgeBlock(BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP, f"unsupported worker step: {step}")
    return aliases[key]


def runtime_context_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"


def worker_readiness_checks(run: dict[str, Any], *, report_id: str, start_step: str, end_step: str) -> list[dict[str, Any]]:
    root = resolve_path(run["artifact_root"])
    assert_formal_run_root_allowed(root)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, **extra: Any) -> None:
        item = {"name": name, "ok": ok}
        item.update(extra)
        checks.append(item)

    expected_sha = str(run.get("repo_sha") or "")
    actual_sha = current_repo_sha()
    add("control_repo_sha_matches_run", actual_sha == expected_sha, expected=expected_sha, actual=actual_sha)
    add("artifact_root_exists", root.exists(), artifact_root=str(root))

    steps = run.get("steps") if isinstance(run.get("steps"), dict) else {}
    for step in ("step1", "step2", "step3a"):
        status = (steps.get(step) if isinstance(steps.get(step), dict) else {}).get("status")
        add(f"{step}_status_pass", status == "PASS", status=status)

    current_step = str(run.get("current_step") or "")
    add("current_step_allows_worker_start", current_step in {start_step, "step3b"}, current_step=current_step, start_step=start_step)

    runtime_written = bool(run.get("runtime_context_written"))
    add("runtime_context_written", runtime_written, runtime_context_written=runtime_written)
    ctx_path = runtime_context_path(root, report_id)
    add("runtime_context_file_exists", ctx_path.exists(), path=str(ctx_path))
    if ctx_path.exists():
        try:
            ctx = read_json(ctx_path)
        except FactorForgeBlock as exc:
            raise FactorForgeBlock(BLOCK_WORKER_RUNTIME_CONTEXT_INVALID, str(exc), payload={"runtime_context": str(ctx_path)}) from exc
        add("runtime_context_report_id_matches", ctx.get("report_id") == report_id, expected=report_id, actual=ctx.get("report_id"))
        ctx_root = ctx.get("artifact_root")
        add("runtime_context_artifact_root_matches", ctx_root in {None, "", str(root)}, expected=str(root), actual=ctx_root)

    failed = [item for item in checks if not item.get("ok")]
    if failed:
        raise FactorForgeBlock(
            BLOCK_WORKER_READINESS_FAILED,
            "worker readiness checks failed",
            payload={"failed_checks": failed, "readiness_checks": checks, "start_step": start_step, "end_step": end_step},
        )
    return checks


def worker_command(run: dict[str, Any], *, start_step: str, end_step: str, worker_repo_root: str) -> list[str]:
    report_id = str(run.get("report_id"))
    runtime_context_check = (
        "import json, os, pathlib; "
        "root = pathlib.Path(os.environ['FACTORFORGE_ROOT']); "
        "report_id = os.environ['FACTORFORGE_REPORT_ID']; "
        "ctx = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'; "
        "print(json.loads(ctx.read_text()).get('report_id'))"
    )
    return [
        "set -eu",
        f"export FACTORFORGE_ROOT={json.dumps(run['artifact_root'])}",
        f"export FACTORFORGE_ACTIVE_RUN_ID={json.dumps(run.get('run_id'))}",
        f"export FACTORFORGE_REPORT_ID={json.dumps(run.get('report_id'))}",
        f"cd {json.dumps(worker_repo_root)}",
        f'test "$(git rev-parse HEAD)" = {json.dumps(run.get("repo_sha"))}',
        "test -z \"$(git status --short)\"",
        "test -d \"$FACTORFORGE_ROOT\"",
        f"test \"$(python3 -c {json.dumps(runtime_context_check)})\" = {json.dumps(report_id)}",
        "python3 scripts/run_factorforge_ultimate.py "
        f"--report-id {json.dumps(run.get('report_id'))} "
        "\"--factorforge-root\" \"$FACTORFORGE_ROOT\" "
        f"--start-step {start_step} --end-step {end_step} --council-mode off",
    ]


def worker_sync_command(run: dict[str, Any], *, artifact_sync_s3_uri: str) -> list[str]:
    report_id = str(run.get("report_id"))
    runtime_context_check = (
        "import json, os, pathlib; "
        "root = pathlib.Path(os.environ['FACTORFORGE_ROOT']); "
        "report_id = os.environ['FACTORFORGE_REPORT_ID']; "
        "ctx = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'; "
        "manifest = json.loads((root / 'formal_run_manifest.json').read_text()); "
        "payload = json.loads(ctx.read_text()); "
        "assert payload.get('report_id') == report_id, payload.get('report_id'); "
        "assert manifest.get('report_id') == report_id, manifest.get('report_id'); "
        "assert manifest.get('repo_sha') == os.environ['FACTORFORGE_REPO_SHA'], manifest.get('repo_sha'); "
        "print('SYNC_ARTIFACT_IDENTITY_OK')"
    )
    return [
        "set -eu",
        f"export FACTORFORGE_ROOT={json.dumps(run['artifact_root'])}",
        f"export FACTORFORGE_REPORT_ID={json.dumps(run.get('report_id'))}",
        f"export FACTORFORGE_ACTIVE_RUN_ID={json.dumps(run.get('run_id'))}",
        f"export FACTORFORGE_REPO_SHA={json.dumps(run.get('repo_sha'))}",
        f"export FACTORFORGE_ARTIFACT_SYNC_S3_URI={json.dumps(artifact_sync_s3_uri)}",
        "mkdir -p \"$(dirname \"$FACTORFORGE_ROOT\")\"",
        "rm -rf \"$FACTORFORGE_ROOT\"",
        "mkdir -p \"$FACTORFORGE_ROOT\"",
        "aws s3 cp \"$FACTORFORGE_ARTIFACT_SYNC_S3_URI\" \"/tmp/${FACTORFORGE_ACTIVE_RUN_ID}.tgz\"",
        "tar -xzf \"/tmp/${FACTORFORGE_ACTIVE_RUN_ID}.tgz\" -C \"$FACTORFORGE_ROOT\"",
        "test -f \"$FACTORFORGE_ROOT/formal_run_manifest.json\"",
        "test -f \"$FACTORFORGE_ROOT/objects/runtime_context/runtime_context__${FACTORFORGE_REPORT_ID}.json\"",
        f"python3 -c {json.dumps(runtime_context_check)}",
    ]


def worker_sync_proof(run: dict[str, Any], *, worker_instance_id: str) -> dict[str, Any] | None:
    sync = run.get("worker_artifact_sync")
    if not isinstance(sync, dict):
        return None
    if sync.get("status") != "PASS":
        return None
    if sync.get("instance_id") != worker_instance_id:
        return None
    if sync.get("run_id") != run.get("run_id"):
        return None
    if sync.get("report_id") != run.get("report_id"):
        return None
    if sync.get("artifact_root") != run.get("artifact_root"):
        return None
    if sync.get("repo_sha") != run.get("repo_sha"):
        return None
    return sync


def wait_for_ssm_online(instance_id: str, *, timeout_seconds: int, poll_interval_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = describe_ssm_instance(instance_id)
    while time.time() < deadline:
        last = describe_ssm_instance(instance_id)
        if last.get("ok") and last.get("ping_status") == "Online":
            return last
        time.sleep(poll_interval_seconds)
    return {"ok": False, "instance_id": instance_id, "timeout_seconds": timeout_seconds, "last_ssm_status": last}


def cmd_start_worker(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    before = describe_ec2_instance(args.worker_instance_id)
    if not before.get("ok"):
        raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "failed to describe worker instance before start", payload=before)
    before_state = before.get("state")
    start_response: dict[str, Any] | None = None
    wait_response: dict[str, Any] | None = None
    ssm_response: dict[str, Any] | None = None
    if before_state == "running":
        after = before
        ssm_response = describe_ssm_instance(args.worker_instance_id)
    elif args.dry_run:
        after = before
    else:
        start_response = start_ec2_instance(args.worker_instance_id)
        if not start_response.get("ok"):
            raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "failed to start worker instance", payload=start_response)
        if args.poll:
            wait_response = wait_ec2_instance_state(args.worker_instance_id, "running")
            if not wait_response.get("ok"):
                raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "worker did not reach running state", payload=wait_response)
            ssm_response = wait_for_ssm_online(
                args.worker_instance_id,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            if not ssm_response.get("ok"):
                raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "worker SSM did not become Online", payload=ssm_response)
        after = describe_ec2_instance(args.worker_instance_id)

    lifecycle = {
        "action": "start-worker",
        "instance_id": args.worker_instance_id,
        "before_state": before_state,
        "after_state": after.get("state") if isinstance(after, dict) else None,
        "dry_run": bool(args.dry_run),
        "poll": bool(args.poll),
        "ssm_ping_status": ssm_response.get("ping_status") if isinstance(ssm_response, dict) else None,
        "created_at_utc": utc_now(),
    }
    run.setdefault("worker_lifecycle", []).append(lifecycle)
    if not args.dry_run and lifecycle.get("after_state") == "running":
        run["worker_instance_state"] = "running"
    update_run(path, registry, args.report_id, run)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="start-worker",
        worker_instance_id=args.worker_instance_id,
        worker_lifecycle=lifecycle,
        worker_start_response=start_response,
        worker_wait_response=wait_response,
        worker_ssm_response=ssm_response,
        worker_started=(not args.dry_run and lifecycle.get("after_state") == "running"),
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def cmd_stop_worker(args: argparse.Namespace) -> int:
    if not args.after_user_acceptance and not args.dry_run:
        raise FactorForgeBlock(
            BLOCK_WORKER_STOP_REQUIRES_USER_ACCEPTANCE,
            "real stop-worker requires --after-user-acceptance",
            payload={"worker_instance_id": args.worker_instance_id},
        )
    path, registry, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    before = describe_ec2_instance(args.worker_instance_id)
    if not before.get("ok"):
        raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "failed to describe worker instance before stop", payload=before)
    before_state = before.get("state")
    stop_response: dict[str, Any] | None = None
    wait_response: dict[str, Any] | None = None
    if before_state == "stopped" or args.dry_run:
        after = before
    else:
        stop_response = stop_ec2_instance(args.worker_instance_id)
        if not stop_response.get("ok"):
            raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "failed to stop worker instance", payload=stop_response)
        if args.poll:
            wait_response = wait_ec2_instance_state(args.worker_instance_id, "stopped")
            if not wait_response.get("ok"):
                raise FactorForgeBlock(BLOCK_WORKER_LIFECYCLE_FAILED, "worker did not reach stopped state", payload=wait_response)
        after = describe_ec2_instance(args.worker_instance_id)

    lifecycle = {
        "action": "stop-worker",
        "instance_id": args.worker_instance_id,
        "before_state": before_state,
        "after_state": after.get("state") if isinstance(after, dict) else None,
        "dry_run": bool(args.dry_run),
        "poll": bool(args.poll),
        "after_user_acceptance": bool(args.after_user_acceptance),
        "created_at_utc": utc_now(),
    }
    run.setdefault("worker_lifecycle", []).append(lifecycle)
    if not args.dry_run and lifecycle.get("after_state") == "stopped":
        run["worker_instance_state"] = "stopped"
    update_run(path, registry, args.report_id, run)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="stop-worker",
        worker_instance_id=args.worker_instance_id,
        worker_lifecycle=lifecycle,
        worker_stop_response=stop_response,
        worker_wait_response=wait_response,
        worker_stopped=(not args.dry_run and lifecycle.get("after_state") == "stopped"),
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def make_artifact_archive(root: Path, run_id: str) -> Path:
    archive = Path(tempfile.gettempdir()) / f"factorforge_artifact_sync__{run_id}.tgz"
    proc = subprocess.run(["tar", "-czf", str(archive), "-C", str(root), "."], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise FactorForgeBlock(BLOCK_WORKER_ARTIFACT_SYNC_FAILED, "failed to create artifact archive", payload={"stderr": proc.stderr, "stdout": proc.stdout})
    return archive


def upload_archive_to_s3(archive: Path, s3_uri: str) -> None:
    proc = subprocess.run(["aws", "s3", "cp", str(archive), s3_uri], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise FactorForgeBlock(
            BLOCK_WORKER_ARTIFACT_SYNC_FAILED,
            "failed to upload artifact archive to S3",
            payload={"s3_uri": s3_uri, "stderr": proc.stderr, "stdout": proc.stdout, "returncode": proc.returncode},
        )


def cmd_sync_worker_artifacts(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    root = resolve_path(run["artifact_root"])
    start = normalize_worker_step(args.start_step)
    end = normalize_worker_step(args.end_step)
    checks = worker_readiness_checks(run, report_id=args.report_id, start_step=start, end_step=end)
    artifact_sync_s3_uri = str(args.artifact_sync_s3_uri or "").strip()
    if not artifact_sync_s3_uri:
        raise FactorForgeBlock(BLOCK_WORKER_ARTIFACT_SYNC_S3_URI_REQUIRED, "--artifact-sync-s3-uri is required for worker artifact sync")
    commands = worker_sync_command(run, artifact_sync_s3_uri=artifact_sync_s3_uri)
    if args.dry_run:
        run["status"] = "WORKER_ARTIFACT_SYNC_DRY_RUN_READY"
        run["current_step"] = start
        run["worker_artifact_sync"] = {
            "status": "DRY_RUN_READY",
            "instance_id": args.worker_instance_id,
            "report_id": args.report_id,
            "run_id": run.get("run_id"),
            "artifact_root": run.get("artifact_root"),
            "repo_sha": run.get("repo_sha"),
            "artifact_sync_s3_uri": artifact_sync_s3_uri,
            "dry_run": True,
        }
        update_run(path, registry, args.report_id, run)
        payload = pass_payload(
            report_id=args.report_id,
            run=run,
            command="sync-worker-artifacts",
            worker_artifact_sync_dry_run=True,
            worker_started=False,
            artifact_synced=False,
            ssm_command_id=None,
            artifact_sync_s3_uri=artifact_sync_s3_uri,
            worker_sync_command=commands,
            readiness_checks=checks,
        )
        proof = write_proof_ledger(root, args.report_id, payload)
        payload["proof_ledger"] = str(proof)
        print_json(payload)
        return 0

    archive = make_artifact_archive(root, str(run.get("run_id")))
    upload_archive_to_s3(archive, artifact_sync_s3_uri)
    sent = send_worker_command(args.worker_instance_id, commands, comment=f"FactorForge sync artifacts {args.report_id}")
    if not sent.get("ok"):
        raise FactorForgeBlock(BLOCK_WORKER_ARTIFACT_SYNC_FAILED, "aws ssm send-command failed for artifact sync", payload=sent)
    command_id = ((sent.get("Command") or {}).get("CommandId")) if isinstance(sent.get("Command"), dict) else None
    final_invocation = None
    sync_status = "SYNCING"
    if args.poll and command_id:
        deadline = time.time() + args.timeout_seconds
        while time.time() < deadline:
            final_invocation = get_command_invocation(args.worker_instance_id, command_id)
            status = final_invocation.get("Status")
            if status in {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}:
                break
            time.sleep(args.poll_interval_seconds)
        if final_invocation is None or final_invocation.get("Status") not in {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise FactorForgeBlock(BLOCK_WORKER_SSM_TIMEOUT, f"worker artifact sync timed out: {command_id}", payload={"command_id": command_id})
        if final_invocation.get("Status") != "Success":
            raise FactorForgeBlock(BLOCK_WORKER_ARTIFACT_SYNC_FAILED, "worker artifact sync command failed", payload={"command_id": command_id, "ssm_invocation": final_invocation})
        sync_status = "PASS"

    run["status"] = "WORKER_ARTIFACT_SYNCED" if sync_status == "PASS" else "WORKER_ARTIFACT_SYNCING"
    run["current_step"] = start
    run["worker_artifact_sync"] = {
        "status": sync_status,
        "instance_id": args.worker_instance_id,
        "command_id": command_id,
        "report_id": args.report_id,
        "run_id": run.get("run_id"),
        "artifact_root": run.get("artifact_root"),
        "repo_sha": run.get("repo_sha"),
        "archive_path": str(archive),
        "artifact_sync_s3_uri": artifact_sync_s3_uri,
        "synced_at_utc": utc_now() if sync_status == "PASS" else None,
    }
    update_run(path, registry, args.report_id, run)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="sync-worker-artifacts",
        worker_artifact_sync_dry_run=False,
        worker_started=False,
        artifact_synced=(sync_status == "PASS"),
        ssm_command_id=command_id,
        ssm_invocation=final_invocation,
        artifact_sync_s3_uri=artifact_sync_s3_uri,
        worker_sync_command=commands,
        readiness_checks=checks,
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def cmd_check_worker(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    start = normalize_worker_step(args.start_step)
    end = normalize_worker_step(args.end_step)
    root = resolve_path(run["artifact_root"])
    checks = worker_readiness_checks(run, report_id=args.report_id, start_step=start, end_step=end)
    commands = worker_command(run, start_step=start, end_step=end, worker_repo_root=args.worker_repo_root)
    run["status"] = "WORKER_PREFLIGHT_READY"
    run["current_step"] = start
    run.setdefault("worker_preflights", []).append(
        {
            "checked_at_utc": utc_now(),
            "start_step": start,
            "end_step": end,
            "worker_repo_root": args.worker_repo_root,
            "readiness_checks": checks,
        }
    )
    update_run(path, registry, args.report_id, run)
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="check-worker",
        worker_preflight_ready=True,
        worker_started=False,
        worker_repo_root=args.worker_repo_root,
        requested_steps=[start, end],
        readiness_checks=checks,
        worker_command=commands,
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def cmd_run_worker(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    start = normalize_worker_step(args.start_step)
    end = normalize_worker_step(args.end_step)
    root = resolve_path(run["artifact_root"])
    checks = worker_readiness_checks(run, report_id=args.report_id, start_step=start, end_step=end)
    commands = worker_command(run, start_step=start, end_step=end, worker_repo_root=args.worker_repo_root)
    if args.dry_run:
        run["status"] = "WORKER_DRY_RUN_READY"
        run["current_step"] = start
        run.setdefault("worker_commands", []).append(
            {
                "instance_id": args.worker_instance_id,
                "command_id": None,
                "start_step": start,
                "end_step": end,
                "dry_run": True,
                "worker_repo_root": args.worker_repo_root,
            }
        )
        update_run(path, registry, args.report_id, run)
        payload = pass_payload(
            report_id=args.report_id,
            run=run,
            command="run-worker",
            worker_instance_id=args.worker_instance_id,
            ssm_command_id=None,
            worker_command=commands,
            worker_dry_run=True,
            worker_started=False,
            worker_repo_root=args.worker_repo_root,
            readiness_checks=checks,
        )
        proof = write_proof_ledger(root, args.report_id, payload)
        payload["proof_ledger"] = str(proof)
        print_json(payload)
        return 0
    sync = worker_sync_proof(run, worker_instance_id=args.worker_instance_id)
    if sync is None:
        raise FactorForgeBlock(
            BLOCK_WORKER_ARTIFACT_SYNC_REQUIRED,
            "worker artifact sync PASS proof is required before real worker dispatch",
            payload={"worker_instance_id": args.worker_instance_id, "artifact_root": run.get("artifact_root")},
        )
    sent = send_worker_command(args.worker_instance_id, commands, comment=f"FactorForge {args.report_id} {start}-{end}")
    if not sent.get("ok"):
        raise FactorForgeBlock(BLOCK_WORKER_COMMAND_FAILED, "aws ssm send-command failed", payload=sent)
    command_id = ((sent.get("Command") or {}).get("CommandId")) if isinstance(sent.get("Command"), dict) else None
    run["status"] = "RUNNING"
    run["current_step"] = start
    run.setdefault("worker_commands", []).append({"instance_id": args.worker_instance_id, "command_id": command_id, "start_step": start, "end_step": end})
    update_run(path, registry, args.report_id, run)
    final_invocation = None
    if args.poll and command_id:
        deadline = time.time() + args.timeout_seconds
        while time.time() < deadline:
            final_invocation = get_command_invocation(args.worker_instance_id, command_id)
            status = final_invocation.get("Status")
            if status in {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}:
                break
            time.sleep(args.poll_interval_seconds)
        if final_invocation is None or final_invocation.get("Status") not in {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise FactorForgeBlock(BLOCK_WORKER_SSM_TIMEOUT, f"worker command timed out: {command_id}", payload={"command_id": command_id})
    payload = pass_payload(
        report_id=args.report_id,
        run=run,
        command="run-worker",
        worker_instance_id=args.worker_instance_id,
        ssm_command_id=command_id,
        ssm_invocation=final_invocation,
        worker_command=commands,
        worker_dry_run=False,
        worker_started=True,
        worker_repo_root=args.worker_repo_root,
        readiness_checks=checks,
    )
    proof = write_proof_ledger(root, args.report_id, payload)
    payload["proof_ledger"] = str(proof)
    print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Factor Forge deterministic control-plane CLI.")
    parser.add_argument("--registry", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-run")
    init.add_argument("--registry", dest="sub_registry", default=None)
    init.add_argument("--report-id", required=True)
    init.add_argument("--report-pdf-s3", default=None)
    init.add_argument("--report-pdf-sha256", required=True)
    init.add_argument("--report-pdf-local", default=None)
    init.add_argument("--archive-root", default=None)
    init.add_argument("--repo-sha", default=None)
    init.add_argument("--step-scope", default="step1-step6")
    init.add_argument("--step1-provider", default="openclaw_pdf_tool")
    init.add_argument("--step1-model", default="google/gemini-3.1-pro-preview")
    init.add_argument("--step2-provider", default="deepseek")
    init.add_argument("--step2-model", default="deepseek-chat")
    init.set_defaults(func=cmd_init_run)

    status = sub.add_parser("status")
    status.add_argument("--registry", dest="sub_registry", default=None)
    status.add_argument("--report-id", required=True)
    status.add_argument("--artifact-root", default=None)
    status.set_defaults(func=cmd_status)

    proof = sub.add_parser("proof")
    proof.add_argument("--registry", dest="sub_registry", default=None)
    proof.add_argument("--report-id", required=True)
    proof.add_argument("--artifact-root", default=None)
    proof.set_defaults(func=cmd_proof)

    recover_block = sub.add_parser("recover-block")
    recover_block.add_argument("--registry", dest="sub_registry", default=None)
    recover_block.add_argument("--report-id", required=True)
    recover_block.add_argument("--artifact-root", default=None)
    recover_block.set_defaults(func=cmd_recover_block)

    resume_step1 = sub.add_parser("resume-step1")
    resume_step1.add_argument("--registry", dest="sub_registry", default=None)
    resume_step1.add_argument("--report-id", required=True)
    resume_step1.add_argument("--artifact-root", default=None)
    resume_step1.add_argument("--task-packet", default=None)
    resume_step1.set_defaults(func=cmd_resume_step1)

    run_local = sub.add_parser("run-local")
    run_local.add_argument("--registry", dest="sub_registry", default=None)
    run_local.add_argument("--report-id", required=True)
    run_local.add_argument("--artifact-root", default=None)
    run_local.add_argument("--report-pdf", default=None)
    run_local.add_argument("--start-step", required=True)
    run_local.add_argument("--end-step", required=True)
    run_local.add_argument("--formal-llm-provider", default="command", choices=["command", "fixture"])
    run_local.add_argument("--allow-deterministic-debug", action="store_true")
    run_local.set_defaults(func=cmd_run_local)

    check_worker = sub.add_parser("check-worker")
    check_worker.add_argument("--registry", dest="sub_registry", default=None)
    check_worker.add_argument("--report-id", required=True)
    check_worker.add_argument("--artifact-root", default=None)
    check_worker.add_argument("--worker-instance-id", default=None)
    check_worker.add_argument("--start-step", required=True)
    check_worker.add_argument("--end-step", required=True)
    check_worker.add_argument("--worker-repo-root", default=os.getenv("FACTORFORGE_WORKER_REPO_ROOT", "/opt/factorforge/factor-factory-production"))
    check_worker.set_defaults(func=cmd_check_worker)

    start_worker = sub.add_parser("start-worker")
    start_worker.add_argument("--registry", dest="sub_registry", default=None)
    start_worker.add_argument("--report-id", required=True)
    start_worker.add_argument("--artifact-root", default=None)
    start_worker.add_argument("--worker-instance-id", required=True)
    start_worker.add_argument("--dry-run", action="store_true")
    start_worker.add_argument("--poll", action="store_true")
    start_worker.add_argument("--timeout-seconds", type=int, default=900)
    start_worker.add_argument("--poll-interval-seconds", type=int, default=10)
    start_worker.set_defaults(func=cmd_start_worker)

    sync_worker = sub.add_parser("sync-worker-artifacts")
    sync_worker.add_argument("--registry", dest="sub_registry", default=None)
    sync_worker.add_argument("--report-id", required=True)
    sync_worker.add_argument("--artifact-root", default=None)
    sync_worker.add_argument("--worker-instance-id", required=True)
    sync_worker.add_argument("--artifact-sync-s3-uri", default=os.getenv("FACTORFORGE_ARTIFACT_SYNC_S3_URI"))
    sync_worker.add_argument("--start-step", default="3b")
    sync_worker.add_argument("--end-step", default="5")
    sync_worker.add_argument("--dry-run", action="store_true")
    sync_worker.add_argument("--poll", action="store_true")
    sync_worker.add_argument("--timeout-seconds", type=int, default=1800)
    sync_worker.add_argument("--poll-interval-seconds", type=int, default=10)
    sync_worker.set_defaults(func=cmd_sync_worker_artifacts)

    run_worker = sub.add_parser("run-worker")
    run_worker.add_argument("--registry", dest="sub_registry", default=None)
    run_worker.add_argument("--report-id", required=True)
    run_worker.add_argument("--artifact-root", default=None)
    run_worker.add_argument("--worker-instance-id", required=True)
    run_worker.add_argument("--start-step", required=True)
    run_worker.add_argument("--end-step", required=True)
    run_worker.add_argument("--worker-repo-root", default=os.getenv("FACTORFORGE_WORKER_REPO_ROOT", "/opt/factorforge/factor-factory-production"))
    run_worker.add_argument("--dry-run", action="store_true")
    run_worker.add_argument("--poll", action="store_true")
    run_worker.add_argument("--timeout-seconds", type=int, default=7200)
    run_worker.add_argument("--poll-interval-seconds", type=int, default=10)
    run_worker.set_defaults(func=cmd_run_worker)

    stop_worker = sub.add_parser("stop-worker")
    stop_worker.add_argument("--registry", dest="sub_registry", default=None)
    stop_worker.add_argument("--report-id", required=True)
    stop_worker.add_argument("--artifact-root", default=None)
    stop_worker.add_argument("--worker-instance-id", required=True)
    stop_worker.add_argument("--dry-run", action="store_true")
    stop_worker.add_argument("--poll", action="store_true")
    stop_worker.add_argument("--after-user-acceptance", action="store_true")
    stop_worker.set_defaults(func=cmd_stop_worker)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report_id = getattr(args, "report_id", None)
    try:
        return int(args.func(args))
    except FactorForgeBlock as exc:
        extra = dict(exc.payload)
        extra.pop("report_id", None)
        print_json(block_payload(exc.token, str(exc), report_id=report_id, **extra))
        return 1
    except SystemExit as exc:
        text = str(exc)
        token = text.split(":", 1)[0] if text.startswith("BLOCK_") else "BLOCK_FACTORFORGECTL_SYSTEM_EXIT"
        print_json(block_payload(token, text, report_id=report_id))
        return int(exc.code) if isinstance(exc.code, int) and exc.code else 1
    except Exception as exc:
        print_json(block_payload("BLOCK_FACTORFORGECTL_UNHANDLED", f"{type(exc).__name__}: {exc}", report_id=report_id))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
