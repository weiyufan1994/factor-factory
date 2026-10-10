"""Host-driven search lifecycle; one tick never starts two research actions."""
from __future__ import annotations

import json
from typing import Any

from .contracts import (CandidateProposer, NativeExecutor, SearchError, bound_json,
                        candidate_hash, digest, file_ref, reservation_cost, text, PROPOSAL_VERSION)
from .ledger import SearchLedger
from .native import collect_result
from .planner import plan_next


class ResearchSearchController:
    def __init__(self, ledger: SearchLedger, campaign_id: str, executor: NativeExecutor):
        self.ledger, self.campaign_id, self.executor = ledger, campaign_id, executor

    def _feedback(self, snapshot: dict) -> list[dict]:
        proposals = {p["candidate_hash"]: json.loads(p["proposal_json"]) for p in snapshot["proposals"]}
        feedback = []
        for row in snapshot["tickets"]:
            if row["feedback_json"] is None:
                continue
            old = json.loads(row["feedback_json"])
            fresh = collect_result(snapshot["context"], proposals[row["candidate_hash"]],
                                   json.loads(row["ticket_json"]), old["evidence_ref"])
            if fresh != old:
                raise SearchError("cached native feedback no longer reproduces")
            feedback.append(old)
        return feedback

    def proposer_context(self) -> dict[str, Any]:
        snapshot = self.ledger.snapshot(self.campaign_id)
        c = snapshot["context"]
        source = bound_json(c["projection_ref"])
        # No raw source paths, data refs, execution credentials or held-out arrays.
        proposals = [json.loads(p["proposal_json"]) for p in snapshot["proposals"]]
        return {"contract_version": "factor_search_proposer_input_v1", "context_hash": digest(c),
                "research_question": source["research_question"], "revision_laws": source["revision_laws"],
                "prior_exposure": source["prior_exposure"], "allowed_mutation_classes": c["allowed_mutation_classes"],
                "root_candidate_hash": c["root_candidate_hash"],
                "candidates": [{k: p[k] for k in ("candidate_hash", "parent_candidate_hash", "program", "semantics",
                                                  "expected_metric_signature", "falsifiers", "kill_criteria")} for p in proposals],
                "development_feedback": [{k: f[k] for k in ("candidate_hash", "status", "candidate_score",
                                                             "learning_increment", "actual_cost", "data_kind")} for f in self.verified_feedback(snapshot)]}

    def verified_feedback(self, snapshot: dict | None = None) -> list[dict]:
        """Return replay-verified terminal feedback; pending tickets are absent."""
        return self._feedback(snapshot or self.ledger.snapshot(self.campaign_id))

    def propose(self, provider: CandidateProposer) -> dict:
        context = self.proposer_context()
        snapshot = self.ledger.snapshot(self.campaign_id)
        limit = snapshot["context"]["max_proposals"]
        # Claim a bounded proposer attempt before calling a potentially costly provider.
        with self.ledger.transaction() as db:
            used = db.execute("SELECT COUNT(*) FROM events WHERE campaign_id=? AND kind='proposer_started'", (self.campaign_id,)).fetchone()[0]
            if used >= limit:
                raise SearchError("proposer call budget exhausted")
            self.ledger._event(db, self.campaign_id, "proposer_started", {"attempt": used + 1})
        try:
            proposals = provider.propose(context, max_proposals=limit - len(snapshot["proposals"]), seed=snapshot["context"]["seed"])
            if not isinstance(proposals, (list, tuple)) or len(proposals) > limit:
                raise SearchError("provider must return a bounded batch")
            return self.ledger.register(self.campaign_id, [self._materialize_proposal(p, snapshot["context"]) for p in proposals])
        except Exception as exc:
            self.ledger.event(self.campaign_id, "proposer_failed", {"error_type": type(exc).__name__})
            raise

    def _materialize_proposal(self, raw: dict, context: dict) -> dict:
        """Persist public derivation content on the host; models need no paths."""
        from .executor import write_once
        p = dict(raw)
        if "public_derivation" in p:
            if "public_derivation_ref" in p:
                raise SearchError("provide derivation content or an existing host ref, not both")
            content = text(p.pop("public_derivation"), "public derivation")
            if len(content.encode("utf-8")) > 65536:
                raise SearchError("public derivation exceeds 64 KiB")
            record = {"contract_version": "factor_search_public_derivation_v1", "context_hash": digest(context),
                      "proposer": p.get("proposer"), "public_derivation": content}
            path = self.ledger.root / "objects/research_search/derivations" / (digest(record) + ".json")
            write_once(path, record)
            p["public_derivation_ref"] = file_ref(path)
        expected = {"contract_version": PROPOSAL_VERSION, "context_hash": digest(context), "candidate_hash": candidate_hash(p)}
        for key, value in expected.items():
            if key in p and p[key] != value:
                raise SearchError("provider supplied inconsistent " + key)
            p[key] = value
        return p

    def tick(self) -> dict:
        snapshot = self.ledger.snapshot(self.campaign_id)
        c = snapshot["context"]
        feedback = self._feedback(snapshot)
        active = [t for t in snapshot["tickets"] if t["feedback_json"] is None]
        if active:
            ticket = json.loads(active[0]["ticket_json"])
            key, state = ticket["ticket_id"], ticket["state"]
            if state == "RESERVED":
                ticket = self.ledger.transition(key, {"RESERVED"}, "DISPATCHING")
                try:
                    receipt = self.executor.dispatch(ticket)
                    if receipt.get("ticket_id") != key or receipt.get("state") != "WAITING_PREPARATION":
                        raise SearchError("research action dispatch must acknowledge preparation only")
                    self.ledger.transition(key, {"DISPATCHING"}, "WAITING_PREPARATION", receipt)
                except Exception as exc:
                    self.ledger.transition(key, {"DISPATCHING"}, "INTERRUPTED", {"error_type": type(exc).__name__})
                    return {"state": "INTERRUPTED", "ticket_id": key}
                return dict(receipt)
            receipt = self.executor.poll(ticket)
            if receipt.get("ticket_id") != key:
                raise SearchError("poll ticket mismatch")
            if receipt.get("result_ref") is not None:
                result = self.ledger.record_feedback(key, receipt["result_ref"])
                return {"state": result["status"], "ticket_id": key, "feedback": result}
            # Pending is never converted to an observation or reward.
            return {"state": state, "ticket_id": key, "poll": dict(receipt)}
        if snapshot["remaining_trials"] <= 0 or snapshot["remaining_compute"] < reservation_cost(c):
            return {"state": "BUDGET_EXHAUSTED"}
        proposals = [json.loads(p["proposal_json"]) for p in snapshot["proposals"]]
        if not proposals:
            return {"state": "WAITING_PROPOSALS"}
        # Cost estimates from candidate generators never authorize compute.
        planner_rows = [{"candidate_hash": p["candidate_hash"], "parent_candidate_hash": p["parent_candidate_hash"],
                         "estimated_cost": reservation_cost(c)} for p in proposals]
        terminal = [{k: f[k] for k in ("candidate_hash", "learning_increment", "actual_cost", "candidate_score", "split")} |
                    {"status": f["status"].lower()} for f in feedback]
        selection = plan_next(planner_rows, terminal, root_candidate_hash=c["root_candidate_hash"],
                              seed=c["seed"], max_depth=c["max_depth"], planner_kind=c["planner_kind"])
        if selection is None:
            return {"state": "NO_ELIGIBLE_CANDIDATE"}
        ticket = self.ledger.reserve(self.campaign_id, selection["candidate_hash"], selection, expected_revision=snapshot["revision"])
        return {"state": "RESERVED", "ticket_id": ticket["ticket_id"], "selection": selection}
