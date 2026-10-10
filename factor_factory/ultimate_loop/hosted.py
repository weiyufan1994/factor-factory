from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from factor_factory.console.evo_child_runtime import (
    CHILD_RECOVERY_READY, EvoChildRuntimeError,
    validate_evo_child_command_recovery_admission, validate_evo_child_execution_state,
)
from factor_factory.console.web_factor_proof import resolve_web_evo_execution_gate
from factor_factory.console.web_research_plan import (
    WebResearchPlanError, required_web_resume_start_step,
    resolve_report_scoped_web_research_plan, validate_materialized_web_research,
)
from factor_factory.evo_child_materialization_admission import validate_evo_child_materialization_admission
from factor_factory.local_is_execution import local_is_recovery_forbidden
from factor_factory.research_evidence import web_factor_proof_oos_recovery_state
from factor_factory.ultimate_loop.state import ExecutionMode


def prepare_hosted_execution(
    *,
    args,
    ctx,
    start,
    end,
    host_private_oos_locator_ready,
    host_private_oos_raw,
    incident_host_env,
    research_organization_runtime,
) -> ExecutionMode | int:
    """Validate explicit hosted execution, retaining its original trust/recovery rules."""
    from factor_factory.ultimate_loop.runner import (
        OOS_HOST_TRUST_ROOT_ENV, OOS_HOST_INSTALLATION_ID_ENV,
        EVO_CHILD_CONTAINER_STATE_ROOT_ENV, EVO_CHILD_CONTAINER_JOB_ID_ENV,
        _required_web_start_step, resolve_evo_child_container_admission_for_ultimate,
    )
    local_is_only = False
    web_materialization: dict[str, str] | None = None
    web_resume_start_step: str | None = None
    web_plan: dict[str, Any] | None = None
    web_plan_path: Path | None = None
    web_oos_release_token_hash: str | None = None
    web_allocation: dict[str, Any] | None = None
    web_is_evo_child = False
    web_evo_gate: dict[str, Any] | None = None
    web_validate_step4_finalizer_recovery = False
    web_command_recovery: dict[str, Any] | None = None
    web_oos_recovery: dict[str, Any] = {
        'recovery_required': False,
        'allowed_execution': 'NORMAL',
        'artifact_refs': [],
        'finalization_receipt_present': False,
    }
    try:
        # Information-release recovery is independent of optional Web marker
        # files.  Marker deletion must never downgrade a partially published
        # OOS workspace into the legacy Agent-executable path.
        web_oos_recovery = web_factor_proof_oos_recovery_state(
            ctx.active_root,
            args.report_id,
        )
    except (OSError, ValueError) as exc:
        print(f'BLOCK_FACTORFORGE_WEB_OOS_RECOVERY_STATE_INVALID: {exc}')
        return 1
    web_catalog_summary = ctx.active_root / 'identity' / 'data_catalog_summary.json'
    if local_is_only and local_is_recovery_forbidden(web_oos_recovery):
        print('BLOCK_FACTORFORGE_LOCAL_IS_OOS_RECOVERY_FORBIDDEN')
        return 1
    if (
        web_catalog_summary.exists()
        or web_catalog_summary.is_symlink()
        or web_oos_recovery['recovery_required']
    ):
        try:
            web_plan_resolution = resolve_report_scoped_web_research_plan(
                ctx.active_root,
                report_id=args.report_id,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
                incident_trust_root=(
                    Path(incident_host_env[OOS_HOST_TRUST_ROOT_ENV])
                    if incident_host_env
                    else None
                ),
                incident_installation_id=(
                    incident_host_env[OOS_HOST_INSTALLATION_ID_ENV]
                    if incident_host_env
                    else None
                ),
                current_authority=bool(incident_host_env),
            )
            web_plan_path = Path(web_plan_resolution['plan_path'])
            web_plan = dict(web_plan_resolution['plan'])
            web_is_evo_child = bool(web_plan_resolution['is_evo_child'])
            if web_is_evo_child and not args.dry_run:
                child_materialization_admission, admission_reasons = (
                    validate_evo_child_materialization_admission(
                        workspace_root=ctx.active_root,
                        parent_report_id=str(
                            web_plan_resolution['parent_report_id']
                        ),
                        child_report_id=args.report_id,
                        expected_host_trust_manifest_sha256=str(
                            args.expected_host_trust_manifest_sha256 or ''
                        ),
                        incident_trust_root=(
                            Path(incident_host_env[OOS_HOST_TRUST_ROOT_ENV])
                            if incident_host_env
                            else None
                        ),
                        incident_installation_id=(
                            incident_host_env[OOS_HOST_INSTALLATION_ID_ENV]
                            if incident_host_env
                            else None
                        ),
                    )
                )
                if child_materialization_admission is None or admission_reasons:
                    print(
                        'BLOCK_FACTORFORGE_EVO_CHILD_MATERIALIZATION_HOST_ADMISSION_REQUIRED'
                    )
                    if admission_reasons:
                        print('\n'.join(admission_reasons))
                    return 1
            web_allocation = web_plan_resolution.get('allocation')
            if isinstance(web_allocation, dict):
                web_oos_release_token_hash = str(
                    web_allocation.get('sealed_token_sha256') or ''
                )
            web_materialization = validate_materialized_web_research(
                ctx.active_root,
                report_id=args.report_id,
                plan_path=web_plan_path,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
                incident_trust_root=(
                    Path(incident_host_env[OOS_HOST_TRUST_ROOT_ENV])
                    if incident_host_env
                    else None
                ),
                incident_installation_id=(
                    incident_host_env[OOS_HOST_INSTALLATION_ID_ENV]
                    if incident_host_env
                    else None
                ),
                current_authority=bool(incident_host_env),
            )
            web_evo_gate = resolve_web_evo_execution_gate(
                workspace_root=ctx.active_root,
                report_id=args.report_id,
                plan=web_plan,
                oos_release_token_hash=web_oos_release_token_hash,
            )
            if (
                args.evo_child_command_recovery_admission
                and args.evo_child_finalizer_recovery_admission
            ):
                raise WebResearchPlanError(
                    'BLOCK_FACTORFORGE_EVO_CHILD_COMMAND_RECOVERY_INVALID',
                    ['multiple_recovery_authorities'],
                )
            if args.evo_child_command_recovery_admission:
                if not web_is_evo_child or not host_private_oos_locator_ready:
                    raise WebResearchPlanError(
                        'BLOCK_FACTORFORGE_EVO_CHILD_COMMAND_RECOVERY_INVALID',
                        ['child_identity_or_host_control'],
                    )
                command_resolution = validate_evo_child_command_recovery_admission(
                    state_root=host_private_oos_raw[
                        EVO_CHILD_CONTAINER_STATE_ROOT_ENV
                    ],
                    trust_root=host_private_oos_raw[OOS_HOST_TRUST_ROOT_ENV],
                    installation_id=host_private_oos_raw[
                        OOS_HOST_INSTALLATION_ID_ENV
                    ],
                    job_id=host_private_oos_raw[
                        EVO_CHILD_CONTAINER_JOB_ID_ENV
                    ],
                    parent_report_id=str(
                        web_plan_resolution['parent_report_id']
                    ),
                    child_report_id=args.report_id,
                    expected_host_trust_manifest_sha256=str(
                        args.expected_host_trust_manifest_sha256 or ''
                    ),
                    admission_path=args.evo_child_command_recovery_admission,
                    workspace_root=ctx.active_root,
                )
                web_command_recovery = command_resolution['receipt']
                web_resume_start_step = str(
                    web_command_recovery['boundary']['required_start_step']
                )
            else:
                web_resume_start_step = required_web_resume_start_step(
                    ctx.active_root,
                    args.report_id,
                )
            if args.evo_child_finalizer_recovery_admission:
                if not web_is_evo_child or not host_private_oos_locator_ready:
                    raise WebResearchPlanError(
                        'BLOCK_FACTORFORGE_EVO_CHILD_FINALIZER_RECOVERY_INVALID',
                        ['child_identity_or_host_control'],
                    )
                recovery_admission = validate_evo_child_execution_state(
                    state_root=host_private_oos_raw[
                        EVO_CHILD_CONTAINER_STATE_ROOT_ENV
                    ],
                    trust_root=host_private_oos_raw[OOS_HOST_TRUST_ROOT_ENV],
                    installation_id=host_private_oos_raw[
                        OOS_HOST_INSTALLATION_ID_ENV
                    ],
                    job_id=host_private_oos_raw[
                        EVO_CHILD_CONTAINER_JOB_ID_ENV
                    ],
                    parent_report_id=str(
                        web_plan_resolution['parent_report_id']
                    ),
                    child_report_id=args.report_id,
                    expected_host_trust_manifest_sha256=str(
                        args.expected_host_trust_manifest_sha256 or ''
                    ),
                    execution_receipt_path=(
                        args.evo_child_finalizer_recovery_admission
                    ),
                    workspace_root=ctx.active_root,
                )
                recovery_receipt = recovery_admission.get('receipt')
                if (
                    recovery_admission.get('status') != CHILD_RECOVERY_READY
                    or not isinstance(recovery_receipt, dict)
                    or recovery_receipt.get('resume_start_step') != '6'
                    or recovery_receipt.get('proof_status')
                    != 'VALIDATE_STEP4_COMPLETE_FINALIZER_ONLY_RECOVERY'
                    or recovery_receipt.get('authority', {}).get('finalizer_only')
                    is not True
                ):
                    raise WebResearchPlanError(
                        'BLOCK_FACTORFORGE_EVO_CHILD_FINALIZER_RECOVERY_INVALID',
                        ['signed_recovery_authority'],
                    )
                web_resume_start_step = '6'
                web_validate_step4_finalizer_recovery = True
        except EvoChildRuntimeError:
            print('BLOCK_FACTORFORGE_EVO_CHILD_FINALIZER_RECOVERY_INVALID')
            return 1
        except (OSError, UnicodeError, json.JSONDecodeError, WebResearchPlanError) as exc:
            print(str(exc))
            return 1
        expected_start = _required_web_start_step(
            resume_step=web_resume_start_step,
            is_evo_child=web_is_evo_child,
        )
        if start != expected_start or end != '6':
            print(
                'BLOCK_FACTORFORGE_WEB_RESEARCH_RESUME_POINT_INVALID: '
                f'expected start-step={expected_start}, end-step=6; got {start}/{end}'
            )
            return 1
        if not args.dry_run and (
            args.research_org_runtime_mode
            not in {'formal-complete', 'revision-child-assured'}
            or research_organization_runtime.get('formal_independence_verified')
            is not True
        ):
            print('BLOCK_FACTORFORGE_WEB_RESEARCH_ORG_RUNTIME_NOT_FORMAL_COMPLETE')
            return 1

    agent_execution_container_resolution: dict[str, Any] | None = None
    if web_is_evo_child and not args.dry_run:
        if (
            args.agent_execution_sandbox_profile
            or args.agent_execution_sandbox_admission
        ):
            print(
                'BLOCK_FACTORFORGE_EVO_CHILD_CALLER_SANDBOX_ARGUMENT_FORBIDDEN'
            )
            return 1
        try:
            agent_execution_container_resolution = resolve_evo_child_container_admission_for_ultimate(
                admission_path=args.agent_execution_container_admission,
                host_control=host_private_oos_raw,
                workspace_root=ctx.active_root,
                worktree=ctx.repo_root,
                parent_report_id=str(web_plan_resolution['parent_report_id']),
                child_report_id=args.report_id,
                expected_host_pin=str(
                    args.expected_host_trust_manifest_sha256 or ''
                ),
            )
        except RuntimeError as exc:
            print(str(exc))
            return 1

    web_evo_action = (
        str(web_evo_gate.get('action') or '')
        if isinstance(web_evo_gate, dict) and web_evo_gate.get('enabled') is True
        else 'LEGACY_WEB_EXECUTION'
    )
    web_secure_child_oos = bool(
        isinstance(web_allocation, dict)
        and web_allocation.get('allocation_authority_mode')
        == 'HOST_PRIVATE_CARRIER_DERIVED'
    )
    if local_is_only and (
        web_materialization is not None
        or web_evo_action != 'LEGACY_WEB_EXECUTION'
        or local_is_recovery_forbidden(web_oos_recovery)
    ):
        print('BLOCK_FACTORFORGE_LOCAL_IS_OOS_RECOVERY_FORBIDDEN')
        return 1
    web_completed_finalization_replay = bool(
        web_oos_recovery.get('finalization_receipt_present') is True
    )
    if (
        (args.sealed_oos_carrier or args.sealed_oos_private_root)
        and web_evo_action != 'RELEASE_ORIGINAL_CANDIDATE_OOS'
    ):
        print('BLOCK_FACTORFORGE_WEB_OOS_CARRIER_EXPOSED_BEFORE_RELEASE')
        return 1
    if args.sealed_oos_agent_visible_root and web_evo_action != 'RELEASE_ORIGINAL_CANDIDATE_OOS':
        print('BLOCK_FACTORFORGE_WEB_OOS_CARRIER_EXPOSED_BEFORE_RELEASE')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and web_secure_child_oos
        and (args.sealed_oos_carrier or args.sealed_oos_private_root)
    ):
        print('BLOCK_FACTORFORGE_WEB_OOS_SECURE_ALLOCATION_PATH_ARGV_FORBIDDEN')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and web_secure_child_oos
        and not host_private_oos_locator_ready
    ):
        print('BLOCK_FACTORFORGE_WEB_OOS_PRIVATE_LOCATOR_CREDENTIALS_REQUIRED')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and host_private_oos_locator_ready
        and not web_secure_child_oos
    ):
        print('BLOCK_FACTORFORGE_WEB_OOS_PRIVATE_LOCATOR_ALLOCATION_REQUIRED')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and not web_completed_finalization_replay
        and not args.sealed_oos_carrier
        and not host_private_oos_locator_ready
    ):
        print('BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_CARRIER_REQUIRED')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and bool(args.sealed_oos_carrier) != bool(args.sealed_oos_private_root)
    ):
        print('BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_SEALED_OOS_PRIVATE_ROOT_REQUIRED')
        return 1
    if (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
        and host_private_oos_locator_ready
        and (args.sealed_oos_carrier or args.sealed_oos_private_root)
    ):
        print('BLOCK_FACTORFORGE_WEB_OOS_PRIVATE_LOCATOR_PATH_MIXED')
        return 1
    web_evo_wait_only = web_evo_action in {
        'AWAIT_HOST_QUALIFICATION',
        'RUN_PRE_OOS_REVISION_COUNCIL',
        'AWAIT_EVO_V2_TRANSFER_AND_USE',
        'AWAIT_EXTERNAL_APPROVAL_AND_CHILD',
        'TERMINAL_KILL_AND_LEARN',
    }
    web_evo_checkpoint_pass = (
        web_evo_action == 'MATERIALIZE_PURGED_IS_AND_PAUSE'
    )
    web_evo_oos_release_pass = (
        web_evo_action == 'RELEASE_ORIGINAL_CANDIDATE_OOS'
    )
    return ExecutionMode(
        web_materialization=web_materialization,
        web_resume_start_step=web_resume_start_step,
        web_plan=web_plan,
        web_plan_path=web_plan_path,
        web_oos_release_token_hash=web_oos_release_token_hash,
        web_allocation=web_allocation,
        web_is_evo_child=web_is_evo_child,
        web_evo_gate=web_evo_gate,
        web_validate_step4_finalizer_recovery=web_validate_step4_finalizer_recovery,
        web_command_recovery=web_command_recovery,
        web_oos_recovery=web_oos_recovery,
        agent_execution_container_resolution=agent_execution_container_resolution,
        web_evo_action=web_evo_action,
        web_secure_child_oos=web_secure_child_oos,
        web_completed_finalization_replay=web_completed_finalization_replay,
        web_evo_wait_only=web_evo_wait_only,
        web_evo_checkpoint_pass=web_evo_checkpoint_pass,
        web_evo_oos_release_pass=web_evo_oos_release_pass,
    )


