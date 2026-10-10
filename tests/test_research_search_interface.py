"""Synthetic protocol fixtures, never a market run or an independent review.

Native review and research-budget validators are real. Wrapper proof rows in
unit fixtures are explicit test doubles; a separate worker test launches the
real wrapper and retains its actual rejection rather than manufacturing PASS.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.research_conjecture import research_protocol_paths
from factor_factory.research_search.contracts import (SearchError, candidate_hash, canonical,
    digest, file_ref, program_identity, read_json, validate_context, validate_proposal)
from factor_factory.research_search.controller import ResearchSearchController
from factor_factory.research_search.executor import FileNativeExecutor, execute_ready, execution_dir, write_once
from factor_factory.research_search.ledger import SearchLedger
from factor_factory.research_search.native import collect_result, command_for_ticket, validate_request, native_source_pin
from tests.helpers.research_protocol import valid_conjecture, valid_state

REPO = Path(__file__).resolve().parents[1]


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value) + "\n")
    return file_ref(path)


def stamp(seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Synthetic chronology leaves enough past time for worker-receipt probes.
    monkeypatch.setattr("factor_factory.research_search.ledger.now", lambda: stamp(-600))
    root = tmp_path / "study"
    root.mkdir()
    conj, state = valid_conjecture(), valid_state()
    rid = conj["report_id"]
    conj["local_is_policy"] = {"scope": "ordinary_local_is_only", **{k: False for k in
        ("oos_allocation_allowed", "oos_access_allowed", "oos_finalization_allowed", "recovery_allowed",
         "child_revision_allowed", "official_promotion_allowed", "canonical_writeback_allowed")}}
    for key in ("oos_start", "oos_end", "sealed_oos_token_hash"):
        conj["evidence_policy"].pop(key)
    native = research_protocol_paths(root, rid)
    cr, sr = put(native["conjecture"], conj), put(native["state"], state)
    spec = put(root / "spec.json", {"report_id": rid})
    mp = put(root / "measurement.json", {"scope": "synthetic metadata"})
    source_refs = {"step2_spec": spec, "measurement_program": mp}
    data = root / "data.csv"
    data.write_text("trade_date,ts_code,close,open\n20200102,000001.SZ,1,1\n")
    inputs = [file_ref(data)]
    meta = {key: put(root / (key + ".json"), {"scope": "synthetic", "role": key}) for key in
            ("calendar_ref", "universe_ref", "information_time_ref")}
    split = put(root / "split.json", {"contract_version": "factor_search_development_split_v1", "split": "development",
         "oos_accessed": False, "input_refs": inputs, "source_conjecture_ref": cr,
         "is_start": "2020-01-01", "is_end": "2024-12-31", "label_end": "2024-12-31"})
    protocol = put(root / "protocol.json", {"split": "development", "data_kind": "engineering_fixture",
                  "input_refs": inputs, **meta, "split_manifest_ref": split})
    authority = put(root / "budget.json", {"contract_version": "factor_search_budget_v1", "campaign_id": "search-1",
        "report_id": rid, "development_protocol_sha256": protocol["sha256"], "trial_budget": 8, "trials_used": 3,
        "compute_budget": 600, "source_authority_ref": cr, "state_ref": sr,
        "execution_cost_policy": {"preparation_seconds": 20, "native_seconds": 40}})
    projection = put(root / "projection.json", {"contract_version": "factor_search_source_projection_v1",
        "source_refs": source_refs, "research_question": "Synthetic interface fixture", "revision_laws": ["test a lawful estimator"],
        "prior_exposure": "development_only", "oos_accessed": False})
    p = {"contract_version": "factor_search_proposal_v1", "proposal_id": "root", "context_hash": "", "candidate_hash": "",
         "parent_candidate_hash": None, "proposer": {"kind": "fixture", "version": "1", "seed": 7},
         "mutation_class": "implementation_equivalent", "program": {"mode": "operator", "expression": "close - open", "required_inputs": ["close", "open"]},
         "semantics": {k: k + " synthetic semantics" for k in ("mathematical_object", "observation_map", "information_time",
                       "units", "missing_zero_policy", "sign_and_long_side", "controls")},
         "changes": ["implementation"], "public_derivation_ref": mp, "expected_metric_signature": "fixture only",
         "falsifiers": "changed legal information set", "kill_criteria": "incorrect implementation", "estimated_cost": 1}
    p["candidate_hash"] = candidate_hash(p)
    c = {"contract_version": "factor_search_context_v1", "campaign_id": "search-1", "report_id": rid,
         "workspace_root": str(root), "origin": "step2", "root_candidate_hash": p["candidate_hash"], "source_refs": source_refs,
         "development_protocol": protocol, "budget_authority": authority, "projection_ref": projection,
         "score_contract": {"metric_pointer": "/metric/value", "sample_count_pointer": "/metric/n", "unit_pointer": "/metric/unit",
                            "unit": "dimensionless", "direction": 1, "baseline": 0, "scale": 1, "minimum_samples": 5,
                            "evaluation_scope": "signal_diagnostic"},
         "allowed_mutation_classes": ["implementation_equivalent", "measurement_variant", "new_mechanism"],
         "max_depth": 3, "max_proposals": 10, "seed": 7, "planner_kind": "mcts", "compute_cost_unit": "wall_seconds"}
    p["context_hash"] = digest(c)
    ledger = SearchLedger(root)
    ledger.create_campaign(c)
    ledger.register(c["campaign_id"], [p])
    controller = ResearchSearchController(ledger, c["campaign_id"], FileNativeExecutor(root))
    return {"root": root, "context": c, "proposal": p, "ledger": ledger, "controller": controller, "tmp": tmp_path}


def dispatch(case):
    out = case["controller"].tick()
    assert out["state"] == "RESERVED"
    assert case["controller"].tick()["state"] == "WAITING_PREPARATION"
    return case["ledger"].ticket("search-1", out["ticket_id"])


def proof(request, names, start, finish):
    records = []
    for name in names:
        step = "2" if name.endswith("step2") else "3" if "step3" in name else "4" if name.endswith("step4") else "5"
        records.append({"name": name, "status": "PASS", "returncode": 0, "cwd": str(REPO),
                        "command": [request["python"], f"skills/factor-forge-step{step}/scripts/{name}.py", "--manifest", request["manifest_ref"]["path"]],
                        "started_at_utc": start, "finished_at_utc": start})
    return {"contract_version": "factorforge_ultimate_wrapper_v1", "report_id": request["report_id"], "repo_root": str(REPO),
            "factor_workspace": request["workspace_root"], "manifest_path": request["manifest_ref"]["path"],
            "dry_run": False, "contract_smoke_only": False, "execution_scope": "local_is_only", "status": "PASS",
            "is_execution_complete": True, "commands": records,
            "formal_command_contract": {"required_command_names": names, "executed_command_names": names, "satisfied": True}}


def ready(case, ticket):
    c, p = case["context"], case["proposal"]
    root = case["tmp"] / "child"
    root.mkdir(exist_ok=True)
    rid = c["report_id"] + "_CHILD"
    started = stamp(-500)
    spec = put(root / "spec.json", {"report_id": rid})
    code = root / "implementation.py"
    code.write_text("raise RuntimeError('Never execute a unit fixture as a market implementation')\n")
    impl = file_ref(code)
    local = {"input_mode": "daily_only", "daily_df_csv": str(case["root"] / "data.csv")}
    transfer = put(root / "handoff.json", {"report_id": rid, "factor_impl_ref": str(code), "local_input_paths": local})
    prep = put(root / "prep.json", {"report_id": rid, "local_input_paths": local})
    manifest = put(root / "manifest.json", {"report_id": rid, "repo_root": str(REPO), "factor_workspace": str(root),
                 "objects": {"factor_spec_master": spec["path"], "handoff_to_step4": transfer["path"], "data_prep_master": prep["path"]}})
    log = root / "tests.log"
    log.write_text("Synthetic fixture reviewed; not a real review or test invocation\n")
    files = [{"role": role, **ref} for role, ref in (("spec", spec), ("implementation", impl))]
    reviewed = stamp(-400)
    review = put(root / "objects/research_journal" / f"code_review__{rid}.json", {"report_id": rid, "author_id": "fixture-author", "reviewer_id": "fixture-reviewer",
        "reviewed_at": reviewed, "decision": "proceed", "summary": "Explicit synthetic protocol fixture", "findings": [],
        "reviewed_files": files, "post_review_tests": {"status": "PASS", "started_at": stamp(-390), "completed_at": stamp(-380),
              "evidence": [file_ref(log)], "tested_files": files}})
    protocol = read_json(c["development_protocol"]["path"])
    binding = put(root / "binding.json", {**protocol, "development_protocol_sha256": c["development_protocol"]["sha256"], "native_local_inputs": local})
    pin = put(root / "pin.json", native_source_pin(REPO))
    r = {"contract_version": "factor_search_native_request_v1", "context_hash": digest(c), "candidate_hash": p["candidate_hash"],
         "report_id": rid, "workspace_root": str(root), "repo_root": str(REPO), "python": sys.executable,
         "python_ref": file_ref(Path(sys.executable).resolve()), "repo_pin_ref": pin,
         "manifest_ref": manifest, "spec_ref": spec, "implementation_ref": impl, "handoff_ref": transfer, "data_prep_ref": prep,
         "data_binding_ref": binding, "metrics_path": str(root / "metrics.json")}
    finished = stamp(-300)
    r["step3_proof_ref"] = put(root / "step3.json", proof(r, ["run_step3b", "validate_step3b"], started, finished))
    r["readiness_ref"] = put(root / "ready.json", {"ticket_id": ticket["ticket_id"], "candidate_hash": p["candidate_hash"],
        "context_hash": digest(c), "decision": "proceed", "mutation_class": p["mutation_class"], "base_source_refs": c["source_refs"],
        "accepted_semantics": p["semantics"], "accepted_program_identity": program_identity(p["program"]),
        "step2_spec_ref": spec, "implementation_ref": impl, "review_ref": review, "post_review_tests_ref": file_ref(log),
        "started_at": started, "finished_at": finished, "preparation_cost_seconds": 0})
    case["ledger"].prepare("search-1", p["candidate_hash"], r)
    return case["ledger"].ticket("search-1", ticket["ticket_id"])


def result(case, ticket, *, value=.3, cost=1, status="COMPLETED"):
    r, c = ticket["native_request"], case["context"]
    root = Path(r["workspace_root"])
    started = stamp(-200)
    finished = (datetime.fromisoformat(started) + timedelta(seconds=cost or 0)).isoformat()
    native_proof = proof(r, ["run_step4", "validate_step4", "run_step5", "validate_step5"], started, finished)
    if status != "COMPLETED":
        native_proof.update(status="FAIL", is_execution_complete=False)
    pr = put(root / "result-proof.json", native_proof)
    metric = put(Path(r["metrics_path"]), {"report_id": r["report_id"], "status": "success", "evaluation_scope": "signal_diagnostic", "account_simulation": False,
        "metric": {"value": value, "n": 30, "unit": "dimensionless"}})
    master = put(root / "run.json", {"report_id": r["report_id"], "evaluation_results": {"backend_runs": [{"payload_path": metric["path"]}]}})
    receipt = put(root / "execution.json", {"contract_version": "factor_search_execution_receipt_v1", "ticket_id": ticket["ticket_id"],
        "request_hash": digest(r), "command": command_for_ticket(ticket, pr["path"]), "cwd": r["repo_root"],
        "started_at": started, "finished_at": finished, "elapsed_seconds": cost,
        "returncode": 0 if status == "COMPLETED" else 1, "output_refs": [pr, master, metric]})
    return put(root / "result.json", {"contract_version": "factor_search_native_result_v1", "ticket_id": ticket["ticket_id"],
        "candidate_hash": ticket["candidate_hash"], "context_hash": digest(c), "request_hash": digest(r), "split": "development",
        "data_kind": "engineering_fixture", "status": status, "actual_cost": cost, "proof_ref": pr,
        "run_master_ref": master if status == "COMPLETED" else None, "metrics_ref": metric if status == "COMPLETED" else None,
        "error": "" if status == "COMPLETED" else "synthetic native failure", "execution_receipt_ref": receipt})


def test_reserve_precedes_dispatch_and_all_preparation(case):
    t = dispatch(case)
    assert t["native_request"] is None
    assert t["reserved_compute_cost"] == 60  # proposer requested 1; host authority wins
    assert case["ledger"].snapshot("search-1")["remaining_trials"] == 4
    for _ in range(3):
        assert case["controller"].tick()["state"] == "WAITING_PREPARATION"
    assert len(case["ledger"].snapshot("search-1")["tickets"]) == 1


def test_ready_native_feedback_replay_preserves_fixed_score_and_trial(case):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    ref = result(case, t)
    f = case["ledger"].record_feedback(t["ticket_id"], ref)
    assert f["candidate_score"] == .3 and f["learning_increment"] == .3
    assert f["data_kind"] == "engineering_fixture"
    assert case["ledger"].record_feedback(t["ticket_id"], ref) == f
    assert case["controller"].tick()["state"] == "NO_ELIGIBLE_CANDIDATE"
    assert case["ledger"].snapshot("search-1")["remaining_trials"] == 4


def test_dispatch_crash_does_not_repeat_external_call(case):
    class Broken:
        calls = 0
        def dispatch(self, ticket):
            self.calls += 1
            raise RuntimeError("crash after uncertain delivery")
        def poll(self, ticket):
            return {"ticket_id": ticket["ticket_id"], "state": "INTERRUPTED"}
    executor = Broken()
    ctl = ResearchSearchController(case["ledger"], "search-1", executor)
    assert ctl.tick()["state"] == "RESERVED"
    assert ctl.tick()["state"] == "INTERRUPTED"
    assert ctl.tick()["state"] == "INTERRUPTED"
    assert executor.calls == 1


def test_reservation_race_has_one_ticket_and_one_trial(case):
    def attempt(_):
        try:
            return case["controller"].tick()
        except SearchError:
            return None
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(attempt, range(4)))
    snap = case["ledger"].snapshot("search-1")
    assert len(snap["tickets"]) == 1
    assert snap["remaining_trials"] == 4


def test_duplicate_formula_whitespace_no_new_candidate_or_trial(case):
    p = deepcopy(case["proposal"])
    p["proposal_id"] = "duplicate"
    p["program"]["expression"] = "close  -  open"
    assert candidate_hash(p) == p["candidate_hash"]
    assert case["ledger"].register("search-1", [p])["duplicates"] == [p["candidate_hash"]]
    assert case["ledger"].snapshot("search-1")["remaining_trials"] == 5


@pytest.mark.parametrize("field,value", [("split", "oos"), ("data_kind", "market"), ("actual_cost", 0), ("candidate_hash", "f" * 64)])
def test_invalid_native_feedback_never_becomes_observation(case, field, value):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    ref = result(case, t)
    obj = read_json(ref["path"])
    obj[field] = value
    ref = put(Path(ref["path"]), obj)
    with pytest.raises(SearchError):
        case["ledger"].record_feedback(t["ticket_id"], ref)
    assert case["ledger"].snapshot("search-1")["tickets"][0]["feedback_json"] is None


@pytest.mark.parametrize("mutation", ["missing_command", "stale_code", "wrong_input", "missing_unit", "empty_coverage", "wrong_scope"])
def test_native_artifact_binding_blocks_false_success(case, mutation):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    ref = result(case, t)
    obj = read_json(ref["path"])
    if mutation == "stale_code":
        Path(t["native_request"]["implementation_ref"]["path"]).write_text("# changed\n")
    elif mutation == "wrong_input":
        Path(case["root"] / "data.csv").write_text("replacement\n")
    elif mutation == "missing_command":
        pr = read_json(obj["proof_ref"]["path"])
        pr["commands"].pop()
        obj["proof_ref"] = put(Path(obj["proof_ref"]["path"]), pr)
    else:
        metrics = read_json(obj["metrics_ref"]["path"])
        if mutation == "missing_unit":
            metrics["metric"].pop("unit")
        elif mutation == "empty_coverage":
            metrics["metric"]["n"] = 0
        else:
            metrics["evaluation_scope"] = "account"
        obj["metrics_ref"] = put(Path(obj["metrics_ref"]["path"]), metrics)
    ref = put(Path(ref["path"]), obj)
    with pytest.raises(SearchError):
        case["ledger"].record_feedback(t["ticket_id"], ref)


def test_failed_and_unknown_costs_do_not_reward_or_refund_trial(case):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    ref = result(case, t, cost=None, status="FAILED_UNKNOWN_COST")
    f = case["ledger"].record_feedback(t["ticket_id"], ref)
    assert f["candidate_score"] is None and f["learning_increment"] is None
    snap = case["ledger"].snapshot("search-1")
    assert snap["remaining_compute"] == 540 and snap["remaining_trials"] == 4


def test_overrun_retains_full_cost_without_reward(case):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    f = case["ledger"].record_feedback(t["ticket_id"], result(case, t, cost=100))
    assert f["status"] == "BLOCKED" and f["candidate_score"] is None
    assert case["ledger"].snapshot("search-1")["remaining_compute"] == 500


def test_source_authority_is_native_and_cannot_reset_used_trials(case):
    c = deepcopy(case["context"])
    authority = read_json(c["budget_authority"]["path"])
    authority["trials_used"] = 0
    c["budget_authority"] = put(case["root"] / "invalid-budget.json", authority)
    with pytest.raises(SearchError, match="reset"):
        validate_context(c)
    authority["trials_used"] = 3
    authority["source_authority_ref"] = put(case["root"] / "fake-source.json", {"trial_budget": 100})
    c["budget_authority"] = put(case["root"] / "invalid-budget.json", authority)
    with pytest.raises(SearchError, match="canonical"):
        validate_context(c)


def test_projection_excludes_source_paths_and_metrics_files(case):
    public = case["controller"].proposer_context()
    assert str(case["root"]) not in canonical(public)
    assert "source_refs" not in public and "development_protocol" not in public


@pytest.mark.parametrize("expression", ["__import__('os').system('id')", "close.shift(-1)", "open('/tmp/x')"])
def test_formula_is_parsed_not_evaluated(case, expression):
    p = deepcopy(case["proposal"])
    p["program"]["expression"] = expression
    with pytest.raises(Exception):
        candidate_hash(p)


def test_revision_cannot_be_downgraded_to_implementation(case):
    p = deepcopy(case["proposal"])
    p["changes"] = ["mathematical_object"]
    with pytest.raises(SearchError, match="downgrade"):
        validate_proposal(case["context"], p)


def test_state_graph_forbids_skip_review(case):
    out = case["controller"].tick()
    with pytest.raises(SearchError, match="illegal"):
        case["ledger"].transition(out["ticket_id"], {"RESERVED"}, "RUNNING")


def test_actual_native_worker_rejection_is_retained_and_not_retried(case):
    t = ready(case, dispatch(case))
    # Deliberately incomplete synthetic manifest: real native wrapper must reject.
    output = execute_ready(case["ledger"], "search-1", t["ticket_id"])
    actual = read_json(output["result_ref"]["path"])
    assert actual["status"] == "FAILED_KNOWN_COST"
    assert actual["actual_cost"] >= 0
    assert execution_dir(t).joinpath("stderr.log").exists()
    with pytest.raises(SearchError, match="never retries"):
        execute_ready(case["ledger"], "search-1", t["ticket_id"])
    f = case["controller"].tick()["feedback"]
    assert f["candidate_score"] is None and f["status"] == "FAILED_KNOWN_COST"


def test_cli_and_file_dispatch_are_idempotent(case):
    run = subprocess.run([sys.executable, str(REPO / "scripts/manage_factor_search.py"), "--workspace", str(case["root"]),
                          "--campaign", "search-1", "proposer-context"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["contract_version"] == "factor_search_proposer_input_v1"
    ticket = dispatch(case)
    executor = FileNativeExecutor(case["root"])
    assert executor.dispatch(ticket) == executor.dispatch(ticket)
    with pytest.raises(SearchError):
        write_once(executor.action_path(ticket["ticket_id"]), {"wrong": True})


def test_failed_preparation_frees_scheduler_without_refunding_budget(case):
    from factor_factory.research_search.executor import stop_preparation
    ticket = dispatch(case)
    feedback = stop_preparation(case["ledger"], "search-1", ticket["ticket_id"], actor="fixture-main", reason="No lawful measurement")
    assert feedback["status"] == "BLOCKED" and feedback["learning_increment"] is None
    assert case["controller"].tick()["state"] == "NO_ELIGIBLE_CANDIDATE"
    snap = case["ledger"].snapshot("search-1")
    assert snap["remaining_compute"] == 540 and snap["remaining_trials"] == 4


def test_reconcile_only_republishes_same_action_after_dispatch_gap(case):
    from factor_factory.research_search.executor import reconcile_dispatch
    key = case["controller"].tick()["ticket_id"]
    case["ledger"].transition(key, {"RESERVED"}, "DISPATCHING")
    assert reconcile_dispatch(case["ledger"], "search-1", key)["state"] == "WAITING_PREPARATION"
    assert len(case["ledger"].snapshot("search-1")["tickets"]) == 1
    with pytest.raises(SearchError):
        reconcile_dispatch(case["ledger"], "search-1", key)


def test_same_authority_cannot_repeat_candidate_through_new_campaign(case):
    dispatch(case)
    c = deepcopy(case["context"])
    c["campaign_id"] = "search-2"
    authority = read_json(c["budget_authority"]["path"])
    authority["campaign_id"] = c["campaign_id"]
    c["budget_authority"] = put(case["root"] / "budget-2.json", authority)
    p = deepcopy(case["proposal"])
    p["context_hash"] = digest(c)
    case["ledger"].create_campaign(c)
    case["ledger"].register("search-2", [p])
    ctl = ResearchSearchController(case["ledger"], "search-2", FileNativeExecutor(case["root"]))
    with pytest.raises(SearchError, match="shared-budget"):
        ctl.tick()
    assert case["ledger"].snapshot("search-2")["remaining_trials"] == 4


def test_changed_terminal_artifact_stops_cached_feedback(case):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    case["ledger"].record_feedback(t["ticket_id"], result(case, t))
    Path(t["native_request"]["metrics_path"]).write_text("{}")
    with pytest.raises(SearchError, match="changed"):
        case["controller"].tick()


@pytest.mark.parametrize("changed", ["unit_pointer", "split", "future_label", "oos_projection", "extra_context"])
def test_context_refuses_heldout_or_untyped_metric_inputs(case, changed):
    c = deepcopy(case["context"])
    if changed == "unit_pointer":
        c["score_contract"]["unit_pointer"] = None
    elif changed == "extra_context":
        c["oos_results"] = {"score": 99}
    elif changed == "oos_projection":
        projection = read_json(c["projection_ref"]["path"])
        projection["oos_accessed"] = True
        c["projection_ref"] = put(case["root"] / "bad-projection.json", projection)
    else:
        protocol = read_json(c["development_protocol"]["path"])
        if changed == "split":
            protocol["split"] = "confirmation"
        else:
            split = read_json(protocol["split_manifest_ref"]["path"])
            split["label_end"] = "2025-01-01"
            protocol["split_manifest_ref"] = put(case["root"] / "bad-split.json", split)
        c["development_protocol"] = put(case["root"] / "bad-protocol.json", protocol)
        authority = read_json(c["budget_authority"]["path"])
        authority["development_protocol_sha256"] = c["development_protocol"]["sha256"]
        c["budget_authority"] = put(case["root"] / "bad-authority.json", authority)
    with pytest.raises(SearchError):
        validate_context(c)


def test_provider_interface_is_replaceable_and_bounded(case):
    class Fixed:
        def propose(self, context, *, max_proposals, seed):
            assert seed == 7 and max_proposals == 9
            assert "revision_laws" in context and "source_refs" not in context
            return [case["proposal"]]
    assert case["controller"].propose(Fixed())["duplicates"] == [case["proposal"]["candidate_hash"]]


def test_revision_action_returns_to_step2(case):
    from factor_factory.research_search.executor import stop_preparation
    t = dispatch(case)
    stop_preparation(case["ledger"], "search-1", t["ticket_id"], actor="fixture", reason="baseline unavailable")
    p = deepcopy(case["proposal"])
    p.update(proposal_id="measurement", parent_candidate_hash=p["candidate_hash"], mutation_class="measurement_variant", changes=["observation_map"])
    p["program"]["expression"] = "close + open"
    p["semantics"]["observation_map"] = "different synthetic measurement"
    p["candidate_hash"] = candidate_hash(p)
    case["ledger"].register("search-1", [p])
    next_ticket = case["controller"].tick()
    out = case["controller"].tick()
    assert next_ticket["state"] == "RESERVED"
    assert read_json(out["action_ref"]["path"])["entry_step"] == "2"


def test_score_change_cannot_repeat_the_same_candidate_protocol(case):
    dispatch(case)
    c = deepcopy(case["context"])
    c["campaign_id"] = "rescore"
    c["score_contract"]["scale"] = 2
    authority = read_json(c["budget_authority"]["path"])
    authority["campaign_id"] = c["campaign_id"]
    c["budget_authority"] = put(case["root"] / "rescore-budget.json", authority)
    p = deepcopy(case["proposal"])
    p["context_hash"] = digest(c)
    case["ledger"].create_campaign(c)
    case["ledger"].register("rescore", [p])
    with pytest.raises(SearchError, match="shared-budget"):
        ResearchSearchController(case["ledger"], "rescore", FileNativeExecutor(case["root"])).tick()


def test_native_budget_alias_cannot_reset_shared_usage(case):
    dispatch(case)
    c = deepcopy(case["context"])
    c["campaign_id"] = "alias"
    a = read_json(c["budget_authority"]["path"])
    path = Path(a["source_authority_ref"]["path"])
    a["source_authority_ref"] = file_ref(path.parent / ".." / path.parent.name / path.name)
    a["campaign_id"] = "alias"
    protocol = read_json(c["development_protocol"]["path"])
    split = read_json(protocol["split_manifest_ref"]["path"])
    split["source_conjecture_ref"] = a["source_authority_ref"]
    protocol["split_manifest_ref"] = put(case["root"] / "alias-split.json", split)
    c["development_protocol"] = put(case["root"] / "alias-protocol.json", protocol)
    a["development_protocol_sha256"] = c["development_protocol"]["sha256"]
    c["budget_authority"] = put(case["root"] / "alias-budget.json", a)
    case["ledger"].create_campaign(c)
    assert case["ledger"].snapshot("alias")["remaining_trials"] == 4
    assert case["ledger"].snapshot("alias")["remaining_compute"] == 540


@pytest.mark.parametrize("mutation", ["future", "missing_finish", "wrong_cwd", "failed_process", "zero_time",
                                    "old_proof", "old_metrics", "capture_mismatch"])
def test_completion_must_match_this_worker_timeline_and_capture(case, mutation):
    t = ready(case, dispatch(case))
    t = case["ledger"].transition(t["ticket_id"], {"READY"}, "RUNNING")
    ref = result(case, t)
    obj = read_json(ref["path"])
    receipt = read_json(obj["execution_receipt_ref"]["path"])
    if mutation == "future":
        receipt["started_at"] = "2099-01-01T00:00:00+00:00"
    elif mutation == "missing_finish":
        receipt.pop("finished_at")
    elif mutation == "wrong_cwd":
        receipt["cwd"] = str(case["root"])
    elif mutation == "failed_process":
        receipt["returncode"] = 42
    elif mutation == "zero_time":
        receipt["elapsed_seconds"] = obj["actual_cost"] = 0
    elif mutation == "capture_mismatch":
        receipt["output_refs"] = []
    elif mutation == "old_metrics":
        import os
        os.utime(obj["metrics_ref"]["path"], (946684800, 946684800))
    else:
        pr = read_json(obj["proof_ref"]["path"])
        for row in pr["commands"]:
            row["started_at_utc"] = row["finished_at_utc"] = "2000-01-01T00:00:00+00:00"
        obj["proof_ref"] = put(Path(obj["proof_ref"]["path"]), pr)
        receipt["output_refs"][0] = obj["proof_ref"]
    obj["execution_receipt_ref"] = put(Path(obj["execution_receipt_ref"]["path"]), receipt)
    with pytest.raises(SearchError):
        case["ledger"].record_feedback(t["ticket_id"], put(Path(ref["path"]), obj))


def test_external_proposer_supplies_content_without_filesystem_access(case):
    class PublicOnly:
        def propose(self, context, *, max_proposals, seed):
            row = deepcopy(case["proposal"])
            for k in ("contract_version", "candidate_hash", "context_hash", "public_derivation_ref"):
                row.pop(k)
            row.update(proposal_id="external", parent_candidate_hash=context["root_candidate_hash"],
                       mutation_class="measurement_variant", changes=["observation_map"],
                       public_derivation="Use the public hypothesis to test a revised measurement; no private data accessed.")
            row["program"]["expression"] = "close + open"
            row["semantics"]["observation_map"] = "Revised public measurement"
            return [row]
    registered = case["controller"].propose(PublicOnly())["registered"]
    assert len(registered) == 1
    rows = case["ledger"].snapshot("search-1")["proposals"]
    p = next(json.loads(r["proposal_json"]) for r in rows if r["candidate_hash"] == registered[0])
    record = read_json(p["public_derivation_ref"]["path"])
    assert record["public_derivation"].startswith("Use the public hypothesis")


def test_native_input_metadata_and_legacy_relative_base_are_preserved(case):
    import os
    from factor_factory.research_search.native import bound_native_input_paths
    root = case["tmp"] / "native"
    root.mkdir()
    request = {"workspace_root": str(root)}
    target = case["root"] / "data.csv"
    local = {"input_mode": "daily_only", "daily_df_csv": os.path.relpath(target, root.parent),
             "snapshot_note": "Ordinary materialized metadata", "preferred_daily_format": "csv",
             "daily_filter_summary": {}, "data_api_resolution": {}}
    protocol = read_json(case["context"]["development_protocol"]["path"])
    assert bound_native_input_paths(local, request, protocol) == [target.resolve()]
    # No heuristic search in alternate neighbouring roots when native resolution disagrees.
    local["daily_df_csv"] = os.path.relpath(target, root)
    with pytest.raises(SearchError, match="not in frozen"):
        bound_native_input_paths(local, request, protocol)


def test_real_prepared_daily_sample_consumer_with_full_sample_selectors(tmp_path, monkeypatch):
    import importlib.util
    import os
    import pandas as pd
    from factor_factory.research_search.native import bound_native_input_paths
    from factor_factory.prepared_daily_inputs import validate_full_scope
    root = tmp_path / "prepared"
    root.mkdir()
    monkeypatch.setenv("FACTORFORGE_ROOT", str(root))
    monkeypatch.setenv("FACTORFORGE_LOCAL_IS_ONLY", "1")
    for key in ("FACTORFORGE_FACTOR_WORKSPACE", "FACTORFORGE_SHARED_EVALUATION_CONTEXT"):
        monkeypatch.delenv(key, raising=False)
    days = ["20200102", "20200103", "20200106"]
    frame = pd.DataFrame({"trade_date": days, "ts_code": ["000001.SZ"] * 3, "open": [1., 2., 3.], "close": [2., 4., 6.]})
    frames = {"full": frame, "sample": frame.iloc[:2], "calendar": pd.DataFrame({"trade_date": days}),
              "sample_calendar": pd.DataFrame({"trade_date": days[:2]})}
    for name, values in frames.items():
        values.to_parquet(root / (name + ".parquet"), index=False)
    rel = lambda name: os.path.relpath(root / (name + ".parquet"), root.parent)
    local = {"input_mode": "daily_only", "prepared_input_kind": "prepared_daily_v1",
             "daily_df_parquet": rel("full"), "step3b_daily_df_parquet": rel("sample"),
             "exchange_calendar_parquet": rel("calendar"), "step3b_exchange_calendar_parquet": rel("sample_calendar"),
             "sample_window_actual": {"start": days[0], "end": days[-1]}, "step3b_sample_window": {"start": days[0], "end": days[1]},
             "snapshot_note": "Engineering fixture; native prepared full/sample selectors"}
    protocol = {"input_refs": [file_ref(root / (name + ".parquet")) for name in frames], "calendar_ref": file_ref(root / "calendar.parquet")}
    assert len(bound_native_input_paths(local, {"workspace_root": str(root)}, protocol)) == 4
    assert validate_full_scope(local, root.parent)["session_count"] == 3
    spec = importlib.util.spec_from_file_location("search_prepared_native_step3", REPO / "skills/factor-forge-step3/scripts/run_step3b.py")
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    impl = root / "factor.py"
    impl.write_text("def compute_factor(daily_df, minute_df=None):\n    return daily_df[['ts_code','trade_date']].assign(factor_value=daily_df.close-daily_df.open)\n")
    sample = stage.generate_first_run_factor_values("SEARCH_PREPARED_FIXTURE", "SEARCH_PREPARED_FIXTURE", impl,
                        local, {"scope": "engineering_fixture"}, csv_output_policy="no_csv")
    assert sample["is_formal_factor_values"] is False
    actual = pd.read_parquet(root / "runs/SEARCH_PREPARED_FIXTURE/step3b_sample_factor_values__SEARCH_PREPARED_FIXTURE.parquet")
    assert actual["factor_value"].tolist() == [1., 2.]
