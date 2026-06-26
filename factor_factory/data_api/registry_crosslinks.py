from __future__ import annotations

from dataclasses import dataclass
from typing import Any


KNOWN_BASE_DATASETS = {
    'clean_daily_bar',
    'daily_basic_backtest_base',
    'minute_bar',
    'prepared_minute_bar_v1',
    'qlib_daily_provider',
    'tradability_risk_flags_daily',
    'standard_full_market_universe',
    'microcap_universe',
    'index_weight_universe',
    'research_side_transform_only',
    'any_feature_datamart',
}


@dataclass(frozen=True)
class RegistryCrosslinkIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def validate_registry_crosslinks(
    *,
    feature_precompute: dict[str, Any],
    feature_family: dict[str, Any],
    data_team_ops: dict[str, Any],
    known_base_datasets: set[str] | None = None,
) -> list[RegistryCrosslinkIssue]:
    issues: list[RegistryCrosslinkIssue] = []
    known = set(known_base_datasets or KNOWN_BASE_DATASETS)
    dataset_entries = [entry for entry in feature_precompute.get('datasets') or [] if isinstance(entry, dict)]
    family_entries = [entry for entry in feature_family.get('feature_families') or [] if isinstance(entry, dict)]
    ops_entries = [entry for entry in data_team_ops.get('tasks') or [] if isinstance(entry, dict)]

    dataset_ids = {str(entry.get('dataset_id')) for entry in dataset_entries if entry.get('dataset_id')}
    family_dataset_ids = {str(entry.get('recommended_dataset')) for entry in family_entries if entry.get('recommended_dataset')}

    for idx, family in enumerate(family_entries):
        recommended = str(family.get('recommended_dataset') or '')
        policy = str(family.get('precompute_policy') or '')
        if policy in {'precompute_now', 'precompute_after_source_ready', 'model_specific_only'}:
            if recommended not in dataset_ids and recommended not in known:
                issues.append(
                    RegistryCrosslinkIssue(
                        f'feature_families[{idx}].recommended_dataset',
                        f'recommended dataset is not in feature precompute registry or known base datasets: {recommended}',
                    )
                )

    for idx, dataset in enumerate(dataset_entries):
        dataset_id = str(dataset.get('dataset_id') or '')
        priority = str(dataset.get('priority') or '')
        status = str(dataset.get('status') or '')
        if priority in {'P0', 'P1'} and status in {'production_candidate', 'read_only_builder_available', 'planned'}:
            if dataset_id not in family_dataset_ids:
                issues.append(
                    RegistryCrosslinkIssue(
                        f'datasets[{idx}].dataset_id',
                        'P0/P1 candidate or planned dataset must be referenced by a feature family recommended_dataset',
                    )
                )

    all_known = dataset_ids | known
    for task_idx, task in enumerate(ops_entries):
        for ds_idx, dataset_id in enumerate(task.get('datasets') or []):
            if str(dataset_id) not in all_known:
                issues.append(
                    RegistryCrosslinkIssue(
                        f'tasks[{task_idx}].datasets[{ds_idx}]',
                        f'ops dataset is neither a feature precompute dataset nor known base dataset: {dataset_id}',
                    )
                )
    return issues


def registry_crosslink_summary(
    *,
    feature_precompute: dict[str, Any],
    feature_family: dict[str, Any],
    data_team_ops: dict[str, Any],
) -> dict[str, Any]:
    dataset_entries = [entry for entry in feature_precompute.get('datasets') or [] if isinstance(entry, dict)]
    family_entries = [entry for entry in feature_family.get('feature_families') or [] if isinstance(entry, dict)]
    ops_entries = [entry for entry in data_team_ops.get('tasks') or [] if isinstance(entry, dict)]
    dataset_ids = {str(entry.get('dataset_id')) for entry in dataset_entries if entry.get('dataset_id')}
    family_links = {
        str(entry.get('family_id')): str(entry.get('recommended_dataset'))
        for entry in family_entries
        if entry.get('family_id') and entry.get('recommended_dataset')
    }
    ops_dataset_refs = sorted({
        str(dataset_id)
        for task in ops_entries
        for dataset_id in (task.get('datasets') or [])
        if str(dataset_id)
    })
    return {
        'dataset_count': len(dataset_ids),
        'family_link_count': len(family_links),
        'ops_dataset_ref_count': len(ops_dataset_refs),
        'family_links': family_links,
        'ops_dataset_refs': ops_dataset_refs,
    }
