from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_preflight_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_intraday_operator_worker_preflight.py'
    spec = importlib.util.spec_from_file_location('run_intraday_operator_worker_preflight', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_preflight_blocks_busy_research_process(tmp_path):
    preflight = _load_preflight_module()
    output_path = tmp_path / 'preflight.json'
    process_rows = [
        {
            'pid': 101,
            'cpu_percent': 92.0,
            'memory_percent': 8.0,
            'command': 'python factorforge step4 full-window run',
        }
    ]

    exit_code = preflight.main([
        '--output-path',
        str(output_path),
        '--load1',
        '1.0',
        '--cpu-count',
        '16',
        '--available-memory-gb',
        '32',
        '--process-snapshot-json',
        json.dumps(process_rows),
        '--protected-process-pattern',
        'factorforge',
        '--max-protected-process-cpu',
        '20',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert 'protected_process_active:factorforge' in payload['issues']
    assert payload['safety']['starts_backfill'] is False
    assert payload['safety']['writes_datamart'] is False


def test_worker_preflight_accepts_idle_worker(tmp_path):
    preflight = _load_preflight_module()
    output_path = tmp_path / 'preflight.json'

    exit_code = preflight.main([
        '--output-path',
        str(output_path),
        '--load1',
        '2.0',
        '--cpu-count',
        '16',
        '--available-memory-gb',
        '64',
        '--process-snapshot-json',
        '[]',
        '--max-load-per-cpu',
        '0.5',
        '--min-available-memory-gb',
        '16',
    ])

    payload = json.loads(output_path.read_text())
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['issues'] == []
    assert payload['metrics']['load1_per_cpu'] == 0.125
