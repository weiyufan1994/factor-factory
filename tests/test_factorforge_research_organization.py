from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from factor_factory.catalog_policy import (
    CLEAN_DAILY_BAR_PIT_GUARANTEES_V1,
    INFORMATION_POLICY_CONTRACT_VERSION,
    project_information_policy_attestation,
)
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
from factor_factory.research_org.director import (
    DATA_LIAISON_FORMAL_EXECUTION_CHECKS,
    DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION,
    DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
    PREFORMAL_CLAIM_SCOPE,
    PREFORMAL_CLEAR_DECISION,
    PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
    PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
    PREFORMAL_EXECUTIVE_SUMMARIES,
    PREFORMAL_FALSIFIER_CODES,
    PREFORMAL_FINDING_CODES,
    PREFORMAL_ROLE_CHECK_IDS,
)
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


def _active_catalog_summary(*, admission: bool = True) -> dict:
    information_policy = {
        "contract": {},
        "pit_guarantees": dict(CLEAN_DAILY_BAR_PIT_GUARANTEES_V1),
        "information_set_legality": "",
        "no_future_data": None,
        "no_future_intraday_minutes": None,
    }
    return {
        "version": "factorforge_web_data_catalog_summary_v2",
        "read_only": True,
        "active_catalog_admission": {
            "version": "factorforge_console_catalog_admission_v1",
            "verdict": "PASS" if admission else "NOT_APPLICABLE",
            "admission_scope": (
                "active_catalog_identity_freshness_and_transport"
                if admission
                else "approved_snapshot_without_host_transport_attestation"
            ),
            "formal_dataset_qa_implied": False,
            "catalog_sha256": "a" * 64,
            "catalog_receipt_sha256": "b" * 64,
        },
        "catalogs": [
            {
                "catalog_name": "data_catalog.json",
                "catalog_sha256": "a" * 64,
                "entries": [
                    {
                        "name": "clean_daily_bar",
                        "dataset_class": "base_market_dataset",
                        "catalog_membership": "active_catalog_member",
                        "columns": ["trade_date", "ts_code", "close", "amount"],
                        "materialized_uri": (
                            "s3://yufan-data-lake/factorforge/datamart/"
                            "clean_daily_bar/v1/daily_clean.parquet"
                        ),
                        "freshness": {
                            "trade_date_min": "20100104",
                            "trade_date_max": "20260624",
                        },
                        "start_date": None,
                        "end_date": None,
                        "producer_provenance": {
                            "source": "s3_factorforge_datamart",
                            "source_label": "workspace_persistent",
                            "mode": "shared_clean_daily_layer",
                        },
                        "information_policy": information_policy,
                        "host_information_policy_attestation": (
                            project_information_policy_attestation(
                                "clean_daily_bar",
                                information_policy,
                            )
                        ),
                    }
                ],
            }
        ],
    }


def _valid_v2_liaison_result(workspace: Path, task: dict) -> dict:
    result = _result(task, session_id="v2_liaison_session")
    catalog_ref = next(
        item
        for item in task["input_artifacts"]
        if item["path"].endswith("/data_catalog_summary.json")
    )
    result["public_research_record"]["catalog_resolution"] = {
        "contract_version": DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION,
        "resolution_scope": "pre_formal_design_only",
        "catalog_snapshot_ref": {
            "path": catalog_ref["path"],
            "sha256": catalog_ref["sha256"],
        },
        "design_time_reuse_hits": [
            {
                "dataset_id": "clean_daily_bar",
                "dataset_class": "base_market_dataset",
                "catalog_membership": "active_catalog_member",
                "materialized_uri": (
                    "s3://yufan-data-lake/factorforge/datamart/"
                    "clean_daily_bar/v1/daily_clean.parquet"
                ),
                "required_fields": ["close", "amount"],
                "required_coverage": {
                    "start": "2016-01-01",
                    "end": "2025-07-11",
                },
                "information_policy_present": True,
                "producer_provenance_present": True,
            }
        ],
        "formal_execution_requirements": list(
            DATA_LIAISON_FORMAL_EXECUTION_CHECKS
        ),
        "formal_execution_gate": {
            "status": "DEFERRED_TO_STEP3",
            "formal_execution_allowed": False,
        },
        "generated_data_requests": [],
    }
    result["public_research_record"]["permissions_boundary"] = {
        "catalog_read_only": True,
        "catalog_write_allowed": False,
        "data_write_allowed": False,
        "pipeline_execution_allowed": False,
    }
    return with_content_hash(result, hash_field="result_sha256")


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


