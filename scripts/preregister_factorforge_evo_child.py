#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_child_preregistration import (
    WAITING_EVO_CHILD_PREREGISTRATION,
    EvoChildPreregistrationError,
    materialize_evo_child_preregistration,
    project_authorized_evo_child_search_trial_ledger,
    project_evo_child_metric_verifier_spec,
    project_evo_child_search_identities,
    project_evo_child_threshold_registration,
    project_evo_child_web_research_plan,
    validate_evo_child_preregistration_inputs,
    validate_evo_child_preregistration_receipt,
)
from factor_factory.evo_v2 import canonical_json_bytes


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--parent-report-id", required=True)
    parser.add_argument("--child-report-id", required=True)
    parser.add_argument(
        "--expected-host-trust-manifest-sha256",
        required=True,
        help=(
            "Out-of-band SHA-256 pin for the Host public trust manifest; never "
            "derived from the workspace under validation."
        ),
    )


def _require_incident_host_context(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--incident-trust-root",
        required=True,
        help=(
            "Host-private OOS exposure incident trust root used for current "
            "formal authority validation."
        ),
    )
    parser.add_argument(
        "--incident-installation-id",
        required=True,
        help=(
            "Host installation id bound to --incident-trust-root for current "
            "formal authority validation."
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project or materialize EVO V2 child preregistration. The command "
            "never authors economic semantics, signs approval, releases OOS, "
            "executes a child, or issues a factor verdict. Projection commands "
            "are development/read-only helpers; formal validate/materialize "
            "require the canonical Agent-authoring admission."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser(
        "project-ledger",
        help=(
            "Read the canonical public authorization/addendum and print the exact "
            "final child ledger plus the file SHA needed by the Host threshold."
        ),
    )
    _common(project)
    project.add_argument("--base-search-trial-ledger", required=True)

    project_spec = commands.add_parser(
        "project-spec",
        help=(
            "Replay protected parent contracts and print the only admissible "
            "child metric-verifier spec."
        ),
    )
    _common(project_spec)
    project_spec.add_argument("--conjecture", required=True)

    project_threshold = commands.add_parser(
        "project-threshold",
        help="Print the unique child threshold derived from frozen controls.",
    )
    _common(project_threshold)
    project_threshold.add_argument("--conjecture", required=True)
    project_threshold.add_argument("--search-trial-ledger", required=True)
    project_threshold.add_argument("--metric-verifier-spec", required=True)

    project_plan = commands.add_parser(
        "project-child-web-plan",
        help=(
            "Validate an Agent-authored child Web plan and print its immutable "
            "Host governance envelope."
        ),
    )
    _common(project_plan)
    project_plan.add_argument("--conjecture", required=True)
    project_plan.add_argument("--approaches", required=True)
    project_plan.add_argument("--search-trial-ledger", required=True)
    project_plan.add_argument("--metric-verifier-spec", required=True)
    project_plan.add_argument("--threshold-registration", required=True)
    project_plan.add_argument("--child-web-research-plan", required=True)

    project_search = commands.add_parser(
        "project-search-identity",
        help=(
            "Print the exact candidate-space and selected-hypothesis hashes "
            "required in the Agent-supplied base ledger."
        ),
    )
    _common(project_search)
    project_search.add_argument("--conjecture", required=True)

    validate = commands.add_parser(
        "validate",
        help="Validate the complete child preregistration without writing it.",
    )
    _common(validate)
    _require_incident_host_context(validate)
    validate.add_argument("--state", required=True)
    validate.add_argument("--conjecture", required=True)
    validate.add_argument("--approaches", required=True)
    validate.add_argument("--base-search-trial-ledger", required=True)
    validate.add_argument("--metric-verifier-spec", required=True)
    validate.add_argument("--threshold-registration", required=True)
    validate.add_argument("--child-web-research-plan", required=True)
    validate.add_argument(
        "--agent-authoring-admission",
        required=True,
        help="Canonical Host-countersigned Agent-authoring admission path.",
    )

    materialize = commands.add_parser(
        "materialize",
        help=(
            "Validate and create-only publish Agent/Host supplied child controls. "
            "READY remains a separate Host-signed ticket."
        ),
    )
    _common(materialize)
    _require_incident_host_context(materialize)
    materialize.add_argument("--state", required=True)
    materialize.add_argument("--conjecture", required=True)
    materialize.add_argument("--approaches", required=True)
    materialize.add_argument("--base-search-trial-ledger", required=True)
    materialize.add_argument("--metric-verifier-spec", required=True)
    materialize.add_argument("--threshold-registration", required=True)
    materialize.add_argument("--child-web-research-plan", required=True)
    materialize.add_argument(
        "--agent-authoring-admission",
        required=True,
        help="Canonical Host-countersigned Agent-authoring admission path.",
    )

    validate_receipt = commands.add_parser(
        "validate-receipt",
        help="Strictly replay the canonical preregistration before READY signing.",
    )
    _common(validate_receipt)
    _require_incident_host_context(validate_receipt)
    return parser


def _emit(payload: dict[str, Any], *, error: bool = False) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=sys.stderr if error else sys.stdout,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "project-ledger":
            ledger = project_authorized_evo_child_search_trial_ledger(
                workspace_root=args.workspace_root,
                parent_report_id=args.parent_report_id,
                child_report_id=args.child_report_id,
                base_search_trial_ledger=args.base_search_trial_ledger,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            _emit(
                {
                    "verdict": "PASS",
                    "status": "PROJECTED_NOT_MATERIALIZED",
                    "parent_report_id": args.parent_report_id,
                    "child_report_id": args.child_report_id,
                    "projected_search_trial_ledger": ledger,
                    "projected_file_sha256": hashlib.sha256(
                        canonical_json_bytes(ledger)
                    ).hexdigest(),
                    "threshold_binding": {
                        "search_trial_ledger_ref": (
                            "objects/research_protocol/"
                            f"search_trial_ledger__{args.child_report_id}.json"
                        ),
                        "search_trial_ledger_sha256": hashlib.sha256(
                            canonical_json_bytes(ledger)
                        ).hexdigest(),
                    },
                    "writes_performed": False,
                    "authority": {
                        "human_approval_granted": False,
                        "child_execution_allowed": False,
                        "oos_accessed": False,
                        "factor_verdict": "NOT_ISSUED",
                    },
                }
            )
            return 0
        if args.command == "project-spec":
            spec = project_evo_child_metric_verifier_spec(
                workspace_root=args.workspace_root,
                parent_report_id=args.parent_report_id,
                child_report_id=args.child_report_id,
                research_conjecture=args.conjecture,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            _emit(
                {
                    "verdict": "PASS",
                    "status": "PROJECTED_NOT_MATERIALIZED",
                    "parent_report_id": args.parent_report_id,
                    "child_report_id": args.child_report_id,
                    "projected_metric_verifier_spec": spec,
                    "projected_file_sha256": hashlib.sha256(
                        canonical_json_bytes(spec)
                    ).hexdigest(),
                    "writes_performed": False,
                    "factor_verdict": "NOT_ISSUED",
                }
            )
            return 0
        if args.command == "project-threshold":
            threshold = project_evo_child_threshold_registration(
                workspace_root=args.workspace_root,
                parent_report_id=args.parent_report_id,
                child_report_id=args.child_report_id,
                research_conjecture=args.conjecture,
                search_trial_ledger=args.search_trial_ledger,
                metric_verifier_spec=args.metric_verifier_spec,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            _emit(
                {
                    "verdict": "PASS",
                    "status": "PROJECTED_NOT_MATERIALIZED",
                    "parent_report_id": args.parent_report_id,
                    "child_report_id": args.child_report_id,
                    "projected_threshold_registration": threshold,
                    "projected_file_sha256": hashlib.sha256(
                        canonical_json_bytes(threshold)
                    ).hexdigest(),
                    "writes_performed": False,
                    "factor_verdict": "NOT_ISSUED",
                }
            )
            return 0
        if args.command == "project-child-web-plan":
            projection = project_evo_child_web_research_plan(
                workspace_root=args.workspace_root,
                parent_report_id=args.parent_report_id,
                child_report_id=args.child_report_id,
                research_conjecture=args.conjecture,
                approach_registry=args.approaches,
                search_trial_ledger=args.search_trial_ledger,
                metric_verifier_spec=args.metric_verifier_spec,
                threshold_registration=args.threshold_registration,
                agent_authored_child_web_research_plan=(
                    args.child_web_research_plan
                ),
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            _emit(
                {
                    "verdict": "PASS",
                    "status": "PROJECTED_NOT_MATERIALIZED",
                    "parent_report_id": args.parent_report_id,
                    "child_report_id": args.child_report_id,
                    "projected_child_web_research_plan": projection,
                    "projected_file_sha256": hashlib.sha256(
                        canonical_json_bytes(projection)
                    ).hexdigest(),
                    "writes_performed": False,
                    "factor_verdict": "NOT_ISSUED",
                }
            )
            return 0
        if args.command == "project-search-identity":
            conjecture_path = Path(args.conjecture).expanduser()
            conjecture = json.loads(conjecture_path.read_text(encoding="utf-8"))
            if not isinstance(conjecture, dict):
                raise ValueError("research_conjecture_object_required")
            projection = project_evo_child_search_identities(conjecture)
            if (
                conjecture.get("report_id") != args.child_report_id
                or args.parent_report_id == args.child_report_id
            ):
                raise ValueError("research_conjecture_child_identity_mismatch")
            _emit(
                {
                    "verdict": "PASS",
                    "status": "PROJECTED_NOT_MATERIALIZED",
                    "parent_report_id": args.parent_report_id,
                    "child_report_id": args.child_report_id,
                    "search_identity_projection": projection,
                    "writes_performed": False,
                    "factor_verdict": "NOT_ISSUED",
                }
            )
            return 0
        if args.command == "validate-receipt":
            _emit(
                validate_evo_child_preregistration_receipt(
                    workspace_root=args.workspace_root,
                    parent_report_id=args.parent_report_id,
                    child_report_id=args.child_report_id,
                    expected_host_trust_manifest_sha256=(
                        args.expected_host_trust_manifest_sha256
                    ),
                    incident_trust_root=Path(args.incident_trust_root),
                    incident_installation_id=args.incident_installation_id,
                )
            )
            return 0
        common_inputs = {
            "workspace_root": args.workspace_root,
            "parent_report_id": args.parent_report_id,
            "child_report_id": args.child_report_id,
            "research_state": args.state,
            "research_conjecture": args.conjecture,
            "approach_registry": args.approaches,
            "base_search_trial_ledger": args.base_search_trial_ledger,
            "metric_verifier_spec": args.metric_verifier_spec,
            "threshold_registration": args.threshold_registration,
            "agent_authored_child_web_research_plan": (
                args.child_web_research_plan
            ),
            "agent_authoring_admission": args.agent_authoring_admission,
            "expected_host_trust_manifest_sha256": (
                args.expected_host_trust_manifest_sha256
            ),
            "incident_trust_root": Path(args.incident_trust_root),
            "incident_installation_id": args.incident_installation_id,
        }
        if args.command == "validate":
            _emit(validate_evo_child_preregistration_inputs(**common_inputs))
            return 0
        result = materialize_evo_child_preregistration(
            **common_inputs,
        )
        _emit(result)
        return 0
    except EvoChildPreregistrationError as exc:
        waiting = any(
            reason.startswith(WAITING_EVO_CHILD_PREREGISTRATION)
            for reason in exc.reasons
        )
        _emit(
            {
                "verdict": "WAITING" if waiting else "BLOCK",
                "status": "WAITING_AUTHORIZATION" if waiting else "INVALID",
                "parent_report_id": args.parent_report_id,
                "child_report_id": args.child_report_id,
                "reasons": exc.reasons,
                "writes_performed": False,
                "factor_verdict": "NOT_ISSUED",
            },
            error=True,
        )
        return 3 if waiting else 1
    except (OSError, ValueError, TypeError) as exc:
        _emit(
            {
                "verdict": "BLOCK",
                "status": "UNEXPECTED_INPUT_OR_IO_ERROR",
                "parent_report_id": args.parent_report_id,
                "child_report_id": args.child_report_id,
                "reasons": [f"{type(exc).__name__}:{exc}"],
                "writes_performed": False,
                "factor_verdict": "NOT_ISSUED",
            },
            error=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
