# Factor Forge Alpha101 Standard Field Contract

## Purpose

Alpha101-style formulas often use semantic fields such as `volume`, `returns`,
`vwap`, and `adv20`, while clean daily inputs may expose `vol`, `amount`,
`pct_chg`, `close`, and `pre_close`. This document defines the Step2 -> Step3A
-> Step4 contract for those fields.

## Contract

Step2 must emit `standard_formula_fields_contract` when Formula-IR/operator or
hybrid formulas reference standard fields:

- `volume <- vol`
- `returns <- pct_chg / 100`, or `close / pre_close - 1`
- `vwap <- amount / volume` with unit policy recorded
- `advN <- rolling mean(volume, N)` with no-future-data policy

Step3A must materialize the required fields into the report-local daily
snapshot, or write a blocked/Step4 Data API status that downstream validators can
enforce. Step3B and Step4 must consume declared fields rather than guessing raw
aliases independently.

## BLOCK Tokens

- `BLOCK_STANDARD_FORMULA_FIELDS_MISSING`
- `BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING`
- `BLOCK_STEP3A_STANDARD_FIELD_NOT_MATERIALIZED`
- `BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING`

## Boundary

This contract derives formula-standard fields from already-clean data. It does
not authorize per-factor raw data cleaning, S3 discovery, or factor-value
execution in Step3A.
