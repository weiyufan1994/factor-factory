# Phase M Factor Forge Ultimate Loop Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real Factor Forge Ultimate loop orchestrator that repeatedly runs formal Step3B -> Step6 child revisions through Council until promotion, exhaustion, pause-for-agent-results, hard block, or the 10-loop cap.

**Architecture:** Add a thin orchestration layer above the existing `scripts/run_factorforge_ultimate.py`; do not rewrite Step1-6, validators, Council merge, or Step3B generation semantics. The orchestrator must call existing formal wrappers/scripts, record a durable loop proof, and stop only on explicit contract states.

**Tech Stack:** Python stdlib, existing Factor Forge scripts, JSON proof artifacts under `objects/runtime_context/`, `/tmp` smoke fixtures, installed skill sync by `rsync` + `diff -qr`.

---

## Non-Negotiable Constraints

- Do not weaken existing Step1/2/3/4/5/6 validators.
- Do not bypass `scripts/run_factorforge_ultimate.py` for a single formal Step3B -> Step6 pass.
- Do not write Step3B handoff, generated code, official library, or clean data outside existing approved scripts.
- Do not execute program search workers unless the wrapper/Council contract explicitly authorizes them.
- Do not auto-finalize `manual_file` / `dispatch_manifest` Council states; stop with `awaiting_agent_results`.
- Do not silently continue after any validator rc != 0.
- Do not overwrite canonical parent factor artifacts when running child revisions.
- Keep `/tmp` smoke hermetic; no repo canonical smoke artifacts.
- Do not implement real provider dispatch in this phase. Codex/OpenClaw/manual runtime policy remains contract metadata unless already implemented by existing adapters.

## Files

### Create

- `factor_factory/ultimate_loop/__init__.py`
  - Exports loop state helpers.

- `factor_factory/ultimate_loop/state.py`
  - Pure functions for reading Step6 iteration state, Council state, stop conditions, and next child report metadata.

- `factor_factory/ultimate_loop/proof.py`
  - Proof schema helpers, atomic JSON write, command tail normalization.

- `scripts/run_factorforge_ultimate_loop.py`
  - New formal loop entrypoint for multi-loop research.

- `scripts/run_factorforge_ultimate_loop_smoke.py`
  - `/tmp` smoke covering promote, reject/exhausted, awaiting agent results, max loop cap, command failure, side-effect guard, and child-lineage isolation.

### Modify

- `skills/factor-forge-ultimate/SKILL.md`
  - Tell agents that real research should use `scripts/run_factorforge_ultimate_loop.py` when the user asks to run the full process until submit/exhaustion.
  - Keep `scripts/run_factorforge_ultimate.py` documented as single-pass formal wrapper used by the loop orchestrator.

- `docs/contracts/step6-contract.md`
  - Add Phase M loop-orchestrator contract and stop-state table.

- `docs/contracts/step6-contract.zh-CN.md`
  - Same contract in Chinese.

- `scripts/run_factorforge_ultimate.py`
  - Only if needed: expose stable proof fields consumed by the loop orchestrator. Do not turn this file into the loop implementation unless absolutely necessary.

---

## Required Behavior

### Loop entrypoint

Create command:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <ROOT_REPORT_ID> \
  --start-step 3 \
  --max-loops 10 \
  --council-mode auto \
  --agentic-council-executor local_mock
```

Supported args:

```text
--report-id REQUIRED
--start-step 2|3|3b|4|5|6 default=3
--max-loops int default=10
--council-mode off|auto|scaffold|agentic default=auto
--agentic-council-executor none|local_mock|dispatch_manifest|real_agent default=none
--agentic-dispatch-adapter none|manual_file|openclaw|codex|remote_api default=none
--runtime-dispatch codex|openclaw|manual_file|unknown optional
--subagent-provider optional
--subagent-model optional
--factorforge-root optional
--dry-run optional
--proof-output optional
```

### Formal pass command

Each loop iteration must call the existing wrapper, not step scripts directly:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id <CURRENT_REPORT_ID> \
  --start-step <START_STEP_FOR_THIS_LOOP> \
  --end-step 6 \
  --council-mode <MODE> \
  --agentic-council-executor <EXECUTOR> \
  --agentic-dispatch-adapter <ADAPTER>
```

