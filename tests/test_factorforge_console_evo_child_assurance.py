from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import factor_factory.console.evo_child_assurance as child_assurance
from factor_factory.console.evo_child_assurance import (
    REVIEW_VERSION,
    EvoChildAssuranceError,
    materialize_evo_child_assurance,
    validate_evo_child_assurance,
)
from tests.evo_child_authoring_fixtures import SignedEvoChildAuthoringFakeRunner
from tests.test_factorforge_evo_child_authoring import (
    CHILD,
    INSTALLATION,
    PARENT,
    _fixture,
    _run,
)
from scripts import run_factorforge_ultimate as ultimate


def _review(verdict: str = "PASS") -> dict:
    passed = verdict == "PASS"
    return {
        "version": REVIEW_VERSION,
        "child_report_id": CHILD,
        "verdict": verdict,
        "checks": {
            "approved_revision_exact": passed,
            "economic_backprojection_preserved": passed,
            "frozen_evaluation_preserved": passed,
            "fresh_oos_unobserved": passed,
            "self_authorization_absent": passed,
        },
    }


def test_isolated_independent_review_yields_truthful_revision_child_assurance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        child_assurance,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: child_assurance.load_runtime_trust_store(
            trust, installation_id=INSTALLATION
        ).public_manifest,
    )
    _run(root, trust, bundle, pin)
    result = materialize_evo_child_assurance(
        runner=SignedEvoChildAuthoringFakeRunner(
            semantic_bundle=_review(),
            trust_root=trust,
            installation_id=INSTALLATION,
        ),
        workspace_root=root,
        worktree=root,
        private_root=tmp_path / "review-private",
        trust_root=trust,
        installation_id=INSTALLATION,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=pin,
        timeout_seconds=60,
    )
    assert result["status"] == "REVISION_CHILD_FORMAL_ASSURANCE"
    assert result["assurance"]["assurance_scope"]["kind"] == (
        "REVISION_CHILD_NOT_FULL_SEVEN_ROLE_RESEARCH_ORG"
    )
    assert result["assurance"]["review_runtime"]["role_id"] == (
        "evo_child_independent_reviewer"
    )


def test_review_block_or_assurance_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        child_assurance,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: child_assurance.load_runtime_trust_store(
            trust, installation_id=INSTALLATION
        ).public_manifest,
    )
    _run(root, trust, bundle, pin)
    with pytest.raises(EvoChildAssuranceError, match="independent_review_failed"):
        materialize_evo_child_assurance(
            runner=SignedEvoChildAuthoringFakeRunner(
                semantic_bundle=_review("BLOCK"),
                trust_root=trust,
                installation_id=INSTALLATION,
            ),
            workspace_root=root,
            worktree=root,
            private_root=tmp_path / "review-private",
            trust_root=trust,
            installation_id=INSTALLATION,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=pin,
            timeout_seconds=60,
        )

    result = materialize_evo_child_assurance(
        runner=SignedEvoChildAuthoringFakeRunner(
            semantic_bundle=_review(),
            trust_root=trust,
            installation_id=INSTALLATION,
        ),
        workspace_root=root,
        worktree=root,
        private_root=tmp_path / "review-private-2",
        trust_root=trust,
        installation_id=INSTALLATION,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=pin,
        timeout_seconds=60,
    )
    path = Path(result["assurance_path"])
    payload = json.loads(path.read_text())
    payload["assurance_scope"]["kind"] = "FULL_SEVEN_ROLE_RESEARCH_ORG"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvoChildAssuranceError, match="exact_replay"):
        validate_evo_child_assurance(
            workspace_root=root,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            assurance=path,
            expected_host_trust_manifest_sha256=pin,
        )


def test_ultimate_revision_child_gate_is_truthful_not_parent_seven_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        ultimate,
        "resolve_report_scoped_web_research_plan",
        lambda *_args, **_kwargs: {"parent_report_id": PARENT},
    )
    monkeypatch.setattr(
        ultimate,
        "validate_evo_child_assurance",
        lambda **_kwargs: {
            "assurance_ref": {"path": "assurance.json", "sha256": "a" * 64}
        },
    )
    result = ultimate.resolve_research_organization_runtime_gate(
        args=SimpleNamespace(
            research_org_runtime_mode="revision-child-assured",
            evo_child_research_org_assurance=str(assurance),
            report_id=CHILD,
            expected_host_trust_manifest_sha256="b" * 64,
        ),
        factor_workspace=tmp_path,
    )
    assert result["formal_independence_verified"] is True
    assert result["runtime_assurance"] == (
        "revision_child_not_full_seven_role_org"
    )
    assert result["child_report_id"] == CHILD


