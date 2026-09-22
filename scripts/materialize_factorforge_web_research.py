#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [item for item in sys.path if item != str(REPO_ROOT)]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_research_plan import (
    AUTHORING_REQUEST_BINDING_SCOPE,
    BOOTSTRAP_VERSION,
    BLOCK_PLAN_CATALOG_INVALID,
    WebResearchPlanError,
    authoring_request_binding_hash,
    build_protocol_payloads,
    build_step1_payloads,
    resolve_workspace_approved_catalog,
    sha256_file,
    stable_json_hash,
    validate_materialized_web_research,
    validate_plan,
    write_json_atomic,
)
from factor_factory.console.conversation_ledger import (
    CONVERSATION_LEDGER_REFERENCE_FIELD,
)
from factor_factory.console.web_factor_proof import (
    prepare_web_factor_proof,
    web_factor_proof_paths,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_snapshot_path,
    research_protocol_paths,
)
from factor_factory.research_org import (
    ResearchOrganizationError,
    validate_research_organization_runtime,
)
from factor_factory.oos_exposure_incident import (
    OOS_EXPOSURE_INSTALLATION_ID_ENV,
    OOS_EXPOSURE_TRUST_ROOT_ENV,
)


BLOCK_RESEARCH_ORG_NOT_FORMAL = (
    "BLOCK_FACTORFORGE_WEB_RESEARCH_ORG_RUNTIME_NOT_FORMAL_COMPLETE"
)


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


def _materialization_runtime_gate(
    *,
    workspace: Path,
    runtime_mode: str,
    private_root: Path | None,
    trust_root: Path | None,
    installation_id: str | None,
    allow_preformal_contract_smoke: bool,
) -> dict[str, Any]:
    organization_plan = workspace / "identity" / "research_organization_plan.json"
    if not organization_plan.is_file() or organization_plan.is_symlink():
        return {
            "materialization_authority": "legacy_non_organization_workspace",
            "formal_independence_verified": False,
        }
    if allow_preformal_contract_smoke:
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        if temporary_root != workspace and temporary_root not in workspace.parents:
            raise WebResearchPlanError(
                BLOCK_RESEARCH_ORG_NOT_FORMAL,
                ["preformal_contract_smoke_must_be_under_system_temp"],
            )
        return {
            "materialization_authority": "contract_smoke_only",
            "formal_independence_verified": False,
        }
    if runtime_mode != "formal-complete":
        raise WebResearchPlanError(
            BLOCK_RESEARCH_ORG_NOT_FORMAL,
            ["research_org_runtime_mode_must_be_formal_complete"],
        )
    if private_root is None or trust_root is None or not installation_id:
        raise WebResearchPlanError(
            BLOCK_RESEARCH_ORG_NOT_FORMAL,
            ["formal_runtime_arguments_missing"],
        )
    try:
        runtime = validate_research_organization_runtime(
            workspace=workspace,
            require_complete=True,
            private_root=private_root,
            trust_root=trust_root,
            installation_id=installation_id,
            require_formal=True,
        )
    except ResearchOrganizationError as exc:
        raise WebResearchPlanError(
            BLOCK_RESEARCH_ORG_NOT_FORMAL,
            [str(exc)],
        ) from exc
    if (
        runtime.get("lifecycle") != "COMPLETE"
        or runtime.get("formal_independence_verified") is not True
    ):
        raise WebResearchPlanError(
            BLOCK_RESEARCH_ORG_NOT_FORMAL,
            ["formal_independence_not_verified"],
        )
    return {
        "materialization_authority": "signed_formal_runtime_complete",
        "runtime_id": runtime["runtime_id"],
        "runtime_assurance": runtime["runtime_assurance"],
        "formal_independence_verified": True,
    }