First loop may start from user `--start-step`. Child loops must start from `3b` unless a formal Council/program-search artifact explicitly says a different restart step.

### Loop proof

Write:

```text
objects/runtime_context/ultimate_loop_report__<ROOT_REPORT_ID>.json
```

Required top-level fields:

```json
{
  "contract_version": "factorforge_ultimate_loop_orchestrator_v1",
  "root_report_id": "...",
  "status": "RUNNING|PASS|FAIL|PAUSED",
  "final_outcome": "promoted|rejected|exhausted|awaiting_agent_results|max_loops_reached|blocked|failed",
  "max_loops": 10,
  "loop_count": 0,
  "started_at_utc": "...",
  "finished_at_utc": "...",
  "factorforge_root": "...",
  "iterations": [],
  "stop_reason": null,
  "canonical_side_effect_policy": {
    "no_clean_data_mutation_by_orchestrator": true,
    "no_parent_generated_code_overwrite": true,
    "child_report_ids_required_for_revision": true
  }
}
```

Each iteration entry must include:

```json
{
  "loop_index": 0,
  "report_id": "...",
  "parent_report_id": null,
  "child_report_id": null,
  "wrapper_command": ["python3", "scripts/run_factorforge_ultimate.py", "..."],
  "wrapper_rc": 0,
  "wrapper_proof_path": "objects/runtime_context/ultimate_run_report__...json",
  "step6_iteration_path": "objects/research_iteration_master/research_iteration_master__...json",
  "decision": "promote_official|iterate|reject|needs_human_review",
  "final_revision_strategy_source": "deterministic|revision_council|none",
  "loop_authorization": "approved_for_step3b_handoff|advisory_only|blocked|not_needed",
  "council_status": "completed|awaiting_agent_results|not_triggered|failed|skipped",
  "selected_revision_id": null,
  "brief_json_path": "...",
  "brief_md_path": "...",
  "metrics_snapshot": {},
  "stop_condition": null
}
```

### Stop conditions

Implement exact stop classification in `factor_factory/ultimate_loop/state.py`.

| Condition | Outcome | Wrapper status |
|---|---|---|
| Step6 decision is `promote_official` and official record exists | `promoted` | `PASS` |
| Step6 decision is `reject` and Council says no material improvement path | `rejected` or `exhausted` | `PASS` |
| Evidence/case prewrite block exists | `blocked` | `FAIL` |
| Council status is `awaiting_agent_results` | `awaiting_agent_results` | `PAUSED` |
| Council final strategy is `advisory_only` with no authorized child revision | `exhausted` or `awaiting_agent_results` depending on explicit Council status | `PASS` or `PAUSED` |
| Loop reaches `--max-loops` without promotion/rejection | `max_loops_reached` | `PASS` |
| Any formal wrapper command rc != 0 | `failed` | `FAIL` |

### Child revision rule

The orchestrator may only continue to a child loop if there is an explicit approved child revision artifact.

Accepted sources:

- Existing Step6-approved `handoff_to_step3b__<report_id>.json` with `loop_authorization=approved_for_step3b_handoff`.
- Approved program-search / revision branch artifact that already passes its validator and explicitly names the child report id.
- Existing `apply_step6_iteration.py` output if it is already the formal approved revision path.

If no accepted source exists:

- Do not invent a child formula.
- Do not manually edit generated code.
- Stop as `awaiting_agent_results` or `exhausted` depending on Council/Step6 state.

### Child report id rule

All child loops must use a new report id. Format:

```text
<PARENT_REPORT_ID>__LOOP<NN>__<SHORT_REVISION_ID>
```

Examples:

```text
ALPHA016_CANONICAL_FORMULA_20160101__LOOP01__COST_PERSISTENCE
ALPHA016_CANONICAL_FORMULA_20160101__LOOP02__MECH_CHALLENGE
```

The parent report's canonical `generated_code/<PARENT_REPORT_ID>/` must not be overwritten by the orchestrator. Any changed implementation must be under the child report id generated code path and produced by Step3B.

### Mandatory brief aggregation

The loop proof must aggregate every loop's brief:

