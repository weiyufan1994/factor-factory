from __future__ import annotations

from pathlib import Path

from factor_factory.research_knowledge_maintenance import record_local_research_episode
from scripts.maintain_factorforge_knowledge import _maintenance_projection
import scripts.maintain_factorforge_knowledge as maintenance_cli


def _proof(status: str = "FAIL") -> dict:
    return {"factor_id": "FACTOR", "status": status, "failure": {"command": "validate_step2"},
            "commands": [{"name": "run_step2", "status": "PASS", "returncode": 0},
                         {"name": "validate_step2", "status": "FAIL", "returncode": 1}]}


def test_records_only_executed_local_is_facts_and_is_idempotent(tmp_path: Path) -> None:
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    workspace.mkdir(); repo.mkdir()
    result = record_local_research_episode(proof=_proof(), workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)
    assert result["status"] == "RECORDED"
    assert result["local_status"] == result["export_status"] == "WRITTEN"
    episodes = list((workspace / "knowledge/research_episodes").glob("episode__RID__*.json"))
    assert len(episodes) == 1
    episode = episodes[0].read_text()
    assert '"formal_step6_completed":false' in episode
    assert '"lessons_status":"NEEDS_RESEARCHER_REVIEW"' in episode
    again = record_local_research_episode(proof=_proof(), workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)
    assert again["local_status"] == again["export_status"] == "IDEMPOTENT"


def test_paused_then_failed_are_distinct_immutable_episodes(tmp_path: Path) -> None:
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    workspace.mkdir(); repo.mkdir()
    paused = _proof("PAUSED")
    paused["failure"] = None
    record_local_research_episode(proof=paused, workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)
    record_local_research_episode(proof=_proof(), workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)
    assert len(list((workspace / "knowledge/research_episodes").glob("episode__RID__*.json"))) == 2


def test_completed_step6_is_not_an_episode(tmp_path: Path) -> None:
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    workspace.mkdir(); repo.mkdir()
    proof = _proof("PASS")
    proof["commands"] = [{"name": "run_step6", "status": "PASS", "returncode": 0},
                         {"name": "validate_step6", "status": "PASS", "returncode": 0}]
    assert record_local_research_episode(proof=proof, workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)["reason"] == "completed_step6_uses_knowledge_record"


def test_engineering_contract_smoke_never_exports_research_episode(tmp_path: Path) -> None:
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    workspace.mkdir(); repo.mkdir()
    result = record_local_research_episode(
        proof={**_proof("PASS"), "contract_smoke_only": True},
        workspace=workspace, repo_root=repo, report_id="SMOKE_LOCAL",
        dry_run=False, local_is_only=True,
    )
    assert result == {"status": "SKIPPED", "reason": "engineering_contract_smoke"}
    assert not (workspace / "knowledge").exists()
    assert not (repo / "knowledge").exists()


def test_cli_projection_drops_command_tails() -> None:
    projected = _maintenance_projection({"factor_id": "F", "status": "FAIL", "failure": {"command": "x"},
        "commands": [{"name": "x", "status": "FAIL", "returncode": 1, "stdout_tail": "private"}]})
    assert projected["commands"] == [{"name": "x", "status": "FAIL", "returncode": 1}]


def test_maintenance_cli_preserves_smoke_boundary_without_episode_or_index(tmp_path, monkeypatch):
    import json
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    repo.mkdir()
    proof = workspace / "objects/runtime_context/ultimate_run_report__SMOKE_LOCAL.json"
    proof.parent.mkdir(parents=True)
    proof.write_text(json.dumps({**_proof("PASS"), "execution_scope": "local_is_only", "contract_smoke_only": True}))
    before = proof.read_bytes()
    monkeypatch.setattr(maintenance_cli, "ROOT", repo)
    monkeypatch.setattr("sys.argv", ["maintain", "--workspace-root", str(workspace), "--report-id", "SMOKE_LOCAL"])
    assert maintenance_cli.main() == 0
    report = json.loads((repo / "knowledge/maintenance/latest.json").read_text())
    assert report["result"]["reason"] == "engineering_contract_smoke"
    assert proof.read_bytes() == before
    assert not (workspace / "knowledge").exists()
    assert not (repo / "knowledge/因子工厂").exists()
    assert _maintenance_projection({"contract_smoke_only": "true"})["contract_smoke_only"] is False


