from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from factor_factory.measurement_program import measurement_program_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = "RPT_pdf_manifest_bound_adapter_test"
FACTOR_ID = "manifest_bound_adapter_test_factor"


def _load_step2():
    path = PROJECT_ROOT / "skills/factor-forge-step2/scripts/run_step2.py"
    spec = importlib.util.spec_from_file_location(
        "factorforge_step2_manifest_bound_adapter_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP2 = _load_step2()


def _load_validator():
    path = PROJECT_ROOT / "skills/factor-forge-step2/scripts/validate_step2.py"
    spec = importlib.util.spec_from_file_location(
        "factorforge_step2_manifest_bound_adapter_validator_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _valid_measurement_program_and_equation() -> tuple[dict, dict]:
    placeholder = "RESEARCHER_MUST_REPLACE"
    program = measurement_program_template(
        placeholder=placeholder,
        implementation_route="operator",
        contract_version=STEP2.MEASUREMENT_PROGRAM_VERSION_V2,
    )

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return "manifest-bound mechanism statement" if value == placeholder else value

    program = fill(program)
    observation = program["observation_and_estimation"]
    observation.update(
        {
            "estimand": "conditional temporary-impact payoff",
            "observation_map": "legal event path maps to temporary-impact state",
            "executable_formula_projection": "score_t = estimate(event_path_t)",
            "estimator": "legal-time event-response estimator",
        }
    )
    outcome = program["market_outcome_projection"]
    outcome.update(
        {
            "source_math_object": "temporary-impact state",
            "projection_equation_or_map": "expected_return_t1 = -temporary_impact_t",
        }
    )
    candidates = program["model_selection"]["candidate_models"]
    candidates[0].update(
        {
            "model_family": "temporary-impact event model",
            "mathematical_object": outcome["source_math_object"],
            "mechanism_equation_or_functional": "impact_t = flow_t - resilience_t",
            "target_functional": observation["estimand"],
            "market_outcome_projection": outcome["projection_equation_or_map"],
            "observation_mapping": observation["observation_map"],
        }
    )
    candidates[1].update(
        {
            "model_family": "permanent-information alternative",
            "mechanism_equation_or_functional": "return_t = information_t",
            "target_functional": "permanent-information payoff",
            "market_outcome_projection": "no reversal",
            "observation_mapping": "news-conditioned event map",
        }
    )
    candidates[2].update(
        {
            "model_family": "liquidity alias null",
            "mechanism_equation_or_functional": "score_t = controls_t + noise_t",
            "target_functional": "zero incremental payoff",
            "market_outcome_projection": "zero after-cost return",
            "observation_mapping": "legal-time control projection",
        }
    )
    equation = program["research_equation"]
    equation.update(
        {
            "equation_status": "research_conjecture",
            "equation_text": "impact_t = event_mass_t * transient_decay_t",
            "assumptions": ["event inputs are available before portfolio formation"],
            "validity_scope": {
                "market": "test equities",
                "frequency": "intraday to next session",
                "regime": "tradable sessions",
                "participant_structure": "finite-depth liquidity supply",
            },
            "symmetry_or_constraint": "balanced flow produces no temporary state",
            "symmetry_breaking_mechanism": "one-sided demand meets finite depth",
            "participant_constraint_loop": {
                "payer": "urgent demander",
                "constraint": "execution urgency",
                "repeat_mechanism": "new urgent demand repeats",
                "failure_condition": "deep liquidity absorbs demand",
            },
            "equation_quality": {
                "evidence_tier": "report_specific_hypothesis",
                "audit_basis": ["manifest-bound source and Step1 program"],
                "demotion_triggers": ["metric_signature_mismatch"],
            },
            "evidence_tier": "report_specific_hypothesis",
            "audit_basis": ["manifest-bound source and Step1 program"],
            "demotion_triggers": ["metric_signature_mismatch"],
            "mathematical_object": candidates[0]["mathematical_object"],
            "observation_or_estimation_map": observation["observation_map"],
            "observable_estimator": observation["estimator"],
            "expected_metric_signature": ["temporary impact later relaxes"],
            "falsification_tests": ["compare matched event-time placebos"],
            "kill_criteria": ["kill when relaxation is absent"],
        }
    )
    return program, deepcopy(equation)


def _raw_spec(route: str) -> dict:
    return {
        "factor_id": FACTOR_ID,
        "report_id": REPORT_ID,
        "route": route,
        "raw_formula_text": f"{route} report-faithful branch lattice",
        "operators": ["occupation_measure()", "event_kernel()"],
        "required_inputs": ["minute_close", "minute_volume"],
        "time_series_steps": ["build legal-time intraday event state"],
        "cross_sectional_steps": ["rank the frozen measurement state"],
        "preprocessing": ["apply declared minute-session mask"],
        "normalization": ["use only the declared normalization branch"],
        "neutralization": [],
        "rebalance_frequency": "monthly",
        "explicit_items": ["source-supported construction branch"],
        "inferred_items": ["unresolved choices remain separate branches"],
        "ambiguities": ["tie and sign conventions require adjudication"],
        "candidate_only": True,
        "authority_effect": "NONE",
    }


def _write_raw(root: Path, route: str, payload: dict | None = None) -> tuple[str, str]:
    relative = f"objects/validation/factor_spec_raw__{route}__{REPORT_ID}.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        payload or _raw_spec(route),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    path.write_bytes(raw)
    return relative, hashlib.sha256(raw).hexdigest()


def _write_json_artifact(root: Path, relative: str, payload: dict) -> dict:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return {"relative_path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def _write_bytes_artifact(
    root: Path,
    relative: str,
    raw: bytes,
    *,
    role: str | None = None,
) -> dict:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    row = {
        "relative_path": relative,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if role is not None:
        row = {"role": role, **row}
    return row


def _write_alpha(root: Path, aim: dict) -> None:
    alpha_path = (
        root
        / "objects/alpha_idea_master"
        / f"alpha_idea_master__{REPORT_ID}.json"
    )
    alpha_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_path.write_text(json.dumps(aim, ensure_ascii=False), encoding="utf-8")


def _aim(root: Path) -> dict:
    research_id = "manifest_bound_adapter_test_research"
    program, equation = _valid_measurement_program_and_equation()
    inputs = {}
    raw_specs = {}
    for route in ("primary", "challenger"):
        raw_specs[route] = _raw_spec(route)
        relative, digest = _write_raw(root, route, raw_specs[route])
        inputs[route] = {
            "route": route,
            "relative_path": relative,
            "sha256": digest,
        }
    source_pdf_relative = "source/s3_original/test-report.pdf"
    source_pdf_raw = b"%PDF-1.7\nmanifest-bound-test\n"
    source_pdf_row = _write_bytes_artifact(
        root,
        source_pdf_relative,
        source_pdf_raw,
        role="s3_report_object",
    )
    source_pdf_binding = {
        "relative_path": source_pdf_row["relative_path"],
        "sha256": source_pdf_row["sha256"],
    }
    text_row = _write_bytes_artifact(
        root,
        "source/s3_original/original.txt",
        b"manifest bound source text\n",
        role="source_text_extraction",
    )
    source_receipt = {
        "schema_id": STEP2.SOURCE_IDENTITY_RECEIPT_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "research_id": research_id,
        "candidate_only": True,
        "signed": False,
        "authority_effect": "NONE",
        "captured_at_utc": "2026-09-01T00:02:00Z",
        "allowed_use": "ISOLATED_FACTOR_RESEARCH_SOURCE_READING",
        "prohibited_inference": ["candidate source is not formal evidence"],
        "provenance_boundary": {
            "s3_object_identity_verified": True,
            "local_bytes_bound_to_s3_readback": True,
            "full_report_acquired": True,
            "official_publisher_origin_authenticated": False,
            "pristine_publisher_byte_identity_claimed": False,
        },
        "document_identity": {"title": "test report"},
        "object_identity": {
            "provider": "AWS_S3",
            "s3_uri": "s3://candidate-test/report.pdf",
            "content_length": len(source_pdf_raw),
        },
        "pdf_readback": {
            "encrypted": False,
            "javascript": False,
            "pages": 1,
            "text_extraction": {
                key: value for key, value in text_row.items() if key != "role"
            },
        },
        "local_capture": {
            "relative_path": source_pdf_relative,
            "sha256": source_pdf_binding["sha256"],
            "bytes": len(source_pdf_raw),
            "regular_file": True,
            "link_count": 1,
        },
    }
    source_identity_binding = _write_json_artifact(
        root,
        "source/s3_original/source_identity_receipt.json",
        source_receipt,
    )
    freeze_rows = [
        _write_bytes_artifact(
            root,
            "manifest.json",
            b'{"candidate":true}\n',
            role="workspace_manifest",
        ),
        _write_bytes_artifact(
            root,
            "source/source_capture_manifest.json",
            b'{"source":"candidate"}\n',
            role="source_capture_manifest",
        ),
        _write_bytes_artifact(
            root,
            "source/source_only_reading.zh-CN.md",
            b"source-only candidate reading\n",
            role="source_only_human_readable_record",
        ),
        _write_bytes_artifact(
            root,
            "candidate_epistemic_shadow_inputs/source-first-overlay.json",
            b'{"authority_effect":"NONE"}\n',
            role="source_first_overlay",
        ),
    ]
    freeze_receipt = {
        "schema_id": STEP2.SOURCE_FREEZE_RECEIPT_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "research_id": research_id,
        "candidate_only": True,
        "signed": False,
        "authority_effect": "NONE",
        "frozen_at_utc": "2026-09-01T00:00:00Z",
        "bindings": freeze_rows,
        "source_boundary": {"formula_uniquely_recoverable": False},
        "reading_process": {"primary_source_only_reader_completed": True},
        "retrieval_boundary": {
            "knowledge_retrieval_started_before_freeze": False,
            "code_or_data_availability_consulted_before_freeze": False,
            "current_factor_failure_or_metrics_consulted_before_freeze": False,
        },
        "outcome_exposure": {
            "current_factor_is_metrics_seen": False,
            "oos_seen": False,
        },
        "source_first_compiler_preflight": {
            "verdict": "PASS",
            "retrieval_executed": False,
        },
    }
    freeze_binding = _write_json_artifact(
        root,
        "candidate_epistemic_shadow_inputs/source-first-freeze-receipt.json",
        freeze_receipt,
    )
    freeze_raw = (
        root / freeze_binding["relative_path"]
    ).read_bytes()
    successor_rows = [
        source_pdf_row,
        {
            "role": "source_identity_receipt",
            "relative_path": source_identity_binding["relative_path"],
            "bytes": (root / source_identity_binding["relative_path"]).stat().st_size,
            "sha256": source_identity_binding["sha256"],
        },
        _write_bytes_artifact(
            root,
            "source/s3_original/original_reading_delta.zh-CN.md",
            b"post-capture reading delta\n",
            role="source_reading_delta",
        ),
        _write_bytes_artifact(
            root,
            "objects/step1/step1_post_a0_measurement_program.zh-CN.md",
            b"post-A0 measurement program\n",
            role="post_a0_measurement_program",
        ),
    ]
    successor_receipt = {
        "schema_id": STEP2.SOURCE_SUCCESSOR_RECEIPT_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "research_id": research_id,
        "candidate_only": True,
        "signed": False,
        "authority_effect": "NONE",
        "created_at_utc": "2026-09-01T00:03:00Z",
        "predecessor": {
            "relative_path": freeze_binding["relative_path"],
            "bytes": len(freeze_raw),
            "sha256": freeze_binding["sha256"],
            "frozen_bytes_modified": False,
        },
        "state_transition": {
            "review_eligible": False,
            "source_reported_outcomes_only": True,
        },
        "successor_bindings": successor_rows,
        "temporal_order": {
            "source_first_freeze_precedes_knowledge_retrieval": True,
            "s3_original_capture_is_not_pre_a0": True,
            "retroactive_prediction_rewrite_allowed": False,
        },
        "operating_boundary": {
            "current_factor_metrics_accessed": False,
            "oos_values_accessed": False,
            "canonical_write": False,
            "promotion": False,
        },
        "semantic_comparison": {"formula_uniquely_recoverable": False},
    }
    successor_binding = _write_json_artifact(
        root,
        "candidate_epistemic_shadow_inputs/source-first-source-successor-receipt-v2.json",
        successor_receipt,
    )
    step1_validation = {
        "report_id": REPORT_ID,
        "result": "PASS",
        "checks": [
            {
                "name": name,
                "ok": True,
                "status": "PASS",
                "severity": "WARN" if name == "information_set_not_illegal" else "BLOCK",
                "error": None,
            }
            for name in STEP2.STEP1_VALIDATION_CHECK_NAMES
        ],
        "errors": [],
        "warnings": [],
    }
    bindings = {
        "source_pdf": source_pdf_binding,
        "source_identity_receipt": source_identity_binding,
        "source_first_freeze_receipt": freeze_binding,
        "source_first_successor_receipt": successor_binding,
        "measurement_program": _write_json_artifact(
            root,
            "objects/step1/measurement_program_candidate_v2.json",
            program,
        ),
        "research_equation": _write_json_artifact(
            root,
            "objects/step1/research_equation_candidate_v1.json",
            equation,
        ),
        "step1_validation": _write_json_artifact(
            root,
            f"objects/validation/step1_validation__{REPORT_ID}.json",
            step1_validation,
        ),
        "branch_parameter_registry": _write_json_artifact(
            root,
            "objects/step2/branch_parameter_registry_candidate_v1.json",
            {
                "schema_id": "candidate_branch_parameter_registry_v1",
                "report_id": REPORT_ID,
                "factor_id": FACTOR_ID,
                "authority_effect": "NONE",
                "branches": [],
            },
        ),
    }
    semantic_alignment = {
        "profile_id": STEP2.DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE,
        "review_status": "PRE_RESULT_CANDIDATE_ALIGNMENT_BOUND",
        "relation": "COMPLEMENTARY_SOURCE_AND_MECHANISM_LATTICE",
        "authority_effect": "NONE",
        "shared_equal_fields": list(STEP2.DUAL_ROUTE_SHARED_EQUAL_FIELDS),
        "dimensions": [
            {
                "ordinal": ordinal,
                "field": field,
                "relation": (
                    STEP2.DUAL_ROUTE_EQUAL_RELATION
                    if raw_specs["primary"].get(field)
                    == raw_specs["challenger"].get(field)
                    else STEP2.DUAL_ROUTE_NONIDENTICAL_RELATION
                ),
                "primary_sha256": STEP2._semantic_value_sha256(
                    raw_specs["primary"].get(field)
                ),
                "challenger_sha256": STEP2._semantic_value_sha256(
                    raw_specs["challenger"].get(field)
                ),
            }
            for ordinal, field in enumerate(STEP2.DUAL_ROUTE_SEMANTIC_FIELDS)
        ],
    }
    aim = {
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "research_id": research_id,
        "source_type": "pdf_report",
        "implementation_mode": "operator",
        "final_factor": {"name": "manifest-bound candidate factor"},
        "mechanism_conditioned_measurement_program": deepcopy(program),
        "research_equation": deepcopy(equation),
        "research_discipline": {
            "mechanism_conditioned_measurement_program": deepcopy(program),
            "research_equation": deepcopy(equation),
            "step1_mathematical_object": "temporary-impact state",
            "target_statistic_hint": "conditional next-session relative return",
            "information_set_hint": "legal-time inputs through close only",
            "initial_return_source_hypothesis": "temporary impact later relaxes",
            "economic_hypothesis": {
                "macro_return_source": "market_structure_arbitrage",
                "second_layer": {
                    "subtype": "temporary price pressure",
                    "expected_counterparty_or_payer": "urgent liquidity demander",
                    "why_they_may_pay": "execution urgency meets finite depth",
                },
                "counterparty_loss_hypothesis": "urgent flow pays temporary impact",
            },
            "math_hypothesis_candidates": [
                {
                    "hypothesis_id": "temporary_impact",
                    "linked_economic_hypothesis": "temporary price pressure",
                    "model_family": "event response",
                    "math_tools": ["marked event kernel"],
                    "observable_estimator": "legal-time event-response estimator",
                    "target_functional": "conditional temporary-impact payoff",
                    "why_suitable": "preserves event and response phase",
                    "falsification_tests": ["matched event-time placebo"],
                    "mathematical_object": "temporary-impact state",
                    "mechanism_equation_or_functional": "impact = flow - resilience",
                }
            ],
            "market_process_thesis": {
                "market_phenomenon": "temporary intraday price pressure",
                "economic_hypothesis": "urgent flow temporarily exhausts depth",
                "return_source_family": "market_structure_arbitrage",
                "payer_or_counterparty": "urgent liquidity demander",
                "why_they_pay": "finite depth and immediacy",
                "what_must_be_true": ["event response later relaxes"],
                "what_would_break_it": ["matched placebo response is identical"],
                "alternative_return_source_tests": [
                    {
                        "alternative_source": "information_advantage",
                        "why_not_primary": "permanent news should not reverse",
                        "discriminating_test": "condition on scheduled news",
                        "expected_signature_if_alternative_true": "continuation",
                    }
                ],
            },
            "primary_mechanism_model_candidates": [
                {
                    "rank": 1,
                    "preferred": True,
                    "selected_model_family": "temporary-impact event model",
                    "why_this_model_fits": "tests impact then relaxation",
                    "why_alternatives_are_less_suitable": [
                        "permanent-news model predicts continuation"
                    ],
                    "mathematical_objects": ["temporary-impact state"],
                }
            ],
            "market_outcome_projection": deepcopy(
                program["market_outcome_projection"]
            ),
            "similar_case_lessons_imported": [
                "candidate-only precedent for event-response identification"
            ],
            "what_must_be_true": ["event response later relaxes"],
            "what_would_break_it": ["no placebo-distinct relaxation"],
        },
        "step2_input_adapter_contract": {
            "contract_version": STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION,
            "kind": STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_KIND,
            "source_type": "pdf_report",
            "report_id": REPORT_ID,
            "factor_id": FACTOR_ID,
            "allow_generic_pdf_fallback": False,
            "required_measurement_program_contract_version": STEP2.MEASUREMENT_PROGRAM_VERSION_V2,
            "require_research_equation": True,
            "input_authority": "CANDIDATE_ONLY",
            "authority_effect": "NONE",
            "source_step1_binding": {
                "profile_id": STEP2.SOURCE_STEP1_BINDING_PROFILE,
                "authority_effect": "NONE",
                "bindings": bindings,
            },
            "semantic_alignment": semantic_alignment,
            "inputs": inputs,
        },
    }
    contract = aim["step2_input_adapter_contract"]
    projection = STEP2._alpha_semantic_subject_projection(
        aim=aim,
        contract=contract,
    )
    review_receipt = {
        "schema_id": STEP2.INDEPENDENT_SEMANTIC_REVIEW_PROFILE,
        "profile_id": STEP2.INDEPENDENT_SEMANTIC_REVIEW_PROFILE,
        "review_id": "independent-semantic-review-test-v1",
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "alpha_semantic_subject_profile": STEP2.ALPHA_SEMANTIC_SUBJECT_PROFILE,
        "alpha_semantic_subject_sha256": STEP2._domain_canonical_sha256(
            STEP2.ALPHA_SEMANTIC_SUBJECT_PROFILE,
            projection,
        ),
        "primary_raw_sha256": inputs["primary"]["sha256"],
        "challenger_raw_sha256": inputs["challenger"]["sha256"],
        "subject_identities": {
            role: bindings[role]["sha256"]
            for role in STEP2.SOURCE_STEP1_BINDING_ROLES_V3
        },
        "exact10_dimensions": [
            {
                "ordinal": ordinal,
                "field": field,
                "relation": (
                    "EQUAL"
                    if raw_specs["primary"].get(field)
                    == raw_specs["challenger"].get(field)
                    else "COMPLEMENTARY"
                ),
                "primary_sha256": STEP2._semantic_value_sha256(
                    raw_specs["primary"].get(field)
                ),
                "challenger_sha256": STEP2._semantic_value_sha256(
                    raw_specs["challenger"].get(field)
                ),
                "rationale": "independent test review of the bound dimension",
                "evidence": [f"bound exact10 field {field}"],
            }
            for ordinal, field in enumerate(STEP2.DUAL_ROUTE_SEMANTIC_FIELDS)
        ],
        "verdict": "GO",
        "p0_count": 0,
        "p1_count": 0,
        "no_result_data_accessed": True,
        "no_oos_accessed": True,
        "reviewer_boundary": {
            "attestation_class": "CANDIDATE_NON_CRYPTOGRAPHIC_DECLARATION_ONLY",
            "independent_from_author": True,
            "independent_from_implementation": True,
            "reviewer_role": "independent_semantic_reviewer",
            "operating_authority_granted": False,
        },
        "authority_effect": "NONE",
    }
    contract["independent_semantic_review"] = _write_json_artifact(
        root,
        "objects/validation/independent_semantic_review_receipt.json",
        review_receipt,
    )
    _write_alpha(root, aim)
    return aim


def _load(root: Path, aim: dict, *, rewrite_alpha: bool = True):
    if rewrite_alpha:
        _write_alpha(root, aim)
    previous = STEP2.FACTORFORGE
    STEP2.FACTORFORGE = root
    try:
        return STEP2.load_manifest_bound_dual_route_pdf_specs(REPORT_ID, aim)
    finally:
        STEP2.FACTORFORGE = previous


def _mutate_review_receipt(root: Path, aim: dict, mutation) -> None:
    binding = aim["step2_input_adapter_contract"][
        "independent_semantic_review"
    ]
    path = root / binding["relative_path"]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    mutation(receipt)
    raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    binding["sha256"] = hashlib.sha256(raw).hexdigest()


def test_absent_contract_preserves_legacy_selection_without_v2_gate(tmp_path: Path) -> None:
    assert STEP2.load_manifest_bound_dual_route_pdf_specs(
        REPORT_ID,
        {"report_id": REPORT_ID, "factor_id": FACTOR_ID},
    ) is None


def test_valid_contract_loads_exact_two_candidate_inputs_and_builds_lineage(tmp_path: Path) -> None:
    aim = _aim(tmp_path)
    loaded = _load(tmp_path, aim)
    assert loaded is not None
    primary, challenger, lineage = loaded

    assert primary["route"] == "primary"
    assert challenger["route"] == "challenger"
    assert lineage["factor_id"] == FACTOR_ID
    assert lineage["report_id"] == REPORT_ID
    assert lineage["input_authority"] == "CANDIDATE_ONLY"
    assert lineage["authority_effect"] == "NONE"
    assert lineage["admission_effect"] == "NONE"
    assert lineage["generic_pdf_fallback_used"] is False
    assert [row["route"] for row in lineage["inputs"]] == [
        "primary",
        "challenger",
    ]
    assert all(row["sha256"] == aim["step2_input_adapter_contract"]["inputs"][row["route"]]["sha256"] for row in lineage["inputs"])
    assert [row["role"] for row in lineage["source_step1_inputs"]] == list(
        STEP2.SOURCE_STEP1_BINDING_ROLES_V3
    )
    assert lineage["alpha_idea_master_raw_sha256"] == hashlib.sha256(
        (
            tmp_path
            / "objects/alpha_idea_master"
            / f"alpha_idea_master__{REPORT_ID}.json"
        ).read_bytes()
    ).hexdigest()
    assert lineage["semantic_alignment_profile"] == (
        STEP2.DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE
    )
    assert lineage["semantic_review_required"] is True
    assert lineage["semantic_review_satisfied"] is True
    assert lineage["independent_semantic_review"]["verdict"] == "GO"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda receipt: receipt.update({"verdict": "REVISE"}), "verdict"),
        (lambda receipt: receipt.update({"p0_count": 1}), "open_findings"),
        (
            lambda receipt: receipt.update({"authority_effect": "FORMAL"}),
            "authority_effect",
        ),
        (
            lambda receipt: receipt["exact10_dimensions"][0].update(
                {"relation": "CONFLICTING"}
            ),
            "unresolved_relation",
        ),
        (
            lambda receipt: receipt["exact10_dimensions"][0].update(
                {"relation": "EQUAL"}
            ),
            "false_equal",
        ),
        (
            lambda receipt: receipt["exact10_dimensions"][1].update(
                {"relation": "COMPLEMENTARY"}
            ),
            "false_non_equal",
        ),
        (
            lambda receipt: receipt["exact10_dimensions"][0].update(
                {"evidence": []}
            ),
            "dimension_evidence",
        ),
        (
            lambda receipt: receipt.update(
                {"alpha_semantic_subject_sha256": "0" * 64}
            ),
            "subject_digest",
        ),
    ],
)
def test_v3_independent_review_receipt_is_closed_and_fail_closed(
    tmp_path: Path,
    mutation,
    reason: str,
) -> None:
    aim = _aim(tmp_path)
    _mutate_review_receipt(tmp_path, aim, mutation)
    with pytest.raises(SystemExit, match=reason):
        _load(tmp_path, aim)


