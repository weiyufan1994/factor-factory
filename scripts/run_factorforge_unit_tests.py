#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_TESTS = [
    "tests/test_factorforge_data_api.py",
    "tests/test_step3_readiness_contract.py",
    "tests/test_step3b_direct_code_contract.py",
    "tests/test_mechanism_math_dirac_review.py",
]


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_test(func) -> None:
    params = inspect.signature(func).parameters
    kwargs = {}
    with tempfile.TemporaryDirectory(prefix="factorforge_test_") as tmp:
        if "tmp_path" in params:
            kwargs["tmp_path"] = Path(tmp)
        func(**kwargs)


def main() -> None:
    raw_paths = sys.argv[1:] or DEFAULT_TESTS
    results = []
    for raw in raw_paths:
        path = (REPO_ROOT / raw).resolve()
        module = _load_module(path)
        for name, func in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(func):
                continue
            record = {"test": f"{path.relative_to(REPO_ROOT)}::{name}", "ok": False}
            try:
                _call_test(func)
                record["ok"] = True
            except Exception as exc:
                record["error"] = repr(exc)
                record["traceback"] = traceback.format_exc()
            results.append(record)

    summary = {
        "total": len(results),
        "passed": sum(1 for item in results if item["ok"]),
        "failed": [item for item in results if not item["ok"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
