from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest


def _source_authority() -> dict[str, object]:
    return {
        "kind": "specific_source_evidence",
        "reference": "source-report.pdf#page=7",
        "rationale": "The cited definitions freeze the implementation choices.",
        "source_excerpt": "TS_MAX_SUM uses the maximum contiguous k-period sum.",
        "implementation_choices_not_performance_selected": True,
    }


def _source_authority_form_fields() -> dict[str, str]:
    return {
        "semantic_authority_kind": "specific_source_evidence",
        "semantic_authority_reference": "source-report.pdf#page=7",
        "semantic_authority_rationale": (
            "The cited definitions freeze the implementation choices."
        ),
        "semantic_source_excerpt": (
            "TS_MAX_SUM uses the maximum contiguous k-period sum."
        ),
        "semantic_choices_not_performance_selected": "true",
    }


class _FakeService:
    def __init__(self, store):
        self.store = store

    def submit(self, request, *, initial_messages=None):
        return self.store.create_job(request, initial_messages=initial_messages)

    def request_resume(self, job_id):
        return self.store.request_resume(job_id)

    def cancel_queued(self, job_id):
        return self.store.cancel_queued(job_id)


@pytest.fixture
def research_console(tmp_path):
    from factor_factory.console.auth import InviteAuth
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.static_app import (
        ResearchConsoleApplication,
        build_research_console_server,
    )
    from factor_factory.console.store import ResearchJobStore

    catalog = tmp_path / "data-runtime" / "catalogs" / "data_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog_data = json.dumps(
        {"schema_version": "test_v1", "datasets": [{"dataset_id": "clean_daily_bar"}]}
    ).encode("utf-8")
    catalog.write_bytes(catalog_data)
    receipt = catalog.with_name("data_catalog.receipt.json")
    refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt.write_text(
        json.dumps(
            {
                "version": "factorforge_console_active_catalog_receipt_v1",
                "bucket": "yufan-data-lake",
                "key": "factorforge/data/catalog/data_catalog.json",
                "etag": "a" * 32,
                "version_id": "",
                "role_name": "console-test-role",
                "catalog_sha256": hashlib.sha256(catalog_data).hexdigest(),
                "catalog_bytes": len(catalog_data),
                "dataset_count": 1,
                "schema_version": "test_v1",
                "source_last_modified_utc": refreshed_at,
                "fetched_at_utc": refreshed_at,
            }
        ),
        encoding="utf-8",
    )
    data_api = tmp_path / "data-api"
    data_api.mkdir()
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "worktrees",
        invite_password="friend-invite-2026-test",
        cookie_secret="test-cookie-signing-secret-2026-at-least-32-bytes",
        data_catalogs=(catalog,),
        catalog_receipt=receipt,
        data_api_pythonpath=data_api,
        data_api_commit="d" * 40,
        aws_readonly_role_name="console-test-role",
        aws_host_role_name="console-test-host-role",
        aws_account_id="525164180577",
        agent_container_image=f"sha256:{'a' * 64}",
    )
    store = ResearchJobStore(config.state_root)
    service = _FakeService(store)
    app = ResearchConsoleApplication(
        config=config,
        store=store,
        service=service,
        auth=InviteAuth(
            "friend-invite-2026-test",
            "test-cookie-signing-secret-2026-at-least-32-bytes",
        ),
    )
    server = build_research_console_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", app
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_catalog_health_validation_is_single_flight_cached(research_console, monkeypatch):
    import factor_factory.console.catalog_health as catalog_health

    _base_url, application = research_console
    calls = 0
    original = catalog_health._evaluate_catalogs

    def counted(config, *, now):
        nonlocal calls
        calls += 1
        return original(config, now=now)

    monkeypatch.setattr(catalog_health, "_evaluate_catalogs", counted)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(
                lambda _item: catalog_health.catalogs_healthy(application.config),
                range(64),
            )
        )

    assert all(results)
    assert calls == 1


