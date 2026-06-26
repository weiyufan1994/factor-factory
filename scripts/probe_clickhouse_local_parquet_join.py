#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Probe clickhouse-local parquet join performance on isolated parquet files.')
    ap.add_argument('--clickhouse', required=True)
    ap.add_argument('--microcap', required=True)
    ap.add_argument('--flags', required=True)
    ap.add_argument('--proof-output', required=True)
    ap.add_argument('--host', default='unknown')
    ap.add_argument('--instance-id', default='unknown')
    ap.add_argument('--expected-flags-count', type=int, required=True)
    ap.add_argument('--expected-microcap-count', type=int, required=True)
    ap.add_argument('--expected-join-count', type=int, required=True)
    ap.add_argument('--expected-investable-core', type=int, required=True)
    ap.add_argument('--verified-download-sha256')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    clickhouse = Path(args.clickhouse)
    microcap = Path(args.microcap)
    flags = Path(args.flags)
    proof_output = Path(args.proof_output)
    version = _run([str(clickhouse), 'local', '--version']).strip()
    timings = {}
    flags_count, timings['flags_count'] = _query_int(clickhouse, f"SELECT count() FROM file('{flags}', Parquet)")
    microcap_count, timings['microcap_count'] = _query_int(clickhouse, f"SELECT count() FROM file('{microcap}', Parquet)")
    join_raw, timings['microcap_flags_join'] = _query(
        clickhouse,
        f"""
        SELECT
            count(),
            sum(if(lower(toString(f.is_investable_core)) IN ('true', '1'), 1, 0))
        FROM file('{microcap}', Parquet) AS m
        LEFT JOIN file('{flags}', Parquet) AS f
        USING (trade_date, ts_code)
        """,
    )
    join_parts = join_raw.split()
    join_count = int(join_parts[0])
    investable_core = int(join_parts[1])
    expected = {
        'flags_count': args.expected_flags_count,
        'microcap_count': args.expected_microcap_count,
        'join_count': args.expected_join_count,
        'investable_core': args.expected_investable_core,
    }
    observed = {
        'flags_count': flags_count,
        'microcap_count': microcap_count,
        'join_count': join_count,
        'investable_core': investable_core,
    }
    issues = [
        f'{key}_mismatch:{observed[key]}!=expected:{value}'
        for key, value in expected.items()
        if observed[key] != value
    ]
    proof = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'host': args.host,
        'instance_id': args.instance_id,
        'engine': 'clickhouse-local',
        'clickhouse_version': version,
        'verified_download_sha256': args.verified_download_sha256,
        'runtime_clickhouse_sha256': _sha256(clickhouse),
        'runtime_clickhouse_size_bytes': clickhouse.stat().st_size,
        'data_window': {'start': '20240102', 'end': '20240329'},
        'data_paths': {'microcap': str(microcap), 'flags': str(flags)},
        'input_file_sizes': {'microcap_bytes': microcap.stat().st_size, 'flags_bytes': flags.stat().st_size},
        'expected': expected,
        'observed': observed,
        'timings': timings,
        'isolation': {
            'root': str(proof_output.parent),
            'uses_research_worker': False,
            'writes_research_artifacts': False,
            'starts_clickhouse_server': False,
            'creates_aws_resources': False,
        },
        'issues': issues,
        'generated_at_epoch': time.time(),
    }
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(proof, indent=2), encoding='utf-8')
    print(json.dumps({'proof': str(proof_output), 'verdict': proof['verdict'], 'issues': issues, 'timings': timings}, indent=2))
    return 0 if proof['verdict'] == 'ACCEPT' else 1


def _query_int(clickhouse: Path, sql: str) -> tuple[int, float]:
    raw, seconds = _query(clickhouse, sql)
    return int(raw.strip()), seconds


def _query(clickhouse: Path, sql: str) -> tuple[str, float]:
    start = time.perf_counter()
    raw = _run([str(clickhouse), 'local', '--query', sql])
    return raw.strip(), time.perf_counter() - start


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())
