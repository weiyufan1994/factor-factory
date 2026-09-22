from __future__ import annotations

import json
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.runtime_context import write_json_atomic


SCHEMA_VERSION = "worker_task_spec_v1"
REPORT_SCHEMA_VERSION = "worker_command_report_v1"

TOKEN_TRANSPORT_FAILED = "BLOCK_WORKER_TRANSPORT_FAILED"
TOKEN_REPO_SHA_MISMATCH = "BLOCK_WORKER_REPO_SHA_MISMATCH"
TOKEN_PYTHON_IMPORT_FAILED = "BLOCK_WORKER_PYTHON_IMPORT_FAILED"
TOKEN_PATH_MISMATCH = "BLOCK_WORKER_PATH_MISMATCH"
TOKEN_RESOURCE_BUSY = "BLOCK_WORKER_RESOURCE_BUSY"
TOKEN_TASK_SPEC_INVALID = "BLOCK_WORKER_TASK_SPEC_INVALID"
TOKEN_BUSINESS_VERDICT_MISSING = "BLOCK_WORKER_BUSINESS_VERDICT_MISSING"
TOKEN_SIDE_EFFECT_CONTRACT_VIOLATED = "BLOCK_WORKER_SIDE_EFFECT_CONTRACT_VIOLATED"
TOKEN_REPORT_SCHEMA_INVALID = "BLOCK_WORKER_REPORT_SCHEMA_INVALID"
TOKEN_BUSINESS_VERDICT_FAILED = "BLOCK_WORKER_BUSINESS_VERDICT_FAILED"

TERMINAL_SSM_STATUSES = {"Success", "Cancelled", "TimedOut", "Failed", "Cancelling"}
IN_PROGRESS_SSM_STATUSES = {"Pending", "InProgress", "Delayed"}
DEFAULT_SIDE_EFFECTS = {
    "clean_data_started": False,
    "search_worker_started": False,
    "official_promotion_written": False,
    "production_loop_started": False,
    "s3_written": False,
    "installed_skill_modified": False,
    "worker_process_started": False,
}


