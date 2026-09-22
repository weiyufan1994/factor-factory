"""Step4 custom-backend export for the local PF/VV monthly reconstruction.

The module is intentionally a thin export layer over
``pfvv_monthly_evaluation_v1``.  It never discovers inputs, does not import an
execution engine implicitly, and does not own factor construction or a second
portfolio simulator.  The caller supplies both a closed prepared-input manifest
and a pure execution-engine module path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.mszq_intraday_momentum_pulse import pfvv_monthly_evaluation_v1 as monthly


BACKEND_ID = "pfvv_monthly_cash_v1"
PREPARED_SCHEMA_ID = "pfvv_monthly_step4_prepared_inputs_v1"
FORBIDDEN_TOKEN = "event_u"
REQUIRED_INPUTS = (
    "factor_values_path", "measurement_domain_path", "daily_prices_path",
    "execution_vwap_path", "normalized_constraints_path", "calendar_path", "complete_months",
)
SELECTION_COLUMNS = ("ts_code", "trade_date", "factor_value")
# These are the actual columns consumed by the frozen engine's
# ``_normalize_inputs`` (plus the producer status retained for coverage).  Do
# not turn ``ts_code`` or ``trade_date`` into categoricals here: the frozen
# engine owns its normalisation and key semantics.
INPUT_COLUMNS = {
    "factor_values": SELECTION_COLUMNS,
    "measurement_domain": ("ts_code", "trade_date"),
    "daily_prices": ("ts_code", "trade_date", "close_unadjusted", "adj_factor"),
    "execution_vwap": (
        "ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count",
        "price_basis", "execution_price_status",
    ),
    "normalized_constraints": (
        "ts_code", "trade_date", "constraint_complete", "st_new_buy_blocked",
        "pretrade_buy_blocked", "pretrade_sell_blocked", "is_st_asof_trade",
        "up_limit", "down_limit", "historicalstatus_present", "listing_status",
    ),
    "calendar": ("trade_date", "is_open"),
}
OPTIONAL_INPUT_COLUMNS = {
    # The old engine creates this column only when absent, but it changes
    # delisting valuation when provided, so column projection must keep it.
    "normalized_constraints": ("delist_cash_settlement_unadjusted",),
}
INPUT_PATH_KEYS = {
    "factor_values": "factor_values_path",
    "measurement_domain": "measurement_domain_path",
    "daily_prices": "daily_prices_path",
    "execution_vwap": "execution_vwap_path",
    "normalized_constraints": "normalized_constraints_path",
    "calendar": "calendar_path",
}
MEMORY_SAMPLE_ROWS = 4096
DEFAULT_MEMORY_BUDGET_FRACTION = 0.60
EVALUATION_MODES = ("full_frame", "bounded_lookup_store")
STANDALONE_COMPONENTS = ("PF", "VV")
# A transparent upper-envelope model for the current full-frame adapter.  It
# accounts for shallow-normalisation replacements, index/date-position lookup
# objects, and (for execution) bridge source/coverage/legacy frames.  These are
# estimates, not a claim of measured full-IS RSS.
PEAK_MULTIPLIER_BY_INPUT = {
    "factor_values": 2.0,
    "measurement_domain": 1.5,
    "daily_prices": 2.3,
    "execution_vwap": 3.5,
    "normalized_constraints": 2.3,
    "calendar": 1.3,
}
BOUNDED_LOOKUP_CACHE_DAYS = 4
BOUNDED_LOOKUP_BATCH_ROWS = 65_536
BOUNDED_TRADE_RETAINED_ACCOUNT_MULTIPLIER = 2.0
PRODUCER_EXECUTION_COLUMNS = {
    "ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count", "price_basis",
    "execution_price_status",
}
LEGACY_PRICE_BASIS = "UNADJUSTED_AMOUNT_OVER_VOL"


class PfvvMonthlyBackendError(ValueError):
    """A closed-input or export-contract violation."""


class PfvvMemoryBudgetError(PfvvMonthlyBackendError):
    """Raised before full-frame reads when the explicit memory preflight fails."""

    def __init__(self, report: Mapping[str, object]):
        self.report = dict(report)
        super().__init__("memory_budget_exceeded")


class _RetainedBoundedWorkRoot:
    """Delete bounded intermediates only after a fully published success."""

    def __init__(self, *, prefix: str, parent: Path) -> None:
        self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type: object, exc: BaseException | None, traceback: object) -> bool:
        if exc is None:
            shutil.rmtree(self.path)
            return False
        retained = f"bounded_work_state_retained:{self.path}"
        exc.add_note(retained)
        # Surface the location even in callers that print only ``str(exc)``.
        exc.args = (*exc.args, retained)
        return False


def _evaluation_mode(value: str) -> str:
    mode = str(value or "").strip()
    if mode not in EVALUATION_MODES:
        raise PfvvMonthlyBackendError("evaluation_mode_invalid")
    return mode


def _forbid_event_u(value: Any, field: str = "root") -> None:
    """Reject EVENT_U factor/state/results rather than silently ignoring them."""

    if FORBIDDEN_TOKEN in str(field).casefold():
        raise PfvvMonthlyBackendError(f"EVENT_U_FORBIDDEN:{field}")
    if isinstance(value, str) and FORBIDDEN_TOKEN in value.casefold():
        raise PfvvMonthlyBackendError(f"EVENT_U_FORBIDDEN:{field}")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _forbid_event_u(child, str(key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _forbid_event_u(child, f"{field}[{index}]")


def _input_path(path_value: object, label: str) -> Path:
    path = Path(str(path_value))
    if not path.is_file():
        raise PfvvMonthlyBackendError(f"prepared_input_missing:{label}")

    return path


def _frame_columns(path_value: object, label: str) -> tuple[str, ...]:
    """Inspect the source schema without materialising its data columns."""

    path = _input_path(path_value, label)
    if path.suffix.lower() == ".csv":
        return tuple(pd.read_csv(path, nrows=0).columns.tolist())
    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - pandas parquet needs an engine too
            raise PfvvMonthlyBackendError("prepared_input_parquet_metadata_unavailable") from exc
        return tuple(pq.ParquetFile(path).schema_arrow.names)
    raise PfvvMonthlyBackendError(f"prepared_input_requires_csv_or_parquet:{label}")


def _required_projection(path_value: object, label: str) -> tuple[str, ...]:
    columns = _frame_columns(path_value, label)
    _forbid_event_u(columns, f"{label}.columns")
    required = INPUT_COLUMNS[label]
    missing = sorted(set(required) - set(columns))
    if missing:
        raise PfvvMonthlyBackendError(f"prepared_input_columns_missing:{label}:" + ",".join(missing))
    optional = tuple(column for column in OPTIONAL_INPUT_COLUMNS.get(label, ()) if column in columns)
    return tuple(required) + optional


def _read_frame(path_value: object, label: str, *, columns: tuple[str, ...]) -> pd.DataFrame:
    path = _input_path(path_value, label)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, usecols=list(columns))
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path, columns=list(columns))
    raise PfvvMonthlyBackendError(f"prepared_input_requires_csv_or_parquet:{label}")


def _canonical_regular_path(value: object, label: str) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_file():
        raise PfvvMonthlyBackendError(f"prepared_input_missing:{label}")
    return path.resolve()


def _load_prepared_manifest(path: Path, *, report_id: str) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PfvvMonthlyBackendError("prepared_inputs_unreadable") from exc
    if not isinstance(manifest, dict):
        raise PfvvMonthlyBackendError("prepared_inputs_must_be_object")
    _forbid_event_u(manifest)
    if manifest.get("schema_id") != PREPARED_SCHEMA_ID:
        raise PfvvMonthlyBackendError("prepared_inputs_schema_mismatch")
    if manifest.get("report_id") != report_id:
        raise PfvvMonthlyBackendError("prepared_inputs_report_id_mismatch")
    missing = [key for key in REQUIRED_INPUTS if key not in manifest]
    if missing:
        raise PfvvMonthlyBackendError("prepared_inputs_missing:" + ",".join(missing))
    complete_months = manifest["complete_months"]
    if not isinstance(complete_months, list) or not all(isinstance(value, str) for value in complete_months):
        raise PfvvMonthlyBackendError("prepared_inputs_complete_months_invalid")
    return manifest


def _declared_standalone_components(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Return only the explicitly preregistered PF/VV diagnostic set.

    A missing or empty declaration preserves historical three-column synthetic
    callers.  Any nonempty declaration must be exactly the frozen PF then VV
    order; components are never inferred from convenient output columns.
    """
    value = manifest.get("standalone_components")
    if value is None or value == []:
        return ()
    if value != list(STANDALONE_COMPONENTS):
        raise PfvvMonthlyBackendError("standalone_components_must_be_exact_pf_vv")
    return STANDALONE_COMPONENTS


