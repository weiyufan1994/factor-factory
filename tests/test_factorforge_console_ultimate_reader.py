from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest


REPORT_ID = "factor_report_001"
RESEARCH_ID = "research_001"
VERIFIER_VERSION = "factorforge_console_bound_factor_proof_verifier_v1"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _wrapper_path(workspace: Path) -> Path:
    return workspace / "objects" / "runtime_context" / f"ultimate_run_report__{REPORT_ID}.json"


def _proof_path(workspace: Path) -> Path:
    return workspace / "objects" / "research_protocol" / f"factor_proof_certificate__{REPORT_ID}.json"


def _verifier_path(workspace: Path) -> Path:
    return workspace / "objects" / "research_protocol" / f"factor_proof_verifier_report__{REPORT_ID}.json"


def _mock_formal_validation(monkeypatch: pytest.MonkeyPatch, *, verdict: str) -> None:
    import factor_factory.console.ultimate_reader as reader

    monkeypatch.setattr(
        reader,
        "validate_factor_proof_certificate",
        lambda *args, **kwargs: {"verdict": verdict, "block_reasons": []},
    )
    monkeypatch.setattr(
        reader,
        "validate_protocol_bundle",
        lambda *args, **kwargs: {"verdict": "PASS", "block_reasons": []},
    )


def _write_council_pass(workspace: Path) -> None:
    root = workspace / "objects" / "research_iteration_master" / "revision_council" / REPORT_ID
    _write_json(
        root / f"revision_council_summary__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "status": "PASS"},
    )
    _write_json(
        root / f"main_agent_council_synthesis__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "status": "PASS", "selected_revision": "terminal"},
    )


def _bound_verifier(*, factor_id: str, verdict: str, formal: bool = True) -> dict:
    return {
        "verifier_contract_version": VERIFIER_VERSION,
        "report_id": REPORT_ID,
        "factor_id": factor_id,
        "research_id": RESEARCH_ID,
        "verdict": verdict,
        "formal_proof_eligible": formal,
        "block_reasons": [],
    }


def _formal_wrapper_contract(*, formal: bool = True) -> dict:
    command_names = [
        "run_step3",
        "validate_step3",
        "run_step3b",
        "validate_step3b",
        "run_step4",
        "validate_step4",
        "run_step5",
        "validate_step5",
        "run_step6",
        "validate_step6",
        "validate_research_protocol_pre_council",
    ]
    return {
        "dry_run": False,
        "formal_proof_eligible": formal,
        "requested_steps": ["3", "4", "5", "6"],
        "commands": [
            {"name": name, "returncode": 0, "status": "PASS"}
            for name in command_names
        ],
        "formal_command_contract": {
            "required_command_names": command_names,
            "research_protocol_verifier_required": True,
            "research_protocol_verifier_name": "validate_research_protocol_pre_council",
            "satisfied": True,
        },
    }


def test_archived_wrapper_is_never_selected_as_current_even_when_newer(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    current = _wrapper_path(workspace)
    archived = current.with_name(
        f"{current.stem}__prior_deadbeef0000{current.suffix}"
    )
    _write_json(
        current,
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CURRENT",
            "research_id": RESEARCH_ID,
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_memo_revision",
            },
        },
    )
    _write_json(
        archived,
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_ARCHIVED",
            "research_id": RESEARCH_ID,
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_memo",
            },
        },
    )
    os.utime(current, ns=(1_000_000_000, 1_000_000_000))
    os.utime(archived, ns=(2_000_000_000, 2_000_000_000))

    summary = read_ultimate_workspace(workspace, report_id=REPORT_ID)

    assert summary.factor_id == "FACTOR_CURRENT"
    assert summary.artifact_ids["wrapper_report"] == current.relative_to(
        workspace
    ).as_posix()


