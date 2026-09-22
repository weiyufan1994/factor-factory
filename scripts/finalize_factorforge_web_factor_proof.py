#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_factor_proof import (
    HOST_AGENT_TERMINATION_AUTHORITY_VERSION,
    finalize_web_factor_proof,
    web_factor_proof_paths,
)
from factor_factory.console.evo_child_container import (
    guard_evo_child_oos_finalization,
)
from factor_factory.console.web_research_plan import (
    resolve_report_scoped_web_research_plan,
    validate_materialized_web_research,
)
from factor_factory.evo_oos import (
    OOS_ALLOCATION_AUTHORITY_SECURE,
    oos_allocation_path,
    oos_registry_path,
    resolve_host_private_oos_carrier,
    validate_child_oos_finalizer_authority,
    validate_oos_allocation,
    validate_oos_release_consumption,
    validate_oos_registry,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)

OOS_HOST_TRUST_ROOT_ENV = "FACTORFORGE_OOS_HOST_TRUST_ROOT"
OOS_HOST_INSTALLATION_ID_ENV = "FACTORFORGE_OOS_HOST_INSTALLATION_ID"
EVO_CHILD_CONTAINER_STATE_ROOT_ENV = (
    "FACTORFORGE_EVO_CHILD_CONTAINER_STATE_ROOT"
)
EVO_CHILD_CONTAINER_JOB_ID_ENV = "FACTORFORGE_EVO_CHILD_CONTAINER_JOB_ID"


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _termination_authority_projection(
    validated: dict,
    *,
    parent_report_id: str,
    child_report_id: str,
    job_id: str,
    expected_host_pin: str,
) -> dict:
    receipt = validated["termination_receipt"]
    container = receipt["container"]
    command = receipt["command"]
    workspace_post = receipt["workspace_tree"]["post_run"]
    return {
        "authority_version": HOST_AGENT_TERMINATION_AUTHORITY_VERSION,
        "termination_receipt_ref": (
            "HOST_PRIVATE_SIGNED_EVO_CHILD_CONTAINER_TERMINATION"
        ),
        "termination_receipt_id": validated["termination_receipt_id"],
        "termination_receipt_sha256": validated[
            "termination_receipt_sha256"
        ],
        "stage_name": validated["stage_name"],
        "attempt": receipt["attempt"],
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "job_id_sha256": _stable_hash(job_id),
        "expected_host_trust_manifest_sha256": expected_host_pin,
        "admission_receipt_id": receipt["admission_ref"]["receipt_id"],
        "inflight_receipt_id": receipt["inflight_ref"]["receipt_id"],
        "logical_command_sha256": command["logical_sha256"],
        "image_digest_sha256": _stable_hash(container["image_digest"]),
        "mounts_sha256": _stable_hash(container["mounts"]),
        "workspace_post_tree_sha256": workspace_post["tree_sha256"],
        "network": container["network"],
        "process_tree_absent": validated["process_tree_absent"],
    }


