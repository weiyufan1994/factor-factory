#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import boto3
    import pandas as pd
    import tushare as ts
except ImportError as exc:
    print(f"[ERROR] missing dependency: {exc}")
    print("Please install: pip install tushare pandas boto3")
    raise SystemExit(1)


DEFAULT_TOKEN_FILE = "/home/ubuntu/.openclaw/media/inbound/tushares_token---f5492736-ee8f-4214-b0de-0422f0cfa0a3"
DEFAULT_BUCKET = "yufan-data-lake"
DEFAULT_PREFIX = "tushares"
DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parent / "_tushare_nonminute_exports"
DEFAULT_START_DATE = "20100101"
DEFAULT_END_DATE = datetime.utcnow().strftime("%Y%m%d")
DEFAULT_MAX_PER_MINUTE = 45
DEFAULT_RETRY = 5
DEFAULT_SLEEP = 0.20
DEFAULT_STOCK_POOL_STATUSES = ("L", "D", "P", "G")
THS_HOT_MARKETS = ("热股", "ETF", "可转债", "行业板块", "概念板块", "港股", "热基", "美股")
KPL_TAGS = ("涨停", "炸板", "跌停", "自然涨停", "竞价")


@dataclass(frozen=True)
class QueryVariant:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    priority: str
    category_dir: str
    dataset_dir: str
    mode: str
    fetcher_name: str
    page_size: int | None = None
    min_start_date: str | None = None
    max_per_minute: int | None = None
    max_per_hour: int | None = None
    description: str = ""
    static_params: dict[str, Any] = field(default_factory=dict)
    variants: tuple[QueryVariant, ...] = ()
    code_source_dataset: str | None = None
    period_param: str = "period"
    month_param: str = "month"


def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download non-minute Tushare datasets and upload them to S3.")
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--local-root", default=str(DEFAULT_LOCAL_ROOT))
    parser.add_argument("--retry", type=int, default=DEFAULT_RETRY)
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    parser.add_argument("--max-per-minute", type=int, default=DEFAULT_MAX_PER_MINUTE)
    parser.add_argument("--priorities", nargs="*", default=("P0", "P1", "P2"))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--exclude", nargs="*", default=None)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--overwrite-existing", action="store_true")
    parser.add_argument("--max-trade-dates", type=int, default=None)
    parser.add_argument("--max-months", type=int, default=None)
    parser.add_argument("--max-periods", type=int, default=None)
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--recent-days", type=int, default=None)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