def _component_factor_values(frame: pd.DataFrame, component: str) -> tuple[pd.DataFrame, dict[str, object]]:
    if component not in STANDALONE_COMPONENTS or component not in frame.columns:
        raise PfvvMonthlyBackendError(f"standalone_component_missing:{component}")
    values = pd.to_numeric(frame[component], errors="coerce")
    result = frame.loc[:, ["ts_code", "trade_date"]].copy()
    # Direction is fixed ex ante: lower PF and lower VV receive the higher
    # standalone score.  No result-dependent sign selection is permitted.
    result["factor_value"] = -values
    finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
    return result, {
        "source_column": component,
        "factor_value_expression": f"-({component})",
        "source_rows": int(len(frame)),
        "finite_source_rows": int(finite.sum()),
        "nonfinite_source_rows": int((~finite).sum()),
    }


def _available_memory_bytes() -> int | None:
    """Return currently available physical memory, without a mandatory dependency."""

    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except (ImportError, AttributeError, OSError):
        try:
            pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            return pages * page_size
        except (AttributeError, OSError, ValueError):
            return None


def _parent_rss_bytes() -> int | None:
    """Best-effort parent RSS, reported as co-resident pressure not double-counted RAM."""

    try:
        import psutil
        return int(psutil.Process(os.getppid()).memory_info().rss)
    except (ImportError, AttributeError, OSError):
        return None


def _declared_row_count(manifest: Mapping[str, object], label: str) -> int | None:
    metadata = manifest.get("input_metadata")
    if not isinstance(metadata, Mapping):
        return None
    item = metadata.get(label)
    if not isinstance(item, Mapping):
        return None
    # Bounded metadata may declare only working-set cardinalities before the
    # formal factor exists.  Its total row count remains the real file footer.
    if "row_count" not in item:
        return None
    value = item.get("row_count")
    if isinstance(value, bool):
        raise PfvvMonthlyBackendError(f"prepared_input_metadata_row_count_invalid:{label}")
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise PfvvMonthlyBackendError(f"prepared_input_metadata_row_count_invalid:{label}") from None
    if count < 0:
        raise PfvvMonthlyBackendError(f"prepared_input_metadata_row_count_invalid:{label}")
    return count


def _bounded_metadata_count(manifest: Mapping[str, object], label: str, field: str) -> int:
    """Require the producer-attested bounded working-set cardinality.

    The bounded route must not scan a full factor parquet merely to discover its
    own monthly working set.  These counts are therefore a closed prepared-input
    requirement, not a fallback estimate from an arbitrary full-frame read.
    """

    metadata = manifest.get("input_metadata")
    item = metadata.get(label) if isinstance(metadata, Mapping) else None
    value = item.get(field) if isinstance(item, Mapping) else None
    if isinstance(value, bool):
        raise PfvvMonthlyBackendError(f"bounded_input_metadata_invalid:{label}:{field}")
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise PfvvMonthlyBackendError(f"bounded_input_metadata_required:{label}:{field}") from None
    if count < 0:
        raise PfvvMonthlyBackendError(f"bounded_input_metadata_invalid:{label}:{field}")
    return count


def _trade_output_sample_bytes(*, compact: bool = False) -> int:
    """Measure a conservative retained old-engine trade-row envelope in pandas."""

    count = MEMORY_SAMPLE_ROWS
    frame = pd.DataFrame({
        "trade_date": ["2016-01-04"] * count,
        "formation_date": ["2015-12-31"] * count,
        "ts_code": ["000001.SZ"] * count,
        "side": ["BUY"] * count,
        "status": ["FILLED"] * count,
        "reason": ["MONTH_END_TOP_QUINTILE"] * count,
        "raw_execution_price": np.ones(count),
        "adj_factor": np.ones(count),
        "gross_amount": np.ones(count),
        "cost": np.zeros(count),
        "net_cash_flow": -np.ones(count),
        "engine_source": ["explicit_frozen_engine"] * count,
        "engine_trade_reason": ["MONTH_END_TOP_QUINTILE"] * count,
        "portfolio_group": ["BENCHMARK_ALL_TEN_GROUPS"] * count,
        "adapter_trade_reason": ["MONTH_END_BENCHMARK_ALL_TEN_GROUPS"] * count,
    })
    if compact:
        frame = monthly._map_account_trades(
            frame, account_id="BENCHMARK_ALL_TEN_GROUPS", engine_source="explicit_frozen_engine",
            counterfactual_rate=0.0,
        )
        # The real universe has more categories than this tiny sample: reserve
        # extra code width and dictionary storage rather than count one symbol.
        return int(math.ceil(frame.memory_usage(index=True, deep=True).sum() / count)) + 32
    return int(math.ceil(frame.memory_usage(index=True, deep=True).sum() / count))


def _parquet_row_count(path: Path) -> int:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise PfvvMonthlyBackendError("prepared_input_parquet_metadata_unavailable") from exc
    return int(pq.ParquetFile(path).metadata.num_rows)


def _csv_row_count(path: Path) -> int:
    # Streaming line count is deliberately bounded in memory; CSV is a test /
    # compatibility format, whereas full IS inputs are expected to be parquet.
    with path.open("rb") as stream:
        return max(0, sum(1 for _ in stream) - 1)


def _sample_pandas_bytes(path: Path, *, columns: tuple[str, ...]) -> tuple[int, int]:
    """Read at most one tiny projected batch to measure pandas' actual dtype cost."""

    if path.suffix.lower() == ".csv":
        sample = pd.read_csv(path, usecols=list(columns), nrows=MEMORY_SAMPLE_ROWS)
    elif path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover
            raise PfvvMonthlyBackendError("prepared_input_parquet_metadata_unavailable") from exc
        batches = pq.ParquetFile(path).iter_batches(batch_size=MEMORY_SAMPLE_ROWS, columns=list(columns))
        batch = next(batches, None)
        if batch is None:
            sample = pd.DataFrame(columns=list(columns))
        else:
            sample = batch.to_pandas()
    else:  # protected by caller, retained for a direct helper call
        raise PfvvMonthlyBackendError("prepared_input_requires_csv_or_parquet:sample")
    return int(len(sample)), int(sample.memory_usage(index=True, deep=True).sum())


