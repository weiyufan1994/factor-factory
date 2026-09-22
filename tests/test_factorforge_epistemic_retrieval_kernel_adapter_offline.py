from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

import factor_factory.epistemic_retrieval_kernel_adapter_offline as adapter
from factor_factory.epistemic_phase_safe_retrieval_offline import (
    FOUR_LANES,
    PHASE_CORPUS_FIELDS,
    PHASE_QUERY_FIELDS,
)
from factor_factory.epistemic_retrieval_kernel_adapter_offline import (
    A0,
    A1,
    EpistemicRetrievalKernelAdapterError,
    build_cross_math_analogy_demo_inputs,
    retrieve_real_knowledge_advisory,
    run_epistemic_retrieval_kernel_adapter_offline,
    validate_epistemic_retrieval_agent_projection,
    validate_epistemic_retrieval_kernel_adapter_result,
)
from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    compile_source_first_kernel_session_candidate,
)


SECRET_A = b"retrieval-session-secret-a-32-bytes-minimum"
SECRET_B = b"retrieval-session-secret-b-32-bytes-minimum"


def _all_items(projection: dict) -> list[dict]:
    return [item for lane in projection["lanes"] for item in lane["items"]]


def _handles(projection: dict) -> list[str]:
    return [item["handle"] for item in _all_items(projection)]


def _run_demo(secret: bytes = SECRET_A) -> dict:
    return _run_demo_result(secret)["agent_visible_projection"]


def _run_demo_result(secret: bytes = SECRET_A) -> dict:
    inputs = build_cross_math_analogy_demo_inputs()
    return run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=inputs["source_first_candidate"],
        source_inputs=inputs["source_inputs"],
        corpus_objects=inputs["corpus_objects"],
        session_scope_secret=secret,
    )


def _synthetic_call(
    *,
    corpus_objects: list[dict],
    phase_request: dict | None = None,
    secret: bytes = SECRET_A,
) -> dict:
    inputs = build_cross_math_analogy_demo_inputs()
    return run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=inputs["source_first_candidate"],
        source_inputs=inputs["source_inputs"],
        corpus_objects=corpus_objects,
        session_scope_secret=secret,
        phase_request=phase_request,
    )


def _a1_payload() -> dict[str, list[str]]:
    payload = {field: [] for field in PHASE_CORPUS_FIELDS[A1]}
    payload.update(
        {
            "economic_game_semantics": [
                "liquidity pressure creates a delayed price response"
            ],
            "latent_mechanism_semantics": [
                "a hidden pressure state decays through time"
            ],
            "mathematical_family_semantics": [
                "Kalman latent state filtering with variational regularization"
            ],
            "falsifier_semantics": [
                "the state estimate should fail when observation noise dominates"
            ],
            "implementation_feasibility_semantics": [
                "the Kalman update can be vectorized with bounded state dimension"
            ],
            "operator_requirement_semantics": [
                "a causal state update and positive covariance guard are required"
            ],
            "observation_and_data_semantics": [
                "daily bar observations must be point in time aligned"
            ],
            "numerical_constraint_semantics": [
                "covariance updates require finite positive diagonal terms"
            ],
            "testability_semantics": [
                "scramble observation order and verify that persistence disappears"
            ],
            "applicability_boundary_semantics": [
                "use only when a low dimensional latent state is plausible"
            ],
            "information_preserved_semantics": [
                "causal ordering and estimated state persistence are preserved"
            ],
            "information_lost_semantics": [
                "rapid nonlinear jumps are lost under the linear state approximation"
            ],
            "advisory_semantics": [
                "historical episode context suggests checking liquidity fragmentation"
            ],
        }
    )
    return payload


def _a1_object() -> dict:
    return {
        "corpus_class": "SYNTHETIC_ADMISSIBLE_CANDIDATE",
        "phase_branch": A1,
        "lane": "near_miss_failure",
        "semantic_payload": _a1_payload(),
    }


def _a1_request(*, freeze: dict | None = None) -> dict:
    payload = _a1_payload()
    return {
        "phase_branch": A1,
        "phase_input": {
            field: payload[field] for field in PHASE_QUERY_FIELDS[A1]
        },
        "phase_policy": {
            "policy_version": "phase-safe-offline-candidate-v1",
            "phase_branch": A1,
            "requested_lane_subset": list(FOUR_LANES),
            "top_k_per_lane": 2,
        },
        "hypothesis_freeze": (
            {
                "freeze_status": "FROZEN",
                "hypothesis_semantics": [
                    "liquidity pressure is represented by a bounded latent state"
                ],
            }
            if freeze is None
            else freeze
        ),
    }


def test_a0_demo_is_real_native_execution_and_shows_cross_math_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = adapter.validate_phase_safe_retrieval_bundle

    def checked(**kwargs):
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(adapter, "validate_phase_safe_retrieval_bundle", checked)
    projection = _run_demo()
    assert calls == 1
    assert projection["result"] == "HIT"
    assert [lane["lane"] for lane in projection["lanes"]] == list(FOUR_LANES)
    assert all(lane["items"] for lane in projection["lanes"])

    cross_math = next(
        lane for lane in projection["lanes"] if lane["lane"] == "cross_math_analogy"
    )
    visible_math = " ".join(cross_math["items"][0]["mathematical_analogy"]).casefold()
    for family in ("wavelet", "kalman", "convolution", "variational"):
        assert family in visible_math


