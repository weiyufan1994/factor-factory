#!/usr/bin/env python3
"""
Serial AWS CLI downloader for minute_bar raw parquet partitions.

This is intentionally conservative for Mac-local research backfills when direct
botocore GETs are unstable but `aws s3 cp` succeeds.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="yufan-data-lake")
    parser.add_argument("--s3-prefix", default="tushares/分钟数据/raw/stk_mins_1min/")
    parser.add_argument(
        "--local-root",
        type=Path,
        default=Path("/Users/humphrey/projects/factorforge-data-api-cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"),
    )
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--listing-file", type=Path)
    parser.add_argument("--max-downloads", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=20)
    parser.add_argument("--connect-timeout", type=int, default=30)
    parser.add_argument("--read-timeout", type=int, default=600)
    return parser.parse_args()


def load_targets(args: argparse.Namespace) -> list[tuple[str, int, str]]:
    listing_file = args.listing_file or (args.local_root / "_sync" / f"s3_listing_{args.start_date}_{args.end_date}.txt")
    if not listing_file.exists():
        raise SystemExit(f"missing listing file: {listing_file}")

    targets: list[tuple[str, int, str]] = []
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
    return sorted(set(targets))


def stat_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def main() -> None:
    args = parse_args()
    targets = load_targets(args)
    downloaded = 0
    attempted = 0
    skipped = 0
    failed = 0
    started = time.perf_counter()

    print(f"[TARGETS] count={len(targets):,} max_downloads={args.max_downloads}", flush=True)
    for date, size, key in targets:
        dest_dir = args.local_root / f"trade_date={date}"
        dest = dest_dir / Path(key).name
        if stat_size(dest) == size:
            skipped += 1
            continue
        if downloaded >= args.max_downloads or attempted >= args.max_attempts:
            break

        attempted += 1
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.awscli-download")
        tmp.unlink(missing_ok=True)
        s3_uri = f"s3://{args.bucket}/{key}"
        cmd = [
            "aws",
            "s3",
            "cp",
            s3_uri,
            str(tmp),
            "--no-progress",
            "--cli-connect-timeout",
            str(args.connect_timeout),
            "--cli-read-timeout",
            str(args.read_timeout),
        ]
        item_start = time.perf_counter()
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        item_sec = time.perf_counter() - item_start
        got = stat_size(tmp)
        if result.returncode == 0 and got == size:
            tmp.replace(dest)
            downloaded += 1
            print(f"[DONE] {date} bytes={size} sec={item_sec:.1f}", flush=True)
        else:
            failed += 1
            tmp.unlink(missing_ok=True)
            message = (result.stderr or result.stdout).strip().replace("\n", " | ")
            print(f"[FAIL] {date} rc={result.returncode} got={got} expected={size} sec={item_sec:.1f} {message}", flush=True)

    elapsed = time.perf_counter() - started
    local_count = sum(1 for _ in args.local_root.glob("trade_date=*/part-000.parquet"))
    print(
        f"[OK] downloaded={downloaded} skipped={skipped} failed={failed} "
        f"attempted={attempted} local_parquet={local_count} elapsed_sec={elapsed:.1f}",
        flush=True,
    )
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
