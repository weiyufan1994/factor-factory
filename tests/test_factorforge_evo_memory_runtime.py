from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.container_agent_adapter import (
    ContainerizedOpenClawResearchAgentAdapter,
)
from factor_factory.console.web_research_plan import write_web_research_packet
from factor_factory.evo_memory_runtime import (
    BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID,
    BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
    _transition_runtime_state,
    admit_evo_v2_memory_transfer_round,
    build_terminal_historical_episode_candidate,
    is_validated_evo_v2_memory_runtime_enabled,
    load_historical_episode_candidates,
    load_evo_v2_memory_round_state,
    persist_historical_episode_candidate,
    prepare_evo_v2_memory_round,
    validate_terminal_historical_episode_candidate,
)
from factor_factory.knowledge_context import (
    EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION,
    retrieve_evo_v2_memory_projection,
)
from factor_factory.research_org.contracts import ResearchOrganizationError
from factor_factory.research_org.runtime import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    ResearchOrgSessionOutcome,
    build_research_org_session_prompt,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from tests.test_factorforge_console_web_research_plan import (
    PROJECT_ROOT,
    _fill_plan,
    _request,
    _workspace,
    _write_catalog,
)
from tests.test_factorforge_researcher_memory_evo_v2 import (
    _adapter_completion_receipt,
    _json_bytes,
    _materialized_admission,
)
from factor_factory.researcher_memory import persist_evo_v2_memory_admission


def _write_deterministic_memory_container_runtime(
    executable: Path,
    runtime_state: Path,
) -> None:
    runtime_state.mkdir(mode=0o700)
    executable.write_text(
        f'''#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

STATE = Path({str(runtime_state)!r})
args = sys.argv[1:]
with (STATE / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args, separators=(",", ":")) + "\\n")

if not args:
    raise SystemExit(64)
if args[0] == "inspect":
    print(f"Error: No such object: {{args[-1]}}", file=sys.stderr)
    raise SystemExit(1)
if args[0] in {{"stop", "rm"}}:
    print(f"Error: No such object: {{args[-1]}}", file=sys.stderr)
    raise SystemExit(1)
if args[0] != "run":
    raise SystemExit(65)

mode_path = STATE / "mode"
mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "success"
if "agents" in args and "add" in args:
    if mode == "prelaunch_failure":
        print("deterministic prelaunch failure", file=sys.stderr)
        raise SystemExit(9)
    home = next(item.split("=", 1)[1] for item in args if item.startswith("HOME="))
    profile_name = args[args.index("--profile") + 1]
    profile = Path(home) / f".openclaw-{{profile_name}}" / "openclaw.json"
    payload = json.loads(profile.read_text(encoding="utf-8"))
    agent_id = args[args.index("add") + 1]
    record = {{
        "id": agent_id,
        "workspace": args[args.index("--workspace") + 1],
        "agentDir": args[args.index("--agent-dir") + 1],
        "model": args[args.index("--model") + 1],
    }}
    payload.setdefault("agents", {{}})["list"] = [{{"id": "main"}}, record]
    profile.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")
    print("{{}}")
    raise SystemExit(0)
if "agent" in args and "--message-file" in args:
    prompt = Path(args[args.index("--message-file") + 1]).read_text(encoding="utf-8")
    request_match = re.search(r"frozen request at\\s*`([^`]+)`", prompt)
    output_match = re.search(r"private-output JSON object to\\s*`([^`]+)`", prompt)
    if request_match is None or output_match is None:
        print("deterministic prompt binding missing", file=sys.stderr)
        raise SystemExit(10)
    request = json.loads(Path(request_match.group(1)).read_text(encoding="utf-8"))
    output = {{
        "contract_version": "factorforge_agent_private_output_v1",
        "status": "PASS",
        "public_research_record": {{
            "contract_version": "factorforge_researcher_memory_evo_v2_cold_start_search_agent_record_v1",
            "artifact_identity": request["artifact_identity"],
            "executor_role_id": "knowledge_librarian",
            "query_sha256": request["query"]["query_sha256"],
            "checked_indexes": request["checked_indexes"],
            "admissible_hits": [],
            "admissible_hit_count": 0,
            "memory_state": "COLD_START_NO_ADMISSIBLE_MEMORY",
        }},
    }}
    Path(output_match.group(1)).write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    print(json.dumps({{"status": "completed"}}))
    raise SystemExit(0)
raise SystemExit(66)
''',
        encoding="utf-8",
    )
    executable.chmod(0o700)


