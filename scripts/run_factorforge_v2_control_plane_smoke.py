#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import factorforgectl
from factor_factory.run_control import FactorForgeBlock


def assert_blocks(fn, expected_token: str) -> None:
    try:
        fn()
    except FactorForgeBlock as exc:
        assert exc.token == expected_token, (exc.token, expected_token, str(exc))
        return
    raise AssertionError(f"expected {expected_token}")


def main() -> int:
    assert factorforgectl.normalize_local_step("1") == "1"
    assert factorforgectl.normalize_local_step("step2") == "2"
    assert factorforgectl.normalize_local_step("3a") == "3a"

    assert_blocks(lambda: factorforgectl.normalize_local_step("6"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert_blocks(lambda: factorforgectl.normalize_local_step("step6"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")

    assert factorforgectl.local_prepare_end_step("1") == "1"
    assert factorforgectl.local_prepare_end_step("2") == "2"
    assert factorforgectl.local_prepare_end_step("3a") == "3a"

    assert factorforgectl.validate_local_step_range("1", "1") == ("1", "1")
    assert factorforgectl.validate_local_step_range("2", "2") == ("2", "2")
    assert factorforgectl.validate_local_step_range("2", "3a") == ("2", "3a")
    assert_blocks(lambda: factorforgectl.validate_local_step_range("1", "3a"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")
    assert_blocks(lambda: factorforgectl.validate_local_step_range("3a", "2"), "BLOCK_UNSUPPORTED_FACTORFORGECTL_STEP")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