def test_prior_text_inside_report_id_does_not_hide_current_wrapper(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    report_id = f"{REPORT_ID}__prior_name"
    workspace = tmp_path / "workspace"
    current = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    _write_json(
        current,
        {
            "report_id": report_id,
            "factor_id": "FACTOR_LEGITIMATE",
            "research_id": RESEARCH_ID,
            "status": "PAUSED",
        },
    )

    summary = read_ultimate_workspace(workspace, report_id=report_id)

    assert summary.factor_id == "FACTOR_LEGITIMATE"
    assert summary.artifact_ids["wrapper_report"] == current.relative_to(
        workspace
    ).as_posix()


def test_wrapper_pass_does_not_override_paused_council(tmp_path: Path) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_A",
            "status": "PASS",
            "formal_proof_eligible": True,
            "commands": [{"name": "run_step6", "returncode": 0, "status": "PASS"}],
            "revision_council": {
                "status": "awaiting_agent_results",
                "formal_council_status": "awaiting_agent_results",
            },
            "started_at_utc": "2026-08-01T01:00:00Z",
            "finished_at_utc": "2026-08-01T01:05:00Z",
        },
    )
    _write_json(
        workspace / "objects" / "runtime_context" / f"ultimate_loop_report__{REPORT_ID}.json",
        {
            "root_report_id": REPORT_ID,
            "status": "PAUSED",
            "formal_proof_eligible": False,
            "final_outcome": "awaiting_agent_results",
            "iterations": [
                {
                    "report_id": REPORT_ID,
                    "outcome": "awaiting_agent_results",
                    "proof_status": "PAUSED",
                    "council_status": "awaiting_agent_results",
                    "wrapper_command": {"rc": 0, "status": "PASS"},
                }
            ],
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_A",
            "declared_verdict": "ACCEPT",
            "metrics": {},
        },
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "PAUSED"
    assert summary.protocol_status == "PAUSED"
    assert summary.council_status == "PAUSED"
    assert summary.factor_verdict == "ACCEPT"
    assert summary.formal_proof_eligible is False
    assert summary.current_stage == "awaiting_agent_results"


def test_formal_reject_is_not_reported_as_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_REJECTED",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "revision_council": {"status": "complete"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_REJECTED",
            "declared_verdict": "REJECT",
            "formal_proof_eligible": True,
            "metrics": {"ic": {"method": "rank_ic", "mean": -0.01}},
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_REJECTED", verdict="REJECT"),
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
        / f"revision_council_summary__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "status": "PASS"},
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
        / f"main_agent_council_synthesis__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "status": "PASS", "selected_revision": "reject"},
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "REJECTED"
    assert summary.protocol_status == "PASS"
    assert summary.factor_verdict == "REJECT"
    assert summary.council_status == "PASS"
    assert summary.formal_proof_eligible is True


def test_reader_extracts_contracts_and_metrics_without_recomputation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="ACCEPT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_METRICS",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "revision_council": {"status": "skipped"},
            "started_at_utc": "2026-08-01T02:00:00Z",
            "finished_at_utc": "2026-08-01T02:10:00Z",
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_METRICS", verdict="ACCEPT"),
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_METRICS",
            "declared_verdict": "ACCEPT",
            "formal_proof_eligible": True,
            "data_contract": {
                "is_window": "2018-01-01/2024-12-31",
                "oos_window": "2025-01-01/2025-12-31",
                "universe": "A-share core",
                "signal_timestamp": "t close",
                "execution_timestamp": "t+1 open",
                "cost_policy_id": "roundtrip_20bps_v1",
                "dataset_path": "/private/data/must-not-leak.parquet",
            },
            "metrics": {
                "ic": {"method": "pearson_ic", "mean": 0.013},
                "rank_ic": {"mean": 0.027, "period_count": 240},
                "icir": {"value": 1.42, "annualized": False},
                "fama_macbeth": {"lambda_mean": 0.0012, "t_stat": 2.3},
                "long_side_after_cost": {"net_return_annual": 0.118},
                "turnover": {"annual_turnover": 4.7},
                "drawdown": {
                    "max_drawdown": -0.18,
                    "recovery_days": 63,
                    "recovery_area": 1.7,
                },
                "bucket_monotonicity": {
                    "bucket_count": 5,
                    "monotonicity_score": 0.75,
                },
            },
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_protocol"
        / f"research_quality_gate__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_METRICS",
            "status": "ready_for_pre_council_validation",
            "mechanism_claim_level": "math_framed",
            "economic_mechanism_contract": {
                "preferred_claim": "Urgent buyers pay patient liquidity providers.",
                "payer_candidates": ["urgent buyers"],
                "receiver": "patient liquidity providers",
            },
            "mathematical_object_contract": {
                "random_object": "conditional occupation measure",
                "target_statistic": "tail-state inner product",
                "observation_equation": "Y = beta X + epsilon",
            },
            "falsification_plan": {"kill_mechanism_if": ["after-cost long side is non-positive"]},
        },
    )
    _write_council_pass(workspace)
    _write_json(
        workspace
        / "objects"
        / "implementation_plan_master"
        / f"implementation_plan_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "implementation_mode": "direct_code",
            "implementation_status": "ready",
            "code_contract": {
                "entrypoint": "compute_factor",
                "required_fields": ["trade_date", "ts_code", "factor"],
                "output_schema": {"columns": ["trade_date", "ts_code", "factor_value"]},
                "source_code": "raise AssertionError('must not be returned')",
            },
        },
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "COMPLETED"
    assert summary.factor_verdict == "ACCEPT"
    assert summary.economic_game["payer_candidates"] == ["urgent buyers"]
    assert summary.math_mechanism["target_statistic"] == "tail-state inner product"
    assert summary.research_method["mechanism_claim_level"] == "math_framed"
    assert summary.data_contract["cost_policy_id"] == "roundtrip_20bps_v1"
    assert "dataset_path" not in summary.data_contract
    assert summary.implementation_contract["entrypoint"] == "compute_factor"
    assert "source_code" not in summary.implementation_contract
    assert summary.core_metrics["ic"]["mean"] == 0.013
    assert summary.core_metrics["rank_ic"]["mean"] == 0.027
    assert summary.core_metrics["icir"]["value"] == 1.42
    assert summary.core_metrics["fama_macbeth"]["t_stat"] == 2.3
    assert summary.core_metrics["long_side_after_cost"]["net_return_annual"] == 0.118
    assert summary.core_metrics["turnover"]["annual_turnover"] == 4.7
    assert summary.core_metrics["drawdown"]["max_drawdown"] == -0.18
    assert summary.core_metrics["recovery"] == {"recovery_days": 63, "recovery_area": 1.7}
    assert summary.core_metrics["monotonicity"]["monotonicity_score"] == 0.75
    assert summary.timestamps["started_at_utc"] == "2026-08-01T02:00:00Z"
    assert all(not Path(value).is_absolute() for value in summary.artifact_ids.values())


