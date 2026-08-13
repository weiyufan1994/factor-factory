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

from factor_factory.research_conjecture import (
    PROTOCOL_VERSION,
    epistemic_evolution_enabled,
    research_protocol_paths,
    validate_approach_registry,
    validate_counterexample_registry,
    validate_proof_obligation_ledger,
    validate_research_conjecture,
    validate_research_state,
    write_json,
)


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def identity_reasons(
    payload: dict[str, Any],
    *,
    report_id: str,
    artifact: str,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_INPUT_VERSION_INVALID:{artifact}")
    if payload.get("report_id") != report_id:
        reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_INPUT_IDENTITY_MISMATCH:{artifact}")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and atomically materialize agent-authored Factor Forge research "
            "protocol artifacts. This command never invents hypotheses or routes."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--conjecture", required=True)
    parser.add_argument("--approaches", required=True)
    parser.add_argument("--obligations")
    parser.add_argument("--counterexamples")
    args = parser.parse_args()

    root = Path(args.workspace_root).expanduser().resolve(strict=False)
    source_payloads = {
        "state": load_json(args.state),
        "conjecture": load_json(args.conjecture),
        "approaches": load_json(args.approaches),
    }
    if bool(args.obligations) != bool(args.counterexamples):
        print(
            "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_PRE_REVISION_INPUTS_INCOMPLETE",
            file=sys.stderr,
        )
        return 1
    if args.obligations:
        source_payloads["obligations"] = load_json(args.obligations)
        source_payloads["counterexamples"] = load_json(args.counterexamples)

    reasons: list[str] = []
    for name, payload in source_payloads.items():
        reasons.extend(identity_reasons(payload, report_id=args.report_id, artifact=name))
    reasons.extend(validate_research_state(source_payloads["state"]))
    reasons.extend(validate_research_conjecture(source_payloads["conjecture"]))
    reasons.extend(
        validate_approach_registry(source_payloads["approaches"], stage="pre_council")
    )
    if "obligations" in source_payloads:
        reasons.extend(
            validate_proof_obligation_ledger(
                source_payloads["obligations"],
                stage="pre_revision",
                workspace_root=root,
            )
        )
        reasons.extend(
            validate_counterexample_registry(
                source_payloads["counterexamples"],
                stage="pre_revision",
                workspace_root=root,
            )
        )
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "report_id": args.report_id,
                    "block_reasons": reasons,
                    "note": "Inputs are agent-authored; no fallback artifacts were written.",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    paths = research_protocol_paths(root, args.report_id)
    for name, payload in source_payloads.items():
        write_json(paths[name], payload)
    print(
        json.dumps(
            {
                "verdict": "PASS",
                "report_id": args.report_id,
                "written": {
                    **{name: str(paths[name]) for name in source_payloads},
                },
                "producer_policy": "agent_authored_no_deterministic_semantic_fallback",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
