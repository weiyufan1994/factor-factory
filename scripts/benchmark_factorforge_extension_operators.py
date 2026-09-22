#!/usr/bin/env python3
"""Bounded synthetic kernel benchmark; no market data or formal research writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from factor_factory.formula.extension_operators import ts_decay_linear, ts_product


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=int, default=200)
    parser.add_argument("--rows-per-symbol", type=int, default=1200)
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = args.symbols * args.rows_per_symbol
    if not (1 <= args.symbols and 1 <= args.window <= args.rows_per_symbol and rows <= 2_000_000 and 1 <= args.repeats <= 10):
        parser.error("Require positive sizes, window <= rows per symbol, <= 2M rows, and 1..10 repeats")
    rng = np.random.default_rng(20260920)
    frame = pd.DataFrame({
        "ts_code": np.repeat(np.arange(args.symbols), args.rows_per_symbol),
        "value": 1 + rng.normal(0, 0.005, rows),
    })
    values = frame["value"]
    weights = np.arange(1, args.window + 1, dtype="float64")

    def reference(reducer):
        return values.groupby(frame["ts_code"], sort=False).transform(
            lambda group: group.rolling(args.window, min_periods=args.window).apply(reducer, raw=True)
        )

    def measure(function):
        durations = []
        result = None
        for _ in range(args.repeats):
            started = time.perf_counter()
            result = function()
            durations.append(time.perf_counter() - started)
        return result, durations

    results = []
    for name, reducer, implementation in [
        ("ts_decay_linear", lambda window: np.dot(window, weights) / weights.sum(), ts_decay_linear),
        ("ts_product", np.prod, ts_product),
    ]:
        expected, reference_seconds = measure(lambda: reference(reducer))
        observed, implementation_seconds = measure(lambda: implementation(values, args.window, frame=frame))
        np.testing.assert_allclose(observed, expected, rtol=1e-12, atol=1e-12, equal_nan=True)
        assert observed.index.equals(expected.index)
        valid = expected.notna()
        results.append({
            "operator": name,
            "reference": "pandas_grouped_rolling_apply",
            "implementation": "numpy_batched_per_security",
            "reference_seconds": reference_seconds,
            "implementation_seconds": implementation_seconds,
            "median_speedup": statistics.median(reference_seconds) / statistics.median(implementation_seconds),
            "max_absolute_difference": float((observed[valid] - expected[valid]).abs().max()),
            "nan_mask_equal": bool(observed.isna().equals(expected.isna())),
        })
    source_paths = [Path(__file__), ROOT / "factor_factory/formula/extension_operators.py"]
    report = {
        "version": "factorforge_synthetic_extension_benchmark_v1",
        "scope": "synthetic_time_series_kernel_only",
        "formal_research_evidence": False,
        "includes_io_sorting_or_backtest": False,
        "description": "Minute-shaped row volume (200 securities x 5 sessions x 240 rows by default); finite synthetic values, already grouped and ordered. Does not validate minute calendars or execution.",
        "rows": rows, "symbols": args.symbols, "rows_per_symbol": args.rows_per_symbol,
        "window": args.window, "repeats": args.repeats, "seed": 20260920,
        "environment": {"python": platform.python_version(), "machine": platform.machine(), "numpy": np.__version__, "pandas": pd.__version__},
        "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
