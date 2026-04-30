from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOCAL_ROOT = Path.home() / '.qlib' / 'raw_tushare'
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
DEFAULT_EC2_PERSISTENT_ROOT = LEGACY_WORKSPACE / 'factorforge' / 'data' / 'raw_tushare'


def _running_as_root() -> bool:
    geteuid = getattr(os, 'geteuid', None)
    return bool(geteuid and geteuid() == 0)


@dataclass(frozen=True)
class LocalTusharePaths:
    root: Path
    daily_csv: Path
    adj_factor_csv: Path
    daily_basic_dir: Path
    trade_cal_csv: Path
    stock_basic_csv: Path
    stock_st_csv: Path
    stock_st_daily_csv: Path
    source_label: str = 'unknown'


def default_local_data_root() -> Path:
    explicit_root = os.getenv('FACTORFORGE_LOCAL_DATA_ROOT')
    if explicit_root:
        return Path(explicit_root).expanduser()
    if DEFAULT_EC2_PERSISTENT_ROOT.exists():
        return DEFAULT_EC2_PERSISTENT_ROOT.expanduser()
    if _running_as_root():
        raise RuntimeError(
            'FACTORFORGE_LOCAL_DATA_ROOT must be set when running as root; '
            'refusing to fall back to /root/.qlib/raw_tushare'
        )
    return DEFAULT_LOCAL_ROOT.expanduser()


def _dedupe(paths: list[Path | None]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path is None:
            continue
        key = str(path.expanduser())
        if key not in seen:
            deduped.append(path.expanduser())
            seen.add(key)
    return deduped


def _first_existing(candidates: list[Path | None], fallback: Path) -> Path:
    for path in _dedupe(candidates):
        if path.exists():
            return path
    return fallback.expanduser()


def _candidate_roots() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []

    explicit_root = os.getenv('FACTORFORGE_LOCAL_DATA_ROOT')
    if explicit_root:
        candidates.append((Path(explicit_root).expanduser(), 'local_env'))

    candidates.append((DEFAULT_EC2_PERSISTENT_ROOT.expanduser(), 'workspace_persistent'))
    if not _running_as_root():
        candidates.append((DEFAULT_LOCAL_ROOT.expanduser(), 'local_default'))

    tailscale_root = os.getenv('FACTORFORGE_TAILSCALE_DATA_ROOT')
    if tailscale_root:
        candidates.append((Path(tailscale_root).expanduser(), 'tailscale_env'))

    candidates.extend(
        [
            (Path('/mnt/tailscale/raw_tushare'), 'tailscale_guess'),
            (Path('/mnt/tailscale/macbook/raw_tushare'), 'tailscale_guess'),
            (Path('/Volumes/raw_tushare'), 'tailscale_guess'),
        ]
    )

    deduped: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, label in candidates:
        key = str(path.expanduser())
        if key in seen:
            continue
        deduped.append((path.expanduser(), label))
        seen.add(key)
    return deduped


def _paths_for_root(root: Path, source_label: str) -> LocalTusharePaths:
    return LocalTusharePaths(
        root=root,
        daily_csv=root / '行情数据' / 'daily.csv',
        adj_factor_csv=root / '行情数据' / 'adj_factor.csv',
        daily_basic_dir=root / '行情数据' / 'daily_basic_incremental',
        trade_cal_csv=root / '基础数据' / 'trade_cal.csv',
        stock_basic_csv=root / '基础数据' / 'stock_basic.csv',
        stock_st_csv=root / '基础数据' / 'stock_st.csv',
        stock_st_daily_csv=root / '基础数据' / 'stock_st_daily_20160101_current.csv',
        source_label=source_label,
    )


def _has_required_inputs(paths: LocalTusharePaths, require_daily_basic: bool = False) -> bool:
    core_ready = all(
        [
            paths.daily_csv.exists(),
            paths.adj_factor_csv.exists(),
            paths.trade_cal_csv.exists(),
            paths.stock_basic_csv.exists(),
            paths.stock_st_csv.exists(),
        ]
    )
    if not core_ready:
        return False
    if require_daily_basic and not inspect_trade_date_csv_root(paths.daily_basic_dir):
        return False
    return True


def resolve_local_tushare_paths(require_daily_basic: bool = False) -> LocalTusharePaths:
    explicit_root = default_local_data_root()

    if any(
        os.getenv(name)
        for name in [
            'FACTORFORGE_DAILY_CSV',
            'FACTORFORGE_ADJ_FACTOR_CSV',
            'FACTORFORGE_DAILY_BASIC_DIR',
            'FACTORFORGE_TRADE_CAL_CSV',
            'FACTORFORGE_STOCK_BASIC_CSV',
            'FACTORFORGE_STOCK_ST_CSV',
            'FACTORFORGE_STOCK_ST_DAILY_CSV',
        ]
    ):
        explicit_bundle = LocalTusharePaths(
            root=explicit_root,
            daily_csv=Path(os.getenv('FACTORFORGE_DAILY_CSV', explicit_root / '行情数据' / 'daily.csv')).expanduser(),
            adj_factor_csv=Path(os.getenv('FACTORFORGE_ADJ_FACTOR_CSV', explicit_root / '行情数据' / 'adj_factor.csv')).expanduser(),
            daily_basic_dir=Path(os.getenv('FACTORFORGE_DAILY_BASIC_DIR', explicit_root / '行情数据' / 'daily_basic_incremental')).expanduser(),
            trade_cal_csv=Path(os.getenv('FACTORFORGE_TRADE_CAL_CSV', explicit_root / '基础数据' / 'trade_cal.csv')).expanduser(),
            stock_basic_csv=Path(os.getenv('FACTORFORGE_STOCK_BASIC_CSV', explicit_root / '基础数据' / 'stock_basic.csv')).expanduser(),
            stock_st_csv=Path(os.getenv('FACTORFORGE_STOCK_ST_CSV', explicit_root / '基础数据' / 'stock_st.csv')).expanduser(),
            stock_st_daily_csv=Path(os.getenv('FACTORFORGE_STOCK_ST_DAILY_CSV', explicit_root / '基础数据' / 'stock_st_daily_20160101_current.csv')).expanduser(),
            source_label='explicit_overrides',
        )
        if _has_required_inputs(explicit_bundle, require_daily_basic=require_daily_basic):
            return explicit_bundle

    for root, label in _candidate_roots():
        candidate = _paths_for_root(root, source_label=label)
        if _has_required_inputs(candidate, require_daily_basic=require_daily_basic):
            return candidate

    root = explicit_root

    daily_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_DAILY_CSV', '')).expanduser() if os.getenv('FACTORFORGE_DAILY_CSV') else None,
            *[candidate_root / '行情数据' / 'daily.csv' for candidate_root, _ in _candidate_roots()],
            Path.home() / 'Downloads' / 'daily.csv',
        ],
        root / '行情数据' / 'daily.csv',
    )
    adj_factor_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_ADJ_FACTOR_CSV', '')).expanduser() if os.getenv('FACTORFORGE_ADJ_FACTOR_CSV') else None,
            *[candidate_root / '行情数据' / 'adj_factor.csv' for candidate_root, _ in _candidate_roots()],
        ],
        root / '行情数据' / 'adj_factor.csv',
    )
    daily_basic_dir = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_DAILY_BASIC_DIR', '')).expanduser() if os.getenv('FACTORFORGE_DAILY_BASIC_DIR') else None,
            *[candidate_root / '行情数据' / 'daily_basic_incremental' for candidate_root, _ in _candidate_roots()],
        ],
        root / '行情数据' / 'daily_basic_incremental',
    )
    trade_cal_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_TRADE_CAL_CSV', '')).expanduser() if os.getenv('FACTORFORGE_TRADE_CAL_CSV') else None,
            *[candidate_root / '基础数据' / 'trade_cal.csv' for candidate_root, _ in _candidate_roots()],
        ],
        root / '基础数据' / 'trade_cal.csv',
    )
    stock_basic_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_STOCK_BASIC_CSV', '')).expanduser() if os.getenv('FACTORFORGE_STOCK_BASIC_CSV') else None,
            *[candidate_root / '基础数据' / 'stock_basic.csv' for candidate_root, _ in _candidate_roots()],
        ],
        root / '基础数据' / 'stock_basic.csv',
    )
    stock_st_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_STOCK_ST_CSV', '')).expanduser() if os.getenv('FACTORFORGE_STOCK_ST_CSV') else None,
            *[candidate_root / '基础数据' / 'stock_st.csv' for candidate_root, _ in _candidate_roots()],
        ],
        root / '基础数据' / 'stock_st.csv',
    )
    stock_st_daily_csv = _first_existing(
        [
            Path(os.getenv('FACTORFORGE_STOCK_ST_DAILY_CSV', '')).expanduser() if os.getenv('FACTORFORGE_STOCK_ST_DAILY_CSV') else None,
            *[candidate_root / '基础数据' / 'stock_st_daily_20160101_current.csv' for candidate_root, _ in _candidate_roots()],
        ],
        root / '基础数据' / 'stock_st_daily_20160101_current.csv',
    )

    return LocalTusharePaths(
        root=root,
        daily_csv=daily_csv,
        adj_factor_csv=adj_factor_csv,
        daily_basic_dir=daily_basic_dir,
        trade_cal_csv=trade_cal_csv,
        stock_basic_csv=stock_basic_csv,
        stock_st_csv=stock_st_csv,
        stock_st_daily_csv=stock_st_daily_csv,
        source_label='mixed_fallback',
    )