def test_string_research_contracts_are_projected_as_notebook_narratives(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            "contract_version": "factorforge_ultimate_wrapper_v1",
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_STRING_CONTRACT",
            "research_id": RESEARCH_ID,
            "status": "FAIL",
            "failure": {"command": "run_step4", "returncode": 1},
        },
    )
    _write_json(
        workspace
        / "objects"
        / "factor_spec_master"
        / f"factor_spec_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_STRING_CONTRACT",
            "research_id": RESEARCH_ID,
            "economic_hypothesis": "Overnight urgency is paid by impatient buyers.",
            "mathematical_mechanism": "E[r_(t+2)|F_t] = beta * gap_t",
        },
    )

    summary = read_ultimate_workspace(workspace, report_id=REPORT_ID)

    assert summary.research_notebook["stages"][0]["content"] == {
        "narrative": "Overnight urgency is paid by impatient buyers."
    }
    assert summary.math_notebook["derivation_steps"][1]["statement"] == {
        "narrative": "E[r_(t+2)|F_t] = beta * gap_t"
    }


def test_measurement_program_is_projected_into_public_math_notebook(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            "contract_version": "factorforge_ultimate_wrapper_v1",
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_MEASUREMENT",
            "research_id": RESEARCH_ID,
            "status": "RUNNING",
        },
    )
    measurement = {
        "model_selection": {
            "selection_target": "temporary pressure",
            "private_chain_of_thought": "MODEL_SELECTION_SECRET_MARKER",
            "candidate_models": [
                {"candidate_id": "m1", "model_family": "transient", "selected": True},
                {"candidate_id": "m2", "model_family": "permanent", "selected": False},
            ],
        },
        "applicable_audits": {
            "selection_rule": "select only mechanism-relevant audits",
            "selected": [],
            "rejected": [],
        },
        "observation_and_estimation": {
            "observation_map": "gap = permanent + temporary + noise",
            "estimator": "negative gap",
        },
        "implementation": {
            "components": [
                {
                    "component_id": "gap",
                    "math_term_or_functional": "-u_t",
                    "implementation_binding": "negate(gap)",
                    "scratchpad": "COMPONENT_SECRET_MARKER",
                }
            ]
        },
        "public_derivation_record": {
            "definitions": ["u_t is temporary pressure"],
            "key_derivation_steps": ["temporary impact decays"],
            "private_chain_of_thought": "must never leave the reader",
            "scratchpad": {"hidden": "must never leave the reader"},
        },
        "deterministic_validation_plan": {
            "future_mutation_invariance": "required"
        },
        "knowledge_role": {"authority": "advisory_prior_and_counterexample_only"},
    }
    _write_json(
        workspace
        / "objects"
        / "factor_spec_master"
        / f"factor_spec_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_MEASUREMENT",
            "research_id": RESEARCH_ID,
            "mechanism_conditioned_measurement_program": measurement,
        },
    )

    summary = read_ultimate_workspace(workspace, report_id=REPORT_ID)

    assert summary.math_notebook["model_selection"]["selection_target"] == (
        "temporary pressure"
    )
    assert summary.math_notebook["applicable_audits"]["selected"] == []
    assert summary.math_notebook["observation_and_estimation"]["estimator"] == (
        "negative gap"
    )
    assert summary.math_notebook["measurement_components"][0]["component_id"] == (
        "gap"
    )
    assert summary.math_notebook["public_derivation_record"][
        "key_derivation_steps"
    ] == ["temporary impact decays"]
    assert "private_chain_of_thought" not in summary.math_notebook[
        "public_derivation_record"
    ]
    assert "scratchpad" not in summary.math_notebook["public_derivation_record"]
    public_payload = json.dumps(summary.to_dict(), ensure_ascii=False)
    assert "MODEL_SELECTION_SECRET_MARKER" not in public_payload
    assert "COMPONENT_SECRET_MARKER" not in public_payload


