from __future__ import annotations

import json
import ipaddress
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urlsplit

from factor_factory.console.artifact_service import (
    ArtifactAccessError,
    read_verified_publication_artifact,
)
from factor_factory.console.auth import InviteAuth
from factor_factory.console.bounded_http import BoundedThreadingHTTPServer
from factor_factory.console.catalog_health import catalogs_healthy
from factor_factory.console.auth import SESSION_MAX_AGE_SECONDS
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.discovery import discover_miner_campaigns
from factor_factory.console.models import (
    PILOT_UNIVERSE,
    ResearchRequest,
    validate_pilot_evaluation_request,
)
from factor_factory.console.readers import read_miner_campaign
from factor_factory.console.run_service import (
    BLOCK_RESUME_TRUST_INVALID,
    ResearchQueueService,
    ResearchRunService,
)
from factor_factory.console.store import ResearchJobStore
from factor_factory.console.task_manifest import create_miner_campaign_task, read_console_tasks
from factor_factory.console.summary import render_dashboard
from factor_factory.console.web_ui import render_dashboard as render_research_dashboard
from factor_factory.console.web_ui import render_job, render_login, render_not_found


_JOB_ID = re.compile(r"job_[a-f0-9]{10}\Z")
_PUBLICATION_ID = re.compile(r"pub_[a-f0-9]{32}\Z")


@dataclass
class _LoginRateLimiter:
    maximum_attempts: int = 8
    window_seconds: int = 300
    attempts: dict[str, list[float]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def allowed(self, address: str) -> bool:
        now = time.monotonic()
        with self.lock:
            recent = [stamp for stamp in self.attempts.get(address, []) if now - stamp < self.window_seconds]
            self.attempts[address] = recent
            return len(recent) < self.maximum_attempts

    def record_failure(self, address: str) -> None:
        with self.lock:
            self.attempts.setdefault(address, []).append(time.monotonic())

    def clear(self, address: str) -> None:
        with self.lock:
            self.attempts.pop(address, None)


@dataclass
class ResearchConsoleApplication:
    config: ConsoleConfig
    store: ResearchJobStore
    service: ResearchRunService | ResearchQueueService
    auth: InviteAuth
    engine_commit: str = ""
    agent_runtime: str = ""
    login_limiter: _LoginRateLimiter = field(default_factory=_LoginRateLimiter)


def build_console_html(roots: Iterable[str | Path]) -> str:
    root_list = [Path(root) for root in roots]
    workspaces = discover_miner_campaigns(root_list)
    summaries = [read_miner_campaign(workspace) for workspace in workspaces]
    tasks = []
    for root in root_list:
        tasks.extend(read_console_tasks(root))
    return render_dashboard(summaries, tasks)


def make_handler(roots: list[Path]) -> type[BaseHTTPRequestHandler]:
    class ConsoleHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/index.html"}:
                self.send_error(404, "Not found")
                return
            html = build_console_html(roots).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self) -> None:
            if self.path != "/tasks/miner":
                self.send_error(404, "Not found")
                return
            if not roots:
                self.send_error(400, "No writable Console root configured")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = self.rfile.read(length).decode("utf-8")
            fields = parse_qs(payload, keep_blank_values=True)
            catalogs = [
                item.strip()
                for value in fields.get("catalogs", [])
                for item in value.replace(",", "\n").splitlines()
                if item.strip()
            ]
            try:
                create_miner_campaign_task(
                    root=roots[0],
                    campaign_id=_field(fields, "campaign_id"),
                    execution_workspace=_field(fields, "execution_workspace"),
                    catalogs=catalogs,
                    screen_window=_field(fields, "screen_window", "2016-01-01..2025-07-11"),
                    universe=_field(fields, "universe", "current_data_api_catalog"),
                )
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return ConsoleHandler


