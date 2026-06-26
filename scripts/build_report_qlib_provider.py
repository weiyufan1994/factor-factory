#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS = REPO_ROOT / 'runs'
QLIB_REPO = REPO_ROOT.parent / 'qlib_repo'


def audit_clean_daily_snapshot(df: pd.DataFrame) -> dict:
    symbols = df['ts_code'].astype(str)
    pct_chg = pd.to_numeric(df['pct_chg'], errors='coerce')
    volume = pd.to_numeric(df['vol'], errors='coerce')
    amount = pd.to_numeric(df['amount'], errors='coerce')
    close = pd.to_numeric(df['close'], errors='coerce')
    counts = df.groupby('trade_date')['ts_code'].nunique()
    audit = {
        'rows': int(len(df)),
        'symbols': int(df['ts_code'].nunique()),
        'dates': int(df['trade_date'].nunique()),
        'date_min': str(df['trade_date'].min()),
        'date_max': str(df['trade_date'].max()),
        'bj_rows': int(symbols.str.endswith('.BJ').sum()),
        'zero_or_negative_volume_rows': int((volume <= 0).sum()),
        'zero_or_negative_amount_rows': int((amount <= 0).sum()),
        'close_lt_1_rows': int((close < 1).sum()),
        'abs_pct_chg_gt_20_rows': int((pct_chg.abs() > 20).sum()),
        'pct_chg_null_rows': int(pct_chg.isna().sum()),
        'daily_symbol_count_min': int(counts.min()) if len(counts) else 0,
        'daily_symbol_count_median': float(counts.median()) if len(counts) else 0.0,
        'daily_symbol_count_max': int(counts.max()) if len(counts) else 0,
        'days_symbol_count_le_30': int((counts <= 30).sum()) if len(counts) else 0,
    }
    hard_failures = {
        'bj_rows': audit['bj_rows'],
        'zero_or_negative_volume_rows': audit['zero_or_negative_volume_rows'],
        'zero_or_negative_amount_rows': audit['zero_or_negative_amount_rows'],
        'abs_pct_chg_gt_20_rows': audit['abs_pct_chg_gt_20_rows'],
        'pct_chg_null_rows': audit['pct_chg_null_rows'],
    }
    failed = {key: value for key, value in hard_failures.items() if value}
    if failed:
        raise SystemExit(f'clean daily snapshot failed qlib tradability audit: {failed}')
    return audit


def build_source_snapshot(report_id: str, source_csv: Path, out_dir: Path) -> tuple[Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_dir = out_dir / 'source_daily'
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    usecols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_chg', 'vol', 'amount']
    df = pd.read_csv(source_csv, usecols=usecols)
    audit = audit_clean_daily_snapshot(df)
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
        'tradability_audit': audit,
    }
    return source_dir, stats


def audit_dumped_provider(provider_dir: Path) -> dict:
    instruments_file = provider_dir / 'instruments' / 'all.txt'
    calendar_file = provider_dir / 'calendars' / 'day.txt'
    if not instruments_file.exists():
        raise SystemExit(f'missing provider instruments file: {instruments_file}')
    if not calendar_file.exists():
        raise SystemExit(f'missing provider day calendar: {calendar_file}')
    instrument_lines = [line.strip() for line in instruments_file.read_text(encoding='utf-8').splitlines() if line.strip()]
    calendar_lines = [line.strip() for line in calendar_file.read_text(encoding='utf-8').splitlines() if line.strip()]
    bj_lines = [line for line in instrument_lines if line.split()[0].upper().endswith('.BJ')]
    synthetic_lines = [
        line for line in instrument_lines
        if line.split()[0].upper().startswith('DAILY_')
    ]
    audit = {
        'provider_dir': str(provider_dir),
        'instrument_count': len(instrument_lines),
        'calendar_count': len(calendar_lines),
        'calendar_start': calendar_lines[0] if calendar_lines else None,
        'calendar_end': calendar_lines[-1] if calendar_lines else None,
        'bj_instrument_count': len(bj_lines),
        'synthetic_instrument_count': len(synthetic_lines),
        'sample_instruments': instrument_lines[:5],
    }
    if audit['instrument_count'] <= 1:
        raise SystemExit(f'provider failed instrument audit: instrument_count={audit["instrument_count"]}')
    if bj_lines:
        raise SystemExit(f'provider failed instrument audit: BJ instruments present, sample={bj_lines[:5]}')
    if synthetic_lines:
        raise SystemExit(f'provider failed instrument audit: synthetic instruments present, sample={synthetic_lines[:5]}')
    return audit


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
    ap.add_argument('--source-csv', required=True)
    ap.add_argument('--provider-dir', required=True)
    args = ap.parse_args()

    report_id = args.report_id
    source_csv = Path(args.source_csv)
    provider_dir = Path(args.provider_dir)
    build_dir = RUNS / report_id / 'qlib_build'

    if not source_csv.exists():
        raise SystemExit(f'missing source daily snapshot: {source_csv}')
    if not (QLIB_REPO / 'scripts' / 'dump_bin.py').exists():
        raise SystemExit(f'missing qlib dump_bin script under {QLIB_REPO}')

    source_dir, stats = build_source_snapshot(report_id, source_csv, build_dir)
    dump_provider(source_dir, provider_dir)
    provider_audit = audit_dumped_provider(provider_dir)
    audit_path = provider_dir / 'provider_audit.json'
    audit_path.write_text(
        json.dumps({'source_stats': stats, 'provider_audit': provider_audit}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'[OK] report_id={report_id}')
    print(f'[SOURCE] {source_dir}')
    print(f'[PROVIDER] {provider_dir}')
    print(f'[AUDIT] {audit_path}')
    print(f'[STATS] rows={stats["rows"]} symbols={stats["symbols"]} dates={stats["dates"]}')


if __name__ == '__main__':
    main()
