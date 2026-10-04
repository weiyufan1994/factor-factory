"""Explicit prepared-Parquet windows and one-month account IO cache.

Extracted from the accepted account reader; no downloads or factor-specific
imports. The caller supplies the window, selected named roles and column map.
"""
import gc
import hashlib
import resource
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from factor_factory.research_api import _dates, _index


def dates(values):
    return _dates(values, name="prepared input dates")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


class WindowReader:
    def __init__(self, files, *, start, end):
        self.start, self.end = dates([start, end])
        if self.start > self.end:
            raise ValueError("invalid_input_window")
        self.specs = files
        self.datasets = {}
        self.profile = {"queries": 0, "maximum_query_rows": 0, "maximum_query_pandas_bytes": 0,
                        "maximum_month_cache_bytes": 0, "full_market_frame_loaded": False}
        for role in files:
            spec = files[role]
            if digest(spec["path"]) != spec["sha256"]:
                raise ValueError(f"input_hash_mismatch:{role}")
            self.datasets[role] = ds.dataset(spec["path"], format="parquet")

    def read(self, role, start, end, *, symbols=None, columns=None):
        spec, dataset = self.specs[role], self.datasets[role]
        mapping = spec["columns"]
        selected = list(columns or mapping)
        start, end = max(pd.Timestamp(start), self.start), min(pd.Timestamp(end), self.end)
        field = mapping["trade_date"]
        typ = dataset.schema.field(field).type
        if pa.types.is_integer(typ):
            lo, hi = int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))
        elif pa.types.is_timestamp(typ):
            lo, hi = start, end
        elif pa.types.is_date(typ):
            lo, hi = start.date(), end.date()
        elif pa.types.is_string(typ) or pa.types.is_large_string(typ):
            fmt = spec.get("date_format", "%Y-%m-%d")
            if fmt not in ("%Y%m%d", "%Y-%m-%d"):
                raise ValueError("unsupported_date_encoding")
            lo, hi = start.strftime(fmt), end.strftime(fmt)
        else:
            raise ValueError("unsupported_date_type")
        predicate = (ds.field(field) >= lo) & (ds.field(field) <= hi)
        if symbols is not None:
            predicate = predicate & ds.field(mapping["ts_code"]).isin(sorted(symbols))
        # Small Arrow scan batches and no cross-fragment prefetch; the complete
        # selected window is still materialized, explicitly included in budget.
        table = dataset.scanner(columns=[mapping[k] for k in selected], filter=predicate,
            batch_size=16384, batch_readahead=1, fragment_readahead=1, use_threads=False).to_table()
        frame = table.to_pandas().rename(columns={mapping[k]: k for k in selected})
        frame["trade_date"] = dates(frame.trade_date)
        for key in spec.get("invert_boolean", []):
            if key in frame:
                if not frame[key].isin([True, False, 0, 1]).all():
                    raise ValueError(f"unknown_boolean:{role}:{key}")
                frame[key] = ~frame[key].astype(bool)
        if role == "calendar":
            if frame.trade_date.duplicated().any():
                raise ValueError("duplicate_calendar_session")
        else:
            _index(pd.MultiIndex.from_arrays([frame.trade_date, frame.ts_code], names=["datetime", "instrument"]))
        self.profile["queries"] += 1
        self.profile["maximum_query_rows"] = max(self.profile["maximum_query_rows"], len(frame))
        self.profile["maximum_query_pandas_bytes"] = max(self.profile["maximum_query_pandas_bytes"], int(frame.memory_usage(deep=True).sum()))
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.profile["process_peak_rss_bytes"] = int(peak if sys.platform == "darwin" else peak*1024)
        return frame


class MonthlyMarket:
    """One calendar-month IO cache, single-session requested keys to account."""
    def __init__(self, reader, symbols=None):
        self.reader = reader
        self.symbols = symbols
        self.month = None
        self.frame = None

    def for_day(self, day, symbols):
        columns = ["trade_date","ts_code","price","constraint_complete","buy_allowed","sell_allowed"]
        if not symbols:
            return pd.DataFrame(columns=columns).astype({"trade_date":"datetime64[ns]"})
        month = day.to_period("M")
        if self.month != month:
            # Drop old cache BEFORE loading the next, not after a full concat.
            self.frame = None
            gc.collect()
            daily = self.reader.read("daily",month.start_time,month.end_time,symbols=self.symbols,columns=["ts_code","trade_date","close_adj"])
            constraints = self.reader.read("constraints",month.start_time,month.end_time,symbols=self.symbols)
            # Explicit constraints must survive a missing daily bar. In
            # particular, suspension-only stock-days cannot be left-joined away.
            self.frame = daily.rename(columns={"close_adj":"price"}).merge(constraints,on=["ts_code","trade_date"],how="outer",validate="one_to_one")
            if "execution_prices" in self.reader.datasets:
                raw = self.reader.read("execution_prices",month.start_time,month.end_time,symbols=self.symbols)
                self.frame = self.frame.merge(raw,on=["ts_code","trade_date"],how="outer",validate="one_to_one")
                # These raw closes are explicitly prepared from the same fixed
                # publication. They are NOT substitutions for missing marks.
                self.frame["execution_price_basis"] = "unadjusted_close"
            self.month = month
            self.reader.profile["maximum_month_cache_bytes"] = max(self.reader.profile["maximum_month_cache_bytes"],int(self.frame.memory_usage(deep=True).sum()))
        return self.frame.loc[self.frame.trade_date.eq(day) & self.frame.ts_code.isin(symbols)].copy()


