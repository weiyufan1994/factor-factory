from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from factor_factory.research_workspace import (
    BLOCK_WORKSPACE_MANIFEST_INVALID,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)

try:
    import fcntl
except Exception:  # pragma: no cover - fcntl is unavailable on some non-Unix hosts
    fcntl = None

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_FACTORFORGE = LEGACY_WORKSPACE / 'factorforge'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def load_runtime_manifest(path: str | Path) -> dict[str, Any]:
    manifest = load_json(Path(path).expanduser())
    version = manifest.get('contract_version')
    if version not in {'factorforge_runtime_context_v1', 'factorforge_runtime_context_v2'}:
        raise ValueError(f'unsupported FactorForge runtime manifest: {version!r}')
    return manifest


def manifest_path(manifest: dict[str, Any] | None, section: str, key: str) -> Path | None:
    if not manifest:
        return None
    raw = ((manifest.get(section) or {}).get(key))
    return Path(raw).expanduser() if raw else None


def manifest_report_id(manifest: dict[str, Any]) -> str:
    report_id = manifest.get('report_id')
    if not report_id:
        raise ValueError('runtime manifest is missing report_id')
    return str(report_id)


def manifest_factorforge_root(manifest: dict[str, Any]) -> Path:
    root = manifest.get('factorforge_root')
    if not root:
        raise ValueError('runtime manifest is missing factorforge_root')
    return Path(root).expanduser()


def manifest_factor_workspace(manifest: dict[str, Any]) -> Path | None:
    raw = manifest.get('factor_workspace')
    return Path(raw).expanduser() if raw else None


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def update_json_locked(path: Path, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('w') as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            current = load_json(path) if path.exists() else {}
            updated = updater(current)
            if updated is None:
                updated = current
            write_json_atomic(path, updated)
            return updated
        finally:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)