def test_catalog_admission_projection_is_hash_bound_and_does_not_claim_dataset_qa(
    research_console,
):
    from factor_factory.console.catalog_health import catalog_admission_projection

    _base_url, application = research_console
    admission = catalog_admission_projection(application.config)

    assert admission["verdict"] == "PASS"
    assert admission["catalog_sha256"] == hashlib.sha256(
        application.config.data_catalogs[0].read_bytes()
    ).hexdigest()
    assert admission["catalog_receipt_sha256"] == hashlib.sha256(
        application.config.catalog_receipt.read_bytes()
    ).hexdigest()
    assert admission["formal_dataset_qa_implied"] is False


def test_catalog_admission_projection_bypasses_cache_for_freshness(research_console):
    from factor_factory.console.catalog_health import (
        catalog_admission_projection,
        catalogs_healthy,
    )

    _base_url, application = research_console
    assert catalogs_healthy(application.config) is True
    stale_time = datetime.now(timezone.utc) + timedelta(hours=25)

    with pytest.raises(RuntimeError, match="DATA_CATALOG_UNAVAILABLE"):
        catalog_admission_projection(application.config, now=stale_time)


def _login_opener(base_url: str):
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    payload = urlencode({"password": "friend-invite-2026-test"}).encode("utf-8")
    response = opener.open(Request(f"{base_url}/login", data=payload, method="POST"), timeout=3)
    assert response.status == 200
    html = response.read().decode("utf-8")
    assert "因子研究任务" in html
    return opener, html


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_invite_login_and_security_headers(research_console):
    base_url, _app = research_console
    response = urlopen(f"{base_url}/healthz", timeout=3)
    assert response.status == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert b'"ledger":true' in response.read()

    response = urlopen(f"{base_url}/favicon.ico", timeout=3)
    assert response.status == 204

    response = urlopen(f"{base_url}/", timeout=3)
    assert response.url.endswith("/login")
    assert "访问口令" in response.read().decode("utf-8")

    with pytest.raises(HTTPError) as failure:
        urlopen(
            Request(
                f"{base_url}/login",
                data=urlencode({"password": "wrong"}).encode("utf-8"),
                method="POST",
            ),
            timeout=3,
        )
    assert failure.value.code == 401

    opener, html = _login_opener(base_url)
    assert "Content-Security-Policy" in opener.open(f"{base_url}/", timeout=3).headers
    assert "服务器路径" not in html
    assert 'name="source_url"' not in html


def test_production_health_fails_when_trusted_calendar_is_missing(
    research_console,
    monkeypatch,
):
    import factor_factory.console.static_app as static_app

    base_url, app = research_console
    app.engine_commit = "a" * 40
    monkeypatch.setattr(static_app, "trusted_calendar_healthy", lambda: False)

    with pytest.raises(HTTPError) as failure:
        urlopen(f"{base_url}/healthz", timeout=3)
    assert failure.value.code == 503
    assert b'"trusted_calendar":false' in failure.value.read()


def test_auth_disabled_health_does_not_require_production_calendar(
    research_console,
    monkeypatch,
):
    import factor_factory.console.static_app as static_app

    base_url, app = research_console
    app.config = replace(app.config, auth_disabled=True)
    app.config.source_repo.mkdir(parents=True, exist_ok=True)
    app.engine_commit = "a" * 40
    monkeypatch.setattr(static_app, "trusted_calendar_healthy", lambda: False)

    response = urlopen(f"{base_url}/healthz", timeout=3)
    assert response.status == 200
    assert b'"trusted_calendar":true' in response.read()


