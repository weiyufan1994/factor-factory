#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

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
DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parent / "_tushare_global_derivatives_exports"
DEFAULT_START_DATE = "19900101"
DEFAULT_END_DATE = datetime.utcnow().strftime("%Y%m%d")
US_EXCHANGES = ("NAS", "NYS", "OTC", "AMEX", "ARC")
OPTION_EXCHANGES = ("SSE", "SZSE", "CFFEX", "DCE", "SHFE", "CZCE")
FUTURE_EXCHANGES = ("CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")
FUTURE_EXCHANGE_SUFFIX = {
    "CFFEX": "CFX",
    "DCE": "DCE",
    "CZCE": "ZCE",
    "SHFE": "SHF",
    "INE": "INE",
    "GFEX": "GFE",
}
US_BASIC_DATASETS = {"us_basic", "us_tradecal"}
US_MARKET_DAILY_DATASETS = {"us_daily", "us_daily_adj", "us_adjfactor"}
US_FINANCIAL_DATASETS = {"us_income", "us_balancesheet", "us_cashflow", "us_fina_indicator"}
OPTION_DATASETS = {"opt_basic", "opt_daily"}
FUTURE_DATASETS = {
    "fut_basic",
    "fut_daily",
    "fut_holding",
    "fut_wsr",
    "fut_settle",
    "fut_mapping",
    "fut_weekly_detail",
}
ALL_DATASETS = (
    sorted(US_BASIC_DATASETS)
    + sorted(US_MARKET_DAILY_DATASETS)
    + sorted(US_FINANCIAL_DATASETS)
    + sorted(OPTION_DATASETS)
    + sorted(FUTURE_DATASETS)
)
DATASET_DIRS = {
    "us_basic": ("美股专题数据", "美股基本信息"),
    "us_tradecal": ("美股专题数据", "美股交易日历"),
    "us_daily": ("美股专题数据", "美股日线行情"),
    "us_daily_adj": ("美股专题数据", "美股复权日线行情"),
    "us_adjfactor": ("美股专题数据", "美股复权因子"),
    "us_income": ("美股专题数据", "美股利润表"),
    "us_balancesheet": ("美股专题数据", "美股资产负债表"),
    "us_cashflow": ("美股专题数据", "美股现金流量表"),
    "us_fina_indicator": ("美股专题数据", "美股财务指标"),
    "opt_basic": ("期权专题数据", "期权基本信息"),
    "opt_daily": ("期权专题数据", "期权日线行情"),
    "fut_basic": ("期货专题数据", "期货基本信息"),
    "fut_daily": ("期货专题数据", "期货日线行情"),
    "fut_holding": ("期货专题数据", "每日成交持仓排名"),
    "fut_wsr": ("期货专题数据", "仓单日报"),
    "fut_settle": ("期货专题数据", "结算参数"),
    "fut_mapping": ("期货专题数据", "期货主力与连续合约映射"),
    "fut_weekly_detail": ("期货专题数据", "期货主要品种交易周报"),
}
DATASET_PAGE_SIZE = {
    "us_basic": 5000,
    "us_daily": 6000,
    "us_daily_adj": 8000,
    "us_adjfactor": 15000,
    "opt_daily": 15000,
    "fut_basic": 10000,
}


def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_segment(value: Any) -> str:
    text = str(value).strip()
    return text.replace("/", "_").replace("\\", "_").replace(" ", "_")


def parse_yyyymmdd(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Tushare US, options, and futures datasets into separated S3 namespaces."
    )
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--local-root", default=str(DEFAULT_LOCAL_ROOT))
    parser.add_argument("--datasets", nargs="*", default=("all",))
    parser.add_argument("--scopes", nargs="*", default=("all",), choices=("all", "us", "options", "futures"))
    parser.add_argument("--page-size", type=int, default=None)
    parser.add_argument("--max-per-minute", type=int, default=60)
    parser.add_argument("--sleep", type=float, default=0.10)
    parser.add_argument("--retry", type=int, default=5)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--overwrite-existing", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recent-days", type=int, default=None)
    parser.add_argument("--max-trade-dates", type=int, default=None)
    parser.add_argument("--max-codes", type=int, default=None)
    parser.add_argument("--max-products", type=int, default=None)
    parser.add_argument("--us-exchanges", nargs="*", default=US_EXCHANGES)
    parser.add_argument("--option-exchanges", nargs="*", default=OPTION_EXCHANGES)
    parser.add_argument("--future-exchanges", nargs="*", default=FUTURE_EXCHANGES)
    parser.add_argument("--future-daily-mode", choices=("trade_date", "exchange"), default="trade_date")
    parser.add_argument("--future-position-mode", choices=("trade_date", "product"), default="trade_date")
    return parser.parse_args()


