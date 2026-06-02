#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.formula import parse_formula
from factor_factory.formula.field_aliases import (
    materialize_standard_formula_fields,
    standard_formula_fields_contract,
    validate_standard_formula_fields_contract,
)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def result(case: str, ok: bool, **extra: Any) -> dict[str, Any]:
    return {'case': case, 'ok': bool(ok), **extra}


def valid_contract_passes() -> dict[str, Any]:
    formula_ir = parse_formula('rank(vwap) + rank(adv20) + rank(returns) + rank(volume)')
    contract = standard_formula_fields_contract(formula_ir.get('required_fields') or [], formula_text=formula_ir.get('formula_text'))
    failures = validate_standard_formula_fields_contract(contract)
    required = set(contract.get('required_standard_formula_fields') or [])
    ok = (
        formula_ir.get('parse_status') == 'success'
        and not failures
        and {'vwap', 'adv20', 'returns', 'volume'}.issubset(required)
    )
    return result('valid_alpha101_standard_formula_fields_contract_passes', ok, failures=failures, required=sorted(required))


def formula_text_recovers_missing_required_fields() -> dict[str, Any]:
    formula_text = 'rank(vwap) + rank(adv20) + returns + volume'
    contract = standard_formula_fields_contract(['close'], formula_text=formula_text)
    failures = validate_standard_formula_fields_contract(contract)
    required = set(contract.get('required_standard_formula_fields') or [])
    formula_tokens = set(contract.get('formula_text_standard_fields') or [])
    ok = (
        not failures
        and {'vwap', 'adv20', 'returns', 'volume'}.issubset(required)
        and {'vwap', 'adv20', 'returns', 'volume'}.issubset(formula_tokens)
    )
    return result(
        'formula_text_standard_fields_recovered_when_required_fields_incomplete',
        ok,
        failures=failures,
        required=sorted(required),
        formula_text_standard_fields=sorted(formula_tokens),
    )


def formula_text_contract_mismatch_blocks() -> dict[str, Any]:
    contract = standard_formula_fields_contract([], formula_text='rank(vwap)+rank(adv20)')
    contract['required_standard_formula_fields'] = []
    contract['fields'] = {}
    failures = validate_standard_formula_fields_contract(contract)
    ok = any('BLOCK_STANDARD_FORMULA_FIELDS_MISSING' in failure and 'formula_text standard fields' in failure for failure in failures)
    return result('formula_text_standard_field_contract_mismatch_blocks', ok, failures=failures)


def missing_source_blocks() -> dict[str, Any]:
    contract = standard_formula_fields_contract(['vwap'], formula_text='rank(vwap)')
    contract['fields']['vwap'].pop('source_candidates', None)
    failures = validate_standard_formula_fields_contract(contract)
    ok = any('BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING' in failure for failure in failures)
    return result('standard_formula_field_source_missing_blocks', ok, failures=failures)


def leakage_policy_missing_blocks() -> dict[str, Any]:
    contract = standard_formula_fields_contract(['adv20'], formula_text='rank(adv20)')
    contract['fields']['adv20'].pop('leakage_policy', None)
    failures = validate_standard_formula_fields_contract(contract)
    ok = any('BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING' in failure for failure in failures)
    return result('standard_formula_field_leakage_policy_missing_blocks', ok, failures=failures)


def materializes_standard_fields(root: Path) -> dict[str, Any]:
    contract = standard_formula_fields_contract(['vwap', 'returns', 'adv20', 'volume'], formula_text='rank(vwap)+rank(adv20)+rank(returns)+rank(volume)')
    rows = []
    for ticker in ['000001.SZ', '000002.SZ']:
        for idx, trade_date in enumerate(['20200101', '20200102', '20200103']):
            close = 10.0 + idx
            vol = 1000.0 + idx * 100.0
            rows.append({
                'ts_code': ticker,
                'trade_date': trade_date,
                'close': close,
                'pre_close': close - 0.5,
                'pct_chg': 5.0,
                'vol': vol,
                'amount': close * vol,
            })
    frame, profile = materialize_standard_formula_fields(pd.DataFrame(rows), contract)
    out = root / 'objects' / 'validation' / 'alpha101_standard_fields_materialized.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    ok = (
        {'volume', 'returns', 'vwap', 'adv20'}.issubset(frame.columns)
        and not profile.get('missing_fields')
        and frame['adv20'].notna().all()
    )
    return result(
        'step3a_standard_fields_materialized_pass',
        ok,
        materialized_fields=profile.get('materialized_fields'),
        missing_fields=profile.get('missing_fields'),
        artifact=str(out),
    )


def missing_materialization_blocks() -> dict[str, Any]:
    contract = standard_formula_fields_contract(['vwap'], formula_text='rank(vwap)')
    frame, profile = materialize_standard_formula_fields(pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20200101', 'vol': 1.0}]), contract)
    ok = 'vwap' in (profile.get('missing_fields') or []) and 'vwap' not in frame.columns
    return result('step3a_standard_field_not_materialized_blocks', ok, profile=profile)


def verdict_for(cases: list[dict[str, Any]]) -> str:
    return 'ACCEPT' if all(case.get('ok') for case in cases) else 'BLOCK'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--root', default='/tmp/factorforge_alpha101_standard_field_contract_smoke')
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    cases = [
        valid_contract_passes(),
        formula_text_recovers_missing_required_fields(),
        formula_text_contract_mismatch_blocks(),
        missing_source_blocks(),
        leakage_policy_missing_blocks(),
        materializes_standard_fields(root),
        missing_materialization_blocks(),
    ]
    verdict = verdict_for(cases)
    summary = {
        'verdict': verdict,
        'canonical_pollution': False,
        'cases': cases,
    }
    summary_path = root / 'objects' / 'validation' / 'alpha101_standard_field_contract_smoke_summary.json'
    write_json(summary_path, summary)
    print(json.dumps({'summary_path': str(summary_path), 'verdict': verdict}, ensure_ascii=False))
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