def test_rate_limiter_trusts_forwarded_address_only_from_loopback_proxy():
    from factor_factory.console.static_app import _rate_limit_address

    proxied = SimpleNamespace(
        client_address=("127.0.0.1", 1234),
        headers={"X-Forwarded-For": "203.0.113.9, 127.0.0.1"},
    )
    direct = SimpleNamespace(
        client_address=("198.51.100.7", 1234),
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert _rate_limit_address(proxied) == "127.0.0.1"
    assert _rate_limit_address(direct) == "198.51.100.7"


def test_catalog_health_fails_when_receipt_hash_is_stale(research_console):
    from factor_factory.console.static_app import _catalogs_healthy

    _base_url, app = research_console
    assert _catalogs_healthy(app.config) is True
    app.config.data_catalogs[0].write_text('{"schema_version":"tampered","datasets":[]}', encoding="utf-8")
    assert _catalogs_healthy(app.config) is False


def test_queue_admission_blocks_stale_catalog_before_creating_job(research_console):
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.run_service import ResearchQueueService

    _base_url, app = research_console
    app.config.data_catalogs[0].write_text(
        '{"schema_version":"tampered","datasets":[]}',
        encoding="utf-8",
    )
    service = ResearchQueueService(
        store=app.store,
        runner_health_socket=app.config.state_root / "missing.sock",
        config=app.config,
    )

    with pytest.raises(RuntimeError, match="DATA_CATALOG_UNAVAILABLE"):
        service.submit(ResearchRequest(title="Blocked catalog", hypothesis="test"))
    assert app.store.list_jobs() == []


def test_submit_research_and_api_hide_private_paths(research_console):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "Overnight information diffusion",
            "factor_id_hint": "OVERNIGHT_INFO",
            "hypothesis": "News spreads after dinner and becomes observable at the next open.",
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
            "source_url": "",
        }
    ).encode("utf-8")
    response = opener.open(Request(f"{base_url}/research", data=payload, method="POST"), timeout=3)
    assert response.status == 200
    assert "/research/job_" in response.url
    detail = response.read().decode("utf-8")
    assert "Overnight information diffusion" in detail
    assert "等待分配" in detail

    job = app.store.list_jobs()[0]
    api = opener.open(f"{base_url}/api/research/{job.job_id}", timeout=3).read().decode("utf-8")
    assert "worktree_path" not in api
    assert "workspace_path" not in api
    assert "agent_session_key" not in api


def test_submit_formula_with_chinese_title_and_generated_factor_id(research_console):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    formula = (
        "  "
        "-1 * (NORMALIZE(S_LOG_LP(TS_KURTOSIS(CLOSE,5))"
        "+TS_MAX_SKEW(VOLUME,5,3)-TS_MIN_SKEW(VOLUME,20,3)"
        "+TS_MAX_SUM(CHANGE_PCT,20,5),STANDARDIZE=1))\n"
    )
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "负价量偏度峰度复合因子",
            "factor_id_hint": "",
            "content_kind": "formula",
            "model": "deepseek-v4-flash",
            "hypothesis": formula,
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
            "max_sum_convention": "contiguous_subwindow",
            "zscore_ddof": "0",
            **_source_authority_form_fields(),
        }
    ).encode("utf-8")

    response = opener.open(
        Request(f"{base_url}/research", data=payload, method="POST"),
        timeout=3,
    )

    assert response.status == 200
    assert "/research/job_" in response.url
    detail = response.read().decode("utf-8")
    assert "负价量偏度峰度复合因子" in detail
    assert "公式语义合同" in detail
    assert "无偏 Fisher 超额峰度" in detail
    assert "具体源证据" in detail
    assert "已核实所提交证据中的算子含义" in detail
    assert "未验证外部来源真实性，仅校验提交摘录完整性" in detail
    assert "rolling_excess_kurtosis" in detail
    assert '"contract_version"' not in detail
    job = app.store.list_jobs()[0]
    assert re.fullmatch(r"FACTOR_[A-F0-9]{16}", job.factor_id)
    assert job.request.input_kind == "formula"
    assert job.request.hypothesis == formula.strip()
    messages = app.store.list_messages(job.job_id)
    assert [item.content_kind for item in messages] == ["formula", "formula_contract"]
    contract = json.loads(messages[1].content)
    assert contract["semantic_authority"]["reference"] == "source-report.pdf#page=7"
    assert contract["semantic_authority"]["implementation_choices_not_performance_selected"] is True
    assert contract["implementation_variant_set"]["implemented_variant_count"] == 16
    assert contract["implementation_variant_set"]["exhaustive_source_truth"] is False


