#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RID = "RUN_ISOLATION_SMOKE"
PDF = ROOT / "fixtures" / "step2" / "sample_report_stub.pdf"

from scripts.factorforge_run_registry import (
    BLOCK_FORMAL_RUN_ROOT_FORBIDDEN,
    BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH,
    BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN,
    allocate_formal_run_root,
    assert_smoke_root_allowed,
    current_repo_sha,
)
from scripts.factorforge_formal_run_manifest import validate_manifest


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def pdf_sha() -> str:
    return hashlib.sha256(PDF.read_bytes()).hexdigest()


def manifest_payload(
    *,
    report_id: str,
    root: Path,
    repo_sha: str | None = None,
    pdf_hash: str | None = None,
    step1_provider: str = "google",
    step1_model: str = "gemini-3.1-pro-preview",
    step2_provider: str = "deepseek",
    step2_model: str = "deepseek-v4-pro",
) -> dict[str, Any]:
    return {
        "manifest_version": "factorforge_formal_run_manifest_v1",
        "run_id": f"smoke_{report_id}",
        "created_at_utc": "2026-01-01T00:00:00Z",
        "report_id": report_id,
        "factorforge_root": str(root.resolve()),
        "artifact_root": str(root.resolve()),
        "report_pdf_sha256": pdf_hash or pdf_sha(),
        "repo_sha": repo_sha or current_repo_sha(),
        "step_scope": "smoke",
        "steps": {
            "step1": {"provider": step1_provider, "model": step1_model},
            "step2": {"provider": step2_provider, "model": step2_model},
        },
    }


def provider_script(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "import pathlib, sys\n"
            "sys.stdin.read()\n"
            f"pathlib.Path({str(path.with_suffix('.called'))!r}).write_text('called', encoding='utf-8')\n"
            "print('{}')\n"
        ),
        encoding="utf-8",
    )
    return path


def run_cmd(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=merged)


def run_step1_with_manifest(case_root: Path, *, report_id: str, factor_root: Path, manifest: dict[str, Any]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    manifest_path = write_json(case_root / "formal_run_manifest.json", manifest)
    provider = provider_script(case_root / "provider.py")
    out_dir = factor_root / "objects" / "raw_llm" / report_id / "step1"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            report_id,
            "--report-pdf",
            str(PDF),
            "--out-dir",
            str(out_dir),
            "--provider",
            "command",
            "--write-report",
        ],
        env={
            "FACTORFORGE_FORMAL_RUN_MANIFEST": str(manifest_path),
            "FACTORFORGE_STEP1_LLM_COMMAND": f"{sys.executable} {provider}",
            "FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER": "google",
            "FACTORFORGE_STEP1_LLM_MODEL": "gemini-3.1-pro-preview",
        },
    )
    return proc, out_dir, provider.with_suffix(".called")


