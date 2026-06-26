#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.smart_money_intraday_state import (  # noqa: E402
    DATASET_ID,
    SmartMoneyIntradayStateParams,
    build_catalog_entry,
    build_smart_money_intraday_state_qa,
    derive_smart_money_intraday_state,
    normalize_trade_date,
    write_partitioned_datamart,
)


MINUTE_COLUMNS = ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'open', 'close', 'vol', 'amount']
AWS_RETRY_ATTEMPTS = 4
AWS_RETRY_BASE_SLEEP_SECONDS = 2.0
AWS_LIST_TIMEOUT_SECONDS = 45.0
AWS_CP_TIMEOUT_SECONDS = 180.0


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build smart_money_intraday_state_v1 from minute_bar-like parquet.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--minute-path')
    source.add_argument('--minute-root')
    source.add_argument('--minute-s3-root')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--dates', default='')
    parser.add_argument('--dates-file', default='', help='Optional file with one target trade_date per line. Ignored when --dates is set.')
    parser.add_argument('--available-dates-file', default='', help='Optional cached source trade_date list; avoids top-level S3 listing when source partitions are already known.')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--qa-output', required=True)
    parser.add_argument('--catalog-output', required=True)
    parser.add_argument('--manifest-output', default='')
    parser.add_argument('--lookback-trading-days', type=int, default=10)
    parser.add_argument('--cutoff-volume-share', type=float, default=0.20)
    parser.add_argument('--min-valid-minutes', type=int, default=5)
    parser.add_argument('--research-window', default='IS', choices=['IS', 'OOS', 'SMOKE'])
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--overwrite-date-partitions', action='store_true')
    parser.add_argument('--max-dates', type=int)
    parser.add_argument('--max-target-dates-without-override', type=int, default=5)
    parser.add_argument('--allow-large-materialization', action='store_true', help='Allow a single invocation to process more target dates than the guard limit.')
    parser.add_argument('--s3-local-cache', default='', help='Optional local cache for S3 minute partitions. If omitted, a temporary cache is removed after the run.')
    parser.add_argument('--batch-plan-output', default='', help='Optional JSON path for the resumable batch execution plan.')
    parser.add_argument('--plan-only', action='store_true', help='Write batch plan without reading source data or writing datamart outputs.')
    return parser.parse_args(argv)


def discover_partition_dates(root: Path) -> list[str]:
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir()
    })


def partition_has_parquet(path: Path) -> bool:
    return any(child.is_file() and child.name.endswith('.parquet') for child in path.iterdir())


def discover_output_ready_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in root.glob('trade_date=*')
        if path.is_dir() and partition_has_parquet(path)
    })


def parse_target_dates(args: argparse.Namespace, available: list[str]) -> list[str]:
    if args.dates:
        return sorted({normalize_trade_date(item) for item in split_csv(args.dates)})
    if args.dates_file:
        raw = Path(args.dates_file).expanduser().read_text(encoding='utf-8')
        return sorted({normalize_trade_date(line) for line in raw.splitlines() if line.strip() and not line.strip().startswith('#')})
    start = normalize_trade_date(args.start)
    end = normalize_trade_date(args.end)
    return [date for date in available if start <= date <= end]


def read_available_dates_file(path: str | Path) -> list[str]:
    raw = Path(path).expanduser().read_text(encoding='utf-8')
    return sorted({normalize_trade_date(line) for line in raw.splitlines() if line.strip() and not line.strip().startswith('#')})


def enforce_materialization_guard(args: argparse.Namespace, target_dates: list[str]) -> None:
    if args.plan_only or args.allow_large_materialization:
        return
    limit = int(args.max_target_dates_without_override)
    if limit >= 0 and len(target_dates) > limit:
        raise SystemExit(
            f'target date count {len(target_dates)} exceeds guard limit {limit}; '
            'use --max-dates, --dates/--dates-file, or --allow-large-materialization for an explicit full run'
        )