def _write_broker_auth_seed(path: Path, *, key: str) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE auth_profile_store (store_key TEXT NOT NULL PRIMARY KEY, store_json TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO auth_profile_store VALUES (?, ?, ?)",
            (
                "primary",
                json.dumps(
                    {
                        "version": 1,
                        "profiles": {
                            "deepseek:console": {
                                "provider": "deepseek",
                                "type": "api_key",
                                "key": key,
                            }
                        },
                    }
                ),
                1,
            ),
        )
    path.chmod(0o600)
    return path


def _prepared_workspace(tmp_path: Path) -> Path:
    workspace = _workspace(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[_write_catalog(tmp_path)],
    )
    _fill_plan(workspace)
    return workspace


class _ZeroHitRunner:
    def __init__(self, trust_store: object):
        self.trust_store = trust_store
        self.prompts: list[str] = []

    def run_research_org_session(self, invocation):
        request = json.loads(
            (
                invocation.context_root
                / "identity/evo_v2_cold_start_search_request.json"
            ).read_text(encoding="utf-8")
        )
        self.prompts.append(build_research_org_session_prompt(invocation))
        output = {
            "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
            "status": "PASS",
            "public_research_record": {
                "contract_version": EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION,
                "artifact_identity": request["artifact_identity"],
                "executor_role_id": "knowledge_librarian",
                "query_sha256": request["query"]["query_sha256"],
                "checked_indexes": request["checked_indexes"],
                "admissible_hits": [],
                "admissible_hit_count": 0,
                "memory_state": "COLD_START_NO_ADMISSIBLE_MEMORY",
            },
        }
        output_bytes = _json_bytes(output)
        invocation.private_output_path.write_bytes(output_bytes)
        adapter_receipt = _adapter_completion_receipt(
            trust_store=self.trust_store,
            artifact_identity=invocation.identity,
            role_id=invocation.role_id,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            runtime_id=invocation.runtime_id,
            task_id=invocation.task_id,
            attempt_id=invocation.attempt_id,
            plan_sha256=invocation.plan_sha256,
            task_sha256=invocation.task_sha256,
            context_manifest_sha256=invocation.context_manifest_sha256,
            output_bytes=output_bytes,
        )
        return ResearchOrgSessionOutcome(
            returncode=0,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc="2026-08-12T00:00:00Z",
            finished_at_utc="2026-08-12T00:00:02Z",
            provider="test-runtime",
            model="test-knowledge-librarian",
            transport="test_disposable_container",
            isolation_class="container_staged_context",
            owned_termination_supported=True,
            provider_session_handle_sha256="1" * 64,
            adapter_receipt=adapter_receipt,
        )