def test_a0_projection_has_no_private_identity_hash_backend_or_phase_fields() -> None:
    projection = _run_demo()
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    lowered = serialized.casefold()
    for forbidden in (
        "fixture-local-",
        "object_id",
        "content_sha",
        "payload_sha",
        "source_path",
        "index_health",
        "index_available",
        "implementation_feasibility",
        "evidence_requirements",
        "failure_modes",
        "episode_context",
    ):
        assert forbidden not in lowered
    assert re.search(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", lowered) is None
    assert all(re.fullmatch(r"ctx_[A-Za-z0-9_-]{43}", value) for value in _handles(projection))
    validate_epistemic_retrieval_agent_projection(projection)


def test_result_binds_source_first_query_counts_and_sanitized_object_digests() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    result = _run_demo_result()
    binding = result["private_replay_binding"]
    projection = result["agent_visible_projection"]

    assert binding["source_first_content_sha256"] == inputs[
        "source_first_candidate"
    ]["content_sha256"]
    assert binding["source_first_input_binding_content_sha256"] == inputs[
        "source_first_candidate"
    ]["explicit_input_binding"]["content_sha256"]
    assert binding["canonical_query"]["query_mode"] == (
        "SOURCE_FIRST_REPLAY_DERIVED_A0_TYPED_QUERY"
    )
    assert binding["canonical_query"]["query_value"] == adapter._plain_source_a0_request(
        inputs["source_first_candidate"]
    )["phase_input"]
    assert binding["filtering_counts"] == {
        "input_object_count": 4,
        "phase_projected_object_count": 4,
        "phase_admissible_object_count": 4,
        "phase_quarantined_object_count": 0,
        "scored_object_count": 4,
        "rejected_object_count": 0,
        "selected_unique_object_count": 4,
        "selected_lane_item_count": 4,
    }
    assert len(binding["selected_sanitized_objects"]) == len(_all_items(projection))
    for bound, item in zip(binding["selected_sanitized_objects"], _all_items(projection)):
        assert bound["handle"] == item["handle"]
        assert re.fullmatch(r"[0-9a-f]{64}", bound["sanitized_object_content_sha256"])
        assert bound["sanitized_object_content_sha256"] != binding[
            "canonical_query"
        ]["content_sha256"]
    validate_epistemic_retrieval_kernel_adapter_result(
        result,
        source_first_candidate=inputs["source_first_candidate"],
        source_inputs=inputs["source_inputs"],
        corpus_objects=inputs["corpus_objects"],
        session_scope_secret=SECRET_A,
    )


def test_source_first_bare_digest_substitution_and_raw_input_drift_fail_closed() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="object_required_not_bare_digest",
    ):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate="a" * 64,  # type: ignore[arg-type]
            source_inputs=inputs["source_inputs"],
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret=SECRET_A,
        )

    drifted_inputs = copy.deepcopy(inputs["source_inputs"])
    drifted_inputs["source_bytes"] += b" drift"
    with pytest.raises(ValueError, match="replay_equality"):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=inputs["source_first_candidate"],
            source_inputs=drifted_inputs,
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret=SECRET_A,
        )


def test_source_first_and_retrieval_frozen_replay_is_deterministic() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    first = run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=copy.deepcopy(inputs["source_first_candidate"]),
        source_inputs=copy.deepcopy(inputs["source_inputs"]),
        corpus_objects=copy.deepcopy(inputs["corpus_objects"]),
        session_scope_secret=SECRET_A,
    )
    replay = run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=copy.deepcopy(inputs["source_first_candidate"]),
        source_inputs=copy.deepcopy(inputs["source_inputs"]),
        corpus_objects=copy.deepcopy(inputs["corpus_objects"]),
        session_scope_secret=SECRET_A,
    )

    assert replay == first


def _rehash_result(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    core = {key: value for key, value in result.items() if key != "content_sha256"}
    result["content_sha256"] = adapter.framed_sha256(
        adapter.RESULT_CONTENT_DOMAIN,
        core,
    )
    return result


def test_full_replay_rejects_coordinated_selected_digest_and_handle_rewrite() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    original = _run_demo_result()
    tampered = copy.deepcopy(original)
    fake_handle = "ctx_" + "A" * 43
    tampered["agent_visible_projection"]["lanes"][0]["items"][0][
        "handle"
    ] = fake_handle
    tampered["private_replay_binding"]["selected_sanitized_objects"][0][
        "handle"
    ] = fake_handle
    tampered["private_replay_binding"]["selected_sanitized_objects"][0][
        "sanitized_object_content_sha256"
    ] = "c" * 64
    tampered["private_replay_binding"][
        "agent_visible_projection_content_sha256"
    ] = adapter.framed_sha256(
        "FF_EPISTEMIC_RETRIEVAL_AGENT_PROJECTION_V1",
        tampered["agent_visible_projection"],
    )
    tampered = _rehash_result(tampered)

    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="full_replay_equality",
    ):
        validate_epistemic_retrieval_kernel_adapter_result(
            tampered,
            source_first_candidate=inputs["source_first_candidate"],
            source_inputs=inputs["source_inputs"],
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret=SECRET_A,
        )


def test_opaque_handle_uses_sanitized_object_digest_not_query_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    original = adapter._opaque_handle

    def checked(**kwargs):
        calls.append(
            (
                kwargs["request_content_sha256"],
                kwargs["object_content_sha256"],
            )
        )
        return original(**kwargs)

    monkeypatch.setattr(adapter, "_opaque_handle", checked)
    _run_demo_result()

    assert calls
    assert all(query_digest != object_digest for query_digest, object_digest in calls)


