from __future__ import annotations

import json
import inspect
from pathlib import Path

import pytest

import factor_factory.epistemic_phase_safe_retrieval_offline as phase_module

from factor_factory.epistemic_phase_safe_retrieval_offline import (
    PHASE_CORPUS_FIELDS,
    compile_offline_corpus,
    compile_phase_request_candidate,
    compile_retrieval_program,
    execute_phase_projection_candidate,
    validate_phase_safe_retrieval_bundle,
    validate_phase_safe_retrieval_offline_candidate_packet,
    write_phase_safe_retrieval_offline_candidate_packet,
)
from factor_factory.epistemic_source_first_offline import (
    write_source_first_offline_candidate_packet,
)


A0 = "A0_MECHANISM_PRIOR"
A1 = "A1_IMPLEMENTATION_FEASIBILITY"
B1 = "B1_PREDICTION_CHALLENGE"
B2_POST = "B2_POSTRESULT_PLAN_SUPPORT"
B2_PRE = "B2_PREMETRIC_FUTURE_QUESTION_ONLY"

PHASES = (A0, A1, B1, B2_POST, B2_PRE)
LANES = (
    "structural_isomorph",
    "cross_math_analogy",
    "near_miss_failure",
    "direct_counterexample",
    "historical_episode_context",
)

SOURCE_FIRST_BINDING = "1" * 64


def _semantic_payload(phase: str, *, marker: str = "shared") -> dict:
    """Construct only fields admitted by the implementation's phase projection."""

    return {
        field: [f"{marker} {field.replace('_', ' ')} mechanism semantics"]
        for field in PHASE_CORPUS_FIELDS[phase]
    }


def _phase_input(phase: str, *, marker: str = "query") -> dict:
    corpus_payload = _semantic_payload(phase, marker=marker)
    return {
        field: corpus_payload[field]
        for field in PHASE_CORPUS_FIELDS[phase]
        if field not in {
            "applicability_boundary_semantics",
            "information_preserved_semantics",
            "information_lost_semantics",
            "advisory_semantics",
            "historical_episode_annotation_semantics",
        }
    }


def _object(
    fixture_id: str,
    *,
    phase: str = A0,
    lane: str = "structural_isomorph",
    marker: str = "shared",
    quarantined: bool = False,
) -> dict:
    # ``fixture_id`` is deliberately encoded only as synthetic semantic content;
    # corpus rows themselves stay inside the closed four-field input contract.
    row = {
        "corpus_class": (
            "QUARANTINED_REJECTED_CANDIDATE"
            if quarantined
            else "SYNTHETIC_ADMISSIBLE_CANDIDATE"
        ),
        "phase_branch": phase,
        "lane": lane,
        "semantic_payload": _semantic_payload(
            phase, marker=f"{fixture_id} {marker}"
        ),
    }
    if quarantined:
        row["quarantine_reasons"] = ["SYNTHETIC_POLICY_QUARANTINE"]
    return row


def _request(
    phase: str,
    *,
    lanes: list[str] | None = None,
    top_k: int = 3,
) -> dict:
    requested = lanes or ["structural_isomorph", "direct_counterexample"]
    return compile_phase_request_candidate(
        phase_branch=phase,
        phase_input=_phase_input(phase),
        phase_policy={
            "policy_version": "phase-safe-offline-candidate-v1",
            "phase_branch": phase,
            "requested_lane_subset": requested,
            "top_k_per_lane": top_k,
        },
        source_first_binding_content_sha256=(
            SOURCE_FIRST_BINDING if phase == A0 else None
        ),
    )


def _run(objects: list[dict], request: dict):
    corpus = compile_offline_corpus(objects)
    program = compile_retrieval_program(request, corpus)
    score, selection, rejection = execute_phase_projection_candidate(program)
    validate_phase_safe_retrieval_bundle(
        request_candidate=request,
        retrieval_program=program,
        score_ledger=score,
        selection_ledger=selection,
        rejection_ledger=rejection,
    )
    return corpus, program, score, selection, rejection


def _rows(payload: dict, stem: str) -> list[dict]:
    for key in (f"ordered_{stem}_rows", f"{stem}_rows", stem):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    raise AssertionError(f"missing {stem} rows in {sorted(payload)}")


def _corpus_object_id(corpus: dict, fixture_id: str) -> str:
    matches = [
        row["object_id"]
        for row in corpus["objects"]
        if fixture_id
        in json.dumps(row["semantic_payload"], ensure_ascii=False, sort_keys=True)
    ]
    assert len(matches) == 1
    return str(matches[0])