def case_tmp_formal_root_rejected(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_TMP_FORBIDDEN"
    factor_root = Path(f"/tmp/factorforge-run-isolation-forbidden-{os.getpid()}")
    case_root = root / "tmp_formal_root_rejected"
    manifest = manifest_payload(report_id=report_id, root=factor_root)
    proc, out_dir, called = run_step1_with_manifest(case_root, report_id=report_id, factor_root=factor_root, manifest=manifest)
    text = proc.stdout + proc.stderr
    return {
        "case": "tmp_factorforge_root_rejected",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "provider_called": called.exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text and not called.exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_command_manifest_required(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_MANIFEST_REQUIRED"
    case_root = root / "manifest_required"
    factor_root = case_root / "run_root"
    provider = provider_script(case_root / "provider.py")
    out_dir = factor_root / "objects" / "raw_llm" / report_id / "step1"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            report_id,
            "--report-pdf",
            str(PDF),
            "--out-dir",
            str(out_dir),
            "--provider",
            "command",
            "--write-report",
        ],
        env={
            "FACTORFORGE_STEP1_LLM_COMMAND": f"{sys.executable} {provider}",
            "FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER": "google",
            "FACTORFORGE_STEP1_LLM_MODEL": "gemini-3.1-pro-preview",
            "FACTORFORGE_FORMAL_RUN_MANIFEST": "",
        },
    )
    text = proc.stdout + proc.stderr
    token = "BLOCK_FORMAL_RUN_MANIFEST_REQUIRED"
    return {
        "case": "formal_command_manifest_required",
        "rc": proc.returncode,
        "token_present": token in text,
        "provider_called": provider.with_suffix(".called").exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and token in text and not provider.with_suffix(".called").exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_workspace_objects_root_rejected(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_WORKSPACE_OBJECTS_FORBIDDEN"
    factor_root = Path("/home/ubuntu/.openclaw/workspace/objects")
    case_root = root / "workspace_objects_root_rejected"
    manifest = manifest_payload(report_id=report_id, root=factor_root)
    proc, out_dir, called = run_step1_with_manifest(case_root, report_id=report_id, factor_root=factor_root, manifest=manifest)
    text = proc.stdout + proc.stderr
    return {
        "case": "workspace_top_objects_root_rejected",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "provider_called": called.exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text and not called.exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_repo_root_rejected(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_REPO_FORBIDDEN"
    factor_root = ROOT / "objects" / "forbidden_formal_root"
    case_root = root / "repo_root_rejected"
    manifest = manifest_payload(report_id=report_id, root=factor_root)
    proc, out_dir, called = run_step1_with_manifest(case_root, report_id=report_id, factor_root=factor_root, manifest=manifest)
    text = proc.stdout + proc.stderr
    return {
        "case": "repo_worktree_root_rejected",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "provider_called": called.exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text and not called.exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_reused_root_different_report_rejected(root: Path) -> dict[str, Any]:
    case_root = root / "reuse_different_report"
    factor_root = case_root / "run_root"
    factor_root.mkdir(parents=True, exist_ok=True)
    write_json(factor_root / "formal_run_manifest.json", manifest_payload(report_id="REPORT_A", root=factor_root))
    manifest = manifest_payload(report_id="REPORT_B", root=factor_root)
    proc, out_dir, called = run_step1_with_manifest(case_root / "attempt", report_id="REPORT_B", factor_root=factor_root, manifest=manifest)
    text = proc.stdout + proc.stderr
    return {
        "case": "reused_root_different_report_id_rejected",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH in text,
        "provider_called": called.exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH in text and not called.exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_reused_root_identity_mismatch_rejected(root: Path) -> dict[str, Any]:
    case_root = root / "reuse_identity_mismatch"
    factor_root = case_root / "run_root"
    factor_root.mkdir(parents=True, exist_ok=True)
    write_json(factor_root / "formal_run_manifest.json", manifest_payload(report_id="REPORT_A", root=factor_root, step1_model="gemini-3.1-pro-preview"))
    manifest = manifest_payload(report_id="REPORT_A", root=factor_root, step1_model="gemini-3.1-pro-preview-v2")
    proc, out_dir, called = run_step1_with_manifest(case_root / "attempt", report_id="REPORT_A", factor_root=factor_root, manifest=manifest)
    text = proc.stdout + proc.stderr
    return {
        "case": "reused_root_repo_pdf_provider_model_mismatch_rejected",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH in text,
        "provider_called": called.exists(),
        "raw_or_report_written": out_dir.exists(),
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH in text and not called.exists() and not out_dir.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_fresh_archive_root_and_exact_resume(root: Path) -> dict[str, Any]:
    archive = root / "archive" / "factorforge-runs"
    run_root, manifest = allocate_formal_run_root(
        report_id="RUN_ISOLATION_ACCEPTED",
        pdf_sha256=pdf_sha(),
        step_scope="step1-step3a",
        archive_root=archive,
        step1_provider="google",
        step1_model="gemini-3.1-pro-preview",
        step2_provider="deepseek",
        step2_model="deepseek-v4-pro",
    )
    first_error = None
    second_error = None
    try:
        validate_manifest(manifest, report_id="RUN_ISOLATION_ACCEPTED", factorforge_root=run_root, report_pdf=PDF)
    except SystemExit as exc:
        first_error = str(exc)
    try:
        validate_manifest(read_json(run_root / "formal_run_manifest.json"), report_id="RUN_ISOLATION_ACCEPTED", factorforge_root=run_root, report_pdf=PDF)
    except SystemExit as exc:
        second_error = str(exc)
    required = ["formal_run_manifest.json", "run_status.json", "archive_index.json"]
    return {
        "case": "fresh_archive_root_and_exact_manifest_resume_accepted",
        "run_root": str(run_root),
        "required_files_present": all((run_root / item).exists() for item in required),
        "first_validate_error": first_error,
        "second_validate_error": second_error,
        "ok": bool(all((run_root / item).exists() for item in required) and first_error is None and second_error is None),
    }


def case_step2_block_no_raw_report_runtime(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_STEP2_FORBIDDEN"
    factor_root = Path(f"/tmp/factorforge-run-isolation-step2-forbidden-{os.getpid()}")
    case_root = root / "step2_block_no_raw"
    manifest_path = write_json(case_root / "formal_run_manifest.json", manifest_payload(report_id=report_id, root=factor_root))
    provider = provider_script(case_root / "provider.py")
    out_dir = factor_root / "objects" / "raw_llm" / report_id / "step2"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step2_llm_bridge.py",
            "--report-id",
            report_id,
            "--factorforge-root",
            str(factor_root),
            "--out-dir",
            str(out_dir),
            "--provider",
            "command",
            "--write-report",
        ],
        env={
            "FACTORFORGE_FORMAL_RUN_MANIFEST": str(manifest_path),
            "FACTORFORGE_STEP2_LLM_COMMAND": f"{sys.executable} {provider}",
            "FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER": "deepseek",
            "FACTORFORGE_STEP2_LLM_MODEL": "deepseek-v4-pro",
        },
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "step2_block_no_raw_report_runtime_context",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "provider_called": provider.with_suffix(".called").exists(),
        "raw_or_report_written": out_dir.exists(),
        "runtime_context_exists": (factor_root / "objects" / "runtime_context").exists(),
        "ok": bool(
            proc.returncode != 0
            and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text
            and not provider.with_suffix(".called").exists()
            and not out_dir.exists()
            and not (factor_root / "objects" / "runtime_context").exists()
        ),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_prepare_block_no_report_runtime(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_PREPARE_FORBIDDEN"
    factor_root = Path(f"/tmp/factorforge-run-isolation-prepare-forbidden-{os.getpid()}")
    case_root = root / "prepare_block_no_runtime"
    manifest_path = write_json(case_root / "formal_run_manifest.json", manifest_payload(report_id=report_id, root=factor_root))
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(factor_root),
            "--report-id",
            report_id,
            "--report-pdf",
            str(PDF),
            "--end-step",
            "1",
            "--run-manifest",
            str(manifest_path),
            "--write-runtime-context",
            "--write-report",
        ],
    )
    text = proc.stdout + proc.stderr
    report_path = factor_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    runtime_context = factor_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    return {
        "case": "prepare_block_no_report_runtime_context_worker",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "prepare_report_exists": report_path.exists(),
        "runtime_context_exists": runtime_context.exists(),
        "worker_started": False,
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text and not report_path.exists() and not runtime_context.exists()),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_agent_tool_step1_writes_task_packet_only(root: Path) -> dict[str, Any]:
    report_id = "RUN_ISOLATION_AGENT_TOOL_STEP1"
    archive = root / "archive" / "factorforge-runs"
    factor_root, manifest = allocate_formal_run_root(
        report_id=report_id,
        pdf_sha256=pdf_sha(),
        step_scope="step1-agent-tool",
        archive_root=archive,
        step1_provider="google",
        step1_model="google/gemini-3.1-pro-preview",
        step2_provider="deepseek",
        step2_model="deepseek-v4-pro",
    )
    manifest_path = factor_root / "formal_run_manifest.json"
    proc = run_cmd(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(factor_root),
            "--report-id",
            report_id,
            "--report-pdf",
            str(PDF),
            "--end-step",
            "1",
            "--run-formal-llm-bridges",
            "--formal-llm-provider",
            "agent_tool",
            "--run-manifest",
            str(manifest_path),
            "--write-report",
        ],
        env={
            "FACTORFORGE_STEP1_FORMAL_LLM_PROVIDER": "google",
            "FACTORFORGE_STEP1_LLM_MODEL": "google/gemini-3.1-pro-preview",
            "FACTORFORGE_STEP2_FORMAL_LLM_PROVIDER": "deepseek",
            "FACTORFORGE_STEP2_LLM_MODEL": "deepseek-v4-pro",
        },
    )
    text = proc.stdout + proc.stderr
    token = "BLOCK_AGENT_TOOL_STEP1_REQUIRED"
    task_packet = factor_root / "objects" / "agent_tool_tasks" / report_id / "step1_openclaw_pdf_task_packet.json"
    raw_dir = factor_root / "objects" / "raw_llm" / report_id / "step1"
    report_path = factor_root / "objects" / "validation" / f"formal_artifact_prepare_report__{report_id}.json"
    runtime_context = factor_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    packet = read_json(task_packet) if task_packet.exists() else {}
    roles = packet.get("roles") if isinstance(packet.get("roles"), list) else []
    next_command = str(packet.get("next_command_after_raw_written") or "")
    return {
        "case": "agent_tool_step1_missing_raw_writes_task_packet_only",
        "rc": proc.returncode,
        "token_present": token in text,
        "task_packet_exists": task_packet.exists(),
        "task_packet_version": packet.get("version"),
        "task_packet_provider": ((packet.get("agent_tool") or {}).get("provider") if isinstance(packet.get("agent_tool"), dict) else None),
        "role_count": len(roles),
        "next_command_uses_agent_tool_resume": "--formal-llm-provider agent_tool" in next_command,
        "raw_written": raw_dir.exists(),
        "prepare_report_exists": report_path.exists(),
        "runtime_context_exists": runtime_context.exists(),
        "manifest_sha_bound": manifest.get("repo_sha") == current_repo_sha(),
        "worker_started": False,
        "ok": bool(
            proc.returncode != 0
            and token in text
            and task_packet.exists()
            and packet.get("version") == "factorforge_step1_agent_tool_task_packet_v1"
            and ((packet.get("agent_tool") or {}).get("provider") == "openclaw_pdf_tool")
            and len(roles) == 3
            and "--formal-llm-provider agent_tool" in next_command
            and "--end-step 1" in next_command
            and not raw_dir.exists()
            and not report_path.exists()
            and not runtime_context.exists()
        ),
        "stderr_tail": proc.stderr[-1200:],
    }


def case_smoke_roots_forbidden() -> dict[str, Any]:
    probes = {
        "tmp": Path(f"/tmp/factorforge-smoke-forbidden-{os.getpid()}"),
        "production_workspace": Path("/home/ubuntu/.openclaw/workspace/factorforge-smoke-forbidden"),
        "production_archive": Path("/home/ubuntu/.openclaw/workspace/archive/factorforge-runs/factorforge-smoke-forbidden"),
    }
    results = {}
    for name, probe_root in probes.items():
        error = None
        try:
            assert_smoke_root_allowed(probe_root)
        except SystemExit as exc:
            error = str(exc)
        results[name] = {
            "root": str(probe_root),
            "token_present": bool(error and BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN in error),
            "error": error,
        }
    ok = all(item["token_present"] for item in results.values())
    return {
        "case": "production_smoke_roots_forbidden",
        "token_present": ok,
        "ok": ok,
        "probes": results,
    }


def run_factorforgectl(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return run_cmd([sys.executable, "scripts/factorforgectl.py", *args], env=env)


def case_factorforgectl_missing_active_run_blocks(root: Path) -> dict[str, Any]:
    registry_path = root / "factorforgectl_missing" / "active_run_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"registry_version": "factorforge_active_run_registry_v2", "active_runs": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    proc = run_factorforgectl(
        ["status", "--report-id", "MISSING_REPORT", "--registry", str(registry_path)],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "factorforgectl_missing_active_run_blocks",
        "rc": proc.returncode,
        "token_present": "BLOCK_ACTIVE_RUN_NOT_FOUND" in text,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(proc.returncode != 0 and "BLOCK_ACTIVE_RUN_NOT_FOUND" in text),
    }


def case_factorforgectl_proof_tmp_root_forbidden(root: Path) -> dict[str, Any]:
    registry_path = root / "factorforgectl_tmp_root" / "active_run_registry.json"
    artifact_root = Path(f"/tmp/factorforgectl-forbidden-{os.getpid()}")
    payload = {
        "registry_version": "factorforge_active_run_registry_v2",
        "active_runs": {
            "TMP_ROOT_REPORT": {
                "report_id": "TMP_ROOT_REPORT",
                "run_id": "tmp_root_report_run",
                "artifact_root": str(artifact_root),
                "repo_sha": current_repo_sha(),
                "status": "CREATED",
                "steps": {},
            }
        },
    }
    write_json(registry_path, payload)
    proc = run_factorforgectl(
        ["proof", "--report-id", "TMP_ROOT_REPORT", "--registry", str(registry_path)],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "factorforgectl_proof_tmp_root_forbidden",
        "rc": proc.returncode,
        "token_present": BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(proc.returncode != 0 and BLOCK_FORMAL_RUN_ROOT_FORBIDDEN in text and not artifact_root.exists()),
    }


def case_factorforgectl_root_mismatch_blocks(root: Path) -> dict[str, Any]:
    registry_path = root / "factorforgectl_root_mismatch" / "active_run_registry.json"
    allowed_root = root / "archive" / "factorforge-runs" / "root_mismatch_run"
    other_root = root / "archive" / "factorforge-runs" / "root_mismatch_other"
    payload = {
        "registry_version": "factorforge_active_run_registry_v2",
        "active_runs": {
            "ROOT_MISMATCH_REPORT": {
                "report_id": "ROOT_MISMATCH_REPORT",
                "run_id": "root_mismatch_run",
                "artifact_root": str(allowed_root),
                "repo_sha": current_repo_sha(),
                "status": "CREATED",
                "steps": {},
            }
        },
    }
    write_json(registry_path, payload)
    proc = run_factorforgectl(
        [
            "proof",
            "--report-id",
            "ROOT_MISMATCH_REPORT",
            "--registry",
            str(registry_path),
            "--artifact-root",
            str(other_root),
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "factorforgectl_root_mismatch_blocks",
        "rc": proc.returncode,
        "token_present": "BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH" in text,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(proc.returncode != 0 and "BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH" in text),
    }


def write_step1_task_packet(root: Path, report_id: str, pdf_hash: str) -> Path:
    task = {
        "version": "factorforge_step1_agent_tool_task_packet_v1",
        "report_id": report_id,
        "factorforge_root": str(root),
        "pdf_sha256": pdf_hash,
        "agent_tool": {
            "provider": "openclaw_pdf_tool",
            "model": "google/gemini-3.1-pro-preview",
        },
        "roles": [
            {
                "role": "primary",
                "prompt_hash": "primary_prompt_hash",
                "target_raw_path": str(root / "objects" / "raw_llm" / report_id / "step1" / "step1_primary_raw.json"),
            },
            {
                "role": "challenger",
                "prompt_hash": "challenger_prompt_hash",
                "target_raw_path": str(root / "objects" / "raw_llm" / report_id / "step1" / "step1_challenger_raw.json"),
            },
            {
                "role": "chief",
                "prompt_hash": "chief_prompt_hash",
                "target_raw_path": str(root / "objects" / "raw_llm" / report_id / "step1" / "step1_chief_raw.json"),
            },
        ],
    }
    return write_json(root / "objects" / "agent_tool_tasks" / report_id / "step1_openclaw_pdf_task_packet.json", task)


def write_factorforgectl_registry(registry_path: Path, report_id: str, artifact_root: Path, *, pdf_hash: str) -> None:
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": f"{report_id.lower()}_run",
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "BLOCK_AGENT_TOOL_STEP1_REQUIRED",
                    "current_step": "step1",
                    "report_pdf": {"sha256": pdf_hash, "s3_uri": "s3://example/report.pdf"},
                    "steps": {"step1": {"status": "WAITING_FOR_AGENT_TOOL_RAW"}},
                }
            },
        },
    )


def write_step1_raw(root: Path, report_id: str, *, role: str, pdf_hash: str, prompt_hash: str) -> Path:
    path = root / "objects" / "raw_llm" / report_id / "step1" / f"step1_{role}_raw.json"
    payload = {
        "report_id": report_id,
        "role": role,
        "result": {"ok": True},
        "_llm_bridge_provenance": {
            "report_id": report_id,
            "role": role,
            "provider": "openclaw_pdf_tool",
            "model": "google/gemini-3.1-pro-preview",
            "pdf_sha256": pdf_hash,
            "prompt_hash": prompt_hash,
            "source_derivation": "agent_tool_formal_route",
            "created_at_utc": "2026-05-29T00:00:00Z",
        },
    }
    return write_json(path, payload)


def case_factorforgectl_resume_step1_missing_raw_blocks(root: Path) -> dict[str, Any]:
    report_id = "RESUME_STEP1_MISSING_RAW"
    artifact_root = root / "archive" / "factorforge-runs" / "resume_step1_missing_raw"
    pdf_hash = "a" * 64
    registry_path = root / "factorforgectl_resume_missing" / "active_run_registry.json"
    write_factorforgectl_registry(registry_path, report_id, artifact_root, pdf_hash=pdf_hash)
    write_step1_task_packet(artifact_root, report_id, pdf_hash)
    proc = run_factorforgectl(
        ["resume-step1", "--report-id", report_id, "--registry", str(registry_path)],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "factorforgectl_resume_step1_missing_raw_blocks",
        "rc": proc.returncode,
        "token_present": "BLOCK_AGENT_TOOL_STEP1_RAW_INVALID" in text,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(proc.returncode != 0 and "BLOCK_AGENT_TOOL_STEP1_RAW_INVALID" in text),
    }


def case_factorforgectl_resume_step1_valid_raw_passes(root: Path) -> dict[str, Any]:
    report_id = "RESUME_STEP1_VALID_RAW"
    artifact_root = root / "archive" / "factorforge-runs" / "resume_step1_valid_raw"
    pdf_hash = "b" * 64
    registry_path = root / "factorforgectl_resume_valid" / "active_run_registry.json"
    write_factorforgectl_registry(registry_path, report_id, artifact_root, pdf_hash=pdf_hash)
    write_step1_task_packet(artifact_root, report_id, pdf_hash)
    write_step1_raw(artifact_root, report_id, role="primary", pdf_hash=pdf_hash, prompt_hash="primary_prompt_hash")
    write_step1_raw(artifact_root, report_id, role="challenger", pdf_hash=pdf_hash, prompt_hash="challenger_prompt_hash")
    write_step1_raw(artifact_root, report_id, role="chief", pdf_hash=pdf_hash, prompt_hash="chief_prompt_hash")
    proc = run_factorforgectl(
        ["resume-step1", "--report-id", report_id, "--registry", str(registry_path)],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    step1 = (run.get("steps") or {}).get("step1") or {}
    proof = artifact_root / "objects" / "proof" / f"proof_ledger__{report_id}.json"
    return {
        "case": "factorforgectl_resume_step1_valid_raw_passes",
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "step1_status": step1.get("status"),
        "current_step": run.get("current_step"),
        "proof_exists": proof.exists(),
        "ok": bool(proc.returncode == 0 and step1.get("status") == "PASS" and run.get("current_step") == "step2" and proof.exists()),
    }


def case_factorforgectl_run_local_step1_generates_task_packet(root: Path) -> dict[str, Any]:
    report_id = "RUN_LOCAL_STEP1_AGENT_TASK"
    archive = root / "archive" / "factorforge-runs"
    artifact_root, manifest = allocate_formal_run_root(
        report_id=report_id,
        pdf_sha256=pdf_sha(),
        step_scope="step1-step6",
        archive_root=archive,
        step1_provider="openclaw_pdf_tool",
        step1_model="google/gemini-3.1-pro-preview",
        step2_provider="deepseek",
        step2_model="deepseek-chat",
    )
    registry_path = root / "factorforgectl_run_local_step1" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": manifest["run_id"],
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "CREATED",
                    "current_step": "step1",
                    "report_pdf": {"sha256": pdf_sha(), "local_path": str(PDF)},
                    "formal_run_manifest": str(artifact_root / "formal_run_manifest.json"),
                    "steps": {},
                }
            },
        },
    )
    proc = run_factorforgectl(
        [
            "run-local",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--start-step",
            "1",
            "--end-step",
            "1",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    text = proc.stdout + proc.stderr
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    task_packet = artifact_root / "objects" / "agent_tool_tasks" / report_id / "step1_openclaw_pdf_task_packet.json"
    return {
        "case": "factorforgectl_run_local_step1_generates_task_packet",
        "rc": proc.returncode,
        "token_present": "BLOCK_AGENT_TOOL_STEP1_REQUIRED" in text,
        "task_packet_exists": task_packet.exists(),
        "registry_status": run.get("status"),
        "step1_status": ((run.get("steps") or {}).get("step1") or {}).get("status"),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            proc.returncode != 0
            and "BLOCK_AGENT_TOOL_STEP1_REQUIRED" in text
            and task_packet.exists()
            and run.get("status") == "BLOCK_AGENT_TOOL_STEP1_REQUIRED"
            and ((run.get("steps") or {}).get("step1") or {}).get("status") == "WAITING_FOR_AGENT_TOOL_RAW"
        ),
    }


def case_factorforgectl_run_local_step2_to_3a_fixture_passes(root: Path) -> dict[str, Any]:
    report_id = "RUN_LOCAL_STEP23_FIXTURE"
    archive = root / "archive" / "factorforge-runs"
    artifact_root, manifest = allocate_formal_run_root(
        report_id=report_id,
        pdf_sha256=pdf_sha(),
        step_scope="step1-step6",
        archive_root=archive,
        step1_provider="openclaw_pdf_tool",
        step1_model="google/gemini-3.1-pro-preview",
        step2_provider="deepseek",
        step2_model="deepseek-chat",
    )
    registry_path = root / "factorforgectl_run_local_step23" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": manifest["run_id"],
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "STEP1_READY",
                    "current_step": "step2",
                    "report_pdf": {"sha256": pdf_sha(), "local_path": str(PDF)},
                    "formal_run_manifest": str(artifact_root / "formal_run_manifest.json"),
                    "providers": manifest.get("steps", {}),
                    "steps": {"step1": {"status": "PASS"}},
                }
            },
        },
    )
    step1_out = artifact_root / "objects" / "raw_llm" / report_id / "step1"
    bridge = run_cmd(
        [
            sys.executable,
            "scripts/run_factorforge_step1_llm_bridge.py",
            "--report-id",
            report_id,
            "--report-pdf",
            str(PDF),
            "--out-dir",
            str(step1_out),
            "--provider",
            "fixture",
            "--write-report",
        ]
    )
    proc = run_factorforgectl(
        [
            "run-local",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--start-step",
            "2",
            "--end-step",
            "3a",
            "--formal-llm-provider",
            "fixture",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    runtime_context = artifact_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    return {
        "case": "factorforgectl_run_local_step2_to_3a_fixture_passes",
        "bridge_rc": bridge.returncode,
        "rc": proc.returncode,
        "status": payload.get("status"),
        "prepare_verdict": payload.get("prepare_verdict"),
        "runtime_context_written": payload.get("runtime_context_written"),
        "runtime_context_exists": runtime_context.exists(),
        "worker_started": False,
        "registry_status": run.get("status"),
        "current_step": run.get("current_step"),
        "step2_status": ((run.get("steps") or {}).get("step2") or {}).get("status"),
        "step3a_status": ((run.get("steps") or {}).get("step3a") or {}).get("status"),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            bridge.returncode == 0
            and proc.returncode == 0
            and payload.get("status") == "PASS"
            and payload.get("prepare_verdict") == "ACCEPT"
            and payload.get("runtime_context_written") is True
            and runtime_context.exists()
            and run.get("current_step") == "step3b"
            and ((run.get("steps") or {}).get("step2") or {}).get("status") == "PASS"
            and ((run.get("steps") or {}).get("step3a") or {}).get("status") == "PASS"
        ),
    }


def case_factorforgectl_run_worker_dry_run_no_ssm(root: Path) -> dict[str, Any]:
    report_id = "RUN_WORKER_DRY_RUN"
    artifact_root = root / "archive" / "factorforge-runs" / "run_worker_dry_run"
    runtime_context = artifact_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    write_json(runtime_context, {"report_id": report_id, "artifact_root": str(artifact_root)})
    registry_path = root / "factorforgectl_run_worker_dry_run" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": "run_worker_dry_run",
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "LOCAL_STEPS_READY",
                    "current_step": "step3b",
                    "runtime_context_written": True,
                    "steps": {
                        "step1": {"status": "PASS"},
                        "step2": {"status": "PASS"},
                        "step3a": {"status": "PASS"},
                    },
                }
            },
        },
    )
    proc = run_factorforgectl(
        [
            "run-worker",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--worker-instance-id",
            "i-dryrun",
            "--start-step",
            "3b",
            "--end-step",
            "5",
            "--dry-run",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    command_text = "\n".join(payload.get("worker_command") or [])
    return {
        "case": "factorforgectl_run_worker_dry_run_no_ssm",
        "rc": proc.returncode,
        "status": payload.get("status"),
        "worker_dry_run": payload.get("worker_dry_run"),
        "worker_started": payload.get("worker_started"),
        "ssm_command_id": payload.get("ssm_command_id"),
        "registry_status": run.get("status"),
        "command_has_root": str(artifact_root) in command_text,
        "command_has_repo_sha": current_repo_sha() in command_text,
        "command_has_step_range": "--start-step 3b --end-step 5" in command_text,
        "readiness_checks_all_ok": all(item.get("ok") for item in payload.get("readiness_checks") or []),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            proc.returncode == 0
            and payload.get("status") == "PASS"
            and payload.get("worker_dry_run") is True
            and payload.get("worker_started") is False
            and payload.get("ssm_command_id") is None
            and run.get("status") == "WORKER_DRY_RUN_READY"
            and str(artifact_root) in command_text
            and current_repo_sha() in command_text
            and "--start-step 3b --end-step 5" in command_text
            and all(item.get("ok") for item in payload.get("readiness_checks") or [])
        ),
    }


def worker_ready_registry(root: Path, report_id: str, run_id: str) -> tuple[Path, Path]:
    artifact_root = root / "archive" / "factorforge-runs" / run_id
    runtime_context = artifact_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    write_json(runtime_context, {"report_id": report_id, "artifact_root": str(artifact_root)})
    registry_path = root / f"factorforgectl_{run_id}" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": run_id,
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "LOCAL_STEPS_READY",
                    "current_step": "step3b",
                    "runtime_context_written": True,
                    "steps": {
                        "step1": {"status": "PASS"},
                        "step2": {"status": "PASS"},
                        "step3a": {"status": "PASS"},
                    },
                }
            },
        },
    )
    return registry_path, artifact_root


