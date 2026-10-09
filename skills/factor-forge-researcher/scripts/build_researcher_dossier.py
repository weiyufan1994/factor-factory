#!/usr/bin/env python3
"""Compatibility CLI; use factor_factory.step6.journal from Python."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.step6.journal import (
    build_researcher_dossier,
    collect_object_files,
    collect_generated_code,
    collect_run_files,
    collect_evaluations,
    load_json,
    file_info,
    compact,
    main,
)


if __name__ == "__main__":
    main()
