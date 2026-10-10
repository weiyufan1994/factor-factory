from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

from factor_factory.factors import FormulaFactor
from factor_factory.measurement_program import MEASUREMENT_PROGRAM_VERSION_V2
from factor_factory.research_search.contracts import (
    SearchError, candidate_hash, digest, file_ref, program_identity, read_json,
)
from factor_factory.research_search.controller import ResearchSearchController
from factor_factory.research_search.executor import FileNativeExecutor
from factor_factory.research_search.induction import FieldSpec, SemanticType, Unit
from factor_factory.research_search.ledger import SearchLedger
from factor_factory.research_search.native import native_source_pin
from factor_factory.research_search.ultimate_cycle import (
    CAUSAL_AFFINE_VARIATIONS, Step2GrammarDeclaration, TwoLevelCandidateProposer, bind_reviewed_step2_scope,
    grammar_declaration_payload, publish_step6_search_material,
)
from tests.test_factorforge_measurement_program_research_equation_v2 import _filled_program
from tests.test_research_search_interface import REPO, case, proof, put, result, stamp


VARIATIONS = CAUSAL_AFFINE_VARIATIONS


def _reviewed_case(case, *, reviewed_program_change=False):
    root = case["root"]
    program = _filled_program(MEASUREMENT_PROGRAM_VERSION_V2)
    program["search_policy"]["allowed_model_or_estimator_variations"].extend(VARIATIONS)
    source_spec = put(root / "b3-step2-spec.json", {
        "report_id": case["context"]["report_id"],
        "mechanism_conditioned_measurement_program": program,
    })
    measurement = put(root / "b3-measurement.json", program)
    c = deepcopy(case["context"])
    c["campaign_id"] = "b3-cycle"
    c["source_refs"] = {"step2_spec": source_spec, "measurement_program": measurement}
    projection = read_json(c["projection_ref"]["path"])
    projection["source_refs"] = c["source_refs"]
    c["projection_ref"] = put(root / "b3-projection.json", projection)
    authority = read_json(c["budget_authority"]["path"])
    authority["campaign_id"] = c["campaign_id"]
    c["budget_authority"] = put(root / "b3-budget.json", authority)
    p = deepcopy(case["proposal"])
    selected = next(row for row in program["model_selection"]["candidate_models"] if row["selected"])
    p["semantics"]["mathematical_object"] = selected["mechanism_equation_or_functional"]
    p["semantics"]["observation_map"] = program["observation_and_estimation"]["observation_map"]
    p["candidate_hash"] = candidate_hash(p)
    p["public_derivation_ref"] = measurement
    c["root_candidate_hash"] = p["candidate_hash"]
    p["context_hash"] = digest(c)
    ledger = SearchLedger(root)
    ledger.create_campaign(c)
    ledger.register(c["campaign_id"], [p])
    controller = ResearchSearchController(ledger, c["campaign_id"], FileNativeExecutor(root))
    signal = SemanticType("panel", "numeric", Unit.dimensionless(),
                          "session_close", "instrument_ts", "observed_at_or_before_t")
    declaration = Step2GrammarDeclaration(
        response_family="causal_affine_response_estimator",
        mathematical_object=selected["mechanism_equation_or_functional"],
        observation_map=program["observation_and_estimation"]["observation_map"],
        allowed_fields=(FieldSpec("close", signal), FieldSpec("open", signal)), output_type=signal,
        allowed_operators=("plus", "minus", "multiply", "delay", "mean"),
        allowed_constants=(-1.0, 0.5, 1.0, 2.0), allowed_windows=(1, 2, 3), max_depth=4,
        missing_value_policy="preserve reviewed Formula warmup and NaN",
        numeric_domain="finite engineering-fixture inputs",
        allowed_variation_evidence=VARIATIONS,
        units_evidence=p["semantics"]["units"],
        information_time_evidence=p["semantics"]["information_time"],
        missing_zero_evidence=p["semantics"]["missing_zero_policy"],
    )
    revised = {**case, "context": c, "proposal": p, "ledger": ledger, "controller": controller}
    reviewed_program = deepcopy(program)
    if reviewed_program_change:
        reviewed_program["observation_and_estimation"]["observation_map"] += " reviewed-only change"
    ticket = _ready(revised, _dispatch(revised), declaration=declaration,
                    reviewed_program=reviewed_program)
    return revised, ticket, declaration


