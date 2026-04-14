#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF
Step 3 minimal reproducibility sample (design card)

Repository root: $ROOT
Expected future fixture root: $ROOT/fixtures/step3/

Current code entry in repo:
  skills/factor-forge-step3/scripts/run_step3.py
  skills/factor-forge-step3/scripts/run_step3b.py

Current status:
  sample command card only; tiny committed Step 3 fixture is not yet formalized.

Success criterion:
  a reproducible Step 3 sample must produce the artifact class set:
  - data_prep_master
  - qlib_adapter_config
  - implementation_plan_master
  - generated/editable code artifact
  - Step 4 handoff artifact
EOF
