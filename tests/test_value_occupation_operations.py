from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.probe_intraday_value_occupation_source import (
    coverage_summary,
    discover_local_partition_dates,
    parse_s3_partition_dates,
)
from scripts.run_intraday_value_occupation_smoke import build_smoke_catalog


class ValueOccupationOperationsTest(unittest.TestCase):
    def test_parse_s3_partition_dates_from_aws_ls_output(self) -> None:
        output = """
                           PRE trade_date=20240102/
                           PRE trade_date=20240103/
        2026-06-10 00:00:00          0 _SUCCESS
        """

        self.assertEqual(parse_s3_partition_dates(output), ['20240102', '20240103'])

    def test_discover_local_partition_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'trade_date=20240102').mkdir()
            (root / 'trade_date=20240104').mkdir()
            (root / 'not_a_partition').mkdir()

            self.assertEqual(discover_local_partition_dates(root), ['20240102', '20240104'])

    def test_coverage_summary_reports_missing_dates(self) -> None:
        summary = coverage_summary(
            expected_dates=['20240102', '20240103', '20240104'],
            available_dates=['20240102', '20240104'],
            label='raw_s3_minute_bar',
        )

        self.assertEqual(summary['label'], 'raw_s3_minute_bar')
        self.assertEqual(summary['expected_date_count'], 3)
        self.assertEqual(summary['available_date_count'], 2)
        self.assertEqual(summary['missing_date_count'], 1)
        self.assertEqual(summary['missing_dates'], ['20240103'])
        self.assertAlmostEqual(summary['coverage_ratio'], 2 / 3)

    def test_smoke_catalog_points_at_s3_uri_when_upload_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / 'catalog.json'
            build_smoke_catalog(
                catalog_path=catalog_path,
                datamart_uri='s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1_smoke',
                qa_output=Path(tmp) / 'qa.json',
                start='20240102',
                end='20240110',
            )
            payload = json.loads(catalog_path.read_text(encoding='utf-8'))
            entry = payload['datasets']['intraday_value_occupation_state_v1']

        self.assertEqual(entry['storage'], 's3')
        self.assertEqual(entry['uri'], 's3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1_smoke')
        self.assertEqual(entry['metadata']['unique_key'], ['ts_code', 'trade_date', 'cutoff_time', 'lookback_days'])


if __name__ == '__main__':
    unittest.main()
