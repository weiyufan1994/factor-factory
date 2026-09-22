from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from factor_factory.implementation_runtime import expects_polars, invoke_factor


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem + "_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["step3", "step4"])
def runner(request):
    name = "run_step3b.py" if request.param == "step3" else "run_step4.py"
    return load(ROOT / "skills" / ("factor-forge-" + request.param) / "scripts" / name)


@pytest.fixture
def frames():
    daily = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240110"], "close": [2.]})
    return daily, daily.assign(close=7.)


def test_body_typeerror_is_not_retried_or_hidden(runner, frames):
    calls = []
    original_error = TypeError("invalid factor operand")

    def compute_factor(daily_df, minute_df=None):
        calls.append(True)
        if len(calls) == 1:
            raise original_error
        return daily_df.assign(factor_value=999.)

    with pytest.raises(TypeError) as failure:
        runner.compute_factor_with_contract(SimpleNamespace(compute_factor=compute_factor), *frames)
    assert failure.value is original_error
    assert len(calls) == 1


def test_keyword_only_minute_argument_is_delivered(runner, frames):
    def compute_factor(daily_df, *, minute_df=None):
        assert minute_df is not None
        return daily_df.assign(factor_value=daily_df.close + 10 * minute_df.close)

    result = runner.compute_factor_with_contract(SimpleNamespace(compute_factor=compute_factor), *frames)
    assert result.factor_value.tolist() == [72.]


@pytest.mark.parametrize("header,expression,expected", [
    ("daily_df, minute_df=None", "daily_df.close + 10 * minute_df.close", 72.),
    ("*, daily_df, minute_df", "daily_df.close + 10 * minute_df.close", 72.),
    ("daily_df, /, *, minute_df", "daily_df.close + 10 * minute_df.close", 72.),
    ("minute, daily, /", "daily.close + 10 * minute.close", 72.),
    ("daily_df", "daily_df.close", 2.),
    ("*, minute_df", "minute_df.close", 7.),
    ("intraday", "intraday.close", 7.),
    ("df", "df.close", 7.),
    ("df, *, minute_df", "df.close + 10 * minute_df.close", 72.),
    ("minute_df=None, /, daily_df=None", "daily_df.close + 10 * minute_df.close", 72.),
    ("daily_df=None, /, *, minute_df=None", "daily_df.close + 10 * minute_df.close", 72.),
    ("df=None, *, minute_df=None", "df.close + 10 * minute_df.close", 72.),
    ("daily_df=None, intraday=None", "daily_df.close + 10 * intraday.close", 72.),
    ("daily_df=None, window=3", "daily_df.close * window", 6.),
    ("daily_df=None, /, **kwargs", "daily_df.close + 10 * kwargs['minute_df'].close", 72.),
    ("daily_df=None, /, window=3, *, minute_df=None", "daily_df.close * window + 10 * minute_df.close", 76.),
    ("df, window=3", "df.close * window", 21.),
])
def test_legacy_binding_and_generated_adapter_agree(header, expression, expected, frames):
    stage3 = load(ROOT / "skills/factor-forge-step3/scripts/run_step3b.py")
    source = f"def compute_factor({header}):\n    return {expression}\n"
    raw = {}; exec(source, raw)
    adapted = {}; exec(stage3.ensure_direct_code_keyword_adapter(source), adapted)
    assert invoke_factor(raw["compute_factor"], *frames).tolist() == [expected]
    assert adapted["compute_factor"](daily_df=frames[0], minute_df=frames[1]).tolist() == [expected]


def test_unbindable_signature_does_not_execute(frames):
    calls = []

    def compute_factor(daily_df, minute_df, required_third):
        calls.append(True)

    with pytest.raises(TypeError, match="BLOCK_FACTOR_IMPLEMENTATION_SIGNATURE_MISMATCH"):
        invoke_factor(compute_factor, *frames)
    assert calls == []


def test_numpy_select_and_comments_do_not_switch_dataframe_backend(runner, frames, tmp_path):
    path = tmp_path / "numpy_factor.py"
    path.write_text(
        "import numpy as np\n"
        "# Polars examples: frame.with_columns(pl.col('close')); frame.lazy()\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    return daily_df.assign(factor_value=np.select([daily_df.close > 0], [daily_df.close], default=0.))\n"
    )
    module = load(path)
    assert runner.direct_code_expects_polars(module) is False
    assert runner.compute_factor_with_contract(module, *frames).factor_value.tolist() == [2.]