```text
objects/runtime_context/ultimate_loop_brief__<ROOT_REPORT_ID>.md
```

Required sections per loop:

1. Economic interpretation: who pays, why they may pay, risk premium / information advantage / market structure arbitrage classification.
2. Math model and derivation: process/distribution/functional/estimator/tools selected and public derivation summary.
3. Metrics: numeric Step4/5/6 metrics and chart references.
4. Council judgment: selected proposals, rejected proposals, derivation appendix link.
5. Decision: promote / iterate / reject / pause, with reason.
6. Next action: child loop id, awaiting agent results, or stop.

Do not require hidden chain-of-thought. Require public derivation artifacts and concise derivation summaries.

---

## Tasks

### Task 1: Add pure loop-state helpers

**Files:**
- Create: `factor_factory/ultimate_loop/__init__.py`
- Create: `factor_factory/ultimate_loop/state.py`

- [ ] **Step 1: Create package init**

Create `factor_factory/ultimate_loop/__init__.py`:

```python
"""Factor Forge Ultimate multi-loop orchestration helpers."""

from .state import LoopDecision, classify_loop_state, next_child_report_id

__all__ = ["LoopDecision", "classify_loop_state", "next_child_report_id"]
```

- [ ] **Step 2: Implement state helper dataclass and utilities**

Create `factor_factory/ultimate_loop/state.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re


@dataclass(frozen=True)
class LoopDecision:
    outcome: str
    status: str
    reason: str
    can_continue_to_child: bool
    child_source: str | None = None
    child_report_id: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", value.upper()).strip("_")
    return token[:40] or "REVISION"


def next_child_report_id(parent_report_id: str, loop_index: int, revision_id: str | None) -> str:
    suffix = _safe_token(revision_id or "REVISION")
    return f"{parent_report_id}__LOOP{loop_index:02d}__{suffix}"


def _official_record_exists(root: Path, report_id: str) -> bool:
    return (root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json").exists()


def _prewrite_block_exists(root: Path, report_id: str) -> bool:
    validation = root / "objects" / "validation"
    if not validation.exists():
        return False
    return any(validation.glob(f"*prewrite_block__{report_id}.json"))


def _handoff_exists(root: Path, report_id: str) -> bool:
    return (root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json").exists()


def _final_revision_strategy(iteration: dict[str, Any]) -> dict[str, Any]:
    memo = (((iteration.get("research_judgment") or {}).get("research_memo")) or {})
    return memo.get("final_revision_strategy") or memo.get("revision_strategy") or {}


def classify_loop_state(root: Path, report_id: str, wrapper_rc: int, max_reached: bool = False) -> LoopDecision:
    if wrapper_rc != 0:
        return LoopDecision("failed", "FAIL", "formal_wrapper_failed", False)

    if _prewrite_block_exists(root, report_id):
        return LoopDecision("blocked", "FAIL", "step6_prewrite_block_present", False)

    iteration_path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    iteration = load_json(iteration_path)
    decision = iteration.get("decision") or (((iteration.get("research_judgment") or {}).get("decision")) or {}).get("decision")
    strategy = _final_revision_strategy(iteration)
    loop_authorization = strategy.get("loop_authorization")
    council_ref = iteration.get("revision_council_ref") or {}
    council_status = council_ref.get("status") or "not_attached"

    if decision == "promote_official" and _official_record_exists(root, report_id):
        return LoopDecision("promoted", "PASS", "official_record_written", False)

    if council_status == "awaiting_agent_results":
        return LoopDecision("awaiting_agent_results", "PAUSED", "council_awaiting_agent_results", False)

    if max_reached:
        return LoopDecision("max_loops_reached", "PASS", "max_council_loops_reached", False)

    if decision == "reject":
        return LoopDecision("rejected", "PASS", "step6_rejected_current_factor", False)

    if decision == "iterate" and loop_authorization == "approved_for_step3b_handoff" and _handoff_exists(root, report_id):
        revision_id = strategy.get("primary_failure_signature") or strategy.get("selected_revision_id") or "revision"
        return LoopDecision("iterate", "RUNNING", "approved_step3b_handoff", True, "handoff_to_step3b", next_child_report_id(report_id, 1, revision_id))

    if decision == "iterate" and loop_authorization == "advisory_only":
        return LoopDecision("awaiting_agent_results", "PAUSED", "advisory_only_revision_requires_agent_or_human_result", False)

    if decision in {"needs_human_review", "human_review"}:
        return LoopDecision("awaiting_agent_results", "PAUSED", "needs_human_review", False)

    return LoopDecision("exhausted", "PASS", "no_authorized_child_revision_path", False)
```

