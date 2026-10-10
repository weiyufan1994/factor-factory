"""Durable file adapter and an explicit worker for the existing native runner.

The file adapter delegates Step2/3 authorship to the existing research roles.
Only the host can attach their reviewed preparation and invoke execute_ready.
No model client, formula evaluator, data loader, or account engine lives here.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Any, Mapping

from .contracts import (RESULT_VERSION, SearchError, bound_json, canonical, digest,
                        file_ref, read_json, validate_context)
from .ledger import SearchLedger, now
from .native import command_for_ticket, validate_preparation, validate_request


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    """Publish complete bytes once, without overwriting another producer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(value) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise SearchError("immutable publication already exists with different bytes")
    finally:
        tmp.unlink()


class FileNativeExecutor:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve() / "objects/research_search/outbox"

    def action_path(self, ticket_id: str) -> Path:
        from .contracts import hash_value
        return self.root / hash_value(ticket_id, "ticket_id") / "action.json"

    def dispatch(self, ticket: Mapping[str, Any]) -> dict:
        p = ticket["proposal"]
        action = {"contract_version": "factor_search_research_action_v1", "ticket_id": ticket["ticket_id"],
                  "context_hash": ticket["context_hash"], "candidate_hash": ticket["candidate_hash"],
                  "proposal": p, "reservation_id": ticket["reservation_id"],
                  "reserved_compute_seconds": ticket["reserved_compute_cost"],
                  "reserved_at": ticket["created_at"],
                  "entry_step": "2" if p["mutation_class"] != "implementation_equivalent" else "3",
                  "required_flow": ["Step2 mathematical/measurement acceptance", "Step3A governed data binding",
                                    "Step3B code, independent review, post-review tests", "Step4 execution", "Step5 metrics"],
                  "feedback_scope": "development", "native_request_ready": False}
        path = self.action_path(ticket["ticket_id"])
        write_once(path, action)
        return {"ticket_id": ticket["ticket_id"], "state": "WAITING_PREPARATION", "action_ref": file_ref(path)}

    def poll(self, ticket: Mapping[str, Any]) -> dict:
        result = {"ticket_id": ticket["ticket_id"], "state": ticket["state"]}
        request = ticket.get("native_request")
        if request:
            path = execution_dir(ticket) / "result.json"
            if path.exists():
                result["result_ref"] = file_ref(path)
        return result


def execution_dir(ticket: Mapping[str, Any]) -> Path:
    return Path(ticket["native_request"]["workspace_root"]) / "objects/research_search/executions" / ticket["ticket_id"]


def native_worker_environment(workspace_root: str | Path) -> dict[str, str]:
    """Use native local advisory routing instead of the repository fallback."""
    root = Path(workspace_root).resolve(strict=True)
    for relative in ("knowledge", "knowledge/retrieval", "knowledge/maintenance",
                     "knowledge/research_episodes", "knowledge/local_advisory"):
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise SearchError("native advisory storage must stay inside the child workspace")
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORFORGE_")}
    env.update(FACTORFORGE_FACTOR_WORKSPACE=str(root), FACTORFORGE_LOCAL_IS_ONLY="1",
               FACTORFORGE_ADVISORY_ROOT=str(root / "knowledge/local_advisory"),
               PYTHONDONTWRITEBYTECODE="1")
    return env


def reconcile_dispatch(ledger: SearchLedger, campaign: str, ticket_id: str) -> dict:
    """File publication is idempotent; this never repeats a native computation."""
    ticket = ledger.ticket(campaign, ticket_id)
    if ticket["state"] not in {"DISPATCHING", "INTERRUPTED"} or ticket["native_request"] is not None:
        raise SearchError("only an interrupted preparation publication can be reconciled")
    receipt = FileNativeExecutor(ledger.root).dispatch(ticket)
    ledger.transition(ticket_id, {ticket["state"]}, "WAITING_PREPARATION", receipt)
    return receipt


def stop_preparation(ledger: SearchLedger, campaign: str, ticket_id: str, *, actor: str, reason: str) -> dict:
    """Host records rejection/abandonment; unknown compute keeps the full reserve."""
    ticket = ledger.ticket(campaign, ticket_id)
    if ticket["native_request"] is not None or ticket["state"] not in {"WAITING_PREPARATION", "WAITING_REVIEW", "INTERRUPTED"}:
        raise SearchError("only an unfinished preparation action can be stopped")
    record = {"contract_version": "factor_search_preparation_stopped_v1", "ticket_id": ticket_id,
              "context_hash": ticket["context_hash"], "candidate_hash": ticket["candidate_hash"],
              "actor": actor, "reason": reason, "stopped_at": now()}
    path = ledger.root / "objects/research_search/outbox" / ticket_id / "preparation_stopped.json"
    write_once(path, record)
    return ledger.record_feedback(ticket_id, file_ref(path))


