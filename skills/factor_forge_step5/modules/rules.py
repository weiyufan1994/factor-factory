"""Compatibility import; implementation lives in factor_factory.step5.rules."""

from factor_factory.step5.rules import (
    VALID_FINAL_STATUS,
    LONG_SIDE_CANDIDATE_MIN_SHARPE,
    _resolve_factorforge_root,
    _get_diagnostic_summary,
    load_step5_inputs,
    validate_input_consistency,
    determine_final_status,
    build_evaluation_summary,
)

__all__ = [
    "VALID_FINAL_STATUS",
    "LONG_SIDE_CANDIDATE_MIN_SHARPE",
    "_resolve_factorforge_root",
    "_get_diagnostic_summary",
    "load_step5_inputs",
    "validate_input_consistency",
    "determine_final_status",
    "build_evaluation_summary"
]