def test_current_main_agent_memo_rejects_unknown_public_schema_fields() -> None:
    from factor_factory.console.ultimate_reader import (
        _current_main_agent_memo,
        _public_evidence_copy,
    )
    from factor_factory.mechanism_math.main_agent_memo import (
        memo_public_schema_failures,
    )

    base = {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "report_id": REPORT_ID,
        "factor_id": "FACTOR_MEMO_ALLOWLIST",
        "research_id": RESEARCH_ID,
        "producer": "current_main_agent",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "agent_role": "main_agent",
            "answered_without_deterministic_template": True,
        },
        "economic_hypothesis": {
            "return_source_class": "information_advantage",
            "payer_or_counterparty": "slow updater",
            "why_they_pay": "legal-time belief updates arrive with delay",
            "necessary_market_structure": "heterogeneous update speed",
        },
    }
    assert _current_main_agent_memo(
        base,
        report_id=REPORT_ID,
        factor_id="FACTOR_MEMO_ALLOWLIST",
        research_id=RESEARCH_ID,
    ) == base

    unknown_top = json.loads(json.dumps(base))
    unknown_top["internal_analysis"] = "TOP_LEVEL_PRIVATE_REASONING_MARKER"
    assert memo_public_schema_failures(unknown_top)
    assert not _current_main_agent_memo(
        unknown_top,
        report_id=REPORT_ID,
        factor_id="FACTOR_MEMO_ALLOWLIST",
        research_id=RESEARCH_ID,
    )

    unknown_nested = json.loads(json.dumps(base))
    unknown_nested["economic_hypothesis"]["thought_process"] = (
        "NESTED_PRIVATE_REASONING_MARKER"
    )
    assert memo_public_schema_failures(unknown_nested)
    assert not _current_main_agent_memo(
        unknown_nested,
        report_id=REPORT_ID,
        factor_id="FACTOR_MEMO_ALLOWLIST",
        research_id=RESEARCH_ID,
    )

    unknown_metric = json.loads(json.dumps(base))
    unknown_metric["evidence_comparison"] = {
        "observed_metrics": {
            "rank_ic_mean": 0.01,
            "deliberation_notes": "NESTED_PRIVATE_REASONING_MARKER",
        }
    }
    failures = memo_public_schema_failures(unknown_metric)
    assert any("observed_metrics.deliberation_notes" in item for item in failures)
    assert not _current_main_agent_memo(
        unknown_metric,
        report_id=REPORT_ID,
        factor_id="FACTOR_MEMO_ALLOWLIST",
        research_id=RESEARCH_ID,
    )

    unknown_formula_feature = json.loads(json.dumps(base))
    unknown_formula_feature["formula_understanding"] = {
        "formula_understanding_version": "factorforge_formula_understanding_v1",
        "formula_features": {
            "fields": ["close"],
            "operators": ["rank"],
            "deliberation_notes": "NESTED_PRIVATE_REASONING_MARKER",
        },
        "component_interpretations": [],
        "interaction_structure": "formula_defined_state",
        "mathematical_object_candidates": ["rank state"],
    }
    failures = memo_public_schema_failures(unknown_formula_feature)
    assert any(
        "formula_understanding.formula_features.deliberation_notes" in item
        for item in failures
    )
    assert not _current_main_agent_memo(
        unknown_formula_feature,
        report_id=REPORT_ID,
        factor_id="FACTOR_MEMO_ALLOWLIST",
        research_id=RESEARCH_ID,
    )

    assert _public_evidence_copy(
        {
            "observed_metrics": {
                "metric_period": "2016-01-01/2025-07-11",
                "rank_ic_mean": 0.01,
                "cost_adjusted_annual_return": 0.05,
                "monotonicity_diagnostic": "top_group_not_above_bottom_group",
            },
            "observed_metric_conflict_keys": ["rank_ic_mean"],
            "mechanism_supported": "partial",
        }
    ) == {
        "observed_metric_conflict_keys": ["rank_ic_mean"],
        "mechanism_supported": "partial",
        "observed_metrics": {
            "metric_period": "2016-01-01/2025-07-11",
            "monotonicity_diagnostic": "top_group_not_above_bottom_group",
        "cost_adjusted_annual_return": 0.05,
        "rank_ic_mean": 0.01,
        },
    }


