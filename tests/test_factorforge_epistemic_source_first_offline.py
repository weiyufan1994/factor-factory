from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import pytest

from factor_factory.epistemic_source_first_offline import (
    AUTHORITY_EFFECT,
    A0_REQUEST_DOMAIN,
    FORMALIZATION_DOMAIN,
    QUERY_CANDIDATE_DOMAIN,
    SourceFirstOfflineError,
    _with_content_sha,
    compile_a0_request_candidate,
    compile_blind_mechanism_seed,
    compile_formalization_or_abstention,
    compile_source_understanding_bundle,
    validate_source_first_bundle,
    validate_source_first_offline_candidate_packet,
    write_source_first_offline_candidate_packet,
)
from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SOURCE_BYTES = (
    "用户假设：当小盘股持仓过度拥挤、边际流动性提供者撤退时，"
    "被迫卖出会在多个时间尺度形成局部价格能量集中。"
).encode("utf-8")


def _lineage(**overrides) -> dict:
    payload = {
        "source_type": "USER_ORAL_OR_TEXT_HYPOTHESIS",
        "source_event_ref": "user-message-20260829-001",
        "source_legally_available_at": "2026-08-29T09:00:00Z",
        "language": "zh-CN",
        "source_integrity_status": "VERIFIED",
        "understanding_completeness": "COMPLETE_ENOUGH_TO_FORMALIZE",
        "source_reader_context_status": "SOURCE_ONLY_CANDIDATE",
        "selection_lineage_claim": "EX_ANTE_UNSELECTED_CLAIMED",
        "proposer_outcome_exposure_claim": "NONE_CLAIMED",
        "source_outcome_status": "SOURCE_OUTCOME_FREE",
        "missing_source_components": [],
        "novel_concepts_not_yet_mapped": ["局部价格能量集中"],
        "internal_tensions": ["拥挤与流动性撤退的先后方向尚需区分"],
    }
    payload.update(overrides)
    return payload


def _author_claims() -> list[dict]:
    return [
        {
            "statement_id": "source-claim-1",
            "classification": "SOURCE_NATIVE_EXPLICIT",
            "text": "小盘股持仓可能出现过度拥挤。",
            "source_locators": ["message:sentence:1"],
            "depends_on_statement_ids": [],
        },
        {
            "statement_id": "source-claim-2",
            "classification": "AGENT_PARAPHRASE",
            "text": "流动性提供者撤退与被迫卖出共同塑造价格路径。",
            "source_locators": ["message:sentence:1"],
            "depends_on_statement_ids": ["source-claim-1"],
        },
    ]


