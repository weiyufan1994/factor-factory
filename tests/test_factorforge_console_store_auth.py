from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
import sqlite3
import tempfile
import sys
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest


def _request(title: str = "Overnight information diffusion"):
    from factor_factory.console.models import ResearchRequest

    return ResearchRequest(
        title=title,
        hypothesis="Information spreads after market close and is reflected in the next opening auction.",
        factor_id_hint=title,
        sample_start="2016-01-01",
        sample_end="2025-07-11",
        transaction_cost_bps=30,
    )


def _resume_task():
    from factor_factory.console.agent_adapter import AgentResumeTask

    return AgentResumeTask(
        version="factorforge_console_resume_task_v1",
        attempt_id=f"resume_{'a' * 32}",
        job_id="job_1234567890",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        resume_start_step="6",
        pause_kind="main_agent_mechanism_memo",
        pause_token="AWAITING_MAIN_AGENT_MECHANISM_MEMO",
        session_policy="fresh_phase_agent",
        ultimate_proof_sha256="b" * 64,
        contract_relative="identity/web_agent_resume_contract.json",
        status_relative="objects/research_iteration_master/main_agent_mechanism_memo_status__REPORT.json",
        questionnaire_relative="objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.json",
        questionnaire_markdown_relative="objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.md",
        facts_relative="identity/web_main_agent_mechanism_facts.json",
        answer_form_relative="identity/web_main_agent_mechanism_answer_form.json",
        required_output_relative="objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json",
        optional_output_relative="objects/research_iteration_master/main_agent_mechanism_memo__REPORT.md",
        read_only_inputs=(),
        protected_inputs=(),
        allowed_model_families=("stochastic_process",),
        validation_command="validate memo",
    )


def _resume_answer_form():
    return {
        "contract_version": "factorforge_main_agent_mechanism_memo_v1",
        "resume_attempt_id": f"resume_{'a' * 32}",
        "report_id": "REPORT",
        "factor_id": "FACTOR",
        "created_at_utc": "2026-08-03T00:00:00Z",
        "producer": "",
        "agent_authorship": {
            "authoring_mode": "",
            "agent_role": "",
            "answered_without_deterministic_template": False,
        },
        "formula": "divide(minus(close, open), pre_close)",
        "formula_understanding": {
            "formula_features": {
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            }
        },
        "source_refs": {
            "factor_spec_master": "objects/factor_spec_master/factor_spec_master__REPORT.json",
            "factor_case_master": "objects/factor_case_master/factor_case_master__REPORT.json",
            "evaluation_summary": "objects/validation/factor_evaluation__REPORT.json",
        },
        "formula_component_map": [
            {
                "component_id": "formula_root",
                "formula_subexpression": "divide(minus(close, open), pre_close)",
                "operators": ["divide", "minus"],
                "observable_estimator": "",
                "economic_state": "",
                "mathematical_object": "",
                "expected_role": "",
                "metric_link": "",
            }
        ],
        "mechanism_qa": {
            "formula_state_answer": "",
            "economic_hypothesis_answer": "",
            "math_model_answer": "",
            "payer_answer": "",
            "payoff_answer": "",
            "estimator_mapping_answer": "",
            "metric_signature_answer": "",
            "falsification_answer": "",
        },
        "economic_hypothesis": {
            "return_source_class": "",
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "math_hypothesis": {
            "selected_model_family": "",
            "why_this_model": "",
            "why_not_generic_template": "",
            "random_object": "",
            "latent_state": "",
            "process_or_distribution": "",
            "target_functional": "",
            "formula_as_estimator": "",
            "expected_metric_signature": {
                "rank_ic": "",
                "long_side": "",
                "cost_adjusted": "",
                "monotonicity": "",
                "turnover": "",
            },
        },
        "math_model_selection": {
            "model_family": "",
            "baseline_model": "",
            "model_mutation": "",
        },
        "payer": {
            "payer_or_counterparty": "",
            "why_they_pay": "",
            "necessary_market_structure": "",
        },
        "formula_state_estimator": {
            "latent_state": "",
            "observable_mapping": "",
            "component_links": [],
        },
        "expected_metric_signature": {
            "rank_ic": "",
            "long_side": "",
            "cost_adjusted": "",
            "monotonicity": "",
            "turnover": "",
        },
        "falsification_tests": [],
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "formula_has_correlation_or_covariance_operator": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "has_sign_or_threshold": False,
            "sign_threshold_discussion_present": False,
            "has_volume_ratio": False,
            "volume_ratio_participation_discussion_present": False,
            "has_additive_rank_raw_ratio": False,
            "additive_scale_commensurability_discussion_present": False,
        },
        "evidence_comparison": {
            "observed_metrics": {"rank_ic_mean": -0.0078},
            "observed_metric_conflict_keys": [],
            "mechanism_supported": "",
            "contradictions": [],
            "revision_implications": [],
            "kill_criteria_triggered": [],
        },
        "council_questions": [],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }


def _resume_research_patch():
    answer_form = _resume_answer_form()
    signature = {
        key: "expected versus observed"
        for key in answer_form["expected_metric_signature"]
    }
    return {
        "producer": "current_main_agent",
        "agent_authorship": {
            "authoring_mode": "current_agent_freeform",
            "agent_role": "main_agent",
            "answered_without_deterministic_template": True,
        },
        "mechanism_qa": {
            key: "formula-specific answer"
            for key in answer_form["mechanism_qa"]
        },
        "economic_hypothesis": {
            key: "formula-specific answer"
            for key in answer_form["economic_hypothesis"]
        },
        "math_hypothesis": {
            **{
                key: "formula-specific answer"
                for key in answer_form["math_hypothesis"]
                if key != "expected_metric_signature"
            },
            "expected_metric_signature": dict(signature),
        },
        "math_model_selection": {
            key: "formula-specific answer"
            for key in answer_form["math_model_selection"]
        },
        "payer": {
            key: "formula-specific answer" for key in answer_form["payer"]
        },
        "formula_state_estimator": {
            "latent_state": "formula-specific answer",
            "observable_mapping": "formula-specific answer",
            "component_links": ["formula_root"],
        },
        "expected_metric_signature": dict(signature),
        "falsification_tests": ["test one", "test two"],
        "council_questions": [],
        "formula_component_map": [
            {
                "observable_estimator": "formula-specific answer",
                "economic_state": "formula-specific answer",
                "mathematical_object": "formula-specific answer",
                "expected_role": "formula-specific answer",
                "metric_link": "formula-specific answer",
            }
        ],
        "evidence_comparison": {
            "mechanism_supported": "not supported",
            "contradictions": ["observed contradiction"],
            "revision_implications": [],
            "kill_criteria_triggered": ["cost kill"],
        },
        "operator_claim_consistency": {
            "claims_correlation_or_covariance": False,
            "claims_dependence_without_operator_justification": False,
            "explicit_dependence_justification": "",
            "sign_threshold_discussion_present": False,
            "volume_ratio_participation_discussion_present": False,
            "additive_scale_commensurability_discussion_present": False,
        },
    }


