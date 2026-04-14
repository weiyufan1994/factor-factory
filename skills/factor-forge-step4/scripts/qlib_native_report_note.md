# qlib native backtest status note

- CPV native qlib minimal chain has been verified with:
  - qlib.init(provider_uri=/home/ubuntu/.qlib/qlib_data/cn_data, region=cn)
  - TopkDropoutStrategy
  - SimulatorExecutor
  - backtest(...)
- Critical adapter fix applied:
  - instrument normalization `000001.SZ -> SZ000001`
  - signal MultiIndex level names set to `[datetime, instrument]`
- Evidence from verified probe:
  - sample qlib close rows: 120
  - close nonnull ratio: 1.0
  - nonzero value rows: 19
  - nonzero turnover rows: 19
  - mean return: 0.0012296318699843234

This note is an engineering status note, not the final backend payload.
Next cleanup targets:
- write native qlib metrics + plots into formal backend payload
- reduce remaining warnings from exchange/data alignment and pandas groupby apply
- freeze user-confirmable run parameters before wider/native production runs
