from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import factor_factory.evo_child_authoring as authoring
from factor_factory.evo_v2 import canonical_json_bytes, sha256_file
from factor_factory.research_org.runtime import build_research_org_session_prompt
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_release import SEARCH_TRIAL_LEDGER_VERSION
from scripts.run_factorforge_research_protocol_smoke import (
    valid_approaches,
    valid_conjecture,
    valid_state,
)
from tests.evo_child_authoring_fixtures import (
    SignedEvoChildAuthoringFakeRunner,
)

PARENT = "AUTHORING_PARENT"
CHILD = "AUTHORING_PARENT__EVO_CHILD_001"
FACTOR = "authoring_factor"
RESEARCH = "authoring_research"
INSTALLATION = "evo-child-authoring-test-host"
FORMULA_HASH = "f" * 64


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict, dict, str]:
    root = tmp_path / "workspace"
    root.mkdir()
    _write(root / "manifest.json", {"fixture": "evo_child_authoring"})
    trust_root = tmp_path / "private-trust"
    store = ensure_runtime_trust_store(
        trust_root,
        installation_id=INSTALLATION,
    )
    trust_path = root / "objects/runtime_context/runtime_trust_manifest.json"
    _write(trust_path, store.public_manifest)

    state = valid_state()
    state.update(
        {
            "report_id": CHILD,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
            "budget_used": {"trials_used": 1, "trial_budget": 20},
        }
    )
    conjecture = valid_conjecture()
    conjecture.update({"report_id": CHILD, "factor_id": FACTOR})
    conjecture["identity"].update(
        {
            "research_id": RESEARCH,
            "workspace_manifest_sha256": sha256_file(root / "manifest.json"),
            "formula_hash": FORMULA_HASH,
            "data_catalog_snapshot_sha256": "d" * 64,
        }
    )
    conjecture["evidence_policy"].update(
        {
            "trials_used": 1,
            "trial_budget": 20,
            "oos_start": "2026-04-01",
            "oos_end": "2026-09-30",
            "sealed_oos_token_hash": "9" * 64,
        }
    )
    approaches = valid_approaches()
    approaches["report_id"] = CHILD
    preferred = next(
        item for item in conjecture["hypotheses"] if item["kind"] == "preferred"
    )
    trials = [
        {
            "trial_id": "authoring_trial_001",
            "status": "REGISTERED_NOT_EVALUATED",
            "hypothesis_id": preferred["hypothesis_id"],
        }
    ]
    base_ledger = {
        "version": SEARCH_TRIAL_LEDGER_VERSION,
        "search_status": "FROZEN",
        "report_id": CHILD,
        "factor_id": FACTOR,
        "freeze_sequence": 10,
        "trial_count": 1,
        "trials": trials,
        "trial_set_sha256": authoring.LEDGER_DERIVED_HASH_SENTINEL,
        "candidate_space_sha256": authoring.LEDGER_DERIVED_HASH_SENTINEL,
        "selected_hypothesis_sha256": authoring.LEDGER_DERIVED_HASH_SENTINEL,
    }
    child_plan = {
        "identity": {
            "job_id": "job_0123456789",
            "report_id": CHILD,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
        },
        "research_object": {
            "formula_or_law": "close",
            "hypothesis": preferred["claim"],
        },
        "hypotheses": copy.deepcopy(conjecture["hypotheses"]),
        "routes": copy.deepcopy(approaches["routes"]),
    }
    semantic_bundle = {
        "research_state": state,
        "research_conjecture": conjecture,
        "approach_registry": approaches,
        "base_search_trial_ledger": base_ledger,
        "agent_authored_child_web_research_plan": child_plan,
    }

    parent_plan = {
        "identity": {
            "job_id": "job_0123456789",
            "report_id": PARENT,
            "factor_id": FACTOR,
            "research_id": RESEARCH,
        },
        "evidence_policy": copy.deepcopy(conjecture["evidence_policy"]),
    }
    parent_conjecture = copy.deepcopy(conjecture)
    parent_conjecture["report_id"] = PARENT
    parent_conjecture["evidence_policy"].update(
        {
            "oos_start": "2025-01-01",
            "oos_end": "2025-12-31",
            "sealed_oos_token_hash": "8" * 64,
        }
    )
    # OOS fields are the only constitutional fields that may change for a new child.
    parent_plan["evidence_policy"] = copy.deepcopy(
        parent_conjecture["evidence_policy"]
    )
    source_payloads = {
        "authorization_ticket": {"ticket": "signed_test_authority"},
        "host_trust_manifest": store.public_manifest,
        "handoff": {"handoff": "selected_revision"},
        "pre_oos_human_approval": {"decision": "APPROVE_SELECTED_REVISION"},
        "pre_oos_root_synthesis": {"synthesis": "minimal_delta"},
        "mechanism_delta": {"law_id": "law_selected"},
        "economic_backprojection": {"status": "FROZEN"},
        "formal_transfer_use_orchestration": {"status": "PASS"},
        "parent_workspace_manifest": {"fixture": "evo_child_authoring"},
        "parent_web_research_plan": parent_plan,
        "parent_research_state": {"report_id": PARENT},
        "parent_research_conjecture": parent_conjecture,
        "parent_approach_registry": {"report_id": PARENT},
        "parent_metric_verifier_spec": {"report_id": PARENT},
        "parent_threshold_registration": {"report_id": PARENT},
        "parent_web_factor_proof_preregistration": {"report_id": PARENT},
    }
    source_paths: dict[str, Path] = {}
    for label, payload in source_payloads.items():
        path = (
            trust_path
            if label == "host_trust_manifest"
            else root / "authoring_sources" / f"{label}.json"
        )
        _write(path, payload)
        source_paths[label] = path
    root_synthesis_sha = sha256_file(source_paths["pre_oos_root_synthesis"])
    conjecture["identity"]["parent_artifact_sha256"] = root_synthesis_sha
    semantic_bundle["research_conjecture"] = conjecture

    allocation_path = root / "objects/research_protocol/evo_oos_allocation.json"
    allocation_payload = {
        "sealed_private_carrier": "MUST_NOT_BE_STAGED",
        "oos_result_bytes": "MUST_NOT_BE_STAGED",
    }
    _write(allocation_path, allocation_payload)
    authorization_path = source_paths["authorization_ticket"]
    handoff = {
        "parent_identity": {"factor_id": FACTOR, "research_id": RESEARCH},
        "selected_revision": {
            "law_id": "law_selected",
            "delta_id": "delta_selected",
            "implementation_mode": "operator",
            "child_formula": "close",
            "child_formula_hash": FORMULA_HASH,
            "expected_metric_signature": {"direction": "positive"},
            "falsification_tests": ["rank_ic_nonpositive"],
            "kill_criteria": ["after_cost_failure"],
        },
    }
    authorization = {
        "authorization_path": authorization_path,
        "allocation_path": allocation_path,
        "handoff": handoff,
        "parent_contracts": {"plan": parent_plan},
    }
    material = {
        "authorization": authorization,
        "trust_manifest": store.public_manifest,
        "trust_manifest_path": trust_path,
        "source_paths": source_paths,
        "source_payloads": source_payloads,
        "source_file_sha256s": {
            path: sha256_file(path) for path in source_paths.values()
        },
        "allocation_public_binding": {
            "allocation_id": "allocation_authoring_001",
            "report_id": CHILD,
            "parent_report_id": PARENT,
            "dataset_snapshot_sha256": "d" * 64,
            "oos_window": {"start": "2026-04-01", "end": "2026-09-30"},
            "sealed_token_sha256": "9" * 64,
            "sealed_carrier_sha256": "7" * 64,
            "release_state": "SEALED_UNRELEASED",
            "consumed": False,
        },
    }
    monkeypatch.setattr(
        authoring,
        "_authorization_material",
        lambda **kwargs: material,
    )
    monkeypatch.setattr(
        authoring,
        "workspace_runtime_trust_manifest",
        lambda *args, **kwargs: store.public_manifest,
    )
    import factor_factory.console.web_research_plan as web_plan

    monkeypatch.setattr(
        web_plan,
        "validate_authorized_evo_child_web_research_plan",
        lambda **kwargs: {"status": "PASS"},
    )
    return root, trust_root, semantic_bundle, material, store.public_manifest[
        "manifest_sha256"
    ]


