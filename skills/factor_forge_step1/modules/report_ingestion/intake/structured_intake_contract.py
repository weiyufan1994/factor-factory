from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class StructuredIntake:
    report_id: str
    report_meta: Dict[str, Any] = field(default_factory=dict)
    section_map: List[Dict[str, Any]] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    signals: List[str] = field(default_factory=list)
    subfactors: List[Dict[str, Any]] = field(default_factory=list)
    final_factor: Dict[str, Any] = field(default_factory=dict)
    formula_clues: List[Dict[str, Any]] = field(default_factory=list)
    code_clues: List[Dict[str, Any]] = field(default_factory=list)
    implementation_clues: List[Dict[str, Any]] = field(default_factory=list)
    alpha_candidates: List[Dict[str, Any]] = field(default_factory=list)
    evidence_clues: List[Dict[str, Any]] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
