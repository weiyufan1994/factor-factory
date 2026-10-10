from factor_factory.research_search.generator import (
    crossover_candidates,
    generate_population,
    mutate_candidate,
)
from factor_factory.research_search.typed_ast import iter_paths
from tests.research_search_d05_helpers import approved_scope


def test_generation_builds_real_trees_and_records_rejections_and_duplicates():
    scope = approved_scope(max_depth=3)
    result = generate_population(scope, seed=17, population_size=8, max_attempts=40)
    assert result.candidates
    assert {row.candidate_hash for row in result.trace if row.status == "accepted"} == {
        row.root.node_hash for row in result.candidates}
    assert len({row.expression for row in result.candidates}) == len(result.candidates)
    assert any(row.root.kind == "operator" for row in result.candidates)
    assert all(row.operation == "typed_hole_expansion" for row in result.candidates)
    assert result.attempts <= 40
    assert result.rejected == sum(row.status == "rejected" for row in result.trace)


def test_subtree_mutation_and_typed_crossover_have_real_lineage():
    scope = approved_scope(max_depth=4)
    population = generate_population(scope, seed=31, population_size=10, max_attempts=80).candidates
    operator_parent = next(row for row in population if row.root.kind == "operator")
    child, mutation = mutate_candidate(operator_parent, scope, seed=8, candidate_id="m1")
    assert child is not None, mutation.reason
    assert child.root.node_hash != operator_parent.root.node_hash
    assert child.parents == (operator_parent.candidate_id,)

    crossed = None
    trace = None
    for index, right in enumerate(population):
        crossed, trace = crossover_candidates(child, right, scope, seed=index, candidate_id=f"x{index}")
        if crossed is not None:
            break
    assert crossed is not None, trace.reason
    assert crossed.parents == (child.candidate_id, right.candidate_id)
    assert crossed.root.node_hash not in {child.root.node_hash, right.root.node_hash}


def test_parameter_mutation_never_mislabels_a_subtree_change():
    scope = approved_scope()
    population = generate_population(scope, seed=3, population_size=10, max_attempts=80).candidates
    without_constant = next(row for row in population if all(node.kind != "constant" for _, node in iter_paths(row.root)))
    child, trace = mutate_candidate(without_constant, scope, seed=1, candidate_id="p", operation="parameter_mutation")
    assert child is None
    assert trace.status == "rejected"
