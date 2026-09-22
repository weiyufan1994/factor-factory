from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from ..intake.structured_intake_contract import StructuredIntake
from ..research_discipline import attach_step1_research_discipline


# These are caller-authored fields which describe the source/factor contract
# rather than a merge implementation detail.  The legacy route never copied
# them because its normalizer rebuilt a research discipline.  The local
# agent-authored route must retain them verbatim instead of silently reducing
# the chief packet to the small historical alpha-master projection.
AGENT_AUTHORED_TOP_LEVEL_FIELDS = (
    'factor_id',
    'source_type',
    'research_subject_mode',
    'source_baseline_reference',
    'source_semantic_review',
    'local_agent_spec_inputs',
    'direct_code_spec',
    'code_contract',
    'direct_code_contract',
    'implementation_contract',
    'batch_execution_plan',
    'research_window_contract',
    'evaluation_contract',
    'math_discipline_review',
    'learning_and_innovation',
)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _meaningful_items(values: List[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = str(value or '').strip()
        if text and text.lower() not in {'under_specified', 'unknown', 'n/a', 'none', 'todo', 'tbd'} and text not in out:
            out.append(text)
    return out


def _collect_from_sources(sources: List[tuple[str, Any]]) -> tuple[List[str], List[str]]:
    items: List[str] = []
    source_names: List[str] = []
    for source_name, value in sources:
        source_items = _meaningful_items(_as_list(value))
        if not source_items:
            continue
        for item in source_items:
            if item not in items:
                items.append(item)
        source_names.append(source_name)
    return items, source_names


def _derive_step1_market_process_fields(chief_decision: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve or derive v2 mechanism fields only from chief/raw evidence.

    This intentionally does not invent generic assumptions. If chief/raw content
    lacks enough mechanism detail, downstream Step1 validation should continue
    to block the formal artifact.
    """
    ff = chief_decision.get('final_factor') or {}
    explicit_thesis = chief_decision.get('market_process_thesis') if isinstance(chief_decision.get('market_process_thesis'), dict) else {}
    explicit_assumptions, assumption_sources = _collect_from_sources([
        ('chief_raw.what_must_be_true', chief_decision.get('what_must_be_true')),
        ('chief_raw.market_process_thesis.what_must_be_true', explicit_thesis.get('what_must_be_true')),
        ('chief_raw.mechanism_assumptions', chief_decision.get('mechanism_assumptions')),
        ('chief_raw.final_factor.what_must_be_true', ff.get('what_must_be_true')),
    ])
    explicit_breaks, break_sources = _collect_from_sources([
        ('chief_raw.what_would_break_it', chief_decision.get('what_would_break_it')),
        ('chief_raw.market_process_thesis.what_would_break_it', explicit_thesis.get('what_would_break_it')),
        ('chief_raw.falsification_conditions', chief_decision.get('falsification_conditions')),
        ('chief_raw.final_factor.what_would_break_it', ff.get('what_would_break_it')),
        ('chief_raw.final_factor.key_implementation_risks', ff.get('key_implementation_risks')),
    ])

    derived_from: List[str] = []
    if explicit_assumptions:
        derived_from.extend(assumption_sources)
    else:
        mechanism_sources = [
            ('chief_raw.final_factor.economic_logic', ff.get('economic_logic')),
            ('chief_raw.final_factor.behavioral_logic', ff.get('behavioral_logic')),
            ('chief_raw.final_factor.causal_chain', ff.get('causal_chain')),
        ]
        for source_name, value in mechanism_sources:
            items = _meaningful_items(_as_list(value))
            if items:
                explicit_assumptions.extend(items)
                derived_from.append(source_name)

    if explicit_breaks:
        derived_from.extend(break_sources)
    else:
        ambiguity_breaks = _meaningful_items(_as_list(chief_decision.get('unresolved_ambiguities')))
        if ambiguity_breaks:
            explicit_breaks.extend(ambiguity_breaks)
            derived_from.append('chief_raw.unresolved_ambiguities')

    thesis = dict(explicit_thesis)
    if explicit_assumptions:
        thesis.setdefault('what_must_be_true', explicit_assumptions)
    if explicit_breaks:
        thesis.setdefault('what_would_break_it', explicit_breaks)
    if ff.get('economic_logic'):
        thesis.setdefault('economic_hypothesis', ff.get('economic_logic'))
        thesis.setdefault('market_phenomenon', ff.get('causal_chain') if isinstance(ff.get('causal_chain'), str) else ' ; '.join(_meaningful_items(_as_list(ff.get('causal_chain')))))
    if ff.get('behavioral_logic'):
        thesis.setdefault('why_they_pay', ff.get('behavioral_logic'))
    if not thesis.get('payer_or_counterparty') and chief_decision.get('payer_or_counterparty'):
        thesis['payer_or_counterparty'] = chief_decision.get('payer_or_counterparty')
    if not thesis.get('return_source_family') and chief_decision.get('return_source_family'):
        thesis['return_source_family'] = chief_decision.get('return_source_family')
    if not thesis.get('alternative_return_source_tests') and chief_decision.get('alternative_return_source_tests'):
        thesis['alternative_return_source_tests'] = chief_decision.get('alternative_return_source_tests')

    return {
        'market_process_thesis': thesis,
        'what_must_be_true': explicit_assumptions,
        'what_would_break_it': explicit_breaks,
        'provenance': {
            'derived_from': list(dict.fromkeys(item for item in derived_from if item)),
            'derivation_policy': 'preserve_or_derive_only_from_chief_raw_mechanism_content',
            'generic_template_used': False,
        },
    }


def _resolve_measurement_program(
    primary_intake: StructuredIntake,
    challenger_intake: StructuredIntake,
    chief_decision: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    chief = chief_decision.get('mechanism_conditioned_measurement_program')
    chief = chief if isinstance(chief, dict) and chief else {}
    primary = primary_intake.mechanism_conditioned_measurement_program
    primary = primary if isinstance(primary, dict) and primary else {}
    challenger = challenger_intake.mechanism_conditioned_measurement_program
    challenger = challenger if isinstance(challenger, dict) and challenger else {}

    if chief:
        return deepcopy(chief), {
            'resolution': 'chief_authored_resolution',
            'primary_agrees': not primary or primary == chief,
            'challenger_agrees': not challenger or challenger == chief,
        }
    if primary and challenger and primary != challenger:
        return {}, {
            'resolution': 'unresolved_primary_challenger_conflict',
            'primary_agrees': False,
            'challenger_agrees': False,
        }
    selected = primary or challenger
    return deepcopy(selected), {
        'resolution': (
            'dual_route_exact_match'
            if primary and challenger
            else 'single_route_preserved_for_legacy_migration'
            if selected
            else 'missing'
        ),
        'primary_agrees': bool(primary and selected == primary),
        'challenger_agrees': bool(challenger and selected == challenger),
    }


def merge_to_alpha_idea_master(
    primary_intake: StructuredIntake,
    challenger_intake: StructuredIntake,
    primary_thesis: Dict[str, Any],
    challenger_thesis: Dict[str, Any],
    chief_decision: Dict[str, Any],
    *,
    agent_authored_only: bool = False,
) -> Dict[str, Any]:
    """Build the canonical alpha_idea_master object from all inputs.

    ``agent_authored_only`` is a narrow local-ingest mode.  It does not call
    ``attach_step1_research_discipline`` (which performs deterministic
    inference and knowledge retrieval).  Its caller must supply a complete
    chief-authored ``research_discipline`` and is responsible for validating
    that packet before this merger is called.  The default remains the legacy
    normalization behaviour for all existing consumers.
    """
    if agent_authored_only:
        return _merge_agent_authored_only(
            primary_intake,
            challenger_intake,
            primary_thesis,
            challenger_thesis,
            chief_decision,
        )
    ff = chief_decision.get('final_factor', {})
    mechanism_fields = _derive_step1_market_process_fields(chief_decision)
    measurement_program, measurement_program_provenance = _resolve_measurement_program(
        primary_intake,
        challenger_intake,
        chief_decision,
    )

    alpha_idea_master = {
        'report_id': primary_intake.report_id,
        'report_meta': primary_intake.report_meta,
        'final_factor': {
            'name': ff.get('name', ''),
            'assembly_steps': ff.get('assembly_steps', []),
            'accepted_subfactor_names': ff.get('accepted_subfactor_names', []),
            'direction': ff.get('direction', ''),
            'alpha_strength': ff.get('alpha_strength', ''),
            'alpha_source': ff.get('alpha_source', ''),
            'key_implementation_risks': ff.get('key_implementation_risks', []),
            'economic_logic': ff.get('economic_logic', ''),
            'economic_logic_provenance': ff.get('economic_logic_provenance', ''),
            'behavioral_logic': ff.get('behavioral_logic', ''),
            'behavioral_logic_provenance': ff.get('behavioral_logic_provenance', ''),
            'causal_chain': ff.get('causal_chain', ''),
            'causal_chain_provenance': ff.get('causal_chain_provenance', ''),
            'what_must_be_true': mechanism_fields['what_must_be_true'],
            'what_would_break_it': mechanism_fields['what_would_break_it'],
        },
        'market_process_thesis': mechanism_fields['market_process_thesis'],
        'economic_hypothesis_candidates': (
            chief_decision.get('economic_hypothesis_candidates')
            or primary_intake.economic_hypothesis_candidates
            or challenger_intake.economic_hypothesis_candidates
        ),
        'preferred_economic_hypothesis': (
            chief_decision.get('preferred_economic_hypothesis')
            or primary_intake.preferred_economic_hypothesis
            or challenger_intake.preferred_economic_hypothesis
        ),
        'alternative_return_source_tests': (
            chief_decision.get('alternative_return_source_tests')
            or primary_intake.alternative_return_source_tests
            or challenger_intake.alternative_return_source_tests
        ),
        'primary_mathematical_model': (
            chief_decision.get('primary_mathematical_model')
            or primary_intake.primary_mathematical_model
            or challenger_intake.primary_mathematical_model
        ),
        'formula_as_observable_estimator': (
            chief_decision.get('formula_as_observable_estimator')
            or primary_intake.formula_as_observable_estimator
            or challenger_intake.formula_as_observable_estimator
        ),
        'measurement_program_provenance': measurement_program_provenance,
        'market_process_thesis_provenance': mechanism_fields['provenance'],
        'rejected_subfactors': ff.get('rejected_subfactor_details', []),
        'logic_provenance_summary': chief_decision.get('logic_provenance_summary', {}),
        'assembly_path': chief_decision.get('assembly_path', []),
        'unresolved_ambiguities': chief_decision.get('unresolved_ambiguities', []),
        'chief_decision_summary': chief_decision.get('chief_decision_summary', ''),
        'chief_confidence': chief_decision.get('chief_confidence', ''),
        'chief_rationale': chief_decision.get('chief_rationale', ''),
        # Provenance trace
        'provenance': {
            'primary_intake_report_id': primary_intake.report_id,
            'primary_thesis_route': 'primary',
            'challenger_intake_report_id': challenger_intake.report_id,
            'challenger_thesis_route': 'challenger',
        }
    }
    if measurement_program:
        alpha_idea_master['mechanism_conditioned_measurement_program'] = deepcopy(
            measurement_program
        )
        route = (measurement_program.get('implementation') or {}).get('route')
        if route:
            alpha_idea_master['implementation_mode'] = route
        alpha_idea_master['research_discipline'] = {
            'mechanism_conditioned_measurement_program': deepcopy(
                measurement_program
            ),
            'market_outcome_projection': deepcopy(
                measurement_program.get('market_outcome_projection') or {}
            ),
        }
    elif measurement_program_provenance['resolution'].startswith('unresolved'):
        alpha_idea_master['unresolved_ambiguities'] = list(
            dict.fromkeys(
                [
                    *alpha_idea_master['unresolved_ambiguities'],
                    'measurement_program_primary_challenger_conflict_requires_chief_resolution',
                ]
            )
        )
    return attach_step1_research_discipline(
        alpha_idea_master,
        None,
        primary_thesis,
        challenger_thesis,
        chief_decision,
    )


def _merge_agent_authored_only(
    primary_intake: StructuredIntake,
    challenger_intake: StructuredIntake,
    primary_thesis: Dict[str, Any],
    challenger_thesis: Dict[str, Any],
    chief_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Project only explicitly authored chief content; infer nothing.

    This intentionally avoids the normal legacy fallbacks from primary or
    challenger fields.  Those inputs remain available in the evidence packet
    written by the local CLI, while the canonical fields are explicitly owned
    by the supplied chief decision.
    """
    discipline = chief_decision.get('research_discipline')
    if not isinstance(discipline, dict):
        raise ValueError('agent_authored_only requires chief_decision.research_discipline object')
    final_factor = chief_decision.get('final_factor')
    if not isinstance(final_factor, dict):
        raise ValueError('agent_authored_only requires chief_decision.final_factor object')
    measurement_program = discipline.get('mechanism_conditioned_measurement_program')
    if not isinstance(measurement_program, dict) or not measurement_program:
        raise ValueError(
            'agent_authored_only requires chief_decision.research_discipline.'
            'mechanism_conditioned_measurement_program object'
        )
    top_level_program = chief_decision.get('mechanism_conditioned_measurement_program')
    if top_level_program is not None and top_level_program != measurement_program:
        raise ValueError(
            'agent_authored_only chief measurement program differs between top-level and research_discipline'
        )

    alpha_idea_master = {
        'report_id': primary_intake.report_id,
        'report_meta': deepcopy(primary_intake.report_meta),
        'final_factor': deepcopy(final_factor),
        'market_process_thesis': deepcopy(
            chief_decision.get('market_process_thesis')
            if isinstance(chief_decision.get('market_process_thesis'), dict)
            else discipline.get('market_process_thesis')
        ),
        'economic_hypothesis_candidates': deepcopy(chief_decision.get('economic_hypothesis_candidates', [])),
        'preferred_economic_hypothesis': deepcopy(chief_decision.get('preferred_economic_hypothesis', {})),
        'alternative_return_source_tests': deepcopy(chief_decision.get('alternative_return_source_tests', [])),
        'primary_mathematical_model': deepcopy(chief_decision.get('primary_mathematical_model', {})),
        'formula_as_observable_estimator': deepcopy(chief_decision.get('formula_as_observable_estimator', {})),
        'logic_provenance_summary': deepcopy(chief_decision.get('logic_provenance_summary', {})),
        'assembly_path': deepcopy(chief_decision.get('assembly_path', final_factor.get('assembly_steps', []))),
        'unresolved_ambiguities': deepcopy(chief_decision.get('unresolved_ambiguities', [])),
        'chief_decision_summary': chief_decision.get('chief_decision_summary', ''),
        'chief_confidence': chief_decision.get('chief_confidence', ''),
        'chief_rationale': chief_decision.get('chief_rationale', ''),
        'research_discipline': deepcopy(discipline),
        'mechanism_conditioned_measurement_program': deepcopy(measurement_program),
        'implementation_mode': (measurement_program.get('implementation') or {}).get('route'),
        'measurement_program_provenance': {
            'resolution': 'chief_authored_research_discipline',
            'primary_agrees': (
                not primary_intake.mechanism_conditioned_measurement_program
                or primary_intake.mechanism_conditioned_measurement_program == measurement_program
            ),
            'challenger_agrees': (
                not challenger_intake.mechanism_conditioned_measurement_program
                or challenger_intake.mechanism_conditioned_measurement_program == measurement_program
            ),
        },
        'market_process_thesis_provenance': {
            'derivation_policy': 'chief_authored_only_no_inference_or_knowledge_retrieval',
            'generic_template_used': False,
        },
        'provenance': {
            'primary_intake_report_id': primary_intake.report_id,
            'primary_thesis_route': 'primary',
            'challenger_intake_report_id': challenger_intake.report_id,
            'challenger_thesis_route': 'challenger',
            'merge_mode': 'agent_authored_only',
        },
    }
    for field in AGENT_AUTHORED_TOP_LEVEL_FIELDS:
        if field in chief_decision:
            alpha_idea_master[field] = deepcopy(chief_decision[field])
    # The caller may carry additional experimental/source fields.  Keep those
    # exact bytes in an explicit canonical extension namespace rather than
    # treating them as normalizer inputs or dropping them.
    core_fields = {
        'report_id', 'final_factor', 'market_process_thesis',
        'economic_hypothesis_candidates', 'preferred_economic_hypothesis',
        'alternative_return_source_tests', 'primary_mathematical_model',
        'formula_as_observable_estimator', 'logic_provenance_summary',
        'assembly_path', 'unresolved_ambiguities', 'chief_decision_summary',
        'chief_confidence', 'chief_rationale', 'research_discipline',
        'mechanism_conditioned_measurement_program', *AGENT_AUTHORED_TOP_LEVEL_FIELDS,
    }
    alpha_idea_master['agent_authored_chief_extensions'] = {
        key: deepcopy(value)
        for key, value in chief_decision.items()
        if key not in core_fields
    }
    return alpha_idea_master
