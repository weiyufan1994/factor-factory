"""Pure calendar/evaluation services, compatibility and dependency direction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from factor_factory.data_access import calendar_snapshot as snapshot
from factor_factory.data_access.calendar import get_trade_calendar
from factor_factory.data_access.paths import LocalTusharePaths
from factor_factory.evaluation_contract import build_web_evaluation_contract, stable_json_hash


DATES = ["2025-01-02", "2025-01-03", "2025-01-06"]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calendar(tmp_path, *, exchange=True):
    path = tmp_path / "calendar.csv"
    rows = {"cal_date": ["20250102", "20250103", "20250104", "20250106"],
            "is_open": [1, 1, 0, 1]}
    if exchange:
        rows["exchange"] = ["SSE"] * 4
    pd.DataFrame(rows).to_csv(path, index=False)
    registry_path = tmp_path / "registry.json"
    registry = {"snapshots": [{
        "snapshot_id": "SYNTHETIC", "scope": "production", "date_count": 3,
        "date_min": DATES[0], "date_max": DATES[-1], "raw_file_sha256": _digest(path),
        "open_dates_sha256": hashlib.sha256(json.dumps(DATES, separators=(",", ":")).encode()).hexdigest(),
    }]}
    registry_path.write_text(json.dumps(registry))
    return path, registry, {
        "registry_path": registry_path, "registry_sha256": _digest(registry_path),
        "snapshot_id": "SYNTHETIC", "registry_git_commit": "fixture-commit",
        "registry_git_blob": "fixture-blob", "workspace_root": tmp_path / "study",
    }


@pytest.mark.parametrize("exchange", [True, False])
def test_registered_calendar_matches_reader_with_optional_constant_column(tmp_path, exchange):
    path, _, options = _calendar(tmp_path, exchange=exchange)
    observed = snapshot.read_calendar_snapshot(path, **options)
    assert observed == {
        "path": path.resolve(), "dates": DATES,
        "open_dates_sha256": hashlib.sha256(json.dumps(DATES, separators=(",", ":")).encode()).hexdigest(),
        "raw_file_sha256": _digest(path), "registry_sha256": options["registry_sha256"],
        "registry_git_commit": "fixture-commit", "registry_git_blob": "fixture-blob",
        "snapshot_id": "SYNTHETIC",
    }
    paths = LocalTusharePaths(tmp_path, path, path, tmp_path, path, path, path, path,
                            trade_calendar_exchange="SSE")
    ordinary = get_trade_calendar(exchange="SSE", open_only=True, columns=["cal_date"], paths=paths)
    assert ordinary["cal_date"].tolist() == [date.replace("-", "") for date in DATES]


@pytest.mark.parametrize("mutation, error", [
    ("duplicate", "not canonical"), ("reorder", "not canonical"),
    ("invalid_date", "dates invalid"), ("empty", "dates invalid"),
    ("missing_day", "untrusted"), ("raw_changed", "untrusted"),
    ("missing_columns", "missing cal_date/is_open"),
    ("missing_file", "trusted calendar missing"),
])
def test_dates_and_raw_bytes_are_both_checked(tmp_path, mutation, error):
    path, _, options = _calendar(tmp_path)
    frame = pd.read_csv(path)
    if mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]])
    elif mutation == "reorder":
        frame = frame.iloc[::-1]
    elif mutation == "invalid_date":
        frame.loc[0, "cal_date"] = 20259999
    elif mutation == "empty":
        frame["is_open"] = 0
    elif mutation == "missing_day":
        frame = frame.iloc[1:]
    elif mutation == "missing_columns":
        frame = frame.drop(columns="is_open")
    frame.to_csv(path, index=False)
    if mutation == "raw_changed":
        path.write_text(path.read_text() + "\n")
    if mutation == "missing_file":
        path = tmp_path / "absent.csv"
    with pytest.raises(ValueError, match=error):
        snapshot.read_calendar_snapshot(path, **options)


@pytest.mark.parametrize("mutation", ["hash", "missing", "duplicate", "nonproduction"])
def test_registry_and_exact_snapshot_match(tmp_path, mutation):
    path, registry, options = _calendar(tmp_path)
    if mutation == "missing":
        registry["snapshots"] = []
    elif mutation == "duplicate":
        registry["snapshots"] *= 2
    elif mutation == "nonproduction":
        registry["snapshots"][0]["scope"] = "candidate"
    options["registry_path"].write_text(json.dumps(registry) + "\n")
    if mutation != "hash":
        options["registry_sha256"] = _digest(options["registry_path"])
    with pytest.raises(ValueError, match="registry diverged" if mutation == "hash" else "snapshot invalid"):
        snapshot.read_calendar_snapshot(path, **options)


@pytest.mark.parametrize("alias", [False, True])
def test_workspace_calendar_is_not_an_independent_snapshot(tmp_path, alias):
    path, _, options = _calendar(tmp_path)
    options["workspace_root"] = tmp_path
    if alias:
        linked = tmp_path / "alias.csv"
        linked.symlink_to(path)
        path = linked
    with pytest.raises(ValueError, match="not independent"):
        snapshot.read_calendar_snapshot(path, **options)


def test_old_console_entry_uses_new_calendar_service(tmp_path, monkeypatch):
    from factor_factory.console import web_factor_proof as web
    path, _, options = _calendar(tmp_path)
    monkeypatch.setenv("FACTORFORGE_TRUSTED_TRADE_CAL_CSV", str(path))
    for name, key in [
        ("TRADING_CALENDAR_REGISTRY_PATH", "registry_path"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_SHA256", "registry_sha256"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_COMMIT", "registry_git_commit"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_BLOB", "registry_git_blob"),
        ("CALENDAR_SNAPSHOT_ID", "snapshot_id"),
    ]:
        monkeypatch.setattr(snapshot, name, options[key])
    assert web._trusted_calendar_snapshot(workspace_root=options["workspace_root"]) == snapshot.read_calendar_snapshot(path, **options)
    assert web.validate_trusted_calendar_snapshot is snapshot.validate_trusted_calendar_snapshot


@pytest.mark.parametrize("claim,controls", [
    ("risk_premium", ["total_mv", "turnover_rate"]),
    ("liquidity_rent", ["pct_chg", "turnover_rate", "ln_mcap_free", "volume_ratio"]),
    ("unknown", []),
])
def test_evaluation_fields_units_and_timing_unchanged(claim, controls):
    from factor_factory.console.web_research_plan import build_web_evaluation_contract as old
    assert old is build_web_evaluation_contract
    plan = {
        "research_object": {"rebalance_frequency": "daily"},
        "data_plan": {"availability_lags": {"close": 0}, "missing_data_policy": "skip_missing"},
        "economic_mechanism": {"claim_class": claim},
        "evidence_policy": {"signal_timestamp_policy": "close_t", "position_entry_policy": "close_t_plus_1",
                            "forward_horizon": 1, "transaction_cost_bps": 30, "cost_model_id": "test-cost",
                            "payoff_contract": {"exit": "close_t_plus_2", "label_expression": "close.shift(-2)/close.shift(-1)-1",
                                                "return_window": "close_t_plus_1_to_close_t_plus_2"}},
        "measurement_program": {"search_policy": {"registered_diagnostic_trials": [
            {"trial_id": "T1", "role": "null", "component_id": "C1", "formula_or_law": "rank(close)"}
        ]}},
    }
    before = deepcopy(plan)
    expected = {
        "version": "factorforge_web_evaluation_contract_v2", "rebalance_frequency": "daily",
        "signal_timestamp_policy": "close_t", "position_entry_policy": "close_t_plus_1", "position_exit_policy": "close_t_plus_2",
        "payoff_label_expression": "close.shift(-2)/close.shift(-1)-1", "availability_lags": {"close": 0},
        "missing_data_policy": "skip_missing", "forward_horizon": 1,
        "label_policy": {"horizon": "one_trading_day_after_execution", "return_type": "simple", "entry_price_field": "close",
                         "exit_price_field": "close", "execution_lag_sessions": 1, "holding_period_sessions": 1,
                         "return_window": "close_t_plus_1_to_close_t_plus_2"},
        "transaction_cost_bps": 30, "cost_model_id": "test-cost", "cost_formula": "one_way_turnover * 0.003",
        "proof_control_columns": controls,
        "diagnostic_trials": [{"trial_id": "T1", "role": "null", "component_id": "C1", "formula_or_law": "rank(close)",
                               "signal_column": "diagnostic__T1", "affects_acceptance": False}],
    }
    assert build_web_evaluation_contract(plan) == expected
    assert plan == before


def test_evaluation_hash_retains_utf8_not_ascii_escape_serialization():
    from factor_factory.console.web_research_plan import stable_json_hash as old
    assert old is stable_json_hash
    assert stable_json_hash({"é": "中文", "a": 1}) == hashlib.sha256('{"a":1,"é":"中文"}'.encode()).hexdigest()


@pytest.mark.parametrize("module", [
    "factor_factory.data_access.calendar_snapshot", "factor_factory.evaluation_contract",
    "factor_factory.knowledge_context",
])
def test_common_services_have_no_console_or_hosted_imports(tmp_path, module):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "nodes.jsonl").write_text("")
    (tmp_path / "edges.jsonl").write_text("")
    script = '''
import importlib, importlib.abc, sys
sys.path.insert(0, sys.argv[1])
class NoHosted(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("factor_factory.console", "factor_factory.research_org", "factor_factory.researcher_memory", "factor_factory.evo_memory_retrieval", "factor_factory.metric_verifier")):
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoHosted())
module = importlib.import_module(sys.argv[2])
if sys.argv[2] == "factor_factory.knowledge_context":
    result = module.retrieve_factor_knowledge_context(text="unknown mechanism", node_index="nodes.jsonl", edge_index="edges.jsonl", taxonomy="absent-taxonomy.json")
    assert result["node_count"] == 0 and result["nodes"] == []
    assert result["node_index_available"] is True
    try:
        module.retrieve_factor_knowledge_context(node_index="missing-index.jsonl", edge_index="edges.jsonl")
    except module.KnowledgeRetrievalError:
        pass
    else:
        raise AssertionError("Missing index was silently accepted")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(root), module],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_hosted_compatibility_signatures_and_arguments(monkeypatch):
    import inspect
    from factor_factory import evo_memory_retrieval as hosted, knowledge_context as generic
    names = (
        "validate_evo_v2_cold_start_search_receipt", "prepare_evo_v2_cold_start_search_session",
        "build_evo_v2_cold_start_search_prompt", "complete_evo_v2_cold_start_search_session",
        "retrieve_evo_v2_memory_projection",
    )
    for name in names:
        wrapper, implementation = getattr(generic, name), getattr(hosted, name)
        assert inspect.signature(wrapper) == inspect.signature(implementation)
        positional, kwargs = [], {}
        for parameter in inspect.signature(wrapper).parameters.values():
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = object()
            else:
                positional.append(object())
        observed = []
        def probe(*args, **kw):
            observed.append((args, kw))
            return "forwarded"
        with monkeypatch.context() as patch:
            patch.setattr(hosted, name, probe)
            assert wrapper(*positional, **kwargs) == "forwarded"
        assert observed == [(tuple(positional), kwargs)]
