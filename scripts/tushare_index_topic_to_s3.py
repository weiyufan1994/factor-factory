#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import traceback
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
DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parent / "_tushare_index_topic_exports"
DEFAULT_START_DATE = "19900101"
DEFAULT_END_DATE = datetime.utcnow().strftime("%Y%m%d")
DEFAULT_MARKETS = ("SSE", "SZSE", "CSI", "CICC", "SW", "MSCI", "OTH")


def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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


class TushareIndexTopicExporter:
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
        self.manifest: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.existing_keys_cache: dict[str, set[str]] = {}

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
                if "每分钟最多访问该接口" in message:
                    time.sleep(65)
                else:
                    time.sleep(min(attempt * 2, 12))
        raise RuntimeError(f"{api_name} failed after retries: {last_error}")

    def fetch_paged(self, api_name: str, base_kwargs: dict[str, Any], page_size: int) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        offset = 0
        while True:
            kwargs = dict(base_kwargs)
            kwargs["limit"] = page_size
            kwargs["offset"] = offset
            df = self.call_with_retry(api_name, kwargs)
            if df is None or df.empty:
                break
            frames.append(df)
            rows = len(df)
            if rows < page_size:
                break
            offset += page_size
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)

    def upload_frame(
        self,
        dataset: str,
        dataset_dir: str,
        df: pd.DataFrame,
        filename: str,
        key_segments: list[str],
        meta: dict[str, Any],
    ) -> None:
        local_path = self.local_path("指数专题数据", dataset_dir, *key_segments, filename)
        df.to_csv(local_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL, escapechar="\\")
        key = self.s3_key("指数专题数据", dataset_dir, *key_segments, filename)
        dataset_prefix = self.s3_key("指数专题数据", dataset_dir) + "/"
        if self.should_skip(key, dataset_prefix):
            print(f"[SKIP] existing s3://{self.args.bucket}/{key}", flush=True)
            return
        print(f"[UPLOAD] {local_path} -> s3://{self.args.bucket}/{key}", flush=True)
        if not self.args.dry_run:
            self.s3.upload_file(str(local_path), self.args.bucket, key)
        self.existing_keys_cache.setdefault(dataset_prefix, set()).add(key)
        self.manifest.append(
            {
                "dataset": dataset,
                "dataset_dir": dataset_dir,
                "rows": int(len(df)),
                "columns": list(df.columns),
                "s3_key": key,
                "generated_at_utc": now_utc_str(),
                **meta,
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

    def download_index_basic(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for market in self.args.markets:
            try:
                df = self.fetch_paged("index_basic", {"market": market}, self.args.page_size)
            except Exception as exc:  # noqa: BLE001
                self.record_failure("index_basic", {"market": market}, exc)
                continue
            if df.empty:
                print(f"[SKIP] index_basic market={market} empty", flush=True)
                continue
            df["market"] = df.get("market", market).fillna(market)
            frames.append(df)
            self.upload_frame(
                "index_basic",
                "指数基本信息",
                df,
                f"index_basic_{market}.csv",
                [f"market={market}"],
                {"api_name": "index_basic", "market": market},
            )
        if not frames:
            raise RuntimeError("index_basic returned no rows for all markets")
        all_basic = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates().reset_index(drop=True)
        all_basic = all_basic.dropna(subset=["ts_code"]).drop_duplicates("ts_code", keep="first").sort_values("ts_code")
        self.upload_frame(
            "index_basic",
            "指数基本信息",
            all_basic,
            "index_basic_all.csv",
            [],
            {"api_name": "index_basic", "markets": list(self.args.markets)},
        )
        return all_basic

    def download_code_history(self, dataset: str, dataset_dir: str, api_name: str, ts_code: str) -> None:
        filename = f"{dataset}.csv"
        key_segments = [f"ts_code={ts_code}"]
        key = self.s3_key("指数专题数据", dataset_dir, *key_segments, filename)
        dataset_prefix = self.s3_key("指数专题数据", dataset_dir) + "/"
        if self.should_skip(key, dataset_prefix):
            print(f"[SKIP] existing s3://{self.args.bucket}/{key}", flush=True)
            return
        kwargs = {"ts_code": ts_code, "start_date": self.args.start_date, "end_date": self.args.end_date}
        try:
            df = self.fetch_paged(api_name, kwargs, self.args.page_size)
        except Exception as exc:  # noqa: BLE001
            self.record_failure(dataset, {"ts_code": ts_code, "api_name": api_name}, exc)
            return
        if df.empty:
            print(f"[SKIP] {dataset} ts_code={ts_code} empty", flush=True)
            return
        self.upload_frame(
            dataset,
            dataset_dir,
            df,
            filename,
            key_segments,
            {
                "api_name": api_name,
                "ts_code": ts_code,
                "start_date": self.args.start_date,
                "end_date": self.args.end_date,
            },
        )

    def write_meta_files(self) -> None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        manifest_path = self.local_path("_meta", f"manifest_index_topic_{stamp}.json")
        payload = {
            "generated_at_utc": now_utc_str(),
            "bucket": self.args.bucket,
            "prefix": self.args.prefix,
            "category": "指数专题数据",
            "start_date": self.args.start_date,
            "end_date": self.args.end_date,
            "markets": list(self.args.markets),
            "items": self.manifest,
            "failures": self.failures,
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        key = self.s3_key("指数专题数据", "_meta", manifest_path.name)
        print(f"[UPLOAD] {manifest_path} -> s3://{self.args.bucket}/{key}", flush=True)
        if not self.args.dry_run:
            self.s3.upload_file(str(manifest_path), self.args.bucket, key)

    def run(self) -> None:
        print("[START] index_basic", flush=True)
        basic = self.download_index_basic()
        codes = basic["ts_code"].dropna().astype(str).drop_duplicates().sort_values().tolist()
        if self.args.max_codes is not None:
            codes = codes[: self.args.max_codes]
        print(f"[INDEX_BASIC_DONE] codes={len(codes)}", flush=True)
        if self.args.only_basic:
            self.write_meta_files()
            print("[DONE] index_basic only", flush=True)
            return

        for i, ts_code in enumerate(codes, 1):
            print(f"[CODE] {i}/{len(codes)} {ts_code}", flush=True)
            if "index_daily" in self.args.datasets:
                self.download_code_history("index_daily", "指数日线行情", "index_daily", ts_code)
            if "index_factor_pro" in self.args.datasets:
                self.download_code_history("index_factor_pro", "指数技术因子_专业版", "idx_factor_pro", ts_code)

        self.write_meta_files()
        print("[DONE] index topic datasets processed", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Tushare index topic datasets and upload them to S3.")
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--local-root", default=str(DEFAULT_LOCAL_ROOT))
    parser.add_argument("--markets", nargs="*", default=list(DEFAULT_MARKETS))
    parser.add_argument("--datasets", nargs="*", default=["index_daily", "index_factor_pro"])
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--retry", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.20)
    parser.add_argument("--max-per-minute", type=int, default=60)
    parser.add_argument("--max-codes", type=int, default=None)
    parser.add_argument("--only-basic", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--overwrite-existing", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.overwrite_existing:
        args.skip_existing = False
    args.datasets = sorted(set(args.datasets))
    allowed = {"index_daily", "index_factor_pro"}
    unknown = set(args.datasets) - allowed
    if unknown:
        raise ValueError(f"unknown datasets: {sorted(unknown)}")
    return args


def main() -> None:
    args = parse_args()
    try:
        exporter = TushareIndexTopicExporter(args)
        exporter.run()
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] {exc}", flush=True)
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