def test_submit_partial_source_formula_requires_only_used_ambiguities(
    research_console,
):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "Partial source formula",
            "economic_hypothesis": (
                "Overnight information demand can create a transient opening imbalance."
            ),
            "formula_input": "TS_KURTOSIS(CLOSE,5)+TS_MAX_SKEW(VOLUME,5,3)",
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
            **_source_authority_form_fields(),
        }
    ).encode("utf-8")

    response = opener.open(
        Request(f"{base_url}/research", data=payload, method="POST"),
        timeout=3,
    )

    assert response.status == 200
    job = app.store.list_jobs()[0]
    messages = app.store.list_messages(job.job_id)
    assert [item.content_kind for item in messages] == [
        "hypothesis",
        "formula",
        "formula_contract",
    ]
    contract = json.loads(messages[2].content)
    assert contract["semantic_choices"] == {
        "kurtosis_convention": "excess_unbiased",
        "skew_convention": "inner_window_extrema",
    }
    assert contract["implementation_variant_set"]["implemented_variant_count"] == 4


def test_user_cannot_submit_internal_formula_contract_message(research_console):
    from factor_factory.console.models import ResearchRequest

    base_url, app = research_console
    opener, dashboard = _login_opener(base_url)
    job = app.store.create_job(
        ResearchRequest(title="Message authority", hypothesis="Initial hypothesis")
    )
    payload = urlencode(
        {
            "csrf": _csrf(dashboard),
            "content_kind": "formula_contract",
            "content": '{"contract_version":"forged"}',
            "idempotency_key": "forged-contract",
            "message_action": "save",
        }
    ).encode("utf-8")

    with pytest.raises(HTTPError) as failure:
        opener.open(
            Request(
                f"{base_url}/research/{job.job_id}/messages",
                data=payload,
                method="POST",
            ),
            timeout=3,
        )

    assert failure.value.code == 409
    assert len(app.store.list_messages(job.job_id)) == 1


def test_user_decision_json_cannot_render_as_system_frozen_contract(research_console):
    from factor_factory.console.models import ResearchRequest
    from factor_factory.formula.source_dialects import resolve_source_formula

    base_url, app = research_console
    opener, _dashboard = _login_opener(base_url)
    job = app.store.create_job(
        ResearchRequest(title="Decision authority", hypothesis="Initial hypothesis")
    )
    contract = resolve_source_formula(
        "-1 * NORMALIZE(TS_KURTOSIS(CLOSE,5),STANDARDIZE=1)",
        {
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
            "max_sum_convention": "contiguous_subwindow",
            "zscore_ddof": "0",
        },
        _source_authority(),
    )
    app.store.add_message(
        job.job_id,
        content_kind="decision",
        content=json.dumps(contract, ensure_ascii=False),
        idempotency_key="user-decision-not-initial",
    )

    detail = opener.open(f"{base_url}/research/{job.job_id}", timeout=3).read().decode("utf-8")

    assert "公式语义合同" not in detail
    assert "系统冻结" not in detail
    assert "研究方向" in detail


def test_user_cannot_spoof_legacy_initial_formula_contract_namespace(
    research_console,
):
    from factor_factory.console.models import ResearchRequest
    from factor_factory.formula.source_dialects import resolve_source_formula

    base_url, app = research_console
    opener, dashboard = _login_opener(base_url)
    job = app.store.create_job(
        ResearchRequest(title="Reserved namespace", hypothesis="Initial hypothesis")
    )
    contract = resolve_source_formula(
        "-1 * NORMALIZE(TS_KURTOSIS(CLOSE,5),STANDARDIZE=1)",
        {
            "kurtosis_convention": "pearson_unbiased",
            "skew_convention": "inner_window_extrema",
            "max_sum_convention": "contiguous_subwindow",
            "zscore_ddof": "0",
        },
        _source_authority(),
    )
    payload = urlencode(
        {
            "csrf": _csrf(dashboard),
            "content_kind": "decision",
            "content": json.dumps(contract, ensure_ascii=False),
            "idempotency_key": "initial:user-controlled",
            "message_action": "save",
        }
    ).encode("utf-8")

    with pytest.raises(HTTPError) as failure:
        opener.open(
            Request(
                f"{base_url}/research/{job.job_id}/messages",
                data=payload,
                method="POST",
            ),
            timeout=3,
        )

    assert failure.value.code == 409
    messages = app.store.list_messages(job.job_id)
    assert len(messages) == 1
    assert messages[0].idempotency_key.startswith("initial:")


