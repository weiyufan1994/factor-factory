#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_obligation_verifier import (
    validate_component_obligation_report,
)
from scripts.run_factorforge_research_protocol_smoke import (
    component_obligation_evidence,
)


def main() -> int:
    root = Path("/tmp/factorforge_component_obligation_smoke")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    cases: dict[str, bool] = {}
    references: dict[str, dict] = {}
    for kind in ("measurement_validity", "component_ablation"):
        reference, _, _ = component_obligation_evidence(
            root,
            obligation_id=kind,
            obligation_kind=kind,
        )
        references[kind] = reference
        report = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
        cases[f"{kind}_replays"] = not validate_component_obligation_report(
            report,
            workspace_root=root,
        )

    component_report = json.loads(
        (root / references["component_ablation"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    forged = deepcopy(component_report)
    forged["metrics"]["rank_ic_delta"] = 0.999999
    forged_reasons = validate_component_obligation_report(
        forged,
        workspace_root=root,
    )
    cases["hand_authored_metric_change_blocks"] = any(
        "COMPONENT_EVIDENCE_REPLAY_MISMATCH:metrics" in reason
        for reason in forged_reasons
    )

    panel_path = root / component_report["source_panel_ref"]
    changed_panel = pd.read_csv(panel_path)
    changed_panel.loc[0, "forward_return"] += 1.0
    changed_panel.to_csv(panel_path, index=False)
    changed_reasons = validate_component_obligation_report(
        component_report,
        workspace_root=root,
    )
    cases["source_panel_change_blocks"] = any(
        "COMPONENT_EVIDENCE_REPLAY_FAILED:"
        "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_DATASET_HASH_MISMATCH"
        in reason
        for reason in changed_reasons
    )

    failed = [name for name, passed in cases.items() if not passed]
    print(
        json.dumps(
            {
                "verdict": "ACCEPT" if not failed else "BLOCK",
                "failed": failed,
                "cases": cases,
                "production_research_started": False,
                "worker_started": False,
                "clean_data_mutated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if failed:
        return 1
    print("FACTORFORGE_COMPONENT_OBLIGATION_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