def test_internal_evidence_with_host_paths_is_read_but_public_text_is_redacted(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_INTERNAL_PATH",
            "research_id": "research_internal_path",
            "status": "RUNNING",
            "command": "/var/lib/factorforge/private/run.sh",
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_protocol"
        / f"research_quality_gate__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_INTERNAL_PATH",
            "economic_mechanism_contract": {
                "preferred_claim": (
                    "workspace: /var/lib/factorforge/private and "
                    "api_key: sk-public-copy-must-redact"
                ),
                "access_key_id": "AKIAEXAMPLE1234567890",
                "access_key": "must-not-be-public",
            },
        },
    )

    summary = read_ultimate_workspace(workspace)
    serialized = json.dumps(summary.to_dict(), ensure_ascii=False)

    assert "wrapper_report" in summary.artifact_ids
    assert summary.evidence_errors == []
    assert "/var/lib/factorforge" not in serialized
    assert "sk-public-copy-must-redact" not in serialized
    assert "must-not-be-public" not in serialized
    assert "access_key_id" not in serialized
    assert "[internal-path]" in serialized
    assert "[redacted]" in serialized


def test_invalid_certificate_cannot_forge_formal_pass(tmp_path: Path) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_FORGED",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "formal_proof_eligible": True,
            "revision_council": {"status": "skipped"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_FORGED",
            "declared_verdict": "ACCEPT",
            "formal_proof_eligible": True,
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_FORGED", verdict="ACCEPT"),
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert summary.protocol_status == "BLOCK"
    assert summary.factor_verdict == "BLOCK"
    assert summary.formal_proof_eligible is False
    assert any("BLOCK_FACTORFORGE_FACTOR_PROOF" in item for item in summary.blockers)


def test_verifier_block_overrides_other_true_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CONTRADICTION",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "formal_proof_eligible": True,
            "revision_council": {"status": "skipped"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CONTRADICTION",
            "declared_verdict": "REJECT",
            "formal_proof_eligible": True,
        },
    )
    _write_json(
        _verifier_path(workspace),
        {
            **_bound_verifier(
                factor_id="FACTOR_CONTRADICTION",
                verdict="BLOCK",
                formal=False,
            ),
            "status": "BLOCK",
            "block_reasons": ["BLOCK_REVIEW_PROBE"],
        },
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert summary.protocol_status == "BLOCK"
    assert summary.formal_proof_eligible is False
    assert "BLOCK_REVIEW_PROBE" in summary.blockers


def test_dry_run_reject_stays_dry_run(tmp_path: Path) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_DRY",
            "status": "DRY_RUN",
            "dry_run": True,
            "formal_proof_eligible": False,
            "revision_council": {"status": "skipped"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_DRY",
            "declared_verdict": "REJECT",
        },
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "DRY_RUN"
    assert summary.protocol_status == "UNKNOWN"
    assert summary.formal_proof_eligible is False


def test_explicit_false_formal_flag_blocks_terminal_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(formal=False),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_FALSE_FLAG",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "revision_council": {"status": "skipped"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_FALSE_FLAG",
            "declared_verdict": "REJECT",
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_FALSE_FLAG", verdict="REJECT"),
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.protocol_status == "BLOCK"
    assert summary.factor_verdict == "BLOCK"
    assert summary.formal_proof_eligible is False


def test_running_council_cannot_be_formal_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="ACCEPT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_COUNCIL_RUNNING",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "revision_council": {"status": "running"},
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_COUNCIL_RUNNING",
            "declared_verdict": "ACCEPT",
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_COUNCIL_RUNNING", verdict="ACCEPT"),
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
        / f"agentic_council_dispatch_manifest__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "status": "RUNNING"},
    )

    summary = read_ultimate_workspace(workspace)

    assert summary.protocol_status == "PASS"
    assert summary.council_status == "RUNNING"
    assert summary.formal_proof_eligible is False
    assert summary.execution_status == "REVIEW_REQUIRED"


