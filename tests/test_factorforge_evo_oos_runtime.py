from __future__ import annotations

import json
from pathlib import Path

import pytest

import factor_factory.research_release as research_release_module
from factor_factory.evo_oos import (
    BLOCK_OOS_ALLOCATION,
    OOS_ALLOCATION_AUTHORITY_SECURE,
    OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
    WAITING_FRESH_OOS,
    _allocate_fresh_child_oos,
    allocate_fresh_child_oos,
    build_fresh_child_oos_allocation,
    consume_oos_allocation_for_release,
    oos_allocation_path,
    oos_allocation_receipt_path,
    oos_registry_path,
    sha256_file,
    validate_child_oos_finalizer_authority,
    validate_fresh_child_oos_allocation,
    validate_oos_registry,
    validate_oos_release_authorization,
    validate_oos_release_consumption,
    write_registry_cas,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_release import (
    METRIC_VERIFIER_SPEC_VERSION,
    stable_hash as release_hash,
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_ID = "test-oos-host"


@pytest.fixture(autouse=True)
def _incident_host_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = tmp_path / "private-host-trust"
    ensure_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT", str(trust_root)
    )
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID", INSTALLATION_ID
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    root.mkdir()
    trust_root = tmp_path / "private-host-trust"
    ensure_runtime_trust_store(trust_root, installation_id=INSTALLATION_ID)
    return root, trust_root


def _allocate(
    root: Path,
    trust_root: Path,
    *,
    report_id: str = "CHILD_A",
    parent_report_id: str = "ROOT_REPORT",
    allocation_id: str = "allocation_child_a_001",
    dataset: str = "a" * 64,
    start: str = "2026-01-01",
    end: str = "2026-03-31",
    token: str = "b" * 64,
    expected: str | None = None,
) -> dict:
    source = root / "identity" / f"allocation_authority_source__{report_id}.json"
    _write_json(source, {"report_id": report_id, "source": "test_fixture"})
    build_authority = {
        "contract_version": OOS_ALLOCATION_BUILD_AUTHORITY_VERSION,
        "allocation_id": allocation_id,
        "report_id": report_id,
        "parent_report_id": parent_report_id,
        "selected_revision": {
            "child_formula": "close",
            "child_formula_hash": "e" * 64,
        },
        "authority_refs": {
            "test_source": {
                "path": source.relative_to(root).as_posix(),
                "sha256": sha256_file(source),
            }
        },
        "calendar_authority": {
            "snapshot_id": "test-calendar",
            "open_dates_sha256": "1" * 64,
            "raw_file_sha256": "2" * 64,
            "registry_sha256": "3" * 64,
            "registry_git_commit": "test-commit",
            "registry_git_blob": "test-blob",
        },
        "universe_binding": {
            "universe_id": "test-universe",
            "investability_mask_id": "test-mask",
        },
        "oos_window": {"start": start, "end": end},
        "sealed_token_sha256": token,
        "sealed_carrier_sha256": "f" * 64,
        "dataset_snapshot_sha256": dataset,
        "projection_row_count": 1,
        "projection_period_count": 60,
    }
    return _allocate_fresh_child_oos(
        workspace_root=root,
        allocation_id=allocation_id,
        report_id=report_id,
        parent_report_id=parent_report_id,
        dataset_snapshot_sha256=dataset,
        oos_start=start,
        oos_end=end,
        sealed_token_sha256=token,
        sealed_carrier_sha256="f" * 64,
        build_authority_sha256=release_hash(build_authority),
        build_authority=build_authority,
        allocation_authority_mode=OOS_ALLOCATION_AUTHORITY_SECURE,
        expected_registry_sha256=expected,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )


def _release(
    root: Path,
    *,
    report_id: str = "CHILD_A",
    dataset: str = "a" * 64,
    token: str = "b" * 64,
    name: str | None = None,
) -> Path:
    protocol = root / "objects/research_protocol"
    ledger_path = protocol / f"search_trial_ledger__{report_id}.json"
    threshold_path = protocol / f"threshold_registration__{report_id}.json"
    if not ledger_path.exists():
        _write_json(ledger_path, {"report_id": report_id, "status": "FROZEN"})
    if not threshold_path.exists():
        _write_json(threshold_path, {"report_id": report_id, "status": "LOCKED"})
    path = (
        protocol
        / (name or f"oos_release_manifest__{report_id}.json")
    )
    payload = {
        "version": "factorforge_oos_release_manifest_v1",
        "release_status": "RELEASED",
        "report_id": report_id,
        "factor_id": "FACTOR_A",
        "release_sequence": 30,
        "search_trial_ledger_ref": ledger_path.relative_to(root).as_posix(),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "threshold_registration_ref": threshold_path.relative_to(root).as_posix(),
        "threshold_registration_sha256": sha256_file(threshold_path),
        "dataset_snapshot_hash": dataset,
        "window_hash": "c" * 64,
        "evaluation_contract_hash": "d" * 64,
        "oos_window": "2026-01-01/2026-03-31",
        "observed_start_date": "2026-01-01",
        "observed_end_date": "2026-03-31",
        "observed_period_count": 60,
        "oos_release_token_hash": token,
    }
    payload["release_manifest_sha256"] = release_hash(payload)
    _write_json(path, payload)
    return path


def test_host_signed_allocation_is_required_and_tamper_fails(tmp_path: Path) -> None:
    root, trust_root = _roots(tmp_path)
    result = _allocate(root, trust_root)
    assert result["status"] == "ALLOCATED"
    registry = json.loads(oos_registry_path(root).read_text(encoding="utf-8"))
    assert validate_oos_registry(registry, workspace_root=root) == []

    receipt_path = oos_allocation_receipt_path(root, "CHILD_A")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["dataset_snapshot_sha256"] = "f" * 64
    _write_json(receipt_path, receipt)
    reasons = validate_oos_registry(registry, workspace_root=root)
    assert any("allocation_host_receipt" in reason for reason in reasons)


def test_duplicate_token_and_sibling_window_are_blocked_before_write(
    tmp_path: Path,
) -> None:
    root, trust_root = _roots(tmp_path)
    first = _allocate(root, trust_root)
    current = first["registry_sha256"]
    with pytest.raises(ValueError, match="sealed_token_reused"):
        _allocate(
            root,
            trust_root,
            report_id="CHILD_B",
            allocation_id="allocation_child_b_001",
            dataset="c" * 64,
            start="2026-04-01",
            end="2026-06-30",
            token="b" * 64,
            expected=current,
        )
    assert not oos_allocation_path(root, "CHILD_B").exists()

    with pytest.raises(ValueError, match="lineage_dataset_window_reused"):
        _allocate(
            root,
            trust_root,
            report_id="CHILD_C",
            allocation_id="allocation_child_c_001",
            dataset="a" * 64,
            start="2026-03-01",
            end="2026-05-31",
            token="d" * 64,
            expected=current,
        )
    assert not oos_allocation_path(root, "CHILD_C").exists()


def test_locked_cas_allows_only_one_concurrent_first_append(tmp_path: Path) -> None:
    root, trust_root = _roots(tmp_path)
    import concurrent.futures

    def allocate(report: str, allocation: str, token: str, start: str, end: str):
        try:
            return _allocate(
                root,
                trust_root,
                report_id=report,
                allocation_id=allocation,
                token=token,
                start=start,
                end=end,
                expected=None,
            )
        except ValueError as exc:
            return exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: allocate(*args),
                [
                    ("CHILD_A", "allocation_child_a_001", "b" * 64, "2026-01-01", "2026-03-31"),
                    ("CHILD_B", "allocation_child_b_001", "c" * 64, "2026-04-01", "2026-06-30"),
                ],
            )
        )
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum("registry_cas_mismatch" in str(item) for item in outcomes) == 1
    assert next(item for item in outcomes if isinstance(item, dict))["status"] == "ALLOCATED"
    registry = json.loads(oos_registry_path(root).read_text(encoding="utf-8"))
    assert len(registry["events"]) == 1
    assert validate_oos_registry(registry, workspace_root=root) == []


