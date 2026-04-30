#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT.parent
RUNS = REPO_ROOT / "runs"
EVALS = REPO_ROOT / "evaluations"
QLIB_REPO = WORKSPACE / "qlib_repo"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(QLIB_REPO) not in sys.path:
    sys.path.insert(0, str(QLIB_REPO))

os.environ.setdefault("MPLCONFIGDIR", str(WORKSPACE / ".cache" / "matplotlib"))

import redis_lock  # noqa: F401,E402
import qlib  # noqa: E402
from qlib.backtest import backtest  # noqa: E402
from qlib.backtest.executor import SimulatorExecutor  # noqa: E402
from qlib.contrib.strategy import TopkDropoutStrategy  # noqa: E402

from factor_factory.data_access import load_factor_values_with_signal, to_qlib_signal_frame  # noqa: E402


def write_line_plot(df: pd.DataFrame, columns: list[str], path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for col in columns:
        if col in df.columns:
            ax.plot(df.index, df[col], label=col, linewidth=1.4)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("datetime")
    if len(columns) > 1:
        ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _normalize_date_arg(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if '-' in value:
        return value
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def run_native(
    report_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    universe_limit: int | None = None,
    topk: int = 50,
    n_drop: int = 5,
    output_dir: str | Path | None = None,
) -> dict:
    provider_uri = RUNS / report_id / "qlib_provider"
    if not provider_uri.exists():
        raise SystemExit(f"missing qlib provider: {provider_uri}")

    factor_df, signal_col, factor_id = load_factor_values_with_signal(report_id)
    if universe_limit and universe_limit > 0:
        keep_codes = sorted(factor_df["ts_code"].dropna().unique())[:universe_limit]
        factor_df = factor_df[factor_df["ts_code"].isin(keep_codes)].copy()

    qlib_signal = to_qlib_signal_frame(
        factor_df[["ts_code", "trade_date", signal_col]].copy(),
        signal_col=signal_col,
        instrument_style="ts_code",
    )

    qlib.init(provider_uri=str(provider_uri), region="cn")

    strategy = TopkDropoutStrategy(signal=qlib_signal, topk=topk, n_drop=n_drop)
    executor = SimulatorExecutor(time_per_step="day", generate_portfolio_metrics=True)
    trading_calendar = sorted(qlib_signal.index.get_level_values("datetime").unique())
    requested_start = pd.Timestamp(_normalize_date_arg(start_date)) if start_date else None
    requested_end = pd.Timestamp(_normalize_date_arg(end_date)) if end_date else None
    if requested_start is not None:
        trading_calendar = [dt for dt in trading_calendar if dt >= requested_start]
    if requested_end is not None:
        trading_calendar = [dt for dt in trading_calendar if dt <= requested_end]
    if not trading_calendar:
        raise SystemExit("requested native qlib window has no trading dates after filtering")
    start = trading_calendar[0]
    end = trading_calendar[-2] if len(trading_calendar) > 1 else trading_calendar[-1]

    # Empty benchmark series disables qlib's fallback to CSI300 while keeping report plumbing intact.
    benchmark = pd.Series(dtype="float64")
    portfolio_dict, indicator_dict = backtest(
        start_time=start,
        end_time=end,
        strategy=strategy,
        executor=executor,
        benchmark=benchmark,
        account=100000000,
        exchange_kwargs={
            "freq": "day",
            "limit_threshold": 0.095,
            "deal_price": "close",
            "codes": sorted(factor_df["ts_code"].dropna().unique().tolist()) if universe_limit and universe_limit > 0 else "all",
        },
    )

    freq_key = list(portfolio_dict.keys())[0]
    metrics_df, hist_positions = portfolio_dict[freq_key]
    indicator_df, _indicator_obj = indicator_dict[freq_key]
    metrics_df = metrics_df.copy()
    metrics_df.index.name = "datetime"

    eval_dir = Path(output_dir) if output_dir else (EVALS / report_id / "qlib_native")
    eval_dir.mkdir(parents=True, exist_ok=True)
    metrics_csv = eval_dir / "native_portfolio_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=True)

    portfolio_plot = eval_dir / "portfolio_value_timeseries.png"
    strategy_plot = eval_dir / "strategy_return_timeseries.png"
    turnover_plot = eval_dir / "turnover_timeseries.png"

    write_line_plot(metrics_df, ["account"], portfolio_plot, f"{report_id} qlib portfolio value")
    write_line_plot(metrics_df, ["return"], strategy_plot, f"{report_id} qlib strategy return")
    write_line_plot(metrics_df, ["total_turnover"], turnover_plot, f"{report_id} qlib turnover")

    payload = {
        "backend": "qlib_native",
        "report_id": report_id,
        "factor_id": factor_id,
        "signal_name": signal_col,
        "mode": "native_minimal",
        "status": "success",
        "engine": "run_qlib_native_report",
        "provider_uri": str(provider_uri),
        "metrics_summary": {
            "freq_key": str(freq_key),
            "rows": int(len(metrics_df)),
            "backtest_start": str(start),
            "backtest_end": str(end),
            "universe_limit": int(universe_limit) if universe_limit else None,
            "universe_size": int(factor_df["ts_code"].nunique()),
            "topk": int(topk),
            "n_drop": int(n_drop),
            "final_account": float(metrics_df["account"].iloc[-1]) if "account" in metrics_df.columns and len(metrics_df) else None,
            "mean_return": float(metrics_df["return"].mean()) if "return" in metrics_df.columns else None,
            "return_std": float(metrics_df["return"].std()) if "return" in metrics_df.columns else None,
            "nonzero_turnover_rows": int((metrics_df["total_turnover"] != 0).sum()) if "total_turnover" in metrics_df.columns else None,
            "nonzero_value_rows": int((metrics_df["value"] != 0).sum()) if "value" in metrics_df.columns else None,
            "max_position_count": int(max((len(position.get_stock_list()) for position in hist_positions.values()), default=0)),
            "indicator_rows": int(len(indicator_df)),
        },
        "artifacts": {
            "native_portfolio_metrics_csv": str(metrics_csv),
            "portfolio_value_timeseries_png": str(portfolio_plot),
            "strategy_return_timeseries_png": str(strategy_plot),
            "turnover_timeseries_png": str(turnover_plot),
        },
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--start-date")
    ap.add_argument("--end-date")
    ap.add_argument("--universe-limit", type=int)
    ap.add_argument("--topk", type=int, default=50)
    ap.add_argument("--n-drop", type=int, default=5)
    args = ap.parse_args()

    output_path = Path(args.output)
    payload = run_native(
        args.report_id,
        start_date=args.start_date,
        end_date=args.end_date,
        universe_limit=args.universe_limit,
        topk=args.topk,
        n_drop=args.n_drop,
        output_dir=output_path.parent,
    )
    out = output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[WRITE] {out}")


if __name__ == "__main__":
    main()
