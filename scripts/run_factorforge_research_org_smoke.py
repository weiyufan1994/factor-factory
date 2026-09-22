#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def expect(
    name: str,
    command: list[str],
    *,
    returncode: int,
    token: str | None = None,
) -> dict[str, object]:
    result = run(command)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != returncode or (token is not None and token not in output):
        raise AssertionError(
            f"{name}: rc={result.returncode}, expected={returncode}, token={token}\n{output}"
        )
    return {"name": name, "status": "PASS", "returncode": result.returncode, "token": token}


def main() -> int:
    root = Path("/tmp/factorforge_research_org_smoke")
    if not str(root).startswith("/tmp/"):
        raise SystemExit("refusing non-/tmp smoke root")
    shutil.rmtree(root, ignore_errors=True)
    runtime = root / "runtime"
    workspace = runtime / "factor_research" / "ORG_SMOKE" / "org_smoke"
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=runtime,
        factor_id="ORG_SMOKE",
        research_id="org_smoke",
        root_report_id="ORG_SMOKE_REPORT",
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    request = {
        "contract_version": "factorforge_console_research_request_v1",
        "job_id": "job_org_smoke",
        "factor_id": "ORG_SMOKE",
        "research_id": "org_smoke",
        "report_id": "ORG_SMOKE_REPORT",
        "title": "Intraday crowding and fundamental constraint",
        "hypothesis": (
            "Minute order-flow pressure may reveal liquidity crowding, while balance-sheet "
            "debt and free cash flow determine which firms become forced sellers."
        ),
        "input_kind": "hypothesis",
        "conversation_snapshot": {
            "messages": [
                {
                    "sequence_no": 1,
                    "role": "user",
                    "content_kind": "hypothesis",
                    "content": (
                        "Minute order-flow pressure may reveal liquidity crowding, while balance-sheet "
                        "debt and free cash flow determine which firms become forced sellers."
                    ),
                }
            ]
        },
    }
    identity = workspace / "identity"
    for name, payload in (
        ("web_research_request.json", request),
        ("web_research_authoring_contract.json", {"status": "seed"}),
        ("factor_knowledge_summary.json", {"cold_start": True}),
        ("data_catalog_summary.json", {"datasets": []}),
    ):
        (identity / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    results: list[dict[str, object]] = []
    results.append(
        expect(
            "build_bundle",
            [
                sys.executable,
                "scripts/build_factorforge_research_org_plan.py",
                "--workspace-root",
                str(workspace),
            ],
            returncode=0,
        )
    )
    results.append(
        expect(
            "validate_bundle",
            [
                sys.executable,
                "scripts/validate_factorforge_research_org.py",
                "--workspace-root",
                str(workspace),
            ],
            returncode=0,
        )
    )
    plan_path = identity / "research_organization_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["routing"]["lead_domain"] != "fundamental":
        raise AssertionError(f"unexpected mixed-route lead: {plan['routing']}")
    if "price_volume" not in plan["routing"]["supporting_domains"]:
        raise AssertionError(f"mixed-domain support route missing: {plan['routing']}")
    if plan["execution_policy"]["single_agent_fallback"] is not False:
        raise AssertionError("single-agent fallback was silently enabled")
    if plan["execution_policy"]["host_is_only_canonical_merger"] is not True:
        raise AssertionError("Host merge authority was not frozen")
    original_hash = plan["plan_sha256"]
    results.append(
        expect(
            "preserve_existing",
            [
                sys.executable,
                "scripts/build_factorforge_research_org_plan.py",
                "--workspace-root",
                str(workspace),
                "--preserve-existing",
            ],
            returncode=0,
        )
    )
    if json.loads(plan_path.read_text(encoding="utf-8"))["plan_sha256"] != original_hash:
        raise AssertionError("preserve-existing mutated the plan")
    plan["workspace_policy"]["result_root"] = "../../outside"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    results.append(
        expect(
            "path_escape_blocks",
            [
                sys.executable,
                "scripts/validate_factorforge_research_org.py",
                "--workspace-root",
                str(workspace),
            ],
            returncode=1,
            token="BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID",
        )
    )
    print(json.dumps({"verdict": "PASS", "results": results}, ensure_ascii=False, indent=2))
    print("FACTORFORGE_RESEARCH_ORG_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
