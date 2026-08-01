from __future__ import annotations

import base64
import re
import threading
from types import SimpleNamespace
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest


class _FakeService:
    def __init__(self, store):
        self.store = store

    def submit(self, request):
        return self.store.create_job(request)

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

    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "worktrees",
        invite_password="friend-invite-2026-test",
        cookie_secret="test-cookie-signing-secret-2026-at-least-32-bytes",
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

    assert _rate_limit_address(proxied) == "203.0.113.9"
    assert _rate_limit_address(direct) == "198.51.100.7"


def test_submit_research_and_api_hide_private_paths(research_console):
    base_url, app = research_console
    opener, html = _login_opener(base_url)
    payload = urlencode(
        {
            "csrf": _csrf(html),
            "title": "Overnight information diffusion",
            "factor_id_hint": "OVERNIGHT_INFO",
            "hypothesis": "News spreads after dinner and becomes observable at the next open.",
            "universe": "a_share_core",
            "sample_start": "2016-01-01",
            "sample_end": "2025-07-11",
            "forward_horizon": "1d",
            "transaction_cost_bps": "10",
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


def test_artifact_endpoint_serves_only_workspace_relative_safe_file(research_console, tmp_path):
    base_url, app = research_console
    opener, _html = _login_opener(base_url)
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
    app.store.update_job(
        job.job_id,
        workspace_path=str(workspace),
        worktree_path=str(tmp_path / "worktree"),
        result={
            "artifacts": [
                {
                    "artifact_id": "evaluations/rank_ic_timeseries.png",
                    "label": "Rank IC",
                    "kind": "image",
                }
            ]
        },
    )

    response = opener.open(
        f"{base_url}/artifact/{job.job_id}/evaluations/rank_ic_timeseries.png",
        timeout=3,
    )
    assert response.headers["Content-Type"] == "image/png"
    assert response.read().startswith(b"\x89PNG")

    with pytest.raises(HTTPError) as failure:
        opener.open(f"{base_url}/artifact/{job.job_id}/../outside.json", timeout=3)
    assert failure.value.code == 404
