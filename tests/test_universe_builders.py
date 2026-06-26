from __future__ import annotations

import pandas as pd

from scripts.download_csi_index_weight_universe import month_ranges
from factor_factory.data_api.universe_builders import (
    build_index_weight_universe,
    build_microcap_universe,
    build_standard_market_universe,
    build_tradability_risk_flags_daily,
    expand_index_weight_universe_daily,
)


def test_standard_market_universe_excludes_top_tail_bottom_tail_and_small_caps():
    frame = pd.DataFrame({
        'ts_code': [f'{idx:06d}.SZ' for idx in range(1, 13)],
        'trade_date': ['20240102'] * 12,
        'circ_mv': [
            1_200_000,
            1_100_000,
            1_000_000,
            900_000,
            800_000,
            700_000,
            600_000,
            500_000,
            400_000,
            300_000,
            40_000,
            None,
        ],
        'total_mv': [
            1_210_000,
            1_110_000,
            1_010_000,
            910_000,
            810_000,
            710_000,
            610_000,
            510_000,
            410_000,
            310_000,
            60_000,
            45_000,
        ],
    })

    result = build_standard_market_universe(frame)

    selected = result[result['in_universe']]['ts_code'].tolist()
    assert selected == [
        '000003.SZ',
        '000004.SZ',
        '000005.SZ',
        '000006.SZ',
        '000007.SZ',
        '000008.SZ',
        '000009.SZ',
        '000010.SZ',
    ]
    assert result.loc[result['ts_code'] == '000011.SZ', 'market_cap'].item() == 40_000
    assert result.loc[result['ts_code'] == '000011.SZ', 'excluded_small_cap'].item()
    assert result.loc[result['ts_code'] == '000012.SZ', 'market_cap_source'].item() == 'total_mv'


def test_index_weight_universe_normalizes_codes_and_deduplicates():
    raw = pd.DataFrame({
        'index_code': ['000300.SH', '000300.SH', '000905.SH'],
        'con_code': ['000001.SZ', '000001.SZ', '600000.SH'],
        'trade_date': ['20240102', '20240102', '20240102'],
        'weight': ['1.23', '1.25', 0.5],
    })
    names = {'000300.SH': '沪深300', '000905.SH': '中证500'}

    result = build_index_weight_universe(raw, index_names=names)

    assert result.to_dict('records') == [
        {
            'universe_id': 'csi300',
            'index_code': '000300.SH',
            'index_name': '沪深300',
            'trade_date': '20240102',
            'ts_code': '000001.SZ',
            'weight': 1.25,
            'in_universe': True,
        },
        {
            'universe_id': 'csi500',
            'index_code': '000905.SH',
            'index_name': '中证500',
            'trade_date': '20240102',
            'ts_code': '600000.SH',
            'weight': 0.5,
            'in_universe': True,
        },
    ]


def test_microcap_universe_excludes_risky_names_new_untradable_and_selects_smallest_eligible():
    trade_date = '20240301'
    codes = [f'{idx:06d}.SZ' for idx in range(1, 21)]
    frame = pd.DataFrame({
        'ts_code': codes,
        'trade_date': [trade_date] * len(codes),
        'circ_mv': [
            40_000,
            100_000,
            110_000,
            120_000,
            130_000,
            140_000,
            150_000,
            160_000,
            170_000,
            180_000,
            190_000,
            200_000,
            210_000,
            220_000,
            230_000,
            240_000,
            250_000,
            260_000,
            270_000,
            280_000,
        ],
        'total_mv': [
            50_000,
            101_000,
            111_000,
            121_000,
            131_000,
            141_000,
            151_000,
            161_000,
            171_000,
            181_000,
            191_000,
            201_000,
            211_000,
            221_000,
            231_000,
            241_000,
            251_000,
            261_000,
            271_000,
            281_000,
        ],
    })
    stock_basic = pd.DataFrame({
        'ts_code': codes,
        'name': [
            '正常A',
            '正常B',
            '*ST 风险',
            '正常新股',
            '正常停牌',
            '退市风险',
            '正常7',
            '正常8',
            '正常9',
            '正常10',
            '正常11',
            '正常12',
            '正常13',
            '正常14',
            '正常15',
            '正常16',
            '正常17',
            '正常18',
            '正常19',
            '正常20',
        ],
        'list_status': ['L', 'L', 'L', 'L', 'L', 'D'] + ['L'] * 14,
        'list_date': ['20200101', '20200101', '20200101', '20240220', '20200101', '20200101'] + ['20200101'] * 14,
    })
    trade_calendar = pd.DataFrame({
        'cal_date': pd.date_range('20200101', trade_date, freq='D').strftime('%Y%m%d'),
        'is_open': 1,
    })
    daily_tradability = pd.DataFrame({
        'ts_code': codes,
        'trade_date': [trade_date] * len(codes),
        'vol': [100.0, 100.0, 100.0, 100.0, 0.0] + [100.0] * 15,
        'amount': [1000.0] * len(codes),
        'close': [10.0] * len(codes),
    })

    result = build_microcap_universe(
        frame,
        stock_basic=stock_basic,
        trade_calendar=trade_calendar,
        daily_tradability=daily_tradability,
    )

    small10 = result[(result['universe_id'] == 'microcap_small10') & result['in_universe']]
    small20 = result[(result['universe_id'] == 'microcap_small20') & result['in_universe']]
    assert small10['ts_code'].tolist() == ['000007.SZ', '000008.SZ']
    assert small20['ts_code'].tolist() == ['000007.SZ', '000008.SZ', '000009.SZ']
    assert result.duplicated(['universe_id', 'trade_date', 'ts_code']).sum() == 0

    base = result[result['universe_id'] == 'microcap_small20'].set_index('ts_code')
    assert base.loc['000001.SZ', 'excluded_small_cap']
    assert base.loc['000002.SZ', 'excluded_bottom_market_cap']
    assert base.loc['000003.SZ', 'excluded_st']
    assert base.loc['000004.SZ', 'excluded_new_stock']
    assert base.loc['000005.SZ', 'excluded_untradable']
    assert base.loc['000006.SZ', 'excluded_major_risk']
    assert not base.loc['000007.SZ', 'excluded_bottom_market_cap']
    assert base.loc['000007.SZ', 'is_eligible_after_exclusion']