- [ ] **Step 3: Run import smoke**

Run:

```bash
python3 - <<'PY'
from factor_factory.ultimate_loop import next_child_report_id
print(next_child_report_id('ALPHA016_CANONICAL_FORMULA_20160101', 1, 'cost too high'))
PY
```

Expected output contains:

```text
ALPHA016_CANONICAL_FORMULA_20160101__LOOP01__COST_TOO_HIGH
```

### Task 2: Add loop proof helpers

**Files:**
- Create: `factor_factory/ultimate_loop/proof.py`

- [ ] **Step 1: Create proof helper file**

Create `factor_factory/ultimate_loop/proof.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import tempfile
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def tail_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def make_initial_proof(root: Path, report_id: str, max_loops: int) -> dict[str, Any]:
    return {
        "contract_version": "factorforge_ultimate_loop_orchestrator_v1",
        "root_report_id": report_id,
        "status": "RUNNING",
        "final_outcome": None,
        "max_loops": max_loops,
        "loop_count": 0,
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "factorforge_root": str(root),
        "iterations": [],
        "stop_reason": None,
        "canonical_side_effect_policy": {
            "no_clean_data_mutation_by_orchestrator": True,
            "no_parent_generated_code_overwrite": True,
            "child_report_ids_required_for_revision": True,
        },
    }
```

- [ ] **Step 2: Compile helper**

Run:

```bash
python3 -m py_compile factor_factory/ultimate_loop/proof.py
```

Expected: rc 0.

### Task 3: Implement loop entrypoint skeleton

**Files:**
- Create: `scripts/run_factorforge_ultimate_loop.py`

- [ ] **Step 1: Create entrypoint with CLI and single-pass call**

