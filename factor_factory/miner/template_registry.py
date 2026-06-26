from __future__ import annotations

from copy import deepcopy
from typing import Any

from factor_factory.miner import BLOCK_TEMPLATE_REGISTRY_INVALID


Template = dict[str, Any]


_TEMPLATES: list[Template] = [
    {
        "template_id": "open_gap_intraday_continuation",
        "family": "open_close_structure",
        "economic_prior": "Opening gaps can overreact; intraday continuation or failure separates information from noise.",
        "math_object": "segmented open-to-close return path",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "open", "close"],
        "operator_dependencies": ["segment_return", "rank", "zscore"],
        "parameter_grid": {"segment": ["open_to_close"]},
        "expected_metric_signature": {
            "ic_direction": "signed_by_continuation",
            "long_end_expected": "positive when gap confirms intraday path",
            "short_end_expected": "negative when gap fades",
            "monotonicity_expected": "moderate",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["gap bucket has no endpoint separation", "signal reverses across liquidity buckets"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "intraday_return_skew",
        "family": "price_path_shape",
        "economic_prior": "Intraday return skew captures asymmetric path pressure and reversal risk.",
        "math_object": "minute return distribution skewness",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "close"],
        "operator_dependencies": ["return", "skew", "rank"],
        "parameter_grid": {"lookback_intraday": ["1d"]},
        "expected_metric_signature": {
            "ic_direction": "negative_skew_reversal_or_positive_skew_momentum",
            "long_end_expected": "endpoint separation after rank transform",
            "short_end_expected": "tail pressure bucket should differ",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["skew buckets have flat forward returns", "effect vanishes in subsamples"],
        "fallback_if_missing": "proxy_allowed",
    },
    {
        "template_id": "intraday_return_kurtosis",
        "family": "volatility_jump_structure",
        "economic_prior": "High intraday kurtosis marks tail-dominated trading days and unstable future risk.",
        "math_object": "minute return distribution kurtosis",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "close"],
        "operator_dependencies": ["return", "kurtosis", "rank"],
        "parameter_grid": {"lookback_intraday": ["1d"]},
        "expected_metric_signature": {
            "ic_direction": "tail_risk_penalty",
            "long_end_expected": "lower tail-risk bucket should be more stable",
            "short_end_expected": "high kurtosis may act as risk filter",
            "monotonicity_expected": "weak_to_medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["no drawdown or endpoint relation", "kurtosis duplicates realized variance only"],
        "fallback_if_missing": "proxy_allowed",
    },
    {
        "template_id": "realized_var_over_range",
        "family": "volatility_jump_structure",
        "economic_prior": "Large realized variance relative to range suggests noisy churn and sigma drag.",
        "math_object": "range-normalized quadratic variation",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "high", "low", "close"],
        "operator_dependencies": ["return", "square", "sum", "divide", "rank"],
        "parameter_grid": {"range_floor": [1e-6]},
        "expected_metric_signature": {
            "ic_direction": "negative",
            "long_end_expected": "low noise bucket outperforms",
            "short_end_expected": "high noise bucket underperforms or flags risk",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["effect only size/liquidity proxy", "range floor dominates results"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "volume_weighted_range",
        "family": "volume_amount_distribution",
        "economic_prior": "Average price movement per unit volume separates locked chips from disagreement.",
        "math_object": "volume-weighted intraday range functional",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "high", "low", "vol"],
        "operator_dependencies": ["range", "weighted_mean", "rank"],
        "parameter_grid": {"weight": ["vol"]},
        "expected_metric_signature": {
            "ic_direction": "negative_if_disagreement_penalty",
            "long_end_expected": "small volume-weighted range may indicate stable holders",
            "short_end_expected": "large range per volume may indicate risk",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["no endpoint spread", "effect disappears after turnover controls"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "high_location_volume_pressure",
        "family": "volume_amount_distribution",
        "economic_prior": "High-location volume can identify distribution or crowded exit pressure.",
        "math_object": "volume measure over normalized price location",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "high", "low", "close", "vol"],
        "operator_dependencies": ["price_location", "weighted_sum", "rank"],
        "parameter_grid": {"location": ["high"]},
        "expected_metric_signature": {
            "ic_direction": "negative",
            "long_end_expected": "low high-location pressure bucket cleaner",
            "short_end_expected": "high pressure bucket underperforms",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["same result from raw volume only", "no short-end separation"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "low_location_absorption",
        "family": "volume_amount_distribution",
        "economic_prior": "Low-location volume can mark absorption when selling pressure is met by demand.",
        "math_object": "volume measure at low normalized price location",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "high", "low", "close", "vol"],
        "operator_dependencies": ["price_location", "weighted_sum", "rank"],
        "parameter_grid": {"location": ["low"]},
        "expected_metric_signature": {
            "ic_direction": "positive_if_absorption",
            "long_end_expected": "low-location absorption bucket outperforms",
            "short_end_expected": "weak absorption bucket underperforms",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["no rebound after low-location volume", "only illiquidity exposure"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "up_down_volume_imbalance_proxy",
        "family": "liquidity_flow_proxy",
        "economic_prior": "OHLCV signed-volume proxy approximates active pressure when Level2 is unavailable.",
        "math_object": "signed volume proxy",
        "required_datasets": ["minute_bar"],
        "required_fields": ["ts_code", "trade_date", "open", "close", "vol"],
        "operator_dependencies": ["sign", "sum", "divide", "rank"],
        "parameter_grid": {"sign_source": ["close_minus_open"]},
        "expected_metric_signature": {
            "ic_direction": "positive_or_reversal_by_horizon",
            "long_end_expected": "persistent buy pressure or reversal signature",
            "short_end_expected": "persistent sell pressure bucket differs",
            "monotonicity_expected": "weak_to_medium",
            "turnover_expected": "high",
        },
        "falsification_tests": ["no horizon-dependent endpoint relation", "proxy collapses in liquid names"],
        "fallback_if_missing": "proxy_allowed",
    },
    {
        "template_id": "cutoff_flow_persistence",
        "family": "liquidity_flow_proxy",
        "economic_prior": "Cutoff flow persistence may capture slow information processing before close.",
        "math_object": "intraday flow state before cutoff",
        "required_datasets": ["intraday_flow_state_v2"],
        "required_fields": ["ts_code", "trade_date", "flow_z", "large_flow_z"],
        "operator_dependencies": ["rank", "zscore", "decay"],
        "parameter_grid": {"cutoff_time": ["14:50:00"]},
        "expected_metric_signature": {
            "ic_direction": "positive",
            "long_end_expected": "strong positive flow persists",
            "short_end_expected": "large negative flow underperforms",
            "monotonicity_expected": "medium",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["flow does not survive cutoff", "effect disappears after no-future guard"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "value_occupation_support_overhang",
        "family": "value_occupation",
        "economic_prior": "Price-axis occupation can identify support, overhang, and value-area migration.",
        "math_object": "occupation measure over price bins",
        "required_datasets": ["intraday_value_occupation_state_v1"],
        "required_fields": ["ts_code", "trade_date", "poc_distance", "value_area_position"],
        "operator_dependencies": ["distance", "rank", "bucket"],
        "parameter_grid": {"state": ["support_overhang"]},
        "expected_metric_signature": {
            "ic_direction": "state_dependent",
            "long_end_expected": "support state should outperform overhang",
            "short_end_expected": "overhang bucket underperforms",
            "monotonicity_expected": "state_bucket",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["no support/overhang endpoint spread", "state duplicates close-to-range"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "turnover_acceleration",
        "family": "liquidity_flow_proxy",
        "economic_prior": "Turnover acceleration flags changing attention, liquidity demand, or crowding.",
        "math_object": "daily turnover transition",
        "required_datasets": ["daily_basic"],
        "required_fields": ["ts_code", "trade_date", "turnover"],
        "operator_dependencies": ["delta", "rank", "zscore"],
        "parameter_grid": {"lookback": [1, 5]},
        "expected_metric_signature": {
            "ic_direction": "state_dependent",
            "long_end_expected": "moderate acceleration may indicate attention",
            "short_end_expected": "extreme acceleration may flag crowding",
            "monotonicity_expected": "weak",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["no endpoint relation after size control", "only raw turnover exposure"],
        "fallback_if_missing": "needs_data",
    },
    {
        "template_id": "residual_vol_liquidity_interaction",
        "family": "projection_covariance",
        "economic_prior": "Residual volatility interacting with liquidity can reveal constrained risk transfer.",
        "math_object": "neutralized volatility-liquidity interaction",
        "required_datasets": ["daily_basic", "cheap_screen_panel"],
        "required_fields": ["ts_code", "trade_date", "turnover"],
        "operator_dependencies": ["residualize", "multiply", "rank"],
        "parameter_grid": {"controls": ["size", "liquidity"]},
        "expected_metric_signature": {
            "ic_direction": "negative_if_constrained_risk",
            "long_end_expected": "low residual risk/liquidity stress bucket outperforms",
            "short_end_expected": "high stress bucket underperforms",
            "monotonicity_expected": "medium_after_controls",
            "turnover_expected": "medium",
        },
        "falsification_tests": ["effect vanishes before residualization", "no liquidity interaction"],
        "fallback_if_missing": "partial",
    },
]


def load_template_registry() -> list[Template]:
    templates = deepcopy(_TEMPLATES)
    ids = [str(row.get("template_id") or "") for row in templates]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError(f"{BLOCK_TEMPLATE_REGISTRY_INVALID}: duplicate_or_missing_template_id")
    for template in templates:
        required = ("family", "economic_prior", "math_object", "required_datasets", "required_fields", "operator_dependencies")
        missing = [key for key in required if key not in template]
        if missing:
            raise ValueError(f"{BLOCK_TEMPLATE_REGISTRY_INVALID}: {template.get('template_id')} missing {missing}")
    return templates


def template_by_id(template_id: str) -> Template:
    for template in load_template_registry():
        if template["template_id"] == template_id:
            return template
    raise KeyError(f"{BLOCK_TEMPLATE_REGISTRY_INVALID}: unknown_template:{template_id}")