def inspect_trade_date_csv_root(path: Path) -> dict | None:
    if not path.exists():
        return None

    csv_parts = sorted(path.glob('trade_date=*/*.csv'))
    if not csv_parts:
        return None

    trade_dates = sorted({part.parent.name.replace('trade_date=', '') for part in csv_parts})
    return {
        'path': path,
        'format': 'trade_date_partitioned_csv',
        'trade_dates': trade_dates,
        'trade_date_count': len(trade_dates),
    }


def summarize_local_tushare_paths() -> dict:
    paths = resolve_local_tushare_paths()
    daily_basic_meta = inspect_trade_date_csv_root(paths.daily_basic_dir)
    return {
        'root': str(paths.root),
        'source_label': paths.source_label,
        'candidate_roots': [
            {'path': str(path), 'label': label, 'exists': path.exists()}
            for path, label in _candidate_roots()
        ],
        'daily_csv': {'path': str(paths.daily_csv), 'exists': paths.daily_csv.exists()},
        'adj_factor_csv': {'path': str(paths.adj_factor_csv), 'exists': paths.adj_factor_csv.exists()},
        'daily_basic_dir': {
            'path': str(paths.daily_basic_dir),
            'exists': paths.daily_basic_dir.exists(),
            'trade_date_count': int(daily_basic_meta['trade_date_count']) if daily_basic_meta else 0,
        },
        'trade_cal_csv': {'path': str(paths.trade_cal_csv), 'exists': paths.trade_cal_csv.exists()},
        'stock_basic_csv': {'path': str(paths.stock_basic_csv), 'exists': paths.stock_basic_csv.exists()},
        'stock_st_csv': {'path': str(paths.stock_st_csv), 'exists': paths.stock_st_csv.exists()},
        'stock_st_daily_csv': {'path': str(paths.stock_st_daily_csv), 'exists': paths.stock_st_daily_csv.exists()},
    }
