"""Full-source Console regressions, outside the standard local research distribution."""
from copy import deepcopy
import hashlib
import json

from factor_factory.measurement_program import (
    MEASUREMENT_PROGRAM_VERSION_V1, MEASUREMENT_PROGRAM_VERSION_V2,
    validate_measurement_program,
)
from factor_factory.mechanism_math.formula_specific import (
    validate_formula_specific_derivation, validate_mechanism_formula_consistency,
)
from factor_factory.mechanism_math.main_agent_memo import (
    formula_specific_derivation_from_main_agent_memo, validate_main_agent_mechanism_memo,
)
from tests.test_factorforge_formula_specific_derivation import _transient_refactor_parity
from tests.test_factorforge_measurement_program_research_equation_v2 import _filled_program


def test_v9_agent_patch_rehydrates_and_closes_formula_contracts(tmp_path) -> None:
    from factor_factory.console.agent_adapter import AgentResumeTask
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    formula = (
        "-(open / pre_close - 1.0) * "
        "(1.0 - sign((open - pre_close) * (close - open))) / 2.0 * "
        "(vol / mean(vol, 5))"
    )
    signature = {
        "rank_ic": "expected positive; observed rank_ic_mean=-0.017245 contradicts",
        "long_side": "expected positive; observed annual return=-0.137989 contradicts",
        "cost_adjusted": "expected positive; observed annual return=-0.766912 contradicts",
        "monotonicity": "expected increasing deciles; observed top below bottom contradicts",
        "turnover": "expected survivable turnover; observed daily turnover=0.832269 contradicts",
    }
    spec = {
        "canonical_spec": {
            "formula_text": formula,
            "required_inputs": ["close", "open", "pre_close", "vol"],
            "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
        }
    }
    estimator = (
        "formula_state estimates temporary impact u, not persistent news s; "
        "F_t=-(open/pre_close-1)*failed_confirmation*(vol/mean(vol,5)), "
        "where relative volume scales precision but never direction."
    )
    memo = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "report_id": "V9_REGRESSION",
        "factor_id": "OVERNIGHT_REVERSAL_V9",
        "research_id": "v9_regression",
        "producer": "current_main_agent",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "agent_role": "main_agent",
            "answered_without_deterministic_template": True,
        },
        "formula": formula,
        "formula_understanding": {
            "formula_features": {
                "fields": ["close", "open", "pre_close", "vol"],
                "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
            }
        },
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": ["divide", "mean", "minus", "multiply", "negate", "sign"],
                "observable_estimator": estimator,
                "economic_state": "signed temporary opening-auction impact",
                "mathematical_object": "gated and precision-scaled opening-gap state",
                "expected_role": "predict residual impact reversal after close t",
                "metric_link": "positive high-state forward return is required",
            }
        ],
        "mechanism_qa": {
            "formula_state_answer": (
                "open/pre_close identifies the opening gap; the failed close-open sign gate "
                "selects rejected gaps and vol/mean(vol,5) scales precision, yielding temporary impact u."
            ),
            "economic_hypothesis_answer": (
                "Urgent call-auction demand creates temporary impact that patient liquidity suppliers "
                "harvest only when the continuous session rejects the opening gap."
            ),
            "math_model_answer": (
                "A transient-impact model decomposes gap g into persistent news s and temporary u; "
                "stable AR(1) decay maps u to the next close-to-close payoff."
            ),
            "payer_answer": (
                "Retail news chasers, margin-constrained accounts, and panic sellers demand opening "
                "immediacy; institutional rebalancers and arbitrage desks supply liquidity."
            ),
            "payoff_answer": (
                "High formula_state should earn positive close t+2 over close t+1 return because "
                "temporary impact u decays after entry at t+1 close."
            ),
            "estimator_mapping_answer": (
                "open/pre_close sets gap direction, close-open determines failed confirmation, and "
                "vol/mean(vol,5) changes magnitude or precision without independently setting sign."
            ),
            "metric_signature_answer": (
                "The model requires positive rank_ic, top-decile long return, net return, and ordered "
                "deciles at survivable turnover; every observed signature contradicts it."
            ),
            "falsification_answer": (
                "Negative rank_ic_mean, top below bottom, negative gross and net long return, and "
                "0.832269 daily turnover jointly falsify the declared temporary-impact payoff."
            ),
        },
        "economic_hypothesis": {
            "return_source_class": "market_structure_arbitrage",
            "payer_or_counterparty": (
                "Retail news chasers, margin-constrained auction accounts, and panic sellers"
            ),
            "why_they_pay": "Opening immediacy and funding constraints make their demand price inelastic.",
            "necessary_market_structure": "Call auction followed by liquid continuous trading.",
        },
        "math_hypothesis": {
            "selected_model_family": "transient_impact",
            "why_this_model": "The hypothesis separates persistent information from temporary impact.",
            "why_not_generic_template": (
                "The sign gate is discontinuous at z=0; zero receives half weight. Active-boundary "
                "bucket and rank instability can amplify turnover, while relative volume is a "
                "non-negative precision scaler in this exact expression."
            ),
            "random_object": "Per-security-day persistent news s, temporary impact u, and innovations.",
            "latent_state": "u is the temporary impact state, not persistent news s.",
            "process_or_distribution": (
                "g_{i,t}=s_{i,t}+u_{i,t}; s_{i,t} is the persistent news component; "
                "u_{i,t+1}=rho*u_{i,t}+eta_{i,t+1}; |rho|<1; "
                "u_{i,t} is the temporary auction-impact state; "
                "return_{i,t+2}=-(1-rho)*u_{i,t}+epsilon_{i,t+2}"
            ),
            "target_functional": (
                "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}], "
                "entry t+1 close, exit t+2 close"
            ),
            "formula_as_estimator": estimator,
            "expected_metric_signature": dict(signature),
        },
        "math_model_selection": {
            "model_family": "transient_impact",
            "baseline_model": "g=s+u with stable AR(1) temporary impact u",
            "model_mutation": "failed-confirmation gate plus relative-volume precision scaling",
        },
        "payer": {
            "payer_or_counterparty": "Urgent auction traders facing attention or funding constraints.",
            "why_they_pay": "They demand immediacy at the opening print.",
            "necessary_market_structure": "Opening auction with patient opposite-side liquidity.",
        },
        "formula_state_estimator": {
            "latent_state": "temporary auction-impact state u",
            "observable_mapping": estimator,
            "component_links": ["formula_root"],
        },
        "expected_metric_signature": dict(signature),
        "falsification_tests": [
            "Ablate the failed-confirmation gate and require the full state to improve rank_ic.",
            "Set relative volume to one and require the full state to improve net long return.",
        ],
        "evidence_comparison": {
            "observed_metrics": {
                "rank_ic_mean": -0.017245,
                "long_side_annual_return": -0.137989,
                "cost_adjusted_annual_return": -0.766912,
                "turnover_mean": 0.832269,
            },
            "mechanism_supported": "The declared positive payoff is falsified.",
            "contradictions": ["Every directional and cost signature contradicts the model."],
            "revision_implications": ["Kill and preserve this exact factor identity."],
            "kill_criteria_triggered": ["Negative long-only return after costs."],
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "formula_has_correlation_or_covariance_operator": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "has_sign_or_threshold": True,
            "sign_threshold_discussion_present": True,
            "has_volume_ratio": True,
            "volume_ratio_participation_discussion_present": True,
            "has_additive_rank_raw_ratio": False,
            "additive_scale_commensurability_discussion_present": False,
        },
        "council_questions": ["Confirm kill-and-preserve without sign inversion."],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }

    source = tmp_path / "source"
    workspace = source / "factor_research" / memo["factor_id"] / memo["research_id"]
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    output_relative = (
        "objects/research_iteration_master/"
        f"main_agent_mechanism_memo__{memo['report_id']}.json"
    )
    task = AgentResumeTask(
        version="factorforge_console_resume_task_v1",
        attempt_id=f"resume_{'a' * 32}",
        job_id="job_v9regression",
        factor_id=memo["factor_id"],
        research_id=memo["research_id"],
        report_id=memo["report_id"],
        resume_start_step="6",
        pause_kind="main_agent_mechanism_memo",
        pause_token="AWAITING_MAIN_AGENT_MECHANISM_MEMO",
        session_policy="fresh_phase_agent",
        ultimate_proof_sha256="b" * 64,
        contract_relative="identity/web_agent_resume_contract.json",
        status_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo_status__{memo['report_id']}.json"
        ),
        questionnaire_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_questionnaire__{memo['report_id']}.json"
        ),
        questionnaire_markdown_relative=(
            "objects/research_iteration_master/"
            f"main_agent_mechanism_questionnaire__{memo['report_id']}.md"
        ),
        facts_relative="identity/web_main_agent_mechanism_facts.json",
        answer_form_relative="identity/web_main_agent_mechanism_answer_form.json",
        required_output_relative=output_relative,
        optional_output_relative=output_relative.removesuffix(".json") + ".md",
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
        protected_inputs=(),
        allowed_model_families=("transient_impact",),
        validation_command="validate memo",
    )

    blank_signature = {field: "" for field in signature}
    answer_form = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "resume_attempt_id": task.attempt_id,
        "report_id": memo["report_id"],
        "factor_id": memo["factor_id"],
        "research_id": memo["research_id"],
        "created_at_utc": "2026-08-04T00:00:00Z",
        "producer": "",
        "agent_authorship": {
            "authoring_mode": "",
            "agent_role": "",
            "answered_without_deterministic_template": False,
        },
        "source_refs": {
            "factor_spec_master": (
                "objects/factor_spec_master/factor_spec_master__V9_REGRESSION.json"
            ),
            "factor_case_master": (
                "objects/factor_case_master/factor_case_master__V9_REGRESSION.json"
            ),
            "evaluation_summary": (
                "objects/validation/factor_evaluation__V9_REGRESSION.json"
            ),
        },
        "formula": formula,
        "formula_understanding": deepcopy(memo["formula_understanding"]),
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": spec["canonical_spec"]["operators"],
                "observable_estimator": "",
                "economic_state": "",
                "mathematical_object": "",
                "expected_role": "",
                "metric_link": "",
            }
        ],
        "mechanism_qa": {field: "" for field in memo["mechanism_qa"]},
        "economic_hypothesis": {
            "return_source_class": "",
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "math_hypothesis": {
            "selected_model_family": "",
            "why_this_model": "",
            "why_not_generic_template": "",
            "random_object": "",
            "latent_state": "",
            "process_or_distribution": "",
            "target_functional": "",
            "formula_as_estimator": "",
            "expected_metric_signature": dict(blank_signature),
        },
        "math_model_selection": {
            "model_family": "",
            "baseline_model": "",
            "model_mutation": "",
        },
        "payer": {
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "formula_state_estimator": {
            "latent_state": "",
            "observable_mapping": "",
            "component_links": [],
        },
        "expected_metric_signature": dict(blank_signature),
        "falsification_tests": [],
        "evidence_comparison": {
            "observed_metrics": deepcopy(memo["evidence_comparison"]["observed_metrics"]),
            "mechanism_supported": "",
            "contradictions": [],
            "revision_implications": [],
            "kill_criteria_triggered": [],
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "formula_has_correlation_or_covariance_operator": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "has_sign_or_threshold": True,
            "sign_threshold_discussion_present": False,
            "has_volume_ratio": True,
            "volume_ratio_participation_discussion_present": False,
            "has_additive_rank_raw_ratio": False,
            "additive_scale_commensurability_discussion_present": False,
        },
        "council_questions": [],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }
    pre_staging_failures = validate_main_agent_mechanism_memo(answer_form, spec)
    assert pre_staging_failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID" in (
        pre_staging_failures
    )
    answer_form_path = workspace / task.answer_form_relative
    answer_form_path.write_text(
        json.dumps(answer_form, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    facts = {
        "formula_facts": {
            "formula": formula,
            "fields": spec["canonical_spec"]["required_inputs"],
            "operators": spec["canonical_spec"]["operators"],
        },
        "revision_context": {
            "mode": "revision",
            "revision_number": 4,
            "failures": [
                "BLOCK_MECHANISM_FORMULA_OPERATOR_OMISSION",
            ],
        },
    }
    facts_path = workspace / task.facts_relative
    facts_path.write_text(
        json.dumps(facts, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract = {
        "version": task.version,
        "attempt_id": task.attempt_id,
        "job_id": task.job_id,
        "factor_id": task.factor_id,
        "research_id": task.research_id,
        "report_id": task.report_id,
        "answer_form": task.answer_form_relative,
        "input_sha256": {
            task.answer_form_relative: hashlib.sha256(
                answer_form_path.read_bytes()
            ).hexdigest(),
            task.facts_relative: hashlib.sha256(facts_path.read_bytes()).hexdigest(),
        },
    }
    (workspace / task.contract_relative).write_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "identity/web_agent_resume.md").write_text(
        "V9 formula-specific mechanism revision\n",
        encoding="utf-8",
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n",
        encoding="utf-8",
    )

    agent_patch = {
        "producer": deepcopy(memo["producer"]),
        "agent_authorship": deepcopy(memo["agent_authorship"]),
        "mechanism_qa": deepcopy(memo["mechanism_qa"]),
        "economic_hypothesis": deepcopy(memo["economic_hypothesis"]),
        "math_hypothesis": deepcopy(memo["math_hypothesis"]),
        "math_model_selection": deepcopy(memo["math_model_selection"]),
        "payer": deepcopy(memo["payer"]),
        "formula_state_estimator": deepcopy(memo["formula_state_estimator"]),
        "expected_metric_signature": deepcopy(memo["expected_metric_signature"]),
        "falsification_tests": deepcopy(memo["falsification_tests"]),
        "council_questions": deepcopy(memo["council_questions"]),
        "formula_component_map": [
            {
                "observable_estimator": component["observable_estimator"],
                "economic_state": component["economic_state"],
                "mathematical_object": component["mathematical_object"],
                "expected_role": component["expected_role"],
                "metric_link": component["metric_link"],
            }
            for component in memo["formula_component_map"]
        ],
        "evidence_comparison": {
            "mechanism_supported": memo["evidence_comparison"]["mechanism_supported"],
            "contradictions": deepcopy(memo["evidence_comparison"]["contradictions"]),
            "revision_implications": deepcopy(
                memo["evidence_comparison"]["revision_implications"]
            ),
            "kill_criteria_triggered": deepcopy(
                memo["evidence_comparison"]["kill_criteria_triggered"]
            ),
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "sign_threshold_discussion_present": True,
            "volume_ratio_participation_discussion_present": True,
            "additive_scale_commensurability_discussion_present": False,
        },
    }
    assert "formula" not in agent_patch
    assert "source_refs" not in agent_patch
    assert "observed_metrics" not in agent_patch["evidence_comparison"]
    assert "has_sign_or_threshold" not in agent_patch["operator_claim_consistency"]
    assert set(agent_patch["formula_component_map"][0]) == {
        "observable_estimator",
        "economic_state",
        "mathematical_object",
        "expected_role",
        "metric_link",
    }

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    view = adapter._prepare_resume_workspace_view(
        runtime_root=runtime_root,
        workspace=workspace,
        resume_task=task,
    )
    adapter._stage_resume_terminal_delivery(
        view,
        terminal_text=json.dumps(
            {
                "status": "MEMO_DRAFT_COMPLETE",
                "memo": agent_patch,
                "ledger": "V9 formula-specific agent patch staged by Host",
            },
            ensure_ascii=False,
        ),
        resume_task=task,
        rehydrate_immutable_fields=True,
    )
    staged_memo = json.loads(
        (view.root / task.required_output_relative).read_text(encoding="utf-8")
    )
    assert staged_memo["producer"] == agent_patch["producer"]
    assert staged_memo["math_hypothesis"]["process_or_distribution"] == (
        agent_patch["math_hypothesis"]["process_or_distribution"]
    )
    assert staged_memo["formula_component_map"][0]["economic_state"] == (
        agent_patch["formula_component_map"][0]["economic_state"]
    )
    assert staged_memo["evidence_comparison"]["mechanism_supported"] == (
        agent_patch["evidence_comparison"]["mechanism_supported"]
    )
    assert staged_memo["operator_claim_consistency"][
        "sign_threshold_discussion_present"
    ] is True
    assert staged_memo["formula"] == formula
    assert staged_memo["formula_component_map"][0]["component_id"] == "formula_root"
    assert staged_memo["evidence_comparison"]["observed_metrics"] == answer_form[
        "evidence_comparison"
    ]["observed_metrics"]
    assert staged_memo["operator_claim_consistency"]["has_sign_or_threshold"] is True
    assert staged_memo["operator_claim_consistency"]["has_volume_ratio"] is True
    assert staged_memo["source_refs"] == answer_form["source_refs"]
    assert staged_memo["canonical_write_permission"] is False

    assert validate_main_agent_mechanism_memo(staged_memo, spec) == []
    derivation = formula_specific_derivation_from_main_agent_memo(staged_memo, spec)
    analysis = {
        "mechanism_hypothesis": (
            staged_memo["mechanism_qa"]["economic_hypothesis_answer"]
            + " "
            + staged_memo["mechanism_qa"]["math_model_answer"]
        ),
        "formula_specific_derivation": derivation,
        "main_agent_mechanism_memo_takeover": {
            "enabled": True,
            "validation_scope": "main_agent_formula_specific_derivation",
        },
    }
    assert validate_formula_specific_derivation(derivation, spec, analysis) == []
    assert validate_mechanism_formula_consistency(
        spec,
        analysis,
        derivation,
    )["failures"] == []


def test_ultimate_public_projection_preserves_and_revalidates_v2_equation() -> None:
    from factor_factory.console.ultimate_reader import (
        _public_measurement_program_copy,
        _research_notebooks,
    )

    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    projected = _public_measurement_program_copy(program)

    assert projected["research_equation"] == program["research_equation"]
    assert validate_measurement_program(
        projected,
        require_web_executable=False,
    ) == []

    _research_notebook, math_notebook = _research_notebooks(
        main_agent_memo={},
        research_method={},
        economic_game={},
        math_mechanism={},
        measurement_program=program,
    )
    assert math_notebook["research_equation"] == program["research_equation"]


def test_ultimate_v2_projection_fails_closed_and_v1_shape_is_unchanged() -> None:
    from factor_factory.console.ultimate_reader import (
        _public_measurement_program_copy,
        _research_notebooks,
    )

    invalid_v2 = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    invalid_v2["research_equation"]["caller_selected_claim"] = "alternate"
    assert _public_measurement_program_copy(invalid_v2) == {}

    v1 = _filled_program(MEASUREMENT_PROGRAM_VERSION_V1)
    projected_v1 = _public_measurement_program_copy(v1)
    assert "research_equation" not in projected_v1
    assert "return_path" not in projected_v1["evaluation_design"][
        "portfolio_contract"
    ]
    assert projected_v1["contract_version"] == MEASUREMENT_PROGRAM_VERSION_V1
    _research_notebook, math_notebook = _research_notebooks(
        main_agent_memo={},
        research_method={},
        economic_game={},
        math_mechanism={},
        measurement_program=v1,
    )
    assert "research_equation" not in math_notebook
