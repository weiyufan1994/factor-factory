"""Run handwritten factor classes and preliminary analyses, entirely offline.

From the repository root:
    python examples/manual_interface_replay/run_demo.py --output-dir /tmp/ff-demo

All prices/returns are tiny synthetic fixtures, not downloaded market evidence.
The hand-calculated expected values are a separate CSV, never regenerated from
the implementation under test. This script is a demonstration, not a new runner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import factorforge_data_api
from factorforge_data_api import DataApiClient, DataQuery
from factor_factory.factors import FormulaFactor
from factor_factory.research_api import evaluate_factor
from factor_factory.research_presentation import write_factor_review
from examples.manual_interface_replay.factor_definitions import (
    HybridMeanIntradaySpread, MeanIntradaySpread,
)

FIXTURE = Path(__file__).resolve().parent


def read_indexed(name: str) -> pd.DataFrame:
    frame = pd.read_csv(FIXTURE / name, dtype={"instrument": str})
    frame["datetime"] = pd.to_datetime(frame["datetime"], format="%Y-%m-%d")
    return frame.set_index(["datetime", "instrument"]).sort_index().astype("float64")


def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    # A local fixture catalog exercises the real SDK. No cloud/catalog mutation.
    catalog = {
        "datasets": [{
            "dataset_id": "synthetic_daily", "uri": str(FIXTURE / "daily.csv"),
            "format": "csv", "storage": "local", "version": "demo_v1",
            "columns": ["ts_code", "trade_date", "open", "close"],
        }],
    }
    catalog_path = output_dir / "local_demo_catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    client = DataApiClient.from_catalog(catalog_path)
    result = client.fetch(DataQuery(
        "synthetic_daily", "20200102", "20200108", "a_share_all", ["open", "close"],
        expected_trade_dates=("20200102", "20200103", "20200106", "20200107", "20200108"),
        calendar_identity="synthetic_five_date_fixture",
    ))
    if result.status != "ready":
        raise RuntimeError(f"fixture SDK read failed: {result.blocked_reason}")
    daily = result.frame
    before = daily.copy(deep=True)

    # Factor objects all accept the same named frames and return the same index.
    routes = {
        "direct_code": MeanIntradaySpread(window=2),
        "operator": FormulaFactor("mean(close - open, 2)", name="same_object_operator"),
        "hybrid": HybridMeanIntradaySpread(window=2),
    }
    expected = read_indexed("expected_factor_values.csv")
    outputs = {}
    for name, factor in routes.items():
        outputs[name] = factor({"daily_df": daily})
        pd.testing.assert_frame_equal(outputs[name], expected, check_exact=False, rtol=0, atol=1e-12)
    pd.testing.assert_frame_equal(daily, before)
    factor_values = outputs["direct_code"]

    # This is an explicit, independently listed label fixture, NOT a return
    # derived from these made-up prices and NOT an empirical payoff claim.
    forward_returns = read_indexed("forward_returns.csv")
    forward_returns.attrs["timing"] = {
        "source": "synthetic label fixture, independently listed",
        "meaning": "decimal payoff assigned to a signal date for testing only",
    }
    # A declared evaluation window, not a dropna filter chosen after seeing IC.
    # Jan 2 is the one-observation warmup and remains in the exported values.
    evaluation_index = expected.index[
        expected.index.get_level_values("datetime") >= pd.Timestamp("2020-01-03")
    ]
    analyses = {
        analysis: evaluate_factor(
            factor_values.reindex(evaluation_index), forward_returns, analysis=analysis,
            expected_index=evaluation_index, newey_west_lags=0,
        )
        for analysis in ("ic", "event_study", "fama_macbeth")
    }
    # No NaN/Infinity disguised as portable JSON. Undefined values must be null.
    encoded = json.dumps(analyses, ensure_ascii=False, indent=2, allow_nan=False)
    (output_dir / "metrics.json").write_text(encoded + "\n", encoding="utf-8")
    factor_values.to_csv(output_dir / "factor_values.csv")
    factor_values.to_parquet(output_dir / "factor_values.parquet")
    daily.to_csv(output_dir / "input_snapshot.csv", index=False)
    source = (
        "# FILE: factor_definitions.py\n" + (FIXTURE / "factor_definitions.py").read_text()
        + "\n# FILE: run_demo.py\n" + Path(__file__).read_text()
    )
    # Include the two actual source roots so a fresh shell can copy this command
    # without inheriting this process's PYTHONPATH or relying on an installed SDK.
    sdk_root = Path(factorforge_data_api.__file__).resolve().parent.parent
    command = (
        "PYTHONDONTWRITEBYTECODE=1 "
        f"PYTHONPATH={shlex.quote(f'{REPO}:{sdk_root}')} "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} "
        f"--output-dir {shlex.quote(str(output_dir.resolve()))}"
    )
    report = write_factor_review(
        output_dir / "human_review.html", factor_values=factor_values,
        source_code=source, metrics=analyses["ic"], command=command,
        title="手写代码 → 标准因子表 → 可独立核算的 IC",
        selected_dates=("2020-01-02", "2020-01-03", "2020-01-08"),
        input_sample=daily.head(9),
        notes=("完全离线合成例子。三条实现路线与手算 CSV 逐格相等；首日 warmup 保留 NaN。"
               "预先指定分析窗口为 1月3日至8日，样本表仍展示全部15行。此页展示 IC；同目录 metrics.json 同时包含 event-study 与 Fama–MacBeth。不是 Amihud 研究或账户回测。"),
    )
    print("Three implementation routes equal the hand-calculated CSV.")
    print("HEAD\n", factor_values.head(6).to_string())
    print("TAIL\n", factor_values.tail(6).to_string())
    print("Analysis outputs:\n", encoded)
    print("Human-readable report:", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    main(parser.parse_args().output_dir)
