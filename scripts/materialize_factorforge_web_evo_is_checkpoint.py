#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.web_factor_proof import (  # noqa: E402
    materialize_web_evo_is_checkpoint,
)
from factor_factory.console.web_research_plan import (  # noqa: E402
    resolve_report_scoped_web_research_plan,
    validate_materialized_web_research,
)
from factor_factory.oos_exposure_incident import (  # noqa: E402
    oos_exposure_private_registry_guard,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the EVO V2 purged-IS diagnostic checkpoint without "
            "releasing OOS or qualifying a contradiction."
        )
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--plan-path", default=None)
    parser.add_argument("--expected-host-trust-manifest-sha256", default=None)
    parser.add_argument("--host-trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.workspace_root).expanduser().resolve(strict=True)
    trust_root = Path(args.host_trust_root).expanduser().resolve(strict=True)
    explicit_plan = Path(args.plan_path) if args.plan_path else None
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=args.installation_id,
    ) as incident_guard:
        resolved = resolve_report_scoped_web_research_plan(
            root,
            report_id=args.report_id,
            plan_path=explicit_plan,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            incident_trust_root=trust_root,
            incident_installation_id=args.installation_id,
            _incident_guard=incident_guard,
            current_authority=True,
        )
        validate_materialized_web_research(
            root,
            report_id=args.report_id,
            plan_path=explicit_plan,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            incident_trust_root=trust_root,
            incident_installation_id=args.installation_id,
            _incident_guard=incident_guard,
            current_authority=True,
        )
        plan = resolved["plan"]
        allocation = resolved.get("allocation")
        token_hash = (
            str(allocation.get("sealed_token_sha256") or "")
            if isinstance(allocation, dict)
            else None
        )
        result = materialize_web_evo_is_checkpoint(
            workspace_root=root,
            plan=plan,
            oos_release_token_hash=token_hash,
            incident_trust_root=trust_root,
            incident_installation_id=args.installation_id,
            _incident_guard=incident_guard,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
