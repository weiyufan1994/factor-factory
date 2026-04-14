#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$ROOT/fixtures/step1/sample_factor_report.html"

cat <<EOF
Step 1 minimal reproducibility sample (design card)

Repository root: $ROOT
Expected fixture path: $FIXTURE

Current intended Python entry:
  from factorforge.modules.report_ingestion.orchestration.run_step1 import run_step1_for_html

Current intended call shape:
  run_step1_for_html(project_root=<repo_root>, html_path=<fixture_path>)

Success criterion:
  the sample run should write Step 1 artifacts equivalent in class to:
  - intake validation artifact
  - report_map artifact
  - alpha_thesis artifact
  - ambiguity_review artifact

Current status:
  placeholder command card only; fixture and exact runnable environment are not yet formalized.
EOF
