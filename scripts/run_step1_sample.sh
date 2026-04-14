#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[INFO] repo_root=$ROOT"
echo "[INFO] fixture_html=$ROOT/fixtures/step1/sample_factor_report.html"
echo "[INFO] fixture_intake=$ROOT/fixtures/step1/sample_intake_response.json"

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" "$ROOT/scripts/run_step1_sample.py"
