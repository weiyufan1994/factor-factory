"""Opt-in bridge from bounded response search to the Ultimate research journal.

The bridge records engineering evidence for a researcher.  It does not create
or amend formal Step2/Step6 decisions and it never treats GP loss as approval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Literal

from factor_factory.runtime_context import load_json, write_json_atomic
from factor_factory.code_review_checkpoint import validate_code_review

from .decision import ScheduleState
from .gp_adapter import SearchResult, run_response_gp
from .response import ResponseSemantics
from .synthetic import FitData
from .variation import DerivationScope

try:
    import fcntl
except Exception:  # pragma: no cover - guarded for non-Unix hosts
    fcntl = None


Split = Literal["development", "final", "confirmation"]
HandoffStage = Literal["step2", "step6"]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class HybridResearchError(RuntimeError):
    """The opt-in episode cannot be bound or resumed safely."""


@dataclass(frozen=True)
class EpisodeOutcome:
    enabled: bool
    status: str
    run_id: str
    input_identity: str | None
    journal_path: str | None
    researcher_material_path: str | None
    resumed: bool
    search_result: SearchResult | None = None


@dataclass(frozen=True)
class ResearcherResponseOutcome:
    enabled: bool
    status: str
    run_id: str
    input_identity: str | None
    journal_path: str | None
    response_sha256: str | None
    resumed: bool


_RESEARCHER_DECISIONS = {
    "retain_for_more_development",
    "revise_scope",
    "reject",
    "stop_insufficient_evidence",
}


def record_hybrid_researcher_response(
    *,
    workspace_root: str | Path,
    report_id: str,
    run_id: str,
    input_identity: str,
    material_sha256: str,
    response_path: str | Path,
    erratum_path: str | Path | None = None,
    enabled: bool = False,
) -> ResearcherResponseOutcome:
    """Bind one real external B response to an existing engineering episode.

    The response is evidence only.  This function never runs search, advances
    the scheduler, learns policy, dispatches an experiment, or grants formal
    Step2/Step6/knowledge authority.
    """
    _validate_id("report_id", report_id)
    _validate_id("run_id", run_id)
    if not enabled:
        return ResearcherResponseOutcome(False, "disabled", run_id, None, None, None, False)
    if not re.fullmatch(r"[0-9a-f]{64}", input_identity):
        raise ValueError("input_identity must be a lowercase SHA256 digest")
    if not re.fullmatch(r"[0-9a-f]{64}", material_sha256):
        raise ValueError("material_sha256 must be a lowercase SHA256 digest")

    root = Path(workspace_root).expanduser().resolve()
    journal_path = (
        root / "objects/research_journal" / f"research_journal__{report_id}.json"
    )
    if not journal_path.is_file():
        raise HybridResearchError("existing hybrid research journal is missing")
    source_path = Path(response_path).expanduser().resolve()
    try:
        raw_response_bytes = source_path.read_bytes()
        raw_response = raw_response_bytes.decode("utf-8")
        response = json.loads(raw_response)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HybridResearchError("researcher response must be readable UTF-8 JSON") from exc
    if not isinstance(response, dict):
        raise HybridResearchError("researcher response must be a JSON object")
    decision = response.get("decision")
    if decision not in _RESEARCHER_DECISIONS:
        raise HybridResearchError("unsupported researcher decision")
    next_record = response.get("next_experiment_and_kill_criterion")
    if next_record is None:
        next_record = response.get("next_experiment")
    if next_record is None:
        next_record = response.get("next_research_question")
    next_question = _next_research_question(next_record)
    if next_question is None:
        raise HybridResearchError(
            "researcher response requires a next research question or experiment"
        )
    response_sha256 = sha256(raw_response_bytes).hexdigest()
    erratum_record = _load_optional_text_binding(erratum_path)
    response_identity = _digest(
        {
            "contract_version": "hybrid_researcher_response_binding_v1",
            "report_id": report_id,
            "run_id": run_id,
            "input_identity": input_identity,
            "material_sha256": material_sha256,
            "response_sha256": response_sha256,
            "erratum_sha256": (
                erratum_record.get("source_sha256") if erratum_record else None
            ),
            "decision": decision,
            "next_research_question": next_question,
        }
    )

    lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            journal = load_json(journal_path)
            _require_report_id("research journal", journal, report_id)
            episodes = _episodes(journal)
            matches = [row for row in episodes if row.get("run_id") == run_id]
            if len(matches) != 1:
                raise HybridResearchError("target hybrid research run is missing or duplicated")
            episode = matches[0]
            if episode.get("input_identity") != input_identity:
                raise HybridResearchError("researcher response input_identity mismatch")
            if episode.get("researcher_material_sha256") != material_sha256:
                raise HybridResearchError("researcher response material identity mismatch")
            material_path = _bound_material_path(root, episode)
            actual_material_sha256 = sha256(material_path.read_bytes()).hexdigest()
            if actual_material_sha256 != material_sha256:
                raise HybridResearchError("bound researcher material changed")
            material = load_json(material_path)
            if (
                material.get("report_id") != report_id
                or material.get("run_id") != run_id
                or material.get("input_identity") != input_identity
                or material.get("status") != "computed_awaiting_researcher"
            ):
                raise HybridResearchError("bound researcher material identity is invalid")
            _validate_external_response_evidence(
                response,
                report_id=report_id,
                run_id=run_id,
                input_identity=input_identity,
                material_sha256=material_sha256,
                material_path=material_path,
            )

            existing = episode.get("researcher_response")
            if existing is not None:
                if not isinstance(existing, dict):
                    raise HybridResearchError("recorded researcher response is invalid")
                _validate_recorded_researcher_response(existing, episode)
                if existing.get("response_identity") != response_identity:
                    raise HybridResearchError("conflicting researcher response already recorded")
                return ResearcherResponseOutcome(
                    True,
                    "researcher_response_recorded",
                    run_id,
                    input_identity,
                    str(journal_path),
                    response_sha256,
                    True,
                )

            response_record = {
                "contract_version": "hybrid_researcher_response_binding_v1",
                "response_identity": response_identity,
                "source_path": str(source_path),
                "source_sha256": response_sha256,
                "original_response_text": raw_response,
                "decision": decision,
                "next_research_question": next_question,
                "next_research_record": next_record,
                "erratum": erratum_record,
                "bound_report_id": report_id,
                "bound_run_id": run_id,
                "bound_input_identity": input_identity,
                "bound_material_sha256": material_sha256,
                "formal_approval": False,
                "policy_update_eligible": False,
                "knowledge_write_allowed": False,
                "next_experiment_dispatched": False,
            }
            replacement = {
                **episode,
                "status": "researcher_response_recorded",
                "researcher_response": response_record,
                "formal_approval": False,
                "policy_update_eligible": False,
            }
            _replace_episode(journal, run_id, replacement)
            write_json_atomic(journal_path, journal)
            return ResearcherResponseOutcome(
                True,
                "researcher_response_recorded",
                run_id,
                input_identity,
                str(journal_path),
                response_sha256,
                False,
            )
        finally:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)


def run_hybrid_episode_from_request(
    *, workspace_root: str | Path, report_id: str, request_path: str | Path
) -> EpisodeOutcome:
    """Parse one explicit Ultimate opt-in request and run its development episode."""
    path = Path(request_path).expanduser().resolve()
    request = load_json(path)
    if request.get("contract_version") != "hybrid_research_request_v1":
        raise HybridResearchError("unsupported hybrid research request contract")
    if request.get("report_id") != report_id:
        raise HybridResearchError("hybrid research request report_id mismatch")
    try:
        fit = request["fit_data"]
        scope = request["derivation_scope"]
        schedule = request["schedule_state"]
        search = request.get("search_config") or {}
        fit_data = FitData(
            tuple(float(value) for value in fit["signed_impulses"]),
            tuple(float(value) for value in fit["observed_response"]),
            float(fit["step"]),
        )
        derivation_scope = DerivationScope(
            derivation_ref=str(scope["derivation_ref"]),
            mathematical_object=str(scope["mathematical_object"]),
            domain=str(scope["domain"]),
            initial_state=str(scope["initial_state"]),
            clock=str(scope["clock"]),
            missing_value_policy=str(scope["missing_value_policy"]),
            observation_map=str(scope["observation_map"]),
            allowed_transformations=tuple(scope["allowed_transformations"]),
            distinguishing_predictions=tuple(scope["distinguishing_predictions"]),
            current_gap=str(scope["current_gap"]),
            allowed_response_families=tuple(scope["allowed_response_families"]),
            allowed_research_actions=tuple(scope["allowed_research_actions"]),
        )
        schedule_state = ScheduleState(**schedule)
        semantics_payload = request.get("response_semantics")
        implementation_evidence = request.get("implementation_evidence")
        if implementation_evidence is not None and not isinstance(implementation_evidence, dict):
            raise ValueError("implementation_evidence must be an object")
        response_semantics = (
            ResponseSemantics(
                observation_timing=str(semantics_payload["observation_timing"]),
                rate_parameterization=str(semantics_payload["rate_parameterization"]),
                pre_sample_input=str(semantics_payload["pre_sample_input"]),
                initial_state=str(semantics_payload["initial_state"]),
                intercept=str(semantics_payload["intercept"]),
                direct_input=str(semantics_payload.get("direct_input", "zero")),
                gain_mode=str(semantics_payload["gain_mode"]),
                gain_constraint=str(semantics_payload["gain_constraint"]),
                memory_rate_policy=str(
                    semantics_payload.get("memory_rate_policy", "legacy_ordered_terms")
                ),
                training_indexes=tuple(semantics_payload["training_indexes"]),
                score_indexes=tuple(semantics_payload.get("score_indexes", ())),
                input_start_index=semantics_payload.get("input_start_index", 0),
                initial_state_start_index=semantics_payload.get(
                    "initial_state_start_index", 0
                ),
                initial_power_offset=semantics_payload.get("initial_power_offset", 1),
            )
            if semantics_payload is not None
            else None
        )
        arguments = {
            "allowed_rates": tuple(float(value) for value in search.get("allowed_rates", (0.0, 0.2, 0.5, 1.0))),
            "allowed_scales": tuple(float(value) for value in search.get("allowed_scales", (0.3, 0.7, 1.0))),
            "seed": int(search.get("seed", 0)),
            "generations": int(search.get("generations", 2)),
            "population_size": int(search.get("population_size", 6)),
            "max_evaluations": int(search.get("max_evaluations", 16)),
            "max_attempts": int(search.get("max_attempts", 32)),
        }
        return run_hybrid_episode(
            workspace_root=workspace_root,
            report_id=report_id,
            run_id=str(request["run_id"]),
            fit_data=fit_data,
            scope=derivation_scope,
            schedule_state=schedule_state,
            handoff_stage=str(request["handoff_stage"]),
            enabled=True,
            split=str(request.get("split", "development")),
            response_semantics=response_semantics,
            implementation_evidence=implementation_evidence,
            **arguments,
        )
    except HybridResearchError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise HybridResearchError(f"invalid hybrid research request payload: {exc}") from exc


def run_hybrid_episode(
    *,
    workspace_root: str | Path,
    report_id: str,
    run_id: str,
    fit_data: FitData,
    scope: DerivationScope,
    schedule_state: ScheduleState,
    handoff_stage: HandoffStage,
    enabled: bool = False,
    split: Split = "development",
    allowed_rates: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0),
    allowed_scales: tuple[float, ...] = (0.3, 0.7, 1.0),
    seed: int = 0,
    generations: int = 2,
    population_size: int = 6,
    max_evaluations: int = 16,
    max_attempts: int = 32,
    response_semantics: ResponseSemantics | None = None,
    implementation_evidence: dict[str, Any] | None = None,
) -> EpisodeOutcome:
    """Run or idempotently resume one local evidence-producing episode.

    Disabled mode has no filesystem side effects.  Enabled mode requires the
    existing Ultimate journal, factor spec, approach registry, and a Step2 or
    Step6 handoff.  The full scheduler state is persisted unchanged because no
    researcher action has yet been accepted.
    """
    _validate_id("report_id", report_id)
    _validate_id("run_id", run_id)
    if split not in {"development", "final", "confirmation"}:
        raise ValueError("split must be development, final, or confirmation")
    if not enabled:
        return EpisodeOutcome(False, "disabled", run_id, None, None, None, False)
    if split != "development":
        raise HybridResearchError(
            "bounded GP fitness is development-only; final/confirmation data cannot drive search"
        )
    if handoff_stage not in {"step2", "step6"}:
        raise ValueError("handoff_stage must be step2 or step6")

    root = Path(workspace_root).expanduser().resolve()
    objects = root / "objects"
    journal_path = objects / "research_journal" / f"research_journal__{report_id}.json"
    spec_path = objects / "factor_spec_master" / f"factor_spec_master__{report_id}.json"
    approach_path = objects / "research_protocol" / f"approach_registry__{report_id}.json"
    handoff_path = _select_handoff(objects, report_id, handoff_stage)
    required = (journal_path, spec_path, approach_path, handoff_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise HybridResearchError("required existing Ultimate artifacts are missing: " + ", ".join(missing))

    spec = load_json(spec_path)
    approach = load_json(approach_path)
    handoff = load_json(handoff_path)
    for label, payload in (
        ("factor spec", spec),
        ("approach registry", approach),
        ("handoff", handoff),
    ):
        _require_report_id(label, payload, report_id)
    measurement_program = spec.get("mechanism_conditioned_measurement_program")
    if not isinstance(measurement_program, dict):
        raise HybridResearchError("factor spec has no mechanism_conditioned_measurement_program")
    model_selection = measurement_program.get("model_selection")
    if not isinstance(model_selection, dict):
        raise HybridResearchError("measurement program has no model_selection")

    config = {
        "split": split,
        "handoff_stage": handoff_stage,
        "seed": seed,
        "allowed_rates": allowed_rates,
        "allowed_scales": allowed_scales,
        "generations": generations,
        "population_size": population_size,
        "max_evaluations": max_evaluations,
        "max_attempts": max_attempts,
    }
    if response_semantics is not None:
        config["response_semantics"] = asdict(response_semantics)
    if implementation_evidence is not None:
        config["implementation_evidence"] = implementation_evidence
    engineering_evidence = _collect_implementation_evidence(
        root=root,
        report_id=report_id,
        handoff_path=handoff_path,
        spec_path=spec_path,
        requested=implementation_evidence,
    )
    source_bindings = {
        "factor_spec": _binding(root, spec_path),
        "approach_registry": _binding(root, approach_path),
        "handoff": _binding(root, handoff_path),
    }
    if response_semantics is not None or implementation_evidence is not None:
        source_bindings["implementation_evidence"] = engineering_evidence["identity_bindings"]
    input_identity = _digest(
        {
            "contract_version": "hybrid_research_episode_input_v1",
            "report_id": report_id,
            "run_id": run_id,
            "fit_data": asdict(fit_data),
            "scope": asdict(scope),
            "schedule_state": asdict(schedule_state),
            "config": config,
            "source_bindings": source_bindings,
        }
    )
    material_path = (
        journal_path.parent / f"hybrid_research_material__{report_id}__{run_id}.json"
    )
    lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            journal = load_json(journal_path)
            _require_report_id("research journal", journal, report_id)
            episodes = _episodes(journal)
            _require_schedule_state(journal, schedule_state)
            prior = next((row for row in episodes if row.get("run_id") == run_id), None)
            if prior is not None:
                if prior.get("input_identity") != input_identity:
                    raise HybridResearchError(f"run_id {run_id!r} is already bound to another input")
                if material_path.is_file():
                    material = load_json(material_path)
                    _validate_material(
                        material,
                        report_id,
                        run_id,
                        input_identity,
                        fit_data=fit_data,
                        scope=scope,
                        schedule_state=schedule_state,
                        source_bindings=source_bindings,
                        config=config,
                        engineering_evidence=engineering_evidence,
                    )
                    material_sha256 = sha256(material_path.read_bytes()).hexdigest()
                    expected_sha256 = prior.get("researcher_material_sha256")
                    if expected_sha256 is not None and expected_sha256 != material_sha256:
                        raise HybridResearchError("researcher material content hash mismatch")
                    completed = _episode_record(
                        material, root, material_path, material_sha256=material_sha256
                    )
                    completed = _preserve_researcher_response(prior, completed)
                    if prior != completed:
                        latest = load_json(journal_path)
                        _replace_episode(latest, run_id, completed)
                        write_json_atomic(journal_path, latest)
                    return EpisodeOutcome(
                        True,
                        str(completed.get("status")),
                        run_id,
                        input_identity,
                        str(journal_path),
                        str(material_path),
                        True,
                    )
                if prior.get("status") == "computed_awaiting_researcher":
                    raise HybridResearchError("journal references missing researcher material")
                return EpisodeOutcome(
                    True,
                    str(prior.get("status")),
                    run_id,
                    input_identity,
                    str(journal_path),
                    None,
                    True,
                )

            if material_path.is_file():
                material = load_json(material_path)
                _validate_material(
                    material,
                    report_id,
                    run_id,
                    input_identity,
                    fit_data=fit_data,
                    scope=scope,
                    schedule_state=schedule_state,
                    source_bindings=source_bindings,
                    config=config,
                    engineering_evidence=engineering_evidence,
                )
                material_sha256 = sha256(material_path.read_bytes()).hexdigest()
                episode = _episode_record(
                    material, root, material_path, material_sha256=material_sha256
                )
                section = journal.setdefault("hybrid_research", {})
                section["contract_version"] = "hybrid_research_journal_v1"
                section["current_schedule_state"] = asdict(schedule_state)
                section["episodes"] = [*episodes, episode]
                write_json_atomic(journal_path, journal)
                return EpisodeOutcome(
                    True,
                    str(material.get("status")),
                    run_id,
                    input_identity,
                    str(journal_path),
                    str(material_path),
                    True,
                )

            intent = {
                "run_id": run_id,
                "input_identity": input_identity,
                "status": "execution_started_completion_unknown",
                "split": split,
                "researcher_material_path": str(material_path.relative_to(root)),
                "schedule_state_before": asdict(schedule_state),
                "schedule_state_after": asdict(schedule_state),
                "used_budget": {
                    "attempts": None,
                    "finite_evaluations": None,
                    "rejected_attempts": None,
                    "attempt_limit": max_attempts,
                    "evaluation_limit": max_evaluations,
                    "actual_cost": None,
                },
                "formal_approval": False,
                "policy_update_eligible": False,
            }
            section = journal.setdefault("hybrid_research", {})
            section["contract_version"] = "hybrid_research_journal_v1"
            section["current_schedule_state"] = asdict(schedule_state)
            section["episodes"] = [*episodes, intent]
            write_json_atomic(journal_path, journal)

            try:
                result = run_response_gp(
                    scope=scope,
                    fit_data=fit_data,
                    allowed_rates=allowed_rates,
                    allowed_scales=allowed_scales,
                    seed=seed,
                    generations=generations,
                    population_size=population_size,
                    max_evaluations=max_evaluations,
                    max_attempts=max_attempts,
                    response_semantics=response_semantics,
                )
            except Exception as exc:
                failed = {
                    **intent,
                    "status": "execution_failed",
                    "execution_failure": {
                        "phase": "search_execution",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
                latest = load_json(journal_path)
                _replace_episode(latest, run_id, failed)
                write_json_atomic(journal_path, latest)
                raise HybridResearchError("hybrid search execution failed and was recorded") from exc
            rejected = [row for row in result.trace if row.status == "rejected"]
            used_budget = {
                "attempts": result.attempt_count,
                "finite_evaluations": result.evaluated_count,
                "rejected_attempts": len(rejected),
                "attempt_limit": max_attempts,
                "evaluation_limit": max_evaluations,
                "actual_cost": None,
            }
            material = {
                "contract_version": "hybrid_researcher_material_v1",
                "report_id": report_id,
                "run_id": run_id,
                "input_identity": input_identity,
                "status": "computed_awaiting_researcher",
                "split": split,
                "formal_approval": False,
                "policy_update_eligible": False,
                "policy_update_reason": "real researcher decision is absent",
                "schedule_state_before": asdict(schedule_state),
                "schedule_state_after": asdict(schedule_state),
                "source_bindings": source_bindings,
                "model_selection": model_selection,
                "approach_context": approach,
                "handoff_context": handoff,
                "derivation_scope": asdict(scope),
                "fit_data": asdict(fit_data),
                "search_config": config,
                "search": asdict(result),
                "evidence_classes": {
                    "executed_engine_version": engineering_evidence["executed_engine_version"],
                    "numerical_fit": {
                        "status": "computed",
                        "authority": "development numerical fit only",
                        "selected_candidate_id": result.selected_id,
                        "selected_fit": asdict(result.selected.fit) if result.selected and result.selected.fit else None,
                    },
                    "author_tests": engineering_evidence["author_tests"],
                    "independent_review": engineering_evidence["independent_review"],
                },
                "failure_reasons": [row.reason for row in rejected],
                "execution_failures": [],
                "used_budget": used_budget,
            }
            try:
                write_json_atomic(material_path, material)
            except Exception as exc:
                failed = {
                    **intent,
                    "status": "execution_completed_material_write_failed",
                    "used_budget": used_budget,
                    "stop_reason": result.stop_reason,
                    "selected_candidate_id": result.selected_id,
                    "execution_failure": {
                        "phase": "material_publication",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
                latest = load_json(journal_path)
                _replace_episode(latest, run_id, failed)
                write_json_atomic(journal_path, latest)
                raise HybridResearchError(
                    "search completed but researcher material publication failed; automatic rerun is blocked"
                ) from exc
            material_sha256 = sha256(material_path.read_bytes()).hexdigest()
            episode = _episode_record(
                material, root, material_path, material_sha256=material_sha256
            )
            latest = load_json(journal_path)
            _require_report_id("research journal", latest, report_id)
            _require_schedule_state(latest, schedule_state)
            _replace_episode(latest, run_id, episode)
            write_json_atomic(journal_path, latest)
            return EpisodeOutcome(
                True,
                material["status"],
                run_id,
                input_identity,
                str(journal_path),
                str(material_path),
                False,
                result,
            )
        finally:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _collect_implementation_evidence(
    *,
    root: Path,
    report_id: str,
    handoff_path: Path,
    spec_path: Path,
    requested: dict[str, Any] | None,
) -> dict[str, Any]:
    requested = requested or {}
    allowed = {
        "author_test_path", "author_test_sha256", "code_review_path", "code_review_sha256"
    }
    unknown = sorted(set(requested) - allowed)
    if unknown:
        raise ValueError(f"unsupported implementation_evidence fields: {', '.join(unknown)}")

    author_path = _requested_evidence_path(
        root,
        requested.get("author_test_path"),
        root / "objects/research_journal" / f"author_tests__{report_id}.json",
    )
    review_path = _requested_evidence_path(
        root,
        requested.get("code_review_path"),
        root / "objects/research_journal" / f"code_review__{report_id}.json",
    )
    author_binding = _read_evidence_binding(
        author_path, requested.get("author_test_sha256")
    )
    review_binding = _read_evidence_binding(
        review_path, requested.get("code_review_sha256")
    )
    repo_root = Path(__file__).resolve().parents[2]
    engine_paths = (
        Path(__file__).resolve().parent / "response.py",
        Path(__file__).resolve().parent / "gp_adapter.py",
    )
    engine_version = tuple(_binding(repo_root, path) for path in engine_paths)

    author_tests: dict[str, Any] = {
        "status": "Unknown",
        "artifact": author_binding,
        "authority": "author-reported deterministic test evidence; not independent review",
        "limits": ["artifact presence and SHA256 do not prove the tests ran or passed"],
    }
    if author_binding["state"] == "current":
        try:
            payload = load_json(author_path)
            author_coverage = _evidence_file_coverage(
                payload.get("tested_files"), engine_version, root=root, repo_root=repo_root
            )
            author_tests.update(
                status="artifact_available_unverified",
                actual_scope=payload.get("scope", "Unknown"),
                reported_result=payload.get("result", payload.get("status", "Unknown")),
                tested_engine_coverage=author_coverage,
                original_record=payload,
                readable_evidence=True,
            )
        except Exception as exc:
            author_tests["limits"].append(f"unreadable author test JSON: {type(exc).__name__}")

    independent_review: dict[str, Any] = {
        "status": "Unknown",
        "artifact": review_binding,
        "independence_status": "Unknown",
        "authority": "existing code-review checkpoint; reviewer independence and review quality are not authenticated",
        "limits": ["no caller PASS flag can create or replace a review"],
    }
    if review_binding["state"] == "current":
        try:
            record = load_json(review_path)
            validation = validate_code_review(
                workspace_root=root,
                report_id=report_id,
                handoff=handoff_path,
                spec=spec_path,
                repo_root=repo_root,
                review_record=record,
                require_post_review_tests=True,
            )
            review_coverage = _evidence_file_coverage(
                record.get("reviewed_files"), engine_version, root=root, repo_root=repo_root
            )
            covers_engine = review_coverage["status"] == "complete_current_coverage"
            independent_review.update(
                status=("current_declared_review_validated"
                        if validation.get("status") == "PASS" and covers_engine else "Unknown"),
                validator_result=validation,
                declared_author_id=record.get("author_id", "Unknown"),
                declared_reviewer_id=record.get("reviewer_id", "Unknown"),
                declared_decision=record.get("decision", "Unknown"),
                actual_scope=record.get("reviewed_files", "Unknown"),
                reviewed_engine_coverage=review_coverage,
                post_review_deterministic_tests=record.get("post_review_tests", "Unknown"),
                original_record=record,
                readable_evidence=True,
                independence_status="declared_not_authenticated",
            )
        except Exception as exc:
            independent_review["limits"].append(
                f"unreadable or invalid review evidence: {type(exc).__name__}"
            )
    return {
        "identity_bindings": {
            "author_tests": author_binding,
            "code_review": review_binding,
            "executed_engine_version": engine_version,
        },
        "executed_engine_version": engine_version,
        "author_tests": author_tests,
        "independent_review": independent_review,
    }


def _evidence_file_coverage(
    records: Any,
    engine_version: tuple[dict[str, str], ...],
    *,
    root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    expected = {str((repo_root / item["path"]).resolve()): item["sha256"] for item in engine_version}
    found: dict[str, str] = {}
    if isinstance(records, list):
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            raw = Path(item["path"]).expanduser()
            base = repo_root if item.get("base") == "repo" else root
            resolved = str((raw if raw.is_absolute() else base / raw).resolve())
            if isinstance(item.get("sha256"), str):
                found[resolved] = item["sha256"].lower()
    missing = [path for path, digest in expected.items() if found.get(path) != digest]
    return {
        "status": "complete_current_coverage" if not missing else "incomplete_or_stale",
        "required_files": expected,
        "missing_or_stale_files": missing,
    }


def _requested_evidence_path(root: Path, raw: Any, default: Path) -> Path:
    if raw is None:
        return default.resolve()
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("implementation evidence paths must be nonempty strings")
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _read_evidence_binding(path: Path, declared_sha256: Any) -> dict[str, Any]:
    if declared_sha256 is not None and (
        not isinstance(declared_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", declared_sha256)
    ):
        raise ValueError("implementation evidence SHA256 must be lowercase hex")
    if not path.is_file():
        return {"path": str(path), "sha256": None, "state": "missing"}
    actual = sha256(path.read_bytes()).hexdigest()
    state = "current" if declared_sha256 in {None, actual} else "stale"
    return {
        "path": str(path),
        "sha256": actual,
        "declared_sha256": declared_sha256,
        "state": state,
    }


def _validate_id(label: str, value: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"unsafe {label}")


def _require_report_id(label: str, payload: dict[str, Any], report_id: str) -> None:
    if payload.get("report_id") != report_id:
        raise HybridResearchError(f"{label} report_id does not match {report_id!r}")


def _select_handoff(objects: Path, report_id: str, handoff_stage: HandoffStage) -> Path:
    filename = (
        f"handoff_to_step3__{report_id}.json"
        if handoff_stage == "step2"
        else f"handoff_to_step6__{report_id}.json"
    )
    return objects / "handoff" / filename


def _binding(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _episodes(journal: dict[str, Any]) -> list[dict[str, Any]]:
    section = journal.get("hybrid_research")
    if section is None:
        return []
    if not isinstance(section, dict) or not isinstance(section.get("episodes", []), list):
        raise HybridResearchError("existing hybrid_research journal section is invalid")
    return list(section.get("episodes", []))


def _require_schedule_state(journal: dict[str, Any], schedule_state: ScheduleState) -> None:
    section = journal.get("hybrid_research")
    if not isinstance(section, dict) or "current_schedule_state" not in section:
        return
    if section["current_schedule_state"] != asdict(schedule_state):
        raise HybridResearchError(
            "caller schedule_state differs from the journal; a researcher decision is required"
        )


def _replace_episode(
    journal: dict[str, Any], run_id: str, replacement: dict[str, Any]
) -> None:
    episodes = _episodes(journal)
    matches = [index for index, row in enumerate(episodes) if row.get("run_id") == run_id]
    if len(matches) != 1:
        raise HybridResearchError("journal execution intent is missing or duplicated")
    episodes[matches[0]] = replacement
    journal["hybrid_research"]["episodes"] = episodes


def _bound_material_path(root: Path, episode: dict[str, Any]) -> Path:
    raw = episode.get("researcher_material_path")
    if not isinstance(raw, str) or not raw:
        raise HybridResearchError("episode has no bound researcher material path")
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HybridResearchError("researcher material path escapes workspace") from exc
    if not path.is_file():
        raise HybridResearchError("bound researcher material is missing")
    return path


def _next_research_question(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        return None
    for key in ("question", "design", "scope"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _load_optional_text_binding(path: str | Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    try:
        original_bytes = resolved.read_bytes()
        original_text = original_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise HybridResearchError("researcher response erratum must be readable UTF-8") from exc
    if not original_text.strip():
        raise HybridResearchError("researcher response erratum cannot be empty")
    return {
        "source_path": str(resolved),
        "source_sha256": sha256(original_bytes).hexdigest(),
        "original_text": original_text,
    }


def _validate_external_response_evidence(
    response: dict[str, Any],
    *,
    report_id: str,
    run_id: str,
    input_identity: str,
    material_sha256: str,
    material_path: Path,
) -> None:
    declared_report = response.get("report_id")
    declared_run = response.get("run_id")
    evidence: dict[str, Any] = {}
    primary_binding = response.get("evidence_binding")
    if isinstance(primary_binding, dict) and isinstance(primary_binding.get("material"), dict):
        evidence = primary_binding["material"]
    challenger_binding = response.get("evidence_identity")
    if not evidence and isinstance(challenger_binding, dict):
        evidence = challenger_binding
        declared_report = declared_report or evidence.get("report_id")
        declared_run = declared_run or evidence.get("run_id")
    if declared_report is not None and declared_report != report_id:
        raise HybridResearchError("researcher response report_id mismatch")
    if declared_run is not None and declared_run != run_id:
        raise HybridResearchError("researcher response run_id mismatch")
    declared_input = evidence.get("input_identity")
    if declared_input is not None and declared_input != input_identity:
        raise HybridResearchError("researcher response evidence input_identity mismatch")
    declared_sha = evidence.get("sha256")
    if declared_sha is not None and declared_sha != material_sha256:
        raise HybridResearchError("researcher response evidence material SHA mismatch")
    declared_path = evidence.get("path") or evidence.get("material_path")
    if declared_path is not None:
        if not isinstance(declared_path, str) or Path(declared_path).expanduser().resolve() != material_path:
            raise HybridResearchError("researcher response evidence material path mismatch")


def _preserve_researcher_response(
    prior: dict[str, Any], completed: dict[str, Any]
) -> dict[str, Any]:
    response = prior.get("researcher_response")
    if response is None:
        return completed
    if not isinstance(response, dict):
        raise HybridResearchError("recorded researcher response is invalid")
    _validate_recorded_researcher_response(response, completed)
    return {
        **completed,
        "status": "researcher_response_recorded",
        "researcher_response": response,
        "formal_approval": False,
        "policy_update_eligible": False,
    }


def _validate_recorded_researcher_response(
    response: dict[str, Any], episode: dict[str, Any]
) -> None:
    if response.get("contract_version") != "hybrid_researcher_response_binding_v1":
        raise HybridResearchError("recorded researcher response contract is invalid")
    original = response.get("original_response_text")
    if not isinstance(original, str):
        raise HybridResearchError("recorded researcher response has no original text")
    original_bytes = original.encode("utf-8")
    source_sha256 = sha256(original_bytes).hexdigest()
    if source_sha256 != response.get("source_sha256"):
        raise HybridResearchError("recorded researcher response source hash mismatch")
    try:
        parsed = json.loads(original)
    except json.JSONDecodeError as exc:
        raise HybridResearchError("recorded researcher response original text is invalid") from exc
    if not isinstance(parsed, dict):
        raise HybridResearchError("recorded researcher response original must be an object")
    decision = parsed.get("decision")
    if decision not in _RESEARCHER_DECISIONS or decision != response.get("decision"):
        raise HybridResearchError("recorded researcher response decision mismatch")
    next_record = parsed.get("next_experiment_and_kill_criterion")
    if next_record is None:
        next_record = parsed.get("next_experiment")
    if next_record is None:
        next_record = parsed.get("next_research_question")
    next_question = _next_research_question(next_record)
    if (
        next_question is None
        or next_question != response.get("next_research_question")
        or _digest(next_record) != _digest(response.get("next_research_record"))
    ):
        raise HybridResearchError("recorded researcher response next question mismatch")
    erratum = response.get("erratum")
    erratum_sha256 = None
    if erratum is not None:
        if not isinstance(erratum, dict) or not isinstance(erratum.get("original_text"), str):
            raise HybridResearchError("recorded researcher response erratum is invalid")
        erratum_sha256 = sha256(erratum["original_text"].encode("utf-8")).hexdigest()
        if erratum_sha256 != erratum.get("source_sha256"):
            raise HybridResearchError("recorded researcher response erratum hash mismatch")
    bound_report_id = response.get("bound_report_id")
    bound_run_id = response.get("bound_run_id")
    bound_input_identity = response.get("bound_input_identity")
    bound_material_sha256 = response.get("bound_material_sha256")
    if (
        bound_run_id != episode.get("run_id")
        or bound_input_identity != episode.get("input_identity")
        or bound_material_sha256 != episode.get("researcher_material_sha256")
        or not isinstance(bound_report_id, str)
    ):
        raise HybridResearchError("recorded researcher response evidence binding mismatch")
    expected_identity = _digest(
        {
            "contract_version": "hybrid_researcher_response_binding_v1",
            "report_id": bound_report_id,
            "run_id": bound_run_id,
            "input_identity": bound_input_identity,
            "material_sha256": bound_material_sha256,
            "response_sha256": source_sha256,
            "erratum_sha256": erratum_sha256,
            "decision": decision,
            "next_research_question": next_question,
        }
    )
    if expected_identity != response.get("response_identity"):
        raise HybridResearchError("recorded researcher response identity mismatch")


def _validate_material(
    material: dict[str, Any],
    report_id: str,
    run_id: str,
    input_identity: str,
    *,
    fit_data: FitData,
    scope: DerivationScope,
    schedule_state: ScheduleState,
    source_bindings: dict[str, dict[str, str]],
    config: dict[str, Any],
    engineering_evidence: dict[str, Any],
) -> None:
    if material.get("contract_version") != "hybrid_researcher_material_v1":
        raise HybridResearchError("researcher material contract is invalid")
    expected = {
        "report_id": report_id,
        "run_id": run_id,
        "input_identity": input_identity,
        "status": "computed_awaiting_researcher",
        "formal_approval": False,
        "policy_update_eligible": False,
    }
    if any(material.get(key) != value for key, value in expected.items()):
        raise HybridResearchError("researcher material identity or status is invalid")
    expected_inputs = {
        "fit_data": asdict(fit_data),
        "derivation_scope": asdict(scope),
        "schedule_state_before": asdict(schedule_state),
        "schedule_state_after": asdict(schedule_state),
        "source_bindings": source_bindings,
        "search_config": config,
        "split": config["split"],
    }
    if any(
        _digest(material.get(key)) != _digest(value)
        for key, value in expected_inputs.items()
    ):
        raise HybridResearchError("researcher material does not match the verified request input")
    search = material.get("search")
    budget = material.get("used_budget")
    if not isinstance(search, dict) or not isinstance(search.get("trace"), list):
        raise HybridResearchError("researcher material search trace is invalid")
    if not isinstance(budget, dict):
        raise HybridResearchError("researcher material budget is invalid")
    rejected = [row for row in search["trace"] if row.get("status") == "rejected"]
    checks = (
        budget.get("attempts") == search.get("attempt_count"),
        budget.get("finite_evaluations") == search.get("evaluated_count"),
        budget.get("rejected_attempts") == len(rejected),
        len(material.get("failure_reasons") or []) == len(rejected),
        budget.get("actual_cost") is None,
        isinstance(material.get("fit_data"), dict),
    )
    if not all(checks):
        raise HybridResearchError("researcher material trace, budget, or fit data is inconsistent")
    evidence_classes = material.get("evidence_classes")
    evidence_required = (
        "response_semantics" in config
        or "implementation_evidence" in config
        or evidence_classes is not None
    )
    if evidence_required:
        selected_id = search.get("selected_id")
        selected_rows = [row for row in search["trace"] if row.get("candidate_id") == selected_id]
        if selected_id is not None and len(selected_rows) != 1:
            raise HybridResearchError("researcher material selected candidate is missing or duplicated")
        selected_fit = selected_rows[0].get("fit") if selected_rows else None
        expected_evidence = {
            "executed_engine_version": engineering_evidence["executed_engine_version"],
            "numerical_fit": {
                "status": "computed",
                "authority": "development numerical fit only",
                "selected_candidate_id": selected_id,
                "selected_fit": selected_fit,
            },
            "author_tests": engineering_evidence["author_tests"],
            "independent_review": engineering_evidence["independent_review"],
        }
        if _digest(evidence_classes) != _digest(expected_evidence):
            raise HybridResearchError(
                "researcher material evidence classes do not match current bound evidence"
            )


def _episode_record(
    material: dict[str, Any], root: Path, material_path: Path, *, material_sha256: str
) -> dict[str, Any]:
    search = material.get("search") or {}
    return {
        "run_id": material.get("run_id"),
        "input_identity": material.get("input_identity"),
        "status": material.get("status"),
        "split": material.get("split"),
        "researcher_material_path": str(material_path.relative_to(root)),
        "researcher_material_sha256": material_sha256,
        "schedule_state_before": material.get("schedule_state_before"),
        "schedule_state_after": material.get("schedule_state_after"),
        "used_budget": material.get("used_budget"),
        "stop_reason": search.get("stop_reason"),
        "selected_candidate_id": search.get("selected_id"),
        "formal_approval": False,
        "policy_update_eligible": False,
    }