def test_handles_are_deterministic_within_session_and_unlinkable_across_sessions() -> None:
    first = _run_demo(SECRET_A)
    replay = _run_demo(SECRET_A)
    other_session = _run_demo(SECRET_B)
    assert first == replay
    assert set(_handles(first)).isdisjoint(_handles(other_session))
    assert {
        item["precedent_group_handle"] for item in _all_items(first)
    }.isdisjoint(
        {item["precedent_group_handle"] for item in _all_items(other_session)}
    )
    assert [
        {
            key: value
            for key, value in item.items()
            if key not in {"handle", "precedent_group_handle"}
        }
        for item in _all_items(first)
    ] == [
        {
            key: value
            for key, value in item.items()
            if key not in {"handle", "precedent_group_handle"}
        }
        for item in _all_items(other_session)
    ]


def test_a0_is_invariant_to_hidden_a1_corpus_presence() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    baseline = run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=inputs["source_first_candidate"],
        source_inputs=inputs["source_inputs"],
        corpus_objects=inputs["corpus_objects"],
        session_scope_secret=SECRET_A,
    )["agent_visible_projection"]
    augmented = run_epistemic_retrieval_kernel_adapter_offline(
        source_first_candidate=inputs["source_first_candidate"],
        source_inputs=inputs["source_inputs"],
        corpus_objects=[*inputs["corpus_objects"], _a1_object()],
        session_scope_secret=SECRET_A,
    )["agent_visible_projection"]
    assert augmented == baseline


def test_a0_requires_exact_four_canonical_lanes() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    source_inputs = copy.deepcopy(inputs["source_inputs"])
    source_inputs["phase_policy_candidate"]["requested_lane_subset"] = [
        "structural_isomorph",
        "direct_counterexample",
    ]
    source_first = compile_source_first_kernel_session_candidate(**source_inputs)
    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="exact4_canonical_lanes_required",
    ):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=source_first,
            source_inputs=source_inputs,
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret=SECRET_A,
        )


def test_a1_requires_hypothesis_freeze_then_returns_advisory_facets() -> None:
    bad_request = _a1_request()
    bad_request["hypothesis_freeze"] = None
    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="hypothesis_freeze",
    ):
        _synthetic_call(
            corpus_objects=[_a1_object()],
            phase_request=bad_request,
        )

    result = _synthetic_call(
        corpus_objects=[_a1_object()],
        phase_request=_a1_request(),
    )
    projection = result["agent_visible_projection"]
    item = next(
        lane["items"][0]
        for lane in projection["lanes"]
        if lane["lane"] == "near_miss_failure" and lane["items"]
    )
    assert any("vectorized" in text for text in item["implementation_feasibility"])
    assert any("observation noise" in text for text in item["failure_modes"])
    assert any("historical episode" in text for text in item["episode_context"])
    assert item["advisory_only"] is True
    demo = build_cross_math_analogy_demo_inputs()
    validate_epistemic_retrieval_kernel_adapter_result(
        result,
        source_first_candidate=demo["source_first_candidate"],
        source_inputs=demo["source_inputs"],
        corpus_objects=[_a1_object()],
        phase_request=_a1_request(),
        session_scope_secret=SECRET_A,
    )


def test_a1_request_and_native_phase_input_are_closed() -> None:
    extra_root = _a1_request()
    extra_root["ambient_index"] = "forbidden"
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="closed_fields"):
        _synthetic_call(
            corpus_objects=[_a1_object()],
            phase_request=extra_root,
        )

    cross_phase = _a1_request()
    cross_phase["phase_input"]["future_metric_semantics"] = ["forbidden"]
    with pytest.raises(ValueError):
        _synthetic_call(
            corpus_objects=[_a1_object()],
            phase_request=cross_phase,
        )


def test_a0_blocks_backend_code_data_failure_or_episode_text_after_native_run() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    poisoned = copy.deepcopy(inputs["corpus_objects"])
    poisoned[0]["semantic_payload"]["advisory_semantics"] = [
        "private data are available for this implementation"
    ]
    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="a0_backend_knowledge_forbidden",
    ):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=inputs["source_first_candidate"],
            source_inputs=inputs["source_inputs"],
            corpus_objects=poisoned,
            session_scope_secret=SECRET_A,
        )


def test_projection_validator_rejects_extra_private_fields_and_digest_text() -> None:
    projection = _run_demo()
    private_leak = copy.deepcopy(projection)
    private_leak["lanes"][0]["items"][0]["object_id"] = "fixture-local-secret"
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="closed_fields"):
        validate_epistemic_retrieval_agent_projection(private_leak)

    digest_leak = copy.deepcopy(projection)
    digest_leak["lanes"][0]["items"][0]["advisory"].append("c" * 64)
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="digest_forbidden"):
        validate_epistemic_retrieval_agent_projection(digest_leak)


def test_session_secret_is_explicit_bytes_and_not_visible() -> None:
    inputs = build_cross_math_analogy_demo_inputs()
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="bytes_required"):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=inputs["source_first_candidate"],
            source_inputs=inputs["source_inputs"],
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret="not-bytes",  # type: ignore[arg-type]
        )
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="min_32_bytes"):
        run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=inputs["source_first_candidate"],
            source_inputs=inputs["source_inputs"],
            corpus_objects=inputs["corpus_objects"],
            session_scope_secret=b"short",
        )
    assert SECRET_A.decode("ascii") not in json.dumps(_run_demo(), sort_keys=True)


def _real_source_bundle(query: str, *, top_k_per_lane: int) -> tuple[dict, dict]:
    inputs = adapter._demo_source_first_inputs(
        shared_math=query,
        top_k_per_lane=top_k_per_lane,
    )
    body = inputs["selected_semantic_body"]
    body.update(
        {
            "economic_mechanism_claim": "qzxeconomicx",
            "payer_or_constraint": "qzxpayerx",
            "estimand": "qzxestimandx",
            "mathematical_object": query,
            "broken_invariant_or_boundary": "qzxboundaryx",
            "observation_mapping": "qzxobservationx",
            "failure_signature": "qzxfailurex",
            "falsifiers": ["qzxfalsifierx"],
            "material_rivals": ["qzxrivalx"],
            "regime_hypotheses": ["qzxconditionalx"],
        }
    )
    return compile_source_first_kernel_session_candidate(**inputs), inputs