def run_pre_oos_transition(
    *,
    args,
    ctx,
    env,
    host_private_proof_values,
    manifest,
    proof,
    proof_path,
    py,
    taskbook_runtime_args,
    mode,
):
    """Handle the explicit hosted lifecycle after its staged commands complete."""
    from factor_factory.ultimate_loop.runner import (
        CommandResult,
        _evo_pre_oos_executor_block_token,
        _validated_evo_outcome_stage,
        agentic_dispatch_required_results_present,
        public_command_proof,
        run_command,
        collect_expected_artifacts,
        collect_step3b_mode_decision,
        pre_oos_root_synthesis_path,
        pre_oos_outcome_verifier_path,
        _json_from_command_stdout,
        write_json_atomic,
        utc_now,
    )
    from factor_factory.console.web_factor_proof import resolve_web_evo_execution_gate

    if (
        not args.dry_run
        and isinstance(mode.web_evo_gate, dict)
        and mode.web_evo_gate.get('enabled') is True
        and mode.web_evo_action != 'RELEASE_ORIGINAL_CANDIDATE_OOS'
    ):
        if mode.web_plan is None:
            proof['status'] = 'FAIL'
            proof['failure'] = {
                'command': 'resolve_web_evo_execution_gate',
                'returncode': 1,
                'token': 'BLOCK_FACTORFORGE_WEB_EVO_PLAN_MISSING',
            }
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print('BLOCK_FACTORFORGE_WEB_EVO_PLAN_MISSING')
            print(f'[PROOF] {proof_path}')
            return 1
        try:
            refreshed_evo_gate = resolve_web_evo_execution_gate(
                workspace_root=ctx.active_root,
                report_id=args.report_id,
                plan=mode.web_plan,
                oos_release_token_hash=mode.web_oos_release_token_hash,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            proof['status'] = 'FAIL'
            proof['failure'] = {
                'command': 'resolve_web_evo_execution_gate',
                'returncode': 1,
                'token': 'BLOCK_FACTORFORGE_WEB_EVO_EXECUTION_GATE_INVALID',
            }
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(str(exc))
            print(f'[PROOF] {proof_path}')
            return 1
        proof['evo_v2_execution_gate'] = refreshed_evo_gate
        executed_names = [
            str(row.get('name') or '')
            for row in proof.get('commands') or []
            if isinstance(row, dict)
        ]
        required_names = list(
            proof['formal_command_contract']['required_command_names']
        )
        proof['formal_command_contract']['executed_command_names'] = executed_names
        proof['formal_command_contract']['satisfied'] = bool(
            executed_names == required_names
            and all(
                row.get('status') == 'PASS' and row.get('returncode') == 0
                for row in proof.get('commands') or []
                if isinstance(row, dict)
            )
        )
        action = str(refreshed_evo_gate.get('action') or '')
        proof['formal_proof_eligible'] = False
        proof['factor_verdict'] = 'NOT_ISSUED'
        proof['failure'] = None
        proof['finished_at_utc'] = utc_now()
        proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
        proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
        if action == 'AWAIT_HOST_QUALIFICATION':
            token = 'AWAITING_EVO_V2_HOST_QUALIFICATION'
            proof['status'] = 'PAUSED'
            proof['proof_semantics'] = 'purged_is_checkpoint_only_awaiting_host_qualification'
            proof['final_outcome'] = 'awaiting_evo_v2_host_qualification'
            proof['revision_council'] = {
                'requested_mode': args.council_mode,
                'status': 'not_reached',
                'reason': 'qualified_contradiction_not_host_admitted',
            }
        elif action == 'RUN_PRE_OOS_REVISION_COUNCIL':
            if args.council_mode == 'off':
                token = 'AWAITING_EVO_V2_PRE_OOS_REVISION_COUNCIL'
                proof['status'] = 'PAUSED'
                proof['proof_semantics'] = 'awaiting_pre_oos_revision_council'
                proof['final_outcome'] = 'awaiting_evo_v2_pre_oos_revision_council'
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'pre_oos_required',
                    'reason': 'host_admitted_qualified_contradiction',
                }
            elif args.council_mode in {'agentic', 'auto'}:
                executor_block = _evo_pre_oos_executor_block_token(
                    args.council_mode,
                    args.agentic_council_executor,
                )
                if executor_block is not None:
                    token = executor_block
                    proof['status'] = 'FAIL'
                    proof['proof_semantics'] = 'pre_oos_revision_council_executor_invalid'
                    proof['failure'] = {
                        'command': 'pre_oos_revision_council_executor',
                        'returncode': 1,
                        'token': token,
                    }
                    proof['revision_council'] = {
                        'requested_mode': args.council_mode,
                        'executor': args.agentic_council_executor,
                        'status': 'blocked',
                        'reason': token,
                    }
                    proof['finished_at_utc'] = utc_now()
                    write_json_atomic(proof_path, proof)
                    print(token)
                    print(f'[PROOF] {proof_path}')
                    return 1
                council_dir = (
                    ctx.active_root
                    / 'objects'
                    / 'research_iteration_master'
                    / 'revision_council'
                    / args.report_id
                )
                dispatch_manifest = (
                    council_dir / f'dispatch_manifest__{args.report_id}.json'
                )
                council_commands: list[tuple[str, list[str]]] = []
                results_ready = False
                if not dispatch_manifest.is_file():
                    council_commands.extend(
                        [
                            (
                                'build_revision_council_packet',
                                [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id],
                            ),
                            (
                                'build_agentic_council_taskbook',
                                [py, 'skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py', '--report-id', args.report_id, '--executor', 'dispatch_manifest', '--research-protocol', 'required', *taskbook_runtime_args],
                            ),
                            (
                                'build_agentic_council_dispatch_manifest',
                                [py, 'skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py', '--report-id', args.report_id],
                            ),
                        ]
                    )
                else:
                    results_ready = agentic_dispatch_required_results_present(
                        ctx.active_root,
                        args.report_id,
                    )
                if results_ready:
                    council_commands.extend(
                        [
                            (
                                'validate_agentic_council_dispatch',
                                [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id],
                            ),
                            (
                                'validate_agentic_council_result',
                                [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_result.py', '--report-id', args.report_id],
                            ),
                            (
                                'collect_agentic_council_results',
                                [py, 'skills/factor-forge-step6/scripts/collect_agentic_council_results.py', '--report-id', args.report_id],
                            ),
                            (
                                'validate_agentic_council_collection',
                                [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_collection.py', '--report-id', args.report_id],
                            ),
                            (
                                'merge_revision_council',
                                [py, 'skills/factor-forge-step6/scripts/merge_revision_council.py', '--report-id', args.report_id],
                            ),
                            (
                                'build_council_derivation_appendix',
                                [py, 'skills/factor-forge-step6/scripts/build_council_derivation_appendix.py', '--report-id', args.report_id],
                            ),
                        ]
                    )
                else:
                    council_commands.append(
                        (
                            'validate_agentic_council_dispatch',
                            [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id],
                        )
                    )
                pre_oos_results: list[dict[str, Any]] = []
                failed_result: CommandResult | None = None
                for council_name, council_command in council_commands:
                    council_result = run_command(
                        council_name,
                        council_command,
                        cwd=ctx.repo_root,
                        env=env,
                        dry_run=False,
                    )
                    pre_oos_results.append(
                        public_command_proof(
                            council_result,
                            denied_values=host_private_proof_values,
                        )
                    )
                    if council_result.returncode != 0:
                        failed_result = council_result
                        break
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'effective_mode': 'agentic_dispatch_manifest',
                    'evidence_view': 'PURGED_IS_ONLY',
                    'oos_state': 'SEALED_NOT_ACCESSED',
                    'commands': pre_oos_results,
                }
                if failed_result is not None:
                    token = 'BLOCK_EVO_V2_PRE_OOS_COUNCIL_DISPATCH_FAILED'
                    proof['status'] = 'FAIL'
                    proof['proof_semantics'] = 'pre_oos_revision_council_dispatch_blocked'
                    proof['failure'] = {
                        'command': failed_result.name,
                        'returncode': failed_result.returncode,
                        'token': token,
                    }
                    proof['revision_council']['status'] = 'blocked'
                elif not results_ready:
                    token = 'AWAITING_REVISION_COUNCIL_AGENT_RESULTS'
                    proof['status'] = 'PAUSED'
                    proof['proof_semantics'] = 'awaiting_pre_oos_revision_council_agent_results'
                    proof['final_outcome'] = 'awaiting_evo_v2_pre_oos_revision_council'
                    proof['revision_council']['status'] = 'awaiting_agent_results'
                else:
                    synthesis_path = pre_oos_root_synthesis_path(
                        ctx.active_root,
                        args.report_id,
                    )
                    verifier_path = pre_oos_outcome_verifier_path(
                        ctx.active_root,
                        args.report_id,
                    )
                    if not synthesis_path.is_file() or synthesis_path.is_symlink():
                        token = 'AWAITING_PRE_OOS_COUNCIL_ROOT_SYNTHESIS'
                        proof['status'] = 'PAUSED'
                        proof['proof_semantics'] = 'awaiting_agent_authored_pre_oos_root_synthesis'
                        proof['final_outcome'] = 'awaiting_pre_oos_council_root_synthesis'
                        proof['revision_council']['status'] = 'awaiting_root_synthesis'
                        proof['revision_council']['root_synthesis_path'] = str(
                            synthesis_path
                        )
                    else:
                        materialize_args = [
                            py,
                            'scripts/materialize_factorforge_pre_oos_council_outcome.py',
                            '--workspace-root',
                            str(ctx.active_root),
                            '--report-id',
                            args.report_id,
                        ]
                        if verifier_path.is_file() and not verifier_path.is_symlink():
                            materialize_args.append('--validate-existing')
                        else:
                            materialize_args.extend(
                                ['--synthesis', str(synthesis_path)]
                            )
                        outcome_result = run_command(
                            'materialize_pre_oos_council_outcome',
                            materialize_args,
                            cwd=ctx.repo_root,
                            env=env,
                            dry_run=False,
                        )
                        pre_oos_results.append(
                            public_command_proof(
                                outcome_result,
                                denied_values=host_private_proof_values,
                            )
                        )
                        outcome_payload = _json_from_command_stdout(outcome_result)
                        if outcome_result.returncode != 0:
                            token = 'BLOCK_EVO_V2_PRE_OOS_ROOT_OUTCOME_INVALID'
                            proof['status'] = 'FAIL'
                            proof['proof_semantics'] = 'pre_oos_root_outcome_blocked'
                            proof['failure'] = {
                                'command': outcome_result.name,
                                'returncode': outcome_result.returncode,
                                'token': token,
                            }
                            proof['revision_council']['status'] = 'blocked'
                        else:
                            token = 'AWAITING_EVO_V2_HOST_OUTCOME_TRANSITION_AND_STAGING'
                            proof['status'] = 'PAUSED'
                            proof['proof_semantics'] = 'pre_oos_council_outcome_verified_review_only'
                            proof['final_outcome'] = 'awaiting_host_lifecycle_transition_and_staged_council_outcome'
                            proof['revision_council'].update(
                                {
                                    'status': 'outcome_verified_awaiting_host',
                                    'authorized_host_transition_state': outcome_payload.get(
                                        'authorized_host_transition_state'
                                    ),
                                    'outcome_verifier': outcome_payload,
                                    'host_transition_performed': False,
                                    'human_approval_granted': False,
                                }
                            )
            else:
                token = 'BLOCK_EVO_V2_PRE_OOS_COUNCIL_REQUIRES_AGENTIC_MODE'
                proof['status'] = 'FAIL'
                proof['proof_semantics'] = 'pre_oos_revision_council_mode_invalid'
                proof['failure'] = {
                    'command': 'pre_oos_revision_council',
                    'returncode': 1,
                    'token': token,
                }
        elif action == 'AWAIT_EVO_V2_TRANSFER_AND_USE':
            staged_ok, staged_reasons, outcome_reference = (
                _validated_evo_outcome_stage(
                    ctx.active_root,
                    args.report_id,
                    'MINIMAL_MECHANISM_DELTA',
                    allowed_current_states={'MINIMAL_MECHANISM_DELTA'},
                    required_event_count=2,
                )
            )
            if not staged_ok:
                token = 'BLOCK_EVO_V2_COUNCIL_OUTCOME_NOT_STAGED'
                proof['status'] = 'FAIL'
                proof['proof_semantics'] = 'review_only_delta_staging_invalid'
                proof['failure'] = {
                    'command': 'validate_evo_v2_staged_council_outcome',
                    'returncode': 1,
                    'token': token,
                    'block_reasons': staged_reasons,
                }
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'blocked',
                    'reason': 'host_transition_without_canonical_staged_outcome',
                }
            else:
                token = 'AWAITING_EVO_V2_TRANSFER_AND_ACTUAL_USE'
                proof['status'] = 'PAUSED'
                proof['proof_semantics'] = 'review_only_delta_awaiting_transfer_and_actual_use'
                proof['final_outcome'] = 'awaiting_evo_v2_transfer_and_actual_use'
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'completed_review_only_awaiting_transfer',
                    'reason': 'experience_transfer_must_precede_human_approval',
                    'outcome_verifier_ref': outcome_reference,
                }
        elif action == 'AWAIT_EXTERNAL_APPROVAL_AND_CHILD':
            current_state = str(refreshed_evo_gate.get('current_state') or '')
            staged_ok, staged_reasons, outcome_reference = (
                _validated_evo_outcome_stage(
                    ctx.active_root,
                    args.report_id,
                    'MINIMAL_MECHANISM_DELTA',
                    allowed_current_states={
                        'TRANSFER_RECORDED',
                        'COLD_START_RECORDED',
                    },
                    required_event_count=4,
                )
            )
            if not staged_ok:
                token = 'BLOCK_EVO_V2_COUNCIL_OUTCOME_NOT_STAGED'
                proof['status'] = 'FAIL'
                proof['proof_semantics'] = 'review_only_delta_staging_invalid'
                proof['failure'] = {
                    'command': 'validate_evo_v2_staged_council_outcome',
                    'returncode': 1,
                    'token': token,
                    'block_reasons': staged_reasons,
                }
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'blocked',
                    'reason': 'host_transition_without_canonical_staged_outcome',
                }
            else:
                token = 'AWAITING_EVO_V2_EXTERNAL_APPROVAL_AND_FRESH_CHILD'
                proof['status'] = 'PAUSED'
                proof['proof_semantics'] = 'review_only_delta_awaiting_external_approval_and_fresh_child'
                proof['final_outcome'] = 'awaiting_evo_v2_external_approval_and_fresh_child'
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'completed_review_only',
                    'reason': 'parent_execution_forbidden',
                    'current_state': current_state,
                    'outcome_verifier_ref': outcome_reference,
                }
        elif action == 'TERMINAL_KILL_AND_LEARN':
            staged_ok, staged_reasons, outcome_reference = (
                _validated_evo_outcome_stage(
                    ctx.active_root,
                    args.report_id,
                    'NO_DERIVED_LAW',
                )
            )
            if not staged_ok:
                token = 'BLOCK_EVO_V2_NO_DERIVED_OUTCOME_NOT_STAGED'
                proof['status'] = 'FAIL'
                proof['proof_semantics'] = 'no_derived_law_staging_invalid'
                proof['failure'] = {
                    'command': 'validate_evo_v2_staged_no_derived_outcome',
                    'returncode': 1,
                    'token': token,
                    'block_reasons': staged_reasons,
                }
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'blocked',
                    'reason': 'terminal_no_derived_proof_not_staged',
                }
            else:
                token = 'EVO_V2_TERMINAL_NO_DERIVED_LAW'
                proof['status'] = 'PASS'
                proof['proof_semantics'] = 'evo_v2_terminal_no_derived_law_no_factor_verdict'
                proof['final_outcome'] = 'kill_and_learn_no_derived_law'
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'terminal_no_derived_law',
                    'reason': 'no_distinguishing_implementable_minimal_delta',
                    'outcome_verifier_ref': outcome_reference,
                }
        else:
            token = 'BLOCK_FACTORFORGE_WEB_EVO_EXECUTION_GATE_INVALID'
            proof['status'] = 'FAIL'
            proof['failure'] = {
                'command': 'resolve_web_evo_execution_gate',
                'returncode': 1,
                'token': token,
            }
        write_json_atomic(proof_path, proof)
        print(token)
        print(f'[PROOF] {proof_path}')
        return 0 if proof['status'] in {'PAUSED', 'PASS'} else 1


