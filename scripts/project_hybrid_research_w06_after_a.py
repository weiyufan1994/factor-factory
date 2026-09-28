#!/usr/bin/env python3
"""Project a real independent W06-A response into an engineering request.

This script does not run search and does not create formal Step2/Step6 objects.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import write_json_atomic


CASE_ID = "W06_SYNTH_DIRECTED_SHOCK_RESPONSE_A_V1"
REPORT_ID = "hybrid-w06-case-a"
RESPONSE_REQUIRED = {
    "contract_version",
    "case_id",
    "researcher_identity",
    "decision",
    "economic_mechanism_candidates",
    "public_derivation_record",
    "mathematical_scope",
    "distinguishing_predictions",
    "non_identification_risks",
    "unknowns",
    "failure_conditions",
    "next_experiment",
    "unsupported_but_reasonable_mechanisms",
    "overclaim_guard",
}
SCOPE_REQUIRED = {
    "derivation_ref",
    "mathematical_object",
    "domain",
    "initial_state",
    "clock",
    "missing_value_policy",
    "observation_map",
    "allowed_transformations",
    "allowed_response_families",
    "allowed_research_actions",
    "current_gap",
}
SEARCH_REQUIRED = {
    "allowed_rates",
    "allowed_scales",
    "generations",
    "population_size",
    "max_evaluations",
    "max_attempts",
    "seed",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--researcher-response", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    args = parser.parse_args()

    case_dir = args.case_dir.expanduser().resolve()
    response_path = args.researcher_response.expanduser().resolve()
    workspace = args.workspace_root.expanduser().resolve()
    visible_path = case_dir / "VISIBLE_FIT_DATA.json"
    response = _load(response_path)
    visible = _load(visible_path)
    _validate_response(response)
    if visible.get("case_id") != CASE_ID:
        raise ValueError("visible FitData case_id mismatch")

    response_sha = sha256(response_path.read_bytes()).hexdigest()
    visible_sha = sha256(visible_path.read_bytes()).hexdigest()
    receipt_path = workspace / "identity/w06_A_projection_receipt.json"
    receipt: dict[str, Any] = {
        "contract_version": "hybrid_w06_a_projection_receipt_v1",
        "case_id": CASE_ID,
        "report_id": REPORT_ID,
        "engineering_fixture": True,
        "formal_authority": False,
        "researcher_response": {"path": str(response_path), "sha256": response_sha},
        "visible_fit_data": {"path": str(visible_path), "sha256": visible_sha},
        "decision": response["decision"],
    }
    if response["decision"] != "proceed":
        receipt["status"] = "stopped_before_search"
        receipt["reason"] = "independent A did not authorize bounded development search"
        write_json_atomic(receipt_path, receipt)
        print(json.dumps({"status": receipt["status"], "receipt_path": str(receipt_path)}, indent=2))
        return

    scope = response["mathematical_scope"]
    unsupported = _engine_scope_reasons(scope)
    if unsupported:
        receipt["status"] = "stopped_engine_scope_unsupported"
        receipt["unsupported_reasons"] = unsupported
        write_json_atomic(receipt_path, receipt)
        print(json.dumps({"status": receipt["status"], "receipt_path": str(receipt_path)}, indent=2))
        return

    search = response.get("search_authorization")
    _validate_search(search)
    run_id = f"w06-a-{response_sha[:12]}"
    request = {
        "contract_version": "hybrid_research_request_v1",
        "report_id": REPORT_ID,
        "run_id": run_id,
        "handoff_stage": "step2",
        "split": "development",
        "fit_data": visible["fit_data"],
        "derivation_scope": {
            **scope,
            "distinguishing_predictions": response["distinguishing_predictions"],
        },
        "schedule_state": {
            "episode_index": 0,
            "explore_allocations": 0,
            "exploit_allocations": 0,
        },
        "search_config": search,
        "researcher_A_binding": {
            "response_path": str(response_path),
            "response_sha256": response_sha,
            "case_visible_fit_data_sha256": visible_sha,
        },
    }
    if response.get("response_semantics") is not None:
        request["response_semantics"] = response["response_semantics"]
    if response.get("implementation_evidence") is not None:
        request["implementation_evidence"] = response["implementation_evidence"]
    request_path = workspace / "identity/hybrid_research_request.json"
    _write_engineering_objects(workspace, response, response_sha, request_path)
    write_json_atomic(request_path, request)
    receipt.update(
        status="ready_for_explicit_ultimate_opt_in",
        run_id=run_id,
        request_path=str(request_path),
        request_sha256=sha256(request_path.read_bytes()).hexdigest(),
    )
    write_json_atomic(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "request_path": str(request_path),
                "receipt_path": str(receipt_path),
                "next_command": (
                    f"python scripts/run_factorforge_ultimate.py --report-id {REPORT_ID} "
                    f"--factorforge-root {workspace} --local-is-only "
                    f"--hybrid-research-adapter-only --hybrid-research-request {request_path}"
                ),
            },
            indent=2,
        )
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_response(response: dict[str, Any]) -> None:
    missing = RESPONSE_REQUIRED - response.keys()
    if missing:
        raise ValueError(f"A response missing fields: {sorted(missing)}")
    if response.get("contract_version") != "hybrid_w06_researcher_a_response_v1":
        raise ValueError("A response contract_version mismatch")
    if response.get("case_id") != CASE_ID:
        raise ValueError("A response case_id mismatch")
    identity = response.get("researcher_identity")
    if not isinstance(identity, dict) or identity.get("independent_of_implementation_author") is not True:
        raise ValueError("A response must identify a genuinely independent researcher")
    if response.get("decision") not in {"proceed", "revise", "stop"}:
        raise ValueError("A decision must be proceed, revise, or stop")
    public_derivation = response.get("public_derivation_record")
    if not isinstance(public_derivation, str) or len(public_derivation.strip()) < 80:
        raise ValueError("A response requires a substantive public_derivation_record")
    scope = response.get("mathematical_scope")
    if not isinstance(scope, dict) or SCOPE_REQUIRED - scope.keys():
        raise ValueError("A mathematical_scope is incomplete")
    for field, minimum in (
        ("economic_mechanism_candidates", 2),
        ("distinguishing_predictions", 2),
        ("non_identification_risks", 1),
        ("unknowns", 1),
        ("failure_conditions", 1),
        ("overclaim_guard", 1),
    ):
        values = response.get(field)
        if not isinstance(values, list) or len(values) < minimum or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"A response field {field} is incomplete")


def _engine_scope_reasons(scope: dict[str, Any]) -> list[str]:
    exact = {
        "mathematical_object": "causal kernels",
        "domain": "finite signed impulses",
        "initial_state": "zero",
        "clock": "event",
        "missing_value_policy": "missing is not zero",
        "observation_map": "signed J to y",
    }
    reasons = [f"unsupported {key}: {scope.get(key)!r}" for key, value in exact.items() if scope.get(key) != value]
    if "causal convolution" not in scope.get("allowed_transformations", []):
        reasons.append("causal convolution was not authorized")
    if "transient_exponential_kernel" not in scope.get("allowed_response_families", []):
        reasons.append("transient exponential kernel was not authorized")
    if "parameter_search" not in scope.get("allowed_research_actions", []):
        reasons.append("parameter search was not authorized")
    return reasons


def _validate_search(search: Any) -> None:
    if not isinstance(search, dict) or SEARCH_REQUIRED - search.keys():
        raise ValueError("proceed requires a complete search_authorization")
    for field in ("allowed_rates", "allowed_scales"):
        values = search[field]
        if not isinstance(values, list) or not values or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
            for value in values
        ):
            raise ValueError(f"invalid search domain: {field}")
    bounds = {
        "generations": (1, 4),
        "population_size": (3, 12),
        "max_evaluations": (1, 16),
        "max_attempts": (1, 32),
    }
    for field, (lower, upper) in bounds.items():
        value = search[field]
        if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
            raise ValueError(f"search budget outside bounded range: {field}")
    if not isinstance(search["seed"], int) or isinstance(search["seed"], bool):
        raise ValueError("search seed must be an integer")


def _write_engineering_objects(
    workspace: Path,
    response: dict[str, Any],
    response_sha: str,
    request_path: Path,
) -> None:
    binding = {
        "researcher_A_response_sha256": response_sha,
        "engineering_fixture": True,
        "formal_authority": False,
    }
    objects = {
        workspace / "objects/research_journal" / f"research_journal__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            **binding,
            "status": "awaiting_explicit_hybrid_opt_in",
        },
        workspace / "objects/factor_spec_master" / f"factor_spec_master__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            **binding,
            "mechanism_conditioned_measurement_program": {
                "model_selection": {
                    "status": "candidate_scope_from_independent_A_not_formal_step2",
                    "mathematical_object": response["mathematical_scope"]["mathematical_object"],
                    "request_path": str(request_path),
                }
            },
        },
        workspace / "objects/research_protocol" / f"approach_registry__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            **binding,
            "approaches": [{
                "id": "independent-A-bounded-search-candidate",
                "status": "engineering_candidate_not_formal_approval",
                "current_gap": response["mathematical_scope"]["current_gap"],
            }],
        },
        workspace / "objects/handoff" / f"handoff_to_step3__{REPORT_ID}.json": {
            "report_id": REPORT_ID,
            **binding,
            "status": "engineering_fixture_not_formal_step2_handoff",
        },
    }
    for path, payload in objects.items():
        if path.exists():
            raise ValueError(f"refusing to overwrite existing projection object: {path}")
        write_json_atomic(path, payload)


if __name__ == "__main__":
    main()
