from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py"
SPEC = importlib.util.spec_from_file_location("step6_council_phase_visibility", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _route(route_id: str, *, status: str, favored: bool) -> dict:
    return {
        "route_id": route_id,
        "route_family": "economic_game",
        "status": status,
        "favored_thesis_visible": favored,
    }


def _task(route: dict, context: dict):
    return MODULE.agent_task(
        "test_agent",
        "test question",
        ["test_tool"],
        "report-test",
        route=route,
        visible_context=context,
    )


def test_closed_historical_blind_routes_do_not_replace_three_active_nonblind_routes():
    routes = [
        _route("historical-blind-1", status="closed", favored=False),
        _route("historical-blind-2", status="closed", favored=False),
        _route("post-result-measurement", status="active", favored=True),
        _route("post-result-null-alias", status="active", favored=True),
        _route("post-result-economic-game", status="active", favored=True),
    ]
    selected = MODULE.select_dispatch_routes(routes)
    assert [route["route_id"] for route in selected] == [
        "post-result-measurement",
        "post-result-null-alias",
        "post-result-economic-game",
    ]


def test_nonblind_task_keeps_formula_context_and_public_selected_model():
    context = {
        "formula_specific_derivation": {"mathematical_object": "public object"},
        "mechanism_conditioned_measurement_program": {
            "selected_model": "publicly disclosed model",
        },
    }
    task = _task(_route("active-nonblind", status="active", favored=True), context)
    assert task["visible_context"] is context
    assert task["visible_context"]["formula_specific_derivation"]


@pytest.mark.parametrize(
    "context",
    [
        {"formula_specific_derivation": {"mathematical_object": "leak"}},
        {"main_agent_mechanism_memo_ref": "objects/main-agent-memo.json"},
        {"main_agent_math_hypothesis": {"mathematical_object": "preferred"}},
        {
            "mechanism_conditioned_measurement_program": {
                "selected_model_authority": {"source": "main_agent"},
            }
        },
    ],
)
def test_blind_task_fails_closed_on_main_agent_thesis_leak(context):
    with pytest.raises(ValueError, match=MODULE.TOKEN_BLIND_CONTEXT_LEAK):
        _task(_route("blind-route", status="active", favored=False), context)


def test_stripped_blind_context_is_valid_and_public_program_is_not_secret():
    context = {
        "factor_family": "public family",
        "mechanism_conditioned_measurement_program": {
            "selected_model": "author-disclosed model",
        },
    }
    task = _task(_route("historical-blind", status="active", favored=False), context)
    assert task["blind_context_policy"]["blind_phase"] is True
    assert task["visible_context"] is context


RID = "VISIBILITY_CLI"
PRIVATE = "ROOT_JUDGMENT_MUST_NOT_REACH_BLIND_READER"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cli(root, script, *args, check=True):
    env = {**os.environ, "FACTORFORGE_ROOT": str(root), "PYTHONPATH": str(ROOT),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(SCRIPT.parent / script),
                             "--report-id", RID, *args], env=env, cwd=ROOT,
                            text=True, capture_output=True, timeout=30)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture
def cli_taskbook(tmp_path):
    from test_factorforge_measurement_program_pipeline import _program

    council = tmp_path / "objects/research_iteration_master/revision_council" / RID
    packet = {
        "report_id": RID, "factor_formula": "sum(returns,20)",
        "implementation_mode": "operator",
        "mechanism_conditioned_measurement_program": _program(),
        "metrics": {"rank_ic_mean": 0.01}, "chart_evidence": {},
        "formula_specific_derivation": {"conclusion": PRIVATE},
        "research_memo": {"mechanism_analysis": {"mechanism_fit": PRIVATE},
                          "revision_strategy": {"primary_failure_signature": PRIVATE}},
        "legacy_mechanism_math_contract": {"conclusion": PRIVATE},
        "mechanism_formula_consistency": {"conclusion": PRIVATE},
        "prior_revision_memory": {"conclusion": PRIVATE},
        "supplemental_research_context": {"content": PRIVATE},
        "loop_research_brief": {"reference": PRIVATE},
        "main_agent_mechanism_memo_ref": PRIVATE,
        "main_agent_math_hypothesis": {"conclusion": PRIVATE},
    }
    _write(council / f"revision_council_packet__{RID}.json", packet)
    _write(tmp_path / "objects/research_iteration_master" / f"research_iteration_master__{RID}.json",
           {"report_id": RID, "factor_id": RID, "research_judgment": {"decision": PRIVATE}})
    _cli(tmp_path, SCRIPT.name, "--executor", "dispatch_manifest", "--runtime-dispatch",
         "codex", "--research-protocol", "off")
    return tmp_path, council, packet


