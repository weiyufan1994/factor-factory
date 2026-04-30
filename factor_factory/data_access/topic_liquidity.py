from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Literal, Sequence

import pandas as pd

from .calendar import get_trade_calendar
from .paths import LocalTusharePaths

TopicAvailability = Literal['next_open', 'same_day_close']

DEFAULT_TOPIC_LIQUIDITY_ROOTS = (
    Path('/home/ubuntu/.openclaw/workspace/runs/topic-liquidity-hhi'),
    Path.home() / 'projects' / 'factor-factory' / 'runs' / 'topic-liquidity-hhi',
)

DEFAULT_TOPIC_FEATURE_COLUMNS = [
    'liquidity_heat_score',
    'flow_share',
    'external_capture',
    'positive_pool_capture',
    'demand_pressure',
    'supply_pressure',
    'demand_supply_ratio',
    'limit_breadth',
    'leader_flow_hhi',
    'leader_flow_hhi_norm',
    'leader_top1_flow_share',
    'leader_top3_flow_share',
    'positive_leader_count',
    'topic_net_amount_wan',
    'positive_flow_wan',
    'negative_flow_wan',
    'topic_turnover_wan',
    'topic_circ_mv_wan',
    'stock_count',
    'limit_up_count',
]


def _normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace('-', '')
    return text if text else None


def _normalize_date_series(series: pd.Series) -> pd.Series:
    return series.astype('string').str.replace('.0', '', regex=False).str.replace('-', '', regex=False).str.zfill(8)