def source_dates_for_targets(available: list[str], targets: list[str], lookback_days: int) -> list[str]:
    positions = {date: index for index, date in enumerate(available)}
    needed: set[str] = set()
    for target in targets:
        if target not in positions:
            continue
        index = positions[target]
        needed.update(available[max(0, index - int(lookback_days) + 1): index + 1])
    return sorted(needed)


def select_resumable_dates(target_dates: list[str], output_root: Path, *, skip_existing: bool, max_dates: int | None) -> tuple[list[str], list[str], list[str], list[str]]:
    existing = discover_output_ready_dates(output_root)
    existing_set = set(existing)
    skipped = [date for date in target_dates if skip_existing and date in existing_set]
    pending = [date for date in target_dates if date not in set(skipped)]
    selected = pending[:max_dates] if max_dates is not None else pending
    remaining = pending[len(selected):]
    return selected, skipped, remaining, existing


def remove_selected_output_partitions(output_root: Path, dates: list[str]) -> list[str]:
    removed: list[str] = []
    for trade_date in dates:
        part = output_root / f'trade_date={trade_date}'
        if part.exists():
            shutil.rmtree(part)
            removed.append(trade_date)
    return removed


def read_minute_path(path: Path) -> tuple[pd.DataFrame, list[str], list[dict[str, object]]]:
    frame = pd.read_parquet(path)
    keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
    frame = frame[keep]
    dates = sorted(frame['trade_date'].map(normalize_trade_date).unique().tolist()) if 'trade_date' in frame.columns else []
    return frame, dates, [{'status': 'single_file', 'path': str(path), 'minute_rows': int(len(frame))}]


def read_minute_root(root: Path, source_dates: list[str]) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    missing: list[str] = []
    for trade_date in source_dates:
        part = root / f'trade_date={trade_date}'
        if not part.exists():
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_partition', 'path': str(part)})
            continue
        parquet_files = sorted(child for child in part.iterdir() if child.is_file() and child.name.endswith('.parquet'))
        if not parquet_files:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_parquet_file', 'path': str(part)})
            continue
        frame = pd.concat([pd.read_parquet(file) for file in parquet_files], ignore_index=True)
        keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
        frame = frame[keep]
        frames.append(frame)
        profile.append({'trade_date': trade_date, 'status': 'ready', 'path': str(part), 'files': [str(file) for file in parquet_files], 'minute_rows': int(len(frame))})
    if not frames:
        return pd.DataFrame(), profile, sorted(set(missing))
    return pd.concat(frames, ignore_index=True), profile, sorted(set(missing))


def discover_s3_partition_dates(root: str) -> list[str]:
    import re

    output = run_aws_text(['aws', 's3', 'ls', root.rstrip('/') + '/'], timeout_seconds=AWS_LIST_TIMEOUT_SECONDS)
    return sorted(set(re.findall(r'trade_date=(\d{8})/', output)))


def list_s3_partition_files(root: str, trade_date: str) -> list[str]:
    partition_uri = f"{root.rstrip('/')}/trade_date={trade_date}/"
    output = run_aws_text(['aws', 's3', 'ls', partition_uri], timeout_seconds=AWS_LIST_TIMEOUT_SECONDS)
    files: list[str] = []
    for line in output.splitlines():
        name = line.strip().split()[-1] if line.strip() else ''
        if name.endswith('.parquet'):
            files.append(partition_uri + name)
    return files


def find_cached_partition_files(local_cache: Path, trade_date: str) -> list[Path]:
    direct = local_cache / f'trade_date={trade_date}'
    direct_files = sorted(path for path in direct.glob('*.parquet') if path.is_file())
    if direct_files:
        return direct_files
    nested_parents = sorted({path.parent for path in local_cache.glob(f'**/trade_date={trade_date}/*.parquet') if path.is_file()})
    if not nested_parents:
        return []
    return sorted(path for path in nested_parents[0].glob('*.parquet') if path.is_file())