def test_pre_result_memory_gate_pauses_then_accepts_only_signed_zero_hit(
    tmp_path: Path,
) -> None:
    workspace = _prepared_workspace(tmp_path)
    state_root = tmp_path / "state"
    trust_store = ensure_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id="evo-memory-runtime-test",
    )
    assert is_validated_evo_v2_memory_runtime_enabled(
        workspace=workspace,
        report_id="WEB_REPORT",
    ) is False

    paused = prepare_evo_v2_memory_round(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=state_root,
        installation_id=trust_store.installation_id,
        runner=None,
    )
    assert paused["stage"] == "AWAITING_KNOWLEDGE_LIBRARIAN_RUNTIME"
    assert paused["formal_execution_allowed"] is False
    assert paused["authority_guard"]["results_or_oos_accessed"] is False

    runner = _ZeroHitRunner(trust_store)
    ready = prepare_evo_v2_memory_round(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=state_root,
        installation_id=trust_store.installation_id,
        runner=runner,
    )
    assert ready["generation"] == 2
    assert ready["stage"] == "COLD_START_VERIFIED_READY"
    assert ready["formal_execution_allowed"] is True
    assert ready["bindings"]["cold_start_search_receipt_ref"] is not None
    assert "mechanism-first memory search" in runner.prompts[0]
    assert "generic" not in runner.prompts[0]
    loaded_state = load_evo_v2_memory_round_state(
        workspace=workspace,
        state_root=state_root,
        installation_id=trust_store.installation_id,
    )
    assert [event["stage"] for event in loaded_state["events"]] == [
        "AWAITING_KNOWLEDGE_LIBRARIAN_RUNTIME",
        "COLD_START_VERIFIED_READY",
    ]

    state_path = (
        workspace
        / "objects/evo_v2/WEB_REPORT/memory_runtime/memory_runtime_state.json"
    )
    tampered = json.loads(state_path.read_text(encoding="utf-8"))
    tampered["formal_execution_allowed"] = False
    state_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
    ):
        prepare_evo_v2_memory_round(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            state_root=state_root,
            installation_id=trust_store.installation_id,
            runner=runner,
        )


