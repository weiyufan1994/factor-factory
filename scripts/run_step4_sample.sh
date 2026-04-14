#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF
Step 4 minimal reproducibility sample (design card)

Repository root: $ROOT
Expected future fixture root: $ROOT/fixtures/step4/

Current code entry in repo:
  skills/factor-forge-step4/scripts/run_step4.py
  skills/factor-forge-step4/scripts/validate_step4.py

Current status:
  sample command card only; tiny committed Step 4 fixture is not yet formalized.

Success criterion:
  a reproducible Step 4 sample must produce the artifact class set:
  - factor_run_master
  - factor_run_diagnostics
  - handoff_to_step5
  - optional backend outputs from a tiny controlled fixture
EOF
