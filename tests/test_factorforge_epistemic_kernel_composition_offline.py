from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from factor_factory.epistemic_kernel_composition_offline import (
    EpistemicKernelCompositionError,
    compose_epistemic_kernel_candidate,
    validate_epistemic_kernel_composition,
)
from factor_factory.epistemic_retrieval_kernel_adapter_offline import (
    build_cross_math_analogy_demo_inputs,
)
from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    FORMALIZATION_SEMANTIC_FIELDS,
)


DIAGNOSIS_FIXTURE_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-20260829/diagnosis-fixture.json"
)
DIAGNOSIS_ASSERTION_DAG_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-r3-20260829/"
    "assertion-dependency-dag.json"
)
DIAGNOSIS_STAGE2_MANIFEST = Path(
    "/Users/researcher/projects/"
    "factor-forge-phase-safe-retrieval-standalone-prototype-r3-20260829/"
    "packet_manifest.json"
)


def _source_inputs() -> dict:
    formalization = {
        "disposition": "FORMALIZED",
        "selected_statement_ids": ["source-claim-1", "source-claim-2", "analyst-inference-1"],
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
    return {
        "source_bytes": (
            "用户假设：当小盘股持仓过度拥挤、边际流动性提供者撤退时，"
            "被迫卖出会在多个时间尺度形成局部价格能量集中。"
        ).encode("utf-8"),
        "source_lineage": {
            "source_type": "USER_ORAL_OR_TEXT_HYPOTHESIS",
            "source_event_ref": "user-message-20260831-001",
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
            "internal_tensions": ["拥挤与流动性撤退的先后方向尚需区分"],
        },
        "author_claims": [
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
        ],
        "analyst_notes": [
            {
                "statement_id": "analyst-inference-1",
                "classification": "AGENT_INFERENCE",
                "text": "该机制可被表述为受约束持有者向剩余流动性供给者支付价格冲击成本。",
                "source_locators": [],
                "depends_on_statement_ids": ["source-claim-1", "source-claim-2"],
            },
            {
                "statement_id": "analyst-unresolved-1",
                "classification": "UNRESOLVED",
                "text": "拥挤状态需要持仓数据还是潜变量尚未解决。",
                "source_locators": [],
                "depends_on_statement_ids": ["source-claim-1"],
            },
        ],
        "selected_semantic_body": formalization,
        "formalization_provenance": _formalization_provenance(),
        "pre_a0_predictions": [
            {
                "prediction_id": "prediction-1",
                "prediction": "局部能量集中与短期负向相对收益相关。",
                "horizon": "未来五个交易日。",
                "expected_direction": "NEGATIVE",
                "falsified_when": "关系在波动率匹配后消失。",
            }
        ],
        "phase_policy_candidate": {
            "policy_version": "source-first-offline-a0-candidate-v1",
            "phase": "A0",
            "requested_lane_subset": [
                "structural_isomorph",
                "cross_math_analogy",
                "near_miss_failure",
                "direct_counterexample",
            ],
            "top_k_per_lane": 2,
        },
    }


def _formalization_provenance() -> dict:
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
            ["source-claim-2"],
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
    return {
        "attestation_mode": (
            "CALLER_CLAIMED_PRE_RETRIEVAL__NOT_INDEPENDENTLY_VERIFIED"
        ),
        "field_rows": [
            {
                "ordinal": ordinal,
                "field_name": field_name,
                "provenance_class": bindings.get(
                    field_name,
                    ("NEW_ASSUMPTION", []),
                )[0],
                "statement_ids": bindings.get(
                    field_name,
                    ("NEW_ASSUMPTION", []),
                )[1],
            }
            for ordinal, field_name in enumerate(FORMALIZATION_SEMANTIC_FIELDS)
        ],
    }


def _corpus(source: dict) -> list[dict]:
    corpus = copy.deepcopy(build_cross_math_analogy_demo_inputs()["corpus_objects"])
    body = source["selected_semantic_body"]
    for row in corpus:
        payload = row["semantic_payload"]
        cross_math = list(payload["mathematical_family_semantics"])
        payload["economic_game_semantics"] = [
            body["economic_mechanism_claim"],
            body["payer_or_constraint"],
        ]
        payload["latent_mechanism_semantics"] = [
            body["broken_invariant_or_boundary"],
            body["observation_mapping"],
        ]
        payload["mathematical_family_semantics"] = [
            body["mathematical_object"],
            *cross_math,
        ]
        payload["falsifier_semantics"] = [body["falsifiers"][0]]
    return corpus


def _load_cli_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "build_factorforge_epistemic_kernel_offline_candidate.py"
    spec = importlib.util.spec_from_file_location("epistemic_kernel_cli_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_end_to_end_source_first_then_a0_retrieval() -> None:
    source = _source_inputs()
    candidate = compose_epistemic_kernel_candidate(
        source_inputs=source,
        retrieval_corpus_objects=_corpus(source),
        session_scope_secret=b"s" * 32,
    )

    advisory = candidate["chief_research_advisory"]
    assert advisory["source_first"]["novel_concepts_not_yet_mapped"] == [
        "局部价格能量集中"
    ]
    assert advisory["knowledge_priors"]["result"] == "HIT"
    assert advisory["knowledge_priors"]["may_rewrite_source_understanding_or_blind_seed"] is False
    assert advisory["source_first"]["formalization_provenance"][
        "caller_semantic_origin_independently_verified"
    ] is False
    assert advisory["exploit_and_explore"]["exploit_candidates"]
    assert advisory["exploit_and_explore"]["explore_candidates"]
    assert advisory["exploit_and_explore"]["challenge_candidates"]
    assert advisory["exploit_and_explore"]["dummy_branch_required"] is False
    assert advisory["next_step"] == (
        "STEP1_POST_A0_MODEL_DIVERSIFICATION_AND_MEASUREMENT_PROGRAM"
    )
    lanes = candidate["stage_outputs"]["retrieval"]["agent_visible_projection"][
        "lanes"
    ]
    assert [lane["lane"] for lane in lanes] == [
        "structural_isomorph",
        "cross_math_analogy",
        "near_miss_failure",
        "direct_counterexample",
    ]
    assert all(lane["items"] for lane in lanes)
    groups = advisory["knowledge_priors"]["precedent_groups"]
    lane_assignments = advisory["knowledge_priors"]["lane_assignments"]
    assert advisory["knowledge_priors"]["unique_precedent_group_count"] == len(
        groups
    )
    assert len({row["precedent_group_handle"] for row in groups}) == len(groups)
    known_groups = {row["precedent_group_handle"] for row in groups}
    assert {
        assignment["precedent_group_handle"]
        for lane in lane_assignments
        for assignment in lane["assignments"]
    } == known_groups
    assert all(
        row["precedent_group_handle"] in known_groups
        for key in ("exploit_candidates", "explore_candidates")
        for row in advisory["exploit_and_explore"][key]
    )
    assert all(
        row["precedent_group_handle"] in known_groups
        for row in advisory["exploit_and_explore"]["challenge_candidates"]
    )
    math_text = " ".join(
        item_text
        for group in groups
        for item_text in group["advisory_payload"]["mathematical_analogy"]
    )
    assert "wavelet" in math_text
    assert "Kalman" in math_text
    assert "convolutional" in math_text
    assert "variational" in math_text
    assert candidate["execution_summary"]["oos_access_performed"] is False
    assert candidate["replay_scope"] == {
        "status": "PUBLISHER_TIME_FULL_REPLAY_VALIDATED__NON_SELF_CONTAINED",
        "standalone_replay_from_delivery_only_supported": False,
        "original_external_inputs_required": True,
        "source_input_names": sorted(
            {
                "source_bytes",
                "source_lineage",
                "author_claims",
                "analyst_notes",
                "selected_semantic_body",
                "formalization_provenance",
                "pre_a0_predictions",
                "phase_policy_candidate",
            }
        ),
        "retrieval_external_input_mode": "SYNTHETIC_CORPUS_PLUS_SESSION_SECRET",
        "diagnosis_external_input_mode": "NONE",
        "external_dependency_bytes_embedded_for_standalone_replay": False,
        "session_scope_secret_persisted": False,
        "candidate_only": True,
        "authority_effect": "NONE",
    }

    validate_epistemic_kernel_composition(
        candidate,
        source_inputs=source,
        retrieval_corpus_objects=_corpus(source),
        session_scope_secret=b"s" * 32,
    )


def test_composition_tamper_fails_full_replay() -> None:
    source = _source_inputs()
    corpus = _corpus(source)
    candidate = compose_epistemic_kernel_candidate(
        source_inputs=source,
        retrieval_corpus_objects=corpus,
        session_scope_secret=b"t" * 32,
    )
    tampered = copy.deepcopy(candidate)
    tampered["chief_research_advisory"]["knowledge_priors"][
        "may_rewrite_source_understanding_or_blind_seed"
    ] = True

    with pytest.raises(EpistemicKernelCompositionError):
        validate_epistemic_kernel_composition(
            tampered,
            source_inputs=source,
            retrieval_corpus_objects=corpus,
            session_scope_secret=b"t" * 32,
        )


def test_wrong_session_secret_changes_all_opaque_handles() -> None:
    source = _source_inputs()
    corpus = _corpus(source)
    left = compose_epistemic_kernel_candidate(
        source_inputs=source,
        retrieval_corpus_objects=corpus,
        session_scope_secret=b"a" * 32,
    )
    right = compose_epistemic_kernel_candidate(
        source_inputs=source,
        retrieval_corpus_objects=corpus,
        session_scope_secret=b"b" * 32,
    )

    left_handles = {
        item["handle"]
        for lane in left["stage_outputs"]["retrieval"]["agent_visible_projection"][
            "lanes"
        ]
        for item in lane["items"]
    }
    right_handles = {
        item["handle"]
        for lane in right["stage_outputs"]["retrieval"]["agent_visible_projection"][
            "lanes"
        ]
        for item in lane["items"]
    }
    assert left_handles
    assert left_handles.isdisjoint(right_handles)


def test_end_to_end_real_repository_knowledge_graph_is_phase_sanitized() -> None:
    source = _source_inputs()
    root = Path(__file__).resolve().parents[1]
    graph = root / "knowledge" / "因子工厂" / "graph"
    candidate = compose_epistemic_kernel_candidate(
        source_inputs=source,
        real_knowledge_inputs={
            "node_index_path": (graph / "factor_knowledge_nodes.jsonl").resolve(),
            "edge_index_path": (graph / "factor_knowledge_edges.jsonl").resolve(),
            "taxonomy_path": (
                root / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"
            ).resolve(),
            "top_k_per_lane": 2,
        },
        session_scope_secret=b"real-knowledge-session-secret-0001",
    )

    projection = candidate["stage_outputs"]["retrieval"]["agent_visible_projection"]
    assert candidate["replay_scope"]["retrieval_external_input_mode"] == (
        "REAL_GRAPH_AND_SOURCE_NODE_BYTES_PLUS_SESSION_SECRET"
    )
    assert projection["result"] == "HIT"
    assert any(lane["items"] for lane in projection["lanes"])
    advisory = candidate["chief_research_advisory"]
    groups = advisory["knowledge_priors"]["precedent_groups"]
    selected_lane_item_count = sum(
        len(lane["items"]) for lane in projection["lanes"]
    )
    assert len(groups) < selected_lane_item_count
    assert any(len(group["lane_assignments"]) > 1 for group in groups)
    documented_tradeoffs = 0
    for group in groups:
        payload = group["advisory_payload"]
        preserved = payload["information_preserved"]
        lost = payload["information_lost"]
        assert set(preserved).isdisjoint(lost)
        if preserved or lost:
            documented_tradeoffs += 1
            assert preserved
            assert lost
    assert documented_tradeoffs == 2
    assert any(
        len(group["challenge_roles"]) > 1
        for group in advisory["exploit_and_explore"]["challenge_candidates"]
    )
    serialized = repr(projection).casefold()
    for forbidden in (
        "node::",
        "source_node_path",
        "content_sha",
        "rank_ic",
        "sharpe",
        "oos",
        "official",
        str(root).casefold(),
    ):
        assert forbidden not in serialized


def test_composition_consumes_raw_diagnosis_bytes_and_exposes_full_plan() -> None:
    source = _source_inputs()
    candidate = compose_epistemic_kernel_candidate(
        source_inputs=source,
        retrieval_corpus_objects=_corpus(source),
        session_scope_secret=b"diagnosis-session-secret-0000001",
        diagnosis_inputs={
            "stage2_manifest_path": DIAGNOSIS_STAGE2_MANIFEST,
            "fixture_raw_bytes": DIAGNOSIS_FIXTURE_PATH.read_bytes(),
            "assertion_dependency_raw_bytes": (
                DIAGNOSIS_ASSERTION_DAG_PATH.read_bytes()
            ),
        },
    )

    diagnosis = candidate["stage_outputs"]["diagnosis"]
    assert candidate["replay_scope"]["diagnosis_external_input_mode"] == (
        "STAGE2_MANIFEST_FIXTURE_AND_ASSERTION_DAG_BYTES"
    )
    assert diagnosis["diagnostic_tests_executed"] is False
    assert diagnosis["agent_visible_projection"]["lineage"]["diagnosis_id"] == (
        diagnosis["diagnosis_id"]
    )
    assert candidate["source_session_id"] == diagnosis["session_id"]
    assert candidate["session_id"] != candidate["source_session_id"]
    assert candidate["stage_output_bindings"]["diagnosis_content_sha256"] == (
        diagnosis["content_sha256"]
    )
    assert diagnosis["agent_visible_projection"]["distinguishing_tests"]
    assert diagnosis["agent_visible_projection"]["partition_plan"][
        "same_partition_identification_forbidden"
    ] is True


def test_composition_session_identity_changes_with_diagnosis_target() -> None:
    source = _source_inputs()
    fixture = json.loads(DIAGNOSIS_FIXTURE_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(fixture)
    changed["target_identity_candidate"]["hypothesis_candidate_id"] += "-alternative"

    def compile_with(raw: bytes) -> dict:
        return compose_epistemic_kernel_candidate(
            source_inputs=source,
            retrieval_corpus_objects=_corpus(source),
            session_scope_secret=b"diagnosis-lineage-session-secret-01",
            diagnosis_inputs={
                "stage2_manifest_path": DIAGNOSIS_STAGE2_MANIFEST,
                "fixture_raw_bytes": raw,
                "assertion_dependency_raw_bytes": (
                    DIAGNOSIS_ASSERTION_DAG_PATH.read_bytes()
                ),
            },
        )

    left = compile_with(DIAGNOSIS_FIXTURE_PATH.read_bytes())
    right = compile_with(
        json.dumps(
            changed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert left["source_session_id"] == right["source_session_id"]
    assert left["stage_output_bindings"]["retrieval_content_sha256"] == right[
        "stage_output_bindings"
    ]["retrieval_content_sha256"]
    assert left["stage_outputs"]["diagnosis"]["diagnosis_id"] != right[
        "stage_outputs"
    ]["diagnosis"]["diagnosis_id"]
    assert left["session_id"] != right["session_id"]


def test_cli_builds_create_only_three_file_delivery_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    expected_parent = tmp_path / "projects"
    fake_repo = expected_parent / "factor-factory-test-repo"
    fake_repo.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", fake_repo.resolve())
    source = _source_inputs()
    secret_hex = "ab" * 32
    payload = {
        "source_text": source["source_bytes"].decode("utf-8"),
        "source_lineage": source["source_lineage"],
        "author_claims": source["author_claims"],
        "analyst_notes": source["analyst_notes"],
        "selected_semantic_body": source["selected_semantic_body"],
        "formalization_provenance": source["formalization_provenance"],
        "pre_a0_predictions": source["pre_a0_predictions"],
        "phase_policy_candidate": source["phase_policy_candidate"],
        "retrieval_corpus_objects": _corpus(source),
        "real_knowledge_inputs": None,
        "session_scope_secret_hex": secret_hex,
        "diagnosis_inputs": {
            "stage2_manifest_path": str(DIAGNOSIS_STAGE2_MANIFEST),
            "fixture_json_path": str(DIAGNOSIS_FIXTURE_PATH),
            "assertion_dependency_json_path": str(
                DIAGNOSIS_ASSERTION_DAG_PATH
            ),
        },
    }
    candidate = module.build_candidate(payload)
    assert candidate["stage_outputs"]["diagnosis"] is not None
    output = expected_parent / f"{module.OUTPUT_ROOT_PREFIX}candidate-output"
    manifest = module.publish_candidate(
        candidate=candidate,
        input_payload=payload,
        output_root=output,
        allowed_parent=expected_parent,
    )

    assert manifest == output / "packet_manifest.json"
    assert sorted(path.name for path in output.iterdir()) == [
        "00_epistemic_kernel_candidate.json",
        "01_chief_research_advisory.json",
        "packet_manifest.json",
    ]
    published = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert secret_hex not in published
    with pytest.raises(module.OfflineCandidateCliError, match="create_only"):
        module.publish_candidate(
            candidate=candidate,
            input_payload=payload,
            output_root=output,
            allowed_parent=expected_parent,
        )