def test_cold_search_real_adapter_prelaunch_failure_retries_new_generation(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    fixture_root = PROJECT_ROOT / f".pytest-memory-runtime-{tmp_path.name}"
    fixture_root.mkdir(parents=True)
    request.addfinalizer(lambda: shutil.rmtree(fixture_root, ignore_errors=True))
    workspace = _prepared_workspace(fixture_root / "research")
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    trust_store = ensure_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id="evo-memory-runtime-test",
    )
    runtime_state = tmp_path / "deterministic-runtime-state"
    runtime = tmp_path / "deterministic-container-runtime"
    _write_deterministic_memory_container_runtime(runtime, runtime_state)
    (runtime_state / "mode").write_text(
        "prelaunch_failure\n",
        encoding="utf-8",
    )
    broker_token = "deterministic-broker-token"
    token_file = tmp_path / "broker-token"
    token_file.write_text(broker_token, encoding="utf-8")
    token_file.chmod(0o600)
    secret_root = tmp_path / "secret-scan"
    secret_root.mkdir(mode=0o700)
    config = ConsoleConfig(
        source_repo=PROJECT_ROOT,
        state_root=state_root,
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_write_broker_auth_seed(
            tmp_path / "openclaw-auth.sqlite",
            key=broker_token,
        ),
        openclaw_profile_template=(
            PROJECT_ROOT / "deploy/factorforge-console/openclaw.json.example"
        ),
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=secret_root,
        container_runtime=str(runtime),
        agent_container_image="sha256:" + "a" * 64,
        installation_id=trust_store.installation_id,
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)

    failed = prepare_evo_v2_memory_round(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=state_root,
        installation_id=trust_store.installation_id,
        runner=adapter,
    )
    assert failed["generation"] == 1
    assert failed["stage"] == "AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT"
    assert failed["formal_execution_allowed"] is False

    (runtime_state / "mode").write_text("success\n", encoding="utf-8")
    ready = prepare_evo_v2_memory_round(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=state_root,
        installation_id=trust_store.installation_id,
        runner=adapter,
    )
    assert ready["generation"] == 2
    assert ready["stage"] == "COLD_START_VERIFIED_READY"
    assert ready["formal_execution_allowed"] is True
    sessions = sorted(
        path.name
        for path in (
            state_root / "researcher-memory-evo-v2-retrieval-sessions"
        ).iterdir()
        if path.is_dir()
    )
    assert len(sessions) == 2
    assert all(re.fullmatch(r"session_[a-f0-9]{32}", item) for item in sessions)
    assert all("evo_v2_search" not in item for item in sessions)

    calls = [
        json.loads(line)
        for line in (runtime_state / "calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    run_calls = [call for call in calls if call and call[0] == "run"]
    assert run_calls
    assert all(
        "factorforge.console.job=job_123abc4567" in call
        for call in run_calls
    )
    receipt = json.loads(
        (
            workspace
            / "objects/evo_v2/WEB_REPORT/memory_runtime/cold_start_search_receipt.json"
        ).read_text(encoding="utf-8")
    )
    signed_identity = receipt["retrieval_runtime"][
        "adapter_completion_receipt"
    ]["identity"]
    assert "job_id" not in signed_identity
    assert signed_identity["factor_id"] == "WEB_FACTOR"
    adapter.clear_denied_secrets("job_123abc4567")


def _write_terminal_sources(
    *,
    tmp_path: Path,
    workspace: Path,
) -> tuple[Path, dict, dict]:
    report_id = "WEB_REPORT"
    certificate = {
        "report_id": report_id,
        "factor_id": "WEB_FACTOR",
        "research_id": "web_research",
        "declared_verdict": "REJECT",
        "formal_proof_eligible": True,
        "metrics": {
            "rank_ic": {"mean": 0.01},
            "long_side_after_cost": {"net_return_annual": -0.12},
        },
    }
    certificate_path = (
        workspace
        / "objects/research_protocol"
        / f"factor_proof_certificate__{report_id}.json"
    )
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state_root = tmp_path / "state"
    attestation_relative = "attestations/job_123abc4567/attestation_test.json"
    attestation_path = state_root / attestation_relative
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation = {
        "version": "factorforge_console_host_execution_attestation_v2",
        "job_id": "job_123abc4567",
        "factor_id": "WEB_FACTOR",
        "research_id": "web_research",
        "report_id": report_id,
        "workspace_evidence_tree_id": (
            "attestations/job_123abc4567/evidence_tree_test.json"
        ),
        "workspace_evidence_tree_sha256": "a" * 64,
        "workspace_evidence_tree_root_sha256": "b" * 64,
    }
    attestation_path.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    host_ref = {
        "id": attestation_relative,
        "sha256": hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
    }
    outcome_ref = {
        "event_id": "outcome_" + "c" * 24,
        "event_sha256": "d" * 64,
        "path": "outcomes/outcome_" + "c" * 24 + ".json",
    }
    return state_root, host_ref, outcome_ref


def test_terminal_episode_is_facts_only_and_next_round_retrieves_context(
    tmp_path: Path,
) -> None:
    workspace = _prepared_workspace(tmp_path / "source")
    state_root, host_ref, outcome_ref = _write_terminal_sources(
        tmp_path=tmp_path,
        workspace=workspace,
    )
    trust_store = ensure_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id="evo-memory-runtime-test",
    )
    terminal = {
        "execution_status": "COMPLETED",
        "protocol_status": "PASS",
        "factor_verdict": "REJECT",
        "council_status": "COMPLETED",
        "formal_proof_eligible": True,
        "organization_runtime_verified": True,
    }
    candidate = build_terminal_historical_episode_candidate(
        evidence_workspace=workspace,
        identity={
            "job_id": "job_123abc4567",
            "factor_id": "WEB_FACTOR",
            "research_id": "web_research",
            "report_id": "WEB_REPORT",
        },
        terminal_outcome=terminal,
        outcome_event_ref=outcome_ref,
        host_attestation_ref=host_ref,
        state_root=state_root,
        trust_store=trust_store,
    )
    assert validate_terminal_historical_episode_candidate(
        candidate,
        trust_store=trust_store,
    ) == []
    assert candidate["episode_layer"] == "historical_episode"
    assert candidate["facts"]["causal_interpretation"] == (
        "NOT_INFERRED_FACTS_ONLY_CANDIDATE"
    )
    assert candidate["authority_guard"][
        "structural_or_conditional_lesson_generated"
    ] is False
    assert candidate["authority_guard"]["canonical_memory_write_authority"] is False

    episode_root = state_root / "researcher-memory-evo-v2-episodes"
    persisted = persist_historical_episode_candidate(
        root=episode_root,
        candidate=candidate,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
        trust_store=trust_store,
    )
    assert persisted["written"] is True
    loaded = load_historical_episode_candidates(
        root=episode_root,
        repo_root=PROJECT_ROOT,
        trust_store=trust_store,
    )
    assert loaded == [candidate]
    projection = retrieve_evo_v2_memory_projection(
        admissions=[],
        historical_episode_candidates=loaded,
        target_mechanism_fingerprint=candidate["facts"]["mechanism_fingerprint"],
        blind_derivation_completed=True,
        trust_store=trust_store,
    )
    assert projection["retrieved_experience_count"] == 1
    assert all(
        not hits
        for lane, hits in projection["lanes"].items()
        if lane != "historical_episode_context"
    )
    hit = projection["lanes"]["historical_episode_context"][0]
    assert hit["candidate_only"] is True
    assert hit["performance_score_used_for_ranking"] is False
    assert hit["current_factor_proof_authority"] is False

    next_workspace = _prepared_workspace(tmp_path / "next")
    paused = prepare_evo_v2_memory_round(
        workspace=next_workspace,
        worktree=PROJECT_ROOT,
        state_root=state_root,
        installation_id=trust_store.installation_id,
        runner=_ZeroHitRunner(trust_store),
    )
    assert paused["stage"] == "AWAITING_TRANSFER_AUTHORING_AND_REVIEW"
    assert paused["formal_execution_allowed"] is False
    assert paused["bindings"]["retrieved_experience_count"] == 1
    assert paused["bindings"]["transfer_authoring_task_ref"]

    forged = copy.deepcopy(candidate)
    forged["facts"]["causal_interpretation"] = "universal bull market rule"
    assert validate_terminal_historical_episode_candidate(
        forged,
        trust_store=trust_store,
    )
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID,
    ):
        persist_historical_episode_candidate(
            root=episode_root,
            candidate=forged,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
            trust_store=trust_store,
        )