def _dispatch(case):
    campaign = case["context"]["campaign_id"]
    out = case["controller"].tick()
    assert out["state"] == "RESERVED"
    assert case["controller"].tick()["state"] == "WAITING_PREPARATION"
    return case["ledger"].ticket(campaign, out["ticket_id"])


def _ready(case, ticket, proposal=None, *, declaration, reviewed_program=None):
    c, p = case["context"], proposal or case["proposal"]
    campaign = c["campaign_id"]
    root = case["tmp"] / (campaign + "-" + p["candidate_hash"][:12])
    root.mkdir(exist_ok=True)
    rid = c["report_id"] + "_B3_" + p["candidate_hash"][:12].upper()
    started = stamp(-500)
    if reviewed_program is None:
        source = read_json(c["source_refs"]["measurement_program"]["path"])
        reviewed_program = source.get("mechanism_conditioned_measurement_program", source)
    spec = put(root / "spec.json", {
        "report_id": rid,
        "mechanism_conditioned_measurement_program": reviewed_program,
        "research_search_grammar_declaration": grammar_declaration_payload(declaration),
        "research_search_lineage": {
            "base_context_hash": digest(c),
            "base_source_refs": c["source_refs"],
            "candidate_hash": p["candidate_hash"],
            "parent_candidate_hash": p["parent_candidate_hash"],
            "mutation_class": p["mutation_class"],
        },
    })
    code = root / "implementation.py"
    code.write_text("raise RuntimeError('review-only synthetic implementation')\n")
    impl = file_ref(code)
    local = {"input_mode": "daily_only", "daily_df_csv": str(case["root"] / "data.csv")}
    transfer = put(root / "handoff.json", {"report_id": rid, "factor_impl_ref": str(code), "local_input_paths": local})
    prep = put(root / "prep.json", {"report_id": rid, "local_input_paths": local})
    manifest = put(root / "manifest.json", {"report_id": rid, "repo_root": str(REPO), "factor_workspace": str(root),
                 "objects": {"factor_spec_master": spec["path"], "handoff_to_step4": transfer["path"],
                             "data_prep_master": prep["path"]}})
    log = root / "tests.log"
    log.write_text("Synthetic B3 fixture review\n")
    files = [{"role": role, **ref} for role, ref in (("spec", spec), ("implementation", impl))]
    review = put(root / "objects/research_journal" / f"code_review__{rid}.json", {
        "report_id": rid, "author_id": "fixture-author", "reviewer_id": "fixture-reviewer",
        "reviewed_at": stamp(-400), "decision": "proceed", "summary": "Synthetic B3 review", "findings": [],
        "reviewed_files": files, "post_review_tests": {"status": "PASS", "started_at": stamp(-390),
            "completed_at": stamp(-380), "evidence": [file_ref(log)], "tested_files": files}})
    protocol = read_json(c["development_protocol"]["path"])
    binding = put(root / "binding.json", {**protocol,
        "development_protocol_sha256": c["development_protocol"]["sha256"], "native_local_inputs": local})
    pin = put(root / "pin.json", native_source_pin(REPO))
    request = {"contract_version": "factor_search_native_request_v1", "context_hash": digest(c),
        "candidate_hash": p["candidate_hash"], "report_id": rid, "workspace_root": str(root),
        "repo_root": str(REPO), "python": sys.executable,
        "python_ref": file_ref(Path(sys.executable).resolve()), "repo_pin_ref": pin,
        "manifest_ref": manifest, "spec_ref": spec, "implementation_ref": impl,
        "handoff_ref": transfer, "data_prep_ref": prep, "data_binding_ref": binding,
        "metrics_path": str(root / "metrics.json")}
    finished = stamp(-300)
    request["step3_proof_ref"] = put(root / "step3.json", proof(
        request, ["run_step3b", "validate_step3b"], started, finished))
    request["readiness_ref"] = put(root / "ready.json", {
        "ticket_id": ticket["ticket_id"], "candidate_hash": p["candidate_hash"],
        "context_hash": digest(c), "decision": "proceed", "mutation_class": p["mutation_class"],
        "base_source_refs": c["source_refs"], "accepted_semantics": p["semantics"],
        "accepted_program_identity": program_identity(p["program"]), "step2_spec_ref": spec,
        "implementation_ref": impl, "review_ref": review, "post_review_tests_ref": file_ref(log),
        "started_at": started, "finished_at": finished, "preparation_cost_seconds": 0})
    case["ledger"].prepare(campaign, p["candidate_hash"], request)
    return case["ledger"].ticket(campaign, ticket["ticket_id"])


