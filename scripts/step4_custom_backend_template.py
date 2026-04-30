#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def load_factor_values(run_dir: Path, report_id: str) -> pd.DataFrame:
    parquet_path = run_dir / f'factor_values__{report_id}.parquet'
    csv_path = run_dir / f'factor_values__{report_id}.csv'
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    raise FileNotFoundError(f'missing factor values in {run_dir}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--tag', default='custom_template')
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    report_id = args.report_id
    run_dir = root / 'runs' / report_id
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = load_factor_values(run_dir, report_id)
    row_count = int(len(df))
    date_count = int(df['trade_date'].nunique()) if 'trade_date' in df.columns else None
    ticker_count = int(df['ts_code'].nunique()) if 'ts_code' in df.columns else None
    factor_col = 'cpv_factor' if 'cpv_factor' in df.columns else (df.columns[-1] if len(df.columns) else None)

    payload = {
        'backend': 'my_custom_backtest',
        'status': 'success',
        'mode': 'custom',
        'summary': {
            'tag': args.tag,
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'factor_column': factor_col,
        },
        'metrics': {
            'row_count': row_count,
            'factor_abs_mean': float(df[factor_col].abs().mean()) if factor_col and factor_col in df.columns else None,
        },
        'artifact_paths': [],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {output_path}')


if __name__ == '__main__':
    main()