def test_factor_case_explicit_block_overrides_positive_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="ACCEPT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CASE_BLOCK",
            "research_id": RESEARCH_ID,
            "status": "PASS",
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CASE_BLOCK",
            "declared_verdict": "ACCEPT",
            "formal_proof_eligible": True,
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_CASE_BLOCK", verdict="ACCEPT"),
    )
    _write_json(
        workspace / "objects" / "factor_case_master" / f"factor_case_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_CASE_BLOCK",
            "status": "BLOCK",
            "formal_proof_eligible": False,
        },
    )
    _write_council_pass(workspace)

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert summary.protocol_status == "BLOCK"
    assert summary.factor_verdict == "BLOCK"
    assert summary.formal_proof_eligible is False


def test_verifier_research_binding_mismatch_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            **_formal_wrapper_contract(),
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_VERIFIER_BINDING",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "formal_proof_eligible": True,
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_VERIFIER_BINDING",
            "declared_verdict": "REJECT",
            "formal_proof_eligible": True,
        },
    )
    verifier = _bound_verifier(factor_id="FACTOR_VERIFIER_BINDING", verdict="REJECT")
    verifier["research_id"] = "another_research"
    _write_json(_verifier_path(workspace), verifier)
    _write_council_pass(workspace)

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert "BLOCK_FACTORFORGE_CONSOLE_FORMAL_VERIFIER_MISMATCH" in summary.blockers


def test_terminal_verdict_requires_formal_ultimate_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    _write_json(
        _wrapper_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_WRAPPER",
            "research_id": RESEARCH_ID,
            "status": "PASS",
            "dry_run": False,
            "formal_proof_eligible": True,
        },
    )
    _write_json(
        _proof_path(workspace),
        {
            "report_id": REPORT_ID,
            "factor_id": "FACTOR_WRAPPER",
            "declared_verdict": "REJECT",
        },
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_WRAPPER", verdict="REJECT"),
    )
    _write_council_pass(workspace)

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert "BLOCK_FACTORFORGE_CONSOLE_FORMAL_WRAPPER_INVALID" in summary.blockers
    assert any("BLOCK_FACTORFORGE_LOOP_WRAPPER_PROOF_NOT_FORMAL" in item for item in summary.blockers)


