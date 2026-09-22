from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ULTIMATE_SKILL = REPO_ROOT / "skills" / "factor-forge-ultimate" / "SKILL.md"
ULTIMATE_CONTRACT = (
    REPO_ROOT
    / "skills"
    / "factor-forge-ultimate"
    / "references"
    / "current-operating-contract.md"
)
ADVISORY_DELTA = (
    REPO_ROOT
    / "skills"
    / "factor-forge-ultimate"
    / "references"
    / "epistemic-advisory-operating-delta-v1.md"
)
STEP1_SKILL = REPO_ROOT / "skills" / "factor-forge-step1" / "SKILL.md"
BRIDGE_CLI = (
    REPO_ROOT / "scripts" / "run_factorforge_epistemic_source_first_advisory.py"
)
VALIDATOR_CLI = (
    REPO_ROOT / "scripts" / "validate_factorforge_epistemic_source_first_advisory.py"
)
OPERATIONS = (
    REPO_ROOT / "docs" / "operations" / "factorforge-ultimate-epistemic-shadow.zh-CN.md"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ultimate_routes_new_sources_through_the_advisory_delta() -> None:
    skill = _text(ULTIMATE_SKILL)

    assert "epistemic-advisory-operating-delta-v1.md" in skill
    assert "freeze the agent-authored source-only overlay before any" in skill
    assert "ask the user to configure RAG paths" in skill
    assert "never reopen the advisory path" in skill
    assert "`0..N` candidates" in skill


def test_current_contract_freezes_source_before_knowledge() -> None:
    contract = _text(ULTIMATE_CONTRACT)
    entry = contract[contract.index("## Non-Negotiable Entry Contract") :]

    source_freeze = entry.index("first freeze the source-only understanding")
    knowledge_read = entry.index("read relevant factor knowledge")
    assert source_freeze < knowledge_read
    assert "Epistemic Advisory Operating Delta" in contract
    assert "future-question-only" in contract
    assert "does not change the current formal Step6 branch validator" in contract


def test_step1_scoped_precedence_is_explicit() -> None:
    skill = _text(STEP1_SKILL)
    scoped = skill[skill.index("For a new source entering through Ultimate") :]

    assert scoped.index("freeze the source-only understanding") < scoped.index(
        "run A0 retrieval"
    )
    assert "For other current routes" in scoped


def test_delta_keeps_user_out_of_rag_and_preserves_negative_authority() -> None:
    delta = _text(ADVISORY_DELTA)
    cli = _text(BRIDGE_CLI)
    validator_cli = _text(VALIDATOR_CLI)
    operations = _text(OPERATIONS)

    assert "Do not ask the user to configure RAG" in delta
    assert "Each lane contains `0..N` candidates" in delta
    assert "Never fabricate a dummy branch" in delta
    assert "ADVISORY_NOT_RUN__DIAGNOSIS_SEED_UNAVAILABLE" in delta
    assert "current formal Step6 multi-branch validator" in delta
    assert "`authority_effect=NONE`" in delta
    assert "new-source formal intake must\nBLOCK" in delta
    assert "After a valid source-only freeze exists" in delta
    assert "Legacy/manual S5 Step1 observation sidecar" in operations
    assert "不是 S6 默认路径" in operations
    assert "不要求 `alpha_idea_master`" in operations
    assert "--node-index" not in cli
    assert "--edge-index" not in cli
    assert "--taxonomy" not in cli
    assert "--session-secret" not in cli
    assert "validate_source_first_advisory_package" in validator_cli
    assert "不得再打开 advisory 路径" in operations


def test_delta_does_not_create_a_formal_failure_diagnosis_adapter() -> None:
    delta = _text(ADVISORY_DELTA)

    assert "may not execute a diagnostic test" in delta
    assert "cannot be written back into the current" in delta
    assert "requires a separate reviewed" in delta