def run_aws_text(command: list[str], *, timeout_seconds: float) -> str:
    last_error: Exception | None = None
    for attempt in range(1, AWS_RETRY_ATTEMPTS + 1):
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            last_error = exc
            if attempt < AWS_RETRY_ATTEMPTS:
                time.sleep(AWS_RETRY_BASE_SLEEP_SECONDS * attempt)
            continue
        if proc.returncode == 0:
            return proc.stdout
        last_error = subprocess.CalledProcessError(
            proc.returncode,
            command,
            output=proc.stdout,
            stderr=proc.stderr,
        )
        if attempt < AWS_RETRY_ATTEMPTS:
            time.sleep(AWS_RETRY_BASE_SLEEP_SECONDS * attempt)
    assert last_error is not None
    raise last_error


def run_aws_checked(command: list[str], *, timeout_seconds: float) -> None:
    run_aws_text(command, timeout_seconds=timeout_seconds)


def cleanup_aws_temp_files(target: Path) -> None:
    for path in target.parent.glob(target.name + '.*'):
        if path.is_file():
            path.unlink()


def download_s3_file(uri: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cleanup_aws_temp_files(target)
    tmp = target.with_name(target.name + '.download_tmp')
    if tmp.exists():
        tmp.unlink()
    try:
        run_aws_checked(['aws', 's3', 'cp', uri, str(tmp), '--only-show-errors'], timeout_seconds=AWS_CP_TIMEOUT_SECONDS)
        tmp.replace(target)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def read_minute_s3_root(root: str, source_dates: list[str], local_cache: Path) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
    frames: list[pd.DataFrame] = []
    profile: list[dict[str, object]] = []
    missing: list[str] = []
    local_cache.mkdir(parents=True, exist_ok=True)
    for trade_date in source_dates:
        date_cache = local_cache / f'trade_date={trade_date}'
        cached_files = find_cached_partition_files(local_cache, trade_date)
        if cached_files:
            frame = pd.concat([pd.read_parquet(file) for file in cached_files], ignore_index=True)
            keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
            frame = frame[keep]
            frames.append(frame)
            profile.append({
                'trade_date': trade_date,
                'status': 'ready_local_cache',
                'local_files': [str(file) for file in cached_files],
                'minute_rows': int(len(frame)),
            })
            continue
        try:
            uris = list_s3_partition_files(root, trade_date)
        except subprocess.CalledProcessError as exc:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 's3_list_error', 'root': root, 'returncode': int(exc.returncode)})
            continue
        except subprocess.TimeoutExpired as exc:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 's3_list_timeout', 'root': root, 'timeout_seconds': float(exc.timeout or 0.0)})
            continue
        if not uris:
            missing.append(trade_date)
            profile.append({'trade_date': trade_date, 'status': 'missing_s3_partition_files', 'root': root})
            continue
        local_files: list[Path] = []
        date_cache.mkdir(parents=True, exist_ok=True)
        for index, uri in enumerate(uris):
            target = date_cache / f'part-{index:03d}.parquet'
            if not target.exists():
                download_s3_file(uri, target)
            local_files.append(target)
        frame = pd.concat([pd.read_parquet(file) for file in local_files], ignore_index=True)
        keep = [column for column in MINUTE_COLUMNS if column in frame.columns]
        frame = frame[keep]
        frames.append(frame)
        profile.append({
            'trade_date': trade_date,
            'status': 'ready_s3_cached',
            's3_files': uris,
            'local_files': [str(file) for file in local_files],
            'minute_rows': int(len(frame)),
        })
    if not frames:
        return pd.DataFrame(), profile, sorted(set(missing))
    return pd.concat(frames, ignore_index=True), profile, sorted(set(missing))


