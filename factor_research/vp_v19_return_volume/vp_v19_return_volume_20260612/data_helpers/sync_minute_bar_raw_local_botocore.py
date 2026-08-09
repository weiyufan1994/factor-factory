#!/usr/bin/env python3.14
"""
Download minute_bar raw parquet partitions with a shared botocore S3 client.

Use the AWS CLI bundled Python when system Python does not have botocore:

  /opt/homebrew/Cellar/awscli/2.34.19/libexec/bin/python \
    scripts/sync_minute_bar_raw_local_botocore.py
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

try:
    import botocore.session
    from botocore.config import Config
except Exception:
    awscli_site = Path("/opt/homebrew/Cellar/awscli/2.34.19/libexec/lib/python3.14/site-packages")
    if awscli_site.exists():
        sys.path.insert(0, str(awscli_site))
    import awscli.botocore as vendored_botocore

    sys.modules.setdefault("botocore", vendored_botocore)
    import botocore.session
    from botocore.config import Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="yufan-data-lake")
    parser.add_argument("--s3-prefix", default="tushares/分钟数据/raw/stk_mins_1min/")
    parser.add_argument("--local-root", type=Path, default=Path("/Users/humphrey/projects/factorforge-data-api-cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"))
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--listing-file", type=Path)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--connect-timeout", type=int, default=20)
    parser.add_argument("--read-timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def load_targets(args: argparse.Namespace) -> list[tuple[str, int, str]]:
    listing_file = args.listing_file or (args.local_root / "_sync" / f"s3_listing_{args.start_date}_{args.end_date}.txt")
    targets: list[tuple[str, int, str]] = []
    if listing_file.exists():
        for line in listing_file.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            size = int(parts[2])
            key = parts[3]
            marker = "trade_date="
            if marker not in key or not key.endswith(".parquet"):
                continue
            date = key.split(marker, 1)[1].split("/", 1)[0]
            if args.start_date <= date <= args.end_date:
                targets.append((date, size, key))
    else:
        raise SystemExit(f"missing listing file: {listing_file}")
    targets = sorted(set(targets))
    if args.max_files:
        targets = targets[: args.max_files]
    return targets


def stat_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def download_one(client, bucket: str, local_root: Path, target: tuple[str, int, str], retries: int) -> tuple[str, str, int, str]:
    date, size, key = target
    dest_dir = local_root / f"trade_date={date}"
    dest = dest_dir / Path(key).name
    have = stat_size(dest)
    if have == size:
        return ("skip", date, size, "")
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.download.{os.getpid()}.{threading.get_ident()}")
    for attempt in range(1, retries + 1):
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            with tmp.open("wb") as handle:
                for chunk in iter(lambda: body.read(1024 * 1024), b""):
                    if chunk:
                        handle.write(chunk)
            got = stat_size(tmp)
            if got != size:
                raise RuntimeError(f"size mismatch got={got} expected={size}")
            os.replace(tmp, dest)
            return ("done", date, size, "")
        except Exception as exc:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            if attempt == retries:
                return ("fail", date, size, f"{type(exc).__name__}: {exc}")
            time.sleep(min(2 * attempt, 10))
    return ("fail", date, size, "retry loop exhausted")


def main() -> None:
    args = parse_args()
    args.local_root.mkdir(parents=True, exist_ok=True)
    targets = load_targets(args)
    total_bytes = sum(size for _, size, _ in targets)
    print(f"[TARGETS] count={len(targets):,} bytes={total_bytes} gib={total_bytes/1024/1024/1024:.3f} jobs={args.jobs}", flush=True)

    config = Config(
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        retries={"max_attempts": args.retries, "mode": "standard"},
        max_pool_connections=max(args.jobs * 2, 16),
    )
    session = botocore.session.get_session()
    client = session.create_client("s3", region_name="ap-southeast-1", config=config)

    counts = {"done": 0, "skip": 0, "fail": 0}
    completed = 0
    started = time.perf_counter()
    with futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_map = {
            executor.submit(download_one, client, args.bucket, args.local_root, target, args.retries): target
            for target in targets
        }
        for future in futures.as_completed(future_map):
            status, date, size, message = future.result()
            counts[status] = counts.get(status, 0) + 1
            completed += 1
            if status != "skip":
                suffix = f" {message}" if message else ""
                print(f"[{status.upper()}] {date}{suffix}", flush=True)
            if completed % args.progress_every == 0 or completed == len(targets):
                elapsed = time.perf_counter() - started
                local_count = sum(1 for _ in args.local_root.glob("trade_date=*/part-000.parquet"))
                print(
                    f"[PROGRESS] completed={completed:,}/{len(targets):,} local_parquet={local_count:,} "
                    f"done={counts.get('done', 0):,} skip={counts.get('skip', 0):,} fail={counts.get('fail', 0):,} "
                    f"elapsed_sec={elapsed:.1f}",
                    flush=True,
                )
    if counts.get("fail", 0):
        raise SystemExit(2)
    local_count = sum(1 for _ in args.local_root.glob("trade_date=*/part-000.parquet"))
    print(f"[OK] local_parquet={local_count:,} root={args.local_root}", flush=True)


if __name__ == "__main__":
    main()