def _run(
    root: Path,
    trust_root: Path,
    semantic_bundle: dict,
    pin: str,
    *,
    runner=None,
) -> dict:
    return authoring.run_and_admit_evo_child_authoring(
        runner=runner
        or SignedEvoChildAuthoringFakeRunner(
            semantic_bundle=semantic_bundle,
            trust_root=trust_root,
            installation_id=INSTALLATION,
        ),
        workspace_root=root,
        worktree=root,
        private_root=root.parent / "private-agent-session",
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=pin,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )


def test_prepare_builds_disposable_closed_task_and_routes_dedicated_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    invocation, prepared = authoring.prepare_evo_child_authoring_session(
        workspace_root=root,
        worktree=root,
        private_root=root.parent / "private-agent-session",
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=pin,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )
    assert invocation.role_id == authoring.EVO_CHILD_AUTHORING_ROLE_ID
    assert invocation.parent_session_uid is None
    assert invocation.private_attempt_root != root
    assert invocation.context_root.is_relative_to(invocation.private_attempt_root)
    assert prepared["task"]["closed_constraints"]["oos_bytes_available"] is False
    assert set(prepared["task"]["required_private_output"]["public_record_exact_keys"]) == {
        "research_state",
        "research_conjecture",
        "approach_registry",
        "base_search_trial_ledger",
        "agent_authored_child_web_research_plan",
    }
    staged_bytes = b"".join(
        path.read_bytes()
        for path in invocation.context_root.rglob("*.json")
        if path.is_file()
    )
    assert b"MUST_NOT_BE_STAGED" not in staged_bytes
    prompt = build_research_org_session_prompt(invocation)
    assert str(
        invocation.context_root / "identity/evo_child_authoring_request.json"
    ) in prompt
    assert str(invocation.private_output_path) in prompt


