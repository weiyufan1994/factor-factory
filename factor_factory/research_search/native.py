"""Translate reviewed native work and verified artifacts into search feedback.

This module contains no formula execution, market loader or account simulator.
Native Step3B is prepared/reviewed by the existing workflow; a ready request
continues its pinned Ultimate entry at Step4 and collects Step4/5 evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Mapping

from .contracts import (REQUEST_VERSION, RESULT_VERSION, SearchError, bound_json,
                        canonical, digest, integer, number, pointer, program_identity,
                        file_ref, text, timestamp, validate_context, verify_ref)


def native_source_pin(repo_root: str | Path) -> dict:
    """Inventory native Python and schema inputs, including transitive helpers."""
    root = Path(repo_root).resolve()
    paths = sorted({path for folder in ("factor_factory", "skills", "scripts", "schemas")
                    for path in (root / folder).rglob("*") if path.is_file()
                    and path.suffix in {".py", ".json", ".toml", ".yaml", ".yml"}
                    and "__pycache__" not in path.parts})
    return {"contract_version": "factor_search_native_source_pin_v1", "repo_root": str(root),
            "entry_refs": [file_ref(path) for path in paths]}


def bound_native_input_paths(local: dict, request: Mapping[str, Any], protocol: dict) -> list[Path]:
    """Use the existing full/sample and auxiliary selection semantics.

    Native legacy daily/minute selectors are relative to active_root.parent;
    explicit auxiliary inputs use the factor workspace itself. Metadata does
    not select an executable input and is retained without rewriting Step3.
    """
    from factor_factory.implementation_runtime import named_input_bindings
    from factor_factory.prepared_daily_inputs import is_prepared_daily, sample_inputs, validate_paths
    root = Path(request["workspace_root"]).resolve()
    primary_base = root.parent
    if local.get("input_mode") not in {"daily_only", "price_volume_minute", "minute_and_daily"}:
        raise SearchError("native input mode requires a dedicated binding adapter")
    for key in ("minute_streaming_query", "derived_state_root", "step3b_derived_state_root",
                "evaluation_daily_df_parquet", "signal_daily_df_parquet"):
        if local.get(key):
            raise SearchError("dynamic native input route requires a dedicated binding adapter")
    selections = [local]
    try:
        if is_prepared_daily(local):
            validate_paths(local, primary_base, additional_workspace=root)
            selections.append(sample_inputs(local))
        selected = []
        for inputs in selections:
            daily = inputs.get("daily_df_parquet") or inputs.get("daily_df_csv")
            minute = inputs.get("minute_df_parquet") or inputs.get("minute_df_csv")
            calendar = inputs.get("exchange_calendar_parquet")
            if not daily or (inputs["input_mode"] in {"price_volume_minute", "minute_and_daily"} and not minute):
                raise SearchError("native materialized daily/minute selection is incomplete")
            selected.extend((primary_base / path).resolve() for path in (daily, minute, calendar) if path)
            selected.extend((root / path).resolve() for path in named_input_bindings(inputs).values())
    except (TypeError, ValueError, OSError) as exc:
        raise SearchError("invalid native input selection: " + str(exc)) from exc
    permitted = {Path(ref["path"]).resolve() for ref in protocol["input_refs"]}
    permitted.add(Path(protocol["calendar_ref"]["path"]).resolve())
    if not set(selected) <= permitted:
        raise SearchError("native input not in frozen development manifest")
    return sorted(set(selected))


def _native_proof(ref, request, names):
    proof = bound_json(ref, root=request["workspace_root"])
    if (proof.get("contract_version") != "factorforge_ultimate_wrapper_v1"
            or proof.get("report_id") != request["report_id"]
            or Path(proof.get("repo_root", "")).resolve() != Path(request["repo_root"]).resolve()
            or proof.get("factor_workspace") != request["workspace_root"]
            or proof.get("manifest_path") != request["manifest_ref"]["path"]
            or proof.get("dry_run") is not False
            or proof.get("contract_smoke_only") is not False
            or proof.get("execution_scope") != "local_is_only"):
        raise SearchError("native proof identity/scope mismatch")
    if proof.get("status") != "PASS" or proof.get("is_execution_complete") is not True:
        raise SearchError("native segment has not completed successfully")
    commands = proof.get("commands")
    if not isinstance(commands, list):
        raise SearchError("native commands missing")
    actual = [r.get("name") for r in commands if isinstance(r, dict)]
    contract = proof.get("formal_command_contract", {})
    if (contract.get("satisfied") is not True or contract.get("required_command_names") != actual
            or contract.get("executed_command_names") != actual or len(set(actual)) != len(actual)):
        raise SearchError("native formal command contract is incomplete")
    if any(r.get("status") != "PASS" or type(r.get("returncode")) is not int or r["returncode"] != 0 for r in commands):
        raise SearchError("partial/failed native command sequence")
    for name in names:
        rows = [r for r in commands if isinstance(r, dict) and r.get("name") == name]
        if len(rows) != 1:
            raise SearchError(f"one actual native {name} record required")
        row = rows[0]
        if row.get("status") != "PASS" or type(row.get("returncode")) is not int or row["returncode"] != 0:
            raise SearchError(f"native {name} did not pass")
        argv = row.get("command")
        step = "2" if name.endswith("step2") else "3" if "step3" in name else "4" if name.endswith("step4") else "5"
        expected = Path(request["repo_root"]) / f"skills/factor-forge-step{step}/scripts/{name}.py"
        if (not isinstance(argv, list) or len(argv) < 2 or argv[0] != request["python"]
                or (Path(row.get("cwd", "")) / argv[1]).resolve() != expected.resolve()
                or Path(row.get("cwd", "")).resolve() != Path(request["repo_root"]).resolve()):
            raise SearchError(f"native {name} argv missing")
        if "--manifest" in argv and argv[argv.index("--manifest") + 1] != request["manifest_ref"]["path"]:
            raise SearchError("native command manifest mismatch")
        if "--report-id" in argv and argv[argv.index("--report-id") + 1] != request["report_id"]:
            raise SearchError("native command report mismatch")
        if timestamp(row["finished_at_utc"]) < timestamp(row["started_at_utc"]):
            raise SearchError("native command timestamps invalid")
    return proof


def validate_request(context: Mapping[str, Any], proposal: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    import json
    r = json.loads(canonical(request))
    required = {"contract_version", "context_hash", "candidate_hash", "report_id", "workspace_root",
                "repo_root", "python", "manifest_ref", "spec_ref", "readiness_ref", "implementation_ref",
                "step3_proof_ref", "data_binding_ref", "metrics_path", "handoff_ref", "data_prep_ref",
                "python_ref", "repo_pin_ref"}
    if set(r) != required or r.get("contract_version") != REQUEST_VERSION:
        raise SearchError("native request fields/version mismatch")
    if r["context_hash"] != digest(context) or r["candidate_hash"] != proposal["candidate_hash"]:
        raise SearchError("native request candidate/context mismatch")
    root = Path(text(r["workspace_root"], "native workspace"))
    repo = Path(text(r["repo_root"], "native repo"))
    if not root.is_absolute() or not repo.is_absolute() or not root.is_dir() or not repo.is_dir():
        raise SearchError("absolute existing native workspace/repo required")
    if not Path(r["python"]).is_absolute() or not Path(r["python"]).is_file():
        raise SearchError("explicit pinned native Python required")
    if verify_ref(r["python_ref"]).resolve() != Path(r["python"]).resolve():
        raise SearchError("native Python identity mismatch")
    pin = bound_json(r["repo_pin_ref"], root=root)
    if pin != native_source_pin(repo):
        raise SearchError("pinned native source/schema inventory changed or incomplete")
    if str(repo / "scripts/run_factorforge_ultimate.py") not in {v["path"] for v in pin["entry_refs"]}:
        raise SearchError("native wrapper not in pinned code receipt")
    if not (repo / "scripts/run_factorforge_ultimate.py").is_file():
        raise SearchError("native Ultimate entry missing")
    if (proposal["candidate_hash"] != context["root_candidate_hash"]
            and r["report_id"] == context["report_id"]):
        raise SearchError("revision requires its own native report identity")
    manifest = bound_json(r["manifest_ref"], root=root)
    if (manifest.get("report_id") != r["report_id"]
            or Path(manifest.get("repo_root", "")).resolve() != repo.resolve()
            or manifest.get("factor_workspace") != str(root)):
        raise SearchError("native manifest/report/pin mismatch")
    for key, ref_key in (("factor_spec_master", "spec_ref"), ("handoff_to_step4", "handoff_ref"),
                         ("data_prep_master", "data_prep_ref")):
        if (manifest.get("objects") or {}).get(key) != r[ref_key]["path"]:
            raise SearchError("request differs from native manifest object: " + key)
    spec = bound_json(r["spec_ref"], root=root)
    if spec.get("report_id") != r["report_id"]:
        raise SearchError("native Step2 spec report mismatch")
    readiness = bound_json(r["readiness_ref"], root=root)
    if (readiness.get("candidate_hash") != proposal["candidate_hash"]
            or readiness.get("context_hash") != digest(context)
            or readiness.get("decision") != "proceed"
            or readiness.get("mutation_class") != proposal["mutation_class"]
            or readiness.get("accepted_semantics") != proposal["semantics"]
            or readiness.get("accepted_program_identity") != program_identity(proposal["program"])
            or readiness.get("step2_spec_ref") != r["spec_ref"]
            or readiness.get("base_source_refs") != context["source_refs"]
            or readiness.get("implementation_ref") != r["implementation_ref"]):
        raise SearchError("candidate requires exact Step2/implementation readiness binding")
    if proposal["mutation_class"] != "implementation_equivalent":
        if readiness.get("step2_revision_accepted") is not True:
            raise SearchError("mechanism/measurement revision must return to Step2")
        _native_proof(readiness.get("step2_revision_ref"), r, ("run_step2", "validate_step2"))
    for name in ("review_ref", "post_review_tests_ref"):
        verify_ref(readiness.get(name), root=root)
    if Path(readiness["review_ref"]["path"]).resolve() != (root / "objects/research_journal" / f"code_review__{r['report_id']}.json").resolve():
        raise SearchError("readiness must bind the review consumed by the native wrapper")
    verify_ref(r["implementation_ref"], root=root)
    handoff = verify_ref(r["handoff_ref"], root=root)
    from factor_factory.code_review_checkpoint import validate_code_review
    gate = validate_code_review(workspace_root=root, report_id=r["report_id"], repo_root=repo,
                                handoff=handoff, spec=r["spec_ref"]["path"])
    if gate.get("status") != "PASS":
        raise SearchError("native code review/post-review tests not ready: " + ";".join(gate.get("reasons", [])))
    if Path(gate["implementation_path"]).resolve() != Path(r["implementation_ref"]["path"]).resolve():
        raise SearchError("reviewed native implementation differs from request")
    protocol = bound_json(context["development_protocol"], root=context["workspace_root"])
    data = bound_json(r["data_binding_ref"], root=root)
    if (data.get("development_protocol_sha256") != context["development_protocol"]["sha256"]
            or data.get("input_refs") != protocol["input_refs"]
            or data.get("data_kind") != protocol["data_kind"]
            or data.get("split") != "development"):
        raise SearchError("native data/split bindings do not match campaign")
    for ref in data["input_refs"]:
        verify_ref(ref)
    for name in ("calendar_ref", "universe_ref", "information_time_ref", "split_manifest_ref"):
        if data.get(name) != protocol[name]:
            raise SearchError(f"native {name} mismatch")
    # Bind the selection Step4 actually consumes, not just an unused sidecar.
    dpm = bound_json(r["data_prep_ref"], root=root)
    transfer = bound_json(r["handoff_ref"], root=root)
    local = transfer.get("local_input_paths") or dpm.get("local_input_paths") or {}
    if not local or data.get("native_local_inputs") != local:
        raise SearchError("actual native input selection differs from data binding")
    bound_native_input_paths(local, r, protocol)
    from factor_factory.prepared_daily_inputs import is_prepared_daily
    for obj in (dpm, transfer, local):
        if obj.get("research_windows") or ((obj.get("step4_data_contract") or {}).get("full_queries") and not is_prepared_daily(local)):
            raise SearchError("dynamic rematerialization/heldout route requires a dedicated binding adapter")
    metrics = Path(text(r["metrics_path"], "metrics_path"))
    if not metrics.is_absolute() or not metrics.resolve().is_relative_to(root.resolve()):
        raise SearchError("native metrics must be an explicit child-workspace artifact")
    _native_proof(r["step3_proof_ref"], r, ("run_step3b", "validate_step3b"))
    return r


def validate_preparation(request: Mapping[str, Any], ticket: Mapping[str, Any]) -> float:
    receipt = bound_json(request["readiness_ref"])
    if receipt.get("ticket_id") != ticket["ticket_id"]:
        raise SearchError("preparation must bind the reserved ticket")
    started, finished = timestamp(receipt.get("started_at")), timestamp(receipt.get("finished_at"))
    if started < timestamp(ticket["created_at"]) or finished < started or finished > datetime.now(timezone.utc):
        raise SearchError("preparation occurred before the trial reservation")
    cost = number(receipt.get("preparation_cost_seconds"), "preparation cost", minimum=0)
    if cost > ticket["reserved_compute_cost"] or cost > (finished - started).total_seconds():
        raise SearchError("preparation cost exceeds its reservation/time bounds")
    proofs = [bound_json(request["step3_proof_ref"])]
    if receipt.get("step2_revision_ref"):
        proofs.append(bound_json(receipt["step2_revision_ref"]))
    command_seconds = 0.0
    for proof in proofs:
        for row in proof["commands"]:
            begin, end = timestamp(row["started_at_utc"]), timestamp(row["finished_at_utc"])
            if begin < started or end > finished or end < begin:
                raise SearchError("Step2/3 evidence predates reservation/preparation receipt")
            command_seconds += (end - begin).total_seconds()
    if cost + 1e-6 < command_seconds:
        raise SearchError("preparation cost omits observed native command time")
    return cost


def command_for_ticket(ticket: Mapping[str, Any], proof_output: str | Path) -> list[str]:
    r = ticket["native_request"]
    return [r["python"], str(Path(r["repo_root"]) / "scripts/run_factorforge_ultimate.py"),
            "--report-id", r["report_id"], "--manifest", r["manifest_ref"]["path"],
            "--factor-workspace", r["workspace_root"],
            "--start-step", "4", "--end-step", "5", "--local-is-only",
            "--proof-output", str(proof_output)]


def score_native_metric(rule: Mapping[str, Any], metrics: Mapping[str, Any]) -> tuple[float, float, float]:
    """Project an existing metric using the frozen rule, without recomputing it."""
    if metrics.get("status") != "success" or metrics.get("evaluation_scope") != rule["evaluation_scope"]:
        raise SearchError("native metric success/scope mismatch")
    if rule["evaluation_scope"] == "account" and metrics.get("account_simulation") is not True:
        raise SearchError("account score requires actual account evidence")
    count = integer(pointer(metrics, rule["sample_count_pointer"]), "metric sample count")
    if rule["unit_pointer"] is None:
        if (metrics.get("backend") != "self_quant_analyzer" or metrics.get("engine") != "self_quant_adapter_quick_mode"
                or rule["metric_pointer"] != "/ic_summary/rank_ic_mean" or rule["sample_count_pointer"] != "/coverage/rank_ic_count"
                or rule["evaluation_scope"] != "signal_diagnostic"):
            raise SearchError("registered rank-IC units require native self-quant output")
        unit = "dimensionless"
    else:
        unit = pointer(metrics, rule["unit_pointer"])
    if count < rule["minimum_samples"] or unit != rule["unit"]:
        raise SearchError("native metric coverage/unit mismatch")
    metric = number(pointer(metrics, rule["metric_pointer"]), "native metric")
    score = rule["direction"] * (metric - rule["baseline"]) / rule["scale"]
    number(score, "candidate score")
    return metric, score, max(-1.0, min(1.0, score))


def collect_result(context: Mapping[str, Any], proposal: Mapping[str, Any], ticket: Mapping[str, Any],
                   result_ref: Mapping[str, str]) -> dict[str, Any]:
    """Read fresh artifact bytes; compute the fixed score, never trust a supplied score."""
    validate_context(context)
    stopped = bound_json(result_ref, root=context["workspace_root"]) if ticket.get("native_request") is None else None
    if stopped is not None:
        if (set(stopped) != {"contract_version", "ticket_id", "context_hash", "candidate_hash", "actor", "reason", "stopped_at"}
                or stopped.get("contract_version") != "factor_search_preparation_stopped_v1"
                or stopped.get("ticket_id") != ticket["ticket_id"] or stopped.get("context_hash") != digest(context)
                or stopped.get("candidate_hash") != proposal["candidate_hash"]
                or timestamp(stopped["stopped_at"]) < timestamp(ticket["created_at"])):
            raise SearchError("preparation stop receipt invalid")
        text(stopped["actor"], "host actor")
        text(stopped["reason"], "stop reason")
        return {"ticket_id": ticket["ticket_id"], "candidate_hash": proposal["candidate_hash"], "status": "BLOCKED",
                "split": "development", "protocol_hash": context["development_protocol"]["sha256"],
                "score_contract_hash": digest(context["score_contract"]), "metric_value": None, "candidate_score": None,
                "learning_increment": None, "actual_cost": None, "data_kind": bound_json(context["development_protocol"])["data_kind"],
                "evidence_ref": dict(result_ref), "error": stopped["reason"]}
    request = validate_request(context, proposal, ticket["native_request"])
    preparation_cost = validate_preparation(request, ticket)
    result = bound_json(result_ref, root=request["workspace_root"])
    required = {"contract_version", "ticket_id", "candidate_hash", "context_hash", "request_hash",
                "split", "data_kind", "status", "actual_cost", "proof_ref", "run_master_ref",
                "metrics_ref", "error", "execution_receipt_ref"}
    if set(result) != required or result.get("contract_version") != RESULT_VERSION:
        raise SearchError("native result fields/version mismatch")
    for key, expected in (("ticket_id", ticket["ticket_id"]), ("candidate_hash", proposal["candidate_hash"]),
                          ("context_hash", digest(context)), ("request_hash", digest(request)), ("split", "development")):
        if result[key] != expected:
            raise SearchError(f"native result {key} mismatch")
    protocol = bound_json(context["development_protocol"])
    if result["data_kind"] != protocol["data_kind"]:
        raise SearchError("engineering evidence cannot become market evidence")
    status = result["status"]
    if status not in {"COMPLETED", "FAILED_KNOWN_COST", "FAILED_UNKNOWN_COST", "BLOCKED"}:
        raise SearchError("pending result is not terminal feedback")
    cost = result["actual_cost"]
    if cost is not None:
        cost = number(cost, "native actual cost", minimum=0)
    if status in {"COMPLETED", "FAILED_KNOWN_COST"} and cost is None:
        raise SearchError("known completion/cost required for terminal result")
    if status == "FAILED_UNKNOWN_COST" and cost is not None:
        raise SearchError("unknown cost must remain null")
    receipt = bound_json(result["execution_receipt_ref"], root=request["workspace_root"])
    receipt_keys = {"contract_version", "ticket_id", "request_hash", "command", "cwd", "started_at", "finished_at",
                    "elapsed_seconds", "returncode", "output_refs"}
    if (set(receipt) != receipt_keys or receipt.get("contract_version") != "factor_search_execution_receipt_v1"
            or receipt.get("ticket_id") != ticket["ticket_id"] or receipt.get("request_hash") != digest(request)
            or receipt.get("cwd") != request["repo_root"]
            or receipt.get("command") != command_for_ticket(ticket, result["proof_ref"]["path"])
            or timestamp(receipt.get("started_at")) < timestamp(bound_json(request["readiness_ref"])["finished_at"])):
        raise SearchError("native execution receipt identity/command/order mismatch")
    started, finished = timestamp(receipt["started_at"]), timestamp(receipt["finished_at"])
    if not started <= finished <= datetime.now(timezone.utc):
        raise SearchError("native execution receipt has an invalid/future time interval")
    elapsed = receipt["elapsed_seconds"]
    if elapsed is not None:
        elapsed = number(elapsed, "execution elapsed", minimum=0)
        # Both timestamps and monotonic time come from this worker. Allow only
        # 50 ms of wall-clock adjustment/bookkeeping, not caller-defined slack.
        if abs((finished - started).total_seconds() - elapsed) > .05:
            raise SearchError("native wall and monotonic elapsed time disagree")
    if cost is not None and (elapsed is None or cost != preparation_cost + elapsed):
        raise SearchError("total cost must include native preparation and execution receipts")
    proof = bound_json(result["proof_ref"], root=request["workspace_root"])
    if proof.get("report_id") != request["report_id"]:
        raise SearchError("native failure proof report mismatch")
    metric_value = score_value = increment = None
    if status == "COMPLETED":
        if type(receipt["returncode"]) is not int or receipt["returncode"] != 0 or elapsed is None or elapsed <= 0:
            raise SearchError("successful native execution requires exit zero and positive measured duration")
        if receipt["output_refs"] != [result[k] for k in ("proof_ref", "run_master_ref", "metrics_ref")]:
            raise SearchError("result artifacts differ from the native worker capture")
        _native_proof(result["proof_ref"], request,
                      ("run_step4", "validate_step4", "run_step5", "validate_step5"))
        command_seconds = 0.0
        # Historical wrappers may serialize UTC command timestamps to seconds.
        precision = timedelta(seconds=1)
        for command in proof["commands"]:
            begin, end = timestamp(command["started_at_utc"]), timestamp(command["finished_at_utc"])
            if not started - precision <= begin <= end <= finished + precision:
                raise SearchError("native proof command is outside this execution window")
            command_seconds += (end - begin).total_seconds()
        if command_seconds > elapsed + 1:
            raise SearchError("execution cost omits native command time")
        for ref in receipt["output_refs"]:
            artifact = verify_ref(ref, root=request["workspace_root"])
            if artifact.stat().st_mtime_ns < int(started.timestamp() * 1e9):
                raise SearchError("native result artifact predates this execution")
        master = bound_json(result["run_master_ref"], root=request["workspace_root"])
        if master.get("report_id") != request["report_id"]:
            raise SearchError("native run-master report mismatch")
        runs = (master.get("evaluation_results") or {}).get("backend_runs") or []
        declared = [str(Path(run["payload_path"]).resolve()) for run in runs
                    if isinstance(run, dict) and isinstance(run.get("payload_path"), str)]
        metrics_path = verify_ref(result["metrics_ref"], root=request["workspace_root"])
        if str(metrics_path.resolve()) != str(Path(request["metrics_path"]).resolve()) or str(metrics_path.resolve()) not in declared:
            raise SearchError("score payload must be the declared native backend result")
        metrics = bound_json(result["metrics_ref"], root=request["workspace_root"])
        if metrics.get("report_id") != request["report_id"] or metrics.get("status") != "success":
            raise SearchError("native metric payload identity/status mismatch")
        rule = context["score_contract"]
        metric_value, score_value, increment = score_native_metric(rule, metrics)
    elif proof.get("status") == "PASS" and status not in {"FAILED_UNKNOWN_COST", "BLOCKED"}:
        raise SearchError("failure feedback must retain a failed native proof")
    else:
        text(result["error"], "native failure reason")
    if cost is not None and cost > ticket["reserved_compute_cost"]:
        status = "BLOCKED"
        score_value = increment = None
        result["error"] = "actual compute cost exceeded reservation; retained full cost"
    return {"ticket_id": ticket["ticket_id"], "candidate_hash": proposal["candidate_hash"],
            "status": status, "split": "development", "protocol_hash": context["development_protocol"]["sha256"],
            "score_contract_hash": digest(context["score_contract"]), "metric_value": metric_value,
            "candidate_score": score_value, "learning_increment": increment, "actual_cost": cost,
            "data_kind": result["data_kind"], "evidence_ref": dict(result_ref), "error": result["error"]}