def _write_resume_prompt_inputs(
    workspace: Path,
    *,
    task=None,
    answer_form: dict | None = None,
):
    task = task or _resume_task()
    answer_form = json.loads(
        json.dumps(answer_form or _resume_answer_form(), ensure_ascii=False)
    )
    answer_form.update(
        {
            "resume_attempt_id": task.attempt_id,
            "report_id": task.report_id,
            "factor_id": task.factor_id,
        }
    )
    answer_bytes = (
        json.dumps(answer_form, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    answer_path = workspace / task.answer_form_relative
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_bytes(answer_bytes)
    facts_bytes = _write_resume_facts(
        workspace,
        task,
        {
            "formula_facts": {
                "formula": answer_form["formula"],
                "fields": answer_form["formula_understanding"]["formula_features"][
                    "fields"
                ],
                "operators": answer_form["formula_understanding"][
                    "formula_features"
                ]["operators"],
            },
            "revision_context": {
                "mode": "initial",
                "revision_number": 0,
                "failures": [],
            },
        },
    )
    contract = {
        "version": task.version,
        "attempt_id": task.attempt_id,
        "job_id": task.job_id,
        "factor_id": task.factor_id,
        "research_id": task.research_id,
        "report_id": task.report_id,
        "answer_form": task.answer_form_relative,
        "input_sha256": {
            task.answer_form_relative: hashlib.sha256(answer_bytes).hexdigest(),
            task.facts_relative: hashlib.sha256(facts_bytes).hexdigest(),
        },
    }
    contract_path = workspace / task.contract_relative
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return task


def _write_resume_facts(workspace: Path, task, payload: dict) -> bytes:
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    payload.setdefault(
        "revision_context",
        {"mode": "initial", "revision_number": 0, "failures": []},
    )
    facts_bytes = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    facts_path = workspace / task.facts_relative
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.write_bytes(facts_bytes)
    contract_path = workspace / task.contract_relative
    if contract_path.is_file():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract.setdefault("input_sha256", {})[task.facts_relative] = (
            hashlib.sha256(facts_bytes).hexdigest()
        )
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return facts_bytes


def _build_resume_prompt_for_test(tmp_path: Path, workspace: Path, task):
    from factor_factory.console.agent_adapter import build_agent_prompt
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.models import ResearchJob

    worktree = workspace.parents[2]
    job = ResearchJob(
        job_id=task.job_id,
        factor_id=task.factor_id,
        research_id=task.research_id,
        report_id=task.report_id,
        request=_request(),
    )
    return build_agent_prompt(
        job,
        worktree=worktree,
        workspace=workspace,
        config=ConsoleConfig(
            source_repo=worktree,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        ),
        resume=True,
        resume_task=task,
    )


def _auth_seed(
    path: Path,
    *,
    provider: str = "deepseek",
    profile_type: str = "api_key",
    key: str = "test-provider-api-key",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                            f"{provider}:console": {
                                "provider": provider,
                                "type": profile_type,
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


def test_research_request_rejects_unsafe_or_oversized_values():
    from factor_factory.console.models import ResearchRequest

    with pytest.raises(ValueError, match="title is required"):
        ResearchRequest(title="", hypothesis="idea")
    with pytest.raises(ValueError, match="hypothesis is too long"):
        ResearchRequest(title="idea", hypothesis="x" * 20_001)
    with pytest.raises(ValueError, match="source_url"):
        ResearchRequest(title="idea", hypothesis="test", source_url="file:///etc/passwd")
    with pytest.raises(ValueError, match="https"):
        ResearchRequest(title="idea", hypothesis="test", source_url="http://example.com/report")
    with pytest.raises(ValueError, match="local or internal"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://metadata.google.internal/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://127.0.0.1/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://127.1/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://2130706433/report")
    with pytest.raises(ValueError, match="without credentials"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://user:pass@example.com/report")
    ResearchRequest(title="idea", hypothesis="test", source_url="https://example.com/report")
    with pytest.raises(ValueError, match="between 0 and 200"):
        ResearchRequest(title="idea", hypothesis="test", transaction_cost_bps=201)


def test_web_pilot_rejects_evaluation_contract_it_cannot_execute():
    from factor_factory.console.models import (
        ResearchRequest,
        validate_pilot_evaluation_request,
    )

    with pytest.raises(ValueError, match="only 1d"):
        validate_pilot_evaluation_request(
            ResearchRequest(title="idea", hypothesis="test", forward_horizon="5d")
        )
    with pytest.raises(ValueError, match="30 bps"):
        validate_pilot_evaluation_request(
            ResearchRequest(title="idea", hypothesis="test", transaction_cost_bps=10)
        )
    with pytest.raises(ValueError, match="a_share_all"):
        validate_pilot_evaluation_request(
            ResearchRequest(
                title="idea",
                hypothesis="test",
                universe="csi300",
            )
        )


def test_research_request_rejects_dns_resolution_to_private_address(monkeypatch):
    import factor_factory.console.models as models

    monkeypatch.setattr(
        models.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (models.socket.AF_INET, models.socket.SOCK_STREAM, 6, "", ("10.2.3.4", 443))
        ],
    )

    with pytest.raises(ValueError, match="private or non-global"):
        models.ResearchRequest(
            title="idea",
            hypothesis="test",
            source_url="https://public-looking.example/report",
        )


def test_job_store_uses_external_sqlite_and_serial_claiming(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    state_root = tmp_path / "console-state"
    store = ResearchJobStore(state_root)
    first = store.create_job(_request("Factor alpha"))
    second = store.create_job(_request("Factor beta"))

    assert store.path == state_root / "console.sqlite3"
    assert first.factor_id == "FACTOR_ALPHA"
    assert first.workspace_path == ""
    assert len(store.list_jobs()) == 2

    claimed = store.claim_next_job()
    assert claimed is not None
    assert claimed.job_id == first.job_id
    assert claimed.execution_status == "ALLOCATING"
    assert store.claim_next_job() is None

    store.update_job(
        first.job_id,
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        finished_at_utc="2026-08-01T00:00:00Z",
        result={"summary": "rejected after costs"},
    )
    claimed_second = store.claim_next_job()
    assert claimed_second is not None
    assert claimed_second.job_id == second.job_id

    public = store.get_job(first.job_id).to_dict()
    assert "worktree_path" not in public
    assert "workspace_path" not in public
    assert "agent_session_key" not in public
    assert public["factor_verdict"] == "REJECT"


def test_job_store_generates_stable_identity_for_unicode_title(tmp_path):
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "console-state")
    request = ResearchRequest(
        title="负价量偏度峰度复合因子",
        hypothesis="公式研究输入",
    )

    first = store.create_job(request)
    second = store.create_job(request)

    assert re.fullmatch(r"FACTOR_[A-F0-9]{16}", first.factor_id)
    assert second.factor_id == first.factor_id

    mixed_first = store.create_job(
        ResearchRequest(title="价量结构5日", hypothesis="公式研究输入")
    )
    mixed_second = store.create_job(
        ResearchRequest(title="波动状态5日", hypothesis="公式研究输入")
    )
    assert mixed_first.factor_id != mixed_second.factor_id
    assert mixed_first.factor_id.startswith("FACTOR_5_")


def test_job_store_keeps_sqlite_database_and_sidecars_group_writable(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o660

    with store._connect():
        sidecars = [Path(f"{store.path}-wal"), Path(f"{store.path}-shm")]
        assert all(path.exists() for path in sidecars)
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o660 for path in sidecars)


def test_service_restart_pauses_inflight_job_without_duplicate_queue(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    job = store.create_job(_request())
    assert store.claim_next_job().job_id == job.job_id
    assert store.pause_interrupted_jobs() == 1
    paused = store.get_job(job.job_id)
    assert paused.execution_status == "REVIEW_REQUIRED"
    assert paused.protocol_status == "PAUSED"
    assert store.claim_next_job() is None

    resumed = store.request_resume(job.job_id)
    assert resumed.execution_status == "QUEUED"
    assert store.claim_next_job().job_id == job.job_id


def test_invite_auth_session_expiry_csrf_and_cookie_flags():
    from factor_factory.console.auth import InviteAuth, SESSION_MAX_AGE_SECONDS

    auth = InviteAuth("invite-pass", "cookie-secret", secure_cookie=True)
    assert auth.password_matches("invite-pass")
    assert not auth.password_matches("wrong")
    token = auth.issue_session(now=1_000)
    assert auth.verify_session(token, now=1_001)
    assert not auth.verify_session(token, now=1_000 + SESSION_MAX_AGE_SECONDS + 1)
    csrf = auth.csrf_token(token)
    assert auth.verify_csrf(token, csrf)
    assert not auth.verify_csrf(token, csrf + "x")
    header = auth.set_cookie_header(token)
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" in header


def test_server_side_session_registration_and_revocation(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    token = "signed-session-token-for-test"
    store.register_session(token, max_age_seconds=60)
    assert store.session_is_active(token) is True
    store.revoke_session(token)
    assert store.session_is_active(token) is False


def test_runner_health_socket_binds_queue_to_exact_engine(tmp_path):
    from factor_factory.console.run_service import ResearchQueueService
    from factor_factory.console.runner_health import RunnerHealthSocket
    from factor_factory.console.store import ResearchJobStore

    with tempfile.TemporaryDirectory(prefix="ff-runner-", dir="/tmp") as socket_root:
        socket_path = Path(socket_root) / "health.sock"
        server = RunnerHealthSocket(
            socket_path,
            lambda: {"ok": True, "engine_commit": "a" * 40},
        )
        server.start()
        try:
            store = ResearchJobStore(tmp_path / "state")
            matching = ResearchQueueService(
                store=store,
                runner_health_socket=socket_path,
                expected_engine_commit="a" * 40,
            )
            mismatch = ResearchQueueService(
                store=store,
                runner_health_socket=socket_path,
                expected_engine_commit="b" * 40,
            )
            assert matching.healthcheck() is True
            assert mismatch.healthcheck() is False
        finally:
            server.stop()


def test_auth_database_rejects_sqlite_sidecars(tmp_path):
    from factor_factory.console.agent_adapter import validate_auth_database

    seed = _auth_seed(tmp_path / "seed.sqlite")
    Path(f"{seed}-wal").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="SQLite sidecars"):
        validate_auth_database(seed, provider="deepseek", label="credential seed")


def test_auth_database_must_match_model_broker_client_token(tmp_path):
    from factor_factory.console.agent_adapter import validate_auth_database

    seed = _auth_seed(tmp_path / "seed.sqlite", key="broker-client-token-alpha-123456")
    assert validate_auth_database(
        seed,
        provider="deepseek",
        label="credential seed",
        expected_key="broker-client-token-alpha-123456",
    ) == "broker-client-token-alpha-123456"
    with pytest.raises(RuntimeError, match="not bound to the model broker"):
        validate_auth_database(
            seed,
            provider="deepseek",
            label="credential seed",
            expected_key="real-provider-key-must-not-be-used",
        )


def test_agent_prompt_binds_exact_workspace_and_read_only_catalog(tmp_path):
    from factor_factory.console.agent_adapter import build_agent_prompt
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.models import ResearchJob

    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research" / "FACTOR" / "research"
    catalog = tmp_path / "catalog.json"
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_catalogs=(catalog,),
        auth_disabled=True,
    )
    job = ResearchJob(
        job_id="job_123",
        factor_id="FACTOR",
        research_id="research",
        report_id="report",
        request=_request(),
    )
    prompt = build_agent_prompt(job, worktree=worktree, workspace=workspace, config=config, resume=False)
    assert str(workspace) in prompt
    assert str(catalog.resolve()) not in prompt
    assert "run_factorforge_ultimate_loop.py" in prompt
    assert "Do not run" in prompt
    assert "agent has no Data API, catalog-file, S3, or raw-data access" in prompt
    assert "never as a broker report" in prompt
    assert "no Data API package, catalog file, S3 credential, or raw dataset mount" in prompt
    assert "Never enumerate environment variables or credential material" in prompt
    assert "scripts/run_factorforge_ultimate.py" in prompt
    assert "the materializer" in prompt
    assert "Do not author or execute custom Python" in prompt
    assert "identity/web_research_runtime.md" in prompt
    assert "identity/data_catalog_summary.json" in prompt
    assert "identity/factor_knowledge_summary.json" in prompt
    assert "identity/web_research_authoring_contract.json" in prompt
    assert "authoring preflight command" in prompt
    assert "preserve its Host-filled `identity` and `authoring_contract` objects exactly" in prompt
    assert "skills/factor-forge-ultimate/SKILL.md" not in prompt
    assert "identity/web_execution_ledger.md" in prompt
    assert "host exclusively materializes and runs formal Step3 through Step6" in prompt
    assert "host derives authoring status" in prompt
    assert "web_agent_completion.json" not in prompt


def test_agent_prompt_blocks_malformed_organization_plan(tmp_path):
    from factor_factory.console.agent_adapter import (
        BLOCK_HOST_DIRECTOR_PROMPT_BINDING_INVALID,
        build_agent_prompt,
    )
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.models import ResearchJob

    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "identity/research_organization_plan.json").write_text(
        "{malformed\n",
        encoding="utf-8",
    )
    job = ResearchJob(
        job_id="job_123",
        factor_id="FACTOR",
        research_id="research",
        report_id="report",
        request=_request(),
    )

    with pytest.raises(
        RuntimeError,
        match=BLOCK_HOST_DIRECTOR_PROMPT_BINDING_INVALID,
    ):
        build_agent_prompt(
            job,
            worktree=worktree,
            workspace=workspace,
            config=ConsoleConfig(
                source_repo=tmp_path / "source",
                state_root=tmp_path / "state",
                worktree_root=tmp_path / "runs",
                auth_disabled=True,
            ),
            resume=False,
        )


def test_container_agent_refuses_prompt_symlink_escape(tmp_path):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )
    from factor_factory.console.models import ResearchJob

    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    task = _write_resume_prompt_inputs(workspace)
    outside = tmp_path / "outside.md"
    outside.write_text("must remain unchanged\n", encoding="utf-8")
    (workspace / "identity" / "web_agent_resume.md").symlink_to(outside)
    config = ConsoleConfig(
        source_repo=worktree,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    job = ResearchJob(
        job_id="job_1234567890",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        request=_request(),
    )

    with pytest.raises(RuntimeError, match="unsafe atomic-write destination"):
        adapter.run(
            job,
            worktree=worktree,
            workspace=workspace,
            resume=True,
            resume_task=task,
        )
    assert outside.read_text(encoding="utf-8") == "must remain unchanged\n"


def test_resume_prompt_rejects_answer_form_hard_link(tmp_path):
    workspace = tmp_path / "source/factor_research/FACTOR/research"
    task = _write_resume_prompt_inputs(workspace)
    answer_path = workspace / task.answer_form_relative
    answer_bytes = answer_path.read_bytes()
    answer_path.unlink()
    outside = tmp_path / "outside-answer-form.json"
    outside.write_bytes(answer_bytes)
    os.link(outside, answer_path)

    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _build_resume_prompt_for_test(tmp_path, workspace, task)


def test_resume_prompt_rejects_answer_form_hash_mismatch(tmp_path):
    workspace = tmp_path / "source/factor_research/FACTOR/research"
    task = _write_resume_prompt_inputs(workspace)
    answer_path = workspace / task.answer_form_relative
    answer_path.write_bytes(answer_path.read_bytes() + b" ")

    with pytest.raises(RuntimeError, match="resume answer form hash mismatch"):
        _build_resume_prompt_for_test(tmp_path, workspace, task)


def test_resume_prompt_rejects_oversized_fact_lock_value(tmp_path):
    workspace = tmp_path / "source/factor_research/FACTOR/research"
    answer_form = _resume_answer_form()
    answer_form["formula_understanding"]["formula_features"]["oversized"] = (
        "x" * 4_097
    )
    task = _write_resume_prompt_inputs(
        workspace,
        answer_form=answer_form,
    )

    with pytest.raises(RuntimeError, match="resume fact lock string is too large"):
        _build_resume_prompt_for_test(tmp_path, workspace, task)


def test_resume_prompt_enforces_answer_form_completion_budget_boundary(tmp_path):
    from factor_factory.console.agent_adapter import RESUME_ANSWER_FORM_MAX_BYTES

    workspace = tmp_path / "source/factor_research/FACTOR/research"
    answer_form = _resume_answer_form()
    metrics = answer_form["evidence_comparison"]["observed_metrics"]
    metrics["budget_padding_a"] = ""
    metrics["budget_padding_b"] = ""
    empty_size = len(
        json.dumps(
            answer_form,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    padding_bytes = RESUME_ANSWER_FORM_MAX_BYTES - empty_size
    assert 0 < padding_bytes <= 8_192
    first_padding = min(4_096, padding_bytes)
    metrics["budget_padding_a"] = "x" * first_padding
    metrics["budget_padding_b"] = "x" * (padding_bytes - first_padding)
    task = _write_resume_prompt_inputs(
        workspace,
        answer_form=answer_form,
    )
    assert len(
        json.dumps(
            answer_form,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ) == RESUME_ANSWER_FORM_MAX_BYTES
    assert "## Host-pinned fact lock" in _build_resume_prompt_for_test(
        tmp_path,
        workspace,
        task,
    )

    metrics["budget_padding_b"] += "x"
    _write_resume_prompt_inputs(
        workspace,
        task=task,
        answer_form=answer_form,
    )
    with pytest.raises(RuntimeError, match="insufficient completion budget"):
        _build_resume_prompt_for_test(tmp_path, workspace, task)


def test_container_resume_accepts_production_sized_answer_form(tmp_path):
    from factor_factory.console.agent_adapter import (
        RESUME_ANSWER_FORM_MAX_BYTES,
        RESUME_MEMO_AGENT_PATCH_MAX_BYTES,
        RESUME_MEMO_MAX_BYTES,
    )

    workspace = tmp_path / "source/factor_research/FACTOR/research"
    answer_form = _resume_answer_form()
    metrics = answer_form["evidence_comparison"]["observed_metrics"]
    metrics["production_padding_a"] = ""
    metrics["production_padding_b"] = ""
    empty_size = len(
        json.dumps(
            answer_form,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    production_size = 8_120
    padding_bytes = production_size - empty_size
    assert 0 < padding_bytes <= 8_192
    first_padding = min(4_096, padding_bytes)
    metrics["production_padding_a"] = "x" * first_padding
    metrics["production_padding_b"] = "x" * (padding_bytes - first_padding)
    task = _write_resume_prompt_inputs(workspace, answer_form=answer_form)

    assert production_size > RESUME_MEMO_MAX_BYTES - RESUME_MEMO_AGENT_PATCH_MAX_BYTES - 1
    assert production_size <= RESUME_ANSWER_FORM_MAX_BYTES
    assert len(
        json.dumps(
            answer_form,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ) == production_size
    assert "## Host-pinned fact lock" in _build_resume_prompt_for_test(
        tmp_path,
        workspace,
        task,
    )


def test_container_resume_prompt_requests_only_agent_owned_research_patch(tmp_path):
    workspace = tmp_path / "source/factor_research/FACTOR/research"
    task = _write_resume_prompt_inputs(workspace)

    prompt = _build_resume_prompt_for_test(tmp_path, workspace, task)

    assert "research-field patch" in prompt
    assert "Do not copy machine-owned values into the patch" in prompt
    assert "never paste the observed-metrics object" in prompt
    assert "Every listed patch field is required" in prompt
    assert "formula_state_estimator.component_links" in prompt
    assert "canonical `component_id` strings" in prompt
    assert "fields must each be JSON arrays (possibly empty)" in prompt
    assert "never\n   scalar strings" in prompt
    assert "`mechanism_qa.formula_state_answer`" in prompt
    assert "`mechanism_qa.estimator_mapping_answer`" in prompt
    assert '["close","open","pre_close"]' in prompt
    assert "each answer independently must\n   literally include" in prompt
    assert "Aliases such as `G`, `R`, or `J` do\n   not count" in prompt
    assert "satisfying one answer does not satisfy the other" in prompt
    assert (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}], entry"
        in prompt
    )
    assert "never put\n     an assignment, formula expression, operator" in prompt
    assert "hard-blocks\n   the patch at 16,000 bytes" in prompt
    assert "the patch at 16,000 bytes and the memo at 24,000 bytes" in prompt


def test_resume_agent_session_is_fresh_and_does_not_reuse_long_context(monkeypatch):
    from factor_factory.console.agent_adapter import build_agent_session_key
    from factor_factory.console.models import ResearchJob

    job = ResearchJob(
        job_id="job_1234567890",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        request=_request(),
        agent_session_key="agent:old:long-session",
    )
    assert build_agent_session_key(job, "agent-id", resume=False) == "agent:old:long-session"
    task = _resume_task()
    resumed = build_agent_session_key(
        job,
        "agent-id",
        resume=True,
        resume_task=task,
    )
    assert resumed == f"agent:agent-id:{job.job_id}:{task.attempt_id}"
    assert resumed != job.agent_session_key


def test_container_resume_phase_does_not_mount_initial_agent_home(tmp_path):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    conversation_ledger = workspace / "identity" / "conversation_ledger"
    conversation_ledger.mkdir(parents=True)
    (conversation_ledger / f"checkpoint__000001__{'a' * 64}.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        openclaw_profile_template=(
            Path(__file__).resolve().parents[1]
            / "deploy/factorforge-console/openclaw.json.example"
        ),
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    initial_root, initial_home, _initial_agent, _initial_profile = (
        adapter._prepare_runtime("job_1234567890")
    )
    marker = initial_home / "old-transcript-marker"
    marker.write_text("must-not-be-visible\n", encoding="utf-8")
    task = _resume_task()
    resume_root, resume_home, resume_agent, resume_profile = adapter._prepare_runtime(
        "job_1234567890",
        phase_id=task.attempt_id,
    )

    assert resume_root != initial_root
    assert json.loads(resume_profile.read_text(encoding="utf-8"))["tools"]["allow"] == [
        "read",
    ]
    assert not (resume_home / marker.name).exists()
    command = adapter._container_prefix(
        container_name="resume-isolation-test",
        job_id="job_1234567890",
        worktree=source,
        workspace=workspace,
        runtime_root=resume_root,
        home=resume_home,
        git_dir=None,
        aws_env_file=None,
        profile_config_readonly=resume_profile,
        auth_store_path=resume_agent / "openclaw-agent.sqlite",
    )
    joined = " ".join(command)
    assert f"src={resume_root},dst={resume_root}" in joined
    assert f"src={initial_root},dst={initial_root}" not in joined
    assert str(marker) not in joined
    assert (
        f"src={conversation_ledger},dst={conversation_ledger},readonly"
        in joined
    )
    assert (
        f"src={resume_agent / 'openclaw-agent.sqlite'},"
        f"dst={resume_agent / 'openclaw-agent.sqlite'},readonly"
    ) not in joined


def test_container_resume_mounts_current_engine_at_original_logical_paths(tmp_path):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "old-research-worktree"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    engine_root = tmp_path / "trusted-engine-worktree"
    (engine_root / workspace.relative_to(source)).mkdir(parents=True)
    workspace_view = tmp_path / "phase-workspace-view"
    workspace_view.mkdir()
    runtime_root = tmp_path / "runtime"
    home = runtime_root / "home"
    agent_dir = runtime_root / "agent"
    git_dir = runtime_root / "engine.git"
    for path in (runtime_root, home, agent_dir, git_dir):
        path.mkdir(exist_ok=True)
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )

    command = adapter._container_prefix(
        container_name="resume-engine-alias-test",
        job_id="job_1234567890",
        worktree=source,
        workspace=workspace,
        runtime_root=runtime_root,
        home=home,
        git_dir=git_dir,
        aws_env_file=None,
        profile_config_readonly=None,
        auth_store_path=None,
        worktree_mount_source=engine_root,
        workspace_readonly=True,
        workspace_mount_source=workspace_view,
        runtime_root_readonly=True,
        writable_runtime_paths=(home, agent_dir),
    )
    joined = " ".join(command)

    assert f"src={engine_root},dst={source},readonly" in joined
    assert f"src={workspace_view},dst={workspace},readonly" in joined
    assert f"src={runtime_root},dst={runtime_root},readonly" in joined
    assert f"src={home},dst={home}" in joined
    assert f"src={agent_dir},dst={agent_dir}" in joined
    assert f"GIT_WORK_TREE={source}" in command
    assert f"PYTHONPATH={source}" in command
    assert str(engine_root) not in [
        item.split("=", 1)[1]
        for item in command
        if item.startswith(("GIT_WORK_TREE=", "PYTHONPATH="))
    ]


def test_container_resume_uses_facts_only_workspace_view(tmp_path, monkeypatch):
    import factor_factory.console.container_agent_adapter as adapter_module
    from dataclasses import replace

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )
    from factor_factory.console.workspace_transaction import (
        workspace_transaction_lock,
    )

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    task = replace(
        _resume_task(),
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
        protected_inputs=(
            "objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.json",
        ),
    )
    _write_resume_prompt_inputs(workspace, task=task)
    _write_resume_facts(
        workspace,
        task,
        {
            "formula_facts": {
                "formula": "divide(minus(close, open), pre_close)",
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            }
        },
    )
    (workspace / "identity/web_agent_resume.md").write_text(
        "facts only\n", encoding="utf-8"
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n", encoding="utf-8"
    )
    protected = workspace / task.protected_inputs[0]
    protected.write_text(
        json.dumps({"deterministic_interpretation": "must stay hidden"}) + "\n",
        encoding="utf-8",
    )
    unlisted_parent_evidence = workspace / "reports/unlisted_evidence.json"
    unlisted_parent_evidence.parent.mkdir(parents=True)
    unlisted_parent_evidence.write_text('{"status": "baseline"}\n', encoding="utf-8")

    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    view = adapter._prepare_resume_workspace_view(
        runtime_root=runtime_root,
        workspace=workspace,
        resume_task=task,
    )

    assert not view.root.is_relative_to(runtime_root)
    assert not (view.root / task.protected_inputs[0]).exists()
    safe_spec = json.loads(
        (
            view.root
            / "objects/factor_spec_master/factor_spec_master__REPORT.json"
        ).read_text(encoding="utf-8")
    )
    assert safe_spec["projection"] == "agent_safe_formula_facts_only"
    assert "deterministic_interpretation" not in json.dumps(safe_spec)
    assert (
        view.root / "identity/web_execution_ledger.md"
    ).read_text(encoding="utf-8") == ""
    assert not (workspace / task.required_output_relative).exists()
    command = adapter._container_prefix(
        container_name="resume-facts-only-test",
        job_id="job_1234567890",
        worktree=source,
        workspace=workspace,
        runtime_root=runtime_root,
        home=runtime_root,
        git_dir=None,
        aws_env_file=None,
        profile_config_readonly=None,
        auth_store_path=None,
        workspace_readonly=True,
        workspace_mount_source=view.root,
        protected_workspace_relatives=tuple(
            relative for relative, _digest in view.read_only_file_sha256
        ),
    )
    joined = " ".join(command)
    mount_specs = [item for item in command if item.startswith("type=bind,")]
    mount_targets = [
        Path(spec.split(",dst=", 1)[1].split(",", 1)[0])
        for spec in mount_specs
    ]
    assert not any(
        view.root == target or view.root.is_relative_to(target)
        for target in mount_targets
    )
    assert f"src={view.root},dst={workspace}" in joined
    assert f"src={view.root},dst={workspace},readonly" in joined
    assert f"src={workspace},dst={workspace}" not in joined
    assert str(protected) not in joined
    for relative, _digest in view.read_only_file_sha256:
        assert (
            f"src={view.root / relative},dst={workspace / relative},readonly"
            in joined
        )
    assert f"src={view.root / task.required_output_relative}" not in joined
    assert f"src={workspace / task.required_output_relative}" not in joined
    assert f"src={workspace / 'identity/web_execution_ledger.md'}" not in joined

    (view.root / task.required_output_relative).write_text(
        '{"memo": "phase local"}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="resume output is empty:identity/web_execution_ledger.md"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"

    (view.root / task.required_output_relative).write_text(
        "not json\n",
        encoding="utf-8",
    )
    (view.root / "identity/web_execution_ledger.md").write_text(
        "phase ledger\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="resume output is invalid JSON"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()

    unexpected = view.root / "unexpected.txt"
    unexpected.write_text("must not be promoted\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected entries"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    unexpected.unlink()

    memo_path = view.root / task.required_output_relative
    ledger_path = view.root / "identity/web_execution_ledger.md"
    memo_path.unlink()
    os.link(ledger_path, memo_path)
    with pytest.raises(RuntimeError, match="resume workspace file is unsafe"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    memo_path.unlink()
    memo_path.touch(mode=0o600)

    (view.root / task.required_output_relative).write_text(
        '{"memo": "phase local"}\n',
        encoding="utf-8",
    )
    read_only_relative, _digest = view.read_only_file_sha256[0]
    read_only_file = view.root / read_only_relative
    original_read_only = read_only_file.read_bytes()
    read_only_file.chmod(0o600)
    read_only_file.write_text("changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="resume input changed"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()
    read_only_file.write_bytes(original_read_only)
    read_only_file.chmod(0o400)

    original_parent_protected = protected.read_bytes()
    protected.write_text("changed parent evidence\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="parent workspace evidence tree changed"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"
    protected.write_bytes(original_parent_protected)

    original_unlisted_evidence = unlisted_parent_evidence.read_bytes()
    unlisted_parent_evidence.write_text(
        '{"status": "changed"}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="parent workspace evidence tree changed"):
        adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()
    unlisted_parent_evidence.write_bytes(original_unlisted_evidence)

    original_atomic_replace = adapter_module._replace_text_atomic_existing

    def fail_after_ledger_replace(
        workspace_root,
        relative,
        text,
        *,
        expected_bytes,
    ):
        original_atomic_replace(
            workspace_root,
            relative,
            text,
            expected_bytes=expected_bytes,
        )
        if relative == "identity/web_execution_ledger.md" and "phase ledger" in text:
            raise OSError("injected post-replace ledger failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter_module,
            "_replace_text_atomic_existing",
            fail_after_ledger_replace,
        )
        with pytest.raises(OSError, match="post-replace ledger failure"):
            adapter._promote_resume_workspace_view(view, workspace=workspace)
    assert not (workspace / task.required_output_relative).exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"

    original_unlink = os.unlink

    def leave_atomic_temporary(path, *, dir_fd=None):
        if str(path).endswith(".tmp"):
            raise OSError("injected temporary cleanup failure")
        return original_unlink(path, dir_fd=dir_fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "unlink", leave_atomic_temporary)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*parent_workspace_evidence_tree",
        ):
            adapter._promote_resume_workspace_view(view, workspace=workspace)
    orphaned_output = workspace / task.required_output_relative
    assert orphaned_output.exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"
    temporary_files = tuple(
        path for path in workspace.rglob("*.tmp") if path.is_file()
    )
    assert len(temporary_files) == 1
    orphaned_output.unlink()
    temporary_files[0].unlink()

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_validate_resume_workspace_artifact",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("Host resume validator rejected the memo")
            ),
        )
        with pytest.raises(RuntimeError, match="Host resume validator rejected"):
            adapter._promote_resume_workspace_view(
                view,
                workspace=workspace,
                worktree=source,
                report_id=task.report_id,
            )
    assert not (workspace / task.required_output_relative).exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"

    validated: list[str] = []
    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_validate_resume_workspace_artifact",
            lambda *_args, **_kwargs: validated.append(task.report_id),
        )
        adapter._promote_resume_workspace_view(
            view,
            workspace=workspace,
            worktree=source,
            report_id=task.report_id,
        )
    assert validated == [task.report_id]

    assert (workspace / task.required_output_relative).read_text(
        encoding="utf-8"
    ) == '{"memo": "phase local"}\n'
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\nphase ledger\n"

    prior_memo = (workspace / task.required_output_relative).read_bytes()
    config.state_root.chmod(0o750)
    production_jobs_root = config.state_root / "jobs"
    production_jobs_root.mkdir(exist_ok=True)
    production_jobs_root.chmod(0o770)
    production_job_root = production_jobs_root / task.job_id
    production_job_root.mkdir(exist_ok=True)
    production_job_root.chmod(0o770)
    revision_task = replace(
        task,
        attempt_id=f"resume_{'b' * 32}",
        prior_output_sha256=((
            task.required_output_relative,
            hashlib.sha256(prior_memo).hexdigest(),
        ),),
        prior_output_archive_id=(
            f"jobs/{task.job_id}/resume-history/"
            f"resume_{'b' * 32}/prior_memo.json"
        ),
    )
    revision_runtime = tmp_path / "runtime-revision"
    revision_runtime.mkdir()
    revision_view = adapter._prepare_resume_workspace_view(
        runtime_root=revision_runtime,
        workspace=workspace,
        resume_task=revision_task,
    )
    revised_memo = '{"memo": "formula-specific revision"}\n'
    (revision_view.root / task.required_output_relative).write_text(
        revised_memo,
        encoding="utf-8",
    )
    (revision_view.root / "identity/web_execution_ledger.md").write_text(
        "revision ledger\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="lacks an outer workspace transaction"):
        adapter._promote_resume_workspace_view(
            revision_view,
            workspace=workspace,
        )
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert not (
        config.state_root / revision_task.prior_output_archive_id
    ).exists()
    revision_archive = config.state_root / revision_task.prior_output_archive_id
    revision_attempt_root = revision_archive.parent
    pre_revision_ledger = (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes()
    validated_attempt_root = revision_attempt_root.with_name(
        f"{revision_attempt_root.name}-validated"
    )
    revision_attempt_root.rename(validated_attempt_root)
    revision_attempt_root.mkdir(mode=0o707)
    revision_attempt_root.chmod(0o707)
    with pytest.raises(RuntimeError, match="archive parent is unsafe"):
        with workspace_transaction_lock(
            config.state_root,
            workspace,
            error_code="BLOCK_TEST",
        ):
            adapter._promote_resume_workspace_view(
                revision_view,
                workspace=workspace,
            )
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()
    revision_attempt_root.rmdir()
    validated_attempt_root.rename(revision_attempt_root)

    original_private_archive_writer = (
        adapter_module._write_private_resume_archive_at
    )
    detached_attempt_root = revision_attempt_root.with_name(
        f"{revision_attempt_root.name}-detached"
    )
    archive_parent_swapped = False

    def swap_archive_parent_after_validation(
        parent_descriptor,
        name,
        payload,
        *,
        relative,
    ):
        nonlocal archive_parent_swapped
        revision_attempt_root.rename(detached_attempt_root)
        revision_attempt_root.mkdir(mode=0o700)
        archive_parent_swapped = True
        return original_private_archive_writer(
            parent_descriptor,
            name,
            payload,
            relative=relative,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter_module,
            "_write_private_resume_archive_at",
            swap_archive_parent_after_validation,
        )
        with pytest.raises(RuntimeError, match="archive parent changed"):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert archive_parent_swapped is True
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()
    assert not (detached_attempt_root / "prior_memo.json").exists()
    revision_attempt_root.rmdir()
    detached_attempt_root.rename(revision_attempt_root)

    def retain_private_archive_temporary(path, *, dir_fd=None):
        if (
            str(path).startswith(".prior_memo.json.")
            and str(path).endswith(".tmp")
        ):
            raise OSError("injected persistent private archive temporary failure")
        return original_unlink(path, dir_fd=dir_fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "unlink", retain_private_archive_temporary)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*prior memo archive cleanup failed",
        ):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()
    orphaned_private_archives = tuple(
        revision_attempt_root.glob(".prior_memo.json.*.tmp")
    )
    assert len(orphaned_private_archives) == 1
    assert orphaned_private_archives[0].read_bytes() == prior_memo
    orphaned_private_archives[0].unlink()

    original_archive_open = os.open
    original_archive_close = os.close
    captured_archive_descriptors: list[int] = []
    archive_close_failure_injected = False

    def capture_private_archive_descriptor(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        descriptor = original_archive_open(path, flags, mode, dir_fd=dir_fd)
        if (
            str(path).startswith(".prior_memo.json.")
            and str(path).endswith(".tmp")
            and flags & os.O_WRONLY
        ):
            captured_archive_descriptors.append(descriptor)
        return descriptor

    def fail_after_private_archive_close(descriptor):
        nonlocal archive_close_failure_injected
        if (
            captured_archive_descriptors
            and descriptor == captured_archive_descriptors[-1]
            and not archive_close_failure_injected
        ):
            original_archive_close(descriptor)
            archive_close_failure_injected = True
            raise OSError("injected private archive close writeback failure")
        return original_archive_close(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", capture_private_archive_descriptor)
        patcher.setattr(os, "close", fail_after_private_archive_close)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*prior memo archive descriptor close failed",
        ):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert archive_close_failure_injected is True
    assert len(captured_archive_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(captured_archive_descriptors[0])
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()
    assert not tuple(revision_attempt_root.glob(".prior_memo.json.*.tmp"))

    original_parent_open = os.open
    original_parent_close = os.close
    captured_attempt_descriptors: list[int] = []
    attempt_close_failure_injected = False

    def capture_attempt_descriptor(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = original_parent_open(path, flags, mode, dir_fd=dir_fd)
        if (
            str(path) == revision_attempt_root.name
            and dir_fd is not None
            and not captured_attempt_descriptors
        ):
            captured_attempt_descriptors.append(descriptor)
        return descriptor

    def fail_after_attempt_parent_close(descriptor):
        nonlocal attempt_close_failure_injected
        if (
            captured_attempt_descriptors
            and descriptor == captured_attempt_descriptors[0]
            and not attempt_close_failure_injected
        ):
            original_parent_close(descriptor)
            attempt_close_failure_injected = True
            raise OSError("injected attempt parent close-after failure")
        return original_parent_close(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", capture_attempt_descriptor)
        patcher.setattr(os, "close", fail_after_attempt_parent_close)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*parent descriptor close failed",
        ):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert attempt_close_failure_injected is True
    assert len(captured_attempt_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(captured_attempt_descriptors[0])
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()

    original_open_absolute = adapter_module._open_absolute_directory_fd
    captured_state_root_descriptors: list[int] = []
    root_close_failure_injected = False

    def capture_state_root_descriptor(path, *, error_code):
        descriptor = original_open_absolute(path, error_code=error_code)
        if path == config.state_root and not captured_state_root_descriptors:
            captured_state_root_descriptors.append(descriptor)
        return descriptor

    def fail_before_state_root_close(descriptor):
        nonlocal root_close_failure_injected
        if (
            captured_state_root_descriptors
            and descriptor == captured_state_root_descriptors[0]
            and not root_close_failure_injected
        ):
            root_close_failure_injected = True
            raise OSError("injected state root close-before failure")
        return original_parent_close(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter_module,
            "_open_absolute_directory_fd",
            capture_state_root_descriptor,
        )
        patcher.setattr(os, "close", fail_before_state_root_close)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*parent descriptor close failed",
        ):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert root_close_failure_injected is True
    assert len(captured_state_root_descriptors) == 1
    os.fstat(captured_state_root_descriptors[0])
    original_parent_close(captured_state_root_descriptors[0])
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()

    combined_attempt_descriptors: list[int] = []
    combined_close_failure_injected = False

    def capture_combined_attempt_descriptor(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        descriptor = original_parent_open(path, flags, mode, dir_fd=dir_fd)
        if (
            str(path) == revision_attempt_root.name
            and dir_fd is not None
            and not combined_attempt_descriptors
        ):
            combined_attempt_descriptors.append(descriptor)
        return descriptor

    def fail_after_combined_attempt_close(descriptor):
        nonlocal combined_close_failure_injected
        if (
            combined_attempt_descriptors
            and descriptor == combined_attempt_descriptors[0]
            and not combined_close_failure_injected
        ):
            original_parent_close(descriptor)
            combined_close_failure_injected = True
            raise OSError("injected close while orphan blocker is active")
        return original_parent_close(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", capture_combined_attempt_descriptor)
        patcher.setattr(os, "unlink", retain_private_archive_temporary)
        patcher.setattr(os, "close", fail_after_combined_attempt_close)
        with pytest.raises(
            RuntimeError,
            match="ORPHANED_WRITER.*prior memo archive cleanup failed",
        ):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    revision_view,
                    workspace=workspace,
                )
    assert combined_close_failure_injected is True
    assert len(combined_attempt_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(combined_attempt_descriptors[0])
    assert (workspace / task.required_output_relative).read_bytes() == prior_memo
    assert (
        workspace / "identity/web_execution_ledger.md"
    ).read_bytes() == pre_revision_ledger
    assert not revision_archive.exists()
    combined_orphaned_archives = tuple(
        revision_attempt_root.glob(".prior_memo.json.*.tmp")
    )
    assert len(combined_orphaned_archives) == 1
    assert combined_orphaned_archives[0].read_bytes() == prior_memo
    combined_orphaned_archives[0].unlink()

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_validate_resume_workspace_artifact",
            lambda *_args, **_kwargs: None,
        )
        with workspace_transaction_lock(
            config.state_root,
            workspace,
            error_code="BLOCK_TEST",
        ):
            adapter._promote_resume_workspace_view(
                revision_view,
                workspace=workspace,
                worktree=source,
                report_id=task.report_id,
            )
    assert (workspace / task.required_output_relative).read_text(
        encoding="utf-8"
    ) == revised_memo
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ).endswith("phase ledger\nrevision ledger\n")
    archived_prior = config.state_root / revision_task.prior_output_archive_id
    assert archived_prior.read_bytes() == prior_memo
    assert archived_prior.stat().st_mode & 0o777 == 0o400
    assert archived_prior.parent.stat().st_mode & 0o777 == 0o700

    accepted_revision = (workspace / task.required_output_relative).read_bytes()
    accepted_ledger = (workspace / "identity/web_execution_ledger.md").read_bytes()
    rollback_task = replace(
        revision_task,
        attempt_id=f"resume_{'d' * 32}",
        prior_output_sha256=((
            task.required_output_relative,
            hashlib.sha256(accepted_revision).hexdigest(),
        ),),
        prior_output_archive_id=(
            f"jobs/{task.job_id}/resume-history/"
            f"resume_{'d' * 32}/prior_memo.json"
        ),
    )
    rollback_runtime = tmp_path / "runtime-revision-rollback"
    rollback_runtime.mkdir()
    rollback_view = adapter._prepare_resume_workspace_view(
        runtime_root=rollback_runtime,
        workspace=workspace,
        resume_task=rollback_task,
    )
    (rollback_view.root / task.required_output_relative).write_text(
        '{"memo": "rollback candidate"}\n',
        encoding="utf-8",
    )
    (rollback_view.root / "identity/web_execution_ledger.md").write_text(
        "rollback ledger\n",
        encoding="utf-8",
    )

    def fail_revision_after_ledger_replace(
        workspace_root,
        relative,
        text,
        *,
        expected_bytes,
    ):
        original_atomic_replace(
            workspace_root,
            relative,
            text,
            expected_bytes=expected_bytes,
        )
        if relative == "identity/web_execution_ledger.md" and "rollback ledger" in text:
            raise OSError("injected revision ledger failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter_module,
            "_replace_text_atomic_existing",
            fail_revision_after_ledger_replace,
        )
        with pytest.raises(OSError, match="revision ledger failure"):
            with workspace_transaction_lock(
                config.state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                adapter._promote_resume_workspace_view(
                    rollback_view,
                    workspace=workspace,
                )
    assert (workspace / task.required_output_relative).read_bytes() == accepted_revision
    assert (workspace / "identity/web_execution_ledger.md").read_bytes() == accepted_ledger
    assert not (
        config.state_root / rollback_task.prior_output_archive_id
    ).exists()

    tamper_task = replace(
        revision_task,
        attempt_id=f"resume_{'e' * 32}",
        prior_output_sha256=((
            task.required_output_relative,
            hashlib.sha256(accepted_revision).hexdigest(),
        ),),
        prior_output_archive_id=(
            f"jobs/{task.job_id}/resume-history/"
            f"resume_{'e' * 32}/prior_memo.json"
        ),
    )
    tamper_runtime = tmp_path / "runtime-revision-tamper"
    tamper_runtime.mkdir()
    tamper_view = adapter._prepare_resume_workspace_view(
        runtime_root=tamper_runtime,
        workspace=workspace,
        resume_task=tamper_task,
    )
    (tamper_view.root / task.required_output_relative).write_text(
        '{"memo": "next revision"}\n',
        encoding="utf-8",
    )
    (tamper_view.root / "identity/web_execution_ledger.md").write_text(
        "next revision ledger\n",
        encoding="utf-8",
    )
    (workspace / task.required_output_relative).write_text(
        '{"memo": "concurrent tamper"}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="prior resume output changed"):
        with workspace_transaction_lock(
            config.state_root,
            workspace,
            error_code="BLOCK_TEST",
        ):
            adapter._promote_resume_workspace_view(
                tamper_view,
                workspace=workspace,
            )
    assert not (
        config.state_root / tamper_task.prior_output_archive_id
    ).exists()
    (workspace / task.required_output_relative).write_bytes(accepted_revision)


def test_resume_terminal_delivery_is_host_staged_and_bounded(tmp_path):
    from dataclasses import replace

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
        _validate_openclaw_terminal_status,
    )

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    task = replace(
        _resume_task(),
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
    )
    _write_resume_prompt_inputs(workspace, task=task)
    _write_resume_facts(
        workspace,
        task,
        {
            "formula_facts": {
                "formula": "divide(minus(close, open), pre_close)",
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            }
        },
    )
    (workspace / "identity/web_agent_resume.md").write_text(
        "facts only\n", encoding="utf-8"
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n", encoding="utf-8"
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )

    def phase_view(name: str):
        runtime_root = tmp_path / name
        runtime_root.mkdir()
        return adapter._prepare_resume_workspace_view(
            runtime_root=runtime_root,
            workspace=workspace,
            resume_task=task,
        )

    view = phase_view("valid")
    adapter._stage_resume_terminal_delivery(
        view,
        terminal_text=json.dumps(
            {
                "status": "MEMO_DRAFT_COMPLETE",
                "memo": {"z": "last", "a": "first"},
                "ledger": "phase ledger",
            }
        ),
        resume_task=task,
    )
    assert (view.root / task.required_output_relative).read_text(
        encoding="utf-8"
    ) == '{"a":"first","z":"last"}\n'
    assert (view.root / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "phase ledger\n"
    assert not (view.root / task.optional_output_relative).exists()

    canonicalized = phase_view("canonicalized")
    model_memo = _resume_research_patch()
    model_memo["evidence_comparison"]["mechanism_supported"] = "no"
    model_memo["formula_component_map"][0][
        "economic_state"
    ] = "model-authored research state"
    adapter._stage_resume_terminal_delivery(
        canonicalized,
        terminal_text=json.dumps(
            {
                "status": "MEMO_DRAFT_COMPLETE",
                "memo": model_memo,
                "ledger": "phase ledger",
            }
        ),
        resume_task=task,
        rehydrate_immutable_fields=True,
    )
    canonical_memo = json.loads(
        (canonicalized.root / task.required_output_relative).read_text(
            encoding="utf-8"
        )
    )
    canonical_answer = json.loads(
        (canonicalized.root / task.answer_form_relative).read_text(
            encoding="utf-8"
        )
    )
    assert canonical_memo["source_refs"] == canonical_answer["source_refs"]
    assert (
        canonical_memo["evidence_comparison"]["observed_metrics"]
        == canonical_answer["evidence_comparison"]["observed_metrics"]
    )
    assert (
        canonical_memo["operator_claim_consistency"][
            "has_additive_rank_raw_ratio"
        ]
        is False
    )
    assert canonical_memo["formula_component_map"][0]["component_id"] == "formula_root"
    assert (
        canonical_memo["formula_component_map"][0]["economic_state"]
        == "model-authored research state"
    )
    assert canonical_memo["evidence_comparison"]["mechanism_supported"] == "no"
    assert canonical_memo["canonical_write_permission"] is False
    assert canonical_memo["execution_allowed_by_default"] is False
    assert canonical_memo["producer"] == "current_main_agent"

    anchored_component = phase_view("anchored-component")
    anchored_component_patch = _resume_research_patch()
    anchored_component_patch["formula_component_map"][0][
        "component_id"
    ] = "formula_root"
    adapter._stage_resume_terminal_delivery(
        anchored_component,
        terminal_text=json.dumps(
            {
                "status": "MEMO_DRAFT_COMPLETE",
                "memo": anchored_component_patch,
                "ledger": "phase ledger",
            }
        ),
        resume_task=task,
        rehydrate_immutable_fields=True,
    )
    anchored_memo = json.loads(
        (anchored_component.root / task.required_output_relative).read_text(
            encoding="utf-8"
        )
    )
    assert (
        anchored_memo["formula_component_map"][0]["component_id"]
        == "formula_root"
    )

    machine_owned_override = phase_view("machine-owned-override")
    machine_override_patch = _resume_research_patch()
    machine_override_patch["source_refs"] = {"wrong": "model-owned-copy"}
    with pytest.raises(
        RuntimeError,
        match="research patch is invalid:top-level field set",
    ):
        adapter._stage_resume_terminal_delivery(
            machine_owned_override,
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": machine_override_patch,
                    "ledger": "phase ledger",
                }
            ),
            resume_task=task,
            rehydrate_immutable_fields=True,
        )

    component_override = _resume_research_patch()
    component_override["formula_component_map"][0]["component_id"] = "invented"
    metrics_override = _resume_research_patch()
    metrics_override["evidence_comparison"]["observed_metrics"] = {}
    operator_override = _resume_research_patch()
    operator_override["operator_claim_consistency"][
        "has_additive_rank_raw_ratio"
    ] = True
    for name, memo, expected in (
        (
            "component-identity-override",
            component_override,
            "research patch is invalid:component field",
        ),
        (
            "observed-metrics-override",
            metrics_override,
            "research patch is invalid:evidence_comparison",
        ),
        (
            "operator-presence-override",
            operator_override,
            "research patch is invalid:operator_claim_consistency",
        ),
    ):
        with pytest.raises(RuntimeError, match=expected):
            adapter._stage_resume_terminal_delivery(
                phase_view(name),
                terminal_text=json.dumps(
                    {
                        "status": "MEMO_DRAFT_COMPLETE",
                        "memo": memo,
                        "ledger": "phase ledger",
                    }
                ),
                resume_task=task,
                rehydrate_immutable_fields=True,
            )

    wrong_evidence_type = _resume_research_patch()
    wrong_evidence_type["evidence_comparison"]["contradictions"] = {
        "not": "a list"
    }
    wrong_component_type = _resume_research_patch()
    wrong_component_type["formula_component_map"][0]["metric_link"] = 1
    invented_component_link = _resume_research_patch()
    invented_component_link["formula_state_estimator"]["component_links"] = [
        "invented_component"
    ]
    wrong_council_type = _resume_research_patch()
    wrong_council_type["council_questions"] = {"not": "a list"}
    wrong_operator_type = _resume_research_patch()
    wrong_operator_type["operator_claim_consistency"][
        "claims_correlation_or_covariance"
    ] = 1
    blank_operator_justification = _resume_research_patch()
    blank_operator_justification["operator_claim_consistency"].update(
        {
            "claims_dependence_without_operator_justification": True,
            "explicit_dependence_justification": " ",
        }
    )
    non_finite_component = _resume_research_patch()
    non_finite_component["formula_component_map"][0]["metric_link"] = float("nan")
    for name, memo, expected in (
        (
            "wrong-evidence-type",
            wrong_evidence_type,
            "research patch is invalid:evidence_comparison value type",
        ),
        (
            "wrong-component-type",
            wrong_component_type,
            "research patch is invalid:component field",
        ),
        (
            "invented-component-link",
            invented_component_link,
            "research patch is invalid:formula_state_estimator value type",
        ),
        (
            "wrong-council-type",
            wrong_council_type,
            "research patch is invalid:council_questions value type",
        ),
        (
            "wrong-operator-type",
            wrong_operator_type,
            "research patch is invalid:operator_claim_consistency value type",
        ),
        (
            "blank-operator-justification",
            blank_operator_justification,
            "research patch is invalid:operator_claim_consistency value type",
        ),
        (
            "non-finite-component",
            non_finite_component,
            "research patch is invalid:component field",
        ),
    ):
        with pytest.raises(RuntimeError, match=expected):
            adapter._stage_resume_terminal_delivery(
                phase_view(name),
                terminal_text=json.dumps(
                    {
                        "status": "MEMO_DRAFT_COMPLETE",
                        "memo": memo,
                        "ledger": "phase ledger",
                    }
                ),
                resume_task=task,
                rehydrate_immutable_fields=True,
            )

    locked_secret = "locked-field-secret-for-rehydration-test"
    secret_in_locked_field = phase_view("secret-in-locked-field")
    secret_memo = _resume_research_patch()
    secret_memo["producer"] = locked_secret
    with pytest.raises(RuntimeError, match="memo contains secret material"):
        adapter._stage_resume_terminal_delivery(
            secret_in_locked_field,
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": secret_memo,
                    "ledger": "phase ledger",
                }
            ),
            resume_task=task,
            extra_secret_values=(locked_secret,),
            rehydrate_immutable_fields=True,
        )

    duplicated_closing_delimiter = phase_view("duplicated-closing-delimiter")
    valid_delivery = json.dumps(
        {
            "status": "MEMO_DRAFT_COMPLETE",
            "memo": {"a": "first"},
            "ledger": "phase ledger",
        }
    )
    authentic_raw_text = (
        "All authorized inputs were reviewed; the exact delivery follows.\n\n"
        + valid_delivery
    )
    authentic_transport = json.dumps(
        {
            "payloads": [{"text": "Visible research summary."}],
            "meta": {
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                },
                "finalAssistantVisibleText": "Visible research summary.",
                "finalAssistantRawText": authentic_raw_text,
                "replayInvalid": True,
                "livenessState": "working",
            },
        }
    )
    authentic_openclaw_transport = phase_view("authentic-openclaw-transport")
    adapter._stage_resume_terminal_delivery(
        authentic_openclaw_transport,
        terminal_text=_validate_openclaw_terminal_status(
            authentic_transport,
            "embedded run agent end: isError=false\n",
        ),
        resume_task=task,
    )
    assert (
        authentic_openclaw_transport.root / task.required_output_relative
    ).read_text(encoding="utf-8") == '{"a":"first"}\n'

    adapter._stage_resume_terminal_delivery(
        duplicated_closing_delimiter,
        terminal_text=valid_delivery + '"}',
        resume_task=task,
    )
    assert (
        duplicated_closing_delimiter.root / task.required_output_relative
    ).read_text(encoding="utf-8") == '{"a":"first"}\n'

    bounded_plain_prefix = phase_view("bounded-plain-prefix")
    adapter._stage_resume_terminal_delivery(
        bounded_plain_prefix,
        terminal_text=(
            "All six authorized inputs were reviewed; `component_links` is "
            '`[\\"formula_root\\"]`; the exact delivery follows.\n\n'
            + valid_delivery
        ),
        resume_task=task,
    )
    assert (
        bounded_plain_prefix.root / task.required_output_relative
    ).read_text(encoding="utf-8") == '{"a":"first"}\n'

    markdown_summary_prefix = (
        "All six authorized inputs were reviewed.\n\n"
        "**Verification pass (reasoning):**\n"
        "- Patch fields and immutable metrics were checked.\n"
        "- Operator consistency and the byte budget were checked.\n\n"
    )
    adapter._stage_resume_terminal_delivery(
        phase_view("markdown-summary-prefix"),
        terminal_text=markdown_summary_prefix + valid_delivery,
        resume_task=task,
    )

    emphasized_label_prefix = (
        "All six authorized inputs were reviewed.\n\n"
        "**Analysis summary:**\n"
        "- **Formula (locked):** `-1 * cs_zscore(formula_state)`.\n"
        "- **Observed evidence:** The pinned metrics were checked.\n\n"
    )
    adapter._stage_resume_terminal_delivery(
        phase_view("emphasized-label-prefix"),
        terminal_text=emphasized_label_prefix + valid_delivery,
        resume_task=task,
    )

    production_length_emphasized_prefix = (
        "All six authorized inputs were reviewed.\n\n"
        "**Analysis summary:**\n"
        "- **Formula (locked):** `-1 * cs_zscore(formula_state)`.\n"
        "- **Observed evidence:** "
        + ("Each pinned metric and identity field was checked. " * 31)
        + "\n\n"
    )
    assert (
        1_600
        < len(production_length_emphasized_prefix.encode("utf-8"))
        < 2_048
    )
    adapter._stage_resume_terminal_delivery(
        phase_view("production-length-emphasized-prefix"),
        terminal_text=production_length_emphasized_prefix + valid_delivery,
        resume_task=task,
    )

    runtime_length_prefix = (
        "All authorized inputs were reviewed. "
        + ("Each pinned metric and identity field was checked. " * 25)
        + "The exact delivery follows.\n\n"
    )
    assert 1_024 < len(runtime_length_prefix.encode("utf-8")) < 2_048
    adapter._stage_resume_terminal_delivery(
        phase_view("runtime-length-plain-prefix"),
        terminal_text=runtime_length_prefix + valid_delivery,
        resume_task=task,
    )

    formula_self_check_prefix = (
        "All authorized inputs were reviewed. The target uses "
        "`formula_state_{i,t}`, while `component_links=[\"formula_root\"]`. "
        + ("Each pinned metric and identity field was checked. " * 24)
        + "The exact delivery follows.\n\n"
    )
    assert 1_024 < len(formula_self_check_prefix.encode("utf-8")) < 2_048
    adapter._stage_resume_terminal_delivery(
        phase_view("formula-brace-prefix"),
        terminal_text=formula_self_check_prefix + valid_delivery,
        resume_task=task,
    )

    for name, prefix in (
        ("incomplete-object-prefix", 'Self-check {"wrapper":'),
        ("incomplete-array-prefix", 'Self-check ["wrapper",'),
        ("labelled-array-prefix", 'Self-check ["prior"]'),
        ("unclosed-inline-code-prefix", "Self-check `formula_state_{i,t}"),
        ("unclosed-emphasis-prefix", "- **Formula (locked): summary\n"),
        ("empty-emphasis-prefix", "- ****summary\n"),
        ("spaced-emphasis-prefix", "- **Formula ** prose\n"),
        ("trailing-emphasis-prefix", "- **Formula:** prose __\n"),
        ("inline-code-closing-emphasis-prefix", "- **Formula `x**` prose\n"),
    ):
        with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
            adapter._stage_resume_terminal_delivery(
                phase_view(name),
                terminal_text=prefix + valid_delivery,
                resume_task=task,
            )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("inline-code-json-object-prefix"),
            terminal_text=f"Prior `{valid_delivery}`\n" + valid_delivery,
            resume_task=task,
        )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("structured-prefix"),
            terminal_text='self-check {"not":"the delivery"}\n' + valid_delivery,
            resume_task=task,
        )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("oversized-prefix"),
            terminal_text=("x" * 2_049) + valid_delivery,
            resume_task=task,
        )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("code-fence-prefix"),
            terminal_text="```json\n" + valid_delivery,
            resume_task=task,
        )

    for name, prefix in (
        ("array-prefix", '["prior"]\n'),
        ("json-scalar-prefix", "null\n"),
        ("json-scalar-extra-token-prefix", "null true\n"),
        ("json-scalar-bracket-boundary-prefix", "null]next\n"),
        ("json-scalar-unicode-boundary-prefix", "null，next\n"),
        ("bullet-json-scalar-prefix", "- null\n"),
        ("numbered-json-scalar-prefix", "1. true\n"),
        ("malformed-array-prefix", "[prior]\n"),
        ("tilde-fence-prefix", "~~~json\n"),
    ):
        with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
            adapter._stage_resume_terminal_delivery(
                phase_view(name),
                terminal_text=prefix + valid_delivery,
                resume_task=task,
            )

    prefix_secret = "resume-prefix-secret-material-for-regression"
    with pytest.raises(RuntimeError, match="prefix contains secret material"):
        adapter._stage_resume_terminal_delivery(
            phase_view("secret-prefix"),
            terminal_text=(
                f"All inputs including {prefix_secret} were reviewed.\n"
                + valid_delivery
            ),
            resume_task=task,
            extra_secret_values=(prefix_secret,),
        )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("arbitrary-trailing-text"),
            terminal_text=valid_delivery + " trailing text",
            resume_task=task,
        )

    with pytest.raises(RuntimeError, match="delivery is invalid JSON"):
        adapter._stage_resume_terminal_delivery(
            phase_view("invalid-json"),
            terminal_text="MEMO_DRAFT_COMPLETE",
            resume_task=task,
        )
    with pytest.raises(RuntimeError, match="delivery schema is invalid"):
        adapter._stage_resume_terminal_delivery(
            phase_view("extra-key"),
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": {},
                    "ledger": "phase ledger",
                    "extra": True,
                }
            ),
            resume_task=task,
        )
    with pytest.raises(RuntimeError, match="memo exceeds byte budget"):
        adapter._stage_resume_terminal_delivery(
            phase_view("oversized-memo"),
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": {"text": "x" * 24_000},
                    "ledger": "phase ledger",
                }
            ),
            resume_task=task,
        )
    with pytest.raises(RuntimeError, match="research patch exceeds byte budget"):
        adapter._stage_resume_terminal_delivery(
            phase_view("oversized-research-patch"),
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": {
                        **_resume_research_patch(),
                        "producer": "x" * 16_000,
                    },
                    "ledger": "phase ledger",
                }
            ),
            resume_task=task,
            rehydrate_immutable_fields=True,
        )
    with pytest.raises(RuntimeError, match="ledger is missing or too large"):
        adapter._stage_resume_terminal_delivery(
            phase_view("oversized-ledger"),
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": {},
                    "ledger": "x" * 1_601,
                }
            ),
            resume_task=task,
        )
    prechanged = phase_view("prechanged")
    (prechanged.root / task.required_output_relative).write_text(
        "agent wrote directly\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="changed before Host staging"):
        adapter._stage_resume_terminal_delivery(
            prechanged,
            terminal_text=json.dumps(
                {
                    "status": "MEMO_DRAFT_COMPLETE",
                    "memo": {},
                    "ledger": "phase ledger",
                }
            ),
            resume_task=task,
        )


def test_container_resume_requires_host_staged_terminal_delivery(
    tmp_path,
    monkeypatch,
):
    import subprocess
    from dataclasses import replace

    from factor_factory.console.agent_adapter import (
        BLOCK_AGENT_ORPHANED_WRITER,
        BLOCK_AGENT_RUNTIME_FAILED,
    )
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )
    from factor_factory.console.models import ResearchJob

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    task = replace(
        _resume_task(),
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
    )
    _write_resume_prompt_inputs(workspace, task=task)
    _write_resume_facts(
        workspace,
        task,
        {
            "formula_facts": {
                "formula": "divide(minus(close, open), pre_close)",
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            }
        },
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n",
        encoding="utf-8",
    )
    token = "broker-client-token-for-empty-resume-test"
    token_file = tmp_path / "broker-client-token"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o600)
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite", key=token),
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=tmp_path / "broker-scan",
        openclaw_profile_template=(
            Path(__file__).resolve().parents[1]
            / "deploy"
            / "factorforge-console"
            / "openclaw.json.example"
        ),
        container_runtime="docker-test",
        agent_container_image="factorforge-agent:test",
        auth_disabled=True,
    )
    job = ResearchJob(
        job_id=task.job_id,
        factor_id=task.factor_id,
        research_id=task.research_id,
        report_id=task.report_id,
        request=_request(),
        base_commit="a" * 40,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    git_view = tmp_path / "engine.git"
    git_view.mkdir()
    monkeypatch.setattr(adapter, "_prepare_git_view", lambda **_kwargs: git_view)
    monkeypatch.setattr(
        adapter,
        "_initialize_credential_material_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "credential_material_state",
        lambda _job_id: "not_issued",
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (None, (token,), None),
    )
    monkeypatch.setattr(
        adapter,
        "_cleanup_aws_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "_run_runtime", lambda *_args, **_kwargs: "{}")
    monkeypatch.setattr(
        adapter,
        "_validate_agent_binding",
        lambda *_args, **_kwargs: None,
    )
    research_commands: list[list[str]] = []

    terminal_text = "MEMO_DRAFT_COMPLETE"

    def fake_run(command, **_kwargs):
        research_commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "payloads": [{"text": terminal_text}],
                    "meta": {
                        "agentMeta": {"provider": "deepseek", "model": "reasoner"},
                        "finalAssistantVisibleText": terminal_text,
                        "livenessState": "working",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = adapter.run(
        job,
        worktree=source,
        workspace=workspace,
        resume=True,
        resume_task=task,
    )

    assert result.returncode == 1
    receipt = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert receipt["returncode"] == 1
    assert receipt["error_code"] == BLOCK_AGENT_RUNTIME_FAILED
    assert "resume terminal delivery is invalid JSON" in receipt["stderr_tail"]
    assert not (workspace / task.required_output_relative).exists()
    assert (workspace / "identity/web_execution_ledger.md").read_text(
        encoding="utf-8"
    ) == "parent ledger\n"
    assert len(research_commands) == 1
    research_command = research_commands[0]
    thinking_index = research_command.index("--thinking")
    assert research_command[thinking_index + 1] == "medium"
    workspace_mount = next(
        item
        for item in research_command
        if item.startswith("type=bind,src=")
        and f",dst={workspace.resolve()}" in item
        and item.endswith(",readonly")
    )
    view_root = Path(
        workspace_mount.split("src=", 1)[1].split(",dst=", 1)[0]
    )
    assert not view_root.is_relative_to(
        config.state_root / "jobs" / job.job_id / "container-agent-phases" / task.attempt_id
    )
    assert not any(
        f"src={view_root / task.required_output_relative}" in item
        for item in research_command
    )
    auth_store = (
        config.state_root
        / "jobs"
        / job.job_id
        / "container-agent-phases"
        / task.attempt_id
        / "agent/openclaw-agent.sqlite"
    )
    assert any(
        f"src={auth_store},dst={auth_store}" in item
        and not item.endswith(",readonly")
        for item in research_command
    )

    terminal_text = json.dumps(
        {
            "status": "MEMO_DRAFT_COMPLETE",
            "memo": {"leaked_value": token},
            "ledger": "phase ledger",
        }
    )
    secret_task = replace(task, attempt_id=f"resume_{'d' * 32}")
    _write_resume_prompt_inputs(workspace, task=secret_task)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_promote_resume_workspace_view",
            lambda *_args, **_kwargs: None,
        )
        secret_result = adapter.run(
            job,
            worktree=source,
            workspace=workspace,
            resume=True,
            resume_task=secret_task,
        )
    assert secret_result.returncode == 1
    secret_receipt_text = Path(secret_result.result_path).read_text(encoding="utf-8")
    assert "resume terminal memo contains secret material" in secret_receipt_text
    assert token not in secret_receipt_text

    terminal_text = json.dumps(
        {
            "status": "MEMO_DRAFT_COMPLETE",
            "memo": _resume_research_patch(),
            "ledger": "phase ledger",
        }
    )
    io_failure_task = replace(task, attempt_id=f"resume_{'b' * 32}")
    _write_resume_prompt_inputs(workspace, task=io_failure_task)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_promote_resume_workspace_view",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected promotion I/O failure")
            ),
        )
        io_failure_result = adapter.run(
            job,
            worktree=source,
            workspace=workspace,
            resume=True,
            resume_task=io_failure_task,
        )
    assert io_failure_result.returncode == 1
    io_failure_receipt = json.loads(
        Path(io_failure_result.result_path).read_text(encoding="utf-8")
    )
    assert io_failure_receipt["error_code"] == BLOCK_AGENT_RUNTIME_FAILED
    assert "resume promotion I/O failure:OSError" in io_failure_receipt["stderr_tail"]

    orphan_task = replace(task, attempt_id=f"resume_{'c' * 32}")
    _write_resume_prompt_inputs(workspace, task=orphan_task)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter,
            "_promote_resume_workspace_view",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError(f"{BLOCK_AGENT_ORPHANED_WRITER}: injected uncertainty")
            ),
        )
        with pytest.raises(RuntimeError, match=BLOCK_AGENT_ORPHANED_WRITER):
            adapter.run(
                job,
                worktree=source,
                workspace=workspace,
                resume=True,
                resume_task=orphan_task,
            )