def _contains_object_ref(rows: list[dict], object_id: str) -> bool:
    return object_id in json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _branch(selection: dict) -> str:
    return str(
        selection.get("result_branch")
        or selection.get("selection_branch")
        or selection.get("disposition")
    )


def test_phase_and_lane_universes_are_closed() -> None:
    assert tuple(PHASE_CORPUS_FIELDS) == PHASES
    assert len(set(PHASE_CORPUS_FIELDS)) == 5
    assert len(set(LANES)) == 5


def test_a0_happy_path_returns_only_requested_admissible_lanes() -> None:
    objects = [
        _object("a0-structural", marker="shared"),
        _object("a0-counter", lane="direct_counterexample", marker="shared"),
        _object("a0-unrequested", lane="cross_math_analogy", marker="shared"),
    ]
    corpus, _, _, selection, rejection = _run(objects, _request(A0))
    returned = _rows(selection, "returned")
    structural = _corpus_object_id(corpus, "a0-structural")
    counter = _corpus_object_id(corpus, "a0-counter")
    unrequested = _corpus_object_id(corpus, "a0-unrequested")
    assert _contains_object_ref(returned, structural)
    assert _contains_object_ref(returned, counter)
    assert not _contains_object_ref(returned, unrequested)
    assert _contains_object_ref(_rows(rejection, "rejection"), unrequested)
    assert "RETURNED" in _branch(selection)


def test_a0_true_zero_hit_is_distinct_from_all_quarantined() -> None:
    _, _, _, empty_selection, empty_rejection = _run(
        [_object("out-of-phase", phase=B2_PRE)], _request(A0)
    )
    assert _rows(empty_selection, "returned") == []
    assert _rows(empty_rejection, "rejection") == []
    assert "ZERO_HIT" in _branch(empty_selection)

    corpus, _, _, rejected_selection, rejected_ledger = _run(
        [_object("quarantined", quarantined=True)], _request(A0)
    )
    assert _rows(rejected_selection, "returned") == []
    assert _contains_object_ref(
        _rows(rejected_ledger, "rejection"),
        _corpus_object_id(corpus, "quarantined"),
    )
    assert "NO_ADMISSIBLE" in _branch(rejected_selection)
    assert "ZERO_HIT" not in _branch(rejected_selection)


def test_quarantined_candidate_cannot_win_even_with_best_semantic_match() -> None:
    objects = [
        _object("quarantine-perfect", marker="shared", quarantined=True),
        _object("admissible-weaker", marker="other"),
    ]
    corpus, _, score, selection, rejection = _run(objects, _request(A0, top_k=1))
    admissible = _corpus_object_id(corpus, "admissible-weaker")
    quarantine = _corpus_object_id(corpus, "quarantine-perfect")
    assert _contains_object_ref(_rows(selection, "returned"), admissible)
    assert _contains_object_ref(_rows(rejection, "rejection"), quarantine)
    assert not _contains_object_ref(_rows(score, "score"), quarantine)


def test_returned_and_rejected_are_disjoint_and_exhaust_considered_objects() -> None:
    objects = [
        _object("returned"),
        _object("unrequested", lane="cross_math_analogy"),
        _object("quarantined", quarantined=True),
    ]
    corpus, _, _, selection, rejection = _run(objects, _request(A0))
    returned = _rows(selection, "returned")
    rejected = _rows(rejection, "rejection")
    for fixture_id in ("returned", "unrequested", "quarantined"):
        object_id = _corpus_object_id(corpus, fixture_id)
        assert _contains_object_ref(returned, object_id) != _contains_object_ref(
            rejected, object_id
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("historical_return", 0.42),
        ("sharpe", 3.0),
        ("oos_performance", "positive"),
        ("source_uri", "s3://private-bucket/object"),
        ("index_health", "PASS"),
    ],
)
def test_performance_uri_and_index_fields_are_rejected(field: str, value) -> None:
    row = _object("poisoned")
    row["semantic_payload"][field] = value
    with pytest.raises((TypeError, ValueError)):
        compile_offline_corpus([row])


