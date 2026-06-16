#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    BLOCK_WORKSPACE_MISSING,
    build_workspace_manifest,
    default_workspace_root,
    load_workspace_manifest,
    validate_workspace_cli_identity,
    validate_workspace_manifest,
    workspace_manifest_path,
    write_workspace_manifest,
)
from factor_factory.runtime_context import load_runtime_manifest, resolve_factorforge_context, utc_now, write_json_atomic
from factor_factory.state_reuse import (
    BLOCK_STATE_DEPENDENCY_UNDECLARED,
    StateReuseBlock,
    assert_no_raw_minute_full_window_scan,
    load_json as load_state_json,
    load_state_dependency_contract,
    require_state_resolution_ready,
    resolve_state_dependencies,
    write_resolution_outputs,
)


STEP_ORDER = ['2', '3', '3b', '4', '5', '6']
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
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--proof-output', default=None)
    ap.add_argument('--state-dependency-contract', default=None)
    ap.add_argument('--state-catalog', default=None)
    ap.add_argument('--state-resolution', default=None)
    ap.add_argument('--state-data-request-dir', default=None)
    ap.add_argument('--state-input-path', action='append', default=[], help='Step4 input path to check for forbidden production raw-minute roots.')
    ap.add_argument('--require-state-reuse-contract', action='store_true')
    ap.add_argument('--explicit-data-production-context', action='store_true')
    return ap.parse_args()


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
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser()
        manifest = runtime_manifest_from_args if runtime_manifest_from_args else ctx.build_manifest(args.report_id, branch_id=args.branch_id)
    else:
        manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
        manifest_path = Path(tempfile.gettempdir()) / f'factorforge_runtime_manifest__{args.report_id}__{os.getpid()}.json'
        write_json_atomic(manifest_path, manifest)

    if args.proof_output:
        proof_path = Path(args.proof_output).expanduser()
    elif args.dry_run:
        proof_path = Path(tempfile.gettempdir()) / f'ultimate_run_report__{args.report_id}.json'
    else:
        proof_path = ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{args.report_id}.json'
    env = os.environ.copy()
    env.pop('FACTORFORGE_ALLOW_DIRECT_STEP', None)
    env.pop('FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF', None)
    env['FACTORFORGE_ROOT'] = str(ctx.active_root)
    env['FACTORFORGE_SHARED_FACTORFORGE_ROOT'] = str(ctx.factorforge_root)
    if ctx.factor_workspace:
        env['FACTORFORGE_FACTOR_WORKSPACE'] = str(ctx.factor_workspace)
        env['FACTORFORGE_FACTOR_WORKSPACE_MANIFEST'] = str(ctx.factor_workspace_manifest or (ctx.factor_workspace / 'manifest.json'))
    env['FACTORFORGE_ULTIMATE_RUN'] = '1'

    py = sys.executable
    commands: list[tuple[str, list[str]]] = []
    runtime_dispatch = args.runtime_dispatch
    if runtime_dispatch is None:
        runtime_dispatch = 'manual_file' if args.agentic_dispatch_adapter == 'manual_file' else 'unknown'
    taskbook_runtime_args = ['--runtime-dispatch', runtime_dispatch]
    if args.subagent_provider:
        taskbook_runtime_args.extend(['--subagent-provider', args.subagent_provider])
    if args.subagent_model:
        taskbook_runtime_args.extend(['--subagent-model', args.subagent_model])

    if args.apply_approved_revision:
        commands.append(('apply_approved_step6_revision', [py, 'skills/factor-forge-step6/scripts/apply_step6_iteration.py', '--manifest', str(manifest_path)]))

    if '2' in steps:
        commands.append(('run_step2', [py, 'skills/factor-forge-step2/scripts/run_step2.py', '--report-id', args.report_id]))
        commands.append(('validate_step2', [py, 'skills/factor-forge-step2/scripts/validate_step2.py', '--report-id', args.report_id]))

    if '3' in steps and not args.skip_step3a:
        commands.append(('run_step3', [py, 'skills/factor-forge-step3/scripts/run_step3.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3', [py, 'skills/factor-forge-step3/scripts/validate_step3.py', '--manifest', str(manifest_path)]))

    if '3b' in steps or ('3' in steps):
        commands.append(('run_step3b', [py, 'skills/factor-forge-step3/scripts/run_step3b.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3b', [py, 'skills/factor-forge-step3/scripts/validate_step3b.py', '--manifest', str(manifest_path)]))

    if '4' in steps:
        commands.append(('run_step4', [py, 'skills/factor-forge-step4/scripts/run_step4.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step4', [py, 'skills/factor-forge-step4/scripts/validate_step4.py', '--report-id', args.report_id]))

    if '5' in steps:
        commands.append(('run_step5', [py, 'skills/factor-forge-step5/scripts/run_step5.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step5', [py, 'skills/factor-forge-step5/scripts/validate_step5.py', '--report-id', args.report_id]))

    if '6' in steps:
        if not args.skip_researcher_packets:
            commands.append(('build_researcher_dossier', [py, 'skills/factor-forge-researcher/scripts/build_researcher_dossier.py', '--report-id', args.report_id]))
            commands.append(('build_step6_researcher_packet', [py, 'skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py', '--report-id', args.report_id]))
        commands.append(('run_step6', [py, 'skills/factor-forge-step6/scripts/run_step6.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step6', [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]))

    proof: dict[str, Any] = {
        'contract_version': 'factorforge_ultimate_wrapper_v1',
        'report_id': args.report_id,
        'started_at_utc': utc_now(),
        'finished_at_utc': None,
        'factorforge_root': str(ctx.factorforge_root),
        'active_root': str(ctx.active_root),
        'factor_workspace': str(ctx.factor_workspace) if ctx.factor_workspace else None,
        'repo_root': str(ctx.repo_root),
        'manifest_path': str(manifest_path),
        'start_step': start,
        'end_step': end,
        'requested_steps': steps,
        'dry_run': bool(args.dry_run),
        'status': 'RUNNING',
        'commands': [],
        'child_env_policy': {
            'FACTORFORGE_ULTIMATE_RUN': '1',
            'removed': ['FACTORFORGE_ALLOW_DIRECT_STEP', 'FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF'],
        },
        'expected_artifacts_before': collect_expected_artifacts(manifest),
        'expected_artifacts_after': {},
        'step3b_mode_decision': collect_step3b_mode_decision(manifest),
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

    if args.council_mode == 'agentic':
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
        result = run_command(name, command, cwd=ctx.repo_root, env=env, dry_run=args.dry_run)
        proof['commands'].append(asdict(result))
        proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
        proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
        proof['finished_at_utc'] = utc_now()
        if result.returncode != 0:
            output = (result.stdout_tail or '') + '\n' + (result.stderr_tail or '')
            if name == 'run_step6' and 'AWAITING_MAIN_AGENT_MECHANISM_MEMO' in output:
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
                print('AWAITING_MAIN_AGENT_MECHANISM_MEMO')
                print(f'[PROOF] {proof_path}')
                return 0
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': name, 'returncode': result.returncode}
            write_json_atomic(proof_path, proof)
            print(f'[FAIL] {name} rc={result.returncode}')
            print(f'[PROOF] {proof_path}')
            return int(result.returncode or 1)
        write_json_atomic(proof_path, proof)

    if '6' in steps and args.council_mode != 'off':
        if args.dry_run:
            proof['revision_council'] = {
                'requested_mode': args.council_mode,
                'status': 'not_triggered',
                'reason': 'dry_run',
            }
            write_json_atomic(proof_path, proof)
        else:
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
                    if effective_mode == 'agentic_dispatch_manifest':
                        council_commands = [
                            ('build_revision_council_packet', [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id]),
                            ('build_agentic_council_taskbook', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py', '--report-id', args.report_id, '--executor', 'dispatch_manifest', *taskbook_runtime_args]),
                            ('build_agentic_council_dispatch_manifest', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py', '--report-id', args.report_id]),
                            ('validate_agentic_council_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py', '--report-id', args.report_id]),
                        ]
                        if args.agentic_dispatch_adapter == 'manual_file':
                            council_commands.extend(
                                [
                                    ('build_agentic_council_manual_dispatch_bundle', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_manual_dispatch_bundle.py', '--report-id', args.report_id]),
                                    ('validate_agentic_council_manual_dispatch', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_manual_dispatch.py', '--report-id', args.report_id]),
                                    ('update_agentic_council_dispatch_status', [py, 'skills/factor-forge-step6/scripts/update_agentic_council_dispatch_status.py', '--report-id', args.report_id]),
                                ]
                            )
                    else:
                        council_commands = [
                            ('build_revision_council_packet', [py, 'skills/factor-forge-step6/scripts/build_revision_council_packet.py', '--report-id', args.report_id]),
                            ('build_agentic_council_taskbook', [py, 'skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py', '--report-id', args.report_id, '--executor', 'local_mock', *taskbook_runtime_args]),
                            ('run_agentic_council_local_mock', [py, 'skills/factor-forge-step6/scripts/run_agentic_council_local_mock.py', '--report-id', args.report_id]),
                            ('validate_agentic_council_result', [py, 'skills/factor-forge-step6/scripts/validate_agentic_council_result.py', '--report-id', args.report_id]),
                            ('merge_revision_council', [py, 'skills/factor-forge-step6/scripts/merge_revision_council.py', '--report-id', args.report_id]),
                            ('build_council_derivation_appendix', [py, 'skills/factor-forge-step6/scripts/build_council_derivation_appendix.py', '--report-id', args.report_id]),
                            ('attach_revision_council_to_step6', [py, 'skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py', '--report-id', args.report_id]),
                            ('validate_step6_after_council_attach', [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]),
                        ]
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
                    proof['revision_council']['commands'].append(asdict(council_result))
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
                if effective_mode == 'agentic_dispatch_manifest':
                    proof['revision_council'].update(summarize_council_dispatch(council_root, args.report_id, side_effect_after, side_effect_before))
                    proof['revision_council']['status'] = 'awaiting_agent_results'
                    proof['revision_council']['formal_council_status'] = 'awaiting_agent_results'
                else:
                    proof['revision_council'].update(summarize_council_attachment(council_root, args.report_id, side_effect_after, side_effect_before))
                    proof['revision_council']['status'] = 'completed'
                    proof['revision_council']['formal_council_status'] = 'agentic_completed' if effective_mode == 'agentic_contract_mock' else 'scaffold_only'
                    proof['revision_council']['attached'] = proof['revision_council'].get('attached') is True
                write_json_atomic(proof_path, proof)
    elif args.council_mode != 'off':
        proof['revision_council'] = {
            'requested_mode': args.council_mode,
            'status': 'not_triggered',
            'reason': 'step6_not_requested',
        }
        write_json_atomic(proof_path, proof)

    proof['status'] = 'PASS'
    proof['finished_at_utc'] = utc_now()
    proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
    proof['step3b_mode_decision'] = collect_step3b_mode_decision(manifest)
    write_json_atomic(proof_path, proof)
    print(f'[PASS] factor-forge-ultimate wrapper completed for {args.report_id}')
    print(f'[MANIFEST] {manifest_path}')
    print(f'[PROOF] {proof_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
