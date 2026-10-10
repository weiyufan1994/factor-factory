"""Exercise the selected research tree, with historical components physically absent."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.build_factorforge_publish_bundle import _select

ROOT = Path(__file__).resolve().parents[1]
ABSENT = (
    "factor_factory/console",
    "factor_factory/miner",
    "factor_factory/research_org/director.py",
    "factor_factory/research_org/runtime.py",
    "factor_factory/researcher_memory.py",
    "factor_factory/evo_memory_runtime.py",
    "factor_factory/evo_terminal_closure.py",
    "factor_factory/ultimate_loop/hosted.py",
    "factor_factory/epistemic_host_bootstrap_expectation_proposal.py",
    "scripts/run_factorforge_performance_smoke.py",
    "scripts/run_factorforge_research_protocol_smoke.py",
    "scripts/build_minute_derived_datamart.py",
    "scripts/run_factorforge_console.py",
)


@pytest.fixture(scope="module")
def selected_tree(tmp_path_factory):
    tree = tmp_path_factory.mktemp("research-distribution") / "source"
    tree.mkdir()
    selected, _ = _select(ROOT)
    for rel in selected:
        source = ROOT / rel
        if source.is_file():
            target = tree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return tree


def _run(tree, tmp_path, code):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FACTORFORGE_", "PYTHON"))}
    env.update(HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(tree)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def test_build_selection_does_not_ship_historical_services(selected_tree):
    for rel in ABSENT:
        assert not (selected_tree / rel).exists(), rel
    for rel in (
        "factor_factory/factors.py", "factor_factory/research_api.py",
        "factor_factory/portfolio_api.py", "factor_factory/hybrid_research/mcts.py",
        "factor_factory/knowledge_context.py", "factor_factory/step5/evaluator.py",
        "skills/factor-forge-step6/SKILL.md", "scripts/run_factorforge_ultimate.py",
        "scripts/build_report_qlib_provider.py", "scripts/publish_qlib_daily_provider.py",
    ):
        assert (selected_tree / rel).is_file(), rel


def test_new_unclassified_module_or_script_is_not_automatically_distributed(tmp_path):
    (tmp_path / "packaging").mkdir()
    shutil.copyfile(ROOT / "packaging/research-files.toml", tmp_path / "packaging/research-files.toml")
    for rel in ("factor_factory/new_deployment_service.py", "scripts/new_backfill.py"):
        p = tmp_path / rel
        p.parent.mkdir(exist_ok=True)
        p.write_text("raise RuntimeError('not a research dependency')\n")
    selected, excluded = _select(tmp_path)
    assert "factor_factory/new_deployment_service.py" not in selected
    assert "scripts/new_backfill.py" not in selected
    assert "factor_factory/new_deployment_service.py" in excluded


def test_all_selected_library_modules_import_without_historical_source(selected_tree, tmp_path):
    _run(selected_tree, tmp_path, '''
import importlib, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
for path in sorted((root / "factor_factory").rglob("*.py")):
    name = ".".join(path.relative_to(root).with_suffix("").parts)
    if name.endswith(".__init__"):
        name = name[:-9]
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(root)
assert not any(n.startswith(("factor_factory.console", "factor_factory.researcher_memory")) for n in sys.modules)
''')


def test_ordinary_workspace_and_local_plan_need_no_director(selected_tree, tmp_path):
    _run(selected_tree, tmp_path, '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from factor_factory.ultimate_loop.cli import parse_args
from factor_factory.ultimate_loop.runner import _run_formal_ultimate
from factor_factory.research_workspace import build_workspace_manifest, write_workspace_manifest, workspace_manifest_path
root = Path.cwd() / "study"
manifest = build_workspace_manifest(repo_root=Path(sys.argv[1]), factorforge_root=Path.cwd(),
    factor_id="packaged", research_id="offline", root_report_id="PACKAGED")
write_workspace_manifest(workspace_manifest_path(root), manifest)
args = parse_args(["--report-id", "PACKAGED", "--factor-workspace", str(root),
    "--local-is-only", "--dry-run", "--start-step", "2", "--end-step", "2", "--council-mode", "off"])
assert _run_formal_ultimate(args) == 0
proof = json.loads((root / "objects/runtime_context/ultimate_run_report__PACKAGED.json").read_text())
assert proof["status"] == "DRY_RUN" and proof["formal_proof_eligible"] is False
assert "factor_factory.research_org.director" not in sys.modules
''')


def test_missing_hosted_mode_reports_component_before_creating_workspace(selected_tree, tmp_path):
    result = _run(selected_tree, tmp_path, '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from factor_factory.ultimate_loop.cli import parse_args
from factor_factory.ultimate_loop.runner import _run_formal_ultimate
root = Path.cwd() / "not-created"
args = parse_args(["--report-id", "HOSTED", "--factorforge-root", str(root),
    "--init-factor-workspace", "--factor-id", "test", "--research-id", "test"])
assert _run_formal_ultimate(args) == 1
assert not root.exists()
''')
    assert "BLOCK_FACTORFORGE_HOSTED_COMPONENTS_NOT_INSTALLED" in result.stdout
    assert "Traceback" not in result.stderr


def test_selected_hosted_plan_is_not_treated_as_absent(selected_tree, tmp_path):
    _run(selected_tree, tmp_path, '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from factor_factory.research_org.gate import resolve_research_organization_gate, PLAN_RELATIVE_PATH
from factor_factory.research_org.contracts import ResearchOrganizationError
root = Path.cwd() / "hosted-study"
plan = root / PLAN_RELATIVE_PATH
plan.parent.mkdir(parents=True)
plan.write_text("{}")
try:
    resolve_research_organization_gate(mode="auto", factor_workspace=root)
except ResearchOrganizationError as exc:
    assert "HOSTED_COMPONENTS_NOT_INSTALLED" in str(exc)
else:
    raise AssertionError("Existing hosted plan was silently bypassed")
''')
