#!/usr/bin/env python3
"""Run the opt-in hybrid-research bridge on a bounded engineering fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.hybrid_research.decision import ScheduleState
from factor_factory.hybrid_research.gp_adapter import evaluate_program
from factor_factory.hybrid_research.journal_adapter import run_hybrid_episode
from factor_factory.hybrid_research.synthetic import hidden_recovery_mse, make_response_scenario
from factor_factory.hybrid_research.variation import DerivationScope
from factor_factory.runtime_context import write_json_atomic


REPORT_ID = "hybrid-d04-engineering"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--run-id", default="engineering-run-001")
    parser.add_argument("--enable", action="store_true", help="opt in; default is no-op")
    parser.add_argument(
        "--bootstrap-engineering-fixture",
        action="store_true",
        help="create bounded non-market Ultimate-shaped inputs when enabled",
    )
    parser.add_argument("--split", choices=("development", "final", "confirmation"), default="development")
    args = parser.parse_args()
    root = args.workspace_root.expanduser().resolve()
    if args.enable and args.bootstrap_engineering_fixture:
        _bootstrap(root)

    scope = _scope()
    fit_data, hidden_truth = make_response_scenario(
        scenario="two_scale", seed=20260927, length=24, noise_scale=0.01
    )
    outcome = run_hybrid_episode(
        workspace_root=root,
        report_id=REPORT_ID,
        run_id=args.run_id,
        fit_data=fit_data,
        scope=scope,
        schedule_state=ScheduleState(7, 2, 5),
        handoff_stage="step2",
        enabled=args.enable,
        split=args.split,
        seed=6,
    )
    candidate_engineering_path = (
        root
        / "objects/hybrid_research_engineering"
        / f"hidden_evaluation__{REPORT_ID}__{args.run_id}.json"
    )
    engineering_path = candidate_engineering_path if candidate_engineering_path.is_file() else None
    if outcome.search_result is not None:
        selected = outcome.search_result.selected
        engineering_path = candidate_engineering_path
        hidden_evaluation = {
            "contract_version": "hybrid_research_engineering_evaluation_v1",
            "non_researcher_fixture": True,
            "run_id": args.run_id,
            "hidden_model_label": hidden_truth.model_label,
            "hidden_terms": hidden_truth.terms,
            "recovery_mse": (
                hidden_recovery_mse(evaluate_program(selected.program, fit_data), hidden_truth)
                if selected is not None
                else None
            ),
        }
        write_json_atomic(engineering_path, hidden_evaluation)
    print(
        json.dumps(
            {
                "enabled": outcome.enabled,
                "status": outcome.status,
                "resumed": outcome.resumed,
                "input_identity": outcome.input_identity,
                "journal_path": outcome.journal_path,
                "researcher_material_path": outcome.researcher_material_path,
                "engineering_hidden_evaluation_path": str(engineering_path) if engineering_path else None,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _bootstrap(root: Path) -> None:
    artifacts = {
        root / "objects/research_journal" / f"research_journal__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            "engineering_fixture": True,
            "existing_field": "preserve-me",
        },
        root / "objects/factor_spec_master" / f"factor_spec_master__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            "engineering_fixture": True,
            "mechanism_conditioned_measurement_program": {
                "model_selection": {
                    "selected_model": "causal_kernel_response",
                    "selection_status": "fixture_only",
                }
            },
        },
        root / "objects/research_protocol" / f"approach_registry__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            "engineering_fixture": True,
            "approaches": [{"id": "bounded-response-gp", "status": "engineering_only"}],
        },
        root / "objects/handoff" / f"handoff_to_step3__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            "engineering_fixture": True,
            "status": "existing_fixture_handoff",
        },
    }
    for path, payload in artifacts.items():
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if not current.get("engineering_fixture"):
                raise RuntimeError(f"refusing to overwrite non-fixture artifact: {path}")
            continue
        write_json_atomic(path, payload)


def _scope() -> DerivationScope:
    return DerivationScope(
        "engineering:response-v1",
        "causal kernels",
        "finite signed impulses",
        "zero",
        "event",
        "missing is not zero",
        "signed J to y",
        ("causal convolution", "linear superposition"),
        ("temporary response decays", "two scales separate fast and slow response"),
        "number of response scales unknown",
        ("transient_exponential_kernel", "permanent_component", "two_scale_superposition"),
        ("parameter_search", "structure_search"),
    )


if __name__ == "__main__":
    main()
