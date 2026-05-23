# RTA-07A Operator Kernel Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a read-only operator-kernel inventory that explains the current Step3B Formula-IR execution model, identifies slow operator implementations, probes optional acceleration libraries including TA-Lib, and emits a reviewed upgrade matrix for RTA-07B.

**Architecture:** This phase must not optimize production code. Add one read-only inventory CLI under `scripts/`, then extend performance smoke with deterministic fixtures proving the inventory contract, `/tmp` write guard, qlib-not-formal-engine classification, TA-Lib factor-library classification, and high-risk operator detection. The output is a JSON artifact that coder/reviewer can use to choose the next operator-kernel work.

**Tech Stack:** Python 3, pandas, numpy, stdlib `importlib`, existing Factor Forge Formula-IR files, existing `scripts/run_factorforge_performance_smoke.py`.

---

## Scope

RTA-07A is exploratory architecture instrumentation only.

Allowed:
- Create `scripts/run_factorforge_operator_kernel_inventory.py`
- Modify `scripts/run_factorforge_performance_smoke.py`
- Optionally update `docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md` with a short pointer after smoke passes

Not allowed:
- Do not change `factor_factory/formula/operators.py` semantics.
- Do not change `factor_factory/formula/kernels.py` selection/default behavior.
- Do not enable experimental Formula kernels by default.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers.
- Do not handle clean data.
- Do not run search worker.
- Do not write official promotion.
- Do not install TA-Lib, numba, bottleneck, numbagg, window-ops, scipy, or any dependency in this task.

## Contract

The new CLI must write JSON with this top-level shape:

```json
{
  "version": "factorforge_operator_kernel_inventory_v1",
  "generated_at": "2026-05-23T00:00:00Z",
  "repo_root": "/Users/humphrey/projects/factor-factory",
  "read_only": true,
  "current_execution_model": {
    "step3b_factor_values_use_qlib_native": false,
    "formal_factor_engine": "factor_forge_formula_ir_pandas",
    "qlib_role": "bridge_export_backtest_compatibility",
    "notes": []
  },
  "operator_inventory": [],
  "optional_dependency_probe": {},
  "library_landscape": [],
  "upgrade_priority": [],
  "diagnostics": [],
  "canonical_pollution": false
}
```

Required diagnostics:
- `QLIB_NOT_FORMAL_OPERATOR_ENGINE`
- `OPERATOR_KERNEL_HOTSPOT_ROLLING_APPLY`
- `OPERATOR_KERNEL_HOTSPOT_GROUPBY_APPLY_CORR_COV`
- `TA_LIB_FACTOR_LIBRARY_CANDIDATE`
- `EXPERIMENTAL_KERNELS_PRESENT_NOT_DEFAULT`

## Task 1: Add Read-Only Inventory CLI

**Files:**
- Create: `scripts/run_factorforge_operator_kernel_inventory.py`

- [ ] **Step 1: Write the script skeleton**