def test_tradability_risk_flags_daily_separates_core_and_500m_investability():
    trade_date = '20240301'
    codes = [f'{idx:06d}.SZ' for idx in range(1, 8)]
    daily = pd.DataFrame({
        'ts_code': codes,
        'trade_date': [trade_date] * len(codes),
        'vol': [100.0, 100.0, 100.0, 100.0, 0.0, 100.0, 100.0],
        'amount': [1000.0] * len(codes),
        'close': [10.0] * len(codes),
    })
    daily_basic = pd.DataFrame({
        'ts_code': codes,
        'trade_date': [trade_date] * len(codes),
        'circ_mv': [40_000, 100_000, 110_000, 120_000, 130_000, 140_000, None],
        'total_mv': [45_000, 101_000, 111_000, 121_000, 131_000, 141_000, 142_000],
    })
    stock_basic = pd.DataFrame({
        'ts_code': codes,
        'name': ['正常小市值', '*ST 风险', '正常新股', '退市风险', '正常停牌', '正常6', '正常7'],
        'list_status': ['L', 'L', 'L', 'D', 'L', 'L', 'L'],
        'list_date': ['20200101', '20200101', '20240220', '20200101', '20200101', '20200101', '20200101'],
    })
    trade_calendar = pd.DataFrame({
        'cal_date': pd.date_range('20200101', trade_date, freq='D').strftime('%Y%m%d'),
        'is_open': 1,
    })

    result_frame = build_tradability_risk_flags_daily(
        daily,
        daily_basic=daily_basic,
        stock_basic=stock_basic,
        trade_calendar=trade_calendar,
    )
    assert result_frame.duplicated(['trade_date', 'ts_code']).sum() == 0
    result = result_frame.set_index('ts_code')

    assert result.loc['000001.SZ', 'excluded_small_cap']
    assert result.loc['000001.SZ', 'is_investable_core']
    assert not result.loc['000001.SZ', 'is_investable_500m']
    assert result.loc['000002.SZ', 'excluded_st']
    assert result.loc['000003.SZ', 'excluded_new_stock']
    assert result.loc['000004.SZ', 'excluded_major_risk']
    assert result.loc['000005.SZ', 'excluded_untradable']
    assert result.loc['000006.SZ', 'is_investable_core']
    assert result.loc['000006.SZ', 'is_investable_500m']
    assert result.loc['000007.SZ', 'market_cap_source'] == 'total_mv'


def test_expand_index_weight_universe_daily_forward_fills_snapshot_until_next_weight_date():
    raw = pd.DataFrame({
        'index_code': ['000300.SH', '000300.SH'],
        'con_code': ['000001.SZ', '000002.SZ'],
        'trade_date': ['20240102', '20240104'],
        'weight': [1.0, 2.0],
    })

    result = expand_index_weight_universe_daily(
        raw,
        trade_dates=['20240102', '20240103', '20240104', '20240105'],
        index_names={'000300.SH': '沪深300'},
    )

    assert result[['trade_date', 'ts_code', 'weight']].to_dict('records') == [
        {'trade_date': '20240102', 'ts_code': '000001.SZ', 'weight': 1.0},
        {'trade_date': '20240103', 'ts_code': '000001.SZ', 'weight': 1.0},
        {'trade_date': '20240104', 'ts_code': '000002.SZ', 'weight': 2.0},
        {'trade_date': '20240105', 'ts_code': '000002.SZ', 'weight': 2.0},
    ]
    assert result['source_weight_date'].tolist() == ['20240102', '20240102', '20240104', '20240104']


def test_month_ranges_split_index_weight_downloads_by_calendar_month():
    assert month_ranges('20240115', '20240302') == [
        ('20240115', '20240131'),
        ('20240201', '20240229'),
        ('20240301', '20240302'),
    ]