def test_source_formula_with_raw_enum_choices_but_no_authority_blocks_before_job_creation(
    research_console,
):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    formula = (
        "-1 * (NORMALIZE(S_LOG_LP(TS_KURTOSIS(CLOSE,5))"
        "+TS_MAX_SKEW(VOLUME,5,3)-TS_MIN_SKEW(VOLUME,20,3)"
        "+TS_MAX_SUM(CHANGE_PCT,20,5),STANDARDIZE=1))"
    )
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "语义尚未冻结的公式",
            "formula_input": formula,
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
            "max_sum_convention": "contiguous_subwindow",
            "zscore_ddof": "0",
        }
    ).encode("utf-8")

    with pytest.raises(HTTPError) as failure:
        opener.open(
            Request(f"{base_url}/research", data=payload, method="POST"),
            timeout=3,
        )

    assert failure.value.code == 400
    body = failure.value.read().decode("utf-8")
    assert "源语义权威尚未满足正式合同要求" in body
    assert "请选择具体源证据或显式用户研究覆盖作为语义权威" in body
    assert "确认实现口径未依据回测或绩效结果选择" in body
    assert app.store.list_jobs() == []


def test_source_evidence_mode_requires_actual_excerpt(research_console):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    formula = "-1 * NORMALIZE(TS_KURTOSIS(CLOSE,5),STANDARDIZE=1)"
    authority_fields = _source_authority_form_fields()
    authority_fields["semantic_source_excerpt"] = ""
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "缺少原文证据绑定",
            "formula_input": formula,
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
            "max_sum_convention": "contiguous_subwindow",
            "zscore_ddof": "0",
            **authority_fields,
        }
    ).encode("utf-8")

    with pytest.raises(HTTPError) as failure:
        opener.open(
            Request(f"{base_url}/research", data=payload, method="POST"),
            timeout=3,
        )

    assert failure.value.code == 400
    body = failure.value.read().decode("utf-8")
    assert "具体源证据模式必须填写可定位的原文摘录；哈希不能替代摘录" in body
    assert 'value="source-report.pdf#page=7"' in body
    assert app.store.list_jobs() == []


def test_submit_combines_hypothesis_report_formula_and_code_atomically(research_console):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "多输入机制研究",
            "factor_id_hint": "MULTI_INPUT_MECHANISM",
            "model": "deepseek-v4-flash",
            "economic_hypothesis": "受约束买方在开盘支付即时性成本。",
            "report_input": "研报认为隔夜信息在集合竞价和开盘阶段集中定价。",
            "formula_input": "-(open / pre_close - 1)",
            "code_input": "signal = -(frame.open / frame.pre_close - 1)",
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
        }
    ).encode("utf-8")

    response = opener.open(
        Request(f"{base_url}/research", data=payload, method="POST"),
        timeout=3,
    )

    assert response.status == 200
    job = app.store.list_jobs()[0]
    messages = app.store.list_messages(job.job_id)
    assert [item.sequence_no for item in messages] == [1, 2, 3, 4]
    assert [item.content_kind for item in messages] == [
        "hypothesis",
        "report",
        "formula",
        "code",
    ]
    assert job.request.input_kind == "hypothesis"
    assert job.request.hypothesis == "受约束买方在开盘支付即时性成本。"


