#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

PLACEHOLDER_TOKENS = {"", "TODO", "TBD", "PLACEHOLDER", "placeholder", "todo", "tbd", None}

CORE_SCRIPT_MARKERS = {
    "skills/factor-forge-step3/scripts/run_step3.py": [
        "COMMENT_POLICY: runtime_path",
        "COMMENT_POLICY: execution_handoff",
    ],
    "skills/factor-forge-step3/scripts/run_step3b.py": [
        "COMMENT_POLICY: runtime_path",
        "COMMENT_POLICY: execution_handoff",
    ],
    "skills/factor-forge-step4/scripts/run_step4.py": [
        "COMMENT_POLICY: runtime_path",
        "COMMENT_POLICY: execution_handoff",
        "COMMENT_POLICY: backend_extensibility",
    ],
}

FACTOR_IMPL_ANCHORS = ["# CONTEXT:", "# CONTRACT:", "# RISK:"]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def is_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return value.strip() in PLACEHOLDER_TOKENS
    return value in PLACEHOLDER_TOKENS


def resolve_factor_impl_path(repo_root: Path, report_id: str) -> tuple[Path | None, str]:
    handoff_path = repo_root / "objects" / "handoff" / f"handoff_to_step4__{report_id}.json"
    if handoff_path.exists():
        handoff = json.loads(load_text(handoff_path))
        for key in ("factor_impl_ref", "factor_impl_stub_ref", "implementation_path"):
            raw = handoff.get(key)
            if is_placeholder(raw):
                continue
            candidate = (repo_root / str(raw)).resolve()
            if candidate.exists():
                return candidate, f"handoff:{key}"

    candidates = [
        repo_root / "generated_code" / report_id / f"factor_impl__{report_id}.py",
        repo_root / "generated_code" / report_id / f"factor_impl_stub__{report_id}.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate, "fallback:generated_code"
    return None, "not_found"


def check_core_scripts(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for rel_path, markers in CORE_SCRIPT_MARKERS.items():
        path = repo_root / rel_path
        if not path.exists():
            errors.append(f"missing core script: {rel_path}")
            continue
        content = load_text(path)
        for marker in markers:
            if marker not in content:
                errors.append(f"{rel_path} missing marker `{marker}`")
    return errors


def check_factor_impl(repo_root: Path, report_id: str) -> tuple[list[str], Path | None, str]:
    errors: list[str] = []
    impl_path, source = resolve_factor_impl_path(repo_root, report_id)
    if impl_path is None:
        errors.append(
            f"factor implementation file not found for report_id={report_id}; expected generated_code/{report_id}/factor_impl__{report_id}.py "
            f"or factor_impl_stub__{report_id}.py"
        )
        return errors, None, source

    content = load_text(impl_path)
    for anchor in FACTOR_IMPL_ANCHORS:
        if anchor not in content:
            errors.append(f"{impl_path.relative_to(repo_root)} missing anchor `{anchor}`")
    return errors, impl_path, source


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce Step3/4 commenting policy.")
    parser.add_argument("--report-id", required=True, help="Report id used to resolve generated factor implementation file.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    errors: list[str] = []
    errors.extend(check_core_scripts(repo_root))
    impl_errors, impl_path, impl_source = check_factor_impl(repo_root, args.report_id)
    errors.extend(impl_errors)

    print("[INFO] Step3/4 commenting policy check")
    print(f"[INFO] report_id={args.report_id}")
    if impl_path is not None:
        print(f"[INFO] factor_impl={impl_path.relative_to(repo_root)} ({impl_source})")
    else:
        print(f"[INFO] factor_impl=unresolved ({impl_source})")

    if errors:
        print("[FAIL] Commenting policy violations:")
        for item in errors:
            print(f"  - {item}")
        raise SystemExit(1)

    print("[PASS] Commenting policy satisfied.")


if __name__ == "__main__":
    main()