Create `scripts/run_factorforge_ultimate_loop.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.ultimate_loop.proof import make_initial_proof, tail_text, utc_now, write_json_atomic
from factor_factory.ultimate_loop.state import classify_loop_state


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Factor Forge Ultimate multi-loop orchestrator.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--start-step", choices=["2", "3", "3b", "4", "5", "6"], default="3")
    ap.add_argument("--max-loops", type=int, default=10)
    ap.add_argument("--council-mode", choices=["off", "auto", "scaffold", "agentic"], default="auto")
    ap.add_argument("--agentic-council-executor", choices=["none", "local_mock", "dispatch_manifest", "real_agent"], default="none")
    ap.add_argument("--agentic-dispatch-adapter", choices=["none", "manual_file", "openclaw", "codex", "remote_api"], default="none")
    ap.add_argument("--runtime-dispatch", choices=["codex", "openclaw", "manual_file", "unknown"], default=None)
    ap.add_argument("--subagent-provider", default=None)
    ap.add_argument("--subagent-model", default=None)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--proof-output", default=None)
    return ap.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_formal_pass(args: argparse.Namespace, report_id: str, start_step: str, ctx_root: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id", report_id,
        "--start-step", start_step,
        "--end-step", "6",
        "--council-mode", args.council_mode,
        "--agentic-council-executor", args.agentic_council_executor,
        "--agentic-dispatch-adapter", args.agentic_dispatch_adapter,
    ]
    if args.runtime_dispatch:
        cmd.extend(["--runtime-dispatch", args.runtime_dispatch])
    if args.subagent_provider:
        cmd.extend(["--subagent-provider", args.subagent_provider])
    if args.subagent_model:
        cmd.extend(["--subagent-model", args.subagent_model])
    if args.factorforge_root:
        cmd.extend(["--factorforge-root", args.factorforge_root])
    if args.dry_run:
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(ctx_root)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        "command": cmd,
        "rc": proc.returncode,
        "stdout_tail": tail_text(proc.stdout),
        "stderr_tail": tail_text(proc.stderr),
    }


def collect_iteration(root: Path, report_id: str) -> dict[str, Any]:
    path = root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    data = load_json(path)
    memo = (((data.get("research_judgment") or {}).get("research_memo")) or {})
    strategy = memo.get("final_revision_strategy") or memo.get("revision_strategy") or {}
    return {
        "step6_iteration_path": str(path),
        "decision": data.get("decision") or ((data.get("research_judgment") or {}).get("decision") or {}).get("decision"),
        "final_revision_strategy_source": strategy.get("source"),
        "loop_authorization": strategy.get("loop_authorization"),
        "council_status": (data.get("revision_council_ref") or {}).get("status"),
        "brief_json_path": ((data.get("loop_research_brief") or {}).get("json_path")),
        "brief_md_path": ((data.get("loop_research_brief") or {}).get("markdown_path")),
        "metrics_snapshot": (((data.get("loop_research_brief") or {}).get("metrics")) or {}),
    }


def main() -> int:
    args = parse_args()
    if args.max_loops < 1 or args.max_loops > 10:
        print("BLOCK_FACTORFORGE_LOOP_MAX_LOOPS_OUT_OF_RANGE")
        return 1

    ctx = resolve_factorforge_context(args.factorforge_root)
    proof_path = Path(args.proof_output).expanduser() if args.proof_output else ctx.objects_root / "runtime_context" / f"ultimate_loop_report__{args.report_id}.json"
    proof = make_initial_proof(ctx.factorforge_root, args.report_id, args.max_loops)
    write_json_atomic(proof_path, proof)

    current_report_id = args.report_id
    current_start_step = args.start_step

    for loop_index in range(1, args.max_loops + 1):
        pass_result = run_formal_pass(args, current_report_id, current_start_step, ctx.factorforge_root)
        max_reached = loop_index >= args.max_loops
        decision = classify_loop_state(ctx.factorforge_root, current_report_id, pass_result["rc"], max_reached=max_reached)
        iteration_entry = {
            "loop_index": loop_index,
            "report_id": current_report_id,
            "parent_report_id": None if loop_index == 1 else args.report_id,
            "wrapper_command": pass_result["command"],
            "wrapper_rc": pass_result["rc"],
            "wrapper_stdout_tail": pass_result["stdout_tail"],
            "wrapper_stderr_tail": pass_result["stderr_tail"],
            "wrapper_proof_path": str(ctx.objects_root / "runtime_context" / f"ultimate_run_report__{current_report_id}.json"),
            **collect_iteration(ctx.factorforge_root, current_report_id),
            "stop_condition": decision.outcome if not decision.can_continue_to_child else None,
            "loop_state_reason": decision.reason,
        }
        proof["iterations"].append(iteration_entry)
        proof["loop_count"] = loop_index
        proof["status"] = decision.status
        proof["final_outcome"] = decision.outcome
        proof["stop_reason"] = decision.reason
        proof["finished_at_utc"] = utc_now()
        write_json_atomic(proof_path, proof)

        if not decision.can_continue_to_child:
            print(f"[LOOP_{decision.status}] {decision.outcome}: {decision.reason}")
            print(f"[LOOP_PROOF] {proof_path}")
            return 0 if decision.status in {"PASS", "PAUSED"} else 1

        print("BLOCK_FACTORFORGE_LOOP_CHILD_REVISION_EXECUTION_NOT_IMPLEMENTED")
        proof["status"] = "FAIL"
        proof["final_outcome"] = "blocked"
        proof["stop_reason"] = "child_revision_execution_not_implemented"
        proof["finished_at_utc"] = utc_now()
        write_json_atomic(proof_path, proof)
        return 1

    proof["status"] = "PASS"
    proof["final_outcome"] = "max_loops_reached"
    proof["stop_reason"] = "max_council_loops_reached"
    proof["finished_at_utc"] = utc_now()
    write_json_atomic(proof_path, proof)
    print(f"[LOOP_PASS] max_loops_reached")
    print(f"[LOOP_PROOF] {proof_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Compile entrypoint**

Run:

```bash
python3 -m py_compile scripts/run_factorforge_ultimate_loop.py
```

Expected: rc 0.

### Task 4: Implement child revision continuation

**Files:**
- Modify: `factor_factory/ultimate_loop/state.py`
- Modify: `scripts/run_factorforge_ultimate_loop.py`

- [ ] **Step 1: Add child handoff reader**

Add to `factor_factory/ultimate_loop/state.py`:

```python
def approved_child_revision_from_handoff(root: Path, report_id: str, loop_index: int) -> dict[str, Any]:
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    handoff = load_json(handoff_path)
    if not handoff:
        return {"ok": False, "reason": "handoff_missing"}
    auth = (((handoff.get("revision_strategy") or {}).get("loop_authorization")) or handoff.get("loop_authorization"))
    if auth != "approved_for_step3b_handoff":
        return {"ok": False, "reason": "handoff_not_approved"}
    revision_id = handoff.get("revision_id") or handoff.get("branch_id") or ((handoff.get("revision_strategy") or {}).get("primary_failure_signature")) or "revision"
    child_id = handoff.get("child_report_id") or next_child_report_id(report_id, loop_index + 1, revision_id)
    return {"ok": True, "source": "handoff_to_step3b", "path": str(handoff_path), "child_report_id": child_id, "revision_id": revision_id}