def test_reviewed_step2_binding_consumes_native_readiness_and_exact_scope(case):
    reviewed, ticket, declaration = _reviewed_case(case)
    binding = bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
    assert binding.scope.induction_record.origin == "reviewed_fixture"
    assert binding.scope.induction_record.data_exposure == "synthetic_only"
    assert binding.scope.induction_record.review_binding_hash == binding.review_binding_hash
    assert binding.scope.induction_record.source_ref == ticket["native_request"]["spec_ref"]["path"]
    assert binding.scope.mathematical_object == declaration.mathematical_object
    assert binding.scope.observation_map == declaration.observation_map

    wrong = Step2GrammarDeclaration(**{**declaration.__dict__, "mathematical_object": "changed object"})
    with pytest.raises(SearchError, match="code-reviewed Step2 spec"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, wrong)


def test_reviewed_step2_binding_passes_program_profile_and_native_scope(case, monkeypatch):
    reviewed, ticket, declaration = _reviewed_case(case)
    import factor_factory.research_search.ultimate_cycle as cycle
    actual = cycle.validate_measurement_program
    captured = {}

    def recording_validator(program, **options):
        captured.update(options)
        return actual(program, **options)

    monkeypatch.setattr(cycle, "validate_measurement_program", recording_validator)
    bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
    reviewed_spec = read_json(ticket["native_request"]["spec_ref"]["path"])
    program = reviewed_spec["mechanism_conditioned_measurement_program"]
    assert captured == {
        "require_web_executable": False,
        "compatibility_profile": program.get("compatibility_profile"),
        "scope": "local_is_only",
    }


def test_generated_ast_children_use_existing_proposer_and_ledger_path(case):
    reviewed, ticket, declaration = _reviewed_case(case)
    binding = bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
    provider = TwoLevelCandidateProposer(binding, population_size=3)
    registered = reviewed["controller"].propose(provider)
    assert len(registered["registered"]) == 3
    snapshot = reviewed["ledger"].snapshot("b3-cycle")
    children = [row for row in snapshot["proposals"] if row["candidate_hash"] != reviewed["proposal"]["candidate_hash"]]
    assert len(children) == 3
    for row in children:
        proposal = __import__("json").loads(row["proposal_json"])
        assert proposal["mutation_class"] == "measurement_variant"
        assert proposal["parent_candidate_hash"] == reviewed["proposal"]["candidate_hash"]
        assert proposal["semantics"] == reviewed["proposal"]["semantics"]
        assert proposal["changes"] == ["observation_map", "implementation"]
    count = len(snapshot["proposals"])
    recovered = TwoLevelCandidateProposer(binding, population_size=3)
    assert reviewed["controller"].propose(recovered) == {"registered": [], "duplicates": []}
    assert len(reviewed["ledger"].snapshot("b3-cycle")["proposals"]) == count
    assert recovered.propose(reviewed["controller"].proposer_context(), max_proposals=0, seed=7) == []
    assert recovered.trace == ()
    with pytest.raises(ValueError, match="positive integer"):
        TwoLevelCandidateProposer(binding, population_size=0)


def test_pending_is_not_scored_and_terminal_native_metric_becomes_step6_material(case):
    reviewed, ticket, declaration = _reviewed_case(case)
    binding = bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
    pending = publish_step6_search_material(reviewed["controller"], binding)
    assert pending["material"]["pending_ticket_ids"] == [ticket["ticket_id"]]
    assert pending["material"]["terminal_expression_evidence"] == []
    assert pending["material"]["mechanism_assessment"].startswith("unknown")

    running = reviewed["ledger"].transition(ticket["ticket_id"], {"READY"}, "RUNNING")
    reviewed["ledger"].record_feedback(ticket["ticket_id"], result(reviewed, running, value=0.25))
    terminal = publish_step6_search_material(reviewed["controller"], binding)
    row = terminal["material"]["terminal_expression_evidence"][0]
    assert row["candidate_score"] == 0.25
    assert row["interpretation"] == "implementation_or_estimator_evidence_only"
    assert terminal["material"]["pending_ticket_ids"] == []
    assert terminal["material"]["mechanism_assessment"].startswith("unknown")
    assert publish_step6_search_material(reviewed["controller"], binding)["material_ref"] == terminal["material_ref"]
    with pytest.raises(SearchError, match="controller/campaign differs"):
        publish_step6_search_material(
            reviewed["controller"], replace(binding, context_hash="0" * 64))


