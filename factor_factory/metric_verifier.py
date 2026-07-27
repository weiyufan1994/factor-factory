from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)
from factor_factory.research_release import (
    MINIMUM_FORMAL_DAILY_PERIODS,
    observed_panel_dates,
    validate_evaluation_release_chain,
    validate_observed_oos_window,
)


VERIFIER_ID = "factorforge_step4_metric_verifier_v1"
VERIFIER_CONTRACT_VERSION = "factorforge_metric_verifier_report_v1"
VERIFIER_SPEC_VERSION = "factorforge_metric_verifier_spec_v1"
THRESHOLD_REGISTRATION_VERSION = "factorforge_threshold_registration_v1"
SHA256_HEX_LENGTH = 64


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def verifier_source_sha256() -> str:
    return sha256_file(Path(__file__))


def _load_panel(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(
        "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_FORMAT_UNSUPPORTED"
    )


def metric_verifier_identities(
    *,
    workspace_root: Path,
    panel_path: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    panel = panel_path.expanduser().resolve(strict=False)
    if panel != root and root not in panel.parents:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_OUTSIDE_WORKSPACE"
        )
    if not panel.is_file():
        raise ValueError("BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_MISSING")
    window_contract = spec.get("window_contract")
    if not isinstance(window_contract, dict) or not window_contract:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_WINDOW_CONTRACT_MISSING"
        )
    panel_contract = spec.get("panel")
    if not isinstance(panel_contract, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:panel"
        )
    date_column = panel_contract.get("date_column")
    if not isinstance(date_column, str) or not date_column:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:panel.date_column"
        )
    observed = observed_panel_dates(
        _load_panel(panel),
        date_column=date_column,
    )
    return {
        "dataset_snapshot_hash": sha256_file(panel),
        "window_hash": _stable_hash(window_contract),
        **observed,
    }


def _validate_spec(
    spec: dict[str, Any],
    *,
    identities: dict[str, Any],
) -> None:
    if spec.get("version") != VERIFIER_SPEC_VERSION:
        raise ValueError("BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:version")
    for field in ("report_id", "factor_id"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise ValueError(
                f"BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:{field}"
            )
    if spec.get("claim_class") not in {
        "risk_premium",
        "information_rent",
        "liquidity_rent",
        "institutional_constraint_rent",
        "behavioral_rent",
        "time_option_rent",
        "mixed",
        "unknown",
    }:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:claim_class"
        )
    if spec.get("dataset_snapshot_hash") != identities["dataset_snapshot_hash"]:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_DATASET_HASH_MISMATCH"
        )
    if spec.get("window_hash") != identities["window_hash"]:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_WINDOW_HASH_MISMATCH"
        )
    window = spec.get("window_contract")
    if window.get("evaluation_window_role") != "OOS_FINAL":
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_WINDOW_NOT_OOS_FINAL"
        )
    release_hash = window.get("oos_release_token_hash")
    if (
        not isinstance(release_hash, str)
        or len(release_hash) != SHA256_HEX_LENGTH
        or any(char not in "0123456789abcdef" for char in release_hash.lower())
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_OOS_RELEASE_HASH_INVALID"
        )
    panel = spec.get("panel")
    if not isinstance(panel, dict):
        raise ValueError("BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:panel")
    for field in (
        "date_column",
        "asset_column",
        "signal_column",
        "forward_return_column",
    ):
        if not isinstance(panel.get(field), str) or not panel[field].strip():
            raise ValueError(
                f"BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:panel.{field}"
            )
    portfolio = spec.get("portfolio")
    if not isinstance(portfolio, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:portfolio"
        )
    annualization = portfolio.get("annualization_factor")
    long_quantile = portfolio.get("long_quantile")
    cost_bps = portfolio.get("cost_bps_per_turnover")
    other_costs = portfolio.get("other_annual_costs")
    if (
        not isinstance(annualization, int)
        or annualization < 1
        or not isinstance(long_quantile, (int, float))
        or not 0 < float(long_quantile) < 1
        or not isinstance(cost_bps, (int, float))
        or float(cost_bps) < 0
        or not isinstance(other_costs, (int, float))
        or float(other_costs) < 0
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:portfolio_parameters"
        )
    for field in (
        "cost_scope",
        "execution_assumption",
        "rebalance_frequency",
    ):
        if (
            not isinstance(portfolio.get(field), str)
            or not portfolio[field].strip()
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:"
                f"portfolio.{field}"
            )
    window = spec["window_contract"]
    for field in (
        "oos_window",
        "observed_start_date",
        "observed_end_date",
        "forward_return_horizon",
        "signal_timestamp",
        "execution_timestamp",
        "universe_id",
        "investability_mask_id",
        "search_trial_ledger_ref",
        "oos_release_manifest_ref",
    ):
        if not isinstance(window.get(field), str) or not window[field].strip():
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:"
                f"window_contract.{field}"
            )
    if window.get("search_frozen_before_oos_release") is not True:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SEARCH_NOT_FROZEN"
        )
    if window.get("return_convention") != "simple_return":
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_RETURN_CONVENTION_UNSUPPORTED"
        )
    if (
        not isinstance(spec.get("cost_policy_id"), str)
        or not spec["cost_policy_id"].strip()
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SPEC_INVALID:cost_policy_id"
        )
    if window.get("sample_frequency") != "daily":
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SAMPLE_FREQUENCY_UNSUPPORTED"
        )
    validate_observed_oos_window(window, identities)
    if spec.get("claim_class") == "risk_premium":
        controls = panel.get("control_columns")
        if not isinstance(controls, list) or not controls:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_RISK_CONTROLS_MISSING"
            )
        bucket = spec.get("bucket_monotonicity")
        if not isinstance(bucket, dict) or bucket.get("bucket_count") not in {
            5,
            10,
        }:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_SPEC_INVALID"
            )
        if bucket.get("expected_direction") not in {
            "ascending",
            "descending",
        }:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_DIRECTION_INVALID"
            )


