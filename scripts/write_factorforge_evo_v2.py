#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_v2 import (
    BLOCK_EVO_V2_INVALID,
    EvoV2Error,
    artifact_sha256,
    load_json_object,
    materialize_evo_v2_bundle,
)
from factor_factory.evo_staging import (
    STAGES,
    materialize_evo_v2_stage,
)


FULL_BUNDLE_STAGE = "full-bundle"


def _required_path(
    parser: argparse.ArgumentParser,
    value: str | None,
    option: str,
) -> Path:
    if not value:
        parser.error(f"{option} is required for the selected stage")
    try:
        return Path(value).expanduser().resolve(strict=True)
    except OSError as exc:
        parser.error(f"{option} cannot be resolved: {type(exc).__name__}")


def _required_value(
    parser: argparse.ArgumentParser,
    value: str | None,
    option: str,
) -> str:
    if not value:
        parser.error(f"{option} is required for the selected stage")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and deterministically materialize Agent-authored Factor Forge "
            "EVO V2 research contracts. This command never invents a contradiction, "
            "mechanism, economic story, experience mapping, or factor verdict."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument(
        "--stage",
        choices=[FULL_BUNDLE_STAGE, *sorted(STAGES)],
        default=FULL_BUNDLE_STAGE,
        help=(
            "Use full-bundle for the legacy terminal five-artifact writer, or "
            "one Host-CAS stage so future artifacts are never required early."
        ),
    )
    parser.add_argument("--feedback-ledger")
    parser.add_argument("--mechanism-delta")
    parser.add_argument("--economic-backprojection")
    parser.add_argument("--experience-transfer-bundle")
    parser.add_argument("--transfer-use-receipt")
    parser.add_argument(
        "--council-proposal",
        help=(
            "Validated Council proposal carrying either the MINIMAL mechanism "
            "delta/backprojection or the closed NO_DERIVED_LAW proof."
        ),
    )
    parser.add_argument(
        "--expected-lifecycle-parent-sha256",
        "--expected-lifecycle-parent-content-sha256",
        dest="expected_lifecycle_parent_sha256",
        help=(
            "SHA-256 identity of the complete parent lifecycle payload. The "
            "older parent-content spelling remains an input alias."
        ),
    )
    parser.add_argument("--expected-lifecycle-content-sha256")
    parser.add_argument(
        "--expected-staging-content-sha256",
        help="Use ABSENT for admit-feedback; then use the prior PASS output value.",
    )
    args = parser.parse_args()

    try:
        root = Path(args.workspace_root).expanduser().resolve(strict=True)
        if args.stage == FULL_BUNDLE_STAGE:
            source_paths = {
                "feedback_ledger": _required_path(
                    parser, args.feedback_ledger, "--feedback-ledger"
                ),
                "mechanism_delta": _required_path(
                    parser, args.mechanism_delta, "--mechanism-delta"
                ),
                "economic_backprojection": _required_path(
                    parser,
                    args.economic_backprojection,
                    "--economic-backprojection",
                ),
                "experience_transfer_bundle": _required_path(
                    parser,
                    args.experience_transfer_bundle,
                    "--experience-transfer-bundle",
                ),
                "transfer_use_receipt": _required_path(
                    parser,
                    args.transfer_use_receipt,
                    "--transfer-use-receipt",
                ),
            }
            artifacts = {
                name: load_json_object(path) for name, path in source_paths.items()
            }
            written = materialize_evo_v2_bundle(
                artifacts,
                workspace_root=root,
                report_id=args.report_id,
            )
            result = {
                "stage": FULL_BUNDLE_STAGE,
                "written": {
                    name: {
                        "path": str(path),
                        "sha256": artifact_sha256(artifacts[name]),
                    }
                    for name, path in written.items()
                },
                "current_state": artifacts["feedback_ledger"]["current_state"],
            }
        else:
            source_by_stage = {
                "admit-feedback": (
                    "feedback_ledger",
                    args.feedback_ledger,
                    "--feedback-ledger",
                ),
                "admit-council-outcome": (
                    "council_proposal",
                    args.council_proposal,
                    "--council-proposal",
                ),
                "admit-transfer": (
                    "experience_transfer_bundle",
                    args.experience_transfer_bundle,
                    "--experience-transfer-bundle",
                ),
                "record-use": (
                    "transfer_use_receipt",
                    args.transfer_use_receipt,
                    "--transfer-use-receipt",
                ),
            }
            source_name, source_value, source_option = source_by_stage[args.stage]
            source_path = _required_path(parser, source_value, source_option)
            source_payload = load_json_object(source_path)
            stage_inputs = {source_name: source_payload}
            result = materialize_evo_v2_stage(
                workspace_root=root,
                report_id=args.report_id,
                stage=args.stage,
                expected_lifecycle_parent_sha256=_required_value(
                    parser,
                    args.expected_lifecycle_parent_sha256,
                    "--expected-lifecycle-parent-sha256",
                ),
                expected_lifecycle_content_sha256=_required_value(
                    parser,
                    args.expected_lifecycle_content_sha256,
                    "--expected-lifecycle-content-sha256",
                ),
                expected_staging_content_sha256=_required_value(
                    parser,
                    args.expected_staging_content_sha256,
                    "--expected-staging-content-sha256",
                ),
                **stage_inputs,
            )
    except (OSError, EvoV2Error) as exc:
        if isinstance(exc, EvoV2Error):
            token = exc.token
            reasons = list(exc.reasons)
        else:
            token = BLOCK_EVO_V2_INVALID
            reasons = [f"filesystem_error:{type(exc).__name__}:{exc}"]
        print(
            json.dumps(
                {
                    "verdict": "BLOCK",
                    "block_token": token,
                    "report_id": args.report_id,
                    "block_reasons": reasons,
                    "producer_policy": "agent_authored_no_semantic_fallback",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
                {
                    "verdict": "PASS",
                    "report_id": args.report_id,
                    **result,
                    "authority": "advisory_research_only_no_factor_or_mutation_authority",
                    "producer_policy": "agent_authored_no_semantic_fallback",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
