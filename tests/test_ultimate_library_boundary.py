"""Real process boundaries; stage planning is not a completed factor study."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from factor_factory.ultimate_loop.cli import build_parser, parse_args


REPO = Path(__file__).resolve().parents[1]


def test_help_preserves_full_parser_but_prioritizes_research():
    ordinary = build_parser().format_help()
    complete = build_parser(show_all=True).format_help()
    assert "--factor-workspace" in ordinary
    assert "--local-is-only" in ordinary
    assert "--help-all" in ordinary
    assert "--sealed-oos-carrier" not in ordinary
    assert "--sealed-oos-carrier" in complete
    assert "--state-resolution" in complete
    assert "--agentic-council-executor" in complete
    args = ["--report-id", "TEST", "--local-is-only", "--council-mode", "off"]
    assert vars(parse_args(args)) == vars(build_parser(show_all=True).parse_args(args))
    assert parse_args(args).max_council_loops == 10
    assert parse_args(args).start_step == "3"


def _process(code, tmp_path, *, env_additions=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORFORGE_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(REPO))
    env.update(env_additions or {})
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


BOUNDARY = '''
import sys
class Boundary:
    def find_spec(self, fullname, path=None, target=None):
        forbidden = (
            "factor_factory.console", "factor_factory.research_org.runtime",
            "factor_factory.researcher_memory", "factor_factory.evo_memory_runtime",
            "factor_factory.evo_terminal_closure",
        )
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise AssertionError("Ordinary research loaded " + fullname)
sys.meta_path.insert(0, Boundary())
'''


def test_local_plan_runs_in_fresh_process_without_hosted_modules(tmp_path):
    _process(BOUNDARY + '''
import json
from pathlib import Path
from factor_factory.ultimate_loop.cli import parse_args
from factor_factory.ultimate_loop.runner import _run_formal_ultimate
from factor_factory.research_workspace import build_workspace_manifest, write_workspace_manifest, workspace_manifest_path
root = Path.cwd() / "study"
manifest = build_workspace_manifest(repo_root=Path(__import__("factor_factory").__file__).parent.parent,
    factorforge_root=Path.cwd(), factor_id="boundary", research_id="dry", root_report_id="BOUNDARY")
write_workspace_manifest(workspace_manifest_path(root), manifest)
args = parse_args(["--report-id", "BOUNDARY", "--factor-workspace", str(root),
    "--local-is-only", "--dry-run", "--start-step", "2", "--end-step", "2", "--council-mode", "off"])
assert _run_formal_ultimate(args) == 0
proof = json.loads((root / "objects/runtime_context/ultimate_run_report__BOUNDARY.json").read_text())
assert proof["status"] == "DRY_RUN"
assert proof["formal_proof_eligible"] is False
assert [c["name"] for c in proof["commands"]] == ["run_step2", "validate_step2"]
assert all(c["status"] == "DRY_RUN" for c in proof["commands"])
''', tmp_path)


def test_cli_help_does_not_import_runner_or_data(tmp_path):
    _process(BOUNDARY + f'''
import runpy
class HelpBoundary:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "factor_factory.ultimate_loop.runner" or fullname.startswith("factor_factory.data_access"):
            raise AssertionError(fullname)
sys.meta_path.insert(0, HelpBoundary())
sys.argv = ["run_factorforge_ultimate.py", "--help-all"]
try:
    runpy.run_path({str(REPO / 'scripts/run_factorforge_ultimate.py')!r}, run_name="__main__")
except SystemExit as exc:
    assert exc.code == 0
''', tmp_path)


def test_real_step4_computation_and_backend_keep_hosted_modules_unloaded(tmp_path):
    """Fresh parent and real backend child, using the existing synthetic study.

    This covers Step4 computation/evaluation, not an independent Step2/6 review
    or a complete Ultimate research acceptance. Only temporary input/output
    paths and environment are selected by the fixture; the backend is not mocked.
    """
    hook = tmp_path / 'python-startup'
    hook.mkdir()
    trace = tmp_path / 'processes.txt'
    (hook / 'sitecustomize.py').write_text(BOUNDARY + f'''
import os
def record_boundary_event(event, args):
    if event == "exec" and getattr(args[0], "co_filename", "").endswith("pfvv_monthly_step4_backend_v1.py"):
        with open({str(trace)!r}, "a") as stream:
            stream.write("backend " + str(os.getpid()) + "\\n")
sys.addaudithook(record_boundary_event)
with open({str(trace)!r}, "a") as stream:
    stream.write("guard " + str(os.getpid()) + "\\n")
''')
    _process('''
from pathlib import Path
from pytest import MonkeyPatch
from tests.test_pfvv_step4_pipeline_integration import (
    test_prepared_pfvv_controller_reaches_current_step4_output_and_monthly_backend,
)
with MonkeyPatch.context() as patch:
    test_prepared_pfvv_controller_reaches_current_step4_output_and_monthly_backend(Path.cwd(), patch)
''', tmp_path, env_additions={'PYTHONPATH': os.pathsep.join([str(hook), str(REPO)])})
    observed = [row.split() for row in trace.read_text().splitlines()]
    guards = {pid for kind, pid in observed if kind == 'guard'}
    backends = {pid for kind, pid in observed if kind == 'backend'}
    assert len(guards) >= 2
    assert len(backends) == 1 and backends <= guards