def test_real_signed_runtime_completion_is_host_admitted_and_publicly_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, material, pin = _fixture(tmp_path, monkeypatch)
    result = _run(root, trust_root, bundle, pin)
    assert result["verdict"] == "PASS"
    assert set(result["semantic_bundle"]) == {
        "research_state",
        "research_conjecture",
        "approach_registry",
        "base_search_trial_ledger",
        "agent_authored_child_web_research_plan",
    }
    assert result["admission"]["issuer"]["kind"] == "host_admission"
    assert result["admission"]["runtime_attestation"] == {
        "session_id": result["admission"]["runtime_attestation"]["session_id"],
        "runtime_instance_id": result["admission"]["runtime_attestation"][
            "runtime_instance_id"
        ],
        "provider": "signed-test-runtime",
        "model": "evo-child-author-test-model",
        "transport": "openclaw_disposable_container",
        "isolation_class": "container_staged_context",
        "owned_termination_supported": True,
        "termination_confirmed": True,
        "parent_session_uid": None,
    }
    projected_task = authoring._project_authoring_task(
        root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        material=material,
    )
    staged_labels = {item["label"] for item in projected_task["staged_files"]}
    assert "fresh_oos_allocation_public_binding" in staged_labels
    assert "oos_allocation" not in staged_labels
    assert "MUST_NOT_BE_STAGED" not in json.dumps(
        result["semantic_bundle"], sort_keys=True
    )
    replay = authoring.validate_evo_child_authoring_admission(
        workspace_root=root,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        agent_authoring_admission=result["admission_ref"]["path"],
        expected_host_trust_manifest_sha256=pin,
    )
    assert replay["semantic_bundle"] == result["semantic_bundle"]

    class MustNotRunAgain:
        def run_research_org_session(self, invocation):
            raise AssertionError(f"unexpected second Agent session: {invocation.task_id}")

    idempotent = _run(
        root,
        trust_root,
        bundle,
        pin,
        runner=MustNotRunAgain(),
    )
    assert idempotent["idempotent_replay"] is True
    assert idempotent["semantic_bundle"] == result["semantic_bundle"]


def test_tampered_agent_output_invalidates_public_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    result = _run(root, trust_root, bundle, pin)
    output_path = authoring.evo_child_authoring_paths(root, CHILD)["agent_output"]
    raw = json.loads(output_path.read_text(encoding="utf-8"))
    raw["public_research_record"]["research_state"]["status"] = "tampered"
    output_path.write_bytes(canonical_json_bytes(raw))
    with pytest.raises(authoring.EvoChildAuthoringError, match="public_ref_hash"):
        authoring.validate_evo_child_authoring_admission(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            agent_authoring_admission=result["admission_ref"]["path"],
            expected_host_trust_manifest_sha256=pin,
        )


