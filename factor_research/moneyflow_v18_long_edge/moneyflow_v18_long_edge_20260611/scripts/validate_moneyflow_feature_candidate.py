#!/usr/bin/env python3
"""Research-side feature validation for moneyflow V15/V18 candidates.

This is not a formal Factor Forge production step. It reads delivered
datamarts, computes candidate factor values, and checks whether the signal
survives simple size/liquidity residualization as a model feature.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_moneyflow_v11_datamart_eval import (
    MOMENT_LAWS,
    add_forward_returns,
    add_index_universes,
    add_universes,
    clean_date,
    compute_law,
    dataframe_to_markdown,
    load_daily_clean,
    load_daily_controls,
    read_partitioned,
)


DEFAULT_LAWS = [
    "miller_flow_v15_repair_confirmed_absorption_fp_v1",
    "miller_flow_v18a_absolute_long_edge_gate_v1",
    "miller_flow_v18b_first_passage_repair_edge_v1",
]

LAW_LABELS = {
    "miller_flow_v15_repair_confirmed_absorption_fp_v1": "V15",
    "miller_flow_v18a_absolute_long_edge_gate_v1": "V18a",
    "miller_flow_v18b_first_passage_repair_edge_v1": "V18b",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moments-root", type=Path, required=True)
    parser.add_argument("--daily-basic-root", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, required=True)
    parser.add_argument("--index-universe-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--cutoff-time", default="14:50")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--laws", default=",".join(DEFAULT_LAWS))
    parser.add_argument(
        "--universes",
        default="full,middle_10_80,fixed_small_10,fixed_small_20,smallest_20,csi800,csi800_csi1000",
    )
    parser.add_argument("--max-dates", type=int, default=None)
    return parser.parse_args()


def zscore_by_date(frame: pd.DataFrame, col: str) -> pd.Series:
    values = pd.to_numeric(frame[col], errors="coerce")
    mean = values.groupby(frame["trade_date"], sort=False).transform("mean")
    std = values.groupby(frame["trade_date"], sort=False).transform("std").replace(0.0, np.nan)
    return (values - mean) / std


def robust_log(value: pd.Series) -> pd.Series:
    return np.log(pd.to_numeric(value, errors="coerce").where(lambda x: x > 0.0))


def standardize_matrix(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for col in cols:
        value = pd.to_numeric(frame[col], errors="coerce")
        std = value.std(ddof=1)
        if not math.isfinite(std) or std == 0.0:
            out[col] = np.nan
        else:
            out[col] = (value - value.mean()) / std
    return out


def residualize(y: pd.Series, controls: pd.DataFrame) -> pd.Series:
    frame = pd.concat([pd.to_numeric(y, errors="coerce").rename("_y"), controls], axis=1).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    valid = frame.dropna()
    result = pd.Series(np.nan, index=y.index, dtype="float64")
    if len(valid) < max(30, controls.shape[1] + 5):
        return result
    x = valid.drop(columns=["_y"]).to_numpy(dtype="float64")
    x = np.column_stack([np.ones(len(valid)), x])
    yy = valid["_y"].to_numpy(dtype="float64")
    try:
        beta, *_ = np.linalg.lstsq(x, yy, rcond=None)
        result.loc[valid.index] = yy - x @ beta
    except np.linalg.LinAlgError:
        pass
    return result


def corr_safe(a: pd.Series, b: pd.Series, method: str) -> float:
    frame = pd.concat([a, b], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 30:
        return np.nan
    if method == "rank":
        return float(frame.iloc[:, 0].rank().corr(frame.iloc[:, 1].rank()))
    return float(frame.iloc[:, 0].corr(frame.iloc[:, 1]))


def add_combo_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    if not {"V15", "V18a", "V18b"}.issubset(out.columns):
        return out
    out["V15_z"] = zscore_by_date(out, "V15")
    out["V18a_z"] = zscore_by_date(out, "V18a")
    out["V18b_z"] = zscore_by_date(out, "V18b")
    out["Combo_V15_plus_05V18b"] = out["V15_z"].fillna(0.0) + 0.5 * out["V18b_z"].fillna(0.0)
    out["Combo_V15_gated_by_V18a"] = out["V15_z"].fillna(0.0) * (
        1.0 + 0.25 * out["V18a_z"].fillna(0.0).clip(lower=0.0, upper=3.0)
    )
    out["Combo_V15_plus_V18a"] = out["V15_z"].fillna(0.0) + out["V18a_z"].fillna(0.0)
    out["Combo_V18a_gated_by_V15"] = out["V18a_z"].fillna(0.0) * (
        1.0 + 0.35 * out["V15_z"].fillna(0.0).clip(lower=0.0, upper=3.0)
    )
    out["Combo_V15V18a_agreement_min"] = np.minimum(out["V15_z"], out["V18a_z"])
    v15_tail = out["V15_z"].fillna(0.0).clip(lower=0.0, upper=3.0)
    v18a_tail = out["V18a_z"].fillna(0.0).clip(lower=0.0, upper=3.0)
    out["Combo_V15V18a_positive_product"] = v15_tail * v18a_tail
    out["Combo_V18a_minus_bad_V15"] = out["V18a_z"].fillna(0.0) - 0.5 * (
        -out["V15_z"].fillna(0.0)
    ).clip(lower=0.0, upper=3.0)
    return out


def tstat(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) < 3:
        return np.nan
    std = vals.std(ddof=1)
    if not math.isfinite(std) or std == 0.0:
        return np.nan
    return float(vals.mean() / (std / math.sqrt(len(vals))))


def evaluate_feature_panel(
    panel: pd.DataFrame,
    features: list[str],
    universes: list[str],
    horizons: list[int],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    control_cols = ["log_circ_mv", "turnover_rate_f", "volume_ratio", "pct_chg"]
    available_controls = [col for col in control_cols if col in panel.columns]
    for universe in universes:
        flag = f"univ_{universe}"
        if flag not in panel.columns:
            continue
        scoped = panel[panel[flag].fillna(False)].copy()
        if len(scoped) < 1000:
            continue
        scoped["date_n"] = scoped.groupby("trade_date")["ts_code"].transform("count")
        scoped = scoped[scoped["date_n"] >= 50].copy()
        if scoped.empty:
            continue
        for feature in features:
            if feature not in scoped.columns:
                continue
            for horizon in horizons:
                ret_col = f"fwd_{horizon}d"
                if ret_col not in scoped.columns:
                    continue
                raw_rank: list[float] = []
                raw_pearson: list[float] = []
                signal_resid_rank: list[float] = []
                both_resid_rank: list[float] = []
                top_excess: list[float] = []
                resid_top_excess: list[float] = []
                for _, day in scoped.groupby("trade_date", sort=False):
                    day = day[[feature, ret_col, *available_controls]].copy()
                    day = day.replace([np.inf, -np.inf], np.nan)
                    raw_rank.append(corr_safe(day[feature], day[ret_col], "rank"))
                    raw_pearson.append(corr_safe(day[feature], day[ret_col], "pearson"))
                    valid_top = day[[feature, ret_col]].dropna()
                    if len(valid_top) >= 50:
                        threshold = valid_top[feature].quantile(0.9)
                        top_excess.append(
                            float(
                                valid_top.loc[valid_top[feature] >= threshold, ret_col].mean()
                                - valid_top[ret_col].mean()
                            )
                        )
                    controls = standardize_matrix(day, available_controls)
                    sig_resid = residualize(day[feature], controls)
                    ret_resid = residualize(day[ret_col], controls)
                    signal_resid_rank.append(corr_safe(sig_resid, day[ret_col], "rank"))
                    both_resid_rank.append(corr_safe(sig_resid, ret_resid, "rank"))
                    valid_resid_top = pd.concat(
                        [sig_resid.rename("sig_resid"), ret_resid.rename("ret_resid")],
                        axis=1,
                    ).dropna()
                    if len(valid_resid_top) >= 50:
                        threshold = valid_resid_top["sig_resid"].quantile(0.9)
                        resid_top_excess.append(
                            float(
                                valid_resid_top.loc[
                                    valid_resid_top["sig_resid"] >= threshold,
                                    "ret_resid",
                                ].mean()
                                - valid_resid_top["ret_resid"].mean()
                            )
                        )
                raw_rank_s = pd.Series(raw_rank, dtype="float64")
                raw_pearson_s = pd.Series(raw_pearson, dtype="float64")
                sig_resid_s = pd.Series(signal_resid_rank, dtype="float64")
                both_resid_s = pd.Series(both_resid_rank, dtype="float64")
                top_s = pd.Series(top_excess, dtype="float64")
                resid_top_s = pd.Series(resid_top_excess, dtype="float64")
                rows.append(
                    {
                        "universe": universe,
                        "feature": feature,
                        "horizon": horizon,
                        "date_count": int(raw_rank_s.count()),
                        "raw_rank_ic_mean": float(raw_rank_s.mean()),
                        "raw_rank_ic_tstat": tstat(raw_rank_s),
                        "raw_pearson_ic_mean": float(raw_pearson_s.mean()),
                        "signal_resid_rank_ic_mean": float(sig_resid_s.mean()),
                        "signal_resid_rank_ic_tstat": tstat(sig_resid_s),
                        "both_resid_rank_ic_mean": float(both_resid_s.mean()),
                        "both_resid_rank_ic_tstat": tstat(both_resid_s),
                        "raw_top_decile_excess": float(top_s.mean()),
                        "resid_top_decile_excess": float(resid_top_s.mean()),
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    started = time.time()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    start = clean_date(args.start_date)
    end = clean_date(args.end_date)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    laws = [x.strip() for x in args.laws.split(",") if x.strip()]
    universes = [x.strip() for x in args.universes.split(",") if x.strip()]

    clean_all = load_daily_clean(args.daily_clean, start, end)
    sampled: set[str] | None = None
    if args.max_dates:
        dates = sorted(clean_all["trade_date"].unique())
        sampled_idx = np.linspace(0, len(dates) - 1, args.max_dates).round().astype(int)
        sampled = {dates[int(i)] for i in sampled_idx}
        start = min(sampled)
        end = max(sampled)

    clean = clean_all[(clean_all["trade_date"] >= start) & (clean_all["trade_date"] <= end)].copy()
    if sampled:
        clean = clean[clean["trade_date"].isin(sampled)].copy()
    if clean.empty:
        raise SystemExit("no clean daily rows")

    daily = load_daily_controls(args.daily_basic_root, clean, start, end, date_whitelist=sampled)
    forward = add_forward_returns(clean, horizons)
    daily = daily.merge(forward, on=["ts_code", "trade_date"], how="left")
    daily = add_universes(daily)
    daily, index_profile = add_index_universes(daily, args.index_universe_root)
    daily["log_circ_mv"] = robust_log(daily.get("circ_mv")).fillna(robust_log(daily.get("total_mv")))
    for col in ["turnover_rate_f", "volume_ratio", "pct_chg"]:
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")

    moment_cols = [
        "ts_code",
        "trade_date",
        "cutoff_time",
        "signed_flow_imbalance",
        "signed_amount_skew",
        "signed_amount_excess_kurtosis",
        "signed_flow_tail_asymmetry",
        "large_small_signed_spread",
        "amount_hhi",
        "amount_top5_share",
        "amount_entropy",
        "ret_skew",
        "ret_excess_kurtosis",
        "ret_tail_asymmetry",
        "realized_vol",
        "realized_vol_of_vol",
        "positive_signed_amount_share",
        "negative_signed_amount_share",
    ]
    if not all(law in MOMENT_LAWS for law in laws):
        raise SystemExit("this validator currently supports moment laws only")
    moments = read_partitioned(args.moments_root, moment_cols, start, end, args.cutoff_time, date_whitelist=sampled)
    if moments.empty:
        summary = {
            "verdict": "BLOCK_NO_MOMENTS_DATA",
            "start_date": start,
            "end_date": end,
            "moments_root": str(args.moments_root),
            "side_effects": {
                "clean_data_started": False,
                "search_worker_started": False,
                "official_promotion_started": False,
                "factor_forge_artifacts_written": False,
            },
        }
        (args.output_dir / "moneyflow_feature_validation_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return 2

    base_cols = [
        "ts_code",
        "trade_date",
        "log_circ_mv",
        "turnover_rate_f",
        "volume_ratio",
        "pct_chg",
        *[f"fwd_{h}d" for h in horizons],
        *[f"univ_{u}" for u in universes if f"univ_{u}" in daily.columns],
    ]
    panel = daily[base_cols].copy()
    for law_id in laws:
        label = LAW_LABELS.get(law_id, law_id)
        print(f"computing {label} {law_id}", flush=True)
        factor = compute_law(law_id, daily, moments).rename(columns={"factor_value": label})
        panel = panel.merge(factor[["ts_code", "trade_date", label]], on=["ts_code", "trade_date"], how="left")

    panel = add_combo_features(panel)
    features = [LAW_LABELS.get(law, law) for law in laws]
    for combo in [
        "Combo_V15_plus_05V18b",
        "Combo_V15_gated_by_V18a",
        "Combo_V15_plus_V18a",
        "Combo_V18a_gated_by_V15",
        "Combo_V15V18a_agreement_min",
        "Combo_V15V18a_positive_product",
        "Combo_V18a_minus_bad_V15",
    ]:
        if combo in panel.columns:
            features.append(combo)

    metrics = evaluate_feature_panel(panel, features, universes, horizons)
    metrics_path = args.output_dir / "moneyflow_feature_validation_metrics.csv"
    metrics.to_csv(metrics_path, index=False)
    summary = {
        "verdict": "ACCEPT" if not metrics.empty else "BLOCK_NO_METRICS",
        "started_at": started,
        "elapsed_seconds": time.time() - started,
        "start_date": start,
        "end_date": end,
        "cutoff_time": args.cutoff_time,
        "laws": laws,
        "features": features,
        "universes": universes,
        "horizons": horizons,
        "daily_rows": int(len(daily)),
        "moment_rows": int(len(moments)),
        "panel_rows": int(len(panel)),
        "metrics_path": str(metrics_path),
        "index_universe_profile": index_profile,
        "controls": ["log_circ_mv", "turnover_rate_f", "volume_ratio", "pct_chg"],
        "notes": [
            "Residualization is cross-sectional by trade_date.",
            "No industry neutralization is included in this research-side validator.",
            "This is feature validation, not official Factor Forge promotion.",
        ],
        "side_effects": {
            "clean_data_started": False,
            "search_worker_started": False,
            "official_promotion_started": False,
            "factor_forge_artifacts_written": False,
        },
    }
    summary_path = args.output_dir / "moneyflow_feature_validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if not metrics.empty:
        top = metrics.sort_values(
            ["both_resid_rank_ic_mean", "signal_resid_rank_ic_mean"],
            ascending=False,
        ).head(30)
        (args.output_dir / "moneyflow_feature_validation_top.md").write_text(
            dataframe_to_markdown(top),
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if not metrics.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