@dataclass(frozen=True)
class FactorForgeContext:
    repo_root: Path
    workspace_root: Path
    factorforge_root: Path
    factor_workspace: Path | None = None
    factor_workspace_manifest: Path | None = None
    factor_id: str | None = None
    research_id: str | None = None

    @property
    def active_root(self) -> Path:
        return self.factor_workspace or self.factorforge_root

    @property
    def objects_root(self) -> Path:
        return self.active_root / 'objects'

    @property
    def runs_root(self) -> Path:
        return self.active_root / 'runs'

    @property
    def evaluations_root(self) -> Path:
        return self.active_root / 'evaluations'

    @property
    def archive_root(self) -> Path:
        return self.active_root / 'archive'

    @property
    def data_root(self) -> Path:
        return self.factorforge_root / 'data'

    @property
    def clean_data_root(self) -> Path:
        return self.data_root / 'clean'

    @property
    def runtime_context_root(self) -> Path:
        return self.objects_root / 'runtime_context'

    @property
    def knowledge_root(self) -> Path:
        return self.active_root / 'knowledge'

    @property
    def step3_runtime_root(self) -> Path:
        return self.active_root / 'step3_runtime'

    def object_path(self, kind: str, report_id: str, *, name: str | None = None) -> Path:
        defaults = {
            'alpha_idea_master': ('alpha_idea_master', f'alpha_idea_master__{report_id}.json'),
            'factor_spec_master': ('factor_spec_master', f'factor_spec_master__{report_id}.json'),
            'data_prep_master': ('data_prep_master', f'data_prep_master__{report_id}.json'),
            'qlib_adapter_config': ('data_prep_master', f'qlib_adapter_config__{report_id}.json'),
            'implementation_plan_master': ('implementation_plan_master', f'implementation_plan_master__{report_id}.json'),
            'factor_run_master': ('factor_run_master', f'factor_run_master__{report_id}.json'),
            'factor_case_master': ('factor_case_master', f'factor_case_master__{report_id}.json'),
            'factor_evaluation': ('validation', f'factor_evaluation__{report_id}.json'),
            'data_feasibility_report': ('validation', f'data_feasibility_report__{report_id}.json'),
            'research_iteration_master': ('research_iteration_master', f'research_iteration_master__{report_id}.json'),
            'researcher_memo': ('research_iteration_master', f'researcher_memo__{report_id}.json'),
            'research_journal': ('research_journal', f'research_journal__{report_id}.json'),
            'program_search_plan': ('research_iteration_master', f'program_search_plan__{report_id}.json'),
            'search_branch_ledger': ('research_iteration_master', f'search_branch_ledger__{report_id}.json'),
            'program_search_merge': ('research_iteration_master', f'program_search_merge__{report_id}.json'),
            'handoff_to_step2': ('handoff', f'handoff_to_step2__{report_id}.json'),
            'handoff_to_step3': ('handoff', f'handoff_to_step3__{report_id}.json'),
            'handoff_to_step3b': ('handoff', f'handoff_to_step3b__{report_id}.json'),
            'handoff_to_step4': ('handoff', f'handoff_to_step4__{report_id}.json'),
            'handoff_to_step5': ('handoff', f'handoff_to_step5__{report_id}.json'),
            'handoff_to_step6': ('handoff', f'handoff_to_step6__{report_id}.json'),
        }
        if kind not in defaults:
            raise KeyError(f'unknown FactorForge object kind: {kind}')
        rel_dir, default_name = defaults[kind]
        return self.objects_root / rel_dir / (name or default_name)

    def search_branch_result_path(self, report_id: str, branch_id: str) -> Path:
        return self.objects_root / 'research_iteration_master' / f'search_branch_result__{report_id}__{branch_id}.json'

    def search_branch_taskbook_path(self, report_id: str, branch_id: str) -> Path:
        return self.objects_root / 'research_iteration_master' / f'search_branch_taskbook__{report_id}__{branch_id}.json'

    def run_dir(self, report_id: str) -> Path:
        return self.runs_root / report_id

    def factor_values_path(self, report_id: str, suffix: str = 'parquet') -> Path:
        return self.run_dir(report_id) / f'factor_values__{report_id}.{suffix}'

    def run_metadata_path(self, report_id: str) -> Path:
        return self.run_dir(report_id) / f'run_metadata__{report_id}.json'

    def step3a_daily_input_path(self, report_id: str) -> Path:
        return self.run_dir(report_id) / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'

    def step3a_daily_meta_path(self, report_id: str) -> Path:
        return self.run_dir(report_id) / 'step3a_local_inputs' / f'daily_input_meta__{report_id}.json'

    def evaluation_payload_path(self, report_id: str, backend: str) -> Path:
        return self.evaluations_root / report_id / backend / 'evaluation_payload.json'

    def research_branch_root(self, report_id: str, branch_id: str) -> Path:
        return self.active_root / 'research_branches' / report_id / branch_id

    def remap_legacy_path(self, raw: str | Path | None) -> Path | None:
        if raw is None:
            return None
        text = str(raw)
        if not text:
            return None
        path = Path(text).expanduser()
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
            legacy_ff = str(LEGACY_FACTORFORGE)
            legacy_ws = str(LEGACY_WORKSPACE)
            if text.startswith(legacy_ff):
                candidates.append(self.factorforge_root / text[len(legacy_ff):].lstrip('/'))
            if text.startswith(legacy_ws):
                candidates.append(self.workspace_root / text[len(legacy_ws):].lstrip('/'))
        else:
            candidates.extend([
                self.factorforge_root / path,
                self.workspace_root / path,
                self.repo_root / path,
                self.runs_root / path,
            ])
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else path

    def build_manifest(self, report_id: str, branch_id: str | None = None) -> dict[str, Any]:
        objects = {
            kind: str(self.object_path(kind, report_id))
            for kind in [
                'alpha_idea_master', 'factor_spec_master', 'data_prep_master', 'qlib_adapter_config',
                'implementation_plan_master', 'factor_run_master', 'factor_case_master',
                'factor_evaluation', 'research_iteration_master', 'researcher_memo', 'research_journal',
                'program_search_plan', 'search_branch_ledger', 'program_search_merge',
                'handoff_to_step2', 'handoff_to_step3', 'handoff_to_step3b', 'handoff_to_step4',
                'handoff_to_step5', 'handoff_to_step6',
            ]
        }
        runs = {
            'run_dir': str(self.run_dir(report_id)),
            'factor_values_parquet': str(self.factor_values_path(report_id, 'parquet')),
            'factor_values_csv': str(self.factor_values_path(report_id, 'csv')),
            'run_metadata': str(self.run_metadata_path(report_id)),
            'step3a_daily_input_csv': str(self.step3a_daily_input_path(report_id)),
            'step3a_daily_input_meta_json': str(self.step3a_daily_meta_path(report_id)),
        }
        evaluations = {
            'evaluation_dir': str(self.evaluations_root / report_id),
            'self_quant_payload': str(self.evaluation_payload_path(report_id, 'self_quant_analyzer')),
            'qlib_backtest_payload': str(self.evaluation_payload_path(report_id, 'qlib_backtest')),
        }
        step_io = {
            'step3': {
                'inputs': {
                    'alpha_idea_master': objects['alpha_idea_master'],
                    'factor_spec_master': objects['factor_spec_master'],
                    'handoff_to_step3': objects['handoff_to_step3'],
                },
                'data_inputs': {
                    'shared_clean_data_root': str(self.clean_data_root),
                },
                'outputs': {
                    'data_prep_master': objects['data_prep_master'],
                    'qlib_adapter_config': objects['qlib_adapter_config'],
                    'implementation_plan_master': objects['implementation_plan_master'],
                    'factor_values_parquet': runs['factor_values_parquet'],
                    'factor_values_csv': runs['factor_values_csv'],
                    'run_metadata': runs['run_metadata'],
                    'handoff_to_step4': objects['handoff_to_step4'],
                },
            },
            'step4': {
                'inputs': {
                    'factor_spec_master': objects['factor_spec_master'],
                    'data_prep_master': objects['data_prep_master'],
                    'handoff_to_step4': objects['handoff_to_step4'],
                    'factor_values_parquet': runs['factor_values_parquet'],
                    'step3a_daily_input_csv': runs['step3a_daily_input_csv'],
                },
                'outputs': {
                    'factor_run_master': objects['factor_run_master'],
                    'factor_run_diagnostics': str(self.objects_root / 'validation' / f'factor_run_diagnostics__{report_id}.json'),
                    'handoff_to_step5': objects['handoff_to_step5'],
                    'self_quant_payload': evaluations['self_quant_payload'],
                    'qlib_backtest_payload': evaluations['qlib_backtest_payload'],
                },
            },
            'step5': {
                'inputs': {
                    'factor_run_master': objects['factor_run_master'],
                    'handoff_to_step5': objects['handoff_to_step5'],
                    'factor_values_parquet': runs['factor_values_parquet'],
                    'evaluation_dir': evaluations['evaluation_dir'],
                },
                'outputs': {
                    'factor_evaluation': objects['factor_evaluation'],
                    'factor_case_master': objects['factor_case_master'],
                    'handoff_to_step6': objects['handoff_to_step6'],
                    'archive_root': str(self.archive_root / report_id),
                },
            },
            'step6': {
                'inputs': {
                    'factor_run_master': objects['factor_run_master'],
                    'factor_case_master': objects['factor_case_master'],
                    'factor_evaluation': objects['factor_evaluation'],
                    'handoff_to_step6': objects['handoff_to_step6'],
                    'factor_spec_master': objects['factor_spec_master'],
                    'alpha_idea_master': objects['alpha_idea_master'],
                },
                'outputs': {
                    'research_iteration_master': objects['research_iteration_master'],
                    'researcher_memo': objects['researcher_memo'],
                    'research_journal': objects['research_journal'],
                    'handoff_to_step3b': objects['handoff_to_step3b'],
                },
            },
        }
        version = 'factorforge_runtime_context_v2' if self.factor_workspace else 'factorforge_runtime_context_v1'
        manifest: dict[str, Any] = {
            'contract_version': version,
            'created_at_utc': utc_now(),
            'report_id': report_id,
            'repo_root': str(self.repo_root),
            'workspace_root': str(self.workspace_root),
            'factorforge_root': str(self.factorforge_root),
            'objects_root': str(self.objects_root),
            'runs_root': str(self.runs_root),
            'evaluations_root': str(self.evaluations_root),
            'archive_root': str(self.archive_root),
            'clean_data_root': str(self.clean_data_root),
            'objects': objects,
            'runs': runs,
            'evaluations': evaluations,
            'knowledge': {
                'knowledge_root': str(self.knowledge_root),
                'canonical_root': str(self.knowledge_root / 'canonical'),
                'human_readable_root': str(self.knowledge_root / 'human_readable'),
                'export_manifest_root': str(self.knowledge_root / 'export_manifest'),
            },
            'write_policy': {
                'production_writes_must_stay_under_workspace': bool(self.factor_workspace),
                'repo_root_knowledge_write_allowed': False if self.factor_workspace else None,
                'repo_root_data_write_allowed': False if self.factor_workspace else None,
                'vault_export_requires_explicit_flag': bool(self.factor_workspace),
            },
            'step_io': step_io,
            'resolution_policy': [
                'Agent/skill orchestration is responsible for discovering inputs and outputs once and writing this manifest.',
                'Step scripts should consume explicit manifest paths instead of independently searching artifact locations.',
                'Handoffs may contain relative paths, but the orchestrator must resolve them before invoking scripts.',
                'Legacy EC2 absolute paths may be remapped to the active factorforge_root.',
                'When a manifest field exists, script-local path guessing is a compatibility fallback only.',
            ],
        }
        if self.factor_workspace:
            manifest.update(
                {
                    'factor_id': self.factor_id,
                    'research_id': self.research_id,
                    'factor_workspace': str(self.factor_workspace),
                    'factor_workspace_manifest': str(self.factor_workspace_manifest or (self.factor_workspace / 'manifest.json')),
                    'step3_runtime_root': str(self.step3_runtime_root),
                }
            )
        if branch_id:
            manifest['branch_id'] = branch_id
            manifest['branch'] = {
                'branch_root': str(self.research_branch_root(report_id, branch_id)),
                'taskbook': str(self.search_branch_taskbook_path(report_id, branch_id)),
                'result': str(self.search_branch_result_path(report_id, branch_id)),
            }
        spec_path = Path(objects['factor_spec_master'])
        spec_identity: dict[str, Any] = {}
        if spec_path.exists():
            try:
                spec_identity = (load_json(spec_path).get('artifact_identity') or {})
            except Exception:
                spec_identity = {}
        manifest['manifest_identity'] = {
            'report_id': report_id,
            'factor_id': spec_identity.get('factor_id'),
            'source_type': spec_identity.get('source_type'),
            'implementation_mode': spec_identity.get('implementation_mode'),
            'contract_version': spec_identity.get('contract_version'),
            'producer': spec_identity.get('producer'),
            'upstream_producer': spec_identity.get('upstream_producer'),
            'formula_hash': spec_identity.get('formula_hash'),
            'code_hash': spec_identity.get('code_hash'),
            'code_contract_hash': spec_identity.get('code_contract_hash'),
            'custom_block_hash': spec_identity.get('custom_block_hash'),
            'hybrid_hash': spec_identity.get('hybrid_hash'),
            'spec_hash': spec_identity.get('spec_hash'),
            'branch_id': branch_id or spec_identity.get('branch_id') or 'main',
            'run_id': spec_identity.get('run_id'),
            'parent_run_id': spec_identity.get('parent_run_id'),
            'artifact_role': spec_identity.get('artifact_role'),
        }
        return manifest

    def write_manifest(self, report_id: str, branch_id: str | None = None) -> Path:
        suffix = f'__{branch_id}' if branch_id else ''
        out = self.runtime_context_root / f'runtime_context__{report_id}{suffix}.json'
        write_json_atomic(out, self.build_manifest(report_id, branch_id=branch_id))
        return out


