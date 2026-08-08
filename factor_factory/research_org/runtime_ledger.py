from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import (
    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
    BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    ResearchOrganizationError,
    stable_json_hash,
    validate_content_hash,
)
from factor_factory.research_org.runtime_trust import RuntimeTrustStore

LEDGER_SCHEMA_VERSION = 2
LEDGER_CONTRACT_VERSION = "factorforge_research_org_runtime_ledger_v1"
VALID_RUN_STATES = {
    "PLANNED",
    "ACTIVE",
    "WAITING_HOST_RESULT",
    "WAITING_DATA",
    "WAITING_CLARIFICATION",
    "BLOCKED",
    "FAILED",
    "CANCELLING",
    "CANCELLED",
    "COMPLETE",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["ledger_payload_not_canonical"],
        ) from exc


def _json(value: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, item in pairs:
            if key in output:
                raise ValueError(f"duplicate_json_key:{key}")
            output[key] = item
        return output

    def reject_constant(item: str) -> None:
        raise ValueError(f"non_finite_json:{item}")

    try:
        return json.loads(
            value,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["ledger_json_invalid"],
        ) from exc


def _private_runtime_root(
    private_root: Path,
    runtime_id: str,
    *,
    create: bool,
) -> Path:
    base = Path(private_root).expanduser()
    if base.exists() or base.is_symlink():
        metadata = base.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"unsafe_private_runtime_base:{base}"],
            )
    else:
        if not create:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"private_runtime_base_missing:{base}"],
            )
        base.mkdir(parents=True, mode=0o700)
    base = base.resolve(strict=True)
    if create:
        base.chmod(0o700)
    root = base / runtime_id
    if not root.exists() and not root.is_symlink():
        if not create:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"private_runtime_root_missing:{root}"],
            )
        root.mkdir(mode=0o700)
    metadata = root.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"unsafe_private_runtime_root:{root}"],
        )
    if create:
        root.chmod(0o700)
    return root


@dataclass(frozen=True)
class DispatchLease:
    scheduler_epoch: int
    dispatch_event_seq: int
    idempotency_key: str
    dependency_admissions: tuple[dict[str, Any], ...]


