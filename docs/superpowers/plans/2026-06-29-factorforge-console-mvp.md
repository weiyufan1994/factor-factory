# Factor Forge Console MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Factor Forge Console that turns Miner/Factor Forge artifacts into a concise dashboard, task/result manifest surface, and artifact viewer.

**Architecture:** Add a read-first Python console layer under `factor_factory/console/`. It discovers existing `factor_research/miner/<campaign_id>` workspaces, summarizes JSON artifacts into stable models, renders local HTML, and writes only explicit task/result manifests under `factor_research/console/`.

**Tech Stack:** Python 3.10 stdlib, dataclasses, json, pathlib, http.server, existing Factor Forge artifact files, pytest smoke tests.

---

## Non-Negotiable Constraints

- Do not modify Ultimate or Miner research logic.
- Do not start production research, workers, formal Step3B, Step4, or Step6.
- Do not write `data/clean`.
- Do not write repo-root knowledge vault.
- Do not treat cheap-screen evidence as official factor promotion.
- Do not use `git add .`.
- Keep Console writes under `factor_research/console/`.

## Files

### Create

- `factor_factory/console/__init__.py`
- `factor_factory/console/models.py`
- `factor_factory/console/discovery.py`
- `factor_factory/console/readers.py`
- `factor_factory/console/task_manifest.py`
- `factor_factory/console/summary.py`
- `factor_factory/console/static_app.py`
- `scripts/run_factorforge_console.py`
- `scripts/run_factorforge_console_smoke.py`
- `tests/test_factorforge_console.py`

### Do Not Modify

- `scripts/run_factorforge_ultimate.py`
- `skills/factor-forge-ultimate/SKILL.md`
- `factor_factory/miner/*` unless a later reviewer explicitly requests a Console integration change

## Task 1: Console Models

**Files:**

- Create: `factor_factory/console/__init__.py`
- Create: `factor_factory/console/models.py`
- Test: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing model tests**

Add tests:

```python
from factor_factory.console.models import CampaignSummary, ConsoleTask, ConsoleResult


def test_campaign_summary_round_trip():
    summary = CampaignSummary(
        campaign_id="current_data_api_catalog_20260626",
        workspace_root="/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626",
        verdict="BLOCK",
        candidate_count=12,
        cheap_screen_passed=0,
        research_queue_count=0,
        data_gap_count=46,
        data_request_count=1,
        template_status_counts={"needs_operator": 6, "partial": 4, "needs_data": 2},
        artifact_paths={"queue": "docs/research_queue.md"},
        blockers=["no ready templates"],
        next_actions=["fix catalog"],
        boundary_statement="No production research.",
    )
    payload = summary.to_dict()
    assert payload["verdict"] == "BLOCK"
    assert payload["candidate_count"] == 12
    assert CampaignSummary.from_dict(payload).template_status_counts["needs_operator"] == 6


def test_console_task_requires_contract_version():
    payload = {
        "contract_version": "wrong",
        "task_id": "task_1",
        "task_type": "factorforge_miner_campaign",
        "repo_root": "/repo",
        "execution_workspace": "/tmp/work",
        "campaign_id": "camp",
        "workspace_root": "factor_research/miner/camp",
        "inputs": {},
        "steps": [],
        "boundaries": {},
        "expected_outputs": [],
    }
    try:
        ConsoleTask.from_dict(payload)
    except ValueError as exc:
        assert "factorforge_console_task_v1" in str(exc)
    else:
        raise AssertionError("invalid contract version accepted")
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: fail because `factor_factory.console` does not exist.

- [ ] **Step 3: Implement models**

Create dataclasses:

```python
@dataclass
class CampaignSummary:
    campaign_id: str
    workspace_root: str
    verdict: str
    candidate_count: int
    cheap_screen_passed: int
    research_queue_count: int
    data_gap_count: int
    data_request_count: int
    template_status_counts: dict[str, int]
    artifact_paths: dict[str, str]
    blockers: list[str]
    next_actions: list[str]
    boundary_statement: str
```

Also create `ConsoleTask` and `ConsoleResult` with contract-version validation.

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/__init__.py factor_factory/console/models.py tests/test_factorforge_console.py
git commit -m "Add Factor Forge Console data models"
```