def test_forged_host_signature_and_weak_isolation_are_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    _run(root, trust_root, bundle, pin)
    admission_path = authoring.evo_child_authoring_paths(root, CHILD)["admission"]
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["signature"]["value_b64"] = "AAAA"
    admission_path.write_bytes(canonical_json_bytes(admission))
    with pytest.raises(
        authoring.EvoChildAuthoringError,
        match="host_admission_signature",
    ):
        authoring.validate_evo_child_authoring_admission(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            agent_authoring_admission=admission_path,
            expected_host_trust_manifest_sha256=pin,
        )

    second_root = tmp_path / "second"
    second_root.mkdir()
    # Rebuild a clean fixture because admitted public objects are write-once.
    root2, trust2, bundle2, _material2, pin2 = _fixture(
        second_root, monkeypatch
    )
    weak = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle2,
        trust_root=trust2,
        installation_id=INSTALLATION,
        isolation_class="process_shared_workspace",
        transport="shared_process",
    )
    with pytest.raises(authoring.EvoChildAuthoringError, match="runtime_outcome"):
        _run(root2, trust2, bundle2, pin2, runner=weak)

    third_root = tmp_path / "third"
    third_root.mkdir()
    root3, trust3, bundle3, _material3, pin3 = _fixture(
        third_root, monkeypatch
    )
    codex_workspace_write = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle3,
        trust_root=trust3,
        installation_id=INSTALLATION,
        isolation_class="codex_subagent_isolated",
        transport="codex_exec_ephemeral",
    )
    with pytest.raises(authoring.EvoChildAuthoringError, match="runtime_outcome"):
        _run(
            root3,
            trust3,
            bundle3,
            pin3,
            runner=codex_workspace_write,
        )


def test_unsigned_or_dummy_adapter_receipt_cannot_be_host_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    signed = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )

    class DummyReceiptRunner:
        def run_research_org_session(self, invocation):
            outcome = signed.run_research_org_session(invocation)
            return replace(outcome, adapter_receipt={})

    with pytest.raises(
        authoring.EvoChildAuthoringError,
        match="adapter_completion",
    ):
        _run(root, trust_root, bundle, pin, runner=DummyReceiptRunner())

    rogue = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=tmp_path / "agent-self-signed-trust",
        installation_id=INSTALLATION,
    )
    with pytest.raises(
        authoring.EvoChildAuthoringError,
        match="adapter_receipt_signature",
    ):
        _run(root, trust_root, bundle, pin, runner=rogue)


def test_completion_journal_recovers_public_admission_crash_without_new_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )

    class CountingRunner:
        calls = 0

        def run_research_org_session(self, invocation):
            self.calls += 1
            return delegate.run_research_org_session(invocation)

    runner = CountingRunner()
    admission_path = authoring.evo_child_authoring_paths(root, CHILD)["admission"]
    original_write = authoring._write_public_once

    def crash_before_admission(workspace, path, raw):
        if path == admission_path:
            raise RuntimeError("simulated_host_crash_before_admission")
        return original_write(workspace, path, raw)

    monkeypatch.setattr(authoring, "_write_public_once", crash_before_admission)
    with pytest.raises(RuntimeError, match="simulated_host_crash"):
        _run(root, trust_root, bundle, pin, runner=runner)
    assert runner.calls == 1
    assert list(
        (root.parent / "private-agent-session").rglob(
            "evo-child-authoring-*/completion_journal.json"
        )
    )

    monkeypatch.setattr(authoring, "_write_public_once", original_write)

    class MustNotRunAgain:
        def run_research_org_session(self, invocation):
            raise AssertionError(f"unexpected recovered rerun: {invocation.task_id}")

    recovered = _run(
        root,
        trust_root,
        bundle,
        pin,
        runner=MustNotRunAgain(),
    )
    assert recovered["verdict"] == "PASS"
    assert recovered["admission_ref"]["path"] == admission_path.relative_to(
        root
    ).as_posix()
    assert runner.calls == 1


def test_prelaunch_crash_reuses_deterministic_attempt_without_duplicate_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )

    class CountingRunner:
        calls = 0

        def run_research_org_session(self, invocation):
            self.calls += 1
            return delegate.run_research_org_session(invocation)

    runner = CountingRunner()
    original_write = authoring._private_write_once
    crashed = False

    def crash_launch(path, raw):
        nonlocal crashed
        if path.name == "launch_journal.json" and not crashed:
            crashed = True
            raise RuntimeError("simulated_prelaunch_journal_crash")
        return original_write(path, raw)

    monkeypatch.setattr(authoring, "_private_write_once", crash_launch)
    with pytest.raises(RuntimeError, match="prelaunch_journal_crash"):
        _run(root, trust_root, bundle, pin, runner=runner)
    assert runner.calls == 0
    attempts = list(
        (root.parent / "private-agent-session").rglob("evo-child-authoring-*")
    )
    assert len(attempts) == 1

    monkeypatch.setattr(authoring, "_private_write_once", original_write)
    recovered = _run(root, trust_root, bundle, pin, runner=runner)
    assert recovered["verdict"] == "PASS"
    assert runner.calls == 1
    assert len(
        list((root.parent / "private-agent-session").rglob("evo-child-authoring-*"))
    ) == 1


