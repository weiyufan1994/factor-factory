"""Hand-verifiable algebra checks, independent of frozen implementation parity."""
import ast
from fractions import Fraction
from pathlib import Path

import pytest

from factor_factory.mechanism_math.transient_impact import has_explicit_transient_impact_model
from factor_factory.mechanism_math.transient_impact_math import parse_math, has_stable_rho_constraint


@pytest.mark.parametrize('expression, expected', [
    ('(a+a)*b', {('a', 'b'): Fraction(2)}),
    ('a-a', {}),
    ('(a+b)/2', {('a',): Fraction(1, 2), ('b',): Fraction(1, 2)}),
    ('(a+b)^2', {('a', 'a'): Fraction(1), ('a', 'b'): Fraction(2), ('b', 'b'): Fraction(1)}),
])
def test_polynomial_matches_hand_calculation(expression, expected):
    assert parse_math(expression)['polynomial'] == expected


@pytest.mark.parametrize('expression', ['a.__class__', '__import__("os")', 'lambda: 1', 'a[0]', 'foo(a)'])
def test_parser_does_not_execute_or_accept_unbounded_python(expression):
    assert parse_math(expression) is None


@pytest.mark.parametrize('constraint, expected', [
    ('|rho|<1', True), ('|rho|<1.2', False), ('not |rho|<1', False),
    ('|rho|<1; rho=2', False), ('|rho|<1; |rho|>1', False),
])
def test_stability_constraint_does_not_accept_contradictions(constraint, expected):
    assert has_stable_rho_constraint(constraint, 'rho') is expected


def test_model_recognition_keeps_residual_and_polarity_requirements():
    model = 'pressure=lambda*imbalance; return=beta*pressure+eps; temporary impact decay'
    assert has_explicit_transient_impact_model(model, {'close'}) is True
    assert has_explicit_transient_impact_model(model.replace('+eps', ''), {'close'}) is False
    assert has_explicit_transient_impact_model(model + '; no temporary impact', {'close'}) is False


def test_kernels_are_small_and_python_311_compatible():
    directory = Path(__file__).resolve().parents[1] / 'factor_factory/mechanism_math'
    for filename, limit in [('transient_impact_math.py', 100), ('transient_impact.py', 200)]:
        tree = ast.parse((directory / filename).read_text(), feature_version=(3, 11))
        assert max(n.end_lineno - n.lineno + 1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)) < limit
