#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.worker_execution import (
    SCHEMA_VERSION,
    TOKEN_BUSINESS_VERDICT_MISSING,
    TOKEN_BUSINESS_VERDICT_FAILED,
    TOKEN_REPO_SHA_MISMATCH,
    TOKEN_SIDE_EFFECT_CONTRACT_VIOLATED,
    run_task_spec,
    validate_worker_command_report,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_runner(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--business-result', required=True)
parser.add_argument('--marker', default=None)
parser.add_argument('--side-effect', action='store_true')
parser.add_argument('--no-verdict', action='store_true')
args = parser.parse_args()
if args.marker:
    Path(args.marker).write_text('executed', encoding='utf-8')
if args.no_verdict:
    print('no structured verdict')
    raise SystemExit(0)
payload = {
    'verdict': 'ACCEPT',
    'validator_verdict': 'PASS',
    'artifact_paths': [str(Path(args.business_result).resolve())],
    'side_effects': {
        'clean_data_started': bool(args.side_effect),
        'search_worker_started': False,
        'official_promotion_written': False,
        'production_loop_started': False,
        's3_written': False,
        'installed_skill_modified': False,
        'worker_process_started': False,
    },
}
Path(args.business_result).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(payload, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def current_sha() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, text=True, capture_output=True).stdout.strip()


def base_spec(tmp: Path, runner: Path, business: Path, marker: Path | None = None) -> dict:
    argv = ["--business-result", str(business)]
    if marker:
        argv.extend(["--marker", str(marker)])
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "worker_execution_contract_smoke",
        "project": "factor-forge",
        "transport": {"type": "local"},
        "runtime": {
            "repo_path": str(ROOT),
            "workspace_path": str(ROOT),
            "python": sys.executable,
        },
        "preflight": {
            "git_sha_required": current_sha(),
            "python_imports": ["json"],
            "require_paths": ["scripts/run_worker_task_spec.py"],
        },
        "execution": {
            "runner": str(runner),
            "argv": argv,
            "cwd": str(ROOT),
            "output_dir": str(tmp / "task_output"),
            "business_result_path": str(business),
            "business_result_required": True,
            "timeout_sec": 30,
        },
        "side_effect_contract": {
            "clean_data_started": False,
            "search_worker_started": False,
            "official_promotion_written": False,
            "production_loop_started": False,
            "s3_written": False,
            "installed_skill_modified": False,
            "worker_process_started": False,
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="factorforge_worker_execution_contract_") as raw:
        tmp = Path(raw)
        runner = tmp / "business_runner.py"
        write_runner(runner)

        ok_business = tmp / "business_result.json"
        marker = tmp / "marker.txt"
        spec = base_spec(tmp, runner, ok_business, marker)
        spec_path = tmp / "task_spec.json"
        write_json(spec_path, spec)
        rc, report = run_task_spec(spec_path, report_path=tmp / "worker_command_report.json")
        cases = {
            "valid_task_accepts": rc == 0 and report["business_result"]["verdict"] == "ACCEPT",
            "report_records_runtime": report["runtime"]["git_sha"] == current_sha() and bool(report["runtime"]["python_path"]),
            "report_records_stdout_stderr": Path(report["execution"]["stdout_path"]).exists() and Path(report["execution"]["stderr_path"]).exists(),
            "side_effects_declared_false": report["side_effects"]["clean_data_started"] is False,
            "runner_executed": marker.exists(),
        }
        validation = validate_worker_command_report(report)
        cases["valid_report_validator_accepts"] = validation["verdict"] == "ACCEPT"

        dry_marker = tmp / "dry_marker.txt"
        dry_business = tmp / "dry_business.json"
        dry_spec = base_spec(tmp, runner, dry_business, dry_marker)
        dry_spec_path = tmp / "dry_task_spec.json"
        write_json(dry_spec_path, dry_spec)
        dry_rc, dry_report = run_task_spec(dry_spec_path, report_path=tmp / "dry_report.json", preflight_only=True)
        cases["preflight_only_does_not_execute_runner"] = dry_rc == 0 and not dry_marker.exists() and dry_report["business_result"]["verdict"] == "PREFLIGHT_PASS"

        mismatch = base_spec(tmp, runner, tmp / "mismatch_business.json")
        mismatch["preflight"]["git_sha_required"] = "0" * 40
        mismatch_path = tmp / "mismatch_spec.json"
        write_json(mismatch_path, mismatch)
        mismatch_rc, mismatch_report = run_task_spec(mismatch_path, report_path=tmp / "mismatch_report.json")
        cases["git_sha_mismatch_blocks"] = mismatch_rc != 0 and mismatch_report["business_result"]["blocker_token"] == TOKEN_REPO_SHA_MISMATCH
        mismatch_validation = validate_worker_command_report(mismatch_report)
        cases["blocked_report_validator_blocks"] = mismatch_validation["verdict"] == "BLOCK"

        side = base_spec(tmp, runner, tmp / "side_business.json")
        side["execution"]["argv"].append("--side-effect")
        side_path = tmp / "side_spec.json"
        write_json(side_path, side)
        side_rc, side_report = run_task_spec(side_path, report_path=tmp / "side_report.json")
        cases["side_effect_violation_blocks"] = side_rc != 0 and side_report["business_result"]["blocker_token"] == TOKEN_SIDE_EFFECT_CONTRACT_VIOLATED

        no_verdict = base_spec(tmp, runner, tmp / "missing_business.json")
        no_verdict["execution"].pop("business_result_path", None)
        no_verdict["execution"]["argv"].append("--no-verdict")
        no_verdict_path = tmp / "no_verdict_spec.json"
        write_json(no_verdict_path, no_verdict)
        no_verdict_rc, no_verdict_report = run_task_spec(no_verdict_path, report_path=tmp / "no_verdict_report.json")
        cases["missing_business_verdict_blocks"] = no_verdict_rc != 0 and no_verdict_report["business_result"]["blocker_token"] == TOKEN_BUSINESS_VERDICT_MISSING
        no_verdict_validation = validate_worker_command_report(no_verdict_report)
        cases["missing_business_validator_blocks"] = no_verdict_validation["verdict"] == "BLOCK" and no_verdict_validation["blocker_token"] == TOKEN_BUSINESS_VERDICT_FAILED

        validator_cli = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "validate_worker_command_report.py"),
                str(tmp / "worker_command_report.json"),
            ],
            text=True,
            capture_output=True,
        )
        cases["validator_cli_accepts_valid_report"] = validator_cli.returncode == 0 and json.loads(validator_cli.stdout)["verdict"] == "ACCEPT"

        dry_ssm = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_worker_task_via_ssm.py"),
                "--instance-id",
                "i-smoke",
                "--task-spec",
                str(spec_path),
                "--remote-spec-path",
                "/tmp/factorforge/task_spec.json",
                "--remote-runner",
                "/home/ubuntu/factorforge/scripts/run_worker_task_spec.py",
                "--dry-run-local",
            ],
            text=True,
            capture_output=True,
        )
        dry_payload = json.loads(dry_ssm.stdout)
        joined_commands = "\n".join(dry_payload.get("commands") or [])
        cases["ssm_dry_run_uses_task_spec_runner"] = (
            dry_ssm.returncode == 0
            and "run_worker_task_spec.py" in joined_commands
            and "business_runner.py" not in joined_commands
        )

        verdict = "ACCEPT" if all(cases.values()) else "BLOCK"
        summary = {
            "verdict": verdict,
            "cases": cases,
            "report_path": str(tmp / "worker_command_report.json"),
            "sample_report": report,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
