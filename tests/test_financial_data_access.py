from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from factor_factory.data_access import (
    get_fina_mainbz_daily,
    get_income_statement_daily,
    get_report_rc_daily,
)
from factor_factory.data_access.paths import LocalTusharePaths


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _make_paths(root: Path) -> LocalTusharePaths:
    _write_csv(
        root / '基础数据' / 'trade_cal.csv',
        [{'cal_date': '20240410', 'is_open': 1}],
    )
    _write_csv(
        root / '基础数据' / 'stock_basic.csv',
        [{'ts_code': '000001.SZ'}],
    )
    _write_csv(
        root / '基础数据' / 'stock_st.csv',
        [{'ts_code': '000001.SZ', 'name': 'PingAn'}],
    )
    _write_csv(
        root / '基础数据' / 'stock_st_daily_20160101_current.csv',
        [{'ts_code': '000001.SZ', 'trade_date': '20240410', 'is_st': 0}],
    )
    _write_csv(
        root / '行情数据' / 'adj_factor.csv',
        [{'ts_code': '000001.SZ', 'trade_date': '20240410', 'adj_factor': 1.0}],
    )
    (root / '行情数据' / 'daily_basic_incremental').mkdir(parents=True, exist_ok=True)
    return LocalTusharePaths(
        root=root,
        daily_csv=root / '行情数据' / 'daily.csv',
        adj_factor_csv=root / '行情数据' / 'adj_factor.csv',
        daily_basic_dir=root / '行情数据' / 'daily_basic_incremental',
        trade_cal_csv=root / '基础数据' / 'trade_cal.csv',
        stock_basic_csv=root / '基础数据' / 'stock_basic.csv',
        stock_st_csv=root / '基础数据' / 'stock_st.csv',
        stock_st_daily_csv=root / '基础数据' / 'stock_st_daily_20160101_current.csv',
        source_label='test',
    )


class FinancialDataAccessTest(unittest.TestCase):
    def test_income_statement_daily_accepts_columns_and_blocks_future_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _make_paths(root)
            _write_csv(
                paths.daily_csv,
                [
                    {'ts_code': '000001.SZ', 'trade_date': '20240418'},
                    {'ts_code': '000001.SZ', 'trade_date': '20240419'},
                    {'ts_code': '000001.SZ', 'trade_date': '20240422'},
                ],
            )
            _write_csv(
                root / '财务数据' / '利润表' / 'period=20231231' / 'income_vip_20231231.csv',
                [
                    {
                        'ts_code': '000001.SZ',
                        'ann_date': '20240316',
                        'f_ann_date': '20240316',
                        'end_date': '20231231',
                        'report_type': 1,
                        'revenue': 100.0,
                    }
                ],
            )
            _write_csv(
                root / '财务数据' / '利润表' / 'period=20240331' / 'income_vip_20240331.csv',
                [
                    {
                        'ts_code': '000001.SZ',
                        'ann_date': '20240420',
                        'f_ann_date': '20240420',
                        'end_date': '20240331',
                        'report_type': 1,
                        'revenue': 120.0,
                    }
                ],
            )

            frame = get_income_statement_daily(
                start='20240418',
                end='20240422',
                symbols=['000001.SZ'],
                columns=['trade_date', 'ts_code', 'available_date', 'end_date', 'revenue'],
                paths=paths,
            )

            self.assertEqual(
                ['trade_date', 'ts_code', 'available_date', 'end_date', 'revenue'],
                list(frame.columns),
            )
            self.assertEqual(['20231231', '20231231', '20240331'], frame['end_date'].tolist())
            self.assertEqual(['20240316', '20240316', '20240420'], frame['available_date'].tolist())
            self.assertEqual([100.0, 100.0, 120.0], frame['revenue'].tolist())

    def test_report_rc_daily_waits_for_report_date_from_month_partition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _make_paths(root)
            _write_csv(
                paths.daily_csv,
                [
                    {'ts_code': '600416.SH', 'trade_date': '20100104'},
                    {'ts_code': '600416.SH', 'trade_date': '20100105'},
                    {'ts_code': '600416.SH', 'trade_date': '20100106'},
                    {'ts_code': '600416.SH', 'trade_date': '20100107'},
                    {'ts_code': '600416.SH', 'trade_date': '20100108'},
                    {'ts_code': '600416.SH', 'trade_date': '20100111'},
                ],
            )
            _write_csv(
                root / '特色数据' / '卖方盈利预测数据' / 'month=201001' / 'report_rc_201001.csv',
                [
                    {
                        'ts_code': '600416.SH',
                        'report_date': '20100108',
                        'quarter': '2009Q4',
                        'rating': '买入',
                    }
                ],
            )

            frame = get_report_rc_daily(
                start='20100101',
                end='20100131',
                symbols=['600416.SH'],
                columns=['trade_date', 'ts_code', 'available_date', 'report_date', 'quarter', 'rating'],
                paths=paths,
            )

            self.assertTrue(frame.loc[:3, 'available_date'].isna().all())
            self.assertEqual('20100108', frame.loc[4, 'available_date'])
            self.assertEqual('20100108', frame.loc[5, 'available_date'])
            self.assertEqual('买入', frame.loc[5, 'rating'])

    def test_fina_mainbz_daily_uses_disclosure_actual_date_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _make_paths(root)
            _write_csv(
                paths.daily_csv,
                [
                    {'ts_code': '000001.SZ', 'trade_date': '20240411'},
                    {'ts_code': '000001.SZ', 'trade_date': '20240412'},
                ],
            )
            _write_csv(
                root / '财务数据' / '主营业务构成' / 'period=20240331' / 'fina_mainbz_vip_20240331.csv',
                [
                    {
                        'ts_code': '000001.SZ',
                        'end_date': '20240331',
                        'bz_item': '核心业务',
                        'bz_sales': 55.0,
                    }
                ],
            )
            _write_csv(
                root / '财务数据' / '财报披露计划' / 'period=20240331' / 'disclosure_date_20240331.csv',
                [
                    {
                        'ts_code': '000001.SZ',
                        'end_date': '20240331',
                        'ann_date': '20240405',
                        'actual_date': '20240412',
                    }
                ],
            )

            frame = get_fina_mainbz_daily(
                start='20240411',
                end='20240412',
                symbols=['000001.SZ'],
                columns=['trade_date', 'ts_code', 'available_date', 'end_date', 'bz_item', 'bz_sales'],
                paths=paths,
            )

            self.assertTrue(pd.isna(frame.loc[0, 'available_date']))
            self.assertTrue(pd.isna(frame.loc[0, 'bz_item']))
            self.assertEqual('20240412', frame.loc[1, 'available_date'])
            self.assertEqual('20240331', frame.loc[1, 'end_date'])
            self.assertEqual('核心业务', frame.loc[1, 'bz_item'])
            self.assertEqual(55.0, frame.loc[1, 'bz_sales'])


if __name__ == '__main__':
    unittest.main()