def _analyst_notes() -> list[dict]:
    return [
        {
            "statement_id": "analyst-inference-1",
            "classification": "AGENT_INFERENCE",
            "text": "该机制可被表述为受约束持有者向剩余流动性供给者支付价格冲击成本。",
            "source_locators": [],
            "depends_on_statement_ids": ["source-claim-1", "source-claim-2"],
        },
        {
            "statement_id": "analyst-unknown-1",
            "classification": "UNRESOLVED",
            "text": "拥挤状态的最小充分统计量尚未确定。",
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
        "economic_mechanism_claim": "拥挤持有者在流动性撤退时被迫向剩余承接者支付冲击成本。",
        "payer_or_constraint": "融资和风险限额约束下的拥挤持有者。",
        "estimand": "未来短周期相对收益对当前多尺度局部能量集中的条件响应。",
        "information_set": "仅使用决策时点及之前的价格与成交量路径。",
        "horizon": "未来五个交易日。",
        "mathematical_object": "多尺度局部化时频能量与尺度间相位一致性。",
        "broken_invariant_or_boundary": "常态流动性下尺度能量分散；撤退时局部尺度能量集中。",
        "observation_mapping": "将价格增量投影到预注册的小波尺度并汇总局部能量比。",
        "failure_signature": "若能量集中不随拥挤或流动性约束增强而变化，则机制失效。",
        "falsifiers": [
            "控制波动率后局部能量比不再与未来路径相关。",
            "大盘高流动性股票出现同等强度且同方向的现象。",
        ],
        "material_rivals": [
            "局部能量集中仅是波动率机械放大。",
            "信号来自反转而非拥挤持有者的约束。",
        ],
        "regime_hypotheses": ["融资收紧时效应增强。"],
        "new_assumptions": ["成交量可作为边际流动性供给变化的有噪声代理。"],
        "clarification_questions": ["拥挤状态是否要求持仓数据，还是只做潜变量？"],
    }


def _predictions() -> list[dict]:
    return [
        {
            "prediction_id": "prediction-1",
            "prediction": "局部能量集中与短期负向相对收益相关。",
            "horizon": "未来五个交易日。",
            "expected_direction": "NEGATIVE",
            "falsified_when": "关系在波动率匹配后消失。",
        },
        {
            "prediction_id": "prediction-2",
            "prediction": "融资收紧样本中的关系更强。",
            "horizon": "未来五个交易日。",
            "expected_direction": "MORE_NEGATIVE_IN_TIGHT_REGIME",
            "falsified_when": "宽松样本与收紧样本无差异。",
        },
    ]


def _policy(**overrides) -> dict:
    payload = {
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
    payload.update(overrides)
    return payload


def _compiled() -> tuple[dict, dict, dict, dict]:
    understanding = compile_source_understanding_bundle(
        SOURCE_BYTES, _lineage(), _author_claims(), _analyst_notes()
    )
    formalization = compile_formalization_or_abstention(
        understanding, _formalized_body()
    )
    seed = compile_blind_mechanism_seed(formalization, _predictions())
    request = compile_a0_request_candidate(seed, _policy())
    return understanding, formalization, seed, request


def test_source_is_understood_before_taxonomy_model_or_retrieval() -> None:
    understanding = compile_source_understanding_bundle(
        SOURCE_BYTES, _lineage(), _author_claims(), _analyst_notes()
    )
    assert understanding["knowledge_or_retrieval_consulted"] is False
    assert understanding["taxonomy_required_before_understanding"] is False
    assert understanding["implementation_or_data_availability_consulted"] is False
    assert understanding["novel_concepts_not_yet_mapped"] == ["局部价格能量集中"]
    classes = {
        row["statement_id"]: row["classification"]
        for row in understanding["semantic_statements"]
    }
    assert classes == {
        "source-claim-1": "SOURCE_NATIVE_EXPLICIT",
        "source-claim-2": "AGENT_PARAPHRASE",
        "analyst-inference-1": "AGENT_INFERENCE",
        "analyst-unknown-1": "UNRESOLVED",
    }
    assert understanding["candidate_blind_semantic_eligibility"] == (
        "ELIGIBLE_CANDIDATE_ONLY"
    )
    assert understanding["formal_a0_authority_present"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda claims, notes: claims[0].__setitem__("classification", "AGENT_INFERENCE"),
        lambda claims, notes: claims[0].__setitem__("source_locators", []),
        lambda claims, notes: notes[0].__setitem__("depends_on_statement_ids", []),
        lambda claims, notes: notes[0].__setitem__("knowledge_node_id", "legacy"),
    ],
)
def test_statement_provenance_cannot_cross_or_expand(mutation) -> None:
    claims = _author_claims()
    notes = _analyst_notes()
    mutation(claims, notes)
    with pytest.raises(SourceFirstOfflineError):
        compile_source_understanding_bundle(SOURCE_BYTES, _lineage(), claims, notes)


def test_formalization_is_after_understanding_and_keeps_math_semantic_not_implementation() -> None:
    understanding, formalization, seed, request = _compiled()
    assert formalization["source_understanding_content_sha256"] == understanding["content_sha256"]
    assert formalization["formalization_body"]["mathematical_object"].startswith("多尺度")
    assert formalization["knowledge_or_retrieval_consulted"] is False
    assert seed["formalization_content_sha256"] == formalization["content_sha256"]
    assert seed["seed_body"]["mechanism_fingerprint"]["mathematical_object"].startswith("多尺度")
    assert request["private_replay_binding"]["blind_seed_content_sha256"] == seed["content_sha256"]
    assert seed["factor_view_created"] is False


def test_lawful_abstention_is_terminal_and_creates_zero_lanes() -> None:
    understanding = compile_source_understanding_bundle(
        SOURCE_BYTES,
        _lineage(),
        _author_claims(),
        [],
    )
    abstention = compile_formalization_or_abstention(
        understanding,
        {
            "disposition": "LAWFUL_ABSTENTION",
            "selected_statement_ids": ["source-claim-1"],
            "reason_code": "UNDER_SPECIFIED",
            "clarification_questions": ["谁承担约束成本？"],
            "structural_anchor_disposition": "TERMINAL_CLARIFICATION",
        },
    )
    seed = compile_blind_mechanism_seed(abstention, [])
    request = compile_a0_request_candidate(seed, None)
    assert seed["seed_body"]["seed_branch"] == "LAWFUL_ABSTENTION_NO_SEED"
    assert request["request_branch"] == "NO_A0_REQUEST_LAWFUL_ABSTENTION"
    assert request["agent_visible_projection"] is None
    assert request["retrieval_executed"] is False
    with pytest.raises(SourceFirstOfflineError, match="a0_policy_forbidden"):
        compile_a0_request_candidate(seed, _policy())


@pytest.mark.parametrize(
    "lineage_override",
    [
        {"selection_lineage_claim": "OUTCOME_DERIVED"},
        {"proposer_outcome_exposure_claim": "PARENT_OOS_SEEN"},
        {"source_reader_context_status": "UNKNOWN"},
        {"source_outcome_status": "EMBEDDED_OUTCOMES_CAPTURED"},
    ],
)
def test_tainted_nonblind_or_outcome_source_cannot_create_a0_seed(lineage_override) -> None:
    understanding = compile_source_understanding_bundle(
        SOURCE_BYTES,
        _lineage(**lineage_override),
        _author_claims(),
        _analyst_notes(),
    )
    formalization = compile_formalization_or_abstention(
        understanding, _formalized_body()
    )
    with pytest.raises(SourceFirstOfflineError, match="predictions_forbidden"):
        compile_blind_mechanism_seed(formalization, _predictions())
    seed = compile_blind_mechanism_seed(formalization, [])
    request = compile_a0_request_candidate(seed, None)
    assert seed["seed_body"]["seed_branch"] == "A0_INELIGIBLE_NO_SEED"
    assert request["request_branch"] == "NO_A0_REQUEST_INELIGIBLE"
    with pytest.raises(SourceFirstOfflineError, match="a0_policy_forbidden"):
        compile_a0_request_candidate(seed, _policy())


def test_offline_a0_candidate_waits_for_host_mint_and_keeps_query_private() -> None:
    understanding, formalization, seed, request = _compiled()
    assert request["agent_visible_projection"] is None
    assert request["request_branch"] == "A0_HOST_PREISSUANCE_CANDIDATE"
    assert request["host_minted_single_use_opaque_handle_required"] is True
    assert request["request_not_issuable"] is True
    assert request["retrieval_executed"] is False
    candidate = request["private_preissuance_request_candidate"]
    assert candidate["phase"] == "A0"
    assert candidate["phase_policy_candidate"]["requested_lane_subset"][-1] == (
        "direct_counterexample"
    )
    assert all(
        set(atom) == {"atom_kind", "semantic_text"}
        for atoms in candidate["query_semantics_candidate"].values()
        for atom in atoms
    )
    validate_source_first_bundle(
        understanding=understanding,
        formalization=formalization,
        blind_seed=seed,
        a0_request_candidate=request,
    )


def test_offline_candidate_is_deterministic_and_never_serializes_session_secret() -> None:
    first = _compiled()[3]
    replay = _compiled()[3]
    assert first == replay
    serialized = repr(first)
    assert "session_secret" not in serialized
    assert "opaque_request_handle" not in serialized
    assert "opq_" not in serialized


@pytest.mark.parametrize(
    "poison_text",
    [
        "参考 s3://private-bucket/index.json 的同类机制。",
        "读取 /tmp/factor-index 后再决定。",
        "case UUID 是 123e4567-e89b-12d3-a456-426614174000。",
        "对应 Git 对象 0123456789abcdef0123456789abcdef01234567。",
        "复用 fvh::stable-factor 的数学对象。",
        "index_health is PASS，因此可使用。",
        "索引缺失时退回旧知识库。",
    ],
)
def test_preissuance_query_semantics_reject_locator_and_index_side_channels(
    poison_text: str,
) -> None:
    understanding = compile_source_understanding_bundle(
        SOURCE_BYTES, _lineage(), _author_claims(), _analyst_notes()
    )
    body = _formalized_body()
    body["mathematical_object"] = poison_text
    formalization = compile_formalization_or_abstention(understanding, body)
    seed = compile_blind_mechanism_seed(formalization, _predictions())
    with pytest.raises(SourceFirstOfflineError):
        compile_a0_request_candidate(seed, _policy())


def _rehash_tampered_request(request: dict) -> dict:
    candidate = request["private_preissuance_request_candidate"]
    candidate["query_semantics_candidate_sha256"] = framed_sha256(
        QUERY_CANDIDATE_DOMAIN, candidate["query_semantics_candidate"]
    )
    return _with_content_sha(
        {key: value for key, value in request.items() if key != "content_sha256"},
        domain=A0_REQUEST_DOMAIN,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda query: query["economic_game_semantics"][0].__setitem__(
            "semantic_text", "另一套完全不同但表面合法的机制。"
        ),
        lambda query: (
            query["economic_game_semantics"].__setitem__(
                0, query["latent_mechanism_semantics"][0]
            ),
            query["latent_mechanism_semantics"].__setitem__(
                0, query["economic_game_semantics"][1]
            ),
        ),
        lambda query: query["economic_game_semantics"][0].__setitem__(
            "atom_kind", "PAYER_OR_CONSTRAINT"
        ),
        lambda query: query["falsifier_semantics"].reverse(),
        lambda query: query["falsifier_semantics"].pop(),
        lambda query: query["falsifier_semantics"].append(
            {"atom_kind": "FALSIFIER", "semantic_text": "新增但未冻结的反证。"}
        ),
    ],
)
def test_query_substitution_lane_swap_and_falsifier_drift_fail_closed(mutation) -> None:
    understanding, formalization, seed, request = _compiled()
    tampered = copy.deepcopy(request)
    mutation(
        tampered["private_preissuance_request_candidate"][
            "query_semantics_candidate"
        ]
    )
    tampered = _rehash_tampered_request(tampered)
    with pytest.raises(SourceFirstOfflineError, match="blind_seed_closed_equality"):
        validate_source_first_bundle(
            understanding=understanding,
            formalization=formalization,
            blind_seed=seed,
            a0_request_candidate=tampered,
        )


