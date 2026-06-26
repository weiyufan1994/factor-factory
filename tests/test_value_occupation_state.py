from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result
from factor_factory.data_api.value_occupation import (
    DATASET_ID,
    P0_COLUMNS,
    ValueOccupationParams,
    build_catalog_entry,
    derive_intraday_value_occupation_state,
    write_partitioned_datamart,
)


def minute_fixture() -> pd.DataFrame:
    rows = []
    for trade_date, base in [('20240102', 10.0), ('20240103', 11.0)]:
        for ts_code, bump in [('000001.SZ', 0.0), ('000002.SZ', 1.0)]:
            for trade_time, close, amount in [
                ('09:31:00', base + bump, 1000.0),
                ('14:49:00', base + bump + 0.5, 2000.0),
                ('14:51:00', base + bump + 50.0, 999999.0),
            ]:
                rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'trade_time': f'{trade_date} {trade_time}',
                    'open': close,
                    'high': close,
                    'low': close,
                    'close': close,
                    'vol': amount / close,
                    'amount': amount,
                })
    return pd.DataFrame(rows)


def write_catalog(path: Path, dataset: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({'catalog_version': 'factorforge_data_catalog_v1', 'datasets': {DATASET_ID: dataset}}, indent=2),
        encoding='utf-8',
    )


def test_value_occupation_p0_state_respects_cutoff_and_excludes_research_scores():
    params = ValueOccupationParams(lookback_days=2, cutoff_time='14:50:00', min_minutes=2)

    result = derive_intraday_value_occupation_state(minute_fixture(), params)

    assert result.columns.tolist() == P0_COLUMNS
    assert 'support_minus_overhang' not in result.columns
    assert 'below_cost_guarded_support' not in result.columns
    row = result[(result['ts_code'] == '000001.SZ') & (result['trade_date'] == '20240103')].iloc[0]
    assert row['reference_price'] == 11.5
    assert row['current_day_minute_count'] == 2
    assert row['minute_count'] == 4
    assert bool(row['no_future_intraday_minutes']) is True
    assert 0 <= row['lower_support_ratio'] <= 1
    assert 0 <= row['upper_overhang_ratio'] <= 1
    assert row['amount_total'] == 6000.0


def test_value_occupation_catalog_read_smoke_uses_cutoff_and_lookback_unique_key(tmp_path):
    minute = minute_fixture()
    state_1450 = derive_intraday_value_occupation_state(
        minute,
        ValueOccupationParams(lookback_days=2, cutoff_time='14:50:00', min_minutes=2),
    )
    state_1000 = derive_intraday_value_occupation_state(
        minute,
        ValueOccupationParams(lookback_days=2, cutoff_time='10:00:00', min_minutes=1),
    )
    state = pd.concat([state_1450, state_1000], ignore_index=True)
    output_root = write_partitioned_datamart(state, tmp_path / 'datamart')
    qa_path = tmp_path / 'qa.json'
    catalog = tmp_path / 'catalog.json'
    write_catalog(catalog, build_catalog_entry(output_root, qa_path, '20240102', '20240103'))

    result = DataApiClient.from_catalog(catalog).fetch(
        DataQuery(DATASET_ID, '20240103', '20240103', 'a_share_all', ['lower_support_ratio'])
    )

    assert result.status == 'ready'
    assert validate_data_api_result(result).result == 'PASS'
    assert result.coverage.duplicate_key_count == 0
    assert result.frame.columns.tolist() == [
        'ts_code',
        'trade_date',
        'cutoff_time',
        'lookback_days',
        'lower_support_ratio',
    ]
    assert set(result.frame['cutoff_time']) == {'10:00:00', '14:50:00'}
