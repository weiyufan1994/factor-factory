"""Real bounded generation, subtree mutation, and typed crossover."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .induction import InductionScope, SemanticType, Unit, require_effect_evaluation_scope
from .typed_ast import ASTNode, ASTTypeError, infer_type, iter_paths, replace_path, require_response_family


@dataclass(frozen=True)
class ExpressionCandidate:
    candidate_id: str
    root: ASTNode
    response_family: str
    induction_scope_hash: str
    generation: int
    parents: tuple[str, ...]
    operation: str
    changed_aspects: tuple[str, ...]

    @property
    def expression(self) -> str:
        return self.root.expression()


@dataclass(frozen=True)
class GenerationTrace:
    attempt: int
    generation: int
    operation: str
    parents: tuple[str, ...]
    status: str
    reason: str
    candidate_hash: str | None
    expression: str | None


@dataclass(frozen=True)
class GenerationResult:
    candidates: tuple[ExpressionCandidate, ...]
    trace: tuple[GenerationTrace, ...]
    attempts: int
    rejected: int
    stop_reason: str


def generate_population(
    scope: InductionScope,
    *,
    seed: int,
    population_size: int,
    max_attempts: int,
    max_depth: int | None = None,
) -> GenerationResult:
    if population_size < 1 or max_attempts < population_size:
        raise ValueError("population and attempt budgets are inconsistent")
    require_effect_evaluation_scope(
        scope, candidate_scope_hash=scope.scope_hash,
        candidate_response_family=scope.response_family,
    )
    rng = Random(seed)
    depth = min(scope.max_depth, max_depth or scope.max_depth)
    candidates: list[ExpressionCandidate] = []
    trace: list[GenerationTrace] = []
    seen: set[str] = set()
    for attempt in range(1, max_attempts + 1):
        if len(candidates) >= population_size:
            break
        try:
            node = _generate_for_type(scope.output_type, scope, rng, depth)
            inferred = infer_type(node, scope)
            if inferred != scope.output_type:
                raise ASTTypeError("generated root does not match induction output type")
            require_response_family(node, scope)
            if node.node_hash in seen:
                raise ASTTypeError("duplicate_tree")
            seen.add(node.node_hash)
            candidate = ExpressionCandidate(
                f"g0-{attempt:03d}", node, scope.response_family, scope.scope_hash,
                0, (), "typed_hole_expansion", ("expression_structure",),
            )
            candidates.append(candidate)
            trace.append(_trace(attempt, 0, "typed_hole_expansion", (), "accepted", "typed_tree_complete", candidate))
        except (ASTTypeError, ValueError) as exc:
            trace.append(GenerationTrace(attempt, 0, "typed_hole_expansion", (), "rejected", str(exc), None, None))
    return GenerationResult(
        tuple(candidates), tuple(trace), len(trace),
        sum(row.status == "rejected" for row in trace),
        "population_complete" if len(candidates) == population_size else "attempt_budget_exhausted",
    )


def mutate_candidate(
    parent: ExpressionCandidate,
    scope: InductionScope,
    *,
    seed: int,
    candidate_id: str,
    operation: str = "subtree_mutation",
) -> tuple[ExpressionCandidate | None, GenerationTrace]:
    _require_candidate(parent, scope)
    rng = Random(seed)
    paths = [(path, node) for path, node in iter_paths(parent.root)
             if operation != "parameter_mutation" or node.kind in {"constant", "window"}]
    rng.shuffle(paths)
    reasons: list[str] = []
    for attempt, (path, old) in enumerate(paths, start=1):
        try:
            expected = infer_type(old, scope)
            if operation == "parameter_mutation":
                values = scope.allowed_windows if old.kind == "window" else scope.allowed_constants
                constructor = ASTNode.window if old.kind == "window" else ASTNode.constant
                pool = [constructor(value) for value in values if float(value) != float(old.value)]
                if not pool:
                    raise ASTTypeError("no alternate parameter")
                replacement = rng.choice(pool)
            else:
                replacement = _generate_for_type(expected, scope, rng, max(1, scope.max_depth - len(path)))
            child_root = replace_path(parent.root, path, replacement)
            inferred = infer_type(child_root, scope)
            if inferred != scope.output_type or child_root.node_hash == parent.root.node_hash:
                raise ASTTypeError("mutation did not produce a distinct compatible tree")
            require_response_family(child_root, scope)
            child = ExpressionCandidate(
                candidate_id, child_root, scope.response_family, scope.scope_hash,
                parent.generation + 1, (parent.candidate_id,), operation,
                ("parameter",) if operation == "parameter_mutation" else ("expression_subtree",),
            )
            return child, _trace(attempt, child.generation, operation, child.parents, "accepted", "typed_mutation", child)
        except (ASTTypeError, ValueError) as exc:
            reasons.append(str(exc))
    return None, GenerationTrace(len(paths), parent.generation + 1, operation, (parent.candidate_id,),
                                 "rejected", ";".join(reasons) or "no_legal_mutation", None, None)


def crossover_candidates(
    left: ExpressionCandidate,
    right: ExpressionCandidate,
    scope: InductionScope,
    *,
    seed: int,
    candidate_id: str,
) -> tuple[ExpressionCandidate | None, GenerationTrace]:
    _require_candidate(left, scope)
    _require_candidate(right, scope)
    rng = Random(seed)
    pairs = [
        (lp, ln, rp, rn)
        for lp, ln in iter_paths(left.root)
        for rp, rn in iter_paths(right.root)
        if lp and rp and infer_type(ln, scope) == infer_type(rn, scope)
    ]
    rng.shuffle(pairs)
    reasons: list[str] = []
    for attempt, (left_path, _left_node, _right_path, right_node) in enumerate(pairs, start=1):
        try:
            child_root = replace_path(left.root, left_path, right_node)
            if child_root.node_hash in {left.root.node_hash, right.root.node_hash}:
                raise ASTTypeError("crossover duplicate parent")
            if infer_type(child_root, scope) != scope.output_type:
                raise ASTTypeError("crossover output type mismatch")
            require_response_family(child_root, scope)
            child = ExpressionCandidate(
                candidate_id, child_root, scope.response_family, scope.scope_hash,
                max(left.generation, right.generation) + 1,
                (left.candidate_id, right.candidate_id), "typed_subtree_crossover",
                ("expression_subtree",),
            )
            return child, _trace(attempt, child.generation, child.operation, child.parents,
                                 "accepted", "compatible_subtree_swap", child)
        except (ASTTypeError, ValueError) as exc:
            reasons.append(str(exc))
    return None, GenerationTrace(len(pairs), max(left.generation, right.generation) + 1,
                                 "typed_subtree_crossover", (left.candidate_id, right.candidate_id),
                                 "rejected", ";".join(reasons) or "no_compatible_subtrees", None, None)


def evaluate_candidate(
    candidate: ExpressionCandidate,
    scope: InductionScope,
    evaluator,
):
    """Call an efficacy evaluator only after induction and type gates pass."""
    _require_candidate(candidate, scope)
    if infer_type(candidate.root, scope) != scope.output_type:
        raise ASTTypeError("candidate output type differs from induction target")
    require_response_family(candidate.root, scope)
    return evaluator(candidate)


def _require_candidate(candidate: ExpressionCandidate, scope: InductionScope) -> None:
    require_effect_evaluation_scope(
        scope,
        candidate_scope_hash=candidate.induction_scope_hash,
        candidate_response_family=candidate.response_family,
        changed_aspects=candidate.changed_aspects,
    )
    require_response_family(candidate.root, scope)


def _generate_for_type(expected: SemanticType, scope: InductionScope, rng: Random, depth: int) -> ASTNode:
    field_nodes = [ASTNode.field(row.name) for row in scope.allowed_fields if row.semantic_type == expected]
    if expected.shape == "scalar":
        constants = [ASTNode.constant(value) for value in scope.allowed_constants]
        if not constants:
            raise ASTTypeError("no scalar terminal for requested type")
        return rng.choice(constants)
    if depth <= 1 or rng.random() < 0.30:
        if not field_nodes:
            raise ASTTypeError("no field terminal for requested type")
        return rng.choice(field_nodes)
    choices = [name for name in scope.allowed_operators if name in {"plus", "minus", "multiply", "divide", "delay", "mean"}]
    rng.shuffle(choices)
    for operator in choices:
        try:
            if operator in {"plus", "minus"}:
                node = ASTNode.operator(operator,
                    _generate_for_type(expected, scope, rng, depth - 1),
                    _generate_for_type(expected, scope, rng, depth - 1))
            elif operator in {"multiply", "divide"}:
                scalar = SemanticType("scalar", "numeric", Unit.dimensionless(), "atemporal", "none", "constant")
                if expected.unit == Unit.dimensionless() and rng.random() < 0.5:
                    right = _generate_for_type(expected, scope, rng, depth - 1)
                else:
                    right = _generate_for_type(scalar, scope, rng, depth - 1)
                node = ASTNode.operator(operator,
                    _generate_for_type(expected, scope, rng, depth - 1), right)
            else:
                if not scope.allowed_windows:
                    continue
                node = ASTNode.operator(operator,
                    _generate_for_type(expected, scope, rng, depth - 1),
                    ASTNode.window(rng.choice(scope.allowed_windows)))
            if infer_type(node, scope) == expected:
                return node
        except (ASTTypeError, ValueError):
            continue
    if field_nodes:
        return rng.choice(field_nodes)
    raise ASTTypeError("no legal expansion for typed hole")


def _trace(attempt: int, generation: int, operation: str, parents: tuple[str, ...],
           status: str, reason: str, candidate: ExpressionCandidate) -> GenerationTrace:
    return GenerationTrace(attempt, generation, operation, parents, status, reason,
                           candidate.root.node_hash, candidate.expression)
