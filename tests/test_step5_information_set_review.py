from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from factor_factory.information_set_review import (
    ILLEGAL, UNCONFIRMED, LAG_DOCUMENTED, classify_information_set,
)
from scripts.repair_step5_information_set import digest, repair


@pytest.mark.parametrize('text', [
    'Use all current-valid PIT formation members as peers independent of own trailing readiness, future labels or controls.',
    'Do not use future returns or lookahead in the score.',
    'Use future returns in the score.',  # prose alone also cannot establish safety
    "Do not call close.shift(-1); it is for label diagnostics only.",
    '不得使用未来收益。',
])
def test_narrative_is_unconfirmed_not_adjudicated_by_words(text):
    assert classify_information_set({'formula_text': 'lag(close, 1)',
                                     'cross_sectional_steps': [text]}) == UNCONFIRMED


@pytest.mark.parametrize('expression', [
    'future_return', "data['future_return']", 'Lead(close, 1)',
    'ts_lead(close, 2)', 'lookahead(close, 1)', 'close.shift(-1)',
    'close.shift(periods=-1)', 'shift(close, -2)', 'ts_delay(close, -1)',
    'lag(close, n=-1)', 'delay(close, -0.5)',
    'shift(mean(close, 5), -1)', 'lag(rank(close), -1)',
    'shift(mean(close, 5), periods=-1)', 'lag(rank(close), n=-1)',
    'Ref(mean($close, 5), -1)', 'close.groupby(sector).shift(-1)',
    'lag(rank(close), -(1))', 'lag(rank(close), −1)',
])
def test_future_expression_cannot_be_cleared_by_safe_sounding_prose(expression):
    assert classify_information_set({'formula_text': expression,
        'preprocessing': ['No future data is used; only lagged bars.']}) == ILLEGAL


def test_future_operator_and_lag_word_substrings():
    assert classify_information_set({'operators': ['lead']}) == ILLEGAL
    assert classify_information_set({'formula_text': 'lag(close, 1)'}) == LAG_DOCUMENTED
    assert classify_information_set({'preprocessing': ['Validate boolean flags.']}) == UNCONFIRMED
    assert classify_information_set({'formula_text': 'close / amount'}) == UNCONFIRMED


@pytest.mark.parametrize('formula', ['lag(rank(close), n)', 'shift(mean(close, 5), -(n))',
                                    'shift(mean(close, 5),', 'lag(x, 1) + lag(x, unknown)'])
def test_ambiguous_lag_never_falls_back_to_documented_lag(formula):
    assert classify_information_set({'formula_text': formula}) == UNCONFIRMED


@pytest.mark.parametrize('package', ['factor-forge-step5', 'factor_forge_step5'])
def test_both_actual_case_producers_use_same_three_state_classification(package):
    builder = importlib.import_module(f'skills.{package}.modules.case_builder')
    canonical = {'formula_text': 'close / amount',
                 'cross_sectional_steps': ['Independent of future labels.']}
    bundle = {'objects': {'factor_spec_master': {'canonical_spec': canonical},
                          'factor_run_master': {'run_status': 'success'}}}
    before = deepcopy(bundle)
    result = builder.build_step5_math_discipline_review(bundle, {'backend_summary': []})
    assert result['information_set_legality'] == UNCONFIRMED
    assert bundle == before
    for expression in ['close.shift(-1)', 'shift(mean(close, 5), -1)', 'lag(rank(close), n=-1)']:
        canonical['formula_text'] = expression
        assert builder.build_step5_math_discipline_review(bundle, {})['information_set_legality'] == ILLEGAL


@pytest.fixture
def metadata_case(tmp_path):
    def save(name, obj):
        path = tmp_path / name
        path.write_text(json.dumps(obj))
        return path
    spec = save('spec.json', {'report_id': 'EXAMPLE', 'canonical_spec': {
        'formula_text': '-e * z', 'cross_sectional_steps': ['Independent of future labels.']}})
    case = {'report_id': 'EXAMPLE', 'factor_id': 'FACTOR', 'final_status': 'partial',
            'math_discipline_review': {'information_set_legality': ILLEGAL, 'other': ['preserve']},
            'artifact_identity': {'producer': 'original'},
            'evaluation_summary': {'rank_ic_mean': 0.01},
            'evidence': {'archive_paths': ['original-archive']}}
    paths = {'spec': spec, 'case': save('case.json', case), 'handoff': save('handoff.json', case)}
    paths['manifest'] = save('manifest.json', {'objects': {
        'factor_spec_master': str(spec), 'factor_case_master': str(paths['case']),
        'handoff_to_step6': str(paths['handoff'])}, 'step_io': {'step5': {'outputs': {
        'factor_case_master': str(paths['case']), 'handoff_to_step6': str(paths['handoff'])}}}})
    expected = {k: digest(p.read_bytes()) for k, p in paths.items()}
    return paths, expected