def test_openclaw_terminal_status_is_structured_and_fail_closed():
    from factor_factory.console.container_agent_adapter import (
        _validate_openclaw_terminal_status,
    )

    def receipt(
        final_text: str,
        *,
        include_optional_final: bool = True,
        include_payloads: bool = True,
    ) -> str:
        metadata = {
            "agentMeta": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
            },
            "livenessState": "working",
        }
        if include_optional_final:
            metadata["finalAssistantVisibleText"] = final_text
        payload = {"meta": metadata}
        if include_payloads:
            payload["payloads"] = [{"text": final_text}]
        return json.dumps(payload)

    assert _validate_openclaw_terminal_status(
        receipt("Memo authored and validator passed."),
        "embedded run agent end: isError=true\n"
        "embedded run agent end: isError=false\n",
    ) == "Memo authored and validator passed."
    assert _validate_openclaw_terminal_status(
        receipt("The memo explains why a context overflow would invalidate proof."),
        "",
    ) == "The memo explains why a context overflow would invalidate proof."
    assert _validate_openclaw_terminal_status(
        receipt(
            "Memo authored and validator passed.",
            include_optional_final=False,
        ),
        "",
    ) == "Memo authored and validator passed."
    raw_delivery = "Raw transport delivery."
    raw_transport = json.loads(receipt("Visible research summary."))
    raw_transport["meta"]["finalAssistantRawText"] = raw_delivery
    assert _validate_openclaw_terminal_status(
        json.dumps(raw_transport),
        "",
    ) == raw_delivery
    invalid_raw_type = json.loads(receipt("Visible research summary."))
    invalid_raw_type["meta"]["finalAssistantRawText"] = {
        "not": "a transport string"
    }
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(invalid_raw_type), "")
    null_raw_type = json.loads(receipt("Visible research summary."))
    null_raw_type["meta"]["finalAssistantRawText"] = None
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(null_raw_type), "")
    raw_terminal_error = json.loads(receipt("Visible research summary."))
    raw_terminal_error["meta"]["finalAssistantRawText"] = (
        "Model request failed: upstream rejected the request."
    )
    with pytest.raises(RuntimeError, match="terminal model error"):
        _validate_openclaw_terminal_status(json.dumps(raw_terminal_error), "")
    assert _validate_openclaw_terminal_status(
        receipt(
            "Memo authored and validator passed.",
            include_payloads=False,
        ),
        "",
    ) == "Memo authored and validator passed."
    lifecycle_only = json.dumps(
        {
            "meta": {
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                },
                "livenessState": "working",
            }
        }
    )
    assert _validate_openclaw_terminal_status(
        lifecycle_only,
        "embedded run agent end: isError=false\n",
    ) == ""
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(lifecycle_only, "")
    with pytest.raises(RuntimeError, match="terminal model error"):
        _validate_openclaw_terminal_status(
            receipt(
                "Context overflow: prompt too large for the model. Try /reset."
            ),
            "",
        )
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status("{}", "")
    invalid_type = json.loads(receipt("Memo authored."))
    invalid_type["meta"]["isError"] = "true"
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(invalid_type), "")
    cancelled = json.loads(receipt("Memo authored."))
    cancelled["meta"]["status"] = "cancelled"
    with pytest.raises(RuntimeError, match="terminal agent error"):
        _validate_openclaw_terminal_status(json.dumps(cancelled), "")
    replay_invalid = json.loads(receipt("Memo authored."))
    replay_invalid["meta"]["replayInvalid"] = True
    replay_invalid["meta"]["livenessState"] = "working"
    assert _validate_openclaw_terminal_status(
        json.dumps(replay_invalid),
        "",
    ) == "Memo authored."
    replay_invalid["meta"]["replayInvalid"] = "true"
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(replay_invalid), "")
    missing_liveness = json.loads(receipt("Memo authored."))
    del missing_liveness["meta"]["livenessState"]
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(missing_liveness), "")
    null_liveness = json.loads(receipt("Memo authored."))
    null_liveness["meta"]["livenessState"] = None
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(json.dumps(null_liveness), "")
    empty_liveness = json.loads(receipt("Memo authored."))
    empty_liveness["meta"]["livenessState"] = ""
    with pytest.raises(RuntimeError, match="terminal liveness state"):
        _validate_openclaw_terminal_status(json.dumps(empty_liveness), "")
    for liveness_state in ("abandoned", "blocked", "paused"):
        unusable = json.loads(receipt("Memo authored."))
        unusable["meta"]["livenessState"] = liveness_state
        with pytest.raises(RuntimeError, match="terminal liveness state"):
            _validate_openclaw_terminal_status(json.dumps(unusable), "")
    invalid_liveness_type = json.loads(receipt("Memo authored."))
    invalid_liveness_type["meta"]["livenessState"] = True
    with pytest.raises(RuntimeError, match="terminal receipt schema"):
        _validate_openclaw_terminal_status(
            json.dumps(invalid_liveness_type),
            "",
        )
    terminal_error = json.loads(receipt("Memo authored."))
    terminal_error["meta"]["error"] = {"kind": "runtime_failure"}
    with pytest.raises(RuntimeError, match="terminal agent error"):
        _validate_openclaw_terminal_status(json.dumps(terminal_error), "")
    incomplete_turn = json.loads(receipt("Memo authored."))
    incomplete_turn["meta"]["error"] = {
        "kind": "incomplete_turn",
        "message": "Agent could not generate a response.",
    }
    with pytest.raises(RuntimeError, match="terminal agent error"):
        _validate_openclaw_terminal_status(json.dumps(incomplete_turn), "")
    explicit_error = json.loads(receipt("Memo authored."))
    explicit_error["meta"]["isError"] = True
    with pytest.raises(RuntimeError, match="terminal agent error"):
        _validate_openclaw_terminal_status(json.dumps(explicit_error), "")
    with pytest.raises(RuntimeError, match="stderr reported a terminal agent error"):
        _validate_openclaw_terminal_status(
            receipt("Memo authored and validator passed."),
            "embedded run agent end: isError=false\n"
            "embedded run agent end: isError=true\n",
        )


