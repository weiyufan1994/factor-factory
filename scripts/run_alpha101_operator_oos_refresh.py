#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.artifact_identity import stable_hash  # noqa: E402
from factor_factory.data_api.client import default_catalog_path  # noqa: E402
from factor_factory.data_api import fetch_data_api_dataset  # noqa: E402
from factor_factory.formula.evaluator import evaluate_formula_frame  # noqa: E402
from factor_factory.formula.parser import parse_formula, resolve_formula_fields_for_schema  # noqa: E402


WINDOW_OPERATORS = {
    "sum",
    "mean",
    "min",
    "max",
    "argmin",
    "argmax",
    "std",
    "stddev",
    "delta",
    "delay",
    "ts_rank",
    "decay_linear",
}
PAIR_WINDOW_OPERATORS = {"correlation", "corr", "covariance", "cov"}
FORBIDDEN_LABEL_COLUMN_TOKENS = (
    "future_return",
    "next_return",
    "target_return",
    "future_",
    "lookahead",
)
FORBIDDEN_LABEL_COLUMN_EXACT = {"label", "target"}
SOURCE_FIELD_ALIASES = {
    "volume": ["vol"],
    "vol": ["vol"],
    "returns": ["pct_chg"],
    "return": ["pct_chg"],
    "ret": ["pct_chg"],
    "turnover": ["turnover_rate"],
    "vwap": ["amount", "vol"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh OOS factor values for a generic Alpha101 Formula-IR operator factor without overwriting parent IS artifacts."
    )
    parser.add_argument("--contract", type=Path, help="Optional OOS refresh contract JSON.")
    parser.add_argument("--workspace", type=Path, help="Factor workspace root.")
    parser.add_argument("--source-report-id", help="Parent/source report id.")
    parser.add_argument("--factor-id", help="Factor id, e.g. Alpha015.")
    parser.add_argument("--formula", help="Formula text to preserve.")
    parser.add_argument("--target-start", default="20250714")
    parser.add_argument("--target-end", default="20260612")
    parser.add_argument("--dataset-id", default="clean_daily_bar_oos_slice")
    parser.add_argument("--catalog-path")
    parser.add_argument("--universe", default="a_share_all")
    parser.add_argument("--history-start", help="Optional explicit formula lookback fetch start.")
    parser.add_argument("--expected-formula-hash", help="Optional parent/source formula hash that must match after schema resolution.")
    parser.add_argument("--engine", default="optimized", choices=["optimized", "reference"])
    return parser.parse_args()


def read_contract(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def parse_universe(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text or text == "a_share_all":
        return "a_share_all"
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return text


def normalize_date(value: str | int | None) -> str:
    if value is None:
        raise SystemExit("BLOCK_OOS_REFRESH_DATE_MISSING")
    return str(value).replace("-", "")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def const_int(node: dict[str, Any] | None) -> int | None:
    if not isinstance(node, dict) or node.get("type") != "constant":
        return None
    value = node.get("value")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return int(value)
    return None


def max_formula_lookback_node(node: dict[str, Any] | None) -> int:
    if not isinstance(node, dict):
        return 0
    if node.get("type") != "operator":
        return 0
    op = str(node.get("operator") or "").lower()
    args = [arg for arg in (node.get("args") or []) if isinstance(arg, dict)]
    child_lookback = max([max_formula_lookback_node(arg) for arg in args] or [0])
    if op in WINDOW_OPERATORS and len(args) >= 2:
        window = const_int(args[1])
        if window is not None and window > 0:
            return child_lookback + max(window - 1, 0)
    if op in PAIR_WINDOW_OPERATORS and len(args) >= 3:
        window = const_int(args[2])
        if window is not None and window > 0:
            return child_lookback + max(window - 1, 0)
    return child_lookback


def max_formula_lookback(formula_ir: dict[str, Any]) -> int:
    return max_formula_lookback_node(formula_ir.get("root") if isinstance(formula_ir, dict) else None)


def conservative_history_start(target_start: str, lookback: int) -> str:
    timestamp = pd.Timestamp(str(target_start))
    # Calendar-day buffer intentionally overestimates trading-day lookback.
    buffer_days = max(10, int(math.ceil(lookback * 3.0)) + 10)
    return (timestamp - pd.Timedelta(days=buffer_days)).strftime("%Y%m%d")


def stable_universe_hash(frame: pd.DataFrame) -> str:
    if frame.empty or "ts_code" not in frame.columns:
        return stable_hash({"universe": []})
    return stable_hash({"universe": sorted(frame["ts_code"].astype(str).dropna().unique().tolist())})


def forbidden_label_columns(columns: list[str] | pd.Index) -> list[str]:
    forbidden: list[str] = []
    for column in columns:
        text = str(column).strip().lower()
        if text in FORBIDDEN_LABEL_COLUMN_EXACT or any(token in text for token in FORBIDDEN_LABEL_COLUMN_TOKENS):
            forbidden.append(str(column))
    return forbidden


def source_fields_for_formula_field(field: str) -> list[str]:
    key = str(field).strip().lower()
    if re.fullmatch(r"adv[1-9][0-9]*", key):
        return ["vol"]
    return list(SOURCE_FIELD_ALIASES.get(key, [field]))


def resolve_catalog_path(raw: str | Path | None) -> str | None:
    if raw is None or str(raw).strip() == "":
        default = default_catalog_path()
        return str(default) if default is not None else None
    path = Path(raw).expanduser()
    if path.exists():
        return str(path)
    if str(raw) == "data/catalog/data_catalog.json":
        default = default_catalog_path()
        return str(default) if default is not None else str(path)
    return str(path)


def main() -> int:
    args = parse_args()
    contract = read_contract(args.contract)
    source_report_id = coalesce(args.source_report_id, contract.get("source_report_id"), contract.get("report_id"))
    factor_id = coalesce(args.factor_id, contract.get("factor_id"))
    formula = coalesce(args.formula, contract.get("formula"), contract.get("formula_text"))
    workspace = Path(coalesce(args.workspace, contract.get("workspace") or ".")).expanduser()
    if not source_report_id or not factor_id or not formula:
        raise SystemExit("BLOCK_OOS_REFRESH_CONTRACT_INCOMPLETE")
    target_start = normalize_date(coalesce(args.target_start, (contract.get("window") or {}).get("start")))
    target_end = normalize_date(coalesce(args.target_end, (contract.get("window") or {}).get("end")))
    dataset_id = str(coalesce(args.dataset_id, contract.get("dataset_id"), "clean_daily_bar_oos_slice"))
    if dataset_id != "clean_daily_bar_oos_slice":
        raise SystemExit(f"BLOCK_OOS_REFRESH_UNSUPPORTED_DATASET:{dataset_id}")
    universe = parse_universe(coalesce(args.universe, contract.get("universe"), "a_share_all"))
    catalog_path = resolve_catalog_path(coalesce(args.catalog_path, contract.get("catalog_path")))
    step4_identity = contract.get("step4_formal_factor_identity") if isinstance(contract.get("step4_formal_factor_identity"), dict) else {}
    expected_formula_hash = coalesce(
        args.expected_formula_hash,
        contract.get("expected_formula_hash"),
        contract.get("formula_hash") if contract.get("formula_hash_must_match_parent") is True else None,
        step4_identity.get("formula_hash"),
    )

    # Parse against catalog/read schema after fetching. Start with no schema to obtain required fields.
    provisional_ir = parse_formula(str(formula), raise_on_error=True)
    formula_source_fields: list[str] = []
    for field in provisional_ir.get("resolved_fields", {}).values():
        formula_source_fields.extend(source_fields_for_formula_field(str(field)))
    requested_fields = list(
        dict.fromkeys(
            [
                "open",
                "high",
                "low",
                "close",
                "vol",
                "amount",
                "pct_chg",
                "turnover_rate",
                *[str(field) for field in formula_source_fields if field],
            ]
        )
    )
    lookback = max_formula_lookback(provisional_ir)
    history_start = normalize_date(args.history_start or contract.get("history_start") or conservative_history_start(target_start, lookback))
    started = time.perf_counter()
    result = fetch_data_api_dataset(
        dataset_id,
        start=history_start,
        end=target_end,
        fields=requested_fields,
        universe=universe,
        frequency="daily",
        catalog_path=catalog_path,
    )
    if result.status not in {"ready", "proxy_ready"}:
        raise SystemExit(f"BLOCK_OOS_REFRESH_DATA_NOT_READY:{result.status}:{result.blocked_reason}")
    frame = result.frame.copy()
    if frame.empty:
        raise SystemExit("BLOCK_OOS_REFRESH_EMPTY_INPUT")
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False)
    frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    formula_ir = resolve_formula_fields_for_schema(parse_formula(str(formula), list(frame.columns), raise_on_error=True), list(frame.columns))
    formula_hash = formula_ir.get("formula_hash")
    if expected_formula_hash and formula_hash != str(expected_formula_hash):
        raise SystemExit(
            "BLOCK_OOS_REFRESH_FORMULA_HASH_MISMATCH:"
            f"expected={expected_formula_hash}:observed={formula_hash}"
        )
    evaluated, eval_profile = evaluate_formula_frame(formula_ir, frame, engine=args.engine, return_profile=True)
    evaluated["trade_date"] = evaluated["trade_date"].astype(str).str.replace("-", "", regex=False)
    oos_values = evaluated[(evaluated["trade_date"] >= target_start) & (evaluated["trade_date"] <= target_end)].copy()
    if oos_values.empty:
        raise SystemExit("BLOCK_OOS_REFRESH_EMPTY_TARGET_WINDOW")
    forbidden_columns = forbidden_label_columns(oos_values.columns)
    if forbidden_columns:
        raise SystemExit(f"BLOCK_OOS_REFRESH_FORBIDDEN_LABEL_COLUMNS:{','.join(forbidden_columns)}")
    duplicate_key_count = int(oos_values.duplicated(["ts_code", "trade_date"]).sum())
    if duplicate_key_count:
        raise SystemExit(f"BLOCK_OOS_REFRESH_FACTOR_VALUES_DUPLICATE_KEYS:{duplicate_key_count}")

    window_id = f"{target_start}_{target_end}"
    out_dir = workspace / "runs" / str(source_report_id) / "oos_refresh" / window_id
    out_dir.mkdir(parents=True, exist_ok=True)
    factor_path = out_dir / f"factor_values__{source_report_id}__oos_{window_id}.parquet"
    metadata_path = out_dir / f"run_metadata__{source_report_id}__oos_{window_id}.json"
    compatibility_path = out_dir / f"factor_library_append_compatibility__{source_report_id}__oos_{window_id}.json"
    oos_values.to_parquet(factor_path, index=False)
    non_null = int(oos_values["factor_value"].notna().sum())
    row_count = int(len(oos_values))
    identity = {
        "producer": "step4_oos_refresh_formal_compute",
        "refresh_mode": "generic_operator_oos_factor_values",
        "is_formal_factor_values": True,
        "source_report_id": source_report_id,
        "report_id": source_report_id,
        "factor_id": factor_id,
        "implementation_mode": "operator",
        "formula_hash": formula_hash,
        "window": {"scope": "oos_holdout_factor_values_only", "start": target_start, "end": target_end},
        "dataset_id": dataset_id,
        "history_start": history_start,
        "universe_hash": stable_universe_hash(oos_values),
        "universe_request": universe,
        "frequency": "daily",
    }
    metadata = {
        "version": "factorforge_alpha101_operator_oos_refresh_v1",
        "status": "success",
        "source_report_id": source_report_id,
        "factor_id": factor_id,
        "formula": formula,
        "formula_ir": formula_ir,
        "formula_hash_preserved": True,
        "expected_formula_hash": expected_formula_hash,
        "formula_hash_matches_expected": (formula_hash == str(expected_formula_hash)) if expected_formula_hash else None,
        "refresh_policy": {
            "window_scope": "oos_holdout_factor_values_only",
            "revision_fitting_allowed": False,
            "manual_is_oos_splice_allowed": False,
            "same_report_id_parent_factor_parquet_overwrite": False,
        },
        "input_data": {
            "dataset_id": dataset_id,
            "history_start": history_start,
            "target_start": target_start,
            "target_end": target_end,
            "status": result.status,
            "row_count": int(len(frame)),
            "date_count": int(frame["trade_date"].nunique()),
            "ticker_count": int(frame["ts_code"].nunique()),
            "metadata": result.to_metadata(),
            "catalog_path": catalog_path,
        },
        "lookback": {
            "formula_max_lookback": lookback,
            "history_start": history_start,
        },
        "output": {
            "factor_values_path": str(factor_path),
            "metadata_path": str(metadata_path),
            "row_count": row_count,
            "date_count": int(oos_values["trade_date"].nunique()),
            "ticker_count": int(oos_values["ts_code"].nunique()),
            "factor_non_null": non_null,
            "factor_non_null_coverage": float(non_null / row_count) if row_count else 0.0,
            "duplicate_key_count": duplicate_key_count,
            "sha256": sha256_file(factor_path),
        },
        "step4_formal_factor_identity": identity,
        "evaluation_profile": eval_profile,
        "wall_seconds": time.perf_counter() - started,
    }
    compatibility = {
        "version": "factorforge_factor_library_append_compatibility_v1",
        "verdict": "ACCEPT",
        "source_report_id": source_report_id,
        "factor_version": source_report_id,
        "factor_values_path": str(factor_path),
        "factor_values_hash": metadata["output"]["sha256"],
        "window": identity["window"],
        "duplicate_key_count": duplicate_key_count,
        "contains_future_return_label": bool(forbidden_columns),
        "contains_forbidden_label_columns": bool(forbidden_columns),
        "forbidden_label_columns": forbidden_columns,
        "appendable_to_factor_library_exposure_panel": True,
        "required_join_keys": ["ts_code", "trade_date"],
        "formula_hash": formula_hash,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    compatibility_path.write_text(json.dumps(compatibility, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "verdict": "ACCEPT",
        "factor_values_path": str(factor_path),
        "metadata_path": str(metadata_path),
        "compatibility_path": str(compatibility_path),
        "row_count": row_count,
        "date_count": metadata["output"]["date_count"],
        "ticker_count": metadata["output"]["ticker_count"],
        "non_null_coverage": metadata["output"]["factor_non_null_coverage"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
