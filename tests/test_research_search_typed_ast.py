from dataclasses import replace

import pytest

from factor_factory.research_search.induction import FieldSpec, Unit
from factor_factory.research_search.typed_ast import ASTNode, ASTTypeError, infer_type
from tests.research_search_d05_helpers import approved_scope, panel_type


def test_addition_rejects_wrong_units():
    scope = approved_scope(allowed_fields=(
        FieldSpec("x", panel_type(unit=Unit.named("return"))),
        FieldSpec("y", panel_type(unit=Unit.named("currency"))),
    ))
    with pytest.raises(ASTTypeError, match="equal numeric units"):
        infer_type(ASTNode.operator("plus", ASTNode.field("x"), ASTNode.field("y")), scope)


@pytest.mark.parametrize("changed", [
    {"clock": "next_session_close"},
    {"grouping": "cross_section"},
    {"information": "future_known"},
])
def test_panel_operation_rejects_clock_grouping_or_information_mismatch(changed):
    scope = approved_scope(allowed_fields=(
        FieldSpec("x", panel_type()),
        FieldSpec("y", panel_type(**changed)),
    ))
    with pytest.raises(ASTTypeError, match="compatible|equal clock"):
        infer_type(ASTNode.operator("plus", ASTNode.field("x"), ASTNode.field("y")), scope)


def test_operator_allowlist_and_integer_window_are_enforced():
    scope = approved_scope(allowed_operators=("plus", "delay"))
    with pytest.raises(ASTTypeError, match="outside induction scope"):
        infer_type(ASTNode.operator("mean", ASTNode.field("x"), ASTNode.constant(2)), scope)
    with pytest.raises(ASTTypeError, match="allowed integer window"):
        infer_type(ASTNode.operator("delay", ASTNode.field("x"), ASTNode.constant(0.5)), scope)


def test_window_role_cannot_be_reused_as_coefficient_and_zero_division_is_rejected():
    scope = approved_scope(allowed_constants=(0.0, 0.5), allowed_windows=(3,))
    with pytest.raises(ASTTypeError, match="constant outside induction scope"):
        infer_type(ASTNode.operator("multiply", ASTNode.field("x"), ASTNode.constant(3)), scope)
    with pytest.raises(ASTTypeError, match="known zero denominator"):
        infer_type(ASTNode.operator("divide", ASTNode.field("x"), ASTNode.constant(0.0)), scope)


def test_typed_tree_renders_formula_expression():
    scope = approved_scope()
    node = ASTNode.operator("plus", ASTNode.field("x"),
                            ASTNode.operator("multiply", ASTNode.field("y"), ASTNode.constant(0.5)))
    assert infer_type(node, scope) == scope.output_type
    assert node.expression() == "(x + (y * 0.5))"