def test_a0_is_invariant_to_presence_of_b2_only_objects() -> None:
    base = [_object("a0-base", marker="shared")]
    baseline = _run(base, _request(A0))
    augmented = _run(
        [
            *base,
            _object(
                "b2-only",
                phase=B2_PRE,
                lane="historical_episode_context",
                marker="shared",
            ),
        ],
        _request(A0),
    )
    assert _rows(baseline[3], "returned") == _rows(augmented[3], "returned")
    b2_only = _corpus_object_id(augmented[0], "b2-only")
    assert not _contains_object_ref(_rows(augmented[2], "score"), b2_only)
    assert not _contains_object_ref(_rows(augmented[3], "returned"), b2_only)
    assert not _contains_object_ref(_rows(augmented[4], "rejection"), b2_only)


@pytest.mark.parametrize(
    ("declared_phase", "payload_phase"),
    [(A0, A1), (A0, B2_PRE), (A1, B1), (B2_POST, B2_PRE)],
)
def test_cross_phase_payload_fields_are_structurally_rejected(
    declared_phase: str, payload_phase: str
) -> None:
    row = _object("cross-phase", phase=declared_phase)
    row["semantic_payload"] = _semantic_payload(payload_phase)
    with pytest.raises((TypeError, ValueError)):
        compile_offline_corpus([row])


def test_ties_are_deterministic_independent_of_input_order() -> None:
    left = _object("tie-left", marker="same")
    right = _object("tie-right", marker="same")
    first = _run([left, right], _request(A0, top_k=1))[2:]
    second = _run([right, left], _request(A0, top_k=1))[2:]
    assert first == second


def test_tampered_ledgers_fail_closed_even_after_local_json_roundtrip() -> None:
    corpus, program, score, selection, rejection = _run(
        [_object("selected"), _object("rejected", lane="cross_math_analogy")],
        _request(A0),
    )
    tampered = json.loads(json.dumps(selection))
    returned = _rows(tampered, "returned")
    returned[0]["corpus_object_content_sha256"] = "f" * 64
    with pytest.raises((TypeError, ValueError)):
        validate_phase_safe_retrieval_bundle(
            request_candidate=_request(A0),
            retrieval_program=program,
            score_ledger=score,
            selection_ledger=tampered,
            rejection_ledger=rejection,
        )


def test_all_five_phase_branches_compile_without_cross_phase_defaults() -> None:
    for phase in PHASES:
        lane = "structural_isomorph"
        request = _request(
            phase, lanes=["structural_isomorph", "direct_counterexample"]
        )
        _, program, _, selection, _ = _run(
            [_object(f"fixture-{phase}", phase=phase, lane=lane)], request
        )
        assert program["phase_branch"] == phase
        assert "RETURNED" in _branch(selection)


def test_hidden_phase_mutation_changes_private_world_but_not_a0_artifacts() -> None:
    a0_object = _object("a0-stable", marker="shared")
    hidden = _object(
        "hidden-b2",
        phase=B2_PRE,
        lane="historical_episode_context",
        marker="shared",
    )
    request = _request(A0)
    base = _run([a0_object], request)
    augmented = _run([hidden, a0_object], request)
    assert base[0]["content_sha256"] != augmented[0]["content_sha256"]
    assert base[0]["corpus_manifest_commitment_sha256"] != augmented[0][
        "corpus_manifest_commitment_sha256"
    ]
    assert base[1:] == augmented[1:]


def test_same_math_operator_without_same_payer_is_structural_hard_negative() -> None:
    phase_input = _phase_input(A0)
    phase_input["economic_game_semantics"] = [
        "forced holders pay remaining liquidity providers"
    ]
    phase_input["latent_mechanism_semantics"] = [
        "binding financing constraints reduce waiting capacity"
    ]
    phase_input["mathematical_family_semantics"] = ["wavelet transform"]
    phase_input["falsifier_semantics"] = ["constraint removal breaks the response"]
    request = compile_phase_request_candidate(
        phase_branch=A0,
        phase_input=phase_input,
        phase_policy={
            "policy_version": "phase-safe-offline-candidate-v1",
            "phase_branch": A0,
            "requested_lane_subset": [
                "structural_isomorph",
                "direct_counterexample",
            ],
            "top_k_per_lane": 2,
        },
        source_first_binding_content_sha256=SOURCE_FIRST_BINDING,
    )
    candidate = _object("same-operator-different-payer")
    candidate["semantic_payload"]["economic_game_semantics"] = [
        "unconstrained traders respond to public information"
    ]
    candidate["semantic_payload"]["latent_mechanism_semantics"] = [
        "fundamental news changes common beliefs"
    ]
    candidate["semantic_payload"]["mathematical_family_semantics"] = [
        "wavelet transform"
    ]
    _, _, _, selection, rejection = _run([candidate], request)
    assert _rows(selection, "returned") == []
    assert selection["result_branch"] == "OFFLINE_NO_ADMISSIBLE_CANDIDATE_CLOSURE"
    assert rejection["overall_disposition"] == selection["result_branch"]
    assert _rows(rejection, "rejection")[0]["reason_code"] == (
        "LANE_SEMANTIC_GATE_FAILED"
    )


