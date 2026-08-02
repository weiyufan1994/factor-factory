from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.console.models import ResearchJob, ResearchRequest
from factor_factory.research_workspace import safe_identity


ACTIVE_STATUSES = ("ALLOCATING", "RESEARCHING", "VERIFYING")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class ResearchJobStore:
    def __init__(self, state_root: str | Path) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o770)
        try:
            self.state_root.chmod(0o770)
        except OSError:
            pass
        self.path = self.state_root / "console.sqlite3"
        self._create_shared_database_file()
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        self._ensure_shared_database_permissions()
        return connection

    def _create_shared_database_file(self) -> None:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o660)
        os.close(descriptor)
        self._ensure_shared_database_permissions()

    def _ensure_shared_database_permissions(self) -> None:
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
        ):
            try:
                candidate.chmod(0o660, follow_symlinks=False)
            except (FileNotFoundError, PermissionError):
                continue

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_jobs (
                    job_id TEXT PRIMARY KEY,
                    factor_id TEXT NOT NULL,
                    research_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    protocol_status TEXT NOT NULL,
                    factor_verdict TEXT NOT NULL,
                    council_status TEXT NOT NULL,
                    formal_proof_eligible INTEGER NOT NULL DEFAULT 0,
                    current_stage TEXT NOT NULL,
                    base_commit TEXT NOT NULL DEFAULT '',
                    worktree_path TEXT NOT NULL DEFAULT '',
                    workspace_path TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    agent_session_key TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL DEFAULT '',
                    finished_at_utc TEXT NOT NULL DEFAULT '',
                    UNIQUE(factor_id, research_id),
                    UNIQUE(report_id)
                );
                CREATE INDEX IF NOT EXISTS research_jobs_status_created
                    ON research_jobs(execution_status, created_at_utc);
                CREATE TABLE IF NOT EXISTS research_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES research_jobs(job_id),
                    created_at_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS research_events_job
                    ON research_events(job_id, event_id);
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_sha256 TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    expires_at_epoch INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            self._ensure_shared_database_permissions()

    def healthcheck(self) -> bool:
        try:
            with self._lock, self._connect() as connection:
                row = connection.execute("SELECT 1 AS ok").fetchone()
            return bool(row and row["ok"] == 1)
        except sqlite3.Error:
            return False

    def register_session(self, token: str, *, max_age_seconds: int) -> None:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires = int(time.time()) + int(max_age_seconds)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO auth_sessions VALUES (?,?,?,0)",
                (digest, utc_now(), expires),
            )
            connection.execute(
                "DELETE FROM auth_sessions WHERE revoked=1 OR expires_at_epoch<?",
                (int(time.time()) - 60,),
            )

    def session_is_active(self, token: str) -> bool:
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at_epoch, revoked FROM auth_sessions WHERE token_sha256=?",
                (digest,),
            ).fetchone()
        return bool(row and not row["revoked"] and int(row["expires_at_epoch"]) >= int(time.time()))

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked=1 WHERE token_sha256=?",
                (digest,),
            )

    def create_job(self, request: ResearchRequest) -> ResearchJob:
        now = utc_now()
        suffix = uuid.uuid4().hex[:10]
        factor_seed = request.factor_id_hint or request.title
        factor_id = safe_identity(factor_seed).upper()[:64]
        if factor_id == "UNKNOWN":
            raise ValueError("factor identity is invalid")
        research_id = f"web_{now[:10].replace('-', '')}_{suffix}"
        report_prefix = f"WEB_{factor_id}_{now[:10].replace('-', '')}"
        report_id = f"{report_prefix[:104]}_{suffix}"
        job = ResearchJob(
            job_id=f"job_{suffix}",
            factor_id=factor_id,
            research_id=research_id,
            report_id=report_id,
            request=request,
            created_at_utc=now,
            updated_at_utc=now,
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_job(connection, job)
            self._insert_event(connection, job.job_id, "JOB_CREATED", "研究任务已进入队列", {})
            connection.execute("COMMIT")
        return job

    def _insert_job(self, connection: sqlite3.Connection, job: ResearchJob) -> None:
        connection.execute(
            """
            INSERT INTO research_jobs (
                job_id, factor_id, research_id, report_id, request_json,
                execution_status, protocol_status, factor_verdict, council_status,
                formal_proof_eligible, current_stage, base_commit, worktree_path,
                workspace_path, agent_id, agent_session_key, error_code,
                error_message, result_json, created_at_utc, updated_at_utc,
                started_at_utc, finished_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.job_id,
                job.factor_id,
                job.research_id,
                job.report_id,
                _compact_json(job.request.to_dict()),
                job.execution_status,
                job.protocol_status,
                job.factor_verdict,
                job.council_status,
                int(job.formal_proof_eligible),
                job.current_stage,
                job.base_commit,
                job.worktree_path,
                job.workspace_path,
                job.agent_id,
                job.agent_session_key,
                job.error_code,
                job.error_message,
                _compact_json(job.result),
                job.created_at_utc,
                job.updated_at_utc,
                job.started_at_utc,
                job.finished_at_utc,
            ),
        )

    def get_job(self, job_id: str) -> ResearchJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[ResearchJob]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_jobs ORDER BY created_at_utc DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def claim_next_job(self) -> ResearchJob | None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT COUNT(*) FROM research_jobs WHERE execution_status IN (?,?,?)", ACTIVE_STATUSES
            ).fetchone()[0]
            if active:
                connection.execute("COMMIT")
                return None
            row = connection.execute(
                "SELECT * FROM research_jobs WHERE execution_status='QUEUED' ORDER BY created_at_utc LIMIT 1"
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            started = str(row["started_at_utc"] or now)
            connection.execute(
                """
                UPDATE research_jobs
                SET execution_status='ALLOCATING', current_stage='allocating_workspace',
                    protocol_status=CASE WHEN protocol_status='NOT_STARTED' THEN 'RUNNING' ELSE protocol_status END,
                    started_at_utc=?, updated_at_utc=?
                WHERE job_id=? AND execution_status='QUEUED'
                """,
                (started, now, row["job_id"]),
            )
            self._insert_event(
                connection,
                str(row["job_id"]),
                "JOB_CLAIMED",
                "任务已由研究执行器领取",
                {},
            )
            connection.execute("COMMIT")
        return self.get_job(str(row["job_id"]))

    def update_job(self, job_id: str, **changes: Any) -> ResearchJob:
        allowed = {
            "execution_status",
            "protocol_status",
            "factor_verdict",
            "council_status",
            "formal_proof_eligible",
            "current_stage",
            "base_commit",
            "worktree_path",
            "workspace_path",
            "agent_id",
            "agent_session_key",
            "error_code",
            "error_message",
            "result",
            "started_at_utc",
            "finished_at_utc",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported job fields: {sorted(unknown)}")
        if not changes:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(job_id)
            return job
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            column = "result_json" if key == "result" else key
            assignments.append(f"{column}=?")
            if key == "result":
                value = _compact_json(value)
            elif key == "formal_proof_eligible":
                value = int(bool(value))
            values.append(value)
        assignments.append("updated_at_utc=?")
        values.extend([utc_now(), job_id])
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE research_jobs SET {', '.join(assignments)} WHERE job_id=?", values
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            self._insert_event(connection, job_id, event_type, message, payload or {})

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO research_events(job_id,created_at_utc,event_type,message,payload_json) VALUES (?,?,?,?,?)",
            (job_id, utc_now(), event_type, message[:800], _compact_json(payload)),
        )

    def list_events(self, job_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, created_at_utc, event_type, message, payload_json
                FROM research_events WHERE job_id=? ORDER BY event_id DESC LIMIT ?
                """,
                (job_id, max(1, min(int(limit), 500))),
            ).fetchall()
        output = []
        for row in reversed(rows):
            output.append(
                {
                    "event_id": row["event_id"],
                    "created_at_utc": row["created_at_utc"],
                    "event_type": row["event_type"],
                    "message": row["message"],
                    "payload": json.loads(row["payload_json"] or "{}"),
                }
            )
        return output

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.execution_status not in {"REVIEW_REQUIRED", "BLOCKED", "FAILED"}:
            raise ValueError("only a paused, blocked, or failed job can be resumed")
        resumed = self.update_job(
            job_id,
            execution_status="QUEUED",
            protocol_status="RUNNING",
            current_stage="resume_requested",
            error_code="",
            error_message="",
            finished_at_utc="",
        )
        self.append_event(job_id, "RESUME_REQUESTED", "已请求研究代理从现有 workspace 继续", {})
        return resumed

    def cancel_queued(self, job_id: str) -> ResearchJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.execution_status != "QUEUED":
            raise ValueError("only queued jobs can be cancelled")
        cancelled = self.update_job(
            job_id,
            execution_status="CANCELLED",
            current_stage="cancelled",
            finished_at_utc=utc_now(),
        )
        self.append_event(job_id, "JOB_CANCELLED", "排队任务已取消", {})
        return cancelled

    def pause_interrupted_jobs(self) -> int:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_id FROM research_jobs WHERE execution_status IN (?,?,?)", ACTIVE_STATUSES
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE research_jobs
                    SET execution_status='REVIEW_REQUIRED', protocol_status='PAUSED',
                        current_stage='service_restart_review',
                        error_code='BLOCK_FACTORFORGE_CONSOLE_SERVICE_RESTART_REVIEW_REQUIRED',
                        error_message='服务重启后未自动重复执行；请从现有 workspace 显式继续。',
                        updated_at_utc=? WHERE job_id=?
                    """,
                    (now, row["job_id"]),
                )
                self._insert_event(
                    connection,
                    str(row["job_id"]),
                    "SERVICE_RESTART_PAUSE",
                    "服务重启，任务已安全暂停，未重复创建 worktree",
                    {},
                )
            connection.execute("COMMIT")
        return len(rows)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> ResearchJob:
        return ResearchJob(
            job_id=str(row["job_id"]),
            factor_id=str(row["factor_id"]),
            research_id=str(row["research_id"]),
            report_id=str(row["report_id"]),
            request=ResearchRequest.from_dict(json.loads(row["request_json"])),
            execution_status=str(row["execution_status"]),
            protocol_status=str(row["protocol_status"]),
            factor_verdict=str(row["factor_verdict"]),
            council_status=str(row["council_status"]),
            formal_proof_eligible=bool(row["formal_proof_eligible"]),
            current_stage=str(row["current_stage"]),
            base_commit=str(row["base_commit"]),
            worktree_path=str(row["worktree_path"]),
            workspace_path=str(row["workspace_path"]),
            agent_id=str(row["agent_id"]),
            agent_session_key=str(row["agent_session_key"]),
            error_code=str(row["error_code"]),
            error_message=str(row["error_message"]),
            result=json.loads(row["result_json"] or "{}"),
            created_at_utc=str(row["created_at_utc"]),
            updated_at_utc=str(row["updated_at_utc"]),
            started_at_utc=str(row["started_at_utc"]),
            finished_at_utc=str(row["finished_at_utc"]),
        )
