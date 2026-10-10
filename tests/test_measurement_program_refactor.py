"""Ordered-error parity plus independent small oracles for section extraction."""
from __future__ import annotations

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from factor_factory import measurement_program as module
from factor_factory.research_profiles import ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2
from tests.test_e_flexible_local_profile import _flexible_program
from tests.test_factorforge_measurement_program_research_equation_v2 import _filled_program


@lru_cache(maxsize=1)
def frozen_validator():
    path = Path(__file__).parent / 'fixtures/measurement_program_before_cleanup.py'
    namespace = dict(vars(module))
    exec(compile(path.read_text(), str(path), 'exec'), namespace)
    return namespace['validate_measurement_program']


def program_and_options(profile):
    options = {'placeholder': 'RESEARCHER_MUST_REPLACE'}
    if profile in ('ordinary', 'wrong-scope'):
        program = _flexible_program()
        program['compatibility_profile'] = ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2
        options.update(
            require_web_executable=False,
            compatibility_profile=ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2,
            scope='local_is_only' if profile == 'ordinary' else 'hosted_formal',
        )
    else:
        version = module.MEASUREMENT_PROGRAM_VERSION_V1 if profile == 'v1' else module.MEASUREMENT_PROGRAM_VERSION_V2
        program = _filled_program(version)
    return program, options


def locations(value, path=()):
    """Visit every container and leaf, not a sample of section names."""
    yield path
    if isinstance(value, dict):
        for key, item in value.items():
            yield from locations(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from locations(item, path + (index,))


def outcome(validate, program, options):
    try:
        return ('reasons', validate(program, **options))
    except (TypeError, ValueError) as error:
        # Some malformed nested Python values raised before this refactor.
        # Preserve that behavior explicitly; it is not counted as validation PASS.
        return ('exception', type(error), str(error))


def assert_parity(program, options):
    original = deepcopy(program)
    expected = outcome(frozen_validator(), program, options)
    actual = outcome(module.validate_measurement_program, program, options)
    assert actual == expected
    assert program == original


@pytest.mark.parametrize('profile', ['v1', 'v2', 'ordinary', 'wrong-scope'])
def test_every_nested_field_mutation_preserves_exact_error_order(profile):
    baseline, options = program_and_options(profile)
    assert_parity(baseline, options)
    for path in locations(baseline):
        for value in (None, '', 'RESEARCHER_MUST_REPLACE', [], {}, False, 0):
            program = deepcopy(baseline)
            if not path:
                program = value
            else:
                parent = program
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
            assert_parity(program, options)
        if path:
            program = deepcopy(baseline)
            parent = program
            for key in path[:-1]:
                parent = parent[key]
            del parent[path[-1]]
            assert_parity(program, options)


@pytest.mark.parametrize('profile', ['v1', 'v2', 'ordinary'])
def test_complete_program_has_no_errors_and_missing_object_is_precise(profile):
    program, options = program_and_options(profile)
    assert module.validate_measurement_program(program, **options) == []
    program['market_outcome_projection']['source_math_object'] = 'unrelated object'
    assert module.validate_measurement_program(program, **options) == [
        'measurement_program.model_selection.selected_model_mathematical_object_global_mismatch'
    ]


@pytest.mark.parametrize('profile', ['v1', 'v2', 'ordinary'])
def test_node_membership_uses_supplied_knowledge_only(profile):
    program, options = program_and_options(profile)
    program['implementation']['components'][0]['knowledge_node_ids'] = ['known']
    assert module.validate_measurement_program(program, **options) == [
        'measurement_program.implementation.components[0].knowledge_node_ids_not_in_summary'
    ]
    assert module.validate_measurement_program(
        program, available_knowledge_node_ids=iter(['known']), **options,
    ) == []


def test_invalid_top_level_keeps_legacy_single_reason():
    assert module.validate_measurement_program(None, compatibility_profile='invalid') == ['measurement_program']


def test_section_boundaries_and_public_entry_are_small():
    tree = ast.parse(Path(module.__file__).read_text(), feature_version=(3, 11))
    entry = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'validate_measurement_program')
    checks = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == '_MeasurementProgramChecks')
    assert entry.end_lineno - entry.lineno < 50
    assert all(node.end_lineno - node.lineno < 210 for node in checks.body if isinstance(node, ast.FunctionDef))
