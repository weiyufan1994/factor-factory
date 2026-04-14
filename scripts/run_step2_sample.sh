#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF
Step 2 minimal reproducibility sample (design card)

Repository root: $ROOT
Expected future fixture root: $ROOT/fixtures/step2/

Current code entry in repo:
  skills/factor-forge-step2/scripts/run_step2.py

Current status:
  sample command card only; tiny committed Step 2 fixture is not yet formalized.

Success criterion:
  a reproducible Step 2 sample must produce the artifact class set:
  - factor_spec_master
  - primary raw spec artifact
  - challenger raw spec artifact
  - consistency audit artifact
  - Step 3 handoff artifact
EOF