class RateLimiter:
    def __init__(self, max_per_minute: int, base_sleep: float, max_per_hour: int | None = None) -> None:
        self.max_per_minute = max_per_minute
        self.base_sleep = base_sleep
        self.window_start = time.time()
        self.count = 0
        self.hour_window_start = time.time()
        self.hour_count = 0
        self.max_per_hour = max_per_hour

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self.window_start
        hour_elapsed = now - self.hour_window_start
        if self.max_per_hour is not None:
            if hour_elapsed >= 3600:
                self.hour_window_start = now
                self.hour_count = 0
            elif self.hour_count >= self.max_per_hour:
                sleep_for = max(0.0, 3600 - hour_elapsed)
                if sleep_for > 0:
                    print(f"[RATE_LIMIT] {self.max_per_hour}/hour reached; sleeping {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                self.hour_window_start = time.time()
                self.hour_count = 0
        if elapsed >= 60:
            self.window_start = now
            self.count = 0
        elif self.count >= self.max_per_minute:
            sleep_for = max(0.0, 60 - elapsed)
            if sleep_for > 0:
                print(f"[RATE_LIMIT] {self.max_per_minute}/min reached; sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for)
            self.window_start = time.time()
            self.count = 0
        if self.base_sleep > 0:
            time.sleep(self.base_sleep)

    def mark(self) -> None:
        self.count += 1
        if self.max_per_hour is not None:
            self.hour_count += 1


class TushareNonMinuteExporter:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.token = args.token or self.read_token(args.token_file)
        if not self.token and not args.dry_run:
            raise ValueError("missing Tushare token")
        if self.token:
            ts.set_token(self.token)
            self.pro = ts.pro_api(self.token)
        else:
            self.pro = None
        self.s3 = boto3.client("s3")
        self.local_root = Path(args.local_root)
        ensure_dir(self.local_root)
        self.limiters: dict[str, RateLimiter] = {}
        self.manifest: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.direct_cache: dict[str, pd.DataFrame] = {}
        self.existing_keys_cache: dict[str, set[str]] = {}
        self._stock_pool_df: pd.DataFrame | None = None
        self._trade_dates: list[str] | None = None

    @staticmethod
    def read_token(path: str) -> str:
        token_path = Path(path)
        if not token_path.exists():
            return ""
        return token_path.read_text(encoding="utf-8").strip()

    def get_limiter(self, spec: DatasetSpec) -> RateLimiter:
        key = spec.name
        limiter = self.limiters.get(key)
        if limiter is None:
            limiter = RateLimiter(
                spec.max_per_minute or self.args.max_per_minute,
                self.args.sleep,
                spec.max_per_hour,
            )
            self.limiters[key] = limiter
        return limiter

    def s3_key(self, *parts: str) -> str:
        base = self.args.prefix.rstrip("/")
        clean = [part.strip("/").replace("\\", "/") for part in parts if part]
        return "/".join([base, *clean])

    def local_path(self, *parts: str) -> Path:
        path = self.local_root.joinpath(*parts)
        ensure_dir(path.parent)
        return path

    def s3_exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.args.bucket, Key=key)
            return True
        except self.s3.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def list_existing_keys(self, prefix: str) -> set[str]:
        cached = self.existing_keys_cache.get(prefix)
        if cached is not None:
            return cached
        keys: set[str] = set()
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.args.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if key:
                    keys.add(key)
        self.existing_keys_cache[prefix] = keys
        return keys

    def upload_file(self, local_path: Path, key: str) -> None:
        print(f"[UPLOAD] {local_path} -> s3://{self.args.bucket}/{key}")
        if not self.args.dry_run:
            self.s3.upload_file(str(local_path), self.args.bucket, key)
        dataset_prefix = "/".join(key.split("/")[:3]) + "/"
        self.existing_keys_cache.setdefault(dataset_prefix, set()).add(key)

    def call_with_retry(self, spec: DatasetSpec, kwargs: dict[str, Any]) -> pd.DataFrame:
        func = getattr(self.pro, spec.fetcher_name)
        limiter = self.get_limiter(spec)
        last_error: Exception | None = None
        for attempt in range(1, self.args.retry + 1):
            try:
                limiter.wait()
                df = func(**kwargs)
                limiter.mark()
                if df is None:
                    return pd.DataFrame()
                return df
            except Exception as exc:
                last_error = exc
                message = str(exc)
                print(f"[WARN] {spec.name} attempt={attempt}/{self.args.retry} kwargs={kwargs} err={message}")
                if "每分钟最多访问该接口" in message:
                    time.sleep(65)
                else:
                    time.sleep(min(attempt * 2, 12))
        raise RuntimeError(f"{spec.name} failed after retries: {last_error}")

    def fetch_paged(self, spec: DatasetSpec, base_kwargs: dict[str, Any]) -> pd.DataFrame:
        page_size = spec.page_size
        if not page_size:
            return self.call_with_retry(spec, base_kwargs)
        frames: list[pd.DataFrame] = []
        offset = 0
        while True:
            kwargs = dict(base_kwargs)
            kwargs["limit"] = page_size
            kwargs["offset"] = offset
            try:
                df = self.call_with_retry(spec, kwargs)
            except Exception as exc:
                message = str(exc)
                if spec.name == "cyq_chips" and offset > 0 and "查询数据失败，请确认参数" in message:
                    break
                raise
            if df is None or df.empty:
                break
            frames.append(df)
            rows = len(df)
            if rows < page_size:
                break
            offset += page_size
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        return out.drop_duplicates().reset_index(drop=True)

    def get_stock_pool_df(self) -> pd.DataFrame:
        if self._stock_pool_df is not None:
            return self._stock_pool_df
        frames: list[pd.DataFrame] = []
        for status in DEFAULT_STOCK_POOL_STATUSES:
            df = self.call_with_retry(
                DatasetSpec(
                    name="stock_pool",
                    priority="P0",
                    category_dir="_meta",
                    dataset_dir="stock_pool",
                    mode="internal",
                    fetcher_name="stock_basic",
                ),
                {
                    "exchange": "",
                    "list_status": status,
                    "fields": "ts_code,symbol,name,area,industry,market,list_status,list_date,delist_date",
                },
            )
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            self._stock_pool_df = pd.DataFrame(columns=["ts_code"])
            return self._stock_pool_df
        pool = pd.concat(frames, ignore_index=True)
        pool = pool.drop_duplicates(subset=["ts_code"]).sort_values(by=["ts_code"]).reset_index(drop=True)
        if self.args.max_stocks:
            pool = pool.head(self.args.max_stocks).reset_index(drop=True)
        self._stock_pool_df = pool
        return pool

    def get_trade_dates(self) -> list[str]:
        if self._trade_dates is not None:
            return self._trade_dates
        df = self.call_with_retry(
            DatasetSpec(
                name="trade_cal",
                priority="P0",
                category_dir="_meta",
                dataset_dir="trade_cal",
                mode="internal",
                fetcher_name="trade_cal",
            ),
            {
                "exchange": "SSE",
                "start_date": self.args.start_date,
                "end_date": self.args.end_date,
                "fields": "cal_date,is_open",
            },
        )
        if df is None or df.empty:
            self._trade_dates = []
            return self._trade_dates
        dates = (
            df[df["is_open"].astype(str) == "1"]["cal_date"]
            .astype(str)
            .sort_values()
            .tolist()
        )
        if self.args.max_trade_dates:
            dates = dates[: self.args.max_trade_dates]
        if self.args.recent_days is not None:
            dates = dates[-self.args.recent_days :]
        self._trade_dates = dates
        return dates

    def get_months(self) -> list[str]:
        start = datetime.strptime(self.args.start_date, "%Y%m%d")
        end = datetime.strptime(self.args.end_date, "%Y%m%d")
        year = start.year
        month = start.month
        months: list[str] = []
        while (year, month) <= (end.year, end.month):
            months.append(f"{year:04d}{month:02d}")
            month += 1
            if month == 13:
                month = 1
                year += 1
        if self.args.max_months:
            months = months[: self.args.max_months]
        return months

    def get_periods(self) -> list[str]:
        start = datetime.strptime(self.args.start_date, "%Y%m%d")
        end = datetime.strptime(self.args.end_date, "%Y%m%d")
        periods: list[str] = []
        for year in range(start.year, end.year + 1):
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
                period = datetime(year, month, day)
                if start <= period <= end:
                    periods.append(period.strftime("%Y%m%d"))
        if self.args.max_periods:
            periods = periods[: self.args.max_periods]
        return periods

    def apply_spec_start_floor(self, spec: DatasetSpec) -> None:
        if not spec.min_start_date:
            return
        if spec.min_start_date > self.args.start_date:
            print(f"[INFO] {spec.name} floor start_date from {self.args.start_date} to {spec.min_start_date}")

    def effective_start_date(self, spec: DatasetSpec) -> str:
        if not spec.min_start_date:
            return self.args.start_date
        return max(self.args.start_date, spec.min_start_date)

    def filtered_trade_dates(self, spec: DatasetSpec) -> list[str]:
        start_date = self.effective_start_date(spec)
        dates = [d for d in self.get_trade_dates() if start_date <= d <= self.args.end_date]
        return dates

    def filtered_months(self, spec: DatasetSpec) -> list[str]:
        start_date = self.effective_start_date(spec)
        start_month = start_date[:6]
        end_month = self.args.end_date[:6]
        return [month for month in self.get_months() if start_month <= month <= end_month]

    def filtered_periods(self, spec: DatasetSpec) -> list[str]:
        start_date = self.effective_start_date(spec)
        return [period for period in self.get_periods() if start_date <= period <= self.args.end_date]

    def month_window(self, month: str) -> tuple[str, str]:
        year = int(month[:4])
        mon = int(month[4:6])
        last_day = calendar.monthrange(year, mon)[1]
        return f"{year:04d}{mon:02d}01", f"{year:04d}{mon:02d}{last_day:02d}"

    def variant_segments(self, variant: QueryVariant | None) -> list[str]:
        if variant is None or not variant.params:
            return []
        return [f"{key}={value}" for key, value in sorted(variant.params.items())]

    def write_partition(
        self,
        spec: DatasetSpec,
        df: pd.DataFrame,
        filename: str,
        key_segments: list[str],
        meta: dict[str, Any],
    ) -> None:
        local_path = self.local_path(spec.category_dir, spec.dataset_dir, *key_segments, filename)
        df.to_csv(local_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL, escapechar="\\")
        key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
        self.upload_file(local_path, key)
        self.manifest.append(
            {
                "dataset": spec.name,
                "priority": spec.priority,
                "category_dir": spec.category_dir,
                "dataset_dir": spec.dataset_dir,
                "rows": int(len(df)),
                "columns": list(df.columns),
                "s3_key": key,
                "generated_at_utc": now_utc_str(),
                **meta,
            }
        )

    def record_failure(self, spec: DatasetSpec, context: dict[str, Any], error: Exception) -> None:
        item = {
            "dataset": spec.name,
            "priority": spec.priority,
            "error": str(error),
            "context": context,
            "failed_at_utc": now_utc_str(),
        }
        self.failures.append(item)
        print(f"[FAIL] {spec.name} context={context} err={error}")
        if self.args.stop_on_error:
            raise error

    def should_skip(self, key: str, dataset_prefix: str) -> bool:
        if self.args.overwrite_existing:
            return False
        if not self.args.skip_existing:
            return False
        return key in self.list_existing_keys(dataset_prefix)

    def run_direct_snapshot(self, spec: DatasetSpec) -> None:
        variant_plan = spec.variants or (QueryVariant(name="default"),)
        for variant in variant_plan:
            key_segments = self.variant_segments(variant)
            filename = "snapshot.csv" if not key_segments else f"{spec.name}_{variant.name}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            kwargs.update(variant.params)
            if spec.fetcher_name == "ths_index":
                df = self.fetch_paged(spec, kwargs)
                self.direct_cache[spec.name] = df
            else:
                df = self.fetch_paged(spec, kwargs)
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} returned empty")
                continue
            self.write_partition(spec, df, filename, key_segments, {"mode": spec.mode, "params": kwargs})

    def run_trade_date_partitions(self, spec: DatasetSpec) -> None:
        dates = self.filtered_trade_dates(spec)
        variants = spec.variants or (QueryVariant(name="default"),)
        for trade_date in dates:
            for variant in variants:
                key_segments = [*self.variant_segments(variant), f"trade_date={trade_date}"]
                filename = f"{spec.name}_{trade_date}.csv"
                key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
                dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
                if self.should_skip(key, dataset_prefix):
                    print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                    continue
                kwargs = dict(spec.static_params)
                kwargs.update(variant.params)
                kwargs["trade_date"] = trade_date
                try:
                    df = self.fetch_paged(spec, kwargs)
                except Exception as exc:
                    self.record_failure(spec, {"trade_date": trade_date, "variant": variant.name}, exc)
                    continue
                if df is None or df.empty:
                    print(f"[SKIP] {spec.name} trade_date={trade_date} variant={variant.name} empty")
                    continue
                self.write_partition(
                    spec,
                    df,
                    filename,
                    key_segments,
                    {"mode": spec.mode, "trade_date": trade_date, "params": kwargs},
                )

    def run_report_date_partitions(self, spec: DatasetSpec) -> None:
        dates = self.filtered_trade_dates(spec)
        for report_date in dates:
            key_segments = [f"report_date={report_date}"]
            filename = f"{spec.name}_{report_date}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            kwargs["report_date"] = report_date
            try:
                df = self.fetch_paged(spec, kwargs)
            except Exception as exc:
                self.record_failure(spec, {"report_date": report_date}, exc)
                continue
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} report_date={report_date} empty")
                continue
            self.write_partition(
                spec,
                df,
                filename,
                key_segments,
                {"mode": spec.mode, "report_date": report_date, "params": kwargs},
            )

    def run_month_partitions(self, spec: DatasetSpec) -> None:
        months = self.filtered_months(spec)
        for month in months:
            key_segments = [f"month={month}"]
            filename = f"{spec.name}_{month}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            if spec.fetcher_name == "report_rc":
                start_date, end_date = self.month_window(month)
                kwargs.update({"start_date": start_date, "end_date": end_date})
            else:
                kwargs[spec.month_param] = month
            try:
                df = self.fetch_paged(spec, kwargs)
            except Exception as exc:
                self.record_failure(spec, {"month": month}, exc)
                continue
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} month={month} empty")
                continue
            self.write_partition(spec, df, filename, key_segments, {"mode": spec.mode, "month": month, "params": kwargs})

    def run_period_partitions(self, spec: DatasetSpec) -> None:
        periods = self.filtered_periods(spec)
        for period in periods:
            key_segments = [f"period={period}"]
            filename = f"{spec.name}_{period}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            kwargs[spec.period_param] = period
            try:
                df = self.fetch_paged(spec, kwargs)
            except Exception as exc:
                self.record_failure(spec, {"period": period}, exc)
                continue
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} period={period} empty")
                continue
            self.write_partition(spec, df, filename, key_segments, {"mode": spec.mode, "period": period, "params": kwargs})

    def get_code_source_values(self, spec: DatasetSpec) -> list[str]:
        if spec.code_source_dataset == "ths_index":
            df = self.direct_cache.get("ths_index")
            if df is None or df.empty:
                df = self.fetch_paged(self.build_specs()["ths_index"], {})
                self.direct_cache["ths_index"] = df
            values = df["ts_code"].dropna().astype(str).unique().tolist()
            return sorted(values)
        raise ValueError(f"unsupported code source: {spec.code_source_dataset}")

    def run_code_partitions(self, spec: DatasetSpec) -> None:
        codes = self.get_code_source_values(spec)
        if self.args.max_stocks:
            codes = codes[: self.args.max_stocks]
        for code in codes:
            key_segments = [f"ts_code={code}"]
            filename = f"{spec.name}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            kwargs["ts_code"] = code
            try:
                df = self.fetch_paged(spec, kwargs)
            except Exception as exc:
                self.record_failure(spec, {"ts_code": code}, exc)
                continue
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} ts_code={code} empty")
                continue
            self.write_partition(spec, df, filename, key_segments, {"mode": spec.mode, "ts_code": code, "params": kwargs})

    def run_stock_range_partitions(self, spec: DatasetSpec) -> None:
        stock_pool = self.get_stock_pool_df()
        start_date = self.effective_start_date(spec)
        codes = stock_pool["ts_code"].dropna().astype(str).tolist()
        for ts_code in codes:
            key_segments = [f"ts_code={ts_code}"]
            filename = f"{spec.name}.csv"
            key = self.s3_key(spec.category_dir, spec.dataset_dir, *key_segments, filename)
            dataset_prefix = self.s3_key(spec.category_dir, spec.dataset_dir) + "/"
            if self.should_skip(key, dataset_prefix):
                print(f"[SKIP] existing s3://{self.args.bucket}/{key}")
                continue
            kwargs = dict(spec.static_params)
            kwargs.update({"ts_code": ts_code, "start_date": start_date, "end_date": self.args.end_date})
            try:
                df = self.fetch_paged(spec, kwargs)
            except Exception as exc:
                self.record_failure(spec, {"ts_code": ts_code}, exc)
                continue
            if df is None or df.empty:
                print(f"[SKIP] {spec.name} ts_code={ts_code} empty")
                continue
            self.write_partition(
                spec,
                df,
                filename,
                key_segments,
                {"mode": spec.mode, "ts_code": ts_code, "params": kwargs},
            )

    def write_meta_files(self) -> None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        manifest_path = self.local_path("_meta", f"manifest_nonminute_{stamp}.json")
        payload = {
            "generated_at_utc": now_utc_str(),
            "bucket": self.args.bucket,
            "prefix": self.args.prefix,
            "start_date": self.args.start_date,
            "end_date": self.args.end_date,
            "items": self.manifest,
            "failures": self.failures,
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_key = self.s3_key("_meta", manifest_path.name)
        self.upload_file(manifest_path, manifest_key)

    def build_specs(self) -> dict[str, DatasetSpec]:
        return {
            "limit_list_d": DatasetSpec(
                name="limit_list_d",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="涨跌停数据",
                mode="trade_date_partitions",
                fetcher_name="limit_list_d",
                page_size=2500,
                min_start_date="20200101",
                description="涨跌停和炸板数据",
            ),
            "dc_concept": DatasetSpec(
                name="dc_concept",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="题材数据",
                mode="trade_date_partitions",
                fetcher_name="dc_concept",
                page_size=5000,
                min_start_date="20260203",
                description="东方财富题材库",
            ),
            "ths_index": DatasetSpec(
                name="ths_index",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="同花顺行业概念板块",
                mode="direct_snapshot",
                fetcher_name="ths_index",
                description="同花顺概念和行业指数字典",
            ),
            "ths_member": DatasetSpec(
                name="ths_member",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="同花顺行业概念成分",
                mode="code_partitions",
                fetcher_name="ths_member",
                code_source_dataset="ths_index",
                description="同花顺概念和行业指数成分",
            ),
            "dc_index": DatasetSpec(
                name="dc_index",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="东方财富概念板块",
                mode="trade_date_partitions",
                fetcher_name="dc_index",
                page_size=5000,
                min_start_date="20241220",
                description="东方财富概念板块列表",
            ),
            "dc_member": DatasetSpec(
                name="dc_member",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="东方财富概念成分",
                mode="trade_date_partitions",
                fetcher_name="dc_member",
                page_size=5000,
                min_start_date="20241220",
                description="东方财富板块成分",
            ),
            "dc_concept_cons": DatasetSpec(
                name="dc_concept_cons",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="东方财富题材成分",
                mode="trade_date_partitions",
                fetcher_name="dc_concept_cons",
                page_size=3000,
                min_start_date="20260203",
                description="东方财富题材成分",
            ),
            "ths_hot": DatasetSpec(
                name="ths_hot",
                priority="P0",
                category_dir="打板专题数据",
                dataset_dir="同花顺热榜",
                mode="trade_date_partitions",
                fetcher_name="ths_hot",
                page_size=2000,
                min_start_date="20240101",
                variants=tuple(QueryVariant(name=market, params={"market": market}) for market in THS_HOT_MARKETS),
                description="同花顺热榜多市场维度",
            ),
            "moneyflow": DatasetSpec(
                name="moneyflow",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="个股资金流向",
                mode="trade_date_partitions",
                fetcher_name="moneyflow",
                page_size=6000,
                description="个股资金流向",
            ),
            "moneyflow_ths": DatasetSpec(
                name="moneyflow_ths",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="个股资金流向_THS",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_ths",
                page_size=6000,
                min_start_date="20240101",
                description="个股资金流向 THS 口径",
            ),
            "moneyflow_dc": DatasetSpec(
                name="moneyflow_dc",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="个股资金流向_DC",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_dc",
                page_size=6000,
                min_start_date="20240101",
                description="个股资金流向 DC 口径",
            ),
            "moneyflow_cnt_ths": DatasetSpec(
                name="moneyflow_cnt_ths",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="概念板块资金流向_THS",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_cnt_ths",
                page_size=5000,
                min_start_date="20240101",
                description="同花顺概念板块资金流向",
            ),
            "moneyflow_ind_ths": DatasetSpec(
                name="moneyflow_ind_ths",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="行业资金流向_THS",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_ind_ths",
                page_size=5000,
                min_start_date="20240101",
                description="同花顺行业资金流向",
            ),
            "moneyflow_ind_dc": DatasetSpec(
                name="moneyflow_ind_dc",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="行业概念板块资金流向_DC",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_ind_dc",
                page_size=5000,
                min_start_date="20240101",
                description="东方财富行业概念板块资金流向",
            ),
            "moneyflow_mkt_dc": DatasetSpec(
                name="moneyflow_mkt_dc",
                priority="P0",
                category_dir="资金流向数据",
                dataset_dir="大盘资金流向_DC",
                mode="trade_date_partitions",
                fetcher_name="moneyflow_mkt_dc",
                page_size=3000,
                min_start_date="20240101",
                description="东方财富大盘资金流向",
            ),
            "hm_list": DatasetSpec(
                name="hm_list",
                priority="P1",
                category_dir="打板专题数据",
                dataset_dir="游资名录",
                mode="direct_snapshot",
                fetcher_name="hm_list",
                description="游资名录字典",
            ),
            "kpl_list": DatasetSpec(
                name="kpl_list",
                priority="P1",
                category_dir="打板专题数据",
                dataset_dir="开盘啦榜单数据",
                mode="trade_date_partitions",
                fetcher_name="kpl_list",
                page_size=8000,
                min_start_date="20240101",
                variants=tuple(QueryVariant(name=tag, params={"tag": tag}) for tag in KPL_TAGS),
                description="开盘啦榜单多标签",
            ),
            "kpl_concept_cons": DatasetSpec(
                name="kpl_concept_cons",
                priority="P1",
                category_dir="打板专题数据",
                dataset_dir="开盘啦题材成分",
                mode="trade_date_partitions",
                fetcher_name="kpl_concept_cons",
                page_size=3000,
                min_start_date="20240101",
                description="开盘啦题材成分",
            ),
            "cyq_perf": DatasetSpec(
                name="cyq_perf",
                priority="P1",
                category_dir="特色数据",
                dataset_dir="每日筹码及胜率",
                mode="trade_date_partitions",
                fetcher_name="cyq_perf",
                page_size=20000,
                description="每日筹码及胜率",
            ),
            "cyq_chips": DatasetSpec(
                name="cyq_chips",
                priority="P1",
                category_dir="特色数据",
                dataset_dir="每日筹码分布",
                mode="stock_range_partitions",
                fetcher_name="cyq_chips",
                page_size=5000,
                description="每日筹码分布按股票历史区间拉取",
            ),
            "stk_factor_pro": DatasetSpec(
                name="stk_factor_pro",
                priority="P1",
                category_dir="特色数据",
                dataset_dir="股票技术面因子_专业版",
                mode="trade_date_partitions",
                fetcher_name="stk_factor_pro",
                page_size=6000,
                description="股票技术面因子专业版",
            ),
            "broker_recommend": DatasetSpec(
                name="broker_recommend",
                priority="P1",
                category_dir="特色数据",
                dataset_dir="券商每月荐股",
                mode="month_partitions",
                fetcher_name="broker_recommend",
                page_size=5000,
                min_start_date="20200101",
                description="券商月度金股",
            ),
            "margin": DatasetSpec(
                name="margin",
                priority="P1",
                category_dir="两融及转融通",
                dataset_dir="融资融券交易汇总",
                mode="trade_date_partitions",
                fetcher_name="margin",
                page_size=4000,
                description="融资融券交易汇总",
            ),
            "margin_detail": DatasetSpec(
                name="margin_detail",
                priority="P1",
                category_dir="两融及转融通",
                dataset_dir="融资融券交易明细",
                mode="trade_date_partitions",
                fetcher_name="margin_detail",
                page_size=6000,
                description="融资融券交易明细",
            ),
            "report_rc": DatasetSpec(
                name="report_rc",
                priority="P2",
                category_dir="特色数据",
                dataset_dir="卖方盈利预测数据",
                mode="report_date_partitions",
                fetcher_name="report_rc",
                page_size=3000,
                max_per_minute=2,
                max_per_hour=10,
                description="券商盈利预测数据，按报告日期做日增量拉取",
            ),
            "income_vip": DatasetSpec(
                name="income_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="利润表",
                mode="period_partitions",
                fetcher_name="income_vip",
                page_size=5000,
                description="利润表 VIP 全市场报告期分片",
            ),
            "balancesheet_vip": DatasetSpec(
                name="balancesheet_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="资产负债表",
                mode="period_partitions",
                fetcher_name="balancesheet_vip",
                page_size=5000,
                description="资产负债表 VIP 全市场报告期分片",
            ),
            "cashflow_vip": DatasetSpec(
                name="cashflow_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="现金流量表",
                mode="period_partitions",
                fetcher_name="cashflow_vip",
                page_size=5000,
                description="现金流量表 VIP 全市场报告期分片",
            ),
            "forecast_vip": DatasetSpec(
                name="forecast_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="业绩预告",
                mode="period_partitions",
                fetcher_name="forecast_vip",
                page_size=5000,
                description="业绩预告 VIP 全市场报告期分片",
            ),
            "express_vip": DatasetSpec(
                name="express_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="业绩快报",
                mode="period_partitions",
                fetcher_name="express_vip",
                page_size=5000,
                description="业绩快报 VIP 全市场报告期分片",
            ),
            "fina_indicator_vip": DatasetSpec(
                name="fina_indicator_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="财务指标数据",
                mode="period_partitions",
                fetcher_name="fina_indicator_vip",
                page_size=5000,
                description="财务指标 VIP 全市场报告期分片",
            ),
            "fina_mainbz_vip": DatasetSpec(
                name="fina_mainbz_vip",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="主营业务构成",
                mode="period_partitions",
                fetcher_name="fina_mainbz_vip",
                page_size=5000,
                description="主营业务构成 VIP 全市场报告期分片",
            ),
            "disclosure_date": DatasetSpec(
                name="disclosure_date",
                priority="P2",
                category_dir="财务数据",
                dataset_dir="财报披露计划",
                mode="period_partitions",
                fetcher_name="disclosure_date",
                page_size=5000,
                period_param="end_date",
                description="财报披露日期表按报告期分片",
            ),
        }

    def plan(self) -> list[DatasetSpec]:
        specs = self.build_specs()
        plan = list(specs.values())
        if self.args.priorities:
            priorities = set(self.args.priorities)
            plan = [spec for spec in plan if spec.priority in priorities]
        if self.args.only:
            wanted = set(self.args.only)
            plan = [spec for spec in plan if spec.name in wanted]
        if self.args.exclude:
            blocked = set(self.args.exclude)
            plan = [spec for spec in plan if spec.name not in blocked]
        return plan

    def run_spec(self, spec: DatasetSpec) -> None:
        print(f"\n[START] {spec.priority} / {spec.name} / mode={spec.mode}")
        if spec.mode == "direct_snapshot":
            self.run_direct_snapshot(spec)
        elif spec.mode == "trade_date_partitions":
            self.run_trade_date_partitions(spec)
        elif spec.mode == "month_partitions":
            self.run_month_partitions(spec)
        elif spec.mode == "period_partitions":
            self.run_period_partitions(spec)
        elif spec.mode == "report_date_partitions":
            self.run_report_date_partitions(spec)
        elif spec.mode == "code_partitions":
            self.run_code_partitions(spec)
        elif spec.mode == "stock_range_partitions":
            self.run_stock_range_partitions(spec)
        else:
            raise ValueError(f"unknown mode: {spec.mode}")

    def run(self) -> None:
        plan = self.plan()
        if not plan:
            print("[INFO] no matched datasets")
            return
        print("[PLAN]")
        for spec in plan:
            print(f"  - {spec.priority} / {spec.name} / {spec.category_dir} / {spec.dataset_dir} / {spec.mode}")
        if self.args.dry_run:
            return
        for spec in plan:
            try:
                self.run_spec(spec)
            except Exception as exc:
                self.record_failure(spec, {"mode": spec.mode}, exc)
        self.write_meta_files()
        print("\n[DONE] non-minute datasets processed")


def main() -> None:
    args = parse_args()
    if args.overwrite_existing:
        args.skip_existing = False
    try:
        exporter = TushareNonMinuteExporter(args)
        exporter.run()
    except Exception as exc:
        print(f"[FATAL] {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
