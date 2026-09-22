from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.ultimate_loop.state import classify_loop_state


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_loop_module():
    path = REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py"
    spec = importlib.util.spec_from_file_location(
        "run_factorforge_ultimate_loop_budget_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_multibranch_materializer_module():
    path = (
        REPO_ROOT
        / "skills"
        / "factor-forge-step6"
        / "scripts"
        / "materialize_step6_multibranch_children.py"
    )
    spec = importlib.util.spec_from_file_location(
        "materialize_step6_multibranch_incident_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_public_loop_proof_redacts_host_private_incident_pair() -> None:
    loop = _load_loop_module()
    private_root = "/host/private/research-org-trust"
    installation_id = "host-private-installation"
    args = SimpleNamespace(
        report_id="REPORT",
        incident_trust_root=private_root,
        incident_installation_id=installation_id,
        harmless="public",
    )
    denied = (private_root, installation_id)

    public_args = loop.public_loop_args(args, denied_values=denied)
    public_result = loop.public_command_result(
        {
            "command": [
                "python3",
                "materialize.py",
                "--incident-trust-root",
                private_root,
                "--incident-installation-id",
                installation_id,
            ],
            "cwd": "/repo",
            "stdout_tail": f"used {private_root}",
            "stderr_tail": installation_id,
        },
        denied_values=denied,
    )
    serialized = json.dumps(
        {"args": public_args, "command": public_result},
        sort_keys=True,
    )

    assert private_root not in serialized
    assert installation_id not in serialized
    assert public_args["incident_trust_root"] == "[HOST_PRIVATE]"
    assert public_args["incident_installation_id"] == "[HOST_PRIVATE]"
    assert public_args["harmless"] == "public"


def _wrapper_proof() -> dict:
    command_names = ["run_step6", "validate_step6"]
    return {
        "status": "PASS",
        "dry_run": False,
        "contract_smoke_only": True,
        "formal_proof_eligible": False,
        "requested_steps": ["6"],
        "commands": [
            {"name": name, "status": "PASS", "returncode": 0}
            for name in command_names
        ],
        "formal_command_contract": {
            "required_command_names": command_names,
            "satisfied": True,
        },
    }


def _write_loop_inputs(
    root: Path,
    report_id: str,
    *,
    decision: str,
    loop_authorization: str = "advisory_only",
) -> None:
    _write_json(
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json",
        _wrapper_proof(),
    )
    _write_json(
        root
        / "objects"
        / "research_iteration_master"
        / f"research_iteration_master__{report_id}.json",
        {
            "decision": decision,
            "research_judgment": {
                "research_memo": {
                    "final_revision_strategy": {
                        "loop_authorization": loop_authorization,
                        "revision_needed": decision == "iterate",
                    }
                }
            },
        },
    )


def test_budget_exhaustion_demotes_continuable_iteration_without_erasing_evidence() -> None:
    loop = _load_loop_module()
    proof = {
        "status": "RUNNING",
        "formal_proof_eligible": True,
        "max_loops": 1,
        "iterations": [],
    }
    iteration = {
        "loop_index": 1,
        "decision": "iterate",
        "can_continue": True,
        "proof_status": "RUNNING",
        "wrapper_proof_path": "/evidence/ultimate_run_report.json",
        "metric_evidence_ref": {"path": "/evidence/metrics.json", "sha256": "a" * 64},
    }

    loop.mark_budget_exhausted(proof, iteration)

    assert proof["status"] == "PAUSED"
    assert proof["formal_proof_eligible"] is False
    assert proof["factor_proof_completed"] is False
    assert proof["final_outcome"] == "max_loops_reached"
    assert proof["completion_semantics"] == "research_budget_exhausted_not_factor_proof"
    assert proof["budget_exhaustion"]["pre_budget_state_can_continue"] is True
    assert proof["budget_exhaustion"]["completed_iteration_evidence_preserved"] is True
    assert iteration["can_continue"] is False
    assert iteration["proof_status"] == "PAUSED"
    assert iteration["formal_proof_eligible"] is False
    assert iteration["metric_evidence_ref"]["sha256"] == "a" * 64


def test_multibranch_budget_exhaustion_is_pause_not_factor_pass() -> None:
    loop = _load_loop_module()
    proof = {
        "status": "RUNNING",
        "formal_proof_eligible": True,
        "max_loops": 2,
    }
    iteration = {
        "loop_index": 2,
        "outcome": "awaiting_agent_results",
        "council_status": "multibranch_synthesis_ready",
        "can_continue": False,
        "selected_branches": ["exploit", "explore"],
    }

    loop.mark_budget_exhausted(proof, iteration)

    assert proof["status"] == "PAUSED"
    assert proof["formal_proof_eligible"] is False
    assert iteration["proof_status"] == "PAUSED"
    assert iteration["selected_branches"] == ["exploit", "explore"]
    assert proof["budget_exhaustion"]["pre_budget_state_can_continue"] is False


def test_classifier_reports_nonterminal_max_loop_as_paused(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    report_id = "MAX_LOOP_ITERATE"
    _write_loop_inputs(root, report_id, decision="iterate")

    state = classify_loop_state(
        root,
        report_id,
        0,
        max_reached=True,
        contract_smoke_mode=True,
    )

    assert state["outcome"] == "max_loops_reached"
    assert state["proof_status"] == "PAUSED"
    assert state["can_continue"] is False
    assert state["decision"] == "iterate"


def test_genuine_terminal_decisions_remain_pass_at_loop_cap(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    promoted_id = "MAX_LOOP_PROMOTED"
    rejected_id = "MAX_LOOP_REJECTED"
    _write_loop_inputs(root, promoted_id, decision="promote_official")
    _write_json(
        root
        / "objects"
        / "factor_library_official"
        / f"factor_record__{promoted_id}.json",
        {"report_id": promoted_id},
    )
    _write_loop_inputs(root, rejected_id, decision="reject")

    promoted = classify_loop_state(
        root,
        promoted_id,
        0,
        max_reached=True,
        contract_smoke_mode=True,
    )
    rejected = classify_loop_state(
        root,
        rejected_id,
        0,
        max_reached=True,
        contract_smoke_mode=True,
    )

    assert (promoted["outcome"], promoted["proof_status"]) == ("promoted", "PASS")
    assert (rejected["outcome"], rejected["proof_status"]) == ("rejected", "PASS")


def test_all_script_cap_paths_share_the_fail_closed_budget_marker() -> None:
    source = (REPO_ROOT / "scripts" / "run_factorforge_ultimate_loop.py").read_text(
        encoding="utf-8"
    )

    assert source.count('proof["final_outcome"] = "max_loops_reached"') == 1
    assert 'iteration["proof_status"] = "PASS"' not in source
    assert source.count("return finalize_budget_exhaustion(") == 4


def test_formal_loop_requires_explicit_exact_incident_host_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _load_loop_module()
    args = SimpleNamespace(
        dry_run=False,
        allow_legacy_research_protocol_smoke=False,
        incident_trust_root=None,
        incident_installation_id=None,
    )
    with pytest.raises(ValueError, match=loop.BLOCK_INCIDENT_CONTEXT_REQUIRED):
        loop.resolve_incident_host_context(args)

    trust_root = tmp_path / "host-one"
    other_trust_root = tmp_path / "host-two"
    ensure_runtime_trust_store(trust_root, installation_id="host-one")
    ensure_runtime_trust_store(other_trust_root, installation_id="host-two")
    args.incident_trust_root = str(trust_root)
    args.incident_installation_id = "host-one"
    monkeypatch.setenv("FACTORFORGE_OOS_HOST_TRUST_ROOT", str(other_trust_root))
    monkeypatch.setenv("FACTORFORGE_OOS_HOST_INSTALLATION_ID", "host-two")
    with pytest.raises(ValueError, match=loop.BLOCK_INCIDENT_CONTEXT_MISMATCH):
        loop.resolve_incident_host_context(args)


def test_loop_materialization_commands_carry_exact_host_pair(
    tmp_path: Path,
) -> None:
    loop = _load_loop_module()
    trust_root = tmp_path / "host-private"
    expected_pin = "a" * 64

    single = loop.materialization_command(
        "PARENT",
        "CHILD",
        tmp_path / "workspace",
        expected_host_trust_manifest_sha256=expected_pin,
        incident_trust_root=trust_root,
        incident_installation_id="host-installation",
    )
    multi = loop.multibranch_materialization_command(
        "PARENT",
        tmp_path / "workspace",
        2,
        expected_host_trust_manifest_sha256=expected_pin,
        incident_trust_root=trust_root,
        incident_installation_id="host-installation",
    )
    for command in (single, multi):
        assert command[command.index("--incident-trust-root") + 1] == str(
            trust_root
        )
        assert (
            command[command.index("--incident-installation-id") + 1]
            == "host-installation"
        )
        assert (
            command[command.index("--expected-host-trust-manifest-sha256") + 1]
            == expected_pin
        )


def test_multibranch_existing_report_cannot_bypass_current_child_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_multibranch_materializer_module()
    root = tmp_path / "workspace"
    root.mkdir()
    report_id = "PARENT"
    child_id = "CHILD"
    source_sha = "b" * 64
    child_report_path = root / "objects/runtime_context/child.json"
    child_spec_path = root / "objects/research_iteration_master/spec.json"
    _write_json(
        child_report_path,
        {"child_report_id": child_id, "child_formula_hash": "c" * 64},
    )
    _write_json(
        child_spec_path,
        {"child_report_id": child_id, "child_formula_hash": "c" * 64},
    )
    _write_json(
        root / f"objects/handoff/handoff_to_step3b__{report_id}.json",
        {"parent_report_id": report_id},
    )
    approval = {
        "source_multibranch_synthesis_sha256": source_sha,
        "selected_branch_count": 1,
        "selected_branches": [
            {
                "child_report_id": child_id,
                "branch_role": "exploit",
                "branch_index": 0,
                "law_id": "law_one",
                "child_formula_hash": "c" * 64,
            }
        ],
    }
    _write_json(
        module.aggregate_report_path(root, report_id, 1),
        {
            "contract_version": module.MATERIALIZATION_VERSION,
            "status": "PASS",
            "parent_report_id": report_id,
            "loop_index": 1,
            "source_multibranch_synthesis_sha256": source_sha,
            "selected_branch_count": 1,
            "children": [
                {
                    "child_report_id": child_id,
                    "branch_role": "exploit",
                    "branch_index": 0,
                    "law_id": "law_one",
                    "child_formula_hash": "c" * 64,
                    "materialization_report_path": str(child_report_path),
                    "executable_revision_spec_path": str(child_spec_path),
                }
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "validate_child_materialization_readback",
        lambda **_kwargs: [],
    )
    calls: list[dict] = []

    def _blocked_current_replay(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "child_report_id": child_id,
            "materialization_rc": 1,
            "stdout_tail": (
                "BLOCK_FACTORFORGE_OOS_EXPOSURE_INCIDENT:"
                "private_registry_incident"
            ),
            "stderr_tail": "",
        }

    monkeypatch.setattr(module, "run_child_materializer", _blocked_current_replay)
    with pytest.raises(ValueError, match="private_registry_incident"):
        module.existing_materialization_reusable(
            root,
            report_id,
            approval,
            loop_index=1,
            incident_trust_root=tmp_path / "host-private",
            incident_installation_id="host-installation",
            expected_host_trust_manifest_sha256="d" * 64,
        )
    assert calls == [
        {
            "incident_trust_root": tmp_path / "host-private",
            "incident_installation_id": "host-installation",
            "expected_host_trust_manifest_sha256": "d" * 64,
        }
    ]


def test_multibranch_materializer_passes_exact_pair_to_each_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_multibranch_materializer_module()
    trust_root = tmp_path / "host-private"
    captured: dict = {}

    def _run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _run)
    module.run_child_materializer(
        tmp_path / "workspace",
        "PARENT",
        {
            "child_report_id": "CHILD",
            "branch_context": {"law_id": "law_one"},
            "adapter_synthesis_path": "adapter.json",
            "branch_index": 0,
            "branch_role": "exploit",
            "law_id": "law_one",
            "child_formula_hash": "e" * 64,
        },
        {
            "branch_group_id": "group-one",
            "source_multibranch_synthesis_path": "synthesis.json",
            "source_multibranch_synthesis_sha256": "f" * 64,
            "selected_branch_count": 1,
        },
        incident_trust_root=trust_root,
        incident_installation_id="host-installation",
        expected_host_trust_manifest_sha256="a" * 64,
    )
    command = captured["command"]
    assert command[command.index("--incident-trust-root") + 1] == str(trust_root)
    assert (
        command[command.index("--incident-installation-id") + 1]
        == "host-installation"
    )
    assert captured["env"]["FACTORFORGE_OOS_HOST_TRUST_ROOT"] == str(
        trust_root
    )
    assert (
        captured["env"]["FACTORFORGE_OOS_HOST_INSTALLATION_ID"]
        == "host-installation"
    )


@pytest.mark.parametrize(
    ("multibranch", "state"),
    [
        (
            False,
            {
                "outcome": "iterate",
                "proof_status": "RUNNING",
                "can_continue": True,
                "stop_reason": "approved_step3b_handoff_available",
                "decision": "iterate",
                "loop_authorization": "approved_for_step3b_handoff",
            },
        ),
        (
            True,
            {
                "outcome": "exhausted",
                "proof_status": "PAUSED",
                "can_continue": False,
                "stop_reason": "multibranch_synthesis_ready",
                "decision": "iterate",
                "loop_authorization": "advisory_only",
            },
        ),
    ],
)
def test_main_cap_branches_write_paused_nonproof_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    multibranch: bool,
    state: dict,
) -> None:
    loop = _load_loop_module()
    root = tmp_path / ("multibranch" if multibranch else "single")
    trust_root = tmp_path / "host-private"
    installation_id = "ultimate-loop-budget-test"
    ensure_runtime_trust_store(
        trust_root,
        installation_id=installation_id,
    )
    monkeypatch.delenv("FACTORFORGE_OOS_HOST_TRUST_ROOT", raising=False)
    monkeypatch.delenv("FACTORFORGE_OOS_HOST_INSTALLATION_ID", raising=False)
    report_id = "BUDGET_CAP_MULTIBRANCH" if multibranch else "BUDGET_CAP_SINGLE"
    args = SimpleNamespace(
        report_id=report_id,
        start_step="3",
        max_loops=1,
        council_mode="off",
        auto_council_policy="dispatch_manifest",
        agentic_council_executor="none",
        agentic_dispatch_adapter="none",
        runtime_dispatch=None,
        subagent_provider=None,
        subagent_model=None,
        factorforge_root=str(root),
        factor_workspace=None,
        runtime_manifest=None,
        expected_host_trust_manifest_sha256=None,
        incident_trust_root=str(trust_root),
        incident_installation_id=installation_id,
        allow_legacy_global_runtime=False,
        proof_path=None,
        dry_run=False,
        allow_legacy_research_protocol_smoke=False,
    )
    monkeypatch.setattr(loop, "parse_args", lambda: args)
    monkeypatch.setattr(
        loop,
        "run_command",
        lambda *_args, **_kwargs: {
            "command": ["formal-wrapper"],
            "rc": 0,
            "status": "PASS",
            "stdout_tail": "",
            "stderr_tail": "",
        },
    )
    monkeypatch.setattr(loop, "classify_loop_state", lambda *_args, **_kwargs: dict(state))
    monkeypatch.setattr(
        loop,
        "multibranch_synthesis_bridge_ready",
        lambda *_args, **_kwargs: multibranch,
    )

    assert loop.main() == 0

    proof_path = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_loop_report__{report_id}.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["status"] == "PAUSED"
    assert proof["formal_proof_eligible"] is False
    assert proof["factor_proof_completed"] is False
    assert proof["final_outcome"] == "max_loops_reached"
    assert proof["budget_exhaustion"]["pre_budget_state_can_continue"] is (
        not multibranch
    )
    serialized = json.dumps(proof, sort_keys=True)
    assert str(trust_root.resolve()) not in serialized
    assert installation_id not in serialized
    assert proof["args"]["incident_trust_root"] == "[HOST_PRIVATE]"
    assert proof["args"]["incident_installation_id"] == "[HOST_PRIVATE]"
    assert proof["iterations"][-1]["proof_status"] == "PAUSED"
    assert proof["iterations"][-1]["can_continue"] is False
    assert Path(proof["paused_research_note_json_path"]).is_file()