def test_launch_only_restart_reconciles_then_signs_abandonment_and_new_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )
    launched: list[str] = []
    reconciled: list[str] = []

    class CrashAfterAgent:
        def run_research_org_session(self, invocation):
            launched.append(invocation.runtime_instance_id)
            delegate.run_research_org_session(invocation)
            raise RuntimeError("simulated_host_kill_after_agent")

    with pytest.raises(RuntimeError, match="host_kill_after_agent"):
        _run(root, trust_root, bundle, pin, runner=CrashAfterAgent())

    class RecoveringRunner:
        def reconcile_research_org_session(self, runtime_instance_id):
            reconciled.append(runtime_instance_id)
            return delegate.reconcile_research_org_session(runtime_instance_id)

        def run_research_org_session(self, invocation):
            launched.append(invocation.runtime_instance_id)
            return delegate.run_research_org_session(invocation)

    result = _run(
        root,
        trust_root,
        bundle,
        pin,
        runner=RecoveringRunner(),
    )
    assert result["verdict"] == "PASS"
    assert reconciled == [launched[0]]
    assert len(launched) == 2
    assert launched[1] != launched[0]
    sessions = sorted(
        (root.parent / "private-agent-session").rglob(
            "evo-child-authoring-*"
        )
    )
    assert len(sessions) == 2
    assert sum((path / "abandoned_journal.json").is_file() for path in sessions) == 1
    assert sum(
        (path / "retry_authorized_journal.json").is_file()
        for path in sessions
    ) == 1


def test_child_private_lock_prevents_concurrent_duplicate_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )
    entered = threading.Event()
    release = threading.Event()
    calls_lock = threading.Lock()
    calls = 0

    class BlockingRunner:
        def run_research_org_session(self, invocation):
            nonlocal calls
            with calls_lock:
                calls += 1
            entered.set()
            assert release.wait(timeout=5)
            return delegate.run_research_org_session(invocation)

    runner = BlockingRunner()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _run, root, trust_root, bundle, pin, runner=runner
        )
        assert entered.wait(timeout=5)
        second = executor.submit(
            _run, root, trust_root, bundle, pin, runner=runner
        )
        time.sleep(0.1)
        assert calls == 1
        release.set()
        first_result = first.result(timeout=5)
        second_result = second.result(timeout=5)
    assert first_result["verdict"] == "PASS"
    assert second_result["verdict"] == "PASS"
    assert calls == 1
    assert second_result["idempotent_replay"] is True


def test_launch_only_restart_with_sticky_runtime_never_authorizes_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=bundle,
        trust_root=trust_root,
        installation_id=INSTALLATION,
    )
    launched = 0

    class CrashAfterAgent:
        def run_research_org_session(self, invocation):
            nonlocal launched
            launched += 1
            delegate.run_research_org_session(invocation)
            raise RuntimeError("simulated_launch_only")

    with pytest.raises(RuntimeError, match="launch_only"):
        _run(root, trust_root, bundle, pin, runner=CrashAfterAgent())

    class StickyRuntime:
        def reconcile_research_org_session(self, runtime_instance_id):
            return delegate.trust_store.sign(
                "runtime_adapter",
                {
                    "receipt_type": "RESEARCH_ORG_CONTAINER_TERMINATION",
                    "identity": {
                        "runtime_instance_id": runtime_instance_id,
                        "runtime_handle_sha256": hashlib.sha256(
                            runtime_instance_id.encode("utf-8")
                        ).hexdigest(),
                        "adapter_id": INSTALLATION,
                    },
                    "ordering": {
                        "issued_at_utc": "2026-08-13T00:00:00Z"
                    },
                    "termination": {
                        "initial_state": "OWNED_PRESENT",
                        "ownership_labels_verified": True,
                        "remove_attempted": True,
                        "inspect_not_found": False,
                        "final_state": "UNCONFIRMED",
                        "termination_confirmed": False,
                    },
                    "authority": {
                        "scope": "OWNED_CONTAINER_TERMINATION_ONLY",
                        "retry_authorized": False,
                        "factor_verdict": "NOT_ISSUED",
                    },
                },
            )

        def run_research_org_session(self, invocation):
            raise AssertionError(invocation.runtime_instance_id)

    with pytest.raises(
        authoring.EvoChildAuthoringError,
        match="targeted_reconcile",
    ):
        _run(root, trust_root, bundle, pin, runner=StickyRuntime())
    assert launched == 1
    private = root.parent / "private-agent-session"
    assert not list(private.rglob("retry_authorized_journal.json"))
    assert not list(private.rglob("abandoned_journal.json"))
