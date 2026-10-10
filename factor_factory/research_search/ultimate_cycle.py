"""B3 bridge from reviewed Step2 scope to the existing native search lifecycle.

This module is deliberately an adapter. Candidate registration, reservations,
pending states, native Step3/4/5 execution, metrics, costs, and immutable
feedback remain owned by the existing controller, ledger, executor, and native
collector. The bridge never turns a pending ticket into a score and never turns
an implementation metric into a mechanism verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, Mapping

from factor_factory.measurement_program import validate_measurement_program
from factor_factory.formula.parser import parse_formula

from .contracts import SearchError, canonical, digest, file_ref, validate_context
from .controller import ResearchSearchController
from .executor import write_once
from .generator import (
    ExpressionCandidate, GenerationTrace, crossover_candidates, generate_population,
    mutate_candidate,
)
from .induction import ForwardInductionRecord, InductionScope, FieldSpec, SemanticType
from .native import validate_preparation, validate_request
from .typed_ast import ASTNode, infer_type, require_response_family

CAUSAL_AFFINE_VARIATIONS = (
    "causal affine combinations of reviewed inputs",
    "constant scaling within the reviewed units",
    "causal delay over reviewed windows",
    "causal trailing mean over reviewed windows",
)


@dataclass(frozen=True)
class Step2GrammarDeclaration:
    response_family: str
    mathematical_object: str
    observation_map: str
    allowed_fields: tuple[FieldSpec, ...]
    output_type: SemanticType
    allowed_operators: tuple[str, ...]
    allowed_constants: tuple[float, ...]
    allowed_windows: tuple[int, ...]
    max_depth: int
    missing_value_policy: str
    numeric_domain: str
    allowed_variation_evidence: tuple[str, ...]
    units_evidence: str
    information_time_evidence: str
    missing_zero_evidence: str
    parent_induction_id: str | None = None
    parent_delta: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewedStep2Scope:
    scope: InductionScope
    context_hash: str
    candidate_hash: str
    accepted_semantics: dict[str, str]
    readiness_ref: dict[str, str]
    review_binding_hash: str


def grammar_declaration_payload(declaration: Step2GrammarDeclaration) -> dict[str, Any]:
    """Canonical machine-readable content that must live in the reviewed spec."""
    return {
        "response_family": declaration.response_family,
        "mathematical_object": declaration.mathematical_object,
        "observation_map": declaration.observation_map,
        "allowed_fields": [
            {"name": row.name, "semantic_type": row.semantic_type.payload()}
            for row in declaration.allowed_fields
        ],
        "output_type": declaration.output_type.payload(),
        "allowed_operators": list(declaration.allowed_operators),
        "allowed_constants": list(declaration.allowed_constants),
        "allowed_windows": list(declaration.allowed_windows),
        "max_depth": declaration.max_depth,
        "missing_value_policy": declaration.missing_value_policy,
        "numeric_domain": declaration.numeric_domain,
        "allowed_variation_evidence": list(declaration.allowed_variation_evidence),
        "units_evidence": declaration.units_evidence,
        "information_time_evidence": declaration.information_time_evidence,
        "missing_zero_evidence": declaration.missing_zero_evidence,
        "parent_induction_id": declaration.parent_induction_id,
        "parent_delta": list(declaration.parent_delta),
    }


def _expected_lineage(context: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "base_context_hash": digest(context),
        "base_source_refs": context["source_refs"],
        "candidate_hash": proposal["candidate_hash"],
        "parent_candidate_hash": proposal["parent_candidate_hash"],
        "mutation_class": proposal["mutation_class"],
    }


def bind_reviewed_step2_scope(
    context: Mapping[str, Any], proposal: Mapping[str, Any], ticket: Mapping[str, Any],
    declaration: Step2GrammarDeclaration,
) -> ReviewedStep2Scope:
    """Project one already-reviewed native request into the first AST family.

    The declaration supplies the machine-readable grammar, but every economic
    and observation identity plus every allowed-variation statement must match
    the Step2 measurement program already bound by the validated request.
    """
    c = validate_context(context)
    if (ticket.get("context_hash") != digest(c)
            or ticket.get("candidate_hash") != proposal.get("candidate_hash")):
        raise SearchError("reviewed Step2 binding ticket identity mismatch")
    request = ticket.get("native_request")
    if not isinstance(request, Mapping):
        raise SearchError("reviewed Step2 binding requires a prepared native request")
    r = validate_request(c, proposal, request)
    validate_preparation(r, ticket)
    readiness = _bound_json(r["readiness_ref"])
    source_spec = _bound_json(c["source_refs"]["step2_spec"])
    measurement_object = _bound_json(c["source_refs"]["measurement_program"])
    base_program = measurement_object.get("mechanism_conditioned_measurement_program", measurement_object)
    source_program = source_spec.get("mechanism_conditioned_measurement_program")
    if source_program != base_program:
        raise SearchError("Step2 spec and measurement-program source are not identical")
    reviewed_spec = _bound_json(r["spec_ref"])
    if reviewed_spec.get("research_search_grammar_declaration") != grammar_declaration_payload(declaration):
        raise SearchError("AST grammar differs from the code-reviewed Step2 spec")
    if reviewed_spec.get("research_search_lineage") != _expected_lineage(c, proposal):
        raise SearchError("reviewed Step2 spec lineage differs from candidate/source lineage")
    program = reviewed_spec.get("mechanism_conditioned_measurement_program")
    if not isinstance(program, Mapping):
        raise SearchError("code-reviewed Step2 spec lacks a measurement program")
    if proposal["mutation_class"] == "implementation_equivalent" and program != base_program:
        raise SearchError("implementation-equivalent reviewed spec differs from base Step2 program")
    reasons = validate_measurement_program(program, require_web_executable=False)
    if reasons:
        raise SearchError("reviewed Step2 measurement program is invalid: " + ";".join(reasons))
    selected = [row for row in program["model_selection"]["candidate_models"] if row.get("selected") is True]
    if len(selected) != 1:
        raise SearchError("Step2 must select exactly one mathematical object")
    model = selected[0]
    if declaration.mathematical_object != model.get("mechanism_equation_or_functional"):
        raise SearchError("search mathematical object differs from reviewed Step2")
    if declaration.observation_map != program["observation_and_estimation"].get("observation_map"):
        raise SearchError("search observation map differs from reviewed Step2")
    semantics = proposal["semantics"]
    if (semantics["mathematical_object"] != declaration.mathematical_object
            or semantics["observation_map"] != declaration.observation_map):
        raise SearchError("reviewed Step2 math/observation differs from proposal semantics")
    if declaration.response_family != "causal_affine_response_estimator":
        raise SearchError("only the implemented causal-affine response family is supported")
    if declaration.allowed_variation_evidence != CAUSAL_AFFINE_VARIATIONS:
        raise SearchError("causal-affine grammar requires the complete reviewed variation set")
    reviewed_variations = set(program["search_policy"].get("allowed_model_or_estimator_variations") or [])
    if (not declaration.allowed_variation_evidence
            or not set(declaration.allowed_variation_evidence).issubset(reviewed_variations)):
        raise SearchError("AST grammar is not explicitly admitted by reviewed Step2 variations")
    if (declaration.units_evidence != semantics["units"]
            or declaration.information_time_evidence != semantics["information_time"]
            or declaration.missing_zero_evidence != semantics["missing_zero_policy"]):
        raise SearchError("AST type/time/missing policies differ from accepted proposal semantics")
    required_inputs = tuple(proposal["program"].get("required_inputs") or ())
    if tuple(row.name for row in declaration.allowed_fields) != required_inputs:
        raise SearchError("AST fields differ from the reviewed candidate program inputs")
    public = program["public_derivation_record"]
    if ((declaration.parent_delta or declaration.parent_induction_id is not None)
            and proposal["mutation_class"] == "implementation_equivalent"):
        raise SearchError("a fresh response induction requires reviewed Step2 revision lineage")
    review_hash = digest({
        "context_hash": digest(c), "candidate_hash": proposal["candidate_hash"],
        "source_refs": c["source_refs"], "reviewed_spec_ref": r["spec_ref"],
        "readiness_ref": r["readiness_ref"],
        "readiness_decision": readiness.get("decision"),
        "accepted_semantics": readiness.get("accepted_semantics"),
    })
    protocol = _bound_json(c["development_protocol"])
    fixture = protocol["data_kind"] == "engineering_fixture"
    record = ForwardInductionRecord(
        record_id="step2-" + review_hash[:20],
        origin="reviewed_fixture" if fixture else "step2_review",
        source_ref=r["spec_ref"]["path"],
        assumptions=tuple(public["assumptions"]),
        key_derivation_steps=tuple(public["key_derivation_steps"]),
        parent_delta=declaration.parent_delta,
        observation_map=declaration.observation_map,
        response_family=declaration.response_family,
        response_constraint="causal_affine",
        grammar_productions=("field", "constant", *declaration.allowed_operators),
        conclusions=(public["overclaim_guard"],),
        falsifiers=tuple(public["identification_gaps"]),
        review_decision="proceed", data_exposure="synthetic_only" if fixture else "development_only",
        review_binding_hash=review_hash,
    )
    scope = InductionScope(
        induction_id=record.record_id, parent_induction_id=declaration.parent_induction_id,
        induction_record=record, response_family=declaration.response_family,
        mathematical_object=declaration.mathematical_object,
        observation_map=declaration.observation_map,
        allowed_fields=declaration.allowed_fields, output_type=declaration.output_type,
        allowed_operators=declaration.allowed_operators,
        allowed_constants=declaration.allowed_constants, allowed_windows=declaration.allowed_windows,
        max_depth=declaration.max_depth, missing_value_policy=declaration.missing_value_policy,
        numeric_domain=declaration.numeric_domain,
        change_class="new_response_structure" if declaration.parent_delta else "in_family_parameter",
    )
    return ReviewedStep2Scope(scope, digest(c), proposal["candidate_hash"],
                              dict(semantics), dict(r["readiness_ref"]), review_hash)


class TwoLevelCandidateProposer:
    """Generate AST children and return ordinary ``CandidateProposer`` rows."""

    def __init__(self, binding: ReviewedStep2Scope, *, population_size: int = 4,
                 max_attempts: int = 48) -> None:
        if type(population_size) is not int or population_size < 1:
            raise ValueError("population_size must be a positive integer")
        if type(max_attempts) is not int or max_attempts < population_size:
            raise ValueError("max_attempts must be an integer at least population_size")
        self.binding = binding
        self.population_size = population_size
        self.max_attempts = max_attempts
        self.trace: tuple[GenerationTrace, ...] = ()

    def propose(self, context: Mapping[str, Any], *, max_proposals: int, seed: int):
        if context.get("context_hash") != self.binding.context_hash:
            raise SearchError("proposer context differs from reviewed Step2 binding")
        if max_proposals <= 0:
            self.trace = ()
            return []
        candidates = {row["candidate_hash"]: row for row in context["candidates"]}
        if self.binding.candidate_hash not in candidates:
            raise SearchError("reviewed parent candidate is absent from proposer context")
        feedback = {row["candidate_hash"]: row for row in context["development_feedback"]}
        scoped = [row for row in context["candidates"]
                  if row["semantics"] == self.binding.accepted_semantics
                  and tuple(row["program"].get("required_inputs") or ())
                  == tuple(field.name for field in self.binding.scope.allowed_fields)]
        scored = [row for row in scoped
                  if feedback.get(row["candidate_hash"], {}).get("candidate_score") is not None]
        scored.sort(key=lambda row: (feedback[row["candidate_hash"]]["candidate_score"], row["candidate_hash"]),
                    reverse=True)
        known_expressions = {row["program"].get("expression") for row in context["candidates"]}
        limit = min(max_proposals, self.population_size)
        generated: list[ExpressionCandidate] = []
        trace: list[GenerationTrace] = []
        rng = Random(seed)
        parent_hash = self.binding.candidate_hash
        parents: list[ExpressionCandidate] = []
        for row in scored[:2]:
            try:
                parents.append(_candidate_from_row(row, self.binding.scope))
            except (ValueError, KeyError):
                continue
        if parents:
            parent_hash = parents[0].candidate_id
            for attempt in range(1, self.max_attempts + 1):
                if len(generated) >= limit:
                    break
                if len(parents) > 1 and attempt % 2 == 0:
                    child, row = crossover_candidates(
                        parents[0], parents[1], self.binding.scope, seed=rng.randrange(2**31),
                        candidate_id=f"native-child-{attempt:03d}")
                else:
                    child, row = mutate_candidate(
                        parents[0], self.binding.scope, seed=rng.randrange(2**31),
                        candidate_id=f"native-child-{attempt:03d}")
                trace.append(row)
                if child is not None and child.expression not in known_expressions:
                    known_expressions.add(child.expression)
                    generated.append(child)
        else:
            result = generate_population(
                self.binding.scope, seed=seed, population_size=limit,
                max_attempts=max(self.max_attempts, limit))
            trace.extend(result.trace)
            generated.extend(row for row in result.candidates if row.expression not in known_expressions)
        self.trace = tuple(trace)
        parent = candidates[parent_hash]
        return [self._proposal(row, parent_hash, parent, seed) for row in generated[:limit]]

    def _proposal(self, candidate: ExpressionCandidate, parent_hash: str,
                  parent: Mapping[str, Any], seed: int) -> dict[str, Any]:
        return {
            "proposal_id": "ast-" + candidate.root.node_hash[:20],
            "parent_candidate_hash": parent_hash,
            "proposer": {"kind": "d05_two_level_ast", "version": "1", "seed": seed},
            "mutation_class": "implementation_equivalent",
            "program": {"mode": "operator", "expression": candidate.expression,
                        "required_inputs": [row.name for row in self.binding.scope.allowed_fields]},
            "semantics": dict(parent["semantics"]),
            "changes": ["implementation"],
            "public_derivation": canonical({
                "induction_record_hash": self.binding.scope.induction_record.record_hash,
                "induction_scope_hash": self.binding.scope.scope_hash,
                "response_family": self.binding.scope.response_family,
                "operation": candidate.operation, "parents": candidate.parents,
                "ast": candidate.root.payload(),
                "boundary": "implementation candidate only; efficacy and mechanism remain unjudged",
            }),
            "expected_metric_signature": parent["expected_metric_signature"],
            "falsifiers": parent["falsifiers"], "kill_criteria": parent["kill_criteria"],
            "estimated_cost": 1.0,
        }


def publish_step6_search_material(
    controller: ResearchSearchController, binding: ReviewedStep2Scope,
) -> dict[str, Any]:
    """Publish replayable Step6 input without issuing a mechanism verdict."""
    snapshot = controller.ledger.snapshot(controller.campaign_id)
    if (digest(snapshot["context"]) != binding.context_hash
            or not any(row["candidate_hash"] == binding.candidate_hash
                       for row in snapshot["proposals"])):
        raise SearchError("Step6 material controller/campaign differs from reviewed binding")
    feedback = controller.verified_feedback(snapshot)
    terminal = []
    for row in feedback:
        terminal.append({
            "candidate_hash": row["candidate_hash"], "status": row["status"],
            "candidate_score": row["candidate_score"],
            "learning_increment": row["learning_increment"],
            "actual_cost": row["actual_cost"], "evidence_ref": row["evidence_ref"],
            "interpretation": "implementation_or_estimator_evidence_only",
        })
    pending = [row["id"] for row in snapshot["tickets"] if row["feedback_json"] is None]
    scored = [row for row in terminal if row["candidate_score"] is not None]
    next_action = ("wait_for_native_feedback" if pending else
                   "continue_in_family_expression_search_or_request_step6_judgment" if scored else
                   "repair_or_stop_without_reward")
    payload = {
        "contract_version": "factor_search_step6_material_v1",
        "campaign_id": controller.campaign_id, "context_hash": binding.context_hash,
        "induction_record_hash": binding.scope.induction_record.record_hash,
        "induction_scope_hash": binding.scope.scope_hash,
        "response_family": binding.scope.response_family,
        "terminal_expression_evidence": terminal,
        "pending_ticket_ids": pending,
        "mechanism_assessment": "unknown_requires_step6_discriminating_evidence",
        "next_action": next_action,
        "new_economics_or_response_route": "return_to_step2_for_fresh_reviewed_induction",
    }
    path = (controller.ledger.root / "objects/research_search/step6_material"
            / f"{digest(payload)}.json")
    existed = path.exists()
    write_once(path, payload)
    if not existed:
        controller.ledger.event(controller.campaign_id, "step6_search_material_published",
                                {"material_ref": file_ref(path)})
    return {"material": payload, "material_ref": file_ref(path)}


def _candidate_from_row(row: Mapping[str, Any], scope: InductionScope) -> ExpressionCandidate:
    program = row["program"]
    ir = parse_formula(program["expression"], list(program["required_inputs"]), raise_on_error=True)
    root = _ast_from_ir(ir["root"])
    infer_type(root, scope)
    require_response_family(root, scope)
    return ExpressionCandidate(
        row["candidate_hash"], root, scope.response_family, scope.scope_hash,
        0, (), "rehydrated_native_candidate", ("expression_structure",))


def _ast_from_ir(node: Mapping[str, Any], *, parent: str | None = None, position: int = 0) -> ASTNode:
    kind = node.get("type")
    if kind == "field":
        return ASTNode.field(str(node.get("name") or node.get("resolved_field")))
    if kind == "constant":
        value = node["value"]
        return ASTNode.window(value) if parent in {"delay", "mean"} and position == 1 else ASTNode.constant(value)
    if kind != "operator":
        raise ValueError("unsupported Formula IR node in AST rehydration")
    operator = str(node["operator"])
    args = node.get("args") or []
    if operator == "negate" and len(args) == 1 and args[0].get("type") == "constant":
        return ASTNode.constant(-args[0]["value"])
    return ASTNode.operator(operator, *(
        _ast_from_ir(child, parent=operator, position=index) for index, child in enumerate(args)))


def _bound_json(ref: Mapping[str, str]) -> dict[str, Any]:
    from .contracts import bound_json
    return bound_json(ref)