def preflight_prepared_inputs(
    prepared_inputs: Path,
    *,
    report_id: str,
    factor_values_override: Path | None = None,
    memory_budget_mb: int | None = None,
    evaluation_mode: str = "full_frame",
) -> dict[str, object]:
    """Estimate the current adapter's co-resident pandas peak before full reads.

    Row counts come from explicit manifest metadata when supplied and from
    parquet footer/streaming CSV metadata otherwise.  Per-row bytes come from
    a projected, at-most-4096-row pandas sample.  The result is intentionally
    an estimate model, not a full-IS capacity assertion.
    """

    mode = _evaluation_mode(evaluation_mode)
    manifest = _load_prepared_manifest(prepared_inputs, report_id=report_id)
    standalone_components = _declared_standalone_components(manifest)
    if standalone_components and mode != "bounded_lookup_store":
        raise PfvvMonthlyBackendError("standalone_components_require_bounded_lookup_store")
    if memory_budget_mb is not None and (isinstance(memory_budget_mb, bool) or int(memory_budget_mb) <= 0):
        raise PfvvMonthlyBackendError("memory_budget_mb_invalid")
    available = _available_memory_bytes()
    if available is None or available <= 0:
        raise PfvvMonthlyBackendError("memory_available_unavailable")
    available_cap = int(available * DEFAULT_MEMORY_BUDGET_FRACTION)
    requested_budget = None if memory_budget_mb is None else int(memory_budget_mb) * 1024 * 1024
    # An explicit deployment limit can only tighten the default; it must not
    # authorize a peak larger than the current physical-memory envelope.
    configured_budget = available_cap if requested_budget is None else min(requested_budget, available_cap)
    budget_source = (
        "available_memory_60_percent_default" if requested_budget is None
        else "min_explicit_memory_budget_mb_and_available_memory_60_percent"
    )

    declared_factor = _canonical_regular_path(manifest["factor_values_path"], "factor_values")
    if factor_values_override is not None:
        actual_override = _canonical_regular_path(factor_values_override, "factor_values_override")
        if actual_override != declared_factor:
            raise PfvvMonthlyBackendError("factor_values_override_manifest_mismatch")
        factor_path = actual_override
    else:
        factor_path = declared_factor
    paths = {label: _input_path(manifest[key], label) for label, key in INPUT_PATH_KEYS.items()}
    paths["factor_values"] = factor_path
    projections = {label: _required_projection(paths[label], label) for label in INPUT_PATH_KEYS}
    if standalone_components:
        available_factor_columns = set(_frame_columns(factor_path, "factor_values"))
        missing_components = sorted(set(standalone_components) - available_factor_columns)
        if missing_components:
            raise PfvvMonthlyBackendError("standalone_component_columns_missing:" + ",".join(missing_components))
        # The bounded store retains all three frozen signal columns at each
        # month end, so memory measurement must not pretend it only reads the
        # composite's three-column view.
        projections["factor_values"] = ("ts_code", "trade_date", "factor_value", *standalone_components)
    if factor_values_override is None and not standalone_components and set(_frame_columns(factor_path, "factor_values")) != set(SELECTION_COLUMNS):
        raise PfvvMonthlyBackendError("factor_values_must_be_exact_pfvv_selection_shape")

    input_estimates: dict[str, dict[str, object]] = {}
    backend_peak = 0
    for label, input_path in paths.items():
        footer_rows = _parquet_row_count(input_path) if input_path.suffix.lower() == ".parquet" else _csv_row_count(input_path)
        declared_rows = _declared_row_count(manifest, label)
        row_count = max(footer_rows, declared_rows or 0)
        sample_rows, sample_bytes = _sample_pandas_bytes(input_path, columns=projections[label])
        bytes_per_row = 0.0 if sample_rows == 0 else sample_bytes / sample_rows
        frame_bytes = int(math.ceil(bytes_per_row * row_count))
        multiplier = PEAK_MULTIPLIER_BY_INPUT[label]
        peak_bytes = int(math.ceil(frame_bytes * multiplier))
        backend_peak += peak_bytes
        input_estimates[label] = {
            "path": str(input_path), "row_count": row_count,
            "row_count_source": "manifest_or_file_metadata_max" if declared_rows is not None else "file_metadata",
            "sample_rows": sample_rows, "sample_pandas_bytes": sample_bytes,
            "estimated_pandas_bytes_per_row": bytes_per_row,
            "selected_columns": list(projections[label]), "peak_multiplier": multiplier,
            "estimated_peak_bytes": peak_bytes,
        }
    bounded_details: dict[str, object] | None = None
    if mode == "bounded_lookup_store":
        # The SQLite store holds at most four date partitions per input.  Factor
        # and domain frames are limited to declared month-end rows.  A source
        # batch and the retained/current old-engine trade ledgers remain live
        # at different points, so each has an explicit measured-envelope term.
        active_rows = {
            "factor_values": _bounded_metadata_count(manifest, "factor_values", "month_end_row_count"),
            "measurement_domain": _bounded_metadata_count(manifest, "measurement_domain", "month_end_row_count"),
            "daily_prices": _bounded_metadata_count(manifest, "daily_prices", "max_rows_per_trade_date") * BOUNDED_LOOKUP_CACHE_DAYS,
            "execution_vwap": _bounded_metadata_count(manifest, "execution_vwap", "max_rows_per_trade_date") * BOUNDED_LOOKUP_CACHE_DAYS,
            "normalized_constraints": _bounded_metadata_count(manifest, "normalized_constraints", "max_rows_per_trade_date") * BOUNDED_LOOKUP_CACHE_DAYS,
            "calendar": int(input_estimates["calendar"]["row_count"]),
        }
        bounded_input_peak = 0
        for label, rows in active_rows.items():
            per_row = float(input_estimates[label]["estimated_pandas_bytes_per_row"])
            peak = int(math.ceil(per_row * rows * PEAK_MULTIPLIER_BY_INPUT[label]))
            input_estimates[label]["bounded_active_rows"] = rows
            input_estimates[label]["bounded_estimated_peak_bytes"] = peak
            bounded_input_peak += peak
        batch_peak = max(
            int(math.ceil(
                float(input_estimates[label]["estimated_pandas_bytes_per_row"])
                * BOUNDED_LOOKUP_BATCH_ROWS * PEAK_MULTIPLIER_BY_INPUT[label]
            ))
            for label in ("factor_values", "daily_prices", "execution_vwap", "normalized_constraints")
        )
        month_end_domain_rows = active_rows["measurement_domain"]
        # Each selected row can have BUY+SELL in both net and zero-cost runs.
        # The benchmark may transiently contain all selections while G01/G10
        # are retained for the diagnostic; this bounds the simultaneous ledger
        # rather than assuming the ten accounts are all resident.
        retained_trade_rows_upper = int(math.ceil(4.8 * month_end_domain_rows))
        trade_row_bytes = _trade_output_sample_bytes(compact=True)
        # The completed net ledger is compacted before the gross simulation.
        # Retain an independent, conservative raw-construction envelope for
        # one BUY+SELL ledger, including its list-to-frame transient buffers.
        raw_trade_row_bytes = _trade_output_sample_bytes()
        raw_construction_rows_upper = int(math.ceil(
            2.0 * month_end_domain_rows * BOUNDED_TRADE_RETAINED_ACCOUNT_MULTIPLIER
        ))
        raw_construction_peak = raw_construction_rows_upper * raw_trade_row_bytes
        trade_peak = retained_trade_rows_upper * trade_row_bytes + raw_construction_peak
        component_signal_peak = 0
        component_view_bytes_per_row = 0.0
        if standalone_components:
            # Components run sequentially against one store, but a new
            # three-column month-end factor view is live next to the retained
            # five-column composite/PF/VV month-end table.  Measure its own
            # projection rather than reusing the composite sample.
            component_sample_rows, component_sample_bytes = _sample_pandas_bytes(
                factor_path, columns=("ts_code", "trade_date", standalone_components[0]),
            )
            component_view_bytes_per_row = (
                0.0 if component_sample_rows == 0 else component_sample_bytes / component_sample_rows
            )
            component_signal_peak = int(math.ceil(
                component_view_bytes_per_row * active_rows["factor_values"] * 1.5
            ))
        # Net+gross across ten disjoint groups and the full-universe benchmark
        # retain independent positions while advancing the same day. Bound
        # even the pathological case where every earlier sell stays blocked.
        import sys
        position_sample = {'ts_code': '000001.SZ', 'formation_date': '2016-01-29',
            'scheduled_exit_date': '2016-03-01', 'units': 1.0, 'last_value': 1.0,
            'stale_days': 1, 'longest_stale_days': 1, 'unvalued_delisted': False}
        position_bytes = sys.getsizeof(position_sample) + sum(sys.getsizeof(k) + sys.getsizeof(v)
            for k, v in position_sample.items()) + 16
        simultaneous_position_rows = 4 * month_end_domain_rows
        position_peak = simultaneous_position_rows * position_bytes
        backend_peak = bounded_input_peak + batch_peak + trade_peak + component_signal_peak + position_peak
        bounded_details = {
            "lookup_cache_days": BOUNDED_LOOKUP_CACHE_DAYS,
            "lookup_batch_rows": BOUNDED_LOOKUP_BATCH_ROWS,
            "estimated_month_end_input_peak_bytes": bounded_input_peak,
            "estimated_source_batch_peak_bytes": batch_peak,
            "estimated_trade_row_bytes": trade_row_bytes,
            "estimated_retained_trade_rows_upper": retained_trade_rows_upper,
            "estimated_retained_trade_peak_bytes": trade_peak,
            "completed_ledger_encoding": "lossless_categorical_text__numeric_values_unchanged",
            "raw_construction_rows_upper": raw_construction_rows_upper,
            "raw_construction_row_bytes": raw_trade_row_bytes,
            "raw_construction_peak_bytes": raw_construction_peak,
            "retained_accounts": ["G01", "G10"],
            "benchmark_transient": True,
            "account_spool_required": True,
            "synchronized_account_count": 22,
            "simultaneous_position_rows_upper": simultaneous_position_rows,
            "estimated_simultaneous_position_peak_bytes": position_peak,
            "standalone_components": list(standalone_components),
            "estimated_sequential_component_month_end_peak_bytes": component_signal_peak,
            "component_view_estimated_pandas_bytes_per_row": component_view_bytes_per_row,
        }

    parent_rss = _parent_rss_bytes()
    parent_remaining = max(0, configured_budget - parent_rss) if parent_rss is not None else None
    co_resident_peak = backend_peak + (parent_rss or 0)
    passes = co_resident_peak <= configured_budget
    report: dict[str, object] = {
        "version": "pfvv_monthly_memory_preflight_v2",
        "evaluation_mode": mode,
        "estimate_method": (
            "file_row_metadata_plus_projected_4096_row_pandas_deep_sample_with_adapter_peak_multipliers"
            if mode == "full_frame"
            else "producer_attested_month_end_and_max_day_counts_plus_projected_4096_row_pandas_samples_with_sqlite_cache_batch_and_retained_trade_envelope"
        ),
        "sample_row_limit": MEMORY_SAMPLE_ROWS,
        "available_memory_bytes": available,
        "available_memory_60_percent_bytes": available_cap,
        "requested_memory_budget_bytes": requested_budget,
        "effective_memory_budget_bytes": configured_budget,
        # Retained as an unambiguous compatibility alias for callers that only
        # need the actual enforced limit.
        "configured_memory_budget_bytes": configured_budget,
        "memory_budget_source": budget_source,
        "parent_rss_bytes": parent_rss,
        "parent_remaining_budget_bytes": parent_remaining,
        "parent_overlap_note": (
            "conservative_co_resident_addition; current_available_memory_already_reflects_parent_usage "
            "and this is not a precise_process_accounting"
        ),
        "estimated_backend_peak_bytes": backend_peak,
        "estimated_co_resident_peak_bytes": co_resident_peak,
        "passes": passes,
        "inputs": input_estimates,
    }
    if bounded_details is not None:
        report["bounded_lookup_store"] = bounded_details
    if not passes:
        report["blocking_reason"] = "BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED"
    return report


