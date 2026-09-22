from __future__ import annotations

import copy

import pytest

from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    ADAPTER_RESULT_DOMAIN,
    FORMALIZATION_SEMANTIC_FIELDS,
    SourceFirstKernelAdapterOfflineError,
    compile_source_first_kernel_session_candidate,
    run_source_first_kernel_offline_candidate,
    validate_source_first_kernel_session_candidate,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SOURCE_BYTES = (
    "用户假设：局部价格路径在流动性供给撤退时形成多尺度能量集中，"
    "受约束持有者随后支付冲击成本。"
).encode("utf-8")


def _lineage(**overrides) -> dict:
    payload = {
        "source_type": "USER_ORAL_OR_TEXT_HYPOTHESIS",
        "source_event_ref": "user-message-source-first-001",
        "source_legally_available_at": "2026-08-31T09:00:00Z",
        "language": "zh-CN",
        "source_integrity_status": "VERIFIED",
        "understanding_completeness": "COMPLETE_ENOUGH_TO_FORMALIZE",
        "source_reader_context_status": "SOURCE_ONLY_CANDIDATE",
        "selection_lineage_claim": "EX_ANTE_UNSELECTED_CLAIMED",
        "proposer_outcome_exposure_claim": "NONE_CLAIMED",
        "source_outcome_status": "SOURCE_OUTCOME_FREE",
        "missing_source_components": [],
        "novel_concepts_not_yet_mapped": ["局部价格能量集中"],
        "internal_tensions": ["流动性撤退与被迫交易的方向需要区分"],
    }
    payload.update(overrides)
    return payload


def _author_claims() -> list[dict]:
    return [
        {
            "statement_id": "source-claim-1",
            "classification": "SOURCE_NATIVE_EXPLICIT",
            "text": "流动性供给撤退时局部价格能量可能集中。",
            "source_locators": ["message:sentence:1"],
            "depends_on_statement_ids": [],
        },
        {
            "statement_id": "source-claim-2",
            "classification": "AGENT_PARAPHRASE",
            "text": "受约束持有者可能承担价格冲击成本。",
            "source_locators": ["message:sentence:1"],
            "depends_on_statement_ids": ["source-claim-1"],
        },
    ]


def _analyst_notes() -> list[dict]:
    return [
        {
            "statement_id": "analyst-inference-1",
            "classification": "AGENT_INFERENCE",
            "text": "可把机制视为受约束持有者向剩余流动性供给者支付成本。",
            "source_locators": [],
            "depends_on_statement_ids": ["source-claim-1", "source-claim-2"],
        },
        {
            "statement_id": "analyst-unresolved-1",
            "classification": "UNRESOLVED",
            "text": "拥挤状态是否为必要条件尚未解决。",
            "source_locators": [],
            "depends_on_statement_ids": ["source-claim-1"],
        },
    ]


def _formalized_body() -> dict:
    return {
        "disposition": "FORMALIZED",
        "selected_statement_ids": [
            "source-claim-1",
            "source-claim-2",
            "analyst-inference-1",
        ],
        "economic_mechanism_claim": "受约束持有者在流动性撤退时向剩余承接者支付冲击成本。",
        "payer_or_constraint": "融资和风险限额约束下的持有者。",
        "estimand": "未来短周期相对收益对当前多尺度局部能量集中的条件响应。",
        "information_set": "仅使用决策时点及之前的价格与成交量路径。",
        "horizon": "未来五个交易日。",
        "mathematical_object": "多尺度局部化时频能量与尺度间相位一致性。",
        "broken_invariant_or_boundary": "常态下尺度能量分散，撤退时局部尺度能量集中。",
        "observation_mapping": "将价格增量投影到预注册尺度并汇总局部能量比。",
        "failure_signature": "若能量集中不随约束增强而变化，则机制失效。",
        "falsifiers": [
            "控制波动率后局部能量比不再与未来路径相关。",
            "高流动性样本出现同等强度且同方向的现象。",
        ],
        "material_rivals": [
            "局部能量集中仅是波动率机械放大。",
            "信号来自普通反转而非约束。",
        ],
        "regime_hypotheses": ["融资收紧时效应增强。"],
        "new_assumptions": ["成交量是边际流动性供给变化的有噪声代理。"],
        "clarification_questions": ["拥挤状态是否必须显式观测？"],
    }


def _predictions() -> list[dict]:
    return [
        {
            "prediction_id": "prediction-1",
            "prediction": "局部能量集中与短期负向相对收益相关。",
            "horizon": "未来五个交易日。",
            "expected_direction": "NEGATIVE",
            "falsified_when": "关系在波动率匹配后消失。",
        }
    ]


def _policy() -> dict:
    return {
        "policy_version": "source-first-offline-a0-candidate-v1",
        "phase": "A0",
        "requested_lane_subset": [
            "structural_isomorph",
            "cross_math_analogy",
            "near_miss_failure",
            "direct_counterexample",
        ],
        "top_k_per_lane": 3,
    }


