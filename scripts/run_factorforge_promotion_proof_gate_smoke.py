#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_conjecture import research_protocol_paths, write_json
from factor_factory.research_proof import factor_proof_certificate_path
from scripts.run_factorforge_factor_proof_smoke import valid_certificate
from scripts.run_factorforge_research_protocol_smoke import (
    REPORT_ID as PROTOCOL_SMOKE_REPORT_ID,
    valid_approaches,
    valid_conjecture,
    valid_counterexamples,
    valid_obligations,
    valid_state,
)
from scripts.run_step6_intelligence_smoke import (
    write_current_agent_memo_fixture,
    write_fixture,
)


REPORT_ID = "STEP6_PROMOTION_FACTOR_PROOF_GATE_SMOKE"
FACTOR_ID = "SMOKE_PROMOTE"


def replace_identity(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_identity(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_identity(item) for item in value]
    if value == PROTOCOL_SMOKE_REPORT_ID:
        return REPORT_ID
    if value == "SMOKE_FACTOR":
        return FACTOR_ID
    return value


def main() -> int:
    root = Path("/tmp/factorforge_promotion_proof_gate_smoke")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)

    write_fixture(
        root,
        REPORT_ID,
        kind="strong_mechanism_support",
        factor_id=FACTOR_ID,
    )
    write_current_agent_memo_fixture(root, REPORT_ID)
    paths = research_protocol_paths(root, REPORT_ID)
    write_json(paths["state"], replace_identity(valid_state()))
    write_json(paths["conjecture"], replace_identity(valid_conjecture()))
    write_json(paths["approaches"], replace_identity(valid_approaches()))
    write_json(
        paths["obligations"],
        replace_identity(valid_obligations(root)),
    )
    write_json(
        paths["counterexamples"],
        replace_identity(valid_counterexamples(root)),
    )

    proof_output = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json"
    )
    command = [
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id",
        REPORT_ID,
        "--start-step",
        "6",
        "--end-step",
        "6",
        "--skip-researcher-packets",
        "--factorforge-root",
        str(root),
        "--allow-legacy-global-runtime",
        "--council-mode",
        "off",
        "--proof-output",
        str(proof_output),
    ]
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    env["FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL"] = "1"
    env["FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT"] = "1"
    process = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    proof = (
        json.loads(proof_output.read_text(encoding="utf-8"))
        if proof_output.is_file()
        else {}
    )
    output = "\n".join(
        [
            process.stdout,
            process.stderr,
            json.dumps(proof, ensure_ascii=False),
        ]
    )
    official_path = (
        root
        / "objects"
        / "factor_library_official"
        / f"factor_record__{REPORT_ID}.json"
    )
    prewrite_path = (
        root
        / "objects"
        / "validation"
        / f"step6_prewrite_block__{REPORT_ID}.json"
    )
    official_absent_before_certificate = not official_path.exists()
    negative_ok = (
        process.returncode != 0
        and "BLOCK_FACTORFORGE_PROMOTION_FACTOR_PROOF_MISSING" in output
        and prewrite_path.is_file()
        and official_absent_before_certificate
    )
    certificate = valid_certificate(
        root,
        claim_class="information_rent",
        report_id=REPORT_ID,
        factor_id=FACTOR_ID,
    )
    write_json(factor_proof_certificate_path(root, REPORT_ID), certificate)
    obligations = replace_identity(valid_obligations(root))
    missing_component = deepcopy(obligations)
    for row in missing_component.get("obligations") or []:
        if row.get("obligation_kind") == "component_ablation":
            row["status"] = "open"
            row["status_source"] = "researcher"
            row["evidence_refs"] = []
    write_json(paths["obligations"], missing_component)
    component_block_output = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}__component_block.json"
    )
    component_block_command = [*command[:-1], str(component_block_output)]
    component_block_process = subprocess.run(
        component_block_command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    component_block_text = "\n".join(
        [
            component_block_process.stdout,
            component_block_process.stderr,
            (
                prewrite_path.read_text(encoding="utf-8")
                if prewrite_path.is_file()
                else ""
            ),
        ]
    )
    no_revision_component_gate_ok = (
        component_block_process.returncode != 0
        and "BLOCK_FACTORFORGE_PROMOTION_WITHOUT_VERIFIED_COMPONENT_ABLATION"
        in component_block_text
        and not official_path.exists()
    )
    write_json(paths["obligations"], obligations)
    positive_proof_output = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}__positive.json"
    )
    positive_command = [*command[:-1], str(positive_proof_output)]
    positive_process = subprocess.run(
        positive_command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    positive_ok = positive_process.returncode == 0 and official_path.is_file()
    ok = negative_ok and no_revision_component_gate_ok and positive_ok
    result = {
        "verdict": "ACCEPT" if ok else "BLOCK",
        "missing_proof_returncode": process.returncode,
        "expected_block_token_present": (
            "BLOCK_FACTORFORGE_PROMOTION_FACTOR_PROOF_MISSING" in output
        ),
        "prewrite_block_exists": prewrite_path.is_file(),
        "official_record_absent_before_certificate": (
            official_absent_before_certificate
        ),
        "accepted_proof_returncode": positive_process.returncode,
        "no_revision_missing_component_returncode": (
            component_block_process.returncode
        ),
        "no_revision_component_gate_blocks_official": (
            no_revision_component_gate_ok
        ),
        "official_record_written_after_accepted_certificate": official_path.is_file(),
        "production_research_started": False,
        "worker_started": False,
        "clean_data_mutated": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not ok:
        print(process.stdout)
        print(process.stderr, file=sys.stderr)
        print(positive_process.stdout)
        print(positive_process.stderr, file=sys.stderr)
        return 1
    print("FACTORFORGE_PROMOTION_PROOF_GATE_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