def load_prepared_inputs(
    path: Path,
    *,
    report_id: str,
    factor_values_override: Path | None = None,
) -> dict[str, object]:
    """Read only paths named by a closed local prepared-input manifest."""

    manifest = _load_prepared_manifest(path, report_id=report_id)
    complete_months = manifest["complete_months"]
    declared_factor_values = _canonical_regular_path(
        manifest["factor_values_path"], "factor_values"
    )
    if factor_values_override is not None:
        actual_override = _canonical_regular_path(
            factor_values_override, "factor_values_override"
        )
        if actual_override != declared_factor_values:
            raise PfvvMonthlyBackendError("factor_values_override_manifest_mismatch")
        factor_values = _read_frame(actual_override, "factor_values", columns=_required_projection(actual_override, "factor_values"))
    else:
        factor_values = _read_frame(declared_factor_values, "factor_values", columns=_required_projection(declared_factor_values, "factor_values"))
    frames = {
        "factor_values": factor_values,
        "measurement_domain": _read_frame(manifest["measurement_domain_path"], "measurement_domain", columns=_required_projection(manifest["measurement_domain_path"], "measurement_domain")),
        "daily_prices": _read_frame(manifest["daily_prices_path"], "daily_prices", columns=_required_projection(manifest["daily_prices_path"], "daily_prices")),
        "execution_vwap": _read_frame(manifest["execution_vwap_path"], "execution_vwap", columns=_required_projection(manifest["execution_vwap_path"], "execution_vwap")),
        "normalized_constraints": _read_frame(manifest["normalized_constraints_path"], "normalized_constraints", columns=_required_projection(manifest["normalized_constraints_path"], "normalized_constraints")),
        "calendar": _read_frame(manifest["calendar_path"], "calendar", columns=_required_projection(manifest["calendar_path"], "calendar")),
        "complete_months": complete_months,
    }
    for label, frame in frames.items():
        if isinstance(frame, pd.DataFrame):
            _forbid_event_u(frame.columns.tolist(), f"{label}.columns")
    selection_columns = set(SELECTION_COLUMNS)
    if factor_values_override is None:
        if set(frames["factor_values"].columns) != selection_columns:
            raise PfvvMonthlyBackendError("factor_values_must_be_exact_pfvv_selection_shape")
    else:
        if not selection_columns.issubset(frames["factor_values"].columns):
            raise PfvvMonthlyBackendError("factor_values_override_missing_pfvv_selection_columns")
        # This is an explicit Step4-owned artifact override.  The controller's
        # PF/VV/warmup diagnostics remain in its parquet, while the evaluator
        # receives only the declared selection statistic.
        frames["factor_values"] = frames["factor_values"].loc[:, [
            "ts_code", "trade_date", "factor_value",
        ]].copy()
    return frames


def load_execution_engine(*, module_path: str, module_name: str) -> object:
    """Load exactly the caller-named engine file, independent of ``sys.modules``."""

    path = Path(module_path)
    if not path.is_dir():
        raise PfvvMonthlyBackendError("execution_engine_path_missing")
    if not module_name or not module_name.isidentifier():
        raise PfvvMonthlyBackendError("execution_engine_module_invalid")
    source = (path / f"{module_name}.py").resolve()
    if not source.is_file():
        raise PfvvMonthlyBackendError("execution_engine_file_missing")
    unique_name = f"_pfvv_explicit_engine_{module_name}_{abs(hash(str(source)))}"
    spec = importlib.util.spec_from_file_location(unique_name, source)
    if spec is None or spec.loader is None:
        raise PfvvMonthlyBackendError("execution_engine_spec_invalid")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    inserted_dependency_path = False
    if str(path) not in sys.path:
        # The explicit engine can import only siblings in this same caller-named
        # directory (for example its frozen calendar contract).  The target
        # engine itself is still executed from ``source`` above, never resolved
        # by this temporary import path.
        sys.path.insert(0, str(path))
        inserted_dependency_path = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(unique_name, None)
        raise PfvvMonthlyBackendError("execution_engine_import_failed") from exc
    finally:
        if inserted_dependency_path:
            sys.path.remove(str(path))
    actual = Path(str(getattr(module, "__file__", ""))).resolve()
    if actual != source:
        raise PfvvMonthlyBackendError("execution_engine_file_identity_mismatch")
    return module