def test_feedback_generates_formula_and_routes_novel_ast_back_to_step2(case):
    reviewed, ticket, declaration = _reviewed_case(case)
    binding = bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
    running = reviewed["ledger"].transition(ticket["ticket_id"], {"READY"}, "RUNNING")
    reviewed["ledger"].record_feedback(ticket["ticket_id"], result(reviewed, running, value=0.4))
    provider = TwoLevelCandidateProposer(binding, population_size=2)
    registered = reviewed["controller"].propose(provider)["registered"]
    snapshot = reviewed["ledger"].snapshot("b3-cycle")
    proposals = {row["candidate_hash"]: __import__("json").loads(row["proposal_json"])
                 for row in snapshot["proposals"]}
    child_reservation = reviewed["controller"].tick()
    assert child_reservation["state"] == "RESERVED"
    dispatch = reviewed["controller"].tick()
    assert dispatch["state"] == "WAITING_PREPARATION"
    assert read_json(dispatch["action_ref"]["path"])["entry_step"] == "2"
    child_ticket = reviewed["ledger"].ticket("b3-cycle", child_reservation["ticket_id"])
    child = proposals[child_ticket["candidate_hash"]]
    assert child["parent_candidate_hash"] == reviewed["proposal"]["candidate_hash"]
    frame = pd.DataFrame({
        "ts_code": ["A", "A", "B", "B"],
        "trade_date": ["20250102", "20250103", "20250102", "20250103"],
        "close": [1.0, 2.0, 3.0, 4.0], "open": [0.5, 1.0, 2.0, 2.5],
    })
    values = FormulaFactor(child["program"]["expression"], name="b3-synthetic")({"daily_df": frame})
    assert len(values) == len(frame)
    assert values.index.is_unique


def test_unreviewed_or_unadmitted_scope_fails_before_generation(case):
    reviewed, ticket, declaration = _reviewed_case(case)
    missing = Step2GrammarDeclaration(**{**declaration.__dict__,
        "allowed_variation_evidence": ("nonlinear variable product",)})
    with pytest.raises(SearchError, match="code-reviewed Step2 spec"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, missing)
    unprepared = dict(ticket)
    unprepared["native_request"] = None
    with pytest.raises(SearchError, match="prepared native request"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], unprepared, declaration)
    wrong_ticket = dict(ticket)
    wrong_ticket["candidate_hash"] = "0" * 64
    with pytest.raises(SearchError, match="ticket identity mismatch"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], wrong_ticket, declaration)
    stale_parent = Step2GrammarDeclaration(**{**declaration.__dict__,
        "parent_induction_id": "prior", "parent_delta": ("changed response",)})
    with pytest.raises(SearchError, match="code-reviewed Step2 spec"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, stale_parent)
    wrong_units = Step2GrammarDeclaration(**{**declaration.__dict__, "units_evidence": "different units"})
    with pytest.raises(SearchError, match="code-reviewed Step2 spec"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, wrong_units)


@pytest.mark.parametrize("change", ["field_unit", "window", "operator", "parent_delta"])
def test_reviewed_grammar_rejects_unreviewed_structural_change(case, change):
    reviewed, ticket, declaration = _reviewed_case(case)
    values = dict(declaration.__dict__)
    if change == "field_unit":
        field = declaration.allowed_fields[0]
        changed = SemanticType(
            field.semantic_type.shape, field.semantic_type.value_type, Unit.named("price"),
            field.semantic_type.clock, field.semantic_type.grouping,
            field.semantic_type.information_semantics,
        )
        values["allowed_fields"] = (FieldSpec(field.name, changed), *declaration.allowed_fields[1:])
    elif change == "window":
        values["allowed_windows"] = declaration.allowed_windows + (5,)
    elif change == "operator":
        values["allowed_operators"] = declaration.allowed_operators + ("divide",)
    else:
        values["parent_induction_id"] = "unreviewed-parent"
        values["parent_delta"] = ("unreviewed response change",)
    with pytest.raises(SearchError, match="code-reviewed Step2 spec"):
        bind_reviewed_step2_scope(
            reviewed["context"], reviewed["proposal"], ticket,
            Step2GrammarDeclaration(**values))


def test_reviewed_spec_cannot_silently_differ_from_base_program(case):
    reviewed, ticket, declaration = _reviewed_case(case, reviewed_program_change=True)
    with pytest.raises(SearchError, match="differs from base Step2 program"):
        bind_reviewed_step2_scope(reviewed["context"], reviewed["proposal"], ticket, declaration)
