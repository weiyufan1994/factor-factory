from __future__ import annotations

from typing import Any, Dict


def build_intake_diff(primary: Dict[str, Any], challenger: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'primary_final_factor': primary.get('final_factor', {}).get('name'),
        'challenger_final_factor': challenger.get('final_factor', {}).get('name'),
        'primary_subfactors': [x.get('name') for x in primary.get('subfactors', [])],
        'challenger_subfactors': [x.get('name') for x in challenger.get('subfactors', [])],
        'ambiguity_gap': {
            'primary': primary.get('ambiguities', []),
            'challenger': challenger.get('ambiguities', []),
        },
    }
