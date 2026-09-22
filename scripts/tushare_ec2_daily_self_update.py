#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_TOKEN_FILE = "/home/ubuntu/.openclaw/media/inbound/tushares_token---f5492736-ee8f-4214-b0de-0422f0cfa0a3"
DEFAULT_REMOTE_ROOT = Path("/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取")
DEFAULT_BUCKET = "yufan-data-lake"
DAILY_KEY = "tushares/行情数据/daily.csv"
DAILY_INCREMENTAL_PREFIX = "tushares/行情数据/daily_incremental"
DAILY_BASIC_PREFIX = "tushares/行情数据/daily_basic_incremental"
ADJ_FACTOR_KEY = "tushares/行情数据/adj_factor.csv"
ADJ_FACTOR_INCREMENTAL_PREFIX = "tushares/行情数据/adj_factor_incremental"
TRADE_CAL_KEY = "tushares/基础数据/trade_cal.csv"

DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,"
    "dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-contained EC2 Tushare daily updater.")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--remote-root", type=Path, default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--start-after", default=None)
    parser.add_argument("--python-bin", default="/home/ubuntu/miniconda3/envs/rdagent/bin/python")
    parser.add_argument("--skip-basics", action="store_true")
    parser.add_argument("--skip-daily-basic", action="store_true")
    parser.add_argument("--skip-adj-factor", action="store_true")
    parser.add_argument("--operator", default=None, help="Data mutation operator. Must be codex for shared raw/canonical writes.")
    parser.add_argument("--upload-canonical", action="store_true", help="Upload merged canonical daily/adj_factor CSVs back to S3.")
    parser.add_argument("--no-upload-canonical", action="store_true")
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("[RUN]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def read_token(path: str) -> str:
    token = Path(path).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"token file is empty: {path}")
    return token


def download_s3(bucket: str, key: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["aws", "s3", "cp", f"s3://{bucket}/{key}", str(target), "--only-show-errors"])


def upload_s3(bucket: str, key: str, source: Path) -> None:
    run(["aws", "s3", "cp", str(source), f"s3://{bucket}/{key}", "--only-show-errors"])


def list_partition_dates(bucket: str, prefix: str) -> set[str]:
    proc = subprocess.run(
        ["aws", "s3", "ls", f"s3://{bucket}/{prefix}/", "--recursive"],
        check=False,
        text=True,
        capture_output=True,
    )
    dates: set[str] = set()
    if proc.returncode != 0:
        return dates
    for line in proc.stdout.splitlines():
        if "trade_date=" not in line:
            continue
        dates.add(line.split("trade_date=")[1].split("/")[0])
    return dates


def max_partition_date(bucket: str, prefix: str) -> str | None:
    dates = list_partition_dates(bucket, prefix)
    return max(dates) if dates else None


def read_last_trade_date(csv_path: Path) -> str:
    last = ""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            last = str(row["trade_date"]).replace(".0", "").zfill(8)
    if not last:
        raise RuntimeError(f"empty CSV: {csv_path}")
    return last


def open_trade_dates(trade_cal_csv: Path, start_after: str, end_date: str) -> list[str]:
    cal = pd.read_csv(trade_cal_csv, dtype={"cal_date": "string"})
    cal["cal_date"] = cal["cal_date"].str.replace(".0", "", regex=False).str.zfill(8)
    frame = cal[(cal["is_open"].astype(str) == "1") & (cal["cal_date"] > start_after) & (cal["cal_date"] <= end_date)]
    return frame["cal_date"].tolist()


def run_basic_refresh(args: argparse.Namespace) -> None:
    for script in [
        "11_stock_basic_to_s3.py",
        "12_trade_cal_to_s3.py",
        "13_stock_st_to_s3.py",
        "14_stock_st_daily_fallback_to_s3.py",
    ]:
        run([args.python_bin, script], cwd=args.remote_root)


