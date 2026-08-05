#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [item for item in sys.path if item != str(REPO_ROOT)]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_research_plan import (
    BOOTSTRAP_VERSION,
    BLOCK_PLAN_CATALOG_INVALID,
    WebResearchPlanError,
    build_protocol_payloads,
    build_step1_payloads,
    resolve_workspace_approved_catalog,
    sha256_file,
    validate_materialized_web_research,
    validate_plan,
    write_json_atomic,
)
from factor_factory.console.web_factor_proof import prepare_web_factor_proof
from factor_factory.research_conjecture import research_protocol_paths


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _catalog_snapshot_hash(workspace: Path) -> str:
    _catalog_path, digest = resolve_workspace_approved_catalog(workspace)
    return digest


def _write_step1(workspace: Path, report_id: str, payloads: dict[str, dict[str, Any]]) -> dict[str, Path]:
    paths = {
        "alpha_idea_master": workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json",
        "primary_thesis": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__alpha_thesis.json",
        "challenger_thesis": workspace / "objects" / "validation" / f"report_map_validation__{report_id}__challenger_alpha_thesis.json",
        "report_map": workspace / "objects" / "report_maps" / f"report_map__{report_id}__primary.json",
    }
    write_json_atomic(paths["alpha_idea_master"], payloads["aim"])
    write_json_atomic(paths["primary_thesis"], payloads["primary"])
    write_json_atomic(paths["challenger_thesis"], payloads["challenger"])
    write_json_atomic(paths["report_map"], payloads["report_map"])
    return paths


def _run_step2(workspace: Path, report_id: str) -> None:
    os.environ["FACTORFORGE_ROOT"] = str(workspace)
    script_dir = REPO_ROOT / "skills" / "factor-forge-step2" / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from run_step2 import run_step2

    with contextlib.redirect_stdout(io.StringIO()):
        run_step2(report_id)


def _validate_command(command: list[str], *, workspace: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(workspace)
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    stdout = proc.stdout.strip()
    parsed: dict[str, Any] = {}
    if stdout:
        try:
            candidate = json.loads(stdout)
            if isinstance(candidate, dict):
                parsed = candidate
        except json.JSONDecodeError:
            parsed = {}
    return {
        "command": command[1],
        "returncode": proc.returncode,
        "result": parsed.get("result") or parsed.get("verdict") or ("PASS" if proc.returncode == 0 else "BLOCK"),
        "errors": parsed.get("errors") or parsed.get("block_reasons") or [],
        "stderr": proc.stderr.strip()[-1200:],
    }


def materialize(*, workspace: Path, plan_path: Path) -> dict[str, Any]:
    workspace = workspace.expanduser().resolve(strict=True)
    plan_path = plan_path.expanduser().resolve(strict=True)
    plan_path.relative_to(workspace)
    result_path = workspace / "identity" / "web_research_bootstrap_result.json"
    if result_path.exists() or result_path.is_symlink():
        if not result_path.is_file() or result_path.is_symlink():
            raise WebResearchPlanError(
                "BLOCK_FACTORFORGE_WEB_RESEARCH_BOOTSTRAP_IMMUTABLE",
                ["existing bootstrap result is missing or unsafe"],
            )
        existing = _read_json(result_path)
        if existing.get("verdict") == "PASS":
            validate_materialized_web_research(workspace)
            return {**existing, "idempotent_reuse": True}
    plan = _read_json(plan_path)
    _, formula_ir = validate_plan(plan, workspace=workspace)
    catalog_sha256 = _catalog_snapshot_hash(workspace)
    knowledge_summary = _read_json(workspace / "identity" / "factor_knowledge_summary.json")
    payloads = build_step1_payloads(
        plan,
        formula_ir=formula_ir,
        knowledge_summary=knowledge_summary,
    )
    report_id = str(plan["identity"]["report_id"])
    step1_paths = _write_step1(workspace, report_id, payloads)
    _run_step2(workspace, report_id)

    protocol = build_protocol_payloads(
        plan,
        workspace=workspace,
        alpha_idea_path=step1_paths["alpha_idea_master"],
        catalog_sha256=catalog_sha256,
        formula_hash=str(formula_ir["formula_hash"]),
    )
    protocol_paths = research_protocol_paths(workspace, report_id)
    for name, payload in protocol.items():
        write_json_atomic(protocol_paths[name], payload)

    proof_preregistration = prepare_web_factor_proof(
        workspace_root=workspace,
        plan=plan,
    )

    validations = [
        _validate_command(
            [sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", report_id],
            workspace=workspace,
        ),
        _validate_command(
            [sys.executable, "skills/factor-forge-step2/scripts/validate_step2.py", "--report-id", report_id],
            workspace=workspace,
        ),
        _validate_command(
            [
                sys.executable,
                "scripts/validate_factorforge_research_protocol.py",
                "--workspace-root",
                str(workspace),
                "--report-id",
                report_id,
                "--stage",
                "pre_council",
            ],
            workspace=workspace,
        ),
    ]
    failed = [item for item in validations if item["returncode"] != 0]
    result = {
        "version": BOOTSTRAP_VERSION,
        "verdict": "BLOCK" if failed else "PASS",
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
        "agent_authored_plan_sha256": sha256_file(plan_path),
        "agent_authored_formula_hash": formula_ir["formula_hash"],
        "approved_catalog_sha256": catalog_sha256,
        "trusted_codegen_only": True,
        "semantic_projection_only": True,
        "empirical_evidence_created": False,
        "validations": validations,
        "artifacts": {
            "alpha_idea_master": str(step1_paths["alpha_idea_master"].relative_to(workspace)),
            "factor_spec_master": f"objects/factor_spec_master/factor_spec_master__{report_id}.json",
            "research_state": str(protocol_paths["state"].relative_to(workspace)),
            "research_conjecture": str(protocol_paths["conjecture"].relative_to(workspace)),
            "approach_registry": str(protocol_paths["approaches"].relative_to(workspace)),
            "factor_proof_preregistration": (
                f"objects/research_protocol/"
                f"web_factor_proof_preregistration__{report_id}.json"
            ),
            "metric_verifier_spec": str(
                proof_preregistration["metric_verifier_spec_ref"]
            ),
            "threshold_registration": str(
                proof_preregistration["threshold_registration_ref"]
            ),
        },
    }
    write_json_atomic(result_path, result)
    if failed:
        raise WebResearchPlanError(
            "BLOCK_FACTORFORGE_WEB_RESEARCH_MATERIALIZATION_INVALID",
            [
                f"{item['command']}:{error}"
                for item in failed
                for error in (item["errors"] or [item["stderr"] or item["result"]])
            ],
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize an agent-authored web research plan into formal Factor Forge inputs."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    try:
        result = materialize(
            workspace=Path(args.workspace_root),
            plan_path=Path(args.plan),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, WebResearchPlanError) as exc:
        token = exc.token if isinstance(exc, WebResearchPlanError) else "BLOCK_FACTORFORGE_WEB_RESEARCH_MATERIALIZATION_FAILED"
        reasons = list(exc.reasons) if isinstance(exc, WebResearchPlanError) else [str(exc)]
        print(
            json.dumps(
                {"verdict": "BLOCK", "block_token": token, "block_reasons": reasons},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