def test_host_resume_validator_uses_phase_root_and_is_fail_closed(
    tmp_path,
    monkeypatch,
):
    import subprocess
    from types import SimpleNamespace

    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_FAILED
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    worktree = tmp_path / "worktree"
    validator = (
        worktree
        / "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py"
    )
    validator.parent.mkdir(parents=True)
    validator.write_text("# pinned validator\n", encoding="utf-8")
    phase_root = tmp_path / "phase"
    phase_root.mkdir()
    view = SimpleNamespace(root=phase_root)
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=worktree,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    captured: dict[str, object] = {}

    def passing_validator(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"report_id": "REPORT", "result": "PASS", "failures": []}
            ),
            stderr="",
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-validator")
    monkeypatch.setattr(subprocess, "run", passing_validator)
    adapter._validate_resume_workspace_artifact(
        view,
        worktree=worktree,
        report_id="REPORT",
    )

    assert captured["command"] == [
        sys.executable,
        "-B",
        str(validator),
        "--report-id",
        "REPORT",
    ]
    validator_env = captured["kwargs"]["env"]
    assert validator_env["FACTORFORGE_ROOT"] == str(phase_root)
    assert "DEEPSEEK_API_KEY" not in validator_env

    def rejecting_validator(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {"report_id": "REPORT", "result": "BLOCK", "failures": ["bad"]}
            ),
            stderr="bad",
        )

    monkeypatch.setattr(subprocess, "run", rejecting_validator)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_FAILED):
        adapter._validate_resume_workspace_artifact(
            view,
            worktree=worktree,
            report_id="REPORT",
        )


