"""JSON contracts for evidence-bound, asynchronous factor search.

Proposals are data. A provider cannot change the campaign budget, invent native
results, execute a formula, or supply an alternative scoring rule in a batch.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Protocol

CONTEXT_VERSION = "factor_search_context_v1"
PROPOSAL_VERSION = "factor_search_proposal_v1"
REQUEST_VERSION = "factor_search_native_request_v1"
RESULT_VERSION = "factor_search_native_result_v1"
MAX_JSON_BYTES = 8 * 1024 * 1024
MUTATIONS = {"implementation_equivalent", "measurement_variant", "new_mechanism"}
TERMINAL = {"COMPLETED", "FAILED_KNOWN_COST", "FAILED_UNKNOWN_COST", "BLOCKED"}
PENDING = {"RESERVED", "DISPATCHING", "DISPATCHED", "WAITING_PREPARATION", "WAITING_REVIEW", "READY", "RUNNING", "INTERRUPTED"}


class SearchError(ValueError):
    """A specific interface violation; callers must preserve its evidence."""


class CandidateProposer(Protocol):
    def propose(self, context: Mapping[str, Any], *, max_proposals: int,
                seed: int) -> Sequence[Mapping[str, Any]]: ...


class NativeExecutor(Protocol):
    """Implementations must make dispatch idempotent by ticket_id.

    poll returns a pending state or a byte-bound result reference. It must never
    claim completion merely because a request was accepted or a process exited.
    """
    def dispatch(self, ticket: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def poll(self, ticket: Mapping[str, Any]) -> Mapping[str, Any]: ...


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise SearchError("non-JSON or nonfinite contract value") from exc


def digest(value: Any) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SearchError(f"{label}: nonempty unpadded string required")
    return value


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise SearchError(f"{label}: invalid identifier")
    return value


def hash_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SearchError(f"{label}: SHA256 required")
    return value


def number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if type(value) not in (float, int) or not isfinite(value):
        raise SearchError(f"{label}: finite number required")
    if minimum is not None and value < minimum:
        raise SearchError(f"{label}: below minimum {minimum}")
    return float(value)


def integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SearchError(f"{label}: integer >= {minimum} required")
    return value


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SearchError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise SearchError(f"regular JSON file required: {path}")
    with path.open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise SearchError("control JSON exceeds size limit")
    try:
        value = json.loads(raw, object_pairs_hook=_object_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(SearchError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SearchError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SearchError("JSON object required")
    return value


def file_ref(path: str | Path) -> dict[str, str]:
    path = Path(path).absolute()
    if not path.is_file() or path.is_symlink():
        raise SearchError(f"regular evidence file required: {path}")
    stat = path.stat()
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return {"path": str(path), "sha256": _file_digest(str(path), identity)}


@lru_cache(maxsize=4096)
def _file_digest(path: str, identity: tuple) -> str:
    """Avoid re-reading unchanged minute files on every control-plane tick.

    Cache only within this host process; inode, size, nanosecond mtime AND ctime
    must all agree. A changed file is always streamed and hashed again.
    """
    h = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    stat = Path(path).stat()
    if identity != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
        raise SearchError("evidence changed while hashing")
    return h.hexdigest()


def verify_ref(ref: Any, *, root: str | Path | None = None) -> Path:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise SearchError("evidence reference requires exact path and sha256")
    path = Path(text(ref["path"], "evidence path"))
    if not path.is_absolute():
        raise SearchError("evidence path must be absolute")
    if root is not None and not path.resolve().is_relative_to(Path(root).resolve()):
        raise SearchError("evidence outside declared workspace")
    hash_value(ref["sha256"], "evidence sha256")
    if file_ref(path) != ref:
        raise SearchError(f"evidence bytes changed: {path}")
    return path


def bound_json(ref: Any, *, root: str | Path | None = None) -> dict[str, Any]:
    path = verify_ref(ref, root=root)
    result = read_json(path)
    # Detect a replacement between verifying and decoding the control record.
    verify_ref(ref, root=root)
    return result


def pointer(value: Any, path: str) -> Any:
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
        raise SearchError("explicit JSON pointer required")
    try:
        for part in path[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SearchError(f"missing metric/evidence pointer: {path}") from exc
    return value


def timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(text(value, "timestamp"))
    except ValueError as exc:
        raise SearchError("ISO timestamp required") from exc
    if parsed.utcoffset() is None:
        raise SearchError("timestamp must carry a timezone")
    return parsed


def reservation_cost(context: Mapping[str, Any]) -> float:
    policy = bound_json(context["budget_authority"])["execution_cost_policy"]
    return policy["preparation_seconds"] + policy["native_seconds"]


def validate_context(context: Mapping[str, Any]) -> dict[str, Any]:
    c = json.loads(canonical(context))
    allowed = {"contract_version", "campaign_id", "report_id", "workspace_root",
               "origin", "root_candidate_hash", "source_refs", "development_protocol",
               "budget_authority", "score_contract", "allowed_mutation_classes",
               "max_depth", "max_proposals", "seed", "planner_kind", "compute_cost_unit", "projection_ref"}
    if set(c) != allowed or c.get("contract_version") != CONTEXT_VERSION:
        raise SearchError("context fields/version mismatch; held-out inputs are forbidden")
    identifier(c["campaign_id"], "campaign_id")
    identifier(c["report_id"], "report_id")
    root = Path(text(c["workspace_root"], "workspace_root"))
    if not root.is_absolute() or not root.is_dir():
        raise SearchError("existing absolute workspace_root required")
    hash_value(c["root_candidate_hash"], "root_candidate_hash")
    if c["origin"] not in {"step2", "step6_council"}:
        raise SearchError("unsupported search origin")
    sources = c["source_refs"]
    required_sources = {"step2_spec", "measurement_program"}
    if c["origin"] == "step6_council":
        required_sources.add("council_proposal")
    if not isinstance(sources, dict) or set(sources) != required_sources:
        raise SearchError("exact Step2/measurement/Council source bindings required")
    for ref in sources.values():
        verify_ref(ref, root=root)
    if bound_json(sources["step2_spec"]).get("report_id") != c["report_id"]:
        raise SearchError("Step2 source report mismatch")
    if c["origin"] == "step6_council":
        from factor_factory.revision_council.validator import validate_revision_council_proposal
        council = bound_json(sources["council_proposal"])
        reasons = validate_revision_council_proposal(
            council, measurement_program=bound_json(sources["measurement_program"]), workspace_root=root)
        if council.get("report_id") != c["report_id"] or reasons:
            raise SearchError("native Council proposal invalid: " + ";".join(reasons))
    protocol = bound_json(c["development_protocol"], root=root)
    if protocol.get("split") != "development":
        raise SearchError("only development protocol can drive search")
    if protocol.get("data_kind") not in {"market", "engineering_fixture"}:
        raise SearchError("explicit market or engineering_fixture data_kind required")
    if not isinstance(protocol.get("input_refs"), list) or not protocol["input_refs"]:
        raise SearchError("development protocol requires governed input references")
    for ref in protocol["input_refs"]:
        verify_ref(ref)
    for key in ("calendar_ref", "universe_ref", "information_time_ref", "split_manifest_ref"):
        verify_ref(protocol.get(key), root=root)
    authority = bound_json(c["budget_authority"], root=root)
    authority_keys = {"contract_version", "campaign_id", "report_id", "development_protocol_sha256",
                      "trial_budget", "trials_used", "compute_budget", "source_authority_ref", "state_ref",
                      "execution_cost_policy"}
    if set(authority) != authority_keys or authority.get("contract_version") != "factor_search_budget_v1":
        raise SearchError("native research budget binding required")
    if (authority.get("campaign_id") != c["campaign_id"] or authority.get("report_id") != c["report_id"]
            or authority.get("development_protocol_sha256") != c["development_protocol"]["sha256"]):
        raise SearchError("budget authority campaign/protocol mismatch")
    integer(authority.get("trial_budget"), "trial_budget", minimum=1)
    integer(authority.get("trials_used"), "trials_used")
    if authority["trials_used"] > authority["trial_budget"]:
        raise SearchError("budget already exhausted")
    number(authority.get("compute_budget"), "compute_budget", minimum=0)
    source_authority = bound_json(authority.get("source_authority_ref"), root=root)
    state = bound_json(authority.get("state_ref"), root=root)
    from factor_factory.research_conjecture import (research_protocol_paths, validate_research_conjecture,
                                                   validate_research_state)
    paths = research_protocol_paths(root, c["report_id"])
    if (Path(authority["source_authority_ref"]["path"]).resolve() != paths["conjecture"].resolve()
            or Path(authority["state_ref"]["path"]).resolve() != paths["state"].resolve()
            or source_authority.get("report_id") != c["report_id"] or state.get("report_id") != c["report_id"]):
        raise SearchError("budget must use the canonical native conjecture and research state")
    from factor_factory.research_profiles import research_profile_from_workspace
    reasons = validate_research_conjecture(source_authority, scope="local_is_only",
                  compatibility_profile=research_profile_from_workspace(root, c["report_id"])) + validate_research_state(state)
    if reasons:
        raise SearchError("native research authority invalid: " + ";".join(reasons))
    policy = source_authority["evidence_policy"]
    source_budget = min(integer(policy["trial_budget"], "source trial budget", minimum=1),
                        integer(state["budget_used"]["trial_budget"], "state trial budget", minimum=1))
    source_used = max(integer(policy["trials_used"], "source trials used"),
                      integer(state["budget_used"]["trials_used"], "state trials used"))
    if authority["trial_budget"] > source_budget or authority["trials_used"] < source_used:
        raise SearchError("campaign cannot expand source trial authority or reset used trials")
    costs = authority["execution_cost_policy"]
    if not isinstance(costs, dict) or set(costs) != {"preparation_seconds", "native_seconds"}:
        raise SearchError("fixed stage cost policy required")
    if any(number(costs[k], k, minimum=0) <= 0 for k in costs):
        raise SearchError("positive stage cost bounds required")
    split = bound_json(protocol["split_manifest_ref"])
    text(split.get("label_end"), "development label end")
    if (split.get("contract_version") != "factor_search_development_split_v1"
            or split.get("split") != "development" or split.get("oos_accessed") is not False
            or split.get("input_refs") != protocol["input_refs"]
            or split.get("source_conjecture_ref") != authority["source_authority_ref"]
            or split.get("is_start") != policy["is_start"] or split.get("is_end") != policy["is_end"]
            or split.get("label_end") > policy["is_end"] or split.get("label_end") < policy["is_start"]):
        raise SearchError("development split must bind frozen native IS windows and unexposed OOS")
    projection = bound_json(c["projection_ref"], root=root)
    if (set(projection) != {"contract_version", "source_refs", "research_question", "revision_laws", "prior_exposure", "oos_accessed"}
            or projection.get("contract_version") != "factor_search_source_projection_v1"
            or projection.get("source_refs") != sources or projection.get("oos_accessed") is not False
            or projection.get("prior_exposure") not in {"development_only", "nonblind_secondary"}):
        raise SearchError("explicit development-only source projection required")
    text(projection["research_question"], "public research question")
    if not isinstance(projection["revision_laws"], list) or not all(isinstance(x, str) for x in projection["revision_laws"]):
        raise SearchError("public revision laws must be strings")
    score = c["score_contract"]
    if not isinstance(score, dict) or set(score) != {"metric_pointer", "sample_count_pointer", "unit_pointer", "unit",
                                                   "direction", "baseline", "scale", "minimum_samples", "evaluation_scope"}:
        raise SearchError("fixed score contract fields required")
    for key in ("metric_pointer", "sample_count_pointer"):
        if not isinstance(score[key], str) or not score[key].startswith("/"):
            raise SearchError("score contract requires JSON pointers")
    if score["unit_pointer"] is None:
        if (score["metric_pointer"], score["sample_count_pointer"], score["unit"], score["evaluation_scope"]) != (
                "/ic_summary/rank_ic_mean", "/coverage/rank_ic_count", "dimensionless", "signal_diagnostic"):
            raise SearchError("unit metadata absent: only the registered native rank-IC adapter is supported")
    elif not isinstance(score["unit_pointer"], str) or not score["unit_pointer"].startswith("/"):
        raise SearchError("explicit metric unit pointer required")
    text(score["unit"], "metric unit")
    if type(score["direction"]) is not int or score["direction"] not in (-1, 1):
        raise SearchError("metric direction must be +1 or -1")
    number(score["baseline"], "baseline")
    if number(score["scale"], "scale", minimum=0) == 0:
        raise SearchError("positive score scale required")
    integer(score["minimum_samples"], "minimum_samples", minimum=1)
    if score["evaluation_scope"] not in {"signal_diagnostic", "account"}:
        raise SearchError("explicit signal_diagnostic/account metric scope required")
    if (not isinstance(c["allowed_mutation_classes"], list) or not c["allowed_mutation_classes"]
            or not set(c["allowed_mutation_classes"]).issubset(MUTATIONS)):
        raise SearchError("allowed mutation classes required")
    integer(c["seed"], "seed")
    integer(c["max_depth"], "max_depth", minimum=1)
    integer(c["max_proposals"], "max_proposals", minimum=1)
    if c["max_depth"] > 64 or c["max_proposals"] > 4096:
        raise SearchError("search bounds exceed interface limits")
    if c["planner_kind"] not in {"mcts", "registered_queue"}:
        raise SearchError("unsupported planner_kind")
    if c["compute_cost_unit"] != "wall_seconds":
        raise SearchError("native compute cost is measured in wall_seconds")
    return c


def program_identity(program: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize safe Formula-IR or a reviewed code-law reference; never eval."""
    p = json.loads(canonical(program))
    if p.get("mode") == "operator":
        if set(p) != {"mode", "expression", "required_inputs"}:
            raise SearchError("operator program fields invalid")
        expression = text(p["expression"], "formula")
        if len(expression) > 8192:
            raise SearchError("formula too long")
        if not isinstance(p["required_inputs"], list) or not all(isinstance(x, str) for x in p["required_inputs"]):
            raise SearchError("required_inputs must be names")
        from factor_factory.formula.parser import parse_formula
        ir = parse_formula(expression, available_columns=p["required_inputs"], raise_on_error=True)
        return {"mode": "operator", "root": ir["root"], "operator_semantic_hash": ir["operator_semantic_hash"],
                "resolved_fields": ir["resolved_fields"]}
    if p.get("mode") in {"direct_code", "hybrid"}:
        if set(p) != {"mode", "code_law", "required_inputs"}:
            raise SearchError("direct/hybrid program requires code law, not executable source")
        text(p["code_law"], "code law")
        if not isinstance(p["required_inputs"], list) or not all(isinstance(x, str) for x in p["required_inputs"]):
            raise SearchError("required_inputs must be names")
        return {**p, "required_inputs": sorted(set(p["required_inputs"]))}
    raise SearchError("program mode must be operator/direct_code/hybrid")


