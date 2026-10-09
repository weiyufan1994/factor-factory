"""Compatibility import; implementation lives in factor_factory.step5.evaluator."""

from factor_factory.step5.evaluator import (
    _resolve_factorforge_root,
    _get_diagnostic_summary,
    collect_backend_runs,
    _extract_key_metrics,
    _float_or_none,
    _read_csv_table,
    _numeric_frame_is_finite,
    _validate_nav_table,
    _validate_return_table,
    _issue,
    _payload_shape_errors,
    build_step4_quality_gate,
    read_backend_payloads,
    build_factor_evaluation,
)

__all__ = [
    "_resolve_factorforge_root",
    "_get_diagnostic_summary",
    "collect_backend_runs",
    "_extract_key_metrics",
    "_float_or_none",
    "_read_csv_table",
    "_numeric_frame_is_finite",
    "_validate_nav_table",
    "_validate_return_table",
    "_issue",
    "_payload_shape_errors",
    "build_step4_quality_gate",
    "read_backend_payloads",
    "build_factor_evaluation"
]
