from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import LocalTusharePaths, resolve_local_tushare_paths


@dataclass(frozen=True)
class TushareDatasetSpec:
    name: str
    category_dir: str
    dataset_dir: str
    partition_columns: tuple[str, ...] = ()


DATASET_SPECS: dict[str, TushareDatasetSpec] = {
    'limit_list_d': TushareDatasetSpec('limit_list_d', '打板专题数据', '涨跌停数据', ('trade_date',)),
    'dc_concept': TushareDatasetSpec('dc_concept', '打板专题数据', '题材数据', ('trade_date',)),
    'ths_index': TushareDatasetSpec('ths_index', '打板专题数据', '同花顺行业概念板块'),
    'ths_member': TushareDatasetSpec('ths_member', '打板专题数据', '同花顺行业概念成分', ('ts_code',)),
    'dc_index': TushareDatasetSpec('dc_index', '打板专题数据', '东方财富概念板块', ('trade_date',)),
    'dc_member': TushareDatasetSpec('dc_member', '打板专题数据', '东方财富概念成分', ('trade_date',)),
    'dc_concept_cons': TushareDatasetSpec('dc_concept_cons', '打板专题数据', '东方财富题材成分', ('trade_date',)),
    'ths_hot': TushareDatasetSpec('ths_hot', '打板专题数据', '同花顺热榜', ('market', 'trade_date')),
    'moneyflow': TushareDatasetSpec('moneyflow', '资金流向数据', '个股资金流向', ('trade_date',)),
    'moneyflow_ths': TushareDatasetSpec('moneyflow_ths', '资金流向数据', '个股资金流向_THS', ('trade_date',)),
    'moneyflow_dc': TushareDatasetSpec('moneyflow_dc', '资金流向数据', '个股资金流向_DC', ('trade_date',)),
    'moneyflow_cnt_ths': TushareDatasetSpec('moneyflow_cnt_ths', '资金流向数据', '概念板块资金流向_THS', ('trade_date',)),
    'moneyflow_ind_ths': TushareDatasetSpec('moneyflow_ind_ths', '资金流向数据', '行业资金流向_THS', ('trade_date',)),
    'moneyflow_ind_dc': TushareDatasetSpec('moneyflow_ind_dc', '资金流向数据', '行业概念板块资金流向_DC', ('trade_date',)),
    'moneyflow_mkt_dc': TushareDatasetSpec('moneyflow_mkt_dc', '资金流向数据', '大盘资金流向_DC', ('trade_date',)),
    'hm_list': TushareDatasetSpec('hm_list', '打板专题数据', '游资名录'),
    'kpl_list': TushareDatasetSpec('kpl_list', '打板专题数据', '开盘啦榜单数据', ('tag', 'trade_date')),
    'kpl_concept_cons': TushareDatasetSpec('kpl_concept_cons', '打板专题数据', '开盘啦题材成分', ('trade_date',)),
    'cyq_perf': TushareDatasetSpec('cyq_perf', '特色数据', '每日筹码及胜率', ('trade_date',)),
    'cyq_chips': TushareDatasetSpec('cyq_chips', '特色数据', '每日筹码分布', ('ts_code',)),
    'stk_factor_pro': TushareDatasetSpec('stk_factor_pro', '特色数据', '股票技术面因子_专业版', ('trade_date',)),
    'broker_recommend': TushareDatasetSpec('broker_recommend', '特色数据', '券商每月荐股', ('month',)),
    'margin': TushareDatasetSpec('margin', '两融及转融通', '融资融券交易汇总', ('trade_date',)),
    'margin_detail': TushareDatasetSpec('margin_detail', '两融及转融通', '融资融券交易明细', ('trade_date',)),
    'report_rc': TushareDatasetSpec('report_rc', '特色数据', '卖方盈利预测数据', ('report_date',)),
    'income_vip': TushareDatasetSpec('income_vip', '财务数据', '利润表', ('period',)),
    'balancesheet_vip': TushareDatasetSpec('balancesheet_vip', '财务数据', '资产负债表', ('period',)),
    'cashflow_vip': TushareDatasetSpec('cashflow_vip', '财务数据', '现金流量表', ('period',)),
    'forecast_vip': TushareDatasetSpec('forecast_vip', '财务数据', '业绩预告', ('period',)),
    'express_vip': TushareDatasetSpec('express_vip', '财务数据', '业绩快报', ('period',)),
    'fina_indicator_vip': TushareDatasetSpec('fina_indicator_vip', '财务数据', '财务指标数据', ('period',)),
    'fina_mainbz_vip': TushareDatasetSpec('fina_mainbz_vip', '财务数据', '主营业务构成', ('period',)),
    'disclosure_date': TushareDatasetSpec('disclosure_date', '财务数据', '财报披露计划', ('period',)),
}


def list_tushare_dataset_names() -> list[str]:
    return sorted(DATASET_SPECS)