def candidate_hash(proposal: Mapping[str, Any]) -> str:
    return digest({"program": program_identity(proposal["program"]),
                   "semantics": proposal["semantics"]})


def validate_proposal(context: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    p = json.loads(canonical(proposal))
    required = {"contract_version", "proposal_id", "context_hash", "candidate_hash", "parent_candidate_hash",
                "proposer", "mutation_class", "program", "semantics", "changes", "public_derivation_ref",
                "expected_metric_signature", "falsifiers", "kill_criteria", "estimated_cost"}
    if set(p) != required or p.get("contract_version") != PROPOSAL_VERSION:
        raise SearchError("proposal fields/version mismatch; scores/credentials are not proposal fields")
    identifier(p["proposal_id"], "proposal_id")
    if p["context_hash"] != digest(context):
        raise SearchError("proposal source/context binding mismatch")
    if p["mutation_class"] not in context["allowed_mutation_classes"]:
        raise SearchError("mutation class outside accepted scope")
    if p["parent_candidate_hash"] is not None:
        hash_value(p["parent_candidate_hash"], "parent candidate hash")
    if p["candidate_hash"] != candidate_hash(p):
        raise SearchError("candidate canonical identity mismatch")
    if p["parent_candidate_hash"] == p["candidate_hash"]:
        raise SearchError("self-parent/unchanged candidate")
    if not isinstance(p["proposer"], dict) or set(p["proposer"]) != {"kind", "version", "seed"}:
        raise SearchError("proposer kind/version/seed required")
    text(p["proposer"]["kind"], "proposer kind")
    text(p["proposer"]["version"], "proposer version")
    integer(p["proposer"]["seed"], "proposer seed")
    semantic_keys = {"mathematical_object", "observation_map", "information_time", "units",
                     "missing_zero_policy", "sign_and_long_side", "controls"}
    if not isinstance(p["semantics"], dict) or set(p["semantics"]) != semantic_keys:
        raise SearchError("complete mathematical and observation semantics required")
    for key in semantic_keys:
        text(p["semantics"][key], key)
    if not isinstance(p["changes"], list) or not p["changes"]:
        raise SearchError("explicit changed layers required")
    layers = {"mathematical_object", "observation_map", "implementation"}
    if not set(p["changes"]).issubset(layers):
        raise SearchError("unsupported changed layer")
    classification = ("new_mechanism" if "mathematical_object" in p["changes"] else
                      "measurement_variant" if "observation_map" in p["changes"] else "implementation_equivalent")
    if classification != p["mutation_class"]:
        raise SearchError("mutation classification cannot downgrade a changed layer")
    verify_ref(p["public_derivation_ref"], root=context["workspace_root"])
    for key in ("expected_metric_signature", "falsifiers", "kill_criteria"):
        text(p[key], key)
    if number(p["estimated_cost"], "estimated_cost", minimum=0) == 0:
        raise SearchError("a positive preparation plus execution reservation is required")
    return p
