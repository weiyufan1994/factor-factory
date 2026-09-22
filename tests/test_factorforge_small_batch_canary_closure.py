from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import scripts.run_factorforge_small_batch_canary_closure as canary
import scripts.validate_factorforge_small_batch_canary_closure as validator
from factor_factory.research_evidence import sha256_file
from factor_factory.research_org.contracts import stable_json_hash
from scripts.validate_factorforge_small_batch_canary_closure import (
    reject_unsupported_certificate,
    validate_certificate_invariants,
)


REQUIRED_ROLES = [
    "research_director",
    "knowledge_librarian",
    "data_liaison",
    "price_volume_researcher",
    "quant_implementation",
    "validation_evidence",
    "independent_council",
]


def role_payload(role_id="portfolio_manager"):
    return {
        "contract_version": "factorforge_small_batch_post_execution_role_v1",
        "role_id": role_id,
        "status": "PASS",
        "evidence_scope": "small_batch_canary_only",
        "finding_codes": ["ABSOLUTE_LONG_GATE_FAIL"],
        "decision": "CANARY_REJECT",
        "public_rationale": "The frozen long-side evidence fails the registered economic gate.",
        "production_authority": False,
    }


def council_payload(bindings):
    return {
        "contract_version": "factorforge_small_batch_investment_council_v1",
        "role_id": "independent_investment_council",
        "status": "PASS",
        "evidence_scope": "small_batch_canary_only",
        "reviewed_role_bindings": bindings,
        "terminal_decision": "CANARY_REJECT",
        "formal_factor_verdict": "NOT_ISSUED",
        "production_eligible": False,
        "official_promotion_allowed": False,
        "public_rationale": "Independent Council rejects the frozen canary implementation.",
    }


