#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_factorforge_small_batch_canary_closure import (
    BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED,
    BLOCK_CANARY_INPUT_INVALID,
    BLOCK_CANARY_STALE_LEGACY_CERTIFICATE_INVALIDATED,
    CanaryClosureError,
    ROLE_DECISIONS,
    _load_object,
    certificate_invalidation_reason,
    validate_canary_preflight,
    validate_council_result,
    validate_role_result,
)


def validate_certificate_invariants(certificate: Mapping[str, Any]) -> list[str]:
    """Validate only non-authoritative canary-tier invariants.

    This function deliberately does not make a certificate authoritative.  No
    closure can PASS until the production runtime supplies the missing trusted
    prompt profile and durable generic session API.
    """

    reasons: list[str] = []
    required = {
        "payload_contract_version": "factorforge_small_batch_canary_closure_v1",
        "status": "COMPLETE",
        "execution_tier": "small_batch_canary",
        "formal_factor_verdict": "NOT_ISSUED",
        "production_eligible": False,
        "official_promotion_allowed": False,
    }
    for key, expected in required.items():
        if certificate.get(key) != expected:
            reasons.append(key)
    if certificate.get("terminal_decision") not in ROLE_DECISIONS:
        reasons.append("terminal_decision")
    return reasons


def reject_unsupported_certificate(
    certificate: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    reasons = validate_certificate_invariants(certificate)
    if reasons:
        raise CanaryClosureError(
            BLOCK_CANARY_INPUT_INVALID
            + ":certificate_invariants:"
            + ",".join(reasons)
        )
    if preflight.get("formal_factor_verdict") != "NOT_ISSUED":
        raise CanaryClosureError(
            BLOCK_CANARY_INPUT_INVALID + ":preflight_formal_factor_verdict"
        )
    # A Host signature over an old local-session projection cannot repair the
    # missing trusted prompt/termination lineage.  Never print PASS here.
    raise CanaryClosureError(
        BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED
        + ":certificate_validation_unavailable_without_trusted_session_lineage"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay small-batch and current Research Org evidence, but reject "
            "all closure certificates until the trusted container prompt profile exists."
        )
    )
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--pre-metric-manifest", required=True)
    parser.add_argument("--org-validation", required=True)
    parser.add_argument("--org-private-root", required=True)
    parser.add_argument("--trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    args = parser.parse_args()

    try:
        workspace = Path(args.workspace_root).expanduser().resolve(strict=True)
        certificate_candidate = Path(args.certificate).expanduser()
        if certificate_candidate.is_symlink():
            raise CanaryClosureError(
                BLOCK_CANARY_INPUT_INVALID + ":certificate_symlink"
            )
        certificate_path = certificate_candidate.resolve(strict=True)
        certificate = _load_object(certificate_path, label="certificate")
        invalidation_reason = certificate_invalidation_reason(
            workspace=workspace,
            certificate_path=certificate_path,
        )
        if invalidation_reason is not None:
            raise CanaryClosureError(
                BLOCK_CANARY_STALE_LEGACY_CERTIFICATE_INVALIDATED
                + ":"
                + invalidation_reason
            )
        # For a certificate not already permanently invalidated, both the
        # sample and exact current organization are replayed before any further
        # evaluation. This validator launches no session.
        preflight = validate_canary_preflight(
            workspace=workspace,
            metrics_path=Path(args.metrics),
            panel_path=Path(args.panel),
            manifest_path=Path(args.pre_metric_manifest),
            org_validation_path=Path(args.org_validation),
            org_private_root=Path(args.org_private_root),
            trust_root=Path(args.trust_root),
            installation_id=args.installation_id,
        )
        reject_unsupported_certificate(certificate, preflight)
    except (CanaryClosureError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
