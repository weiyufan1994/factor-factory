from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import threading
import time
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
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
    USER_MESSAGE_CONTENT_KINDS,
    validate_pilot_evaluation_request,
)
from factor_factory.console.model_broker import DEEPSEEK_V4_FLASH_MODEL
from factor_factory.console.readers import read_miner_campaign
from factor_factory.console.report_upload import (
    BLOCK_PDF_UPLOAD_INVALID,
    ResearchAttachmentUpload,
)
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
from factor_factory.console.web_factor_proof import trusted_calendar_healthy
from factor_factory.formula.parser import parse_formula
from factor_factory.formula.source_dialects import (
    BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
    SourceFormulaDialectError,
    resolve_source_formula_for_host,
)


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


def _raw_field(fields: dict[str, list[str]], name: str, default: str = "") -> str:
    values = fields.get(name)
    if not values:
        return default
    return values[0]


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
        server_version = "FactorForgeConsole/2"

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
                self._send_html(
                    200,
                    render_job(job, application.store.list_messages(job_id), csrf),
                )
                return
            api_job_id = _path_job_id(path, prefix="/api/research/")
            if api_job_id:
                job = application.store.get_job(api_job_id)
                if job is None:
                    self._send_json(404, {"error": "not_found"})
                    return
                payload = job.to_dict()
                payload["messages"] = [
                    message.to_dict()
                    for message in application.store.list_messages(api_job_id)
                ]
                payload["attachments"] = [
                    attachment.to_dict(public=True)
                    for attachment in application.store.list_attachments(api_job_id)
                ]
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
                if path == "/research":
                    fields, attachments = self._read_research_form()
                else:
                    fields = self._read_form()
                    attachments = []
            except ValueError as exc:
                if path == "/research":
                    self._send_html(
                        400,
                        render_research_dashboard(
                            application.store.list_jobs(),
                            application.auth.csrf_token(session),
                            form_error=_research_request_error(exc),
                        ),
                    )
                else:
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
                self._create_research(
                    fields,
                    application.auth.csrf_token(session),
                    attachments,
                )
                return
            message_job_id = _research_message_job_id(path)
            if message_job_id:
                self._add_research_message(message_job_id, fields)
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

        def _create_research(
            self,
            fields: dict[str, list[str]],
            csrf_token: str,
            attachments: list[ResearchAttachmentUpload],
        ) -> None:
            try:
                _validate_research_form_dates(fields)
                initial_messages, primary_kind, primary_content = (
                    _initial_research_messages(fields, attachments=attachments)
                )
                request = ResearchRequest(
                    title=_research_title(fields, attachments=attachments),
                    hypothesis=primary_content,
                    input_kind=primary_kind,
                    factor_id_hint=_field(fields, "factor_id_hint"),
                    universe=_field(fields, "universe", PILOT_UNIVERSE),
                    sample_start=_field(fields, "sample_start", "2016-01-01"),
                    sample_end=_field(fields, "sample_end", "2025-07-11"),
                    forward_horizon=_field(fields, "forward_horizon", "1d"),
                    transaction_cost_bps=float(_field(fields, "transaction_cost_bps", "30")),
                    model=_field(fields, "model", DEEPSEEK_V4_FLASH_MODEL),
                    source_url=_field(fields, "source_url"),
                    research_scope=_field(
                        fields,
                        "research_scope",
                        "full_formal",
                    ),
                )
                _validate_request_choices(request)
                job = application.service.submit(
                    request,
                    initial_messages=initial_messages,
                    initial_attachments=attachments,
                )
            except (ValueError, OverflowError, SourceFormulaDialectError) as exc:
                self._send_html(
                    400,
                    render_research_dashboard(
                        application.store.list_jobs(),
                        csrf_token,
                        form_error=_research_request_error(exc),
                        form_values=_research_form_values(fields),
                    ),
                )
                return
            except RuntimeError:
                self._send_html(
                    503,
                    render_research_dashboard(
                        application.store.list_jobs(),
                        csrf_token,
                        form_error="研究服务暂时不可用，输入内容已保留，请稍后重试。",
                        form_values=_research_form_values(fields),
                    ),
                )
                return
            self._redirect(f"/research/{job.job_id}")

        def _add_research_message(
            self,
            job_id: str,
            fields: dict[str, list[str]],
        ) -> None:
            job = application.store.get_job(job_id)
            if job is None:
                self._send_html(404, render_not_found())
                return
            try:
                content_kind = _field(fields, "content_kind", "decision")
                if content_kind not in USER_MESSAGE_CONTENT_KINDS:
                    raise ValueError("invalid user message content_kind")
                application.store.add_message(
                    job_id,
                    content_kind=content_kind,
                    content=_raw_field(fields, "content"),
                    model=job.request.model or DEEPSEEK_V4_FLASH_MODEL,
                    idempotency_key=_field(fields, "idempotency_key"),
                )
                if _field(fields, "message_action") == "save_and_resume":
                    application.service.request_resume(job_id)
            except KeyError:
                self._send_html(404, render_not_found())
                return
            except ValueError as exc:
                self._send_json(409, {"error": "invalid_message", "message": str(exc)})
                return
            except RuntimeError as exc:
                if str(exc).startswith(BLOCK_RESUME_TRUST_INVALID):
                    self._send_json(
                        409,
                        {
                            "error": "resume_not_safe",
                            "message": "研究消息已保存，但该任务缺少可信续跑证据。",
                        },
                    )
                    return
                self._send_json(503, {"error": "research_runtime_unavailable"})
                return
            self._redirect(f"/research/{job_id}#conversation")

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
            if length < 0 or length > min(application.config.max_request_bytes, 65_536):
                raise ValueError("request is too large")
            payload = self.rfile.read(length).decode("utf-8", errors="strict")
            return parse_qs(payload, keep_blank_values=True, max_num_fields=40)

        def _read_research_form(
            self,
        ) -> tuple[dict[str, list[str]], list[ResearchAttachmentUpload]]:
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("application/x-www-form-urlencoded"):
                return self._read_form(), []
            if not content_type.lower().startswith("multipart/form-data"):
                raise ValueError("only form submissions are accepted")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as exc:
                raise ValueError("invalid request length") from exc
            if length <= 0 or length > application.config.max_request_bytes:
                raise ValueError("request is too large")
            raw = self.rfile.read(length)
            header = (
                f"Content-Type: {content_type}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("utf-8")
            message = BytesParser(policy=policy.default).parsebytes(header + raw)
            if not message.is_multipart():
                raise ValueError("invalid multipart form")
            fields: dict[str, list[str]] = {}
            attachments: list[ResearchAttachmentUpload] = []
            parts = list(message.iter_parts())
            if len(parts) > 40:
                raise ValueError("too many form fields")
            for part in parts:
                if part.get_content_disposition() != "form-data" or part.is_multipart():
                    raise ValueError("invalid multipart field")
                name = str(
                    part.get_param("name", header="content-disposition") or ""
                ).strip()
                if not name:
                    raise ValueError("invalid multipart field name")
                payload = part.get_payload(decode=True) or b""
                filename = part.get_filename()
                if filename is not None:
                    if name == "report_pdf" and not filename and not payload:
                        continue
                    if name != "report_pdf" or not filename:
                        raise ValueError("only one PDF report attachment is accepted")
                    attachments.append(
                        ResearchAttachmentUpload(
                            original_filename=filename,
                            media_type=part.get_content_type(),
                            data=payload,
                        )
                    )
                    continue
                if len(payload) > 25_000:
                    raise ValueError("form field is too large")
                try:
                    value = payload.decode(part.get_content_charset() or "utf-8")
                except (LookupError, UnicodeDecodeError) as exc:
                    raise ValueError("form field is not valid UTF-8") from exc
                fields.setdefault(name, []).append(value)
            if len(attachments) > 1:
                raise ValueError("only one PDF report attachment is accepted")
            return fields, attachments

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


def _research_message_job_id(path: str) -> str:
    match = re.fullmatch(r"/research/(job_[a-f0-9]{10})/messages", path)
    return match.group(1) if match else ""


def _validate_request_choices(request: ResearchRequest) -> None:
    validate_pilot_evaluation_request(request)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.sample_start):
        raise ValueError("invalid sample_start")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.sample_end):
        raise ValueError("invalid sample_end")
    if request.sample_start >= request.sample_end:
        raise ValueError("sample_start must be before sample_end")


