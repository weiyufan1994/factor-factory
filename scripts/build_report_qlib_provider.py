#!/usr/bin/env python3
from __future__ import annotations

raise SystemExit(
    "BLOCKED_CANONICAL_OUTPUT: scripts/build_report_qlib_provider.py previously defaulted to canonical runs/<report_id> provider output. "
    "Keep it blocked until it is manifest-bound or requires explicit non-canonical --source-csv and --provider-dir."
)

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS = REPO_ROOT / 'runs'
QLIB_REPO = REPO_ROOT.parent / 'qlib_repo'


def build_source_snapshot(report_id: str, source_csv: Path, out_dir: Path) -> tuple[Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_dir = out_dir / 'source_daily'
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    usecols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_chg', 'vol', 'amount']
    df = pd.read_csv(source_csv, usecols=usecols)
    df = df.rename(columns={'ts_code': 'symbol', 'trade_date': 'date', 'vol': 'volume'})
    df['date'] = pd.to_datetime(df['date'].astype(str), format='%Y%m%d', errors='raise').dt.strftime('%Y-%m-%d')
    df['change'] = pd.to_numeric(df['pct_chg'], errors='coerce') / 100.0
    df['factor'] = 1.0
    df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'factor', 'change', 'amount', 'pre_close']]
    df = df.sort_values(['symbol', 'date'])

    for symbol, sdf in df.groupby('symbol', sort=True):
        sdf.to_csv(source_dir / f'{symbol}.csv', index=False)

    stats = {
        'rows': int(len(df)),
        'symbols': int(df['symbol'].nunique()),
        'dates': int(df['date'].nunique()),
        'source_dir': str(source_dir),
    }
    return source_dir, stats


def dump_provider(source_dir: Path, provider_dir: Path) -> None:
    if provider_dir.exists():
        shutil.rmtree(provider_dir)
    provider_dir.parent.mkdir(parents=True, exist_ok=True)

    dump_bin = QLIB_REPO / 'scripts' / 'dump_bin.py'
    cmd = [
        sys.executable,
        str(dump_bin),
        'dump_all',
        '--data_path',
        str(source_dir),
        '--qlib_dir',
        str(provider_dir),
        '--freq',
        'day',
        '--date_field_name',
        'date',
        '--symbol_field_name',
        'symbol',
        '--include_fields',
        'open,high,low,close,volume,factor,change,amount,pre_close',
        '--file_suffix',
        '.csv',
    ]
    env = dict(**__import__('os').environ)
    current_pythonpath = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f'{QLIB_REPO}:{current_pythonpath}' if current_pythonpath else str(QLIB_REPO)
    subprocess.run(cmd, check=True, env=env)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--source-csv')
    ap.add_argument('--provider-dir')
    args = ap.parse_args()

    report_id = args.report_id
    source_csv = Path(args.source_csv) if args.source_csv else RUNS / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'
    provider_dir = Path(args.provider_dir) if args.provider_dir else RUNS / report_id / 'qlib_provider'
    build_dir = RUNS / report_id / 'qlib_build'

    if not source_csv.exists():
        raise SystemExit(f'missing source daily snapshot: {source_csv}')
    if not (QLIB_REPO / 'scripts' / 'dump_bin.py').exists():
        raise SystemExit(f'missing qlib dump_bin script under {QLIB_REPO}')

    source_dir, stats = build_source_snapshot(report_id, source_csv, build_dir)
    dump_provider(source_dir, provider_dir)
    print(f'[OK] report_id={report_id}')
    print(f'[SOURCE] {source_dir}')
    print(f'[PROVIDER] {provider_dir}')
    print(f'[STATS] rows={stats["rows"]} symbols={stats["symbols"]} dates={stats["dates"]}')


if __name__ == '__main__':
    main()
