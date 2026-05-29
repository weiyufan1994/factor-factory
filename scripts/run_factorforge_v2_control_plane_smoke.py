#!/usr/bin/env python3
from __future__ import annotations

import sys
import shutil
import contextlib
import io
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import factorforgectl
from factor_factory.run_control import FactorForgeBlock


def assert_blocks(fn, expected_token: str) -> None:
    try:
        fn()
    except FactorForgeBlock as exc:
        assert exc.token == expected_token, (exc.token, expected_token, str(exc))
        return
    raise AssertionError(f"expected {expected_token}")


def smoke_root(name: str) -> Path:
    root = Path.home() / ".factorforge-smoke" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(factorforgectl.json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def minimal_run(root: Path, report_id: str) -> dict:
    return {
        "report_id": report_id,
        "run_id": f"smoke_{report_id}",
        "artifact_root": str(root),
        "repo_sha": factorforgectl.current_repo_sha(),
        "status": "WORKER_DONE",
        "current_step": "6",
        "runtime_context_written": True,
        "steps": {
            "step1": {"status": "PASS"},
            "step2": {"status": "PASS"},
            "step3a": {"status": "PASS"},
        },
    }


def seed_step6_inputs(root: Path, report_id: str) -> None:
    write_json(root / "objects" / "runtime_context" / f"runtime_context__{report_id}.json", {"report_id": report_id, "artifact_root": str(root)})
    write_json(root / "objects" / "factor_run_master" / f"factor_run_master__{report_id}.json", {"report_id": report_id, "run_status": "success"})
    write_json(root / "objects" / "factor_case_master" / f"factor_case_master__{report_id}.json", {"report_id": report_id, "final_status": "validated"})
    write_json(root / "objects" / "validation" / f"factor_evaluation__{report_id}.json", {"report_id": report_id, "verdict": "PASS"})
    write_json(root / "objects" / "handoff" / f"handoff_to_step6__{report_id}.json", {"report_id": report_id})


def main() -> int:
    assert factorforgectl.normalize_local_step("1") == "1"
    assert factorforgectl.normalize_local_step("step2") == "2"
    assert factorforgectl.normalize_local_step("3a") == "3a"

    assert_blocks(lambda: factorforgectl.normalize_local_step("6"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert_blocks(lambda: factorforgectl.normalize_local_step("step6"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")

    assert factorforgectl.local_prepare_end_step("1") == "1"
    assert factorforgectl.local_prepare_end_step("2") == "2"
    assert factorforgectl.local_prepare_end_step("3a") == "3a"

    assert factorforgectl.validate_local_step_range("1", "1") == ("1", "1")
    assert factorforgectl.validate_local_step_range("2", "2") == ("2", "2")
    assert factorforgectl.validate_local_step_range("3a", "3a") == ("3a", "3a")
    assert_blocks(lambda: factorforgectl.validate_local_step_range("2", "3a"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert_blocks(lambda: factorforgectl.validate_local_step_range("1", "3a"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert_blocks(lambda: factorforgectl.validate_local_step_range("3a", "2"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert factorforgectl.validate_worker_step_range("3b", "5") == ("3b", "5")
    assert factorforgectl.validate_worker_step_range("3b", "3b") == ("3b", "3b")
    assert factorforgectl.validate_worker_step_range("4", "4") == ("4", "4")
    assert factorforgectl.validate_worker_step_range("5", "5") == ("5", "5")
    assert_blocks(lambda: factorforgectl.validate_worker_step_range("3b", "4"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")

    manifest_path = "/var/lib/factorforge/artifacts/smoke_report/smoke_run/formal_run_manifest.json"
    env_overrides = factorforgectl.local_prepare_env_overrides(
        {
            "formal_run_manifest": manifest_path,
            "providers": {
                "step1": {"provider": "openclaw_pdf_tool", "model": "google/gemini-3.1-pro-preview"},
                "step2": {"provider": "deepseek", "model": "deepseek-chat"},
            },
        },
        start="2",
        formal_llm_provider="command",
        manifest=manifest_path,
    )
    assert env_overrides["FACTORFORGE_FORMAL_RUN_MANIFEST"] == manifest_path
    assert env_overrides["FACTORFORGE_CONTROL_PLANE_ENTRYPOINT"] == "factorforgectl"
    assert "FACTORFORGE_STEP2_LLM_COMMAND" in env_overrides

    direct_root = smoke_root("direct_prepare_requires_control_plane")
    fake_pdf = direct_root / "report.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n% smoke\n")
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_factorforge_formal_artifacts.py",
            "--factorforge-root",
            str(direct_root),
            "--report-id",
            "direct_prepare_smoke",
            "--report-pdf",
            str(fake_pdf),
            "--run-manifest",
            str(direct_root / "formal_run_manifest.json"),
            "--end-step",
            "2",
            "--write-report",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 1, proc
    assert "BLOCK_FACTORFORGE_CONTROL_PLANE_REQUIRED" in (proc.stdout + proc.stderr), proc.stderr

    integrity_root = smoke_root("step1_raw_integrity")
    raw_path = integrity_root / "objects" / "raw_llm" / "integrity_report" / "step1" / "step1_primary_raw.json"
    write_json(raw_path, {"provenance": {"role": "primary"}, "payload": "original"})
    raw_sha = factorforgectl.sha256_file(raw_path)
    integrity_run = {
        "artifact_root": str(integrity_root),
        "steps": {
            "step1": {
                "status": "PASS",
                "raw_outputs": [
                    {"role": "primary", "path": str(raw_path), "raw_response_sha256": raw_sha}
                ],
            }
        },
    }
    assert factorforgectl.verify_step1_raw_integrity(integrity_run) == []
    write_json(raw_path, {"provenance": {"role": "primary"}, "payload": "tampered"})
    assert_blocks(lambda: factorforgectl.verify_step1_raw_integrity(integrity_run), "BLOCK_AGENT_TOOL_STEP1_RAW_TAMPERED")

    report_id = "step6_smoke_report"
    blocked_root = smoke_root("step6_missing_worker_evidence")
    assert_blocks(
        lambda: factorforgectl.step6_readiness_checks(minimal_run(blocked_root, report_id), report_id=report_id),
        "BLOCK_STEP6_PRECONDITION_FAILED",
    )

    ready_root = smoke_root("step6_ready")
    seed_step6_inputs(ready_root, report_id)
    checks = factorforgectl.step6_readiness_checks(minimal_run(ready_root, report_id), report_id=report_id)
    assert all(item["ok"] for item in checks), checks
    command = factorforgectl.step6_command(minimal_run(ready_root, report_id), council_mode="auto")
    assert "--start-step 6 --end-step 6" in " ".join(command), command
    assert "--council-mode auto" in " ".join(command), command
    parsed = factorforgectl.build_parser().parse_args(["run-step6", "--report-id", report_id, "--dry-run"])
    assert parsed.command == "run-step6", parsed
    assert parsed.dry_run is True, parsed
    registry = ready_root / "registry.json"
    write_json(registry, {"active_runs": {report_id: minimal_run(ready_root, report_id)}})
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = factorforgectl.main(["--registry", str(registry), "run-step6", "--report-id", report_id, "--dry-run"])
    assert rc == 0, stdout.getvalue()
    updated = factorforgectl.json.loads(registry.read_text(encoding="utf-8"))
    active = updated["active_runs"][report_id]
    assert active["status"] == "STEP6_DRY_RUN_READY", active
    assert active["current_step"] == "6", active

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
