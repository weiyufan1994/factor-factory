from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from factor_factory.research_org import (
    AGENT_RESULT_CONTRACT_VERSION,
    ResearchOrganizationError,
    admit_agent_result,
    build_agent_registry_snapshot,
    load_research_organization_plan,
    resolve_research_organization_gate,
    route_research_request,
    validate_agent_result,
    validate_research_organization_bundle,
    write_research_organization_bundle,
)
from factor_factory.research_org.contracts import (
    BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID,
    BLOCK_RESEARCH_ORG_PLAN_INVALID,
    BLOCK_RESEARCH_ORG_RESULT_INVALID,
    stable_json_hash,
    with_content_hash,
)
from factor_factory.research_org.registry import validate_agent_registry_snapshot
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    workspace = runtime / "factor_research" / "ORG_FACTOR" / "org_research"
    manifest = build_workspace_manifest(
        repo_root=PROJECT_ROOT,
        factorforge_root=runtime,
        factor_id="ORG_FACTOR",
        research_id="org_research",
        root_report_id="ORG_REPORT",
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    identity = workspace / "identity"
    (identity / "web_research_request.json").write_text("{}\n", encoding="utf-8")
    (identity / "web_research_authoring_contract.json").write_text("{}\n", encoding="utf-8")
    (identity / "factor_knowledge_summary.json").write_text("{}\n", encoding="utf-8")
    (identity / "data_catalog_summary.json").write_text("{}\n", encoding="utf-8")
    return workspace


def _request(*, hypothesis: str, title: str = "Research idea") -> dict:
    return {
        "job_id": "job_org_001",
        "factor_id": "ORG_FACTOR",
        "research_id": "org_research",
        "report_id": "ORG_REPORT",
        "title": title,
        "hypothesis": hypothesis,
        "input_kind": "hypothesis",
        "conversation_snapshot": {
            "messages": [
                {
                    "sequence_no": 1,
                    "role": "user",
                    "content_kind": "hypothesis",
                    "content": hypothesis,
                }
            ]
        },
    }


def _task(workspace: Path, role_id: str) -> dict:
    plan = load_research_organization_plan(workspace)
    dispatch_path = workspace / plan["workspace_policy"]["dispatch_manifest_path"]
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    reference = next(item for item in dispatch["tasks"] if item["role_id"] == role_id)
    return json.loads((workspace / reference["path"]).read_text(encoding="utf-8"))


def _result(task: dict, *, producer_mode: str = "real_agent", session_id: str = "agent_session_1") -> dict:
    if task["role_id"] == "data_liaison":
        public_record = {
            "contract_version": task["output_contract"],
            "identity": {
                "task_id": task["task_id"],
                "factor_id": task["identity"]["factor_id"],
                "research_id": task["identity"]["research_id"],
                "report_id": task["identity"]["report_id"],
                "agent_role": task["role_id"],
            },
            "domain": "data_liaison",
            "proposal_status": "ready_for_director_review",
            "domain_fit": {"fit": "interface", "reason": "Catalog contract checked."},
            "catalog_resolution": {
                "reuse_hits": [],
                "generated_data_requests": [],
            },
            "delivery_receipt_verification": {"status": "not_required"},
            "knowledge_use": [],
            "permissions_boundary": {"data_materialization": False},
            "uncertainties": [],
            "handoff": {"status": "ready_for_host_review"},
        }
    elif task["output_contract"] == "factorforge_domain_research_proposal_v1":
        public_record = {
            "contract_version": task["output_contract"],
            "identity": {
                "task_id": task["task_id"],
                "factor_id": task["identity"]["factor_id"],
                "research_id": task["identity"]["research_id"],
                "report_id": task["identity"]["report_id"],
                "agent_role": task["role_id"],
            },
            "domain": (
                "fundamental"
                if task["role_id"] == "fundamental_researcher"
                else "price_volume"
            ),
            "proposal_status": "ready_for_director_review",
            "domain_fit": {"fit": "primary", "reason": "Mechanism-aligned."},
            "public_research_record": {"public_derivation_summary": ["Define and falsify."]},
            "math_model_search": {"candidates": ["primary", "alternative", "null"]},
            "measurement_proposal": {"implementation_route": "direct_code"},
            "knowledge_use": [],
            "data_dependencies": [],
            "falsification_plan": {"distinguishing_tests": ["null test"]},
            "uncertainties": [],
            "artifact_refs": [],
            "handoff": {"status": "ready_for_host_review"},
        }
    else:
        public_record = {
            "contract_version": task["output_contract"],
            "executive_summary": "Public, reproducible research conclusion.",
            "claims": [
                {
                    "claim": "The selected mechanism is testable.",
                    "falsifier": "The predicted conditional signature is absent.",
                }
            ],
            "artifact_refs": [],
            "handoff": {"status": "ready_for_host_review"},
        }
    payload = {
        "contract_version": AGENT_RESULT_CONTRACT_VERSION,
        "task_ref": {"task_id": task["task_id"], "sha256": task["task_sha256"]},
        "identity": task["identity"],
        "role_id": task["role_id"],
        "status": "PASS",
        "producer_mode": producer_mode,
        "session_id": session_id,
        "public_research_record": public_record,
    }
    if task["role_id"] == "independent_council":
        payload["independence_attestation"] = {
            "independence_satisfied": producer_mode == "real_agent",
            "reviewed_role_ids": task["required_review_role_ids"],
        }
    return with_content_hash(payload, hash_field="result_sha256")


def test_registry_snapshot_is_deterministic_and_valid() -> None:
    first = build_agent_registry_snapshot()
    second = build_agent_registry_snapshot()
    assert first == second
    assert validate_agent_registry_snapshot(first) == []
    roles = {item["role_id"]: item for item in first["roles"]}
    assert roles["event_researcher"]["status"] == "planned"
    assert roles["independent_council"]["session_requirement"] == "independent_session"


def test_router_prioritizes_economic_hypothesis_over_formula_fields() -> None:
    request = _request(
        title="Legal-time FCF valuation gap",
        hypothesis=(
            "Use discounted cash flow, WACC and terminal value to estimate a valuation gap. "
            "The implementation may use close and volume only as controls."
        ),
    )
    request["conversation_snapshot"]["messages"].append(
        {
            "sequence_no": 2,
            "role": "user",
            "content_kind": "formula",
            "content": "RANK(CLOSE / TS_MEAN(VOLUME, 20))",
        }
    )
    route = route_research_request(request)
    assert route["route_state"] == "ROUTED"
    assert route["lead_domain"] == "fundamental"
    assert route["domain_scores"]["fundamental"] > route["domain_scores"]["price_volume"]


def test_router_fails_closed_for_unsupported_and_under_specified_inputs() -> None:
    event = route_research_request(
        _request(
            title="Overnight disclosure diffusion",
            hypothesis="An announcement spreads overnight and affects the next open.",
        )
    )
    assert event["lead_domain"] == "event_text"
    assert event["route_state"] == "WAITING_CAPABILITY"
    assert event["capability_gaps"] == ["event_text"]

    unknown = route_research_request(
        _request(title="Idea", hypothesis="There may be a useful relation.")
    )
    assert unknown["route_state"] == "UNDER_SPECIFIED"
    assert unknown["lead_domain"] is None


def test_mixed_route_with_unavailable_supporting_domain_waits_for_capability(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    request = _request(
        title="Mixed market mechanism",
        hypothesis=(
            "Minute liquidity and order flow reveal intraday pressure, while announcement "
            "disclosure and news determine whether the move is information-driven."
        ),
    )
    route = route_research_request(request)
    assert route["lead_domain"] == "price_volume"
    assert "event_text" in route["supporting_domains"]
    assert route["route_state"] == "ROUTED_WITH_CAPABILITY_GAP"

    write_research_organization_bundle(workspace=workspace, request=request)
    plan = load_research_organization_plan(workspace)
    assert plan["state"] == "WAITING_CAPABILITY"
    assert plan["role_plan"]["unavailable_roles"] == ["event_researcher"]


def test_bundle_is_workspace_scoped_and_preserved_on_resume(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    request = _request(
        title="Intraday crowding pressure",
        hypothesis="Minute order flow and the price-volume path reveal liquidity crowding.",
    )
    written = write_research_organization_bundle(workspace=workspace, request=request)
    assert written["verdict"] == "PASS"
    assert written["lead_domain"] == "price_volume"
    assert written["task_count"] == 7
    assert written["single_agent_fallback"] is False

    plan = load_research_organization_plan(workspace)
    assert plan["workspace_policy"]["plan_path"] == "identity/research_organization_plan.json"
    assert plan["execution_policy"]["host_is_only_canonical_merger"] is True
    assert plan["execution_policy"]["private_chain_of_thought_forbidden_in_artifacts"] is True
    domain_task = _task(workspace, "price_volume_researcher")
    assert domain_task["result_ingress"] == {
        "mode": "host_validated_atomic_admission",
        "agent_direct_workspace_write_allowed": False,
        "admission_script": "scripts/admit_factorforge_agent_result.py",
    }
    input_snapshots = list(
        (workspace / "objects/research_organization/ORG_REPORT/inputs").glob("*.json")
    )
    assert len(input_snapshots) == 4
    before = (workspace / "identity/research_organization_plan.json").read_bytes()

    resumed = dict(request)
    resumed["conversation_snapshot"] = {
        "messages": [
            *request["conversation_snapshot"]["messages"],
            {
                "sequence_no": 2,
                "role": "user",
                "content_kind": "decision",
                "content": "Continue the already frozen research route.",
            },
        ]
    }
    preserved = write_research_organization_bundle(
        workspace=workspace,
        request=resumed,
        preserve_existing=True,
    )
    assert preserved["verdict"] == "PASS"
    assert (workspace / "identity/research_organization_plan.json").read_bytes() == before


def test_bundle_rejects_plan_tampering_and_path_escape(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    request = _request(
        title="Intraday reversal",
        hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
    )
    write_research_organization_bundle(workspace=workspace, request=request)
    plan_path = workspace / "identity/research_organization_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["workspace_policy"]["result_root"] = "../../outside"
    plan = with_content_hash(plan, hash_field="plan_sha256")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ResearchOrganizationError, match=BLOCK_RESEARCH_ORG_PLAN_INVALID) as exc:
        validate_research_organization_bundle(workspace=workspace)
    assert "workspace_policy_mismatch" in str(exc.value)


def test_bundle_recomputes_route_from_captured_host_request(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    snapshot_path = (
        workspace
        / "objects/research_organization/ORG_REPORT/inputs/web_research_request.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["captured_payload"]["title"] = "Legal-time FCF valuation gap"
    snapshot["captured_payload"]["hypothesis"] = (
        "Discount free cash flow with WACC and terminal value to estimate a valuation gap."
    )
    snapshot["captured_payload"]["conversation_snapshot"]["messages"][0]["content"] = (
        snapshot["captured_payload"]["hypothesis"]
    )
    snapshot["source_sha256"] = stable_json_hash(snapshot["captured_payload"])
    snapshot = with_content_hash(snapshot, hash_field="snapshot_sha256")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ResearchOrganizationError, match="request_route_mismatch"):
        validate_research_organization_bundle(workspace=workspace)


def test_bundle_rejects_rehashed_registry_policy_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    plan_path = workspace / "identity/research_organization_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["agent_registry"]["roles"][0]["forbidden_side_effects"] = []
    plan["agent_registry"] = with_content_hash(
        plan["agent_registry"], hash_field="registry_sha256"
    )
    plan = with_content_hash(plan, hash_field="plan_sha256")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ResearchOrganizationError, match="policy_mismatch"):
        validate_research_organization_bundle(workspace=workspace)


def test_bundle_rejects_rehashed_dispatch_and_task_structure_tampering(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    plan = load_research_organization_plan(workspace)
    dispatch_path = workspace / plan["workspace_policy"]["dispatch_manifest_path"]
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    reference = dispatch["tasks"][-1]
    task_path = workspace / reference["path"]
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["depends_on_roles"] = []
    task["status"] = "READY"
    task = with_content_hash(task, hash_field="task_sha256")
    task_path.write_text(json.dumps(task), encoding="utf-8")
    reference["sha256"] = task["task_sha256"]
    reference["status"] = "READY"
    dispatch = with_content_hash(dispatch, hash_field="dispatch_sha256")
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")

    with pytest.raises(ResearchOrganizationError, match="depends_on_roles"):
        validate_research_organization_bundle(workspace=workspace)


def test_bundle_rejects_rehashed_task_input_substitution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    plan = load_research_organization_plan(workspace)
    dispatch_path = workspace / plan["workspace_policy"]["dispatch_manifest_path"]
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    reference = next(
        item for item in dispatch["tasks"] if item["role_id"] == "price_volume_researcher"
    )
    task_path = workspace / reference["path"]
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["input_artifacts"] = task["input_artifacts"][:-1]
    task = with_content_hash(task, hash_field="task_sha256")
    task_path.write_text(json.dumps(task), encoding="utf-8")
    reference["sha256"] = task["task_sha256"]
    dispatch = with_content_hash(dispatch, hash_field="dispatch_sha256")
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")

    with pytest.raises(ResearchOrganizationError, match="input_artifacts"):
        validate_research_organization_bundle(workspace=workspace)


def test_bundle_rejects_rehashed_dispatch_task_identity_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    plan = load_research_organization_plan(workspace)
    dispatch_path = workspace / plan["workspace_policy"]["dispatch_manifest_path"]
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    dispatch["tasks"][0]["task_id"] = "task_99_research_director"
    dispatch["tasks"][0]["path"] = (
        "objects/research_organization/ORG_REPORT/tasks/"
        "task_99_research_director.json"
    )
    dispatch = with_content_hash(dispatch, hash_field="dispatch_sha256")
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")

    with pytest.raises(ResearchOrganizationError, match="dispatch.task_identity"):
        validate_research_organization_bundle(workspace=workspace)


def test_bundle_rejects_unbound_task_and_result_files(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    org_root = workspace / "objects/research_organization/ORG_REPORT"
    (org_root / "tasks/unbound.json").write_text("{}\n", encoding="utf-8")
    (org_root / "results/unbound.json").parent.mkdir(parents=True, exist_ok=True)
    (org_root / "results/unbound.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ResearchOrganizationError) as exc:
        validate_research_organization_bundle(workspace=workspace)
    assert "task_directory" in str(exc.value)
    assert "result_directory" in str(exc.value)


def test_agent_result_blocks_private_reasoning_and_false_independence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    request = _request(
        title="Intraday reversal",
        hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
    )
    write_research_organization_bundle(workspace=workspace, request=request)

    domain_task = _task(workspace, "price_volume_researcher")
    valid_domain = _result(domain_task)
    assert validate_agent_result(valid_domain, task=domain_task, workspace=workspace) == []
    reused_domain_reasons = validate_agent_result(
        valid_domain,
        task=domain_task,
        workspace=workspace,
        peer_session_ids=["agent_session_1"],
    )
    assert any("session_reused" in reason for reason in reused_domain_reasons)
    fallback_domain = _result(
        domain_task,
        producer_mode="single_agent_fallback",
        session_id="director_session",
    )
    fallback_domain_reasons = validate_agent_result(
        fallback_domain,
        task=domain_task,
        workspace=workspace,
    )
    assert any("fallback_not_allowed" in reason for reason in fallback_domain_reasons)
    leaked = dict(valid_domain)
    leaked["chain_of_thought"] = "hidden trace"
    leaked = with_content_hash(leaked, hash_field="result_sha256")
    leaked_reasons = validate_agent_result(leaked, task=domain_task, workspace=workspace)
    assert any(BLOCK_RESEARCH_ORG_RESULT_INVALID in reason for reason in leaked_reasons)

    council_task = _task(workspace, "independent_council")
    fallback = _result(
        council_task,
        producer_mode="single_agent_fallback",
        session_id="director_session",
    )
    fallback["formal_independent_verdict"] = "PROMOTE"
    fallback = with_content_hash(fallback, hash_field="result_sha256")
    fallback_reasons = validate_agent_result(fallback, task=council_task, workspace=workspace)
    assert any(BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID in reason for reason in fallback_reasons)

    reused = _result(council_task, session_id="author_session")
    reused_reasons = validate_agent_result(
        reused,
        task=council_task,
        workspace=workspace,
        peer_session_ids=["author_session"],
    )
    assert any("session_reused" in reason for reason in reused_reasons)

    incomplete_review = _result(council_task, session_id="independent_but_incomplete")
    incomplete_review["independence_attestation"]["reviewed_role_ids"] = [
        "research_director"
    ]
    incomplete_review = with_content_hash(
        incomplete_review,
        hash_field="result_sha256",
    )
    incomplete_reasons = validate_agent_result(
        incomplete_review,
        task=council_task,
        workspace=workspace,
    )
    assert any("reviewed_roles" in reason for reason in incomplete_reasons)

    liaison_task = _task(workspace, "data_liaison")
    rogue_request = (
        workspace
        / "objects/research_organization/ORG_REPORT/data_requests/unbound.json"
    )
    rogue_request.parent.mkdir(parents=True, exist_ok=True)
    rogue_request.write_text("{}\n", encoding="utf-8")
    liaison_reasons = validate_agent_result(
        _result(liaison_task, session_id="liaison_session"),
        task=liaison_task,
        workspace=workspace,
    )
    assert any("data_request_directory" in reason for reason in liaison_reasons)


def test_require_results_means_every_dispatched_role(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    validation = validate_research_organization_bundle(workspace=workspace)
    assert validation["execution_state"] == "DISPATCH_CONTRACT_GENERATED"
    assert validation["independence_satisfied"] is False
    with pytest.raises(ResearchOrganizationError, match=BLOCK_RESEARCH_ORG_PLAN_INVALID):
        validate_research_organization_bundle(
            workspace=workspace,
            require_results=True,
        )


def test_host_admission_enforces_dependencies_and_can_complete_ordered_bundle(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    council_task = _task(workspace, "independent_council")
    with pytest.raises(ResearchOrganizationError, match="dependencies_not_satisfied"):
        admit_agent_result(
            workspace=workspace,
            result=_result(council_task, session_id="council_too_early"),
        )

    ordered_roles = [
        "research_director",
        "knowledge_librarian",
        "data_liaison",
        "price_volume_researcher",
        "quant_implementation",
        "validation_evidence",
        "independent_council",
    ]
    for index, role_id in enumerate(ordered_roles):
        outcome = admit_agent_result(
            workspace=workspace,
            result=_result(
                _task(workspace, role_id),
                session_id=f"ordered_session_{index}_{role_id}",
            ),
        )
        assert outcome["admitted_role_id"] == role_id

    completed = validate_research_organization_bundle(
        workspace=workspace,
        require_results=True,
    )
    assert completed["execution_state"] == "COMPLETE"
    assert completed["independence_satisfied"] is True


def test_host_admission_is_immutable_and_rejects_reused_agent_session(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Cash-flow constrained intraday selling",
            hypothesis=(
                "Free cash flow and balance-sheet debt identify constrained firms, while "
                "minute liquidity and order flow reveal intraday forced selling."
            ),
        ),
    )
    fundamental_task = _task(workspace, "fundamental_researcher")
    price_volume_task = _task(workspace, "price_volume_researcher")
    fundamental = _result(fundamental_task, session_id="specialist_session_shared")
    admitted = admit_agent_result(workspace=workspace, result=fundamental)
    assert admitted["admitted_role_id"] == "fundamental_researcher"
    assert admitted["idempotent"] is False
    assert admit_agent_result(workspace=workspace, result=fundamental)["idempotent"] is True

    reused = _result(price_volume_task, session_id="specialist_session_shared")
    with pytest.raises(ResearchOrganizationError, match="session_reused"):
        admit_agent_result(workspace=workspace, result=reused)

    changed = json.loads(json.dumps(fundamental))
    changed["public_research_record"]["domain_fit"]["reason"] = "Changed after admission."
    changed = with_content_hash(changed, hash_field="result_sha256")
    with pytest.raises(ResearchOrganizationError, match="immutable_result_conflict"):
        admit_agent_result(workspace=workspace, result=changed)


def test_concurrent_host_admission_never_overwrites_first_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    task = _task(workspace, "price_volume_researcher")
    candidates = []
    for index in range(8):
        candidate = _result(task, session_id=f"specialist_session_{index}")
        candidate["public_research_record"]["domain_fit"]["reason"] = f"Candidate {index}."
        candidates.append(with_content_hash(candidate, hash_field="result_sha256"))

    def admit(candidate: dict) -> tuple[str, str]:
        try:
            outcome = admit_agent_result(workspace=workspace, result=candidate)
            return "admitted", "idempotent" if outcome["idempotent"] else "created"
        except ResearchOrganizationError as exc:
            return "blocked", str(exc)

    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        outcomes = list(executor.map(admit, candidates))

    assert sum(outcome == ("admitted", "created") for outcome in outcomes) == 1
    assert all(
        outcome == ("admitted", "created") or "immutable_result_conflict" in outcome[1]
        for outcome in outcomes
    )
    stored = json.loads(
        (workspace / task["expected_result_path"]).read_text(encoding="utf-8")
    )
    assert stored in candidates


def test_concurrent_cross_role_admission_enforces_session_isolation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Cash-flow constrained intraday selling",
            hypothesis=(
                "Free cash flow and balance-sheet debt identify constrained firms, while "
                "minute liquidity and order flow reveal intraday forced selling."
            ),
        ),
    )
    candidates = [
        _result(
            _task(workspace, "fundamental_researcher"),
            session_id="improperly_shared_session",
        ),
        _result(
            _task(workspace, "price_volume_researcher"),
            session_id="improperly_shared_session",
        ),
    ]

    def admit(candidate: dict) -> str:
        try:
            admit_agent_result(workspace=workspace, result=candidate)
            return "admitted"
        except ResearchOrganizationError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(admit, candidates))

    assert outcomes.count("admitted") == 1
    assert sum("session_reused" in outcome for outcome in outcomes) == 1
    assert validate_research_organization_bundle(workspace=workspace)["result_count"] == 1


def test_host_result_cannot_reuse_an_already_admitted_specialist_session(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Intraday reversal",
            hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
        ),
    )
    shared_session = "specialist_session_must_remain_isolated"
    specialist = _result(
        _task(workspace, "price_volume_researcher"),
        session_id=shared_session,
    )
    admit_agent_result(workspace=workspace, result=specialist)

    host = _result(
        _task(workspace, "research_director"),
        session_id=shared_session,
    )
    with pytest.raises(ResearchOrganizationError, match="session_reused"):
        admit_agent_result(workspace=workspace, result=host)

    assert validate_research_organization_bundle(workspace=workspace)["result_count"] == 1


def test_ultimate_gate_is_backward_compatible_but_required_mode_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert resolve_research_organization_gate(
        mode="auto", factor_workspace=workspace
    )["status"] == "not_present_legacy"

    with pytest.raises(ResearchOrganizationError, match="BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_MISSING"):
        resolve_research_organization_gate(mode="required", factor_workspace=workspace)

    request = _request(
        title="Intraday liquidity pressure",
        hypothesis="Minute price-volume imbalance may reverse after a liquidity shock.",
    )
    write_research_organization_bundle(workspace=workspace, request=request)
    validated = resolve_research_organization_gate(
        mode="required", factor_workspace=workspace
    )
    assert validated["status"] == "validated"
    assert validated["lead_domain"] == "price_volume"
    assert validated["formal_org_independence"] is False
