from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake
from ..research_discipline import attach_step1_research_discipline


def merge_to_alpha_idea_master(
    primary_intake: StructuredIntake,
    challenger_intake: StructuredIntake,
    primary_thesis: Dict[str, Any],
    challenger_thesis: Dict[str, Any],
    chief_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the canonical alpha_idea_master object from all inputs."""
    ff = chief_decision.get('final_factor', {})

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
        },
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
    return attach_step1_research_discipline(
        alpha_idea_master,
        None,
        primary_thesis,
        challenger_thesis,
        chief_decision,
    )