def _preformal_checks(task: dict) -> list[dict]:
    return [
        {
            "check_id": check_id,
            "claim_type": "DESIGN_REQUIREMENT",
            "status": "PASS",
            "finding_code": PREFORMAL_FINDING_CODES["PASS"],
            "falsifier_code": PREFORMAL_FALSIFIER_CODES[check_id],
            "evidence_refs": [],
        }
        for check_id in PREFORMAL_ROLE_CHECK_IDS[task["role_id"]]
    ]


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
                    "claim_type": "DESIGN_REQUIREMENT",
                    "statement": "The selected mechanism is testable.",
                    "falsifier": "The predicted conditional signature is absent.",
                    "evidence_refs": [],
                }
            ],
            "artifact_refs": [],
            "handoff": {"status": "ready_for_host_review"},
        }
        if task["role_id"] in PREFORMAL_ROLE_CHECK_IDS:
            checks = _preformal_checks(task)
            public_record["executive_summary"] = PREFORMAL_EXECUTIVE_SUMMARIES[
                PREFORMAL_CLEAR_DECISION
            ]
            public_record["claims"] = [dict(check) for check in checks]
            public_record["design_review"] = {
                "contract_version": PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
                "stage": "pre_formal_research_design",
                "evidence_basis": "pre_registered_design_only",
                "claim_scope": PREFORMAL_CLAIM_SCOPE,
                "empirical_factor_verdict": "NOT_ISSUED",
                "decision": PREFORMAL_CLEAR_DECISION,
                "checks": checks,
                "blockers": [],
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
        payload["formal_independent_verdict"] = {
            "contract_version": PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
            "stage": "pre_formal_research_design",
            "claim_scope": PREFORMAL_CLAIM_SCOPE,
            "decision": PREFORMAL_CLEAR_DECISION,
            "reviewed_role_ids": task["required_review_role_ids"],
            "blocking_findings": [],
            "empirical_factor_verdict": "NOT_ISSUED",
        }
    return with_content_hash(payload, hash_field="result_sha256")


def _director_result(
    workspace: Path,
    task: dict,
    *,
    session_id: str,
) -> dict:
    reviewed = []
    for role_id in task["depends_on_roles"]:
        dependency_task = _task(workspace, role_id)
        path = dependency_task["expected_result_path"]
        payload = json.loads((workspace / path).read_text(encoding="utf-8"))
        reviewed.append(
            {
                "role_id": role_id,
                "path": path,
                "result_sha256": payload["result_sha256"],
            }
        )
    source_path = workspace / "identity/web_research_director_record.json"
    source_path.write_text(
        json.dumps(
            {
                "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
                "reviewed_specialist_results": reviewed,
                "test_fixture": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    source_ref = {
        "path": "identity/web_research_director_record.json",
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    payload = _result(task, session_id=session_id)
    payload["public_research_record"] = {
        "contract_version": task["output_contract"],
        "executive_summary": "The admitted intake defines one frozen mechanism.",
        "claims": [
            {
                "claim": "Liquidity pressure is measured before formal execution.",
                "falsifier": "The planned observable does not identify pressure.",
            }
        ],
        "artifact_refs": [source_ref],
        "director_synthesis": {
            "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
            "stage": "pre_formal_research_design",
            "mechanism_decision": "Freeze the liquidity-pressure mechanism.",
            "selected_measurement_object": "A legal-time price-volume pressure projection.",
            "rejected_alternatives": ["Reject an unconditioned raw return ratio."],
            "unresolved_risks": [],
            "falsifiers": ["The conditional pressure signature is absent."],
            "reviewed_specialist_results": reviewed,
            "source_record_ref": source_ref,
            "handoff_status": "ready_for_specialist_verification",
        },
        "handoff": {"status": "ready_for_specialist_verification"},
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
    assert route["mechanism_gate"]["passed"] is True
    assert any(
        item["source_kind"] == "formula" and item["routing_eligible"] is False
        for item in route["evidence"]
    )


def test_router_rejects_exact_canary_formula_without_mechanism_evidence(
    tmp_path: Path,
) -> None:
    formula = (
        "-1 * (NORMALIZE(S_LOG_LP(TS_KURTOSIS(CLOSE,5))"
        "+TS_MAX_SKEW(VOLUME,5,3)-TS_MIN_SKEW(VOLUME,20,3)"
        "+TS_MAX_SUM(CHANGE_PCT,20,5),STANDARDIZE=1))"
    )
    request = _request(title="负价量偏度峰度复合因子", hypothesis=formula)
    request["input_kind"] = "formula"
    request["conversation_snapshot"]["messages"][0]["content_kind"] = "formula"

    route = route_research_request(request)

    assert route["route_state"] == "UNDER_SPECIFIED"
    assert route["lead_domain"] is None
    assert route["supporting_domains"] == []
    assert route["mechanism_gate"] == {
        "passed": False,
        "eligible_source_kinds": [],
        "eligible_source_origins": [],
        "rejected_claimed_source_origins": [],
        "reasons": [
            "NO_MECHANISM_BEARING_USER_EVIDENCE",
            "EXPLORATORY_LEXICAL_MATCHES_EXCLUDED_FROM_DOMAIN_SELECTION",
        ],
    }
    assert route["exploratory_candidates"][0]["domain"] == "price_volume"
    assert route["exploratory_candidates"][0]["source_kinds"] == ["formula"]

    workspace = _workspace(tmp_path)
    write_research_organization_bundle(workspace=workspace, request=request)
    plan = load_research_organization_plan(workspace)
    assert plan["state"] == "NEEDS_CLARIFICATION"
    assert plan["role_plan"]["domain_role_assignments"] == {}


def test_router_keeps_code_and_title_matches_exploratory_only() -> None:
    request = _request(
        title="Intraday volume liquidity implementation",
        hypothesis="def factor(close, volume): return close / volume",
    )
    request["input_kind"] = "code"
    request["conversation_snapshot"]["messages"][0]["content_kind"] = "code"

    route = route_research_request(request)

    assert route["route_state"] == "UNDER_SPECIFIED"
    assert route["lead_domain"] is None
    assert route["supporting_domains"] == []
    assert route["exploratory_candidates"][0]["domain"] == "price_volume"
    assert route["exploratory_candidates"][0]["source_kinds"] == ["code", "title"]


def test_router_rejects_formula_disguised_as_hypothesis() -> None:
    request = _request(
        title="Liquidity hypothesis",
        hypothesis="close / volume",
    )

    route = route_research_request(request)

    assert route["route_state"] == "UNDER_SPECIFIED"
    assert route["lead_domain"] is None
    assert route["mechanism_gate"]["rejected_claimed_source_origins"] == [
        "hypothesis"
    ]
    classified = route["routing_input_projection"]["sources"][1]
    assert classified["kind"] == "hypothesis"
    assert classified["origin"] == "hypothesis"
    assert classified["content_class"] == "formula"
    assert classified["mechanism_bearing"] is False
    assert len(classified["text_sha256"]) == 64


@pytest.mark.parametrize(
    "description",
    [
        "The market price and volume data are available every trading day.",
        "This report contains market price, volume, turnover, and return fields.",
        "This report contains forced selling, liquidity pressure, and future return fields.",
        "This report contains support, resistance, liquidity pressure, and future return fields.",
        "This report contains support levels, resistance, liquidity pressure, and future return fields.",
        "This report contains discount rate, cash flow, and valuation gap columns.",
    ],
)
def test_router_rejects_descriptive_market_data_as_mechanism(
    description: str,
) -> None:
    route = route_research_request(
        _request(title="Available market fields", hypothesis=description)
    )

    assert route["route_state"] == "UNDER_SPECIFIED"
    assert route["lead_domain"] is None
    classified = next(
        item
        for item in route["routing_input_projection"]["sources"]
        if item["origin"] == "hypothesis"
    )
    assert classified["content_class"] == "descriptive_prose"
    assert classified["mechanism_bearing"] is False
    assert classified["descriptive_data_only"] is True


def test_router_accepts_complete_mechanism_triple_inside_report_prose() -> None:
    mechanism = (
        "This report contains evidence that forced selling pressure causes a "
        "temporary price dislocation and predicts future return reversal after "
        "liquidity suppliers absorb the flow."
    )
    request = _request(title="Forced selling report", hypothesis=mechanism)
    request["input_kind"] = "report"
    request["conversation_snapshot"]["messages"][0]["content_kind"] = "report"

    route = route_research_request(request)

    assert route["route_state"] == "ROUTED"
    assert route["lead_domain"] == "price_volume"
    classified = next(
        item
        for item in route["routing_input_projection"]["sources"]
        if item["origin"] == "hypothesis"
    )
    assert classified["content_class"] == "mechanism_prose"
    assert classified["mechanism_bearing"] is True
    assert classified["descriptive_data_only"] is False


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
        _request(title="Intraday volume idea", hypothesis="There may be a useful relation.")
    )
    assert unknown["route_state"] == "UNDER_SPECIFIED"
    assert unknown["lead_domain"] is None
    assert unknown["supporting_domains"] == []
    assert unknown["mechanism_gate"]["passed"] is False
    assert unknown["mechanism_gate"]["reasons"] == [
        "NO_MECHANISM_BEARING_USER_EVIDENCE",
        "CLAIMED_MECHANISM_MODALITY_REJECTED_BY_CONTENT_GATE",
        "EXPLORATORY_LEXICAL_MATCHES_EXCLUDED_FROM_DOMAIN_SELECTION",
    ]
    assert unknown["exploratory_candidates"][0]["domain"] == "price_volume"
    assert unknown["exploratory_candidates"][0]["source_kinds"] == ["title"]


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

    empirical_council = _result(
        council_task,
        session_id="independent_empirical_claim",
    )
    empirical_council["public_research_record"]["executive_summary"] = (
        "Backtest proves Sharpe = 2.1 and factor verdict ACCEPT."
    )
    empirical_council = with_content_hash(
        empirical_council,
        hash_field="result_sha256",
    )
    empirical_reasons = validate_agent_result(
        empirical_council,
        task=council_task,
        workspace=workspace,
    )
    assert any("empirical_claim" in reason for reason in empirical_reasons)

    paraphrased_empirical_council = _result(
        council_task,
        session_id="independent_paraphrased_empirical_claim",
    )
    paraphrased_empirical_council["public_research_record"][
        "executive_summary"
    ] = (
        "The completed historical simulation delivered a Sharpe ratio reaching "
        "2.4, so promotion is warranted."
    )
    paraphrased_empirical_council = with_content_hash(
        paraphrased_empirical_council,
        hash_field="result_sha256",
    )
    paraphrased_reasons = validate_agent_result(
        paraphrased_empirical_council,
        task=council_task,
        workspace=workspace,
    )
    assert any("empirical_claim" in reason for reason in paraphrased_reasons)

    free_text_threshold = _result(
        council_task,
        session_id="independent_preregistered_threshold",
    )
    free_text_threshold["public_research_record"]["executive_summary"] = (
        "The frozen design preregisters a Sharpe ratio threshold of 1.0 as a "
        "future falsification criterion; no performance evidence is observed."
    )
    free_text_threshold = with_content_hash(
        free_text_threshold,
        hash_field="result_sha256",
    )
    threshold_reasons = validate_agent_result(
        free_text_threshold,
        task=council_task,
        workspace=workspace,
    )
    assert any(
        "preformal_record.executive_summary" in reason
        for reason in threshold_reasons
    )

    for index, claim in enumerate(
        (
            "The retrospective experiment posted SR 2.4; graduate this signal "
            "to the production factor library.",
            "The historical simulation posted a risk-adjusted score of 2.4, so "
            "graduate this signal.",
            "Ex post testing posted a risk adjusted score of 2.4 and supports "
            "production inclusion.",
        ),
        start=1,
    ):
        paraphrase = _result(
            council_task,
            session_id=f"independent_controlled_record_paraphrase_{index}",
        )
        paraphrase["public_research_record"]["executive_summary"] = claim
        paraphrase = with_content_hash(paraphrase, hash_field="result_sha256")
        paraphrase_reasons = validate_agent_result(
            paraphrase,
            task=council_task,
            workspace=workspace,
        )
        assert any(
            "preformal_record.executive_summary" in reason
            for reason in paraphrase_reasons
        )

    free_text_check = _result(
        council_task,
        session_id="independent_free_text_check_injection",
    )
    free_text_check["public_research_record"]["design_review"]["checks"][0][
        "finding"
    ] = "The retrospective experiment posted SR 2.4."
    free_text_check = with_content_hash(
        free_text_check,
        hash_field="result_sha256",
    )
    free_text_check_reasons = validate_agent_result(
        free_text_check,
        task=council_task,
        workspace=workspace,
    )
    assert any(
        "design_review.check_shape" in reason
        for reason in free_text_check_reasons
    )

    outer_claim = _result(
        council_task,
        session_id="independent_outer_envelope_claim",
    )
    outer_claim["factor_verdict"] = "PROMOTE"
    outer_claim = with_content_hash(outer_claim, hash_field="result_sha256")
    outer_claim_reasons = validate_agent_result(
        outer_claim,
        task=council_task,
        workspace=workspace,
    )
    assert any("result_envelope.shape" in reason for reason in outer_claim_reasons)

    identity_claim = _result(
        council_task,
        session_id="independent_identity_claim",
    )
    identity_claim["identity"] = dict(identity_claim["identity"])
    identity_claim["identity"]["factor_verdict"] = "PROMOTE"
    identity_claim["identity"]["note"] = "The historical experiment supports inclusion."
    identity_claim = with_content_hash(
        identity_claim,
        hash_field="result_sha256",
    )
    identity_claim_reasons = validate_agent_result(
        identity_claim,
        task=council_task,
        workspace=workspace,
    )
    assert any("identity.shape" in reason for reason in identity_claim_reasons)

    attestation_claim = _result(
        council_task,
        session_id="independent_attestation_claim",
    )
    attestation_claim["independence_attestation"]["note"] = (
        "The historical experiment supports production inclusion."
    )
    attestation_claim = with_content_hash(
        attestation_claim,
        hash_field="result_sha256",
    )
    attestation_claim_reasons = validate_agent_result(
        attestation_claim,
        task=council_task,
        workspace=workspace,
    )
    assert any(
        "attestation.shape" in reason
        for reason in attestation_claim_reasons
    )

    artifact_claim = _result(
        council_task,
        session_id="independent_artifact_ref_claim",
    )
    source_ref = dict(council_task["input_artifacts"][0])
    source_ref["note"] = "The retrospective experiment posted SR 2.4."
    artifact_claim["public_research_record"]["artifact_refs"] = [source_ref]
    artifact_claim = with_content_hash(
        artifact_claim,
        hash_field="result_sha256",
    )
    artifact_claim_reasons = validate_agent_result(
        artifact_claim,
        task=council_task,
        workspace=workspace,
    )
    assert any("artifact_ref" in reason for reason in artifact_claim_reasons)

    untyped_claim = _result(
        council_task,
        session_id="independent_untyped_claim",
    )
    untyped_claim["public_research_record"]["claims"] = [
        {
            "claim": "The design looks acceptable.",
            "falsifier": "A future test fails.",
        }
    ]
    untyped_claim = with_content_hash(
        untyped_claim,
        hash_field="result_sha256",
    )
    untyped_reasons = validate_agent_result(
        untyped_claim,
        task=council_task,
        workspace=workspace,
    )
    assert any(
        "typed_claims.controlled_check_binding" in reason
        for reason in untyped_reasons
    )

    forged_scope = json.loads(
        json.dumps(
            _result(
                council_task,
                session_id="independent_forged_claim_scope",
            )
        )
    )
    forged_scope["public_research_record"]["design_review"]["claim_scope"][
        "promotion_authority"
    ] = True
    forged_scope = with_content_hash(forged_scope, hash_field="result_sha256")
    forged_scope_reasons = validate_agent_result(
        forged_scope,
        task=council_task,
        workspace=workspace,
    )
    assert any("design_review.claim_scope" in reason for reason in forged_scope_reasons)

    promoted_handoff = _result(
        council_task,
        session_id="independent_promoted_handoff",
    )
    promoted_handoff["public_research_record"]["handoff"] = {
        "status": "PROMOTE"
    }
    promoted_handoff = with_content_hash(
        promoted_handoff,
        hash_field="result_sha256",
    )
    promoted_reasons = validate_agent_result(
        promoted_handoff,
        task=council_task,
        workspace=workspace,
    )
    assert any("preformal_handoff.shape" in reason for reason in promoted_reasons)

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


def test_v2_data_liaison_base_admission_is_canonically_enforced(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(_active_catalog_summary(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Daily price-volume pressure",
            hypothesis=(
                "Constrained sellers create price-volume pressure that patient "
                "liquidity suppliers absorb before a daily reversal."
            ),
        ),
    )
    task = _task(workspace, "data_liaison")
    valid = _valid_v2_liaison_result(workspace, task)
    assert validate_agent_result(valid, task=task, workspace=workspace) == []

    forged_derived = copy.deepcopy(valid)
    hit = forged_derived["public_research_record"]["catalog_resolution"][
        "design_time_reuse_hits"
    ][0]
    hit["dataset_id"] = "derived_state_v1"
    hit["dataset_class"] = "derived_state"
    forged_derived = with_content_hash(
        forged_derived,
        hash_field="result_sha256",
    )
    derived_reasons = validate_agent_result(
        forged_derived,
        task=task,
        workspace=workspace,
    )
    assert any("design_time_reuse_hits[0].dataset_id" in item for item in derived_reasons)

    missing_checks = copy.deepcopy(valid)
    missing_checks["public_research_record"]["catalog_resolution"][
        "formal_execution_requirements"
    ] = ["catalog_identity"]
    missing_checks = with_content_hash(
        missing_checks,
        hash_field="result_sha256",
    )
    check_reasons = validate_agent_result(
        missing_checks,
        task=task,
        workspace=workspace,
    )
    assert any("formal_execution_requirements" in item for item in check_reasons)

    malformed_fields = copy.deepcopy(valid)
    malformed_fields["public_research_record"]["catalog_resolution"][
        "design_time_reuse_hits"
    ][0]["required_fields"] = [{"field": "close"}]
    malformed_fields = with_content_hash(
        malformed_fields,
        hash_field="result_sha256",
    )
    malformed_reasons = validate_agent_result(
        malformed_fields,
        task=task,
        workspace=workspace,
    )
    assert any("required_fields" in item for item in malformed_reasons)


def test_v2_data_liaison_rejects_unattested_future_information_policy(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    summary = _active_catalog_summary()
    entry = summary["catalogs"][0]["entries"][0]
    entry["information_policy"] = {
        "contract": {},
        "pit_guarantees": {},
        "information_set_legality": "future observations are permitted",
        "no_future_data": False,
        "no_future_intraday_minutes": False,
    }
    # A copied PASS attestation cannot survive deterministic Host recomputation.
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Future information probe",
            hypothesis="A future-permitted policy must never support design reuse.",
        ),
    )
    task = _task(workspace, "data_liaison")
    result = _valid_v2_liaison_result(workspace, task)
    reasons = validate_agent_result(result, task=task, workspace=workspace)

    assert any("information_policy_present" in item for item in reasons)


def test_v2_data_liaison_rejects_contradictory_structured_policy(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    summary = _active_catalog_summary()
    entry = summary["catalogs"][0]["entries"][0]
    entry["information_policy"] = {
        "contract": {
            "version": INFORMATION_POLICY_CONTRACT_VERSION,
            "formation_time": "daily_close",
            "future_observations_excluded": True,
        },
        "pit_guarantees": {},
        "information_set_legality": "future observations are permitted",
        "no_future_data": None,
        "no_future_intraday_minutes": None,
    }
    entry["host_information_policy_attestation"] = (
        project_information_policy_attestation(
            "clean_daily_bar",
            entry["information_policy"],
        )
    )
    assert entry["host_information_policy_attestation"]["verdict"] == (
        "NOT_ATTESTED"
    )
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Contradictory structured policy",
            hypothesis="Conflicting policy fields must fail closed.",
        ),
    )
    task = _task(workspace, "data_liaison")
    result = _valid_v2_liaison_result(workspace, task)
    reasons = validate_agent_result(result, task=task, workspace=workspace)

    assert any("information_policy_present" in item for item in reasons)


def test_v2_data_liaison_pass_requires_active_catalog_admission(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(_active_catalog_summary(admission=False), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Unattested daily data",
            hypothesis=(
                "Constrained sellers create price-volume pressure that patient "
                "liquidity suppliers absorb before a daily reversal."
            ),
        ),
    )
    task = _task(workspace, "data_liaison")
    result = _valid_v2_liaison_result(workspace, task)
    reasons = validate_agent_result(result, task=task, workspace=workspace)

    assert any("active_catalog_admission" in item for item in reasons)


def test_v2_data_liaison_pass_requires_catalog_hash_binding(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    summary = _active_catalog_summary()
    summary["active_catalog_admission"]["catalog_sha256"] = "c" * 64
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="Misbinding probe",
            hypothesis="A valid-looking admission must bind the selected catalog.",
        ),
    )
    task = _task(workspace, "data_liaison")
    result = _valid_v2_liaison_result(workspace, task)
    reasons = validate_agent_result(result, task=task, workspace=workspace)

    assert any("active_catalog_binding" in item for item in reasons)


def test_v2_empty_catalog_accepts_only_legacy_no_data_liaison_pass(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    empty_summary = {
        "version": "factorforge_web_data_catalog_summary_v2",
        "read_only": True,
        "active_catalog_admission": {
            "version": "factorforge_console_catalog_admission_v1",
            "verdict": "NOT_APPLICABLE",
            "admission_scope": "no_catalog_configured",
            "formal_dataset_qa_implied": False,
        },
        "catalogs": [],
    }
    (workspace / "identity/data_catalog_summary.json").write_text(
        json.dumps(empty_summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(
            title="No catalog compatibility",
            hypothesis="This probe makes no data reuse claim.",
        ),
    )
    task = _task(workspace, "data_liaison")
    no_data = _result(task, session_id="empty_catalog_no_data")
    assert validate_agent_result(no_data, task=task, workspace=workspace) == []

    forged = copy.deepcopy(no_data)
    forged["public_research_record"]["catalog_resolution"]["reuse_hits"] = [
        {"dataset_id": "derived_state_without_catalog_evidence"}
    ]
    forged = with_content_hash(forged, hash_field="result_sha256")
    reasons = validate_agent_result(forged, task=task, workspace=workspace)

    assert any("active_catalog_entries" in item for item in reasons)

    legacy_workspace = _workspace(tmp_path / "legacy")
    write_research_organization_bundle(
        workspace=legacy_workspace,
        request=_request(
            title="Legacy no-data compatibility",
            hypothesis="A legacy empty snapshot must not authorize reuse.",
        ),
    )
    legacy_task = _task(legacy_workspace, "data_liaison")
    legacy_no_data = _result(
        legacy_task,
        session_id="legacy_empty_catalog_no_data",
    )
    assert validate_agent_result(
        legacy_no_data,
        task=legacy_task,
        workspace=legacy_workspace,
    ) == []

    legacy_forged = copy.deepcopy(legacy_no_data)
    legacy_forged["public_research_record"]["catalog_resolution"][
        "reuse_hits"
    ] = [{"dataset_id": "derived_state_without_catalog_evidence"}]
    legacy_forged = with_content_hash(
        legacy_forged,
        hash_field="result_sha256",
    )
    legacy_reasons = validate_agent_result(
        legacy_forged,
        task=legacy_task,
        workspace=legacy_workspace,
    )

    assert any("legacy_catalog_reuse_forbidden" in item for item in legacy_reasons)


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
        "knowledge_librarian",
        "data_liaison",
        "price_volume_researcher",
        "research_director",
        "quant_implementation",
        "validation_evidence",
        "independent_council",
    ]
    for index, role_id in enumerate(ordered_roles):
        task = _task(workspace, role_id)
        result = (
            _director_result(
                workspace,
                task,
                session_id=f"ordered_session_{index}_{role_id}",
            )
            if role_id == "research_director"
            else _result(
                task,
                session_id=f"ordered_session_{index}_{role_id}",
            )
        )
        outcome = admit_agent_result(
            workspace=workspace,
            result=result,
        )
        assert outcome["admitted_role_id"] == role_id

    completed = validate_research_organization_bundle(
        workspace=workspace,
        require_results=True,
    )
    assert completed["execution_state"] == "COMPLETE"
    assert completed["council_independence_attestation_valid"] is True
    assert completed["independence_satisfied"] is False
    assert completed["independence_authority"] == "signed_runtime_ledger_required"


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
    for index, role_id in enumerate(("knowledge_librarian", "data_liaison")):
        admit_agent_result(
            workspace=workspace,
            result=_result(
                _task(workspace, role_id),
                session_id=f"support_session_{index}",
            ),
        )

    host = _director_result(
        workspace,
        _task(workspace, "research_director"),
        session_id=shared_session,
    )
    with pytest.raises(ResearchOrganizationError, match="session_reused"):
        admit_agent_result(workspace=workspace, result=host)

    assert validate_research_organization_bundle(workspace=workspace)["result_count"] == 3


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
