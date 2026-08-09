#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.artifact_identity import build_spec_hash
from factor_factory.mechanism_math.classifier import build_mechanism_math_contract
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract
from factor_factory.measurement_program import (
    IMPLEMENTATION_ROUTES,
    MEASUREMENT_PROGRAM_VERSION,
    selected_measurement_model,
    validate_measurement_program,
)

CONTRACT_VERSION = "factorforge_mechanism_math_contract_v1"
TOKEN_LEGACY_CONFIRMATION_REQUIRED = "BLOCK_MECHANISM_MATH_BACKFILL_LEGACY_CONFIRMATION_REQUIRED"
TOKEN_CURRENT_PROGRAM_PRESENT = "BLOCK_MECHANISM_MATH_BACKFILL_CURRENT_PROGRAM_PRESENT"
HANDOFF_NAMES = [
    "handoff_to_step3",
    "handoff_to_step5",
    "handoff_to_step6",
]
PRESERVED_IDENTITY_KEYS = [
    "spec_hash",
    "formula_hash",
    "run_id",
    "branch_id",
    "code_hash",
    "code_contract_hash",
    "custom_block_hash",
    "hybrid_hash",
]


class BackfillBlock(RuntimeError):
    def __init__(self, token: str, payload: dict[str, Any]):
        super().__init__(token)
        self.token = token
        self.payload = payload


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_factorforge_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    if os.getenv("FACTORFORGE_ROOT"):
        return Path(os.environ["FACTORFORGE_ROOT"]).expanduser().resolve()
    return REPO_ROOT


def identity_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("artifact_identity") or {}
    out = {
        "top_level_spec_hash": payload.get("spec_hash"),
    }
    for key in PRESERVED_IDENTITY_KEYS:
        out[f"artifact_identity.{key}"] = identity.get(key)
    return out


