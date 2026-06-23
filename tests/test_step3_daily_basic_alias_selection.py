import importlib.util
from pathlib import Path


def _load_run_step3():
    path = Path(__file__).resolve().parents[1] / "skills" / "factor-forge-step3" / "scripts" / "run_step3.py"
    spec = importlib.util.spec_from_file_location("factorforge_step3_run_step3", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_daily_basic_alias_selection_maps_turnover_to_turnover_rate():
    run_step3 = _load_run_step3()
    fields = run_step3.select_daily_basic_fields_for_required_formula_fields(["turnover"])

    assert fields == ["ts_code", "trade_date", "turnover_rate"]


def test_rank_formula_requires_cross_sectional_sample_universe():
    run_step3 = _load_run_step3()
    formula_ir = {
        "root": {
            "type": "operator",
            "operator": "rank",
            "args": [{"type": "field", "name": "amount", "resolved_field": "amount"}],
        }
    }

    assert run_step3.requires_cross_sectional_sample(formula_ir) is True
