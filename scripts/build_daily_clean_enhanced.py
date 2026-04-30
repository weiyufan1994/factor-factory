#!/usr/bin/env python3
"""
Build enhanced daily_clean.parquet with daily_basic columns.

free_float_mcap = close * free_share
ln_mcap_free = ln(free_float_mcap)

Workflow:
1. Load daily_basic_incremental CSVs from the local raw Tushare cache
2. Forward-fill free_share per stock across dates
3. Compute free_float_mcap = daily_basic_close * free_share
4. Merge daily_basic enhancement columns into daily_clean.parquet
5. Save daily_clean_enhanced.parquet and optionally replace daily_clean.parquet
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import default_clean_daily_layer_root, default_local_data_root
from factor_factory.data_access.mutation_guard import require_data_mutation_authority

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_daily_clean_enhanced")

DEFAULT_CLEAN_DIR = default_clean_daily_layer_root()
DEFAULT_DAILY_CLEAN = DEFAULT_CLEAN_DIR / "daily_clean.parquet"
DEFAULT_DAILY_META = DEFAULT_CLEAN_DIR / "daily_clean.meta.json"
DEFAULT_ENHANCED = DEFAULT_CLEAN_DIR / "daily_clean_enhanced.parquet"
DEFAULT_DAILY_BASIC_DIR = default_local_data_root() / "行情数据" / "daily_basic_incremental"

DAILY_BASIC_COLUMNS = [
    "ts_code",
    "trade_date",
    "close",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
]


def iter_daily_basic_csvs(root: Path, start: str | None = None, end: str | None = None) -> list[Path]:
    """Return local daily_basic CSV partitions within the inclusive date range."""
    csvs: list[Path] = []
    for part_dir in sorted(root.glob("trade_date=*")):
        if not part_dir.is_dir():
            continue
        trade_date = part_dir.name.replace("trade_date=", "")
        if start and trade_date < start:
            continue
        if end and trade_date > end:
            continue
        csvs.extend(sorted(part_dir.glob("*.csv")))
    return csvs


def load_all_daily_basic(root: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load local daily_basic CSVs into one normalized DataFrame."""
    if not root.exists():
        raise FileNotFoundError(f"daily_basic_incremental not found: {root}")

    csv_paths = iter_daily_basic_csvs(root, start=start, end=end)
    if not csv_paths:
        raise FileNotFoundError(f"no daily_basic CSVs found under {root}")

    log.info("Found %s local daily_basic partitions under %s", len(csv_paths), root)
    dfs = []
    for i, csv_path in enumerate(csv_paths, start=1):
        if i == 1 or i % 200 == 0 or i == len(csv_paths):
            log.info("  Loading partition %s/%s (%s)", i, len(csv_paths), csv_path.parent.name)
        try:
            df = pd.read_csv(
                csv_path,
                usecols=lambda column: column in DAILY_BASIC_COLUMNS,
                dtype={"ts_code": "string", "trade_date": "string"},
            )
            df["trade_date"] = df["trade_date"].str.replace(".0", "", regex=False).str.zfill(8)
            dfs.append(df)
        except Exception as exc:
            log.warning("  Failed %s: %s", csv_path, exc)

    if not dfs:
        raise RuntimeError("daily_basic CSV discovery succeeded but no CSV could be loaded")
    combined = pd.concat(dfs, ignore_index=True)
    log.info(
        "Loaded daily_basic rows=%s dates=%s tickers=%s",
        f"{len(combined):,}",
        combined["trade_date"].nunique(),
        combined["ts_code"].nunique(),
    )
    return combined