def test_transfer_pause_advances_only_after_private_admission_readback(
    tmp_path: Path,
) -> None:
    workspace, _artifacts, admission, trust_store = _materialized_admission(
        tmp_path
    )
    identity = admission["artifact_identity"]
    paused = _transition_runtime_state(
        workspace=workspace,
        identity=identity,
        stage="AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
        bindings={"transfer_authoring_task_ref": {"path": "task", "sha256": "a" * 64}},
        pause_reason="real independent review and Host persistence required",
        resume_action="admit the persisted envelope",
        trust_store=trust_store,
    )
    assert paused["formal_execution_allowed"] is False
    admission_root = tmp_path / "researcher-memory-evo-v2"
    persisted = persist_evo_v2_memory_admission(
        root=admission_root,
        admission=admission,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
        trust_store=trust_store,
    )
    forged = dict(persisted)
    forged["file_sha256"] = "f" * 64
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
    ):
        admit_evo_v2_memory_transfer_round(
            workspace=workspace,
            state_root=tmp_path,
            installation_id=trust_store.installation_id,
            repo_root=PROJECT_ROOT,
            memory_admission=admission,
            persisted_admission_ref=forged,
        )
    ready = admit_evo_v2_memory_transfer_round(
        workspace=workspace,
        state_root=tmp_path,
        installation_id=trust_store.installation_id,
        repo_root=PROJECT_ROOT,
        memory_admission=admission,
        persisted_admission_ref=persisted,
    )
    assert ready["stage"] == "TRANSFER_ADMITTED_READY"
    assert ready["formal_execution_allowed"] is True
    assert ready["bindings"]["transfer_admission_ref"] == persisted