```

- [ ] **Step 2: Use child handoff in loop**

In `scripts/run_factorforge_ultimate_loop.py`, import:

```python
from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff, classify_loop_state
```

Replace the current `BLOCK_FACTORFORGE_LOOP_CHILD_REVISION_EXECUTION_NOT_IMPLEMENTED` block with:

```python
        child = approved_child_revision_from_handoff(ctx.factorforge_root, current_report_id, loop_index)
        if not child.get("ok"):
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = f"approved_child_revision_missing:{child.get('reason')}"
            proof["finished_at_utc"] = utc_now()
            write_json_atomic(proof_path, proof)
            print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
            print(f"[LOOP_PROOF] {proof_path}")
            return 1
        proof["iterations"][-1]["child_report_id"] = child["child_report_id"]
        proof["iterations"][-1]["selected_revision_id"] = child.get("revision_id")
        proof["iterations"][-1]["child_revision_source"] = child
        write_json_atomic(proof_path, proof)
        current_report_id = child["child_report_id"]
        current_start_step = "3b"
```

- [ ] **Step 3: Compile**

Run:

```bash
python3 -m py_compile factor_factory/ultimate_loop/state.py scripts/run_factorforge_ultimate_loop.py
```

Expected: rc 0.

### Task 5: Add aggregate loop brief

**Files:**
- Modify: `scripts/run_factorforge_ultimate_loop.py`

- [ ] **Step 1: Add brief writer**

Add function to `scripts/run_factorforge_ultimate_loop.py`:

```python
def write_loop_brief(root: Path, root_report_id: str, proof: dict[str, Any]) -> str:
    out = root / "objects" / "runtime_context" / f"ultimate_loop_brief__{root_report_id}.md"
    lines = [
        f"# Factor Forge Ultimate Loop Brief: {root_report_id}",
        "",
        f"Final outcome: `{proof.get('final_outcome')}`",
        f"Stop reason: `{proof.get('stop_reason')}`",
        f"Loop count: `{proof.get('loop_count')}`",
        "",
    ]
    for item in proof.get("iterations", []):
        lines.extend([
            f"## Loop {item.get('loop_index')}: {item.get('report_id')}",
            "",
            f"Decision: `{item.get('decision')}`",
            f"Council status: `{item.get('council_status')}`",
            f"Final revision source: `{item.get('final_revision_strategy_source')}`",
            f"Loop authorization: `{item.get('loop_authorization')}`",
            f"Stop condition: `{item.get('stop_condition')}`",
            "",
            "### Required Evidence Links",
            f"- Wrapper proof: `{item.get('wrapper_proof_path')}`",
            f"- Step6 iteration: `{item.get('step6_iteration_path')}`",
            f"- Loop brief JSON: `{item.get('brief_json_path')}`",
            f"- Loop brief Markdown: `{item.get('brief_md_path')}`",
            "",
            "### Metrics Snapshot",
            "```json",
            json.dumps(item.get("metrics_snapshot") or {}, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "### Research Note",
            "The detailed economic interpretation, math model, derivation summary, chart evidence, Council judgment, and next action must be read from the linked Step6 loop brief and Council derivation appendix. This aggregate brief is an index, not a replacement for formal Step6 evidence.",
            "",
        ])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)