def test_workspace_promotion_lock_serializes_console_writers(tmp_path):
    import threading

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o770)
    state_root.chmod(0o770)
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=state_root,
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    started = threading.Event()
    acquired = threading.Event()

    def contender():
        started.set()
        with adapter._workspace_promotion_lock(workspace):
            acquired.set()

    with adapter._workspace_promotion_lock(workspace):
        with adapter._workspace_promotion_lock(workspace):
            assert not acquired.is_set()
        thread = threading.Thread(target=contender, daemon=True)
        thread.start()
        assert started.wait(timeout=1)
        assert not acquired.wait(timeout=0.1)
    assert acquired.wait(timeout=1)
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert stat.S_IMODE(state_root.stat().st_mode) == 0o770


def test_workspace_transaction_identity_includes_private_state_root(tmp_path):
    from factor_factory.console.workspace_transaction import (
        workspace_transaction_lock,
        workspace_transaction_lock_held,
    )

    workspace = tmp_path / "source/factor_research/FACTOR/research"
    workspace.mkdir(parents=True)
    trusted_state_root = tmp_path / "trusted-state"
    trusted_state_root.mkdir(mode=0o770)
    trusted_state_root.chmod(0o770)
    unsafe_state_root = tmp_path / "unsafe-state"
    unsafe_state_root.mkdir(mode=0o777)
    unsafe_state_root.chmod(0o777)

    with workspace_transaction_lock(
        trusted_state_root,
        workspace,
        error_code="BLOCK_TEST",
    ):
        assert workspace_transaction_lock_held(trusted_state_root, workspace)
        assert not workspace_transaction_lock_held(unsafe_state_root, workspace)
        with pytest.raises(RuntimeError, match="state root is unsafe"):
            with workspace_transaction_lock(
                unsafe_state_root,
                workspace,
                error_code="BLOCK_TEST",
            ):
                raise AssertionError("unsafe state root lock must not be acquired")

    assert not (unsafe_state_root / "workspace-promotion-locks").exists()


def test_private_resume_archive_rejects_ancestor_symlink_without_escape(tmp_path):
    from dataclasses import replace

    from factor_factory.console.container_agent_adapter import (
        _prepare_private_resume_archive_path,
    )

    task = replace(
        _resume_task(),
        attempt_id=f"resume_{'c' * 32}",
        prior_output_archive_id=(
            "jobs/job_1234567890/resume-history/"
            f"resume_{'c' * 32}/prior_memo.json"
        ),
    )
    state_root = tmp_path / "state"
    job_root = state_root / "jobs" / task.job_id
    job_root.mkdir(parents=True, mode=0o700)
    state_root.chmod(0o700)
    (state_root / "jobs").chmod(0o700)
    job_root.chmod(0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (job_root / "resume-history").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="archive parent is unsafe"):
        _prepare_private_resume_archive_path(state_root, task)

    assert not (outside / task.attempt_id).exists()


def test_private_resume_archive_rejects_world_accessible_state_root(tmp_path):
    from dataclasses import replace

    from factor_factory.console.container_agent_adapter import (
        _prepare_private_resume_archive_path,
    )

    task = replace(
        _resume_task(),
        attempt_id=f"resume_{'f' * 32}",
        prior_output_archive_id=(
            "jobs/job_1234567890/resume-history/"
            f"resume_{'f' * 32}/prior_memo.json"
        ),
    )
    state_root = tmp_path / "world-accessible-state"
    state_root.mkdir(mode=0o707)
    state_root.chmod(0o707)

    with pytest.raises(RuntimeError, match="archive state root is unsafe"):
        _prepare_private_resume_archive_path(state_root, task)

    assert not (state_root / "jobs").exists()


def test_private_resume_archive_openat_rejects_state_root_symlink_swap(
    tmp_path,
    monkeypatch,
):
    from dataclasses import replace

    from factor_factory.console.container_agent_adapter import (
        _prepare_private_resume_archive_path,
    )

    task = replace(
        _resume_task(),
        attempt_id=f"resume_{'1' * 32}",
        prior_output_archive_id=(
            "jobs/job_1234567890/resume-history/"
            f"resume_{'1' * 32}/prior_memo.json"
        ),
    )
    state_root = tmp_path / "state-root-race"
    state_root.mkdir(mode=0o750)
    state_root.chmod(0o750)
    outside = tmp_path / "outside-state-root-race"
    outside.mkdir(mode=0o750)
    outside.chmod(0o750)
    backup = tmp_path / "state-root-race-backup"
    original_open = os.open
    swapped = False

    def swap_state_root_before_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if str(path) == state_root.name and dir_fd is not None and not swapped:
            state_root.rename(backup)
            state_root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", swap_state_root_before_open)
        with pytest.raises(RuntimeError, match="archive state root is unsafe"):
            _prepare_private_resume_archive_path(state_root, task)

    assert swapped is True
    assert not (outside / "jobs").exists()
    state_root.unlink()
    backup.rename(state_root)