def resolve_factorforge_context(
    explicit_root: str | Path | None = None,
    *,
    factor_workspace: str | Path | None = None,
) -> FactorForgeContext:
    if explicit_root:
        ff = Path(explicit_root).expanduser()
    elif os.getenv('FACTORFORGE_ROOT'):
        ff = Path(os.environ['FACTORFORGE_ROOT']).expanduser()
    elif LEGACY_FACTORFORGE.exists():
        ff = LEGACY_FACTORFORGE
    else:
        ff = REPO_ROOT
    ff = ff.resolve()
    workspace = Path(factor_workspace).expanduser().resolve() if factor_workspace else None
    workspace_manifest = None
    factor_id = None
    research_id = None
    if workspace:
        workspace_manifest = workspace_manifest_path(workspace)
        if not workspace_manifest.exists():
            raise ValueError(f'{BLOCK_WORKSPACE_MANIFEST_INVALID}: missing manifest {workspace_manifest}')
        payload = load_workspace_manifest(workspace_manifest)
        failures = validate_workspace_manifest(payload)
        if failures:
            raise ValueError('; '.join(failures))
        factor_id = str(payload.get('factor_id') or '')
        research_id = str(payload.get('research_id') or '')
        ff = Path(str(payload.get('factorforge_root') or ff)).expanduser().resolve()
    return FactorForgeContext(
        repo_root=REPO_ROOT,
        workspace_root=ff.parent,
        factorforge_root=ff,
        factor_workspace=workspace,
        factor_workspace_manifest=workspace_manifest,
        factor_id=factor_id,
        research_id=research_id,
    )
