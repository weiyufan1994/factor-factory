"""Local IS must not even probe hosted/OOS window evidence paths."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def step6(tmp_path, monkeypatch):
    # Portable when installed in the repo; an overlay loads its own candidate
    # while PYTHONPATH supplies read-only source dependencies explicitly.
    monkeypatch.setenv('FACTORFORGE_ROOT', str(tmp_path))
    script = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step6/scripts/run_step6.py'
    spec = importlib.util.spec_from_file_location('step6_local_is_window_guard', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _forbid_window_access(step6, monkeypatch):
    touched = []

    class ForbiddenObjectRoot:
        def __truediv__(self, part):
            touched.append(('path', part))
            raise AssertionError('local IS attempted a window OBJ path probe')

    def forbidden_load(path):
        touched.append(('load', str(path)))
        raise AssertionError('local IS attempted to load window evidence')

    monkeypatch.setattr(step6, 'OBJ', ForbiddenObjectRoot())
    monkeypatch.setattr(step6, 'load_json', forbidden_load)
    return touched


def test_local_returns_before_any_window_path_or_json_access(step6, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    touched = _forbid_window_access(step6, monkeypatch)
    assert step6.load_window_evidence('SYNTHETIC_WINDOW_GUARD') == {}
    assert touched == []


@pytest.mark.parametrize('scope', [None, '0'])
def test_nonlocal_reads_existing_synthetic_window_unchanged(step6, tmp_path, monkeypatch, scope):
    if scope is None:
        monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY', raising=False)
    else:
        monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', scope)
    root = tmp_path / 'synthetic-objects'
    path = root / 'window_evidence/window_evidence__SYNTHETIC.json'
    path.parent.mkdir(parents=True)
    payload = {'synthetic_only': True, 'full_is': {'fixture': 'is'}, 'oos': {'fixture': 'not-real-oos'}}
    path.write_text(json.dumps(payload), encoding='utf-8')
    original_bytes = path.read_bytes()
    monkeypatch.setattr(step6, 'OBJ', root)
    original_load = step6.load_json
    loads = []

    def load_json(path):
        loads.append(path)
        return original_load(path)

    monkeypatch.setattr(step6, 'load_json', load_json)
    assert step6.load_window_evidence('SYNTHETIC') == {**payload, 'artifact_path': str(path)}
    assert loads == [path]
    assert path.read_bytes() == original_bytes


def test_iteration_builder_passes_empty_window_to_actual_summary_boundary(step6, monkeypatch):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    touched = _forbid_window_access(step6, monkeypatch)
    monkeypatch.setattr(step6, 'decide', lambda *args: 'needs_human_review')
    monkeypatch.setattr(step6, 'local_reviewers_agree_to_reject', lambda *args: False)
    monkeypatch.setattr(step6, 'derive_strengths_weaknesses', lambda *args: ([], [], [], []))
    monkeypatch.setattr(step6, 'extract_headline_metrics', lambda *args: {})
    observed = []
    original_summary = step6.summarize_window_evidence

    class ReachedSummaryBoundary(Exception):
        pass

    def summarize(window_evidence):
        observed.append(window_evidence)
        assert window_evidence == {}
        assert original_summary(window_evidence) == (
            [], ['formal full_is/is_subsamples/oos window evidence is missing'])
        # Stop before any unrelated retrieval, decision authoring, or writing.
        raise ReachedSummaryBoundary

    monkeypatch.setattr(step6, 'summarize_window_evidence', summarize)
    bundle = {
        'factor_run_master': {'report_id': 'SYNTHETIC_WINDOW_GUARD', 'factor_id': 'SYNTHETIC'},
        'factor_case_master': {}, 'factor_evaluation': {}, 'handoff_to_step6': {},
    }
    with pytest.raises(ReachedSummaryBoundary):
        step6.build_iteration_payload(bundle, {})
    assert observed == [{}]
    assert touched == []