def run_daily_incremental(args: argparse.Namespace, trade_dates: list[str]) -> None:
    existing = list_partition_dates(args.bucket, DAILY_INCREMENTAL_PREFIX)
    for trade_date in trade_dates:
        if trade_date in existing:
            print(f"[SKIP] daily_incremental {trade_date} already exists")
            continue
        run([args.python_bin, "16_daily_incremental_to_s3.py", "--trade-date", trade_date], cwd=args.remote_root)


def fetch_daily_basic(pro: Any, trade_date: str) -> pd.DataFrame:
    df = pro.daily_basic(trade_date=trade_date, fields=DAILY_BASIC_FIELDS)
    if df is None or df.empty:
        raise RuntimeError(f"daily_basic(trade_date={trade_date}) returned empty")
    return df.sort_values("ts_code").reset_index(drop=True)


def run_daily_basic_incremental(args: argparse.Namespace, pro: ts.pro_api, trade_dates: list[str]) -> None:
    import boto3

    existing = list_partition_dates(args.bucket, DAILY_BASIC_PREFIX)
    local_root = args.remote_root / "_daily_basic_incremental"
    local_root.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3")
    for trade_date in trade_dates:
        if trade_date in existing:
            print(f"[SKIP] daily_basic_incremental {trade_date} already exists")
            continue
        df = fetch_daily_basic(pro, trade_date)
        local_csv = local_root / f"daily_basic_{trade_date}.csv"
        df.to_csv(local_csv, index=False, encoding="utf-8-sig")
        key = f"{DAILY_BASIC_PREFIX}/trade_date={trade_date}/daily_basic_{trade_date}.csv"
        s3.upload_file(str(local_csv), args.bucket, key)
        print(f"[UPLOAD] daily_basic {trade_date} rows={len(df)} s3=s3://{args.bucket}/{key}")


def run_adj_factor_incremental(args: argparse.Namespace, trade_dates: list[str]) -> None:
    existing = list_partition_dates(args.bucket, ADJ_FACTOR_INCREMENTAL_PREFIX)
    for trade_date in trade_dates:
        if trade_date in existing:
            print(f"[SKIP] adj_factor_incremental {trade_date} already exists")
            continue
        run([args.python_bin, "21_adj_factor_incremental_to_s3.py", "--trade-date", trade_date], cwd=args.remote_root)