def test_cross_seed_query_splice_fails_closed() -> None:
    understanding, formalization, seed, request = _compiled()
    second_body = _formalized_body()
    second_body["economic_mechanism_claim"] = "另一条不相容的风险转移机制。"
    second_formalization = compile_formalization_or_abstention(
        understanding, second_body
    )
    second_seed = compile_blind_mechanism_seed(second_formalization, _predictions())
    second_request = compile_a0_request_candidate(second_seed, _policy())
    spliced = copy.deepcopy(request)
    spliced_candidate = spliced["private_preissuance_request_candidate"]
    second_candidate = second_request["private_preissuance_request_candidate"]
    spliced_candidate["query_semantics_candidate"] = copy.deepcopy(
        second_candidate["query_semantics_candidate"]
    )
    spliced = _rehash_tampered_request(spliced)
    with pytest.raises(SourceFirstOfflineError, match="blind_seed_closed_equality"):
        validate_source_first_bundle(
            understanding=understanding,
            formalization=formalization,
            blind_seed=seed,
            a0_request_candidate=spliced,
        )


@pytest.mark.parametrize(
    "policy_mutation",
    [
        lambda policy: policy.__setitem__("index_health", "PASS"),
        lambda policy: policy.__setitem__("phase", "B2_POST"),
        lambda policy: policy.__setitem__("requested_lane_subset", ["structural_isomorph"]),
    ],
)
def test_hidden_phase_or_caller_expansion_cannot_enter_a0_policy(policy_mutation) -> None:
    _, _, seed, _ = _compiled()
    policy = _policy()
    policy_mutation(policy)
    with pytest.raises(SourceFirstOfflineError):
        compile_a0_request_candidate(seed, policy)


