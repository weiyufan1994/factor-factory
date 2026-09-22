from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = 'LOCAL_PFVV_REPORT'
FACTOR_ID = 'PFVV_COMPOSITE'


def _module():
    path = PROJECT_ROOT / 'skills/factor-forge-step2/scripts/run_step2.py'
    spec = importlib.util.spec_from_file_location('step2_local_agent_specs', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


STEP2 = _module()


def _raw_spec(route: str) -> dict:
    return {
        'factor_id': FACTOR_ID,
        'report_id': REPORT_ID,
        'route': route,
        'raw_formula_text': (
            '-0.5 * CS_ZSCORE(TS_STD(SAME_SIGN_SKEW_GATE(LOG1P(RETURNS)), 20)) '
            '- 0.5 * CS_ZSCORE(TS_STD(VOLUME_PEAK_SEGMENT_RETURN_STD(RETURNS, VOLUME), 20))'
        ),
        'operators': [
            'log1p()', 'same_sign_skew_gate()', 'ts_std()', 'volume_peak_segment()',
            'return_std()', 'cs_zscore()', 'negative_equal_weight()',
        ],
        'required_inputs': ['returns', 'volume'],
        'time_series_steps': [
            'PF: apply the skew-gated same-sign return condition, then log1p-transform return deviations.',
            'PF: take a rolling 20-day standard deviation of the gated log1p return deviations.',
            'VV: segment returns at volume peaks, calculate within-segment return standard deviation, and cross-sectionally z-score it.',
            'VV: take a rolling 20-day standard deviation of the cross-sectionally z-scored segmented return statistic.',
        ],
        'cross_sectional_steps': [
            'Cross-sectionally z-score PF and VV.',
            'Construct the negative equal-weight PF/VV composite.',
        ],
        'preprocessing': ['Use only contemporaneously available daily returns and volume.'],
        'normalization': ['Cross-sectional z-score of both PF and VV.'],
        'neutralization': ['No unreported neutralization is asserted.'],
        'rebalance_frequency': 'monthly',
        'explicit_items': [
            'PF rolling standard deviation of skew-gated log1p same-sign return deviations',
            'VV rolling standard deviation of CS-zscore volume-peak segmented return standard deviation',
            'negative equal-weight PF/VV composite',
        ],
        'inferred_items': ['None beyond the simplified authored construction.'],
        'ambiguities': ['The exact skew threshold remains explicitly recorded upstream.'],
        'candidate_only': True,
        'oos_accessed': False,
    }


def _write_json(root: Path, relative_path: str, payload: dict) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _aim(primary_sha: str, challenger_sha: str, canonical_core: dict) -> dict:
    return {
        'report_id': REPORT_ID,
        'factor_id': FACTOR_ID,
        'source_type': 'pdf_report',
        'final_factor': {'construction_id': FACTOR_ID, 'name': FACTOR_ID},
        'research_subject_mode': 'report_replication',
        'source_baseline_reference': {
            'source_construction_id': 'paper_pfvvs_negative_equal_weight',
            'selected_construction_id': FACTOR_ID,
            'relation': 'selected_baseline',
        },
        'source_semantic_review': {
            'status': 'match',
            'reviewer_basis': 'The authored negative PF/VV equal-weight construction is selected unchanged.',
            'compared_source_components': ['PF', 'VV', 'negative_equal_weight'],
            'compared_selected_components': ['PF', 'VV', 'negative_equal_weight'],
            'material_deviations': [],
        },
        'local_agent_spec_inputs': {
            'chief_canonical_core': canonical_core,
            'primary': {
                'relative_path': 'objects/local_agent_specs/pfvvs_primary.json',
                'sha256': primary_sha,
                'role': 'local_agent_primary_spec',
                'identity': {
                    'report_id': REPORT_ID,
                    'factor_id': FACTOR_ID,
                    'route': 'primary',
                },
            },
            'challenger': {
                'relative_path': 'objects/local_agent_specs/pfvvs_challenger.json',
                'sha256': challenger_sha,
                'role': 'local_agent_challenger_spec',
                'identity': {
                    'report_id': REPORT_ID,
                    'factor_id': FACTOR_ID,
                    'route': 'challenger',
                },
            },
        },
    }


def _bound_aim(root: Path) -> tuple[dict, dict, dict]:
    primary = _raw_spec('primary')
    challenger = _raw_spec('challenger')
    primary_sha = _write_json(root, 'objects/local_agent_specs/pfvvs_primary.json', primary)
    challenger_sha = _write_json(root, 'objects/local_agent_specs/pfvvs_challenger.json', challenger)
    canonical_core = {
        field: primary[field]
        for field in STEP2.LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS
    }
    return _aim(primary_sha, challenger_sha, canonical_core), primary, challenger


def _load(root: Path, aim: dict):
    previous = STEP2.FACTORFORGE
    STEP2.FACTORFORGE = root
    try:
        return STEP2.load_local_agent_dual_route_specs(REPORT_ID, aim)
    finally:
        STEP2.FACTORFORGE = previous


def test_local_agent_specs_are_bound_verbatim_and_pfvvs_is_not_corr(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, primary, challenger = _bound_aim(tmp_path)

    loaded_primary, loaded_challenger = _load(tmp_path, aim)

    assert loaded_primary == primary
    assert loaded_challenger == challenger
    assert 'corr' not in loaded_primary['raw_formula_text'].lower()
    assert all('corr' not in operator.lower() for operator in loaded_primary['operators'])
    assert loaded_primary['required_inputs'] == ['returns', 'volume']
    assert 'price_to_free_cashflow' not in loaded_primary['raw_formula_text']
    assert 'negative_equal_weight()' in loaded_primary['operators']


@pytest.mark.parametrize(
    'mutate',
    [
        lambda root, aim: aim['local_agent_spec_inputs']['challenger'].update({
            'relative_path': aim['local_agent_spec_inputs']['primary']['relative_path'],
            'sha256': aim['local_agent_spec_inputs']['primary']['sha256'],
        }),
        lambda root, aim: aim['local_agent_spec_inputs']['primary'].update({
            'relative_path': '../outside.json',
        }),
        lambda root, aim: aim['local_agent_spec_inputs']['primary'].update({
            'relative_path': 'objects/local_agent_specs/missing.json',
        }),
        lambda root, aim: aim['local_agent_spec_inputs']['primary'].update({
            'sha256': '0' * 64,
        }),
        lambda root, aim: aim['local_agent_spec_inputs']['primary'].update({
            'identity': {'report_id': REPORT_ID, 'factor_id': FACTOR_ID, 'route': 'challenger'},
        }),
    ],
    ids=['same-file', 'escape', 'missing', 'hash-mismatch', 'identity-mismatch'],
)
def test_local_agent_spec_refs_fail_closed(tmp_path, monkeypatch, mutate):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, _, _ = _bound_aim(tmp_path)
    mutate(tmp_path, aim)

    with pytest.raises(SystemExit):
        _load(tmp_path, aim)


def test_local_agent_spec_symlink_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, _, _ = _bound_aim(tmp_path)
    primary_path = tmp_path / aim['local_agent_spec_inputs']['primary']['relative_path']
    outside = tmp_path.parent / 'outside_primary.json'
    outside.write_bytes(primary_path.read_bytes())
    primary_path.unlink()
    primary_path.symlink_to(outside)

    with pytest.raises(SystemExit):
        _load(tmp_path, aim)


def test_local_routes_require_chief_canonical_core_not_primary_default(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, _, challenger = _bound_aim(tmp_path)
    challenger.update({
        'raw_formula_text': 'TS_STD(RANK(CLOSE), 60)',
        'operators': ['rank()', 'ts_std()'],
        'required_inputs': ['close'],
        'rebalance_frequency': 'weekly',
    })
    challenger_ref = aim['local_agent_spec_inputs']['challenger']
    challenger_ref['sha256'] = _write_json(
        tmp_path, challenger_ref['relative_path'], challenger,
    )

    with pytest.raises(SystemExit, match='local route canonical core mismatch') as exc:
        _load(tmp_path, aim)

    message = str(exc.value)
    assert 'challenger.raw_formula_text != chief_canonical_core.raw_formula_text' in message
    assert 'challenger.operators != chief_canonical_core.operators' in message
    assert 'challenger.required_inputs != chief_canonical_core.required_inputs' in message
    assert 'challenger.rebalance_frequency != chief_canonical_core.rebalance_frequency' in message


def test_local_route_textual_steps_may_differ_after_core_agreement(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, primary, challenger = _bound_aim(tmp_path)
    challenger['time_series_steps'] = ['Challenger independently describes the same PF/VV calculation.']
    challenger['cross_sectional_steps'] = ['Challenger independently describes the same negative composite.']
    challenger_ref = aim['local_agent_spec_inputs']['challenger']
    challenger_ref['sha256'] = _write_json(
        tmp_path, challenger_ref['relative_path'], challenger,
    )

    loaded_primary, loaded_challenger = _load(tmp_path, aim)

    assert loaded_primary == primary
    assert loaded_challenger == challenger


def test_local_pdf_without_explicit_specs_cannot_reach_generic_template(monkeypatch):
    aim = {
        'report_id': REPORT_ID,
        'factor_id': FACTOR_ID,
        'source_type': 'pdf_report',
    }
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setattr(STEP2, 'load_alpha_idea_master', lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        'load_source_context',
        lambda *args: pytest.fail('generic PDF path must not run for local IS'),
    )

    with pytest.raises(SystemExit, match='generic PDF templates are disabled'):
        STEP2.run_step2(REPORT_ID, dry_run=True)


def test_nonlocal_cannot_enable_local_agent_specs(tmp_path, monkeypatch):
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY', raising=False)
    aim, _, _ = _bound_aim(tmp_path)

    with pytest.raises(SystemExit, match='FACTORFORGE_LOCAL_IS_ONLY=1'):
        _load(tmp_path, aim)


@pytest.mark.parametrize(
    ('source_type', 'primary_builder', 'challenger_builder'),
    [
        (
            'paper_canonical_formula',
            'build_primary_spec_from_canonical_formula',
            'build_challenger_spec_from_canonical_formula',
        ),
        (
            'natural_language_hypothesis',
            'build_primary_spec_from_hypothesis',
            'build_challenger_spec_from_hypothesis',
        ),
    ],
)
def test_local_non_pdf_source_types_keep_existing_builders(
    monkeypatch, source_type, primary_builder, challenger_builder,
):
    aim = {'report_id': REPORT_ID, 'factor_id': FACTOR_ID, 'source_type': source_type}
    primary = _raw_spec('primary')
    challenger = _raw_spec('challenger')
    captured = {}
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setattr(STEP2, 'load_alpha_idea_master', lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        'load_source_context',
        lambda report_id, aim_arg: {
            'source_type': source_type,
            'primary_thesis': {},
            'challenger_thesis': {},
            'primary_report_map': {},
        },
    )
    monkeypatch.setattr(STEP2, primary_builder, lambda *args: primary)
    monkeypatch.setattr(STEP2, challenger_builder, lambda *args: challenger)
    monkeypatch.setattr(
        STEP2,
        'build_factor_spec_master',
        lambda report_id, aim_arg, primary_arg, consistency, thesis, **kwargs: (
            captured.update(primary=primary_arg) or {'factor_id': primary_arg['factor_id']}
        ),
    )

    STEP2.run_step2(REPORT_ID, dry_run=True)

    assert captured['primary'] is primary


def test_missing_source_semantic_review_blocks_local_spec_consumption(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, _, _ = _bound_aim(tmp_path)
    del aim['source_semantic_review']
    previous = STEP2.FACTORFORGE
    STEP2.FACTORFORGE = tmp_path
    monkeypatch.setattr(STEP2, 'load_alpha_idea_master', lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        'build_factor_spec_master',
        lambda *args: pytest.fail('invalid source semantic review must block before master construction'),
    )
    try:
        with pytest.raises(SystemExit, match='source_semantic_review object required'):
            STEP2.run_step2(REPORT_ID, dry_run=True)
    finally:
        STEP2.FACTORFORGE = previous


def test_local_core_mismatch_blocks_run_step2_before_master(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, _, challenger = _bound_aim(tmp_path)
    challenger['raw_formula_text'] = 'RANK(CLOSE)'
    challenger['operators'] = ['rank()']
    challenger['required_inputs'] = ['close']
    challenger_ref = aim['local_agent_spec_inputs']['challenger']
    challenger_ref['sha256'] = _write_json(
        tmp_path, challenger_ref['relative_path'], challenger,
    )
    previous = STEP2.FACTORFORGE
    STEP2.FACTORFORGE = tmp_path
    monkeypatch.setattr(STEP2, 'load_alpha_idea_master', lambda report_id: aim)
    monkeypatch.setattr(
        STEP2,
        'build_factor_spec_master',
        lambda *args: pytest.fail('core disagreement must block before master construction'),
    )
    try:
        with pytest.raises(SystemExit, match='local route canonical core mismatch'):
            STEP2.run_step2(REPORT_ID, dry_run=True)
    finally:
        STEP2.FACTORFORGE = previous


def test_run_step2_consumes_authored_specs_without_generic_rewrite(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    aim, primary, challenger = _bound_aim(tmp_path)
    captured = {}
    previous = STEP2.FACTORFORGE
    STEP2.FACTORFORGE = tmp_path
    monkeypatch.setattr(STEP2, 'load_alpha_idea_master', lambda report_id: deepcopy(aim))
    monkeypatch.setattr(
        STEP2,
        'build_primary_spec_from_pdf',
        lambda *args: pytest.fail('generic primary PDF template must not run'),
    )
    monkeypatch.setattr(
        STEP2,
        'build_challenger_spec',
        lambda *args: pytest.fail('generic challenger PDF template must not run'),
    )

    def capture_master(report_id, aim_arg, primary_arg, consistency, thesis, **kwargs):
        captured['primary'] = primary_arg
        captured['consistency'] = consistency
        return {'factor_id': primary_arg['factor_id']}

    monkeypatch.setattr(STEP2, 'build_factor_spec_master', capture_master)
    try:
        STEP2.run_step2(REPORT_ID, dry_run=True)
    finally:
        STEP2.FACTORFORGE = previous

    assert captured['primary'] == primary
    assert captured['consistency']['factor_id'] == FACTOR_ID
    assert captured['consistency']['source_subject_routing']['source_semantic_match'] is True
    assert captured['primary']['raw_formula_text'] == primary['raw_formula_text']
    assert captured['primary']['raw_formula_text'] == challenger['raw_formula_text']
    assert 'corr' not in captured['primary']['raw_formula_text'].lower()