def test_release_consumes_once_identical_replay_does_not_append(
    tmp_path: Path,
) -> None:
    root, trust_root = _roots(tmp_path)
    _allocate(root, trust_root)
    allocation_only_registry = json.loads(
        oos_registry_path(root).read_text(encoding="utf-8")
    )
    assert any(
        "release_allocation_binding" in reason
        for reason in validate_oos_release_authorization(
            workspace_root=root,
            report_id="CHILD_A",
            oos_window="2026-01-01/2026-03-31",
            sealed_token_sha256="f" * 64,
        )
    )
    forged_release = (
        root
        / "objects/research_protocol"
        / "oos_release_manifest__CHILD_A__forged.json"
    )
    _write_json(
        forged_release,
        {
            "release_status": "RELEASED",
            "report_id": "CHILD_A",
            "dataset_snapshot_hash": "a" * 64,
            "oos_window": "2026-01-01/2026-03-31",
            "oos_release_token_hash": "b" * 64,
        },
    )
    with pytest.raises(ValueError, match="release_evidence_shape"):
        consume_oos_allocation_for_release(
            workspace_root=root,
            report_id="CHILD_A",
            release_manifest_path=forged_release,
        )
    assert len(
        json.loads(oos_registry_path(root).read_text(encoding="utf-8"))["events"]
    ) == 1
    release_path = _release(root)
    first = consume_oos_allocation_for_release(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    )
    assert first["status"] == "CONSUMED"
    assert validate_oos_release_consumption(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    ) == []
    second = consume_oos_allocation_for_release(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    )
    assert second["status"] == "IDENTICAL_CONSUMPTION_REPLAY"
    registry = json.loads(oos_registry_path(root).read_text(encoding="utf-8"))
    assert [event["event_type"] for event in registry["events"]] == [
        "ALLOCATE",
        "CONSUME",
    ]
    with pytest.raises(ValueError, match="registry_not_append_only"):
        write_registry_cas(
            oos_registry_path(root),
            allocation_only_registry,
            expected_parent_sha256=sha256_file(oos_registry_path(root)),
        )

    second_path = _release(root, name="oos_release_manifest__CHILD_A__replay.json")
    with pytest.raises(ValueError, match="allocation_already_consumed"):
        consume_oos_allocation_for_release(
            workspace_root=root,
            report_id="CHILD_A",
            release_manifest_path=second_path,
        )
    assert f"{BLOCK_OOS_ALLOCATION}:allocation_not_available" in (
        validate_fresh_child_oos_allocation(
            root=root,
            parent_report_id="ROOT_REPORT",
            child_report_id="CHILD_A",
            allocation_id="allocation_child_a_001",
            allocation_ref=oos_allocation_path(root, "CHILD_A")
            .relative_to(root)
            .as_posix(),
        )
    )