def _provenance() -> dict:
    bindings = {
        "economic_mechanism_claim": (
            "PRE_RETRIEVAL_ANALYST_INFERENCE",
            ["analyst-inference-1"],
        ),
        "payer_or_constraint": (
            "PRE_RETRIEVAL_ANALYST_INFERENCE",
            ["analyst-inference-1"],
        ),
        "broken_invariant_or_boundary": (
            "CALLER_CLAIMED_SOURCE_GROUNDED",
            ["source-claim-1"],
        ),
        "failure_signature": (
            "CALLER_CLAIMED_SOURCE_GROUNDED",
            ["source-claim-1"],
        ),
        "clarification_questions": (
            "UNRESOLVED",
            ["analyst-unresolved-1"],
        ),
    }
    rows = []
    for ordinal, field_name in enumerate(FORMALIZATION_SEMANTIC_FIELDS):
        provenance_class, statement_ids = bindings.get(
            field_name,
            ("NEW_ASSUMPTION", []),
        )
        rows.append(
            {
                "ordinal": ordinal,
                "field_name": field_name,
                "provenance_class": provenance_class,
                "statement_ids": statement_ids,
            }
        )
    return {
        "attestation_mode": (
            "CALLER_CLAIMED_PRE_RETRIEVAL__NOT_INDEPENDENTLY_VERIFIED"
        ),
        "field_rows": rows,
    }


def _inputs(**overrides) -> dict:
    payload = {
        "source_bytes": SOURCE_BYTES,
        "source_lineage": _lineage(),
        "author_claims": _author_claims(),
        "analyst_notes": _analyst_notes(),
        "selected_semantic_body": _formalized_body(),
        "formalization_provenance": _provenance(),
        "pre_a0_predictions": _predictions(),
        "phase_policy_candidate": _policy(),
    }
    payload.update(overrides)
    return payload


