#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.mechanism_math.main_agent_memo import validate_main_agent_mechanism_memo

OBJ = FF / "objects"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-id", required=True)
    args = ap.parse_args()
    rid = args.report_id
    memo_path = OBJ / "research_iteration_master" / f"main_agent_mechanism_memo__{rid}.json"
    spec_path = OBJ / "factor_spec_master" / f"factor_spec_master__{rid}.json"
    if not memo_path.exists():
        print("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING: " + str(memo_path), file=sys.stderr)
        raise SystemExit(1)
    memo = load_json(memo_path)
    spec = load_json(spec_path) if spec_path.exists() else {}
    failures = validate_main_agent_mechanism_memo(memo, spec)
    result = {
        "report_id": rid,
        "memo_path": str(memo_path),
        "result": "PASS" if not failures else "BLOCK",
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if failures:
        print(";".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
