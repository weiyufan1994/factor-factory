from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from factor_factory.research_conjecture import (
    RESEARCH_PROTOCOL_SCOPE_HOSTED,
    RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
    research_protocol_paths,
    validate_protocol_bundle,
    validate_research_conjecture,
    write_json,
)
from scripts.run_factorforge_research_protocol_smoke import (
    valid_approaches,
    valid_conjecture,
    valid_state,
)


LOCAL_IS_POLICY = {
    "scope": "ordinary_local_is_only",
    "oos_allocation_allowed": False,
    "oos_access_allowed": False,
    "oos_finalization_allowed": False,
    "recovery_allowed": False,
    "child_revision_allowed": False,
    "official_promotion_allowed": False,
    "canonical_writeback_allowed": False,
}


def local_is_conjecture() -> dict:
    conjecture = deepcopy(valid_conjecture())
    conjecture["local_is_policy"] = deepcopy(LOCAL_IS_POLICY)
    evidence = conjecture["evidence_policy"]
    for field in ("oos_start", "oos_end", "sealed_oos_token_hash"):
        evidence.pop(field)
    evidence["oos_sealed_during_search"] = True
    return conjecture


def _write_local_bundle(root: Path) -> str:
    state = valid_state()
    conjecture = local_is_conjecture()
    approaches = valid_approaches()
    report_id = str(conjecture["report_id"])
    paths = research_protocol_paths(root, report_id)
    write_json(paths["state"], state)
    write_json(paths["conjecture"], conjecture)
    write_json(paths["approaches"], approaches)
    return report_id


def test_explicit_local_is_scope_accepts_unallocated_oos_with_full_is_controls() -> None:
    assert (
        validate_research_conjecture(
            local_is_conjecture(), scope=RESEARCH_PROTOCOL_SCOPE_LOCAL_IS
        )
        == []
    )


def test_missing_local_scope_does_not_relax_hosted_oos_requirements() -> None:
    reasons = validate_research_conjecture(
        local_is_conjecture(), scope=RESEARCH_PROTOCOL_SCOPE_HOSTED
    )
    assert "BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_MISSING:oos_start" in reasons
    assert "BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_MISSING:oos_end" in reasons
    assert "BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_MISSING:sealed_oos_token_hash" in reasons


def test_local_scope_requires_an_explicit_non_authority_policy() -> None:
    conjecture = local_is_conjecture()
    conjecture.pop("local_is_policy")
    reasons = validate_research_conjecture(
        conjecture, scope=RESEARCH_PROTOCOL_SCOPE_LOCAL_IS
    )
    assert "BLOCK_FACTORFORGE_LOCAL_IS_POLICY_INVALID" in reasons


def test_local_is_scope_rejects_real_oos_allocation() -> None:
    conjecture = local_is_conjecture()
    conjecture["evidence_policy"].update(
        {
            "oos_start": "2025-01-01",
            "oos_end": "2025-12-31",
            "sealed_oos_token_hash": "a" * 64,
        }
    )
    reasons = validate_research_conjecture(
        conjecture, scope=RESEARCH_PROTOCOL_SCOPE_LOCAL_IS
    )
    assert "BLOCK_FACTORFORGE_LOCAL_IS_OOS_ALLOCATION_FORBIDDEN" in reasons


def test_local_is_bundle_cannot_use_promotion_or_final_exemption(tmp_path: Path) -> None:
    report_id = _write_local_bundle(tmp_path)
    pre_council = validate_protocol_bundle(
        root=tmp_path,
        report_id=report_id,
        stage="pre_council",
        scope=RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
    )
    assert pre_council["verdict"] == "PASS"
    assert pre_council["scope"] == RESEARCH_PROTOCOL_SCOPE_LOCAL_IS

    for stage in ("pre_promotion", "final"):
        report = validate_protocol_bundle(
            root=tmp_path,
            report_id=report_id,
            stage=stage,
            scope=RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
        )
        assert report["verdict"] == "BLOCK"
        assert "BLOCK_FACTORFORGE_LOCAL_IS_DOWNSTREAM_AUTHORITY_FORBIDDEN" in report[
            "block_reasons"
        ]
