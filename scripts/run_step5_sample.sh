#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF
Step 5 minimal reproducibility sample (design card)

Repository root: $ROOT
Expected future fixture root: $ROOT/fixtures/step5/

Current code entry in repo:
  skills/factor-forge-step5/scripts/run_step5.py
  skills/factor-forge-step5/scripts/validate_step5.py

Current status:
  sample command card only; tiny committed Step 5 fixture is not yet formalized.

Success criterion:
  a reproducible Step 5 sample must produce the artifact class set:
  - factor_case_master
  - factor_evaluation
  - archive bundle (or explicitly documented tiny archive substitute)
EOF