def test_splice_reorder_extra_field_and_visible_identity_fail_closed() -> None:
    understanding, formalization, seed, request = _compiled()
    reordered = copy.deepcopy(understanding)
    reordered["semantic_statements"].reverse()
    reordered = _with_content_sha(
        {key: value for key, value in reordered.items() if key != "content_sha256"},
        domain="FF_SOURCE_FIRST_OFFLINE_UNDERSTANDING_CANDIDATE_V1",
    )
    with pytest.raises(SourceFirstOfflineError):
        validate_source_first_bundle(
            understanding=reordered,
            formalization=formalization,
            blind_seed=seed,
            a0_request_candidate=request,
        )

    expanded = copy.deepcopy(request)
    expanded["agent_visible_projection"] = {"source_id": "stable-source"}
    expanded = _with_content_sha(
        {key: value for key, value in expanded.items() if key != "content_sha256"},
        domain=A0_REQUEST_DOMAIN,
    )
    with pytest.raises(SourceFirstOfflineError, match="agent_visible"):
        validate_source_first_bundle(
            understanding=understanding,
            formalization=formalization,
            blind_seed=seed,
            a0_request_candidate=expanded,
        )

    wrong = copy.deepcopy(formalization)
    wrong["formalization_body"]["implementation_mode"] = "wavelet_library"
    wrong = _with_content_sha(
        {key: value for key, value in wrong.items() if key != "content_sha256"},
        domain=FORMALIZATION_DOMAIN,
    )
    with pytest.raises(SourceFirstOfflineError):
        validate_source_first_bundle(
            understanding=understanding,
            formalization=wrong,
            blind_seed=seed,
            a0_request_candidate=request,
        )