def test_assurance_completion_journal_replays_after_public_write_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        child_assurance,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: child_assurance.load_runtime_trust_store(
            trust, installation_id=INSTALLATION
        ).public_manifest,
    )
    _run(root, trust, bundle, pin)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=_review(),
        trust_root=trust,
        installation_id=INSTALLATION,
    )
    calls = 0

    class CountingRunner:
        def run_research_org_session(self, invocation):
            nonlocal calls
            calls += 1
            return delegate.run_research_org_session(invocation)

    original_write = child_assurance._write_once
    crashed = False

    def crash_public(root_path, output_path, raw):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated_assurance_public_kill")
        return original_write(root_path, output_path, raw)

    monkeypatch.setattr(child_assurance, "_write_once", crash_public)
    kwargs = {
        "workspace_root": root,
        "worktree": root,
        "private_root": tmp_path / "review-private",
        "trust_root": trust,
        "installation_id": INSTALLATION,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": pin,
        "timeout_seconds": 60,
    }
    with pytest.raises(RuntimeError, match="assurance_public_kill"):
        materialize_evo_child_assurance(
            runner=CountingRunner(), **kwargs
        )
    monkeypatch.setattr(child_assurance, "_write_once", original_write)

    class MustNotRun:
        def run_research_org_session(self, invocation):
            raise AssertionError(invocation.runtime_instance_id)

    recovered = materialize_evo_child_assurance(
        runner=MustNotRun(), **kwargs
    )
    assert recovered["status"] == "REVISION_CHILD_FORMAL_ASSURANCE"
    assert calls == 1


def test_assurance_launch_only_restart_reconciles_before_new_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        child_assurance,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: child_assurance.load_runtime_trust_store(
            trust, installation_id=INSTALLATION
        ).public_manifest,
    )
    _run(root, trust, bundle, pin)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=_review(),
        trust_root=trust,
        installation_id=INSTALLATION,
    )
    launched: list[str] = []
    reconciled: list[str] = []
    kwargs = {
        "workspace_root": root,
        "worktree": root,
        "private_root": tmp_path / "review-private",
        "trust_root": trust,
        "installation_id": INSTALLATION,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": pin,
        "timeout_seconds": 60,
    }

    class CrashAfterReview:
        def run_research_org_session(self, invocation):
            launched.append(invocation.runtime_instance_id)
            delegate.run_research_org_session(invocation)
            raise RuntimeError("simulated_review_host_kill")

    with pytest.raises(RuntimeError, match="review_host_kill"):
        materialize_evo_child_assurance(
            runner=CrashAfterReview(), **kwargs
        )

    class RecoveringRunner:
        def reconcile_research_org_session(self, runtime_instance_id):
            reconciled.append(runtime_instance_id)
            return delegate.reconcile_research_org_session(runtime_instance_id)

        def run_research_org_session(self, invocation):
            launched.append(invocation.runtime_instance_id)
            return delegate.run_research_org_session(invocation)

    result = materialize_evo_child_assurance(
        runner=RecoveringRunner(), **kwargs
    )
    assert result["status"] == "REVISION_CHILD_FORMAL_ASSURANCE"
    assert reconciled == [launched[0]]
    assert len(launched) == 2
    assert launched[0] != launched[1]
    sessions = sorted(
        (tmp_path / "review-private").rglob("evo-child-assurance-*")
    )
    assert len(sessions) == 2
    assert sum((path / "abandoned_journal.json").is_file() for path in sessions) == 1
    assert sum(
        (path / "retry_authorized_journal.json").is_file()
        for path in sessions
    ) == 1


def test_assurance_private_lock_prevents_duplicate_review_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust, bundle, _material, pin = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        child_assurance,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: child_assurance.load_runtime_trust_store(
            trust, installation_id=INSTALLATION
        ).public_manifest,
    )
    _run(root, trust, bundle, pin)
    delegate = SignedEvoChildAuthoringFakeRunner(
        semantic_bundle=_review(),
        trust_root=trust,
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

    kwargs = {
        "runner": BlockingRunner(),
        "workspace_root": root,
        "worktree": root,
        "private_root": tmp_path / "review-private",
        "trust_root": trust,
        "installation_id": INSTALLATION,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": pin,
        "timeout_seconds": 60,
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(materialize_evo_child_assurance, **kwargs)
        assert entered.wait(timeout=5)
        second = executor.submit(materialize_evo_child_assurance, **kwargs)
        time.sleep(0.1)
        assert calls == 1
        release.set()
        assert first.result(timeout=5)["verdict"] == "PASS"
        assert second.result(timeout=5)["verdict"] == "PASS"
    assert calls == 1