def _dispatch(root, council):
    _cli(root, "build_agentic_council_dispatch_manifest.py")
    path = council / f"dispatch_manifest__{RID}.json"
    return path, json.loads(path.read_text())


def test_real_cli_projects_blind_and_nonblind_context_through_dispatch(cli_taskbook):
    root, council, source = cli_taskbook
    _, manifest = _dispatch(root, council)
    _cli(root, "validate_agentic_council_dispatch.py")
    _cli(root, "build_agentic_council_manual_dispatch_bundle.py")
    blind_count = nonblind_count = 0
    for task in manifest['agent_tasks']:
        packet = json.loads((root / task['task_packet_path']).read_text())
        context = packet['shared_context']
        assert context['factor_formula'] == source['factor_formula']
        assert context['key_metrics'] == source['metrics']
        assert context['mechanism_conditioned_measurement_program'] == source['mechanism_conditioned_measurement_program']
        assert packet['measurement_program_binding'] == task['measurement_program_binding']
        if task['blind_phase']:
            blind_count += 1
            assert PRIVATE not in json.dumps(packet)
            assert not packet['source_taskbook_path'] and not packet['source_packet_path']
            assignment = council / 'manual_dispatch' / f"assignment__{RID}__{task['task_id']}.md"
            assert PRIVATE not in assignment.read_text()
            assert 'Mark critiques of withheld material as not_visible' in assignment.read_text()
        else:
            nonblind_count += 1
            assert context['formula_specific_derivation'] == source['formula_specific_derivation']
            assert context['main_agent_mechanism_memo_ref'] == PRIVATE
            assert packet['source_packet_path'] and packet['source_taskbook_path']
    assert blind_count == 3 and nonblind_count == 2


def test_dispatch_builder_rejects_nested_thesis_before_writing_any_task(cli_taskbook):
    root, council, _ = cli_taskbook
    path = council / f"agentic_taskbook__{RID}.json"
    taskbook = json.loads(path.read_text())
    blind = next(task for task in taskbook['agent_tasks'] if task['blind_context_policy']['blind_phase'])
    blind['visible_context']['key_metrics']['injected'] = {'preferred_thesis': PRIVATE}
    _write(path, taskbook)
    result = _cli(root, 'build_agentic_council_dispatch_manifest.py', check=False)
    assert result.returncode != 0 and MODULE.TOKEN_BLIND_CONTEXT_LEAK in result.stderr
    assert not (council / 'agent_tasks').exists()
    assert not (council / f'dispatch_manifest__{RID}.json').exists()


@pytest.mark.parametrize('field', [
    'formula_specific_derivation', 'decision', 'mechanism_fit', 'primary_failure_signature',
    'main_agent_mechanism_memo_ref', 'loop_research_brief_ref', 'preferred_thesis',
    'nested_root_thesis', 'source_packet_path', 'source_taskbook_path',
])
def test_final_cli_validator_rejects_reintroduced_root_context_even_with_valid_hash(cli_taskbook, field):
    root, council, _ = cli_taskbook
    manifest_path, manifest = _dispatch(root, council)
    task = next(task for task in manifest['agent_tasks'] if task['blind_phase'])
    packet_path = root / task['task_packet_path']
    packet = json.loads(packet_path.read_text())
    if field.startswith('source_'):
        packet[field] = 'objects/root-material.json'
    elif field == 'nested_root_thesis':
        packet['shared_context']['key_metrics']['injected'] = {'root_thesis': PRIVATE}
    else:
        packet['shared_context'][field] = PRIVATE
    _write(packet_path, packet)
    task['task_packet_sha256'] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    _write(manifest_path, manifest)
    result = _cli(root, 'validate_agentic_council_dispatch.py', check=False)
    assert result.returncode != 0 and MODULE.TOKEN_BLIND_CONTEXT_LEAK in result.stdout
    assert 'TASK_PACKET_HASH_MISMATCH' not in result.stdout