class RateLimiter:
    def __init__(self, max_per_minute: int, base_sleep: float) -> None:
        self.max_per_minute = max_per_minute
        self.base_sleep = base_sleep
        self.window_start = time.time()
        self.count = 0

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self.window_start
        if elapsed >= 60:
            self.window_start = now
            self.count = 0
        elif self.count >= self.max_per_minute:
            sleep_for = max(0.0, 60 - elapsed)
            if sleep_for > 0:
                print(f"[RATE_LIMIT] {self.max_per_minute}/min reached; sleeping {sleep_for:.1f}s", flush=True)
                time.sleep(sleep_for)
            self.window_start = time.time()
            self.count = 0
        if self.base_sleep > 0:
            time.sleep(self.base_sleep)

    def mark(self) -> None:
        self.count += 1


class TushareGlobalDerivativesExporter:
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
        self.local_root = Path(args.local_root).expanduser()
        ensure_dir(self.local_root)
        self.limiter = RateLimiter(args.max_per_minute, args.sleep)
        self.existing_keys_cache: dict[str, set[str]] = {}
        self.manifest: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self._us_basic: pd.DataFrame | None = None
        self._us_trade_dates: list[str] | None = None
        self._cn_trade_dates: list[str] | None = None
        self._opt_basic: pd.DataFrame | None = None
        self._fut_basic: pd.DataFrame | None = None

    @staticmethod
    def read_token(path: str) -> str:
        token_path = Path(path)
        if not token_path.exists():
            return ""
        return token_path.read_text(encoding="utf-8").strip()

    def s3_key(self, *parts: str) -> str:
        base = self.args.prefix.rstrip("/")
        clean = [part.strip("/").replace("\\", "/") for part in parts if part]
        return "/".join([base, *clean])

    def local_path(self, *parts: str) -> Path:
        path = self.local_root.joinpath(*parts)
        ensure_dir(path.parent)
        return path

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

    def should_skip(self, key: str, dataset_prefix: str) -> bool:
        if self.args.overwrite_existing:
            return False
        if not self.args.skip_existing:
            return False
        return key in self.list_existing_keys(dataset_prefix)

    def call_with_retry(self, api_name: str, kwargs: dict[str, Any]) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(1, self.args.retry + 1):
            try:
                self.limiter.wait()
                if hasattr(self.pro, api_name):
                    df = getattr(self.pro, api_name)(**kwargs)
                else:
                    df = self.pro.query(api_name, **kwargs)
                self.limiter.mark()
                if df is None:
                    return pd.DataFrame()
                return df
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                message = str(exc)
                print(f"[WARN] {api_name} attempt={attempt}/{self.args.retry} kwargs={kwargs} err={message}", flush=True)
                if "次/小时" in message or "次/天" in message:
                    raise RuntimeError(f"{api_name} quota is lower than batch cadence: {message}") from exc
                if "每分钟最多访问该接口" in message or "每分钟可以访问" in message or "次/分钟" in message:
                    time.sleep(65)
                else:
                    time.sleep(min(attempt * 2, 12))
        raise RuntimeError(f"{api_name} failed after retries: {last_error}")

    def page_size_for(self, dataset: str) -> int:
        return self.args.page_size or DATASET_PAGE_SIZE.get(dataset, 5000)

    def fetch_paged(self, api_name: str, base_kwargs: dict[str, Any], page_size: int | None = None) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        offset = 0
        size = page_size or self.page_size_for(api_name)
        while True:
            kwargs = dict(base_kwargs)
            kwargs["limit"] = size
            kwargs["offset"] = offset
            df = self.call_with_retry(api_name, kwargs)
            if df.empty:
                break
            frames.append(df)
            if len(df) < size:
                break
            offset += size
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True)

    def upload_frame(
        self,
        dataset: str,
        df: pd.DataFrame,
        filename: str,
        key_segments: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        if df.empty:
            print(f"[SKIP] {dataset} empty meta={meta or {}}", flush=True)
            return
        category_dir, dataset_dir = DATASET_DIRS[dataset]
        segments = key_segments or []
        local_path = self.local_path(category_dir, dataset_dir, *segments, filename)
        df.to_csv(local_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL, escapechar="\\")
        key = self.s3_key(category_dir, dataset_dir, *segments, filename)
        dataset_prefix = self.s3_key(category_dir, dataset_dir) + "/"
        if self.should_skip(key, dataset_prefix):
            print(f"[SKIP] existing s3://{self.args.bucket}/{key}", flush=True)
            return
        print(f"[UPLOAD] {local_path} -> s3://{self.args.bucket}/{key} rows={len(df)}", flush=True)
        if not self.args.dry_run:
            self.s3.upload_file(str(local_path), self.args.bucket, key)
        self.existing_keys_cache.setdefault(dataset_prefix, set()).add(key)
        self.manifest.append(
            {
                "dataset": dataset,
                "rows": int(len(df)),
                "columns": list(df.columns),
                "s3_key": key,
                "generated_at_utc": now_utc_str(),
                **(meta or {}),
            }
        )

    def record_failure(self, dataset: str, context: dict[str, Any], error: Exception) -> None:
        item = {
            "dataset": dataset,
            "context": context,
            "error": str(error),
            "failed_at_utc": now_utc_str(),
        }
        self.failures.append(item)
        print(f"[FAIL] {dataset} context={context} err={error}", flush=True)
        if self.args.stop_on_error:
            raise error

    def write_run_artifacts(self) -> None:
        run_dir = self.local_root / "_manifests"
        ensure_dir(run_dir)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        manifest_path = run_dir / f"manifest_{stamp}.json"
        failures_path = run_dir / f"failures_{stamp}.json"
        manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        failures_path.write_text(json.dumps(self.failures, ensure_ascii=False, indent=2), encoding="utf-8")
        for dataset, path in (("run_manifest", manifest_path), ("run_failures", failures_path)):
            key = self.s3_key("运行记录", "tushare_global_derivatives", path.name)
            print(f"[UPLOAD] {path} -> s3://{self.args.bucket}/{key}", flush=True)
            if not self.args.dry_run:
                self.s3.upload_file(str(path), self.args.bucket, key)
        print(f"[SUMMARY] manifest_items={len(self.manifest)} failures={len(self.failures)}", flush=True)

    def select_recent_dates(self, dates: Iterable[str]) -> list[str]:
        unique_dates = sorted({str(d) for d in dates if str(d)})
        if self.args.recent_days is not None:
            cutoff = parse_yyyymmdd(self.args.end_date) - timedelta(days=self.args.recent_days)
            unique_dates = [d for d in unique_dates if parse_yyyymmdd(d) >= cutoff]
        if self.args.max_trade_dates is not None:
            unique_dates = unique_dates[-self.args.max_trade_dates :]
        return unique_dates

    def us_basic(self) -> pd.DataFrame:
        if self._us_basic is not None:
            return self._us_basic
        df = self.fetch_paged("us_basic", {}, self.page_size_for("us_basic"))
        if not df.empty and "ts_code" in df.columns:
            df = df[df["ts_code"].notna()]
            df = df[df["ts_code"].astype(str).str.strip().ne("")]
            df = df[df["ts_code"].astype(str).str.lower().ne("none")]
            df = df.drop_duplicates("ts_code", keep="first").sort_values("ts_code").reset_index(drop=True)
        self.upload_frame("us_basic", df, "us_basic_all.csv", meta={"api_name": "us_basic"})
        self._us_basic = df
        return df

    def us_codes(self) -> list[str]:
        df = self.us_basic()
        if df.empty or "ts_code" not in df.columns:
            return []
        codes = sorted(df["ts_code"].astype(str).dropna().unique().tolist())
        if self.args.max_codes is not None:
            codes = codes[: self.args.max_codes]
        return codes

    def us_trade_dates(self) -> list[str]:
        if self._us_trade_dates is not None:
            return self._us_trade_dates
        df = self.fetch_paged("us_tradecal", {"start_date": self.args.start_date, "end_date": self.args.end_date})
        self.upload_frame(
            "us_tradecal",
            df,
            f"us_tradecal_{self.args.start_date}_{self.args.end_date}.csv",
            meta={"api_name": "us_tradecal", "start_date": self.args.start_date, "end_date": self.args.end_date},
        )
        if df.empty or "cal_date" not in df.columns:
            dates: list[str] = []
        else:
            open_df = df
            if "is_open" in open_df.columns:
                open_df = open_df[open_df["is_open"].astype(str).eq("1")]
            dates = self.select_recent_dates(open_df["cal_date"].astype(str).tolist())
        self._us_trade_dates = dates
        return dates

    def cn_trade_dates(self) -> list[str]:
        if self._cn_trade_dates is not None:
            return self._cn_trade_dates
        df = self.fetch_paged(
            "trade_cal",
            {"exchange": "SSE", "start_date": self.args.start_date, "end_date": self.args.end_date, "is_open": "1"},
        )
        if df.empty or "cal_date" not in df.columns:
            start = parse_yyyymmdd(self.args.start_date)
            end = parse_yyyymmdd(self.args.end_date)
            dates = [
                (start + timedelta(days=i)).strftime("%Y%m%d")
                for i in range((end - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5
            ]
        else:
            dates = df["cal_date"].astype(str).tolist()
        self._cn_trade_dates = self.select_recent_dates(dates)
        return self._cn_trade_dates

    def opt_basic(self) -> pd.DataFrame:
        if self._opt_basic is not None:
            return self._opt_basic
        frames: list[pd.DataFrame] = []
        for exchange in self.args.option_exchanges:
            try:
                df = self.fetch_paged("opt_basic", {"exchange": exchange}, self.page_size_for("opt_basic"))
            except Exception as exc:  # noqa: BLE001
                self.record_failure("opt_basic", {"exchange": exchange}, exc)
                continue
            if df.empty:
                continue
            df["exchange"] = df.get("exchange", exchange).fillna(exchange)
            frames.append(df)
            self.upload_frame(
                "opt_basic",
                df,
                f"opt_basic_{exchange}.csv",
                [f"exchange={clean_segment(exchange)}"],
                {"api_name": "opt_basic", "exchange": exchange},
            )
        all_df = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True) if frames else pd.DataFrame()
        if not all_df.empty and "ts_code" in all_df.columns:
            all_df = all_df.drop_duplicates("ts_code", keep="first").sort_values("ts_code").reset_index(drop=True)
        self.upload_frame("opt_basic", all_df, "opt_basic_all.csv", meta={"api_name": "opt_basic"})
        self._opt_basic = all_df
        return all_df

    def fut_basic(self) -> pd.DataFrame:
        if self._fut_basic is not None:
            return self._fut_basic
        frames: list[pd.DataFrame] = []
        for exchange in self.args.future_exchanges:
            try:
                df = self.fetch_paged("fut_basic", {"exchange": exchange}, self.page_size_for("fut_basic"))
            except Exception as exc:  # noqa: BLE001
                self.record_failure("fut_basic", {"exchange": exchange}, exc)
                continue
            if df.empty:
                continue
            df["exchange"] = df.get("exchange", exchange).fillna(exchange)
            frames.append(df)
            self.upload_frame(
                "fut_basic",
                df,
                f"fut_basic_{exchange}.csv",
                [f"exchange={clean_segment(exchange)}"],
                {"api_name": "fut_basic", "exchange": exchange},
            )
        all_df = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True) if frames else pd.DataFrame()
        if not all_df.empty and "ts_code" in all_df.columns:
            all_df = all_df.drop_duplicates("ts_code", keep="first").sort_values("ts_code").reset_index(drop=True)
        self.upload_frame("fut_basic", all_df, "fut_basic_all.csv", meta={"api_name": "fut_basic"})
        self._fut_basic = all_df
        return all_df

    def future_products(self) -> list[str]:
        df = self.fut_basic()
        if df.empty:
            return []
        if "fut_code" in df.columns:
            products = sorted({str(x).upper() for x in df["fut_code"].dropna().tolist() if str(x).strip()})
        elif "symbol" in df.columns:
            products = sorted({str(x).rstrip("0123456789").upper() for x in df["symbol"].dropna().tolist() if str(x).strip()})
        else:
            products = []
        if self.args.max_products is not None:
            products = products[: self.args.max_products]
        return products

    def future_mapping_codes(self) -> list[str]:
        df = self.fut_basic()
        if df.empty:
            return []
        codes: set[str] = set()
        if {"fut_code", "exchange"}.issubset(df.columns):
            for _, row in df[["fut_code", "exchange"]].dropna().drop_duplicates().iterrows():
                suffix = FUTURE_EXCHANGE_SUFFIX.get(str(row["exchange"]))
                fut_code = str(row["fut_code"]).upper()
                if suffix and fut_code:
                    codes.add(f"{fut_code}.{suffix}")
        if "ts_code" in df.columns:
            continuous = df[df["ts_code"].astype(str).str.contains(r"\\.", na=False)]["ts_code"].astype(str).tolist()
            for code in continuous:
                if not any(ch.isdigit() for ch in code.split(".")[0]):
                    codes.add(code)
        out = sorted(codes)
        if self.args.max_codes is not None:
            out = out[: self.args.max_codes]
        return out

    def download_us_market_daily(self, dataset: str) -> None:
        for trade_date in self.us_trade_dates():
            try:
                df = self.fetch_paged(dataset, {"trade_date": trade_date}, self.page_size_for(dataset))
                self.upload_frame(
                    dataset,
                    df,
                    f"{dataset}.csv",
                    [f"trade_date={trade_date}"],
                    {"api_name": dataset, "trade_date": trade_date},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure(dataset, {"trade_date": trade_date}, exc)

    def download_us_financial(self, dataset: str) -> None:
        for ts_code in self.us_codes():
            try:
                df = self.call_with_retry(dataset, {"ts_code": ts_code, "start_date": self.args.start_date, "end_date": self.args.end_date})
                self.upload_frame(
                    dataset,
                    df,
                    f"{dataset}.csv",
                    [f"ts_code={clean_segment(ts_code)}"],
                    {"api_name": dataset, "ts_code": ts_code, "start_date": self.args.start_date, "end_date": self.args.end_date},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure(dataset, {"ts_code": ts_code}, exc)

    def download_opt_daily(self) -> None:
        self.opt_basic()
        for trade_date in self.cn_trade_dates():
            try:
                df = self.fetch_paged("opt_daily", {"trade_date": trade_date}, self.page_size_for("opt_daily"))
                self.upload_frame(
                    "opt_daily",
                    df,
                    "opt_daily.csv",
                    [f"trade_date={trade_date}"],
                    {"api_name": "opt_daily", "trade_date": trade_date},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure("opt_daily", {"trade_date": trade_date}, exc)

    def download_fut_daily_by_exchange(self, dataset: str) -> None:
        self.fut_basic()
        for trade_date in self.cn_trade_dates():
            for exchange in self.args.future_exchanges:
                try:
                    df = self.fetch_paged(dataset, {"trade_date": trade_date, "exchange": exchange}, self.page_size_for(dataset))
                    self.upload_frame(
                        dataset,
                        df,
                        f"{dataset}.csv",
                        [f"trade_date={trade_date}", f"exchange={clean_segment(exchange)}"],
                        {"api_name": dataset, "trade_date": trade_date, "exchange": exchange},
                    )
                except Exception as exc:  # noqa: BLE001
                    self.record_failure(dataset, {"trade_date": trade_date, "exchange": exchange}, exc)

    def download_fut_by_trade_date(self, dataset: str) -> None:
        self.fut_basic()
        for trade_date in self.cn_trade_dates():
            try:
                df = self.fetch_paged(dataset, {"trade_date": trade_date}, self.page_size_for(dataset))
                self.upload_frame(
                    dataset,
                    df,
                    f"{dataset}.csv",
                    [f"trade_date={trade_date}"],
                    {"api_name": dataset, "trade_date": trade_date},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure(dataset, {"trade_date": trade_date}, exc)

    def download_fut_by_product(self, dataset: str) -> None:
        self.fut_basic()
        for trade_date in self.cn_trade_dates():
            for product in self.future_products():
                try:
                    df = self.fetch_paged(dataset, {"trade_date": trade_date, "symbol": product}, self.page_size_for(dataset))
                    self.upload_frame(
                        dataset,
                        df,
                        f"{dataset}.csv",
                        [f"trade_date={trade_date}", f"symbol={clean_segment(product)}"],
                        {"api_name": dataset, "trade_date": trade_date, "symbol": product},
                    )
                except Exception as exc:  # noqa: BLE001
                    self.record_failure(dataset, {"trade_date": trade_date, "symbol": product}, exc)

    def download_fut_mapping(self) -> None:
        for ts_code in self.future_mapping_codes():
            try:
                df = self.call_with_retry("fut_mapping", {"ts_code": ts_code, "start_date": self.args.start_date, "end_date": self.args.end_date})
                self.upload_frame(
                    "fut_mapping",
                    df,
                    "fut_mapping.csv",
                    [f"ts_code={clean_segment(ts_code)}"],
                    {"api_name": "fut_mapping", "ts_code": ts_code, "start_date": self.args.start_date, "end_date": self.args.end_date},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure("fut_mapping", {"ts_code": ts_code}, exc)

    def download_fut_weekly_detail(self) -> None:
        start_week = self.args.start_date[:6]
        end_week = self.args.end_date[:6]
        for product in self.future_products():
            try:
                df = self.call_with_retry("fut_weekly_detail", {"prd": product, "start_week": start_week, "end_week": end_week})
                self.upload_frame(
                    "fut_weekly_detail",
                    df,
                    "fut_weekly_detail.csv",
                    [f"prd={clean_segment(product)}"],
                    {"api_name": "fut_weekly_detail", "prd": product, "start_week": start_week, "end_week": end_week},
                )
            except Exception as exc:  # noqa: BLE001
                self.record_failure("fut_weekly_detail", {"prd": product}, exc)

    def selected_datasets(self) -> list[str]:
        requested = set(ALL_DATASETS if "all" in self.args.datasets else self.args.datasets)
        scopes = set(self.args.scopes)
        if "all" not in scopes:
            allowed: set[str] = set()
            if "us" in scopes:
                allowed |= US_BASIC_DATASETS | US_MARKET_DAILY_DATASETS | US_FINANCIAL_DATASETS
            if "options" in scopes:
                allowed |= OPTION_DATASETS
            if "futures" in scopes:
                allowed |= FUTURE_DATASETS
            requested &= allowed
        unknown = sorted(requested - set(ALL_DATASETS))
        if unknown:
            raise ValueError(f"unknown datasets: {unknown}")
        return [dataset for dataset in ALL_DATASETS if dataset in requested]

    def run_dataset(self, dataset: str) -> None:
        print(f"[DATASET] start {dataset}", flush=True)
        if dataset == "us_basic":
            self.us_basic()
        elif dataset == "us_tradecal":
            self.us_trade_dates()
        elif dataset in US_MARKET_DAILY_DATASETS:
            self.download_us_market_daily(dataset)
        elif dataset in US_FINANCIAL_DATASETS:
            self.download_us_financial(dataset)
        elif dataset == "opt_basic":
            self.opt_basic()
        elif dataset == "opt_daily":
            self.download_opt_daily()
        elif dataset == "fut_basic":
            self.fut_basic()
        elif dataset in {"fut_daily", "fut_settle"}:
            if self.args.future_daily_mode == "exchange":
                self.download_fut_daily_by_exchange(dataset)
            else:
                self.download_fut_by_trade_date(dataset)
        elif dataset in {"fut_holding", "fut_wsr"}:
            if self.args.future_position_mode == "product":
                self.download_fut_by_product(dataset)
            else:
                self.download_fut_by_trade_date(dataset)
        elif dataset == "fut_mapping":
            self.download_fut_mapping()
        elif dataset == "fut_weekly_detail":
            self.download_fut_weekly_detail()
        print(f"[DATASET] done {dataset}", flush=True)

    def run(self) -> None:
        for dataset in self.selected_datasets():
            try:
                self.run_dataset(dataset)
            except Exception as exc:  # noqa: BLE001
                self.record_failure(dataset, {"stage": "dataset"}, exc)
                traceback.print_exc()
        self.write_run_artifacts()


def main() -> int:
    args = parse_args()
    exporter = TushareGlobalDerivativesExporter(args)
    exporter.run()
    return 0 if not exporter.failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
