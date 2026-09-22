"""Bounded local day-streaming controller for the frozen PF/VV baseline.

The numerical authority remains ``pfvv_source_baseline_v1``.  This controller
only turns one explicit day at a time into that kernel's inputs, retains at
most twenty daily PF and VV-z observations per already-seen ticker, and yields
one long output frame per calendar day.  It never discovers files, reads a
directory, calls a network service, or writes an artifact.

It is local bounded plumbing, not a formal Step4/raw-minute route.  A full IS
calculation has not yet been executed or integrated by this module.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import importlib.util
import os
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

import numpy as np
import pandas as pd


_ADAPTER_PATH = Path(__file__).with_name("pfvv_source_baseline_dataframe_adapter_v1.py")
_ADAPTER_SPEC = importlib.util.spec_from_file_location("pfvv_source_baseline_dataframe_adapter_v1", _ADAPTER_PATH)
if _ADAPTER_SPEC is None or _ADAPTER_SPEC.loader is None:  # pragma: no cover - installation failure
    raise ImportError(f"cannot import local PF/VV adapter: {_ADAPTER_PATH}")
_ADAPTER = importlib.util.module_from_spec(_ADAPTER_SPEC)
_ADAPTER_SPEC.loader.exec_module(_ADAPTER)
_KERNEL = _ADAPTER._KERNEL


WINDOW = 20
PREPARED_DAILY_STATE_CONTRACT_VERSION = "pfvv_prepared_daily_state_v1"
PREPARED_DAILY_STATE_AUTHORITY = "pfvv_source_baseline_v1"
PREPARED_DAILY_STATE_COLUMNS = ("ts_code", "trade_date", "pf_daily", "vv_daily")
DEFAULT_MAX_CALENDAR_DAYS = 3_000
DEFAULT_MAX_RAW_ROWS_PER_DAY = 2_400_000
DEFAULT_MAX_TICKERS_PER_DAY = 10_000
DEFAULT_MAX_ESTIMATED_BYTES_PER_DAY = 512 * 1024 * 1024
ESTIMATED_BYTES_PER_EXPANDED_CELL = _ADAPTER.ESTIMATED_BYTES_PER_EXPANDED_CELL
OUTPUT_COLUMNS = [
    "ts_code",
    "trade_date",
    "PF",
    "VV",
    "PF_z",
    "VV_z",
    "component_z",
    "composite",
    "factor_value",
    "warmup",
]

METADATA = {
    "controller_version": "pfvv_source_baseline_partitioned_v1",
    "local_bounded_streaming": True,
    "prepared_state_projection": True,
    "raw_minute_access": False,
    "full_is_executed": False,
    "formal_step4_integrated": False,
    "math_authority": "pfvv_source_baseline_v1",
}


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _empty_output() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": pd.Series(dtype="object"),
            "trade_date": pd.Series(dtype="object"),
            "PF": pd.Series(dtype="float64"),
            "VV": pd.Series(dtype="float64"),
            "PF_z": pd.Series(dtype="float64"),
            "VV_z": pd.Series(dtype="float64"),
            "component_z": pd.Series(dtype="float64"),
            "composite": pd.Series(dtype="float64"),
            "factor_value": pd.Series(dtype="float64"),
            "warmup": pd.Series(dtype="bool"),
        }
    )[OUTPUT_COLUMNS]


class PFVVPartitionState:
    """Caller-owned bounded state for resumable contiguous calendar chunks."""

    def __init__(self, trading_calendar: pd.DataFrame | pd.Series | pd.Index | Sequence[object]):
        self.calendar = _ADAPTER._resolve_calendar(None, trading_calendar)
        self.next_index = 0
        self.known_tickers: list[str] = []
        self.pf_history: dict[str, deque[float]] = {}
        self.vv_z_history: dict[str, deque[float]] = {}
        self.failed = False
        self.failed_index: int | None = None
        self.failure_message: str | None = None
        self.outputs_reusable = True

    def retained_daily_state_count(self) -> int:
        def count(history):
            return int(history.counts.sum()) if isinstance(history, _ArrayDailyHistory) else sum(len(values) for values in history.values())
        return count(self.pf_history) + count(self.vv_z_history)


def _assert_day_budget(
    *,
    calendar_days: int,
    raw_rows: int,
    ticker_count: int,
    max_calendar_days: int,
    max_raw_rows_per_day: int,
    max_tickers_per_day: int,
    max_estimated_bytes_per_day: int,
) -> None:
    max_calendar_days = _positive_int(max_calendar_days, "max_calendar_days")
    max_raw_rows_per_day = _positive_int(max_raw_rows_per_day, "max_raw_rows_per_day")
    max_tickers_per_day = _positive_int(max_tickers_per_day, "max_tickers_per_day")
    max_estimated_bytes_per_day = _positive_int(max_estimated_bytes_per_day, "max_estimated_bytes_per_day")
    expanded_cells = _ADAPTER.EXPECTED_SLOTS * ticker_count
    estimated_bytes = (raw_rows + expanded_cells) * ESTIMATED_BYTES_PER_EXPANDED_CELL
    if (
        calendar_days > max_calendar_days
        or raw_rows > max_raw_rows_per_day
        or ticker_count > max_tickers_per_day
        or estimated_bytes > max_estimated_bytes_per_day
    ):
        raise ValueError(
            "BLOCK_PFVV_PARTITIONED_DAY_BUDGET: local bounded controller refuses this day; "
            f"calendar_days={calendar_days} limit={max_calendar_days}; raw_rows={raw_rows} "
            f"limit={max_raw_rows_per_day}; tickers={ticker_count} limit={max_tickers_per_day}; "
            f"day_x_240_tickers={expanded_cells}; estimated_bytes={estimated_bytes} "
            f"limit={max_estimated_bytes_per_day}"
        )


def _assert_state_can_advance(state: PFVVPartitionState, calendar: pd.DatetimeIndex) -> None:
    if state.failed:
        raise RuntimeError(
            "PFVVPartitionState cannot resume after a failed day; create a new state and explicitly restart "
            f"from the failed input. failed_index={state.failed_index}; failure={state.failure_message}"
        )
    if isinstance(state.next_index, bool) or not isinstance(state.next_index, int):
        raise ValueError("state.next_index must be an integer")
    if state.next_index < 0 or state.next_index > len(calendar):
        raise ValueError("state.next_index lies outside the explicit calendar")


class _ArrayDailyHistory(Mapping):
    """Chronological twenty-slot arrays with a read-only mapping compatibility view."""
    def __init__(self, codes, values, counts):
        self.codes = tuple(codes)
        self.positions = {code: i for i, code in enumerate(codes)}
        self.values_array, self.counts = values, counts
        self.values_array.flags.writeable = False
        self.counts.flags.writeable = False

    def __len__(self):
        return len(self.codes)

    def __iter__(self):
        return iter(self.codes)

    def __getitem__(self, code):
        row = self.positions[code]
        return tuple(self.values_array[row, -int(self.counts[row]):])

    @classmethod
    def advance(cls, prior, codes, daily):
        count = len(codes)
        values = np.full((count, WINDOW), np.nan, dtype=float)
        counts = np.ones(count, dtype=np.int16)
        if isinstance(prior, cls):
            size = len(prior)
            if tuple(codes[:size]) != prior.codes:
                raise ValueError('rolling_state_code_order_changed')
            values[:size, :-1] = prior.values_array[:, 1:]
            counts[:size] = np.minimum(prior.counts + 1, WINDOW)
        elif prior:
            # Compatibility for caller-created states; the steady path is array-only.
            for row, code in enumerate(codes):
                history = list(prior.get(code, ()))
                retained = history[-(WINDOW-1):]
                if retained:
                    values[row, -(len(retained)+1):-1] = retained
                counts[row] = min(len(history)+1, WINDOW)
        values[:, -1] = daily.reindex(codes).to_numpy(dtype=float)
        return cls(codes, values, counts)


def _next_daily_state(state, prospective_codes, pf_daily, vv_daily_z):
    """Calculate a bounded array window without mutating committed caller state."""
    pf = _ArrayDailyHistory.advance(state.pf_history, prospective_codes, pf_daily)
    vv = _ArrayDailyHistory.advance(state.vv_z_history, prospective_codes, vv_daily_z)
    warmup = (pf.counts < WINDOW) | (vv.counts < WINDOW)
    def deviation(history):
        result = np.full(len(prospective_codes), np.nan)
        valid = ~warmup & np.isfinite(history.values_array).all(axis=1)
        # Row-contiguous reductions preserve the frozen per-ticker ddof=1 order.
        result[valid] = np.std(history.values_array[valid], axis=1, ddof=1)
        return result
    index = pd.Index(prospective_codes, name='ts_code')
    return (pf, vv, pd.Series(deviation(pf), index=index, dtype=float),
        pd.Series(deviation(vv), index=index, dtype=float),
        pd.Series(warmup, index=index, dtype=bool))


def _output_for_day(day: pd.Timestamp, pf20: pd.Series, vv20: pd.Series, warmup: pd.Series) -> pd.DataFrame:
    common = pf20.notna() & vv20.notna()
    pf_z = _KERNEL.daily_cross_section_zscore(pf20.where(common))
    vv_z = _KERNEL.daily_cross_section_zscore(vv20.where(common))
    component_z = (pf_z + vv_z) / 2.0
    composite = -component_z
    out = pd.DataFrame(
        {
            "ts_code": pf20.index.astype(str),
            "trade_date": day.strftime("%Y%m%d"),
            "PF": pf20.to_numpy(),
            "VV": vv20.to_numpy(),
            "PF_z": pf_z.to_numpy(),
            "VV_z": vv_z.to_numpy(),
            "component_z": component_z.to_numpy(),
            "composite": composite.to_numpy(),
            "factor_value": composite.to_numpy(),
            "warmup": warmup.to_numpy(),
        }
    )
    return out[OUTPUT_COLUMNS]


def _new_tickers(state: PFVVPartitionState, codes: pd.Index) -> list[str]:
    known = set(state.known_tickers)
    return [str(code) for code in codes if str(code) not in known]


def _mark_failed(state: PFVVPartitionState, exc: Exception) -> None:
    state.failed = True
    state.failed_index = state.next_index
    state.failure_message = f"{type(exc).__name__}: {exc}"
    state.outputs_reusable = False


def stream_pfvv_source_baseline(
    trading_calendar: pd.DataFrame | pd.Series | pd.Index | Sequence[object],
    load_one_day: Callable[[pd.Timestamp], pd.DataFrame | None],
    *,
    state: PFVVPartitionState | None = None,
    stop_index: int | None = None,
    max_calendar_days: int = DEFAULT_MAX_CALENDAR_DAYS,
    max_raw_rows_per_day: int = DEFAULT_MAX_RAW_ROWS_PER_DAY,
    max_tickers_per_day: int = DEFAULT_MAX_TICKERS_PER_DAY,
    max_estimated_bytes_per_day: int = DEFAULT_MAX_ESTIMATED_BYTES_PER_DAY,
) -> Iterator[pd.DataFrame]:
    """Yield one calendar-day PF/VV frame while retaining only a 20-day state.

    ``load_one_day`` receives a normalized ``Timestamp`` and must return that
    day's explicit minute frame once, or ``None``/an empty frame to declare an
    unavailable day.  It must not return another day or a directory-derived
    collection.  To resume, reuse a ``PFVVPartitionState`` built from the same
    complete calendar and advance with ``stop_index``; prior outputs are never
    recomputed when a future ticker appears.  If a day raises after its loader
    has been called, the state is marked failed and cannot be resumed: this
    prevents an accidental second read of the same day.
    """
    if not callable(load_one_day):
        raise TypeError("load_one_day must be callable")
    calendar = _ADAPTER._resolve_calendar(None, trading_calendar)
    _assert_day_budget(
        calendar_days=len(calendar),
        raw_rows=0,
        ticker_count=0,
        max_calendar_days=max_calendar_days,
        max_raw_rows_per_day=max_raw_rows_per_day,
        max_tickers_per_day=max_tickers_per_day,
        max_estimated_bytes_per_day=max_estimated_bytes_per_day,
    )
    if state is None:
        state = PFVVPartitionState(calendar)
    if not isinstance(state, PFVVPartitionState):
        raise TypeError("state must be a PFVVPartitionState")
    if not state.calendar.equals(calendar):
        raise ValueError("state calendar must exactly match the explicit controller calendar")
    _assert_state_can_advance(state, calendar)
    end = len(calendar) if stop_index is None else _positive_int(stop_index, "stop_index")
    if end > len(calendar) or end < state.next_index:
        raise ValueError("stop_index must lie between the current state position and calendar length")

    while state.next_index < end:
        day = calendar[state.next_index]
        try:
            loaded = load_one_day(day)
            if loaded is None or (isinstance(loaded, pd.DataFrame) and loaded.empty):
                pf_daily = pd.Series(np.nan, index=pd.Index(state.known_tickers, name="ts_code"), dtype=float)
                vv_daily_z = pf_daily.copy()
            else:
                frame, today_codes = _ADAPTER._validate_minute_rows(loaded, calendar)
                observed_dates = pd.DatetimeIndex(frame["_trade_date"].unique())
                if len(observed_dates) != 1 or observed_dates[0] != day:
                    raise ValueError("load_one_day must return rows for exactly its requested calendar date")
                prospective_codes = [*state.known_tickers, *_new_tickers(state, today_codes)]
                _assert_day_budget(
                    calendar_days=len(calendar),
                    raw_rows=len(frame),
                    ticker_count=len(prospective_codes),
                    max_calendar_days=max_calendar_days,
                    max_raw_rows_per_day=max_raw_rows_per_day,
                    max_tickers_per_day=max_tickers_per_day,
                    max_estimated_bytes_per_day=max_estimated_bytes_per_day,
                )
                codes = pd.Index(prospective_codes, name="ts_code")
                close, opening, volume = _ADAPTER._one_day_panels(frame, day, codes)
                returns = _KERNEL.minute_returns(close, opening)
                pf_daily = _KERNEL.pf_daily(returns, expected_slots=_ADAPTER.EXPECTED_SLOTS)["daily"]
                vv_daily = _KERNEL.vv_daily(returns, volume, expected_slots=_ADAPTER.EXPECTED_SLOTS)["daily"]
                vv_daily_z = _KERNEL.daily_cross_section_zscore(vv_daily)

            prospective_codes = state.known_tickers if loaded is None or (
                isinstance(loaded, pd.DataFrame) and loaded.empty
            ) else prospective_codes
            next_pf_history, next_vv_z_history, pf20, vv20, warmup = _next_daily_state(
                state,
                prospective_codes,
                pf_daily,
                vv_daily_z,
            )
            output = _output_for_day(day, pf20, vv20, warmup)
        except Exception as exc:
            _mark_failed(state, exc)
            raise
        state.known_tickers = list(prospective_codes)
        state.pf_history = next_pf_history
        state.vv_z_history = next_vv_z_history
        state.next_index += 1
        yield output


def _prepared_state_contract(local_inputs: Any) -> tuple[dict[str, Any], pd.DatetimeIndex, dict[str, Any]]:
    if not isinstance(local_inputs, dict) or local_inputs.get("input_mode") != "derived_state_with_daily":
        raise ValueError("PFVV prepared controller requires local_inputs.input_mode=derived_state_with_daily")
    if local_inputs.get("minute_df_parquet") or local_inputs.get("minute_df_csv"):
        raise ValueError("PFVV prepared controller forbids raw minute input declarations")
    contract = local_inputs.get("pfvv_prepared_daily_state")
    if not isinstance(contract, dict):
        raise ValueError("PFVV prepared controller requires local_inputs.pfvv_prepared_daily_state")
    if contract.get("contract_version") != PREPARED_DAILY_STATE_CONTRACT_VERSION:
        raise ValueError("PFVV prepared daily state has an unsupported contract_version")
    if contract.get("measurement_authority") != PREPARED_DAILY_STATE_AUTHORITY:
        raise ValueError("PFVV prepared daily state must identify pfvv_source_baseline_v1 as its measurement_authority")
    required_columns = contract.get("required_columns")
    if list(required_columns or []) != list(PREPARED_DAILY_STATE_COLUMNS):
        raise ValueError(f"PFVV prepared daily state required_columns must exactly be {list(PREPARED_DAILY_STATE_COLUMNS)}")
    calendar_values = contract.get("calendar_dates")
    if not isinstance(calendar_values, list) or not calendar_values:
        raise ValueError("PFVV prepared daily state requires an explicit nonempty calendar_dates list")
    calendar = _ADAPTER._resolve_calendar(None, calendar_values)
    paths = contract.get("day_paths")
    if not isinstance(paths, dict):
        raise ValueError("PFVV prepared daily state requires an explicit day_paths map")
    expected_keys = {day.strftime("%Y%m%d") for day in calendar}
    if set(paths) != expected_keys:
        raise ValueError("PFVV prepared daily state day_paths must cover exactly the explicit calendar dates")
    return contract, calendar, paths


def _resolve_declared_state_path(derived_state_root: Path, declared: Any) -> Path | None:
    if declared is None:
        return None
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("PFVV prepared daily state path must be a nonempty string or explicit null")
    root = derived_state_root.resolve()
    candidate = Path(declared).expanduser()
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("PFVV prepared daily state path escapes derived_state_root")
    if resolved.suffix.lower() != ".parquet":
        raise ValueError("PFVV prepared daily state partitions must be explicit parquet paths")
    if not resolved.is_file():
        raise ValueError(f"PFVV prepared daily state partition does not exist: {resolved}")
    return resolved


def _canonical_derived_state_root(value: Path) -> Path:
    """Return an existing root only when the caller did not traverse a symlink.

    The manifest's relative paths are an authority boundary.  Resolving a
    caller-supplied symlink silently would make that boundary point at a
    different directory than the explicit input names, so require the caller
    to provide the canonical directory itself.
    """
    requested = Path(value).expanduser()
    lexical = Path(os.path.abspath(os.fspath(requested)))
    try:
        root = lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("PFVV prepared controller derived_state_root must be an existing directory") from exc
    if lexical != root:
        raise ValueError("PFVV prepared controller derived_state_root must not use a symlink alias")
    if not root.is_dir():
        raise ValueError("PFVV prepared controller derived_state_root must be an existing directory")
    return root


def _validate_prepared_daily_frame(loaded: Any, day: pd.Timestamp) -> tuple[pd.Series, pd.Series, pd.Index]:
    if not isinstance(loaded, pd.DataFrame):
        raise TypeError("prepared PFVV daily state loader must return a pandas DataFrame")
    missing = set(PREPARED_DAILY_STATE_COLUMNS) - set(loaded.columns)
    if missing:
        raise ValueError(f"prepared PFVV daily state is missing columns: {sorted(missing)}")
    frame = loaded.loc[:, list(PREPARED_DAILY_STATE_COLUMNS)].copy()
    declared_dates = _ADAPTER._as_date_series(frame["trade_date"], "prepared PFVV trade_date")
    if not declared_dates.eq(day).all():
        raise ValueError("prepared PFVV daily state partition contains a date other than its declared calendar day")
    codes = frame["ts_code"].astype("string").str.strip()
    if codes.isna().any() or (codes == "").any() or not codes.str.fullmatch(r"\d{6}\.(?:SH|SZ)").all():
        raise ValueError("prepared PFVV daily state ts_code must be a six-digit SH or SZ code")
    frame["ts_code"] = codes.astype(str)
    if frame["ts_code"].duplicated().any():
        raise ValueError("prepared PFVV daily state contains duplicate ts_code rows")
    try:
        pf_daily = pd.to_numeric(frame["pf_daily"], errors="raise").astype(float)
        vv_daily = pd.to_numeric(frame["vv_daily"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("prepared PFVV pf_daily/vv_daily must be numeric or missing") from exc
    if np.isinf(pf_daily.to_numpy()).any() or np.isinf(vv_daily.to_numpy()).any():
        raise ValueError("prepared PFVV pf_daily/vv_daily must not contain +/-inf")
    index = pd.Index(frame["ts_code"], name="ts_code")
    return pd.Series(pf_daily.to_numpy(), index=index, dtype=float), pd.Series(vv_daily.to_numpy(), index=index, dtype=float), index


def stream_pfvv_prepared_daily_state(
    trading_calendar: pd.DataFrame | pd.Series | pd.Index | Sequence[object],
    load_one_day: Callable[[pd.Timestamp], pd.DataFrame | None],
    *,
    state: PFVVPartitionState | None = None,
    stop_index: int | None = None,
    max_calendar_days: int = DEFAULT_MAX_CALENDAR_DAYS,
    max_rows_per_day: int = DEFAULT_MAX_TICKERS_PER_DAY,
    max_tickers_per_day: int = DEFAULT_MAX_TICKERS_PER_DAY,
    max_estimated_bytes_per_day: int = DEFAULT_MAX_ESTIMATED_BYTES_PER_DAY,
) -> Iterator[pd.DataFrame]:
    """Stream explicit daily PF/VV components without reading raw minute bars.

    The loader is called once per fixed calendar date and returns only the
    prepared ``pf_daily``/``vv_daily`` state for that date.  An explicit
    ``None`` preserves an unavailable calendar day as NaN for known tickers.
    """
    if not callable(load_one_day):
        raise TypeError("load_one_day must be callable")
    calendar = _ADAPTER._resolve_calendar(None, trading_calendar)
    _assert_day_budget(
        calendar_days=len(calendar), raw_rows=0, ticker_count=0,
        max_calendar_days=max_calendar_days, max_raw_rows_per_day=max_rows_per_day,
        max_tickers_per_day=max_tickers_per_day, max_estimated_bytes_per_day=max_estimated_bytes_per_day,
    )
    if state is None:
        state = PFVVPartitionState(calendar)
    if not isinstance(state, PFVVPartitionState) or not state.calendar.equals(calendar):
        raise ValueError("prepared daily state requires a matching PFVVPartitionState calendar")
    _assert_state_can_advance(state, calendar)
    end = len(calendar) if stop_index is None else _positive_int(stop_index, "stop_index")
    if end > len(calendar) or end < state.next_index:
        raise ValueError("stop_index must lie between the current state position and calendar length")

    while state.next_index < end:
        day = calendar[state.next_index]
        try:
            loaded = load_one_day(day)
            if loaded is None:
                prospective_codes = list(state.known_tickers)
                pf_daily = pd.Series(np.nan, index=pd.Index(prospective_codes, name="ts_code"), dtype=float)
                vv_daily_z = pf_daily.copy()
            else:
                pf_daily, vv_daily, today_codes = _validate_prepared_daily_frame(loaded, day)
                prospective_codes = [*state.known_tickers, *_new_tickers(state, today_codes)]
                _assert_day_budget(
                    calendar_days=len(calendar), raw_rows=len(loaded), ticker_count=len(prospective_codes),
                    max_calendar_days=max_calendar_days, max_raw_rows_per_day=max_rows_per_day,
                    max_tickers_per_day=max_tickers_per_day, max_estimated_bytes_per_day=max_estimated_bytes_per_day,
                )
                pf_daily = pf_daily.reindex(prospective_codes)
                vv_daily_z = _KERNEL.daily_cross_section_zscore(vv_daily.reindex(prospective_codes))
            next_pf_history, next_vv_z_history, pf20, vv20, warmup = _next_daily_state(
                state, prospective_codes, pf_daily, vv_daily_z
            )
            output = _output_for_day(day, pf20, vv20, warmup)
        except Exception as exc:
            _mark_failed(state, exc)
            raise
        state.known_tickers = list(prospective_codes)
        state.pf_history = next_pf_history
        state.vv_z_history = next_vv_z_history
        state.next_index += 1
        yield output


def compute_factor_partitioned(
    *,
    local_inputs: dict[str, Any],
    derived_state_root: Path,
    daily_input_path: Path,
    output_path: Path,
) -> Path:
    """Materialize only the declared prepared PF/VV daily state to ``output_path``.

    This is the Step3B/Step4 partitioned-controller shape.  It never reads
    ``daily_input_path`` and never falls back to raw minute paths.  The manifest
    explicitly names every parquet partition; no directory scan or latest-file
    resolution is performed.
    """
    del daily_input_path
    _, calendar, day_paths = _prepared_state_contract(local_inputs)
    root = _canonical_derived_state_root(derived_state_root)
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError("PFVV prepared controller refuses to overwrite an existing Step-owned output_path")
    if target == root or root in target.parents:
        raise ValueError("PFVV prepared controller output_path must not lie under derived_state_root")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        raise ValueError("PFVV prepared controller found an existing partial output; remove it explicitly before retry")

    def load_one_day(day: pd.Timestamp) -> pd.DataFrame | None:
        path = _resolve_declared_state_path(root, day_paths[day.strftime("%Y%m%d")])
        return None if path is None else pd.read_parquet(path, columns=list(PREPARED_DAILY_STATE_COLUMNS))

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("BLOCK_PFVV_PREPARED_STATE_PARQUET_DEPENDENCY_MISSING") from exc
    writer = None
    try:
        for batch in stream_pfvv_prepared_daily_state(calendar, load_one_day):
            table = pa.Table.from_pandas(batch, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(partial, table.schema)
            writer.write_table(table)
        if writer is None:
            table = pa.Table.from_pandas(_empty_output(), preserve_index=False)
            writer = pq.ParquetWriter(partial, table.schema)
        writer.close()
        writer = None
        try:
            # ``link`` is create-only: unlike replace(), it cannot clobber a
            # concurrently published Step-owned target.  The partial remains
            # for explicit inspection/recovery when publication loses the race.
            os.link(partial, target)
        except FileExistsError as exc:
            raise ValueError(
                "PFVV prepared controller output_path was created concurrently; partial retained"
            ) from exc
        os.unlink(partial)
    finally:
        if writer is not None:
            writer.close()
    return target


__all__ = [
    "METADATA",
    "PFVVPartitionState",
    "compute_factor_partitioned",
    "stream_pfvv_prepared_daily_state",
    "stream_pfvv_source_baseline",
]