def compare_identity(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        checks[key] = {
            "before": before_value,
            "after": after_value,
            "preserved": before_value == after_value,
        }
    return checks


def canonical_contract(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def declared_knowledge_node_ids(program: dict[str, Any]) -> set[str]:
    implementation = program.get("implementation") or {}
    return {
        str(node_id)
        for component in implementation.get("components") or []
        if isinstance(component, dict)
        for node_id in component.get("knowledge_node_ids") or []
        if str(node_id).strip()
    }


def validate_backfill_measurement_program(program: Any) -> list[str]:
    if not isinstance(program, dict):
        return ["measurement_program"]
    return validate_measurement_program(
        program,
        available_knowledge_node_ids=declared_knowledge_node_ids(program),
        require_web_executable=False,
    )


def build_legacy_measurement_program(
    spec: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Build a conservative bridge; Step6 must still re-author the research view."""
    canonical = spec.get("canonical_spec") or {}
    identity = spec.get("artifact_identity") or {}
    model_family = str(contract.get("model_family") or "mechanism_specific_model")
    mathematical_object = str(
        contract.get("state_or_object") or "formula_defined_mechanism_state"
    )
    target_functional = str(
        contract.get("target_functional")
        or "expected after-cost long-side payoff conditional on the mechanism state"
    )
    mechanism_equation = str(
        contract.get("process_hypothesis")
        or contract.get("economic_mechanism")
        or "the declared mechanism state changes the conditional payoff distribution"
    )
    formula_text = str(
        canonical.get("formula_text")
        or spec.get("formula_text")
        or contract.get("observable_estimator")
        or contract.get("factor_as_estimator")
        or "legacy implementation binding"
    )
    observation_mapping = str(
        contract.get("factor_as_estimator")
        or contract.get("observable_estimator")
        or formula_text
    )
    economic_implication = str(
        contract.get("economic_mechanism")
        or "the factor estimates the declared economic mechanism state"
    )
    necessary_conditions = [
        str(item)
        for item in contract.get("necessary_conditions") or []
        if str(item).strip()
    ]
    falsification_tests = [
        str(item)
        for item in contract.get("falsification_tests") or []
        if str(item).strip()
    ]
    mechanism_falsifiers = [
        str(item)
        for item in contract.get("mechanism_falsification_tests") or []
        if str(item).strip()
    ]
    decisive_test = (
        mechanism_falsifiers or falsification_tests or [
            "reject if the declared mechanism does not discriminate future after-cost long-side payoff"
        ]
    )[0]
    identifiability_condition = (
        necessary_conditions
        or ["the observation mapping must distinguish the mechanism from alias and null models"]
    )[0]
    market_projection = (
        "project the selected mathematical object into the declared future "
        "after-cost conditional long-side payoff"
    )

    tool_candidates = [
        str(item)
        for item in contract.get("math_toolkits") or []
        if str(item).strip()
    ]
    if model_family not in tool_candidates:
        tool_candidates.insert(0, model_family)
    if len(tool_candidates) < 2:
        tool_candidates.append("model_comparison_and_identification")
    tool_candidates = list(dict.fromkeys(tool_candidates))
    rejected_tool = (
        "valuation_identity"
        if "stochastic" in model_family
        else "stochastic_process"
    )
    if rejected_tool in tool_candidates:
        rejected_tool = "unconditioned_operator_search"

    alternative_families = {
        "valuation_identity": "cash_flow_or_accounting_quality_alternative",
        "price_volume_microstructure": "liquidity_or_attention_alternative",
        "stochastic_process": "behavioral_or_risk_compensation_alternative",
        "signal_processing": "latent_state_or_structural_break_alternative",
    }
    alternative_family = alternative_families.get(
        model_family, "competing_economic_mechanism"
    )
    observable_inputs = [
        str(item)
        for item in contract.get("observable_inputs") or []
        if str(item).strip()
    ] or ["legacy_factor_inputs"]
    implementation_mode = str(
        identity.get("implementation_mode")
        or spec.get("implementation_mode")
        or "operator"
    )
    route = implementation_mode if implementation_mode in IMPLEMENTATION_ROUTES else "operator"
    information_set = contract.get("information_set") or {}
    filtration = str(
        information_set.get("filtration")
        if isinstance(information_set, dict)
        else information_set
    )
    if not filtration or filtration == "None":
        filtration = "information available at the declared factor timestamp"
    metric_signature = contract.get("expected_metric_signature") or {}
    metric_signature_text = (
        "; ".join(f"{key}={value}" for key, value in metric_signature.items())
        if isinstance(metric_signature, dict) and metric_signature
        else "positive after-cost long-side evidence with horizon-consistent turnover"
    )
    primary = {
        "candidate_id": "legacy_primary_mechanism",
        "candidate_role": "primary",
        "model_family": model_family,
        "mathematical_object": mathematical_object,
        "mechanism_equation_or_functional": mechanism_equation,
        "target_functional": target_functional,
        "market_outcome_projection": market_projection,
        "observation_mapping": observation_mapping,
        "economic_implication": economic_implication,
        "identifiability_condition": identifiability_condition,
        "decisive_test": decisive_test,
        "selected": True,
    }
    alternative = {
        "candidate_id": "legacy_mechanism_alternative",
        "candidate_role": "mechanism_alternative",
        "model_family": alternative_family,
        "mathematical_object": f"alternative explanation for {mathematical_object}",
        "mechanism_equation_or_functional": (
            "an alternative economic mechanism explains the same observables "
            "without the selected primary state"
        ),
        "target_functional": target_functional,
        "market_outcome_projection": "project the alternative mechanism into the same future payoff target",
        "observation_mapping": observation_mapping,
        "economic_implication": "the observed relation belongs to a distinct payer, risk, or information channel",
        "identifiability_condition": "the alternative must predict a different ablation or regime signature",
        "decisive_test": "compare mechanism-specific component and regime signatures against the primary model",
        "selected": False,
    }
    null_alias = {
        "candidate_id": "legacy_null_or_alias",
        "candidate_role": "null_alias",
        "model_family": "measurement_alias_or_noise",
        "mathematical_object": "nuisance exposure or sampling artifact",
        "mechanism_equation_or_functional": "factor = nuisance(observables) + measurement noise",
        "target_functional": target_functional,
        "market_outcome_projection": "no stable after-cost conditional payoff remains after controls and ablations",
        "observation_mapping": observation_mapping,
        "economic_implication": "the factor has no distinct compensated or behavioral mechanism",
        "identifiability_condition": "the signal must survive controls, ablations, OOS evidence, and costs",
        "decisive_test": "reject the primary model if nuisance controls or component ablation eliminate the payoff signature",
        "selected": False,
    }
    selected_audit = {
        "audit_family": "information_set_legality",
        "rationale": "legacy migration must preserve the original legal information boundary",
        "audit_record": filtration,
        "falsifier": "any future information dependence invalidates the measurement program",
    }
    rejected_audit_family = (
        "stochastic_process_diagnostics"
        if "stochastic" not in model_family
        else "valuation_identity_audit"
    )
    binding_role = "full_formula" if route == "operator" else "component"
    return {
        "contract_version": MEASUREMENT_PROGRAM_VERSION,
        "authority_order": [
            "economic_hypothesis",
            "open_math_tool_selection",
            "competing_model_selection",
            "primary_math_mechanism",
            "market_outcome_projection",
            "applicable_audits",
            "observation_equation",
            "measurement_program",
            "data_and_implementation",
            "empirical_falsification",
        ],
        "knowledge_role": {
            "authority": "advisory_prior_and_counterexample_only",
            "uses": ["candidate_model_prior", "counterexample", "tool_candidate"],
            "cannot_override": [
                "selected_estimand",
                "selected_math_mechanism",
                "information_set",
                "falsification_result",
            ],
            "conflict_resolution": "the economic hypothesis and mathematical mechanism prevail over legacy or knowledge priors",
        },
        "math_tool_selection": {
            "search_space_policy": "open_and_mechanism_conditioned",
            "candidate_tool_families": tool_candidates,
            "selected_tool_families": tool_candidates,
            "selection_rationale": (
                "legacy evidence selects only the tools implied by the existing economic mechanism and formula structure"
            ),
            "rejected_tool_families": [{
                "tool_family": rejected_tool,
                "reason": "not selected automatically because this legacy mechanism does not establish that tool family as necessary",
            }],
            "composition_or_new_object_allowed": True,
            "operator_availability_must_not_decide": True,
        },
        "model_selection": {
            "selection_target": target_functional,
            "candidate_models": [primary, alternative, null_alias],
            "selection_argument": (
                "the primary model is inherited conservatively from the validated legacy mechanism contract and remains subject to current-agent review"
            ),
            "rejected_model_reason": (
                "alternative and null models remain live falsifiers until component, regime, OOS, and after-cost evidence discriminate them"
            ),
        },
        "market_outcome_projection": {
            "role": "terminal_tradeable_quantity_bridge_not_core_model_restriction",
            "projection_kind": "conditional_after_cost_long_side_payoff",
            "source_math_object": mathematical_object,
            "traded_quantity": "future after-cost long-side return at the declared horizon",
            "affected_payoff_or_distribution_terms": [target_functional],
            "projection_equation_or_map": market_projection,
            "link_to_observation_equation": observation_mapping,
            "falsifier": decisive_test,
        },
        "applicable_audits": {
            "selection_rule": "apply only audits justified by the selected legacy mechanism; current-agent review may revise this set",
            "selected": [selected_audit],
            "rejected": [{
                "audit_family": rejected_audit_family,
                "reason": "not universally required for the selected mechanism family",
            }],
        },
        "observation_and_estimation": {
            "estimand": target_functional,
            "observation_map": observation_mapping,
            "estimator": formula_text,
            "identification_assumptions": [
                identifiability_condition,
                "the observation mapping is not merely an alias for the alternative or null model",
            ],
            "bias_variance_and_noise": "legacy estimator bias, variance, and sampling noise require explicit current-agent and empirical review",
            "legal_information_time": filtration,
            "data_construction_is_hypothesis_conditioned": True,
        },
        "public_derivation_record": {
            "record_type": "auditable_summary_not_private_chain_of_thought",
            "definitions": [f"selected object: {mathematical_object}"],
            "assumptions": [
                identifiability_condition,
                "the legacy formula and code lineage are preserved without claiming new proof",
            ],
            "key_derivation_steps": [
                "recover the economic mechanism and mathematical object from the validated legacy contract",
                "freeze the estimand and compare primary, alternative, and null explanations",
                "bind the preserved implementation to the observation map and preregister falsifiers",
            ],
            "identification_gaps": ["current-agent review must re-establish mechanism discrimination before revision or promotion"],
            "approximations": ["the bridge reuses legacy public contract fields and does not reconstruct private reasoning"],
            "overclaim_guard": "migration compatibility is not mechanism proof, empirical acceptance, or promotion authority",
        },
        "implementation": {
            "route": route,
            "web_execution_status": (
                "trusted_formula_ir_execution"
                if route == "operator"
                else "model_only_requires_trusted_isolated_code_harness"
            ),
            "why_this_route": "preserve the legacy implementation mode and immutable formula or code lineage",
            "components": [{
                "component_id": "legacy_full_implementation",
                "binding_role": binding_role,
                "economic_claim": economic_implication,
                "math_term_or_functional": mechanism_equation,
                "mechanism_role": "observable estimator of the selected mathematical object",
                "observable_or_input": ", ".join(observable_inputs),
                "input_fields": observable_inputs,
                "transformation_or_estimator": observation_mapping,
                "implementation_binding": formula_text,
                "input_measurement_semantics": "legacy input semantics preserved from the factor specification",
                "output_measurement_semantics": f"estimator of {mathematical_object}",
                "information_time": filtration,
                "preserved_information": "original formula or code lineage and declared economic state",
                "discarded_information": "no new data transformation is introduced by migration",
                "expected_metric_signature": metric_signature_text,
                "ablation_test": "remove or neutralize the legacy implementation component and test loss of the predicted signature",
                "falsifier": decisive_test,
                "knowledge_node_ids": [],
            }],
        },
        "deterministic_validation_plan": {
            "schema_and_measurement_checks": ["validate program schema, identity, and exact propagation through Step5"],
            "future_mutation_invariance": "all legacy inputs obey the original declared information timestamp",
            "limiting_case_oracles": ["constant or degenerate inputs must not create a supported economic mechanism"],
            "ablation_and_alias_tests": ["compare primary component evidence with alternative and null models"],
            "implementation_parity": "formula or code hash remains unchanged by the migration bridge",
        },
        "search_policy": {
            "invariant_estimand": target_functional,
            "allowed_model_or_estimator_variations": ["current-agent may replace the bridge only through explicit model comparison and falsification"],
            "forbidden_shortcuts": [
                "choose a story because an operator already exists",
                "change the estimand because an available field is convenient",
                "accept in-sample fitness without mechanism discrimination",
            ],
            "objective_vector": [
                "mechanism_consistency",
                "identifiability",
                "out_of_sample_evidence",
                "after_cost_long_side_value",
            ],
            "stop_rules": ["stop if the selected mechanism cannot beat the alternative or null model under preregistered tests"],
        },
    }


def assert_factor_spec_preserved(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    canonical_before: dict[str, Any],
    implementation_before: dict[str, Any],
    research_before: dict[str, Any],
) -> dict[str, Any]:
    hash_before = build_spec_hash(before)
    hash_after = build_spec_hash(after)
    checks = compare_identity(identity_snapshot(before), identity_snapshot(after))
    checks["build_spec_hash"] = {
        "before": hash_before,
        "after": hash_after,
        "preserved": hash_before == hash_after,
    }
    checks["canonical_spec"] = {
        "preserved": canonical_before == (after.get("canonical_spec") or {}),
    }
    checks["implementation_contract"] = {
        "preserved": implementation_before == (after.get("implementation_contract") or {}),
    }
    checks["research_contract"] = {
        "preserved": research_before == (after.get("research_contract") or {}),
    }
    failed = [key for key, item in checks.items() if item.get("preserved") is not True]
    if failed:
        raise RuntimeError(f"backfill would modify protected lineage fields: {failed}")
    return checks


def prepare_handoff_update(
    path: Path,
    contract: dict[str, Any],
    measurement_program: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    before = load_json(path)
    after = copy.deepcopy(before)
    updated = False
    existing = before.get("mechanism_math_contract")
    if isinstance(existing, dict) and existing:
        failures = validate_mechanism_math_contract(existing)
        if failures:
            raise BackfillBlock(
                "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID_HANDOFF",
                {
                    "path": str(path),
                    "failures": failures,
                },
            )
        if canonical_contract(existing) != canonical_contract(contract):
            raise BackfillBlock(
                "BLOCK_MECHANISM_MATH_BACKFILL_HANDOFF_CONFLICT",
                {
                    "path": str(path),
                    "reason": "valid existing handoff mechanism_math_contract differs from target contract",
                    "existing_math_model_status": existing.get("math_model_status"),
                    "existing_model_family": existing.get("model_family"),
                    "target_math_model_status": contract.get("math_model_status"),
                    "target_model_family": contract.get("model_family"),
                },
            )
    else:
        after["mechanism_math_contract"] = contract
        updated = True

    existing_program = before.get("mechanism_conditioned_measurement_program")
    if isinstance(existing_program, dict) and existing_program:
        failures = validate_backfill_measurement_program(existing_program)
        if failures:
            raise BackfillBlock(
                "BLOCK_MEASUREMENT_PROGRAM_BACKFILL_EXISTING_INVALID_HANDOFF",
                {"path": str(path), "failures": failures},
            )
        if canonical_contract(existing_program) != canonical_contract(measurement_program):
            raise BackfillBlock(
                "BLOCK_MEASUREMENT_PROGRAM_BACKFILL_HANDOFF_CONFLICT",
                {
                    "path": str(path),
                    "reason": "valid existing handoff measurement program differs from target program",
                },
            )
    else:
        after["mechanism_conditioned_measurement_program"] = measurement_program
        updated = True

    before_identity = identity_snapshot(before)
    after_identity = identity_snapshot(after)
    identity_checks = compare_identity(before_identity, after_identity)
    failed = [key for key, item in identity_checks.items() if item.get("preserved") is not True]
    if failed:
        raise RuntimeError(f"backfill would modify protected handoff identity fields for {path}: {failed}")
    return {
        "path": str(path),
        "updated": updated,
        "reason": "backfilled_missing_contracts" if updated else "existing_valid_contracts_match",
        "payload": after,
        "identity_preservation": identity_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill explicitly confirmed legacy Factor Forge Step2 artifacts with "
            "migration-only mechanism and measurement contracts without changing "
            "canonical formula/code lineage."
        )
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--factorforge-root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--confirm-legacy-artifact",
        action="store_true",
        help="Explicitly confirm that a missing measurement program is a legacy migration target.",
    )
    args = parser.parse_args()

    root = resolve_factorforge_root(args.factorforge_root)
    objects = root / "objects"
    spec_path = objects / "factor_spec_master" / f"factor_spec_master__{args.report_id}.json"
    if not spec_path.exists():
        print(f"BLOCK_MECHANISM_MATH_BACKFILL_INPUT_MISSING: {spec_path}", file=sys.stderr)
        raise SystemExit(1)

    before = load_json(spec_path)
    after = copy.deepcopy(before)
    canonical_before = copy.deepcopy(before.get("canonical_spec") or {})
    implementation_before = copy.deepcopy(before.get("implementation_contract") or {})
    research_before = copy.deepcopy(before.get("research_contract") or {})

    existing = before.get("mechanism_math_contract")
    existing_program = before.get("mechanism_conditioned_measurement_program")
    contract_present = isinstance(existing, dict) and bool(existing)
    program_present = isinstance(existing_program, dict) and bool(existing_program)
    if not contract_present and program_present:
        print(
            TOKEN_CURRENT_PROGRAM_PRESENT
            + ": current measurement program is authoritative; do not synthesize a legacy mechanism contract",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if (not contract_present or not program_present) and not args.confirm_legacy_artifact:
        print(
            TOKEN_LEGACY_CONFIRMATION_REQUIRED
            + ": pass --confirm-legacy-artifact only after verifying the artifact predates the measurement-program contract",
            file=sys.stderr,
        )
        raise SystemExit(1)

    contract_added = False
    if isinstance(existing, dict) and existing:
        failures = validate_mechanism_math_contract(existing)
        if failures:
            print(
                "BLOCK_MECHANISM_MATH_BACKFILL_EXISTING_INVALID: "
                + json.dumps(failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        contract = existing
    else:
        contract = build_mechanism_math_contract(before)
        failures = validate_mechanism_math_contract(contract)
        if failures:
            print(
                "BLOCK_MECHANISM_MATH_BACKFILL_CONTRACT_INVALID: "
                + json.dumps(failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        after["mechanism_math_contract"] = contract
        contract_added = True

    program_added = False
    if isinstance(existing_program, dict) and existing_program:
        program_failures = validate_backfill_measurement_program(existing_program)
        if program_failures:
            print(
                "BLOCK_MEASUREMENT_PROGRAM_BACKFILL_EXISTING_INVALID: "
                + json.dumps(program_failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        selected_model = selected_measurement_model(existing_program)
        if (
            selected_model
            and selected_model.get("model_family") != contract.get("model_family")
        ):
            print(
                "BLOCK_MEASUREMENT_PROGRAM_BACKFILL_MODEL_CONFLICT: "
                + json.dumps(
                    {
                        "measurement_program_model_family": selected_model.get("model_family"),
                        "mechanism_math_model_family": contract.get("model_family"),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)
        measurement_program = existing_program
    else:
        measurement_program = build_legacy_measurement_program(after, contract)
        program_failures = validate_backfill_measurement_program(measurement_program)
        if program_failures:
            print(
                "BLOCK_MEASUREMENT_PROGRAM_BACKFILL_INVALID: "
                + json.dumps(program_failures, ensure_ascii=False),
                file=sys.stderr,
            )
            raise SystemExit(1)
        after["mechanism_conditioned_measurement_program"] = measurement_program
        program_added = True

    changed = contract_added or program_added
    status = (
        "dry_run"
        if args.dry_run and changed
        else "backfilled"
        if changed
        else "already_present"
    )

    try:
        preservation = assert_factor_spec_preserved(
            before=before,
            after=after,
            canonical_before=canonical_before,
            implementation_before=implementation_before,
            research_before=research_before,
        )

        handoff_updates: list[dict[str, Any]] = []
        prepared_handoffs: list[dict[str, Any]] = []
        for handoff_name in HANDOFF_NAMES:
            handoff_path = objects / "handoff" / f"{handoff_name}__{args.report_id}.json"
            update = prepare_handoff_update(
                handoff_path,
                contract,
                measurement_program,
            )
            if update:
                prepared_handoffs.append(update)
                handoff_updates.append({key: value for key, value in update.items() if key != "payload"})
    except BackfillBlock as exc:
        print(
            exc.token + ": " + json.dumps(exc.payload, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1)

    updated_paths: list[str] = []
    if not args.dry_run and changed:
        write_json(spec_path, after)
        updated_paths.append(str(spec_path))

    if not args.dry_run:
        for update in prepared_handoffs:
            if update.get("updated"):
                path = Path(str(update["path"]))
                write_json(path, update["payload"])
                updated_paths.append(str(path))

    summary = {
        "status": status,
        "report_id": args.report_id,
        "factorforge_root": str(root),
        "factor_spec_path": str(spec_path),
        "contract_version": contract.get("contract_version") or CONTRACT_VERSION,
        "math_model_status": contract.get("math_model_status"),
        "model_family": contract.get("model_family"),
        "under_specified_reason": contract.get("under_specified_reason"),
        "measurement_program_contract_version": measurement_program.get("contract_version"),
        "measurement_program_selected_model_family": (
            selected_measurement_model(measurement_program).get("model_family")
        ),
        "measurement_program_migration_only": program_added,
        "lineage_preservation": preservation,
        "handoff_updates": handoff_updates,
        "updated_paths": updated_paths,
        "created_at_utc": utc_now(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