def download_incremental_rows(bucket: str, prefix: str, trade_dates: list[str], basename: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix=f"{basename}_merge_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for trade_date in trade_dates:
            remote = f"s3://{bucket}/{prefix}/trade_date={trade_date}/{basename}_{trade_date}.csv"
            local = tmp_root / f"{basename}_{trade_date}.csv"
            run(["aws", "s3", "cp", remote, str(local), "--only-show-errors"])
            with local.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    grouped[row["ts_code"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["trade_date"])
    return grouped


def merge_by_ts_code(base_csv: Path, output_csv: Path, update_dates: list[str], incremental_rows: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    update_date_set = set(update_dates)
    pending_codes = set(incremental_rows)
    written_rows = 0
    replaced_rows = 0
    with base_csv.open("r", encoding="utf-8-sig", newline="") as src, output_csv.open("w", encoding="utf-8-sig", newline="") as dst:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            raise RuntimeError(f"missing CSV header: {base_csv}")
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        current_code = None
        for row in reader:
            code = row["ts_code"]
            if current_code is None:
                current_code = code
            elif code != current_code:
                for inc_row in incremental_rows.get(current_code, []):
                    writer.writerow(inc_row)
                    written_rows += 1
                pending_codes.discard(current_code)
                current_code = code
            if row["trade_date"] in update_date_set:
                replaced_rows += 1
                continue
            writer.writerow(row)
            written_rows += 1
        if current_code is not None:
            for inc_row in incremental_rows.get(current_code, []):
                writer.writerow(inc_row)
                written_rows += 1
            pending_codes.discard(current_code)
        for code in sorted(pending_codes):
            for inc_row in incremental_rows[code]:
                writer.writerow(inc_row)
                written_rows += 1
    return {"written_rows": written_rows, "replaced_rows": replaced_rows}


def merge_canonical(bucket: str, key: str, prefix: str, basename: str, local_root: Path, end_date: str, upload: bool) -> dict[str, object]:
    base_csv = local_root / Path(key).name
    merged_csv = local_root / f"{Path(key).stem}.merged.csv"
    download_s3(bucket, key, base_csv)
    base_max = read_last_trade_date(base_csv)
    existing_dates = sorted(d for d in list_partition_dates(bucket, prefix) if base_max < d <= end_date)
    if not existing_dates:
        return {"status": "noop", "key": key, "base_max_trade_date": base_max}
    rows = download_incremental_rows(bucket, prefix, existing_dates, basename)
    summary = merge_by_ts_code(base_csv, merged_csv, existing_dates, rows)
    merged_csv.replace(base_csv)
    if upload:
        upload_s3(bucket, key, base_csv)
    summary.update(
        {
            "status": "merged",
            "key": key,
            "first_update_trade_date": existing_dates[0],
            "last_update_trade_date": existing_dates[-1],
            "base_max_trade_date": base_max,
            "active_csv": str(base_csv),
            "uploaded": upload,
        }
    )
    return summary


def main() -> int:
    args = parse_args()
    require_data_mutation_authority(args.operator, operation="tushare_ec2_daily_self_update")
    args.remote_root = args.remote_root.expanduser()
    import tushare as ts

    ts.set_token(read_token(args.token_file))
    pro = ts.pro_api()

    if not args.skip_basics:
        run_basic_refresh(args)

    work_root = args.remote_root / "_ec2_daily_self_update"
    work_root.mkdir(parents=True, exist_ok=True)
    trade_cal_csv = work_root / "trade_cal.csv"
    daily_work_root = work_root / "daily"
    adj_work_root = work_root / "adj_factor"
    daily_work_root.mkdir(parents=True, exist_ok=True)
    adj_work_root.mkdir(parents=True, exist_ok=True)

    download_s3(args.bucket, TRADE_CAL_KEY, trade_cal_csv)
    daily_base = daily_work_root / "daily.csv"
    download_s3(args.bucket, DAILY_KEY, daily_base)
    daily_start_after = args.start_after or read_last_trade_date(daily_base)
    daily_dates = open_trade_dates(trade_cal_csv, daily_start_after, args.end_date)

    daily_basic_start_after = args.start_after or max_partition_date(args.bucket, DAILY_BASIC_PREFIX) or daily_start_after
    daily_basic_dates = open_trade_dates(trade_cal_csv, daily_basic_start_after, args.end_date)

    adj_factor_start_after = args.start_after or max_partition_date(args.bucket, ADJ_FACTOR_INCREMENTAL_PREFIX) or "00000000"
    adj_factor_dates = open_trade_dates(trade_cal_csv, adj_factor_start_after, args.end_date)
    print(
        json.dumps(
            {
                "end_date": args.end_date,
                "daily": {"start_after": daily_start_after, "trade_dates": daily_dates},
                "daily_basic": {"start_after": daily_basic_start_after, "trade_dates": daily_basic_dates},
                "adj_factor": {"start_after": adj_factor_start_after, "trade_dates": adj_factor_dates},
            },
            ensure_ascii=False,
        )
    )

    run_daily_incremental(args, daily_dates)
    if not args.skip_daily_basic:
        run_daily_basic_incremental(args, pro, daily_basic_dates)
    if not args.skip_adj_factor:
        run_adj_factor_incremental(args, adj_factor_dates)

    upload = bool(args.upload_canonical and not args.no_upload_canonical)
    daily_summary = merge_canonical(args.bucket, DAILY_KEY, DAILY_INCREMENTAL_PREFIX, "daily", daily_work_root, args.end_date, upload)
    adj_summary = None
    if not args.skip_adj_factor:
        adj_summary = merge_canonical(args.bucket, ADJ_FACTOR_KEY, ADJ_FACTOR_INCREMENTAL_PREFIX, "adj_factor", adj_work_root, args.end_date, upload)

    print(json.dumps({"daily": daily_summary, "adj_factor": adj_summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