def _prepare_panel(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    panel = spec["panel"]
    date_col = panel["date_column"]
    asset_col = panel["asset_column"]
    signal_col = panel["signal_column"]
    return_col = panel["forward_return_column"]
    controls = list(panel.get("control_columns") or [])
    required = [date_col, asset_col, signal_col, return_col, *controls]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_COLUMNS_MISSING:"
            + ",".join(missing)
        )
    work = frame[required].copy()
    parsed_dates = pd.to_datetime(work[date_col], errors="coerce", utc=True)
    if parsed_dates.isna().any():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_DATE_INVALID"
        )
    work[date_col] = parsed_dates.dt.strftime("%Y-%m-%d")
    work[asset_col] = work[asset_col].astype(str)
    for column in [signal_col, return_col, *controls]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.replace([np.inf, -np.inf], np.nan)
    work = work.dropna(subset=required)
    if work.duplicated([date_col, asset_col]).any():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_IDENTITY_DUPLICATE"
        )
    minimum_periods = int(spec["window_contract"]["minimum_periods"])
    if (
        minimum_periods < MINIMUM_FORMAL_DAILY_PERIODS
        or work[date_col].nunique() < minimum_periods
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_PERIODS_INSUFFICIENT"
        )
    bucket_spec = spec.get("bucket_monotonicity")
    bucket_count = (
        int(bucket_spec["bucket_count"])
        if spec.get("claim_class") == "risk_premium"
        and isinstance(bucket_spec, dict)
        and bucket_spec.get("bucket_count") in {5, 10}
        else 0
    )
    minimum_cross_section = max(4, bucket_count, len(controls) + 2)
    if (
        work.groupby(date_col)[asset_col].nunique().min()
        < minimum_cross_section
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_CROSS_SECTION_INSUFFICIENT"
        )
    if (work[return_col] <= -1.0).any():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_SIMPLE_RETURN_RANGE_INVALID"
        )
    return work.sort_values([date_col, asset_col]).reset_index(drop=True)


def _daily_rank_ic(
    frame: pd.DataFrame,
    *,
    date_col: str,
    signal_col: str,
    return_col: str,
) -> pd.Series:
    values: dict[str, float] = {}
    for date, group in frame.groupby(date_col, sort=True):
        if len(group) < 2:
            continue
        signal_rank = group[signal_col].rank(method="average")
        return_rank = group[return_col].rank(method="average")
        value = signal_rank.corr(return_rank)
        if pd.notna(value):
            values[str(date)] = float(value)
    return pd.Series(values, dtype=float)


