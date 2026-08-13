#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [item for item in sys.path if item != str(REPO_ROOT)]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.evo_child_assurance import (
    EvoChildAssuranceError,
    validate_evo_child_assurance,
)
from factor_factory.console.evo_child_container import (
    EvoChildContainerError,
    run_evo_child_agent_stage,
    validate_evo_child_container_admission,
)
from factor_factory.console.evo_child_runtime import (
    CHILD_RECOVERY_READY,
    EvoChildRuntimeError,
    validate_evo_child_command_recovery_admission,
    validate_evo_child_execution_state,
)
from factor_factory.console.web_factor_proof import (
    resolve_web_evo_execution_gate,
    web_factor_proof_oos_recovery_state,
)
from factor_factory.console.web_research_plan import (
    WebResearchPlanError,
    required_web_resume_start_step,
    resolve_report_scoped_web_research_plan,
    resolve_workspace_approved_catalog,
    validate_materialized_web_research,
)
from factor_factory.council_terminal import classify_terminal_rejection_result
from factor_factory.evo_child_materialization_admission import (
    validate_evo_child_materialization_admission,
)
from factor_factory.evo_oos import formal_oos_incident_reasons
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)
from factor_factory.evo_staging import (
    staging_manifest_path as evo_staging_manifest_path,
)
from factor_factory.evo_staging import (
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_terminal_closure import (
    issue_evo_post_oos_terminal_closure,
    validate_evo_post_oos_terminal_closure,
)
from factor_factory.research_proof import (
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from factor_factory.evo_v2 import load_json_object as load_evo_json_object
from factor_factory.research_conjecture import (
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.research_org import (
    ResearchOrganizationError,
    load_research_organization_plan,
    resolve_research_organization_gate,
    validate_research_organization_runtime,
)
from factor_factory.research_workspace import (
    BLOCK_OUTPUT_OUTSIDE_WORKSPACE,
    BLOCK_WORKSPACE_MISSING,
    build_workspace_manifest,
    default_workspace_root,
    load_workspace_manifest,
    validate_workspace_cli_identity,
    validate_workspace_manifest,
    workspace_manifest_path,
    write_workspace_manifest,
)
from factor_factory.revision_council.pre_oos_outcome import (
    pre_oos_outcome_evidence_reference,
    pre_oos_outcome_verifier_path,
    pre_oos_root_synthesis_path,
)
from factor_factory.runtime_context import (
    load_runtime_manifest,
    resolve_factorforge_context,
    utc_now,
    write_json_atomic,
)
from factor_factory.state_reuse import (
    BLOCK_STATE_DEPENDENCY_UNDECLARED,
    StateReuseBlock,
    assert_no_raw_minute_full_window_scan,
    load_state_dependency_contract,
    require_state_resolution_ready,
    resolve_state_dependencies,
    write_resolution_outputs,
)
from factor_factory.state_reuse import (
    load_json as load_state_json,
)

STEP_ORDER = ['2', '3', '3b', '4', '5', '6']
OOS_HOST_TRUST_ROOT_ENV = 'FACTORFORGE_OOS_HOST_TRUST_ROOT'
OOS_HOST_INSTALLATION_ID_ENV = 'FACTORFORGE_OOS_HOST_INSTALLATION_ID'
EVO_CHILD_CONTAINER_STATE_ROOT_ENV = 'FACTORFORGE_EVO_CHILD_CONTAINER_STATE_ROOT'
EVO_CHILD_CONTAINER_JOB_ID_ENV = 'FACTORFORGE_EVO_CHILD_CONTAINER_JOB_ID'
EVO_CHILD_AGENT_STAGE_NAMES = frozenset(
    {'run_step3b', 'validate_step3b', 'run_step4', 'validate_step4'}
)
START_ALIASES = {
    '2': '2',
    'step2': '2',
    '3': '3',
    '3a': '3',
    'step3': '3',
    'step3a': '3',
    '3b': '3b',
    'step3b': '3b',
    '4': '4',
    'step4': '4',
    '5': '5',
    'step5': '5',
    '6': '6',
    'step6': '6',
}


def _required_web_start_step(
    *,
    resume_step: str | None,
    is_evo_child: bool,
) -> str:
    return resume_step or ('3b' if is_evo_child else '3')
END_ALIASES = START_ALIASES | {'all': '6'}


@dataclass
class CommandResult:
    name: str
    command: list[str]
    cwd: str
    started_at_utc: str
    finished_at_utc: str | None = None
    returncode: int | None = None
    stdout_tail: str = ''
    stderr_tail: str = ''
    status: str = 'NOT_RUN'


def evo_agent_execution_env(source: dict[str, str]) -> dict[str, str]:
    """Return the credential-free environment for Agent-authored execution.

    This is a defence-in-depth process contract.  The production caller must
    additionally run the process in an OS/container boundary which cannot see
    Host-private OOS carriers and has no network access.
    """

    isolated = dict(source)
    for key in list(isolated):
        upper = key.upper()
        if key.startswith(
            (
                'AWS_',
                'S3_',
                'FACTORFORGE_DATA_API_',
                'FACTORFORGE_DATA_CATALOG',
                'FACTORFORGE_OOS_HOST_',
                'FACTORFORGE_EVO_CHILD_CONTAINER_',
                'FACTORFORGE_READONLY_',
            )
        ) or any(
            token in upper
            for token in ('API_KEY', 'PASSWORD', 'SECRET', 'TOKEN', 'COOKIE')
        ):
            isolated.pop(key, None)
    isolated['AWS_EC2_METADATA_DISABLED'] = 'true'
    isolated['FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY'] = 'DENY'
    return isolated


def capture_host_control_environment(
    source: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Capture the four Host-only values and remove them from child env."""

    stripped = dict(source)
    captured = {
        key: stripped.pop(key, '')
        for key in (
            OOS_HOST_TRUST_ROOT_ENV,
            OOS_HOST_INSTALLATION_ID_ENV,
            EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
            EVO_CHILD_CONTAINER_JOB_ID_ENV,
        )
    }
    return stripped, captured


def command_environment_for_host_controls(
    *,
    name: str,
    base_env: dict[str, str],
    incident_host_env: dict[str, str],
    container_host_env: dict[str, str],
    web_secure_child_oos: bool,
) -> tuple[dict[str, str], bool]:
    """Inject negative-incident context only into the trusted finalizer."""

    injected = bool(name == 'finalize_web_factor_proof' and incident_host_env)
    if not injected:
        return base_env, False
    command_env = {**base_env, **incident_host_env}
    if web_secure_child_oos:
        command_env.update(container_host_env)
    return command_env, True


def resolve_evo_child_container_admission_for_ultimate(
    *,
    admission_path: Path | str | None,
    host_control: dict[str, str],
    workspace_root: Path,
    worktree: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
) -> dict[str, Any]:
    """Resolve the private admission without exposing private validation detail."""

    if not admission_path:
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_ADMISSION_REQUIRED'
        )
    required = {
        OOS_HOST_TRUST_ROOT_ENV,
        OOS_HOST_INSTALLATION_ID_ENV,
        EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
        EVO_CHILD_CONTAINER_JOB_ID_ENV,
    }
    if set(host_control) != required or any(
        not isinstance(host_control[key], str) or not host_control[key]
        for key in required
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_HOST_CONTROL_REQUIRED'
        )
    try:
        resolution = validate_evo_child_container_admission(
            admission_path=admission_path,
            state_root=host_control[EVO_CHILD_CONTAINER_STATE_ROOT_ENV],
            trust_root=host_control[OOS_HOST_TRUST_ROOT_ENV],
            installation_id=host_control[OOS_HOST_INSTALLATION_ID_ENV],
            job_id=host_control[EVO_CHILD_CONTAINER_JOB_ID_ENV],
            workspace_root=workspace_root,
            worktree=worktree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_pin,
        )
    except (EvoChildContainerError, OSError, RuntimeError, ValueError):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_ADMISSION_INVALID'
        ) from None
    admission = (
        resolution.get('admission')
        if isinstance(resolution, dict)
        else None
    )
    identity = (
        admission.get('identity') if isinstance(admission, dict) else None
    )
    container = (
        admission.get('container') if isinstance(admission, dict) else None
    )
    if (
        not isinstance(resolution, dict)
        or resolution.get('verdict') != 'PASS'
        or resolution.get('status')
        != 'HOST_ADMITTED_CLOSED_EVO_CHILD_CONTAINER'
        or resolution.get('factor_verdict') != 'NOT_ISSUED'
        or not isinstance(admission, dict)
        or admission.get('status')
        != 'HOST_ADMITTED_CLOSED_EVO_CHILD_CONTAINER'
        or admission.get('expected_host_trust_manifest_sha256')
        != expected_host_pin
        or identity
        != {
            'installation_id': host_control[
                OOS_HOST_INSTALLATION_ID_ENV
            ],
            'job_id': host_control[EVO_CHILD_CONTAINER_JOB_ID_ENV],
            'parent_report_id': parent_report_id,
            'child_report_id': child_report_id,
        }
        or not re.fullmatch(
            r'[0-9a-f]{64}', str(admission.get('receipt_id') or '')
        )
        or not re.fullmatch(
            r'[0-9a-f]{64}', str(admission.get('content_sha256') or '')
        )
        or not isinstance(container, dict)
        or not re.fullmatch(
            r'(?:[a-z0-9][a-z0-9._/-]{0,239}@)?sha256:[0-9a-f]{64}',
            str(container.get('image_digest') or ''),
        )
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_ADMISSION_INVALID'
        )
    return resolution


def normalize_step(raw: str, aliases: dict[str, str]) -> str:
    key = raw.strip().lower().replace('_', '').replace('-', '')
    if key not in aliases:
        raise SystemExit(f'unsupported step: {raw!r}')
    return aliases[key]


def step_slice(start: str, end: str) -> list[str]:
    s = STEP_ORDER.index(start)
    e = STEP_ORDER.index(end)
    if e < s:
        raise SystemExit(f'end-step {end} is before start-step {start}')
    return STEP_ORDER[s:e + 1]


def tail(text: str, limit: int = 12000) -> str:
    return text[-limit:] if len(text) > limit else text


def redact_denied_values(text: str, denied_values: list[str]) -> str:
    redacted = text
    for value in sorted(
        {item for item in denied_values if item},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(value, '[HOST_PRIVATE]')
    return redacted


def public_command_proof(
    result: CommandResult,
    *,
    denied_values: list[str],
) -> dict[str, Any]:
    """Serialize a command without exposing Host-private authority coordinates."""

    projected = asdict(result)
    projected['command'] = [
        redact_denied_values(value, denied_values)
        if isinstance(value, str)
        else value
        for value in projected.get('command', [])
    ]
    for field in ('cwd', 'stdout_tail', 'stderr_tail'):
        value = projected.get(field)
        if isinstance(value, str):
            projected[field] = redact_denied_values(value, denied_values)
    return projected


def host_private_proof_denied_values(
    args: argparse.Namespace,
    host_control: dict[str, str],
) -> list[str]:
    """Collect exact Host-private values that may never enter public proofs."""

    values = [value for value in host_control.values() if value]
    for name in (
        'research_org_runtime_private_root',
        'research_org_runtime_trust_root',
        'research_org_runtime_installation_id',
        'sealed_oos_carrier',
        'sealed_oos_private_root',
    ):
        value = str(getattr(args, name, None) or '')
        if value:
            values.append(value)
    for value in tuple(values):
        if '/' not in value:
            continue
        try:
            values.append(str(Path(value).expanduser().resolve(strict=False)))
        except (OSError, RuntimeError, ValueError):
            # The literal value is still denied even when it cannot be resolved.
            pass
    return list(dict.fromkeys(value for value in values if value))


def run_command(name: str, command: list[str], *, cwd: Path, env: dict[str, str], dry_run: bool = False) -> CommandResult:
    item = CommandResult(name=name, command=command, cwd=str(cwd), started_at_utc=utc_now())
    if dry_run:
        item.status = 'DRY_RUN'
        item.returncode = 0
        item.finished_at_utc = utc_now()
        return item
    proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    item.returncode = proc.returncode
    item.stdout_tail = tail(proc.stdout)
    item.stderr_tail = tail(proc.stderr)
    item.finished_at_utc = utc_now()
    item.status = 'PASS' if proc.returncode == 0 else 'FAIL'
    return item


def run_evo_child_container_command(
    *,
    admission_path: Path | str,
    name: str,
    command: list[str],
    env: dict[str, str],
    trust_root: Path | str,
    installation_id: str,
    repo_root: Path,
    timeout: float = 86_400,
) -> tuple[CommandResult, dict[str, Any]]:
    """Run one closed EVO child Agent stage and project its public proof ref."""

    if name not in EVO_CHILD_AGENT_STAGE_NAMES:
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_STAGE_NAME_INVALID'
        )
    execution = run_evo_child_agent_stage(
        admission_path,
        name,
        command,
        env,
        timeout,
        trust_root,
        installation_id,
    )
    if not isinstance(execution, dict):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_EXECUTION_INVALID'
        )
    raw_result = execution.get('command_result')
    expected_result_fields = {
        'name',
        'command',
        'cwd',
        'started_at_utc',
        'finished_at_utc',
        'returncode',
        'stdout_tail',
        'stderr_tail',
        'status',
    }
    if (
        not isinstance(raw_result, dict)
        or set(raw_result) != expected_result_fields
        or raw_result.get('name') != name
        or raw_result.get('command') != command
        or raw_result.get('cwd') != str(repo_root.resolve())
        or not isinstance(raw_result.get('started_at_utc'), str)
        or not isinstance(raw_result.get('finished_at_utc'), str)
        or isinstance(raw_result.get('returncode'), bool)
        or not isinstance(raw_result.get('returncode'), int)
        or not isinstance(raw_result.get('stdout_tail'), str)
        or not isinstance(raw_result.get('stderr_tail'), str)
        or raw_result.get('status') not in {'PASS', 'FAIL'}
        or (raw_result.get('returncode') == 0) != (raw_result.get('status') == 'PASS')
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_COMMAND_RESULT_INVALID'
        )
    receipt = execution.get('termination_receipt')
    receipt_sha256 = execution.get('termination_receipt_sha256')
    stage_status = execution.get('stage_status')
    timed_out = execution.get('timed_out')
    receipt_process_tree = (
        receipt.get('process_tree') if isinstance(receipt, dict) else None
    )
    receipt_execution = (
        receipt.get('execution') if isinstance(receipt, dict) else None
    )
    receipt_admission_ref = (
        receipt.get('admission_ref') if isinstance(receipt, dict) else None
    )
    receipt_inflight_ref = (
        receipt.get('inflight_ref') if isinstance(receipt, dict) else None
    )
    receipt_container = (
        receipt.get('container') if isinstance(receipt, dict) else None
    )
    receipt_command = (
        receipt.get('command') if isinstance(receipt, dict) else None
    )
    expected_stage_status = (
        'TIMED_OUT'
        if timed_out is True
        else 'SUCCEEDED'
        if raw_result['returncode'] == 0
        else 'FAILED'
    )
    if (
        not isinstance(receipt, dict)
        or receipt.get('stage_name') != name
        or receipt.get('status')
        != 'HOST_CONFIRMED_CONTAINER_PROCESS_TREE_ABSENT'
        or not isinstance(receipt_process_tree, dict)
        or receipt_process_tree.get('process_tree_absent') is not True
        or not isinstance(receipt_execution, dict)
        or receipt_execution.get('factor_verdict') != 'NOT_ISSUED'
        or receipt_execution.get('returncode') != raw_result.get('returncode')
        or receipt_execution.get('timed_out') is not timed_out
        or receipt_execution.get('stage_status') != stage_status
        or execution.get('factor_verdict') != 'NOT_ISSUED'
        or execution.get('process_tree_absent') is not True
        or stage_status != expected_stage_status
        or not isinstance(timed_out, bool)
        or not re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('receipt_id') or ''))
        or not re.fullmatch(r'[0-9a-f]{64}', str(receipt_sha256 or ''))
        or not isinstance(receipt_admission_ref, dict)
        or not isinstance(receipt_inflight_ref, dict)
        or not isinstance(receipt_container, dict)
        or receipt_container.get('network') != 'none'
        or not isinstance(receipt_command, dict)
        or receipt_command.get('logical_argv') != command
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_TERMINATION_INVALID'
        )
    termination_ref = {
        'contract_version': 'factorforge_ultimate_evo_child_container_ref_v1',
        'stage_name': name,
        'stage_status': stage_status,
        'process_tree_absent': True,
        'factor_verdict': 'NOT_ISSUED',
        'admission_receipt_id': receipt_admission_ref.get('receipt_id'),
        'inflight_receipt_id': receipt_inflight_ref.get('receipt_id'),
        'termination_receipt_id': receipt['receipt_id'],
        'termination_receipt_sha256': receipt_sha256,
        'image_digest': receipt_container.get('image_digest'),
        'logical_command_sha256': receipt_command.get('logical_sha256'),
    }
    if any(
        not isinstance(termination_ref[field], str)
        or not termination_ref[field]
        for field in (
            'admission_receipt_id',
            'inflight_receipt_id',
            'termination_receipt_id',
            'termination_receipt_sha256',
            'image_digest',
            'logical_command_sha256',
        )
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_TERMINATION_REF_INVALID'
        )
    if (
        not all(
            re.fullmatch(r'[0-9a-f]{64}', termination_ref[field])
            for field in (
                'admission_receipt_id',
                'inflight_receipt_id',
                'termination_receipt_id',
                'termination_receipt_sha256',
                'logical_command_sha256',
            )
        )
        or not re.fullmatch(
            r'(?:[a-z0-9][a-z0-9._/-]{0,239}@)?sha256:[0-9a-f]{64}',
            termination_ref['image_digest'],
        )
    ):
        raise RuntimeError(
            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_TERMINATION_REF_INVALID'
        )
    return CommandResult(**raw_result), termination_ref


def _json_from_command_stdout(result: CommandResult) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout_tail)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _validated_evo_outcome_stage(
    factorforge_root: Path,
    report_id: str,
    expected_council_state: str,
    *,
    allowed_current_states: set[str] | None = None,
    required_event_count: int = 2,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Replay the Host lifecycle, pre-OOS outcome and staged CAS commit."""

    reasons: list[str] = []
    lifecycle_path = epistemic_evolution_lifecycle_path(
        factorforge_root, report_id
    )
    try:
        lifecycle = load_evo_json_object(lifecycle_path)
    except Exception as exc:
        return False, [f'lifecycle_unreadable:{type(exc).__name__}'], None
    reasons.extend(
        validate_epistemic_evolution_lifecycle(
            lifecycle,
            report_id=report_id,
            workspace_root=factorforge_root,
            require_signed_host_receipts=True,
        )
    )
    accepted_states = allowed_current_states or {expected_council_state}
    current_state = str(lifecycle.get('current_state') or '')
    if current_state not in accepted_states:
        reasons.append('lifecycle_state_mismatch')
    verifier, verifier_reasons = pre_oos_outcome_evidence_reference(
        workspace_root=factorforge_root,
        report_id=report_id,
        expected_transition_state=expected_council_state,
    )
    reasons.extend(verifier_reasons)
    manifest_path = evo_staging_manifest_path(factorforge_root, report_id)
    try:
        manifest = load_evo_json_object(manifest_path)
    except Exception as exc:
        reasons.append(f'staging_manifest_unreadable:{type(exc).__name__}')
        manifest = None
    if isinstance(manifest, dict):
        reasons.extend(
            validate_evo_v2_staging_manifest(
                manifest,
                root=factorforge_root,
                report_id=report_id,
                verify_readback=True,
            )
        )
        events = manifest.get('events')
        if not isinstance(events, list) or len(events) != required_event_count:
            reasons.append('staging_council_outcome_missing')
        else:
            council_binding = events[1].get('lifecycle_binding')
            council_generation = next(
                (
                    index + 1
                    for index, event in enumerate(lifecycle.get('events') or [])
                    if isinstance(event, dict)
                    and event.get('to_state') == expected_council_state
                ),
                None,
            )
            council_snapshot = None
            council_snapshot_path = None
            if isinstance(council_generation, int):
                council_snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
                    factorforge_root,
                    report_id,
                    council_generation,
                )
                try:
                    council_snapshot = load_evo_json_object(council_snapshot_path)
                except Exception as exc:
                    reasons.append(
                        f'council_lifecycle_snapshot_unreadable:{type(exc).__name__}'
                    )
                else:
                    reasons.extend(
                        validate_epistemic_evolution_lifecycle(
                            council_snapshot,
                            report_id=report_id,
                            workspace_root=factorforge_root,
                            require_signed_host_receipts=True,
                        )
                    )
                    current_events = lifecycle.get('events') or []
                    snapshot_events = council_snapshot.get('events') or []
                    if (
                        council_snapshot.get('current_state')
                        != expected_council_state
                        or current_events[: len(snapshot_events)] != snapshot_events
                    ):
                        reasons.append('council_lifecycle_snapshot_not_ancestor')
            else:
                reasons.append('council_lifecycle_state_missing')
            if (
                events[1].get('outcome') != expected_council_state
                or not isinstance(council_binding, dict)
                or not isinstance(council_snapshot, dict)
                or council_binding.get('content_sha256')
                != council_snapshot.get('content_sha256')
                or council_snapshot_path is None
                or council_binding.get('sha256')
                != sha256_file(council_snapshot_path)
            ):
                reasons.append('staging_lifecycle_outcome_mismatch')
            current_binding = events[-1].get('lifecycle_binding')
            if (
                not isinstance(current_binding, dict)
                or current_binding.get('current_state') != current_state
                or current_binding.get('content_sha256')
                != lifecycle.get('content_sha256')
                or current_binding.get('sha256') != sha256_file(lifecycle_path)
            ):
                reasons.append('staging_current_lifecycle_mismatch')
    return not reasons, list(dict.fromkeys(reasons)), verifier


def _evo_pre_oos_executor_block_token(
    council_mode: str,
    executor: str,
) -> str | None:
    """Return a formal pre-OOS executor blocker, never a silent fallback."""

    if council_mode == 'agentic' and executor == 'none':
        return 'BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED'
    if executor == 'real_agent':
        return 'BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED'
    if executor == 'local_mock':
        return 'BLOCK_EVO_V2_PRE_OOS_COUNCIL_LOCAL_MOCK_FORBIDDEN'
    if council_mode == 'agentic' and executor != 'dispatch_manifest':
        return 'BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED'
    return None


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return (
        name == '__pycache__'
        or name == '.DS_Store'
        or name.endswith('.lock')
        or name.endswith('.tmp')
        or name.endswith('.swp')
        or name.endswith('.swx')
        or name.startswith('.#')
        or name.startswith('~$')
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_dir():
        return None
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob('*'), key=lambda p: p.relative_to(path).as_posix()):
        rel = item.relative_to(path)
        if any(should_skip_digest_path(part) for part in rel.parents):
            continue
        if should_skip_digest_path(item):
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        entries.append(
            {
                'relative_path': rel.as_posix(),
                'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns,
                'sha256': sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def path_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {'path': str(path), 'exists': False, 'kind': None, 'sha256': None, 'digest': None}
    if path.is_file():
        return {'path': str(path), 'exists': True, 'kind': 'file', 'sha256': sha256_file(path), 'digest': None}
    if path.is_dir():
        return {'path': str(path), 'exists': True, 'kind': 'directory', 'sha256': None, 'digest': directory_digest(path)}
    return {'path': str(path), 'exists': True, 'kind': 'other', 'sha256': None, 'digest': None}


def council_side_effect_snapshot(
    factorforge_root: Path,
    report_id: str,
    *,
    clean_data_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        'step3b_handoff': path_snapshot(factorforge_root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json'),
        'generated_code': path_snapshot(factorforge_root / 'generated_code' / report_id),
        'official_record': path_snapshot(factorforge_root / 'objects' / 'factor_library_official' / f'factor_record__{report_id}.json'),
        'data_clean': path_snapshot(clean_data_root or (factorforge_root / 'data' / 'clean')),
    }


def side_effect_changes(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key, old in before.items():
        new = after.get(key) or {}
        if old.get('exists') != new.get('exists') or old.get('kind') != new.get('kind') or old.get('sha256') != new.get('sha256') or old.get('digest') != new.get('digest'):
            changes.append({'path_key': key, 'before': old, 'after': new})
    return changes


def disable_provisional_step3b_handoff_for_council(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    """Council-primary mode must not leave the deterministic Step6 handoff active.

    Step6 core can still produce a legacy/deterministic handoff before Council runs.
    Once Council is selected as the final revision authority, that handoff becomes
    provisional evidence, not executable loop authorization. Archive it inside the
    Council workspace before the Council packet baseline is captured.
    """
    handoff = factorforge_root / 'objects' / 'handoff' / f'handoff_to_step3b__{report_id}.json'
    if not handoff.exists():
        return {'disabled': False, 'reason': 'handoff_absent', 'original_path': str(handoff)}
    try:
        handoff_payload = json.loads(handoff.read_text(encoding='utf-8'))
    except Exception:
        handoff_payload = {}
    approval_markers = {
        handoff_payload.get('loop_authorization'),
        handoff_payload.get('authorization'),
        handoff_payload.get('status'),
    }
    if (
        'approved_for_step3b_handoff' in approval_markers
        and (
            handoff_payload.get('main_agent_council_synthesis_path')
            or handoff_payload.get('orchestrator_synthesis_path')
            or handoff_payload.get('approval_source') in {'ultimate_loop_auto_bridge', 'current_main_agent_orchestration_synthesis'}
        )
    ):
        return {
            'disabled': False,
            'reason': 'approved_main_agent_council_synthesis_handoff_preserved',
            'original_path': str(handoff),
            'original_snapshot': path_snapshot(handoff),
            'canonical_write_permission': False,
            'step3b_handoff_active_after_disable': True,
        }
    council_dir = factorforge_root / 'objects' / 'research_iteration_master' / 'revision_council' / report_id
    archive = council_dir / f'provisional_step3b_handoff_disabled_by_council__{report_id}.json'
    meta = council_dir / f'provisional_step3b_handoff_disabled_by_council__{report_id}.meta.json'
    council_dir.mkdir(parents=True, exist_ok=True)
    snapshot = path_snapshot(handoff)
    archive.write_bytes(handoff.read_bytes())
    meta.write_text(
        json.dumps(
            {
                'report_id': report_id,
                'disabled_at_utc': utc_now(),
                'reason': 'Council-primary final revision authority requires advisory-only proposals until explicit approval.',
                'original_path': str(handoff),
                'archive_path': str(archive),
                'original_snapshot': snapshot,
                'canonical_write_permission': False,
                'step3b_handoff_active_after_disable': False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding='utf-8',
    )
    handoff.unlink()
    return {
        'disabled': True,
        'reason': 'council_primary_advisory_authority',
        'original_path': str(handoff),
        'archive_path': str(archive),
        'metadata_path': str(meta),
        'original_snapshot': snapshot,
    }


def enforce_evo_post_oos_no_revision(
    factorforge_root: Path,
    report_id: str,
) -> dict[str, Any]:
    """Remove a provisional handoff and fail closed on an approved one.

    A NO_QUALIFIED_CONTRADICTION parent may consume its sealed OOS exactly
    once for the original factor decision.  That outcome cannot authorize a
    Revision Council or a Step3B child because the holdout is now consumed.
    """

    policy = disable_provisional_step3b_handoff_for_council(
        factorforge_root,
        report_id,
    )
    handoff = (
        factorforge_root
        / 'objects'
        / 'handoff'
        / f'handoff_to_step3b__{report_id}.json'
    )
    active = handoff.exists() or handoff.is_symlink()
    return {
        'status': 'BLOCK' if active else 'SAFE_NO_REVISION',
        'active_step3b_handoff': active,
        'handoff_path': str(handoff),
        'handoff_policy': policy,
    }


def is_tmp_root(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith('/tmp/') or resolved.startswith('/tmp/') or resolved.startswith('/private/tmp/')


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


DATA_REQUEST_BLOCKER_PATTERNS = (
    'BLOCK_FACTORFORGE_DATA_REQUEST_REQUIRED',
    'BLOCK_STEP3A_DATA_API_RESOLUTION_MISSING',
    'BLOCK_STEP4_DATA_API_FETCH_FAILED',
    'BLOCK_STEP4_DATA_CONTRACT_MISSING',
    'BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED',
    'BLOCK_STEP4_MINUTE_DERIVED_STATE_EMPTY',
    'BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE',
    'missing_data_api',
    'Data API could not resolve',
    'dataset_not_found',
    'missing_intraday_flow_proxy_dataset',
    'Required clean/precomputed intraday proxy dataset',
    'BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED',
)

TRANSIENT_DATA_TRANSPORT_PATTERNS = (
    'AWS Error NETWORK_CONNECTION',
    'Timeout was reached',
    'Operation too slow',
    'ReadTimeoutError',
    'ConnectTimeoutError',
    'ConnectionResetError',
    'Temporary failure in name resolution',
)


def is_transient_data_transport_failure(output: str) -> bool:
    lowered = output.lower()
    return any(pattern.lower() in lowered for pattern in TRANSIENT_DATA_TRANSPORT_PATTERNS)


def safe_request_token(raw: str) -> str:
    token = re.sub(r'[^A-Za-z0-9_.-]+', '_', raw.strip())
    return token.strip('_') or 'unknown'


def resolve_data_api_root(repo_root: Path) -> Path | None:
    candidates = []
    env_root = os.environ.get('FACTORFORGE_DATA_API_ROOT')
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(
        [
            Path('/Users/humphrey/projects/factor-factory-data-api'),
            repo_root.parent / 'factor-factory-data-api',
            repo_root.parent / 'factorforge-data-api',
        ]
    )
    for candidate in candidates:
        if (candidate / 'scripts' / 'data_request_inbox.py').exists():
            return candidate
    return None


def extract_missing_datasets(payload: Any) -> list[str]:
    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'missing_datasets' and isinstance(item, list):
                    found.extend(str(dataset) for dataset in item if str(dataset).strip())
                elif key in {'dataset_id', 'requested_dataset_id'} and isinstance(item, str):
                    if any(marker in item for marker in ('intraday_', 'daily_basic', 'minute_bar', 'clean_daily')):
                        found.append(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    deduped: list[str] = []
    for item in found:
        if item not in deduped:
            deduped.append(item)
    return deduped


def feasibility_has_data_blocker(feasibility: dict[str, Any]) -> bool:
    if not feasibility:
        return False
    verdicts = {
        str(feasibility.get(key) or '').strip().lower()
        for key in ('feasibility', 'final_result', 'status', 'verdict')
    }
    if verdicts & {'block', 'blocked', 'fail', 'failed', 'missing', 'unavailable'}:
        return True
    if feasibility.get('blocked') is True:
        return True
    blocked_items = feasibility.get('blocked_items')
    if isinstance(blocked_items, list) and bool(blocked_items):
        return True

    def has_explicit_missing_list(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'missing_datasets' and isinstance(item, list):
                    if any(str(dataset).strip() for dataset in item):
                        return True
                elif has_explicit_missing_list(item):
                    return True
        elif isinstance(value, list):
            return any(has_explicit_missing_list(item) for item in value)
        return False

    return has_explicit_missing_list(feasibility)


def data_request_candidate_from_failure(
    *,
    report_id: str,
    command_name: str,
    output: str,
    ctx: Any,
) -> dict[str, Any] | None:
    if command_name not in {'run_step3', 'validate_step3', 'run_step3b', 'validate_step3b', 'run_step4', 'validate_step4'}:
        return None
    # A transport failure does not establish that a catalog entry, field, or
    # coverage range is missing.  In particular, do not combine a stale prior
    # feasibility BLOCK with a fresh network traceback and manufacture a P0
    # coverage request for a dataset that is already admitted and QA'd.
    if is_transient_data_transport_failure(output):
        return None
    feasibility_path = ctx.objects_root / 'validation' / f'data_feasibility_report__{report_id}.json'
    feasibility = load_json_if_exists(feasibility_path)
    feasibility_blocked = feasibility_has_data_blocker(feasibility)
    combined = output
    if feasibility_blocked:
        combined += '\n' + json.dumps(feasibility, ensure_ascii=False)
    if not any(pattern in combined for pattern in DATA_REQUEST_BLOCKER_PATTERNS):
        return None
    missing_datasets = extract_missing_datasets(feasibility) if feasibility_blocked else []
    if 'intraday_flow_distribution_moments_v1' in combined and 'intraday_flow_distribution_moments_v1' not in missing_datasets:
        missing_datasets.insert(0, 'intraday_flow_distribution_moments_v1')
    if 'daily_basic_backtest_base' in combined and 'daily_basic_backtest_base' not in missing_datasets:
        missing_datasets.append('daily_basic_backtest_base')
    if not missing_datasets:
        if 'minute' in combined.lower() or 'intraday' in combined.lower():
            missing_datasets = ['intraday_derived_datamart']
        elif 'clean_daily_bar' in combined:
            missing_datasets = ['clean_daily_bar']
        else:
            missing_datasets = [f'{safe_request_token(report_id)}_data_dependency']
    dataset_id = missing_datasets[0]
    request_type = 'new_datamart' if any(token in dataset_id for token in ('intraday_', 'datamart', 'state')) else 'coverage_repair'
    timestamp = utc_now().replace('-', '').replace(':', '').replace('T', '').replace('Z', '')
    return {
        'schema_version': 'data_request_v1',
        'request_id': f'{safe_request_token(report_id)}__{safe_request_token(dataset_id)}__{timestamp}',
        'created_at_utc': utc_now(),
        'created_by': 'factorforge-ultimate-wrapper',
        'report_id': report_id,
        'priority': 'P0',
        'requested_dataset_id': dataset_id,
        'request_type': request_type,
        'research_need': {
            'economic_purpose': 'Automatically generated from Factor Forge Ultimate data blocker.',
            'formula_or_state': '',
            'upstream_datasets': missing_datasets,
        },
        'window': {
            'is_start': '20160104',
            'is_end': '20250711',
            'oos_start': '20250714',
            'research_window_rule': 'OOS marked holdout; do not fit parameters on OOS',
        },
        'information_set': {
            'cutoff_times': [],
            'no_future_data': True,
            'state_continuity_required': 'state' in dataset_id or 'slow' in dataset_id,
        },
        'unique_key': ['ts_code', 'trade_date'],
        'required_fields': ['ts_code', 'trade_date'],
        'qa_requirements': [
            'duplicate_key_count=0',
            'missing_dates=[]',
            'coverage_summary',
            'representative_read_smoke',
            'worker_read_smoke',
        ],
        'execution_preference': {
            'preferred_executor': 'research_worker',
            'batch_spot_allowed': True,
            'requires_cost_estimate_before_full_run': True,
        },
        'boundaries': {
            'do_not_start_clean_data': True,
            'do_not_start_search_worker': True,
            'do_not_start_official_promotion': True,
            'do_not_write_factor_forge_research_artifacts': True,
            'do_not_start_factor_loop': True,
        },
        'auto_generation_context': {
            'command': command_name,
            'feasibility_path': str(feasibility_path),
            'source': 'run_factorforge_ultimate_failure_handler',
        },
    }


def write_data_request_candidate(candidate: dict[str, Any], *, repo_root: Path, ctx: Any) -> dict[str, Any]:
    paths: dict[str, str] = {}
    local_dir = ctx.active_root / 'objects' / 'data_requests'
    local_path = local_dir / f"data_request__{safe_request_token(candidate['request_id'])}.json"
    write_json_atomic(local_path, candidate)
    paths['local_request_path'] = str(local_path)
    data_api_root = resolve_data_api_root(repo_root)
    if data_api_root is not None:
        inbox = data_api_root / 'factorforge' / 'data' / 'requests' / 'inbox'
        inbox_path = inbox / f"data_request__{safe_request_token(candidate['request_id'])}.json"
        write_json_atomic(inbox_path, candidate)
        paths['data_api_inbox_path'] = str(inbox_path)
        paths['data_api_root'] = str(data_api_root)
    return {
        'status': 'CREATED',
        'request_id': candidate['request_id'],
        'dataset_id': candidate['requested_dataset_id'],
        'request_type': candidate['request_type'],
        **paths,
    }


def research_memo_from_iteration(iteration: dict[str, Any]) -> dict[str, Any]:
    return ((iteration.get('research_judgment') or {}).get('research_memo') or {})


def council_auto_trigger(iteration: dict[str, Any]) -> tuple[bool, str]:
    research_judgment = iteration.get('research_judgment') or {}
    research_memo = research_memo_from_iteration(iteration)
    evidence_audit = research_memo.get('evidence_audit') or {}
    case_comparison = research_memo.get('case_comparison') or {}
    revision_strategy = research_memo.get('revision_strategy') or {}
    mechanism_analysis = research_memo.get('mechanism_analysis') or {}
    decision = research_judgment.get('decision')
    revision_needed = revision_strategy.get('revision_needed') is True
    failure_signature = revision_strategy.get('primary_failure_signature')
    mechanism_fit = mechanism_analysis.get('mechanism_fit')
    if evidence_audit.get('evidence_verdict') == 'blocked':
        return False, 'evidence_blocked'
    if case_comparison.get('case_comparison_verdict') == 'blocked':
        return False, 'case_comparison_blocked'
    if decision == 'promote_official' and not revision_needed:
        return False, 'no_revision_needed'
    if decision == 'reject' and not revision_needed:
        return False, 'no_revision_needed'
    if decision == 'iterate':
        return True, 'decision_iterate'
    if revision_needed:
        return True, 'revision_needed'
    if mechanism_fit in {'weak', 'contradicted'}:
        return True, f'mechanism_fit_{mechanism_fit}'
    if failure_signature and failure_signature != 'none':
        return True, f'failure_signature_{failure_signature}'
    return False, 'no_revision_needed'


def council_blocked_by_evidence(iteration: dict[str, Any]) -> bool:
    research_memo = research_memo_from_iteration(iteration)
    return (
        ((research_memo.get('evidence_audit') or {}).get('evidence_verdict') == 'blocked')
        or ((research_memo.get('case_comparison') or {}).get('case_comparison_verdict') == 'blocked')
    )


def summarize_council_attachment(factorforge_root: Path, report_id: str, side_effect_after: dict[str, dict[str, Any]], side_effect_before: dict[str, dict[str, Any]]) -> dict[str, Any]:
    iteration_path = factorforge_root / 'objects' / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    iteration = load_json_if_exists(iteration_path)
    research_memo = research_memo_from_iteration(iteration)
    final_strategy = research_memo.get('final_revision_strategy') or {}
    council_dir = factorforge_root / 'objects' / 'research_iteration_master' / 'revision_council' / report_id
    summary = load_json_if_exists(council_dir / f'revision_council_summary__{report_id}.json')
    taskbook_path = council_dir / f'agentic_taskbook__{report_id}.json'
    agent_result_paths = sorted(str(path) for path in (council_dir / 'agent_results').glob(f'agent_result__{report_id}__*.json'))
    payload = {
        'packet_path': str(factorforge_root / 'objects' / 'research_iteration_master' / 'revision_council' / report_id / f'revision_council_packet__{report_id}.json'),
        'summary_path': str(factorforge_root / 'objects' / 'research_iteration_master' / 'revision_council' / report_id / f'revision_council_summary__{report_id}.json'),
        'attached': (iteration.get('revision_council_ref') or {}).get('enabled') is True,
        'final_revision_strategy_source': final_strategy.get('source'),
        'loop_authorization': final_strategy.get('loop_authorization'),
        'step3b_handoff_exists': side_effect_after['step3b_handoff']['exists'],
        'official_record_exists': side_effect_after['official_record']['exists'],
        'generated_code_digest_unchanged': side_effect_before['generated_code'].get('digest') == side_effect_after['generated_code'].get('digest') and side_effect_before['generated_code'].get('exists') == side_effect_after['generated_code'].get('exists'),
        'data_clean_digest_unchanged': side_effect_before['data_clean'].get('digest') == side_effect_after['data_clean'].get('digest') and side_effect_before['data_clean'].get('exists') == side_effect_after['data_clean'].get('exists'),
    }
    if taskbook_path.exists() or summary.get('valid_agent_results') is not None:
        payload.update(
            {
                'agentic_taskbook_path': str(taskbook_path),
                'agent_result_paths': agent_result_paths,
                'agent_result_count': len(agent_result_paths),
                'valid_agent_result_count': len(summary.get('valid_agent_results') or []),
                'blocked_agent_result_count': len(summary.get('blocked_agent_results') or []),
            }
        )
    return payload


def summarize_council_dispatch(factorforge_root: Path, report_id: str, side_effect_after: dict[str, dict[str, Any]], side_effect_before: dict[str, dict[str, Any]]) -> dict[str, Any]:
    council_dir = factorforge_root / 'objects' / 'research_iteration_master' / 'revision_council' / report_id
    manifest_path = council_dir / f'dispatch_manifest__{report_id}.json'
    manifest = load_json_if_exists(manifest_path)
    manual_manifest_path = council_dir / 'manual_dispatch' / f'manual_dispatch_manifest__{report_id}.json'
    manual_manifest = load_json_if_exists(manual_manifest_path)
    status_ledger_path = council_dir / f'agentic_dispatch_status__{report_id}.json'
    status_ledger = load_json_if_exists(status_ledger_path)
    task_paths = [
        str(factorforge_root / item.get('task_packet_path'))
        for item in (manifest.get('agent_tasks') or [])
        if isinstance(item, dict) and isinstance(item.get('task_packet_path'), str)
    ]
    payload = {
        'packet_path': str(council_dir / f'revision_council_packet__{report_id}.json'),
        'agentic_taskbook_path': str(council_dir / f'agentic_taskbook__{report_id}.json'),
        'dispatch_manifest_path': str(manifest_path),
        'agent_task_count': manifest.get('agent_task_count'),
        'agent_task_packet_paths': task_paths,
        'next_action': 'agents_must_write_results_then_run_finalize_agentic_council_dispatch',
        'attached': False,
        'step3b_handoff_exists': side_effect_after['step3b_handoff']['exists'],
        'official_record_exists': side_effect_after['official_record']['exists'],
        'generated_code_digest_unchanged': side_effect_before['generated_code'].get('digest') == side_effect_after['generated_code'].get('digest') and side_effect_before['generated_code'].get('exists') == side_effect_after['generated_code'].get('exists'),
        'data_clean_digest_unchanged': side_effect_before['data_clean'].get('digest') == side_effect_after['data_clean'].get('digest') and side_effect_before['data_clean'].get('exists') == side_effect_after['data_clean'].get('exists'),
    }
    if manual_manifest_path.exists():
        payload.update(
            {
                'manual_dispatch_manifest_path': str(manual_manifest_path),
                'manual_dispatch_status': manual_manifest.get('status'),
                'manual_assignment_count': manual_manifest.get('agent_count'),
                'manual_assignment_paths': [
                    str(factorforge_root / item.get('assignment_markdown_path'))
                    for item in (manual_manifest.get('assignments') or [])
                    if isinstance(item, dict) and isinstance(item.get('assignment_markdown_path'), str)
                ],
                'manual_result_dropbox_paths': [
                    str(factorforge_root / item.get('result_dropbox_path'))
                    for item in (manual_manifest.get('assignments') or [])
                    if isinstance(item, dict) and isinstance(item.get('result_dropbox_path'), str)
                ],
            }
        )
    if status_ledger_path.exists():
        payload.update(
            {
                'dispatch_status_ledger_path': str(status_ledger_path),
                'dispatch_status': status_ledger.get('status'),
                'ready_for_collection': status_ledger.get('ready_for_collection'),
            }
        )
    return payload


def agentic_dispatch_required_results_present(
    factorforge_root: Path,
    report_id: str,
) -> bool:
    council_dir = (
        factorforge_root
        / 'objects'
        / 'research_iteration_master'
        / 'revision_council'
        / report_id
    )
    manifest_path = council_dir / f'dispatch_manifest__{report_id}.json'
    manifest = load_json_if_exists(manifest_path)
    tasks = manifest.get('agent_tasks')
    if (
        manifest.get('dispatch_manifest_version')
        != 'factorforge_agentic_council_dispatch_manifest_v1'
        or manifest.get('report_id') != report_id
        or not isinstance(tasks, list)
        or not tasks
    ):
        return False
    result_root = (council_dir / 'agent_results').resolve(strict=False)
    for task in tasks:
        if not isinstance(task, dict) or task.get('required') is not True:
            return False
        raw = task.get('expected_result_path')
        if not isinstance(raw, str) or not raw:
            return False
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else factorforge_root / candidate
        if candidate.is_symlink():
            return False
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(result_root)
        except (FileNotFoundError, ValueError):
            return False
        if resolved.is_symlink() or not resolved.is_file():
            return False
    return True


def summarize_main_agent_memo_pause(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    rim = factorforge_root / 'objects' / 'research_iteration_master'
    status_path = rim / f'main_agent_mechanism_memo_status__{report_id}.json'
    questionnaire_path = rim / f'main_agent_mechanism_questionnaire__{report_id}.json'
    questionnaire_md_path = rim / f'main_agent_mechanism_questionnaire__{report_id}.md'
    memo_path = rim / f'main_agent_mechanism_memo__{report_id}.json'
    status = load_json_if_exists(status_path)
    return {
        'status': status.get('status') or 'awaiting_main_agent_mechanism_memo',
        'token': status.get('token') or 'AWAITING_MAIN_AGENT_MECHANISM_MEMO',
        'status_path': str(status_path),
        'questionnaire_path': str(questionnaire_path),
        'questionnaire_markdown_path': str(questionnaire_md_path),
        'expected_memo_path': str(memo_path),
        'next_action': status.get('next_action') or 'Current main agent must answer the questionnaire and rerun Step6.',
        'canonical_write_permission': False,
        'execution_allowed_by_default': False,
    }


def object_status(path: Path) -> dict[str, Any]:
    return {
        'path': str(path),
        'exists': path.exists(),
        'size': path.stat().st_size if path.exists() else None,
        'mtime': path.stat().st_mtime if path.exists() else None,
    }


def collect_expected_artifacts(manifest: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, str] = {}
    for section in ['objects', 'runs', 'evaluations']:
        for key, value in (manifest.get(section) or {}).items():
            if isinstance(value, str):
                paths[f'{section}.{key}'] = value
    for step, spec in (manifest.get('step_io') or {}).items():
        for direction in ['inputs', 'data_inputs', 'outputs']:
            for key, value in (spec.get(direction) or {}).items():
                if isinstance(value, str):
                    paths[f'step_io.{step}.{direction}.{key}'] = value
    return {key: object_status(Path(value)) for key, value in sorted(paths.items())}


def collect_step3b_mode_decision(manifest: dict[str, Any]) -> dict[str, Any] | None:
    raw = (
        ((manifest.get('step_io') or {}).get('step3') or {})
        .get('outputs', {})
        .get('implementation_plan_master')
    ) or ((manifest.get('objects') or {}).get('implementation_plan_master'))
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return {'status': 'unreadable', 'path': str(path), 'error': str(exc)}
    decision = data.get('implementation_mode_decision')
    if not isinstance(decision, dict):
        return None
    return {
        'path': str(path),
        'selected_mode': decision.get('selected_mode'),
        'requested_mode': decision.get('requested_mode'),
        'final_decision_reason': decision.get('final_decision_reason'),
        'correctness_risk': decision.get('correctness_risk'),
        'human_review_required': decision.get('human_review_required'),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Strict single-entry runner for Factor Forge Step2-6.')
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--start-step', default='3', help='2, 3, 3b, 4, 5, or 6')
    ap.add_argument('--end-step', default='6', help='2, 3, 3b, 4, 5, 6, or all')
    ap.add_argument('--factorforge-root', default=None)
    ap.add_argument('--branch-id', default=None)
    ap.add_argument('--manifest', default=None, help='Use an existing runtime manifest instead of creating a new one.')
    ap.add_argument('--factor-id', default=None)
    ap.add_argument('--research-id', default=None)
    ap.add_argument('--factor-workspace', default=None)
    ap.add_argument('--init-factor-workspace', action='store_true')
    ap.add_argument('--allow-legacy-global-runtime', action='store_true')
    ap.add_argument('--skip-step3a', action='store_true', help='When starting at Step3, skip run_step3 and run only Step3B onward.')
    ap.add_argument('--skip-researcher-packets', action='store_true', help='Do not build Step6 researcher packet/dossier before Step6.')
    ap.add_argument('--apply-approved-revision', action='store_true', help='Apply a human-approved Step6 revision before running the requested step range.')
    ap.add_argument('--council-mode', choices=['off', 'auto', 'scaffold', 'agentic'], default='auto')
    ap.add_argument('--auto-council-policy', choices=['scaffold', 'dispatch_manifest', 'block_without_agentic'], default='dispatch_manifest')
    ap.add_argument('--research-loop-policy', choices=['single_pass', 'council_until_promote_or_exhausted'], default='council_until_promote_or_exhausted')
    ap.add_argument('--max-council-loops', type=int, default=10)
    ap.add_argument('--agentic-council-executor', choices=['none', 'local_mock', 'dispatch_manifest', 'real_agent'], default='none')
    ap.add_argument('--agentic-dispatch-adapter', choices=['none', 'manual_file', 'openclaw', 'codex', 'remote_api'], default='none')
    ap.add_argument('--runtime-dispatch', choices=['codex', 'openclaw', 'manual_file', 'unknown'], default=None)
    ap.add_argument('--subagent-provider', default=None)
    ap.add_argument('--subagent-model', default=None)
    ap.add_argument(
        '--research-org-mode',
        choices=['off', 'auto', 'required'],
        default='auto',
        help='Validate the workspace research-organization plan; required fails closed when absent.',
    )
    ap.add_argument(
        '--research-org-plan',
        default=None,
        help='Explicit plan path. It must equal the active workspace Host-owned plan path.',
    )
    ap.add_argument(
        '--research-org-runtime-mode',
        choices=['off', 'if-present', 'required', 'formal-complete', 'revision-child-assured'],
        default='off',
        help='Optionally bind this Ultimate run to the validated specialist runtime.',
    )
    ap.add_argument('--research-org-runtime-private-root', default=None)
    ap.add_argument('--research-org-runtime-trust-root', default=None)
    ap.add_argument('--research-org-runtime-installation-id', default=None)
    ap.add_argument('--evo-child-research-org-assurance', default=None)
    ap.add_argument(
        '--expected-host-trust-manifest-sha256',
        default=None,
        help=(
            'Externally pinned Host public trust-manifest digest used to replay '
            'formal EVO child contracts. It must come from the Host control '
            'plane, not from the mutable workspace.'
        ),
    )
    ap.add_argument(
        '--sealed-oos-carrier',
        default=None,
        help='Host-private fresh OOS dataset exposed only after NQC release.',
    )
    ap.add_argument(
        '--sealed-oos-private-root',
        default=None,
        help='Externally pinned Host-private root containing the sealed OOS carrier.',
    )
    ap.add_argument(
        '--sealed-oos-agent-visible-root',
        action='append',
        default=[],
        help='Host-pinned root mounted into an Agent runtime; repeat as needed.',
    )
    ap.add_argument(
        '--agent-execution-sandbox-profile',
        default=None,
        help=(
            'Deprecated and forbidden for EVO child execution. A caller-owned '
            'profile is not execution authority; use the signed admission.'
        ),
    )
    ap.add_argument(
        '--agent-execution-sandbox-admission',
        default=None,
        help=(
            'Deprecated and forbidden for EVO child execution. Production child '
            'Agent stages require the dedicated signed container admission.'
        ),
    )
    ap.add_argument(
        '--agent-execution-container-admission',
        default=None,
        help=(
            'Host-private signed admission for the closed EVO child Step3B/Step4 '
            'container runner. Required for every non-dry-run EVO child.'
        ),
    )
    ap.add_argument(
        '--evo-child-finalizer-recovery-admission',
        default=None,
        help=(
            'Host-private signed CHILD_RECOVERY_READY receipt. It authorizes '
            'only the Host finalizer after a completed validate_step4 crash.'
        ),
    )
    ap.add_argument(
        '--evo-child-command-recovery-admission',
        default=None,
        help=(
            'Host-private signed exact-command recovery admission for a '
            'RUNNING EVO child proof. Direct unsigned command skipping is forbidden.'
        ),
    )
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--allow-legacy-research-protocol-smoke', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--proof-output', default=None)
    ap.add_argument('--state-dependency-contract', default=None)
    ap.add_argument('--state-catalog', default=None)
    ap.add_argument('--state-resolution', default=None)
    ap.add_argument('--state-data-request-dir', default=None)
    ap.add_argument('--state-input-path', action='append', default=[], help='Step4 input path to check for forbidden production raw-minute roots.')
    ap.add_argument('--require-state-reuse-contract', action='store_true')
    ap.add_argument('--explicit-data-production-context', action='store_true')
    return ap.parse_args()


def resolve_research_organization_runtime_gate(
    *,
    args: argparse.Namespace,
    factor_workspace: Path | None,
) -> dict[str, Any]:
    mode = str(args.research_org_runtime_mode or 'off')
    requested_report_id = str(getattr(args, 'report_id', '') or '')
    if mode == 'off':
        return {
            'mode': mode,
            'status': 'disabled',
            'formal_independence_verified': False,
            'runtime_assurance': 'not_requested',
        }
    if factor_workspace is None:
        if mode == 'if-present':
            return {
                'mode': mode,
                'status': 'not_present',
                'formal_independence_verified': False,
                'runtime_assurance': 'not_present',
            }
        raise ResearchOrganizationError(
            'BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_MISSING',
            ['factor_workspace_required'],
        )
    if mode == 'revision-child-assured':
        if not requested_report_id or not args.evo_child_research_org_assurance:
            raise ResearchOrganizationError(
                'BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID',
                [
                    'revision_child_report_identity_missing'
                    if not requested_report_id
                    else 'revision_child_assurance_missing'
                ],
            )
        try:
            resolution = resolve_report_scoped_web_research_plan(
                factor_workspace,
                report_id=requested_report_id,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            parent_report_id = str(resolution['parent_report_id'])
            assurance = validate_evo_child_assurance(
                workspace_root=factor_workspace,
                parent_report_id=parent_report_id,
                child_report_id=requested_report_id,
                assurance=args.evo_child_research_org_assurance,
                expected_host_trust_manifest_sha256=str(
                    args.expected_host_trust_manifest_sha256 or ''
                ),
            )
        except (EvoChildAssuranceError, WebResearchPlanError, OSError, ValueError) as exc:
            raise ResearchOrganizationError(
                'BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID',
                [f'revision_child_assurance:{exc}'],
            ) from exc
        return {
            'mode': mode,
            'status': 'validated',
            'formal_independence_verified': True,
            'runtime_assurance': 'revision_child_not_full_seven_role_org',
            'revision_child_assurance_ref': assurance['assurance_ref'],
            'parent_report_id': parent_report_id,
            'child_report_id': requested_report_id,
        }
    plan = load_research_organization_plan(factor_workspace)
    plan_identity = (
        plan.get('identity') if isinstance(plan.get('identity'), dict) else {}
    )
    plan_report_id = str(plan_identity.get('report_id') or '')
    effective_report_id = requested_report_id or plan_report_id
    if not effective_report_id or plan_report_id != effective_report_id:
        raise ResearchOrganizationError(
            'BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID',
            ['runtime_plan_report_identity_mismatch'],
        )
    runtime_state = (
        factor_workspace
        / str(plan['workspace_policy']['organization_root'])
        / 'runtime'
        / 'runtime_state.json'
    )
    runtime_entry_present = runtime_state.exists() or runtime_state.is_symlink()
    if mode == 'if-present' and not runtime_entry_present:
        return {
            'mode': mode,
            'status': 'not_present',
            'formal_independence_verified': False,
            'runtime_assurance': 'not_present',
        }
    formal = mode == 'formal-complete'
    if formal and not (
        args.research_org_runtime_private_root
        and args.research_org_runtime_trust_root
        and args.research_org_runtime_installation_id
    ):
        raise ResearchOrganizationError(
            'BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID',
            ['formal_runtime_arguments_missing'],
        )
    validation = validate_research_organization_runtime(
        workspace=factor_workspace,
        require_complete=formal,
        private_root=(
            Path(args.research_org_runtime_private_root).expanduser()
            if args.research_org_runtime_private_root
            else None
        ),
        trust_root=(
            Path(args.research_org_runtime_trust_root).expanduser()
            if args.research_org_runtime_trust_root
            else None
        ),
        installation_id=args.research_org_runtime_installation_id,
        require_formal=formal,
    )
    return {
        'mode': mode,
        'status': 'validated',
        **validation,
    }


def apply_evo_child_command_recovery(
    commands: list[tuple[str, list[str]]],
    recovery_receipt: dict[str, Any],
) -> list[tuple[str, list[str]]]:
    """Project the wrapper command list to the one Host-admitted suffix."""

    boundary = recovery_receipt.get('boundary')
    authority = recovery_receipt.get('authority')
    if not isinstance(boundary, dict) or not isinstance(authority, dict):
        raise ValueError('command_recovery_shape')
    next_command = str(boundary.get('next_command') or '')
    if (
        authority.get('exact_next_command') != next_command
        or authority.get('required_start_step')
        != boundary.get('required_start_step')
        or authority.get('oos_release_allowed') is not False
        or authority.get('scientific_verdict_issued') is not False
    ):
        raise ValueError('command_recovery_authority')
    matching = [
        index for index, (name, _command) in enumerate(commands)
        if name == next_command
    ]
    if len(matching) != 1:
        raise ValueError('command_recovery_next_command')
    return commands[matching[0]:]


def _manifest_state_path(manifest: dict[str, Any], key: str) -> Path | None:
    raw = ((manifest.get('state_reuse') or {}).get(key))
    return Path(raw).expanduser() if raw else None


def run_state_reuse_gate(
    *,
    args: argparse.Namespace,
    manifest: dict[str, Any],
    ctx,
    steps: list[str],
) -> dict[str, Any]:
    state_resolution_path = Path(args.state_resolution).expanduser() if args.state_resolution else _manifest_state_path(manifest, 'state_resolution')
    state_contract_path = Path(args.state_dependency_contract).expanduser() if args.state_dependency_contract else _manifest_state_path(manifest, 'state_dependency_contract')
    data_request_dir = Path(args.state_data_request_dir).expanduser() if args.state_data_request_dir else _manifest_state_path(manifest, 'data_request_dir')
    requires_gate = bool(args.require_state_reuse_contract or ('4' in steps and not args.dry_run))
    gate: dict[str, Any] = {
        'contract_version': 'factorforge_ultimate_state_reuse_gate_v1',
        'required': requires_gate,
        'status': 'skipped',
        'state_dependency_contract_path': str(state_contract_path) if state_contract_path else None,
        'state_catalog_path': args.state_catalog,
        'state_resolution_path': str(state_resolution_path) if state_resolution_path else None,
        'data_request_dir': str(data_request_dir) if data_request_dir else None,
    }

    if not requires_gate and not args.state_dependency_contract and not args.state_resolution and not args.state_catalog and not args.state_input_path:
        return gate

    assert_no_raw_minute_full_window_scan(
        input_paths=[str(item) for item in (args.state_input_path or [])],
        production='4' in steps,
        explicit_data_production_context=bool(args.explicit_data_production_context),
    )

    if args.state_dependency_contract or args.state_catalog:
        if not state_contract_path or not state_contract_path.exists():
            raise StateReuseBlock(BLOCK_STATE_DEPENDENCY_UNDECLARED, str(state_contract_path))
        if not args.state_catalog:
            raise StateReuseBlock(BLOCK_STATE_DEPENDENCY_UNDECLARED, '--state-catalog is required with --state-dependency-contract')
        catalog_path = Path(args.state_catalog).expanduser()
        contract = load_state_dependency_contract(state_contract_path)
        catalog = load_state_json(catalog_path)
        resolution = resolve_state_dependencies(
            contract=contract,
            catalog=catalog,
            report_id=args.report_id,
            factor_id=args.factor_id or ctx.factor_id,
            research_id=args.research_id or ctx.research_id,
            dependency_contract_path=str(state_contract_path),
            catalog_source={'type': 'local_json', 'path_or_uri': str(catalog_path)},
        )
        if not state_resolution_path:
            raise StateReuseBlock(BLOCK_STATE_DEPENDENCY_UNDECLARED, 'state_resolution path missing from runtime manifest')
        write_resolution_outputs(
            resolution=resolution,
            state_resolution_path=state_resolution_path,
            data_request_dir=data_request_dir,
        )
        gate['resolution_written'] = str(state_resolution_path)
        gate['data_request_ids'] = resolution.get('data_request_ids') or []
        if resolution.get('blocked') is True:
            token = str(resolution.get('blocker_token') or BLOCK_STATE_DEPENDENCY_UNDECLARED)
            gate['status'] = 'blocked'
            gate['blocker_token'] = token
            raise StateReuseBlock(token, f'state dependency resolution blocked: {state_resolution_path}')

    if requires_gate:
        if (
            '3' in steps
            and not args.skip_step3a
            and not args.dry_run
            and not args.state_dependency_contract
            and not args.state_catalog
            and not args.state_resolution
            and state_resolution_path
            and not state_resolution_path.exists()
        ):
            gate['status'] = 'deferred_to_step3'
            gate['state_resolution_path'] = str(state_resolution_path)
            gate['reason'] = 'Step3A is responsible for writing state dependency/no-op resolution before Step4.'
            return gate
        if (not state_resolution_path or not state_resolution_path.exists()) and (not state_contract_path or not state_contract_path.exists()):
            raise StateReuseBlock(BLOCK_STATE_DEPENDENCY_UNDECLARED, str(state_contract_path))
        if not state_resolution_path:
            raise StateReuseBlock(BLOCK_STATE_DEPENDENCY_UNDECLARED, 'state_resolution path missing from runtime manifest')
        resolution = require_state_resolution_ready(state_resolution_path)
        gate['status'] = 'passed'
        gate['reuse_hit_count'] = len(resolution.get('reuse_hits') or [])
    else:
        gate['status'] = 'checked'
    return gate


def main() -> int:
    args = parse_args()
    start = normalize_step(args.start_step, START_ALIASES)
    end = normalize_step(args.end_step, END_ALIASES)
    steps = step_slice(start, end)

    formal_workspace_steps = bool(set(steps) & {'3', '3b', '4', '5', '6'})
    factor_workspace = Path(args.factor_workspace).expanduser().resolve() if args.factor_workspace else None
    runtime_manifest_from_args: dict[str, Any] | None = None
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser()
        if manifest_path.exists():
            runtime_manifest_from_args = load_runtime_manifest(manifest_path)
            if runtime_manifest_from_args.get('contract_version') == 'factorforge_runtime_context_v2':
                raw_workspace = runtime_manifest_from_args.get('factor_workspace')
                if raw_workspace:
                    factor_workspace = Path(str(raw_workspace)).expanduser().resolve()
        elif formal_workspace_steps and not factor_workspace and not args.allow_legacy_global_runtime:
            print(BLOCK_WORKSPACE_MISSING)
            return 1
    if formal_workspace_steps and not factor_workspace:
        if args.init_factor_workspace:
            if not args.factor_id or not args.research_id:
                print(f'{BLOCK_WORKSPACE_MISSING}: --init-factor-workspace requires --factor-id and --research-id')
                return 1
            factorforge_root = Path(args.factorforge_root).expanduser().resolve() if args.factorforge_root else REPO_ROOT
            factor_workspace = default_workspace_root(
                factorforge_root=factorforge_root,
                factor_id=args.factor_id,
                research_id=args.research_id,
            )
            ws_manifest = build_workspace_manifest(
                repo_root=REPO_ROOT,
                factorforge_root=factorforge_root,
                factor_id=args.factor_id,
                research_id=args.research_id,
                root_report_id=args.report_id,
                implementation_mode='unknown',
            )
            write_workspace_manifest(workspace_manifest_path(factor_workspace), ws_manifest)
        elif not args.allow_legacy_global_runtime:
            print(BLOCK_WORKSPACE_MISSING)
            return 1
    if factor_workspace:
        ws_path = workspace_manifest_path(factor_workspace)
        if not ws_path.exists():
            print(f'BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID: missing {ws_path}')
            return 1
        ws_manifest = load_workspace_manifest(ws_path)
        failures = validate_workspace_manifest(ws_manifest)
        failures.extend(
            validate_workspace_cli_identity(
                ws_manifest,
                factor_id=args.factor_id,
                research_id=args.research_id,
            )
        )
        if failures:
            print('\n'.join(failures))
            return 1
    ctx = resolve_factorforge_context(args.factorforge_root, factor_workspace=factor_workspace)
    if ctx.factor_workspace:
        child_marker_paths = (
            ctx.active_root
            / 'objects'
            / 'research_protocol'
            / f'evo_child_materialization_ticket__{args.report_id}__authorization.json',
            ctx.active_root
            / 'objects'
            / 'research_protocol'
            / f'evo_child_materialization_ticket__{args.report_id}__ready.json',
            ctx.active_root
            / 'objects'
            / 'research_protocol'
            / f'evo_child_intent__{args.report_id}.json',
            ctx.active_root
            / 'objects'
            / 'research_iteration_master'
            / f'executable_revision_spec__{args.report_id}.json',
        )
        evo_child_execution = any(
            path.exists() or path.is_symlink() for path in child_marker_paths
        )
        if evo_child_execution and not re.fullmatch(
            r'[0-9a-f]{64}',
            str(args.expected_host_trust_manifest_sha256 or ''),
        ):
            # The external public-key pin must be supplied by the Host control
            # plane before Step3B is allowed to write anything.  Reading the
            # mutable workspace manifest here would turn a self-signed child
            # workspace into its own trust anchor.
            print(
                'BLOCK_FACTORFORGE_EVO_CHILD_EXTERNAL_HOST_TRUST_PIN_REQUIRED'
            )
            return 1
    try:
        research_organization = resolve_research_organization_gate(
            mode=str(args.research_org_mode or 'auto'),
            factor_workspace=ctx.factor_workspace,
            explicit_plan=(
                Path(args.research_org_plan).expanduser()
                if args.research_org_plan
                else None
            ),
        )
    except ResearchOrganizationError as exc:
        print(str(exc))
        return 1
    try:
        research_organization_runtime = resolve_research_organization_runtime_gate(
            args=args,
            factor_workspace=ctx.factor_workspace,
        )
    except ResearchOrganizationError as exc:
        print(str(exc))
        return 1
    legacy_protocol_smoke = bool(
        args.allow_legacy_research_protocol_smoke
        and (
            str(ctx.active_root).startswith('/tmp/')
            or str(ctx.active_root).startswith('/private/tmp/')
        )
        and ('SMOKE' in args.report_id or args.report_id.startswith('STEP6_INTEL_'))
    )
    if args.allow_legacy_research_protocol_smoke and not legacy_protocol_smoke:
        print('BLOCK_FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE_SCOPE_INVALID')
        return 1
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser()
        manifest = runtime_manifest_from_args if runtime_manifest_from_args else ctx.build_manifest(args.report_id, branch_id=args.branch_id)
    else:
        manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
        if ctx.factor_workspace:
            manifest_path = (
                ctx.objects_root
                / 'runtime_context'
                / f'factorforge_runtime_manifest__{args.report_id}.json'
            )
        else:
            manifest_path = Path(tempfile.gettempdir()) / f'factorforge_runtime_manifest__{args.report_id}__{os.getpid()}.json'
        write_json_atomic(manifest_path, manifest)

    if args.proof_output:
        proof_path = Path(args.proof_output).expanduser().resolve(
            strict=False
        )
    elif ctx.factor_workspace:
        proof_path = (
            ctx.objects_root
            / 'runtime_context'
            / f'ultimate_run_report__{args.report_id}.json'
        )
    elif args.dry_run:
        proof_path = Path(tempfile.gettempdir()) / f'ultimate_run_report__{args.report_id}.json'
    else:
        proof_path = ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{args.report_id}.json'
    if ctx.factor_workspace:
        active_root = ctx.active_root.resolve(strict=False)
        resolved_proof = proof_path.resolve(strict=False)
        if (
            resolved_proof != active_root
            and active_root not in resolved_proof.parents
        ):
            print(
                f'{BLOCK_OUTPUT_OUTSIDE_WORKSPACE}: '
                f'proof_output={resolved_proof}'
            )
            return 1
        proof_path = resolved_proof
    env, host_private_oos_raw = capture_host_control_environment(
        dict(os.environ)
    )
    host_private_proof_values = host_private_proof_denied_values(
        args,
        host_private_oos_raw,
    )
    host_private_oos_env = {
        key: value for key, value in host_private_oos_raw.items() if value
    }
    incident_host_env = {
        key: host_private_oos_raw[key]
        for key in (OOS_HOST_TRUST_ROOT_ENV, OOS_HOST_INSTALLATION_ID_ENV)
        if host_private_oos_raw[key]
    }
    container_host_env = {
        key: host_private_oos_raw[key]
        for key in (
            EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
            EVO_CHILD_CONTAINER_JOB_ID_ENV,
        )
        if host_private_oos_raw[key]
    }
    if len(incident_host_env) not in {0, 2} or len(container_host_env) not in {0, 2}:
        print('BLOCK_FACTORFORGE_WEB_OOS_HOST_FINALIZER_CREDENTIALS_PARTIAL')
        return 1
    if not args.dry_run and len(incident_host_env) != 2:
        print('BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_REQUIRED')
        return 1
    runtime_incident_pair_present = bool(
        args.research_org_runtime_trust_root
        or args.research_org_runtime_installation_id
    )
    runtime_incident_pair_complete = bool(
        args.research_org_runtime_trust_root
        and args.research_org_runtime_installation_id
    )
    if (
        not args.dry_run
        and runtime_incident_pair_present
        and (
            not runtime_incident_pair_complete
            or Path(args.research_org_runtime_trust_root).expanduser().resolve(
                strict=False
            )
            != Path(incident_host_env[OOS_HOST_TRUST_ROOT_ENV])
            .expanduser()
            .resolve(strict=False)
            or args.research_org_runtime_installation_id
            != incident_host_env[OOS_HOST_INSTALLATION_ID_ENV]
        )
    ):
        print('BLOCK_FACTORFORGE_OOS_INCIDENT_RUNTIME_TRUST_CONTEXT_MISMATCH')
        return 1
    if container_host_env and len(host_private_oos_env) != 4:
        print('BLOCK_FACTORFORGE_WEB_OOS_HOST_FINALIZER_CREDENTIALS_PARTIAL')
        return 1
    host_private_oos_locator_ready = len(host_private_oos_env) == 4
    if incident_host_env and ctx.factor_workspace:
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=ctx.factor_workspace,
            report_id=args.report_id,
            trust_root=Path(incident_host_env[OOS_HOST_TRUST_ROOT_ENV]),
            installation_id=incident_host_env[OOS_HOST_INSTALLATION_ID_ENV],
        )
        if incident_reasons:
            print(';'.join(incident_reasons))
            return 1
    env.pop('FACTORFORGE_ALLOW_DIRECT_STEP', None)
    env.pop('FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF', None)
    env['FACTORFORGE_ROOT'] = str(ctx.active_root)
    env['FACTORFORGE_SHARED_FACTORFORGE_ROOT'] = str(ctx.factorforge_root)
    if ctx.factor_workspace:
        env['FACTORFORGE_FACTOR_WORKSPACE'] = str(ctx.factor_workspace)
        env['FACTORFORGE_FACTOR_WORKSPACE_MANIFEST'] = str(ctx.factor_workspace_manifest or (ctx.factor_workspace / 'manifest.json'))
        if research_organization.get('status') == 'validated':
            env['FACTORFORGE_RESEARCH_ORG_PLAN'] = str(
                research_organization['plan_path']
            )
        if research_organization_runtime.get('status') == 'validated':
            env['FACTORFORGE_RESEARCH_ORG_RUNTIME_ID'] = str(
                research_organization_runtime['runtime_id']
            )
        web_catalog_summary = ctx.factor_workspace / 'identity' / 'data_catalog_summary.json'
        if web_catalog_summary.exists() or web_catalog_summary.is_symlink():
            try:
                approved_catalog, _approved_catalog_hash = resolve_workspace_approved_catalog(
                    ctx.factor_workspace,
                    environ=env,
                )
            except WebResearchPlanError as exc:
                print(str(exc))
                return 1
            env['FACTORFORGE_STATE_CATALOG'] = str(approved_catalog)
            env['FACTORFORGE_DATA_CATALOG'] = str(approved_catalog)
        else:
            env.setdefault('FACTORFORGE_DATA_CATALOG', str(ctx.factorforge_root / 'data' / 'catalog' / 'data_catalog.json'))
    env['FACTORFORGE_ULTIMATE_RUN'] = '1'
    if legacy_protocol_smoke:
        env['FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE'] = '1'

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
    if (
        web_evo_action != 'LEGACY_WEB_EXECUTION'
        and args.apply_approved_revision
    ):
        print('BLOCK_FACTORFORGE_EVO_V2_PARENT_REVISION_APPLICATION_FORBIDDEN')
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

    py = sys.executable
    commands: list[tuple[str, list[str]]] = []
    runtime_dispatch = args.runtime_dispatch
    if runtime_dispatch is None:
        runtime_dispatch = 'manual_file' if args.agentic_dispatch_adapter == 'manual_file' else 'unknown'
    taskbook_runtime_args = ['--runtime-dispatch', runtime_dispatch]
    taskbook_protocol_mode = 'off' if legacy_protocol_smoke else 'required'
    if args.subagent_provider:
        taskbook_runtime_args.extend(['--subagent-provider', args.subagent_provider])
    if args.subagent_model:
        taskbook_runtime_args.extend(['--subagent-model', args.subagent_model])

    if args.apply_approved_revision and not web_evo_wait_only:
        commands.append(('apply_approved_step6_revision', [py, 'skills/factor-forge-step6/scripts/apply_step6_iteration.py', '--manifest', str(manifest_path)]))

    if web_evo_wait_only:
        pass
    elif '2' in steps:
        commands.append(('run_step2', [py, 'skills/factor-forge-step2/scripts/run_step2.py', '--report-id', args.report_id]))
        commands.append(('validate_step2', [py, 'skills/factor-forge-step2/scripts/validate_step2.py', '--report-id', args.report_id]))
        if '6' in steps and not legacy_protocol_smoke:
            commands.append(
                (
                    'validate_research_protocol_pre_council',
                    [
                        py,
                        'scripts/validate_factorforge_research_protocol.py',
                        '--workspace-root',
                        str(ctx.active_root),
                        '--report-id',
                        args.report_id,
                        '--stage',
                        'pre_council',
                    ],
                )
            )
    elif '6' in steps and not legacy_protocol_smoke:
        commands.append(
            (
                'validate_research_protocol_pre_council',
                [
                    py,
                    'scripts/validate_factorforge_research_protocol.py',
                    '--workspace-root',
                    str(ctx.active_root),
                    '--report-id',
                    args.report_id,
                    '--stage',
                    'pre_council',
                ],
            )
        )

    if '3' in steps and not args.skip_step3a:
        commands.append(('run_step3', [py, 'skills/factor-forge-step3/scripts/run_step3.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3', [py, 'skills/factor-forge-step3/scripts/validate_step3.py', '--manifest', str(manifest_path)]))

    if '3b' in steps or ('3' in steps):
        commands.append(('run_step3b', [py, 'skills/factor-forge-step3/scripts/run_step3b.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3b', [py, 'skills/factor-forge-step3/scripts/validate_step3b.py', '--manifest', str(manifest_path)]))

    if '4' in steps:
        if isinstance(web_evo_gate, dict) and web_evo_gate.get('enabled') is True:
            trusted_prefetch_command = [
                py,
                'skills/factor-forge-step4/scripts/run_step4.py',
                '--manifest',
                str(manifest_path),
                '--trusted-data-prefetch-only',
            ]
            if args.expected_host_trust_manifest_sha256:
                trusted_prefetch_command.extend(
                    [
                        '--expected-host-trust-manifest-sha256',
                        args.expected_host_trust_manifest_sha256,
                    ]
                )
            commands.append(
                ('materialize_evo_pre_release_data', trusted_prefetch_command)
            )
        run_step4_command = [
            py,
            'skills/factor-forge-step4/scripts/run_step4.py',
            '--manifest',
            str(manifest_path),
        ]
        if args.expected_host_trust_manifest_sha256:
            run_step4_command.extend(
                [
                    '--expected-host-trust-manifest-sha256',
                    args.expected_host_trust_manifest_sha256,
                ]
            )
        commands.append(('run_step4', run_step4_command))
        validate_step4_command = [py, 'skills/factor-forge-step4/scripts/validate_step4.py', '--report-id', args.report_id]
        if args.expected_host_trust_manifest_sha256:
            validate_step4_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
        commands.append(('validate_step4', validate_step4_command))
        if web_materialization is not None and not web_evo_checkpoint_pass:
            web_factor_proof_args = [
                py,
                'scripts/finalize_factorforge_web_factor_proof.py',
                '--workspace-root',
                str(ctx.active_root),
                '--report-id',
                args.report_id,
                '--plan-path',
                str(web_plan_path),
            ]
            if args.expected_host_trust_manifest_sha256:
                web_factor_proof_args.extend(
                    [
                        '--expected-host-trust-manifest-sha256',
                        args.expected_host_trust_manifest_sha256,
                    ]
                )
            commands.append(
                (
                    'finalize_web_factor_proof',
                    web_factor_proof_args,
                )
            )
        if web_materialization is not None and web_evo_checkpoint_pass:
            web_checkpoint_args = [
                py,
                'scripts/materialize_factorforge_web_evo_is_checkpoint.py',
                '--workspace-root',
                str(ctx.active_root),
                '--report-id',
                args.report_id,
                '--plan-path',
                str(web_plan_path),
            ]
            if incident_host_env:
                web_checkpoint_args.extend(
                    [
                        '--host-trust-root',
                        incident_host_env[OOS_HOST_TRUST_ROOT_ENV],
                        '--installation-id',
                        incident_host_env[OOS_HOST_INSTALLATION_ID_ENV],
                    ]
                )
            if args.expected_host_trust_manifest_sha256:
                web_checkpoint_args.extend(
                    [
                        '--expected-host-trust-manifest-sha256',
                        args.expected_host_trust_manifest_sha256,
                    ]
                )
            commands.append(
                (
                    'materialize_web_evo_purged_is_checkpoint',
                    web_checkpoint_args,
                )
            )

    if web_evo_oos_release_pass and web_materialization is not None:
        web_factor_proof_args = [
            py,
            'scripts/finalize_factorforge_web_factor_proof.py',
            '--workspace-root',
            str(ctx.active_root),
            '--report-id',
            args.report_id,
            '--plan-path',
            str(web_plan_path),
        ]
        if args.expected_host_trust_manifest_sha256:
            web_factor_proof_args.extend(
                [
                    '--expected-host-trust-manifest-sha256',
                    args.expected_host_trust_manifest_sha256,
                ]
            )
        if web_completed_finalization_replay:
            pass
        elif host_private_oos_locator_ready:
            web_factor_proof_args.append('--resolve-host-private-oos')
        else:
            web_factor_proof_args.extend(
                ['--sealed-oos-carrier', args.sealed_oos_carrier]
            )
            web_factor_proof_args.extend(
                ['--sealed-oos-private-root', args.sealed_oos_private_root]
            )
        for visible_root in args.sealed_oos_agent_visible_root:
            web_factor_proof_args.extend(
                ['--sealed-oos-agent-visible-root', visible_root]
            )
        commands.append(
            (
                'finalize_web_factor_proof',
                web_factor_proof_args,
            )
        )
        run_step5_command = [py, 'skills/factor-forge-step5/scripts/run_step5.py', '--manifest', str(manifest_path)]
        validate_step5_command = [py, 'skills/factor-forge-step5/scripts/validate_step5.py', '--report-id', args.report_id]
        if args.expected_host_trust_manifest_sha256:
            run_step5_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
            validate_step5_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
        commands.append(('run_step5', run_step5_command))
        commands.append(('validate_step5', validate_step5_command))
    elif '5' in steps and not web_evo_checkpoint_pass:
        run_step5_command = [py, 'skills/factor-forge-step5/scripts/run_step5.py', '--manifest', str(manifest_path)]
        validate_step5_command = [py, 'skills/factor-forge-step5/scripts/validate_step5.py', '--report-id', args.report_id]
        if args.expected_host_trust_manifest_sha256:
            run_step5_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
            validate_step5_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
        commands.append(('run_step5', run_step5_command))
        commands.append(('validate_step5', validate_step5_command))

    if '6' in steps and not web_evo_checkpoint_pass and not web_evo_wait_only:
        if not args.skip_researcher_packets:
            commands.append(('build_researcher_dossier', [py, 'skills/factor-forge-researcher/scripts/build_researcher_dossier.py', '--report-id', args.report_id]))
            commands.append(('build_step6_researcher_packet', [py, 'skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py', '--report-id', args.report_id]))
        run_step6_command = [py, 'skills/factor-forge-step6/scripts/run_step6.py', '--manifest', str(manifest_path)]
        validate_step6_command = [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]
        if args.expected_host_trust_manifest_sha256:
            run_step6_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
            validate_step6_command.extend(['--expected-host-trust-manifest-sha256', args.expected_host_trust_manifest_sha256])
        commands.append(('run_step6', run_step6_command))
        commands.append(('validate_step6', validate_step6_command))

    if web_command_recovery is not None:
        try:
            commands = apply_evo_child_command_recovery(
                commands, web_command_recovery
            )
        except ValueError:
            print('BLOCK_FACTORFORGE_EVO_CHILD_COMMAND_RECOVERY_INVALID')
            return 1

    if (
        web_oos_recovery['recovery_required']
        or web_validate_step4_finalizer_recovery
    ):
        # Once any OOS artifact exists, a crash/retry may never return to an
        # Agent-authored phase.  The start-step=6 value is a resume sentinel;
        # this exact projection is Host finalizer-only and the existing
        # post-OOS branch below performs the trusted terminal closure.
        recovery_finalizer = [
            py,
            'scripts/finalize_factorforge_web_factor_proof.py',
            '--workspace-root',
            str(ctx.active_root),
            '--report-id',
            args.report_id,
            '--plan-path',
            str(web_plan_path),
        ]
        if args.expected_host_trust_manifest_sha256:
            recovery_finalizer.extend(
                [
                    '--expected-host-trust-manifest-sha256',
                    args.expected_host_trust_manifest_sha256,
                ]
            )
        if web_completed_finalization_replay:
            pass
        elif host_private_oos_locator_ready:
            recovery_finalizer.append('--resolve-host-private-oos')
        elif args.sealed_oos_carrier:
            recovery_finalizer.extend(
                ['--sealed-oos-carrier', args.sealed_oos_carrier]
            )
        if not host_private_oos_locator_ready and args.sealed_oos_private_root:
            recovery_finalizer.extend(
                ['--sealed-oos-private-root', args.sealed_oos_private_root]
            )
        for visible_root in args.sealed_oos_agent_visible_root:
            recovery_finalizer.extend(
                ['--sealed-oos-agent-visible-root', visible_root]
            )
        commands = [('finalize_web_factor_proof', recovery_finalizer)]

    prior_proof_archive: str | None = None
    if web_resume_start_step and proof_path.exists():
        prior_digest = sha256_file(proof_path)
        archive_path = proof_path.with_name(
            f'{proof_path.stem}__prior_{prior_digest[:12]}{proof_path.suffix}'
        )
        counter = 1
        while archive_path.exists() or archive_path.is_symlink():
            archive_path = proof_path.with_name(
                f'{proof_path.stem}__prior_{prior_digest[:12]}_{counter}{proof_path.suffix}'
            )
            counter += 1
        os.replace(proof_path, archive_path)
        prior_proof_archive = str(archive_path)

    agent_execution_container_proof: dict[str, Any] = {
        'required': bool(web_is_evo_child and not args.dry_run),
        'status': (
            'VALIDATED'
            if agent_execution_container_resolution is not None
            else 'DRY_RUN_NOT_EXECUTED'
            if web_is_evo_child and args.dry_run
            else 'NOT_APPLICABLE'
        ),
        'admission_ref': None,
        'allowed_stages': sorted(EVO_CHILD_AGENT_STAGE_NAMES),
        'factor_verdict': 'NOT_ISSUED',
    }
    if agent_execution_container_resolution is not None:
        admitted = agent_execution_container_resolution['admission']
        agent_execution_container_proof['admission_ref'] = {
            'receipt_id': admitted['receipt_id'],
            'content_sha256': admitted['content_sha256'],
            'status': admitted['status'],
            'image_digest': admitted['container']['image_digest'],
        }

    proof: dict[str, Any] = {
        'contract_version': 'factorforge_ultimate_wrapper_v1',
        'report_id': args.report_id,
        'factor_id': ctx.factor_id,
        'research_id': ctx.research_id,
        'started_at_utc': utc_now(),
        'finished_at_utc': None,
        'factorforge_root': str(ctx.factorforge_root),
        'active_root': str(ctx.active_root),
        'factor_workspace': str(ctx.factor_workspace) if ctx.factor_workspace else None,
        'research_organization': research_organization,
        'research_organization_runtime': research_organization_runtime,
        'repo_root': str(ctx.repo_root),
        'manifest_path': str(manifest_path),
        'start_step': start,
        'end_step': end,
        'requested_steps': steps,
        'dry_run': bool(args.dry_run),
        'contract_smoke_only': bool(legacy_protocol_smoke),
        'formal_proof_eligible': False,
        'status': 'RUNNING',
        'commands': [],
        'evo_child_agent_execution_container': agent_execution_container_proof,
        'formal_command_contract': {
            'required_command_names': [name for name, _ in commands],
            'research_protocol_verifier_required': (
                '6' in steps and not legacy_protocol_smoke
            ),
            'research_protocol_verifier_name': (
                'validate_research_protocol_pre_council'
            ),
            'all_commands_must_execute_and_pass': True,
            'satisfied': False,
        },
        'child_env_policy': {
            'FACTORFORGE_ULTIMATE_RUN': '1',
            'removed': ['FACTORFORGE_ALLOW_DIRECT_STEP', 'FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF'],
            'host_control_only': [
                OOS_HOST_TRUST_ROOT_ENV,
                OOS_HOST_INSTALLATION_ID_ENV,
                EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
                EVO_CHILD_CONTAINER_JOB_ID_ENV,
            ],
        },
        'expected_artifacts_before': collect_expected_artifacts(manifest),
        'expected_artifacts_after': {},
        'step3b_mode_decision': collect_step3b_mode_decision(manifest),
        'runtime_manifest_refreshes': [],
        'revision_council': {'requested_mode': args.council_mode, 'auto_council_policy': args.auto_council_policy, 'executor': args.agentic_council_executor, 'dispatch_adapter': args.agentic_dispatch_adapter, 'runtime_dispatch': runtime_dispatch, 'status': 'skipped', 'reason': 'disabled'} if args.council_mode == 'off' else {'requested_mode': args.council_mode, 'auto_council_policy': args.auto_council_policy, 'executor': args.agentic_council_executor, 'dispatch_adapter': args.agentic_dispatch_adapter, 'runtime_dispatch': runtime_dispatch, 'subagent_provider': args.subagent_provider, 'subagent_model': args.subagent_model, 'status': 'pending'},
        'state_reuse_gate': None,
        'research_loop_policy': {
            'policy': args.research_loop_policy,
            'max_council_loops': args.max_council_loops,
            'council_primary_default': args.council_mode != 'off',
            'stop_conditions': [
                'promote_official',
                'council_final_no_material_improvement_path',
                'max_council_loops_reached',
                'evidence_or_case_prewrite_block',
            ],
            'note': 'Current wrapper runs one formal Step2-6 pass plus Council attachment/dispatch. Subsequent approved revision loops must be launched as child report ids through the guarded revision/search contracts.',
        },
        'failure': None,
        'web_research_preflight': web_materialization,
        'evo_v2_execution_gate': web_evo_gate,
        'web_resume_start_step': web_resume_start_step,
        'web_oos_recovery': web_oos_recovery,
        'evo_child_command_recovery': (
            {
                'receipt_id': web_command_recovery['receipt_id'],
                'boundary': web_command_recovery['boundary'],
            }
            if web_command_recovery is not None
            else None
        ),
        'prior_proof_archive': prior_proof_archive,
        'usage_rule': 'This proof report is the only acceptable evidence for a claimed factor-forge-ultimate run. Agents must not replace formal Step4/5/6 execution by ad-hoc metrics or post-hoc object writing.',
    }
    try:
        proof['state_reuse_gate'] = run_state_reuse_gate(args=args, manifest=manifest, ctx=ctx, steps=steps)
        if isinstance(proof.get('state_reuse_gate'), dict):
            state_resolution_for_child = proof['state_reuse_gate'].get('state_resolution_path')
            if state_resolution_for_child:
                env['FACTORFORGE_STATE_RESOLUTION'] = str(state_resolution_for_child)
            if proof['state_reuse_gate'].get('required') is True:
                env['FACTORFORGE_REQUIRE_STATE_REUSE_CONTRACT'] = '1'
    except StateReuseBlock as exc:
        proof['state_reuse_gate'] = {
            'contract_version': 'factorforge_ultimate_state_reuse_gate_v1',
            'status': 'blocked',
            'blocker_token': exc.token,
            'message': str(exc),
        }
        proof['status'] = 'FAIL'
        proof['failure'] = {'command': 'state_reuse_gate', 'returncode': 1, 'token': exc.token}
        proof['finished_at_utc'] = utc_now()
        write_json_atomic(proof_path, proof)
        print(exc.token)
        print(f'[PROOF] {proof_path}')
        return 1
    write_json_atomic(proof_path, proof)

    def refresh_runtime_manifest_for_command(command_name: str) -> None:
        nonlocal manifest
        if args.manifest or args.dry_run:
            return
        if command_name not in {
            'run_step3',
            'validate_step3',
            'run_step3b',
            'validate_step3b',
            'run_step4',
            'run_step5',
            'run_step6',
        }:
            return
        manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
        write_json_atomic(manifest_path, manifest)
        refresh = {
            'command': command_name,
            'manifest_path': str(manifest_path),
            'refreshed_at_utc': utc_now(),
            'manifest_identity': manifest.get('manifest_identity') or {},
        }
        proof.setdefault('runtime_manifest_refreshes', []).append(refresh)
        proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
        proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
        write_json_atomic(proof_path, proof)

    # A Web EVO parent cannot know whether Council execution is needed until
    # the signed post-Step4 lifecycle is read.  Enforce the legacy agentic
    # executor gate only when we are actually outside that resumable EVO gate;
    # the QUALIFIED branch below owns its stricter dispatch-only policy.
    if args.council_mode == 'agentic' and not (
        isinstance(web_evo_gate, dict) and web_evo_gate.get('enabled') is True
    ):
        if args.agentic_council_executor == 'none':
            token = 'BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED'
            proof['revision_council'] = {
                'requested_mode': 'agentic',
                'executor': 'none',
                'runtime_dispatch': runtime_dispatch,
                'status': 'blocked',
                'block_reason': token,
            }
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': 'revision_council_agentic_executor', 'returncode': 1, 'token': token}
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(token)
            print(f'[PROOF] {proof_path}')
            return 1
        if args.agentic_council_executor == 'real_agent':
            token = 'BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED'
            proof['revision_council'] = {
                'requested_mode': 'agentic',
                'executor': 'real_agent',
                'runtime_dispatch': runtime_dispatch,
                'status': 'blocked',
                'block_reason': token,
            }
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': 'revision_council_real_agent', 'returncode': 1, 'token': token}
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(token)
            print(f'[PROOF] {proof_path}')
            return 1
        if args.agentic_council_executor == 'dispatch_manifest' and args.agentic_dispatch_adapter in {'openclaw', 'codex', 'remote_api'}:
            token = 'BLOCK_AGENTIC_COUNCIL_DISPATCH_ADAPTER_NOT_IMPLEMENTED'
            proof['revision_council'] = {
                'requested_mode': 'agentic',
                'executor': 'dispatch_manifest',
                'dispatch_adapter': args.agentic_dispatch_adapter,
                'runtime_dispatch': runtime_dispatch,
                'status': 'blocked',
                'block_reason': token,
            }
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': 'revision_council_dispatch_adapter', 'returncode': 1, 'token': token}
            proof['finished_at_utc'] = utc_now()
            write_json_atomic(proof_path, proof)
            print(token)
            print(f'[PROOF] {proof_path}')
            return 1

    for name, command in commands:
        refresh_runtime_manifest_for_command(name)
        command_env, _host_private_finalizer_injected = (
            command_environment_for_host_controls(
                name=name,
                base_env=env,
                incident_host_env=incident_host_env,
                container_host_env=container_host_env,
                web_secure_child_oos=web_secure_child_oos,
            )
        )
        result: CommandResult | None = None
        termination_ref: dict[str, Any] | None = None
        if name in EVO_CHILD_AGENT_STAGE_NAMES:
            command_env = evo_agent_execution_env(env)
            if web_is_evo_child and not args.dry_run:
                try:
                    result, termination_ref = run_evo_child_container_command(
                        admission_path=str(
                            args.agent_execution_container_admission
                        ),
                        name=name,
                        command=command,
                        env=command_env,
                        trust_root=host_private_oos_raw[
                            OOS_HOST_TRUST_ROOT_ENV
                        ],
                        installation_id=host_private_oos_raw[
                            OOS_HOST_INSTALLATION_ID_ENV
                        ],
                        repo_root=Path(
                            agent_execution_container_resolution['admission'][
                                'roots'
                            ]['engine_root']
                        ),
                    )
                except (
                    EvoChildContainerError,
                    KeyError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    now = utc_now()
                    result = CommandResult(
                        name=name,
                        command=command,
                        cwd=str(ctx.repo_root),
                        started_at_utc=now,
                        finished_at_utc=now,
                        returncode=1,
                        stderr_tail=(
                            'BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_EXECUTION_FAILED'
                        ),
                        status='FAIL',
                    )
        if result is None:
            result = run_command(
                name,
                command,
                cwd=ctx.repo_root,
                env=command_env,
                dry_run=args.dry_run,
            )
        # Host controls are never public proof material.  Redact every command
        # projection, not only the finalizer, because Host checkpoint commands
        # also carry the incident authority pair in argv.
        command_proof = public_command_proof(
            result,
            denied_values=host_private_proof_values,
        )
        if termination_ref is not None:
            command_proof['evo_child_container_termination_ref'] = (
                termination_ref
            )
        proof['commands'].append(command_proof)
        proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
        proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
        proof['finished_at_utc'] = utc_now()
        if result.returncode != 0:
            output = (result.stdout_tail or '') + '\n' + (result.stderr_tail or '')
            if web_evo_oos_release_pass:
                # Step4 has already consumed the original sealed OOS.  Even a
                # later Step5/6 failure must not leave an executable revision
                # handoff behind or rely on the success-only guard below.
                post_oos_failure_guard = enforce_evo_post_oos_no_revision(
                    ctx.active_root,
                    args.report_id,
                )
                proof['post_oos_revision_guard_on_command_failure'] = (
                    post_oos_failure_guard
                )
                if post_oos_failure_guard['status'] != 'SAFE_NO_REVISION':
                    token = (
                        'BLOCK_FACTORFORGE_EVO_V2_CONSUMED_OOS_REVISION_HANDOFF'
                    )
                    proof['status'] = 'FAIL'
                    proof['formal_proof_eligible'] = False
                    proof['failure'] = {
                        'command': name,
                        'returncode': result.returncode,
                        'token': token,
                        'primary_command_failure_preserved': True,
                    }
                    proof['revision_council'] = {
                        'requested_mode': args.council_mode,
                        'status': 'blocked',
                        'reason': 'consumed_oos_cannot_authorize_revision',
                        'post_oos_revision_guard': post_oos_failure_guard,
                    }
                    proof['finished_at_utc'] = utc_now()
                    write_json_atomic(proof_path, proof)
                    print(token)
                    print(f'[PROOF] {proof_path}')
                    return 1
            mechanism_pause_token = next(
                (
                    token
                    for token in (
                        'AWAITING_MAIN_AGENT_MECHANISM_MANUAL_REVIEW',
                        'AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION',
                        'AWAITING_MAIN_AGENT_MECHANISM_MEMO',
                    )
                    if token in output
                ),
                '',
            )
            if name == 'run_step6' and mechanism_pause_token:
                proof['status'] = 'PAUSED'
                proof['main_agent_mechanism_memo'] = summarize_main_agent_memo_pause(ctx.active_root, args.report_id)
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'status': 'not_reached',
                    'reason': 'awaiting_main_agent_mechanism_memo',
                }
                proof['failure'] = None
                proof['finished_at_utc'] = utc_now()
                write_json_atomic(proof_path, proof)
                print(mechanism_pause_token)
                print(f'[PROOF] {proof_path}')
                return 0
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': name, 'returncode': result.returncode}
            if is_transient_data_transport_failure(output):
                proof['status'] = 'BLOCK_RUNTIME_TRANSPORT'
                proof['failure']['block_class'] = 'transient_data_transport'
            data_request_candidate = data_request_candidate_from_failure(
                report_id=args.report_id,
                command_name=name,
                output=output,
                ctx=ctx,
            )
            if data_request_candidate:
                proof['data_request'] = write_data_request_candidate(data_request_candidate, repo_root=ctx.repo_root, ctx=ctx)
                proof['status'] = 'BLOCK_DATA_REQUEST_PENDING'
                proof['failure']['data_request_id'] = proof['data_request']['request_id']
                proof['failure']['block_class'] = 'data_request_pending'
            write_json_atomic(proof_path, proof)
            print(f'[FAIL] {name} rc={result.returncode}')
            if proof.get('data_request'):
                print(f"[DATA_REQUEST] {proof['data_request']['request_id']}")
            print(f'[PROOF] {proof_path}')
            return int(result.returncode or 1)
        write_json_atomic(proof_path, proof)

    if (
        not args.dry_run
        and isinstance(web_evo_gate, dict)
        and web_evo_gate.get('enabled') is True
        and web_evo_action != 'RELEASE_ORIGINAL_CANDIDATE_OOS'
    ):
        if web_plan is None:
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
                plan=web_plan,
                oos_release_token_hash=web_oos_release_token_hash,
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

    if (
        '6' in steps
        and args.council_mode != 'off'
        and not web_evo_oos_release_pass
    ):
        if args.dry_run:
            proof['revision_council'] = {
                'requested_mode': args.council_mode,
                'status': 'not_triggered',
                'reason': 'dry_run',
            }
            write_json_atomic(proof_path, proof)
        else:
            agentic_dispatch_finalizing = False
            iteration_path = ctx.objects_root / 'research_iteration_master' / f'research_iteration_master__{args.report_id}.json'
            iteration = load_json_if_exists(iteration_path)
            should_run = False
            trigger_reason = 'no_revision_needed'
            effective_mode = None
            if args.council_mode == 'auto':
                should_run, trigger_reason = council_auto_trigger(iteration)
                if should_run:
                    if args.auto_council_policy == 'dispatch_manifest':
                        effective_mode = 'agentic_dispatch_manifest'
                    elif args.auto_council_policy == 'scaffold':
                        effective_mode = 'scaffold'
                        trigger_reason = f'{trigger_reason}:auto_scaffold_policy'
                    else:
                        token = 'BLOCK_REVISION_COUNCIL_AGENTIC_REQUIRED'
                        proof['revision_council'] = {
                            'requested_mode': args.council_mode,
                            'auto_council_policy': args.auto_council_policy,
                            'effective_mode': 'none',
                            'status': 'blocked',
                            'formal_council_status': 'blocked',
                            'block_reason': token,
                            'trigger_reason': trigger_reason,
                            'deterministic_scaffold_used': False,
                            'deterministic_scaffold_formal': False,
                            'agentic_required_for_formal_research': True,
                        }
                        proof['status'] = 'FAIL'
                        proof['failure'] = {'command': 'revision_council_auto_policy', 'returncode': 1, 'token': token}
                        proof['finished_at_utc'] = utc_now()
                        write_json_atomic(proof_path, proof)
                        print(token)
                        print(f'[PROOF] {proof_path}')
                        return 1
            elif args.council_mode == 'scaffold':
                if council_blocked_by_evidence(iteration):
                    should_run = False
                    trigger_reason = 'evidence_or_case_blocked'
                else:
                    should_run = True
                    trigger_reason = 'explicit_scaffold'
                    effective_mode = 'scaffold'
            elif args.council_mode == 'agentic':
                if council_blocked_by_evidence(iteration):
                    should_run = False
                    trigger_reason = 'evidence_or_case_blocked'
                else:
                    should_run = True
                    if args.agentic_council_executor == 'dispatch_manifest':
                        trigger_reason = 'explicit_agentic_dispatch_manifest'
                        effective_mode = 'agentic_dispatch_manifest'
                    else:
                        trigger_reason = 'explicit_agentic_local_mock'
                        effective_mode = 'agentic_contract_mock'

            if not should_run:
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'auto_council_policy': args.auto_council_policy,
                    'effective_mode': 'none',
                    'status': 'not_triggered',
                    'formal_council_status': 'not_triggered',
                    'reason': trigger_reason,
                    'deterministic_scaffold_used': False,
                    'deterministic_scaffold_formal': False,
                    'agentic_required_for_formal_research': args.council_mode == 'auto',
                }
                write_json_atomic(proof_path, proof)
            else:
                council_root = ctx.active_root
                provisional_handoff_policy = disable_provisional_step3b_handoff_for_council(council_root, args.report_id)
                side_effect_before = council_side_effect_snapshot(council_root, args.report_id, clean_data_root=ctx.clean_data_root)
                if effective_mode in {'agentic_dispatch_manifest', 'agentic_contract_mock'}:
                    council_dir = (
                        council_root
                        / 'objects'
                        / 'research_iteration_master'
                        / 'revision_council'
                        / args.report_id
                    )
                    existing_dispatch_manifest = (
                        council_dir / f'dispatch_manifest__{args.report_id}.json'
                    )
                    if effective_mode == 'agentic_dispatch_manifest':
                        if existing_dispatch_manifest.exists():
                            agentic_dispatch_finalizing = (
                                agentic_dispatch_required_results_present(
                                    council_root,
                                    args.report_id,
                                )
                            )
                            if agentic_dispatch_finalizing:
                                council_commands = [
                                    ('validate_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id]),
                                    ('collect_agentic_council_results', [py, 'skills/factor-forge-step6/scripts/collect_agentic_council_results.py', '--report-id', args.report_id]),
                                    ('finalize_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/finalize_agentic_council_dispatch.py', '--report-id', args.report_id]),
                                ]
                            else:
                                council_commands = [
                                    ('validate_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id]),
                                ]
                        else:
                            council_commands = [
                                ('build_revision_council_packet', [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id]),
                                ('build_agentic_council_taskbook', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py', '--report-id', args.report_id, '--executor', 'dispatch_manifest', '--research-protocol', taskbook_protocol_mode, *taskbook_runtime_args]),
                                ('build_agentic_council_dispatch_manifest', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py', '--report-id', args.report_id]),
                                ('validate_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id]),
                            ]
                        if (
                            args.agentic_dispatch_adapter == 'manual_file'
                            and not existing_dispatch_manifest.exists()
                        ):
                            council_commands.extend(
                                [
                                    ('build_agentic_council_manual_dispatch_bundle', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_manual_dispatch_bundle.py', '--report-id', args.report_id]),
                                    ('validate_agentic_council_manual_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_manual_dispatch.py', '--report-id', args.report_id]),
                                    ('update_agentic_council_dispatch_status', [py, 'skills/factor-forge-step6/scripts/update_agentic_council_dispatch_status.py', '--report-id', args.report_id]),
                                ]
                            )
                    else:
                        council_commands = []
                        if not existing_dispatch_manifest.exists():
                            council_commands.extend(
                                [
                                    ('build_revision_council_packet', [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id]),
                                    ('build_agentic_council_taskbook', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py', '--report-id', args.report_id, '--executor', 'local_mock', '--research-protocol', taskbook_protocol_mode, *taskbook_runtime_args]),
                                    ('build_agentic_council_dispatch_manifest', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py', '--report-id', args.report_id]),
                                ]
                            )
                        council_commands.append(
                            ('validate_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id])
                        )
                        result_dir = council_dir / 'agent_results'
                        existing_results = (
                            result_dir.exists() and any(result_dir.glob('agent_result__*.json'))
                        )
                        if not existing_results:
                            council_commands.append(
                                ('run_agentic_council_local_mock', [py, 'skills/factor-forge-step6/scripts/run_agentic_council_local_mock.py', '--report-id', args.report_id])
                            )
                        council_commands.extend(
                            [
                                ('validate_agentic_council_result', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_result.py', '--report-id', args.report_id]),
                                ('merge_revision_council', [py, 'skills/factor-forge-step6/scripts/merge_revision_council.py', '--report-id', args.report_id]),
                                ('build_council_derivation_appendix', [py, 'skills/factor-forge-step6/scripts/build_council_derivation_appendix.py', '--report-id', args.report_id]),
                                ('attach_revision_council_to_step6', [py, 'skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py', '--report-id', args.report_id]),
                                ('validate_step6_after_council_attach', [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]),
                            ]
                        )
                else:
                    council_commands = [
                        ('build_revision_council_packet', [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id]),
                        ('run_revision_council', [py, 'skills/factor-forge-step6/scripts/run_revision_council.py', '--report-id', args.report_id]),
                        ('merge_revision_council', [py, 'skills/factor-forge-step6/scripts/merge_revision_council.py', '--report-id', args.report_id]),
                        ('build_council_derivation_appendix', [py, 'skills/factor-forge-step6/scripts/build_council_derivation_appendix.py', '--report-id', args.report_id]),
                        ('attach_revision_council_to_step6', [py, 'skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py', '--report-id', args.report_id]),
                        ('validate_step6_after_council_attach', [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]),
                    ]
                proof['revision_council'] = {
                    'requested_mode': args.council_mode,
                    'auto_council_policy': args.auto_council_policy,
                    'effective_mode': effective_mode or 'scaffold',
                    'executor': args.agentic_council_executor,
                    'dispatch_adapter': args.agentic_dispatch_adapter,
                    'runtime_dispatch': runtime_dispatch,
                    'subagent_provider': args.subagent_provider,
                    'subagent_model': args.subagent_model,
                    'status': 'running',
                    'trigger_reason': trigger_reason,
                    'formal_council_status': 'running',
                    'deterministic_scaffold_used': effective_mode == 'scaffold',
                    'deterministic_scaffold_formal': False,
                    'agentic_required_for_formal_research': args.council_mode == 'auto',
                    'commands': [],
                    'provisional_step3b_handoff_policy': provisional_handoff_policy,
                    'side_effect_baseline': side_effect_before,
                }
                write_json_atomic(proof_path, proof)
                for council_name, council_command in council_commands:
                    injected_failure = os.environ.get('FACTORFORGE_ULTIMATE_TEST_FAIL_COUNCIL_COMMAND')
                    if injected_failure and injected_failure == council_name and is_tmp_root(council_root):
                        council_command = [py, '-c', f"import sys; print('INJECTED_COUNCIL_FAILURE:{council_name}', file=sys.stderr); raise SystemExit(1)"]
                    council_result = run_command(council_name, council_command, cwd=ctx.repo_root, env=env, dry_run=False)
                    proof['revision_council']['commands'].append(
                        public_command_proof(
                            council_result,
                            denied_values=host_private_proof_values,
                        )
                    )
                    proof['finished_at_utc'] = utc_now()
                    write_json_atomic(proof_path, proof)
                    if council_result.returncode != 0:
                        proof['status'] = 'FAIL'
                        proof['revision_council']['status'] = 'failed'
                        proof['revision_council']['failing_command'] = council_name
                        proof['failure'] = {'command': council_name, 'returncode': council_result.returncode}
                        write_json_atomic(proof_path, proof)
                        print(f'[FAIL] {council_name} rc={council_result.returncode}')
                        print(f'[PROOF] {proof_path}')
                        return int(council_result.returncode or 1)

                side_effect_after = council_side_effect_snapshot(council_root, args.report_id, clean_data_root=ctx.clean_data_root)
                if os.environ.get('FACTORFORGE_ULTIMATE_TEST_MUTATE_GENERATED_CODE_AFTER_COUNCIL') == '1' and is_tmp_root(council_root):
                    injected_path = council_root / 'generated_code' / args.report_id / 'wrapper_side_effect_injection.txt'
                    injected_path.parent.mkdir(parents=True, exist_ok=True)
                    injected_path.write_text('forbidden side effect injected by council primary smoke\n', encoding='utf-8')
                    side_effect_after = council_side_effect_snapshot(council_root, args.report_id, clean_data_root=ctx.clean_data_root)
                changes = side_effect_changes(side_effect_before, side_effect_after)
                proof['revision_council']['side_effect_after'] = side_effect_after
                if changes:
                    token = 'BLOCK_REVISION_COUNCIL_WRAPPER_FORBIDDEN_SIDE_EFFECT'
                    proof['status'] = 'FAIL'
                    proof['revision_council']['status'] = 'failed'
                    proof['revision_council']['block_reason'] = token
                    proof['revision_council']['side_effect_changes'] = changes
                    proof['failure'] = {'command': 'revision_council_side_effect_guard', 'returncode': 1, 'token': token}
                    proof['finished_at_utc'] = utc_now()
                    write_json_atomic(proof_path, proof)
                    print(token)
                    print(f'[PROOF] {proof_path}')
                    return 1
                if (
                    effective_mode == 'agentic_dispatch_manifest'
                    and not agentic_dispatch_finalizing
                ):
                    proof['revision_council'].update(summarize_council_dispatch(council_root, args.report_id, side_effect_after, side_effect_before))
                    proof['revision_council']['status'] = 'awaiting_agent_results'
                    proof['revision_council']['formal_council_status'] = 'awaiting_agent_results'
                    proof['status'] = 'PAUSED'
                    proof['formal_proof_eligible'] = False
                    proof['proof_semantics'] = 'awaiting_revision_council_agent_results'
                    proof['failure'] = None
                    proof['finished_at_utc'] = utc_now()
                    proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
                    proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
                    write_json_atomic(proof_path, proof)
                    print('AWAITING_REVISION_COUNCIL_AGENT_RESULTS')
                    print(f'[PROOF] {proof_path}')
                    return 0
                else:
                    proof['revision_council'].update(summarize_council_attachment(council_root, args.report_id, side_effect_after, side_effect_before))
                    proof['revision_council']['status'] = 'completed'
                    proof['revision_council']['formal_council_status'] = (
                        'agentic_results_completed'
                        if agentic_dispatch_finalizing
                        else (
                            'contract_mock_completed'
                            if effective_mode == 'agentic_contract_mock'
                            else 'scaffold_only'
                        )
                    )
                    proof['revision_council']['attached'] = proof['revision_council'].get('attached') is True
                    if web_materialization is not None and agentic_dispatch_finalizing:
                        terminal_command = [
                            py,
                            'skills/factor-forge-step6/scripts/close_terminal_council_rejection.py',
                            '--report-id',
                            args.report_id,
                            '--factorforge-root',
                            str(council_root),
                            '--loop-index',
                            '1',
                            '--max-loops',
                            str(args.max_council_loops),
                        ]
                        terminal_result = run_command(
                            'close_terminal_council_rejection',
                            terminal_command,
                            cwd=ctx.repo_root,
                            env=env,
                            dry_run=False,
                        )
                        proof['revision_council']['commands'].append(
                            public_command_proof(
                                terminal_result,
                                denied_values=host_private_proof_values,
                            )
                        )
                        terminal_output = (
                            f'{terminal_result.stdout_tail}\n'
                            f'{terminal_result.stderr_tail}'
                        )
                        terminal_state = classify_terminal_rejection_result(
                            returncode=int(terminal_result.returncode or 0),
                            output=terminal_output,
                            branch_falsification_exists=(
                                council_dir
                                / f'branch_falsification__{args.report_id}.json'
                            ).is_file(),
                        )
                        if terminal_state == 'closed':
                            final_protocol_result = run_command(
                                'validate_research_protocol_final',
                                [
                                    py,
                                    'scripts/validate_factorforge_research_protocol.py',
                                    '--workspace-root',
                                    str(council_root),
                                    '--report-id',
                                    args.report_id,
                                    '--stage',
                                    'final',
                                ],
                                cwd=ctx.repo_root,
                                env=env,
                                dry_run=False,
                            )
                            proof['revision_council']['commands'].append(
                                public_command_proof(
                                    final_protocol_result,
                                    denied_values=host_private_proof_values,
                                )
                            )
                            if final_protocol_result.returncode != 0:
                                proof['status'] = 'FAIL'
                                proof['revision_council']['status'] = 'failed'
                                proof['revision_council']['formal_council_status'] = 'blocked'
                                proof['failure'] = {
                                    'command': 'validate_research_protocol_final',
                                    'returncode': final_protocol_result.returncode,
                                }
                                proof['finished_at_utc'] = utc_now()
                                write_json_atomic(proof_path, proof)
                                print('[FAIL] validate_research_protocol_final')
                                print(f'[PROOF] {proof_path}')
                                return int(final_protocol_result.returncode or 1)
                            proof['revision_council']['status'] = 'terminal_rejected'
                            proof['revision_council']['formal_council_status'] = 'rejected'
                            proof['revision_council']['terminal_protocol_validated'] = True
                            proof['revision_council']['terminal_decision'] = 'REJECT'
                        elif terminal_state == 'awaiting_next_derivation':
                            proof['status'] = 'PAUSED'
                            proof['formal_proof_eligible'] = False
                            proof['proof_semantics'] = 'awaiting_next_derivation'
                            proof['final_outcome'] = 'awaiting_next_derivation'
                            proof['failure'] = None
                            proof['revision_council']['status'] = 'awaiting_next_derivation'
                            proof['revision_council']['formal_council_status'] = 'paused'
                            proof['finished_at_utc'] = utc_now()
                            write_json_atomic(proof_path, proof)
                            print('AWAITING_NEXT_DERIVATION')
                            print(f'[PROOF] {proof_path}')
                            return 0
                        elif terminal_state == 'awaiting_main_agent_council_synthesis':
                            proof['status'] = 'PAUSED'
                            proof['formal_proof_eligible'] = False
                            proof['proof_semantics'] = (
                                'awaiting_main_agent_council_synthesis'
                            )
                            proof['final_outcome'] = (
                                'awaiting_main_agent_council_synthesis'
                            )
                            proof['failure'] = None
                            proof['revision_council']['status'] = (
                                'awaiting_main_agent_council_synthesis'
                            )
                            proof['revision_council']['formal_council_status'] = 'paused'
                            proof['finished_at_utc'] = utc_now()
                            write_json_atomic(proof_path, proof)
                            print('AWAITING_MAIN_AGENT_COUNCIL_SYNTHESIS')
                            print(f'[PROOF] {proof_path}')
                            return 0
                        else:
                            proof['status'] = 'FAIL'
                            proof['revision_council']['status'] = 'failed'
                            proof['revision_council']['formal_council_status'] = 'blocked'
                            proof['failure'] = {
                                'command': 'close_terminal_council_rejection',
                                'returncode': terminal_result.returncode,
                            }
                            proof['finished_at_utc'] = utc_now()
                            write_json_atomic(proof_path, proof)
                            print('[FAIL] close_terminal_council_rejection')
                            print(f'[PROOF] {proof_path}')
                            return int(terminal_result.returncode or 1)
                write_json_atomic(proof_path, proof)
    elif web_evo_oos_release_pass:
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
    elif args.council_mode != 'off':
        proof['revision_council'] = {
            'requested_mode': args.council_mode,
            'status': 'not_triggered',
            'reason': 'step6_not_requested',
        }
        write_json_atomic(proof_path, proof)

    command_contract = proof['formal_command_contract']
    executed_names = [
        str(row.get('name') or '')
        for row in proof.get('commands') or []
        if isinstance(row, dict)
    ]
    required_names = list(command_contract['required_command_names'])
    commands_passed = (
        executed_names == required_names
        and all(
            row.get('status') == 'PASS'
            and row.get('returncode') == 0
            for row in proof.get('commands') or []
            if isinstance(row, dict)
        )
    )
    command_contract['executed_command_names'] = executed_names
    command_contract['satisfied'] = bool(commands_passed)
    if args.dry_run:
        proof['status'] = 'DRY_RUN'
        proof['formal_proof_eligible'] = False
        proof['proof_semantics'] = 'execution_plan_only'
    else:
        web_council_terminal = (
            web_materialization is None
            or (
                proof.get('revision_council', {}).get(
                    'terminal_protocol_validated'
                )
                is True
            )
        )
        proof['status'] = 'PASS' if web_council_terminal else 'PAUSED'
        proof['formal_proof_eligible'] = bool(
            commands_passed
            and not legacy_protocol_smoke
            and web_council_terminal
            and (
                web_materialization is None
                or research_organization_runtime.get(
                    'formal_independence_verified'
                )
                is True
            )
        )
        proof['proof_semantics'] = (
            'contract_smoke_only'
            if legacy_protocol_smoke
            else (
                'formal_execution_proof'
                if web_council_terminal
                else (
                    'awaiting_evo_v2_non_revision_terminal_closure'
                    if web_evo_oos_release_pass
                    else 'awaiting_main_agent_council_synthesis'
                )
            )
        )
        if not web_council_terminal:
            proof['final_outcome'] = (
                'awaiting_evo_v2_non_revision_terminal_closure'
                if web_evo_oos_release_pass
                else 'awaiting_main_agent_council_synthesis'
            )
    proof['finished_at_utc'] = utc_now()
    proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
    proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
    if not args.dry_run:
        final_trust_root = Path(
            incident_host_env[OOS_HOST_TRUST_ROOT_ENV]
        ).expanduser().resolve(strict=True)
        final_installation_id = incident_host_env[
            OOS_HOST_INSTALLATION_ID_ENV
        ]
        with oos_exposure_private_registry_guard(
            final_trust_root,
            installation_id=final_installation_id,
        ) as final_incident_guard:
            incident_reasons = formal_oos_incident_reasons(
                workspace_root=ctx.active_root,
                report_id=args.report_id,
                trust_root=final_trust_root,
                installation_id=final_installation_id,
            )
            if incident_reasons:
                proof['status'] = 'FAIL'
                proof['formal_proof_eligible'] = False
                proof['proof_semantics'] = 'blocked_current_formal_authority'
                proof['factor_verdict'] = None
                proof['final_outcome'] = 'blocked'
                proof['failure'] = {
                    'command': 'ultimate_current_authority_commit',
                    'returncode': 1,
                    'token': 'BLOCK_FACTORFORGE_OOS_EXPOSURE_INCIDENT',
                    'block_reasons': incident_reasons,
                }
            elif proof.get('formal_proof_eligible') is True and web_materialization is not None:
                certificate_path = factor_proof_certificate_path(
                    ctx.active_root,
                    args.report_id,
                )
                try:
                    certificate_payload = json.loads(
                        certificate_path.read_text(encoding='utf-8')
                    )
                    certificate_replay = validate_factor_proof_certificate(
                        certificate_payload,
                        workspace_root=ctx.active_root,
                        expected_report_id=args.report_id,
                        expected_factor_id=str(
                            certificate_payload.get('factor_id') or ''
                        ),
                        incident_trust_root=final_trust_root,
                        incident_installation_id=final_installation_id,
                        _incident_guard=final_incident_guard,
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    certificate_replay = {
                        'verdict': 'BLOCK',
                        'block_reasons': [str(exc)],
                        'current_formal_authority_verified': False,
                    }
                if (
                    certificate_replay.get('verdict') not in {'ACCEPT', 'REJECT'}
                    or certificate_replay.get(
                        'current_formal_authority_verified'
                    ) is not True
                ):
                    proof['status'] = 'FAIL'
                    proof['formal_proof_eligible'] = False
                    proof['proof_semantics'] = 'blocked_current_formal_authority'
                    proof['factor_verdict'] = None
                    proof['final_outcome'] = 'blocked'
                    proof['failure'] = {
                        'command': 'ultimate_current_certificate_replay',
                        'returncode': 1,
                        'token': 'BLOCK_FACTORFORGE_FACTOR_PROOF_CURRENT_AUTHORITY',
                        'block_reasons': certificate_replay.get(
                            'block_reasons'
                        ) or [],
                    }
                proof['current_factor_proof_authority'] = certificate_replay
            if proof.get('formal_proof_eligible') is True and web_evo_oos_release_pass:
                closure_replay = validate_evo_post_oos_terminal_closure(
                    workspace_root=ctx.active_root,
                    report_id=args.report_id,
                    trust_root=final_trust_root,
                    installation_id=final_installation_id,
                    _incident_guard=final_incident_guard,
                )
                if closure_replay.get('verdict') != 'PASS':
                    proof['status'] = 'FAIL'
                    proof['formal_proof_eligible'] = False
                    proof['proof_semantics'] = 'blocked_current_formal_authority'
                    proof['factor_verdict'] = None
                    proof['final_outcome'] = 'blocked'
                    proof['failure'] = {
                        'command': 'ultimate_current_terminal_closure_replay',
                        'returncode': 1,
                        'token': 'BLOCK_FACTORFORGE_EVO_V2_POST_OOS_TERMINAL_CLOSURE_INVALID',
                        'block_reasons': closure_replay.get('block_reasons') or [],
                    }
                proof['current_evo_terminal_authority'] = closure_replay
            proof['current_formal_authority_verified'] = bool(
                proof.get('formal_proof_eligible') is True
            )
            write_json_atomic(proof_path, proof)
    else:
        proof['current_formal_authority_verified'] = False
        write_json_atomic(proof_path, proof)
    result_label = (
        'DRY_RUN'
        if args.dry_run
        else ('PASS' if proof['status'] == 'PASS' else 'PAUSED')
    )
    print(
        f'[{result_label}] factor-forge-ultimate wrapper completed '
        f'for {args.report_id}'
    )
    print(f'[MANIFEST] {manifest_path}')
    print(f'[PROOF] {proof_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