@pytest.mark.parametrize(
    "smuggled_text",
    ["IC equals three", "historical return is positive", "换手率很低", "信息系数显著"],
)
def test_forbidden_rank_features_cannot_hide_in_semantic_text(smuggled_text: str) -> None:
    row = _object("semantic-smuggle")
    row["semantic_payload"]["advisory_semantics"] = [smuggled_text]
    with pytest.raises((TypeError, ValueError)):
        compile_offline_corpus([row])


def test_phase_execution_signature_and_call_graph_cannot_touch_full_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = compile_offline_corpus(
        [
            _object("phase-only"),
            _object(
                "hidden-world",
                phase=B2_PRE,
                lane="historical_episode_context",
            ),
        ]
    )
    program = compile_retrieval_program(_request(A0), corpus)
    assert list(inspect.signature(execute_phase_projection_candidate).parameters) == [
        "retrieval_program"
    ]

    def forbidden_full_world_access(*_args, **_kwargs):
        raise AssertionError("phase execution touched full world")

    monkeypatch.setattr(phase_module, "_validate_corpus", forbidden_full_world_access)
    monkeypatch.setattr(phase_module, "_phase_projection", forbidden_full_world_access)
    score, selection, rejection = execute_phase_projection_candidate(program)
    assert score["phase_only_execution_access_trace"] == {
        "accepted_input_kind": "CLOSED_PHASE_PROJECTION_PROGRAM_ONLY",
        "full_world_argument_accepted": False,
        "filesystem_open_stat_or_directory_discovery_count": 0,
        "index_count_health_or_availability_probe_count": 0,
        "network_or_host_api_call_count": 0,
        "timing_bucket": "PURE_CPU_DETERMINISTIC_NO_EXTERNAL_IO",
    }
    validate_phase_safe_retrieval_bundle(
        request_candidate=_request(A0),
        retrieval_program=program,
        score_ledger=score,
        selection_ledger=selection,
        rejection_ledger=rejection,
    )


@pytest.mark.parametrize(
    "instruction",
    [
        "revise current diagnosis using this analogy",
        "change current qualification using this history",
        "回填当前诊断并改写当前结论",
    ],
)
def test_b2_future_question_text_cannot_smuggle_current_writeback(
    instruction: str,
) -> None:
    row = _object(
        "b2-writeback-smuggle",
        phase=B2_PRE,
        lane="historical_episode_context",
    )
    row["semantic_payload"]["advisory_semantics"] = [instruction]
    with pytest.raises((TypeError, ValueError)):
        compile_offline_corpus([row])


def test_b2_premetric_selection_is_structurally_future_question_only() -> None:
    corpus, program, score, selection, rejection = _run(
        [
            _object(
                "b2-future",
                phase=B2_PRE,
                lane="historical_episode_context",
            ),
            _object(
                "b2-counter",
                phase=B2_PRE,
                lane="direct_counterexample",
            ),
        ],
        _request(
            B2_PRE,
            lanes=["direct_counterexample", "historical_episode_context"],
        ),
    )
    assert program["phase_use_policy"] == {
        "use_scope": "FUTURE_QUESTION_NAMESPACE_ONLY",
        "future_question_namespace_only": True,
        "current_diagnosis_qualification_revision_writeback_allowed": False,
        "current_parent_council_consumption_allowed": False,
    }
    assert selection["phase_use_policy"] == program["phase_use_policy"]
    assert selection["returned_rows"]
    assert all(row["future_question_namespace_only"] for row in selection["returned_rows"])
    assert not any(
        row["current_diagnosis_qualification_revision_writeback_allowed"]
        for row in selection["returned_rows"]
    )
    tampered = json.loads(json.dumps(selection))
    tampered["returned_rows"][0][
        "current_diagnosis_qualification_revision_writeback_allowed"
    ] = True
    with pytest.raises((TypeError, ValueError)):
        validate_phase_safe_retrieval_bundle(
            request_candidate=program["request_candidate"],
            retrieval_program=program,
            score_ledger=score,
            selection_ledger=tampered,
            rejection_ledger=rejection,
        )