def test_v3_missing_review_binding_blocks(tmp_path: Path) -> None:
    aim = _aim(tmp_path)
    aim["step2_input_adapter_contract"].pop("independent_semantic_review")
    with pytest.raises(SystemExit, match="keys mismatch"):
        _load(tmp_path, aim)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda aim: aim["step2_input_adapter_contract"].update({"extra": True}), "keys mismatch"),
        (lambda aim: aim["step2_input_adapter_contract"].update({"allow_generic_pdf_fallback": True}), "allow_generic_pdf_fallback"),
        (lambda aim: aim["mechanism_conditioned_measurement_program"].update({"contract_version": "factorforge_mechanism_conditioned_measurement_program_v1"}), "measurement-program v2"),
        (lambda aim: aim["research_equation"].update({"equation_text": "different"}), "mirror must equal"),
        (lambda aim: aim["step2_input_adapter_contract"]["inputs"]["primary"].update({"sha256": "0" * 64}), "sha256 mismatch"),
        (lambda aim: aim["step2_input_adapter_contract"]["inputs"]["primary"].update({"relative_path": "objects/validation/*primary*.json"}), "glob syntax"),
    ],
)
def test_contract_is_closed_fail_closed_and_never_requests_generic_fallback(
    tmp_path: Path,
    mutation,
    reason: str,
) -> None:
    aim = _aim(tmp_path)
    mutation(aim)
    with pytest.raises(SystemExit, match=reason):
        _load(tmp_path, aim)