def test_preview_then_apply_only_classification_and_its_provenance(metadata_case, tmp_path):
    paths, expected = metadata_case
    original = {k: p.read_bytes() for k, p in paths.items()}
    preview = repair(paths['manifest'], expected, tmp_path / 'preview')
    assert preview['status'] == 'PREVIEW'
    assert {k: p.read_bytes() for k, p in paths.items()} == original
    receipt = repair(paths['manifest'], expected, tmp_path / 'applied', apply=True)
    assert receipt['status'] == 'METADATA_REDERIVED_REQUIRES_NATIVE_VALIDATION'
    for key in ('case', 'handoff'):
        current = json.loads(paths[key].read_text())
        math = current['math_discipline_review']
        assert math.pop('information_set_legality') == UNCONFIRMED
        revision = math.pop('information_set_metadata_revision')
        assert revision['implementation_safety_confirmed'] is False
        assert revision['independent_confirmation_required'] is True
        assert revision['parents'][key]['sha256'] == expected[key]
        math['information_set_legality'] = ILLEGAL
        assert current == json.loads(original[key])
        assert (tmp_path / 'applied' / f'original_{key}.json').read_bytes() == original[key]
        assert paths[key].read_bytes() == (tmp_path / 'preview' / f'derived_{key}.json').read_bytes()
    assert paths['spec'].read_bytes() == original['spec']
    assert paths['manifest'].read_bytes() == original['manifest']
    with pytest.raises(ValueError, match='changed'):
        repair(paths['manifest'], expected, tmp_path / 'retry', apply=True)


@pytest.mark.parametrize('kind', ['manifest', 'spec', 'case', 'handoff'])
def test_changed_bound_input_refused_before_any_write(metadata_case, tmp_path, kind):
    paths, expected = metadata_case
    paths[kind].write_bytes(paths[kind].read_bytes() + b' ')
    before = {k: p.read_bytes() for k, p in paths.items()}
    with pytest.raises(ValueError, match='changed'):
        repair(paths['manifest'], expected, tmp_path / 'refused', apply=True)
    assert {k: p.read_bytes() for k, p in paths.items()} == before
    assert not (tmp_path / 'refused').exists()


@pytest.mark.parametrize('expression', ['close.shift(-1)', 'shift(mean(close, 5), -1)',
                                       'lag(rank(close), -1)', 'shift(mean(close, 5), periods=-1)',
                                       'lag(rank(close), n=-1)'])
def test_real_forward_expression_refuses_metadata_repair(metadata_case, tmp_path, expression):
    paths, expected = metadata_case
    spec = json.loads(paths['spec'].read_text())
    spec['canonical_spec']['formula_text'] = expression
    paths['spec'].write_text(json.dumps(spec))
    expected['spec'] = digest(paths['spec'].read_bytes())
    with pytest.raises(ValueError, match='Only legacy narrative BLOCK'):
        repair(paths['manifest'], expected, tmp_path / 'refused', apply=True)


def test_partial_apply_failure_preserves_originals_and_never_reports_success(metadata_case, tmp_path, monkeypatch):
    from scripts import repair_step5_information_set as maintenance
    paths, expected = metadata_case
    original_write = maintenance.write_json_atomic
    def fail_handoff(path, value):
        if path == paths['handoff']:
            raise OSError('synthetic filesystem failure')
        original_write(path, value)
    monkeypatch.setattr(maintenance, 'write_json_atomic', fail_handoff)
    with pytest.raises(OSError, match='filesystem failure'):
        repair(paths['manifest'], expected, tmp_path / 'partial', apply=True)
    receipt = json.loads((tmp_path / 'partial/receipt.json').read_text())
    assert receipt['status'] == 'APPLY_FAILED_RECONCILE_NO_AUTOMATIC_RETRY'
    assert receipt['applied_paths'] == [str(paths['case'])]
    for key in ('case', 'handoff'):
        assert digest((tmp_path / 'partial' / f'original_{key}.json').read_bytes()) == expected[key]
