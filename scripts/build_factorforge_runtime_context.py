#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context


def _run_validator(script_path: str, report_id: str, *, factorforge_root: Path) -> int:
    env = dict(__import__("os").environ, FACTORFORGE_ROOT=str(factorforge_root))
    result = subprocess.run(
        [sys.executable, script_path, "--report-id", report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the standard Factor Forge runtime context manifest.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--branch-id")
    parser.add_argument("--factorforge-root")
    parser.add_argument("--write", action="store_true", help="Write manifest under objects/runtime_context/.")
    args = parser.parse_args()

    ctx = resolve_factorforge_context(args.factorforge_root)
    report_id = args.report_id

    # Fix 3: runtime_context gate — only write when all upstream validators pass.
    # Step1 and Step2 must PASS before runtime_context is written.
    step1_rc = _run_validator(
        "skills/factor-forge-step1/scripts/validate_step1.py",
        report_id,
        factorforge_root=ctx.factorforge_root,
    )
    step2_rc = _run_validator(
        "skills/factor-forge-step2/scripts/validate_step2.py",
        report_id,
        factorforge_root=ctx.factorforge_root,
    )

    gate_passed = step1_rc == 0 and step2_rc == 0

    manifest = ctx.build_manifest(report_id, branch_id=args.branch_id)
    if args.write:
        if gate_passed:
            out = ctx.write_manifest(report_id, branch_id=args.branch_id)
            print(f"[WRITE] {out}")
        else:
            print(
                f"[BLOCK_RUNTIME_CONTEXT_WRITE] Step1 rc={step1_rc} Step2 rc={step2_rc} — "
                "runtime_context not written. Resolve BLOCK items before retry.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())