def _newey_west_tstat(values: np.ndarray, lags: int) -> float | None:
    clean = values[np.isfinite(values)]
    count = len(clean)
    if count < 2:
        return None
    centered = clean - clean.mean()
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, min(lags, count - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        covariance = float(
            np.dot(centered[lag:], centered[:-lag]) / count
        )
        long_run_variance += 2.0 * weight * covariance
    variance_of_mean = max(long_run_variance, 0.0) / count
    if variance_of_mean <= 0:
        return None
    return float(clean.mean() / math.sqrt(variance_of_mean))


def _fama_macbeth(
    frame: pd.DataFrame,
    *,
    date_col: str,
    signal_col: str,
    return_col: str,
    controls: list[str],
    lags: int,
) -> tuple[float, float, int]:
    lambdas: list[float] = []
    regression_columns = [signal_col, *controls]
    for date, group in frame.groupby(date_col, sort=True):
        clean = group[[return_col, *regression_columns]].dropna()
        if len(clean) <= len(regression_columns) + 1:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_FAMA_MACBETH_CROSS_SECTION_INSUFFICIENT:"
                f"{date}"
            )
        x = clean[regression_columns].to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(x)), x])
        y = clean[return_col].to_numpy(dtype=float)
        beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
        if rank != x.shape[1]:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_FAMA_MACBETH_RANK_DEFICIENT:"
                f"{date}"
            )
        lambdas.append(float(beta[1]))
    if len(lambdas) < 2:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_FAMA_MACBETH_PERIODS_INSUFFICIENT"
        )
    values = np.asarray(lambdas, dtype=float)
    tstat = _newey_west_tstat(values, lags)
    if tstat is None:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_FAMA_MACBETH_VARIANCE_INVALID"
        )
    return float(values.mean()), tstat, len(values)


def _bucket_returns(
    frame: pd.DataFrame,
    *,
    date_col: str,
    signal_col: str,
    return_col: str,
    bucket_count: int,
) -> list[float]:
    daily: list[list[float]] = [[] for _ in range(bucket_count)]
    for date, group in frame.groupby(date_col, sort=True):
        if len(group) < bucket_count:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_CROSS_SECTION_INSUFFICIENT:"
                f"{date}"
            )
        try:
            bucket_series = pd.qcut(
                group[signal_col],
                q=bucket_count,
                labels=False,
                duplicates="drop",
            )
        except ValueError as exc:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_TIES_UNRESOLVED:"
                f"{date}"
            ) from exc
        if (
            bucket_series.isna().any()
            or int(bucket_series.nunique()) != bucket_count
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_TIES_UNRESOLVED:"
                f"{date}"
            )
        buckets = bucket_series.to_numpy(dtype=int)
        returns = group[return_col].to_numpy(dtype=float)
        for bucket in range(bucket_count):
            selected = returns[buckets == bucket]
            if len(selected):
                daily[bucket].append(float(selected.mean()))
    if any(not values for values in daily):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_COVERAGE_INSUFFICIENT"
        )
    return [float(np.mean(values)) for values in daily]


def _long_only_series(
    frame: pd.DataFrame,
    *,
    date_col: str,
    asset_col: str,
    signal_col: str,
    return_col: str,
    long_quantile: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    previous_post_return_weights: dict[str, float] = {}
    for date, group in frame.groupby(date_col, sort=True):
        if len(group) < 2:
            continue
        threshold = group[signal_col].quantile(1.0 - long_quantile)
        selected = group[group[signal_col] >= threshold]
        if selected.empty:
            continue
        weight = 1.0 / len(selected)
        weights = {
            str(asset): weight for asset in selected[asset_col].astype(str)
        }
        gross_return = float(selected[return_col].mean())
        turnover = (
            1.0
            if not previous_post_return_weights
            else 0.5
            * sum(
                abs(
                    weights.get(asset, 0.0)
                    - previous_post_return_weights.get(asset, 0.0)
                )
                for asset in set(weights).union(previous_post_return_weights)
            )
        )
        rows.append(
            {
                "trade_date": str(date),
                "gross_return": gross_return,
                "turnover": float(turnover),
            }
        )
        selected_returns = {
            str(row[asset_col]): float(row[return_col])
            for _, row in selected[[asset_col, return_col]].iterrows()
        }
        end_nav = 1.0 + gross_return
        if end_nav <= 0:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_LONG_END_NAV_NONPOSITIVE"
            )
        previous_post_return_weights = {
            asset: weight * (1.0 + selected_returns[asset]) / end_nav
            for asset, weight in weights.items()
        }
    if len(rows) < 2:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_LONG_END_PERIODS_INSUFFICIENT"
        )
    return pd.DataFrame(rows)


