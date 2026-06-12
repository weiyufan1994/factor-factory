#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / 'scripts'
sys.path = [item for item in sys.path if Path(item or '.').resolve() != SCRIPTS_DIR]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import fetch_data_api_dataset  # noqa: E402

_builder_spec = importlib.util.spec_from_file_location(
    'factorforge_build_report_qlib_provider',
    SCRIPTS_DIR / 'build_report_qlib_provider.py',
)
if _builder_spec is None or _builder_spec.loader is None:
    raise ImportError(f'cannot load {SCRIPTS_DIR / "build_report_qlib_provider.py"}')
_builder_module = importlib.util.module_from_spec(_builder_spec)
_builder_spec.loader.exec_module(_builder_module)
build_provider = _builder_module.build_provider
load_daily_source = _builder_module.load_daily_source
normalize_source = _builder_module.normalize_source
raw_format_smoke = _builder_module.raw_format_smoke


DEFAULT_PROVIDER_DIR = Path.home() / '.qlib' / 'qlib_data' / 'cn_data'
DEFAULT_FIELDS = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_yyyymmdd(value: str | int | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if '-' in raw:
        return pd.Timestamp(raw).strftime('%Y%m%d')
    return raw.replace('.0', '').zfill(8)


def load_from_data_api(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = normalize_yyyymmdd(args.start_date)
    end = normalize_yyyymmdd(args.end_date)
    if not start or not end:
        raise SystemExit('--start-date and --end-date are required when using --data-api')
    fields = args.fields or DEFAULT_FIELDS
    result = fetch_data_api_dataset(
        args.dataset_id,
        start=start,
        end=end,
        fields=fields,
        universe=args.universe,
        frequency='daily',
        catalog_path=args.catalog_path,
    )
    if getattr(result, 'status', None) == 'blocked':
        raise SystemExit(f'DATA_API_BLOCKED: {getattr(result, "blocked_reason", None)}')
    frame = result.frame
    metadata = result.to_metadata()
    return frame, {
        'source_type': 'data_api',
        'dataset_id': args.dataset_id,
        'catalog_path': str(args.catalog_path) if args.catalog_path else metadata.get('source', {}).get('catalog_path'),
        'data_api_status': getattr(result, 'status', None),
        'data_api_metadata': metadata,
    }


def load_source(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if args.data_api:
        return load_from_data_api(args)
    if not args.input:
        raise SystemExit('one of --input or --data-api is required')
    source_path = Path(args.input).expanduser().resolve()
    frame = load_daily_source(source_path)
    return frame, {'source_type': 'local_file', 'source_path': str(source_path)}


def sync_provider_to_s3(provider_dir: Path, s3_uri: str) -> dict[str, Any]:
    if not shutil.which('aws'):
        raise SystemExit('aws CLI is required for --sync-s3-uri')
    cmd = ['aws', 's3', 'sync', str(provider_dir), s3_uri, '--delete']
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    payload = {
        'command': cmd,
        'returncode': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }
    if result.returncode != 0:
        raise SystemExit('S3_SYNC_FAILED: ' + json.dumps(payload, ensure_ascii=False))
    return payload


def microsoft_qlib_import_status() -> dict[str, Any]:
    try:
        import qlib  # type: ignore
    except Exception as exc:
        return {'available': False, 'reason': f'import_failed:{type(exc).__name__}:{exc}'}
    module_file = str(getattr(qlib, '__file__', ''))
    if not hasattr(qlib, 'init'):
        return {
            'available': False,
            'reason': 'imported_non_microsoft_qlib_without_init',
            'module_file': module_file,
        }
    try:
        from qlib.data import D  # noqa: F401
    except Exception as exc:
        return {
            'available': False,
            'reason': f'microsoft_qlib_data_import_failed:{type(exc).__name__}:{exc}',
            'module_file': module_file,
        }
    return {'available': True, 'module_file': module_file}


def run_microsoft_qlib_smoke(provider_dir: Path, allow_missing: bool = False) -> dict[str, Any]:
    status = microsoft_qlib_import_status()
    if not status.get('available'):
        if allow_missing:
            return {'status': 'SKIPPED', **status}
        raise SystemExit('MICROSOFT_QLIB_UNAVAILABLE: ' + json.dumps(status, ensure_ascii=False))

    import qlib  # type: ignore
    from qlib.data import D  # type: ignore

    qlib.init(provider_uri=str(provider_dir), region='cn')
    calendar = D.calendar(freq='day')
    instruments = sorted((provider_dir / 'features').iterdir())
    if not instruments:
        raise SystemExit(f'no feature instruments under {provider_dir / "features"}')
    first = instruments[0].name.upper()
    values = D.features([first], ['$close'], freq='day')
    return {
        'status': 'PASS',
        'module_file': status.get('module_file'),
        'calendar_count': int(len(calendar)),
        'first_instrument': first,
        'first_close_rows': int(len(values)),
    }


def write_env_file(path: Path, provider_dir: Path, s3_uri: str | None) -> None:
    lines = [
        '# Generated by scripts/publish_qlib_daily_provider.py',
        f'export QLIB_PROVIDER_URI={provider_dir}',
    ]
    if s3_uri:
        lines.append(f'export FACTORFORGE_QLIB_PROVIDER_S3_URI={s3_uri}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser(description='Publish a cleaned daily dataset into a Qlib provider directory.')
    ap.add_argument('--input', help='Clean daily parquet/csv with ts_code, trade_date, OHLCV, amount, pct_chg.')
    ap.add_argument('--data-api', action='store_true', help='Fetch clean_daily_bar through the independent Data API catalog.')
    ap.add_argument('--catalog-path')
    ap.add_argument('--dataset-id', default='clean_daily_bar')
    ap.add_argument('--start-date')
    ap.add_argument('--end-date')
    ap.add_argument('--fields', nargs='+')
    ap.add_argument('--universe', default='a_share_all')
    ap.add_argument('--provider-dir', default=os.getenv('QLIB_PROVIDER_URI') or str(DEFAULT_PROVIDER_DIR))
    ap.add_argument('--instrument-style', default='legacy_qlib', choices=['ts_code', 'tushare', 'provider', 'legacy_qlib', 'qlib', 'raw'])
    ap.add_argument('--sync-s3-uri', help='Optional S3 prefix to mirror the provider directory with aws s3 sync --delete.')
    ap.add_argument('--write-env-file', help='Optional shell env file containing QLIB_PROVIDER_URI.')
    ap.add_argument('--raw-smoke', action='store_true', default=True)
    ap.add_argument('--qlib-smoke', action='store_true')
    ap.add_argument('--allow-missing-microsoft-qlib', action='store_true')
    args = ap.parse_args()

    provider_dir = Path(args.provider_dir).expanduser().resolve()
    source_frame, source_meta = load_source(args)
    normalized = normalize_source(source_frame, instrument_style=args.instrument_style)
    stats = build_provider(normalized, provider_dir, instrument_style=args.instrument_style)
    publish_report: dict[str, Any] = {
        'version': 'factorforge_qlib_daily_provider_publish_v1',
        'created_at_utc': utc_now(),
        'provider_dir': str(provider_dir),
        'instrument_style': args.instrument_style,
        'source': source_meta,
        'provider_stats': stats,
    }

    if args.raw_smoke:
        publish_report['raw_format_smoke'] = raw_format_smoke(provider_dir)
    if args.qlib_smoke:
        publish_report['microsoft_qlib_smoke'] = run_microsoft_qlib_smoke(
            provider_dir,
            allow_missing=args.allow_missing_microsoft_qlib,
        )
    if args.sync_s3_uri:
        publish_report['s3_sync'] = sync_provider_to_s3(provider_dir, args.sync_s3_uri)
    if args.write_env_file:
        env_file = Path(args.write_env_file).expanduser().resolve()
        write_env_file(env_file, provider_dir, args.sync_s3_uri)
        publish_report['env_file'] = str(env_file)

    report_path = provider_dir / 'publish_report.json'
    report_path.write_text(json.dumps(publish_report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[PUBLISH_REPORT] ' + json.dumps(publish_report, ensure_ascii=False, sort_keys=True))
    print(f'[WRITE] {report_path}')


if __name__ == '__main__':
    main()