def _real_call(
    *,
    query: str,
    node_index: Path,
    edge_index: Path,
    taxonomy: Path,
    top_k_per_lane: int,
    phase_branch: str = A0,
    hypothesis_freeze: dict | None = None,
    secret: bytes = SECRET_A,
) -> dict:
    source_first, source_inputs = _real_source_bundle(
        query,
        top_k_per_lane=top_k_per_lane,
    )
    return retrieve_real_knowledge_advisory(
        source_first_candidate=source_first,
        source_inputs=source_inputs,
        phase_branch=phase_branch,
        top_k_per_lane=top_k_per_lane,
        node_index_path=node_index.resolve(),
        edge_index_path=edge_index.resolve(),
        taxonomy_path=taxonomy.resolve(),
        session_scope_secret=secret,
        hypothesis_freeze=hypothesis_freeze,
    )


def _write_real_graph_fixture(root: Path) -> tuple[Path, Path, Path]:
    node_file = root / "mechanism_node.json"
    node = {
        "schema_version": "factor_knowledge_node_v1",
        "id": "node::secret_factor_identity",
        "node_type": "mechanism",
        "title": "SECRET_FACTOR_TITLE",
        "summary": "Alpha999 OOS Sharpe 2.4 from a private report",
        "factor_ids": ["FACTOR_SECRET_999"],
        "report_ids": ["REPORT_SECRET_999"],
        "taxonomy": {
            "economic_mechanism": ["liquidity_pressure"],
            "math_mechanism": [
                "wavelet_transform",
                "kalman_filter",
                "convolution",
                "variational_method",
            ],
            "worldquant_style": ["rank_transform", "ts_operator"],
            "data_source": ["daily_ohlcv"],
            "failure_mode": ["state_aliasing"],
            "research_status": ["official"],
        },
        "mechanism": {
            "economic_hypothesis": (
                "transient liquidity pressure creates delayed adjustment"
            ),
            "payer": "short horizon liquidity demanders create temporary pressure",
            "receiver": "patient liquidity providers absorb the temporary pressure",
            "random_object": "multiscale latent pressure state",
            "dirac_style_forced_insight": (
                "wavelet localization and Kalman filtering preserve different state information"
            ),
            "information_preserved_removed": (
                "scale localization preserves transient timing while smoothing removes jump detail"
            ),
            "complexity_penalty_reasoning": (
                "use the simplest state representation consistent with the payer"
            ),
            "formula_latex": "SECRET_FORMULA_ALPHA999",
        },
        "evidence": {
            "key_metrics": {"oos_sharpe": 2.4, "rank_ic": 0.12},
            "index_health": "PASS",
            "artifact_path": "/private/evidence/path.json",
        },
        "relations": [
            {
                "edge_type": "contradicts",
                "target": "factor::SECRET_TARGET",
                "note": (
                    "scale scrambling leaves the effect unchanged and contradicts the transient mechanism"
                ),
            }
        ],
        "reuse_guidance": [
            "compare the representation under a historical market state before choosing an operator",
            "Alpha999 has OOS Sharpe 2.4 and official status",
        ],
        "source_paths": ["/private/report/path.md"],
    }
    node_file.write_text(json.dumps(node, ensure_ascii=False), encoding="utf-8")

    node_index = root / "nodes.jsonl"
    index_row = {
        "id": node["id"],
        "node_type": "mechanism",
        "title": node["title"],
        "summary": node["summary"],
        "text": "liquidity pressure latent state wavelet Kalman",
        "tags": ["math_mechanism:wavelet_transform", "official"],
        "research_status": ["official"],
        "source_node_path": str(node_file),
        "factor_ids": node["factor_ids"],
        "report_ids": node["report_ids"],
        "evidence": node["evidence"],
    }
    node_index.write_text(json.dumps(index_row) + "\n", encoding="utf-8")

    edge_index = root / "edges.jsonl"
    edge_index.write_text(
        json.dumps(
            {
                "edge_type": "contradicts",
                "source": node["id"],
                "target": "factor::SECRET_TARGET",
                "source_node_path": str(node_file),
                "note": "private edge note",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    taxonomy = root / "taxonomy.json"
    taxonomy.write_text(json.dumps({"aliases": {}}), encoding="utf-8")
    return node_index, edge_index, taxonomy


def _write_tied_real_graph_fixture(
    root: Path,
) -> tuple[Path, Path, Path, Path, bytes]:
    def node_payload(token: str, evidence_nonce: str) -> dict:
        return {
            "schema_version": "factor_knowledge_node_v1",
            "id": f"node::{token}",
            "node_type": "mechanism",
            "taxonomy": {"economic_mechanism": ["liquidity_pressure"]},
            "mechanism": {
                "economic_hypothesis": f"liquidity pressure {token}",
                "payer": "short horizon liquidity demanders",
                "receiver": "patient liquidity providers",
            },
            "evidence": {"excluded_nonce": evidence_nonce},
            "relations": [],
            "reuse_guidance": [],
        }

    def raw(payload: dict) -> bytes:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    node_a_path = root / "node_a.json"
    node_b_path = root / "node_b.json"
    node_b_raw = raw(node_payload("tokenbbbb", "fixed"))
    node_b_digest = hashlib.sha256(node_b_raw).hexdigest()
    low_raw: bytes | None = None
    high_raw: bytes | None = None
    for ordinal in range(1000):
        candidate_raw = raw(node_payload("tokenaaaa", f"nonce-{ordinal}"))
        candidate_digest = hashlib.sha256(candidate_raw).hexdigest()
        if candidate_digest < node_b_digest and low_raw is None:
            low_raw = candidate_raw
        if candidate_digest > node_b_digest and high_raw is None:
            high_raw = candidate_raw
        if low_raw is not None and high_raw is not None:
            break
    assert low_raw is not None and high_raw is not None
    node_a_path.write_bytes(low_raw)
    node_b_path.write_bytes(node_b_raw)

    node_index = root / "nodes.jsonl"
    node_index.write_text(
        "".join(
            json.dumps({"source_node_path": str(path)}) + "\n"
            for path in (node_a_path, node_b_path)
        ),
        encoding="utf-8",
    )
    edge_index = root / "edges.jsonl"
    edge_index.write_text("", encoding="utf-8")
    taxonomy = root / "taxonomy.json"
    taxonomy.write_text(json.dumps({"aliases": {}}), encoding="utf-8")
    return node_index, edge_index, taxonomy, node_a_path, high_raw


def test_real_graph_a0_strict_projection_strips_identity_paths_metrics_and_status(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    result = _real_call(
        query="liquidity pressure latent state wavelet",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    projection = result["agent_visible_projection"]
    assert projection["result"] == "HIT"
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True).casefold()
    for forbidden in (
        "node::",
        "secret_factor",
        "factor_secret",
        "report_secret",
        "alpha999",
        str(tmp_path).casefold(),
        "source_node_path",
        "source_paths",
        "key_metrics",
        "sharpe",
        "rank_ic",
        "2.4",
        "official",
        "research_status",
        "index_health",
        "index_available",
        "content_sha",
        "failure_modes",
        "episode_context",
    ):
        assert forbidden not in serialized
    assert "wavelet" in serialized
    assert "kalman" in serialized
    assert re.search(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", serialized) is None
    items = _all_items(projection)
    assert items
    assert all(
        set(item["information_preserved"]).isdisjoint(item["information_lost"])
        for item in items
    )
    assert {
        tuple(item["information_preserved"]) for item in items
    } == {("scale localization preserves transient timing",)}
    assert {tuple(item["information_lost"]) for item in items} == {
        ("smoothing removes jump detail",)
    }
    validate_epistemic_retrieval_agent_projection(projection)
    source_first, source_inputs = _real_source_bundle(
        "liquidity pressure latent state wavelet",
        top_k_per_lane=2,
    )
    validate_epistemic_retrieval_kernel_adapter_result(
        result,
        source_first_candidate=source_first,
        source_inputs=source_inputs,
        top_k_per_lane=2,
        node_index_path=node_index.resolve(),
        edge_index_path=edge_index.resolve(),
        taxonomy_path=taxonomy.resolve(),
        session_scope_secret=SECRET_A,
    )

    binding = result["private_replay_binding"]
    raw_binding = binding["retrieval_input"]
    assert raw_binding["node_index_raw_bytes_identity"] == {
        "byte_count": node_index.stat().st_size,
        "raw_sha256": __import__("hashlib").sha256(node_index.read_bytes()).hexdigest(),
    }
    assert raw_binding["edge_index_raw_bytes_identity"] == {
        "byte_count": edge_index.stat().st_size,
        "raw_sha256": __import__("hashlib").sha256(edge_index.read_bytes()).hexdigest(),
    }
    assert raw_binding["taxonomy_raw_bytes_identity"] == {
        "byte_count": taxonomy.stat().st_size,
        "raw_sha256": __import__("hashlib").sha256(taxonomy.read_bytes()).hexdigest(),
    }
    assert re.fullmatch(r"[0-9a-f]{64}", raw_binding["graph_raw_bytes_identity"])
    counts = binding["filtering_counts"]
    assert counts["indexed_row_count"] == 1
    assert counts["source_node_read_count"] == 1
    assert counts["strict_projection_count"] == 1
    assert counts["selected_unique_object_count"] == 1


def test_real_graph_distinguishes_zero_hit_from_no_admissible_candidate(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    zero_result = _real_call(
        query="qzxnomatchtoken",
        top_k_per_lane=1,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    assert zero_result["agent_visible_projection"]["result"] == "ZERO_HIT"
    assert zero_result["private_replay_binding"]["filtering_counts"][
        "lane_admissible_candidate_count"
    ] == 1

    index_row = json.loads(node_index.read_text(encoding="utf-8"))
    node_file = Path(index_row["source_node_path"])
    node = json.loads(node_file.read_text(encoding="utf-8"))
    node["taxonomy"] = {"research_status": ["official"]}
    node["mechanism"] = {}
    node["relations"] = []
    node["reuse_guidance"] = []
    node_file.write_text(json.dumps(node, ensure_ascii=False), encoding="utf-8")

    no_admissible_result = _real_call(
        query="qzxnomatchtoken",
        top_k_per_lane=1,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    assert no_admissible_result["agent_visible_projection"]["result"] == (
        "NO_ADMISSIBLE_CANDIDATE"
    )
    assert no_admissible_result["private_replay_binding"]["filtering_counts"][
        "lane_admissible_candidate_count"
    ] == 0
    assert no_admissible_result["private_replay_binding"]["filtering_counts"][
        "strict_projection_rejected_count"
    ] == 1


def test_real_graph_excluded_bytes_cannot_change_tie_break_or_visible_handle(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy, node_a_path, replacement_raw = (
        _write_tied_real_graph_fixture(tmp_path)
    )
    first = _real_call(
        query="liquidity pressure",
        top_k_per_lane=1,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    node_a_path.write_bytes(replacement_raw)
    second = _real_call(
        query="liquidity pressure",
        top_k_per_lane=1,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )

    assert first["agent_visible_projection"] == second["agent_visible_projection"]
    first_binding = first["private_replay_binding"]["retrieval_input"]
    second_binding = second["private_replay_binding"]["retrieval_input"]
    assert first_binding["graph_raw_bytes_identity"] != second_binding[
        "graph_raw_bytes_identity"
    ]
    assert first_binding["source_node_raw_bytes_identity"] != second_binding[
        "source_node_raw_bytes_identity"
    ]


def test_real_precedent_group_handle_is_lane_independent_and_session_scoped(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    first = _real_call(
        query="liquidity pressure latent state wavelet",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
        secret=SECRET_A,
    )
    second_session = _real_call(
        query="liquidity pressure latent state wavelet",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
        secret=SECRET_B,
    )
    first_items = _all_items(first["agent_visible_projection"])
    second_items = _all_items(second_session["agent_visible_projection"])

    assert len(first_items) == 4
    assert len({item["handle"] for item in first_items}) == 4
    assert len({item["precedent_group_handle"] for item in first_items}) == 1
    assert first_items[0]["eligible_lanes"] == list(FOUR_LANES)
    assert {
        tuple(item["lane_role_rationale"]) for item in first_items
    } == {(adapter._LANE_ROLE_RATIONALES[lane],) for lane in FOUR_LANES}
    assert {
        item["precedent_group_handle"] for item in first_items
    }.isdisjoint(
        {item["precedent_group_handle"] for item in second_items}
    )


def test_real_full_replay_rejects_coordinated_graph_hash_rewrite(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    result = _real_call(
        query="liquidity pressure latent state wavelet",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    tampered = copy.deepcopy(result)
    tampered["private_replay_binding"]["retrieval_input"][
        "graph_raw_bytes_identity"
    ] = "d" * 64
    tampered = _rehash_result(tampered)
    source_first, source_inputs = _real_source_bundle(
        "liquidity pressure latent state wavelet",
        top_k_per_lane=2,
    )

    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="full_replay_equality",
    ):
        validate_epistemic_retrieval_kernel_adapter_result(
            tampered,
            source_first_candidate=source_first,
            source_inputs=source_inputs,
            top_k_per_lane=2,
            node_index_path=node_index.resolve(),
            edge_index_path=edge_index.resolve(),
            taxonomy_path=taxonomy.resolve(),
            session_scope_secret=SECRET_A,
        )


def test_real_graph_a1_exposes_only_advisory_implementation_and_failure_taxonomy(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    result = _real_call(
        query="liquidity pressure latent state wavelet",
        phase_branch=A1,
        top_k_per_lane=1,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
        hypothesis_freeze={
            "freeze_status": "FROZEN",
            "hypothesis_semantics": ["latent liquidity pressure state"],
        },
    )
    projection = result["agent_visible_projection"]
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True).casefold()
    assert "operator families" in serialized
    assert "failure modes" in serialized
    assert "historical market state" in serialized
    assert re.search(r"\boos\b|out[- ]of[- ]sample", serialized) is None
    assert "2.4" not in serialized
    assert "hypothesis_semantics" not in serialized
    assert all(item["advisory_only"] is True for item in _all_items(projection))


def test_real_graph_named_math_bridge_without_typed_anchor_is_truthful_zero_hit(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    index_row = json.loads(node_index.read_text(encoding="utf-8"))
    node_file = Path(index_row["source_node_path"])
    node = json.loads(node_file.read_text(encoding="utf-8"))
    node["taxonomy"]["math_mechanism"] = [
        "multiscale",
        "time_frequency",
        "local_energy",
    ]
    # Prose may mention wavelets as an analogy, but it is not a typed corpus
    # claim that this node contains a dedicated wavelet method.
    assert "wavelet" in node["mechanism"]["dirac_style_forced_insight"].casefold()
    node_file.write_text(json.dumps(node, ensure_ascii=False), encoding="utf-8")

    result = _real_call(
        query="小波分析",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )
    projection = result["agent_visible_projection"]

    assert projection["result"] == "ZERO_HIT"
    assert _all_items(projection) == []


def test_real_graph_named_math_scoring_consumes_only_safe_projected_anchors(
    tmp_path: Path,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    index_row = json.loads(node_index.read_text(encoding="utf-8"))
    node_file = Path(index_row["source_node_path"])
    node = json.loads(node_file.read_text(encoding="utf-8"))
    node["taxonomy"]["math_mechanism"] = [
        "wavelet_transform",
        "out.of.sample evidence",
    ]
    node_file.write_text(json.dumps(node, ensure_ascii=False), encoding="utf-8")
    first = _real_call(
        query="小波分析",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )

    node["taxonomy"]["math_mechanism"][1] = "ＯＵＴ＿ＯＦ＿ＳＡＭＰＬＥ evidence"
    node_file.write_text(json.dumps(node, ensure_ascii=False), encoding="utf-8")
    second = _real_call(
        query="小波分析",
        top_k_per_lane=2,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=taxonomy,
    )

    assert first["agent_visible_projection"] == second["agent_visible_projection"]
    assert first["agent_visible_projection"]["result"] == "HIT"
    visible = json.dumps(first["agent_visible_projection"], ensure_ascii=False).casefold()
    assert "wavelet transform" in visible
    assert "out.of.sample" not in visible
    assert "out_of_sample" not in visible
    assert first["private_replay_binding"]["retrieval_input"][
        "graph_raw_bytes_identity"
    ] != second["private_replay_binding"]["retrieval_input"][
        "graph_raw_bytes_identity"
    ]


@pytest.mark.parametrize(
    "value",
    [
        "out_of_sample evidence",
        "out.of.sample evidence",
        "ＯＵＴ＿ＯＦ＿ＳＡＭＰＬＥ evidence",
        "oos.metrics",
        "ＯＯＳ＿metrics",
        "样本外证据",
    ],
)
def test_safe_real_text_rejects_separator_equivalent_oos_text(value: str) -> None:
    assert adapter._safe_real_text(value, phase_branch=A0) is None


def test_bound_repository_graph_returns_explicitly_covered_wavelet_reference() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = _real_call(
        query="小波分析",
        top_k_per_lane=2,
        node_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"
        ),
        edge_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_edges.jsonl"
        ),
        taxonomy=(
            project_root / "knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json"
        ),
    )
    projection = result["agent_visible_projection"]

    assert projection["result"] == "HIT"
    visible = json.dumps(projection, ensure_ascii=False)
    assert "Retrieve for 小波分析" in visible
    assert all(item["advisory_only"] is True for item in _all_items(projection))
    source = project_root / "knowledge/因子工厂/graph/nodes/METHOD_TRANSIENT_SIGNAL_MODELS_20260907.json"
    expected_source_identity = {
        "byte_count": len(source.read_bytes()),
        "raw_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    source_rows = result["private_replay_binding"]["retrieval_input"]["source_node_raw_bytes_identity"]["rows"]
    assert expected_source_identity in [
        {"byte_count": row["byte_count"], "raw_sha256": row["raw_sha256"]}
        for row in source_rows
    ]


def test_bound_repository_graph_does_not_invent_genuinely_uncovered_named_math() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = _real_call(
        query="Hankel-Radon 变换",
        top_k_per_lane=2,
        node_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"
        ),
        edge_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_edges.jsonl"
        ),
        taxonomy=(
            project_root / "knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json"
        ),
    )
    projection = result["agent_visible_projection"]

    assert projection["result"] == "ZERO_HIT"
    assert _all_items(projection) == []


def test_bound_repository_graph_natural_chinese_query_returns_relevant_advisory() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = _real_call(
        query="拥挤交易导致流动性撤退与价格压力",
        top_k_per_lane=1,
        node_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"
        ),
        edge_index=(
            project_root / "knowledge/因子工厂/graph/factor_knowledge_edges.jsonl"
        ),
        taxonomy=(
            project_root / "knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json"
        ),
    )
    projection = result["agent_visible_projection"]

    assert projection["result"] == "HIT"
    visible = json.dumps(projection, ensure_ascii=False).casefold()
    assert "liquidity" in visible or "pressure" in visible
    validate_epistemic_retrieval_agent_projection(projection)


def test_real_graph_api_has_no_ambient_path_defaults_and_rejects_relative_paths(
    tmp_path: Path,
) -> None:
    signature = inspect.signature(retrieve_real_knowledge_advisory)
    for parameter in ("node_index_path", "edge_index_path", "taxonomy_path"):
        assert signature.parameters[parameter].default is inspect.Parameter.empty

    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    source_first, source_inputs = _real_source_bundle(
        "liquidity pressure",
        top_k_per_lane=1,
    )
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="absolute_path_required"):
        retrieve_real_knowledge_advisory(
            source_first_candidate=source_first,
            source_inputs=source_inputs,
            phase_branch=A0,
            top_k_per_lane=1,
            node_index_path=Path(node_index.name),
            edge_index_path=edge_index.resolve(),
            taxonomy_path=taxonomy.resolve(),
            session_scope_secret=SECRET_A,
        )


def test_real_graph_rejects_source_outside_bound_graph_root_before_bound_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    node_index, edge_index, taxonomy = _write_real_graph_fixture(graph_root)
    index_row = json.loads(node_index.read_text(encoding="utf-8"))
    original_node = Path(index_row["source_node_path"])
    outside = tmp_path / "outside-node.json"
    outside.write_bytes(original_node.read_bytes())
    index_row["source_node_path"] = str(outside.resolve())
    node_index.write_text(json.dumps(index_row) + "\n", encoding="utf-8")

    bound_reads: list[Path] = []
    original_bound_read = adapter._read_bound_bytes

    def record_bound_read(path: Path, label: str, **kwargs: object) -> bytes:
        resolved = Path(path).resolve(strict=True)
        bound_reads.append(resolved)
        assert resolved != outside.resolve()
        return original_bound_read(path, label, **kwargs)

    monkeypatch.setattr(adapter, "_read_bound_bytes", record_bound_read)

    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="source_outside_graph_root",
    ):
        _real_call(
            query="liquidity pressure latent state wavelet",
            node_index=node_index,
            edge_index=edge_index,
            taxonomy=taxonomy,
            top_k_per_lane=1,
        )

    assert outside.resolve() not in bound_reads
    assert bound_reads == [
        node_index.resolve(),
        edge_index.resolve(),
        taxonomy.resolve(),
    ]


def test_bound_read_rejects_directory_entry_swap_during_open_descriptor_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "bound.json"
    replacement = tmp_path / "replacement.json"
    detached = tmp_path / "detached.json"
    target.write_bytes(b'{"version":1}\n')
    replacement.write_bytes(b'{"version":2}\n')
    original_read = adapter.os.read
    swapped = False

    def read_then_swap(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        chunk = original_read(descriptor, size)
        if chunk and not swapped:
            target.rename(detached)
            replacement.rename(target)
            swapped = True
        return chunk

    monkeypatch.setattr(adapter.os, "read", read_then_swap)

    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="changed_during_read|entry_replaced_during_read",
    ):
        adapter._read_bound_bytes(target.resolve(), "bound")

    assert swapped is True


def test_bound_read_rejects_direct_parent_swap_before_dirfd_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declared_parent = tmp_path / "declared" / "graph"
    declared_parent.mkdir(parents=True)
    target = declared_parent / "bound.json"
    target.write_bytes(b'{"origin":"declared"}\n')
    target_argument = target.resolve()

    external_parent = tmp_path / "external-graph"
    external_parent.mkdir()
    (external_parent / target.name).write_bytes(b'{"origin":"external"}\n')
    detached_parent = declared_parent.with_name("detached-graph")
    original_open = adapter.os.open
    original_read = adapter.os.read
    swapped = False
    reads = 0

    def swap_parent_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and kwargs.get("dir_fd") is not None
            and Path(path) == Path(declared_parent.name)
        ):
            declared_parent.rename(detached_parent)
            declared_parent.symlink_to(external_parent, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    def record_read(descriptor: int, size: int) -> bytes:
        nonlocal reads
        reads += 1
        return original_read(descriptor, size)

    monkeypatch.setattr(adapter.os, "open", swap_parent_then_open)
    monkeypatch.setattr(adapter.os, "read", record_read)

    with pytest.raises((EpistemicRetrievalKernelAdapterError, OSError)):
        adapter._read_bound_bytes(target_argument, "bound")

    assert swapped is True
    assert reads == 0


def test_canonical_real_graph_rejects_symlinked_nodes_root_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = tmp_path / "repo"
    graph_root = fake_repo / "knowledge" / "因子工厂" / "graph"
    graph_root.mkdir(parents=True)
    external_nodes = tmp_path / "external-nodes"
    external_nodes.mkdir()
    external_node = external_nodes / "mechanism-node.json"
    fixture_index, edge_index, taxonomy = _write_real_graph_fixture(graph_root)
    external_node.write_bytes((graph_root / "mechanism_node.json").read_bytes())
    (graph_root / "mechanism_node.json").unlink()
    (graph_root / "nodes").symlink_to(external_nodes, target_is_directory=True)
    index_row = json.loads(fixture_index.read_text(encoding="utf-8"))
    index_row["source_node_path"] = str(external_node.resolve())
    canonical_index = graph_root / "factor_knowledge_nodes.jsonl"
    canonical_index.write_text(json.dumps(index_row) + "\n", encoding="utf-8")
    fixture_index.unlink()
    fake_module = fake_repo / "factor_factory" / "adapter.py"
    fake_module.parent.mkdir()
    monkeypatch.setattr(adapter, "__file__", str(fake_module))

    source_reads: list[Path] = []
    original_bound_read = adapter._read_bound_bytes

    def record_bound_read(path: Path, label: str, **kwargs: object) -> bytes:
        resolved = Path(path).resolve(strict=True)
        if "source_node" in label:
            source_reads.append(resolved)
        return original_bound_read(path, label, **kwargs)

    monkeypatch.setattr(adapter, "_read_bound_bytes", record_bound_read)

    with pytest.raises(
        EpistemicRetrievalKernelAdapterError,
        match="source_node_root:canonical_direct_real_directory_required",
    ):
        _real_call(
            query="liquidity pressure latent state wavelet",
            node_index=canonical_index,
            edge_index=edge_index,
            taxonomy=taxonomy,
            top_k_per_lane=1,
        )

    assert source_reads == []


@pytest.mark.parametrize(
    "component",
    ["oos_results", "out-of-sample-results", "out_of_sample_metrics", "ＯＯＳ-cache"],
)
@pytest.mark.parametrize("role", ["node_index", "edge_index", "taxonomy", "source_node"])
def test_real_graph_rejects_normalized_oos_component_prefixes_for_every_input_role(
    tmp_path: Path,
    component: str,
    role: str,
) -> None:
    node_index, edge_index, taxonomy = _write_real_graph_fixture(tmp_path)
    forbidden_dir = tmp_path / component
    forbidden_dir.mkdir()
    if role == "node_index":
        replacement = forbidden_dir / "nodes.jsonl"
        replacement.write_bytes(node_index.read_bytes())
        node_index = replacement
    elif role == "edge_index":
        replacement = forbidden_dir / "edges.jsonl"
        replacement.write_bytes(edge_index.read_bytes())
        edge_index = replacement
    elif role == "taxonomy":
        replacement = forbidden_dir / "taxonomy.json"
        replacement.write_bytes(taxonomy.read_bytes())
        taxonomy = replacement
    else:
        index_row = json.loads(node_index.read_text(encoding="utf-8"))
        original_node = Path(index_row["source_node_path"])
        replacement = forbidden_dir / "node.json"
        replacement.write_bytes(original_node.read_bytes())
        index_row["source_node_path"] = str(replacement.resolve())
        node_index.write_text(json.dumps(index_row) + "\n", encoding="utf-8")

    source_first, source_inputs = _real_source_bundle(
        "liquidity pressure",
        top_k_per_lane=1,
    )
    with pytest.raises(EpistemicRetrievalKernelAdapterError, match="oos.*forbidden"):
        retrieve_real_knowledge_advisory(
            source_first_candidate=source_first,
            source_inputs=source_inputs,
            phase_branch=A0,
            top_k_per_lane=1,
            node_index_path=node_index.resolve(),
            edge_index_path=edge_index.resolve(),
            taxonomy_path=taxonomy.resolve(),
            session_scope_secret=SECRET_A,
        )