## Task 2: Miner Campaign Reader

**Files:**

- Create: `factor_factory/console/readers.py`
- Modify: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing reader test**

Add a fixture builder in the test file that writes:

```text
objects/miner_capability_inventory.json
objects/candidates/candidate_manifest.json
objects/data_gap_report.json
objects/cheap_screen/cheap_screen_summary.json
objects/research_queue/research_queue.json
```

Test:

```python
from factor_factory.console.readers import read_miner_campaign


def test_read_miner_campaign_blocks_when_no_queue(tmp_path):
    workspace = make_miner_fixture(tmp_path)
    summary = read_miner_campaign(workspace)
    assert summary.verdict == "BLOCK"
    assert summary.candidate_count == 12
    assert summary.data_gap_count == 46
    assert summary.data_request_count == 1
    assert summary.research_queue_count == 0
    assert summary.template_status_counts == {"needs_operator": 6, "partial": 4, "needs_data": 2}
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py::test_read_miner_campaign_blocks_when_no_queue -q
```

Expected: fail because reader is missing.

- [ ] **Step 3: Implement reader**

Implement `read_miner_campaign(workspace_root: Path) -> CampaignSummary`.

Rules:

- Missing required JSON -> `BLOCK` summary with blocker.
- `promotion_forbidden_until_formal` not true -> `BLOCK`.
- Queue items count > 0 -> `PARTIAL`.
- No queue and nonzero data gaps -> `BLOCK`.
- Artifact paths must be relative to workspace.

- [ ] **Step 4: Verify test passes**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/readers.py tests/test_factorforge_console.py
git commit -m "Summarize Miner campaign artifacts for Console"
```

## Task 3: Campaign Discovery

**Files:**

- Create: `factor_factory/console/discovery.py`
- Modify: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing discovery test**

Test:

```python
from factor_factory.console.discovery import discover_miner_campaigns