def get_tushare_dataset_spec(name: str) -> TushareDatasetSpec:
    try:
        return DATASET_SPECS[name]
    except KeyError as exc:
        available = ', '.join(list_tushare_dataset_names())
        raise KeyError(f'unknown tushare dataset: {name}. available={available}') from exc


def get_tushare_dataset_root(
    name: str,
    paths: LocalTusharePaths | None = None,
) -> Path:
    resolved_paths = paths or resolve_local_tushare_paths()
    spec = get_tushare_dataset_spec(name)
    return Path(resolved_paths.root) / spec.category_dir / spec.dataset_dir


def _normalize_scalar(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_symbols(symbols: Iterable[str] | None) -> set[str] | None:
    if symbols is None:
        return None
    normalized = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
    return normalized or None


def _normalize_partition_filters(
    partition_filters: dict[str, str | int | Iterable[str | int]] | None,
) -> dict[str, set[str]]:
    if not partition_filters:
        return {}
    normalized: dict[str, set[str]] = {}
    for key, raw_value in partition_filters.items():
        if isinstance(raw_value, (str, int)):
            values = {str(raw_value).strip()}
        else:
            values = {str(value).strip() for value in raw_value if str(value).strip()}
        if values:
            normalized[str(key).strip()] = values
    return normalized


def _extract_partition_values(root: Path, csv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        relative_parent = csv_path.parent.relative_to(root)
    except ValueError:
        return values
    for part in relative_parent.parts:
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        if key and value:
            values[key] = value
    return values


def _matches_partitions(
    partitions: dict[str, str],
    start: str | None,
    end: str | None,
    partition_filters: dict[str, set[str]],
) -> bool:
    for key, allowed in partition_filters.items():
        value = partitions.get(key)
        if value is None or value not in allowed:
            return False

    for key in ('trade_date', 'report_date', 'period', 'month'):
        value = partitions.get(key)
        if value is None:
            continue
        compare_start = start
        compare_end = end
        compare_value = value
        if key == 'month':
            compare_start = start[:6] if start else None
            compare_end = end[:6] if end else None
            compare_value = value[:6]
        if compare_start and compare_value < compare_start:
            return False
        if compare_end and compare_value > compare_end:
            return False
    return True


def _iter_dataset_csvs(
    root: Path,
    start: str | None,
    end: str | None,
    partition_filters: dict[str, set[str]],
) -> list[tuple[Path, dict[str, str]]]:
    csvs: list[tuple[Path, dict[str, str]]] = []
    for csv_path in sorted(root.rglob('*.csv')):
        partitions = _extract_partition_values(root, csv_path)
        if not _matches_partitions(partitions, start=start, end=end, partition_filters=partition_filters):
            continue
        csvs.append((csv_path, partitions))
    return csvs


def _inject_partition_columns(frame: pd.DataFrame, partitions: dict[str, str]) -> pd.DataFrame:
    enriched = frame.copy()
    for key, value in partitions.items():
        if key not in enriched.columns:
            enriched[key] = value
    return enriched


def _filter_by_symbols(frame: pd.DataFrame, symbols: set[str] | None) -> pd.DataFrame:
    if not symbols:
        return frame
    if 'ts_code' in frame.columns:
        return frame[frame['ts_code'].astype('string').isin(symbols)]
    if 'symbol' in frame.columns:
        return frame[frame['symbol'].astype('string').isin(symbols)]
    return frame


def get_tushare_dataset(
    name: str,
    start: str | int | None = None,
    end: str | int | None = None,
    symbols: Iterable[str] | None = None,
    columns: Iterable[str] | None = None,
    partition_filters: dict[str, str | int | Iterable[str | int]] | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    dataset_root = get_tushare_dataset_root(name, paths=paths)
    if not dataset_root.exists():
        raise FileNotFoundError(f'tushare dataset root not found: {dataset_root}')

    requested_columns = list(columns) if columns else None
    normalized_symbols = _normalize_symbols(symbols)
    normalized_partitions = _normalize_partition_filters(partition_filters)
    start_key = _normalize_scalar(start)
    end_key = _normalize_scalar(end)

    csvs = _iter_dataset_csvs(
        dataset_root,
        start=start_key,
        end=end_key,
        partition_filters=normalized_partitions,
    )
    if not csvs:
        return pd.DataFrame(columns=requested_columns or [])

    frames: list[pd.DataFrame] = []
    for csv_path, partitions in csvs:
        frame = pd.read_csv(csv_path)
        frame = _inject_partition_columns(frame, partitions)
        frame = _filter_by_symbols(frame, normalized_symbols)
        if requested_columns:
            missing = [column for column in requested_columns if column not in frame.columns]
            for column in missing:
                frame[column] = pd.NA
            frame = frame[requested_columns]
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=requested_columns or [])
    return pd.concat(frames, ignore_index=True)