def build_batch_execution_plan(
    *,
    args: argparse.Namespace,
    available_dates: list[str],
    requested_targets: list[str],
    selected_targets: list[str],
    source_dates: list[str],
    skipped_dates: list[str],
    remaining_dates: list[str],
) -> dict[str, object]:
    source_kind = 'minute_path' if args.minute_path else 'minute_root' if args.minute_root else 'minute_s3_root'
    return {
        'version': 'factorforge_batch_execution_plan_v1',
        'dataset_id': DATASET_ID,
        'source_kind': source_kind,
        'source_uri': args.minute_path or args.minute_root or args.minute_s3_root,
        'partition_key': 'trade_date',
        'selected_columns': MINUTE_COLUMNS,
        'lookback_overlap': {
            'lookback_trading_days': int(args.lookback_trading_days),
            'source_dates_for_selected_targets': source_dates,
        },
        'target_window': {
            'start': normalize_trade_date(args.start),
            'end': normalize_trade_date(args.end),
            'requested_targets': requested_targets,
            'selected_targets_this_run': selected_targets,
            'skipped_existing_dates': skipped_dates,
            'remaining_dates_after_this_run': remaining_dates,
            'available_source_date_count': len(available_dates),
            'materialization_guard': {
                'max_target_dates_without_override': int(args.max_target_dates_without_override),
                'allow_large_materialization': bool(args.allow_large_materialization),
                'plan_only': bool(args.plan_only),
            },
        },
        'memory_policy': {
            'batch_unit': 'target trade_date slice plus lookback source date overlap',
            'does_not_scan_full_s3_dataset': True,
            'does_not_keep_cross_batch_dataframe_list': True,
            'resume_with_skip_existing': True,
        },
        'output': {
            'format': 'partitioned parquet',
            'output_root': str(Path(args.output_root).expanduser()),
            'qa_output': str(Path(args.qa_output).expanduser()),
            'catalog_output': str(Path(args.catalog_output).expanduser()),
            'manifest_output': str(Path(args.manifest_output).expanduser()) if args.manifest_output else '',
        },
        'validation': {
            'qa_checks': ['row_count_nonzero', 'duplicate_key_count_zero', 'expected_columns_present', 'qa_status_pass_row_count_positive', 'no_future_intraday_minutes_true'],
            'sample_parity_policy': 'compare small local fixture output against formula-level expected invariants before production batches',
        },
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    }


