#!/usr/bin/env python3
"""
Linear incremental evaluation for V18 value-occupation signals.

Research-side only. This script asks whether a simple V18 state variable adds
linear information beyond momentum/reversal-like price controls and basic
Barra-style risk controls. Nonlinear bucket results are diagnostic only.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research_vp_p0_baseline_eval import add_signals, add_universe_flags, clean_date, finite_float, load_vp_state
from research_vp_v18_drift_persistence_eval import add_v18_features, load_daily


DEFAULT_SIGNALS = [
    "v18_repair_drift_score",
    "v18_repair_base_z",
    "below_cost_depth_score_raw",
]

UNIVERSES = ["full", "middle_20_90", "largest_10", "smallest_20"]

CORE_CONTROLS = [
    "ln_total_mv",
    "turnover_rate",
    "vol_20d",
    "drift_1d_to_cutoff",
    "mom_5d_to_cutoff",
    "mom_20d_to_cutoff",
]

STATE_CONTROLS = [
    "below_cost_depth_score_raw",
    "lower_support_mass",
    "support_minus_overhang",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vp-root", type=Path, required=True)
    parser.add_argument("--daily-clean", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20250714")
    parser.add_argument("--end-date", default="20260612")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--signals", default=",".join(DEFAULT_SIGNALS))
    parser.add_argument("--universes", default=",".join(UNIVERSES))
    parser.add_argument("--min-date-rows", type=int, default=80)
    parser.add_argument("--use-state-controls", action="store_true")
    return parser.parse_args()


def tstat(values: pd.Series) -> float | None:
    vals = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(vals) < 3:
        return None
    std = float(vals.std(ddof=1))
    if std == 0.0 or not math.isfinite(std):
        return None
    return float(vals.mean() / std * math.sqrt(len(vals)))


def rank_z(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    ranks = values.rank(method="average")
    mean = ranks.mean()
    std = ranks.std(ddof=0)
    if not math.isfinite(float(std)) or float(std) == 0.0:
        return pd.Series(np.nan, index=series.index)
    return (ranks - mean) / std


def residualize(y: np.ndarray, x: np.ndarray) -> np.ndarray | None:
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    if valid.sum() < x.shape[1] + 5:
        return None
    xv = np.column_stack([np.ones(valid.sum()), x[valid]])
    yv = y[valid]
    try:
        beta = np.linalg.lstsq(xv, yv, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    resid = np.full(len(y), np.nan)
    resid[valid] = yv - xv @ beta
    return resid


def ols_metrics(y: np.ndarray, controls: np.ndarray, candidate: np.ndarray) -> dict[str, float | None]:
    valid_base = np.isfinite(y) & np.isfinite(controls).all(axis=1)
    valid_full = valid_base & np.isfinite(candidate)
    if valid_full.sum() < controls.shape[1] + 10:
        return {}

    y_full = y[valid_full]
    x_base = np.column_stack([np.ones(valid_full.sum()), controls[valid_full]])
    x_full = np.column_stack([x_base, candidate[valid_full]])
    try:
        beta_base = np.linalg.lstsq(x_base, y_full, rcond=None)[0]
        beta_full = np.linalg.lstsq(x_full, y_full, rcond=None)[0]
    except np.linalg.LinAlgError:
        return {}

    pred_base = x_base @ beta_base
    pred_full = x_full @ beta_full
    tss = float(np.sum((y_full - y_full.mean()) ** 2))
    if tss <= 0.0 or not math.isfinite(tss):
        return {}
    r2_base = 1.0 - float(np.sum((y_full - pred_base) ** 2)) / tss
    r2_full = 1.0 - float(np.sum((y_full - pred_full) ** 2)) / tss
    return {
        "fm_beta": float(beta_full[-1]),
        "baseline_r2": r2_base,
        "with_signal_r2": r2_full,
        "delta_r2": r2_full - r2_base,
    }


def corr_safe(x: pd.Series, y: pd.Series) -> float | None:
    frame = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 20 or frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
        return None
    value = float(frame["x"].corr(frame["y"]))
    return value if math.isfinite(value) else None


def prepare_panel(vp_root: Path, daily_clean: Path, start_date: str, end_date: str, horizons: list[int]) -> pd.DataFrame:
    vp = load_vp_state(vp_root, start_date, end_date, max_dates=None)
    daily = load_daily(daily_clean, horizons)
    daily_cols = [
        "ts_code",
        "trade_date",
        "total_mv",
        "circ_mv",
        "ln_total_mv",
        "turnover_rate",
        "vol_20d",
        "close_lag1",
        "close_lag3",
        "close_lag5",
        "close_lag20",
    ] + [f"fwd_{h}d" for h in horizons]
    daily_cols = [col for col in daily_cols if col in daily.columns]
    panel = vp.merge(daily[daily_cols], on=["ts_code", "trade_date"], how="inner")
    panel = add_universe_flags(add_signals(panel))
    panel = add_v18_features(panel)
    panel["trade_date"] = panel["trade_date"].map(clean_date)
    return panel


def evaluate(panel: pd.DataFrame, signals: list[str], universes: list[str], horizons: list[int], controls: list[str], min_rows: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metric_rows: list[dict[str, object]] = []
    bucket_rows: list[dict[str, object]] = []
    corr_rows: list[dict[str, object]] = []

    available_controls = [col for col in controls if col in panel.columns]
    for date, day in panel.groupby("trade_date", sort=True):
        for universe in universes:
            universe_col = f"universe_{universe}"
            if universe_col not in day.columns:
                continue
            base = day[day[universe_col]].copy()
            if len(base) < min_rows:
                continue

            ranked_controls = pd.DataFrame(index=base.index)
            for control in available_controls:
                ranked_controls[control] = rank_z(base[control])
            control_matrix = ranked_controls.to_numpy(dtype=float)

            for signal in signals:
                if signal not in base.columns:
                    continue
                sig_rank = rank_z(base[signal])
                for control in available_controls:
                    corr = corr_safe(sig_rank, ranked_controls[control])
                    if corr is not None:
                        corr_rows.append(
                            {
                                "trade_date": date,
                                "universe": universe,
                                "signal": signal,
                                "control": control,
                                "rank_corr": corr,
                            }
                        )

                for horizon in horizons:
                    ret_col = f"fwd_{horizon}d"
                    if ret_col not in base.columns:
                        continue
                    ret_rank = rank_z(base[ret_col])
                    valid = pd.DataFrame({"signal": sig_rank, "ret": ret_rank}).dropna()
                    if len(valid) < min_rows:
                        continue
                    raw_ic = corr_safe(valid["signal"], valid["ret"])

                    sig_resid = residualize(sig_rank.to_numpy(dtype=float), control_matrix)
                    ret_resid = residualize(ret_rank.to_numpy(dtype=float), control_matrix)
                    partial_ic = None
                    if sig_resid is not None and ret_resid is not None:
                        partial_ic = corr_safe(pd.Series(sig_resid, index=base.index), pd.Series(ret_resid, index=base.index))

                    ols = ols_metrics(ret_rank.to_numpy(dtype=float), control_matrix, sig_rank.to_numpy(dtype=float))
                    if raw_ic is not None or partial_ic is not None or ols:
                        metric_rows.append(
                            {
                                "trade_date": date,
                                "universe": universe,
                                "horizon": horizon,
                                "signal": signal,
                                "row_count": int(len(base)),
                                "raw_rank_ic": raw_ic,
                                "partial_rank_ic": partial_ic,
                                **ols,
                            }
                        )

                    bucket_frame = pd.DataFrame(
                        {
                            "signal": sig_rank,
                            "ret": pd.to_numeric(base[ret_col], errors="coerce"),
                        }
                    ).replace([np.inf, -np.inf], np.nan).dropna()
                    if len(bucket_frame) >= min_rows and bucket_frame["signal"].nunique() >= 5:
                        try:
                            bucket_frame["bucket"] = pd.qcut(bucket_frame["signal"], 5, labels=False, duplicates="drop") + 1
                        except ValueError:
                            continue
                        universe_ret = float(bucket_frame["ret"].mean())
                        for bucket, bucket_df in bucket_frame.groupby("bucket", sort=True):
                            bucket_rows.append(
                                {
                                    "trade_date": date,
                                    "universe": universe,
                                    "horizon": horizon,
                                    "signal": signal,
                                    "bucket": int(bucket),
                                    "bucket_return": float(bucket_df["ret"].mean()),
                                    "universe_return": universe_ret,
                                    "bucket_excess": float(bucket_df["ret"].mean() - universe_ret),
                                    "row_count": int(len(bucket_df)),
                                }
                            )

    return (
        aggregate_metrics(pd.DataFrame(metric_rows)),
        aggregate_buckets(pd.DataFrame(bucket_rows)),
        aggregate_corr(pd.DataFrame(corr_rows)),
    )


def aggregate_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    out: list[dict[str, object]] = []
    for key, group in rows.groupby(["signal", "universe", "horizon"], sort=True):
        signal, universe, horizon = key
        out.append(
            {
                "signal": signal,
                "universe": universe,
                "horizon": int(horizon),
                "date_count": int(group["trade_date"].nunique()),
                "row_count": int(group["row_count"].sum()),
                "raw_rank_ic_mean": finite_float(group["raw_rank_ic"].mean()),
                "raw_rank_ic_tstat": finite_float(tstat(group["raw_rank_ic"])),
                "partial_rank_ic_mean": finite_float(group["partial_rank_ic"].mean()),
                "partial_rank_ic_tstat": finite_float(tstat(group["partial_rank_ic"])),
                "fm_beta_mean": finite_float(group["fm_beta"].mean()),
                "fm_beta_tstat": finite_float(tstat(group["fm_beta"])),
                "baseline_r2_mean": finite_float(group["baseline_r2"].mean()),
                "with_signal_r2_mean": finite_float(group["with_signal_r2"].mean()),
                "delta_r2_mean": finite_float(group["delta_r2"].mean()),
                "delta_r2_tstat": finite_float(tstat(group["delta_r2"])),
            }
        )
    return pd.DataFrame(out)


def aggregate_buckets(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    out: list[dict[str, object]] = []
    for key, group in rows.groupby(["signal", "universe", "horizon", "bucket"], sort=True):
        signal, universe, horizon, bucket = key
        out.append(
            {
                "signal": signal,
                "universe": universe,
                "horizon": int(horizon),
                "bucket": int(bucket),
                "date_count": int(group["trade_date"].nunique()),
                "bucket_excess_mean": finite_float(group["bucket_excess"].mean()),
                "bucket_excess_tstat": finite_float(tstat(group["bucket_excess"])),
                "bucket_return_mean": finite_float(group["bucket_return"].mean()),
                "universe_return_mean": finite_float(group["universe_return"].mean()),
            }
        )
    return pd.DataFrame(out)


def aggregate_corr(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    out: list[dict[str, object]] = []
    for key, group in rows.groupby(["signal", "universe", "control"], sort=True):
        signal, universe, control = key
        out.append(
            {
                "signal": signal,
                "universe": universe,
                "control": control,
                "date_count": int(group["trade_date"].nunique()),
                "rank_corr_mean": finite_float(group["rank_corr"].mean()),
                "rank_corr_abs_mean": finite_float(group["rank_corr"].abs().mean()),
            }
        )
    return pd.DataFrame(out)


def write_markdown(metrics: pd.DataFrame, buckets: pd.DataFrame, corr: pd.DataFrame, path: Path) -> None:
    lines = [
        "# V18 Linear Incremental Evaluation",
        "",
        "Main test: daily cross-sectional rank-z linear regression. Candidate signal enters as one linear column after momentum/reversal and risk controls.",
        "",
        "## Incremental Metrics",
        "",
    ]
    if not metrics.empty:
        view = metrics.sort_values(["signal", "universe", "horizon"])
        lines.append(view.to_markdown(index=False, floatfmt=".6f"))
    else:
        lines.append("_No metrics produced._")
    lines.extend(["", "## Bucket Diagnostics", ""])
    if not buckets.empty:
        diag = buckets.sort_values(["signal", "universe", "horizon", "bucket"])
        lines.append(diag.to_markdown(index=False, floatfmt=".6f"))
    else:
        lines.append("_No bucket diagnostics produced._")
    lines.extend(["", "## Control Overlap", ""])
    if not corr.empty:
        lines.append(corr.sort_values(["signal", "universe", "rank_corr_abs_mean"], ascending=[True, True, False]).to_markdown(index=False, floatfmt=".6f"))
    else:
        lines.append("_No control correlations produced._")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]
    signals = [x.strip() for x in args.signals.split(",") if x.strip()]
    universes = [x.strip() for x in args.universes.split(",") if x.strip()]
    controls = CORE_CONTROLS + (STATE_CONTROLS if args.use_state_controls else [])

    print(f"[LOAD] panel vp={args.vp_root} daily={args.daily_clean}", flush=True)
    panel = prepare_panel(args.vp_root, args.daily_clean, args.start_date, args.end_date, horizons)
    print(
        f"[PANEL] rows={len(panel):,} dates={panel['trade_date'].nunique():,} tickers={panel['ts_code'].nunique():,}",
        flush=True,
    )
    print(f"[EVAL] signals={signals} controls={[c for c in controls if c in panel.columns]}", flush=True)
    metrics, buckets, corr = evaluate(panel, signals, universes, horizons, controls, args.min_date_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "vp_v18_incremental_linear_metrics.csv"
    buckets_path = args.output_dir / "vp_v18_incremental_bucket_diagnostics.csv"
    corr_path = args.output_dir / "vp_v18_incremental_control_corr.csv"
    summary_path = args.output_dir / "vp_v18_incremental_linear_summary.json"
    markdown_path = args.output_dir / "vp_v18_incremental_linear_report.md"

    metrics.to_csv(metrics_path, index=False)
    buckets.to_csv(buckets_path, index=False)
    corr.to_csv(corr_path, index=False)
    summary_path.write_text(
        json.dumps(
            {
                "meta": {
                    "vp_root": str(args.vp_root),
                    "daily_clean": str(args.daily_clean),
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "horizons": horizons,
                    "signals": signals,
                    "universes": universes,
                    "controls": [c for c in controls if c in panel.columns],
                    "panel_rows": int(len(panel)),
                    "panel_date_count": int(panel["trade_date"].nunique()),
                    "panel_ticker_count": int(panel["ts_code"].nunique()),
                },
                "metrics": metrics.where(pd.notna(metrics), None).to_dict(orient="records"),
                "bucket_diagnostics": buckets.where(pd.notna(buckets), None).to_dict(orient="records"),
                "control_corr": corr.where(pd.notna(corr), None).to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_markdown(metrics, buckets, corr, markdown_path)
    print(f"[OK] wrote {metrics_path}", flush=True)
    print(f"[OK] wrote {markdown_path}", flush=True)


if __name__ == "__main__":
    main()