```

- [ ] **Step 2: Call brief writer before every return**

Before any final return in `main()`, set:

```python
proof["aggregate_loop_brief_path"] = write_loop_brief(ctx.factorforge_root, args.report_id, proof)
write_json_atomic(proof_path, proof)
```

- [ ] **Step 3: Compile**

Run:

```bash
python3 -m py_compile scripts/run_factorforge_ultimate_loop.py
```

Expected: rc 0.

### Task 6: Add loop smoke harness

**Files:**
- Create: `scripts/run_factorforge_ultimate_loop_smoke.py`

- [ ] **Step 1: Create smoke harness with `/tmp` root guard**

Create `scripts/run_factorforge_ultimate_loop_smoke.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(cmd: list[str], root: Path) -> dict:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, env={"FACTORFORGE_ROOT": str(root)})
    return {"cmd": cmd, "rc": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


def canonical_pollution_matches() -> list[str]:
    roots = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
    matches = []
    for rel in roots:
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*ULTIMATE_LOOP_SMOKE*"):
            matches.append(str(p))
    return sorted(matches)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(tempfile.gettempdir()) / f"factorforge_ultimate_loop_smoke_{utc_stamp()}"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).expanduser()
    if not str(root).startswith("/tmp/"):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    cases = []
    py = sys.executable

    # This harness intentionally starts with wrapper-level dry-run/negative checks.
    compile_cmd = [py, "-m", "py_compile", "scripts/run_factorforge_ultimate_loop.py", "factor_factory/ultimate_loop/state.py", "factor_factory/ultimate_loop/proof.py"]
    compile_case = run(compile_cmd, root)
    cases.append({"name": "py_compile", "ok": compile_case["rc"] == 0, **compile_case})

    bad_max = run([py, "scripts/run_factorforge_ultimate_loop.py", "--report-id", "ULTIMATE_LOOP_SMOKE_BAD_MAX", "--factorforge-root", str(root), "--max-loops", "11"], root)
    cases.append({"name": "max_loops_above_10_blocks", "ok": bad_max["rc"] == 1 and "BLOCK_FACTORFORGE_LOOP_MAX_LOOPS_OUT_OF_RANGE" in bad_max["stdout"], **bad_max})

    # Full synthetic positive cases should be added with existing Step fixtures. Until then, the harness must not claim full closure.
    summary = {
        "verdict": "ACCEPT" if all(c["ok"] for c in cases) and not canonical_pollution_matches() else "BLOCK",
        "cases": cases,
        "canonical_pollution": {"polluted": bool(canonical_pollution_matches()), "new_files": canonical_pollution_matches()},
        "notes": [
            "Phase M smoke starts with structural checks. Coder must extend this file with full promote/reject/pause/max-loop fixtures before requesting review.",
            "No real factor research is run by this smoke.",
        ],
    }
    out = root / "ultimate_loop_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[SUMMARY] {out}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run initial smoke**

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_m_initial
```

Expected: rc 0, verdict `ACCEPT` for structural checks.

- [ ] **Step 3: Add full fixture coverage before reviewer handoff**

Extend the smoke to include these cases before marking Phase M complete:

```text
loop_promote_stops
loop_reject_stops
loop_awaiting_agent_results_pauses
loop_max_10_stops
loop_wrapper_failure_blocks
loop_child_revision_missing_blocks
loop_child_report_id_isolation
loop_aggregate_brief_written
loop_non_tmp_root_blocks
```

Each case must assert exact rc, proof status, final outcome, and no canonical pollution.

### Task 7: Update skill and contracts

**Files:**
- Modify: `skills/factor-forge-ultimate/SKILL.md`
- Modify: `docs/contracts/step6-contract.md`
- Modify: `docs/contracts/step6-contract.zh-CN.md`

- [ ] **Step 1: Update Ultimate skill**

Add this section to `skills/factor-forge-ultimate/SKILL.md` after “Mandatory Single Entry Wrapper”:

```markdown
## Multi-Loop Research Orchestrator

