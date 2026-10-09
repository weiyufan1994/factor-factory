# Optional evaluation backends

Read for selecting/debugging the actual backend; these are capability limits,
not a requirement to install Qlib for ordinary research.

Current practical backend maturity:
- `self_quant_analyzer` quick mode produces signal diagnostics: IC, group-mean
  returns and turnover-based cost estimates. Its payload and Step5 archive mark
  `evaluation_scope=signal_diagnostic`, `account_simulation=false` and
  `tradable_net_alpha_evidence=false`. It does not simulate a cash/position ledger
  or blocked fills, even when the labels use delayed entry. Claims about
  executable net alpha require the research's explicitly selected account
  backend (for example, the PF/VV evaluator), with its separately evidenced
  valuation prices, calendar, costs and buy/sell constraints. A filtered clean
  signal view alone cannot establish that execution evidence.
- `qlib_backtest` now has both a sample-stub layer and a native minimal backtest path; native execution depends on qlib-friendly signal formatting, especially `instrument` / `datetime` semantics
- Qlib native requires the Microsoft Qlib package and a provider/store. A Python package named `qlib` is not sufficient; preflight must verify `qlib.init` plus `qlib.data.D`, and must skip native execution if a non-Microsoft `qlib` package is imported.
- Direct-code child revisions over derived intraday state may be outside qlib's
  native adapter surface. In that case Step3/Step6 must provide a child-local
  `qlib_adapter_config__{report_id}.json` with
  `qlib_native_status=not_applicable` and a reason such as
  `direct_code_derived_state_not_supported_by_qlib`; Step4 must record qlib as
  skipped/not_applicable, not failed because the qlib input config is missing.
- Standard Step4 evidence is mandatory. Agents must not fill missing Step4 evidence with ad hoc plotting scripts or one-off notebooks.

## Qlib configuration

Choose an explicit provider URI and, if needed, dedicated interpreter via
`FACTORFORGE_QLIB_PYTHON`/backend `qlib_python`. Verify `qlib.init` and
`qlib.data.D` in that same interpreter. The existing
`scripts/publish_qlib_daily_provider.py` converts already-clean data; publishing a
provider is a separately scoped operation, not an implicit evaluation side effect.
Report actual `qlib_native_status`: only `native_backtest_success` or explicitly
`native_minimal_success` establish their named execution. Data compatibility
or a skipped adapter does not establish native-account parity.