def test_polars_alias_executes_consistently_in_both_stages(runner, frames, tmp_path):
    pytest.importorskip("polars")
    path = tmp_path / "polars_factor.py"
    path.write_text(
        "import polars as px\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    return daily_df.with_columns((px.col('close') * 3).alias('factor_value'))\n"
    )
    module = load(path)
    assert runner.direct_code_expects_polars(module) is True
    assert runner.compute_factor_with_contract(module, *frames).factor_value.tolist() == [6.]


def test_explicit_pandas_input_allows_internal_polars_conversion(runner, frames, tmp_path):
    pytest.importorskip("polars")
    path = tmp_path / "mixed_libraries.py"
    path.write_text(
        "import polars as pl\n"
        "METADATA = {'input_dataframe_backend': 'pandas'}\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    temp = daily_df.assign(factor_value=daily_df.close * 4)\n"
        "    return pl.from_pandas(temp).select('ts_code', 'trade_date', 'factor_value')\n"
    )
    assert runner.compute_factor_with_contract(load(path), *frames).factor_value.tolist() == [8.]


def test_unknown_explicit_backend_blocks_before_execution():
    with pytest.raises(ValueError, match="BLOCK_FACTOR_INPUT_DATAFRAME_BACKEND_INVALID"):
        expects_polars(SimpleNamespace(METADATA={"input_dataframe_backend": "guess"}))


def test_unused_polars_helper_and_pandas_filter_do_not_change_inputs(runner, frames, tmp_path):
    pytest.importorskip("polars")
    path = tmp_path / "pandas_with_unused_helper.py"
    path.write_text(
        "import polars as pl\n"
        "def unused_helper(frame):\n"
        "    return frame.with_columns(pl.col('close').alias('factor_value'))\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    return daily_df.filter(items=['ts_code', 'trade_date', 'close']).assign(factor_value=daily_df.close)\n"
    )
    module = load(path)
    assert runner.direct_code_expects_polars(module) is False
    assert runner.compute_factor_with_contract(module, *frames).factor_value.tolist() == [2.]


def test_called_polars_helper_still_selects_polars(runner, frames, tmp_path):
    pytest.importorskip("polars")
    path = tmp_path / "polars_helper.py"
    path.write_text(
        "import polars as pl\n"
        "def add_signal(frame):\n"
        "    return frame.with_columns(pl.col('close').alias('factor_value'))\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    return add_signal(daily_df)\n"
    )
    module = load(path)
    assert runner.direct_code_expects_polars(module) is True
    assert runner.compute_factor_with_contract(module, *frames).factor_value.tolist() == [2.]


def test_validator_distinguishes_factor_body_failure_from_signature(tmp_path):
    validator = load(ROOT / "skills/factor-forge-step3/scripts/validate_step3b.py")
    path = tmp_path / "factor_error.py"
    path.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    raise TypeError('invalid factor operand')\n"
    )
    with pytest.raises(AssertionError, match="BLOCK_DIRECT_CODE_FIXTURE_EXECUTION_FAILED") as failure:
        validator.run_direct_code_fixture_smoke(path, {"columns": ["ts_code", "trade_date", "factor_value"]})
    assert isinstance(failure.value.__cause__, TypeError)
    assert "invalid factor operand" in str(failure.value.__cause__)


def test_validator_accepts_numpy_select_without_polars_conversion(tmp_path):
    validator = load(ROOT / "skills/factor-forge-step3/scripts/validate_step3b.py")
    path = tmp_path / "numpy_smoke.py"
    path.write_text(
        "import numpy as np\n"
        "def compute_factor(daily_df, minute_df=None):\n"
        "    return daily_df[['ts_code','trade_date']].assign(factor_value=np.select([daily_df.close > 0], [daily_df.close], default=0.))\n"
    )
    validator.run_direct_code_fixture_smoke(path, {"columns": ["ts_code", "trade_date", "factor_value"]})