def certificate_payload():
    return {
        "payload_contract_version": "factorforge_small_batch_canary_closure_v1",
        "status": "COMPLETE",
        "execution_tier": "small_batch_canary",
        "terminal_decision": "CANARY_REJECT",
        "formal_factor_verdict": "NOT_ISSUED",
        "production_eligible": False,
        "official_promotion_allowed": False,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sample_bundle(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "source.csv"
    spec = tmp_path / "spec.json"
    calendar = tmp_path / "calendar.csv"
    runner = tmp_path / "runner.py"
    panel = tmp_path / "factor_panel.parquet"
    for path, content in (
        (source, "trade_date,close\n20250714,10\n"),
        (spec, "{}\n"),
        (calendar, "cal_date,is_open\n20250714,1\n"),
        (runner, "# frozen runner\n"),
        (panel, "immutable panel bytes\n"),
    ):
        path.write_text(content, encoding="utf-8")

    engine_relative = "scripts/run_factorforge_small_batch_canary_closure.py"
    engine_path = canary.REPO_ROOT / engine_relative
    manifest = {
        "contract_version": "factorforge_provisional_sample_manifest_v1",
        "status": "FROZEN_BEFORE_METRICS",
        "authority": "NON_FORMAL_CANARY_ONLY_NO_FACTOR_VERDICT",
        "factor_id": "FACTOR_TEST",
        "formula_hash": "1" * 64,
        "formula_ir_sha256": "2" * 64,
        "evaluation_contract_sha256": "3" * 64,
        "created_at_utc": "2026-08-13T00:00:00Z",
        "inputs": {
            "source_path": str(source),
            "source_sha256": sha256_file(source),
            "spec_path": str(spec),
            "spec_sha256": sha256_file(spec),
            "trusted_calendar_path": str(calendar),
            "trusted_calendar_sha256": sha256_file(calendar),
            "runner_path": str(runner),
            "runner_sha256": sha256_file(runner),
            "engine_source_sha256": {
                engine_relative: sha256_file(engine_path),
            },
        },
        "runtime_versions": {
            "python": "3.14",
            "numpy": "2",
            "pandas": "2",
            "pyarrow": "22",
        },
        "frozen_parameters": {
            "formal_oos_end": 20250711,
            "read_start": 20250714,
            "score_start": 20250808,
            "pseudo_holdout_start": 20260105,
            "read_end": 20260507,
            "cost_one_way": 0.003,
            "first_day_cash_entry_turnover": 1.0,
            "portfolio": "equal-weight top submitted-score decile",
            "label": "calendar-aligned close_t_plus_1_to_close_t_plus_2",
        },
    }
    manifest["content_sha256"] = stable_json_hash(manifest)
    manifest_path = tmp_path / "pre_metric_manifest.json"
    _write_json(manifest_path, manifest)
    metrics = {
        "status": "PROVISIONAL_NON_FORMAL_SAMPLE",
        "factor_id": "FACTOR_TEST",
        "formula_hash": "1" * 64,
        "formal_factor_verdict": "NOT_ISSUED",
        "panel": {"path": str(panel), "sha256": sha256_file(panel)},
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "admission": "bounded canary only",
        },
        "replay": {
            "pre_metric_manifest_path": str(manifest_path),
            "pre_metric_manifest_sha256": sha256_file(manifest_path),
            "runner_sha256": sha256_file(runner),
            "spec_sha256": sha256_file(spec),
            "trusted_calendar_sha256": sha256_file(calendar),
        },
        "frozen_before_metrics": {
            "formal_oos_end": "20250711",
            "read_start": "20250714",
            "score_start": "20250808",
            "pseudo_holdout_start": "20260105",
            "read_end": "20260507",
            "cost_one_way": 0.003,
            "portfolio": "equal-weight top submitted-score decile",
            "label": "calendar-aligned close_t_plus_2 / close_t_plus_1 - 1",
        },
    }
    metrics_path = tmp_path / "provisional_metrics.json"
    _write_json(metrics_path, metrics)
    return {
        "metrics": metrics_path,
        "panel": panel,
        "manifest": manifest_path,
    }


def install_valid_org_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    trust = tmp_path / "trust"
    for path in (workspace, private, trust):
        path.mkdir()
    current = {
        "verdict": "PASS",
        "contract_version": "factorforge_research_org_runtime_state_v1",
        "runtime_id": "runtime_" + "a" * 20,
        "lifecycle": "COMPLETE",
        "task_count": 7,
        "result_count": 7,
        "receipt_count": 6,
        "session_count": 6,
        "role_states": {role: "PASS" for role in REQUIRED_ROLES},
        "formal_independence_verified": True,
        "runtime_assurance": "signed_specialist_runtime_complete_host_director_external",
    }
    org_validation = tmp_path / "org_validation.json"
    _write_json(org_validation, current)
    plan = {
        "identity": {
            "factor_id": "FACTOR_TEST",
            "research_id": "research_test",
            "report_id": "REPORT_TEST",
            "job_id": "job_a812c0ffee",
        },
        "execution_policy": {"single_agent_fallback": False},
        "role_plan": {"required_roles": REQUIRED_ROLES},
    }
    (workspace / "identity").mkdir()
    _write_json(workspace / "identity/research_organization_plan.json", plan)
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: current,
    )
    monkeypatch.setattr(
        canary,
        "load_research_organization_plan",
        lambda _workspace: plan,
    )
    return {
        "workspace": workspace,
        "private": private,
        "trust": trust,
        "org_validation": org_validation,
    }


def invocation_kwargs(bundle: dict[str, Path], org: dict[str, Path]) -> dict:
    return {
        "workspace": org["workspace"],
        "metrics_path": bundle["metrics"],
        "panel_path": bundle["panel"],
        "manifest_path": bundle["manifest"],
        "org_validation_path": org["org_validation"],
        "org_private_root": org["private"],
        "trust_root": org["trust"],
        "installation_id": "installation-test-001",
    }


def test_small_batch_role_contract_accepts_canary_reject():
    assert canary.validate_role_result(role_payload(), "portfolio_manager") == []


def test_small_batch_role_contract_rejects_accept_and_production_authority():
    payload = role_payload()
    payload["decision"] = "ACCEPT"
    payload["production_authority"] = True
    reasons = canary.validate_role_result(payload, "portfolio_manager")
    assert "decision" in reasons
    assert "production_authority" in reasons


def test_small_batch_council_contract_binds_exact_role_results():
    bindings = [
        {"role_id": "portfolio_manager", "result_sha256": "a" * 64, "receipt_id": "b" * 64},
        {"role_id": "risk_officer", "result_sha256": "c" * 64, "receipt_id": "d" * 64},
        {"role_id": "execution_capacity", "result_sha256": "e" * 64, "receipt_id": "f" * 64},
    ]
    assert canary.validate_council_result(council_payload(bindings), bindings) == []


