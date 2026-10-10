"""One transactional journal for proposals, reservations, tickets and feedback.

SQLite transactions make reservation durable before dispatch. Running callbacks
never hold a database lock. A dispatch whose completion is unknown is reconciled,
not retried; every state transition retains a durable event.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .contracts import (PENDING, SearchError, bound_json, canonical, digest,
                        file_ref, reservation_cost, validate_context, validate_proposal)
from .native import validate_request, validate_preparation


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchLedger:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()
        if not self.root.is_dir():
            raise SearchError("existing workspace required")
        self.path = self.root / "objects/research_search/ledger.sqlite3"

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def create_campaign(self, context: Mapping[str, Any]) -> dict:
        c = validate_context(context)
        if Path(c["workspace_root"]).resolve() != self.root:
            raise SearchError("ledger workspace/context mismatch")
        authority = bound_json(c["budget_authority"])
        source_identity = file_ref(Path(authority["source_authority_ref"]["path"]).resolve())
        state_identity = file_ref(Path(authority["state_ref"]["path"]).resolve())
        budget_key = digest({"root": str(self.root), "source": source_identity["path"]})
        limits = {"source": source_identity, "state": state_identity,
                  "trial_budget": authority["trial_budget"], "trials_used": authority["trials_used"],
                  "compute_budget": authority["compute_budget"], "execution_cost_policy": authority["execution_cost_policy"]}
        with self.transaction() as db:
            for sql in (
                "CREATE TABLE IF NOT EXISTS budgets (id TEXT PRIMARY KEY, limits_json TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, context_json TEXT NOT NULL, context_hash TEXT NOT NULL, budget_id TEXT NOT NULL REFERENCES budgets(id), revision INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS proposals (campaign_id TEXT NOT NULL REFERENCES campaigns(id), candidate_hash TEXT NOT NULL, proposal_json TEXT NOT NULL, request_json TEXT, PRIMARY KEY(campaign_id,candidate_hash))",
                "CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), candidate_hash TEXT NOT NULL, state TEXT NOT NULL, ticket_json TEXT NOT NULL, reserved_cost REAL NOT NULL, actual_cost REAL, feedback_json TEXT, UNIQUE(campaign_id,candidate_hash))",
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, at_utc TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL)",
            ):
                db.execute(sql)
            old_budget = db.execute("SELECT limits_json FROM budgets WHERE id=?", (budget_key,)).fetchone()
            if old_budget and old_budget[0] != canonical(limits):
                raise SearchError("shared budget authority/limits changed; explicit reconciliation required")
            db.execute("INSERT OR IGNORE INTO budgets VALUES (?,?)", (budget_key, canonical(limits)))
            old = db.execute("SELECT context_hash FROM campaigns WHERE id=?", (c["campaign_id"],)).fetchone()
            if old and old[0] != digest(c):
                raise SearchError("campaign context is immutable")
            if not old:
                db.execute("INSERT INTO campaigns(id,context_json,context_hash,budget_id) VALUES (?,?,?,?)",
                           (c["campaign_id"], canonical(c), digest(c), budget_key))
                self._event(db, c["campaign_id"], "campaign_created", {"context_hash": digest(c)})
        return c

    @staticmethod
    def _event(db, campaign, kind, payload):
        db.execute("INSERT INTO events(campaign_id,at_utc,kind,payload_json) VALUES (?,?,?,?)",
                   (campaign, now(), kind, canonical(payload)))
        db.execute("UPDATE campaigns SET revision=revision+1 WHERE id=?", (campaign,))

    @staticmethod
    def _campaign(db, campaign):
        row = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign,)).fetchone()
        if row is None:
            raise SearchError("unknown campaign")
        return row

    def snapshot(self, campaign: str, *, verify_sources: bool = True) -> dict:
        if not self.path.exists():
            raise SearchError("campaign ledger has not been initialized")
        with self.transaction() as db:
            row = self._campaign(db, campaign)
            c = json.loads(row["context_json"])
            proposals = [dict(r) for r in db.execute("SELECT * FROM proposals WHERE campaign_id=? ORDER BY candidate_hash", (campaign,))]
            tickets = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE campaign_id=? ORDER BY id", (campaign,))]
            limits = json.loads(db.execute("SELECT limits_json FROM budgets WHERE id=?", (row["budget_id"],)).fetchone()[0])
            usage = db.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN actual_cost IS NULL THEN reserved_cost ELSE actual_cost END),0) FROM tickets WHERE campaign_id IN (SELECT id FROM campaigns WHERE budget_id=?)", (row["budget_id"],)).fetchone()
        if verify_sources:
            validate_context(c)
        return {"context": c, "revision": row["revision"], "proposals": proposals, "tickets": tickets,
                "remaining_trials": limits["trial_budget"] - limits["trials_used"] - usage[0],
                "remaining_compute": limits["compute_budget"] - usage[1]}

    def register(self, campaign: str, proposals) -> dict:
        snapshot = self.snapshot(campaign)
        c = snapshot["context"]
        checked = [validate_proposal(c, proposal) for proposal in proposals]
        if len(checked) > c["max_proposals"]:
            raise SearchError("proposal batch exceeds limit")
        with self.transaction() as db:
            count = db.execute("SELECT COUNT(*) FROM proposals WHERE campaign_id=?", (campaign,)).fetchone()[0]
            known = {r[0] for r in db.execute("SELECT candidate_hash FROM proposals WHERE campaign_id=?", (campaign,))}
            added, duplicates = [], []
            for p in checked:
                h = p["candidate_hash"]
                parent = p["parent_candidate_hash"]
                if h in known:
                    existing = json.loads(db.execute("SELECT proposal_json FROM proposals WHERE campaign_id=? AND candidate_hash=?", (campaign, h)).fetchone()[0])
                    if existing["parent_candidate_hash"] != parent:
                        raise SearchError("duplicate candidate has ambiguous parent lineage")
                    duplicates.append(h)
                    self._event(db, campaign, "duplicate_proposal", {"candidate_hash": h, "occurrence": p})
                    continue
                if count >= c["max_proposals"]:
                    raise SearchError("campaign proposal cap exhausted")
                if (h == c["root_candidate_hash"]) != (parent is None):
                    raise SearchError("exactly the registered root has no parent")
                if parent is not None and parent not in known:
                    raise SearchError("parent must be registered before its child")
                if parent is not None:
                    old = json.loads(db.execute("SELECT proposal_json FROM proposals WHERE campaign_id=? AND candidate_hash=?", (campaign, parent)).fetchone()[0])
                    if p["mutation_class"] == "implementation_equivalent" and p["semantics"] != old["semantics"]:
                        raise SearchError("implementation-equivalent change altered mathematical/measurement semantics")
                    if p["mutation_class"] == "measurement_variant" and p["semantics"]["mathematical_object"] != old["semantics"]["mathematical_object"]:
                        raise SearchError("measurement variant changed mathematical object")
                    ancestor, depth = parent, 0
                    while ancestor is not None:
                        depth += 1
                        if depth > c["max_depth"]:
                            raise SearchError("proposal exceeds the frozen tree depth")
                        ancestor = json.loads(db.execute("SELECT proposal_json FROM proposals WHERE campaign_id=? AND candidate_hash=?",
                                              (campaign, ancestor)).fetchone()[0])["parent_candidate_hash"]
                db.execute("INSERT INTO proposals VALUES (?,?,?,NULL)", (campaign, h, canonical(p)))
                self._event(db, campaign, "proposal_registered", {"candidate_hash": h})
                known.add(h); added.append(h); count += 1
        return {"registered": added, "duplicates": duplicates}

    def prepare(self, campaign: str, candidate: str, request: Mapping[str, Any]) -> dict:
        snapshot = self.snapshot(campaign)
        rows = [p for p in snapshot["proposals"] if p["candidate_hash"] == candidate]
        if len(rows) != 1:
            raise SearchError("candidate not registered")
        tickets = [t for t in snapshot["tickets"] if t["candidate_hash"] == candidate]
        if len(tickets) != 1 or tickets[0]["state"] not in {"WAITING_PREPARATION", "WAITING_REVIEW"}:
            raise SearchError("reserve and dispatch the research action before Step2/3 preparation")
        r = validate_request(snapshot["context"], json.loads(rows[0]["proposal_json"]), request)
        prep_cost = validate_preparation(r, json.loads(tickets[0]["ticket_json"]))
        if prep_cost > bound_json(snapshot["context"]["budget_authority"])["execution_cost_policy"]["preparation_seconds"]:
            raise SearchError("preparation exceeded its frozen stage allowance")
        with self.transaction() as db:
            ticket_row = db.execute("SELECT * FROM tickets WHERE id=?", (tickets[0]["id"],)).fetchone()
            if ticket_row["state"] not in {"WAITING_PREPARATION", "WAITING_REVIEW"}:
                raise SearchError("preparation state changed")
            row = db.execute("SELECT request_json FROM proposals WHERE campaign_id=? AND candidate_hash=?", (campaign, candidate)).fetchone()
            if row[0] is not None and row[0] != canonical(r):
                raise SearchError("prepared request is immutable")
            if row[0] is None:
                db.execute("UPDATE proposals SET request_json=? WHERE campaign_id=? AND candidate_hash=?", (canonical(r), campaign, candidate))
                ticket = json.loads(ticket_row["ticket_json"])
                ticket.update(native_request=r, state="READY", last_transition=now())
                db.execute("UPDATE tickets SET state='READY',ticket_json=? WHERE id=?", (canonical(ticket), ticket["ticket_id"]))
                self._event(db, campaign, "native_request_prepared", {"candidate_hash": candidate, "request_hash": digest(r)})
        return r

    def reserve(self, campaign: str, candidate: str, selection: Mapping[str, Any], *, expected_revision: int) -> dict:
        snapshot = self.snapshot(campaign)
        c = snapshot["context"]
        rows = [p for p in snapshot["proposals"] if p["candidate_hash"] == candidate]
        if len(rows) != 1:
            raise SearchError("candidate is not registered")
        p = json.loads(rows[0]["proposal_json"])
        cost = reservation_cost(c)
        if (selection.get("candidate_hash") != candidate or selection.get("seed") != c["seed"]
                or selection.get("planner_kind") != c["planner_kind"]
                or not selection.get("path") or selection["path"][-1] != candidate):
            raise SearchError("planner selection mismatch")
        key = digest({"campaign": campaign, "candidate": candidate, "protocol": c["development_protocol"]["sha256"]})
        with self.transaction() as db:
            old = db.execute("SELECT ticket_json FROM tickets WHERE id=?", (key,)).fetchone()
            if old:
                return json.loads(old[0])
            row = self._campaign(db, campaign)
            if row["revision"] != expected_revision:
                raise SearchError("campaign revision changed; replan without dispatch")
            for prior in db.execute("SELECT t.ticket_json,c.context_json FROM tickets t JOIN campaigns c ON c.id=t.campaign_id WHERE c.budget_id=? AND t.candidate_hash=?", (row["budget_id"], candidate)):
                prior_context = json.loads(prior["context_json"])
                if prior_context["development_protocol"]["sha256"] == c["development_protocol"]["sha256"]:
                    raise SearchError("same candidate/protocol already has a shared-budget ticket; use its original campaign")
            active = db.execute("SELECT id FROM tickets WHERE campaign_id=? AND feedback_json IS NULL", (campaign,)).fetchone()
            if active:
                raise SearchError("one active ticket already exists")
            limits = json.loads(db.execute("SELECT limits_json FROM budgets WHERE id=?", (row["budget_id"],)).fetchone()[0])
            usage = db.execute("SELECT COUNT(*),COALESCE(SUM(CASE WHEN actual_cost IS NULL THEN reserved_cost ELSE actual_cost END),0) FROM tickets WHERE campaign_id IN (SELECT id FROM campaigns WHERE budget_id=?)", (row["budget_id"],)).fetchone()
            if limits["trials_used"] + usage[0] >= limits["trial_budget"] or usage[1] + cost > limits["compute_budget"]:
                raise SearchError("shared trial/compute budget exhausted")
            ticket = {"ticket_id": key, "campaign_id": campaign, "candidate_hash": candidate,
                      "context_hash": digest(c), "state": "RESERVED", "attempt_ordinal": 1,
                      "seed": c["seed"], "reservation_id": key, "reserved_trial_units": 1,
                      "reserved_compute_cost": cost, "native_request": None,
                      "proposal": p,
                      "selection": dict(selection), "created_at": now()}
            db.execute("INSERT INTO tickets(id,campaign_id,candidate_hash,state,ticket_json,reserved_cost) VALUES (?,?,?,?,?,?)",
                       (key, campaign, candidate, "RESERVED", canonical(ticket), cost))
            self._event(db, campaign, "reserved", {"ticket_id": key})
        return ticket

    def event(self, campaign: str, kind: str, payload: Mapping[str, Any]) -> None:
        with self.transaction() as db:
            self._campaign(db, campaign)
            self._event(db, campaign, kind, payload)

    def ticket(self, campaign: str, ticket_id: str) -> dict:
        rows = [t for t in self.snapshot(campaign)["tickets"] if t["id"] == ticket_id]
        if len(rows) != 1:
            raise SearchError("unknown ticket in campaign")
        return json.loads(rows[0]["ticket_json"])

    def transition(self, ticket_id: str, expected: set[str], state: str, details: Mapping[str, Any] | None = None) -> dict:
        if state not in PENDING:
            raise SearchError("terminal state requires verified feedback")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None or row["state"] not in expected or row["feedback_json"] is not None:
                raise SearchError("ticket transition lost race or is terminal")
            graph = {"RESERVED": {"DISPATCHING"}, "DISPATCHING": {"WAITING_PREPARATION", "INTERRUPTED"},
                     "WAITING_PREPARATION": {"WAITING_REVIEW", "INTERRUPTED"},
                     "WAITING_REVIEW": {"INTERRUPTED"}, "READY": {"RUNNING", "INTERRUPTED"},
                     "RUNNING": {"INTERRUPTED"}, "INTERRUPTED": {"WAITING_PREPARATION"}}
            if state not in graph.get(row["state"], set()):
                raise SearchError("illegal research ticket state transition")
            ticket = json.loads(row["ticket_json"])
            ticket.update(state=state, last_transition=now(), transition_details=dict(details or {}))
            db.execute("UPDATE tickets SET state=?,ticket_json=? WHERE id=?", (state, canonical(ticket), ticket_id))
            self._event(db, row["campaign_id"], state.lower(), {"ticket_id": ticket_id, "details": dict(details or {})})
            return ticket

    def record_feedback(self, ticket_id: str, result_ref: Mapping[str, Any]) -> dict:
        from .native import collect_result
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                raise SearchError("unknown ticket")
            context = json.loads(self._campaign(db, row["campaign_id"])["context_json"])
            proposal = json.loads(db.execute("SELECT proposal_json FROM proposals WHERE campaign_id=? AND candidate_hash=?",
                                             (row["campaign_id"], row["candidate_hash"])).fetchone()[0])
            ticket = json.loads(row["ticket_json"])
        f = collect_result(context, proposal, ticket, result_ref)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None or row["candidate_hash"] != f.get("candidate_hash"):
                raise SearchError("feedback ticket/candidate mismatch")
            if row["feedback_json"]:
                if row["feedback_json"] != canonical(f):
                    raise SearchError("terminal feedback is immutable")
                return json.loads(row["feedback_json"])
            preparation_stop = ticket.get("native_request") is None and f["status"] == "BLOCKED"
            if row["state"] not in {"RUNNING", "INTERRUPTED"} and not (
                    preparation_stop and row["state"] in {"WAITING_PREPARATION", "WAITING_REVIEW"}):
                raise SearchError("terminal feedback requires an actual native dispatch")
            ticket = json.loads(row["ticket_json"])
            ticket.update(state=f["status"], last_transition=now())
            db.execute("UPDATE tickets SET state=?,ticket_json=?,feedback_json=?,actual_cost=? WHERE id=?",
                       (f["status"], canonical(ticket), canonical(f), f["actual_cost"], ticket_id))
            self._event(db, row["campaign_id"], "feedback_recorded", {"ticket_id": ticket_id, "feedback_hash": digest(f)})
        return f