def case_factorforgectl_sync_worker_artifacts_dry_run_no_ssm(root: Path) -> dict[str, Any]:
    report_id = "SYNC_WORKER_ARTIFACTS_DRY_RUN"
    registry_path, artifact_root = worker_ready_registry(root, report_id, "sync_worker_artifacts_dry_run")
    proc = run_factorforgectl(
        [
            "sync-worker-artifacts",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--worker-instance-id",
            "i-syncdry",
            "--artifact-sync-s3-uri",
            "s3://factorforge-smoke/sync_worker_artifacts_dry_run.tgz",
            "--dry-run",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    command_text = "\n".join(payload.get("worker_sync_command") or [])
    return {
        "case": "factorforgectl_sync_worker_artifacts_dry_run_no_ssm",
        "rc": proc.returncode,
        "status": payload.get("status"),
        "worker_artifact_sync_dry_run": payload.get("worker_artifact_sync_dry_run"),
        "worker_started": payload.get("worker_started"),
        "ssm_command_id": payload.get("ssm_command_id"),
        "registry_status": run.get("status"),
        "command_has_s3_uri": "s3://factorforge-smoke/sync_worker_artifacts_dry_run.tgz" in command_text,
        "command_has_artifact_root": str(artifact_root) in command_text,
        "proof_exists": bool(payload.get("proof_ledger")) and Path(payload.get("proof_ledger") or "").exists(),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            proc.returncode == 0
            and payload.get("status") == "PASS"
            and payload.get("worker_artifact_sync_dry_run") is True
            and payload.get("worker_started") is False
            and payload.get("ssm_command_id") is None
            and run.get("status") == "WORKER_ARTIFACT_SYNC_DRY_RUN_READY"
            and "s3://factorforge-smoke/sync_worker_artifacts_dry_run.tgz" in command_text
            and str(artifact_root) in command_text
            and bool(payload.get("proof_ledger"))
            and Path(payload.get("proof_ledger") or "").exists()
        ),
    }


def case_factorforgectl_run_worker_blocks_without_sync_proof(root: Path) -> dict[str, Any]:
    report_id = "RUN_WORKER_NO_SYNC_PROOF"
    registry_path, _artifact_root = worker_ready_registry(root, report_id, "run_worker_no_sync_proof")
    proc = run_factorforgectl(
        [
            "run-worker",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--worker-instance-id",
            "i-nosync",
            "--start-step",
            "3b",
            "--end-step",
            "5",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    return {
        "case": "factorforgectl_run_worker_blocks_without_sync_proof",
        "rc": proc.returncode,
        "block_token": payload.get("block_token"),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(proc.returncode != 0 and payload.get("block_token") == "BLOCK_WORKER_ARTIFACT_SYNC_REQUIRED"),
    }


def case_factorforgectl_check_worker_preflight_passes(root: Path) -> dict[str, Any]:
    report_id = "CHECK_WORKER_PREFLIGHT"
    artifact_root = root / "archive" / "factorforge-runs" / "check_worker_preflight"
    runtime_context = artifact_root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json"
    write_json(runtime_context, {"report_id": report_id, "artifact_root": str(artifact_root)})
    registry_path = root / "factorforgectl_check_worker_preflight" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": "check_worker_preflight",
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "LOCAL_STEPS_READY",
                    "current_step": "step3b",
                    "runtime_context_written": True,
                    "steps": {
                        "step1": {"status": "PASS"},
                        "step2": {"status": "PASS"},
                        "step3a": {"status": "PASS"},
                    },
                }
            },
        },
    )
    proc = run_factorforgectl(
        [
            "check-worker",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--start-step",
            "3b",
            "--end-step",
            "5",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    registry = read_json(registry_path)
    run = (registry.get("active_runs") or {}).get(report_id) or {}
    return {
        "case": "factorforgectl_check_worker_preflight_passes",
        "rc": proc.returncode,
        "status": payload.get("status"),
        "worker_preflight_ready": payload.get("worker_preflight_ready"),
        "worker_started": payload.get("worker_started"),
        "registry_status": run.get("status"),
        "readiness_checks_all_ok": all(item.get("ok") for item in payload.get("readiness_checks") or []),
        "proof_exists": Path(payload.get("proof_ledger") or "").exists(),
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            proc.returncode == 0
            and payload.get("status") == "PASS"
            and payload.get("worker_preflight_ready") is True
            and payload.get("worker_started") is False
            and run.get("status") == "WORKER_PREFLIGHT_READY"
            and all(item.get("ok") for item in payload.get("readiness_checks") or [])
            and Path(payload.get("proof_ledger") or "").exists()
        ),
    }


def case_factorforgectl_check_worker_blocks_without_runtime_context(root: Path) -> dict[str, Any]:
    report_id = "CHECK_WORKER_NO_RUNTIME_CONTEXT"
    artifact_root = root / "archive" / "factorforge-runs" / "check_worker_no_runtime_context"
    artifact_root.mkdir(parents=True, exist_ok=True)
    registry_path = root / "factorforgectl_check_worker_no_runtime_context" / "active_run_registry.json"
    write_json(
        registry_path,
        {
            "registry_version": "factorforge_active_run_registry_v2",
            "active_runs": {
                report_id: {
                    "report_id": report_id,
                    "run_id": "check_worker_no_runtime_context",
                    "artifact_root": str(artifact_root),
                    "repo_sha": current_repo_sha(),
                    "status": "LOCAL_STEPS_READY",
                    "current_step": "step3b",
                    "runtime_context_written": False,
                    "steps": {
                        "step1": {"status": "PASS"},
                        "step2": {"status": "PASS"},
                        "step3a": {"status": "PASS"},
                    },
                }
            },
        },
    )
    proc = run_factorforgectl(
        [
            "check-worker",
            "--report-id",
            report_id,
            "--registry",
            str(registry_path),
            "--start-step",
            "3b",
            "--end-step",
            "5",
        ],
        env={"FACTORFORGE_ACTIVE_RUN_REGISTRY": str(registry_path)},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    failed_names = {item.get("name") for item in payload.get("failed_checks") or []}
    return {
        "case": "factorforgectl_check_worker_blocks_without_runtime_context",
        "rc": proc.returncode,
        "block_token": payload.get("block_token"),
        "runtime_written_failed": "runtime_context_written" in failed_names,
        "runtime_file_failed": "runtime_context_file_exists" in failed_names,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "ok": bool(
            proc.returncode != 0
            and payload.get("block_token") == "BLOCK_WORKER_READINESS_FAILED"
            and "runtime_context_written" in failed_names
            and "runtime_context_file_exists" in failed_names
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / ".factorforge-smoke" / "run_isolation_smoke"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()
    try:
        assert_smoke_root_allowed(root)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.code) if isinstance(exc.code, int) and exc.code else 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = [
        case_command_manifest_required(root),
        case_tmp_formal_root_rejected(root),
        case_workspace_objects_root_rejected(root),
        case_repo_root_rejected(root),
        case_reused_root_different_report_rejected(root),
        case_reused_root_identity_mismatch_rejected(root),
        case_fresh_archive_root_and_exact_resume(root),
        case_step2_block_no_raw_report_runtime(root),
        case_prepare_block_no_report_runtime(root),
        case_agent_tool_step1_writes_task_packet_only(root),
        case_smoke_roots_forbidden(),
        case_factorforgectl_missing_active_run_blocks(root),
        case_factorforgectl_proof_tmp_root_forbidden(root),
        case_factorforgectl_root_mismatch_blocks(root),
        case_factorforgectl_resume_step1_missing_raw_blocks(root),
        case_factorforgectl_resume_step1_valid_raw_passes(root),
        case_factorforgectl_run_local_step1_generates_task_packet(root),
        case_factorforgectl_run_local_step2_to_3a_fixture_passes(root),
        case_factorforgectl_check_worker_preflight_passes(root),
        case_factorforgectl_check_worker_blocks_without_runtime_context(root),
        case_factorforgectl_sync_worker_artifacts_dry_run_no_ssm(root),
        case_factorforgectl_run_worker_blocks_without_sync_proof(root),
        case_factorforgectl_run_worker_dry_run_no_ssm(root),
    ]
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) else "BLOCK"
    summary = {
        "version": "factorforge_run_isolation_smoke_v1",
        "verdict": verdict,
        "root": str(root),
        "runtime_context_written": False,
        "worker_started": False,
        "cases": cases,
    }
    out = root / "objects" / "validation" / "factorforge_run_isolation_smoke_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {out}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
