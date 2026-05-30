from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_validate_step3b():
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/validate_step3b.py"
    spec = importlib.util.spec_from_file_location("validate_step3b_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_direct_code_smoke_blocks_positional_only_signature(tmp_path):
    validate_step3b = _load_validate_step3b()
    impl = tmp_path / "bad_positional.py"
    impl.write_text(
        "import pandas as pd\n"
        "def compute_factor(df):\n"
        "    return pd.DataFrame({'ts_code':['000001.SZ'], 'trade_date':['20260101'], 'factor_value':[1.0]})\n",
        encoding="utf-8",
    )

    try:
        validate_step3b.run_direct_code_fixture_smoke(impl, {"columns": ["ts_code", "trade_date", "factor_value"]})
    except AssertionError as exc:
        assert "BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH" in str(exc)
    else:
        raise AssertionError("expected positional-only compute_factor to fail")


def test_direct_code_smoke_blocks_all_null_signal(tmp_path):
    validate_step3b = _load_validate_step3b()
    impl = tmp_path / "all_null.py"
    impl.write_text(
        "import pandas as pd\n"
        "def compute_factor(*, daily_df, minute_df=None):\n"
        "    return pd.DataFrame({'ts_code':['000001.SZ'], 'trade_date':['20260101'], 'factor_value':[None]})\n",
        encoding="utf-8",
    )

    try:
        validate_step3b.run_direct_code_fixture_smoke(impl, {"columns": ["ts_code", "trade_date", "factor_value"]})
    except AssertionError as exc:
        assert "BLOCK_STEP3B_DIRECT_CODE_ALL_NULL_OUTPUT" in str(exc)
    else:
        raise AssertionError("expected all-null factor_value to fail")


def test_direct_code_smoke_accepts_keyword_interface_with_non_null_signal(tmp_path):
    validate_step3b = _load_validate_step3b()
    impl = tmp_path / "valid_keyword.py"
    impl.write_text(
        "import pandas as pd\n"
        "def compute_factor(*, daily_df, minute_df=None):\n"
        "    df = daily_df.copy()\n"
        "    return pd.DataFrame({'ts_code': df['ts_code'].head(2), 'trade_date': df['trade_date'].head(2), 'factor_value': [1.0, 2.0]})\n",
        encoding="utf-8",
    )

    validate_step3b.run_direct_code_fixture_smoke(impl, {"columns": ["ts_code", "trade_date", "factor_value"]})
