# V19 return-volume universe split cached200 toy test

Date: 2026-06-12

## Scope

This is a research-side toy test for V19 value-occupation repair signals with return-volume covariation. It uses the available minute-cache overlap only, not a full-window production conclusion.

- Output S3: `s3://yufan-data-lake/factorforge/tmp/vp_v19_20260612/universe_cached200_core/`
- Local output: `/tmp/factorforge_vp_v19_universe_cached200_core_local_20260612/`
- SSM command: `ca4c05ec-056e-452f-964f-e20edc6ebe94`
- Worker: `i-02cc0b6e93856fbb4`
- VP datamart: `intraday_value_occupation_state_v1`
- Index universe datamart: `index_weight_universe/v1`
- Minute feature mode: cached minute overlap, `available_minute_only=1`, `max_dates=200`

Coverage:

- VP sampled rows: 1,037,840
- Return-volume feature rows: 1,037,900
- Merged rows: 880,086
- Merged dates: 200
- Merged tickers: 4,953
- Index universe loaded dates in this sample: 192/200

## Signals

Core signals:

- `v18_repair_drift_score`
- `v19_rv_corr_repair`
- `v19_upside_confirmed_repair`

Small-cap size-neutral versions were generated only for `fixed_small_20`:

- `v18_repair_drift_score__sn_fixed_small_20`
- `v19_rv_corr_repair__sn_fixed_small_20`
- `v19_upside_confirmed_repair__sn_fixed_small_20`

Do not interpret `__sn_fixed_small_20` rows outside `fixed_small_20`; the signal is non-null only on the fixed-small sub-sample.

Controls for residual IC:

- `ln_total_mv`
- `drift_1d_to_cutoff`
- `mom_5d_to_cutoff`
- `mom_20d_to_cutoff`
- `turnover_rate`
- `vol_20d`

## 5D Core Result

All values are from `period=all`, 20 bps one-way cost proxy applied through top-decile turnover.

| Universe | Signal | Rank IC | Residual IC | Top excess | Net top excess | Hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `csi800` | `v18_repair_drift_score` | 0.039192 | 0.012874 | 0.002278 | 0.001275 | 0.598958 |
| `csi800` | `v19_rv_corr_repair` | 0.038698 | 0.014869 | 0.002403 | 0.001306 | 0.593750 |
| `csi800` | `v19_upside_confirmed_repair` | 0.038079 | 0.013808 | 0.002512 | 0.001387 | 0.604167 |
| `csi800_csi1000` | `v18_repair_drift_score` | 0.034691 | 0.007075 | 0.001512 | 0.000533 | 0.630208 |
| `csi800_csi1000` | `v19_rv_corr_repair` | 0.032145 | 0.008552 | 0.001633 | 0.000568 | 0.593750 |
| `csi800_csi1000` | `v19_upside_confirmed_repair` | 0.031338 | 0.008468 | 0.001490 | 0.000374 | 0.593750 |
| `csi2000` | `v18_repair_drift_score` | 0.060240 | 0.006279 | 0.001989 | 0.001073 | 0.583333 |
| `csi2000` | `v19_rv_corr_repair` | 0.049765 | 0.003650 | 0.001676 | 0.000657 | 0.609375 |
| `csi2000` | `v19_upside_confirmed_repair` | 0.043657 | 0.001259 | 0.001177 | 0.000055 | 0.609375 |
| `csi_all_share` | `v18_repair_drift_score` | 0.043121 | 0.006503 | 0.001004 | 0.000070 | 0.578125 |
| `csi_all_share` | `v19_rv_corr_repair` | 0.035743 | 0.005509 | 0.000571 | -0.000456 | 0.578125 |
| `csi_all_share` | `v19_upside_confirmed_repair` | 0.032247 | 0.003826 | 0.000392 | -0.000714 | 0.567708 |
| `largest_10` | `v18_repair_drift_score` | 0.048458 | 0.015078 | 0.002316 | 0.001276 | 0.590000 |
| `largest_10` | `v19_rv_corr_repair` | 0.047132 | 0.016492 | 0.002827 | 0.001708 | 0.615000 |
| `largest_10` | `v19_upside_confirmed_repair` | 0.047071 | 0.015540 | 0.002715 | 0.001568 | 0.600000 |
| `fixed_small_20` | `v18_repair_drift_score` | 0.056311 | 0.006960 | 0.002928 | 0.001962 | 0.565000 |
| `fixed_small_20` | `v19_rv_corr_repair` | 0.046061 | 0.004012 | 0.002440 | 0.001383 | 0.555000 |
| `fixed_small_20` | `v19_upside_confirmed_repair` | 0.037861 | 0.000510 | 0.001274 | 0.000107 | 0.550000 |

