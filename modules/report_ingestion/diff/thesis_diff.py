from __future__ import annotations

from typing import Any, Dict, List


def build_thesis_diff(primary: Dict[str, Any], challenger: Dict[str, Any]) -> Dict[str, Any]:
    """Compare primary and challenger thesis objects and surface structural differences."""
    fields_to_compare = [
        'economic_logic', 'behavioral_logic', 'causal_chain',
        'direction', 'thesis_name',
    ]
    logic_fields = ['economic_logic', 'behavioral_logic', 'causal_chain']
    source_fields = ['economic_logic_source', 'behavioral_logic_source', 'causal_chain_source']

    diff = {}
    for field in fields_to_compare:
        p_val = primary.get(field)
        c_val = challenger.get(field)
        if p_val != c_val:
            diff[field] = {'primary': p_val, 'challenger': c_val}

    # Source/provenance diff
    source_diff = {}
    for field in source_fields:
        p_val = primary.get(field)
        c_val = challenger.get(field)
        if p_val != c_val:
            source_diff[field] = {'primary': p_val, 'challenger': c_val}
    if source_diff:
        diff['logic_sources'] = source_diff

    # Subfactors comparison
    p_subs = primary.get('subfactors', [])
    c_subs = challenger.get('subfactors', [])
    if p_subs != c_subs:
        diff['subfactors'] = {'primary': p_subs, 'challenger': c_subs}

    # Final factor comparison
    p_ff = primary.get('final_factor', {})
    c_ff = challenger.get('final_factor', {})
    if p_ff != c_ff:
        diff['final_factor'] = {'primary': p_ff, 'challenger': c_ff}

    return diff if diff else {"status": "no_structural_diff"}
