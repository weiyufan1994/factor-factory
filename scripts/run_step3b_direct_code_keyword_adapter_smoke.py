#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import json
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_STEP3B = REPO_ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3b.py'


def load_run_step3b_module():
    spec = importlib.util.spec_from_file_location('factorforge_step3b_keyword_adapter_smoke_run_step3b', RUN_STEP3B)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {RUN_STEP3B}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_generated(path: Path):
    spec = importlib.util.spec_from_file_location('factorforge_step3b_keyword_adapter_generated', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load generated module {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    run_step3b = load_run_step3b_module()
    daily_source = '''
import pandas as pd

def compute_factor(df):
    out = df[["ts_code", "trade_date"]].copy()
    out["factor_value"] = pd.to_numeric(df["close"], errors="coerce") * 2.0
    return out
'''
    minute_source = '''
import pandas as pd

def compute_factor(df):
    out = df[["ts_code", "trade_date"]].copy()
    out["factor_value"] = pd.to_numeric(df["amount"], errors="coerce") / 100.0
    return out
'''
    wrapped = run_step3b.ensure_direct_code_keyword_adapter(daily_source)
    minute_wrapped = run_step3b.ensure_direct_code_keyword_adapter(minute_source)
    with tempfile.TemporaryDirectory(prefix='factorforge_step3b_keyword_adapter_') as tmp:
        generated = Path(tmp) / 'generated.py'
        generated.write_text(wrapped, encoding='utf-8')
        module = import_generated(generated)
        signature = inspect.signature(module.compute_factor)
        fixture = pd.DataFrame(
            [
                {'ts_code': '000001.SZ', 'trade_date': '20200102', 'close': 10.0},
                {'ts_code': '000001.SZ', 'trade_date': '20200103', 'close': 11.0},
            ]
        )
        result = module.compute_factor(daily_df=fixture, minute_df=None)
        minute_generated = Path(tmp) / 'generated_minute.py'
        minute_generated.write_text(minute_wrapped, encoding='utf-8')
        minute_module = import_generated(minute_generated)
        minute_fixture = pd.DataFrame(
            [
                {'ts_code': '000001.SZ', 'trade_date': '20200102', 'amount': 300.0},
                {'ts_code': '000001.SZ', 'trade_date': '20200103', 'amount': 500.0},
            ]
        )
        minute_result = minute_module.compute_factor(daily_df=fixture, minute_df=minute_fixture)
    ok = (
        'daily_df' in signature.parameters
        and 'minute_df' in signature.parameters
        and list(result.columns) == ['ts_code', 'trade_date', 'factor_value']
        and result['factor_value'].tolist() == [20.0, 22.0]
        and minute_result['factor_value'].tolist() == [3.0, 5.0]
    )
    summary = {
        'verdict': 'ACCEPT' if ok else 'REJECT',
        'signature': str(signature),
        'rows': int(len(result)),
        'factor_values': result['factor_value'].tolist(),
        'ambiguous_single_arg_minute_values': minute_result['factor_value'].tolist(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