def test_formal_factor_verdict_is_always_not_issued():
    payload = council_payload([])
    payload["formal_factor_verdict"] = "ACCEPT"
    payload["production_eligible"] = True
    payload["official_promotion_allowed"] = True
    reasons = canary.validate_council_result(payload, [])
    assert "formal_factor_verdict" in reasons
    assert "production_eligible" in reasons
    assert "official_promotion_allowed" in reasons

    certificate = certificate_payload()
    certificate["formal_factor_verdict"] = "REJECT"
    assert "formal_factor_verdict" in validate_certificate_invariants(certificate)


def test_local_cli_workspace_write_and_self_signing_are_absent():
    source = inspect.getsource(canary)
    assert "workspace-write" not in source
    assert "subprocess" not in source
    assert "ensure_runtime_trust_store" not in source
    assert ".sign(" not in source
    with pytest.raises(
        canary.CanaryClosureError,
        match=canary.BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED,
    ):
        canary.dispatch_canary_sessions({"formal_factor_verdict": "NOT_ISSUED"})


def test_v4_style_manifest_and_actual_panel_are_exactly_bound(tmp_path: Path):
    bundle = sample_bundle(tmp_path)
    result = canary.validate_provisional_sample_bundle(
        metrics_path=bundle["metrics"],
        panel_path=bundle["panel"],
        manifest_path=bundle["manifest"],
    )
    assert result["formal_factor_verdict"] == "NOT_ISSUED"
    assert result["panel_sha256"] == sha256_file(bundle["panel"])
    bundle["panel"].write_text("tampered\n", encoding="utf-8")
    with pytest.raises(canary.CanaryClosureError, match="panel_hash_mismatch"):
        canary.validate_provisional_sample_bundle(
            metrics_path=bundle["metrics"],
            panel_path=bundle["panel"],
            manifest_path=bundle["manifest"],
        )


def test_panel_failure_prevents_any_session_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundle = sample_bundle(tmp_path)
    org = install_valid_org_replay(tmp_path, monkeypatch)
    bundle["panel"].write_text("tampered\n", encoding="utf-8")
    dispatched = []
    monkeypatch.setattr(canary, "dispatch_canary_sessions", dispatched.append)
    with pytest.raises(canary.CanaryClosureError, match="panel_hash_mismatch"):
        canary.run_canary_preflight_then_dispatch(**invocation_kwargs(bundle, org))
    assert dispatched == []


def test_current_org_replay_failure_prevents_any_session_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundle = sample_bundle(tmp_path)
    org = install_valid_org_replay(tmp_path, monkeypatch)
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("current org drift")),
    )
    dispatched = []
    monkeypatch.setattr(canary, "dispatch_canary_sessions", dispatched.append)
    with pytest.raises(
        canary.CanaryClosureError,
        match=canary.BLOCK_CANARY_PREFORMAL_ORG_REPLAY_INVALID,
    ):
        canary.run_canary_preflight_then_dispatch(**invocation_kwargs(bundle, org))
    assert dispatched == []


def test_valid_preflight_still_blocks_without_trusted_prompt_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundle = sample_bundle(tmp_path)
    org = install_valid_org_replay(tmp_path, monkeypatch)
    with pytest.raises(
        canary.CanaryClosureError,
        match=canary.BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED,
    ):
        canary.run_canary_preflight_then_dispatch(**invocation_kwargs(bundle, org))


def test_validator_never_accepts_even_well_shaped_legacy_certificate():
    with pytest.raises(
        canary.CanaryClosureError,
        match=canary.BLOCK_CANARY_CONTAINER_PROMPT_PROFILE_API_REQUIRED,
    ):
        reject_unsupported_certificate(
            certificate_payload(),
            {"formal_factor_verdict": "NOT_ISSUED"},
        )


def _legacy_certificates(workspace: Path, count: int = 3) -> list[Path]:
    paths: list[Path] = []
    for index in range(count):
        closure_id = f"small_batch_closure_{index + 1:016x}"
        path = (
            workspace
            / "tmp/small_batch_canary_closure"
            / closure_id
            / "canary_closure_certificate.json"
        )
        path.parent.mkdir(parents=True)
        payload = {
            **certificate_payload(),
            "closure_id": closure_id,
            "receipt_id": f"{index + 11:064x}",
            "preformal_organization": {
                "runtime_id": "runtime_stale_legacy",
                "formal_independence_verified": True,
            },
        }
        _write_json(path, payload)
        paths.append(path)
    return paths