For real research where the user asks Factor Forge Ultimate to continue until the factor is promotable or exhausted, use:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <report_id> \
  --start-step 3 \
  --max-loops 10 \
  --council-mode auto
```

The loop orchestrator is the only approved multi-loop runner. It calls `scripts/run_factorforge_ultimate.py` for each formal Step3B -> Step6 pass and records `objects/runtime_context/ultimate_loop_report__<report_id>.json`.

Stop conditions are: official promotion, rejection/exhaustion, awaiting agent results, prewrite block, wrapper failure, or max 10 loops. Agents must not invent child formulas outside approved Step6/Council artifacts.
```
```

- [ ] **Step 2: Update contracts**

Add a Phase M section to both contract docs with the stop table from “Required Behavior”.

- [ ] **Step 3: Run doc grep check**

Run:

```bash
rg -n "Multi-Loop Research Orchestrator|ultimate_loop_report|max 10" skills/factor-forge-ultimate/SKILL.md docs/contracts/step6-contract.md docs/contracts/step6-contract.zh-CN.md
```

Expected: all three files contain the Phase M text.

### Task 8: Final verification and sync

**Files:**
- No new source files unless previous tasks require fixes.

- [ ] **Step 1: Compile all changed Python files**

Run:

```bash
python3 -m py_compile \
  factor_factory/ultimate_loop/__init__.py \
  factor_factory/ultimate_loop/state.py \
  factor_factory/ultimate_loop/proof.py \
  scripts/run_factorforge_ultimate_loop.py \
  scripts/run_factorforge_ultimate_loop_smoke.py \
  scripts/run_factorforge_ultimate.py
```

Expected: rc 0.

- [ ] **Step 2: Run Phase M smoke**

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_m_final
```

Expected: rc 0, verdict `ACCEPT`, all required cases present.

- [ ] **Step 3: Run existing regressions**

Run:

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_hypothesis_contract_phase_m_regression
python3 scripts/run_agentic_council_manual_dispatch_smoke.py --fresh --root /tmp/factorforge_agentic_council_manual_dispatch_phase_m_regression
python3 scripts/run_step6_council_primary_smoke.py --fresh --root /tmp/factorforge_step6_council_primary_phase_m_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_m_regression
```

Expected:

```text
Step12 smoke verdict ACCEPT
manual dispatch smoke verdict ACCEPT
council primary smoke verdict ACCEPT
STEP6_INTELLIGENCE_ACCEPTED
```

- [ ] **Step 4: Verify non-`/tmp` block**

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /Users/humphrey/tmp_factorforge_bad
```

Expected:

```text
BLOCK_NON_TMP_FACTORFORGE_ROOT
```

- [ ] **Step 5: Sync installed skills**

Run:

```bash
rsync -a --delete skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
rsync -a --delete skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/
diff -qr -x __pycache__ skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
diff -qr -x __pycache__ skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
```

Expected: both diff commands rc 0 and no output.

- [ ] **Step 6: Report explicit non-actions**

The coder final report must explicitly state:

```text
No real factor run was performed unless explicitly requested.
No clean data was processed by Phase M smoke.
No search worker was executed.
No Step3B handoff was written by the orchestrator itself.
No official promotion was written by the orchestrator itself.
No parent generated_code was overwritten.
```

---

## Reviewer Acceptance Checklist

Reviewer should BLOCK if any item fails:

- `run_factorforge_ultimate_loop.py` calls `run_factorforge_ultimate.py` for formal passes instead of directly calling Step3B/4/5/6.
- Max loop cap is enforced at `<= 10`.
- Loop proof exists and contains all iterations with wrapper proof paths.
- Orchestrator stops on `awaiting_agent_results`; it does not fake agent results.
- Orchestrator does not invent child formulas.
- Child loops use child report ids, not parent overwrite.
- Existing Step1/2/6 acceptance regressions still pass.
- `/tmp` smoke reports no canonical pollution.
- Installed Ultimate and Step6 skills are synced.