def test_step6_only_wrapper_cannot_claim_complete_console_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    identity = {
        "report_id": REPORT_ID,
        "factor_id": "FACTOR_STEP6_ONLY",
        "research_id": RESEARCH_ID,
    }
    step6_commands = [
        "run_step6",
        "validate_step6",
        "validate_research_protocol_pre_council",
    ]
    _write_json(
        _wrapper_path(workspace),
        {
            **identity,
            "dry_run": False,
            "formal_proof_eligible": True,
            "requested_steps": ["6"],
            "commands": [
                {"name": name, "returncode": 0, "status": "PASS"}
                for name in step6_commands
            ],
            "formal_command_contract": {
                "required_command_names": step6_commands,
                "research_protocol_verifier_required": True,
                "research_protocol_verifier_name": "validate_research_protocol_pre_council",
                "satisfied": True,
            },
        },
    )
    _write_json(
        _proof_path(workspace),
        {**identity, "declared_verdict": "REJECT"},
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_STEP6_ONLY", verdict="REJECT"),
    )
    _write_council_pass(workspace)

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert any("complete_step3_step6_chain_required" in item for item in summary.blockers)


def test_newer_pass_cannot_hide_earlier_block_for_same_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    _mock_formal_validation(monkeypatch, verdict="REJECT")
    workspace = tmp_path / "workspace"
    identity = {
        "report_id": REPORT_ID,
        "factor_id": "FACTOR_HISTORY",
        "research_id": RESEARCH_ID,
    }
    _write_json(
        _wrapper_path(workspace),
        {**_formal_wrapper_contract(), **identity, "status": "PASS"},
    )
    _write_json(
        _proof_path(workspace),
        {**identity, "declared_verdict": "REJECT"},
    )
    _write_json(
        _verifier_path(workspace),
        _bound_verifier(factor_id="FACTOR_HISTORY", verdict="REJECT"),
    )
    factor_case_root = workspace / "objects" / "factor_case_master"
    _write_json(
        factor_case_root / f"factor_case_master__{REPORT_ID}__early.json",
        {**identity, "status": "BLOCK"},
    )
    _write_json(
        factor_case_root / f"factor_case_master__{REPORT_ID}__latest.json",
        {**identity, "status": "PASS", "final_verdict": "REJECT"},
    )
    _write_council_pass(workspace)

    summary = read_ultimate_workspace(workspace)

    assert summary.execution_status == "BLOCKED"
    assert any("EXPLICIT_BLOCKED_EVIDENCE:factor_case" in item for item in summary.blockers)


def test_artifact_service_lists_only_user_safe_files(tmp_path: Path) -> None:
    from factor_factory.console.artifact_service import list_artifact_ids

    workspace = tmp_path / "workspace"
    safe_files = {
        "reports/method.md": "# Method",
        "reports/result.txt": "ACCEPT",
        "reports/metrics.csv": "metric,value\nic,0.03\n",
        "objects/proof.json": "{}",
        "charts/nav.svg": "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        "reports/report.html": "<html><body>report</body></html>",
    }
    for artifact_id, content in safe_files.items():
        path = workspace / artifact_id
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    png_path = workspace / "charts" / "nav.png"
    png_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )

    blocked_files = {
        "logs/worker.txt": "raw worker output",
        "objects/step1_llm_raw__primary.json": "{}",
        "objects/provider_credentials.json": '{"api_key": "sk-not-for-browser-123456"}',
        "objects/config.json": '{"api_key": "sk-not-for-browser-123456"}',
        "objects/session.json": '{"session_token": "temporary-session-token-must-not-publish"}',
        "objects/access.json": '{"access_token": "temporary-access-token-must-not-publish"}',
        "objects/aws_session.json": '{"aws_session_token": "temporary-aws-token-must-not-publish"}',
        "objects/generic_token.json": '{"token": "temporary-generic-token-must-not-publish"}',
        "reports/run.log": "returncode=0",
        "reports/report.pdf": "%PDF",
        "reports/internal_path.md": "workspace: /srv/factorforge/jobs/private/repo",
        "reports/var_lib_path.md": "workspace: /var/lib/factorforge/private/repo",
        "reports/unquoted_secret.md": "api_key: sk-this-must-never-reach-the-browser",
        "reports/late_secret.md": "x" * (2 * 1024 * 1024 + 16)
        + "\npassword: this-is-a-late-secret",
    }
    for artifact_id, content in blocked_files.items():
        path = workspace / artifact_id
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (workspace / "charts" / "trailing-payload.png").write_bytes(
        png_path.read_bytes() + b"api_key: sk-png-trailing-payload"
    )

    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (workspace / "reports" / "outside-link.md").symlink_to(outside)

    assert list_artifact_ids(workspace) == sorted([*safe_files, "charts/nav.png"])