def _normalize_filter(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    normalized = {str(value).strip() for value in values if str(value).strip()}
    return normalized or None


def resolve_topic_liquidity_root(root: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if root is not None:
        candidates.append(Path(root).expanduser())
    env_root = os.getenv('FACTORFORGE_TOPIC_LIQUIDITY_ROOT')
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(path.expanduser() for path in DEFAULT_TOPIC_LIQUIDITY_ROOTS)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _date_from_path(path: Path) -> str | None:
    match = re.search(r'(20\d{6})', path.name)
    if match:
        return match.group(1)
    match = re.search(r'(20\d{2})-(\d{2})-(\d{2})', str(path.parent))
    if match:
        return ''.join(match.groups())
    return None


def _iter_result_csvs(root: Path, kind: Literal['topics', 'leaders']) -> list[Path]:
    pattern = f'topic_liquidity_{kind}_*.csv'
    return sorted(path for path in root.glob(f'20??-??-??/{pattern}') if path.is_file())


def _load_result_kind(
    kind: Literal['topics', 'leaders'],
    start: str | int | None = None,
    end: str | int | None = None,
    root: str | Path | None = None,
) -> pd.DataFrame:
    resolved_root = resolve_topic_liquidity_root(root)
    start_key = _normalize_date(start)
    end_key = _normalize_date(end)
    frames: list[pd.DataFrame] = []
    for csv_path in _iter_result_csvs(resolved_root, kind):
        date_from_path = _date_from_path(csv_path)
        if date_from_path is None:
            continue
        if start_key and date_from_path < start_key:
            continue
        if end_key and date_from_path > end_key:
            continue
        frame = pd.read_csv(csv_path)
        if 'trade_date' not in frame.columns:
            frame.insert(0, 'trade_date', date_from_path)
        frame['trade_date'] = _normalize_date_series(frame['trade_date'])
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _attach_available_date(
    frame: pd.DataFrame,
    availability: TopicAvailability,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    enriched = frame.copy()
    enriched['event_trade_date'] = _normalize_date_series(enriched['trade_date'])
    if availability == 'same_day_close':
        enriched['available_date'] = enriched['event_trade_date']
        enriched['available_time'] = 'post_close'
        return enriched
    if availability != 'next_open':
        raise ValueError("availability must be 'next_open' or 'same_day_close'")

    min_date = str(enriched['event_trade_date'].min())
    max_date = str(enriched['event_trade_date'].max())
    calendar_frame = get_trade_calendar(
        start=min_date,
        end=str(int(max_date[:4]) + 1) + '1231',
        exchange=None,
        open_only=True,
        columns=['cal_date'],
        paths=paths,
    )
    calendar = calendar_frame['cal_date'].astype(str).tolist()
    next_open: dict[str, str] = {}
    for idx, trade_date in enumerate(calendar[:-1]):
        next_open[trade_date] = calendar[idx + 1]
    enriched['available_date'] = enriched['event_trade_date'].map(next_open).astype('string')
    enriched['available_time'] = 'next_open'
    return enriched


def get_topic_liquidity_topics(
    start: str | int | None = None,
    end: str | int | None = None,
    topics: Iterable[str] | None = None,
    columns: Sequence[str] | None = None,
    root: str | Path | None = None,
    availability: TopicAvailability = 'next_open',
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    frame = _load_result_kind('topics', start=start, end=end, root=root)
    if frame.empty:
        return pd.DataFrame(columns=list(columns) if columns else None)
    wanted_topics = _normalize_filter(topics)
    if wanted_topics is not None:
        frame = frame[frame['topic'].astype('string').isin(wanted_topics)]
    frame = _attach_available_date(frame, availability=availability, paths=paths)
    if columns:
        required = list(dict.fromkeys(['topic', 'event_trade_date', 'available_date', *columns]))
        for column in required:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[required]
    return frame.reset_index(drop=True)


def get_topic_liquidity_leaders(
    start: str | int | None = None,
    end: str | int | None = None,
    topics: Iterable[str] | None = None,
    symbols: Iterable[str] | None = None,
    columns: Sequence[str] | None = None,
    root: str | Path | None = None,
    availability: TopicAvailability = 'next_open',
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    frame = _load_result_kind('leaders', start=start, end=end, root=root)
    if frame.empty:
        return pd.DataFrame(columns=list(columns) if columns else None)
    wanted_topics = _normalize_filter(topics)
    wanted_symbols = _normalize_filter(symbols)
    if wanted_topics is not None:
        frame = frame[frame['topic'].astype('string').isin(wanted_topics)]
    if wanted_symbols is not None:
        frame = frame[frame['ts_code'].astype('string').isin(wanted_symbols)]
    frame = _attach_available_date(frame, availability=availability, paths=paths)
    if columns:
        required = list(dict.fromkeys(['topic', 'ts_code', 'event_trade_date', 'available_date', *columns]))
        for column in required:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[required]
    return frame.reset_index(drop=True)


def align_topic_liquidity_to_daily(
    daily_dates: Iterable[str | int],
    topic_frame: pd.DataFrame | None = None,
    topics: Iterable[str] | None = None,
    feature_columns: Sequence[str] | None = None,
    start: str | int | None = None,
    end: str | int | None = None,
    root: str | Path | None = None,
    paths: LocalTusharePaths | None = None,
) -> pd.DataFrame:
    dates = sorted({_normalize_date(date) for date in daily_dates if _normalize_date(date)})
    if not dates:
        return pd.DataFrame()

    features = topic_frame.copy() if topic_frame is not None else get_topic_liquidity_topics(
        start=start or dates[0],
        end=end or dates[-1],
        topics=topics,
        root=root,
        availability='next_open',
        paths=paths,
    )
    if features.empty:
        return pd.DataFrame()
    if 'available_date' not in features.columns:
        features = _attach_available_date(features, availability='next_open', paths=paths)

    wanted_topics = _normalize_filter(topics)
    if wanted_topics is not None:
        features = features[features['topic'].astype('string').isin(wanted_topics)]

    use_columns = list(feature_columns or DEFAULT_TOPIC_FEATURE_COLUMNS)
    required = ['topic', 'event_trade_date', 'available_date', *use_columns]
    for column in required:
        if column not in features.columns:
            features[column] = pd.NA
    features = features[required].dropna(subset=['available_date']).copy()
    features['available_date'] = _normalize_date_series(features['available_date'])

    left_dates = pd.DataFrame({'trade_date': dates})
    left_dates['_trade_date_int'] = pd.to_numeric(left_dates['trade_date'], errors='coerce').astype('float64')
    features['_available_date_int'] = pd.to_numeric(features['available_date'], errors='coerce').astype('float64')
    aligned: list[pd.DataFrame] = []
    for topic, sub in features.sort_values('available_date').groupby('topic', sort=False):
        left = left_dates.copy()
        left['topic'] = topic
        merged = pd.merge_asof(
            left.sort_values('_trade_date_int'),
            sub.sort_values('_available_date_int'),
            left_on='_trade_date_int',
            right_on='_available_date_int',
            direction='backward',
        )
        merged['topic'] = topic
        merged = merged.drop(
            columns=[
                c
                for c in ('_trade_date_int', '_available_date_int', 'topic_x', 'topic_y')
                if c in merged.columns
            ]
        )
        aligned.append(merged)
    if not aligned:
        return pd.DataFrame()
    out = pd.concat(aligned, ignore_index=True, sort=False)
    return out.sort_values(['trade_date', 'topic']).reset_index(drop=True)