def test_finalizer_authority_accepts_fresh_and_both_release_crash_states(
    tmp_path: Path,
) -> None:
    root, trust_root = _roots(tmp_path)
    _allocate(root, trust_root)
    common = {
        "workspace_root": root,
        "parent_report_id": "ROOT_REPORT",
        "child_report_id": "CHILD_A",
        "allocation_id": "allocation_child_a_001",
    }
    assert validate_child_oos_finalizer_authority(**common) == []

    # Crash after immutable release write but before registry consumption.
    release_path = _release(root)
    assert validate_child_oos_finalizer_authority(**common) == []

    consume_oos_allocation_for_release(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    )
    assert validate_child_oos_finalizer_authority(**common) == []

    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["dataset_snapshot_hash"] = "f" * 64
    release["release_manifest_sha256"] = release_hash(
        {
            key: value
            for key, value in release.items()
            if key != "release_manifest_sha256"
        }
    )
    _write_json(release_path, release)
    assert validate_child_oos_finalizer_authority(**common)


def test_unregistered_allocation_cannot_be_consumed(tmp_path: Path) -> None:
    root, _trust_root = _roots(tmp_path)
    allocation = build_fresh_child_oos_allocation(
        allocation_id="allocation_child_a_001",
        report_id="CHILD_A",
        parent_report_id="ROOT_REPORT",
        lineage_root_report_id="ROOT_REPORT",
        dataset_snapshot_sha256="a" * 64,
        oos_start="2026-01-01",
        oos_end="2026-03-31",
        sealed_token_sha256="b" * 64,
    )
    _write_json(oos_allocation_path(root, "CHILD_A"), allocation)
    release_path = _release(root)
    with pytest.raises(ValueError, match="incident_lineage_registry_missing"):
        consume_oos_allocation_for_release(
            workspace_root=root,
            report_id="CHILD_A",
            release_manifest_path=release_path,
        )


