"""The legacy advisory adapter consumes the installed library, not a CLI module."""
import json
from pathlib import Path

import pytest

from factor_factory import epistemic_kernel_inputs as inputs
from factor_factory import epistemic_ultimate_shadow as shadow
from factor_factory import epistemic_ultimate_source_first_bridge as bridge
from scripts import build_factorforge_epistemic_kernel_offline_candidate as cli


def _input():
    path = Path(__file__).resolve().parents[1] / 'examples/factorforge_epistemic_kernel_wavelet_demo_input.json'
    payload = json.loads(path.read_text())
    payload['diagnosis_inputs'] = None
    payload['real_knowledge_inputs'] = None
    payload['retrieval_corpus_objects'] = None
    payload['session_scope_secret_hex'] = None
    return payload


def test_all_callers_use_one_input_projection_and_builder():
    assert cli.build_candidate is shadow.build_candidate is bridge.build_candidate is inputs.build_candidate
    assert cli.epistemic_kernel_composition_inputs is shadow.epistemic_kernel_composition_inputs
    assert cli.validate_epistemic_kernel_input_payload is inputs.validate_epistemic_kernel_input_payload
    payload = _input()
    projected = inputs.epistemic_kernel_composition_inputs(payload)
    assert projected['source_inputs']['source_bytes'] == payload['source_text'].encode('utf-8')
    assert projected['diagnosis_inputs'] is None
    assert projected['session_scope_secret'] is None
    assert inputs.validate_epistemic_kernel_input_payload(payload) is payload


@pytest.mark.parametrize('case', ['extra_field', 'empty_source', 'secret_without_retrieval'])
def test_library_and_cli_reject_the_same_invalid_input(case):
    payload = _input()
    if case == 'extra_field':
        payload['unexpected'] = True
    elif case == 'empty_source':
        payload['source_text'] = ''
    else:
        payload['session_scope_secret_hex'] = '1' * 64
    with pytest.raises(inputs.OfflineCandidateCliError) as native:
        inputs.epistemic_kernel_composition_inputs(payload)
    with pytest.raises(cli.OfflineCandidateCliError) as historical:
        cli.epistemic_kernel_composition_inputs(payload)
    assert str(native.value) == str(historical.value)