def close_post_oos_council(*, args, ctx, incident_host_env, proof, proof_path):
    """Retain terminal-only behavior once hosted OOS has been consumed."""
    from factor_factory.ultimate_loop.runner import (
        enforce_evo_post_oos_no_revision, OOS_HOST_TRUST_ROOT_ENV,
        OOS_HOST_INSTALLATION_ID_ENV, oos_exposure_private_registry_guard,
        utc_now, write_json_atomic,
    )
    from factor_factory.evo_terminal_closure import (
        issue_evo_post_oos_terminal_closure, validate_evo_post_oos_terminal_closure,
    )
    import subprocess

    post_oos_revision_guard = enforce_evo_post_oos_no_revision(
        ctx.active_root,
        args.report_id,
    )
    if post_oos_revision_guard['status'] != 'SAFE_NO_REVISION':
        token = 'BLOCK_FACTORFORGE_EVO_V2_CONSUMED_OOS_REVISION_HANDOFF'
        proof['status'] = 'FAIL'
        proof['formal_proof_eligible'] = False
        proof['revision_council'] = {
            'requested_mode': args.council_mode,
            'status': 'blocked',
            'reason': 'consumed_oos_cannot_authorize_revision',
            'post_oos_revision_guard': post_oos_revision_guard,
        }
        proof['failure'] = {
            'command': 'evo_v2_post_oos_revision_guard',
            'returncode': 1,
            'token': token,
        }
        proof['finished_at_utc'] = utc_now()
        write_json_atomic(proof_path, proof)
        print(token)
        print(f'[PROOF] {proof_path}')
        return 1
    proof['revision_council'] = {
        'requested_mode': args.council_mode,
        'status': 'not_triggered',
        'formal_council_status': 'forbidden_after_oos_consumption',
        'reason': 'evo_v2_revision_council_requires_pre_oos_qualified_contradiction',
        'post_oos_revision_guard': post_oos_revision_guard,
    }
    if not args.dry_run:
        try:
            terminal_trust_root = Path(
                incident_host_env[OOS_HOST_TRUST_ROOT_ENV]
            ).expanduser()
            terminal_installation_id = incident_host_env[
                OOS_HOST_INSTALLATION_ID_ENV
            ]
            with oos_exposure_private_registry_guard(
                terminal_trust_root,
                installation_id=terminal_installation_id,
            ) as terminal_incident_guard:
                closure = issue_evo_post_oos_terminal_closure(
                    workspace_root=ctx.active_root,
                    report_id=args.report_id,
                    trust_root=terminal_trust_root,
                    installation_id=terminal_installation_id,
                    _incident_guard=terminal_incident_guard,
                )
                closure_validation = validate_evo_post_oos_terminal_closure(
                    workspace_root=ctx.active_root,
                    report_id=args.report_id,
                    trust_root=terminal_trust_root,
                    installation_id=terminal_installation_id,
                    _incident_guard=terminal_incident_guard,
                )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            token = 'BLOCK_FACTORFORGE_EVO_V2_POST_OOS_TERMINAL_CLOSURE_INVALID'
            proof['status'] = 'FAIL'
            proof['formal_proof_eligible'] = False
            proof['failure'] = {
                'command': 'issue_evo_post_oos_terminal_closure',
                'returncode': 1,
                'token': token,
                'detail': str(exc),
            }
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(token)
            print(f'[PROOF] {proof_path}')
            return 1
        if closure_validation.get('verdict') != 'PASS':
            token = 'BLOCK_FACTORFORGE_EVO_V2_POST_OOS_TERMINAL_CLOSURE_INVALID'
            proof['status'] = 'FAIL'
            proof['formal_proof_eligible'] = False
            proof['failure'] = {
                'command': 'validate_evo_post_oos_terminal_closure',
                'returncode': 1,
                'token': token,
                'block_reasons': closure_validation.get('block_reasons') or [],
            }
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(token)
            print(f'[PROOF] {proof_path}')
            return 1
        proof['evo_v2_post_oos_terminal_closure'] = {
            **closure_validation,
            'issue_status': closure.get('status'),
        }
        proof['revision_council'][
            'terminal_protocol_validated'
        ] = True
        proof['factor_verdict'] = closure_validation.get(
            'formal_factor_verdict'
        )
        proof['final_outcome'] = (
            'promote_official'
            if proof['factor_verdict'] == 'ACCEPT'
            else 'reject'
        )
    else:
        proof['revision_council'][
            'terminal_protocol_validated'
        ] = False
        proof['evo_v2_post_oos_terminal_closure'] = {
            'verdict': 'AWAITING_HOST_SIGNATURE',
            'formal_factor_verdict': None,
            'block_reasons': [
                'formal Host trust root and installation identity required'
            ],
        }
    write_json_atomic(proof_path, proof)