def _write_stage1_packet(tmp_path: Path) -> tuple[Path, Path]:
    source_path = tmp_path / "source.txt"
    source_path.write_text(
        "约束持有人在承接深度下降时被迫支付价格冲击成本。",
        encoding="utf-8",
    )
    output = tmp_path / "stage1"
    write_source_first_offline_candidate_packet(
        output,
        source_path=source_path,
        source_lineage={
            "source_type": "USER_ORAL_OR_TEXT_HYPOTHESIS",
            "source_event_ref": "synthetic-source-event",
            "source_legally_available_at": "2026-08-29T00:00:00Z",
            "language": "zh-CN",
            "source_integrity_status": "VERIFIED",
            "understanding_completeness": "COMPLETE_ENOUGH_TO_FORMALIZE",
            "source_reader_context_status": "SOURCE_ONLY_CANDIDATE",
            "selection_lineage_claim": "EX_ANTE_UNSELECTED_CLAIMED",
            "proposer_outcome_exposure_claim": "NONE_CLAIMED",
            "source_outcome_status": "SOURCE_OUTCOME_FREE",
            "missing_source_components": [],
            "novel_concepts_not_yet_mapped": [],
            "internal_tensions": [],
        },
        author_claims=[
            {
                "statement_id": "source-claim",
                "classification": "SOURCE_NATIVE_EXPLICIT",
                "text": "约束持有人会支付价格冲击成本。",
                "source_locators": ["sentence-one"],
                "depends_on_statement_ids": [],
            }
        ],
        analyst_notes=[
            {
                "statement_id": "analyst-inference",
                "classification": "AGENT_INFERENCE",
                "text": "剩余承接者是价格冲击成本的接收者。",
                "source_locators": [],
                "depends_on_statement_ids": ["source-claim"],
            }
        ],
        selected_semantic_body={
            "disposition": "FORMALIZED",
            "selected_statement_ids": ["source-claim", "analyst-inference"],
            "economic_mechanism_claim": "约束持有人向剩余承接者支付价格冲击成本。",
            "payer_or_constraint": "等待能力受约束的持有人。",
            "estimand": "局部路径响应。",
            "information_set": "仅使用决策时点之前的观测。",
            "horizon": "固定短周期。",
            "mathematical_object": "局部尺度能量。",
            "broken_invariant_or_boundary": "承接深度下降时局部能量集中。",
            "observation_mapping": "将价格增量投影到固定尺度。",
            "failure_signature": "约束变化不改变局部响应。",
            "falsifiers": ["高承接深度对照产生相同响应。"],
            "material_rivals": ["一般波动放大。"],
            "regime_hypotheses": [],
            "new_assumptions": [],
            "clarification_questions": [],
        },
        pre_a0_predictions=[
            {
                "prediction_id": "prediction-one",
                "prediction": "约束增强时局部响应增强。",
                "horizon": "固定短周期。",
                "expected_direction": "NEGATIVE",
                "falsified_when": "约束强弱不改变响应。",
            }
        ],
        phase_policy_candidate={
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
    )
    return output / "packet_manifest.json", source_path


def test_packet_roundtrip_is_exact8_and_stays_standalone(tmp_path: Path) -> None:
    stage1_manifest, source_path = _write_stage1_packet(tmp_path)
    output = tmp_path / "stage2"
    manifest = write_phase_safe_retrieval_offline_candidate_packet(
        output,
        source_first_manifest_path=stage1_manifest,
        source_path=source_path,
        corpus_objects=[
            _object("packet-structural"),
            _object("packet-counter", lane="direct_counterexample"),
            _object(
                "packet-hidden",
                phase=B2_PRE,
                lane="historical_episode_context",
            ),
        ],
    )
    assert manifest["factor_forge_successor"] is False
    assert manifest["direct_predecessor_manifest_raw_sha256"] is None
    assert manifest["prototype_input_dependency_count"] == 1
    assert manifest["permissions_opened_count"] == 0
    assert len(list(output.iterdir())) == 8
    assert validate_phase_safe_retrieval_offline_candidate_packet(
        output / "packet_manifest.json",
        source_first_manifest_path=stage1_manifest,
        source_path=source_path,
    ) == manifest
    (output / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises((TypeError, ValueError)):
        validate_phase_safe_retrieval_offline_candidate_packet(
            output / "packet_manifest.json",
            source_first_manifest_path=stage1_manifest,
            source_path=source_path,
        )