def test_publication_omits_exact_temporary_credential_in_innocent_field(tmp_path: Path) -> None:
    import base64

    from factor_factory.console.artifact_service import publish_official_artifacts

    workspace = tmp_path / "workspace"
    denied_value = "temporary-session-value-for-publication-test"
    artifact = workspace / "objects" / "formal_result.json"
    _write_json(
        artifact,
        {"status": "PASS", "ordinary_note": denied_value},
    )
    escaped = "".join(
        f"\\u{ord(character):04x}"
        for character in denied_value
    )
    encoded_artifact = workspace / "objects" / "encoded_formal_result.json"
    encoded_artifact.write_text(
        '{"status":"PASS","ordinary_note":"' + escaped + '"}',
        encoding="utf-8",
    )
    base64_artifact = workspace / "objects" / "base64_formal_result.json"
    _write_json(
        base64_artifact,
        {
            "status": "PASS",
            "ordinary_note": base64.urlsafe_b64encode(
                denied_value.encode("utf-8")
            ).decode("ascii").rstrip("="),
        },
    )
    escaped_markdown = workspace / "objects" / "encoded_formal_result.md"
    escaped_markdown.write_text(f"ordinary note: {escaped}\n", encoding="utf-8")
    base64_markdown = workspace / "objects" / "base64_formal_result.md"
    base64_markdown.write_text(
        "ordinary note: "
        + base64.b64encode(denied_value.encode("utf-8")).decode("ascii").rstrip("=")
        + "\n",
        encoding="utf-8",
    )
    publication_id, published = publish_official_artifacts(
        workspace,
        tmp_path / "public" / "job_1234567890",
        role_artifact_ids={
            "formal_result": "objects/formal_result.json",
            "encoded_formal_result": "objects/encoded_formal_result.json",
            "base64_formal_result": "objects/base64_formal_result.json",
            "encoded_markdown": "objects/encoded_formal_result.md",
            "base64_markdown": "objects/base64_formal_result.md",
        },
        identity={"job_id": "job_1234567890"},
        denied_values=(denied_value,),
    )

    assert publication_id.startswith("pub_")
    assert published == []
    manifest = json.loads(
        (
            tmp_path
            / "public"
            / "job_1234567890"
            / publication_id
            / ".publication.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["artifacts"] == []
    assert {item["artifact_id"] for item in manifest["omitted_artifacts"]} == {
        "objects/formal_result.json",
        "objects/encoded_formal_result.json",
        "objects/base64_formal_result.json",
        "objects/encoded_formal_result.md",
        "objects/base64_formal_result.md",
    }


@pytest.mark.parametrize(
    "artifact_id",
    ["../outside.md", "reports/../../outside.md", "/tmp/outside.md", "~/outside.md", "reports\\x.md"],
)
def test_artifact_resolver_blocks_traversal_and_absolute_paths(
    tmp_path: Path,
    artifact_id: str,
) -> None:
    from factor_factory.console.artifact_service import ArtifactAccessError, resolve_artifact_path

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ArtifactAccessError):
        resolve_artifact_path(workspace, artifact_id)


def test_artifact_resolver_blocks_symlink_and_logs(tmp_path: Path) -> None:
    from factor_factory.console.artifact_service import ArtifactAccessError, resolve_artifact_path

    workspace = tmp_path / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (reports / "outside.md").symlink_to(outside)
    (reports / "run.log").write_text("PASS", encoding="utf-8")

    with pytest.raises(ArtifactAccessError):
        resolve_artifact_path(workspace, "reports/outside.md")
    with pytest.raises(ArtifactAccessError):
        resolve_artifact_path(workspace, "reports/run.log")


def test_artifact_descriptor_never_exposes_absolute_path(tmp_path: Path) -> None:
    from factor_factory.console.artifact_service import describe_artifact

    workspace = tmp_path / "workspace"
    artifact = workspace / "reports" / "result.json"
    _write_json(artifact, {"verdict": "ACCEPT"})

    payload = describe_artifact(workspace, "reports/result.json").to_dict()

    assert payload["artifact_id"] == "reports/result.json"
    assert str(workspace) not in json.dumps(payload)
    assert set(payload) == {
        "artifact_id",
        "media_type",
        "size_bytes",
        "modified_at_utc",
        "content_disposition",
    }
