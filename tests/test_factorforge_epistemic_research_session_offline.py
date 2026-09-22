from __future__ import annotations

import copy

import pytest

from factor_factory.epistemic_research_session_offline import (
    ADAPTER_ID,
    SESSION_DOMAIN,
    STAGE_DEFINITIONS,
    EpistemicResearchSessionOfflineError,
    compile_candidate_research_session_envelope,
    validate_candidate_research_session_envelope,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


def _stages() -> list[dict]:
    return [
        {
            "ordinal": ordinal,
            "stage": stage,
            "schema_id": schema_id,
            "content_sha256": f"{ordinal + 1:x}" * 64,
        }
        for ordinal, (stage, schema_id) in enumerate(STAGE_DEFINITIONS)
    ]


def _compile(branch: str = "A0_HOST_PREISSUANCE_CANDIDATE") -> dict:
    return compile_candidate_research_session_envelope(
        explicit_input_binding_content_sha256="a" * 64,
        ordered_stage_bindings=_stages(),
        request_branch=branch,
    )


def _rehash(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    core = {key: value for key, value in result.items() if key != "content_sha256"}
    result["content_sha256"] = framed_sha256(SESSION_DOMAIN, core)
    return result


def test_session_envelope_is_deterministic_closed_and_source_first() -> None:
    session = _compile()
    assert session == _compile()
    assert session["adapter_id"] == ADAPTER_ID
    assert [row["stage"] for row in session["ordered_stage_bindings"]] == [
        stage for stage, _ in STAGE_DEFINITIONS
    ]
    assert session["source_first_invariant"] == {
        "understanding_precedes_formalization": True,
        "formalization_precedes_blind_seed": True,
        "blind_seed_precedes_knowledge_request": True,
        "source_or_user_hypothesis_is_primary_input": True,
        "taxonomy_gate_before_understanding": False,
        "adapter_knowledge_access_before_blind_seed": False,
        "adapter_implementation_data_or_results_access_before_blind_seed": False,
        "caller_claimed_pre_retrieval_semantic_origin": True,
        "caller_semantic_origin_independently_verified": False,
    }
    assert validate_candidate_research_session_envelope(session) == session


def test_session_has_no_execution_or_ambient_authority() -> None:
    boundary = _compile()["execution_boundary"]
    assert boundary["mode"] == "PURE_OFFLINE_EXPLICIT_INPUTS"
    assert boundary["output_publication_owner"] == "CALLER_CREATE_ONLY"
    for field in (
        "ambient_discovery_allowed",
        "environment_lookup_allowed",
        "network_allowed",
        "filesystem_read_allowed",
        "filesystem_write_allowed",
        "output_overwrite_allowed",
        "host_authority_present",
        "canonical_write_allowed",
        "oos_access_allowed",
        "production_activation_allowed",
    ):
        assert boundary[field] is False


@pytest.mark.parametrize(
    ("branch", "state"),
    [
        ("A0_HOST_PREISSUANCE_CANDIDATE", "AWAITING_HOST_MINT__NOT_EXECUTABLE"),
        ("NO_A0_REQUEST_LAWFUL_ABSTENTION", "TERMINAL_LAWFUL_ABSTENTION"),
        ("NO_A0_REQUEST_INELIGIBLE", "TERMINAL_A0_INELIGIBLE"),
    ],
)
def test_terminal_branch_is_closed(branch: str, state: str) -> None:
    session = _compile(branch)
    assert session["terminal"]["session_state"] == state
    validate_candidate_research_session_envelope(session)


def test_stage_reorder_duplicate_digest_and_unknown_branch_fail_closed() -> None:
    reordered = _stages()
    reordered.reverse()
    with pytest.raises(EpistemicResearchSessionOfflineError):
        compile_candidate_research_session_envelope(
            explicit_input_binding_content_sha256="a" * 64,
            ordered_stage_bindings=reordered,
            request_branch="A0_HOST_PREISSUANCE_CANDIDATE",
        )
    duplicate = _stages()
    duplicate[1]["content_sha256"] = duplicate[0]["content_sha256"]
    with pytest.raises(EpistemicResearchSessionOfflineError, match="unique"):
        compile_candidate_research_session_envelope(
            explicit_input_binding_content_sha256="a" * 64,
            ordered_stage_bindings=duplicate,
            request_branch="A0_HOST_PREISSUANCE_CANDIDATE",
        )
    with pytest.raises(EpistemicResearchSessionOfflineError, match="unknown"):
        compile_candidate_research_session_envelope(
            explicit_input_binding_content_sha256="a" * 64,
            ordered_stage_bindings=_stages(),
            request_branch="CALLER_SELECTED_BRANCH",
        )


def test_coordinated_boundary_tamper_and_extra_field_fail_closed() -> None:
    session = _compile()
    tampered = copy.deepcopy(session)
    tampered["execution_boundary"]["filesystem_write_allowed"] = True
    tampered = _rehash(tampered)
    with pytest.raises(EpistemicResearchSessionOfflineError, match="closed_replay_equality"):
        validate_candidate_research_session_envelope(tampered)

    expanded = copy.deepcopy(session)
    expanded["ambient_registry"] = "legacy"
    expanded = _rehash(expanded)
    with pytest.raises(EpistemicResearchSessionOfflineError, match="closed_fields"):
        validate_candidate_research_session_envelope(expanded)