def test_maintenance_cli_repairs_existing_proof_without_research_subprocess(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    proof = workspace / "objects/runtime_context/ultimate_run_report__RID.json"
    proof.parent.mkdir(parents=True)
    proof.write_text('{"execution_scope":"local_is_only","commands":[{"name":"x","status":"FAIL","returncode":1,"stdout_tail":"ignored"}]}')
    observed = {}
    monkeypatch.setattr(maintenance_cli, "record_local_research_episode", lambda **kw: observed.setdefault("proof", kw["proof"]) or {"status":"SKIPPED"})
    monkeypatch.setattr(maintenance_cli, "write_latest_maintenance_report", lambda **kw: "report.json")
    monkeypatch.setattr("sys.argv", ["maintain", "--workspace-root", str(workspace), "--report-id", "RID"])
    assert maintenance_cli.main() == 0
    assert observed["proof"]["commands"] == [{"name":"x", "status":"FAIL", "returncode":1}]


def test_skips_dry_run_and_no_command_preflight(tmp_path: Path) -> None:
    workspace, repo = tmp_path / "workspace", tmp_path / "repo"
    workspace.mkdir(); repo.mkdir()
    assert record_local_research_episode(proof=_proof(), workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=True, local_is_only=True)["status"] == "SKIPPED"
    assert record_local_research_episode(proof={"commands": []}, workspace=workspace, repo_root=repo,
        report_id="RID", dry_run=False, local_is_only=True)["status"] == "SKIPPED"
    assert not (workspace / "knowledge").exists()


def test_episode_only_workspace_and_empty_project_can_be_read_back(tmp_path):
    from factor_factory.research_knowledge_maintenance import refresh_episode_maintenance
    workspace, repo = tmp_path/'workspace', tmp_path/'empty-project'
    workspace.mkdir(); repo.mkdir()
    record_local_research_episode(proof=_proof(), workspace=workspace, repo_root=repo,
        report_id='RID', dry_run=False, local_is_only=True)
    result = refresh_episode_maintenance(workspace=workspace, repo_root=repo, report_id='RID')
    assert result['default_readback'] is True
    assert Path(result['workspace_index']).is_file()


def test_completed_step6_cli_repairs_indexes_without_mutating_proof(tmp_path, monkeypatch):
    import json
    import scripts.run_factorforge_ultimate as ultimate
    from tests.test_factorforge_ultimate_knowledge_refresh import _proof as complete, _write_record
    workspace, repo = tmp_path/'workspace', tmp_path/'repo'
    repo.mkdir()
    record = _write_record(workspace, 'RID')
    path = workspace/'objects/runtime_context/ultimate_run_report__RID.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**complete(), 'execution_scope':'local_is_only'}))
    originals = path.read_bytes(), record.read_bytes()
    monkeypatch.setattr(maintenance_cli, 'ROOT', repo)
    monkeypatch.setattr(ultimate, 'REPO_ROOT', repo)
    monkeypatch.setattr('sys.argv', ['maintain', '--workspace-root', str(workspace), '--report-id', 'RID'])
    assert maintenance_cli.main() == 0
    report = json.loads((repo/'knowledge/maintenance/latest.json').read_text())
    assert report['result']['completed_step6_maintenance']['default_readback'] is True
    assert (path.read_bytes(), record.read_bytes()) == originals
    assert not (workspace/'knowledge/research_episodes').exists()


def test_duplicate_step6_commands_are_not_completed(tmp_path):
    workspace, repo = tmp_path/'workspace', tmp_path/'repo'
    workspace.mkdir(); repo.mkdir()
    proof = {'status':'PASS', 'commands':[
        {'name':'run_step6','status':'PASS','returncode':0},
        {'name':'run_step6','status':'PASS','returncode':0}]}
    result = record_local_research_episode(proof=proof, workspace=workspace, repo_root=repo,
        report_id='RID', dry_run=False, local_is_only=True)
    assert result['status'] == 'RECORDED'