Create a CLI with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION = "factorforge_operator_kernel_inventory_v1"
CANONICAL_DIRS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
```

Add helpers:
- `utc_now() -> str`
- `is_tmp_path(path: Path) -> bool`
- `write_json(path: Path, payload: dict[str, Any]) -> None`
- `snapshot_canonical_files() -> set[str]`
- `canonical_pollution(before: set[str], after: set[str]) -> bool`

The CLI arguments must be:

```text
--output PATH
--allow-non-tmp-output
--repo-root PATH
```

Default `repo_root` is `REPO_ROOT`. If `--output` is not under `/tmp/` or `/private/tmp/` and `--allow-non-tmp-output` is not present, exit with:

```text
BLOCK_OPERATOR_KERNEL_INVENTORY_NON_TMP_OUTPUT
```

- [ ] **Step 2: Add optional dependency probe**

Implement `probe_optional_dependencies()` using `importlib.util.find_spec`; do not import heavy libraries.

Probe these module names:

```python
{
    "talib": "TA-Lib technical indicator library",
    "bottleneck": "fast nan-aware array reductions",
    "numba": "jit compiled custom rolling kernels",
    "scipy": "rankdata and statistical kernels",
    "numbagg": "numba-backed aggregations",
    "window_ops": "rolling window operations",
    "polars": "alternate dataframe backend"
}
```

Each entry must include:

```json
{
  "module": "talib",
  "importable": false,
  "version": null,
  "install_required_for_rta07a": false,
  "role": "factor_indicator_library"
}
```

Roles:
- `talib`: `factor_indicator_library`
- `bottleneck`, `numbagg`, `window_ops`, `numba`, `scipy`: `operator_kernel_candidate`
- `polars`: `alternate_dataframe_backend`

- [ ] **Step 3: Add operator inventory**

Read `factor_factory/formula/operators.py`, `factor_factory/formula/kernels.py`, `factor_factory/formula/registry.py`, and `factor_factory/formula/ts_rank_candidates.py` as text. This task may use conservative pattern matching because it is observational.

Emit at least these operators:

```python
[
    "cs_rank",
    "ts_sum",
    "ts_mean",
    "ts_std",
    "ts_rank",
    "ts_min",
    "ts_max",
    "ts_argmin",
    "ts_argmax",
    "ts_delta",
    "ts_delay",
    "rolling_corr",
    "rolling_cov",
    "cs_scale",
    "signed_power"
]
```

For each operator, include:

```json
{
  "operator": "ts_argmin",
  "current_impl": "pandas_groupby_rolling_apply_raw_lambda",
  "qlib_bridge_supported": false,
  "performance_risk": "high",
  "semantic_risk": "medium",
  "reason": "rolling apply lambda executes custom window logic through pandas apply",
  "upgrade_candidates": ["numba_per_ticker_loop", "numpy_per_ticker_loop"],
  "default_safe_to_change": false
}
```

Classification rules:
- `ts_argmin`, `ts_argmax`: high performance risk; candidates `numba_per_ticker_loop`, `numpy_per_ticker_loop`.
- `rolling_corr`, `rolling_cov`: high performance risk; candidates `pandas_vectorized_no_groupby_apply`, `numba_per_ticker_loop`, `bottleneck_formula_candidate`.
- `ts_rank`: high performance risk; candidates `existing_numpy_sliding_window_experimental`, `pandas_rolling_rank_candidate`, `scipy_rankdata_candidate`, `numba_per_ticker_loop`.
- `ts_sum`, `ts_mean`, `ts_std`, `ts_min`, `ts_max`: medium performance risk; candidates `existing_numpy_rolling_experimental`, `bottleneck`, `window_ops`, `numbagg`.
- `ts_delta`, `ts_delay`: low performance risk; no urgent replacement.
- `cs_rank`, `cs_scale`, `signed_power`: medium or low depending on implementation; do not mark urgent unless evidence exists.

`qlib_bridge_supported` should be read from `registry.py` where possible. If not detected, set `null` and add a note.

- [ ] **Step 4: Add current execution model**

The output must explicitly say Step3B formal factor values do not use qlib native execution.

Set:

```json
{
  "step3b_factor_values_use_qlib_native": false,
  "formal_factor_engine": "factor_forge_formula_ir_pandas",
  "qlib_role": "bridge_export_backtest_compatibility",
  "evidence_files": [
    "skills/factor-forge-step3/scripts/run_step3b.py",
    "factor_factory/formula/evaluator.py",
    "factor_factory/formula/operators.py",
    "factor_factory/formula/qlib_codegen.py"
  ]
}
```

Do not overstate qlib quality. The wording should be factual:

```text
Current slowness should be attributed first to pandas/groupby/rolling/apply execution in Factor Forge's formal Formula-IR path, not to qlib native operator execution.
```

- [ ] **Step 5: Add library landscape**

Emit a fixed `library_landscape` section:

```json
[
  {
    "library": "TA-Lib",
    "best_role": "factor_indicator_library",
    "good_for": ["RSI", "MACD", "ATR", "BBANDS", "technical_indicator_factor_family"],
    "not_safe_for": ["silent_replacement_of_formula_ir_rolling_semantics"],
    "reason": "TA-Lib indicator warmup, NaN, price-field, and multi-input semantics differ from Alpha/Formula-IR primitive operators."
  },
  {
    "library": "bottleneck",
    "best_role": "operator_kernel_candidate",
    "good_for": ["nan-aware moving reductions"],
    "not_safe_for": ["ts_rank_without_parity", "corr_cov_without_semantic_check"]
  },
  {
    "library": "numba",
    "best_role": "operator_kernel_candidate",
    "good_for": ["argmin_argmax", "ts_rank", "corr_cov"],
    "not_safe_for": ["default_dependency_without_gate"]
  }
]
```

Include `numbagg`, `window-ops`, `scipy`, `polars`, and `pandas Rolling.rank` with similarly bounded roles.

- [ ] **Step 6: Add upgrade priority**

Emit:

```json
[
  {
    "rank": 1,
    "operators": ["rolling_corr", "rolling_cov"],
    "why": "groupby.apply rolling pairwise statistics likely high overhead and common in Alpha101-style formulas",
    "next_phase": "RTA-07B benchmark and parity harness"
  },
  {
    "rank": 2,
    "operators": ["ts_argmin", "ts_argmax"],
    "why": "rolling apply lambda is avoidable and semantics are narrow enough for numba/numpy parity",
    "next_phase": "RTA-07B candidate implementation"
  },
  {
    "rank": 3,
    "operators": ["ts_rank"],
    "why": "already has experimental candidate; needs benchmark across ties, NaNs, memory, and real panel shapes",
    "next_phase": "RTA-07B benchmark matrix"
  },
  {
    "rank": 4,
    "operators": ["ts_sum", "ts_mean", "ts_std", "ts_min", "ts_max"],
    "why": "medium-risk rolling reductions; benchmark before changing because pandas builtins may already be competitive",
    "next_phase": "RTA-07C optional dependency comparison"
  }
]
```

- [ ] **Step 7: Run CLI manually**

Run:

```bash
python3 scripts/run_factorforge_operator_kernel_inventory.py --output /tmp/factorforge_operator_kernel_inventory.json
```

Expected:
- exit code 0
- JSON `version` equals `factorforge_operator_kernel_inventory_v1`
- `current_execution_model.step3b_factor_values_use_qlib_native=false`
- diagnostics include `QLIB_NOT_FORMAL_OPERATOR_ENGINE`
- `canonical_pollution=false`

## Task 2: Add Performance Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add smoke case for CLI contract**

Add a case named:

```text
operator_kernel_inventory_contract
```

It must run:

```bash
python3 scripts/run_factorforge_operator_kernel_inventory.py --output /tmp/<fresh_root>/operator_kernel_inventory.json
```

Assert:
- `version == "factorforge_operator_kernel_inventory_v1"`
- `read_only is True`
- `current_execution_model.step3b_factor_values_use_qlib_native is False`
- diagnostics include `QLIB_NOT_FORMAL_OPERATOR_ENGINE`
- `operator_inventory` contains `ts_rank`, `ts_argmin`, `ts_argmax`, `rolling_corr`, `rolling_cov`

- [ ] **Step 2: Add smoke case for high-risk operator classification**

Add a case named:

```text
operator_kernel_inventory_flags_hotspots
```

Assert:
- `ts_argmin.performance_risk == "high"`
- `ts_argmax.performance_risk == "high"`
- `rolling_corr.performance_risk == "high"`
- `rolling_cov.performance_risk == "high"`
- `ts_rank.performance_risk == "high"`
- diagnostics include `OPERATOR_KERNEL_HOTSPOT_ROLLING_APPLY`
- diagnostics include `OPERATOR_KERNEL_HOTSPOT_GROUPBY_APPLY_CORR_COV`

- [ ] **Step 3: Add smoke case for TA-Lib classification**

Add a case named:

```text
operator_kernel_inventory_classifies_talib_as_factor_library
```

Assert:
- `optional_dependency_probe.talib.role == "factor_indicator_library"`
- `TA-Lib` exists in `library_landscape`
- TA-Lib `not_safe_for` includes `silent_replacement_of_formula_ir_rolling_semantics`
- diagnostics include `TA_LIB_FACTOR_LIBRARY_CANDIDATE`

- [ ] **Step 4: Add smoke case for non-/tmp output block**

Add a case named:

```text
operator_kernel_inventory_blocks_non_tmp_output_unless_explicit
```

Run without `--allow-non-tmp-output` against a repo-local output path such as:

```text
docs/.tmp_operator_kernel_inventory_should_block.json
```

Expected:
- non-zero exit
- stderr/stdout contains `BLOCK_OPERATOR_KERNEL_INVENTORY_NON_TMP_OUTPUT`
- file does not exist

Then run with `--allow-non-tmp-output` only inside a throwaway `/tmp` copied repo if needed; do not write repo-local files as a success path.

- [ ] **Step 5: Add smoke case for canonical pollution**

Add a case named:

```text
operator_kernel_inventory_no_canonical_pollution
```

Snapshot canonical directories before and after the CLI run, matching existing smoke helpers. Assert no files are added under:

```python
["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
```

## Task 3: Verification

**Files:**
- Compile: `scripts/run_factorforge_operator_kernel_inventory.py`
- Compile: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Compile**

Run:

```bash
python3 -m py_compile scripts/run_factorforge_operator_kernel_inventory.py scripts/run_factorforge_performance_smoke.py
```

Expected: exit code 0.

- [ ] **Step 2: Run focused smoke**

Run:

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07a_operator_inventory_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07A cases pass

- [ ] **Step 3: Inspect output JSON**

Run:

```bash
python3 scripts/run_factorforge_operator_kernel_inventory.py --output /tmp/factorforge_rta07a_operator_inventory.json
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/factorforge_rta07a_operator_inventory.json')
data = json.loads(p.read_text())
print(data['version'])
print(data['current_execution_model']['step3b_factor_values_use_qlib_native'])
print([x['operator'] for x in data['upgrade_priority'][0:3]])
print(data['canonical_pollution'])
PY
```

Expected output includes:

```text
factorforge_operator_kernel_inventory_v1
False
[['rolling_corr', 'rolling_cov'], ['ts_argmin', 'ts_argmax'], ['ts_rank']]
False
```

The operator list print should show the top three priority groups containing `rolling_corr/rolling_cov`, `ts_argmin/ts_argmax`, and `ts_rank`.

## Reviewer Checklist

Reviewer should verify:
- The script is read-only except for explicit `--output`.
- Non-`/tmp` output is blocked unless explicitly allowed.
- The inventory does not claim qlib is slow or bad; it only says qlib is not the formal factor-value execution path.
- TA-Lib is classified as a factor/indicator library candidate, not a silent replacement for Formula-IR primitives.
- High-risk operator classifications match actual current implementation.
- No production defaults changed.
- No clean data/search worker/official promotion path touched.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Path to generated `/tmp` inventory JSON.
- Performance smoke summary path.
- `py_compile` result.
- Whether optional dependencies were importable on the machine, but without installing any.
- Confirmation that no Step3B/Step4 execution semantics changed.