def _validate_research_form_dates(fields: dict[str, list[str]]) -> None:
    sample_start = _field(fields, "sample_start", "2016-01-01")
    sample_end = _field(fields, "sample_end", "2025-07-11")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sample_start):
        raise ValueError("invalid sample_start")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sample_end):
        raise ValueError("invalid sample_end")
    if sample_start >= sample_end:
        raise ValueError("sample_start must be before sample_end")


def _initial_research_messages(
    fields: dict[str, list[str]],
    *,
    attachments: list[ResearchAttachmentUpload] | None = None,
) -> tuple[list[tuple[str, str]], str, str]:
    inputs = [
        ("hypothesis", _raw_field(fields, "economic_hypothesis").strip()),
        ("report", _raw_field(fields, "report_input").strip()),
        ("formula", _raw_field(fields, "formula_input").strip()),
        ("code", _raw_field(fields, "code_input").strip()),
    ]
    messages = [(kind, content) for kind, content in inputs if content]
    uploads = list(attachments or [])
    if uploads:
        upload = uploads[0]
        messages.append(
            (
                "report",
                (
                    f"已上传 PDF 研报《{upload.original_filename}》，"
                    f"文件 SHA-256 为 {upload.sha256}。请读取 factor workspace 内"
                    "由 Host 校验的原始 PDF 和带页码提取文本，并将其作为用户提供的"
                    "研究材料；不得据此虚构作者、券商或外部真实性。"
                ),
            )
        )
    if not messages:
        legacy_content = _raw_field(fields, "hypothesis").strip()
        legacy_kind = _field(fields, "content_kind", "hypothesis")
        if legacy_content:
            messages = [(legacy_kind, legacy_content)]
    if not messages:
        raise ValueError("hypothesis is required")

    formula = next((content for kind, content in messages if kind == "formula"), "")
    if formula:
        source_contract = resolve_source_formula_for_host(formula)
        formula_ir = parse_formula(
            source_contract["canonical_formula"],
            raise_on_error=False,
            source_dialect_contract=(
                source_contract
                if source_contract.get("dialect_id")
                != "canonical_factorforge_formula_ir"
                else None
            ),
        )
        if formula_ir.get("parse_status") != "success":
            raise ValueError(
                "formula preflight failed: "
                + "; ".join(str(item) for item in formula_ir.get("parse_errors") or [])
            )
        if source_contract.get("dialect_id") != "canonical_factorforge_formula_ir":
            messages.append(
                (
                    "formula_contract",
                    json.dumps(
                        source_contract,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )

    primary_kind, primary_content = messages[0]
    return messages, primary_kind, primary_content


def _research_title(
    fields: dict[str, list[str]],
    *,
    attachments: list[ResearchAttachmentUpload] | None = None,
) -> str:
    explicit = _field(fields, "title").strip()
    if explicit:
        return explicit
    for field_name in ("economic_hypothesis", "report_input", "hypothesis"):
        content = _raw_field(fields, field_name).strip()
        if content:
            first_line = " ".join(content.splitlines()[0].split())
            return first_line[:80]
    uploads = list(attachments or [])
    if uploads:
        return Path(uploads[0].original_filename).stem[:80] or "上传研报因子研究"
    formula = _raw_field(fields, "formula_input").strip()
    if formula:
        digest = hashlib.sha256(formula.encode("utf-8")).hexdigest()[:8]
        return f"公式因子研究 {digest.upper()}"
    code = _raw_field(fields, "code_input").strip()
    if code:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:8]
        return f"代码因子研究 {digest.upper()}"
    raise ValueError("hypothesis is required")


def _research_form_values(fields: dict[str, list[str]]) -> dict[str, str]:
    names = (
        "title",
        "factor_id_hint",
        "content_kind",
        "model",
        "research_scope",
        "hypothesis",
        "economic_hypothesis",
        "report_input",
        "formula_input",
        "code_input",
        "universe",
        "sample_start",
        "sample_end",
    )
    return {name: _raw_field(fields, name) for name in names}


def _research_request_error(error: Exception) -> str:
    message = str(error)
    if message.startswith(BLOCK_SOURCE_SEMANTICS_UNRESOLVED):
        return (
            "系统未能在回测前冻结该公式的实现口径。"
            "这不是需要用户填写的字段，请保留输入并由研究服务修复。"
        )
    if message.startswith("formula preflight failed:"):
        return "公式当前无法进入可信 Formula IR：" + message.split(":", 1)[1].strip()
    translated = {
        "title is required": "请填写研究名称。",
        "title is too long": "研究名称过长，请控制在 160 个字符以内。",
        "hypothesis is required": "请填写研究输入。",
        "hypothesis is too long": "研究输入过长，请控制在 20,000 个字符以内。",
        "invalid sample_start": "样本开始日期无效。",
        "invalid sample_end": "样本结束日期无效。",
        "sample_start must be before sample_end": "样本开始日期必须早于结束日期。",
    }
    if message.startswith(BLOCK_PDF_UPLOAD_INVALID):
        return "PDF 研报无效。请上传不超过 20 MB、文件头有效且扩展名为 .pdf 的文件。"
    return translated.get(message, "研究请求不符合当前 Pilot 合同，请检查输入后重试。")


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
        "trusted_calendar": (
            trusted_calendar_healthy()
            if not application.config.auth_disabled
            else True
        ),
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
