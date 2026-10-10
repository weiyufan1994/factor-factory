"""Real bounded generation, subtree mutation, and typed crossover."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, log, sqrt
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


@dataclass(frozen=True)
class SearchTrace:
    iteration: int
    generation: int
    operation: str
    parents: tuple[str, ...]
    candidate_id: str | None
    expression: str | None
    score: float | None
    status: str
    detail: str


@dataclass(frozen=True)
class ExpressionSearchResult:
    algorithm: str
    best_candidate: ExpressionCandidate | None
    best_score: float | None
    evaluated_candidates: tuple[ExpressionCandidate, ...]
    trace: tuple[SearchTrace, ...]
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


def run_expression_gp(
    scope: InductionScope, *, evaluator, seed: int, population_size: int = 8,
    generations: int = 3, max_attempts_per_generation: int = 64,
) -> ExpressionSearchResult:
    """Run bounded multi-generation selection, mutation, and crossover."""
    if population_size < 2 or generations < 1:
        raise ValueError("GP requires population_size >= 2 and at least one generation")
    rng = Random(seed)
    initial = generate_population(scope, seed=rng.randrange(2**31), population_size=population_size,
                                  max_attempts=max_attempts_per_generation)
    population = list(initial.candidates)
    trace = [SearchTrace(row.attempt, 0, row.operation, row.parents, None, row.expression, None,
                         row.status, row.reason) for row in initial.trace]
    evaluated: list[ExpressionCandidate] = []
    scored: list[tuple[float, ExpressionCandidate]] = []
    score_cache: dict[str, float] = {}
    if not population:
        return ExpressionSearchResult("gp", None, None, (), tuple(trace), "initial_population_empty")
    for generation in range(generations):
        scored = []
        for candidate in population:
            reused = candidate.root.node_hash in score_cache
            if reused:
                score = score_cache[candidate.root.node_hash]
            else:
                try:
                    score = float(evaluate_candidate(candidate, scope, evaluator))
                except Exception as exc:
                    trace.append(SearchTrace(
                        len(trace) + 1, generation, "evaluate", candidate.parents,
                        candidate.candidate_id, candidate.expression, None, "evaluator_error",
                        f"{type(exc).__name__}: {exc}"))
                    return _expression_result("gp", scored, evaluated, trace, "evaluator_error")
                if not isfinite(score):
                    trace.append(SearchTrace(len(trace) + 1, generation, "evaluate", candidate.parents,
                                             candidate.candidate_id, candidate.expression, None,
                                             "evaluator_error", "nonfinite evaluator score"))
                    return _expression_result("gp", scored, evaluated, trace, "evaluator_error")
                score_cache[candidate.root.node_hash] = score
                evaluated.append(candidate)
            scored.append((score, candidate))
            trace.append(SearchTrace(len(trace) + 1, generation, "evaluate", candidate.parents,
                                     candidate.candidate_id, candidate.expression, score,
                                     "reused" if reused else "completed",
                                     "cached_ast_score" if reused else "complete_ast"))
        scored.sort(key=lambda row: (row[0], -row[1].root.complexity, row[1].root.node_hash), reverse=True)
        if generation == generations - 1:
            break
        elites = [row[1] for row in scored[:max(2, population_size // 2)]]
        next_population = [elites[0]]
        seen = {elites[0].root.node_hash}
        attempts = 0
        while len(next_population) < population_size and attempts < max_attempts_per_generation:
            attempts += 1
            if attempts % 2 == 0 and len(elites) > 1:
                left, right = rng.sample(elites, 2)
                child, generated = crossover_candidates(
                    left, right, scope, seed=rng.randrange(2**31),
                    candidate_id=f"gp-g{generation + 1}-{attempts:03d}")
            else:
                parent = rng.choice(elites)
                child, generated = mutate_candidate(
                    parent, scope, seed=rng.randrange(2**31),
                    candidate_id=f"gp-g{generation + 1}-{attempts:03d}")
            status = generated.status
            detail = generated.reason
            if child is not None and child.root.node_hash in seen:
                child = None
                status, detail = "rejected", "duplicate_offspring"
            if child is not None:
                seen.add(child.root.node_hash)
                next_population.append(child)
            trace.append(SearchTrace(len(trace) + 1, generation + 1, generated.operation,
                                     generated.parents, child.candidate_id if child else None,
                                     child.expression if child else None, None, status, detail))
        if len(next_population) < 2:
            return _expression_result("gp", scored, evaluated, trace, "offspring_budget_exhausted")
        population = next_population
    return _expression_result("gp", scored, evaluated, trace, "generation_budget_exhausted")


@dataclass
class _ExpressionTreeNode:
    partial: ASTNode
    parent: "_ExpressionTreeNode | None" = None
    action: str = "root"
    children: list["_ExpressionTreeNode"] = field(default_factory=list)
    visits: int = 0
    value_sum: float = 0.0

    @property
    def mean(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


def run_expression_mcts(
    scope: InductionScope, *, evaluator, seed: int, iterations: int = 32,
    exploration_weight: float = 1.0,
) -> ExpressionSearchResult:
    """Expand typed AST holes, roll out complete trees, and backpropagate scores."""
    if iterations < 1 or not isfinite(exploration_weight) or exploration_weight < 0:
        raise ValueError("invalid MCTS budget or exploration weight")
    require_effect_evaluation_scope(scope, candidate_scope_hash=scope.scope_hash,
                                    candidate_response_family=scope.response_family)
    rng = Random(seed)
    root = _ExpressionTreeNode(ASTNode.hole("panel"))
    trace: list[SearchTrace] = []
    evaluated: list[ExpressionCandidate] = []
    scored: list[tuple[float, ExpressionCandidate]] = []
    score_cache: dict[str, float] = {}
    for iteration in range(iterations):
        selected = _select_ast_node(root, scope, exploration_weight, rng)
        if selected is None:
            return _expression_result("mcts", scored, evaluated, trace, "tree_exhausted")
        options = _untried_ast_expansions(selected, scope)
        if not options:
            return _expression_result("mcts", scored, evaluated, trace, "tree_exhausted")
        action, partial = rng.choice(options)
        child = _ExpressionTreeNode(partial, selected, action)
        selected.children.append(child)
        try:
            complete = _rollout_ast(partial, scope, rng)
        except (ASTTypeError, ValueError) as exc:
            trace.append(SearchTrace(iteration, iteration + 1, action, (), None, None, None,
                                     "rejected", str(exc)))
            continue
        candidate = ExpressionCandidate(
            f"mcts-{iteration:03d}", complete, scope.response_family, scope.scope_hash,
            iteration + 1, (), "typed_hole_mcts", ("expression_structure",),
        )
        reused = candidate.root.node_hash in score_cache
        if reused:
            score = score_cache[candidate.root.node_hash]
        else:
            try:
                score = float(evaluate_candidate(candidate, scope, evaluator))
            except Exception as exc:
                trace.append(SearchTrace(iteration, iteration + 1, action, (), candidate.candidate_id,
                                         candidate.expression, None, "evaluator_error",
                                         f"{type(exc).__name__}: {exc}"))
                return _expression_result("mcts", scored, evaluated, trace, "evaluator_error")
            if not isfinite(score):
                trace.append(SearchTrace(iteration, iteration + 1, action, (), candidate.candidate_id,
                                         candidate.expression, None, "evaluator_error",
                                         "nonfinite evaluator score"))
                return _expression_result("mcts", scored, evaluated, trace, "evaluator_error")
            score_cache[candidate.root.node_hash] = score
            evaluated.append(candidate)
        scored.append((score, candidate))
        _backpropagate_ast(child, score)
        trace.append(SearchTrace(iteration, iteration + 1, action, (), candidate.candidate_id,
                                 candidate.expression, score, "reused" if reused else "completed",
                                 "cached_ast_score" if reused else "typed_rollout_backpropagated"))
    return _expression_result("mcts", scored, evaluated, trace, "iteration_budget_exhausted")


def _expression_result(algorithm: str, scored, evaluated, trace, stop_reason: str) -> ExpressionSearchResult:
    best = max(scored, key=lambda row: (row[0], -row[1].root.complexity, row[1].root.node_hash)) if scored else None
    return ExpressionSearchResult(algorithm, best[1] if best else None, best[0] if best else None,
                                  tuple(evaluated), tuple(trace), stop_reason)


def _first_hole(root: ASTNode) -> tuple[tuple[int, ...], ASTNode] | None:
    return next(((path, node) for path, node in iter_paths(root) if node.kind == "hole"), None)


def _ast_expansions(partial: ASTNode, scope: InductionScope) -> list[tuple[str, ASTNode]]:
    found = _first_hole(partial)
    if found is None:
        return []
    path, hole = found
    remaining = scope.max_depth - len(path)
    replacements: list[tuple[str, ASTNode]] = []
    if hole.value == "scalar":
        replacements.extend((f"constant:{value}", ASTNode.constant(value)) for value in scope.allowed_constants)
    else:
        replacements.extend((f"field:{row.name}", ASTNode.field(row.name))
                            for row in scope.allowed_fields if row.semantic_type == scope.output_type)
        if remaining > 1:
            if "plus" in scope.allowed_operators:
                replacements.extend((name, node) for name, node in (
                    ("plus:panel-panel", ASTNode.operator("plus", ASTNode.hole("panel"), ASTNode.hole("panel"))),
                    ("plus:panel-scalar", ASTNode.operator("plus", ASTNode.hole("panel"), ASTNode.hole("scalar"))),
                ))
            if "minus" in scope.allowed_operators:
                replacements.extend((name, node) for name, node in (
                    ("minus:panel-panel", ASTNode.operator("minus", ASTNode.hole("panel"), ASTNode.hole("panel"))),
                    ("minus:panel-scalar", ASTNode.operator("minus", ASTNode.hole("panel"), ASTNode.hole("scalar"))),
                ))
            if "multiply" in scope.allowed_operators:
                replacements.append(("multiply:panel-scalar",
                                     ASTNode.operator("multiply", ASTNode.hole("panel"), ASTNode.hole("scalar"))))
            if "divide" in scope.allowed_operators:
                replacements.append(("divide:panel-scalar",
                                     ASTNode.operator("divide", ASTNode.hole("panel"), ASTNode.hole("scalar"))))
            for operator in ("delay", "mean"):
                if operator in scope.allowed_operators:
                    replacements.extend((f"{operator}:{window}",
                                         ASTNode.operator(operator, ASTNode.hole("panel"), ASTNode.window(window)))
                                        for window in scope.allowed_windows)
    return [(action, replace_path(partial, path, replacement)) for action, replacement in replacements
            if replacement.depth <= remaining]


def _untried_ast_expansions(node: _ExpressionTreeNode, scope: InductionScope) -> list[tuple[str, ASTNode]]:
    existing = {child.partial.node_hash for child in node.children}
    return [(action, partial) for action, partial in _ast_expansions(node.partial, scope)
            if partial.node_hash not in existing]


def _has_ast_expansion(node: _ExpressionTreeNode, scope: InductionScope) -> bool:
    return bool(_untried_ast_expansions(node, scope)) or any(_has_ast_expansion(child, scope) for child in node.children)


def _select_ast_node(root: _ExpressionTreeNode, scope: InductionScope, weight: float,
                     rng: Random) -> _ExpressionTreeNode | None:
    node = root
    while True:
        if _untried_ast_expansions(node, scope):
            return node
        children = [child for child in node.children if _has_ast_expansion(child, scope)]
        if not children:
            return None
        best = max((child.mean + weight * sqrt(log(node.visits + 1) / (child.visits + 1))) for child in children)
        tied = [child for child in children
                if child.mean + weight * sqrt(log(node.visits + 1) / (child.visits + 1)) == best]
        node = rng.choice(tied)


def _rollout_ast(partial: ASTNode, scope: InductionScope, rng: Random) -> ASTNode:
    for _ in range(scope.max_depth * 8):
        options = _ast_expansions(partial, scope)
        if not options:
            if _first_hole(partial) is not None:
                raise ASTTypeError("rollout reached an unfillable typed hole")
            infer_type(partial, scope)
            require_response_family(partial, scope)
            return partial
        _action, partial = rng.choice(options)
    raise ASTTypeError("rollout expansion budget exhausted")


def _backpropagate_ast(node: _ExpressionTreeNode, score: float) -> None:
    current: _ExpressionTreeNode | None = node
    while current is not None:
        current.visits += 1
        current.value_sum += score
        current = current.parent
