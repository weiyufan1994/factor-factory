#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
    resolve_path,
    write_active_registry,
    write_proof_ledger,
)
from factor_factory.ssm_control import get_command_invocation, send_worker_command
from scripts.factorforge_run_registry import (
    allocate_formal_run_root,
    assert_formal_run_root_allowed,
)

BLOCK_WORKER_COMMAND_FAILED = "BLOCK_WORKER_COMMAND_FAILED"
BLOCK_WORKER_SSM_TIMEOUT = "BLOCK_WORKER_SSM_TIMEOUT"
BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP = "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP"


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


def normalize_local_step(step: str) -> str:
    key = step.strip().lower().replace("_", "").replace("-", "")
    aliases = {"1": "1", "step1": "1", "2": "2", "step2": "2", "3": "3a", "3a": "3a", "step3": "3a", "step3a": "3a", "6": "6", "step6": "6"}
    if key not in aliases:
        raise FactorForgeBlock(BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP, f"unsupported local step: {step}")
    return aliases[key]


def cmd_run_local(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    start = normalize_local_step(args.start_step)
    end = normalize_local_step(args.end_step)
    root = resolve_path(run["artifact_root"])
    requested = [start, end]
    # V2 control-plane guard: local execution is wired explicitly; Step1 still
    # requires OpenClaw runtime integration and must not be silently faked.
    payload = pass_payload(report_id=args.report_id, run=run, command="run-local", requested_steps=requested)
    run["status"] = "RUNNING"
    run["current_step"] = start
    run.setdefault("steps", {}).setdefault(start, {"status": "PENDING"})
    update_run(path, registry, args.report_id, run)
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


def worker_command(run: dict[str, Any], *, start_step: str, end_step: str) -> list[str]:
    return [
        "set -eu",
        f"export FACTORFORGE_ROOT={json.dumps(run['artifact_root'])}",
        f"export FACTORFORGE_ACTIVE_RUN_ID={json.dumps(run.get('run_id'))}",
        f"export FACTORFORGE_REPORT_ID={json.dumps(run.get('report_id'))}",
        "cd /opt/factorforge/factor-factory-production",
        f'test "$(git rev-parse HEAD)" = {json.dumps(run.get("repo_sha"))}',
        "test -z \"$(git status --short)\"",
        "python3 scripts/run_factorforge_ultimate.py "
        f"--report-id {json.dumps(run.get('report_id'))} "
        "\"--factorforge-root\" \"$FACTORFORGE_ROOT\" "
        f"--start-step {start_step} --end-step {end_step} --council-mode off",
    ]


def cmd_run_worker(args: argparse.Namespace) -> int:
    path, registry, run = load_run(args)
    start = normalize_worker_step(args.start_step)
    end = normalize_worker_step(args.end_step)
    root = resolve_path(run["artifact_root"])
    commands = worker_command(run, start_step=start, end_step=end)
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

    run_local = sub.add_parser("run-local")
    run_local.add_argument("--registry", dest="sub_registry", default=None)
    run_local.add_argument("--report-id", required=True)
    run_local.add_argument("--artifact-root", default=None)
    run_local.add_argument("--start-step", required=True)
    run_local.add_argument("--end-step", required=True)
    run_local.set_defaults(func=cmd_run_local)

    run_worker = sub.add_parser("run-worker")
    run_worker.add_argument("--registry", dest="sub_registry", default=None)
    run_worker.add_argument("--report-id", required=True)
    run_worker.add_argument("--artifact-root", default=None)
    run_worker.add_argument("--worker-instance-id", required=True)
    run_worker.add_argument("--start-step", required=True)
    run_worker.add_argument("--end-step", required=True)
    run_worker.add_argument("--poll", action="store_true")
    run_worker.add_argument("--timeout-seconds", type=int, default=7200)
    run_worker.add_argument("--poll-interval-seconds", type=int, default=10)
    run_worker.set_defaults(func=cmd_run_worker)
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