def _drawdown_geometry(net_returns: pd.Series) -> tuple[float, int, float]:
    compounded = (1.0 + net_returns.reset_index(drop=True)).cumprod()
    nav = pd.concat(
        [pd.Series([1.0], dtype=float), compounded],
        ignore_index=True,
    )
    running_peak = nav.cummax()
    drawdown = nav / running_peak - 1.0
    trough_position = int(np.argmin(drawdown.to_numpy()))
    max_drawdown = float(drawdown.iloc[trough_position])
    peak_value = float(running_peak.iloc[trough_position])
    peak_candidates = np.flatnonzero(
        np.isclose(nav.iloc[: trough_position + 1].to_numpy(), peak_value)
    )
    peak_position = int(peak_candidates[-1]) if len(peak_candidates) else 0
    recovery_position = len(nav) - 1
    for position in range(trough_position + 1, len(nav)):
        if float(nav.iloc[position]) >= peak_value:
            recovery_position = position
            break
    recovery_days = max(0, recovery_position - peak_position)
    path = nav.iloc[peak_position : recovery_position + 1]
    recovery_area = float(((peak_value - path).clip(lower=0) / peak_value).sum())
    return max_drawdown, recovery_days, recovery_area


def _build_metrics(
    frame: pd.DataFrame,
    spec: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    panel = spec["panel"]
    portfolio = spec["portfolio"]
    date_col = panel["date_column"]
    asset_col = panel["asset_column"]
    signal_col = panel["signal_column"]
    return_col = panel["forward_return_column"]
    controls = list(panel.get("control_columns") or [])
    annualization = int(portfolio["annualization_factor"])
    long_quantile = float(portfolio["long_quantile"])
    cost_bps = float(portfolio["cost_bps_per_turnover"])
    other_annual_costs = float(portfolio["other_annual_costs"])

    ic_series = _daily_rank_ic(
        frame,
        date_col=date_col,
        signal_col=signal_col,
        return_col=return_col,
    )
    if len(ic_series) < 2:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_IC_PERIODS_INSUFFICIENT"
        )
    if len(ic_series) != frame[date_col].nunique():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_IC_SAMPLE_MISMATCH"
        )
    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std(ddof=0))
    if ic_std <= 0:
        raise ValueError("BLOCK_FACTORFORGE_METRIC_VERIFIER_IC_STD_INVALID")
    icir_value = ic_mean / ic_std

    long_series = _long_only_series(
        frame,
        date_col=date_col,
        asset_col=asset_col,
        signal_col=signal_col,
        return_col=return_col,
        long_quantile=long_quantile,
    )
    daily_other_cost = other_annual_costs / annualization
    long_series["cost"] = (
        long_series["turnover"] * cost_bps / 10000.0 + daily_other_cost
    )
    long_series["net_return"] = (
        long_series["gross_return"] - long_series["cost"]
    )
    if (long_series["net_return"] <= -1.0).any():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_NET_RETURN_BELOW_MINUS_ONE"
        )
    gross_return_annual = float(long_series["gross_return"].mean() * annualization)
    annual_turnover = float(long_series["turnover"].mean() * annualization)
    modeled_cost_annual = annual_turnover * cost_bps / 10000.0 + other_annual_costs
    net_return_annual = gross_return_annual - modeled_cost_annual
    geometric_return_annual = float(
        (1.0 + long_series["net_return"]).prod()
        ** (annualization / len(long_series))
        - 1.0
    )
    net_wealth = (1.0 + long_series["net_return"]).cumprod()
    terminal_wealth = float(net_wealth.iloc[-1])
    minimum_wealth = float(
        min(1.0, float(net_wealth.min()))
    )
    arithmetic_growth_benchmark_annual = float(
        (1.0 + long_series["net_return"].mean()) ** annualization - 1.0
    )
    realized_volatility_annual = float(
        long_series["net_return"].std(ddof=0) * math.sqrt(annualization)
    )
    realized_volatility_drag = (
        arithmetic_growth_benchmark_annual - geometric_return_annual
    )
    half_variance_benchmark = 0.5 * realized_volatility_annual**2
    net_std = float(long_series["net_return"].std(ddof=0))
    sharpe_net = (
        float(long_series["net_return"].mean() / net_std * math.sqrt(annualization))
        if net_std > 0
        else 0.0
    )
    max_drawdown, recovery_days, recovery_area = _drawdown_geometry(
        long_series["net_return"]
    )
    metrics: dict[str, dict[str, Any]] = {
        "ic": {
            "method": "rank_ic",
            "mean": ic_mean,
            "std": ic_std,
            "std_definition": "population_std_over_daily_rank_ic",
            "period_count": int(len(ic_series)),
            "horizon": str(spec["window_contract"]["forward_return_horizon"]),
            "evidence_role": "promotion_gate_evidence",
        },
        "icir": {
            "value": icir_value,
            "annualized": False,
            "annualization_factor": annualization,
            "reconciliation_tolerance": 1e-10,
            "evidence_role": "promotion_gate_evidence",
        },
        "volatility_cost": {
            "arithmetic_return_annual": arithmetic_growth_benchmark_annual,
            "geometric_return_annual": geometric_return_annual,
            "realized_volatility_drag": realized_volatility_drag,
            "realized_volatility_annual": realized_volatility_annual,
            "half_variance_benchmark": half_variance_benchmark,
            "return_compounding_convention": (
                "constant daily arithmetic-mean growth benchmark versus actual "
                f"daily geometric compounding, annualized by {annualization}"
            ),
            "reconciliation_tolerance": 1e-10,
        },
        "transaction_cost": {
            "gross_return_annual": gross_return_annual,
            "net_return_annual": net_return_annual,
            "annual_turnover": annual_turnover,
            "cost_bps_per_turnover": cost_bps,
            "other_annual_costs": other_annual_costs,
            "modeled_cost_annual": modeled_cost_annual,
            "turnover_definition": (
                "one-way 0.5 * sum absolute target weight minus drifted "
                "pretrade weight; initial portfolio establishment equals 1.0"
            ),
            "cost_scope": str(portfolio["cost_scope"]),
            "execution_assumption": str(portfolio["execution_assumption"]),
            "reconciliation_tolerance": 1e-10,
            "annual_return_convention": "arithmetic_mean_times_annualization",
        },
        "drawdown": {
            "max_drawdown": max_drawdown,
            "recovery_days": recovery_days,
            "recovery_area": recovery_area,
            "nav_definition": (
                "cumulative long-only net-of-cost NAV from verified forward returns"
            ),
        },
        "long_end": {
            "gross_return_annual": gross_return_annual,
            "net_return_annual": net_return_annual,
            "net_geometric_return_annual": geometric_return_annual,
            "terminal_wealth": terminal_wealth,
            "minimum_wealth": minimum_wealth,
            "sharpe_net": sharpe_net,
            "coverage": float(
                len(long_series) / frame[date_col].nunique()
            ),
            "selection_rule": (
                f"top {long_quantile:.6g} fraction by signal within each date"
            ),
            "weighting": "equal_weight",
            "rebalance_frequency": str(portfolio["rebalance_frequency"]),
            "annual_return_convention": (
                "net_daily_simple_returns_geometrically_compounded"
            ),
            "short_leg_used_for_acceptance": False,
            "evidence_role": "promotion_gate_evidence",
        },
    }
    bucket_spec = spec.get("bucket_monotonicity")
    if isinstance(bucket_spec, dict) and bucket_spec.get("bucket_count") in {
        5,
        10,
    }:
        bucket_count = int(bucket_spec["bucket_count"])
        expected_direction = str(bucket_spec["expected_direction"])
        bucket_returns = _bucket_returns(
            frame,
            date_col=date_col,
            signal_col=signal_col,
            return_col=return_col,
            bucket_count=bucket_count,
        )
        pairs_violated = sum(
            1
            for left, right in zip(bucket_returns, bucket_returns[1:])
            if (
                expected_direction == "ascending"
                and right < left
            )
            or (
                expected_direction == "descending"
                and right > left
            )
        )
        pairs_total = bucket_count - 1
        risk_required = spec["claim_class"] == "risk_premium"
        metrics["bucket_monotonicity"] = {
            "bucket_count": bucket_count,
            "required_for_acceptance": risk_required,
            "evidence_role": (
                "promotion_gate_evidence"
                if risk_required
                else "diagnostic_evidence"
            ),
            "monotonicity_score": (
                pairs_total - pairs_violated
            )
            / pairs_total,
            "adjacent_pairs_total": pairs_total,
            "adjacent_pairs_violated": pairs_violated,
            "expected_direction": expected_direction,
            "bucket_returns": bucket_returns,
            "period_count": int(frame[date_col].nunique()),
        }
    if spec["claim_class"] == "risk_premium":
        fmb_spec = spec.get("fama_macbeth")
        fmb_spec = fmb_spec if isinstance(fmb_spec, dict) else {}
        lags = int(fmb_spec.get("newey_west_lags") or 0)
        lambda_mean, lambda_tstat, period_count = _fama_macbeth(
            frame,
            date_col=date_col,
            signal_col=signal_col,
            return_col=return_col,
            controls=controls,
            lags=lags,
        )
        metrics["fama_macbeth"] = {
            "applicable": True,
            "lambda_mean": lambda_mean,
            "lambda_tstat": lambda_tstat,
            "period_count": period_count,
            "newey_west_lags": lags,
            "cross_sectional_regression": (
                f"{return_col} ~ {signal_col} + " + " + ".join(controls)
            ),
            "exposure_timing": str(
                spec["window_contract"]["signal_timestamp"]
            ),
            "return_horizon": str(
                spec["window_contract"]["forward_return_horizon"]
            ),
            "controls": controls,
            "required_for_acceptance": True,
            "evidence_role": "promotion_gate_evidence",
        }
    return metrics


