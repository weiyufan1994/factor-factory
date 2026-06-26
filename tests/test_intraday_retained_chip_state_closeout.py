from __future__ import annotations

import pandas as pd

from scripts.closeout_intraday_retained_chip_state import build_catalog, validate_frame


def test_closeout_catalog_declares_s3_contract():
    catalog = build_catalog(
        root='s3://bucket/factorforge/datamart/intraday_retained_chip_state/v1/',
        qa_path='s3://bucket/proofs/qa.json',
        start='20160104',
        end='20250711',
        row_count=10,
        date_count=2,
        ticker_count=5,
        research_window='IS+OOS',
    )
    entry = catalog['datasets']['intraday_retained_chip_state_v1']
    assert entry['storage'] == 's3'
    assert entry['partition_columns'] == ['trade_date']
    assert entry['metadata']['unique_key'] == ['ts_code', 'trade_date']
    assert entry['metadata']['no_future_data'] is True
    assert entry['metadata']['no_future_intraday_minutes'] is True
    assert entry['metadata']['research_window'] == 'IS+OOS'
    assert entry['freshness']['trade_date_min'] == '20160104'


def test_validate_frame_blocks_duplicate_key_and_future_flag():
    frame = pd.DataFrame(
        {
            'ts_code': ['000001.SZ', '000001.SZ'],
            'trade_date': ['20200102', '20200102'],
            'lcr_raw': [0.1, 0.2],
            'no_future_data': [True, True],
            'no_future_intraday_minutes': [True, False],
            'research_window': ['OOS', 'OOS'],
        }
    )
    result = validate_frame(frame, '20200102')
    assert result['verdict'] == 'BLOCK'
    assert 'duplicate_key_count_nonzero' in result['issues']
    assert 'no_future_intraday_minutes_not_true' in result['issues']
    assert result['research_windows'] == ['OOS']