def forward_fill_free_share(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill free_share per stock across dates."""
    log.info(
        "Forward filling free_share: %s stocks, %s dates",
        df["ts_code"].nunique(),
        df["trade_date"].nunique(),
    )
    df = df.sort_values(["ts_code", "trade_date"])
    df["free_share"] = df.groupby("ts_code")["free_share"].ffill()
    df = df.dropna(subset=["free_share"])
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    log.info("After ffill + dedup: %s rows", f"{len(df):,}")
    return df


def build_daily_basic_enrichment(df: pd.DataFrame) -> pd.DataFrame:
    """Compute derived market-cap fields and keep daily_basic columns with clear names."""
    df = df.copy()
    df = df.rename(columns={"close": "daily_basic_close"})

    df["free_float_mcap"] = df["daily_basic_close"] * df["free_share"]
    df["ln_mcap_free"] = np.log(df["free_float_mcap"].clip(lower=1))
    df["ln_total_mv"] = np.log(df["total_mv"].clip(lower=1))
    df["ln_circ_mv"] = np.log(df["circ_mv"].clip(lower=1))

    keep_columns = [
        "ts_code",
        "trade_date",
        "daily_basic_close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
        "free_float_mcap",
        "ln_mcap_free",
        "ln_total_mv",
        "ln_circ_mv",
    ]
    return df[keep_columns].copy()


def merge_into_daily_clean(enrichment_df: pd.DataFrame, daily_clean_path: Path) -> pd.DataFrame:
    """Merge daily_basic enrichments into daily_clean.parquet."""
    log.info("Reading daily_clean from %s", daily_clean_path)
    daily = pd.read_parquet(daily_clean_path)
    log.info("daily_clean shape before merge: %s", daily.shape)

    daily["trade_date"] = daily["trade_date"].astype(str).str.replace(".0", "", regex=False).str.zfill(8)

    enhancement_columns = [col for col in enrichment_df.columns if col not in {"ts_code", "trade_date"}]
    overlap = [col for col in enhancement_columns if col in daily.columns]
    if overlap:
        log.info("Dropping existing enhancement columns before merge: %s", overlap)
        daily = daily.drop(columns=overlap)

    before = len(daily)
    merged = daily.merge(enrichment_df, on=["ts_code", "trade_date"], how="left", validate="many_to_one")
    if len(merged) != before:
        raise AssertionError(f"merge changed row count: before={before} after={len(merged)}")

    for column in ["free_share", "free_float_mcap", "ln_mcap_free", "total_mv", "circ_mv"]:
        if column in merged.columns:
            log.info("%s null ratio: %.3f%%", column, merged[column].isna().mean() * 100)
    log.info("daily_clean shape after merge: %s", merged.shape)
    return merged


def update_metadata(
    metadata_path: Path,
    output_path: Path,
    daily_basic_root: Path,
    enrichment_df: pd.DataFrame,
    merged_df: pd.DataFrame,
) -> None:
    payload = {}
    if metadata_path.exists():
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload.setdefault("artifacts", {})
    payload["artifacts"]["daily_parquet"] = str(output_path)
    payload["artifacts"]["metadata_json"] = str(metadata_path)
    payload["daily_basic_enrichment"] = {
        "source": str(daily_basic_root),
        "source_trade_date_start": str(enrichment_df["trade_date"].min()),
        "source_trade_date_end": str(enrichment_df["trade_date"].max()),
        "source_rows": int(len(enrichment_df)),
        "source_tickers": int(enrichment_df["ts_code"].nunique()),
        "merged_at": datetime.now().isoformat(timespec="seconds"),
        "columns_added": [
            col for col in enrichment_df.columns if col not in {"ts_code", "trade_date"}
        ],
        "null_ratios": {
            col: float(merged_df[col].isna().mean())
            for col in ["free_share", "free_float_mcap", "ln_mcap_free", "total_mv", "circ_mv"]
            if col in merged_df.columns
        },
    }
    payload["output_summary"] = {
        "rows": int(len(merged_df)),
        "tickers": int(merged_df["ts_code"].nunique()) if "ts_code" in merged_df.columns else None,
        "trade_dates": int(merged_df["trade_date"].nunique()) if "trade_date" in merged_df.columns else None,
        "columns": list(merged_df.columns),
    }
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-clean", type=Path, default=DEFAULT_DAILY_CLEAN)
    parser.add_argument("--metadata-json", type=Path, default=DEFAULT_DAILY_META)
    parser.add_argument("--daily-basic-dir", type=Path, default=DEFAULT_DAILY_BASIC_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_ENHANCED)
    parser.add_argument("--start", default=None, help="Inclusive YYYYMMDD filter for daily_basic loading.")
    parser.add_argument("--end", default=None, help="Inclusive YYYYMMDD filter for daily_basic loading.")
    parser.add_argument("--replace", action="store_true", help="Replace daily_clean.parquet with the enhanced output.")
    parser.add_argument("--backup", action="store_true", help="Create timestamped backups before replacing daily_clean artifacts.")
    parser.add_argument("--operator", default=None, help="Data mutation operator. Must be codex for shared clean-layer writes.")
    return parser.parse_args()


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.stem}.pre_daily_basic_merge_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
    shutil.copy2(path, backup_path)
    log.info("Backup written: %s", backup_path)
    return backup_path


def main() -> None:
    args = parse_args()
    require_data_mutation_authority(args.operator, operation="build_daily_clean_enhanced")
    t0 = datetime.now()

    log.info("Step 1: Load local daily_basic partitions")
    daily_basic = load_all_daily_basic(args.daily_basic_dir.expanduser(), start=args.start, end=args.end)

    log.info("Step 2: Forward-fill free_share per stock")
    daily_basic = forward_fill_free_share(daily_basic)

    log.info("Step 3: Compute daily_basic enrichment columns")
    enrichment_df = build_daily_basic_enrichment(daily_basic)

    log.info("Step 4: Merge enrichment columns into daily_clean")
    merged = merge_into_daily_clean(enrichment_df, args.daily_clean)

    log.info("Step 5: Save enhanced parquet to %s", args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(args.output, index=False)
    log.info("Saved: %s", args.output)
    log.info("Enhanced file size: %.1f MB", os.path.getsize(args.output) / 1024**2)

    if args.replace:
        log.info("Step 6: Replace daily_clean parquet with enhanced output")
        if args.backup:
            backup_file(args.daily_clean)
            backup_file(args.metadata_json)
        shutil.move(str(args.output), str(args.daily_clean))
        update_metadata(
            args.metadata_json,
            args.daily_clean,
            args.daily_basic_dir.expanduser(),
            enrichment_df,
            merged,
        )
        log.info("daily_clean replaced: %s", args.daily_clean)
        log.info("metadata updated: %s", args.metadata_json)

    elapsed = (datetime.now() - t0).total_seconds()
    log.info("Done in %.0fs (%.1f min)", elapsed, elapsed / 60)


if __name__ == "__main__":
    main()
