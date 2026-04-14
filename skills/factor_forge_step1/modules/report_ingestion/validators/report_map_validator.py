from __future__ import annotations

from typing import Any, Dict, List, Set


class ReportMapValidator:
    def compare(self, primary: Dict[str, Any], challenger: Dict[str, Any]) -> Dict[str, Any]:
        section_agreement = self._compare_section_structure(primary, challenger)
        variable_overlap = self._compare_variable_inventory(primary, challenger)
        visual_alignment = self._compare_visual_elements(primary, challenger)
        issues = self._collect_issues(primary, challenger)
        needs_arbitration = bool(section_agreement < 0.7 or variable_overlap < 0.6 or issues)
        result = {
            "pass": not needs_arbitration,
            "section_agreement": section_agreement,
            "variable_overlap": variable_overlap,
            "visual_alignment": visual_alignment,
            "issues": issues,
            "needs_arbitration": needs_arbitration,
        }
        return result

    def is_pass(self, compare_result: Dict[str, Any]) -> bool:
        return bool(compare_result.get("pass"))

    def _compare_section_structure(self, primary: Dict[str, Any], challenger: Dict[str, Any]) -> float:
        p = len(primary.get("section_map", []))
        c = len(challenger.get("section_map", []))
        if p == c == 0:
            return 1.0
        return min(p, c) / max(p, c) if max(p, c) else 0.0

    def _compare_variable_inventory(self, primary: Dict[str, Any], challenger: Dict[str, Any]) -> float:
        p: Set[str] = set(primary.get("variables", []))
        c: Set[str] = set(challenger.get("variables", []))
        if not p and not c:
            return 1.0
        return len(p & c) / len(p | c) if (p or c) else 0.0

    def _compare_visual_elements(self, primary: Dict[str, Any], challenger: Dict[str, Any]) -> float:
        p = len(primary.get("key_visual_elements", []))
        c = len(challenger.get("key_visual_elements", []))
        if p == c == 0:
            return 1.0
        return min(p, c) / max(p, c) if max(p, c) else 0.0

    def _collect_issues(self, primary: Dict[str, Any], challenger: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        if self._compare_section_structure(primary, challenger) < 0.7:
            issues.append("section structure mismatch")
        if self._compare_variable_inventory(primary, challenger) < 0.6:
            issues.append("variable inventory mismatch")
        return issues
