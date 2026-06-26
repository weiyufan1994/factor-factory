#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_PROTECTED_PATTERNS = [
    'factorforge',
    'factor_forge',
    'factor_research',
    'rdagent',
    'qlib_backtest',
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Check whether a worker is idle enough for a bounded operator benchmark.')
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--max-load-per-cpu', type=float, default=0.75)
    parser.add_argument('--min-available-memory-gb', type=float, default=16.0)
    parser.add_argument('--max-protected-process-cpu', type=float, default=25.0)
    parser.add_argument('--protected-process-pattern', action='append', default=[])
    parser.add_argument('--load1', type=float)
    parser.add_argument('--cpu-count', type=int)
    parser.add_argument('--available-memory-gb', type=float)
    parser.add_argument('--process-snapshot-json')
    return parser.parse_args(argv)


def _available_memory_gb() -> float | None:
    meminfo = Path('/proc/meminfo')
    if not meminfo.exists():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith('MemAvailable:'):
            parts = line.split()
            if len(parts) >= 2:
                return float(parts[1]) / 1024.0 / 1024.0
    return None


def _parse_ps_output(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        pid, cpu, mem, command, args = parts
        try:
            cpu_percent = float(cpu)
            memory_percent = float(mem)
        except ValueError:
            continue
        rows.append({
            'pid': int(pid),
            'cpu_percent': cpu_percent,
            'memory_percent': memory_percent,
            'command': f'{command} {args}'.strip(),
        })
    return rows


def _process_snapshot() -> list[dict[str, Any]]:
    result = subprocess.run(
        ['ps', '-eo', 'pid=,pcpu=,pmem=,comm=,args='],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return _parse_ps_output(result.stdout)


def _matching_busy_processes(
    *,
    rows: list[dict[str, Any]],
    protected_patterns: list[str],
    max_cpu: float,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    compiled = [(pattern, re.compile(pattern, re.IGNORECASE)) for pattern in protected_patterns]
    for row in rows:
        command = str(row.get('command') or '')
        cpu = float(row.get('cpu_percent') or 0.0)
        if cpu < float(max_cpu):
            continue
        for pattern, regex in compiled:
            if regex.search(command):
                enriched = dict(row)
                enriched['matched_pattern'] = pattern
                matches.append(enriched)
                break
    return matches


def evaluate_preflight(
    *,
    load1: float,
    cpu_count: int,
    available_memory_gb: float | None,
    process_rows: list[dict[str, Any]],
    protected_patterns: list[str],
    max_load_per_cpu: float,
    min_available_memory_gb: float,
    max_protected_process_cpu: float,
) -> dict[str, Any]:
    issues: list[str] = []
    cpu_count_safe = max(int(cpu_count), 1)
    load1_per_cpu = float(load1) / float(cpu_count_safe)
    if load1_per_cpu > float(max_load_per_cpu):
        issues.append('load1_per_cpu_above_limit')
    if available_memory_gb is None:
        issues.append('available_memory_unavailable')
    elif float(available_memory_gb) < float(min_available_memory_gb):
        issues.append('available_memory_below_minimum')
    busy_processes = _matching_busy_processes(
        rows=process_rows,
        protected_patterns=protected_patterns,
        max_cpu=float(max_protected_process_cpu),
    )
    for row in busy_processes:
        issues.append(f"protected_process_active:{row.get('matched_pattern')}")
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'metrics': {
            'load1': float(load1),
            'cpu_count': int(cpu_count_safe),
            'load1_per_cpu': load1_per_cpu,
            'available_memory_gb': available_memory_gb,
            'protected_busy_process_count': len(busy_processes),
            'protected_busy_processes': busy_processes[:20],
        },
        'thresholds': {
            'max_load_per_cpu': float(max_load_per_cpu),
            'min_available_memory_gb': float(min_available_memory_gb),
            'max_protected_process_cpu': float(max_protected_process_cpu),
            'protected_process_patterns': protected_patterns,
        },
        'safety': {
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load1 = float(args.load1) if args.load1 is not None else float(os.getloadavg()[0])
    cpu_count = int(args.cpu_count) if args.cpu_count is not None else int(os.cpu_count() or 1)
    available_memory = (
        float(args.available_memory_gb)
        if args.available_memory_gb is not None
        else _available_memory_gb()
    )
    if args.process_snapshot_json:
        process_rows = json.loads(args.process_snapshot_json)
    else:
        process_rows = _process_snapshot()
    patterns = list(args.protected_process_pattern or []) or list(DEFAULT_PROTECTED_PATTERNS)
    payload = evaluate_preflight(
        load1=load1,
        cpu_count=cpu_count,
        available_memory_gb=available_memory,
        process_rows=process_rows,
        protected_patterns=patterns,
        max_load_per_cpu=float(args.max_load_per_cpu),
        min_available_memory_gb=float(args.min_available_memory_gb),
        max_protected_process_cpu=float(args.max_protected_process_cpu),
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
