"""Local prepared daily inputs: distinct full and bounded-sample selectors."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

KIND = 'prepared_daily_v1'


def is_prepared_daily(inputs: dict) -> bool:
    return inputs.get('input_mode') == 'daily_only' and inputs.get('prepared_input_kind') == KIND


def validate_prepared_daily(inputs: dict) -> dict:
    if inputs.get('input_mode') != 'daily_only':
        raise ValueError('prepared daily inputs require daily_only')
    for key in ('minute_df_parquet', 'minute_df_csv', 'minute_streaming_query',
                'derived_state_root', 'step3b_derived_state_root',
                'evaluation_daily_df_parquet', 'signal_daily_df_parquet'):
        if inputs.get(key):
            raise ValueError(f'prepared daily inputs forbid {key}')
    for key in ('daily_df_parquet', 'step3b_daily_df_parquet',
                'exchange_calendar_parquet', 'step3b_exchange_calendar_parquet'):
        if not isinstance(inputs.get(key), str) or not inputs[key].strip():
            raise ValueError(f'prepared daily inputs missing {key}')
    windows = []
    for key in ('sample_window_actual', 'step3b_sample_window'):
        window = inputs.get(key) or {}
        try:
            bounds = tuple(datetime.strptime(str(window[k]), '%Y%m%d') for k in ('start', 'end'))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f'prepared daily inputs invalid {key}') from exc
        if bounds[0] > bounds[1]:
            raise ValueError(f'prepared daily inputs reversed {key}')
        windows.append(bounds)
    if not (windows[0][0] <= windows[1][0] <= windows[1][1] <= windows[0][1]):
        raise ValueError('prepared daily sample window outside actual window')
    return {**inputs, 'prepared_input_kind': KIND}


def sample_inputs(inputs: dict) -> dict:
    validated = validate_prepared_daily(inputs)
    return {
        **validated,
        'daily_df_parquet': validated['step3b_daily_df_parquet'],
        'exchange_calendar_parquet': validated['step3b_exchange_calendar_parquet'],
        'sample_window_actual': dict(validated['step3b_sample_window']),
    }


def validate_sample_frames(daily, calendar, window: dict) -> None:
    """Check supplied sample, never derive exchange sessions from stock rows."""
    import pandas as pd

    if not {'ts_code', 'trade_date'} <= set(daily.columns) or 'trade_date' not in calendar:
        raise ValueError('prepared daily sample missing key/calendar columns')
    if daily.empty or calendar.empty:
        raise ValueError('prepared daily sample/calendar empty')
    def days(frame):
        values = frame['trade_date'].astype(str).str.replace('-', '', regex=False).str[:8]
        pd.to_datetime(values, format='%Y%m%d', errors='raise')
        return values
    daily_days, calendar_days = days(daily), days(calendar)
    start, end = str(window['start']), str(window['end'])
    if not daily_days.between(start, end).all() or not calendar_days.between(start, end).all():
        raise ValueError('prepared daily sample exceeds declared sample window')
    if calendar_days.duplicated().any() or not calendar_days.is_monotonic_increasing:
        raise ValueError('prepared daily sample calendar must be unique and ordered')
    if not set(daily_days) <= set(calendar_days):
        raise ValueError('prepared daily sample has dates outside exchange calendar')
    if daily.assign(trade_date=daily_days).duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('prepared daily sample has duplicate security/date keys')


def validate_paths(inputs: dict, workspace: Path) -> None:
    validated = validate_prepared_daily(inputs)
    for key in ('daily_df_parquet', 'step3b_daily_df_parquet',
                'exchange_calendar_parquet', 'step3b_exchange_calendar_parquet'):
        if not (workspace / validated[key]).is_file():
            raise ValueError(f'prepared daily input missing file: {key}')
    if validated['sample_window_actual'] != validated['step3b_sample_window']:
        for full, sample in (('daily_df_parquet', 'step3b_daily_df_parquet'),
                             ('exchange_calendar_parquet', 'step3b_exchange_calendar_parquet')):
            if (workspace / validated[full]).samefile(workspace / validated[sample]):
                raise ValueError('prepared daily full/sample alias with different declared windows')


def validate_full_scope(inputs: dict, workspace: Path) -> dict:
    """Read only date columns; prevent a sample being promoted to full IS input.

    Prepared windows use inclusive open-session endpoints. Individual securities
    may be sparse, but the full daily input must cover the independent calendar's
    aggregate session set. This is consumer scope validation, not source QA.
    """
    import pandas as pd
    import pyarrow.parquet as pq

    validate_paths(inputs, workspace)
    window = inputs['sample_window_actual']
    start, end = str(window['start']), str(window['end'])

    def normalize(values):
        values = values.astype(str).str.replace('-', '', regex=False).str[:8]
        pd.to_datetime(values, format='%Y%m%d', errors='raise')
        if not values.between(start, end).all():
            raise ValueError('prepared daily full input exceeds declared window')
        return values

    calendar = normalize(pd.read_parquet(workspace / inputs['exchange_calendar_parquet'], columns=['trade_date'])['trade_date'])
    if calendar.empty or calendar.duplicated().any() or not calendar.is_monotonic_increasing:
        raise ValueError('prepared daily full calendar must be nonempty, unique and ordered')
    if calendar.iloc[0] != start or calendar.iloc[-1] != end:
        raise ValueError('prepared daily full calendar does not span declared open-session endpoints')
    expected = set(calendar)
    observed = set()
    daily = pq.ParquetFile(workspace / inputs['daily_df_parquet'])
    for batch in daily.iter_batches(columns=['trade_date'], batch_size=65536):
        observed.update(normalize(batch.to_pandas()['trade_date']))
    if observed != expected:
        raise ValueError('prepared daily full date coverage differs from independent calendar')
    return {'start': start, 'end': end, 'session_count': len(expected),
            'row_count': daily.metadata.num_rows, 'scope_check': 'actual_full_dates_vs_calendar'}


def check_sample_size(inputs: dict, workspace: Path) -> None:
    """Reject oversized prepared samples before loading; do not silently resample."""
    import pyarrow.parquet as pq

    limit = int(os.getenv('FACTORFORGE_STEP3B_SAMPLE_MAX_ROWS') or '250000')
    if limit < 1:
        raise ValueError('invalid Step3B sample row budget')
    for key in ('step3b_daily_df_parquet', 'step3b_exchange_calendar_parquet'):
        rows = pq.read_metadata(workspace / inputs[key]).num_rows
        if not 0 < rows <= limit:
            raise ValueError(f'prepared daily sample outside row budget: {key}, rows={rows}, limit={limit}')
