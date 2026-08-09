from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from factor_factory.miner.common import read_json, utc_now, workspace_path, write_json
from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)


DATA_SPLIT_MANIFEST_VERSION = "factorforge_miner_data_split_manifest_v1"
BLOCK_DATA_SPLIT_INVALID = "BLOCK_FACTORFORGE_MINER_DATA_SPLIT_MANIFEST_INVALID"
CANONICAL_DATA_SPLIT_REF = "objects/search_control/data_split_manifest.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OOS_RELEASE_STATES = {"SEALED_UNRELEASED"}


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_panel(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:unsupported_panel_format")


def _normalized_dates(frame: pd.DataFrame) -> list[str]:
    if "trade_date" not in frame.columns:
        raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:trade_date_missing")
    raw = frame["trade_date"].dropna().astype(str).str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(raw, errors="coerce")
    if parsed.isna().any() or parsed.empty:
        raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:trade_date_invalid")
    return sorted(set(parsed.dt.strftime("%Y-%m-%d").tolist()))


def _panel_contract(path: Path, workspace_root: Path) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    resolved = path.expanduser().resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:panel_outside_workspace")
    if not resolved.is_file():
        raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:panel_missing")
    frame = _load_panel(resolved)
    dates = _normalized_dates(frame)
    return {
        "panel_ref": str(resolved.relative_to(root)),
        "panel_sha256": sha256_file(resolved),
        "observed_start_date": dates[0],
        "observed_end_date": dates[-1],
        "observed_period_count": len(dates),
        "observed_dates_sha256": _stable_hash(dates),
        "row_count": int(len(frame.index)),
    }


def canonical_data_split_path(
    workspace_root: Path,
    *,
    campaign_id: str,
) -> Path:
    return workspace_path(
        workspace_root,
        "objects",
        "search_control",
        "data_split_manifest.json",
        campaign_id=campaign_id,
    )


def _validate_panel_entry(
    entry: Any,
    *,
    workspace_root: Path,
    expected_role: str,
) -> tuple[list[str], set[str]]:
    reasons: list[str] = []
    dates: set[str] = set()
    if not isinstance(entry, dict):
        return [f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_entry"], dates
    if entry.get("role") != expected_role:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_role")
    for field in (
        "window_id",
        "panel_ref",
        "panel_sha256",
        "observed_start_date",
        "observed_end_date",
        "observed_dates_sha256",
    ):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(
                f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_{field}"
            )
    for field in ("observed_period_count", "row_count"):
        value = entry.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append(
                f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_{field}"
            )
    for field in ("panel_sha256", "observed_dates_sha256"):
        value = entry.get(field)
        if (
            isinstance(value, str)
            and value
            and not SHA256_RE.fullmatch(value.lower())
        ):
            reasons.append(
                f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_{field}"
            )
    path = resolve_workspace_evidence_path(
        workspace_root,
        entry.get("panel_ref"),
    )
    if path is None:
        reasons.append(
            f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_panel_path"
        )
        return reasons, dates
    if not path.is_file():
        reasons.append(
            f"{BLOCK_DATA_SPLIT_INVALID}:{expected_role.lower()}_panel_missing"
        )
        return reasons, dates
    try:
        actual = _panel_contract(path, workspace_root)
        dates = set(_normalized_dates(_load_panel(path)))
    except ValueError as exc:
        reasons.append(str(exc))
        return reasons, dates
    for field, actual_value in actual.items():
        if entry.get(field) != actual_value:
            reasons.append(
                f"{BLOCK_DATA_SPLIT_INVALID}:"
                f"{expected_role.lower()}_{field}_mismatch"
            )
    return reasons, dates


def validate_data_split_manifest(
    manifest: Any,
    *,
    workspace_root: Path,
    expected_campaign_id: str | None = None,
    expected_is_panel_sha256: str | None = None,
    expected_selection_window_id: str | None = None,
    expected_universe_id: str | None = None,
) -> list[str]:
    if not isinstance(manifest, dict):
        return [f"{BLOCK_DATA_SPLIT_INVALID}:missing"]
    reasons: list[str] = []
    if manifest.get("version") != DATA_SPLIT_MANIFEST_VERSION:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:version")
    if manifest.get("immutable") is not True:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:immutable")
    if manifest.get("search_state") != "OPEN":
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:search_not_open")
    campaign_id = manifest.get("campaign_id")
    universe_id = manifest.get("universe_id")
    for field, value, expected in (
        ("campaign_id", campaign_id, expected_campaign_id),
        ("universe_id", universe_id, expected_universe_id),
    ):
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:{field}")
        elif expected is not None and value != expected:
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:{field}_mismatch")

    is_search = manifest.get("is_search")
    is_reasons, is_dates = _validate_panel_entry(
        is_search,
        workspace_root=workspace_root,
        expected_role="IS_SEARCH",
    )
    reasons.extend(is_reasons)
    if isinstance(is_search, dict):
        if is_search.get("release_state") != "SEARCH_OPEN":
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:is_release_state")
        if (
            expected_is_panel_sha256 is not None
            and is_search.get("panel_sha256") != expected_is_panel_sha256
        ):
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:is_panel_hash_mismatch")
        if (
            expected_selection_window_id is not None
            and is_search.get("window_id") != expected_selection_window_id
        ):
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:window_id_mismatch")

    oos_rows = manifest.get("sealed_oos")
    if not isinstance(oos_rows, list) or not oos_rows:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:sealed_oos")
        oos_rows = []
    seen_window_ids: set[str] = set()
    seen_hashes: set[str] = set()
    is_hash = is_search.get("panel_sha256") if isinstance(is_search, dict) else None
    for index, row in enumerate(oos_rows):
        row_reasons, oos_dates = _validate_panel_entry(
            row,
            workspace_root=workspace_root,
            expected_role="OOS_HOLDOUT",
        )
        reasons.extend(row_reasons)
        if not isinstance(row, dict):
            continue
        window_id = row.get("window_id")
        panel_hash = row.get("panel_sha256")
        if window_id in seen_window_ids:
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:oos_window_duplicate")
        elif isinstance(window_id, str):
            seen_window_ids.add(window_id)
        if panel_hash in seen_hashes or panel_hash == is_hash:
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:panel_hash_overlap")
        elif isinstance(panel_hash, str):
            seen_hashes.add(panel_hash)
        if row.get("release_state") not in OOS_RELEASE_STATES:
            reasons.append(
                f"{BLOCK_DATA_SPLIT_INVALID}:"
                f"oos_release_state:{index}"
            )
        if is_dates.intersection(oos_dates):
            reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:date_overlap")
    return list(dict.fromkeys(reasons))


def validate_data_split_reference(
    *,
    workspace_root: Path,
    manifest_ref: Any,
    manifest_sha256: Any,
    expected_campaign_id: str | None = None,
    expected_is_panel_sha256: str | None = None,
    expected_selection_window_id: str | None = None,
    expected_universe_id: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    if manifest_ref != CANONICAL_DATA_SPLIT_REF:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_not_canonical")
    if (
        not isinstance(manifest_sha256, str)
        or not SHA256_RE.fullmatch(manifest_sha256.lower())
    ):
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_hash")
    path = resolve_workspace_evidence_path(workspace_root, manifest_ref)
    if path is None:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_path")
        return reasons
    if not path.is_file():
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_missing")
        return reasons
    if (
        isinstance(manifest_sha256, str)
        and SHA256_RE.fullmatch(manifest_sha256.lower())
        and sha256_file(path) != manifest_sha256
    ):
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_sha256_mismatch")
    try:
        payload = read_json(path)
    except Exception:
        reasons.append(f"{BLOCK_DATA_SPLIT_INVALID}:reference_invalid_json")
        return reasons
    reasons.extend(
        validate_data_split_manifest(
            payload,
            workspace_root=workspace_root,
            expected_campaign_id=expected_campaign_id,
            expected_is_panel_sha256=expected_is_panel_sha256,
            expected_selection_window_id=expected_selection_window_id,
            expected_universe_id=expected_universe_id,
        )
    )
    return list(dict.fromkeys(reasons))


def write_data_split_manifest(
    *,
    campaign_id: str,
    workspace_root: Path,
    is_panel_path: Path,
    is_window_id: str,
    universe_id: str,
    oos_windows: list[dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    root = workspace_root.expanduser().resolve(strict=False)
    is_contract = _panel_contract(is_panel_path, root)
    sealed_oos: list[dict[str, Any]] = []
    for row in oos_windows:
        if not isinstance(row, dict):
            raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:oos_entry")
        path = Path(str(row.get("panel_path") or "")).expanduser()
        contract = _panel_contract(path, root)
        sealed_oos.append(
            {
                "role": "OOS_HOLDOUT",
                "window_id": str(row.get("window_id") or ""),
                "release_state": str(
                    row.get("release_state") or "SEALED_UNRELEASED"
                ),
                **contract,
            }
        )
    payload = {
        "version": DATA_SPLIT_MANIFEST_VERSION,
        "campaign_id": campaign_id,
        "created_at_utc": utc_now(),
        "immutable": True,
        "search_state": "OPEN",
        "universe_id": universe_id,
        "is_search": {
            "role": "IS_SEARCH",
            "window_id": is_window_id,
            "release_state": "SEARCH_OPEN",
            **is_contract,
        },
        "sealed_oos": sealed_oos,
        "policy": {
            "is_oos_hash_disjoint_required": True,
            "is_oos_date_disjoint_required": True,
            "oos_must_remain_unreleased_during_search": True,
        },
    }
    reasons = validate_data_split_manifest(
        payload,
        workspace_root=root,
        expected_campaign_id=campaign_id,
        expected_is_panel_sha256=is_contract["panel_sha256"],
        expected_selection_window_id=is_window_id,
        expected_universe_id=universe_id,
    )
    if reasons:
        raise ValueError(";".join(reasons))
    path = canonical_data_split_path(root, campaign_id=campaign_id)
    if path.is_file():
        existing = read_json(path)
        left = dict(existing) if isinstance(existing, dict) else existing
        right = dict(payload)
        if isinstance(left, dict):
            left.pop("created_at_utc", None)
        right.pop("created_at_utc", None)
        if left != right:
            raise ValueError(f"{BLOCK_DATA_SPLIT_INVALID}:canonical_immutable")
        return path, existing
    write_json(path, payload)
    return path, payload