def test_private_resume_archive_closes_descriptors_when_fstat_fails(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.container_agent_adapter as adapter_module
    from dataclasses import replace

    task = replace(
        _resume_task(),
        attempt_id=f"resume_{'2' * 32}",
        prior_output_archive_id=(
            "jobs/job_1234567890/resume-history/"
            f"resume_{'2' * 32}/prior_memo.json"
        ),
    )
    original_open_absolute = adapter_module._open_absolute_directory_fd
    original_open = os.open
    original_fstat = os.fstat

    state_root = tmp_path / "state-root-fstat"
    state_root.mkdir(mode=0o750)
    state_root.chmod(0o750)
    captured_root_descriptor: list[int] = []

    def capture_root_descriptor(path, *, error_code):
        descriptor = original_open_absolute(path, error_code=error_code)
        captured_root_descriptor.append(descriptor)
        return descriptor

    def fail_root_fstat(descriptor):
        if captured_root_descriptor and descriptor == captured_root_descriptor[-1]:
            raise OSError("injected root fstat failure")
        return original_fstat(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            adapter_module,
            "_open_absolute_directory_fd",
            capture_root_descriptor,
        )
        patcher.setattr(os, "fstat", fail_root_fstat)
        with pytest.raises(RuntimeError, match="archive state root is unsafe"):
            adapter_module._prepare_private_resume_archive_path(state_root, task)
    assert len(captured_root_descriptor) == 1
    with pytest.raises(OSError):
        original_fstat(captured_root_descriptor[0])

    child_state_root = tmp_path / "child-fstat"
    jobs_root = child_state_root / "jobs"
    jobs_root.mkdir(parents=True, mode=0o700)
    child_state_root.chmod(0o700)
    jobs_root.chmod(0o700)
    captured_child_descriptor: list[int] = []

    def capture_jobs_open(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if str(path) == "jobs" and dir_fd is not None:
            captured_child_descriptor.append(descriptor)
        return descriptor

    def fail_child_fstat(descriptor):
        if captured_child_descriptor and descriptor == captured_child_descriptor[-1]:
            raise OSError("injected child fstat failure")
        return original_fstat(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", capture_jobs_open)
        patcher.setattr(os, "fstat", fail_child_fstat)
        with pytest.raises(RuntimeError, match="archive parent is unsafe"):
            adapter_module._prepare_private_resume_archive_path(
                child_state_root,
                task,
            )
    assert len(captured_child_descriptor) == 1
    with pytest.raises(OSError):
        original_fstat(captured_child_descriptor[0])


def test_workspace_openat_chain_rejects_parent_symlink_swap(tmp_path, monkeypatch):
    import factor_factory.console.container_agent_adapter as adapter_module

    workspace = tmp_path / "workspace"
    safe = workspace / "safe"
    safe.mkdir(parents=True)
    (safe / "input.json").write_text('{"source": "workspace"}\n', encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "input.json").write_text('{"source": "outside"}\n', encoding="utf-8")
    original_open = os.open
    backup = workspace / "safe-backup"
    swapped = False

    def swap_before_parent_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if str(path) == "safe" and dir_fd is not None and not swapped:
            safe.rename(backup)
            safe.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", swap_before_parent_open)
        with pytest.raises((OSError, RuntimeError)):
            adapter_module._read_stable_workspace_file_bytes(
                workspace,
                "safe/input.json",
                max_bytes=1024,
            )
    assert swapped is True
    assert (outside / "input.json").read_text(encoding="utf-8") == (
        '{"source": "outside"}\n'
    )
    safe.unlink()
    backup.rename(safe)

    swapped = False
    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", swap_before_parent_open)
        with pytest.raises((OSError, RuntimeError)):
            adapter_module._write_text_atomic_new(
                workspace / "safe/output.json",
                '{"status": "created"}\n',
                root=workspace,
            )
    assert swapped is True
    assert not (outside / "output.json").exists()


def test_resume_view_binds_phase_inputs_to_parent_tree_baseline(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.container_agent_adapter as adapter_module
    from dataclasses import replace

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    task = replace(
        _resume_task(),
        read_only_inputs=(
            "identity/web_main_agent_mechanism_facts.json",
            "identity/web_main_agent_mechanism_answer_form.json",
        ),
        protected_inputs=(),
    )
    _write_resume_prompt_inputs(workspace, task=task)
    _write_resume_facts(
        workspace,
        task,
        {
            "formula_facts": {
                "formula": "divide(minus(close, open), pre_close)",
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            }
        },
    )
    (workspace / "identity/web_agent_resume.md").write_text(
        "facts only\n",
        encoding="utf-8",
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n",
        encoding="utf-8",
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    original_tree_snapshot = adapter_module._workspace_tree_snapshot
    facts_path = workspace / task.facts_relative

    def mutate_before_tree_snapshot(*args, **kwargs):
        facts_path.write_text('{"changed": true}\n', encoding="utf-8")
        return original_tree_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        adapter_module,
        "_workspace_tree_snapshot",
        mutate_before_tree_snapshot,
    )
    with pytest.raises(RuntimeError, match="phase input and parent tree baseline diverged"):
        adapter._prepare_resume_workspace_view(
            runtime_root=runtime_root,
            workspace=workspace,
            resume_task=task,
        )


def test_agent_readiness_requires_healthy_dedicated_profile(tmp_path, monkeypatch):
    import subprocess

    from factor_factory.console.agent_adapter import OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "health" in command:
            return subprocess.CompletedProcess(command, 0, stdout='{"ok": true, "plugins": {"errors": []}}', stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="Config valid\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_profile="factorforge-console-test",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        auth_disabled=True,
    )
    assert OpenClawResearchAgentAdapter(config).validate_ready() == "factorforge-console-test"
    assert all(command[:3] == ["openclaw", "--profile", "factorforge-console-test"] for command in calls)


def test_agent_readiness_blocks_plugin_errors(tmp_path, monkeypatch):
    import subprocess

    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE, OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    def fake_run(command, **kwargs):
        output = '{"ok": true, "plugins": {"errors": [{"id": "bad"}]}}' if "health" in command else "ok"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        auth_disabled=True,
    )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        OpenClawResearchAgentAdapter(config).validate_ready()


def test_agent_readiness_rejects_oauth_seed(tmp_path, monkeypatch):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE, OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite", profile_type="oauth"),
        auth_disabled=True,
    )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        OpenClawResearchAgentAdapter(config).validate_ready()


def test_auth_seed_rejects_symlink_broad_permissions_and_multiple_profiles(tmp_path):
    from factor_factory.console.agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        validate_auth_database,
    )

    broad = _auth_seed(tmp_path / "broad.sqlite")
    broad.chmod(0o644)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(broad, provider="deepseek", label="seed")

    target = _auth_seed(tmp_path / "target.sqlite")
    link = tmp_path / "linked.sqlite"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(link, provider="deepseek", label="seed")

    multiple = _auth_seed(tmp_path / "multiple.sqlite")
    with sqlite3.connect(multiple) as connection:
        row = connection.execute(
            "SELECT store_json FROM auth_profile_store WHERE store_key = 'primary'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["profiles"]["deepseek:second"] = {
            "provider": "deepseek",
            "type": "api_key",
            "key": "second-test-api-key",
        }
        connection.execute(
            "UPDATE auth_profile_store SET store_json = ? WHERE store_key = 'primary'",
            (json.dumps(payload),),
        )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(multiple, provider="deepseek", label="seed")


def test_console_config_rejects_unknown_thinking_level(tmp_path):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError, match="thinking level"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            openclaw_thinking="invented",
            auth_disabled=True,
        )

    with pytest.raises(ValueError, match="thinking level"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            openclaw_resume_thinking="invented",
            auth_disabled=True,
        )


@pytest.mark.parametrize(
    ("invite", "cookie"),
    [
        ("replace-via-secrets-manager", "strong-cookie-secret-2026-with-entropy-value"),
        ("short", "strong-cookie-secret-2026-with-entropy-value"),
        ("strong-invite-secret-2026", "replace-with-random-secret"),
        ("same-secret-value-2026-with-enough-length", "same-secret-value-2026-with-enough-length"),
    ],
)
def test_console_config_rejects_weak_or_placeholder_production_secrets(
    tmp_path,
    invite,
    cookie,
):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            invite_password=invite,
            cookie_secret=cookie,
        )


def test_console_config_rejects_non_pilot_aws_account(tmp_path):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError, match="pinned Pilot account"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            invite_password="strong-invite-secret-2026",
            cookie_secret="strong-cookie-secret-2026-with-entropy-value",
            data_catalogs=(tmp_path / "catalog.json",),
            catalog_receipt=tmp_path / "catalog.receipt.json",
            data_api_pythonpath=tmp_path / "data-api",
            data_api_commit="d" * 40,
            aws_readonly_role_name="console-test-role",
            aws_host_role_name="console-test-host-role",
            aws_account_id="123456789012",
            agent_container_image=f"sha256:{'a' * 64}",
        )


def test_console_config_rejects_multiple_production_catalogs(tmp_path):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError, match="exactly one active catalog"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            invite_password="strong-invite-secret-2026",
            cookie_secret="strong-cookie-secret-2026-with-entropy-value",
            data_catalogs=(tmp_path / "catalog-a.json", tmp_path / "catalog-b.json"),
            catalog_receipt=tmp_path / "catalog.receipt.json",
            data_api_pythonpath=tmp_path / "data-api",
            data_api_commit="d" * 40,
            aws_readonly_role_name="console-test-role",
            aws_host_role_name="console-test-host-role",
            aws_account_id="525164180577",
            agent_container_image=f"sha256:{'a' * 64}",
        )


def test_container_agent_uses_read_only_engine_and_one_writable_workspace(tmp_path, monkeypatch):
    import subprocess
    import factor_factory.console.container_agent_adapter as adapter_module

    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_FAILED
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import ContainerizedOpenClawResearchAgentAdapter
    from factor_factory.console.models import ResearchJob

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    protected_task_files = (
        workspace / "manifest.json",
        workspace / "identity" / "web_research_request.json",
        workspace / "identity" / "data_catalog_summary.json",
        workspace / "identity" / "factor_knowledge_summary.json",
        workspace / "identity" / "web_research_authoring_contract.json",
        workspace / "identity" / "web_research_runtime.md",
        workspace / "identity" / "web_agent_task.md",
        workspace / "reports" / "user_hypothesis.md",
    )
    for protected in protected_task_files:
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text("{}\n" if protected.suffix == ".json" else "fixture\n", encoding="utf-8")
    catalog_root = tmp_path / "data-runtime"
    catalog = catalog_root / "catalogs" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")
    data_api = tmp_path / "data-api"
    data_api_package = data_api / "factor_factory" / "data_api"
    data_api_package.mkdir(parents=True)
    (data_api_package / "__init__.py").write_text("\n", encoding="utf-8")
    broker_client_token = "broker-client-token-for-container-test"
    broker_client_token_file = tmp_path / "broker-client-token"
    broker_client_token_file.write_text(broker_client_token, encoding="utf-8")
    broker_client_token_file.chmod(0o600)
    broker_scan_root = tmp_path / "broker-scan"
    broker_scan_root.mkdir(mode=0o770)
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_catalogs=(catalog,),
        data_api_pythonpath=data_api,
        aws_host_role_name="console-test-host-role",
        openclaw_auth_seed_db=_auth_seed(
            tmp_path / "seed.sqlite",
            key=broker_client_token,
        ),
        model_broker_client_token_file=broker_client_token_file,
        model_broker_secret_scan_root=broker_scan_root,
        openclaw_profile_template=(
            Path(__file__).resolve().parents[1] / "deploy" / "factorforge-console" / "openclaw.json.example"
        ),
        container_runtime="docker-test",
        agent_container_image="factorforge-agent:test",
        auth_disabled=True,
    )
    job = ResearchJob(
        job_id="job_123abc4567",
        factor_id="FACTOR",
        research_id="research",
        report_id="report",
        request=_request(),
    )
    calls: list[list[str]] = []
    broker_readiness_registry_seen = False
    agent_stdout = json.dumps(
        {
            "payloads": [{"text": "Authoring complete."}],
            "meta": {
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                },
                "finalAssistantVisibleText": "Authoring complete.",
                "livenessState": "working",
            },
        }
    )

    def fake_run(command, **kwargs):
        nonlocal broker_readiness_registry_seen
        calls.append(command)
        if "network" in command and "inspect" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Name": config.container_network,
                            "Internal": False,
                            "EnableIPv6": False,
                            "IPAM": {"Config": [{"Subnet": config.container_network_subnet}]},
                        }
                    ]
                ),
                stderr="",
            )
        if "ps" in command and "-aq" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "agents" in command and "add" in command:
            profile = (
                config.state_root
                / "jobs"
                / job.job_id
                / "container-agent"
                / "home"
                / ".openclaw-factorforge-console"
                / "openclaw.json"
            )
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload.setdefault("agents", {})["list"] = [
                {"id": "main"},
                {
                    "id": "factorforge-web-123abc4567",
                    "workspace": str(source.resolve()),
                    "agentDir": str(
                        (
                            config.state_root
                            / "jobs"
                            / job.job_id
                            / "container-agent"
                            / "agent"
                        ).resolve()
                    ),
                    "model": "deepseek/deepseek-v4-flash",
                }
            ]
            profile.write_text(json.dumps(payload), encoding="utf-8")
        if f"{config.container_model_broker_url}/healthz" in command:
            active_registry = broker_scan_root / "active.registry"
            assert active_registry.is_file()
            active_name = active_registry.read_text(encoding="utf-8").strip()
            readiness_registry = broker_scan_root / active_name
            assert active_name == f"{config.installation_id}.readiness.secrets"
            assert broker_client_token in readiness_registry.read_text(encoding="utf-8")
            broker_readiness_registry_seen = True
        if "--message-file" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=agent_stdout,
                stderr="embedded run agent end: isError=false\n",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    git_view = config.state_root / "jobs" / job.job_id / "container-agent" / "engine.git"
    git_view.mkdir(parents=True)
    monkeypatch.setattr(adapter, "_prepare_git_view", lambda **_: git_view)
    assert adapter.validate_ready() == "container:factorforge-agent:test"
    assert broker_readiness_registry_seen
    assert not (broker_scan_root / "active.registry").exists()
    assert not (broker_scan_root / f"{config.installation_id}.readiness.secrets").exists()
    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("agent authoring must not request an AWS lease")
        ),
    )
    result = adapter.run(job, worktree=source, workspace=workspace, resume=False)
    assert result.returncode == 0
    assert adapter.denied_secret_values(job.job_id) == (broker_client_token,)
    assert adapter.credential_material_state(job.job_id) == "not_issued"
    probe_commands = [
        command
        for command in calls
        if len(command) > 1 and command[1] == "run" and "python3" in command
    ]
    assert len(probe_commands) == 9
    egress_probes = [command for command in probe_commands if "--dns" in command]
    assert len(egress_probes) == 8
    assert any("https://example.com" in command for command in egress_probes)
    assert any("169.254.169.254" in " ".join(command) for command in egress_probes)
    assert any("factorforge-console-egress-probe.example.com" in command for command in egress_probes)
    assert all(command[command.index("--dns") + 1] == "127.0.0.1" for command in egress_probes)
    marker_root = config.state_root / "credential-states"
    boundary_probes = [
        command for command in probe_commands if str(marker_root) in command
    ]
    assert len(boundary_probes) == 1
    boundary_probe = boundary_probes[0]
    assert boundary_probe[boundary_probe.index("--network") + 1] == "none"
    assert "--read-only" in boundary_probe
    assert boundary_probe[-1] == str(marker_root)
    run_commands = [
        command
        for command in calls
        if len(command) > 1 and command[1] == "run" and config.openclaw_binary in command
    ]
    assert len(run_commands) == 2
    research_command = run_commands[-1]
    assert "--read-only" in research_command
    assert "--local" in research_command
    assert research_command[research_command.index("--network") + 1] == config.container_network
    assert research_command[research_command.index("--dns") + 1] == "127.0.0.1"
    assert f"HTTP_PROXY={config.container_proxy_url}" not in research_command
    assert f"HTTPS_PROXY={config.container_proxy_url}" not in research_command
    assert f"http_proxy={config.container_proxy_url}" not in research_command
    assert f"https_proxy={config.container_proxy_url}" not in research_command
    assert f"FACTORFORGE_S3_PROXY_URL={config.container_proxy_url}" not in research_command
    assert f"NO_PROXY={urlsplit(config.container_model_broker_url).hostname}" in research_command
    assert "AWS_EC2_METADATA_DISABLED=true" in research_command
    assert "PYTHONDONTWRITEBYTECODE=1" in research_command
    assert f"type=bind,src={source.resolve()},dst={source.resolve()},readonly" in research_command
    assert f"type=bind,src={workspace.resolve()},dst={workspace.resolve()}" in research_command
    for protected in protected_task_files:
        assert f"type=bind,src={protected.resolve()},dst={protected.resolve()},readonly" in research_command
    assert f"type=bind,src={catalog_root.resolve()},dst={catalog_root.resolve()},readonly" not in research_command
    assert (
        f"type=bind,src={data_api_package.resolve()},dst={data_api_package.resolve()},readonly"
        not in research_command
    )
    assert f"FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT={data_api_package.resolve()}" not in research_command
    assert f"FACTORFORGE_DATA_CATALOG={catalog.resolve()}" not in research_command
    assert "--env-file" not in research_command
    python_path = next(item for item in research_command if item.startswith("PYTHONPATH="))
    assert str(data_api.resolve()) not in python_path
    assert python_path == f"PYTHONPATH={source.resolve()}"
    assert f"type=bind,src={git_view.resolve()},dst={git_view.resolve()},readonly" in research_command
    assert f"GIT_DIR={git_view.resolve()}" in research_command
    assert f"GIT_WORK_TREE={source.resolve()}" in research_command
    assert "GIT_OPTIONAL_LOCKS=0" in research_command
    profile_path = (
        config.state_root
        / "jobs"
        / job.job_id
        / "container-agent"
        / "home"
        / ".openclaw-factorforge-console"
        / "openclaw.json"
    )
    assert f"type=bind,src={profile_path},dst={profile_path},readonly" in research_command
    tmpfs_index = research_command.index("--tmpfs")
    assert research_command[tmpfs_index + 1].startswith("/tmp:rw,nosuid,nodev,size=")
    assert str(marker_root) not in " ".join(research_command)

    agent_stdout = json.dumps(
        {
            "payloads": [],
            "meta": {
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                },
                "replayInvalid": True,
                "livenessState": "abandoned",
                "error": {
                    "kind": "incomplete_turn",
                    "message": "Agent couldn't generate a response.",
                },
            },
        }
    )
    incomplete = adapter.run(
        job,
        worktree=source,
        workspace=workspace,
        resume=False,
    )
    assert incomplete.returncode == 1
    incomplete_receipt = json.loads(
        Path(incomplete.result_path).read_text(encoding="utf-8")
    )
    assert incomplete_receipt["error_code"] == BLOCK_AGENT_RUNTIME_FAILED
    assert "terminal liveness state is not usable" in incomplete_receipt["stderr_tail"]
    adapter.clear_denied_secrets(job.job_id)