@pytest.mark.parametrize(
    ("delete_allocation", "delete_registry", "expected_suffixes"),
    [
        (True, False, ["allocation_missing_or_noncanonical"]),
        (False, True, ["registry_missing"]),
        (
            True,
            True,
            ["allocation_missing_or_noncanonical", "registry_missing"],
        ),
    ],
)
def test_evo_child_cannot_fall_back_to_legacy_after_oos_control_deletion(
    tmp_path: Path,
    delete_allocation: bool,
    delete_registry: bool,
    expected_suffixes: list[str],
) -> None:
    root, trust_root = _roots(tmp_path)
    _allocate(root, trust_root)
    intent_path = (
        root
        / "objects/research_protocol"
        / "evo_child_intent__CHILD_A.json"
    )
    _write_json(
        intent_path,
        {
            "contract_version": "factorforge_pre_oos_child_intent_projection_v1",
            "parent_report_id": "ROOT_REPORT",
            "child_report_id": "CHILD_A",
        },
    )
    if delete_allocation:
        oos_allocation_path(root, "CHILD_A").unlink()
    if delete_registry:
        oos_registry_path(root).unlink()
    release_path = _release(root)

    authorization = validate_oos_release_authorization(
        workspace_root=root,
        report_id="CHILD_A",
        oos_window="2026-01-01/2026-03-31",
        sealed_token_sha256="b" * 64,
    )
    assert authorization == [
        f"{WAITING_FRESH_OOS}:{suffix}" for suffix in expected_suffixes
    ]
    assert validate_oos_release_consumption(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    ) == authorization
    with pytest.raises(ValueError, match=WAITING_FRESH_OOS):
        consume_oos_allocation_for_release(
            workspace_root=root,
            report_id="CHILD_A",
            release_manifest_path=release_path,
        )


def test_original_candidate_without_evo_child_markers_remains_explicit_legacy(
    tmp_path: Path,
) -> None:
    root, _trust_root = _roots(tmp_path)
    assert validate_oos_release_authorization(
        workspace_root=root,
        report_id="ORIGINAL_CANDIDATE",
        oos_window="2026-01-01/2026-03-31",
        sealed_token_sha256="b" * 64,
    ) == []


def test_ancestor_release_and_descendant_or_sibling_reuse_are_blocked(
    tmp_path: Path,
) -> None:
    root, trust_root = _roots(tmp_path)
    _write_json(
        root / "objects/research_protocol/oos_release_manifest__ROOT_REPORT.json",
        {
            "release_status": "RELEASED",
            "report_id": "ROOT_REPORT",
            "dataset_snapshot_hash": "a" * 64,
            "oos_window": "2026-01-01/2026-03-31",
            "oos_release_token_hash": "e" * 64,
        },
    )
    with pytest.raises(ValueError, match="ancestor_or_sibling_dataset_window_reused"):
        _allocate(root, trust_root)
    assert not oos_allocation_path(root, "CHILD_A").exists()

    (root / "objects/research_protocol/oos_release_manifest__ROOT_REPORT.json").unlink()
    first = _allocate(root, trust_root)
    _write_json(
        root / "objects/research_protocol/oos_release_manifest__ROOT_REPORT.json",
        {
            "release_status": "RELEASED",
            "report_id": "ROOT_REPORT",
            "dataset_snapshot_hash": "a" * 64,
            "oos_window": "2025-01-01/2025-03-31",
            "oos_release_token_hash": "e" * 64,
        },
    )
    with pytest.raises(ValueError, match="ancestor_or_sibling_dataset_window_reused"):
        _allocate(
            root,
            trust_root,
            report_id="GRANDCHILD_A",
            parent_report_id="CHILD_A",
            allocation_id="allocation_grandchild_a_001",
            dataset="a" * 64,
            start="2025-02-01",
            end="2025-04-30",
            token="f" * 64,
            expected=first["registry_sha256"],
        )