def execute_ready(ledger: SearchLedger, campaign_id: str, ticket_id: str) -> dict:
    """Run one reviewed ticket exactly once, synchronously in a separate worker.

    Launch this function/CLI as a host job. The controller remains nonblocking.
    A crash after the durable RUNNING claim requires evidence reconciliation;
    invoking this worker again never automatically repeats a native evaluation.
    """
    snapshot = ledger.snapshot(campaign_id)
    c = validate_context(snapshot["context"])
    ticket = ledger.ticket(campaign_id, ticket_id)
    if ticket["state"] != "READY":
        raise SearchError("native worker requires READY; never retries a claimed execution")
    r = validate_request(c, ticket["proposal"], ticket["native_request"])
    prep_cost = validate_preparation(r, ticket)
    costs = bound_json(c["budget_authority"])["execution_cost_policy"]
    if prep_cost > costs["preparation_seconds"]:
        raise SearchError("preparation exceeded its frozen stage allowance")
    env = native_worker_environment(r["workspace_root"])
    ticket = ledger.transition(ticket_id, {"READY"}, "RUNNING")
    out = execution_dir(ticket)
    out.mkdir(parents=True, exist_ok=True)
    proof_path = out / "native_proof.json"
    argv = command_for_ticket(ticket, proof_path)
    started_at, start = now(), time.monotonic()
    error = ""
    try:
        with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
            proc = subprocess.Popen(argv, cwd=r["repo_root"], env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                code = proc.wait(timeout=costs["native_seconds"])
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                code = proc.wait()
                error = "native execution exceeded its frozen timeout"
    except Exception as exc:
        code, error = None, "native launch failed: " + type(exc).__name__
    elapsed = time.monotonic() - start
    finished_at = now()
    master_path = Path(r["workspace_root"]) / "objects/factor_run_master" / f"factor_run_master__{r['report_id']}.json"
    captured = []
    for path in (proof_path, master_path, Path(r["metrics_path"])):
        if path.is_file():
            captured.append(file_ref(path))
    receipt = {"contract_version": "factor_search_execution_receipt_v1", "ticket_id": ticket_id,
               "request_hash": digest(r), "command": argv, "cwd": r["repo_root"],
               "started_at": started_at, "finished_at": finished_at, "elapsed_seconds": elapsed, "returncode": code,
               "output_refs": captured}
    receipt_path = out / "execution_receipt.json"
    write_once(receipt_path, receipt)
    if not proof_path.exists():
        write_once(proof_path, {"report_id": r["report_id"], "status": "FAIL", "error": error or "native proof not produced"})
    proof = read_json(proof_path)
    completed = code == 0 and not error and proof.get("status") == "PASS" and proof.get("is_execution_complete") is True
    result = {"contract_version": RESULT_VERSION, "ticket_id": ticket_id, "candidate_hash": ticket["candidate_hash"],
              "context_hash": digest(c), "request_hash": digest(r), "split": "development",
              "data_kind": bound_json(c["development_protocol"])["data_kind"],
              "status": "COMPLETED" if completed else "FAILED_KNOWN_COST", "actual_cost": prep_cost + elapsed,
              "proof_ref": file_ref(proof_path), "execution_receipt_ref": file_ref(receipt_path),
              "run_master_ref": None, "metrics_ref": None, "error": error or ("" if completed else "native Step4/5 did not complete")}
    if completed:
        master = Path(r["workspace_root"]) / "objects/factor_run_master" / f"factor_run_master__{r['report_id']}.json"
        try:
            result.update(run_master_ref=file_ref(master), metrics_ref=file_ref(r["metrics_path"]))
        except SearchError:
            # Preserve the successful process proof; no score for incomplete artifacts.
            result.update(status="BLOCKED", error="native output artifacts are incomplete")
    result_path = out / "result.json"
    write_once(result_path, result)
    return {"ticket_id": ticket_id, "state": "AWAITING_COLLECTION", "result_ref": file_ref(result_path)}
