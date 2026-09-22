#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.metric_verifier import (
    VERIFIER_SPEC_VERSION as METRIC_SPEC_VERSION,
    metric_verifier_identities,
)
from factor_factory.evo_oos import validate_oos_release_authorization
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)
from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)
from factor_factory.research_obligation_verifier import (
    VERIFIER_SPEC_VERSION as COMPONENT_SPEC_VERSION,
    component_verifier_identities,
)
from factor_factory.research_release import (
    stable_hash,
    validate_evaluation_release_chain,
    validate_evaluation_release_chain_current,
    validate_observed_oos_window,
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)


def load_json(path: Path) -> Any:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def require_workspace_path(
    root: Path,
    raw_path: str | Path,
    *,
    must_exist: bool,
) -> Path:
    path = Path(raw_path).expanduser().resolve(strict=False)
    if path != root and root not in path.parents:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_PATH_OUTSIDE_WORKSPACE"
        )
    if must_exist and not path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_INPUT_MISSING"
        )
    return path


def freeze_search(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.workspace_root).expanduser().resolve(strict=False)
    trials_path = require_workspace_path(root, args.trials, must_exist=True)
    candidate_space_path = require_workspace_path(
        root, args.candidate_space, must_exist=True
    )
    selected_hypothesis_path = require_workspace_path(
        root, args.selected_hypothesis, must_exist=True
    )
    output_path = require_workspace_path(root, args.output, must_exist=False)
    trials = load_json(trials_path)
    if not isinstance(trials, list):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_INVALID"
        )
    return write_search_trial_ledger(
        output_path,
        report_id=args.report_id,
        factor_id=args.factor_id,
        trials=trials,
        candidate_space=load_json(candidate_space_path),
        selected_hypothesis=load_json(selected_hypothesis_path),
        freeze_sequence=args.freeze_sequence,
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def register_threshold(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.workspace_root).expanduser().resolve(strict=False)
    spec_path = require_workspace_path(root, args.spec, must_exist=True)
    spec = load_json(spec_path)
    rules_path = require_workspace_path(
        root, args.decision_rules, must_exist=True
    )
    rules = load_json(rules_path)
    if not isinstance(rules, list):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULES_MISSING"
        )
    threshold_path = resolve_workspace_evidence_path(
        root, spec.get("threshold_registration_ref")
    )
    if threshold_path is None:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_INVALID"
        )
    payload = write_threshold_registration(
        threshold_path,
        workspace_root=root,
        spec=spec,
        decision_rules=rules,
        registration_sequence=args.registration_sequence,
    )
    spec["window_hash"] = stable_hash(spec["window_contract"])
    write_json_atomic(spec_path, spec)
    return {
        "verdict": "PASS",
        "threshold_registration_ref": str(threshold_path.relative_to(root)),
        "threshold_registration_sha256": sha256_file(threshold_path),
        "registration": payload,
    }


def release_oos(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.workspace_root).expanduser().resolve(strict=False)
    trust_root = Path(args.host_trust_root).expanduser().resolve(strict=True)
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=args.installation_id,
    ) as incident_guard:
        return _release_oos_guarded(
            args,
            root=root,
            trust_root=trust_root,
            incident_guard=incident_guard,
        )


def _release_oos_guarded(
    args: argparse.Namespace,
    *,
    root: Path,
    trust_root: Path,
    incident_guard: object,
) -> dict[str, Any]:
    panel = Path(args.panel).expanduser().resolve(strict=False)
    spec_path = require_workspace_path(root, args.spec, must_exist=True)
    spec = load_json(spec_path)
    if spec.get("dataset_snapshot_hash"):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_ALREADY_BOUND"
        )
    authorization_reasons = validate_oos_release_authorization(
        workspace_root=root,
        report_id=str(spec.get("report_id") or ""),
        oos_window=(spec.get("window_contract") or {}).get("oos_window"),
        sealed_token_sha256=(spec.get("window_contract") or {}).get(
            "oos_release_token_hash"
        ),
        incident_trust_root=trust_root,
        incident_installation_id=args.installation_id,
        _incident_guard=incident_guard,
    )
    if authorization_reasons:
        raise ValueError(";".join(authorization_reasons))
    if spec.get("version") == METRIC_SPEC_VERSION:
        identities = metric_verifier_identities(
            workspace_root=root,
            panel_path=panel,
            spec=spec,
        )
    elif spec.get("version") == COMPONENT_SPEC_VERSION:
        identities = component_verifier_identities(
            workspace_root=root,
            panel_path=panel,
            spec=spec,
        )
    else:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
        )
    if spec.get("window_hash") != identities["window_hash"]:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_WINDOW_CHANGED_AFTER_REGISTRATION"
        )
    validate_observed_oos_window(spec["window_contract"], identities)
    threshold_path = resolve_workspace_evidence_path(
        root, spec.get("threshold_registration_ref")
    )
    if threshold_path is None or not threshold_path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_REGISTRATION_MISSING"
        )
    if args.threshold_registration:
        supplied_threshold = Path(
            args.threshold_registration
        ).expanduser().resolve(strict=False)
        if supplied_threshold != threshold_path:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_MISMATCH"
            )
    output = resolve_workspace_evidence_path(
        root,
        spec["window_contract"].get("oos_release_manifest_ref"),
    )
    if output is None:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_PATH_INVALID"
        )
    write_oos_release_manifest(
        output,
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
        release_sequence=args.release_sequence,
        incident_trust_root=trust_root,
        incident_installation_id=args.installation_id,
        _incident_guard=incident_guard,
    )
    threshold_payload = load_json(threshold_path)
    bindings = validate_evaluation_release_chain_current(
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
        threshold_payload=threshold_payload,
        incident_trust_root=trust_root,
        incident_installation_id=args.installation_id,
        _incident_guard=incident_guard,
    )
    spec.update(identities)
    write_json_atomic(spec_path, spec)
    return {
        "verdict": "PASS",
        "identities": identities,
        "release_bindings": bindings,
        "bound_spec": str(spec_path.relative_to(root)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the hash-chained search-freeze and OOS-release "
            "artifacts used by Factor Forge verifier replay."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze-search")
    freeze.add_argument("--workspace-root", required=True)
    freeze.add_argument("--report-id", required=True)
    freeze.add_argument("--factor-id", required=True)
    freeze.add_argument("--trials", required=True)
    freeze.add_argument("--candidate-space", required=True)
    freeze.add_argument("--selected-hypothesis", required=True)
    freeze.add_argument("--output", required=True)
    freeze.add_argument("--freeze-sequence", type=int, default=10)

    register = subparsers.add_parser("register-threshold")
    register.add_argument("--workspace-root", required=True)
    register.add_argument("--spec", required=True)
    register.add_argument("--decision-rules", required=True)
    register.add_argument("--registration-sequence", type=int, default=20)

    release = subparsers.add_parser("release-oos")
    release.add_argument("--workspace-root", required=True)
    release.add_argument("--panel", required=True)
    release.add_argument("--spec", required=True)
    release.add_argument("--threshold-registration")
    release.add_argument("--release-sequence", type=int, default=30)
    release.add_argument("--host-trust-root", required=True)
    release.add_argument("--installation-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze-search":
            result = freeze_search(args)
        elif args.command == "register-threshold":
            result = register_threshold(args)
        else:
            result = release_oos(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
