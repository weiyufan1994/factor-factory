from __future__ import annotations

import importlib.util
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