def test_invalid_research_form_returns_html_and_preserves_input(research_console):
    from factor_factory.console.models import ResearchRequest

    base_url, app = research_console
    opener, html = _login_opener(base_url)
    active = app.store.create_job(
        ResearchRequest(
            title="Existing active task",
            hypothesis="Keep polling disabled on the invalid form response.",
            factor_id_hint="EXISTING_ACTIVE",
        )
    )
    app.store.claim_next_job()
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "保留这个研究名称",
            "factor_id_hint": "",
            "content_kind": "formula",
            "model": "deepseek-v4-flash",
            "hypothesis": "  A < B\n",
            "universe": "a_share_all",
            "sample_start": "2025-07-11",
            "sample_end": "2016-01-01",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
        }
    ).encode("utf-8")

    with pytest.raises(HTTPError) as failure:
        opener.open(
            Request(f"{base_url}/research", data=payload, method="POST"),
            timeout=3,
        )

    assert failure.value.code == 400
    assert failure.value.headers["Content-Type"] == "text/html; charset=utf-8"
    body = failure.value.read().decode("utf-8")
    assert "提交未成功" in body
    assert "样本开始日期必须早于结束日期" in body
    assert 'value="保留这个研究名称"' in body
    assert ">  A &lt; B\n</textarea>" in body
    assert 'id="formula-input"' in body
    assert "第三方公式语义" in body
    assert 'name="semantic_authority_kind"' in body
    assert 'id="semantic-source-excerpt"' in body
    assert 'id="semantic-override-reason"' in body
    assert 'name="semantic_choices_not_performance_selected"' in body
    assert "location.reload()" not in body
    assert [job.job_id for job in app.store.list_jobs()] == [active.job_id]


def test_explicit_human_decision_pause_hides_generic_resume_action(
    research_console,
):
    from factor_factory.console.models import ResearchRequest

    base_url, app = research_console
    opener, _html = _login_opener(base_url)
    job = app.store.create_job(
        ResearchRequest(title="Council decision", hypothesis="test hypothesis")
    )
    app.store.update_job(
        job.job_id,
        execution_status="REVIEW_REQUIRED",
        protocol_status="PAUSED",
        council_status="PAUSED",
        workspace_path="/private/workspace",
        error_code="FACTORFORGE_CONSOLE_EXPLICIT_HUMAN_DECISION_REQUIRED",
        error_message="Council synthesis requires an explicit decision.",
        result={
            "host_attestation_id": "attestations/test.json",
            "summary": "Council synthesis requires an explicit decision.",
            "next_actions": ["Use the dedicated Council synthesis approval."],
        },
    )

    detail = opener.open(
        f"{base_url}/research/{job.job_id}", timeout=3
    ).read().decode("utf-8")
    assert "Council synthesis requires an explicit decision." in detail
    assert "从现有证据继续" not in detail


def test_csrf_blocks_forged_submission(research_console):
    base_url, _app = research_console
    opener, _html = _login_opener(base_url)
    payload = urlencode(
        {
            "csrf": "forged",
            "title": "Forged",
            "hypothesis": "Should not be queued",
        }
    ).encode("utf-8")
    with pytest.raises(HTTPError) as failure:
        opener.open(Request(f"{base_url}/research", data=payload, method="POST"), timeout=3)
    assert failure.value.code == 403


