from __future__ import annotations

from copy import deepcopy

from factor_factory.mechanism_math.main_agent_memo import (
    _factor_spec_knowledge_node_ids,
)


def _current_summary() -> dict:
    method_id = "node::method::conditional-observation"
    case_id = "node::case::materialized-prior"
    learning = {
        # The method/context lane is deliberately independent from cases.
        "factor_knowledge_context": {"nodes": [{"id": method_id}]},
        # Only materialized cases, not a declared ID list, enter the case lane.
        "knowledge_reference_contract": {
            "retrieved_case_ids": [case_id],
            "retrieved_cases": [{"id": case_id}],
        },
    }
    return {
        "learning_and_innovation": learning,
        "mechanism_conditioned_measurement_program": {
            "implementation": {
                "components": [
                    {
                        "component_id": "primary",
                        "knowledge_node_ids": [method_id, case_id],
                    }
                ]
            }
        },
        "canonical_spec": {"learning_and_innovation": deepcopy(learning)},
    }


def test_current_step2_summary_projects_method_and_materialized_case_lanes() -> None:
    summary = _current_summary()

    assert _factor_spec_knowledge_node_ids(summary) == {
        "node::method::conditional-observation",
        "node::case::materialized-prior",
    }


def test_current_step2_summary_rejects_component_self_cite_and_unmaterialized_case() -> None:
    forged = {
        "learning_and_innovation": {
            "knowledge_reference_contract": {"cited_node_ids": ["forged-id"]},
        },
        "mechanism_conditioned_measurement_program": {
            "implementation": {
                "components": [{"knowledge_node_ids": ["forged-id"]}],
            }
        },
    }
    assert _factor_spec_knowledge_node_ids(forged) == set()

    missing_case_record = {
        "learning_and_innovation": {
            "knowledge_reference_contract": {
                "retrieved_case_ids": ["case-without-record"],
                "retrieved_cases": [],
            }
        }
    }
    assert _factor_spec_knowledge_node_ids(missing_case_record) == set()


def test_legacy_research_contract_keeps_existing_strict_intersection() -> None:
    legacy_node = "legacy-retrieved-node"
    legacy = {
        "research_contract": {
            "factor_knowledge_context": {
                "schema_version": "factor_knowledge_context_v1",
                "node_count": 1,
                "query": {"text": "legacy", "top_k": 1},
                "nodes": [{"id": legacy_node}],
            },
            "knowledge_reference_contract": {
                "contract_version": "factorforge_knowledge_reference_contract_v1",
                "producer": "legacy_retrieval",
                "retrieval_required": True,
                "retrieval_status": "retrieved",
                "query_hash": "a" * 64,
                "indexes_available": ["knowledge/retrieval/index.jsonl"],
                "hit_count": 1,
                "retrieved_case_ids": [legacy_node],
            },
        }
    }
    assert _factor_spec_knowledge_node_ids(legacy) == {legacy_node}