def _field(fields: dict[str, list[str]], name: str, default: str = "") -> str:
    values = fields.get(name)
    if not values:
        return default
    return values[0].strip() or default


def serve_console(roots: list[str | Path], host: str, port: int) -> None:
    server = build_console_server(roots, host, port)
    serve_console_server(server)


def build_console_server(roots: list[str | Path], host: str, port: int) -> ThreadingHTTPServer:
    root_paths = [Path(root) for root in roots]
    return ThreadingHTTPServer((host, port), make_handler(root_paths))


def serve_console_server(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever()
    finally:
        server.server_close()


def build_research_console_server(
    application: ResearchConsoleApplication,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    class ConsoleHTTPServer(BoundedThreadingHTTPServer):
        max_request_threads = 32

    return ConsoleHTTPServer((host, port), make_research_handler(application))


def serve_research_console_server(
    server: ThreadingHTTPServer,
    application: ResearchConsoleApplication,
) -> None:
    application.service.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        application.service.stop()


def make_research_handler(application: ResearchConsoleApplication) -> type[BaseHTTPRequestHandler]:
    class ResearchConsoleHandler(BaseHTTPRequestHandler):
        server_version = "FactorForgeConsole/1"

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                checks = _health_checks(application)
                ready = all(checks.values())
                self._send_json(
                    200 if ready else 503,
                    {
                        "status": "ok" if ready else "unhealthy",
                        "service": "factorforge-console",
                        "checks": checks,
                    },
                    public=True,
                )
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self._security_headers(public=True)
                self.end_headers()
                return
            if path == "/login":
                if self._authenticated():
                    self._redirect("/")
                else:
                    self._send_html(200, render_login(), public=True)
                return
            session = self._require_auth()
            if session is None:
                return
            csrf = application.auth.csrf_token(session)
            if path in {"/", "/index.html"}:
                self._send_html(200, render_research_dashboard(application.store.list_jobs(), csrf))
                return
            if path == "/api/jobs":
                jobs = application.store.list_jobs()
                self._send_json(
                    200,
                    {
                        "jobs": [job.to_dict() for job in jobs],
                        "latest_updated_at_utc": jobs[0].updated_at_utc if jobs else "",
                    },
                )
                return
            job_id = _path_job_id(path, prefix="/research/")
            if job_id:
                job = application.store.get_job(job_id)
                if job is None:
                    self._send_html(404, render_not_found())
                    return
                self._send_html(200, render_job(job, application.store.list_events(job_id), csrf))
                return
            api_job_id = _path_job_id(path, prefix="/api/research/")
            if api_job_id:
                job = application.store.get_job(api_job_id)
                if job is None:
                    self._send_json(404, {"error": "not_found"})
                    return
                payload = job.to_dict()
                payload["events"] = application.store.list_events(api_job_id)
                self._send_json(200, payload)
                return
            if path.startswith("/artifact/"):
                self._serve_artifact(path)
                return
            self._send_html(404, render_not_found())

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/login":
                self._login()
                return
            session = self._require_auth()
            if session is None:
                return
            try:
                fields = self._read_form()
            except ValueError as exc:
                self._send_html(400, render_not_found(str(exc)))
                return
            if not application.auth.verify_csrf(session, _field(fields, "csrf")):
                self._send_json(403, {"error": "csrf_invalid"})
                return
            if path == "/logout":
                application.store.revoke_session(session)
                self.send_response(303)
                self._security_headers(public=True)
                self.send_header("Set-Cookie", application.auth.clear_cookie_header())
                self.send_header("Location", "/login")
                self.end_headers()
                return
            if path == "/research":
                self._create_research(fields)
                return
            action = _research_action(path)
            if action:
                job_id, command = action
                try:
                    if command == "resume":
                        application.service.request_resume(job_id)
                    else:
                        application.service.cancel_queued(job_id)
                except KeyError:
                    self._send_html(404, render_not_found())
                    return
                except ValueError as exc:
                    self._send_json(409, {"error": "invalid_state", "message": str(exc)})
                    return
                except RuntimeError as exc:
                    if str(exc).startswith(BLOCK_RESUME_TRUST_INVALID):
                        self._send_json(
                            409,
                            {
                                "error": "resume_not_safe",
                                "message": "该任务缺少可信续跑证据，请新建隔离研究任务。",
                            },
                        )
                        return
                    self._send_json(503, {"error": "research_runtime_unavailable"})
                    return
                self._redirect(f"/research/{job_id}")
                return
            self._send_json(404, {"error": "not_found"})

        def _login(self) -> None:
            address = _rate_limit_address(self)
            if not application.login_limiter.allowed(address):
                self._send_html(429, render_login("尝试次数过多，请稍后再试。"), public=True)
                return
            try:
                fields = self._read_form()
            except ValueError:
                self._send_html(400, render_login("请求无效。"), public=True)
                return
            if not application.auth.password_matches(_field(fields, "password")):
                application.login_limiter.record_failure(address)
                time.sleep(0.25)
                self._send_html(401, render_login("访问口令不正确。"), public=True)
                return
            application.login_limiter.clear(address)
            token = application.auth.issue_session()
            application.store.register_session(token, max_age_seconds=SESSION_MAX_AGE_SECONDS)
            self.send_response(303)
            self._security_headers(public=True)
            self.send_header("Set-Cookie", application.auth.set_cookie_header(token))
            self.send_header("Location", "/")
            self.end_headers()

        def _create_research(self, fields: dict[str, list[str]]) -> None:
            try:
                request = ResearchRequest(
                    title=_field(fields, "title"),
                    hypothesis=_field(fields, "hypothesis"),
                    factor_id_hint=_field(fields, "factor_id_hint"),
                    universe=_field(fields, "universe", PILOT_UNIVERSE),
                    sample_start=_field(fields, "sample_start", "2016-01-01"),
                    sample_end=_field(fields, "sample_end", "2025-07-11"),
                    forward_horizon=_field(fields, "forward_horizon", "1d"),
                    transaction_cost_bps=float(_field(fields, "transaction_cost_bps", "30")),
                    source_url=_field(fields, "source_url"),
                )
                _validate_request_choices(request)
                job = application.service.submit(request)
            except (ValueError, OverflowError) as exc:
                self._send_json(400, {"error": "invalid_research_request", "message": str(exc)})
                return
            except RuntimeError:
                self._send_json(503, {"error": "research_runtime_unavailable"})
                return
            self._redirect(f"/research/{job.job_id}")

        def _serve_artifact(self, path: str) -> None:
            parts = path.split("/", 3)
            if len(parts) != 4 or not _JOB_ID.fullmatch(parts[2]):
                self._send_json(404, {"error": "not_found"})
                return
            job = application.store.get_job(parts[2])
            if job is None:
                self._send_json(404, {"error": "not_found"})
                return
            artifact_id = unquote(parts[3])
            publication_id = str(job.result.get("public_artifact_set_id") or "")
            allowed_artifacts = {
                str(item.get("artifact_id") or "")
                for item in (job.result.get("artifacts") or [])
                if isinstance(item, dict)
            }
            if not _PUBLICATION_ID.fullmatch(publication_id) or artifact_id not in allowed_artifacts:
                self._send_json(404, {"error": "artifact_not_available"})
                return
            public_root = application.config.state_root / "public" / job.job_id / publication_id
            try:
                description, data = read_verified_publication_artifact(public_root, artifact_id)
            except ArtifactAccessError:
                self._send_json(404, {"error": "artifact_not_available"})
                return
            self.send_response(200)
            self._security_headers()
            self.send_header("Content-Type", description.media_type)
            self.send_header("Content-Length", str(len(data)))
            filename = Path(description.artifact_id).name
            fallback = f"artifact{Path(filename).suffix.lower()}"
            disposition = description.content_disposition
            self.send_header(
                "Content-Disposition",
                f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}',
            )
            self.send_header("Cache-Control", "private, max-age=60")
            self.end_headers()
            self.wfile.write(data)

        def _read_form(self) -> dict[str, list[str]]:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/x-www-form-urlencoded"):
                raise ValueError("only form submissions are accepted")
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid request length") from exc
            if length < 0 or length > application.config.max_request_bytes:
                raise ValueError("request is too large")
            payload = self.rfile.read(length).decode("utf-8", errors="strict")
            return parse_qs(payload, keep_blank_values=True, max_num_fields=40)

        def _authenticated(self) -> bool:
            token = application.auth.session_from_cookie(self.headers.get("Cookie"))
            return self._session_valid(token)

        def _require_auth(self) -> str | None:
            token = application.auth.session_from_cookie(self.headers.get("Cookie"))
            if self._session_valid(token):
                return token
            if self.headers.get("Accept", "").startswith("application/json") or self.path.startswith("/api/"):
                self._send_json(401, {"error": "authentication_required"}, public=True)
            else:
                self._redirect("/login")
            return None

        def _session_valid(self, token: str) -> bool:
            if application.config.auth_disabled:
                return application.auth.verify_session(token)
            return application.auth.verify_session(token) and application.store.session_is_active(token)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self._security_headers()
            self.send_header("Location", location)
            self.end_headers()

        def _send_html(self, status: int, html: str, *, public: bool = False) -> None:
            data = html.encode("utf-8")
            self.send_response(status)
            self._security_headers(public=public)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status: int, payload: dict, *, public: bool = False) -> None:
            data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            self.send_response(status)
            self._security_headers(public=public)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _security_headers(self, *, public: bool = False) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            self.send_header("Cache-Control", "no-store" if not public else "no-cache")

        def log_message(self, format: str, *args: object) -> None:
            return

    return ResearchConsoleHandler