def _load_threshold_registration(
    *,
    workspace_root: Path,
    raw_path: Any,
    spec: dict[str, Any],
    identities: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    path = resolve_workspace_evidence_path(workspace_root, raw_path)
    if path is None or not path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_THRESHOLD_REGISTRATION_MISSING"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "version": THRESHOLD_REGISTRATION_VERSION,
        "registration_status": "LOCKED",
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "claim_class": spec["claim_class"],
        "window_hash": identities["window_hash"],
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_THRESHOLD_IDENTITY_MISMATCH:"
                f"{field}"
            )
    rules = payload.get("decision_rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_THRESHOLD_RULES_MISSING"
        )
    if payload.get("rule_set_sha256") != _stable_hash(rules):
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_THRESHOLD_RULE_HASH_MISMATCH"
        )
    if payload.get("registered_before_evaluation") is not True:
        raise ValueError(
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_THRESHOLDS_POST_HOC"
        )
    return path, payload


def run_metric_verifier(
    *,
    workspace_root: Path,
    panel_path: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    resolved_panel = panel_path.expanduser().resolve(strict=False)
    identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=resolved_panel,
        spec=spec,
    )
    _validate_spec(spec, identities=identities)
    threshold_path, threshold_payload = _load_threshold_registration(
        workspace_root=root,
        raw_path=spec.get("threshold_registration_ref"),
        spec=spec,
        identities=identities,
    )
    release_chain = validate_evaluation_release_chain(
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
        threshold_payload=threshold_payload,
    )
    frame = _prepare_panel(_load_panel(resolved_panel), spec)
    metrics = _build_metrics(frame, spec)
    threshold_sha256 = sha256_file(threshold_path)
    rule_set_sha256 = str(threshold_payload["rule_set_sha256"])
    source_sha256 = verifier_source_sha256()
    required_metrics = {
        "ic",
        "icir",
        "volatility_cost",
        "transaction_cost",
        "drawdown",
        "long_end",
    }
    if spec["claim_class"] == "risk_premium":
        required_metrics.update({"fama_macbeth", "bucket_monotonicity"})
    evidence_bindings: dict[str, dict[str, Any]] = {}
    output_root = (
        root
        / "objects"
        / "evidence"
        / "factor_proof"
        / str(spec["report_id"])
    )
    output_root.mkdir(parents=True, exist_ok=True)
    for metric_name in sorted(required_metrics):
        metric_payload = metrics.get(metric_name)
        if not isinstance(metric_payload, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_METRIC_VERIFIER_REQUIRED_METRIC_MISSING:"
                f"{metric_name}"
            )
        evidence = {
            "verifier_contract_version": VERIFIER_CONTRACT_VERSION,
            "verifier_id": VERIFIER_ID,
            "verifier_source_sha256": source_sha256,
            "verifier_status": "PASS",
            "metric": metric_name,
            "metric_payload": metric_payload,
            "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
            "window_hash": identities["window_hash"],
            "threshold_registration_sha256": threshold_sha256,
            "threshold_rule_set_sha256": rule_set_sha256,
            "source_panel_ref": str(resolved_panel.relative_to(root)),
            "source_panel_sha256": identities["dataset_snapshot_hash"],
            "source_row_count": int(len(frame)),
            "verifier_spec": spec,
            "evaluation_release_chain": release_chain,
        }
        evidence_path = output_root / f"{metric_name}.json"
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_bindings[metric_name] = {
            "path": str(evidence_path.relative_to(root)),
            "metric": metric_name,
            "sha256": sha256_file(evidence_path),
            "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
            "window_hash": identities["window_hash"],
            "threshold_registration_sha256": threshold_sha256,
            "threshold_rule_set_sha256": rule_set_sha256,
            "verifier_id": VERIFIER_ID,
            "verifier_source_sha256": source_sha256,
            "verifier_status": "PASS",
        }
    bundle = {
        "version": "factorforge_metric_verifier_bundle_v1",
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "claim_class": spec["claim_class"],
        "verifier_id": VERIFIER_ID,
        "verifier_source_sha256": source_sha256,
        "verifier_status": "PASS",
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "threshold_registration_ref": str(threshold_path.relative_to(root)),
        "threshold_registration_sha256": threshold_sha256,
        "threshold_rule_set_sha256": rule_set_sha256,
        "evaluation_release_chain": release_chain,
        "metrics": metrics,
        "evidence_bindings": evidence_bindings,
        "source_row_count": int(len(frame)),
        "source_panel_ref": str(resolved_panel.relative_to(root)),
        "source_panel_sha256": identities["dataset_snapshot_hash"],
        "verifier_spec": spec,
    }
    bundle_path = (
        root
        / "objects"
        / "research_protocol"
        / f"metric_verifier_bundle__{spec['report_id']}.json"
    )
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def validate_metric_verifier_report(
    report: dict[str, Any],
    *,
    workspace_root: Path,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(report, dict):
        return ["BLOCK_FACTORFORGE_METRIC_EVIDENCE_REPORT_INVALID"]
    if report.get("verifier_contract_version") != VERIFIER_CONTRACT_VERSION:
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_CONTRACT_INVALID")
    if report.get("verifier_id") != VERIFIER_ID:
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_VERIFIER_ID_INVALID")
    if report.get("verifier_source_sha256") != verifier_source_sha256():
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_SOURCE_HASH_MISMATCH")
    metric_name = report.get("metric")
    if not isinstance(metric_name, str) or not metric_name:
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_METRIC_MISSING")
        return reasons
    spec = report.get("verifier_spec")
    if not isinstance(spec, dict):
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_SPEC_MISSING")
        return reasons
    root = workspace_root.expanduser().resolve(strict=False)
    panel_path = resolve_workspace_evidence_path(root, report.get("source_panel_ref"))
    if panel_path is None or not panel_path.is_file():
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_PANEL_MISSING")
        return reasons
    try:
        identities = metric_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
        _validate_spec(spec, identities=identities)
        threshold_path, threshold_payload = _load_threshold_registration(
            workspace_root=root,
            raw_path=spec.get("threshold_registration_ref"),
            spec=spec,
            identities=identities,
        )
        release_chain = validate_evaluation_release_chain(
            workspace_root=root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
            threshold_payload=threshold_payload,
        )
        frame = _prepare_panel(_load_panel(panel_path), spec)
        metrics = _build_metrics(frame, spec)
    except Exception as exc:
        reasons.append(f"BLOCK_FACTORFORGE_METRIC_EVIDENCE_REPLAY_FAILED:{exc}")
        return reasons
    if metric_name not in metrics:
        reasons.append("BLOCK_FACTORFORGE_METRIC_EVIDENCE_METRIC_UNSUPPORTED")
        return reasons
    expected = {
        "verifier_status": "PASS",
        "metric_payload": metrics[metric_name],
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "threshold_registration_sha256": sha256_file(threshold_path),
        "threshold_rule_set_sha256": threshold_payload.get("rule_set_sha256"),
        "source_panel_sha256": identities["dataset_snapshot_hash"],
        "source_row_count": int(len(frame)),
        "evaluation_release_chain": release_chain,
    }
    for field, value in expected.items():
        if report.get(field) != value:
            reasons.append(
                f"BLOCK_FACTORFORGE_METRIC_EVIDENCE_REPLAY_MISMATCH:{field}"
            )
    return reasons