def test_artifact_endpoint_serves_only_published_official_artifact(research_console, tmp_path):
    base_url, app = research_console
    opener, _html = _login_opener(base_url)
    from factor_factory.console.artifact_service import publish_official_artifacts
    from factor_factory.console.models import ResearchRequest

    job = app.store.create_job(ResearchRequest(title="Artifact factor", hypothesis="test hypothesis"))
    workspace = tmp_path / "factor-workspace"
    image = workspace / "evaluations" / "rank_ic_timeseries.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    internal = workspace / "objects" / "internal_but_safe.json"
    internal.parent.mkdir(parents=True)
    internal.write_text('{"status":"internal"}\n', encoding="utf-8")
    summary = workspace / "reports" / "summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text('{"status":"PASS"}\n', encoding="utf-8")
    publication_id, _ = publish_official_artifacts(
        workspace,
        app.config.state_root / "public" / job.job_id,
        role_artifact_ids={
            "rank_ic_chart": "evaluations/rank_ic_timeseries.png",
            "summary": "reports/summary.json",
        },
        identity={
            "job_id": job.job_id,
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
        },
    )
    app.store.update_job(
        job.job_id,
        workspace_path=str(workspace),
        worktree_path=str(tmp_path / "worktree"),
        result={
            "public_artifact_set_id": publication_id,
            "artifacts": [
                {
                    "artifact_id": "evaluations/rank_ic_timeseries.png",
                    "label": "Rank IC",
                    "kind": "image",
                },
                {
                    "artifact_id": "reports/summary.json",
                    "label": "Summary",
                    "kind": "document",
                },
            ]
        },
    )

    response = opener.open(
        f"{base_url}/artifact/{job.job_id}/evaluations/rank_ic_timeseries.png",
        timeout=3,
    )
    assert response.headers["Content-Type"] == "image/png"
    assert "filename*=UTF-8''rank_ic_timeseries.png" in response.headers["Content-Disposition"]
    assert response.read().startswith(b"\x89PNG")

    summary_url = f"{base_url}/artifact/{job.job_id}/reports/summary.json"
    assert json.loads(opener.open(summary_url, timeout=3).read()) == {"status": "PASS"}
    published_summary = (
        app.config.state_root
        / "public"
        / job.job_id
        / publication_id
        / "reports"
        / "summary.json"
    )
    published_summary.chmod(0o640)
    published_summary.write_text('{"status":"REJECT"}\n', encoding="utf-8")
    with pytest.raises(HTTPError) as failure:
        opener.open(summary_url, timeout=3)
    assert failure.value.code == 404

    with pytest.raises(HTTPError) as failure:
        opener.open(
            f"{base_url}/artifact/{job.job_id}/objects/internal_but_safe.json",
            timeout=3,
        )
    assert failure.value.code == 404

    with pytest.raises(HTTPError) as failure:
        opener.open(f"{base_url}/artifact/{job.job_id}/../outside.json", timeout=3)
    assert failure.value.code == 404


def test_chatbox_persists_messages_and_api_hides_control_events(research_console):
    base_url, app = research_console
    opener, dashboard = _login_opener(base_url)
    csrf = _csrf(dashboard)
    create_payload = urlencode(
        {
            "csrf": csrf,
            "title": "Interactive research",
            "hypothesis": "A payer-specific economic hypothesis.",
            "content_kind": "hypothesis",
            "model": "deepseek-v4-flash",
            "universe": "a_share_all",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "30",
        }
    ).encode("utf-8")
    response = opener.open(
        Request(f"{base_url}/research", data=create_payload, method="POST"),
        timeout=3,
    )
    match = re.search(r"/research/(job_[a-f0-9]{10})", response.url)
    assert match
    job_id = match.group(1)
    detail_html = response.read().decode("utf-8")
    assert "Chatbox" in detail_html
    assert "Research Notebook" in detail_html
    assert "任务记录" not in detail_html

    message_payload = urlencode(
        {
            "csrf": csrf,
            "content_kind": "formula",
            "content": r"E[R_{t+1} | F_t, Z_t]",
            "idempotency_key": "web-test-message-1",
            "message_action": "save",
        }
    ).encode("utf-8")
    opener.open(
        Request(
            f"{base_url}/research/{job_id}/messages",
            data=message_payload,
            method="POST",
        ),
        timeout=3,
    ).read()

    api_payload = json.loads(
        opener.open(f"{base_url}/api/research/{job_id}", timeout=3).read()
    )
    assert [item["content_kind"] for item in api_payload["messages"]] == [
        "hypothesis",
        "formula",
    ]
    assert "events" not in api_payload
    assert app.store.list_events(job_id)