def bridge_execution_vwap(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map the producer's VWAP schema to old-engine semantics without filling gaps.

    Only an observed 16-bar row is supplied to the legacy execution lookup.
    A null VWAP on such a row is retained because the old engine records it as
    unavailable.  Any non-16 window is excluded rather than rewritten as 16;
    the returned coverage artifact preserves every original row and its reason.
    """

    _forbid_event_u(frame.columns.tolist(), "execution_vwap.columns")
    missing = PRODUCER_EXECUTION_COLUMNS - set(frame.columns)
    if missing:
        raise PfvvMonthlyBackendError("execution_producer_columns_missing:" + ",".join(sorted(missing)))
    source = frame.copy()
    source_count = pd.to_numeric(source["execution_bar_count"], errors="coerce")
    exact_sixteen = source_count.eq(16)
    wrong_basis = ~source["price_basis"].eq(LEGACY_PRICE_BASIS)
    if wrong_basis.any():
        raise PfvvMonthlyBackendError("execution_price_basis_not_legacy_compatible")
    # ``execution_price_status`` is producer evidence, including cases such as
    # AMOUNT_VOLUME_PRICE_RANGE_MISMATCH which intentionally leave VWAP null.
    # It is not an eligibility override: the frozen old-engine bridge still
    # admits exactly observed 16-bar rows and lets its native null-price route
    # handle unavailable execution.
    coverage = source.loc[:, [
        "ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count", "price_basis",
        "execution_price_status",
    ]].copy()
    coverage["legacy_lookup_included"] = exact_sixteen
    coverage["legacy_bridge_status"] = np.select(
        [
            ~exact_sixteen,
            exact_sixteen & coverage["vwap_0945_1000_unadjusted"].isna(),
        ],
        [
            "EXECUTION_UNAVAILABLE_NON16_BAR_WINDOW",
            "LEGACY_NULL_VWAP_RETAINED_AS_UNAVAILABLE",
        ],
        default="LEGACY_16_BAR_VWAP_ROW",
    )
    legacy = source.loc[exact_sixteen, ["ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count", "price_basis"]].copy()
    legacy = legacy.rename(columns={
        "vwap_0945_1000_unadjusted": "vwap_unadjusted",
        "execution_bar_count": "bar_count",
    })
    return legacy, coverage


def _finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _long_side_performance(performance: Mapping[str, object], nav: pd.DataFrame) -> dict[str, object]:
    day_count = max(1, int(len(nav)))
    turnover = _finite_or_none(performance.get("turnover_gross_amount"))
    costs = _finite_or_none(performance.get("cost_sum"))
    return {
        "metric_period": "daily",
        "annualization_factor": 252,
        "long_side_annual_return": _finite_or_none(performance.get("net_annualized_return")),
        "long_side_annual_volatility": _finite_or_none(performance.get("net_annualized_volatility")),
        "long_side_sharpe": _finite_or_none(performance.get("net_annualized_daily_sharpe")),
        "long_side_max_drawdown": _finite_or_none(performance.get("net_max_drawdown")),
        "long_side_recovery_days": _finite_or_none(performance.get("net_recovery_days")),
        "long_side_recovery_status": performance.get("net_recovery_status"),
        "long_side_recovery_lower_bound_days": _finite_or_none(performance.get("net_recovery_lower_bound_days")),
        "long_side_recovery_observation_end": performance.get("net_recovery_observation_end"),
        "long_side_turnover_mean_daily": None if turnover is None else turnover / day_count,
        "trading_cogs_daily": None if costs is None else costs / day_count,
        "cost_adjusted_long_side_sharpe": _finite_or_none(performance.get("net_annualized_daily_sharpe")),
        "gross_zero_cost_counterfactual_annual_return": _finite_or_none(performance.get("gross_annualized_return")),
        "gross_zero_cost_counterfactual_sharpe": _finite_or_none(performance.get("gross_annualized_daily_sharpe")),
    }


def _position_transition_ledger(trades: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "trade_date", "formation_date", "ts_code", "portfolio_group", "side", "status", "reason",
        "gross_amount", "cost", "net_cash_flow", "position_evidence_kind",
    ]
    filled = trades.loc[trades["status"].eq("FILLED")].copy()
    if filled.empty:
        return pd.DataFrame(columns=columns)
    filled["position_evidence_kind"] = np.where(
        filled["side"].eq("BUY"), "OPEN_ORDER_TRANSITION", "CLOSE_OR_SETTLEMENT_ORDER_TRANSITION",
    )
    return filled.reindex(columns=columns)


def _constraint_evidence(trades: pd.DataFrame) -> pd.DataFrame:
    blocked = trades.loc[trades["status"].eq("BLOCKED")]
    if blocked.empty:
        return pd.DataFrame([{"evidence_status": "NO_BLOCKED_ORDER_EVENTS", "reason": None, "event_count": 0}])
    return (
        blocked.groupby(["side", "reason"], dropna=False, as_index=False)
        .size().rename(columns={"size": "event_count"})
        .assign(evidence_status="BLOCKED_ORDER_EVENTS")
    )


def _fee_evidence(trades: pd.DataFrame) -> pd.DataFrame:
    filled = trades.loc[trades["status"].eq("FILLED")]
    if filled.empty:
        return pd.DataFrame([{"evidence_status": "NO_FILLED_ORDERS", "gross_amount": 0.0, "cost": 0.0}])
    return (
        filled.groupby(["side", "reason"], dropna=False, as_index=False)[["gross_amount", "cost"]]
        .sum().assign(evidence_status="FILLED_ORDER_COSTS")
    )


def _account_summary_evidence(evaluation: Mapping[str, object]) -> pd.DataFrame:
    """Persist compact per-account completion evidence when ledgers are released."""

    summaries = evaluation.get("account_summaries")
    if not isinstance(summaries, Mapping):
        return pd.DataFrame(columns=["account_id", "daily_nav_rows", "net_trade_rows", "gross_trade_rows"])
    rows = []
    for account_id, value in summaries.items():
        if not isinstance(value, Mapping):
            continue
        rows.append({
            "account_id": str(value.get("account_id") or account_id),
            "daily_nav_rows": value.get("daily_nav_rows"),
            "net_trade_rows": value.get("net_trade_rows"),
            "gross_trade_rows": value.get("gross_trade_rows"),
        })
    return pd.DataFrame(rows, columns=["account_id", "daily_nav_rows", "net_trade_rows", "gross_trade_rows"])


def _execution_price_status_counts(coverage: pd.DataFrame | None) -> list[dict[str, object]]:
    """Return raw producer status counts as evidence, without changing eligibility."""

    if coverage is None or "execution_price_status" not in coverage.columns:
        return []
    counts = coverage.groupby("execution_price_status", dropna=False).size().reset_index(name="row_count")
    return [
        {
            "execution_price_status": None if pd.isna(row.execution_price_status) else str(row.execution_price_status),
            "row_count": int(row.row_count),
        }
        for row in counts.itertuples(index=False)
    ]


def export_step4_payload(
    *, report_id: str, output: Path, evaluation: Mapping[str, object], execution_coverage: pd.DataFrame | None = None,
    execution_coverage_path: Path | None = None,
    execution_price_status_counts: list[dict[str, object]] | None = None,
    diagnostic_signal: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Write custom-primary artifacts from one in-memory monthly evaluation."""

    if evaluation.get("status") not in {"EVALUABLE", "PARTIAL_EVALUABLE"}:
        raise PfvvMonthlyBackendError("monthly_evaluation_not_exportable")
    accounts = evaluation.get("group_accounts")
    if not isinstance(accounts, Mapping) or not isinstance(accounts.get("G10"), Mapping):
        raise PfvvMonthlyBackendError("preferred_long_group_account_missing")
    g10 = accounts["G10"]
    nav, trades = g10.get("daily_nav"), g10.get("trades")
    performance = g10.get("performance")
    groups, monthly_ic = evaluation.get("groups"), evaluation.get("monthly_ic")
    if not isinstance(nav, pd.DataFrame) or not isinstance(trades, pd.DataFrame) or not isinstance(performance, Mapping):
        raise PfvvMonthlyBackendError("preferred_long_account_shape_invalid")
    if not isinstance(groups, monthly.MonthlyTenGroups) or not isinstance(monthly_ic, pd.DataFrame):
        raise PfvvMonthlyBackendError("monthly_evaluation_evidence_shape_invalid")

    output.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = output.parent / f"{output.stem}__pfvv_monthly_artifacts"
    if output.exists() or artifact_dir.exists():
        raise PfvvMonthlyBackendError("create_only_target_exists")
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{output.stem}__pfvv_staging_", dir=output.parent))
    if execution_coverage_path is not None and not execution_coverage_path.is_file():
        raise PfvvMonthlyBackendError("execution_coverage_path_missing")
    coverage_suffix = execution_coverage_path.suffix if execution_coverage_path is not None else ".csv"
    artifacts = {
        "daily_nav": artifact_dir / "daily_nav.csv",
        "trades": artifact_dir / "trades.csv",
        "monthly_ic": artifact_dir / "monthly_ic_20_trading_days.csv",
        "performance": artifact_dir / "performance.csv",
        "coverage": artifact_dir / "monthly_group_coverage.csv",
        "holdings": artifact_dir / "holdings_order_transition_ledger.csv",
        "fees": artifact_dir / "fees_by_filled_order.csv",
        "trading_constraints": artifact_dir / "trading_constraint_events.csv",
        "group_counts": artifact_dir / "monthly_ten_group_counts.csv",
        "account_summaries": artifact_dir / "monthly_account_completion_summary.csv",
        "execution_coverage": artifact_dir / f"execution_vwap_legacy_bridge_coverage{coverage_suffix}",
    }
    diagnostic_spread = evaluation.get("diagnostic_spread")
    if isinstance(diagnostic_spread, pd.DataFrame):
        artifacts["diagnostic_spread"] = artifact_dir / "g10_minus_g01_daily_return_diagnostic.csv"
    staged = {key: staging_dir / path.name for key, path in artifacts.items()}
    account_spool = evaluation.get("account_spool")
    spooled_artifacts: dict[str, dict[str, Path]] = {}
    try:
        nav.to_csv(staged["daily_nav"], index=False)
        trades.to_csv(staged["trades"], index=False)
        monthly_ic.to_csv(staged["monthly_ic"], index=False)
        pd.DataFrame([dict(performance)]).to_csv(staged["performance"], index=False)
        groups.counts.to_csv(staged["coverage"], index=False)
        _position_transition_ledger(trades).to_csv(staged["holdings"], index=False)
        _fee_evidence(trades).to_csv(staged["fees"], index=False)
        _constraint_evidence(trades).to_csv(staged["trading_constraints"], index=False)
        groups.counts.to_csv(staged["group_counts"], index=False)
        _account_summary_evidence(evaluation).to_csv(staged["account_summaries"], index=False)
        if "diagnostic_spread" in staged:
            diagnostic_spread.to_csv(staged["diagnostic_spread"], index=False)
        if account_spool is not None:
            if not isinstance(account_spool, Mapping):
                raise PfvvMonthlyBackendError("account_spool_invalid")
            required_accounts = {*(f"G{number:02d}" for number in range(1, 11)), "BENCHMARK_ALL_TEN_GROUPS"}
            if set(account_spool) != required_accounts:
                raise PfvvMonthlyBackendError("account_spool_incomplete")
            for account_id in sorted(required_accounts):
                files = account_spool[account_id]
                if not isinstance(files, Mapping) or set(files) != {"daily_nav", "trades", "gross_trades", "performance"}:
                    raise PfvvMonthlyBackendError(f"account_spool_shape_invalid:{account_id}")
                safe_id = account_id.replace("/", "_")
                destination: dict[str, Path] = {}
                for key, raw_source in files.items():
                    source = Path(str(raw_source))
                    if not source.is_file():
                        raise PfvvMonthlyBackendError(f"account_spool_file_missing:{account_id}:{key}")
                    suffix = source.suffix or ".bin"
                    relative = Path("group_accounts") / safe_id / f"{key}{suffix}"
                    target = staging_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    destination[key] = artifact_dir / relative
                spooled_artifacts[account_id] = destination
            spool_manifest = {
                account_id: {key: str(path) for key, path in paths.items()}
                for account_id, paths in spooled_artifacts.items()
            }
            spool_manifest_path = staging_dir / "monthly_all_accounts_artifacts.json"
            spool_manifest_path.write_text(json.dumps(spool_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts["all_accounts_manifest"] = artifact_dir / spool_manifest_path.name
            staged["all_accounts_manifest"] = spool_manifest_path
        if execution_coverage_path is not None:
            shutil.copyfile(execution_coverage_path, staged["execution_coverage"])
        else:
            (execution_coverage if execution_coverage is not None else pd.DataFrame()).to_csv(staged["execution_coverage"], index=False)

        ic_summary = {
            "pearson_ic_mean": _finite_or_none(monthly_ic.get("pearson_ic", pd.Series(dtype=float)).mean()),
            "rank_ic_mean": _finite_or_none(monthly_ic.get("rank_ic", pd.Series(dtype=float)).mean()),
            "observation_count": int(monthly_ic.get("pearson_ic", pd.Series(dtype=float)).notna().sum()),
            "label_contract": "INDEPENDENT_20_TRADING_DAYS__NOT_MONTHLY_PORTFOLIO_NAV",
        }
        long_side = _long_side_performance(performance, nav)
        primary_required = (
            ic_summary["pearson_ic_mean"], ic_summary["rank_ic_mean"],
            long_side["long_side_annual_return"], long_side["long_side_annual_volatility"],
            long_side["long_side_sharpe"], long_side["long_side_max_drawdown"],
            long_side["long_side_turnover_mean_daily"], long_side["trading_cogs_daily"],
            long_side["cost_adjusted_long_side_sharpe"],
        )
        payload_status = "success" if (
            evaluation.get("status") == "EVALUABLE"
            and performance.get("net_valuation_complete") is True
            and performance.get("gross_valuation_complete") is True
            and all(value is not None for value in primary_required)
        ) else "partial"
        payload = {
            "backend": BACKEND_ID,
            "status": payload_status,
            "schema_id": "pfvv_monthly_step4_backend_payload_v1",
            "report_id": report_id,
            "scope": "local_is_only",
            "producer": "pfvv_monthly_step4_backend_v1",
            "diagnostic_signal": dict(diagnostic_signal) if diagnostic_signal is not None else None,
            "engine_source": evaluation.get("engine_source"),
            "portfolio_contract": {
                "signal": "MONTH_END",
                "entry": "NEXT_TRADING_DAY_0945_1000_UNADJUSTED_VWAP",
                "exit": "NEXT_MONTH_REBALANCE_SAME_WINDOW",
                "group_count": 10,
                "preferred_long_group": "G10",
                "g10_minus_g01": "DIAGNOSTIC_ONLY__NOT_A_SHORT_ACCOUNT",
                "one_way_cost_rate": monthly.ONE_WAY_COST,
                "final_immature_month_traded": False,
                "tie_rule": monthly.TIE_RULE,
                "research_window": {"start": monthly.IS_START.isoformat(), "end": monthly.IS_CUTOFF.isoformat()},
            },
            "ic_summary": ic_summary,
            "performance": dict(performance),
            "long_side_performance": long_side,
            "artifacts": {key: str(path) for key, path in artifacts.items()},
            "artifact_paths": [
                *(str(path) for path in artifacts.values()),
                *(str(path) for account in spooled_artifacts.values() for path in account.values()),
            ],
            "summary": {
                "evaluation_status": evaluation.get("status"),
                "non_evaluable_mature_formations": (evaluation.get("contracts") or {}).get("non_evaluable_mature_formations", []),
                "monthly_nav_and_20_day_ic_separate": True,
                "event_u_inputs_rejected": True,
                "execution_bridge": "PRODUCER_VWAP_0945_1000__EXACT_16_BAR_ONLY__NULL_VWAP_RETAINED",
                "execution_price_status_counts": (
                    execution_price_status_counts
                    if execution_price_status_counts is not None
                    else _execution_price_status_counts(execution_coverage)
                ),
                "bounded_lookup_store": evaluation.get("bounded_lookup_store"),
                "all_ten_groups_and_benchmark_spooled": bool(spooled_artifacts),
                "component_diagnostics": evaluation.get("component_diagnostics"),
            },
            "component_diagnostics": evaluation.get("component_diagnostics"),
        }
        staged_payload = staging_dir / "evaluation_payload.json"
        staged_payload.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        staging_dir.replace(artifact_dir)
        # ``replace`` is atomic on this filesystem because staging and final are
        # siblings.  Payload publication happens only after every artifact exists.
        (artifact_dir / staged_payload.name).replace(output)
        return payload
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _resolved_prepared_paths(
    prepared_inputs: Path,
    *, report_id: str, factor_values_override: Path | None,
) -> tuple[dict[str, object], dict[str, Path]]:
    manifest = _load_prepared_manifest(prepared_inputs, report_id=report_id)
    declared_factor = _canonical_regular_path(manifest["factor_values_path"], "factor_values")
    factor_path = declared_factor
    if factor_values_override is not None:
        actual_override = _canonical_regular_path(factor_values_override, "factor_values_override")
        if actual_override != declared_factor:
            raise PfvvMonthlyBackendError("factor_values_override_manifest_mismatch")
        factor_path = actual_override
    paths = {label: _input_path(manifest[key], label) for label, key in INPUT_PATH_KEYS.items()}
    paths["factor_values"] = factor_path
    return manifest, paths


def _stream_execution_coverage(
    execution_path: Path,
    *, output_path: Path,
) -> tuple[Path, list[dict[str, object]]]:
    """Materialize coverage as a bounded audit stream, never a full dataframe.

    The lookup store owns the engine-normalized execution lookup.  This second,
    projection-only source pass is intentionally separate: it preserves every
    producer status and bridge decision as a Step4 artifact without retaining
    the full availability table in the evaluator process.
    """

    if execution_path.suffix.lower() != ".parquet":
        raise PfvvMonthlyBackendError("bounded_execution_coverage_requires_parquet")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - required by bounded store too
        raise PfvvMonthlyBackendError("prepared_input_parquet_metadata_unavailable") from exc
    columns = _required_projection(execution_path, "execution_vwap")
    counts: dict[str | None, int] = {}
    writer = None
    try:
        for batch in pq.ParquetFile(execution_path).iter_batches(
            batch_size=BOUNDED_LOOKUP_BATCH_ROWS, columns=list(columns),
        ):
            _legacy, coverage = bridge_execution_vwap(batch.to_pandas())
            for value, count in coverage.groupby("execution_price_status", dropna=False).size().items():
                key = None if pd.isna(value) else str(value)
                counts[key] = counts.get(key, 0) + int(count)
            table = pa.Table.from_pandas(coverage, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(output_path, table.schema)
            writer.write_table(table)
        if writer is None:
            empty = pd.DataFrame(columns=[
                "ts_code", "trade_date", "vwap_0945_1000_unadjusted", "execution_bar_count",
                "price_basis", "execution_price_status", "legacy_lookup_included", "legacy_bridge_status",
            ])
            writer = pq.ParquetWriter(output_path, pa.Table.from_pandas(empty, preserve_index=False).schema)
        writer.close()
        writer = None
    finally:
        if writer is not None:
            writer.close()
    return output_path, [
        {"execution_price_status": status, "row_count": count}
        for status, count in sorted(counts.items(), key=lambda item: "" if item[0] is None else item[0])
    ]


def _run_bounded_lookup_evaluation(
    *,
    report_id: str,
    output: Path,
    prepared_inputs: Path,
    execution_engine_path: str,
    execution_engine_module: str,
    factor_values_override: Path | None,
) -> tuple[dict[str, object], Path, list[dict[str, object]] | None]:
    """Run the shared kernel from a create-only, day-bounded lookup store."""

    manifest, paths = _resolved_prepared_paths(
        prepared_inputs, report_id=report_id, factor_values_override=factor_values_override,
    )
    projections = {label: _required_projection(paths[label], label) for label in INPUT_PATH_KEYS}
    calendar = _read_frame(paths["calendar"], "calendar", columns=projections["calendar"])
    engine = load_execution_engine(module_path=execution_engine_path, module_name=execution_engine_module)
    from examples.mszq_intraday_momentum_pulse import pfvv_daily_lookup_store_v1 as lookup_store

    output.parent.mkdir(parents=True, exist_ok=True)
    with _RetainedBoundedWorkRoot(prefix=f".{output.stem}__pfvv_lookup_", parent=output.parent) as temp_root:
        store_result = lookup_store.cached_pfvv_daily_lookup_store(
            factor_values_path=paths["factor_values"],
            measurement_domain_path=paths["measurement_domain"],
            daily_prices_path=paths["daily_prices"],
            execution_vwap_path=paths["execution_vwap"],
            normalized_constraints_path=paths["normalized_constraints"],
            calendar=calendar,
            execution_engine=engine,
            cache_root=output.parent / ".pfvv_lookup_cache",
            factor_value_columns=("factor_value", *_declared_standalone_components(manifest)),
            project_structural_nan_factor_tail=True,
        )
        if not isinstance(store_result, Mapping):
            raise PfvvMonthlyBackendError("bounded_lookup_store_result_invalid")
        lookups = store_result.get("lookups")
        if not isinstance(lookups, Mapping) or not all(key in lookups for key in ("daily", "execution", "constraints")):
            raise PfvvMonthlyBackendError("bounded_lookup_store_lookups_missing")
        coverage_path, counts = _stream_execution_coverage(
            paths["execution_vwap"], output_path=temp_root / "execution_coverage.parquet",
        )
        spool_root = temp_root / "account_spool"
        spool_root.mkdir()

        def evaluate_and_spool(signal_label: str, factor_values: pd.DataFrame) -> dict[str, object]:
            """Run one fixed signal and persist every account before release."""
            account_spool: dict[str, dict[str, str]] = {}

            def spool_account(account_id: str, account: Mapping[str, object]) -> None:
                if account_id in account_spool:
                    raise PfvvMonthlyBackendError(f"account_spool_duplicate:{signal_label}:{account_id}")
                directory = spool_root / signal_label / account_id
                directory.mkdir(parents=True)
                expected_frames = ("daily_nav", "trades", "gross_trades")
                files: dict[str, str] = {}
                for key in expected_frames:
                    frame = account.get(key)
                    if not isinstance(frame, pd.DataFrame):
                        raise PfvvMonthlyBackendError(f"account_spool_frame_missing:{signal_label}:{account_id}:{key}")
                    path = directory / f"{key}.parquet"
                    frame.to_parquet(path, index=False)
                    files[key] = str(path)
                performance = account.get("performance")
                if not isinstance(performance, Mapping):
                    raise PfvvMonthlyBackendError(f"account_spool_performance_missing:{signal_label}:{account_id}")
                performance_path = directory / "performance.json"
                performance_path.write_text(json.dumps(dict(performance), ensure_ascii=False, default=_json_default), encoding="utf-8")
                files["performance"] = str(performance_path)
                account_spool[account_id] = files

            evaluation = monthly.evaluate_monthly_groups_from_normalized(
                factor_values=factor_values,
                measurement_domain=store_result.get("month_end_measurement_domain"),
                calendar_dates=store_result.get("calendar_dates"),
                daily_lookup=lookups["daily"],
                execution_lookup=lookups["execution"],
                constraint_lookup=lookups["constraints"],
                complete_months=manifest["complete_months"],
                execution_engine=engine,
                retain_account_ids={"G01", "G10"},
                account_sink=spool_account,
            )
            evaluation["account_spool"] = account_spool
            return evaluation

        composite_factors = store_result.get("month_end_factor_values")
        if not isinstance(composite_factors, pd.DataFrame):
            raise PfvvMonthlyBackendError("bounded_lookup_store_factor_values_missing")
        standalone_components = _declared_standalone_components(manifest)
        required_factor_columns = ("factor_value", *standalone_components)
        if not set(required_factor_columns).issubset(composite_factors.columns):
            raise PfvvMonthlyBackendError("bounded_lookup_store_component_columns_missing")
        evaluation = evaluate_and_spool("COMPOSITE", composite_factors)
        evaluation["bounded_lookup_store"] = {
            "mode": "sqlite_day_lookup_cache",
            "input_store_reuse": store_result.get("reuse"),
            "day_reads": {key: dict(getattr(value, 'day_read_counts', {})) for key, value in lookups.items()},
            "account_schedule": "same_day_independent_net_and_zero_cost_accounts",
            "cache_days": ((store_result.get("qa") or {}).get("cache_days")),
            "batch_size": ((store_result.get("qa") or {}).get("batch_size")),
            "factor_domain_projection": ((store_result.get("qa") or {}).get("factor_domain_projection")),
            "retained_accounts": ["G01", "G10"],
            "benchmark_transient": True,
            "all_accounts_spooled_before_release": True,
            "composite_accounts_released_before_component_diagnostics": bool(standalone_components),
        }
        composite_export_context = {
            key: evaluation.get(key)
            for key in ("status", "engine_source", "groups", "monthly_ic", "diagnostic_spread", "contracts", "account_summaries", "account_spool", "bounded_lookup_store")
        }
        # Main G01/G10 ledgers are on disk now.  Do not retain them beside the
        # current standalone component's G01/G10 ledgers.
        del evaluation
        component_diagnostics: dict[str, object] | None = None
        if standalone_components:
            composite_values = pd.to_numeric(composite_factors["factor_value"], errors="coerce")
            component_diagnostics = {
                "declared_components": list(standalone_components),
                "comparison_contract": "COMPONENTS_USE_OWN_FINITE_SUPPORT__NO_COMMON_MASK_PORTFOLIO_RERUN",
                "composite_finite_rows": int(np.isfinite(composite_values.to_numpy(dtype=float, na_value=np.nan)).sum()),
                "common_finite_pf_vv_composite_rows": int((
                    np.isfinite(composite_values.to_numpy(dtype=float, na_value=np.nan))
                    & np.isfinite(pd.to_numeric(composite_factors["PF"], errors="coerce").to_numpy(dtype=float, na_value=np.nan))
                    & np.isfinite(pd.to_numeric(composite_factors["VV"], errors="coerce").to_numpy(dtype=float, na_value=np.nan))
                ).sum()),
                "components": {},
            }
            component_root = output.parent / "component_diagnostics"
            for component in standalone_components:
                component_frame, support = _component_factor_values(composite_factors, component)
                common = np.isfinite(composite_values.to_numpy(dtype=float, na_value=np.nan)) & np.isfinite(
                    pd.to_numeric(composite_factors[component], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
                )
                support["common_finite_with_composite_rows"] = int(common.sum())
                component_evaluation = evaluate_and_spool(component, component_frame)
                component_output = component_root / f"{output.stem}__{component.lower()}_standalone.json"
                record: dict[str, object] = {"support": support, "evaluation_status": component_evaluation.get("status")}
                if component_evaluation.get("status") in {"EVALUABLE", "PARTIAL_EVALUABLE"}:
                    component_evaluation["bounded_lookup_store"] = {"mode": "sqlite_day_lookup_cache", "reused_from_composite": True}
                    component_payload = export_step4_payload(
                        report_id=report_id, output=component_output, evaluation=component_evaluation,
                        execution_coverage_path=coverage_path, execution_price_status_counts=counts,
                        diagnostic_signal={"component": component, **support},
                    )
                    record.update({"payload_path": str(component_output), "artifacts": component_payload["artifacts"]})
                else:
                    component_root.mkdir(parents=True, exist_ok=True)
                    try:
                        with component_output.open("x", encoding="utf-8") as stream:
                            json.dump({"report_id": report_id, "diagnostic_signal": component, **record}, stream, ensure_ascii=False, indent=2, default=_json_default)
                    except FileExistsError as exc:
                        raise PfvvMonthlyBackendError("create_only_target_exists") from exc
                    record["payload_path"] = str(component_output)
                component_diagnostics["components"][component] = record
                # Retain only the small summary record before the next run.
                if component_evaluation.get("status") in {"EVALUABLE", "PARTIAL_EVALUABLE"}:
                    del component_payload
                del component_evaluation, component_frame
        composite_spool = composite_export_context.get("account_spool")
        if not isinstance(composite_spool, Mapping) or not isinstance(composite_spool.get("G10"), Mapping):
            raise PfvvMonthlyBackendError("composite_account_spool_missing_g10")
        g10_files = composite_spool["G10"]
        try:
            export_evaluation = {
                **composite_export_context,
                "group_accounts": {
                    "G10": {
                        "daily_nav": pd.read_parquet(g10_files["daily_nav"]),
                        "trades": pd.read_parquet(g10_files["trades"]),
                        "gross_trades": pd.read_parquet(g10_files["gross_trades"]),
                        "performance": json.loads(Path(str(g10_files["performance"])).read_text(encoding="utf-8")),
                    },
                },
                "component_diagnostics": component_diagnostics,
            }
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise PfvvMonthlyBackendError("composite_account_spool_rehydrate_failed") from exc
        # The coverage file is copied into the Step4 artifact before this
        # create-only temporary store is removed.
        payload = export_step4_payload(
            report_id=report_id, output=output, evaluation=export_evaluation,
            execution_coverage_path=coverage_path, execution_price_status_counts=counts,
        )
        del export_evaluation, composite_factors
    return payload, output, counts


def run_backend(
    *, report_id: str, output: Path, prepared_inputs: Path, execution_engine_path: str,
    execution_engine_module: str, factor_values_override: Path | None = None,
    memory_budget_mb: int | None = None,
    evaluation_mode: str = "full_frame",
) -> dict[str, object]:
    mode = _evaluation_mode(evaluation_mode)
    memory_preflight = preflight_prepared_inputs(
        prepared_inputs, report_id=report_id, factor_values_override=factor_values_override,
        memory_budget_mb=memory_budget_mb, evaluation_mode=mode,
    )
    if not bool(memory_preflight["passes"]):
        raise PfvvMemoryBudgetError(memory_preflight)
    if mode == "bounded_lookup_store":
        payload, _output, _counts = _run_bounded_lookup_evaluation(
            report_id=report_id, output=output, prepared_inputs=prepared_inputs,
            execution_engine_path=execution_engine_path, execution_engine_module=execution_engine_module,
            factor_values_override=factor_values_override,
        )
    else:
        frames = load_prepared_inputs(
            prepared_inputs,
            report_id=report_id,
            factor_values_override=factor_values_override,
        )
        engine = load_execution_engine(module_path=execution_engine_path, module_name=execution_engine_module)
        legacy_execution, execution_coverage = bridge_execution_vwap(frames["execution_vwap"])
        evaluation = monthly.evaluate_monthly_groups(
            factor_values=frames["factor_values"], measurement_domain=frames["measurement_domain"],
            daily_prices=frames["daily_prices"], execution_vwap=legacy_execution,
            normalized_constraints=frames["normalized_constraints"], calendar=frames["calendar"],
            complete_months=frames["complete_months"], execution_engine=engine,
        )
        payload = export_step4_payload(
            report_id=report_id, output=output, evaluation=evaluation, execution_coverage=execution_coverage,
        )
    payload["resource_budget"] = memory_preflight
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prepared-inputs", required=True)
    parser.add_argument("--execution-engine-path", required=True)
    parser.add_argument("--execution-engine-module", default="mszq_step4_portfolio_evaluator_candidate_v1")
    parser.add_argument("--factor-values")
    parser.add_argument("--memory-budget-mb", type=int)
    parser.add_argument("--evaluation-mode", choices=EVALUATION_MODES, default="full_frame")
    parser.add_argument("--manifest")  # Step4 common envelope; no discovery is performed from it.
    args = parser.parse_args()
    try:
        run_backend(
            report_id=args.report_id, output=Path(args.output), prepared_inputs=Path(args.prepared_inputs),
            execution_engine_path=args.execution_engine_path, execution_engine_module=args.execution_engine_module,
            factor_values_override=Path(args.factor_values) if args.factor_values else None,
            memory_budget_mb=args.memory_budget_mb,
            evaluation_mode=args.evaluation_mode,
        )
    except PfvvMemoryBudgetError as exc:
        print(json.dumps({"status": "blocked", "resource_budget": exc.report}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