@pytest.mark.parametrize("fail_second_import", [False, True])
def test_container_council_ingress_isolates_routes_before_host_import(
    tmp_path,
    monkeypatch,
    fail_second_import,
):
    import subprocess
    import factor_factory.console.container_agent_adapter as adapter_module

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )
    from factor_factory.console.council_ingress import CouncilIngressTask
    from factor_factory.console.models import ResearchJob

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    token = "broker-client-token-for-council-ingress-test"
    token_file = tmp_path / "broker-client-token"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o600)
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite", key=token),
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=tmp_path / "broker-scan",
        openclaw_profile_template=(
            Path(__file__).resolve().parents[1]
            / "deploy"
            / "factorforge-console"
            / "openclaw.json.example"
        ),
        container_runtime="docker-test",
        agent_container_image="factorforge-agent:test",
        auth_disabled=True,
    )
    tasks = tuple(
        CouncilIngressTask(
            task_id=f"route_{index}",
            agent_role=f"role_{index}",
            expected_agent_identifier=f"independent_agent_{index}",
            task_packet_path=f"council/task_{index}.json",
            task_packet_sha256=f"hash-{index}",
            expected_result_path=f"council/results/result_{index}.json",
        )
        for index in (1, 2)
    )
    for task in tasks:
        packet = workspace / task.task_packet_path
        packet.parent.mkdir(parents=True, exist_ok=True)
        packet.write_text(
            json.dumps({"task_id": task.task_id}) + "\n",
            encoding="utf-8",
        )
    job = ResearchJob(
        job_id="job_council1234",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        request=_request(),
        base_commit="a" * 40,
    )
    trusted_engine_commit = "b" * 40
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit=trusted_engine_commit,
    )
    git_view = config.state_root / "jobs" / job.job_id / "container-agent" / "engine.git"
    git_view.mkdir(parents=True)
    trusted_engine_root = tmp_path / "trusted-engine-root"
    trusted_engine_root.mkdir()
    monkeypatch.setattr(adapter, "_prepare_git_view", lambda **_: git_view)
    monkeypatch.setattr(
        adapter,
        "_prepare_engine_worktree_view",
        lambda **_: trusted_engine_root,
    )
    monkeypatch.setattr(
        adapter,
        "_load_verified_council_validator",
        lambda **_: (lambda *_args, **_kwargs: []),
    )
    engine_validation_roots: list[Path] = []

    def validate_engine_worktree_view(**kwargs):
        engine_validation_roots.append(kwargs["engine_root"])

    monkeypatch.setattr(
        adapter,
        "_validate_engine_worktree_view",
        validate_engine_worktree_view,
    )
    monkeypatch.setattr(adapter, "_initialize_credential_material_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter, "credential_material_state", lambda _job_id: "not_issued")
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (None, (token,), None),
    )
    monkeypatch.setattr(adapter, "_cleanup_aws_environment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter, "_run_runtime", lambda *_args, **_kwargs: "{}")
    monkeypatch.setattr(adapter, "_validate_agent_binding", lambda *_args, **_kwargs: None)
    validator_worktrees: list[Path] = []

    def validate_private_council_result(**kwargs):
        validator_worktrees.append(kwargs["worktree"])
        return []

    monkeypatch.setattr(
        adapter_module,
        "_validate_private_council_result",
        validate_private_council_result,
    )
    original_write_text_atomic = adapter_module.write_text_atomic
    staged_write_count = 0

    def write_text_with_injected_failure(path, text, **kwargs):
        nonlocal staged_write_count
        if ".console-stage-" in path.parent.name:
            staged_write_count += 1
            if fail_second_import and staged_write_count == 2:
                raise OSError("injected second Council result write failure")
        return original_write_text_atomic(path, text, **kwargs)

    monkeypatch.setattr(
        adapter_module,
        "write_text_atomic",
        write_text_with_injected_failure,
    )
    research_commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        research_commands.append(command)
        prompt_path = Path(command[command.index("--message-file") + 1])
        prompt = prompt_path.read_text(encoding="utf-8")
        private_output = Path(
            prompt.split("Write exactly one JSON result and no other workspace file:\n", 1)[1]
            .splitlines()[0]
        )
        task = tasks[len(research_commands) - 1]
        private_output.write_text(
            json.dumps(
                {
                    "report_id": job.report_id,
                    "task_id": task.task_id,
                    "agent_role": task.agent_role,
                    "agent_identifier": task.expected_agent_identifier,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    if fail_second_import:
        with pytest.raises(
            OSError,
            match="injected second Council result write failure",
        ):
            adapter.run_council_ingress(
                job,
                worktree=source,
                workspace=workspace,
                tasks=tasks,
            )
        result_root = workspace / Path(tasks[0].expected_result_path).parent
        assert not result_root.exists()
        assert not list(
            result_root.parent.glob(f".{result_root.name}.console-stage-*")
        )
        assert not any(
            (workspace / task.expected_result_path).exists() for task in tasks
        )
        return

    result = adapter.run_council_ingress(
        job,
        worktree=source,
        workspace=workspace,
        tasks=tasks,
    )

    assert result.returncode == 0
    assert len(research_commands) == 2
    view_sources = []
    for index, command in enumerate(research_commands):
        worktree_mount = next(
            item
            for item in command
            if item.startswith("type=bind,src=")
            and f",dst={source.resolve()},readonly" in item
        )
        worktree_source = Path(
            worktree_mount.split("src=", 1)[1].split(",dst=", 1)[0]
        )
        assert worktree_source != source.resolve()
        assert not (worktree_source / "skills").exists()
        assert "GIT_DIR=" not in command
        assert not any(
            item.startswith(("HTTP_PROXY=", "HTTPS_PROXY=", "http_proxy=", "https_proxy="))
            for item in command
        )
        workspace_mount = next(
            item
            for item in command
            if item.startswith("type=bind,src=")
            and f",dst={workspace.resolve()},readonly" in item
        )
        assert f"src={workspace.resolve()}," not in workspace_mount
        source_path = Path(
            workspace_mount.split("src=", 1)[1].split(",dst=", 1)[0]
        )
        view_sources.append(source_path)
        visible_packets = sorted(source_path.rglob("task_*.json"))
        assert len(visible_packets) == 1
        assert visible_packets[0].name == f"task_{index + 1}.json"
    assert view_sources[0] != view_sources[1]
    assert all((workspace / task.expected_result_path).is_file() for task in tasks)
    assert (workspace / "identity" / "web_agent_resume.md").is_file()
    assert Path(result.result_path).is_relative_to(config.state_root)
    assert not Path(result.result_path).is_relative_to(workspace)
    assert validator_worktrees == [trusted_engine_root, trusted_engine_root]
    assert engine_validation_roots == [trusted_engine_root] * 4
    receipt = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert receipt["research_base_commit"] == job.base_commit
    assert receipt["engine_commit"] == trusted_engine_commit


def test_container_agent_git_view_is_shallow_exact_and_reusable(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import ContainerizedOpenClawResearchAgentAdapter

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "console@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Console Test"], cwd=source, check=True)
    (source / "engine.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "engine"], cwd=source, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_root = config.state_root / "jobs" / "job_git" / "container-agent"
    runtime_root.mkdir(parents=True)

    first = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source.resolve(),
        base_commit=commit,
    )
    second = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source.resolve(),
        base_commit=commit,
    )
    assert first == second
    assert subprocess.run(
        ["git", f"--git-dir={first}", "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip() == commit
    assert (first / "shallow").is_file()


def test_container_git_view_disables_and_rejects_replace_refs(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=source,
        check=True,
    )
    (source / "engine.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "old engine"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    old_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    (source / "engine.py").write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "trusted engine"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    trusted_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    trusted_tree = subprocess.run(
        ["git", "rev-parse", f"{trusted_commit}^{{tree}}"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    old_tree = subprocess.run(
        ["git", "rev-parse", f"{old_commit}^{{tree}}"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert trusted_tree != old_tree

    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_root = config.state_root / "jobs/job_replace/container-agent"
    runtime_root.mkdir(parents=True)
    git_dir = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source,
        base_commit=trusted_commit,
    )
    subprocess.run(
        [
            "git",
            f"--git-dir={git_dir}",
            "fetch",
            "--depth=1",
            source.as_uri(),
            old_commit,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            f"--git-dir={git_dir}",
            "replace",
            trusted_commit,
            old_commit,
        ],
        check=True,
    )
    direct_tree = subprocess.run(
        ["git", f"--git-dir={git_dir}", "rev-parse", f"{trusted_commit}^{{tree}}"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    protected_tree = adapter._run_host_git(
        [
            "git",
            f"--git-dir={git_dir}",
            "rev-parse",
            f"{trusted_commit}^{{tree}}",
        ],
        timeout=30,
        label="replace regression probe",
    ).strip()
    assert direct_tree == old_tree
    assert protected_tree == trusted_tree
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        adapter._validate_git_view(
            git_dir=git_dir,
            worktree=source,
            base_commit=trusted_commit,
        )


def test_trusted_git_uses_only_exact_command_scoped_safe_directory(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "foreign-owned-checkout"
    source.mkdir()
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=source,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            auth_disabled=True,
        )
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="trusted\n", stderr="")

    monkeypatch.setenv("GIT_REPLACE_REF_BASE", "refs/evil/")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/tmp/untrusted-git-config")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert adapter._run_host_git(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        timeout=30,
        label="safe directory regression probe",
    ) == "trusted\n"
    command = captured["command"]
    process_env = captured["env"]
    assert command[:5] == [
        "git",
        "--no-replace-objects",
        "--no-pager",
        "-c",
        f"safe.directory={source.resolve()}",
    ]
    assert "GIT_REPLACE_REF_BASE" not in process_env
    assert process_env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert process_env["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_data_api_git_validation_ignores_executable_local_config(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    package = checkout / "factor_factory/data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (checkout / ".gitattributes").write_text(
        "payload.txt filter=local_exec\n",
        encoding="utf-8",
    )
    payload = checkout / "payload.txt"
    payload.write_text("payload\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-m", "data api"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    marker = tmp_path / "local-config-executed"
    executable = tmp_path / "local-config-command.sh"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf 'executed\\n' >> '{marker}'\n"
        "cat\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    subprocess.run(
        ["git", "config", "core.fsmonitor", str(executable)],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "filter.local_exec.clean", str(executable)],
        cwd=checkout,
        check=True,
    )

    subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    assert marker.is_file()
    marker.unlink()
    payload.write_text("payload\n", encoding="utf-8")

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            data_api_pythonpath=checkout,
            data_api_commit=commit,
            auth_disabled=True,
        )
    )
    assert adapter._data_api_package_root() == package.resolve()
    assert not marker.exists()


def test_data_api_checkout_rejects_ignored_package_files(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    package = checkout / "factor_factory/data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (checkout / ".gitignore").write_text(
        "factor_factory/data_api/ignored_exec.py\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-m", "data api"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    ignored = package / "ignored_exec.py"
    ignored.write_text("raise RuntimeError('must not load')\n", encoding="utf-8")
    ignored.chmod(0o700)

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            data_api_pythonpath=checkout,
            data_api_commit=commit,
            auth_disabled=True,
        )
    )
    with pytest.raises(RuntimeError, match="not the pinned clean commit"):
        adapter._data_api_package_root()


def test_data_api_checkout_rejects_gitlinks(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    checkout.mkdir()
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=checkout,
        check=True,
    )
    empty_tree = subprocess.run(
        ["git", "mktree"],
        cwd=checkout,
        input="",
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    nested_commit = subprocess.run(
        ["git", "commit-tree", empty_tree, "-m", "nested"],
        cwd=checkout,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{nested_commit},factor_factory",
        ],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "gitlink data api"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    package = checkout / "factor_factory/data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            data_api_pythonpath=checkout,
            data_api_commit=commit,
            auth_disabled=True,
        )
    )
    with pytest.raises(RuntimeError, match="Data API checkout cannot be verified"):
        adapter._data_api_package_root()


@pytest.mark.parametrize("symlink_relative", ["factor_factory", "factor_factory/data_api"])
def test_data_api_checkout_rejects_package_path_symlinks(tmp_path, symlink_relative):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    package = checkout / "factor_factory/data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-m", "data api"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    symlink_path = checkout / symlink_relative
    moved_path = checkout / ".git" / f"moved-{symlink_relative.replace('/', '-')}"
    symlink_path.rename(moved_path)
    symlink_path.symlink_to(moved_path, target_is_directory=True)

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            data_api_pythonpath=checkout,
            data_api_commit=commit,
            auth_disabled=True,
        )
    )
    with pytest.raises(RuntimeError, match="Data API package root is invalid"):
        adapter._data_api_package_root()


def test_data_api_private_git_views_are_prebounded_and_retained(tmp_path, monkeypatch):
    import subprocess
    import factor_factory.console.container_agent_adapter as adapter_module

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    package = checkout / "factor_factory/data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 0\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=checkout,
        check=True,
    )
    commits: list[str] = []
    for version in range(3):
        (package / "__init__.py").write_text(
            f"VALUE = {version}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"data api {version}"],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        commits.append(
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=checkout,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
        )

    adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            data_api_pythonpath=checkout,
            data_api_commit=commits[-1],
            auth_disabled=True,
        )
    )
    for commit in commits:
        adapter._prepare_data_api_git_view(
            checkout=checkout.resolve(),
            expected_commit=commit,
        )
    checkout_view_root = next(
        (tmp_path / "state" / "data-api-git-views").iterdir()
    )
    retained = tuple(checkout_view_root.glob("*.git"))
    assert len(retained) == adapter_module.DATA_API_GIT_VIEW_RETENTION
    assert {path.stem for path in retained} == set(commits[-2:])

    interrupted_state = tmp_path / "interrupted-state"
    interrupted_adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=interrupted_state,
            worktree_root=tmp_path / "interrupted-runs",
            data_api_pythonpath=checkout,
            data_api_commit=commits[-1],
            auth_disabled=True,
        )
    )
    checkout_identity = hashlib.sha256(
        str(checkout.resolve()).encode("utf-8")
    ).hexdigest()
    interrupted_view_root = (
        interrupted_state / "data-api-git-views" / checkout_identity
    )
    interrupted_view_root.mkdir(parents=True, mode=0o700)
    interrupted_view_root.chmod(0o700)
    interrupted = interrupted_view_root / f".{commits[-1]}-{'a' * 32}.tmp"
    interrupted.mkdir(mode=0o700)
    (interrupted / "partial-object").write_bytes(b"partial")
    interrupted_adapter._prepare_data_api_git_view(
        checkout=checkout.resolve(),
        expected_commit=commits[-1],
    )
    assert not interrupted.exists()

    second_state = tmp_path / "bounded-state"
    bounded_adapter = ContainerizedOpenClawResearchAgentAdapter(
        ConsoleConfig(
            source_repo=checkout,
            state_root=second_state,
            worktree_root=tmp_path / "bounded-runs",
            data_api_pythonpath=checkout,
            data_api_commit=commits[-1],
            auth_disabled=True,
        )
    )
    monkeypatch.setattr(adapter_module, "DATA_API_GIT_OBJECT_MAX_BYTES", 1)
    with pytest.raises(RuntimeError, match="object source is too large"):
        bounded_adapter._prepare_data_api_git_view(
            checkout=checkout.resolve(),
            expected_commit=commits[-1],
        )


def test_container_resume_engine_identity_separates_research_and_framework_commits(
    tmp_path,
):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        ContainerizedOpenClawResearchAgentAdapter,
    )
    from factor_factory.console.models import ResearchJob

    source = tmp_path / "source"
    research_worktree = tmp_path / "research-worktree"
    source.mkdir()
    research_worktree.mkdir()
    research_commit = "a" * 40
    engine_commit = "b" * 40
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit=engine_commit,
    )
    job = ResearchJob(
        job_id="job_engine_identity",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        request=_request(),
        base_commit=research_commit,
    )

    assert adapter._engine_identity(
        job=job,
        worktree=research_worktree,
        resume=False,
    ) == (research_worktree, research_commit)
    assert adapter._engine_identity(
        job=job,
        worktree=research_worktree,
        resume=True,
    ) == (source.resolve(), engine_commit)

    production_config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "production-state",
        worktree_root=tmp_path / "production-runs",
        invite_password="invite-value-123456789",
        cookie_secret="cookie-value-that-is-distinct-and-long-enough",
        agent_container_image=f"sha256:{'c' * 64}",
    )
    unpinned = ContainerizedOpenClawResearchAgentAdapter(production_config)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        unpinned._engine_identity(
            job=job,
            worktree=research_worktree,
            resume=True,
        )


def test_container_resume_engine_worktree_is_exact_and_rejects_pollution(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "console@example.invalid"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Console Test"],
        cwd=source,
        check=True,
    )
    (source / ".gitignore").write_text("factor_research/**\n", encoding="utf-8")
    (source / "engine.py").write_text("ENGINE_VERSION = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "engine.py"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "old engine"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    old_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    (source / "engine.py").write_text("ENGINE_VERSION = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "current engine"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    engine_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert engine_commit != old_commit

    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit=engine_commit,
    )
    runtime_root = config.state_root / "jobs/job_engine/container-agent-phases/resume_test"
    runtime_root.mkdir(parents=True)
    git_dir = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source,
        base_commit=engine_commit,
    )
    workspace_relative = Path("factor_research/FACTOR/research")
    engine_root = adapter._prepare_engine_worktree_view(
        runtime_root=runtime_root,
        git_dir=git_dir,
        engine_commit=engine_commit,
        workspace_relative=workspace_relative,
    )

    assert (engine_root / "engine.py").read_text(encoding="utf-8") == (
        "ENGINE_VERSION = 2\n"
    )
    assert list((engine_root / workspace_relative).iterdir()) == []
    assert subprocess.run(
        ["git", f"--git-dir={git_dir}", "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip() == engine_commit
    assert engine_root.stat().st_mode & 0o222 == 0

    engine_file = engine_root / "engine.py"
    engine_file.chmod(0o600)
    engine_file.write_text("ENGINE_VERSION = 999\n", encoding="utf-8")
    engine_file.chmod(0o400)
    subprocess.run(
        ["git", "update-index", "--assume-unchanged", "engine.py"],
        env={
            **os.environ,
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(engine_root),
        },
        check=True,
    )
    with pytest.raises(RuntimeError, match="file content changed"):
        adapter._prepare_engine_worktree_view(
            runtime_root=runtime_root,
            git_dir=git_dir,
            engine_commit=engine_commit,
            workspace_relative=workspace_relative,
        )
    engine_file.chmod(0o600)
    engine_file.write_text("ENGINE_VERSION = 2\n", encoding="utf-8")
    engine_file.chmod(0o400)
    adapter._prepare_engine_worktree_view(
        runtime_root=runtime_root,
        git_dir=git_dir,
        engine_commit=engine_commit,
        workspace_relative=workspace_relative,
    )

    factor_research_root = engine_root / "factor_research"
    factor_research_root.chmod(0o700)
    ignored_injection = factor_research_root / "OTHER/ignored-injection.py"
    ignored_injection.parent.mkdir(parents=True)
    ignored_injection.write_text(
        "raise RuntimeError('must not execute')\n",
        encoding="utf-8",
    )
    ignored_injection.chmod(0o400)
    ignored_injection.parent.chmod(0o500)
    factor_research_root.chmod(0o500)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        adapter._prepare_engine_worktree_view(
            runtime_root=runtime_root,
            git_dir=git_dir,
            engine_commit=engine_commit,
            workspace_relative=workspace_relative,
        )


def test_trusted_validator_callables_execute_verified_blob_bytes(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit=commit,
    )
    runtime_root = config.state_root / "jobs/job_validator/container-agent"
    runtime_root.mkdir(parents=True)
    git_dir = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source,
        base_commit=commit,
    )
    workspace_relative = Path("_test_factor_research/FACTOR/research")
    engine_root = adapter._prepare_engine_worktree_view(
        runtime_root=runtime_root,
        git_dir=git_dir,
        engine_commit=commit,
        workspace_relative=workspace_relative,
    )
    mechanism_validator = adapter._load_verified_main_agent_validator(
        engine_root=engine_root,
        git_dir=git_dir,
        engine_commit=commit,
    )
    council_validator = adapter._load_verified_council_validator(
        engine_root=engine_root,
        git_dir=git_dir,
        engine_commit=commit,
        workspace=engine_root / workspace_relative,
    )
    mechanism_failures = mechanism_validator({}, {})
    council_failures = council_validator(
        {},
        expected_task={},
        expected_report_id="REPORT",
    )
    assert mechanism_failures
    assert council_failures

    mechanism_path = (
        engine_root / "factor_factory/mechanism_math/main_agent_memo.py"
    )
    mechanism_path.chmod(0o600)
    mechanism_path.write_text(
        "def validate_main_agent_mechanism_memo(*_args, **_kwargs):\n"
        "    return []\n",
        encoding="utf-8",
    )
    mechanism_path.chmod(0o400)
    council_path = (
        engine_root
        / "skills/factor-forge-step6/scripts/validate_agentic_council_result.py"
    )
    council_path.chmod(0o600)
    council_path.write_text(
        "def validate_agentic_result(*_args, **_kwargs):\n"
        "    return []\n",
        encoding="utf-8",
    )
    council_path.chmod(0o500)

    assert mechanism_validator({}, {}) == mechanism_failures
    assert council_validator(
        {},
        expected_task={},
        expected_report_id="REPORT",
    ) == council_failures
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        adapter._validate_engine_worktree_view(
            engine_root=engine_root,
            git_dir=git_dir,
            engine_commit=commit,
            workspace_relative=workspace_relative,
        )


def test_container_rejects_invalid_trusted_engine_commit(tmp_path):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    source = tmp_path / "source"
    source.mkdir()
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    sha256_commit = "d" * 64
    assert ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit=sha256_commit,
    ).trusted_engine_commit == sha256_commit
    with pytest.raises(ValueError, match="exact Git object ID"):
        ContainerizedOpenClawResearchAgentAdapter(
            config,
            trusted_engine_commit="main",
        )