def materialize(
    *,
    workspace: Path,
    plan_path: Path,
    runtime_mode: str = "off",
    private_root: Path | None = None,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    allow_preformal_contract_smoke: bool = False,
) -> dict[str, Any]:
    workspace = workspace.expanduser().resolve(strict=True)
    plan_path = plan_path.expanduser().resolve(strict=True)
    plan_path.relative_to(workspace)
    incident_trust_root = incident_trust_root or (
        Path(os.environ.get(OOS_EXPOSURE_TRUST_ROOT_ENV) or os.environ.get(
            "FACTORFORGE_OOS_HOST_TRUST_ROOT"
        ))
        if (
            os.environ.get(OOS_EXPOSURE_TRUST_ROOT_ENV)
            or os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT")
        )
        else None
    )
    incident_installation_id = incident_installation_id or os.environ.get(
        OOS_EXPOSURE_INSTALLATION_ID_ENV
    ) or os.environ.get("FACTORFORGE_OOS_HOST_INSTALLATION_ID")
    if not incident_trust_root or not incident_installation_id:
        raise ValueError(
            "BLOCK_FACTORFORGE_WEB_PREREGISTRATION_INCIDENT_HOST_CONTEXT_REQUIRED"
        )
    runtime_gate = _materialization_runtime_gate(
        workspace=workspace,
        runtime_mode=runtime_mode,
        private_root=(private_root.expanduser().resolve(strict=True) if private_root else None),
        trust_root=(trust_root.expanduser().resolve(strict=True) if trust_root else None),
        installation_id=installation_id,
        allow_preformal_contract_smoke=allow_preformal_contract_smoke,
    )
    result_path = workspace / "identity" / "web_research_bootstrap_result.json"
    if result_path.exists() or result_path.is_symlink():
        if not result_path.is_file() or result_path.is_symlink():
            raise WebResearchPlanError(
                "BLOCK_FACTORFORGE_WEB_RESEARCH_BOOTSTRAP_IMMUTABLE",
                ["existing bootstrap result is missing or unsafe"],
            )
        existing = _read_json(result_path)
        if existing.get("verdict") == "PASS":
            if existing.get("research_organization_runtime") != runtime_gate:
                raise WebResearchPlanError(
                    "BLOCK_FACTORFORGE_WEB_RESEARCH_BOOTSTRAP_IMMUTABLE",
                    ["existing bootstrap runtime authority mismatch"],
                )
            if incident_trust_root is None or not incident_installation_id:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_PREREGISTRATION_INCIDENT_HOST_CONTEXT_REQUIRED"
                )
            validate_materialized_web_research(
                workspace,
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                current_authority=True,
            )
            return {**existing, "idempotent_reuse": True}
    plan = _read_json(plan_path)
    _, formula_ir = validate_plan(plan, workspace=workspace)
    catalog_sha256 = _catalog_snapshot_hash(workspace)
    knowledge_summary = _read_json(workspace / "identity" / "factor_knowledge_summary.json")
    request = _read_json(workspace / "identity" / "web_research_request.json")
    authoring_contract_path = workspace / "identity" / "web_research_authoring_contract.json"
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
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
    )
    proof_paths = web_factor_proof_paths(workspace, report_id)

    # Freeze the epistemic lifecycle only after the trial ledger, thresholds,
    # and metric specification exist.  This first event records no empirical
    # result and cannot qualify a contradiction.
    evo_root = protocol_paths["evo_lifecycle"].parent
    freeze_verifier_path = evo_root / "prediction_freeze_verifier.json"
    freeze_window_hash = stable_json_hash(
        {
            "research_conjecture_sha256": sha256_file(protocol_paths["conjecture"]),
            "search_trial_ledger_sha256": sha256_file(proof_paths["search_ledger"]),
            "threshold_registration_sha256": sha256_file(proof_paths["threshold"]),
            "metric_verifier_spec_sha256": sha256_file(proof_paths["spec"]),
        }
    )
    freeze_verifier = {
        "contract_version": "factorforge_evo_v2_prediction_freeze_verifier_v1",
        "report_id": report_id,
        "verifier_id": "factorforge_evo_v2_prediction_freeze_verifier_v1",
        "verifier_status": "PASS",
        "dataset_snapshot_hash": catalog_sha256,
        "window_hash": freeze_window_hash,
        "information_set": "PREREGISTRATION_ONLY_NO_EMPIRICAL_EVIDENCE",
        "oos_accessed": False,
        "plan_sha256": sha256_file(plan_path),
        "formula_hash": str(formula_ir["formula_hash"]),
    }
    write_json_atomic(freeze_verifier_path, freeze_verifier)
    freeze_ref = {
        "path": str(freeze_verifier_path.relative_to(workspace)),
        "sha256": sha256_file(freeze_verifier_path),
        "dataset_snapshot_hash": catalog_sha256,
        "window_hash": freeze_window_hash,
        "verifier_id": "factorforge_evo_v2_prediction_freeze_verifier_v1",
        "verifier_status": "PASS",
    }
    lifecycle = build_epistemic_evolution_lifecycle(
        report_id=report_id,
        to_state="PREDICTIONS_FROZEN",
        evidence_refs=[freeze_ref],
    )
    write_json_atomic(protocol_paths["evo_lifecycle"], lifecycle)
    write_json_atomic(
        epistemic_evolution_lifecycle_snapshot_path(workspace, report_id, 1),
        lifecycle,
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
        "host_authoring_contract_sha256": sha256_file(authoring_contract_path),
        "host_request_sha256": stable_json_hash(request),
        "host_request_binding_scope": AUTHORING_REQUEST_BINDING_SCOPE,
        "host_request_binding_sha256": authoring_request_binding_hash(request),
        "host_conversation_ledger_checkpoint": request.get(
            CONVERSATION_LEDGER_REFERENCE_FIELD
        ),
        "host_knowledge_summary_sha256": stable_json_hash(knowledge_summary),
        "approved_catalog_sha256": catalog_sha256,
        "trusted_codegen_only": True,
        "semantic_projection_only": True,
        "empirical_evidence_created": False,
        "research_organization_runtime": runtime_gate,
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
            "evo_v2_prediction_freeze_verifier": str(
                freeze_verifier_path.relative_to(workspace)
            ),
            "evo_v2_lifecycle": str(
                protocol_paths["evo_lifecycle"].relative_to(workspace)
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
    parser.add_argument(
        "--research-org-runtime-mode",
        choices=["off", "formal-complete"],
        default="off",
    )
    parser.add_argument("--research-org-runtime-private-root", default=None)
    parser.add_argument("--research-org-runtime-trust-root", default=None)
    parser.add_argument("--research-org-runtime-installation-id", default=None)
    parser.add_argument("--incident-trust-root", default=None)
    parser.add_argument("--incident-installation-id", default=None)
    parser.add_argument(
        "--allow-preformal-contract-smoke",
        action="store_true",
        help="Allow contract-only materialization under the system temp directory; never formal proof.",
    )
    args = parser.parse_args()
    try:
        result = materialize(
            workspace=Path(args.workspace_root),
            plan_path=Path(args.plan),
            runtime_mode=args.research_org_runtime_mode,
            private_root=(
                Path(args.research_org_runtime_private_root)
                if args.research_org_runtime_private_root
                else None
            ),
            trust_root=(
                Path(args.research_org_runtime_trust_root)
                if args.research_org_runtime_trust_root
                else None
            ),
            installation_id=args.research_org_runtime_installation_id,
            incident_trust_root=(
                Path(args.incident_trust_root)
                if args.incident_trust_root
                else None
            ),
            incident_installation_id=args.incident_installation_id,
            allow_preformal_contract_smoke=args.allow_preformal_contract_smoke,
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