def test_create_only_negative_index_permanently_invalidates_bound_legacy_certs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    org = install_valid_org_replay(tmp_path, monkeypatch)
    certificates = _legacy_certificates(org["workspace"])
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("current replay drift")),
    )
    first = canary.materialize_stale_legacy_invalidation_index(
        workspace=org["workspace"],
        org_private_root=org["private"],
        trust_root=org["trust"],
        installation_id="installation-test-001",
        certificate_paths=certificates,
    )
    assert first["written"] is True
    assert first["certificate_count"] == 3
    assert first["formal_factor_verdict"] == "NOT_ISSUED"
    index = canary.validate_legacy_invalidation_index(workspace=org["workspace"])
    assert index["invalidation_reason"] == (
        canary.STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
    )
    assert index["authority"] == {
        "scope": "NEGATIVE_ONLY",
        "formal_factor_verdict": "NOT_ISSUED",
        "certificate_acceptance_authority": False,
        "factor_verdict_authority": False,
        "permanent_for_bound_certificate_identity": True,
    }
    assert all(path.is_file() for path in certificates)
    assert (
        canary.certificate_invalidation_reason(
            workspace=org["workspace"], certificate_path=certificates[0]
        )
        == canary.STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
    )

    # A future repaired current validator cannot undo the closed negative index.
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: {"verdict": "PASS"},
    )
    assert (
        canary.certificate_invalidation_reason(
            workspace=org["workspace"], certificate_path=certificates[0]
        )
        == canary.STALE_LEGACY_INVALID_CURRENT_ORG_REPLAY
    )


def test_closed_negative_index_cannot_be_extended_or_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    org = install_valid_org_replay(tmp_path, monkeypatch)
    certificates = _legacy_certificates(org["workspace"], count=4)
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("current replay drift")),
    )
    canary.materialize_stale_legacy_invalidation_index(
        workspace=org["workspace"],
        org_private_root=org["private"],
        trust_root=org["trust"],
        installation_id="installation-test-001",
        certificate_paths=certificates[:3],
    )
    replay = canary.materialize_stale_legacy_invalidation_index(
        workspace=org["workspace"],
        org_private_root=org["private"],
        trust_root=org["trust"],
        installation_id="installation-test-001",
        certificate_paths=certificates[:3],
    )
    assert replay["written"] is False
    with pytest.raises(
        canary.CanaryClosureError,
        match="closed_index_certificate_set_conflict",
    ):
        canary.materialize_stale_legacy_invalidation_index(
            workspace=org["workspace"],
            org_private_root=org["private"],
            trust_root=org["trust"],
            installation_id="installation-test-001",
            certificate_paths=certificates,
        )


def test_validator_rejects_indexed_certificate_before_current_org_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    org = install_valid_org_replay(tmp_path, monkeypatch)
    certificate = _legacy_certificates(org["workspace"], count=1)[0]
    monkeypatch.setattr(
        canary,
        "validate_research_organization_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("current replay drift")),
    )
    canary.materialize_stale_legacy_invalidation_index(
        workspace=org["workspace"],
        org_private_root=org["private"],
        trust_root=org["trust"],
        installation_id="installation-test-001",
        certificate_paths=[certificate],
    )
    monkeypatch.setattr(
        validator,
        "validate_canary_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("indexed certificate must stop before replay")
        ),
    )
    monkeypatch.setattr(
        validator.sys,
        "argv",
        [
            "validate_factorforge_small_batch_canary_closure.py",
            "--certificate",
            str(certificate),
            "--workspace-root",
            str(org["workspace"]),
            "--metrics",
            "unused",
            "--panel",
            "unused",
            "--pre-metric-manifest",
            "unused",
            "--org-validation",
            "unused",
            "--org-private-root",
            "unused",
            "--trust-root",
            "unused",
            "--installation-id",
            "installation-test-001",
        ],
    )
    assert validator.main() == 1
    assert canary.BLOCK_CANARY_STALE_LEGACY_CERTIFICATE_INVALIDATED in (
        capsys.readouterr().err
    )