def test_data_api_checkout_must_match_pinned_clean_commit(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    checkout = tmp_path / "data-api"
    package = checkout / "factor_factory" / "data_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "console@example.invalid"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.name", "Console Test"], cwd=checkout, check=True)
    subprocess.run(["git", "add", "factor_factory/data_api/__init__.py"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-m", "data api"], cwd=checkout, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_api_pythonpath=checkout,
        data_api_commit=commit,
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    assert adapter._data_api_package_root() == package.resolve()

    (checkout / "dirty.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not the pinned clean commit"):
        adapter._data_api_package_root()


def test_container_profile_policy_rejects_extra_tools_and_model_endpoint():
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE
    from factor_factory.console.container_agent_adapter import _validate_profile_policy

    template = Path(__file__).resolve().parents[1] / "deploy" / "factorforge-console" / "openclaw.json.example"
    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["tools"]["allow"].append("browser")
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["models"]["providers"]["deepseek"]["baseUrl"] = "https://127.0.0.1"
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    for key, value in (
        ("host", "auto"),
        ("mode", "ask"),
        ("strictInlineEval", True),
        ("security", "full"),
        ("ask", "off"),
    ):
        payload = json.loads(template.read_text(encoding="utf-8"))
        payload["tools"]["exec"][key] = value
        with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
            _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["agents"]["defaults"]["compaction"]["midTurnPrecheck"] = {"enabled": False}
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["agents"]["defaults"]["compaction"]["reserveTokens"] = 24_000
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["models"]["providers"]["deepseek"]["models"][0]["maxTokens"] = 128000
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["models"]["providers"]["deepseek"]["models"][0]["id"] = "deepseek-reasoner"
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["agents"]["defaults"]["model"]["primary"] = "deepseek/deepseek-reasoner"
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["agents"]["defaults"]["models"]["deepseek/deepseek-v4-flash"]["params"][
        "maxTokens"
    ] = 384000
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)


def test_aws_credential_lease_file_stays_outside_container_runtime(tmp_path, monkeypatch):
    import factor_factory.console.container_agent_adapter as adapter_module
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
        _AwsCredentialLease,
    )

    scan_root = tmp_path / "broker-scan"
    scan_root.mkdir(mode=0o770)
    broker_client_token = "broker-client-token-for-lease-test"
    broker_client_token_file = tmp_path / "broker-client-token"
    broker_client_token_file.write_text(broker_client_token, encoding="utf-8")
    broker_client_token_file.chmod(0o600)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        model_broker_client_token_file=broker_client_token_file,
        model_broker_secret_scan_root=scan_root,
        auth_disabled=True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda _role, _host_role, _account: _AwsCredentialLease(
            access_key="ASIATESTACCESSKEY0000",
            secret_key="temporary-secret-for-test",
            token="temporary-session-token-for-test",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            method="iam-role",
            caller_arn="arn:aws:sts::123456789012:assumed-role/test-role/session",
        ),
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    job_id = "job_1234567890"
    assert adapter.credential_material_state(job_id) == "unknown"
    adapter._initialize_credential_material_state(job_id, resume=False)
    assert adapter.credential_material_state(job_id) == "not_issued"
    adapter._initialize_credential_material_state(job_id, resume=True)
    assert adapter.credential_material_state(job_id) == "not_issued"
    lease_path, values, scan_path = adapter._prepare_aws_environment(
        job_id,
        allow_missing_history=True,
    )
    assert adapter.credential_material_state(job_id) == "may_have_been_issued"
    assert adapter._credential_material_marker_path(job_id) == (
        config.state_root / "credential-states" / f"{job_id}.marker"
    )
    assert lease_path == config.state_root / "credential-leases" / f"{job_id}.env"
    assert scan_path == scan_root / f"{config.installation_id}.{job_id}.secrets"
    assert (scan_root / "active.registry").read_text(encoding="utf-8").strip() == scan_path.name
    assert config.state_root / "jobs" not in lease_path.parents
    assert lease_path.stat().st_mode & 0o077 == 0
    assert scan_path.stat().st_mode & 0o007 == 0
    assert broker_client_token in values
    assert broker_client_token in scan_path.read_text(encoding="utf-8")
    assert "temporary-session-token-for-test" in values
    assert "temporary-session-token-for-test" in scan_path.read_text(encoding="utf-8")
    adapter._cleanup_aws_environment(lease_path, None)
    assert not lease_path.exists()
    assert scan_path.exists()
    host_env, host_denied_values = adapter.prepare_host_data_environment(job_id)
    assert set(host_env) == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_CREDENTIAL_EXPIRATION",
    }
    assert host_env["AWS_SESSION_TOKEN"] == "temporary-session-token-for-test"
    assert "temporary-session-token-for-test" in host_denied_values
    assert not lease_path.exists()
    assert scan_path.exists()
    adapter.deactivate_denied_secrets(job_id)
    assert adapter.credential_material_state(job_id) == "may_have_been_issued"
    assert scan_path.exists()
    assert not (scan_root / "active.registry").exists()
    assert adapter.denied_secret_values(job_id) == values
    adapter.clear_denied_secrets(job_id)
    assert adapter.credential_material_state(job_id) == "unknown"
    assert not scan_path.exists()
    assert not (scan_root / "active.registry").exists()


def test_initial_sts_failure_does_not_consume_credential_issuance_state(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.container_agent_adapter as adapter_module
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
        _AwsCredentialLease,
    )

    token_file = tmp_path / "broker-client-token"
    token_file.write_text("broker-client-token-for-sts-retry-test", encoding="utf-8")
    token_file.chmod(0o600)
    scan_root = tmp_path / "broker-scan"
    scan_root.mkdir(mode=0o770)
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}\n", encoding="utf-8")
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_catalogs=(catalog,),
        catalog_receipt=tmp_path / "catalog-receipt.json",
        data_api_pythonpath=tmp_path / "data-api",
        data_api_commit="a" * 40,
        invite_password="pilot-access-8f7c2a1e6d4b",
        cookie_secret="session-signing-4c9e8b2f7a1d6c3e5f0b9a8d",
        agent_container_image=f"sha256:{'b' * 64}",
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=scan_root,
        aws_readonly_role_name="factorforge-console-read-role",
        aws_host_role_name="factorforge-console-host-role",
        aws_account_id="525164180577",
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    job_id = "job_abcdef1234"
    adapter._initialize_credential_material_state(job_id, resume=False)

    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("STS unavailable")),
    )
    with pytest.raises(RuntimeError, match="STS unavailable"):
        adapter._prepare_aws_environment(job_id, allow_missing_history=True)

    registry = scan_root / f"{config.installation_id}.{job_id}.secrets"
    assert adapter.credential_material_state(job_id) == "not_issued"
    assert not registry.exists()
    assert not (scan_root / "active.registry").exists()

    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda *_args: _AwsCredentialLease(
            access_key="RETRYACCESSKEYFORTEST",
            secret_key="retry-secret-for-test",
            token="retry-session-token-for-test",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            method="assume-role",
            caller_arn=(
                "arn:aws:sts::525164180577:assumed-role/"
                "factorforge-console-read-role/session"
            ),
        ),
    )
    lease_path, _values, registry_path = adapter._prepare_aws_environment(
        job_id,
        allow_missing_history=True,
    )
    assert adapter.credential_material_state(job_id) == "may_have_been_issued"
    assert lease_path is not None and lease_path.is_file()
    assert registry_path == registry and registry.is_file()
    adapter._cleanup_aws_environment(lease_path, None)
    adapter.clear_denied_secrets(job_id)


def test_crash_resume_retains_and_merges_prior_denied_secret_values(tmp_path, monkeypatch):
    import factor_factory.console.container_agent_adapter as adapter_module
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
        _AwsCredentialLease,
    )

    token_file = tmp_path / "broker-client-token"
    token_file.write_text("broker-client-token-for-resume-test", encoding="utf-8")
    token_file.chmod(0o600)
    scan_root = tmp_path / "broker-scan"
    scan_root.mkdir(mode=0o770)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=scan_root,
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    job_id = "job_abcdef1234"
    registry = scan_root / f"{config.installation_id}.{job_id}.secrets"
    registry.write_text("prior-session-secret-for-resume-test\n", encoding="utf-8")
    registry.chmod(0o640)
    active_registry = scan_root / "active.registry"
    active_registry.write_text(f"{registry.name}\n", encoding="utf-8")
    active_registry.chmod(0o640)
    readiness = scan_root / f"{config.installation_id}.readiness.secrets"
    readiness.write_text("stale-readiness-secret-for-test\n", encoding="utf-8")
    readiness.chmod(0o640)
    lease_root = config.state_root / "credential-leases"
    lease_root.mkdir(parents=True, mode=0o700)
    stale_lease = lease_root / f"{job_id}.env"
    stale_lease.write_text("expired\n", encoding="utf-8")
    stale_lease.chmod(0o600)

    adapter._reconcile_orphan_credentials()

    assert registry.exists()
    assert active_registry.read_text(encoding="utf-8").strip() == registry.name
    assert not readiness.exists()
    assert not stale_lease.exists()
    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda _role, _host_role, _account: _AwsCredentialLease(
            access_key="ASIARESUMEACCESS00000",
            secret_key="new-secret-for-resume-test",
            token="new-session-token-for-resume-test",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            method="assume-role",
            caller_arn="arn:aws:sts::525164180577:assumed-role/test-role/session",
        ),
    )

    adapter._initialize_credential_material_state(job_id, resume=True)
    assert adapter.credential_material_state(job_id) == "may_have_been_issued"
    lease_path, values, scan_path = adapter._prepare_aws_environment(job_id)

    assert scan_path == registry
    assert "prior-session-secret-for-resume-test" in values
    assert "new-session-token-for-resume-test" in values
    assert "prior-session-secret-for-resume-test" in registry.read_text(encoding="utf-8")
    assert "new-session-token-for-resume-test" in registry.read_text(encoding="utf-8")
    adapter._cleanup_aws_environment(lease_path, None)
    adapter.clear_denied_secrets(job_id)


def test_legacy_resume_without_denied_secret_history_blocks_before_new_lease(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.container_agent_adapter as adapter_module
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        ContainerizedOpenClawResearchAgentAdapter,
    )

    token_file = tmp_path / "broker-client-token"
    token_file.write_text("broker-client-token-for-legacy-test", encoding="utf-8")
    token_file.chmod(0o600)
    scan_root = tmp_path / "broker-scan"
    scan_root.mkdir(mode=0o770)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        model_broker_client_token_file=token_file,
        model_broker_secret_scan_root=scan_root,
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    job_id = "job_0123456789"
    legacy_runtime = config.state_root / "jobs" / job_id / "container-agent"
    legacy_runtime.mkdir(parents=True)
    (legacy_runtime / "credential-material-issued.marker").write_text(
        "factorforge_console_credential_material_may_have_been_issued_v1\n",
        encoding="utf-8",
    )
    lease_called = False

    def fail_if_lease_requested(*_args):
        nonlocal lease_called
        lease_called = True
        raise AssertionError("a replacement lease must not be issued")

    monkeypatch.setattr(adapter_module, "_load_aws_credentials", fail_if_lease_requested)
    adapter._initialize_credential_material_state(job_id, resume=True)

    assert adapter.credential_material_state(job_id) == "may_have_been_issued"
    with pytest.raises(RuntimeError, match="prior denied-secret registry is missing") as exc:
        adapter._prepare_aws_environment(job_id)
    assert BLOCK_AGENT_RUNTIME_UNAVAILABLE in str(exc.value)
    assert lease_called is False


def test_unstoppable_stale_container_uses_orphaned_writer_blocker(
    tmp_path,
    monkeypatch,
):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_ORPHANED_WRITER
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    monkeypatch.setattr(
        adapter,
        "_run_runtime",
        lambda *_args, **_kwargs: "stale-container-id\n",
    )
    monkeypatch.setattr(adapter, "_stop_container", lambda _name: False)

    with pytest.raises(RuntimeError, match=BLOCK_AGENT_ORPHANED_WRITER):
        adapter._reconcile_stale_containers()


def test_aws_credentials_are_assumed_from_distinct_host_role(monkeypatch):
    from factor_factory.console.container_agent_adapter import _load_aws_credentials

    expected_role = "factorforge-console-pilot-data-read-role"

    class SourceCredentials:
        method = "iam-role"

    class FakeSts:
        def __init__(self, *, assumed: bool = False):
            self.assumed = assumed

        def get_caller_identity(self):
            role = expected_role if self.assumed else "factorforge-console-pilot-host-role"
            return {
                "Account": "123456789012",
                "Arn": f"arn:aws:sts::123456789012:assumed-role/{role}/session",
            }

        def assume_role(self, **kwargs):
            assert kwargs["RoleArn"] == f"arn:aws:iam::123456789012:role/{expected_role}"
            assert kwargs["DurationSeconds"] == 3600
            return {
                "Credentials": {
                    "AccessKeyId": "ASIATEMPORARYKEY0000",
                    "SecretAccessKey": "temporary-secret-for-assume-role-test",
                    "SessionToken": "temporary-session-token-for-assume-role-test",
                    "Expiration": datetime.now(timezone.utc) + timedelta(minutes=59),
                }
            }

    class FakeSession:
        def get_credentials(self):
            return SourceCredentials()

        def create_client(self, service, **kwargs):
            assert service == "sts"
            return FakeSts(assumed=bool(kwargs.get("aws_session_token")))

    session_module = types.ModuleType("botocore.session")
    session_module.get_session = lambda: FakeSession()
    package = types.ModuleType("botocore")
    package.session = session_module
    monkeypatch.setitem(sys.modules, "botocore", package)
    monkeypatch.setitem(sys.modules, "botocore.session", session_module)

    lease = _load_aws_credentials(
        expected_role,
        "factorforge-console-pilot-host-role",
        "123456789012",
    )
    assert lease.method == "assume-role"
    assert lease.caller_arn.endswith(f"assumed-role/{expected_role}/session")
    assert lease.token == "temporary-session-token-for-assume-role-test"
    with pytest.raises(RuntimeError, match="scoped AWS credentials are unavailable"):
        _load_aws_credentials(
            expected_role,
            "factorforge-console-pilot-host-role",
            "999999999999",
        )


def test_secret_redaction(monkeypatch):
    import base64

    from factor_factory.console.agent_adapter import redact_secrets

    monkeypatch.setenv("TEST_API_KEY", "super-secret-provider-key")
    encoded_secret = "~~~~~~~~?"
    standard_unpadded = base64.b64encode(encoded_secret.encode("utf-8")).decode("ascii").rstrip("=")
    unicode_escaped = "".join(f"\\u{ord(character):04x}" for character in encoded_secret)
    raw = json.dumps(
        {
            "api_key": "super-secret-provider-key",
            "authorization": "Bearer sk-example-secret-123456789",
            "aws_access_key_id": "AKIAABCDEFGHIJKLMNOP",
            "aws_secret_access_key": "aws-secret-material-for-test",
            "encoded": standard_unpadded,
            "escaped": unicode_escaped,
        }
    )
    redacted = redact_secrets(
        raw,
        extra_values=("aws-secret-material-for-test", encoded_secret),
    )
    assert "super-secret-provider-key" not in redacted
    assert "sk-example-secret-123456789" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "aws-secret-material-for-test" not in redacted
    assert standard_unpadded not in redacted
    assert unicode_escaped not in redacted
    assert "[REDACTED]" in redacted