## Small-Cap Size-Neutral Check

`fixed_small_20` definition: use `circ_mv` when positive, otherwise `total_mv`; require market cap >= 50000 in Tushare units; drop daily bottom 10%; then take the smallest 20% among eligible names.

| Horizon | Signal | Rank IC | Residual IC | Net top excess |
| --- | --- | ---: | ---: | ---: |
| 1D | `v18_repair_drift_score` | 0.040443 | 0.005814 | -0.000073 |
| 1D | `v18_repair_drift_score__sn_fixed_small_20` | 0.040582 | 0.005712 | -0.000081 |
| 3D | `v18_repair_drift_score` | 0.052960 | 0.008202 | 0.001152 |
| 3D | `v18_repair_drift_score__sn_fixed_small_20` | 0.053062 | 0.008098 | 0.001124 |
| 5D | `v18_repair_drift_score` | 0.056311 | 0.006960 | 0.001962 |
| 5D | `v18_repair_drift_score__sn_fixed_small_20` | 0.056530 | 0.007151 | 0.002056 |
| 5D | `v19_rv_corr_repair` | 0.046061 | 0.004012 | 0.001383 |
| 5D | `v19_rv_corr_repair__sn_fixed_small_20` | 0.046072 | 0.004144 | 0.001746 |

The fixed-small result does not disappear after one-dimensional log-size neutralization. However, this is still a toy sample and does not prove robustness to full microstructure, liquidity, industry, and risk-model controls.

## Interpretation

The result does not support a simple monotonic claim that larger universe is always stronger.

- Breadth / Rank IC is stronger in `csi2000` and `fixed_small_20`.
- Residual IC and long-side quality are stronger in `largest_10` / `csi800`.
- Adding return-volume covariation is useful mainly in large-cap style universes: `largest_10` improves 5D residual IC from 0.015078 to 0.016492 and net top excess from 0.001276 to 0.001708 under `v19_rv_corr_repair`; `csi800` improves long-side net slightly under `v19_upside_confirmed_repair`.
- Adding return-volume covariation hurts broad and smaller universes in this cached200 run; V18 baseline remains the more stable body there.

Economic reading: large-cap/institutional-participation ecology is consistent with the residual and long-side improvements, but this test does not prove that mutual funds or national-team-like players are the direct mechanism. A safer statement is that value-occupation repair plus return-volume confirmation appears more aligned with high-participation, lower-noise order-flow environments; in small caps, the value-domain repair body still works, but return-volume confirmation may be more contaminated by liquidity and retail/microcap effects.

## Run Notes

An earlier wide run generated size-neutral signals for every universe and expanded the evaluation matrix too far. It was stopped after no metrics were written within the observation window. The core run above completed successfully and uploaded all artifacts.

Local validation before worker dispatch:

- `python3 -m py_compile factor_research/vp_v19_return_volume_20260612/scripts/research_vp_v19_return_volume_eval.py`
- `bash -n factor_research/vp_v19_return_volume_20260612/scripts/run_vp_v19_worker.sh`
- `git diff --check -- factor_research/vp_v19_return_volume_20260612/scripts/research_vp_v19_return_volume_eval.py factor_research/vp_v19_return_volume_20260612/scripts/run_vp_v19_worker.sh`

The core result is for direction-finding only. A full-window test requires either broader minute feature coverage or a production return-volume state datamart.
