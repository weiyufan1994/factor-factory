"""Independent mathematics/consumer checks for the W09 connection repairs.

Only fresh, deterministic engineering vectors belong here.  These checks do
not replay W08/W09, evaluate alpha, or assert a research-quality improvement.
The reference calculations use finite sums rather than the implementation's
recurrence. Constrained fitting is compared to a separate SciPy solver, its
KKT conditions, and an additionally coded active-set reference.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import combinations
import json
from math import log
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import lsq_linear

from factor_factory.hybrid_research import journal_adapter as adapter
from factor_factory.hybrid_research.decision import ScheduleState
from factor_factory.hybrid_research.gp_adapter import (
    KernelTerm,
    ResponseProgram,
    evaluate_program,
    fit_response_program,
    run_response_gp,
)
from factor_factory.hybrid_research.response import (
    ResponseSemantics,
    initial_state_column,
    response_column,
)
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope


def _finite_sum(inputs, retention, *, lag=0, previous_input=None, start=0):
    """Unit-forcing response with an explicitly specified pre-sample input."""
    if lag not in (0, 1):
        raise ValueError("reference supports only explicit event lags 0 and 1")
    if lag == 1 and start == 0 and previous_input is None:
        raise ValueError("lagged pre-sample input is unspecified")
    result = []
    for t in range(len(inputs)):
        value = 0.0
        for j in range(start, t + 1):
            source = j - lag
            impulse = previous_input if source == -1 else inputs[source]
            value += float(impulse) * retention ** (t - j)
        result.append(value)
    return np.asarray(result)


def _homogeneous(length, retention, *, offset=1):
    return np.asarray([retention ** (t + offset) for t in range(length)])


def _enumerated_nonnegative_lsq(design, observed, constrained_columns):
    """Small independent oracle: enumerate every possible active gain face.

    Unconstrained intercept/state columns remain free on every face.  The
    production solver also enumerates active sets; this independently coded
    reference is secondary to the separate SciPy TRF / KKT checks below.
    """
    design = np.asarray(design, dtype=float)
    observed = np.asarray(observed, dtype=float)
    constrained_columns = tuple(constrained_columns)
    free_columns = tuple(
        j for j in range(design.shape[1]) if j not in constrained_columns
    )
    best = None
    for count in range(len(constrained_columns) + 1):
        for inactive in combinations(constrained_columns, count):
            columns = free_columns + inactive
            coefficients = np.zeros(design.shape[1])
            if columns:
                coefficients[list(columns)] = np.linalg.lstsq(
                    design[:, list(columns)], observed, rcond=None
                )[0]
            if any(coefficients[j] < -1e-10 for j in inactive):
                continue
            residual = design @ coefficients - observed
            loss = float(residual @ residual)
            if best is None or loss < best[0]:
                best = loss, coefficients, design @ coefficients
    if best is None:
        raise AssertionError("a finite zero-gain face must exist")
    return best


INPUTS = (1.0, -0.2, 0.6, 0.0, -0.8, 0.3, 0.0, 0.9) * 3


def _scope(initial="zero", permanent=True):
    families = ["transient_exponential_kernel", "two_scale_superposition"]
    if permanent:
        families.append("permanent_component")
    return DerivationScope(
        "independent:w10-engineering-vector", "causal kernels",
        "finite signed impulses", initial, "event", "missing is not zero",
        "signed J to y", ("causal convolution", "linear superposition"),
        ("conditioned input response versus homogeneous initial-state decay",),
        "which declared scale is compatible with this engineering vector",
        tuple(families), ("parameter_search", "structure_search"),
    )


def _program(*rates, scales=None):
    scales = scales or (1.0,) * len(rates)
    return ResponseProgram(tuple(KernelTerm(s, r) for s, r in zip(scales, rates)))


def _fit(observed):
    return FitData(INPUTS, tuple(float(v) for v in observed), 1.0)


@pytest.mark.parametrize("lag", (0, 1))
@pytest.mark.parametrize("retention", (0.0, 0.35, 1.0))
@pytest.mark.parametrize("start", (0, 1))
def test_columns_match_direct_sums_at_endpoints_and_time_origins(lag, retention, start):
    sem = ResponseSemantics(
        observation_timing="lag_one" if lag else "same_event",
        rate_parameterization="retention", pre_sample_input="zero",
        input_start_index=start,
    )
    actual = response_column(INPUTS, rate=retention, semantics=sem)
    expected = _finite_sum(INPUTS, retention, lag=lag, previous_input=0.0, start=start)
    np.testing.assert_allclose(actual, expected, atol=2e-14)


def test_retention_and_continuous_rate_have_explicit_different_zero_endpoints():
    retention = ResponseSemantics(rate_parameterization="retention")
    continuous = ResponseSemantics(rate_parameterization="continuous_decay")
    np.testing.assert_allclose(response_column(INPUTS, rate=0.0, semantics=retention), INPUTS)
    np.testing.assert_allclose(
        response_column(INPUTS, rate=0.0, semantics=continuous), np.cumsum(INPUTS)
    )
    np.testing.assert_allclose(
        response_column(INPUTS, rate=0.4, semantics=retention),
        response_column(INPUTS, rate=-log(0.4), semantics=continuous), atol=2e-14,
    )


@pytest.mark.parametrize("lag", (0, 1))
def test_fit_recovers_profiled_gain_intercept_and_initial_state(lag):
    sem = ResponseSemantics(
        observation_timing="lag_one" if lag else "same_event",
        rate_parameterization="retention", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=tuple(range(16)),
    )
    expected = -2.0 + 0.7 * _finite_sum(INPUTS, 0.4, lag=lag, previous_input=0.0)
    expected += 1.2 * _homogeneous(len(INPUTS), 0.4)
    result = fit_response_program(_program(0.4), _fit(expected), sem)
    np.testing.assert_allclose(result.prediction, expected, atol=2e-12)
    assert dict(result.coefficients) == pytest.approx({
        "component_gain_0": 0.7, "intercept": -2.0, "initial_state_0": 1.2,
    })


def test_time_zero_boundary_excludes_boundary_observation_and_continues_state():
    sem = ResponseSemantics(
        rate_parameterization="retention", input_start_index=1,
        initial_power_offset=0, initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=tuple(range(1, 16)),
    )
    # The forcing starts at j=1; the independently anchored initial state is
    # still at t=0.  These are distinct semantics in the original request.
    initial = 0.4 ** np.arange(len(INPUTS))
    expected = -2 + 0.7 * _finite_sum(INPUTS, 0.4, start=1) + 1.2 * initial
    changed = expected.copy()
    changed[0] = 900.0
    changed[16:] = -800.0
    first = fit_response_program(_program(0.4), _fit(expected), sem)
    second = fit_response_program(_program(0.4), _fit(changed), sem)
    np.testing.assert_allclose(first.prediction, expected, atol=2e-12)
    assert first.coefficients == second.coefficients
    assert first.prediction == second.prediction
    assert 0 not in first.continuation_indexes
    assert dict(first.coefficients)["initial_state_0"] == pytest.approx(1.2)


def test_zero_retention_boundary_state_is_not_silently_dropped():
    sem = ResponseSemantics(
        rate_parameterization="retention", initial_power_offset=0,
        initial_state="profiled_component", intercept="profiled",
        gain_mode="profiled_component", training_indexes=tuple(range(16)),
    )
    initial = np.r_[1.0, np.zeros(len(INPUTS) - 1)]
    expected = -2.0 + 0.7 * np.asarray(INPUTS) + 3.0 * initial
    np.testing.assert_array_equal(
        initial_state_column(len(INPUTS), rate=0.0, step=1.0, semantics=sem), initial
    )
    result = fit_response_program(_program(0.0), _fit(expected), sem)
    np.testing.assert_allclose(result.prediction, expected, atol=2e-12)


def test_unknown_pre_sample_input_is_not_zeroed_for_unrepresentable_lag():
    sem = ResponseSemantics(
        observation_timing="lag_one", rate_parameterization="retention",
        pre_sample_input="unknown", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_component",
    )
    with pytest.raises(ValueError, match="unrepresentable|pre.sample"):
        fit_response_program(_program(0.0), _fit(np.zeros(len(INPUTS))), sem)


def test_nonnegative_fit_matches_separate_solver_and_kkt_conditions():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        gain_constraint="nonnegative", intercept="profiled",
        training_indexes=tuple(range(16)),
    )
    design = np.column_stack((
        _finite_sum(INPUTS, 0.25), _finite_sum(INPUTS, 0.75), np.ones(len(INPUTS)),
    ))
    observed = design @ np.asarray((-2.0, 1.4, -3.0)) + 0.01 * np.arange(len(INPUTS))
    result = fit_response_program(_program(0.25, 0.75), _fit(observed), sem)
    independent = lsq_linear(design[:16], observed[:16], bounds=((0, 0, -np.inf), np.inf))
    assert independent.success
    residual = np.asarray(result.prediction[:16]) - observed[:16]
    assert float(residual @ residual) == pytest.approx(
        2 * independent.cost, rel=1e-8, abs=1e-9
    )
    enumeration = _enumerated_nonnegative_lsq(design[:16], observed[:16], (0, 1))
    assert float(residual @ residual) == pytest.approx(enumeration[0], abs=1e-9)
    gains = np.asarray([dict(result.coefficients)[f"component_gain_{i}"] for i in range(2)])
    gradient = design[:16].T @ residual
    assert np.all(gains >= -1e-12)
    assert np.all(gradient[:2][gains < 1e-8] >= -1e-8)
    assert np.all(np.abs(gradient[:2][gains >= 1e-8]) < 1e-8)
    assert abs(gradient[-1]) < 1e-8
    assert dict(result.coefficients)["intercept"] < 0


def test_shared_mixture_gain_does_not_turn_into_free_component_gains():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_shared",
        intercept="profiled", training_indexes=tuple(range(16)),
    )
    mixed = 0.25 * _finite_sum(INPUTS, 0.4) + 0.75 * _finite_sum(INPUTS, 1.0)
    expected = -2.0 + 1.3 * mixed
    result = fit_response_program(_program(0.4, 1.0, scales=(0.25, 0.75)), _fit(expected), sem)
    assert dict(result.coefficients) == pytest.approx({"shared_gain": 1.3, "intercept": -2.0})
    np.testing.assert_allclose(result.prediction, expected, atol=2e-12)


def test_entire_gp_selection_ignores_continuation_observations():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        initial_state="profiled_component", intercept="profiled",
        training_indexes=tuple(range(16)),
    )
    observed = -2.0 + 0.7 * _finite_sum(INPUTS, 0.4) + 1.2 * _homogeneous(len(INPUTS), 0.4)
    changed = observed.copy()
    changed[16:] = 1e200
    kwargs = dict(
        scope=_scope(initial=sem.initial_state), allowed_rates=(0.15, 0.4, 0.75, 1.0),
        allowed_scales=(1.0,), seed=271, generations=3, population_size=4,
        max_evaluations=16, max_attempts=32, response_semantics=sem,
    )
    first = run_response_gp(fit_data=_fit(observed), **kwargs)
    second = run_response_gp(fit_data=_fit(changed), **kwargs)
    assert first == second
    assert first.selected is not None
    assert any(row.parents for row in first.trace)
    assert any(len(row.parents) == 2 for row in first.trace)
    assert first.evaluated_count <= 16 and first.attempt_count <= 32


def test_search_cannot_score_on_rows_declared_as_continuation():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        training_indexes=tuple(range(16)), score_indexes=tuple(range(16, 24)),
    )
    with pytest.raises(ValueError, match="score|training|continuation"):
        fit_response_program(_program(0.4), _fit(np.zeros(len(INPUTS))), sem)


def test_retention_one_requires_the_same_permanent_component_permission_as_lambda_zero():
    sem = ResponseSemantics(rate_parameterization="retention")
    with pytest.raises(ValueError, match="permanent"):
        run_response_gp(
            scope=_scope(permanent=False), fit_data=_fit(np.zeros(len(INPUTS))),
            response_semantics=sem, allowed_rates=(0.2, 0.7, 1.0),
            allowed_scales=(1.0,), seed=4,
        )


def test_permanent_initial_state_with_later_anchor_is_not_a_global_intercept():
    sem = ResponseSemantics(
        rate_parameterization="retention", initial_state="profiled_component",
        initial_state_start_index=2, initial_power_offset=0,
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=tuple(range(16)),
    )
    initial = np.r_[0.0, 0.0, np.ones(len(INPUTS) - 2)]
    observed = -2.0 + 0.7 * _finite_sum(INPUTS, 1.0) + 3.0 * initial
    result = fit_response_program(_program(1.0), _fit(observed), sem)
    np.testing.assert_allclose(result.prediction, observed, atol=2e-12)


def test_unobserved_boundary_state_is_reported_unidentified_not_known_zero():
    sem = ResponseSemantics(
        rate_parameterization="retention", initial_power_offset=0,
        initial_state="profiled_component", input_start_index=1,
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=tuple(range(1, 16)),
    )
    observed = -2.0 + 0.7 * _finite_sum(INPUTS, 0.0, start=1)
    result = fit_response_program(_program(0.0), _fit(observed), sem)
    assert "initial_state_0" in result.unidentified_coefficients
    assert result.design_rank < len(result.design_columns)


def test_collinear_nonzero_coefficients_are_not_mistaken_for_identified_ones():
    sem = ResponseSemantics(
        rate_parameterization="retention", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=tuple(range(16)),
    )
    observed = -2.0 + 0.7 * _finite_sum(INPUTS, 0.4) + _homogeneous(len(INPUTS), 0.4)
    result = fit_response_program(_program(0.4, 0.4), _fit(observed), sem)
    np.testing.assert_allclose(result.prediction, observed, atol=2e-12)
    assert result.design_rank == 3
    assert set(result.unidentified_coefficients) >= {
        "component_gain_0", "component_gain_1", "initial_state_0", "initial_state_1",
    }


def test_design_rank_is_not_the_number_of_nonzero_constrained_coefficients():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        gain_constraint="nonnegative", intercept="profiled",
        training_indexes=tuple(range(16)),
    )
    observed = -2.0 - _finite_sum(INPUTS, 0.4)
    result = fit_response_program(_program(0.4), _fit(observed), sem)
    assert dict(result.coefficients)["component_gain_0"] == pytest.approx(0.0)
    assert result.design_rank == 2


def test_explicit_default_semantics_preserve_the_zero_fitted_columns_path():
    data = _fit(np.zeros(len(INPUTS)))
    program = _program(0.4, scales=(0.7,))
    result = fit_response_program(program, data, ResponseSemantics())
    np.testing.assert_allclose(result.prediction, evaluate_program(program, data))
    assert result.design_rank == 0
    assert result.coefficients == ()
    assert result.unidentified_coefficients == ()


def test_identifiability_diagnostic_is_not_lost_when_input_units_are_rescaled():
    sem = ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        training_indexes=tuple(range(16)),
    )
    scaled = tuple(value * 1e16 for value in INPUTS)
    data = FitData(scaled, tuple(_finite_sum(scaled, 0.4)), 1.0)
    result = fit_response_program(_program(0.4, 0.4), data, sem)
    assert result.design_rank == 1
    assert set(result.unidentified_coefficients) == {"component_gain_0", "component_gain_1"}


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


REPORT = "w10-independent-engineering-fixture"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence_workspace(tmp_path):
    spec = tmp_path / "objects/factor_spec_master" / f"factor_spec_master__{REPORT}.json"
    handoff = tmp_path / "objects/handoff" / f"handoff_to_step3__{REPORT}.json"
    impl = tmp_path / "generated_code" / "fixture.py"
    impl.parent.mkdir(parents=True)
    impl.write_text("# Engineering fixture, never imported or used as a real review.\n", encoding="utf-8")
    _write_json(spec, {
        "report_id": REPORT, "engineering_fixture": True,
        "mechanism_conditioned_measurement_program": {"model_selection": {}},
    })
    _write_json(handoff, {
        "report_id": REPORT, "engineering_fixture": True,
        "factor_impl_ref": "generated_code/fixture.py",
    })
    _write_json(tmp_path / "objects/research_journal" / f"research_journal__{REPORT}.json", {
        "report_id": REPORT, "engineering_fixture": True,
    })
    _write_json(tmp_path / "objects/research_protocol" / f"approach_registry__{REPORT}.json", {
        "report_id": REPORT, "engineering_fixture": True, "approaches": [],
    })
    log = tmp_path / "fixture-test-log.txt"
    log.write_text("Synthetic fixture record only, not a claim of actual test/review execution.\n", encoding="utf-8")
    reviewed = [
        {"role": "spec", "path": str(spec), "sha256": sha256(spec.read_bytes()).hexdigest()},
        {"role": "implementation", "path": str(impl), "sha256": sha256(impl.read_bytes()).hexdigest()},
    ]
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    record = {
        "report_id": REPORT, "engineering_fixture": True,
        "author_id": "synthetic-author", "reviewer_id": "synthetic-reviewer",
        "reviewed_at": now.isoformat(), "decision": "proceed",
        "summary": "Synthetic review input for a parser test; not actual independent execution.",
        "findings": [], "reviewed_files": reviewed,
        "post_review_tests": {
            "status": "PASS", "started_at": (now + timedelta(minutes=1)).isoformat(),
            "completed_at": (now + timedelta(minutes=2)).isoformat(),
            "tested_files": deepcopy(reviewed),
            "evidence": [{"path": str(log), "sha256": sha256(log.read_bytes()).hexdigest()}],
        },
    }
    return {"root": tmp_path, "spec": spec, "handoff": handoff, "review": record}


def _collect(case, requested=None):
    return adapter._collect_implementation_evidence(
        root=case["root"], report_id=REPORT, handoff_path=case["handoff"],
        spec_path=case["spec"], requested=requested,
    )


def _save_review(case, *, include_engine=False, stale=False):
    record = deepcopy(case["review"])
    if include_engine:
        snapshot = _collect(case)["executed_engine_version"]
        for file in snapshot:
            record["reviewed_files"].append({
                "role": "helper", "base": "repo", "path": file["path"],
                "sha256": "0" * 64 if stale else file["sha256"],
            })
        record["post_review_tests"]["tested_files"] = deepcopy(record["reviewed_files"])
    path = case["root"] / "objects/research_journal" / f"code_review__{REPORT}.json"
    _write_json(path, record)
    return path


def test_absent_evidence_does_not_turn_numerical_results_into_verification(evidence_workspace):
    evidence = _collect(evidence_workspace)
    assert evidence["author_tests"]["status"] == "Unknown"
    assert evidence["independent_review"]["status"] == "Unknown"
    assert evidence["executed_engine_version"]


def test_review_for_unrelated_factor_code_does_not_certify_the_gp_engine(evidence_workspace):
    _save_review(evidence_workspace)
    evidence = _collect(evidence_workspace)
    assert evidence["independent_review"]["validator_result"]["status"] == "PASS"
    assert evidence["independent_review"]["status"] == "Unknown"
    assert evidence["independent_review"]["reviewed_engine_coverage"]["status"] != "complete_current_coverage"


def test_current_versioned_review_remains_declared_not_authenticated(evidence_workspace):
    _save_review(evidence_workspace, include_engine=True)
    evidence = _collect(evidence_workspace)
    review = evidence["independent_review"]
    assert review["status"] == "current_declared_review_validated"
    assert review["independence_status"] == "declared_not_authenticated"
    assert review["reviewed_engine_coverage"]["status"] == "complete_current_coverage"
    assert review["post_review_deterministic_tests"]["evidence"]


def test_stale_engine_review_is_unknown_even_if_record_claims_pass(evidence_workspace):
    _save_review(evidence_workspace, include_engine=True, stale=True)
    evidence = _collect(evidence_workspace)
    assert evidence["independent_review"]["status"] == "Unknown"


def test_inline_pass_is_not_a_review_or_test_record(evidence_workspace):
    with pytest.raises(ValueError, match="unsupported"):
        _collect(evidence_workspace, {"passed": True})


def test_produced_researcher_material_contains_code_evidence_and_real_profiled_fit(evidence_workspace):
    case = evidence_workspace
    _save_review(case, include_engine=True)
    sem = ResponseSemantics(
        rate_parameterization="retention", initial_state="profiled_component",
        gain_mode="profiled_component", intercept="profiled",
        training_indexes=tuple(range(16)),
    )
    observed = -2.0 + 0.7 * _finite_sum(INPUTS, 0.4)
    arguments = dict(
        workspace_root=case["root"], report_id=REPORT, run_id="synthetic-consumer",
        fit_data=_fit(observed), scope=_scope(initial=sem.initial_state),
        schedule_state=ScheduleState(), handoff_stage="step2", enabled=True,
        response_semantics=sem, allowed_rates=(0.2, 0.4, 0.7),
        allowed_scales=(1.0,), seed=2, max_evaluations=8, max_attempts=16,
    )
    outcome = adapter.run_hybrid_episode(**arguments)
    material = json.loads(Path(outcome.researcher_material_path).read_text())
    evidence = material["evidence_classes"]
    assert evidence["independent_review"]["status"] == "current_declared_review_validated"
    assert evidence["author_tests"]["status"] == "Unknown"
    assert evidence["numerical_fit"]["selected_fit"]["coefficients"]
    assert evidence["executed_engine_version"]
    assert material["formal_approval"] is False
    resumed = adapter.run_hybrid_episode(**arguments)
    assert resumed.resumed is True
    assert resumed.search_result is None


@pytest.mark.parametrize("field,value", (
    ("training_indexes", [0.25, 1.75]),
    ("initial_state_start_index", 1.75),
))
def test_request_parser_does_not_round_mathematical_time_semantics(evidence_workspace, monkeypatch, field, value):
    sem = asdict(ResponseSemantics(
        rate_parameterization="retention", gain_mode="profiled_component",
        training_indexes=(0, 1, 2),
    ))
    sem[field] = value
    request = {
        "contract_version": "hybrid_research_request_v1", "report_id": REPORT,
        "run_id": "must-not-dispatch", "handoff_stage": "step2", "split": "development",
        "fit_data": asdict(_fit(np.zeros(len(INPUTS)))), "derivation_scope": asdict(_scope()),
        "schedule_state": asdict(ScheduleState()), "response_semantics": sem,
        "search_config": {"allowed_rates": [0.2, 0.4], "allowed_scales": [1.0]},
    }
    path = evidence_workspace["root"] / "invalid-math-time-request.json"
    _write_json(path, request)

    def unexpected_execution(**kwargs):
        pytest.fail("parser silently coerced the mathematical time specification before execution")

    monkeypatch.setattr(adapter, "run_hybrid_episode", unexpected_execution)
    with pytest.raises(adapter.HybridResearchError, match="integer|index|indices|semantics"):
        adapter.run_hybrid_episode_from_request(
            workspace_root=evidence_workspace["root"], report_id=REPORT, request_path=path,
        )


def test_interrupted_material_publication_cannot_promote_unverified_evidence(evidence_workspace, monkeypatch):
    case = evidence_workspace
    arguments = dict(
        workspace_root=case["root"], report_id=REPORT, run_id="interrupted-evidence",
        fit_data=_fit(np.zeros(len(INPUTS))), scope=_scope(),
        schedule_state=ScheduleState(), handoff_stage="step2", enabled=True,
        response_semantics=ResponseSemantics(), allowed_rates=(0.2, 0.4, 0.7),
        allowed_scales=(1.0,), seed=2, max_evaluations=4, max_attempts=8,
    )
    original_write = adapter.write_json_atomic
    original_search = adapter.run_response_gp
    calls = []

    def counted_search(**kwargs):
        calls.append(True)
        return original_search(**kwargs)

    def fail_completed_journal(path, payload):
        rows = (payload.get("hybrid_research") or {}).get("episodes", [])
        if Path(path).name.startswith("research_journal__") and any(
            row.get("status") == "computed_awaiting_researcher" for row in rows
        ):
            raise OSError("injected interruption after material publication")
        return original_write(path, payload)

    monkeypatch.setattr(adapter, "run_response_gp", counted_search)
    with monkeypatch.context() as fault:
        fault.setattr(adapter, "write_json_atomic", fail_completed_journal)
        with pytest.raises((OSError, adapter.HybridResearchError)):
            adapter.run_hybrid_episode(**arguments)
    material_path = case["root"] / "objects/research_journal" / f"hybrid_research_material__{REPORT}__interrupted-evidence.json"
    material = json.loads(material_path.read_text())
    material["evidence_classes"]["independent_review"]["status"] = "current_declared_review_validated"
    _write_json(material_path, material)
    try:
        resumed = adapter.run_hybrid_episode(**arguments)
    except adapter.HybridResearchError:
        pass
    else:
        delivered = json.loads(Path(resumed.researcher_material_path).read_text())
        assert delivered["evidence_classes"]["independent_review"]["status"] == "Unknown"
    assert len(calls) == 1