def _path_job_id(path: str, *, prefix: str) -> str:
    if not path.startswith(prefix):
        return ""
    value = path[len(prefix) :]
    return value if _JOB_ID.fullmatch(value) else ""


def _research_action(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/research/(job_[a-f0-9]{10})/(resume|cancel)", path)
    return (match.group(1), match.group(2)) if match else None


def _validate_request_choices(request: ResearchRequest) -> None:
    validate_pilot_evaluation_request(request)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.sample_start):
        raise ValueError("invalid sample_start")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.sample_end):
        raise ValueError("invalid sample_end")
    if request.sample_start >= request.sample_end:
        raise ValueError("sample_start must be before sample_end")


def _health_checks(application: ResearchConsoleApplication) -> dict[str, bool]:
    service_health = getattr(application.service, "healthcheck", None)
    return {
        "ledger": application.store.healthcheck(),
        "worker": bool(service_health()) if callable(service_health) else True,
        "engine": (
            application.config.source_repo.exists()
            if application.engine_commit
            else True
        ),
        "agent_runtime": bool(application.agent_runtime) if application.agent_runtime else True,
        "data_catalogs": catalogs_healthy(application.config),
    }


def _catalogs_healthy(config: ConsoleConfig) -> bool:
    return catalogs_healthy(config)


def _rate_limit_address(handler: BaseHTTPRequestHandler) -> str:
    peer = handler.client_address[0] if handler.client_address else ""
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return "unknown"
    if peer_address.is_loopback:
        forwarded_values = [
            item.strip()
            for item in handler.headers.get("X-Forwarded-For", "").split(",")
            if item.strip()
        ]
        if len(forwarded_values) != 1:
            return peer_address.compressed
        forwarded = forwarded_values[0]
        try:
            forwarded_address = ipaddress.ip_address(forwarded)
        except ValueError:
            return peer_address.compressed
        return forwarded_address.compressed
    return peer_address.compressed