class WorkerTaskError(Exception):
    def __init__(self, token: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.token = token
        self.message = message
        self.details = details or {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(raw: str | None, *, base: Path | None = None) -> Path | None:
    if raw is None or str(raw).strip() == "":
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path


def run_text(cmd: list[str], *, cwd: Path | None = None, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout_sec)


def git_sha(path: Path) -> str | None:
    proc = run_text(["git", "-C", str(path), "rev-parse", "HEAD"], timeout_sec=10)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_task_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise WorkerTaskError(TOKEN_TASK_SPEC_INVALID, f"schema_version must be {SCHEMA_VERSION}")
    for key in ["task_id", "project", "execution"]:
        if not spec.get(key):
            raise WorkerTaskError(TOKEN_TASK_SPEC_INVALID, f"task spec missing required key: {key}")
    execution = spec.get("execution")
    if not isinstance(execution, dict) or not execution.get("runner"):
        raise WorkerTaskError(TOKEN_TASK_SPEC_INVALID, "execution.runner is required")


def build_initial_report(spec: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    transport = spec.get("transport") if isinstance(spec.get("transport"), dict) else {}
    side_effect_contract = dict(DEFAULT_SIDE_EFFECTS)
    if isinstance(spec.get("side_effect_contract"), dict):
        side_effect_contract.update(spec["side_effect_contract"])
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "task_spec_path": str(spec_path),
        "task_id": spec.get("task_id"),
        "project": spec.get("project"),
        "transport": {
            "type": transport.get("type") or "local",
            "command_id": transport.get("command_id"),
            "instance_id": transport.get("instance_id"),
            "ssm_status": transport.get("ssm_status"),
        },
        "runtime": {
            "hostname": platform.node(),
            "repo_path": runtime.get("repo_path"),
            "workspace_path": runtime.get("workspace_path"),
            "git_sha": None,
            "git_sha_required": (spec.get("preflight") or {}).get("git_sha_required"),
            "source_bundle_path": (spec.get("preflight") or {}).get(
                "source_bundle_path"
            ),
            "source_bundle_sha256": None,
            "source_bundle_sha256_required": (spec.get("preflight") or {}).get(
                "source_bundle_sha256_required"
            ),
            "python_path": runtime.get("python") or sys.executable,
            "python_version": None,
            "env_summary": {
                "cwd": os.getcwd(),
                "platform": platform.platform(),
            },
        },
        "execution": {
            "runner": (spec.get("execution") or {}).get("runner"),
            "argv": (spec.get("execution") or {}).get("argv") or [],
            "return_code": None,
            "started_at_utc": None,
            "ended_at_utc": None,
            "stdout_path": None,
            "stderr_path": None,
        },
        "preflight": {
            "status": "not_run",
            "checks": [],
        },
        "business_result": {
            "verdict": None,
            "validator_verdict": None,
            "blocker_token": None,
            "artifact_paths": [],
        },
        "side_effect_contract": side_effect_contract,
        "side_effects": dict(DEFAULT_SIDE_EFFECTS),
    }


def record_check(report: dict[str, Any], name: str, ok: bool, **details: Any) -> None:
    report.setdefault("preflight", {}).setdefault("checks", []).append({"name": name, "ok": bool(ok), **details})


def top_processes(limit: int = 8) -> list[dict[str, Any]]:
    proc = run_text(["ps", "-eo", "pid,pcpu,pmem,comm,args"], timeout_sec=10)
    if proc.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        try:
            cpu = float(parts[1])
            mem = float(parts[2])
        except ValueError:
            continue
        rows.append({"pid": parts[0], "pcpu": cpu, "pmem": mem, "comm": parts[3], "args": parts[4]})
    rows.sort(key=lambda item: item["pcpu"], reverse=True)
    return rows[:limit]


def run_preflight(spec: dict[str, Any], report: dict[str, Any], spec_path: Path) -> None:
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    preflight = spec.get("preflight") if isinstance(spec.get("preflight"), dict) else {}
    repo_path = resolve_path(runtime.get("repo_path"))
    workspace_path = resolve_path(runtime.get("workspace_path"))
    python_path = runtime.get("python") or sys.executable
    python_resolved = shutil.which(python_path) if not Path(str(python_path)).is_absolute() else str(Path(str(python_path)).expanduser())
    if not python_resolved or not Path(python_resolved).exists():
        record_check(report, "python_exists", False, python_path=python_path)
        raise WorkerTaskError(TOKEN_PATH_MISMATCH, f"python path not found: {python_path}")
    report["runtime"]["python_path"] = python_resolved
    version_proc = run_text([python_resolved, "--version"], timeout_sec=10)
    report["runtime"]["python_version"] = (version_proc.stdout or version_proc.stderr).strip()
    record_check(report, "python_exists", True, python_path=python_resolved)

    if repo_path is not None:
        if not repo_path.exists():
            record_check(report, "repo_path_exists", False, repo_path=str(repo_path))
            raise WorkerTaskError(TOKEN_PATH_MISMATCH, f"repo_path not found: {repo_path}")
        actual_sha = git_sha(repo_path)
        report["runtime"]["repo_path"] = str(repo_path)
        report["runtime"]["git_sha"] = actual_sha
        record_check(report, "repo_path_exists", True, repo_path=str(repo_path), git_sha=actual_sha)
        required_sha = preflight.get("git_sha_required")
        if required_sha and actual_sha != required_sha:
            record_check(report, "git_sha_required", False, required_sha=required_sha, actual_sha=actual_sha)
            raise WorkerTaskError(TOKEN_REPO_SHA_MISMATCH, "worker repo sha mismatch", {"required_sha": required_sha, "actual_sha": actual_sha})
        if required_sha:
            record_check(report, "git_sha_required", True, required_sha=required_sha, actual_sha=actual_sha)

    source_bundle_path = resolve_path(
        preflight.get("source_bundle_path"),
        base=workspace_path or spec_path.parent,
    )
    source_bundle_required = preflight.get("source_bundle_sha256_required")
    if source_bundle_path is not None or source_bundle_required:
        if source_bundle_path is None or not source_bundle_path.is_file():
            record_check(
                report,
                "source_bundle_exists",
                False,
                path=str(source_bundle_path) if source_bundle_path else None,
            )
            raise WorkerTaskError(
                TOKEN_PATH_MISMATCH,
                "source bundle path is missing or not a file",
            )
        actual_bundle_sha = file_sha256(source_bundle_path)
        report["runtime"]["source_bundle_path"] = str(source_bundle_path)
        report["runtime"]["source_bundle_sha256"] = actual_bundle_sha
        record_check(
            report,
            "source_bundle_exists",
            True,
            path=str(source_bundle_path),
            sha256=actual_bundle_sha,
        )
        if not source_bundle_required or actual_bundle_sha != source_bundle_required:
            record_check(
                report,
                "source_bundle_sha256_required",
                False,
                required_sha=source_bundle_required,
                actual_sha=actual_bundle_sha,
            )
            raise WorkerTaskError(
                TOKEN_REPO_SHA_MISMATCH,
                "worker source bundle sha mismatch",
                {
                    "required_sha": source_bundle_required,
                    "actual_sha": actual_bundle_sha,
                },
            )
        record_check(
            report,
            "source_bundle_sha256_required",
            True,
            required_sha=source_bundle_required,
            actual_sha=actual_bundle_sha,
        )

    if workspace_path is not None:
        if not workspace_path.exists():
            record_check(report, "workspace_path_exists", False, workspace_path=str(workspace_path))
            raise WorkerTaskError(TOKEN_PATH_MISMATCH, f"workspace_path not found: {workspace_path}")
        report["runtime"]["workspace_path"] = str(workspace_path)
        record_check(report, "workspace_path_exists", True, workspace_path=str(workspace_path))

    for raw in preflight.get("require_paths") or []:
        path = resolve_path(str(raw), base=repo_path or spec_path.parent)
        ok = bool(path and path.exists())
        record_check(report, "require_path_exists", ok, path=str(path) if path else str(raw))
        if not ok:
            raise WorkerTaskError(TOKEN_PATH_MISMATCH, f"required path not found: {raw}")

    for module in preflight.get("python_imports") or []:
        proc = run_text([python_resolved, "-c", f"import {module}"], cwd=repo_path, timeout_sec=30)
        ok = proc.returncode == 0
        record_check(report, "python_import", ok, module=module, stderr=proc.stderr[-500:])
        if not ok:
            raise WorkerTaskError(TOKEN_PYTHON_IMPORT_FAILED, f"python import failed: {module}", {"stderr": proc.stderr})

    resource_guard = preflight.get("resource_guard") if isinstance(preflight.get("resource_guard"), dict) else {}
    if resource_guard.get("enabled"):
        load_1m = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
        cpu_count = os.cpu_count() or 1
        load_per_cpu = (load_1m / cpu_count) if load_1m is not None else None
        process_sample = top_processes()
        report["preflight"]["resource_snapshot"] = {
            "load_1m": load_1m,
            "cpu_count": cpu_count,
            "load_1m_per_cpu": load_per_cpu,
            "top_processes": process_sample,
        }
        max_load = resource_guard.get("max_load_1m_per_cpu")
        if max_load is not None and load_per_cpu is not None and load_per_cpu > float(max_load):
            record_check(report, "resource_load_guard", False, load_1m_per_cpu=load_per_cpu, max_load_1m_per_cpu=max_load)
            raise WorkerTaskError(TOKEN_RESOURCE_BUSY, "worker resource load exceeds guard", report["preflight"]["resource_snapshot"])
        blocked_patterns = [str(item) for item in resource_guard.get("blocked_process_patterns") or [] if str(item).strip()]
        hits = [
            item for item in process_sample
            if any(pattern in item.get("args", "") for pattern in blocked_patterns)
        ]
        if hits:
            record_check(report, "resource_process_guard", False, blocked_processes=hits)
            raise WorkerTaskError(TOKEN_RESOURCE_BUSY, "blocked worker process is already running", {"blocked_processes": hits})
        record_check(report, "resource_guard", True, load_1m_per_cpu=load_per_cpu)

    report["preflight"]["status"] = "PASS"


def resolve_runner(spec: dict[str, Any], spec_path: Path) -> tuple[Path, Path, list[str]]:
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    execution = spec.get("execution") or {}
    repo_path = resolve_path(runtime.get("repo_path")) or spec_path.parent
    cwd = resolve_path(execution.get("cwd"), base=repo_path) or repo_path
    runner = resolve_path(execution.get("runner"), base=repo_path)
    if runner is None:
        raise WorkerTaskError(TOKEN_TASK_SPEC_INVALID, "execution.runner is required")
    argv = [str(item) for item in (execution.get("argv") or [])]
    return runner, cwd, argv


def parse_business_result(spec: dict[str, Any], stdout_text: str, cwd: Path, repo_path: Path | None) -> dict[str, Any] | None:
    execution = spec.get("execution") or {}
    raw_path = execution.get("business_result_path")
    if raw_path:
        result_path = resolve_path(str(raw_path), base=cwd)
        if result_path and result_path.exists():
            return load_json(result_path)
        result_path = resolve_path(str(raw_path), base=repo_path) if repo_path else None
        if result_path and result_path.exists():
            return load_json(result_path)
    stripped = stdout_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
    return None


def enforce_side_effect_contract(spec: dict[str, Any], report: dict[str, Any], business_result: dict[str, Any] | None) -> None:
    expected = spec.get("side_effect_contract") if isinstance(spec.get("side_effect_contract"), dict) else {}
    observed = dict(DEFAULT_SIDE_EFFECTS)
    if business_result and isinstance(business_result.get("side_effects"), dict):
        observed.update(business_result["side_effects"])
    report["side_effects"] = observed
    violations = {
        key: {"expected": value, "observed": observed.get(key)}
        for key, value in expected.items()
        if observed.get(key) != value
    }
    if violations:
        raise WorkerTaskError(TOKEN_SIDE_EFFECT_CONTRACT_VIOLATED, "worker side-effect contract violated", {"violations": violations})


def execute_task(spec: dict[str, Any], report: dict[str, Any], spec_path: Path, *, dry_run: bool = False, preflight_only: bool = False) -> int:
    execution = spec.get("execution") or {}
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    repo_path = resolve_path(runtime.get("repo_path"))
    runner, cwd, argv = resolve_runner(spec, spec_path)
    output_dir = resolve_path(execution.get("output_dir"), base=spec_path.parent) or (spec_path.parent / spec.get("task_id", "worker_task"))
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    report["execution"]["stdout_path"] = str(stdout_path)
    report["execution"]["stderr_path"] = str(stderr_path)
    report["execution"]["cwd"] = str(cwd)
    report["execution"]["runner"] = str(runner)
    report["execution"]["argv"] = argv

    if not runner.exists():
        raise WorkerTaskError(TOKEN_PATH_MISMATCH, f"runner not found: {runner}")

    python_path = report["runtime"]["python_path"]
    command = [python_path, str(runner), *argv] if execution.get("use_python", True) else [str(runner), *argv]
    report["execution"]["command_display"] = " ".join(shlex.quote(part) for part in command)
    if dry_run or preflight_only:
        report["business_result"] = {"verdict": "PREFLIGHT_PASS", "validator_verdict": "PASS", "blocker_token": None, "artifact_paths": []}
        return 0

    timeout_sec = int(execution.get("timeout_sec") or 3600)
    report["execution"]["started_at_utc"] = utc_now()
    try:
        proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=timeout_sec)
        report["execution"]["return_code"] = proc.returncode
        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")
        business_result = parse_business_result(spec, proc.stdout or "", cwd, repo_path)
        if business_result is None and execution.get("business_result_required", True):
            raise WorkerTaskError(TOKEN_BUSINESS_VERDICT_MISSING, "business result missing; runner must write JSON verdict")
        if business_result is None:
            business_result = {
                "verdict": "ACCEPT" if proc.returncode == 0 else "BLOCK",
                "validator_verdict": "PASS" if proc.returncode == 0 else "FAIL",
                "blocker_token": None if proc.returncode == 0 else TOKEN_TRANSPORT_FAILED,
                "artifact_paths": [],
            }
        report["business_result"] = {
            "verdict": business_result.get("verdict"),
            "validator_verdict": business_result.get("validator_verdict"),
            "blocker_token": business_result.get("blocker_token"),
            "artifact_paths": business_result.get("artifact_paths") or [],
            "raw": business_result,
        }
        enforce_side_effect_contract(spec, report, business_result)
        if proc.returncode != 0:
            return proc.returncode
        if not report["business_result"].get("verdict"):
            report["business_result"]["blocker_token"] = TOKEN_BUSINESS_VERDICT_MISSING
            return 1
        return 0 if str(report["business_result"].get("verdict")).upper() in {"ACCEPT", "PASS"} else 1
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        report["execution"]["return_code"] = 124
        report["business_result"] = {"verdict": "BLOCK", "validator_verdict": "FAIL", "blocker_token": TOKEN_TRANSPORT_FAILED, "artifact_paths": [], "timeout_sec": timeout_sec}
        return 124
    finally:
        report["execution"]["ended_at_utc"] = utc_now()


def run_task_spec(
    task_spec_path: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
    preflight_only: bool = False,
) -> tuple[int, dict[str, Any]]:
    spec_path = Path(task_spec_path).expanduser().resolve()
    output_report_path = Path(report_path).expanduser().resolve() if report_path else spec_path.with_name(f"worker_command_report__{spec_path.stem}.json")
    report: dict[str, Any] | None = None
    try:
        spec = load_json(spec_path)
        ensure_task_spec(spec)
        report = build_initial_report(spec, spec_path)
        run_preflight(spec, report, spec_path)
        rc = execute_task(spec, report, spec_path, dry_run=dry_run, preflight_only=preflight_only)
    except WorkerTaskError as exc:
        if report is None:
            try:
                spec = load_json(spec_path) if spec_path.exists() else {}
            except Exception:
                spec = {}
            report = build_initial_report(spec if isinstance(spec, dict) else {}, spec_path)
        report["business_result"] = {
            "verdict": "BLOCK",
            "validator_verdict": "FAIL",
            "blocker_token": exc.token,
            "artifact_paths": [],
            "message": exc.message,
            "details": exc.details,
        }
        rc = 1
    except Exception as exc:
        report = build_initial_report({}, spec_path)
        report["business_result"] = {
            "verdict": "BLOCK",
            "validator_verdict": "FAIL",
            "blocker_token": TOKEN_TRANSPORT_FAILED,
            "artifact_paths": [],
            "message": str(exc),
        }
        rc = 1
    write_json_atomic(output_report_path, report)
    report["report_path"] = str(output_report_path)
    return rc, report


def validate_worker_command_report(report: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, message: str = "", **details: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "message": message, **details})

    check("schema_version", report.get("schema_version") == REPORT_SCHEMA_VERSION, f"schema_version must be {REPORT_SCHEMA_VERSION}")
    task_id = report.get("task_id")
    check("task_id_present", isinstance(task_id, str) and bool(task_id.strip()), "task_id is required")

    transport = report.get("transport") if isinstance(report.get("transport"), dict) else {}
    transport_type = transport.get("type")
    check("transport_type_present", isinstance(transport_type, str) and bool(transport_type.strip()), "transport.type is required")
    if transport_type == "ssm":
        check("ssm_command_id_present", bool(transport.get("command_id")), "transport.command_id is required for ssm")
        check("ssm_instance_id_present", bool(transport.get("instance_id")), "transport.instance_id is required for ssm")
        check("ssm_status_success", transport.get("ssm_status") == "Success", "transport.ssm_status must be Success")

    runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else {}
    check("runtime_python_present", bool(runtime.get("python_path")), "runtime.python_path is required")
    source_bundle_sha = runtime.get("source_bundle_sha256")
    check(
        "runtime_source_identity_present",
        bool(runtime.get("git_sha")) or bool(source_bundle_sha),
        "runtime requires git_sha or source_bundle_sha256",
    )
    required_sha = runtime.get("git_sha_required")
    if required_sha:
        check("runtime_git_sha_matches_required", runtime.get("git_sha") == required_sha, "runtime.git_sha must match runtime.git_sha_required", required_sha=required_sha, actual_sha=runtime.get("git_sha"))
    required_bundle_sha = runtime.get("source_bundle_sha256_required")
    if required_bundle_sha:
        check(
            "runtime_source_bundle_sha_matches_required",
            source_bundle_sha == required_bundle_sha,
            "runtime.source_bundle_sha256 must match the required bundle identity",
            required_sha=required_bundle_sha,
            actual_sha=source_bundle_sha,
        )

    preflight = report.get("preflight") if isinstance(report.get("preflight"), dict) else {}
    check("preflight_pass", preflight.get("status") == "PASS", "preflight.status must be PASS")
    for item in preflight.get("checks") or []:
        if isinstance(item, dict):
            check(f"preflight_check_{item.get('name')}", item.get("ok") is True, "preflight check failed", check_detail=item)

    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    rc = execution.get("return_code")
    verdict = ((report.get("business_result") or {}).get("verdict") if isinstance(report.get("business_result"), dict) else None)
    if verdict != "PREFLIGHT_PASS":
        check("execution_return_code_zero", rc == 0, "execution.return_code must be 0", return_code=rc)
    check("execution_stdout_path_present", bool(execution.get("stdout_path")), "execution.stdout_path is required")
    check("execution_stderr_path_present", bool(execution.get("stderr_path")), "execution.stderr_path is required")

    business = report.get("business_result") if isinstance(report.get("business_result"), dict) else {}
    check("business_verdict_present", bool(business.get("verdict")), "business_result.verdict is required")
    check("business_verdict_accept", business.get("verdict") in {"ACCEPT", "PASS", "PREFLIGHT_PASS"}, "business_result.verdict must be ACCEPT/PASS/PREFLIGHT_PASS", verdict=business.get("verdict"), blocker_token=business.get("blocker_token"))
    check("business_validator_pass", business.get("validator_verdict") in {"PASS", "ACCEPT"}, "business_result.validator_verdict must be PASS/ACCEPT", validator_verdict=business.get("validator_verdict"))

    side_effects = report.get("side_effects") if isinstance(report.get("side_effects"), dict) else {}
    expected_side_effects = dict(DEFAULT_SIDE_EFFECTS)
    if isinstance(report.get("side_effect_contract"), dict):
        expected_side_effects.update(report["side_effect_contract"])
    for key in sorted(DEFAULT_SIDE_EFFECTS):
        check(f"side_effect_{key}_declared", key in side_effects, f"side_effects.{key} must be declared")
        if key in side_effects:
            expected = expected_side_effects[key]
            check(
                f"side_effect_{key}_matches_contract",
                side_effects.get(key) == expected,
                f"side_effects.{key} must match side_effect_contract",
                expected=expected,
                observed=side_effects.get(key),
            )

    failed = [item for item in checks if not item.get("ok")]
    blocker = None
    if failed:
        failed_names = {str(item.get("name")) for item in failed}
        if any(name.startswith("business_") for name in failed_names):
            blocker = TOKEN_BUSINESS_VERDICT_FAILED
        elif any(name.startswith("side_effect_") for name in failed_names):
            blocker = TOKEN_SIDE_EFFECT_CONTRACT_VIOLATED
        else:
            blocker = TOKEN_REPORT_SCHEMA_INVALID
    return {
        "schema_version": "worker_command_report_validation_v1",
        "verdict": "ACCEPT" if not failed else "BLOCK",
        "blocker_token": blocker,
        "checks": checks,
        "failed_checks": failed,
    }