@pytest.mark.parametrize("field,bad_value", [("report_id", "other"), ("factor_id", "other"), ("route", "challenger")])
def test_payload_identity_mismatch_blocks_even_when_rehashed(
    tmp_path: Path,
    field: str,
    bad_value: str,
) -> None:
    aim = _aim(tmp_path)
    bad = _raw_spec("primary")
    bad[field] = bad_value
    relative, digest = _write_raw(tmp_path, "primary", bad)
    row = aim["step2_input_adapter_contract"]["inputs"]["primary"]
    row.update({"relative_path": relative, "sha256": digest})

    with pytest.raises(SystemExit, match=f"primary factor_spec_raw {field} mismatch"):
        _load(tmp_path, aim)


def test_formal_or_unmarked_raw_input_cannot_be_admitted(tmp_path: Path) -> None:
    aim = _aim(tmp_path)
    bad = _raw_spec("primary")
    bad.pop("candidate_only")
    bad["authority_effect"] = "FORMAL"
    relative, digest = _write_raw(tmp_path, "primary", bad)
    aim["step2_input_adapter_contract"]["inputs"]["primary"].update(
        {"relative_path": relative, "sha256": digest}
    )

    with pytest.raises(SystemExit, match="candidate-only marker"):
        _load(tmp_path, aim)


