"""Exchange-calendar snapshot checks shared by research and hosted consumers.

``read_calendar_snapshot`` has explicit file/registration inputs. The separate
compatibility entry resolves the existing configuration only when called.
Neither imports a Console, starts a service, or fetches market data.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from factor_factory.research_evidence import sha256_file
from .calendar import DEFAULT_CALENDAR_COLUMNS, read_trade_calendar_csv
from .paths import resolve_local_tushare_paths


TRADING_CALENDAR_REGISTRY_VERSION = "factorforge_trusted_trading_calendar_registry_v1"
TRADING_CALENDAR_REGISTRY_RELATIVE_PATH = (
    "docs/contracts/factorforge-trusted-trading-calendar-snapshots-v1.json"
)
TRADING_CALENDAR_REGISTRY_PATH = Path(__file__).resolve().parents[2] / TRADING_CALENDAR_REGISTRY_RELATIVE_PATH
TRADING_CALENDAR_REGISTRY_TRUST_COMMIT = "f3809e2c9610f2b434357d16fa53389aae07bcda"
TRADING_CALENDAR_REGISTRY_TRUST_BLOB = "3cc5b79f62da35330be4b9b30ce1d759af0fd152"
TRADING_CALENDAR_REGISTRY_TRUST_SHA256 = "81816dc7fac1213a9ba8442ac729e32447b25fd215b5a1a8dfcc26e55936d4d5"
CALENDAR_SNAPSHOT_ID = "tushare_sse_open_days_19901219_20261231"
# Retained for compatibility with existing error consumers.
BLOCK_PREREGISTRATION = "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PREREGISTRATION_INVALID"


def read_calendar_snapshot(
    calendar_path: Path,
    *,
    registry_path: Path,
    registry_sha256: str,
    snapshot_id: str,
    registry_git_commit: str,
    registry_git_blob: str,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Check raw bytes and the ordered open dates against one registered snapshot.

    A missing exchange column retains the legacy convention: acceptance requires
    the exact registered raw file. Individual-security dates are not a calendar.
    """
    calendar_path = calendar_path.expanduser().resolve(strict=False)
    if workspace_root is not None:
        root = workspace_root.resolve(strict=False)
        if calendar_path == root or root in calendar_path.parents:
            raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar is not independent")
    if not calendar_path.is_file():
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar missing")
    if sha256_file(registry_path) != registry_sha256:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar registry diverged")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError(f"expected JSON object: {registry_path}")
    matches = [
        row for row in registry.get("snapshots") or []
        if isinstance(row, dict) and row.get("snapshot_id") == snapshot_id
    ]
    if len(matches) != 1 or matches[0].get("scope") != "production":
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar snapshot invalid")
    trusted = matches[0]
    frame = read_trade_calendar_csv(calendar_path, DEFAULT_CALENDAR_COLUMNS)
    if "exchange" in frame.columns and (frame["exchange"] == "SSE").any():
        frame = frame[frame["exchange"] == "SSE"]
    dates = frame.loc[frame["is_open"].astype(str) == "1", "cal_date"].astype(str)
    parsed = pd.to_datetime(dates, errors="coerce", utc=True)
    if parsed.isna().any() or parsed.empty:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar dates invalid")
    normalized = parsed.dt.strftime("%Y-%m-%d").tolist()
    if normalized != sorted(set(normalized)):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar is not canonical")
    open_dates_sha256 = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    raw_file_sha256 = sha256_file(calendar_path)
    if (
        trusted.get("open_dates_sha256") != open_dates_sha256
        or trusted.get("raw_file_sha256") != raw_file_sha256
        or trusted.get("date_count") != len(normalized)
        or trusted.get("date_min") != normalized[0]
        or trusted.get("date_max") != normalized[-1]
    ):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar snapshot is untrusted")
    return {
        "path": calendar_path,
        "dates": normalized,
        "open_dates_sha256": open_dates_sha256,
        "raw_file_sha256": raw_file_sha256,
        "registry_sha256": registry_sha256,
        "registry_git_commit": registry_git_commit,
        "registry_git_blob": registry_git_blob,
        "snapshot_id": snapshot_id,
    }


def validate_trusted_calendar_snapshot(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """Compatibility entry for the existing configured production snapshot."""
    configured = os.getenv("FACTORFORGE_TRUSTED_TRADE_CAL_CSV")
    calendar_path = Path(configured) if configured else Path(resolve_local_tushare_paths().trade_cal_csv)
    return read_calendar_snapshot(
        calendar_path,
        registry_path=TRADING_CALENDAR_REGISTRY_PATH,
        registry_sha256=TRADING_CALENDAR_REGISTRY_TRUST_SHA256,
        snapshot_id=CALENDAR_SNAPSHOT_ID,
        registry_git_commit=TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
        registry_git_blob=TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
        workspace_root=workspace_root,
    )