def test_discover_miner_campaigns(tmp_path):
    workspace = make_miner_fixture(tmp_path / "root")
    found = discover_miner_campaigns([tmp_path / "root"])
    assert found == [workspace]
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py::test_discover_miner_campaigns -q
```

Expected: fail because discovery is missing.

- [ ] **Step 3: Implement discovery**

Search only:

```text
<root>/factor_research/miner/*/objects/miner_capability_inventory.json
```

Return the campaign workspace path.

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/discovery.py tests/test_factorforge_console.py
git commit -m "Discover Miner campaign workspaces"
```

## Task 4: Task and Result Manifest Writer

**Files:**

- Create: `factor_factory/console/task_manifest.py`
- Modify: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing manifest tests**

Tests:

```python
from factor_factory.console.task_manifest import write_console_task, write_console_result
from factor_factory.console.models import ConsoleTask, ConsoleResult


def test_write_console_task_under_console_root(tmp_path):
    task = ConsoleTask(
        contract_version="factorforge_console_task_v1",
        task_id="task_1",
        task_type="factorforge_miner_campaign",
        repo_root=str(tmp_path),
        execution_workspace=str(tmp_path),
        campaign_id="camp",
        workspace_root="factor_research/miner/camp",
        inputs={},
        steps=[],
        boundaries={},
        expected_outputs=[],
    )
    path = write_console_task(tmp_path, task)
    assert path == tmp_path / "factor_research" / "console" / "tasks" / "task_1.json"
    assert path.exists()
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py::test_write_console_task_under_console_root -q
```

Expected: fail because writer is missing.

- [ ] **Step 3: Implement writer**

Implement:

```python
BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE = "BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE"
```

Write only under:

```text
<root>/factor_research/console/tasks/
<root>/factor_research/console/results/
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/task_manifest.py tests/test_factorforge_console.py
git commit -m "Add Console task and result manifests"
```

## Task 5: HTML Summary Renderer

**Files:**

- Create: `factor_factory/console/summary.py`
- Modify: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing renderer test**

Test:

```python
from factor_factory.console.summary import render_dashboard


def test_render_dashboard_contains_campaign_metrics(tmp_path):
    summary = read_miner_campaign(make_miner_fixture(tmp_path))
    html = render_dashboard([summary])
    assert "Factor Forge Console" in html
    assert "current_data_api_catalog_20260626" in html
    assert "BLOCK" in html
    assert "46" in html
    assert "research queue" in html.lower()
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py::test_render_dashboard_contains_campaign_metrics -q
```

Expected: fail because renderer is missing.

- [ ] **Step 3: Implement renderer**

Render plain HTML with:

- Dashboard cards
- Campaign summary table
- Data gap counts
- Queue count
- Artifact links
- Boundary statement

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/summary.py tests/test_factorforge_console.py
git commit -m "Render Factor Forge Console dashboard"
```

## Task 6: Local Console Server

**Files:**

- Create: `factor_factory/console/static_app.py`
- Create: `scripts/run_factorforge_console.py`
- Modify: `tests/test_factorforge_console.py`

- [ ] **Step 1: Write failing CLI smoke test**

Test a pure function first:

```python
from factor_factory.console.static_app import build_console_html


def test_build_console_html_from_root(tmp_path):
    make_miner_fixture(tmp_path)
    html = build_console_html([tmp_path])
    assert "Factor Forge Console" in html
    assert "current_data_api_catalog_20260626" in html
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py::test_build_console_html_from_root -q
```

Expected: fail because static app is missing.

- [ ] **Step 3: Implement static app and CLI**

CLI:

```bash
python3 scripts/run_factorforge_console.py --root /tmp/factorforge-miner-workspace --host 127.0.0.1 --port 8765
```

The script should print:

```text
Factor Forge Console running at http://127.0.0.1:8765
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_factorforge_console.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add factor_factory/console/static_app.py scripts/run_factorforge_console.py tests/test_factorforge_console.py
git commit -m "Serve Factor Forge Console locally"
```

## Task 7: Console Smoke

**Files:**

- Create: `scripts/run_factorforge_console_smoke.py`

- [ ] **Step 1: Write smoke script**

Behavior:

- Prefer real campaign:

```text
/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626
```

- If missing, create `/tmp/factorforge_console_smoke` fixture.
- Assert:

```text
candidate_count == 12
research_queue_count == 0
data_gap_count == 46
data_request_count == 1
template_status_counts.needs_operator == 6
template_status_counts.partial == 4
template_status_counts.needs_data == 2
verdict == BLOCK
```

- Print:

```text
FACTORFORGE_CONSOLE_SMOKE PASS
```

- [ ] **Step 2: Run smoke**

Run:

```bash
python3 scripts/run_factorforge_console_smoke.py
```

Expected:

```text
FACTORFORGE_CONSOLE_SMOKE PASS
```

- [ ] **Step 3: Run full verification**

Run:

```bash
python3 -m py_compile factor_factory/console/*.py scripts/run_factorforge_console.py scripts/run_factorforge_console_smoke.py
python3 -m pytest tests/test_factorforge_console.py -q
python3 scripts/run_factorforge_console_smoke.py
git diff --check
```

Expected: all pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add scripts/run_factorforge_console_smoke.py
git commit -m "Add Factor Forge Console smoke"
```

## Task 8: Final Review Packet

**Files:**

- No code changes unless reviewer requests them.

- [ ] **Step 1: Verify final status**

Run:

```bash
git status --short --branch
python3 -m py_compile factor_factory/console/*.py scripts/run_factorforge_console.py scripts/run_factorforge_console_smoke.py
python3 -m pytest tests/test_factorforge_console.py -q
python3 scripts/run_factorforge_console_smoke.py
git diff --check HEAD~7..HEAD
```

- [ ] **Step 2: Ask independent reviewer**

Reviewer must check:

- No Ultimate/Miner research logic changed.
- Console default is read-only.
- Manifest writes stay under `factor_research/console/`.
- Real Miner campaign displays as `BLOCK`.
- No production research / worker / formal Step3B/Step4/Step6 / clean data mutation.

- [ ] **Step 3: Fix findings or close**

If reviewer returns `BLOCK`, fix and repeat review.

If reviewer returns `ACCEPT`, report to user with:

```text
本地 URL:
Smoke:
Campaign shown:
Verdict:
Known limitations:
Boundary:
```