def _redact_host_private_values(message: str, denied_values: list[str]) -> str:
    redacted = message
    for value in sorted(
        {item for item in denied_values if item},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(value, "[HOST_PRIVATE]")
    return redacted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the web research OOS panel, replay formal metrics, and write "
            "a bound factor-proof certificate."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--plan-path", default=None)
    parser.add_argument("--expected-host-trust-manifest-sha256", default=None)
    parser.add_argument("--sealed-oos-carrier", default=None)
    parser.add_argument("--sealed-oos-private-root", default=None)
    parser.add_argument(
        "--resolve-host-private-oos",
        action="store_true",
        help=(
            "Resolve the signed Host-private carrier locator from protected "
            "environment credentials; no private OOS path appears in argv."
        ),
    )
    parser.add_argument(
        "--sealed-oos-agent-visible-root", action="append", default=[]
    )
    args = parser.parse_args()

    private_denied_values = [
        os.environ.get(OOS_HOST_TRUST_ROOT_ENV, ""),
        os.environ.get(OOS_HOST_INSTALLATION_ID_ENV, ""),
        os.environ.get(EVO_CHILD_CONTAINER_STATE_ROOT_ENV, ""),
        os.environ.get(EVO_CHILD_CONTAINER_JOB_ID_ENV, ""),
    ]
    if private_denied_values[0]:
        try:
            private_denied_values.append(
                str(
                    Path(private_denied_values[0])
                    .expanduser()
                    .resolve(strict=False)
                )
            )
        except (OSError, RuntimeError):
            # The raw value remains on the deny-list.  Resolution errors for a
            # Host-private credential must never escape as a path-bearing
            # traceback before the fixed-token finalizer error boundary.
            pass
    if private_denied_values[2]:
        try:
            private_denied_values.append(
                str(
                    Path(private_denied_values[2])
                    .expanduser()
                    .resolve(strict=False)
                )
            )
        except (OSError, RuntimeError):
            pass
    workspace = Path(args.workspace_root).expanduser().resolve(strict=True)
    trust_root_raw = os.environ.get(OOS_HOST_TRUST_ROOT_ENV, "")
    installation_id = os.environ.get(OOS_HOST_INSTALLATION_ID_ENV, "")
    finalization_stack = ExitStack()
    try:
        if not trust_root_raw or not installation_id:
            raise ValueError(
                "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_INCIDENT_HOST_CONTEXT_REQUIRED"
            )
        incident_guard = finalization_stack.enter_context(
            oos_exposure_private_registry_guard(
                Path(trust_root_raw),
                installation_id=installation_id,
            )
        )
        explicit_plan = Path(args.plan_path) if args.plan_path else None
        resolved = resolve_report_scoped_web_research_plan(
            workspace,
            report_id=args.report_id,
            plan_path=explicit_plan,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            incident_trust_root=Path(trust_root_raw),
            incident_installation_id=installation_id,
            _incident_guard=incident_guard,
            current_authority=True,
        )
        validate_materialized_web_research(
            workspace,
            report_id=args.report_id,
            plan_path=explicit_plan,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            incident_trust_root=Path(trust_root_raw),
            incident_installation_id=installation_id,
            _incident_guard=incident_guard,
            current_authority=True,
        )
        plan = resolved["plan"]
        allocation = resolved.get("allocation")
        finalization_path = web_factor_proof_paths(
            workspace,
            args.report_id,
        )["finalization"]
        completed_finalization_replay = bool(
            finalization_path.is_file() and not finalization_path.is_symlink()
        )
        if allocation is None and args.sealed_oos_carrier:
            allocation_path = oos_allocation_path(workspace, args.report_id)
            registry_path = oos_registry_path(workspace)
            if (
                not allocation_path.is_file()
                or allocation_path.is_symlink()
                or not registry_path.is_file()
                or registry_path.is_symlink()
            ):
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_ALLOCATION_REQUIRED"
                )
            allocation = json.loads(allocation_path.read_text(encoding="utf-8"))
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            reasons = [
                *validate_oos_allocation(allocation, workspace_root=workspace),
                *validate_oos_registry(registry, workspace_root=workspace),
            ]
            matching_events = [
                event
                for event in registry.get("events") or []
                if isinstance(event, dict)
                and event.get("event_type") == "ALLOCATE"
                and event.get("report_id") == args.report_id
                and event.get("allocation_ref")
                == str(allocation_path.relative_to(workspace))
                and event.get("allocation_sha256") == sha256_file(allocation_path)
            ]
            consumed = [
                event
                for event in registry.get("events") or []
                if isinstance(event, dict)
                and event.get("event_type") == "CONSUME"
                and event.get("report_id") == args.report_id
            ]
            release_path = (
                workspace
                / "objects"
                / "research_protocol"
                / f"oos_release_manifest__{args.report_id}.json"
            )
            consumed_replay_reasons = (
                validate_oos_release_consumption(
                    workspace_root=workspace,
                    report_id=args.report_id,
                    release_manifest_path=release_path,
                    incident_trust_root=Path(trust_root_raw),
                    incident_installation_id=installation_id,
                    _incident_guard=incident_guard,
                )
                if consumed
                else []
            )
            if (
                reasons
                or len(matching_events) != 1
                or len(consumed) > 1
                or consumed_replay_reasons
            ):
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_ALLOCATION_INVALID:"
                    + ";".join([*reasons, *consumed_replay_reasons])
                )
        secure_allocation = bool(
            isinstance(allocation, dict)
            and allocation.get("allocation_authority_mode")
            == OOS_ALLOCATION_AUTHORITY_SECURE
        )
        parent_report_id = str(resolved.get("parent_report_id") or "")
        allocation_id = (
            str(allocation.get("allocation_id") or "")
            if isinstance(allocation, dict)
            else ""
        )
        if secure_allocation:
            allocation_path = oos_allocation_path(workspace, args.report_id)
            if not allocation_path.is_file() or allocation_path.is_symlink():
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_ALLOCATION_READBACK"
                )
            canonical_allocation = json.loads(
                allocation_path.read_text(encoding="utf-8")
            )
            if allocation != canonical_allocation:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_ALLOCATION_READBACK"
                )
            authority_reasons = validate_child_oos_finalizer_authority(
                workspace_root=workspace,
                parent_report_id=parent_report_id,
                child_report_id=args.report_id,
                allocation_id=allocation_id,
                incident_trust_root=Path(trust_root_raw),
                incident_installation_id=installation_id,
                _incident_guard=incident_guard,
            )
            if authority_reasons:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_ALLOCATION_INVALID:"
                    + ";".join(authority_reasons)
                )
            container_state_root_raw = os.environ.get(
                EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
                "",
            )
            container_job_id = os.environ.get(
                EVO_CHILD_CONTAINER_JOB_ID_ENV,
                "",
            )
            if (
                not trust_root_raw
                or not installation_id
                or not container_state_root_raw
                or not container_job_id
                or not args.expected_host_trust_manifest_sha256
            ):
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_HOST_TERMINATION_CREDENTIALS_REQUIRED"
                )
            try:
                validated_termination = finalization_stack.enter_context(
                    guard_evo_child_oos_finalization(
                        state_root=Path(container_state_root_raw),
                        trust_root=Path(trust_root_raw),
                        installation_id=installation_id,
                        job_id=container_job_id,
                        workspace_root=workspace,
                        worktree=REPO_ROOT,
                        parent_report_id=parent_report_id,
                        child_report_id=args.report_id,
                        expected_host_pin=(
                            args.expected_host_trust_manifest_sha256
                        ),
                        _incident_guard=incident_guard,
                    )
                )
                termination_authority = _termination_authority_projection(
                    validated_termination,
                    parent_report_id=parent_report_id,
                    child_report_id=args.report_id,
                    job_id=container_job_id,
                    expected_host_pin=(
                        args.expected_host_trust_manifest_sha256
                    ),
                )
            except Exception:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_HOST_TERMINATION_GATE_FAILED"
                ) from None
        else:
            termination_authority = None
        if args.resolve_host_private_oos:
            if args.sealed_oos_carrier or args.sealed_oos_private_root:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_PATH_MIXED"
                )
            if not secure_allocation:
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_ALLOCATION_REQUIRED"
                )
            if completed_finalization_replay:
                carrier_path = None
                private_root = None
            else:
                if not trust_root_raw or not installation_id:
                    raise ValueError(
                        "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_CREDENTIALS_REQUIRED"
                    )
                try:
                    private_oos = resolve_host_private_oos_carrier(
                    workspace_root=workspace,
                    trust_root=Path(trust_root_raw),
                    installation_id=installation_id,
                    allocation_id=allocation_id,
                    report_id=args.report_id,
                    parent_report_id=parent_report_id,
                    expected_host_trust_manifest_sha256=str(
                        args.expected_host_trust_manifest_sha256 or ""
                    ),
                    expected_sealed_carrier_sha256=str(
                        allocation.get("sealed_carrier_sha256") or ""
                    ),
                    expected_dataset_snapshot_sha256=str(
                        allocation.get("dataset_snapshot_sha256") or ""
                    ),
                    expected_build_authority_sha256=str(
                        allocation.get("build_authority_sha256") or ""
                    ),
                    agent_visible_roots=[
                        Path(item) for item in args.sealed_oos_agent_visible_root
                    ],
                )
                except Exception:
                    raise ValueError(
                        "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_RESOLUTION_FAILED"
                    ) from None
                carrier_path = private_oos["sealed_oos_carrier_path"]
                private_root = private_oos["sealed_oos_private_root"]
                private_denied_values.extend(
                    [str(carrier_path), str(private_root)]
                )
        else:
            carrier_path = (
                Path(args.sealed_oos_carrier)
                if args.sealed_oos_carrier
                else None
            )
            private_root = (
                Path(args.sealed_oos_private_root)
                if args.sealed_oos_private_root
                else None
            )
            if (
                isinstance(allocation, dict)
                and allocation.get("allocation_authority_mode")
                == OOS_ALLOCATION_AUTHORITY_SECURE
                and not completed_finalization_replay
            ):
                raise ValueError(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PRIVATE_LOCATOR_REQUIRED"
                )
        token_hash = (
            str(allocation.get("sealed_token_sha256") or "")
            if isinstance(allocation, dict)
            else None
        )
        if (
            isinstance(allocation, dict)
            and carrier_path is None
            and not completed_finalization_replay
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_CARRIER_REQUIRED"
            )
        if (
            isinstance(allocation, dict)
            and private_root is None
            and not completed_finalization_replay
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_PRIVATE_ROOT_REQUIRED"
            )
        if isinstance(allocation, dict) and not allocation.get(
            "sealed_carrier_sha256"
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_CARRIER_UNBOUND"
            )
        result = finalize_web_factor_proof(
            workspace_root=workspace,
            plan=plan,
            oos_release_token_hash=token_hash,
            sealed_oos_carrier_path=carrier_path,
            sealed_oos_private_root=private_root,
            sealed_oos_agent_visible_roots=[
                REPO_ROOT,
                *[Path(item) for item in args.sealed_oos_agent_visible_root],
            ],
            expected_dataset_snapshot_sha256=(
                str(allocation.get("dataset_snapshot_sha256") or "")
                if isinstance(allocation, dict)
                else None
            ),
            expected_sealed_carrier_sha256=(
                str(allocation.get("sealed_carrier_sha256") or "")
                if isinstance(allocation, dict)
                else None
            ),
            host_agent_termination_authority=termination_authority,
            incident_trust_root=Path(trust_root_raw),
            incident_installation_id=installation_id,
            _incident_guard=incident_guard,
        )
    except Exception as exc:
        finalization_stack.close()
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "block_token": (
                        "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_FINALIZATION_FAILED"
                    ),
                    "block_reasons": [
                        _redact_host_private_values(
                            str(exc),
                            private_denied_values,
                        )
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finalization_stack.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