def write_json(path: str | Path, payload: dict[str, object]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    output_root = Path(args.output_root).expanduser()
    if args.max_dates is not None and int(args.max_dates) < 0:
        raise SystemExit('--max-dates must be non-negative')
    temp_cache: tempfile.TemporaryDirectory[str] | None = None
    source_dates: list[str] = []
    if args.minute_path:
        minute, available_dates, source_profile = read_minute_path(Path(args.minute_path).expanduser())
        requested_targets = parse_target_dates(args, available_dates)
        target_dates, skipped_dates, remaining_dates, existing_dates = select_resumable_dates(
            requested_targets,
            output_root,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        enforce_materialization_guard(args, target_dates)
        missing_dates: list[str] = []
        source_dates = target_dates
    elif args.minute_root:
        minute_root = Path(args.minute_root).expanduser()
        available_dates = read_available_dates_file(args.available_dates_file) if args.available_dates_file else discover_partition_dates(minute_root)
        requested_targets = parse_target_dates(args, available_dates)
        target_dates, skipped_dates, remaining_dates, existing_dates = select_resumable_dates(
            requested_targets,
            output_root,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        enforce_materialization_guard(args, target_dates)
        source_dates = source_dates_for_targets(available_dates, target_dates, int(args.lookback_trading_days))
        minute, source_profile, missing_dates = read_minute_root(minute_root, source_dates)
    else:
        available_dates = read_available_dates_file(args.available_dates_file) if args.available_dates_file else discover_s3_partition_dates(str(args.minute_s3_root))
        requested_targets = parse_target_dates(args, available_dates)
        target_dates, skipped_dates, remaining_dates, existing_dates = select_resumable_dates(
            requested_targets,
            output_root,
            skip_existing=bool(args.skip_existing),
            max_dates=args.max_dates,
        )
        enforce_materialization_guard(args, target_dates)
        source_dates = source_dates_for_targets(available_dates, target_dates, int(args.lookback_trading_days))
        cache_root = Path(args.s3_local_cache).expanduser() if args.s3_local_cache else None
        if args.plan_only:
            minute = pd.DataFrame()
            source_profile = []
            missing_dates = []
        else:
            if cache_root is None:
                temp_cache = tempfile.TemporaryDirectory(prefix='smart_money_minute_s3_')
                cache_root = Path(temp_cache.name)
            minute, source_profile, missing_dates = read_minute_s3_root(str(args.minute_s3_root), source_dates, cache_root)
    batch_plan = build_batch_execution_plan(
        args=args,
        available_dates=available_dates,
        requested_targets=requested_targets,
        selected_targets=target_dates,
        source_dates=source_dates,
        skipped_dates=skipped_dates,
        remaining_dates=remaining_dates,
    )
    if args.batch_plan_output:
        write_json(args.batch_plan_output, batch_plan)
    if args.plan_only:
        print(json.dumps({'verdict': 'PLAN_ONLY', 'dataset_id': DATASET_ID, 'batch_plan_output': str(args.batch_plan_output)}, ensure_ascii=False))
        if temp_cache is not None:
            temp_cache.cleanup()
        return 0
    if args.overwrite_date_partitions:
        removed_dates = remove_selected_output_partitions(output_root, target_dates)
    else:
        removed_dates = []
        if not args.skip_existing:
            conflicts = sorted(set(target_dates).intersection(existing_dates))
            if conflicts:
                raise SystemExit(f'output partitions already exist; pass --skip-existing or --overwrite-date-partitions: {conflicts[:10]}')
    params = SmartMoneyIntradayStateParams(
        lookback_trading_days=int(args.lookback_trading_days),
        cutoff_volume_share=float(args.cutoff_volume_share),
        min_valid_minutes=int(args.min_valid_minutes),
        research_window=str(args.research_window),
    )
    output = derive_smart_money_intraday_state(minute, params=params, target_dates=target_dates)
    write_partitioned_datamart(output, output_root)
    runtime_seconds = float(time.perf_counter() - started)
    qa = build_smart_money_intraday_state_qa(
        output,
        params=params,
        missing_dates=missing_dates,
        output_path=output_root,
        runtime_seconds=runtime_seconds,
        input_minute_row_count=int(len(minute)),
    )
    qa.update({
        'available_dates': available_dates,
        'requested_target_dates': requested_targets,
        'target_dates': target_dates,
        'processed_dates': sorted(output['trade_date'].unique().tolist()) if not output.empty else [],
        'skipped_existing_dates': skipped_dates,
        'remaining_dates': remaining_dates,
        'existing_output_dates_before': existing_dates,
        'removed_output_partitions': removed_dates,
        'source_profile': source_profile,
        'batch_execution_plan': batch_plan,
        'safety': {
            'starts_worker': False,
            'sends_ssm_command': False,
            'writes_active_catalog': False,
            'writes_factorforge_artifacts': False,
            'production_loop_side_effect': False,
        },
    })
    qa_path = Path(args.qa_output).expanduser()
    write_json(qa_path, qa)
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            DATASET_ID: build_catalog_entry(
                output_root,
                qa_path,
                str(qa.get('start_date') or args.start),
                str(qa.get('end_date') or args.end),
                params=params,
            )
        },
    }
    catalog_path = Path(args.catalog_output).expanduser()
    write_json(catalog_path, catalog)
    if args.manifest_output:
        manifest = {
            'verdict': qa['verdict'],
            'dataset_id': DATASET_ID,
            'output_root': str(output_root),
            'qa_output': str(qa_path),
            'catalog_output': str(catalog_path),
            'processed_dates': qa['processed_dates'],
            'skipped_existing_dates': skipped_dates,
            'remaining_dates': remaining_dates,
            'removed_output_partitions': removed_dates,
            'safety': qa['safety'],
        }
        manifest_path = Path(args.manifest_output).expanduser()
        write_json(manifest_path, manifest)
    if temp_cache is not None:
        temp_cache.cleanup()
    print(json.dumps({'verdict': qa['verdict'], 'dataset_id': DATASET_ID, 'row_count': qa['row_count'], 'output_root': str(output_root)}, ensure_ascii=False))
    return 0 if qa['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