class ResearchOrgRuntimeLedger:
    def __init__(
        self,
        *,
        private_root: Path,
        runtime_id: str,
        identity: Mapping[str, Any],
        plan_sha256: str,
        tasks: Sequence[Mapping[str, Any]],
        policy: Mapping[str, Any],
        trust_store: RuntimeTrustStore | None,
        existing_only: bool = False,
        read_only: bool = False,
    ) -> None:
        self.runtime_id = runtime_id
        self.identity = dict(identity)
        self.plan_sha256 = str(plan_sha256)
        self.tasks = {str(task["role_id"]): dict(task) for task in tasks}
        self.policy = dict(policy)
        self.trust_store = trust_store
        if read_only and not existing_only:
            raise ValueError("read_only ledger requires existing_only=True")
        self.existing_only = existing_only
        self.read_only = read_only
        self.root = _private_runtime_root(
            private_root,
            runtime_id,
            create=not existing_only,
        )
        self.path = self.root / "runtime_ledger.sqlite3"
        if existing_only:
            self._ensure_safe_ledger_file(create=False)
            with self._connect() as connection:
                self._validate_static_binding(connection)
        else:
            self._initialize()

    def _ensure_safe_ledger_file(self, *, create: bool) -> None:
        if not self.path.exists() and not self.path.is_symlink():
            if not create:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"private_runtime_ledger_missing:{self.path}"],
                )
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        metadata = self.path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"unsafe_private_runtime_ledger:{self.path}"],
            )

    def _connect(self) -> sqlite3.Connection:
        self._ensure_safe_ledger_file(create=not self.existing_only)
        if self.read_only:
            connection = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro",
                timeout=30,
                isolation_level=None,
                uri=True,
            )
        else:
            connection = sqlite3.connect(
                self.path,
                timeout=30,
                isolation_level=None,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA trusted_schema=OFF")
        if self.read_only:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        self._ensure_safe_ledger_file(create=False)
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["read_only_ledger_transaction_forbidden"],
            )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        fresh = not self.path.exists()
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    runtime_id TEXT PRIMARY KEY,
                    contract_version TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    identity_json TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    trust_manifest_json TEXT,
                    state TEXT NOT NULL,
                    scheduler_epoch INTEGER NOT NULL DEFAULT 0,
                    cancel_seq INTEGER,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    role_id TEXT NOT NULL UNIQUE,
                    task_sha256 TEXT NOT NULL,
                    dependency_roles_json TEXT NOT NULL,
                    session_requirement TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    result_status TEXT,
                    admitted_result_sha256 TEXT,
                    admission_receipt_id TEXT UNIQUE,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    role_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    session_uid TEXT NOT NULL UNIQUE,
                    runtime_handle TEXT NOT NULL UNIQUE,
                    runtime_handle_sha256 TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    scheduler_epoch INTEGER NOT NULL,
                    dispatch_event_seq INTEGER NOT NULL UNIQUE,
                    context_manifest_sha256 TEXT NOT NULL,
                    attempt_projection_sha256 TEXT,
                    receipt_projection_sha256 TEXT,
                    dependency_admissions_json TEXT NOT NULL,
                    adapter_challenge TEXT NOT NULL,
                    parent_session_uid TEXT,
                    provider_handle_sha256 TEXT UNIQUE,
                    adapter_build_sha256 TEXT,
                    container_image_digest TEXT,
                    private_output_sha256 TEXT,
                    private_output_size_bytes INTEGER,
                    state TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT,
                    adapter_receipt_id TEXT UNIQUE,
                    evidence_class TEXT NOT NULL,
                    error_class TEXT,
                    retryable INTEGER,
                    UNIQUE(task_id, attempt_no)
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    receipt_type TEXT NOT NULL,
                    issuer_kind TEXT NOT NULL,
                    event_seq INTEGER NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admissions (
                    role_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
                    result_status TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL UNIQUE,
                    result_json TEXT NOT NULL,
                    adapter_receipt_id TEXT,
                    host_receipt_id TEXT NOT NULL UNIQUE REFERENCES receipts(receipt_id),
                    event_seq INTEGER NOT NULL UNIQUE,
                    evidence_class TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_seq INTEGER PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    role_id TEXT,
                    attempt_id TEXT,
                    previous_event_sha256 TEXT,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    occurred_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            trust_manifest = (
                self.trust_store.public_manifest if self.trust_store is not None else None
            )
            now = utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO runs (
                    runtime_id, contract_version, schema_version, identity_json,
                    plan_sha256, policy_json, trust_manifest_json, state,
                    scheduler_epoch, cancel_seq, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PLANNED', 0, NULL, ?, ?)
                """,
                (
                    self.runtime_id,
                    LEDGER_CONTRACT_VERSION,
                    LEDGER_SCHEMA_VERSION,
                    _canonical_json(self.identity),
                    self.plan_sha256,
                    _canonical_json(self.policy),
                    _canonical_json(trust_manifest) if trust_manifest is not None else None,
                    now,
                    now,
                ),
            )
            for role_id, task in self.tasks.items():
                dependencies = list(task.get("depends_on_roles") or [])
                if role_id == "independent_council":
                    dependencies = list(task.get("required_review_role_ids") or [])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO tasks (
                        task_id, role_id, task_sha256, dependency_roles_json,
                        session_requirement, state
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        task["task_id"],
                        role_id,
                        task["task_sha256"],
                        _canonical_json(dependencies),
                        task["session_policy"]["requirement"],
                    ),
                )
            self._validate_static_binding(connection)
            if fresh:
                os.chmod(self.path, 0o600)

    def _validate_static_binding(self, connection: sqlite3.Connection) -> None:
        run = connection.execute(
            "SELECT * FROM runs WHERE runtime_id=?",
            (self.runtime_id,),
        ).fetchone()
        if run is None or (
            run["contract_version"] != LEDGER_CONTRACT_VERSION
            or run["schema_version"] != LEDGER_SCHEMA_VERSION
            or _json(run["identity_json"]) != self.identity
            or run["plan_sha256"] != self.plan_sha256
            or _json(run["policy_json"]) != self.policy
            or run["state"] not in VALID_RUN_STATES
            or (
                _json(run["trust_manifest_json"])
                if run["trust_manifest_json"]
                else None
            )
            != (
                self.trust_store.public_manifest
                if self.trust_store is not None
                else None
            )
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["ledger_run_binding"],
            )
        rows = connection.execute("SELECT * FROM tasks ORDER BY role_id").fetchall()
        if {row["role_id"] for row in rows} != set(self.tasks):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["ledger_task_set"],
            )
        for row in rows:
            task = self.tasks[row["role_id"]]
            dependencies = list(task.get("depends_on_roles") or [])
            if row["role_id"] == "independent_council":
                dependencies = list(task.get("required_review_role_ids") or [])
            if (
                row["task_id"] != task["task_id"]
                or row["task_sha256"] != task["task_sha256"]
                or _json(row["dependency_roles_json"]) != dependencies
                or row["session_requirement"]
                != task["session_policy"]["requirement"]
            ):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"ledger_task_binding:{row['role_id']}"],
                )

    @staticmethod
    def _next_event_seq(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(event_seq), 0) + 1 AS next_seq FROM events"
        ).fetchone()
        return int(row["next_seq"])

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        role_id: str | None,
        attempt_id: str | None,
        detail: Mapping[str, Any],
    ) -> int:
        sequence = self._next_event_seq(connection)
        previous = connection.execute(
            "SELECT event_sha256 FROM events ORDER BY event_seq DESC LIMIT 1"
        ).fetchone()
        payload = {
            "contract_version": "factorforge_research_org_ledger_event_v1",
            "runtime_id": self.runtime_id,
            "identity": self.identity,
            "event_seq": sequence,
            "event_type": event_type,
            "role_id": role_id,
            "attempt_id": attempt_id,
            "previous_event_sha256": previous["event_sha256"] if previous else None,
            "occurred_at_utc": utc_now(),
            "detail": dict(detail),
        }
        event_sha256 = stable_json_hash(payload)
        connection.execute(
            """
            INSERT INTO events (
                event_seq, event_type, role_id, attempt_id,
                previous_event_sha256, event_sha256, occurred_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                event_type,
                role_id,
                attempt_id,
                payload["previous_event_sha256"],
                event_sha256,
                payload["occurred_at_utc"],
                _canonical_json(payload),
            ),
        )
        return sequence

    def start_scheduler(self) -> int:
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT state, scheduler_epoch FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if run["state"] in {"CANCELLING", "CANCELLED"}:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
                    [f"ledger_state={run['state']}"],
                )
            epoch = int(run["scheduler_epoch"]) + 1
            sequence = self._append_event(
                connection,
                event_type="SCHEDULER_EPOCH_STARTED",
                role_id=None,
                attempt_id=None,
                detail={"scheduler_epoch": epoch},
            )
            connection.execute(
                """
                UPDATE runs SET state='ACTIVE', scheduler_epoch=?, updated_at_utc=?
                WHERE runtime_id=?
                """,
                (epoch, utc_now(), self.runtime_id),
            )
            _ = sequence
            return epoch

    def dependency_admissions(
        self,
        role_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], ...]:
        own_connection = connection is None
        db = connection or self._connect()
        try:
            task = db.execute(
                "SELECT dependency_roles_json FROM tasks WHERE role_id=?",
                (role_id,),
            ).fetchone()
            if task is None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"ledger_role_missing:{role_id}"],
                )
            dependencies = _json(task["dependency_roles_json"])
            output: list[dict[str, Any]] = []
            for dependency_role in dependencies:
                row = db.execute(
                    """
                    SELECT role_id, result_status, result_sha256,
                           host_receipt_id, event_seq
                    FROM admissions WHERE role_id=?
                    """,
                    (dependency_role,),
                ).fetchone()
                if row is None or row["result_status"] != "PASS":
                    raise ResearchOrganizationError(
                        BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                        [f"dependency_not_admitted_pass:{role_id}:{dependency_role}"],
                    )
                output.append(
                    {
                        "role_id": row["role_id"],
                        "result_sha256": row["result_sha256"],
                        "admission_receipt_id": row["host_receipt_id"],
                        "event_seq": int(row["event_seq"]),
                    }
                )
            return tuple(output)
        finally:
            if own_connection:
                db.close()

    def begin_attempt(
        self,
        *,
        role_id: str,
        attempt_id: str,
        attempt_no: int,
        session_uid: str,
        runtime_handle: str,
        context_manifest_sha256: str,
        idempotency_key: str,
        dependency_admissions: Sequence[Mapping[str, Any]],
        adapter_challenge: str,
        parent_session_uid: str | None,
        scheduler_epoch: int,
    ) -> DispatchLease:
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT state, scheduler_epoch, cancel_seq FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if (
                run["state"] in {"CANCELLING", "CANCELLED"}
                or run["cancel_seq"] is not None
            ):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
                    ["ledger_cancel_fence"],
                )
            if int(run["scheduler_epoch"]) != scheduler_epoch:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["stale_scheduler_epoch"],
                )
            task = connection.execute(
                "SELECT * FROM tasks WHERE role_id=?",
                (role_id,),
            ).fetchone()
            if task is None or task["session_requirement"] == "host_session":
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"invalid_dispatch_role:{role_id}"],
                )
            max_attempts = int(self.policy["max_attempts_per_role"])
            if attempt_no != int(task["attempt_count"]) + 1 or attempt_no > max_attempts:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"attempt_budget_or_sequence:{role_id}"],
                )
            dependencies = self.dependency_admissions(
                role_id,
                connection=connection,
            )
            if list(dependencies) != [dict(item) for item in dependency_admissions]:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"dependency_snapshot_changed:{role_id}"],
                )
            if role_id == "independent_council" and parent_session_uid is not None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["council_parent_session_forbidden"],
                )
            expected_idempotency_key = stable_json_hash(
                {
                    "runtime_id": self.runtime_id,
                    "task_id": task["task_id"],
                    "task_sha256": task["task_sha256"],
                    "attempt_no": attempt_no,
                    "scheduler_epoch": scheduler_epoch,
                }
            )
            if idempotency_key != expected_idempotency_key:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"idempotency_key_mismatch:{role_id}"],
                )
            runtime_handle_sha256 = hashlib.sha256(runtime_handle.encode("utf-8")).hexdigest()
            sequence = self._append_event(
                connection,
                event_type="SESSION_DISPATCHED",
                role_id=role_id,
                attempt_id=attempt_id,
                detail={
                    "scheduler_epoch": scheduler_epoch,
                    "session_uid": session_uid,
                    "idempotency_key": idempotency_key,
                    "dependencies": list(dependencies),
                },
            )
            if any(int(item["event_seq"]) >= sequence for item in dependencies):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"dependency_ordering:{role_id}"],
                )
            connection.execute(
                """
                INSERT INTO attempts (
                    attempt_id, task_id, role_id, attempt_no, session_uid,
                    runtime_handle, runtime_handle_sha256, idempotency_key, scheduler_epoch,
                    dispatch_event_seq, context_manifest_sha256,
                    dependency_admissions_json, adapter_challenge,
                    parent_session_uid, state,
                    started_at_utc, evidence_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DISPATCHED', ?, 'pending')
                """,
                (
                    attempt_id,
                    task["task_id"],
                    role_id,
                    attempt_no,
                    session_uid,
                    runtime_handle,
                    runtime_handle_sha256,
                    idempotency_key,
                    scheduler_epoch,
                    sequence,
                    context_manifest_sha256,
                    _canonical_json(list(dependencies)),
                    adapter_challenge,
                    parent_session_uid,
                    utc_now(),
                ),
            )
            connection.execute(
                """
                UPDATE tasks SET state='RUNNING', attempt_count=? WHERE role_id=?
                """,
                (attempt_no, role_id),
            )
            return DispatchLease(
                scheduler_epoch=scheduler_epoch,
                dispatch_event_seq=sequence,
                idempotency_key=idempotency_key,
                dependency_admissions=dependencies,
            )

    def dispatch_material(
        self,
        *,
        role_id: str,
        attempt_no: int,
        scheduler_epoch: int,
    ) -> tuple[tuple[dict[str, Any], ...], str]:
        with self._connect() as connection:
            task = connection.execute(
                "SELECT task_id, task_sha256 FROM tasks WHERE role_id=?",
                (role_id,),
            ).fetchone()
            if task is None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"ledger_role_missing:{role_id}"],
                )
            dependencies = self.dependency_admissions(role_id, connection=connection)
            idempotency_key = stable_json_hash(
                {
                    "runtime_id": self.runtime_id,
                    "task_id": task["task_id"],
                    "task_sha256": task["task_sha256"],
                    "attempt_no": attempt_no,
                    "scheduler_epoch": scheduler_epoch,
                }
            )
            return dependencies, idempotency_key

    def active_attempts(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, role_id, attempt_no, session_uid,
                       runtime_handle, scheduler_epoch, dispatch_event_seq,
                       context_manifest_sha256, dependency_admissions_json,
                       adapter_challenge, idempotency_key, started_at_utc
                FROM attempts WHERE state='DISPATCHED'
                ORDER BY dispatch_event_seq
                """
            ).fetchall()
            return tuple(
                {
                    **dict(row),
                    "dependency_admissions": _json(
                        row["dependency_admissions_json"]
                    ),
                }
                for row in rows
            )

    def bind_attempt_projection(
        self,
        *,
        attempt_id: str,
        attempt_sha256: str,
    ) -> None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT attempt_projection_sha256 FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"projection_attempt_missing:{attempt_id}"],
                )
            existing = row["attempt_projection_sha256"]
            if existing is not None and existing != attempt_sha256:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"projection_attempt_changed:{attempt_id}"],
                )
            connection.execute(
                """
                UPDATE attempts SET attempt_projection_sha256=? WHERE attempt_id=?
                """,
                (attempt_sha256, attempt_id),
            )

    def bind_receipt_projection(
        self,
        *,
        attempt_id: str,
        receipt_sha256: str,
    ) -> None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT receipt_projection_sha256 FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"projection_receipt_attempt_missing:{attempt_id}"],
                )
            existing = row["receipt_projection_sha256"]
            if existing is not None and existing != receipt_sha256:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"projection_receipt_changed:{attempt_id}"],
                )
            connection.execute(
                """
                UPDATE attempts SET receipt_projection_sha256=? WHERE attempt_id=?
                """,
                (receipt_sha256, attempt_id),
            )

    def projection_bindings(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role_id, attempt_id, context_manifest_sha256,
                       attempt_projection_sha256, receipt_projection_sha256
                FROM attempts ORDER BY dispatch_event_seq
                """
            ).fetchall()
            return tuple(dict(row) for row in rows)

    def mark_attempt_lost(
        self,
        *,
        attempt_id: str,
        error_class: str,
        retryable: bool,
        termination_confirmed: bool,
    ) -> None:
        with self._transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["state"] != "DISPATCHED":
                return
            max_attempts = int(self.policy["max_attempts_per_role"])
            can_retry = (
                retryable
                and termination_confirmed
                and int(attempt["attempt_no"]) < max_attempts
            )
            self._append_event(
                connection,
                event_type="SESSION_LOST",
                role_id=attempt["role_id"],
                attempt_id=attempt_id,
                detail={
                    "error_class": error_class,
                    "retryable": can_retry,
                    "termination_confirmed": termination_confirmed,
                },
            )
            connection.execute(
                """
                UPDATE attempts SET state='LOST', finished_at_utc=?,
                    evidence_class='host_recovery', error_class=?, retryable=?
                WHERE attempt_id=?
                """,
                (utc_now(), error_class, 1 if can_retry else 0, attempt_id),
            )
            connection.execute(
                "UPDATE tasks SET state=?, last_error=? WHERE role_id=?",
                (
                    "RETRY_WAIT" if can_retry else "FAILED_FINAL",
                    error_class,
                    attempt["role_id"],
                ),
            )

    def _insert_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        receipt: Mapping[str, Any],
        receipt_type: str,
        issuer_kind: str,
        event_seq: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO receipts (
                receipt_id, receipt_type, issuer_kind, event_seq, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                receipt["receipt_id"],
                receipt_type,
                issuer_kind,
                event_seq,
                _canonical_json(receipt),
            ),
        )

    def _adapter_receipt_binding_reasons(
        self,
        *,
        attempt: sqlite3.Row,
        receipt: Mapping[str, Any],
        canonical_result: Mapping[str, Any] | None,
        observed_private_output_sha256: str | None,
        observed_private_output_size_bytes: int | None,
    ) -> list[str]:
        reasons: list[str] = []
        expected_top = {
            "contract_version",
            "receipt_type",
            "identity",
            "ordering",
            "bindings",
            "session",
            "outcome",
            "issuer",
            "receipt_id",
            "signature",
        }
        if set(receipt) != expected_top:
            reasons.append("adapter_receipt.fields")
        identity = receipt.get("identity") if isinstance(receipt.get("identity"), dict) else {}
        expected_identity = {
            **self.identity,
            "runtime_id": self.runtime_id,
            "task_id": attempt["task_id"],
            "role_id": attempt["role_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_no": int(attempt["attempt_no"]),
        }
        if identity != expected_identity:
            reasons.append("adapter_receipt.identity")
        ordering = receipt.get("ordering") if isinstance(receipt.get("ordering"), dict) else {}
        if (
            set(ordering)
            != {
                "scheduler_epoch",
                "dispatch_event_seq",
                "issued_at_utc",
                "started_at_utc",
                "finished_at_utc",
            }
            or ordering.get("scheduler_epoch") != int(attempt["scheduler_epoch"])
            or ordering.get("dispatch_event_seq")
            != int(attempt["dispatch_event_seq"])
            or any(
                not isinstance(ordering.get(field), str)
                or not ordering[field].strip()
                for field in ("issued_at_utc", "started_at_utc", "finished_at_utc")
            )
        ):
            reasons.append("adapter_receipt.ordering")
        bindings = receipt.get("bindings") if isinstance(receipt.get("bindings"), dict) else {}
        expected_bindings = {
            "plan_sha256": self.plan_sha256,
            "task_sha256": self.tasks[attempt["role_id"]]["task_sha256"],
            "context_manifest_sha256": attempt["context_manifest_sha256"],
            "dependency_admissions": _json(attempt["dependency_admissions_json"]),
            "idempotency_key": attempt["idempotency_key"],
            "adapter_challenge": attempt["adapter_challenge"],
        }
        if bindings != expected_bindings:
            reasons.append("adapter_receipt.bindings")
        session = receipt.get("session") if isinstance(receipt.get("session"), dict) else {}
        expected_session_fields = {
            "session_uid",
            "runtime_handle_sha256",
            "provider_handle_sha256",
            "adapter_id",
            "adapter_build_sha256",
            "container_image_digest",
            "isolation_profile_sha256",
            "parent_session_uid",
            "lease_epoch",
        }
        if (
            set(session) != expected_session_fields
            or session.get("session_uid") != attempt["session_uid"]
            or session.get("runtime_handle_sha256")
            != attempt["runtime_handle_sha256"]
            or session.get("parent_session_uid") != attempt["parent_session_uid"]
            or session.get("lease_epoch") != int(attempt["scheduler_epoch"])
            or self.trust_store is None
            or session.get("adapter_id") != self.trust_store.installation_id
            or any(
                not isinstance(session.get(field), str)
                or len(session[field]) != 64
                or any(character not in "0123456789abcdef" for character in session[field])
                for field in (
                    "provider_handle_sha256",
                    "adapter_build_sha256",
                    "isolation_profile_sha256",
                )
            )
            or not isinstance(session.get("container_image_digest"), str)
        ):
            reasons.append("adapter_receipt.session")
        outcome = receipt.get("outcome") if isinstance(receipt.get("outcome"), dict) else {}
        expected_outcome_fields = {
            "returncode",
            "cancelled",
            "error_class",
            "private_output_sha256",
            "private_output_size_bytes",
            "termination_confirmed",
        }
        if (
            set(outcome) != expected_outcome_fields
            or type(outcome.get("returncode")) is not int
            or type(outcome.get("cancelled")) is not bool
            or type(outcome.get("termination_confirmed")) is not bool
        ):
            reasons.append("adapter_receipt.outcome")
        if canonical_result is not None and (
            receipt.get("receipt_type") != "COMPLETED"
            or outcome.get("returncode") != 0
            or outcome.get("cancelled") is not False
            or not isinstance(outcome.get("private_output_sha256"), str)
            or len(outcome.get("private_output_sha256") or "") != 64
            or type(outcome.get("private_output_size_bytes")) is not int
            or int(outcome.get("private_output_size_bytes") or 0) <= 0
            or outcome.get("private_output_sha256")
            != observed_private_output_sha256
            or outcome.get("private_output_size_bytes")
            != observed_private_output_size_bytes
        ):
            reasons.append("adapter_receipt.completed_outcome")
        if canonical_result is None and receipt.get("receipt_type") not in {
            "FAILED",
            "TERMINATED",
            "COMPLETED",
        }:
            reasons.append("adapter_receipt.failure_type")
        return reasons

    def _host_receipt_binding_reasons(
        self,
        *,
        admission: sqlite3.Row,
        receipt: Mapping[str, Any],
        attempt: sqlite3.Row | None,
    ) -> list[str]:
        reasons: list[str] = []
        expected_top = {
            "contract_version",
            "receipt_type",
            "identity",
            "ordering",
            "bindings",
            "outcome",
            "issuer",
            "receipt_id",
            "signature",
        }
        if set(receipt) != expected_top:
            reasons.append("host_receipt.fields")
        role_id = str(admission["role_id"])
        task = self.tasks[role_id]
        identity = receipt.get("identity") if isinstance(receipt.get("identity"), dict) else {}
        ordering = receipt.get("ordering") if isinstance(receipt.get("ordering"), dict) else {}
        bindings = receipt.get("bindings") if isinstance(receipt.get("bindings"), dict) else {}
        outcome = receipt.get("outcome") if isinstance(receipt.get("outcome"), dict) else {}
        expected_outcome = {
            "result_status": admission["result_status"],
            "evidence_class": admission["evidence_class"],
        }
        if attempt is None:
            expected_identity = {
                **self.identity,
                "runtime_id": self.runtime_id,
                "task_id": admission["task_id"],
                "role_id": role_id,
            }
            expected_ordering_fields = {
                "event_seq",
                "scheduler_epoch",
                "issued_at_utc",
            }
            expected_bindings = {
                "plan_sha256": self.plan_sha256,
                "task_sha256": task["task_sha256"],
                "result_sha256": admission["result_sha256"],
            }
            if (
                task["session_policy"]["requirement"] != "host_session"
                or receipt.get("receipt_type") != "HOST_RESULT_IMPORTED"
                or identity != expected_identity
                or set(ordering) != expected_ordering_fields
                or ordering.get("event_seq") != int(admission["event_seq"])
                or type(ordering.get("scheduler_epoch")) is not int
                or int(ordering.get("scheduler_epoch") or 0) < 1
                or not isinstance(ordering.get("issued_at_utc"), str)
                or not str(ordering.get("issued_at_utc") or "").strip()
                or bindings != expected_bindings
                or outcome != expected_outcome
            ):
                reasons.append("host_receipt.import_binding")
            return reasons

        expected_identity = {
            **self.identity,
            "runtime_id": self.runtime_id,
            "task_id": admission["task_id"],
            "role_id": role_id,
            "attempt_id": attempt["attempt_id"],
        }
        expected_ordering = {
            "event_seq": int(admission["event_seq"]),
            "scheduler_epoch": int(attempt["scheduler_epoch"]),
            "dispatch_event_seq": int(attempt["dispatch_event_seq"]),
        }
        expected_bindings = {
            "plan_sha256": self.plan_sha256,
            "task_sha256": task["task_sha256"],
            "context_manifest_sha256": attempt["context_manifest_sha256"],
            "dependency_admissions": _json(attempt["dependency_admissions_json"]),
            "adapter_receipt_id": admission["adapter_receipt_id"],
            "result_sha256": admission["result_sha256"],
        }
        if (
            task["session_policy"]["requirement"] == "host_session"
            or receipt.get("receipt_type") != "RESULT_ADMITTED"
            or identity != expected_identity
            or set(ordering)
            != {
                "event_seq",
                "scheduler_epoch",
                "dispatch_event_seq",
                "issued_at_utc",
            }
            or any(ordering.get(key) != value for key, value in expected_ordering.items())
            or not isinstance(ordering.get("issued_at_utc"), str)
            or not str(ordering.get("issued_at_utc") or "").strip()
            or bindings != expected_bindings
            or outcome != expected_outcome
        ):
            reasons.append("host_receipt.admission_binding")
        return reasons

    def complete_attempt(
        self,
        *,
        attempt_id: str,
        adapter_receipt: Mapping[str, Any] | None,
        canonical_result: Mapping[str, Any] | None,
        error_class: str | None,
        retryable: bool,
        allow_unverified_test_runner: bool,
        observed_private_output_sha256: str | None = None,
        observed_private_output_size_bytes: int | None = None,
    ) -> dict[str, Any] | None:
        if adapter_receipt is None and not allow_unverified_test_runner:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                ["signed_adapter_receipt_missing"],
            )
        if adapter_receipt is not None:
            if self.trust_store is None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                    ["runtime_trust_store_missing"],
                )
            signature_reasons = self.trust_store.verify(
                adapter_receipt,
                expected_issuer="runtime_adapter",
            )
            if signature_reasons:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                    signature_reasons,
                )
        with self._transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["state"] != "DISPATCHED":
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    [f"attempt_not_dispatchable:{attempt_id}"],
                )
            if adapter_receipt is not None:
                binding_reasons = self._adapter_receipt_binding_reasons(
                    attempt=attempt,
                    receipt=adapter_receipt,
                    canonical_result=canonical_result,
                    observed_private_output_sha256=observed_private_output_sha256,
                    observed_private_output_size_bytes=observed_private_output_size_bytes,
                )
                if binding_reasons:
                    raise ResearchOrganizationError(
                        BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                        binding_reasons,
                    )
            run = connection.execute(
                "SELECT state, cancel_seq FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if canonical_result is not None and (
                run["state"] in {"CANCELLING", "CANCELLED"}
                or run["cancel_seq"] is not None
            ):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
                    ["ledger_cancel_fence"],
                )
            adapter_session = (
                adapter_receipt.get("session")
                if isinstance(adapter_receipt, Mapping)
                and isinstance(adapter_receipt.get("session"), dict)
                else {}
            )
            if adapter_receipt is not None:
                reused_provider_handle = connection.execute(
                    """
                    SELECT attempt_id FROM attempts
                    WHERE provider_handle_sha256=? AND attempt_id<>?
                    """,
                    (
                        adapter_session["provider_handle_sha256"],
                        attempt_id,
                    ),
                ).fetchone()
                reused_receipt = connection.execute(
                    "SELECT receipt_id FROM receipts WHERE receipt_id=?",
                    (adapter_receipt["receipt_id"],),
                ).fetchone()
                if reused_provider_handle is not None or reused_receipt is not None:
                    raise ResearchOrganizationError(
                        BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                        ["adapter_session_or_receipt_reused"],
                    )
            evidence_class = "unverified_test"
            if adapter_receipt is not None:
                evidence_class = (
                    "signed_adapter"
                    if isinstance(adapter_session.get("container_image_digest"), str)
                    and re.fullmatch(
                        r"sha256:[0-9a-f]{64}",
                        str(adapter_session["container_image_digest"]),
                    )
                    else "signed_adapter_unpinned"
                )
            effective_retryable = retryable if canonical_result is None else False
            completion_sequence = self._append_event(
                connection,
                event_type=(
                    "SESSION_CANDIDATE_READY"
                    if canonical_result is not None
                    else "SESSION_FAILED"
                ),
                role_id=attempt["role_id"],
                attempt_id=attempt_id,
                detail={
                    "adapter_receipt_id": (
                        adapter_receipt.get("receipt_id")
                        if adapter_receipt is not None
                        else None
                    ),
                    "evidence_class": evidence_class,
                    "retryable": effective_retryable,
                    "error_class": error_class,
                },
            )
            if adapter_receipt is not None:
                self._insert_receipt(
                    connection,
                    receipt=adapter_receipt,
                    receipt_type=str(adapter_receipt.get("receipt_type") or "COMPLETED"),
                    issuer_kind="runtime_adapter",
                    event_seq=completion_sequence,
                )
            if canonical_result is None:
                max_attempts = int(self.policy["max_attempts_per_role"])
                task_state = (
                    "RETRY_WAIT"
                    if effective_retryable and int(attempt["attempt_no"]) < max_attempts
                    else "FAILED_FINAL"
                )
                connection.execute(
                    """
                    UPDATE attempts SET state=?, finished_at_utc=?,
                        adapter_receipt_id=?, evidence_class=?, error_class=?, retryable=?,
                        private_output_sha256=?, private_output_size_bytes=?
                    WHERE attempt_id=?
                    """,
                    (
                        "FAILED_RETRYABLE" if task_state == "RETRY_WAIT" else "FAILED_FINAL",
                        utc_now(),
                        adapter_receipt.get("receipt_id") if adapter_receipt else None,
                        evidence_class,
                        error_class,
                        1 if effective_retryable else 0,
                        observed_private_output_sha256,
                        observed_private_output_size_bytes,
                        attempt_id,
                    ),
                )
                if adapter_receipt is not None:
                    connection.execute(
                        """
                        UPDATE attempts SET provider_handle_sha256=?,
                            adapter_build_sha256=?, container_image_digest=?
                        WHERE attempt_id=?
                        """,
                        (
                            adapter_session["provider_handle_sha256"],
                            adapter_session["adapter_build_sha256"],
                            adapter_session["container_image_digest"],
                            attempt_id,
                        ),
                    )
                connection.execute(
                    "UPDATE tasks SET state=?, last_error=? WHERE role_id=?",
                    (task_state, error_class, attempt["role_id"]),
                )
                return None

            result_sha256 = canonical_result.get("result_sha256")
            if not isinstance(result_sha256, str):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["canonical_result_sha256_missing"],
                )
            admission_sequence = self._next_event_seq(connection)
            dependency_admissions = _json(attempt["dependency_admissions_json"])
            if self.trust_store is None:
                host_receipt = {
                    "contract_version": "factorforge_unsigned_test_admission_v1",
                    "receipt_id": stable_json_hash(
                        {
                            "attempt_id": attempt_id,
                            "result_sha256": result_sha256,
                            "event_seq": admission_sequence,
                        }
                    ),
                    "receipt_type": "RESULT_ADMITTED",
                    "issuer": {"kind": "unverified_test", "key_id": None},
                }
            else:
                host_receipt = self.trust_store.sign(
                    "host_admission",
                    {
                        "receipt_type": "RESULT_ADMITTED",
                        "identity": {
                            **self.identity,
                            "runtime_id": self.runtime_id,
                            "task_id": attempt["task_id"],
                            "role_id": attempt["role_id"],
                            "attempt_id": attempt_id,
                        },
                        "ordering": {
                            "event_seq": admission_sequence,
                            "scheduler_epoch": int(attempt["scheduler_epoch"]),
                            "dispatch_event_seq": int(attempt["dispatch_event_seq"]),
                            "issued_at_utc": utc_now(),
                        },
                        "bindings": {
                            "plan_sha256": self.plan_sha256,
                            "task_sha256": self.tasks[attempt["role_id"]]["task_sha256"],
                            "context_manifest_sha256": attempt[
                                "context_manifest_sha256"
                            ],
                            "dependency_admissions": dependency_admissions,
                            "adapter_receipt_id": (
                                adapter_receipt.get("receipt_id")
                                if adapter_receipt is not None
                                else None
                            ),
                            "result_sha256": result_sha256,
                        },
                        "outcome": {
                            "result_status": canonical_result.get("status"),
                            "evidence_class": evidence_class,
                        },
                    },
                )
            event_payload = {
                "host_receipt_id": host_receipt["receipt_id"],
                "adapter_receipt_id": (
                    adapter_receipt.get("receipt_id")
                    if adapter_receipt is not None
                    else None
                ),
                "result_sha256": result_sha256,
                "evidence_class": evidence_class,
            }
            actual_admission_sequence = self._append_event(
                connection,
                event_type="RESULT_ADMITTED",
                role_id=attempt["role_id"],
                attempt_id=attempt_id,
                detail=event_payload,
            )
            if actual_admission_sequence != admission_sequence:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["admission_event_sequence_race"],
                )
            self._insert_receipt(
                connection,
                receipt=host_receipt,
                receipt_type="RESULT_ADMITTED",
                issuer_kind=(
                    "host_admission" if self.trust_store is not None else "unverified_test"
                ),
                event_seq=admission_sequence,
            )
            connection.execute(
                """
                INSERT INTO admissions (
                    role_id, task_id, result_status, result_sha256, result_json,
                    adapter_receipt_id, host_receipt_id, event_seq, evidence_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt["role_id"],
                    attempt["task_id"],
                    canonical_result.get("status"),
                    result_sha256,
                    _canonical_json(canonical_result),
                    adapter_receipt.get("receipt_id") if adapter_receipt else None,
                    host_receipt["receipt_id"],
                    admission_sequence,
                    evidence_class,
                ),
            )
            if adapter_receipt is not None:
                connection.execute(
                    """
                    UPDATE attempts SET provider_handle_sha256=?,
                        adapter_build_sha256=?, container_image_digest=?
                    WHERE attempt_id=?
                    """,
                    (
                        adapter_session["provider_handle_sha256"],
                        adapter_session["adapter_build_sha256"],
                        adapter_session["container_image_digest"],
                        attempt_id,
                    ),
                )
            connection.execute(
                """
                UPDATE attempts SET state='SUCCEEDED', finished_at_utc=?,
                    adapter_receipt_id=?, evidence_class=?, error_class=NULL,
                    retryable=0, private_output_sha256=?,
                    private_output_size_bytes=? WHERE attempt_id=?
                """,
                (
                    utc_now(),
                    adapter_receipt.get("receipt_id") if adapter_receipt else None,
                    evidence_class,
                    observed_private_output_sha256,
                    observed_private_output_size_bytes,
                    attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE tasks SET state=?, result_status=?, admitted_result_sha256=?,
                    admission_receipt_id=?, last_error=NULL WHERE role_id=?
                """,
                (
                    "ADMITTED_PASS"
                    if canonical_result.get("status") == "PASS"
                    else "ADMITTED_NONPASS",
                    canonical_result.get("status"),
                    result_sha256,
                    host_receipt["receipt_id"],
                    attempt["role_id"],
                ),
            )
            return host_receipt

    def import_host_result(
        self,
        *,
        role_id: str,
        result: Mapping[str, Any],
        allow_unverified_test_runner: bool = False,
    ) -> dict[str, Any]:
        task = self.tasks[role_id]
        if task["session_policy"]["requirement"] != "host_session":
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"non_host_result_injection:{role_id}"],
            )
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT result_sha256, host_receipt_id FROM admissions WHERE role_id=?",
                (role_id,),
            ).fetchone()
            if existing is not None:
                if existing["result_sha256"] != result.get("result_sha256"):
                    raise ResearchOrganizationError(
                        BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                        [f"host_result_changed:{role_id}"],
                    )
                receipt = connection.execute(
                    "SELECT payload_json FROM receipts WHERE receipt_id=?",
                    (existing["host_receipt_id"],),
                ).fetchone()
                return _json(receipt["payload_json"])
            run = connection.execute(
                "SELECT state, cancel_seq, scheduler_epoch FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if run["state"] in {"CANCELLING", "CANCELLED"} or run["cancel_seq"] is not None:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
                    ["ledger_cancel_fence"],
                )
            event_seq = self._next_event_seq(connection)
            unsigned_payload = {
                    "receipt_type": "HOST_RESULT_IMPORTED",
                    "identity": {
                        **self.identity,
                        "runtime_id": self.runtime_id,
                        "task_id": task["task_id"],
                        "role_id": role_id,
                    },
                    "ordering": {
                        "event_seq": event_seq,
                        "scheduler_epoch": int(run["scheduler_epoch"]),
                        "issued_at_utc": utc_now(),
                    },
                    "bindings": {
                        "plan_sha256": self.plan_sha256,
                        "task_sha256": task["task_sha256"],
                        "result_sha256": result["result_sha256"],
                    },
                    "outcome": {
                        "result_status": result.get("status"),
                        "evidence_class": (
                            "host_external_session"
                            if self.trust_store is not None
                            else "unverified_test"
                        ),
                    },
                }
            if self.trust_store is not None:
                receipt = self.trust_store.sign(
                    "host_admission",
                    unsigned_payload,
                )
                evidence_class = "host_external_session"
                issuer_kind = "host_admission"
            elif allow_unverified_test_runner:
                receipt = {
                    **unsigned_payload,
                    "contract_version": "factorforge_unsigned_test_admission_v1",
                    "issuer": {"kind": "unverified_test", "key_id": None},
                    "receipt_id": stable_json_hash(unsigned_payload),
                }
                evidence_class = "unverified_test"
                issuer_kind = "unverified_test"
            else:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["host_admission_trust_store_missing"],
                )
            actual_seq = self._append_event(
                connection,
                event_type="HOST_RESULT_IMPORTED",
                role_id=role_id,
                attempt_id=None,
                detail={
                    "host_receipt_id": receipt["receipt_id"],
                    "result_sha256": result["result_sha256"],
                },
            )
            if actual_seq != event_seq:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                    ["host_import_event_sequence_race"],
                )
            self._insert_receipt(
                connection,
                receipt=receipt,
                receipt_type="HOST_RESULT_IMPORTED",
                issuer_kind=issuer_kind,
                event_seq=event_seq,
            )
            connection.execute(
                """
                INSERT INTO admissions (
                    role_id, task_id, result_status, result_sha256, result_json,
                    adapter_receipt_id, host_receipt_id, event_seq, evidence_class
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    role_id,
                    task["task_id"],
                    result.get("status"),
                    result["result_sha256"],
                    _canonical_json(result),
                    receipt["receipt_id"],
                    event_seq,
                    evidence_class,
                ),
            )
            connection.execute(
                """
                UPDATE tasks SET state=?, result_status=?, admitted_result_sha256=?,
                    admission_receipt_id=? WHERE role_id=?
                """,
                (
                    "ADMITTED_PASS"
                    if result.get("status") == "PASS"
                    else "ADMITTED_NONPASS",
                    result.get("status"),
                    result["result_sha256"],
                    receipt["receipt_id"],
                    role_id,
                ),
            )
            return receipt

    def request_cancel(self, *, requested_by: str, reason: str) -> int:
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT state, cancel_seq FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if run["cancel_seq"] is not None:
                return int(run["cancel_seq"])
            sequence = self._append_event(
                connection,
                event_type="CANCEL_REQUESTED",
                role_id=None,
                attempt_id=None,
                detail={"requested_by": requested_by, "reason": reason},
            )
            connection.execute(
                """
                UPDATE runs SET state='CANCELLING', cancel_seq=?, updated_at_utc=?
                WHERE runtime_id=?
                """,
                (sequence, utc_now(), self.runtime_id),
            )
            return sequence

    def finish_scheduler(self) -> str:
        with self._transaction() as connection:
            task_rows = connection.execute("SELECT * FROM tasks").fetchall()
            states = {row["state"] for row in task_rows}
            statuses = {row["result_status"] for row in task_rows if row["result_status"]}
            run = connection.execute(
                "SELECT state, cancel_seq FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if run["cancel_seq"] is not None:
                state = "CANCELLING" if "RUNNING" in states else "CANCELLED"
            elif "NEEDS_DATA" in statuses:
                state = "WAITING_DATA"
            elif "NEEDS_CLARIFICATION" in statuses:
                state = "WAITING_CLARIFICATION"
            elif "BLOCK" in statuses:
                state = "BLOCKED"
            elif states and all(item == "ADMITTED_PASS" for item in states):
                state = "COMPLETE"
            elif "FAILED_FINAL" in states:
                state = "FAILED"
            elif any(
                self.tasks[row["role_id"]]["session_policy"]["requirement"]
                == "host_session"
                and row["state"] == "PENDING"
                for row in task_rows
            ):
                state = "WAITING_HOST_RESULT"
            else:
                state = "ACTIVE"
            self._append_event(
                connection,
                event_type="SCHEDULER_EPOCH_FINISHED",
                role_id=None,
                attempt_id=None,
                detail={"state": state},
            )
            connection.execute(
                "UPDATE runs SET state=?, updated_at_utc=? WHERE runtime_id=?",
                (state, utc_now(), self.runtime_id),
            )
            return state

    def canonical_results(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role_id, result_json FROM admissions"
            ).fetchall()
            return {row["role_id"]: _json(row["result_json"]) for row in rows}

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            tasks = connection.execute("SELECT * FROM tasks ORDER BY role_id").fetchall()
            attempts = connection.execute(
                "SELECT * FROM attempts ORDER BY dispatch_event_seq"
            ).fetchall()
            admissions = connection.execute(
                "SELECT * FROM admissions ORDER BY event_seq"
            ).fetchall()
            return {
                "contract_version": LEDGER_CONTRACT_VERSION,
                "runtime_id": self.runtime_id,
                "state": run["state"],
                "scheduler_epoch": int(run["scheduler_epoch"]),
                "cancel_seq": run["cancel_seq"],
                "trust_manifest": (
                    _json(run["trust_manifest_json"])
                    if run["trust_manifest_json"]
                    else None
                ),
                "tasks": {
                    row["role_id"]: {
                        "state": row["state"],
                        "attempt_count": int(row["attempt_count"]),
                        "result_status": row["result_status"],
                        "admission_receipt_id": row["admission_receipt_id"],
                    }
                    for row in tasks
                },
                "attempt_count": len(attempts),
                "admission_count": len(admissions),
            }

    def validate(self, *, require_formal: bool = False) -> dict[str, Any]:
        reasons: list[str] = []
        with self._connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                reasons.append(f"ledger_integrity:{integrity}")
            self._validate_static_binding(connection)
            events = connection.execute(
                "SELECT * FROM events ORDER BY event_seq"
            ).fetchall()
            previous: str | None = None
            event_map: dict[int, dict[str, Any]] = {}
            for expected_seq, event in enumerate(events, start=1):
                payload = _json(event["payload_json"])
                if (
                    set(payload)
                    != {
                        "contract_version",
                        "runtime_id",
                        "identity",
                        "event_seq",
                        "event_type",
                        "role_id",
                        "attempt_id",
                        "previous_event_sha256",
                        "occurred_at_utc",
                        "detail",
                    }
                    or payload.get("contract_version")
                    != "factorforge_research_org_ledger_event_v1"
                    or payload.get("runtime_id") != self.runtime_id
                    or payload.get("identity") != self.identity
                    or int(event["event_seq"]) != expected_seq
                    or payload.get("event_seq") != expected_seq
                    or payload.get("event_type") != event["event_type"]
                    or payload.get("role_id") != event["role_id"]
                    or payload.get("attempt_id") != event["attempt_id"]
                    or payload.get("previous_event_sha256") != previous
                    or event["previous_event_sha256"] != previous
                    or payload.get("occurred_at_utc") != event["occurred_at_utc"]
                    or not isinstance(payload.get("detail"), dict)
                    or stable_json_hash(payload) != event["event_sha256"]
                ):
                    reasons.append(f"ledger_event_chain:{expected_seq}")
                previous = event["event_sha256"]
                event_map[expected_seq] = payload
            receipts = connection.execute("SELECT * FROM receipts").fetchall()
            receipt_map = {row["receipt_id"]: row for row in receipts}
            receipt_payloads = {
                row["receipt_id"]: _json(row["payload_json"]) for row in receipts
            }
            admissions = connection.execute(
                "SELECT * FROM admissions ORDER BY event_seq"
            ).fetchall()
            admission_map = {row["role_id"]: row for row in admissions}
            attempts = connection.execute(
                "SELECT * FROM attempts ORDER BY dispatch_event_seq"
            ).fetchall()
            attempt_by_adapter_receipt = {
                row["adapter_receipt_id"]: row
                for row in attempts
                if row["adapter_receipt_id"] is not None
            }
            for row in receipts:
                receipt = receipt_payloads[row["receipt_id"]]
                issuer = receipt.get("issuer") if isinstance(receipt.get("issuer"), dict) else {}
                receipt_event = event_map.get(int(row["event_seq"]))
                if (
                    receipt.get("receipt_id") != row["receipt_id"]
                    or receipt.get("receipt_type") != row["receipt_type"]
                    or issuer.get("kind") != row["issuer_kind"]
                    or receipt_event is None
                ):
                    reasons.append(f"ledger_receipt_identity:{row['receipt_id']}")
                    continue
                if row["issuer_kind"] in {"runtime_adapter", "host_admission"}:
                    if self.trust_store is None:
                        reasons.append("ledger_trust_store_missing")
                    else:
                        reasons.extend(
                            f"{row['receipt_id']}:{reason}"
                            for reason in self.trust_store.verify(
                                receipt,
                                expected_issuer=row["issuer_kind"],
                            )
                        )
            for admission in admissions:
                result = _json(admission["result_json"])
                expected_task = self.tasks[str(admission["role_id"])]
                host_row = receipt_map.get(admission["host_receipt_id"])
                host_receipt = (
                    receipt_payloads.get(admission["host_receipt_id"])
                    if host_row is not None
                    else None
                )
                attempt = (
                    attempt_by_adapter_receipt.get(admission["adapter_receipt_id"])
                    if admission["adapter_receipt_id"] is not None
                    else next(
                        (
                            row
                            for row in attempts
                            if row["role_id"] == admission["role_id"]
                            and row["state"] == "SUCCEEDED"
                        ),
                        None,
                    )
                    if expected_task["session_policy"]["requirement"]
                    != "host_session"
                    else None
                )
                admission_event = event_map.get(int(admission["event_seq"]))
                expected_event_type = (
                    "RESULT_ADMITTED" if attempt is not None else "HOST_RESULT_IMPORTED"
                )
                expected_event_detail = (
                    {
                        "host_receipt_id": admission["host_receipt_id"],
                        "adapter_receipt_id": admission["adapter_receipt_id"],
                        "result_sha256": admission["result_sha256"],
                        "evidence_class": admission["evidence_class"],
                    }
                    if attempt is not None
                    else {
                        "host_receipt_id": admission["host_receipt_id"],
                        "result_sha256": admission["result_sha256"],
                    }
                )
                if (
                    result.get("result_sha256") != admission["result_sha256"]
                    or result.get("status") != admission["result_status"]
                    or validate_content_hash(
                        result,
                        hash_field="result_sha256",
                        label="ledger_result",
                    )
                    or result.get("identity") != self.identity
                    or result.get("role_id") != admission["role_id"]
                    or result.get("task_ref")
                    != {
                        "task_id": admission["task_id"],
                        "sha256": expected_task["task_sha256"],
                    }
                    or host_row is None
                    or int(host_row["event_seq"]) != int(admission["event_seq"])
                    or host_receipt is None
                    or admission_event is None
                    or admission_event.get("event_type") != expected_event_type
                    or admission_event.get("role_id") != admission["role_id"]
                    or admission_event.get("attempt_id")
                    != (attempt["attempt_id"] if attempt is not None else None)
                    or admission_event.get("detail") != expected_event_detail
                    or (
                        attempt is None
                        and expected_task["session_policy"]["requirement"]
                        != "host_session"
                    )
                    or (
                        attempt is not None
                        and expected_task["session_policy"]["requirement"]
                        == "host_session"
                    )
                ):
                    reasons.append(f"ledger_admission_binding:{admission['role_id']}")
                if host_row is not None and host_row["issuer_kind"] == "host_admission":
                    reasons.extend(
                        f"{admission['host_receipt_id']}:{reason}"
                        for reason in self._host_receipt_binding_reasons(
                            admission=admission,
                            receipt=host_receipt or {},
                            attempt=attempt,
                        )
                    )
            for attempt in attempts:
                bindings = _json(attempt["dependency_admissions_json"])
                task = self.tasks[str(attempt["role_id"])]
                expected_dependency_roles = list(task.get("depends_on_roles") or [])
                if attempt["role_id"] == "independent_council":
                    expected_dependency_roles = list(
                        task.get("required_review_role_ids") or []
                    )
                dispatch_event = event_map.get(int(attempt["dispatch_event_seq"]))
                if (
                    attempt["task_id"] != task["task_id"]
                    or [item.get("role_id") for item in bindings]
                    != expected_dependency_roles
                    or dispatch_event is None
                    or dispatch_event.get("event_type") != "SESSION_DISPATCHED"
                    or dispatch_event.get("role_id") != attempt["role_id"]
                    or dispatch_event.get("attempt_id") != attempt["attempt_id"]
                    or dispatch_event.get("detail")
                    != {
                        "scheduler_epoch": int(attempt["scheduler_epoch"]),
                        "session_uid": attempt["session_uid"],
                        "idempotency_key": attempt["idempotency_key"],
                        "dependencies": bindings,
                    }
                    or hashlib.sha256(
                        str(attempt["runtime_handle"]).encode("utf-8")
                    ).hexdigest()
                    != attempt["runtime_handle_sha256"]
                ):
                    reasons.append(f"ledger_attempt_binding:{attempt['attempt_id']}")
                for binding in bindings:
                    dependency = admission_map.get(binding.get("role_id"))
                    if (
                        dependency is None
                        or dependency["result_status"] != "PASS"
                        or dependency["result_sha256"]
                        != binding.get("result_sha256")
                        or dependency["host_receipt_id"]
                        != binding.get("admission_receipt_id")
                        or int(dependency["event_seq"]) != binding.get("event_seq")
                        or int(dependency["event_seq"])
                        >= int(attempt["dispatch_event_seq"])
                    ):
                        reasons.append(
                            f"ledger_dependency_binding:{attempt['attempt_id']}"
                        )
                if (
                    attempt["role_id"] == "independent_council"
                    and attempt["parent_session_uid"] is not None
                ):
                    reasons.append("ledger_council_parent_session")
                adapter_row = (
                    receipt_map.get(attempt["adapter_receipt_id"])
                    if attempt["adapter_receipt_id"] is not None
                    else None
                )
                admitted = admission_map.get(attempt["role_id"])
                admitted_for_attempt = (
                    admitted
                    if admitted is not None
                    and (
                        (
                            attempt["adapter_receipt_id"] is not None
                            and admitted["adapter_receipt_id"]
                            == attempt["adapter_receipt_id"]
                        )
                        or (
                            attempt["adapter_receipt_id"] is None
                            and admitted["adapter_receipt_id"] is None
                            and attempt["state"] == "SUCCEEDED"
                        )
                    )
                    else None
                )
                if adapter_row is not None:
                    adapter_receipt = receipt_payloads[attempt["adapter_receipt_id"]]
                    canonical_result = (
                        _json(admitted_for_attempt["result_json"])
                        if admitted_for_attempt is not None
                        else None
                    )
                    reasons.extend(
                        f"{attempt['adapter_receipt_id']}:{reason}"
                        for reason in self._adapter_receipt_binding_reasons(
                            attempt=attempt,
                            receipt=adapter_receipt,
                            canonical_result=canonical_result,
                            observed_private_output_sha256=attempt[
                                "private_output_sha256"
                            ],
                            observed_private_output_size_bytes=attempt[
                                "private_output_size_bytes"
                            ],
                        )
                    )
                    session = adapter_receipt.get("session", {})
                    completion_event = event_map.get(int(adapter_row["event_seq"]))
                    if (
                        adapter_row["issuer_kind"] != "runtime_adapter"
                        or session.get("provider_handle_sha256")
                        != attempt["provider_handle_sha256"]
                        or session.get("adapter_build_sha256")
                        != attempt["adapter_build_sha256"]
                        or session.get("container_image_digest")
                        != attempt["container_image_digest"]
                        or completion_event is None
                        or completion_event.get("event_type")
                        != (
                            "SESSION_CANDIDATE_READY"
                            if admitted_for_attempt is not None
                            else "SESSION_FAILED"
                        )
                        or completion_event.get("role_id") != attempt["role_id"]
                        or completion_event.get("attempt_id") != attempt["attempt_id"]
                        or completion_event.get("detail")
                        != {
                            "adapter_receipt_id": attempt["adapter_receipt_id"],
                            "evidence_class": attempt["evidence_class"],
                            "retryable": bool(attempt["retryable"]),
                            "error_class": attempt["error_class"],
                        }
                    ):
                        reasons.append(
                            f"ledger_adapter_binding:{attempt['attempt_id']}"
                        )
                elif attempt["adapter_receipt_id"] is not None:
                    reasons.append(f"ledger_adapter_missing:{attempt['attempt_id']}")
                if attempt["state"] == "SUCCEEDED" and (
                    admitted_for_attempt is None
                    or attempt["finished_at_utc"] is None
                    or attempt["private_output_sha256"] is None
                    or attempt["private_output_size_bytes"] is None
                ):
                    reasons.append(f"ledger_attempt_success:{attempt['attempt_id']}")
                if attempt["state"] in {"FAILED_RETRYABLE", "FAILED_FINAL", "LOST"} and (
                    admitted_for_attempt is not None or attempt["finished_at_utc"] is None
                ):
                    reasons.append(f"ledger_attempt_failure:{attempt['attempt_id']}")
                if attempt["state"] == "DISPATCHED" and (
                    attempt["finished_at_utc"] is not None
                    or attempt["adapter_receipt_id"] is not None
                ):
                    reasons.append(f"ledger_attempt_active:{attempt['attempt_id']}")
            task_rows = connection.execute("SELECT * FROM tasks").fetchall()
            for task_row in task_rows:
                role_id = str(task_row["role_id"])
                role_attempts = [row for row in attempts if row["role_id"] == role_id]
                admission = admission_map.get(role_id)
                if (
                    int(task_row["attempt_count"]) != len(role_attempts)
                    or [int(row["attempt_no"]) for row in role_attempts]
                    != list(range(1, len(role_attempts) + 1))
                ):
                    reasons.append(f"ledger_task_attempt_count:{role_id}")
                if admission is not None:
                    expected_task_state = (
                        "ADMITTED_PASS"
                        if admission["result_status"] == "PASS"
                        else "ADMITTED_NONPASS"
                    )
                    if (
                        task_row["state"] != expected_task_state
                        or task_row["result_status"] != admission["result_status"]
                        or task_row["admitted_result_sha256"]
                        != admission["result_sha256"]
                        or task_row["admission_receipt_id"]
                        != admission["host_receipt_id"]
                    ):
                        reasons.append(f"ledger_task_admission:{role_id}")
                elif any(
                    task_row[field] is not None
                    for field in (
                        "result_status",
                        "admitted_result_sha256",
                        "admission_receipt_id",
                    )
                ):
                    reasons.append(f"ledger_task_unadmitted_result:{role_id}")
            complete = bool(task_rows) and all(
                row["state"] == "ADMITTED_PASS" for row in task_rows
            )
            signed_specialist_roles = {
                row["role_id"]
                for row in admissions
                if row["evidence_class"] == "signed_adapter"
            }
            expected_specialist_roles = {
                role_id
                for role_id, task in self.tasks.items()
                if task["session_policy"]["requirement"] != "host_session"
            }
            run = connection.execute(
                "SELECT state FROM runs WHERE runtime_id=?",
                (self.runtime_id,),
            ).fetchone()
            if (run["state"] == "COMPLETE") != complete:
                reasons.append("ledger_run_state_not_derived")
            all_host_receipts_signed = all(
                receipt_map.get(row["host_receipt_id"]) is not None
                and receipt_map[row["host_receipt_id"]]["issuer_kind"]
                == "host_admission"
                for row in admissions
            )
            all_attempts_terminal = all(
                row["state"] != "DISPATCHED" for row in attempts
            )
            all_attempt_projections_bound = all(
                row["attempt_projection_sha256"] is not None
                and row["receipt_projection_sha256"] is not None
                for row in attempts
            )
            formal = (
                complete
                and run["state"] == "COMPLETE"
                and signed_specialist_roles == expected_specialist_roles
                and self.trust_store is not None
                and all_host_receipts_signed
                and all_attempts_terminal
                and all_attempt_projections_bound
                and "independent_council" in signed_specialist_roles
                and not reasons
            )
            if require_formal and not formal:
                reasons.append("formal_signed_runtime_not_satisfied")
        if reasons:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                reasons,
            )
        return {
            "verdict": "PASS",
            "runtime_id": self.runtime_id,
            "ledger_state": self.snapshot()["state"],
            "formal_independence_verified": formal,
            "assurance": (
                "signed_specialist_runtime_complete_host_director_external"
                if formal
                else "transactional_runtime_unverified_sessions"
            ),
            "ledger_path": str(self.path),
        }