def _rehash_outer(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    core = {key: value for key, value in result.items() if key != "content_sha256"}
    result["content_sha256"] = framed_sha256(ADAPTER_RESULT_DOMAIN, core)
    return result


def test_adapter_runs_real_source_first_candidate_session_and_replays() -> None:
    inputs = _inputs()
    candidate = run_source_first_kernel_offline_candidate(**inputs)
    assert candidate == compile_source_first_kernel_session_candidate(**inputs)
    assert validate_source_first_kernel_session_candidate(candidate, **inputs) == candidate
    assert candidate["session_envelope"]["terminal"]["request_branch"] == (
        "A0_HOST_PREISSUANCE_CANDIDATE"
    )
    assert candidate["execution_summary"]["compiled_artifact_count"] == 4
    assert candidate["execution_summary"]["retrieval_executed"] is False
    assert candidate["execution_summary"]["writes_performed"] is False


def test_step1_understands_source_before_blind_seed_or_knowledge() -> None:
    candidate = compile_source_first_kernel_session_candidate(**_inputs())
    artifacts = candidate["artifacts"]
    understanding = artifacts["source_understanding"]
    formalization = artifacts["source_faithful_formalization"]
    seed = artifacts["blind_mechanism_seed"]
    assert understanding["novel_concepts_not_yet_mapped"] == ["局部价格能量集中"]
    assert understanding["taxonomy_required_before_understanding"] is False
    assert understanding["knowledge_or_retrieval_consulted"] is False
    assert formalization["source_understanding_content_sha256"] == understanding[
        "content_sha256"
    ]
    assert formalization["knowledge_or_retrieval_consulted"] is False
    assert seed["formalization_content_sha256"] == formalization["content_sha256"]
    assert seed["knowledge_or_retrieval_consulted"] is False
    assert [row["stage"] for row in candidate["session_envelope"]["ordered_stage_bindings"]] == [
        "SOURCE_UNDERSTANDING",
        "SOURCE_FAITHFUL_FORMALIZATION",
        "BLIND_MECHANISM_SEED",
        "A0_REQUEST_CANDIDATE",
    ]
    guarantees = candidate["source_first_guarantees"]
    assert guarantees[
        "knowledge_policy_allows_supplement_only_after_blind_seed"
    ] is True
    assert guarantees["adapter_retrieval_or_knowledge_access_before_blind_seed"] is False
    assert guarantees["caller_claimed_pre_retrieval_semantic_origin"] is True
    assert guarantees["caller_semantic_origin_independently_verified"] is False
    assert guarantees["strong_no_knowledge_consultation_attestation_present"] is False

    provenance = candidate["formalization_provenance"]
    assert provenance["field_count"] == 14
    assert provenance["caller_claimed_source_grounded_field_count"] == 2
    assert provenance["pre_retrieval_analyst_inference_field_count"] == 2
    assert provenance["new_assumption_field_count"] == 9
    assert provenance["unresolved_field_count"] == 1
    assert provenance["strong_source_faithful_claim_allowed"] is False


def test_all_inputs_are_explicitly_committed_without_ambient_discovery() -> None:
    candidate = compile_source_first_kernel_session_candidate(**_inputs())
    binding = candidate["explicit_input_binding"]
    assert binding["input_count"] == 8
    assert [row["input_name"] for row in binding["input_commitments"]] == [
        "source_bytes",
        "source_lineage",
        "author_claims",
        "analyst_notes",
        "selected_semantic_body",
        "formalization_provenance",
        "pre_a0_predictions",
        "phase_policy_candidate",
    ]
    assert binding["ambient_discovery_performed"] is False
    assert binding["environment_lookup_performed"] is False
    assert binding["filesystem_read_performed"] is False
    assert binding["network_access_performed"] is False
    assert binding["source_content_embedded"] is False
    assert binding["semantic_input_values_embedded"] is False


def test_explicit_source_or_semantic_input_substitution_fails_replay() -> None:
    inputs = _inputs()
    candidate = compile_source_first_kernel_session_candidate(**inputs)
    substituted = dict(inputs)
    substituted["source_bytes"] = SOURCE_BYTES + b"x"
    with pytest.raises(SourceFirstKernelAdapterOfflineError, match="replay_equality"):
        validate_source_first_kernel_session_candidate(candidate, **substituted)

    changed = dict(inputs)
    changed["selected_semantic_body"] = copy.deepcopy(inputs["selected_semantic_body"])
    changed["selected_semantic_body"]["economic_mechanism_claim"] = "另一条机制。"
    with pytest.raises(SourceFirstKernelAdapterOfflineError, match="replay_equality"):
        validate_source_first_kernel_session_candidate(candidate, **changed)


def test_artifact_tamper_and_outer_rehash_still_fail_closed() -> None:
    inputs = _inputs()
    candidate = compile_source_first_kernel_session_candidate(**inputs)
    tampered = copy.deepcopy(candidate)
    tampered["artifacts"]["source_understanding"][
        "knowledge_or_retrieval_consulted"
    ] = True
    tampered = _rehash_outer(tampered)
    with pytest.raises(ValueError):
        validate_source_first_kernel_session_candidate(tampered, **inputs)


def test_lawful_abstention_is_a_runnable_terminal_candidate() -> None:
    body = {
        "disposition": "LAWFUL_ABSTENTION",
        "selected_statement_ids": ["source-claim-1"],
        "reason_code": "UNDER_SPECIFIED",
        "clarification_questions": ["谁承担约束成本？"],
        "structural_anchor_disposition": "TERMINAL_CLARIFICATION",
    }
    inputs = _inputs(
        analyst_notes=[],
        selected_semantic_body=body,
        formalization_provenance=None,
        pre_a0_predictions=[],
        phase_policy_candidate=None,
    )
    candidate = compile_source_first_kernel_session_candidate(**inputs)
    assert candidate["artifacts"]["blind_mechanism_seed"]["seed_body"]["seed_branch"] == (
        "LAWFUL_ABSTENTION_NO_SEED"
    )
    assert candidate["session_envelope"]["terminal"]["session_state"] == (
        "TERMINAL_LAWFUL_ABSTENTION"
    )
    validate_source_first_kernel_session_candidate(candidate, **inputs)


def test_caller_cannot_expand_source_lineage_or_hide_knowledge_field() -> None:
    lineage = _lineage()
    lineage["knowledge_index"] = "legacy"
    with pytest.raises(ValueError):
        compile_source_first_kernel_session_candidate(
            **_inputs(source_lineage=lineage)
        )

    expanded = compile_source_first_kernel_session_candidate(**_inputs())
    expanded = copy.deepcopy(expanded)
    expanded["source_first_guarantees"]["knowledge_index_available"] = True
    expanded = _rehash_outer(expanded)
    with pytest.raises(SourceFirstKernelAdapterOfflineError, match="closed_fields"):
        validate_source_first_kernel_session_candidate(expanded, **_inputs())


def test_external_model_cannot_be_mislabelled_source_grounded() -> None:
    body = _formalized_body()
    body["mathematical_object"] = "卡尔曼状态空间与小波卷积混合模型。"
    provenance = _provenance()
    math_row = provenance["field_rows"][5]
    assert math_row["field_name"] == "mathematical_object"
    math_row["provenance_class"] = "CALLER_CLAIMED_SOURCE_GROUNDED"
    math_row["statement_ids"] = ["source-claim-1"]

    with pytest.raises(
        SourceFirstKernelAdapterOfflineError,
        match="no_lexical_grounding",
    ):
        compile_source_first_kernel_session_candidate(
            **_inputs(
                selected_semantic_body=body,
                formalization_provenance=provenance,
            )
        )

    math_row["provenance_class"] = "NEW_ASSUMPTION"
    math_row["statement_ids"] = []
    candidate = compile_source_first_kernel_session_candidate(
        **_inputs(
            selected_semantic_body=body,
            formalization_provenance=provenance,
        )
    )
    assert candidate["formalization_provenance"]["strong_source_faithful_claim_allowed"] is False


def test_legacy_source_grounded_label_is_rejected_as_overclaim() -> None:
    provenance = _provenance()
    provenance["field_rows"][2]["provenance_class"] = "SOURCE_GROUNDED"

    with pytest.raises(
        SourceFirstKernelAdapterOfflineError,
        match="provenance_class",
    ):
        compile_source_first_kernel_session_candidate(
            **_inputs(formalization_provenance=provenance)
        )
