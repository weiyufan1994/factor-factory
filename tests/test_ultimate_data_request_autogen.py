from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.run_factorforge_ultimate import data_request_candidate_from_failure, write_data_request_candidate


@dataclass
class DummyContext:
    active_root: Path
    objects_root: Path


def test_data_request_candidate_created_for_missing_intraday_datamart(tmp_path):
    ctx = DummyContext(active_root=tmp_path, objects_root=tmp_path / 'objects')
    feasibility = ctx.objects_root / 'validation' / 'data_feasibility_report__REPORT.json'
    feasibility.parent.mkdir(parents=True)
    feasibility.write_text(
        '''
        {
          "feasibility": "blocked",
          "blocked_items": [
            {
              "reason": "missing_intraday_flow_proxy_dataset",
              "missing_datasets": ["intraday_flow_distribution_moments_v1"]
            }
          ]
        }
        ''',
        encoding='utf-8',
    )

    candidate = data_request_candidate_from_failure(
        report_id='REPORT',
        command_name='validate_step3',
        output='Required clean/precomputed intraday proxy dataset is absent from the Data API catalog.',
        ctx=ctx,
    )

    assert candidate is not None
    assert candidate['schema_version'] == 'data_request_v1'
    assert candidate['requested_dataset_id'] == 'intraday_flow_distribution_moments_v1'
    assert candidate['request_type'] == 'new_datamart'
    assert candidate['boundaries']['do_not_start_clean_data'] is True


def test_data_request_candidate_not_created_for_plain_code_failure(tmp_path):
    ctx = DummyContext(active_root=tmp_path, objects_root=tmp_path / 'objects')

    candidate = data_request_candidate_from_failure(
        report_id='REPORT',
        command_name='validate_step3b',
        output='NameError: name foo is not defined',
        ctx=ctx,
    )

    assert candidate is None


def test_data_request_candidate_not_created_when_ready_feasibility_mentions_catalog(tmp_path):
    ctx = DummyContext(active_root=tmp_path, objects_root=tmp_path / 'objects')
    feasibility = ctx.objects_root / 'validation' / 'data_feasibility_report__REPORT.json'
    feasibility.parent.mkdir(parents=True)
    feasibility.write_text(
        '''
        {
          "final_result": "ready",
          "checks": [{"name": "daily_history", "status": "pass"}],
          "data_api_resolution": {
            "clean_daily_bar": {
              "dataset_id": "clean_daily_bar",
              "status": "ready",
              "access_mode": "catalog",
              "missing_datasets": []
            }
          }
        }
        ''',
        encoding='utf-8',
    )

    candidate = data_request_candidate_from_failure(
        report_id='REPORT',
        command_name='validate_step4',
        output=(
            'Data API catalog was loaded successfully. '
            'BLOCK_NO_SUCCESSFUL_BACKEND: ModuleNotFoundError: matplotlib'
        ),
        ctx=ctx,
    )

    assert candidate is None


def test_ready_feasibility_dataset_id_does_not_override_actual_missing_dataset(tmp_path):
    ctx = DummyContext(active_root=tmp_path, objects_root=tmp_path / 'objects')
    feasibility = ctx.objects_root / 'validation' / 'data_feasibility_report__REPORT.json'
    feasibility.parent.mkdir(parents=True)
    feasibility.write_text(
        '''
        {
          "final_result": "ready",
          "data_api_resolution": {
            "clean_daily_bar": {
              "dataset_id": "clean_daily_bar",
              "status": "ready",
              "missing_datasets": []
            }
          }
        }
        ''',
        encoding='utf-8',
    )

    candidate = data_request_candidate_from_failure(
        report_id='REPORT',
        command_name='validate_step4',
        output='Required clean/precomputed intraday proxy dataset is absent.',
        ctx=ctx,
    )

    assert candidate is not None
    assert candidate['requested_dataset_id'] == 'intraday_derived_datamart'


def test_write_data_request_candidate_writes_local_and_data_api_inbox(tmp_path, monkeypatch):
    data_api_root = tmp_path / 'factor-factory-data-api'
    (data_api_root / 'scripts').mkdir(parents=True)
    (data_api_root / 'scripts' / 'data_request_inbox.py').write_text('# smoke', encoding='utf-8')
    monkeypatch.setenv('FACTORFORGE_DATA_API_ROOT', str(data_api_root))
    ctx = DummyContext(active_root=tmp_path / 'research', objects_root=tmp_path / 'research' / 'objects')
    candidate = {
        'schema_version': 'data_request_v1',
        'request_id': 'REPORT__intraday_flow_distribution_moments_v1__20260615000000',
        'requested_dataset_id': 'intraday_flow_distribution_moments_v1',
        'request_type': 'new_datamart',
    }

    result = write_data_request_candidate(candidate, repo_root=tmp_path / 'factor-factory', ctx=ctx)

    assert result['status'] == 'CREATED'
    assert Path(result['local_request_path']).exists()
    assert Path(result['data_api_inbox_path']).exists()