@pytest.mark.parametrize("forbidden_field", ["implementation", "direct_code", "code_hash"])
def test_raw_candidate_schema_structurally_rejects_implementation_fields(
    tmp_path: Path,
    forbidden_field: str,
) -> None:
    aim = _aim(tmp_path)
    bad = _raw_spec("primary")
    bad[forbidden_field] = "caller-selected implementation payload"
    relative, digest = _write_raw(tmp_path, "primary", bad)
    aim["step2_input_adapter_contract"]["inputs"]["primary"].update(
        {"relative_path": relative, "sha256": digest}
    )

    with pytest.raises(SystemExit, match="unexpected fields"):
        _load(tmp_path, aim)


def test_duplicate_json_key_is_rejected_even_when_raw_hash_is_rebound(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    row = aim["step2_input_adapter_contract"]["inputs"]["primary"]
    path = tmp_path / row["relative_path"]
    raw = path.read_bytes().rstrip()[:-1] + b',"route":"challenger"}'
    path.write_bytes(raw)
    row["sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(SystemExit, match="duplicate JSON key"):
        _load(tmp_path, aim)


def test_nonfinite_json_number_is_rejected_even_when_raw_hash_is_rebound(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    row = aim["step2_input_adapter_contract"]["inputs"]["primary"]
    path = tmp_path / row["relative_path"]
    raw = path.read_bytes().rstrip()[:-1] + b',"candidate_status":NaN}'
    path.write_bytes(raw)
    row["sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(SystemExit, match="non-finite JSON number"):
        _load(tmp_path, aim)


def test_bound_source_pdf_tamper_blocks_before_step2_admission(tmp_path: Path) -> None:
    aim = _aim(tmp_path)
    binding = aim["step2_input_adapter_contract"]["source_step1_binding"][
        "bindings"
    ]["source_pdf"]
    (tmp_path / binding["relative_path"]).write_bytes(b"%PDF-1.7\ntampered\n")

    with pytest.raises(SystemExit, match="source_pdf.sha256 mismatch"):
        _load(tmp_path, aim)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("source_first_freeze_receipt", "closed_schema_fields"),
        ("step1_validation", "closed validation shape"),
    ],
)
def test_shallow_self_reported_receipt_cannot_replace_replayable_evidence(
    tmp_path: Path,
    role: str,
    expected: str,
) -> None:
    aim = _aim(tmp_path)
    binding = aim["step2_input_adapter_contract"]["source_step1_binding"][
        "bindings"
    ][role]
    path = tmp_path / binding["relative_path"]
    shallow = {
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "result": "PASS",
        "authority_effect": "NONE",
    }
    raw = json.dumps(shallow).encode("utf-8")
    path.write_bytes(raw)
    binding["sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(SystemExit, match=expected):
        _load(tmp_path, aim)


def test_exact22_caller_pass_rows_cannot_override_recomputed_step1_failure(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    del aim["final_factor"]

    with pytest.raises(SystemExit, match="does not equal pure-validator replay"):
        _load(tmp_path, aim)


@pytest.mark.parametrize("field", ["raw_formula_text", "operators"])
def test_semantic_alignment_blocks_rehashed_route_drift(
    tmp_path: Path,
    field: str,
) -> None:
    aim = _aim(tmp_path)
    bad = _raw_spec("primary")
    bad[field] = (
        "post-freeze formula drift"
        if field == "raw_formula_text"
        else ["caller_selected_operator()"]
    )
    relative, digest = _write_raw(tmp_path, "primary", bad)
    aim["step2_input_adapter_contract"]["inputs"]["primary"].update(
        {"relative_path": relative, "sha256": digest}
    )

    with pytest.raises(SystemExit, match=f"semantic_alignment:primary_digest:{field}"):
        _load(tmp_path, aim)


def test_rehashed_nonidentical_semantics_never_self_authorize_proceed(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    contract = aim["step2_input_adapter_contract"]
    contract["contract_version"] = STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V2
    contract.pop("independent_semantic_review")
    contract["source_step1_binding"]["bindings"].pop(
        "branch_parameter_registry"
    )
    primary = _raw_spec("primary")
    challenger = _raw_spec("challenger")
    primary["raw_formula_text"] = "positive continuation after the pulse"
    challenger["raw_formula_text"] = "negative reversal after the pulse"
    primary["operators"] = ["CONTINUATION"]
    challenger["operators"] = ["REVERSAL"]
    for route, payload in (("primary", primary), ("challenger", challenger)):
        relative, digest = _write_raw(tmp_path, route, payload)
        aim["step2_input_adapter_contract"]["inputs"][route].update(
            {"relative_path": relative, "sha256": digest}
        )
    for row in aim["step2_input_adapter_contract"]["semantic_alignment"][
        "dimensions"
    ]:
        field = row["field"]
        row["primary_sha256"] = STEP2._semantic_value_sha256(primary.get(field))
        row["challenger_sha256"] = STEP2._semantic_value_sha256(
            challenger.get(field)
        )
        row["relation"] = (
            STEP2.DUAL_ROUTE_EQUAL_RELATION
            if primary.get(field) == challenger.get(field)
            else STEP2.DUAL_ROUTE_NONIDENTICAL_RELATION
        )

    loaded = _load(tmp_path, aim)
    assert loaded is not None
    consistency = STEP2.score_consistency(loaded[0], loaded[1], aim)
    assert consistency["consistency_score"] < 0.7
    assert consistency["matches_core_driver"] is False
    assert consistency["semantic_review_required"] is True
    assert consistency["recommendation"] == "independent_semantic_review_required"


def test_symlinked_raw_input_is_rejected_even_when_bytes_and_hash_match(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    row = aim["step2_input_adapter_contract"]["inputs"]["primary"]
    path = tmp_path / row["relative_path"]
    outside = tmp_path / "outside-primary.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)

    with pytest.raises(SystemExit, match="regular non-symlink file"):
        _load(tmp_path, aim)


def test_hardlinked_raw_input_is_rejected_even_when_bytes_and_hash_match(
    tmp_path: Path,
) -> None:
    aim = _aim(tmp_path)
    row = aim["step2_input_adapter_contract"]["inputs"]["primary"]
    path = tmp_path / row["relative_path"]
    outside = tmp_path / "outside-primary.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    os.link(outside, path)

    with pytest.raises(SystemExit, match="hard-linked alias"):
        _load(tmp_path, aim)


def test_ancestor_directory_symlink_is_rejected(tmp_path: Path) -> None:
    aim = _aim(tmp_path)
    validation = tmp_path / "objects/validation"
    real_validation = tmp_path / "objects/validation-real"
    validation.rename(real_validation)
    validation.symlink_to(real_validation, target_is_directory=True)

    with pytest.raises(SystemExit, match="ancestor directories"):
        _load(tmp_path, aim)


def test_primary_and_challenger_same_physical_object_gate_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    real_same = STEP2._same_physical_file

    def fake_same(left: Path, right: Path) -> bool:
        if "factor_spec_raw__" in left.name and "factor_spec_raw__" in right.name:
            return True
        return real_same(left, right)

    monkeypatch.setattr(STEP2, "_same_physical_file", fake_same)
    with pytest.raises(SystemExit, match="distinct physical files"):
        _load(tmp_path, aim)


def test_run_step2_explicit_contract_bypasses_legacy_pdf_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    captured = {}
    monkeypatch.setattr(STEP2, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(STEP2, "load_alpha_idea_master", lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        "load_source_context",
        lambda *args, **kwargs: pytest.fail("legacy source context must not be read"),
    )
    monkeypatch.setattr(
        STEP2,
        "build_primary_spec_from_pdf",
        lambda *args, **kwargs: pytest.fail("generic PDF primary builder must not run"),
    )
    monkeypatch.setattr(
        STEP2,
        "build_challenger_spec",
        lambda *args, **kwargs: pytest.fail("generic PDF challenger builder must not run"),
    )
    monkeypatch.setattr(
        STEP2,
        "score_consistency",
            lambda primary, challenger, _aim, verified_lineage=None: {
            "factor_id": primary["factor_id"],
            "report_id": primary["report_id"],
            "consistency_score": 1.0,
        },
    )

    def fake_master(report_id, _aim, primary, consistency, thesis, source_adapter_lineage=None):
        captured.update(
            {
                "report_id": report_id,
                "primary": primary,
                "consistency": consistency,
                "thesis": thesis,
                "lineage": source_adapter_lineage,
            }
        )
        return {"factor_id": primary["factor_id"]}

    monkeypatch.setattr(STEP2, "build_factor_spec_master", fake_master)
    STEP2.run_step2(REPORT_ID, dry_run=True)

    assert captured["primary"]["raw_formula_text"].startswith("primary")
    assert captured["lineage"]["adapter_kind"] == STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_KIND
    assert captured["consistency"]["source_adapter_lineage"] == captured["lineage"]


def test_v2_nonidentical_semantics_block_before_any_formal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    contract = aim["step2_input_adapter_contract"]
    contract["contract_version"] = STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V2
    contract.pop("independent_semantic_review")
    contract["source_step1_binding"]["bindings"].pop(
        "branch_parameter_registry"
    )
    _write_alpha(tmp_path, aim)
    monkeypatch.setattr(STEP2, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(STEP2, "load_alpha_idea_master", lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        "build_factor_spec_master",
        lambda *args, **kwargs: pytest.fail(
            "master construction must not run before the semantic gate"
        ),
    )
    monkeypatch.setattr(
        STEP2,
        "write_json",
        lambda *args, **kwargs: pytest.fail("no formal write is allowed"),
    )
    with pytest.raises(SystemExit, match="semantic review is required"):
        STEP2.run_step2(REPORT_ID, dry_run=False)


def test_validator_replays_contract_raw_hashes_and_all_lineage_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    loaded = _load(tmp_path, aim)
    assert loaded is not None
    lineage = loaded[2]
    alpha_path = (
        tmp_path
        / "objects/alpha_idea_master"
        / f"alpha_idea_master__{REPORT_ID}.json"
    )
    alpha_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_path.write_text(json.dumps(aim, ensure_ascii=False), encoding="utf-8")
    consistency_path = (
        tmp_path
        / "objects/validation"
        / f"factor_consistency__{REPORT_ID}.json"
    )
    consistency_path.write_text(
        json.dumps(
            {
                "source_adapter_lineage": lineage,
                "semantic_review_required": False,
                "semantic_review_satisfied": True,
                "recommendation": "proceed",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    master = {
        "factor_id": FACTOR_ID,
        "source_metadata": {
            "source_adapter_alpha_raw_sha256": lineage[
                "alpha_idea_master_raw_sha256"
            ],
            "source_adapter_pdf_sha256": next(
                row["sha256"]
                for row in lineage["source_step1_inputs"]
                if row["role"] == "source_pdf"
            ),
        },
        "source_adapter_lineage": deepcopy(lineage),
        "research_contract": {"source_adapter_lineage": deepcopy(lineage)},
        "human_review_required": False,
        "chief_decision": None,
    }
    handoff = {"source_adapter_lineage": deepcopy(lineage)}
    monkeypatch.setattr(VALIDATOR, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(VALIDATOR, "OBJECTS", tmp_path / "objects")

    checks = VALIDATOR.manifest_bound_adapter_lineage_checks(
        master,
        handoff,
        REPORT_ID,
    )
    assert checks
    assert all(item["ok"] for item in checks), checks

    primary_path = tmp_path / aim["step2_input_adapter_contract"]["inputs"]["primary"]["relative_path"]
    primary_path.write_bytes(primary_path.read_bytes() + b"\n")
    tampered = VALIDATOR.manifest_bound_adapter_lineage_checks(
        master,
        handoff,
        REPORT_ID,
    )
    assert any(
        item["name"] == "manifest_bound_adapter_replay"
        and item["status"] == "BLOCK"
        and "sha256 mismatch" in item["error"]
        for item in tampered
    )

    alpha_bytes = alpha_path.read_bytes()
    alpha_alias_source = tmp_path / "alpha-alias-source.json"
    alpha_alias_source.write_bytes(alpha_bytes)
    alpha_path.unlink()
    os.link(alpha_alias_source, alpha_path)
    aliased = VALIDATOR.manifest_bound_adapter_lineage_checks(
        master,
        handoff,
        REPORT_ID,
    )
    assert any(
        item["name"] == "manifest_bound_alpha_master_exists"
        and item["status"] == "BLOCK"
        and "aliased" in item["error"]
        for item in aliased
    )


def test_v2_nonidentical_semantics_cannot_pass_formal_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    contract = aim["step2_input_adapter_contract"]
    contract["contract_version"] = STEP2.MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V2
    contract.pop("independent_semantic_review")
    contract["source_step1_binding"]["bindings"].pop(
        "branch_parameter_registry"
    )
    loaded = _load(tmp_path, aim)
    assert loaded is not None
    lineage = loaded[2]
    consistency = STEP2.score_consistency(
        loaded[0], loaded[1], aim, verified_lineage=lineage
    )
    consistency["source_adapter_lineage"] = lineage
    consistency_path = (
        tmp_path
        / "objects/validation"
        / f"factor_consistency__{REPORT_ID}.json"
    )
    consistency_path.write_text(json.dumps(consistency), encoding="utf-8")
    master = {
        "factor_id": FACTOR_ID,
        "source_metadata": {
            "source_adapter_alpha_raw_sha256": lineage[
                "alpha_idea_master_raw_sha256"
            ],
            "source_adapter_pdf_sha256": next(
                row["sha256"]
                for row in lineage["source_step1_inputs"]
                if row["role"] == "source_pdf"
            ),
        },
        "source_adapter_lineage": deepcopy(lineage),
        "research_contract": {"source_adapter_lineage": deepcopy(lineage)},
        "human_review_required": True,
        "chief_decision": "semantic review required",
    }
    handoff = {"source_adapter_lineage": deepcopy(lineage)}
    monkeypatch.setattr(VALIDATOR, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(VALIDATOR, "OBJECTS", tmp_path / "objects")
    checks = VALIDATOR.manifest_bound_adapter_lineage_checks(
        master, handoff, REPORT_ID
    )
    assert any(
        row["name"] == "manifest_bound_semantic_review_gate_satisfied"
        and row["status"] == "BLOCK"
        for row in checks
    )


def test_validator_cannot_treat_stripped_lineage_as_legacy_when_contract_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _aim(tmp_path)
    monkeypatch.setattr(VALIDATOR, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(VALIDATOR, "OBJECTS", tmp_path / "objects")

    checks = VALIDATOR.manifest_bound_adapter_lineage_checks(
        {"factor_id": FACTOR_ID, "research_contract": {}},
        {},
        REPORT_ID,
    )

    assert checks
    assert any(
        item["name"] == "manifest_bound_lineage_all_output_copies_present"
        and item["status"] == "BLOCK"
        for item in checks
    )


def test_validator_blocks_stripped_lineage_when_alpha_is_missing_but_projection_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aim = _aim(tmp_path)
    loaded = _load(tmp_path, aim)
    assert loaded is not None
    lineage = loaded[2]
    alpha_path = (
        tmp_path
        / "objects/alpha_idea_master"
        / f"alpha_idea_master__{REPORT_ID}.json"
    )
    alpha_path.unlink()
    master = {
        "factor_id": FACTOR_ID,
        "source_metadata": {
            "source_adapter_alpha_raw_sha256": lineage[
                "alpha_idea_master_raw_sha256"
            ],
            "source_adapter_pdf_sha256": next(
                row["sha256"]
                for row in lineage["source_step1_inputs"]
                if row["role"] == "source_pdf"
            ),
        },
        "research_contract": {},
    }
    monkeypatch.setattr(VALIDATOR, "FACTORFORGE", tmp_path)
    monkeypatch.setattr(VALIDATOR, "OBJECTS", tmp_path / "objects")

    checks = VALIDATOR.manifest_bound_adapter_lineage_checks(
        master,
        {},
        REPORT_ID,
    )

    assert len(checks) == 1
    assert checks[0]["name"] == (
        "manifest_bound_lineage_stripped_with_alpha_unavailable"
    )
    assert checks[0]["status"] == "BLOCK"
