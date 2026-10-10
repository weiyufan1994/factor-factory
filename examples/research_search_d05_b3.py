"""Bridge one reviewed Step2 ticket into search proposals and Step6 material.

This example operates on an existing local campaign ledger. It does not create
review evidence, run native Step3/4/5, or turn pending work into a score. The
grammar JSON is a host-authored declaration whose claims must match the bound
Step2 measurement program before any proposal can be generated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_search.contracts import read_json
from factor_factory.research_search.controller import ResearchSearchController
from factor_factory.research_search.executor import FileNativeExecutor
from factor_factory.research_search.induction import FieldSpec, SemanticType, Unit
from factor_factory.research_search.ledger import SearchLedger
from factor_factory.research_search.ultimate_cycle import (
    Step2GrammarDeclaration,
    TwoLevelCandidateProposer,
    bind_reviewed_step2_scope,
    publish_step6_search_material,
)


def _semantic_type(value: dict) -> SemanticType:
    dimensions = tuple((str(name), int(power)) for name, power in value["unit"])
    return SemanticType(
        shape=value["shape"], value_type=value["value_type"], unit=Unit(dimensions),
        clock=value["clock"], grouping=value["grouping"],
        information_semantics=value["information_semantics"],
    )


def _declaration(path: Path) -> Step2GrammarDeclaration:
    value = read_json(path)
    fields = tuple(FieldSpec(row["name"], _semantic_type(row["semantic_type"]))
                   for row in value.pop("allowed_fields"))
    output_type = _semantic_type(value.pop("output_type"))
    for key in ("allowed_operators", "allowed_variation_evidence", "parent_delta"):
        value[key] = tuple(value.get(key, ()))
    for key in ("allowed_constants", "allowed_windows"):
        value[key] = tuple(value[key])
    return Step2GrammarDeclaration(allowed_fields=fields, output_type=output_type, **value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--ticket", required=True,
                        help="A ticket with an already validated native request")
    parser.add_argument("--grammar", type=Path, required=True,
                        help="Machine-readable grammar declaration JSON")
    parser.add_argument("--proposals", type=int, default=0,
                        help="Register this many bounded AST proposals; zero only inspects/publishes")
    args = parser.parse_args()
    if args.proposals < 0:
        parser.error("--proposals must be zero or greater")

    ledger = SearchLedger(args.workspace)
    snapshot = ledger.snapshot(args.campaign)
    ticket = ledger.ticket(args.campaign, args.ticket)
    proposals = {row["candidate_hash"]: json.loads(row["proposal_json"])
                 for row in snapshot["proposals"]}
    proposal = proposals[ticket["candidate_hash"]]
    binding = bind_reviewed_step2_scope(
        snapshot["context"], proposal, ticket, _declaration(args.grammar))
    controller = ResearchSearchController(
        ledger, args.campaign, FileNativeExecutor(args.workspace))
    registration = {"registered": [], "duplicates": []}
    if args.proposals:
        registration = controller.propose(
            TwoLevelCandidateProposer(binding, population_size=args.proposals))
    material = publish_step6_search_material(controller, binding)
    print(json.dumps({
        "scope": {
            "review_binding_hash": binding.review_binding_hash,
            "induction_record_hash": binding.scope.induction_record.record_hash,
            "induction_scope_hash": binding.scope.scope_hash,
            "response_family": binding.scope.response_family,
        },
        "proposal_registration": registration,
        "step6_material_ref": material["material_ref"],
        "step6_summary": {
            "terminal_count": len(material["material"]["terminal_expression_evidence"]),
            "pending_ticket_ids": material["material"]["pending_ticket_ids"],
            "mechanism_assessment": material["material"]["mechanism_assessment"],
            "next_action": material["material"]["next_action"],
        },
        "boundary": "local development evidence only; Step6 judgment remains external",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