def _packet_inputs(source_path: Path) -> dict:
    return {
        "source_path": source_path,
        "source_lineage": _lineage(),
        "author_claims": _author_claims(),
        "analyst_notes": _analyst_notes(),
        "selected_semantic_body": _formalized_body(),
        "pre_a0_predictions": _predictions(),
        "phase_policy_candidate": _policy(),
    }


def test_packet_is_exact6_immutable_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(SOURCE_BYTES)
    first = tmp_path / "packet-a"
    second = tmp_path / "packet-b"
    first_manifest = write_source_first_offline_candidate_packet(
        first, **_packet_inputs(source)
    )
    second_manifest = write_source_first_offline_candidate_packet(
        second, **_packet_inputs(source)
    )
    expected_names = {
        "packet_manifest.json",
        "00_source_understanding_candidate.json",
        "01_source_faithful_formalization_candidate.json",
        "02_blind_mechanism_seed_candidate.json",
        "03_a0_request_candidate.json",
        "04_local_validation_report.json",
    }
    assert {path.name for path in first.iterdir()} == expected_names
    assert first_manifest == second_manifest
    for name in expected_names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert first_manifest["authority_effect"] == AUTHORITY_EFFECT
    assert first_manifest["permissions_opened_count"] == 0
    assert first_manifest["source_bytes_sha256"] == hashlib.sha256(SOURCE_BYTES).hexdigest()
    validated = validate_source_first_offline_candidate_packet(
        first / "packet_manifest.json", source_path=source
    )
    assert validated == first_manifest


def test_packet_tamper_extra_file_and_source_substitution_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(SOURCE_BYTES)
    packet = tmp_path / "packet"
    write_source_first_offline_candidate_packet(packet, **_packet_inputs(source))
    substituted = tmp_path / "substituted.txt"
    substituted.write_bytes(b"x" * len(SOURCE_BYTES))
    with pytest.raises(SourceFirstOfflineError, match="external_source_sha256"):
        validate_source_first_offline_candidate_packet(
            packet / "packet_manifest.json", source_path=substituted
        )
    (packet / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SourceFirstOfflineError, match="exact6_closure"):
        validate_source_first_offline_candidate_packet(
            packet / "packet_manifest.json", source_path=source
        )


def test_packet_and_source_symlink_or_hardlink_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(SOURCE_BYTES)
    source_link = tmp_path / "source-link.txt"
    source_link.symlink_to(source)
    with pytest.raises(SourceFirstOfflineError, match="source_file:unsafe"):
        write_source_first_offline_candidate_packet(
            tmp_path / "symlink-source-packet", **_packet_inputs(source_link)
        )

    packet = tmp_path / "packet"
    write_source_first_offline_candidate_packet(packet, **_packet_inputs(source))
    artifact = packet / "00_source_understanding_candidate.json"
    os.link(artifact, tmp_path / "artifact-hardlink.json")
    with pytest.raises(SourceFirstOfflineError, match="packet_entry:unsafe"):
        validate_source_first_offline_candidate_packet(
            packet / "packet_manifest.json", source_path=source
        )


def test_packet_json_is_strict_and_source_bytes_are_not_embedded(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(SOURCE_BYTES)
    packet = tmp_path / "packet"
    write_source_first_offline_candidate_packet(packet, **_packet_inputs(source))
    for path in packet.iterdir():
        payload = strict_json_loads(path.read_bytes(), label=path.name)
        assert isinstance(payload, dict)
        assert SOURCE_BYTES not in path.read_bytes()
        assert b"session_secret" not in path.read_bytes()
        assert b"opq_" not in path.read_bytes()