def test_research_release_writes_manifest_and_consumes_registered_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root = _roots(tmp_path)
    _allocate(root, trust_root)
    protocol = root / "objects/research_protocol"
    ledger_path = protocol / "search_trial_ledger__CHILD_A.json"
    threshold_path = protocol / "threshold_registration__CHILD_A.json"
    release_path = protocol / "oos_release_manifest__CHILD_A.json"
    write_search_trial_ledger(
        ledger_path,
        report_id="CHILD_A",
        factor_id="FACTOR_A",
        trials=[{"trial_id": "trial_001"}],
        candidate_space={"candidate": "frozen"},
        selected_hypothesis={"hypothesis_id": "preferred"},
    )
    window = {
        "oos_window": "2026-01-01/2026-03-31",
        "oos_release_token_hash": "b" * 64,
        "search_trial_ledger_ref": ledger_path.relative_to(root).as_posix(),
        "oos_release_manifest_ref": release_path.relative_to(root).as_posix(),
    }
    label = {"version": "test_label_contract_v1"}
    spec = {
        "version": METRIC_VERIFIER_SPEC_VERSION,
        "verification_scope": "production",
        "report_id": "CHILD_A",
        "factor_id": "FACTOR_A",
        "claim_class": "information_rent",
        "cost_policy_id": "cost_v1",
        "window_contract": window,
        "panel": {"signal_column": "factor_value"},
        "portfolio": {"return_path_mode": "daily_one_period_forward_return"},
        "label_contract": label,
        "fama_macbeth": {},
        "bucket_monotonicity": {},
        "threshold_registration_ref": threshold_path.relative_to(root).as_posix(),
    }
    rules = [
        {"rule_id": "ic", "metric_path": "metrics.ic.mean", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "icir", "metric_path": "metrics.icir.value", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "vol", "metric_path": "metrics.volatility_cost.realized_volatility_drag", "operator": "<=", "threshold": 1.0, "on_fail": "REJECT"},
        {"rule_id": "cost", "metric_path": "metrics.transaction_cost.net_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "drawdown", "metric_path": "metrics.drawdown.max_drawdown", "operator": ">=", "threshold": -0.35, "on_fail": "REJECT"},
        {"rule_id": "long", "metric_path": "metrics.long_end.net_geometric_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
    ]
    write_threshold_registration(
        threshold_path,
        workspace_root=root,
        spec=spec,
        decision_rules=rules,
    )
    identities = {
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": release_hash(window),
        "label_contract_hash": release_hash(label),
        "observed_start_date": "2026-01-01",
        "observed_end_date": "2026-03-31",
        "observed_period_count": 60,
    }
    with pytest.raises(ValueError, match="release_allocation_binding"):
        write_oos_release_manifest(
            release_path,
            workspace_root=root,
            spec=spec,
            identities={**identities, "dataset_snapshot_hash": "c" * 64},
            threshold_path=threshold_path,
        )
    assert not release_path.exists()
    real_consume = research_release_module.consume_oos_allocation_for_release

    def _crash_after_manifest(**_kwargs):
        raise RuntimeError("simulated crash after immutable release write")

    monkeypatch.setattr(
        research_release_module,
        "consume_oos_allocation_for_release",
        _crash_after_manifest,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        write_oos_release_manifest(
            release_path,
            workspace_root=root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
        )
    assert release_path.is_file()
    assert validate_oos_release_authorization(
        workspace_root=root,
        report_id="CHILD_A",
        oos_window="2026-01-01/2026-03-31",
        sealed_token_sha256="b" * 64,
    ) == []
    monkeypatch.setattr(
        research_release_module,
        "consume_oos_allocation_for_release",
        real_consume,
    )
    write_oos_release_manifest(
        release_path,
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
    )
    write_oos_release_manifest(
        release_path,
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
    )
    assert validate_oos_release_consumption(
        workspace_root=root,
        report_id="CHILD_A",
        release_manifest_path=release_path,
    ) == []
    registry = json.loads(oos_registry_path(root).read_text(encoding="utf-8"))
    assert [event["event_type"] for event in registry["events"]] == [
        "ALLOCATE",
        "CONSUME",
    ]
