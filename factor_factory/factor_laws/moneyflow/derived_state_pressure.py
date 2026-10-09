"""Pressure-state calculations and historical cost/quality law variants."""

import numpy as _factorforge_np
import pandas as _factorforge_pd
from .derived_state_common import _factorforge_z_by_day, _factorforge_positive


def _quality_cost_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * out["precision_gain"].fillna(0.0)
                + 0.22 * out["state_persistence"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
                - 0.10 * out["impact_pressure"].fillna(0.0)
                - 0.04
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["quality_cost_boundary"] = (
        out["expected_cost_boundary"].fillna(0.0)
        + 0.08 * out["impact_pressure"].fillna(0.0)
        + 0.06 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["quality_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.10 * out["quality_cost_boundary"].fillna(0.0)
        )
    )
    out["factor_value"] = (
        out["quality_excess_state"].fillna(0.0)
        * (0.78 + 0.16 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * out["quality_weight"].fillna(0.0)
        - 0.12 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _leader_state_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.42 * out["precision_gain"].fillna(0.0)
                + 0.24 * out["state_persistence"].fillna(0.0)
                + 0.16 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
                - 0.10 * out["impact_pressure"].fillna(0.0)
                - 0.05
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["leader_continuation_margin"] = (
        0.36 * out["state_persistence"].fillna(0.0)
        + 0.30 * out["precision_gain"].fillna(0.0)
        + 0.22 * _factorforge_positive(out["concentration_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
        - 0.24 * out["prior_overheat"].fillna(0.0)
        - 0.16 * out["observation_noise"].fillna(0.0)
        - 0.06
    )
    out["leader_state_score"] = 1.0 / (
        1.0
        + _factorforge_np.exp(-out["leader_continuation_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["soft_cost_load"] = (
        0.12 * out["impact_pressure"].fillna(0.0)
        + 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        + 0.05 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.035 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["leader_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.07 * out["expected_cost_boundary"].fillna(0.0)
        )
    )
    out["factor_value"] = (
        out["leader_excess_state"].fillna(0.0)
        * (0.76 + 0.16 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * out["quality_weight"].fillna(0.0)
        * (0.88 + 0.28 * out["leader_state_score"].fillna(0.0))
        - out["soft_cost_load"].fillna(0.0)
    )
    return out


def _moment_proxy_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    for _moment_col in ("amount_hhi", "flow_hhi", "net_flow_ratio", "large_net_flow_ratio_rel", "small_net_flow_ratio_rel"):
        if _moment_col not in out.columns:
            out[_moment_col] = _factorforge_np.nan
        out[_moment_col] = _factorforge_pd.to_numeric(out[_moment_col], errors="coerce")
    out["amount_hhi_z"] = _factorforge_z_by_day(out, "amount_hhi")
    out["flow_hhi_z"] = _factorforge_z_by_day(out, "flow_hhi")
    out["net_flow_ratio_z"] = _factorforge_z_by_day(out, "net_flow_ratio")
    out["large_small_flow_spread"] = out["large_net_flow_ratio_rel"].fillna(0.0) - out["small_net_flow_ratio_rel"].fillna(0.0)
    out["large_small_flow_spread_z"] = _factorforge_z_by_day(out, "large_small_flow_spread")
    out["moment_tail_proxy"] = (
        0.34 * _factorforge_positive(out["amount_hhi_z"]).fillna(0.0)
        + 0.30 * _factorforge_positive(out["flow_hhi_z"]).fillna(0.0)
        + 0.22 * _factorforge_positive(out["large_small_flow_spread_z"]).fillna(0.0)
        + 0.14 * _factorforge_positive(out["net_flow_ratio_z"]).fillna(0.0)
    )
    out["moment_quality_filter"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.38 * out["precision_gain"].fillna(0.0)
                + 0.30 * out["moment_tail_proxy"].fillna(0.0)
                + 0.18 * out["state_persistence"].fillna(0.0)
                - 0.24 * out["observation_noise"].fillna(0.0)
                - 0.18 * out["prior_overheat"].fillna(0.0)
                - 0.10
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["moment_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.08 * out["expected_cost_boundary"].fillna(0.0)
        )
    )
    out["factor_value"] = (
        out["moment_excess_state"].fillna(0.0)
        * out["moment_quality_filter"].fillna(0.0)
        * (1.0 + 0.08 * out["precision_gain"].fillna(0.0))
        - 0.10 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _information_soft_cost_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["v7_information_edge"] = (
        out["state_surprise"].fillna(0.0)
        * out["fisher_information"].fillna(0.0)
        / (1.0 + out["impact_pressure"].fillna(0.0) + out["observation_noise"].fillna(0.0))
    )
    out["v7_information_edge"] = out["v7_information_edge"].clip(lower=-10.0, upper=10.0)
    out["information_gate_margin"] = (
        0.42 * out["precision_gain"].fillna(0.0)
        + 0.22 * out["state_persistence"].fillna(0.0)
        + 0.18 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
        - 0.20 * out["observation_noise"].fillna(0.0)
        - 0.12 * out["impact_pressure"].fillna(0.0)
        - 0.05
    )
    out["information_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(-out["information_gate_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["v9a_soft_cost_load"] = (
        0.12 * out["impact_pressure"].fillna(0.0)
        + 0.11 * out["right_tail_overpricing_penalty"].fillna(0.0)
        + 0.06 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["factor_value"] = (
        out["v7_information_edge"].fillna(0.0)
        * out["information_gate"].fillna(0.0)
        * (0.90 + 0.10 * out["state_persistence"].fillna(0.0))
        - out["v9a_soft_cost_load"].fillna(0.0)
    )
    return out


def _payer_soft_gate_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * out["precision_gain"].fillna(0.0)
                + 0.22 * out["state_persistence"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
                - 0.10 * out["impact_pressure"].fillna(0.0)
                - 0.04
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["quality_cost_boundary"] = (
        out["expected_cost_boundary"].fillna(0.0)
        + 0.08 * out["impact_pressure"].fillna(0.0)
        + 0.06 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["quality_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.10 * out["quality_cost_boundary"].fillna(0.0)
        )
    )
    out["v9a_base_signal"] = (
        out["quality_excess_state"].fillna(0.0)
        * (0.78 + 0.16 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * out["quality_weight"].fillna(0.0)
        - 0.12 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["small_size_score"] = _factorforge_positive(-out["size_prev_z"].fillna(0.0)).clip(0.0, 2.5)
    out["not_mega_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp((out["size_prev_z"].fillna(0.0) - 0.80).clip(lower=-20.0, upper=20.0))
    )
    out["tradable_activity_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.22 * out["float_turnover_prev_z"].fillna(0.0)
                + 0.18 * out["relative_participation_z"].fillna(0.0)
                - 0.20 * out["observation_noise"].fillna(0.0)
                - 0.12 * out["impact_pressure"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["payer_soft_gate"] = (
        0.68
        + 0.18 * out["not_mega_gate"].fillna(0.0)
        + 0.10 * out["tradable_activity_gate"].fillna(0.0)
        + 0.04 * out["small_size_score"].fillna(0.0) / 2.5
    ).clip(0.50, 1.05)
    out["factor_value"] = (
        out["v9a_base_signal"].fillna(0.0) * out["payer_soft_gate"].fillna(0.0)
        - 0.025 * _factorforge_positive(out["size_prev_z"].fillna(0.0) - 1.0)
    )
    return out


def _small_mid_liquidity_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * out["precision_gain"].fillna(0.0)
                + 0.22 * out["state_persistence"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
                - 0.10 * out["impact_pressure"].fillna(0.0)
                - 0.04
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["quality_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.10 * out["expected_cost_boundary"].fillna(0.0)
        )
    )
    out["v9a_base_signal"] = (
        out["quality_excess_state"].fillna(0.0)
        * (0.78 + 0.16 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * out["quality_weight"].fillna(0.0)
        - 0.12 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["mega_penalty"] = _factorforge_positive(out["size_prev_z"].fillna(0.0) - 0.75)
    out["micro_illiquid_penalty"] = (
        _factorforge_positive(-out["size_prev_z"].fillna(0.0) - 1.60)
        + _factorforge_positive(-out["float_turnover_prev_z"].fillna(0.0) - 0.50)
    )
    out["small_mid_liquidity_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.38 * _factorforge_positive(-out["size_prev_z"].fillna(0.0)).clip(0.0, 2.0)
                + 0.24 * out["float_turnover_prev_z"].fillna(0.0)
                + 0.16 * out["relative_participation_z"].fillna(0.0)
                - 0.34 * out["mega_penalty"].fillna(0.0)
                - 0.30 * out["micro_illiquid_penalty"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["factor_value"] = (
        out["v9a_base_signal"].fillna(0.0) * (0.72 + 0.34 * out["small_mid_liquidity_gate"].fillna(0.0))
        - 0.04 * out["mega_penalty"].fillna(0.0)
        - 0.04 * out["micro_illiquid_penalty"].fillna(0.0)
    )
    return out


def _hot_money_preposition_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * out["precision_gain"].fillna(0.0)
                + 0.22 * out["state_persistence"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
                - 0.10 * out["impact_pressure"].fillna(0.0)
                - 0.04
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["quality_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.10 * out["expected_cost_boundary"].fillna(0.0)
        )
    )
    out["v9a_base_signal"] = (
        out["quality_excess_state"].fillna(0.0)
        * (0.78 + 0.16 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * out["quality_weight"].fillna(0.0)
        - 0.12 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["preposition_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.28 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
                + 0.24 * _factorforge_positive(out["concentration_z"]).fillna(0.0)
                + 0.20 * out["precision_gain"].fillna(0.0)
                - 0.34 * out["prior_overheat"].fillna(0.0)
                - 0.22 * _factorforge_positive(out["pct_chg_prev_z"]).fillna(0.0)
                - 0.16 * out["observation_noise"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["strategic_anchor_penalty"] = _factorforge_positive(out["size_prev_z"].fillna(0.0) - 0.85) * (
        1.0 / (1.0 + out["turnover_prev_z"].abs().fillna(0.0))
    )
    out["factor_value"] = (
        out["v9a_base_signal"].fillna(0.0) * (0.70 + 0.36 * out["preposition_gate"].fillna(0.0))
        - 0.045 * out["strategic_anchor_penalty"].fillna(0.0)
        - 0.030 * out["prior_overheat"].fillna(0.0)
    )
    return out


def _posterior_odds_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_state_variance"] = (
        1.0 / (1.0 + out["fisher_information"].fillna(0.0))
        + 0.15 * out["observation_noise"].fillna(0.0) ** 2
        + 0.08 * out["impact_pressure"].fillna(0.0)
    ).clip(lower=0.03, upper=12.0)
    out["posterior_state_std"] = _factorforge_np.sqrt(out["posterior_state_variance"].fillna(1.0))
    out["boundary_pressure"] = _factorforge_positive(
        1.0
        - out["hysteretic_state"].abs().fillna(0.0)
        / (
            out["hold_boundary"].fillna(0.18)
            + 0.45 * out["posterior_state_std"].fillna(1.0)
            + 1.0e-6
        )
    )
    out["convex_cost_boundary"] = (
        out["expected_cost_boundary"].fillna(0.0)
        + 0.16 * out["impact_pressure"].fillna(0.0) ** 2
        + 0.12 * out["observation_noise"].fillna(0.0) ** 2
        + 0.14 * out["boundary_pressure"].fillna(0.0) ** 2
        + 0.08 * out["posterior_state_std"].fillna(1.0) * out["boundary_pressure"].fillna(0.0)
        + 0.05 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["posterior_drift_mean"] = (
        out["hysteretic_state"].fillna(0.0)
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        * (0.92 + 0.08 * out["state_persistence"].fillna(0.0))
    )
    out["posterior_cost_sigma"] = (
        0.25
        + 0.18 * out["observation_noise"].fillna(0.0)
        + 0.10 * out["impact_pressure"].fillna(0.0)
        + 0.05 * out["boundary_pressure"].fillna(0.0)
    )
    out["posterior_net_surplus_z"] = (
        out["posterior_drift_mean"].fillna(0.0)
        - 0.72 * out["convex_cost_boundary"].fillna(0.0)
    ) / _factorforge_np.sqrt(
        out["posterior_state_variance"].fillna(1.0)
        + out["posterior_cost_sigma"].fillna(0.25) ** 2
        + 1.0e-6
    )
    out["posterior_net_surplus_z"] = out["posterior_net_surplus_z"].clip(lower=-8.0, upper=8.0)
    out["posterior_net_prob"] = 1.0 / (
        1.0 + _factorforge_np.exp(-1.70 * out["posterior_net_surplus_z"].fillna(0.0))
    )
    out["posterior_odds_score"] = _factorforge_np.log(
        out["posterior_net_prob"].clip(lower=1.0e-6, upper=1.0 - 1.0e-6)
        / (1.0 - out["posterior_net_prob"].clip(lower=1.0e-6, upper=1.0 - 1.0e-6))
    )
    out["posterior_quality_weight"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.38 * out["precision_gain"].fillna(0.0)
                + 0.20 * out["state_persistence"].fillna(0.0)
                - 0.22 * out["observation_noise"].fillna(0.0)
                - 0.14 * out["boundary_pressure"].fillna(0.0)
                - 0.06
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["factor_value"] = (
        out["posterior_odds_score"].fillna(0.0)
        * out["posterior_quality_weight"].fillna(0.0)
        - 0.08 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.06 * out["impact_pressure"].fillna(0.0)
        - 0.04 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _durable_surplus_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["surplus_boundary"] = (
        out["hold_boundary"].fillna(0.18)
        + 0.22 * out["expected_cost_boundary"].fillna(0.0)
        + 0.10 * out["impact_pressure"].fillna(0.0)
        + 0.08 * out["observation_noise"].fillna(0.0)
    )
    out["durable_surplus_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["surplus_boundary"].fillna(0.0)
        )
    )
    out["durable_surplus_state_lag1"] = out.groupby("ts_code", sort=False)["durable_surplus_state"].shift(1)
    out["durable_surplus_state_lag2"] = out.groupby("ts_code", sort=False)["durable_surplus_state"].shift(2)
    out["durable_sign_agreement"] = (
        _factorforge_np.sign(out["durable_surplus_state"].fillna(0.0))
        * (
            0.65 * _factorforge_np.sign(out["durable_surplus_state_lag1"].fillna(0.0))
            + 0.35 * _factorforge_np.sign(out["durable_surplus_state_lag2"].fillna(0.0))
        )
    )
    out["surplus_crossing_distance"] = (
        out["durable_surplus_state"].fillna(0.0)
        + 0.35 * out["durable_surplus_state_lag1"].fillna(0.0)
        + 0.15 * out["durable_surplus_state_lag2"].fillna(0.0)
    )
    out["near_boundary_penalty"] = _factorforge_positive(
        out["surplus_boundary"].fillna(0.0)
        - out["hysteretic_state"].abs().fillna(0.0)
    )
    out["durable_surplus_gate_margin"] = (
        0.42 * _factorforge_positive(out["durable_sign_agreement"]).fillna(0.0)
        + 0.30 * out["precision_gain"].fillna(0.0)
        + 0.20 * _factorforge_positive(out["state_persistence"]).fillna(0.0)
        - 0.26 * out["observation_noise"].fillna(0.0)
        - 0.20 * out["impact_pressure"].fillna(0.0)
        - 0.18 * out["near_boundary_penalty"].fillna(0.0)
        - 0.08
    )
    out["durable_surplus_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -out["durable_surplus_gate_margin"].clip(lower=-20.0, upper=20.0)
        )
    )
    out["factor_value"] = (
        out["surplus_crossing_distance"].fillna(0.0)
        * out["durable_surplus_gate"].fillna(0.0)
        * (1.0 + 0.08 * out["precision_gain"].fillna(0.0))
        - 0.08 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.06 * out["impact_pressure"].fillna(0.0)
        - 0.05 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _payer_ecology_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["small_size_score"] = _factorforge_positive(-out["size_prev_z"].fillna(0.0)).clip(0.0, 3.0)
    out["tradable_liquidity_score"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.35 * out["float_turnover_prev_z"].fillna(0.0)
                + 0.20 * out["relative_participation_z"].fillna(0.0)
                - 0.22 * out["observation_noise"].fillna(0.0)
                - 0.15 * out["impact_pressure"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["retail_hot_money_proxy"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * out["relative_participation_z"].fillna(0.0)
                + 0.30 * _factorforge_positive(out["concentration_z"]).fillna(0.0)
                + 0.18 * _factorforge_positive(out["turnover_prev_z"]).fillna(0.0)
                - 0.18 * out["prior_overheat"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["strategic_anchor_penalty"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.45 * out["size_prev_z"].fillna(0.0)
                - 0.20 * out["turnover_prev_z"].abs().fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["payer_ecology_score"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.70 * out["small_size_score"].fillna(0.0)
                + 0.35 * out["retail_hot_money_proxy"].fillna(0.0)
                + 0.25 * out["tradable_liquidity_score"].fillna(0.0)
                - 0.45 * out["strategic_anchor_penalty"].fillna(0.0)
                - 0.18 * out["observation_noise"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    out["payer_cost_boundary"] = (
        out["expected_cost_boundary"].fillna(0.0)
        + 0.12 * (1.0 - out["tradable_liquidity_score"].fillna(0.0))
        + 0.10 * out["impact_pressure"].fillna(0.0)
    )
    out["payer_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(
            out["hysteretic_state"].abs().fillna(0.0)
            - out["hold_boundary"].fillna(0.0)
            - 0.08 * out["payer_cost_boundary"].fillna(0.0)
        )
    )
    out["factor_value"] = (
        out["payer_excess_state"].fillna(0.0)
        * out["payer_ecology_score"].fillna(0.0)
        * (1.0 + 0.08 * out["precision_gain"].fillna(0.0))
        - 0.08 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.05 * out["impact_pressure"].fillna(0.0)
    )
    return out


def _hysteretic_default_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["factor_value"] = (
        out["hysteretic_excess_state"].fillna(0.0)
        * (0.74 + 0.18 * out["state_persistence"].fillna(0.0))
        * (1.0 + 0.14 * out["precision_gain"].fillna(0.0))
        - 0.16 * out["impact_pressure"].fillna(0.0)
        - 0.14 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.05 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _hysteretic_states(out):
    """Derive the shared posterior, cost boundary and hysteresis states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["posterior_tail_pressure_H_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(2)
    _y_centered = out["tail_pressure_z"].fillna(0.0) - out.groupby("trade_date", sort=False)[
        "tail_pressure_z"
    ].transform("mean").fillna(0.0)
    _x_size = out["size_prev_z"].fillna(0.0)
    _x_float_turnover = out["float_turnover_prev_z"].fillna(0.0)
    _x_volume_ratio = out["volume_ratio_prev_z"].fillna(0.0)
    _x_pct_chg = out["pct_chg_prev_z"].fillna(0.0)
    _ridge = 1.55
    _beta_size = (_y_centered * _x_size).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _beta_float_turnover = (
        (_y_centered * _x_float_turnover).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_volume_ratio = (
        (_y_centered * _x_volume_ratio).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_pct_chg = (_y_centered * _x_pct_chg).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _residual_fit = (
        _beta_size.fillna(0.0) * _x_size
        + _beta_float_turnover.fillna(0.0) * _x_float_turnover
        + _beta_volume_ratio.fillna(0.0) * _x_volume_ratio
        + _beta_pct_chg.fillna(0.0) * _x_pct_chg
    )
    out["tail_pressure_residual"] = _y_centered - _residual_fit
    out["tail_pressure_residual_z"] = _factorforge_z_by_day(out, "tail_pressure_residual")
    out["tail_pressure_residual_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(1)
    out["tail_pressure_residual_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(2)
    out["state_prior"] = (
        0.60 * out["tail_pressure_residual_z_lag1"].fillna(0.0)
        + 0.25 * out["tail_pressure_residual_z_lag2"].fillna(0.0)
        + 0.15 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
    )
    out["state_surprise"] = out["tail_pressure_residual_z"].fillna(0.0) - out["state_prior"].fillna(0.0)
    out["participation_info"] = _factorforge_np.log1p(
        out["relative_participation"].clip(lower=0.0, upper=20.0).fillna(0.0)
    )
    out["observation_noise"] = (
        0.72 * out["noise_z"].abs().fillna(0.0)
        + 0.22 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.16 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["impact_pressure"] = (
        0.42 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
        + 0.34 * out["observation_noise"].fillna(0.0)
        + 0.24 * out["prior_overheat"].fillna(0.0)
    )
    out["fisher_information"] = (
        (1.0 + _factorforge_positive(out["concentration_z"]).fillna(0.0))
        * out["participation_info"].fillna(0.0)
        / (0.95 + out["observation_noise"].fillna(0.0) ** 2)
    ).clip(lower=0.0, upper=12.0)
    out["precision_gain"] = _factorforge_np.log1p(out["fisher_information"].fillna(0.0))
    out["expected_cost_boundary"] = (
        0.32
        + 0.30 * out["impact_pressure"].fillna(0.0)
        + 0.24 * out["observation_noise"].fillna(0.0)
        + 0.16 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.12 * _factorforge_positive(out["right_tail_overpricing_penalty"]).fillna(0.0)
    )
    out["confirmed_surprise"] = (
        _factorforge_np.sign(out["state_surprise"].fillna(0.0))
        * _factorforge_positive(out["state_surprise"].abs().fillna(0.0) - out["expected_cost_boundary"].fillna(0.0))
    )
    out["update_gate_margin"] = (
        out["confirmed_surprise"].abs().fillna(0.0)
        + 0.34 * out["precision_gain"].fillna(0.0)
        - 0.22 * out["observation_noise"].fillna(0.0)
        - 0.10
    )
    out["update_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["update_gate_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["hysteretic_state"] = (
        out["state_prior"].fillna(0.0)
        + out["update_gate"].fillna(0.0) * out["confirmed_surprise"].fillna(0.0)
    )
    out["hysteretic_state_lag1"] = out.groupby("ts_code", sort=False)["hysteretic_state"].shift(1)
    out["state_persistence"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_np.sign(out["hysteretic_state_lag1"].fillna(0.0))
    )
    out["hold_boundary"] = (
        0.18
        + 0.18 * out["impact_pressure"].fillna(0.0)
        + 0.16 * out["observation_noise"].fillna(0.0)
        - 0.12 * out["precision_gain"].fillna(0.0)
    ).clip(lower=0.05)
    out["hysteretic_excess_state"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(out["hysteretic_state"].abs().fillna(0.0) - out["hold_boundary"].fillna(0.0))
    )
    return out


def _apply_hysteretic_family(out, _factorforge_direct_code_law_id):
    """Select a hysteretic variant without changing the state construction."""
    out = _hysteretic_states(out)
    if _factorforge_direct_code_law_id == "miller_flow_fisher_quality_cost_boundary_v9a":
        out = _quality_cost_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_v9a_leader_state_soft_cost_v1":
        out = _leader_state_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_distribution_moment_proxy_filter_v1":
        out = _moment_proxy_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_v7_information_v9a_soft_cost_v1":
        out = _information_soft_cost_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_v9a_profit_payer_soft_gate_v1":
        out = _payer_soft_gate_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_v9a_small_mid_liquidity_filter_v1":
        out = _small_mid_liquidity_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_v9a_hot_money_preposition_filter_v1":
        out = _hot_money_preposition_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_posterior_odds_convex_cost_v10a":
        out = _posterior_odds_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_durable_surplus_crossing_v10b":
        out = _durable_surplus_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_profit_payer_ecology_v9b_lite":
        out = _payer_ecology_factor(out)
    else:
        out = _hysteretic_default_factor(out)
    return out


def _sparse_posterior_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["expected_cost_load"] = (
        0.36 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        + 0.30 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.28 * out["noise_z"].abs().fillna(0.0)
        + 0.18 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["overheat_noise_load"] = (
        0.34 * out["prior_overheat"].fillna(0.0)
        + 0.24 * _factorforge_positive(out["pct_chg_prev_z"]).fillna(0.0)
        + 0.20 * out["noise_z"].abs().fillna(0.0)
    )
    out["posterior_after_cost_surplus"] = (
        out["tail_pressure_z"].fillna(0.0)
        - out["expected_cost_load"].fillna(0.0)
        - out["overheat_noise_load"].fillna(0.0)
        - 0.06 * out["size_prev_z"].abs().fillna(0.0)
    )
    out["posterior_after_cost_surplus_lag1"] = out.groupby("ts_code", sort=False)[
        "posterior_after_cost_surplus"
    ].shift(1)
    out["sparse_entry_margin"] = (
        out["posterior_after_cost_surplus"].fillna(0.0)
        + 0.25 * out["posterior_after_cost_surplus_lag1"].fillna(0.0)
        - 0.55
    )
    out["carry_state_margin"] = (
        out["posterior_after_cost_surplus"].fillna(0.0)
        + 0.45 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
        - 0.20
    )
    out["sparse_entry_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["sparse_entry_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["carry_state_decay"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["carry_state_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["sparse_posterior_gate"] = (
        0.72 * out["sparse_entry_gate"].fillna(0.0)
        + 0.28 * out["carry_state_decay"].fillna(0.0)
    ).clip(0.0, 1.0)
    out["factor_value"] = (
        out["posterior_after_cost_surplus"].fillna(0.0)
        * out["sparse_posterior_gate"].fillna(0.0)
        - 0.05 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _residual_posterior_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["cost_viability_margin"] = (
        out["tail_pressure_z"].abs().fillna(0.0)
        - 0.25
        - 0.35 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        - 0.25 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        - 0.24 * out["noise_z"].abs().fillna(0.0)
    )
    _y_centered = out["tail_pressure_z"].fillna(0.0) - out.groupby("trade_date", sort=False)[
        "tail_pressure_z"
    ].transform("mean").fillna(0.0)
    _x_size = out["size_prev_z"].fillna(0.0)
    _x_float_turnover = out["float_turnover_prev_z"].fillna(0.0)
    _x_volume_ratio = out["volume_ratio_prev_z"].fillna(0.0)
    _x_pct_chg = out["pct_chg_prev_z"].fillna(0.0)
    _ridge = 1.35
    _beta_size = (_y_centered * _x_size).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _beta_float_turnover = (
        (_y_centered * _x_float_turnover).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_volume_ratio = (
        (_y_centered * _x_volume_ratio).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_pct_chg = (_y_centered * _x_pct_chg).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _residual_fit = (
        _beta_size.fillna(0.0) * _x_size
        + _beta_float_turnover.fillna(0.0) * _x_float_turnover
        + _beta_volume_ratio.fillna(0.0) * _x_volume_ratio
        + _beta_pct_chg.fillna(0.0) * _x_pct_chg
    )
    out["tail_pressure_residual"] = _y_centered - _residual_fit
    out["tail_pressure_residual_z"] = _factorforge_z_by_day(out, "tail_pressure_residual")
    out["tail_pressure_residual_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(1)
    out["residual_state_smooth"] = (
        0.55 * out["tail_pressure_residual_z"].fillna(0.0)
        + 0.30 * out["tail_pressure_residual_z_lag1"].fillna(0.0)
        + 0.15 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
    )
    out["residual_confidence_margin"] = (
        out["residual_state_smooth"].fillna(0.0)
        + 0.22 * out["cost_viability_margin"].fillna(0.0)
        - 0.16 * out["prior_overheat"].fillna(0.0)
        - 0.12 * out["noise_z"].abs().fillna(0.0)
        - 0.18
    )
    out["residual_confidence_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["residual_confidence_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["residual_liquidity_penalty"] = (
        0.14 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.12 * out["noise_z"].abs().fillna(0.0)
        + 0.10 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
    )
    out["factor_value"] = (
        out["residual_state_smooth"].fillna(0.0) * out["residual_confidence_gate"].fillna(0.0)
        - 0.34 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - out["residual_liquidity_penalty"].fillna(0.0)
    )
    return out


def _fisher_innovation_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["posterior_tail_pressure_H_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(2)
    _y_centered = out["tail_pressure_z"].fillna(0.0) - out.groupby("trade_date", sort=False)[
        "tail_pressure_z"
    ].transform("mean").fillna(0.0)
    _x_size = out["size_prev_z"].fillna(0.0)
    _x_float_turnover = out["float_turnover_prev_z"].fillna(0.0)
    _x_volume_ratio = out["volume_ratio_prev_z"].fillna(0.0)
    _x_pct_chg = out["pct_chg_prev_z"].fillna(0.0)
    _ridge = 1.45
    _beta_size = (_y_centered * _x_size).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _beta_float_turnover = (
        (_y_centered * _x_float_turnover).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_volume_ratio = (
        (_y_centered * _x_volume_ratio).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_pct_chg = (_y_centered * _x_pct_chg).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _residual_fit = (
        _beta_size.fillna(0.0) * _x_size
        + _beta_float_turnover.fillna(0.0) * _x_float_turnover
        + _beta_volume_ratio.fillna(0.0) * _x_volume_ratio
        + _beta_pct_chg.fillna(0.0) * _x_pct_chg
    )
    out["tail_pressure_residual"] = _y_centered - _residual_fit
    out["tail_pressure_residual_z"] = _factorforge_z_by_day(out, "tail_pressure_residual")
    out["tail_pressure_residual_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(1)
    out["tail_pressure_residual_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(2)
    out["state_prior"] = (
        0.55 * out["tail_pressure_residual_z_lag1"].fillna(0.0)
        + 0.25 * out["tail_pressure_residual_z_lag2"].fillna(0.0)
        + 0.20 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
    )
    out["state_innovation"] = out["tail_pressure_residual_z"].fillna(0.0) - out["state_prior"].fillna(0.0)
    out["participation_info"] = _factorforge_np.log1p(
        out["relative_participation"].clip(lower=0.0, upper=20.0).fillna(0.0)
    )
    out["observation_noise"] = (
        0.70 * out["noise_z"].abs().fillna(0.0)
        + 0.20 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.14 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["impact_pressure"] = (
        0.45 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
        + 0.35 * out["observation_noise"].fillna(0.0)
        + 0.20 * out["prior_overheat"].fillna(0.0)
    )
    out["fisher_information"] = (
        (1.0 + _factorforge_positive(out["concentration_z"]).fillna(0.0))
        * out["participation_info"].fillna(0.0)
        / (0.85 + out["observation_noise"].fillna(0.0) ** 2)
    ).clip(lower=0.0, upper=12.0)
    out["precision_gain"] = _factorforge_np.log1p(out["fisher_information"].fillna(0.0))
    out["noise_ratio"] = (
        out["observation_noise"].fillna(0.0) + 0.30 * out["impact_pressure"].fillna(0.0)
    ) / (1.0 + out["fisher_information"].fillna(0.0))
    out["sign_persistence"] = (
        _factorforge_np.sign(out["state_innovation"].fillna(0.0))
        * (
            0.60 * _factorforge_np.sign(out["tail_pressure_residual_z_lag1"].fillna(0.0))
            + 0.40 * _factorforge_np.sign(out["tail_pressure_residual_z_lag2"].fillna(0.0))
        )
    )
    out["fisher_innovation_ratio"] = (
        out["state_innovation"].fillna(0.0)
        * out["fisher_information"].fillna(0.0)
        / (1.0 + out["fisher_information"].fillna(0.0))
        / _factorforge_np.sqrt(1.0 + out["observation_noise"].fillna(0.0) ** 2)
    )
    out["innovation_gate_margin"] = (
        0.62 * out["precision_gain"].fillna(0.0)
        + 0.22 * out["sign_persistence"].fillna(0.0)
        - 0.42 * out["noise_ratio"].fillna(0.0)
        - 0.18 * out["impact_pressure"].fillna(0.0)
        - 0.08
    )
    out["innovation_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["innovation_gate_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["factor_value"] = (
        out["fisher_innovation_ratio"].fillna(0.0) * out["innovation_gate"].fillna(0.0)
        - 0.22 * out["impact_pressure"].fillna(0.0)
        - 0.18 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.06 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _net_edge_decay_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["posterior_tail_pressure_H_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(2)
    _y_centered = out["tail_pressure_z"].fillna(0.0) - out.groupby("trade_date", sort=False)[
        "tail_pressure_z"
    ].transform("mean").fillna(0.0)
    _x_size = out["size_prev_z"].fillna(0.0)
    _x_float_turnover = out["float_turnover_prev_z"].fillna(0.0)
    _x_volume_ratio = out["volume_ratio_prev_z"].fillna(0.0)
    _x_pct_chg = out["pct_chg_prev_z"].fillna(0.0)
    _ridge = 1.65
    _beta_size = (_y_centered * _x_size).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _beta_float_turnover = (
        (_y_centered * _x_float_turnover).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_volume_ratio = (
        (_y_centered * _x_volume_ratio).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    )
    _beta_pct_chg = (_y_centered * _x_pct_chg).groupby(out["trade_date"], sort=False).transform("mean") / _ridge
    _residual_fit = (
        _beta_size.fillna(0.0) * _x_size
        + _beta_float_turnover.fillna(0.0) * _x_float_turnover
        + _beta_volume_ratio.fillna(0.0) * _x_volume_ratio
        + _beta_pct_chg.fillna(0.0) * _x_pct_chg
    )
    out["tail_pressure_residual"] = _y_centered - _residual_fit
    out["tail_pressure_residual_z"] = _factorforge_z_by_day(out, "tail_pressure_residual")
    out["tail_pressure_residual_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(1)
    out["tail_pressure_residual_z_lag2"] = out.groupby("ts_code", sort=False)["tail_pressure_residual_z"].shift(2)
    out["state_prior"] = (
        0.62 * out["tail_pressure_residual_z_lag1"].fillna(0.0)
        + 0.23 * out["tail_pressure_residual_z_lag2"].fillna(0.0)
        + 0.15 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
    )
    out["state_surprise"] = out["tail_pressure_residual_z"].fillna(0.0) - out["state_prior"].fillna(0.0)
    out["participation_info"] = _factorforge_np.log1p(
        out["relative_participation"].clip(lower=0.0, upper=20.0).fillna(0.0)
    )
    out["observation_noise"] = (
        0.74 * out["noise_z"].abs().fillna(0.0)
        + 0.24 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.18 * out["turnover_prev_z"].abs().fillna(0.0)
    )
    out["impact_pressure"] = (
        0.44 * _factorforge_positive(out["relative_participation_z"]).fillna(0.0)
        + 0.34 * out["observation_noise"].fillna(0.0)
        + 0.22 * out["prior_overheat"].fillna(0.0)
    )
    out["fisher_information"] = (
        (1.0 + _factorforge_positive(out["concentration_z"]).fillna(0.0))
        * out["participation_info"].fillna(0.0)
        / (1.05 + out["observation_noise"].fillna(0.0) ** 2)
    ).clip(lower=0.0, upper=12.0)
    out["precision_gain"] = _factorforge_np.log1p(out["fisher_information"].fillna(0.0))
    out["expected_cost_boundary"] = (
        0.34
        + 0.34 * out["impact_pressure"].fillna(0.0)
        + 0.24 * out["observation_noise"].fillna(0.0)
        + 0.18 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.14 * _factorforge_positive(out["right_tail_overpricing_penalty"]).fillna(0.0)
    )
    out["confirmed_surprise"] = (
        _factorforge_np.sign(out["state_surprise"].fillna(0.0))
        * _factorforge_positive(out["state_surprise"].abs().fillna(0.0) - out["expected_cost_boundary"].fillna(0.0))
    )
    out["update_gate_margin"] = (
        out["confirmed_surprise"].abs().fillna(0.0)
        + 0.36 * out["precision_gain"].fillna(0.0)
        - 0.24 * out["observation_noise"].fillna(0.0)
        - 0.12
    )
    out["update_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["update_gate_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["hysteretic_state"] = (
        out["state_prior"].fillna(0.0)
        + out["update_gate"].fillna(0.0) * out["confirmed_surprise"].fillna(0.0)
    )
    out["hysteretic_state_lag1"] = out.groupby("ts_code", sort=False)["hysteretic_state"].shift(1)
    out["hysteretic_state_lag2"] = out.groupby("ts_code", sort=False)["hysteretic_state"].shift(2)
    out["state_persistence"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_np.sign(out["hysteretic_state_lag1"].fillna(0.0))
    )
    out["recent_confirmation"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * (
            0.55 * _factorforge_np.sign(out["hysteretic_state_lag1"].fillna(0.0))
            + 0.30 * _factorforge_np.sign(out["hysteretic_state_lag2"].fillna(0.0))
            + 0.15 * _factorforge_np.sign(out["confirmed_surprise"].fillna(0.0))
        )
    )
    out["recent_confirmation_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp((-1.20 * out["recent_confirmation"].fillna(0.0)).clip(lower=-20.0, upper=20.0))
    )
    out["stale_state_penalty"] = (
        _factorforge_positive(out["hysteretic_state_lag1"].abs().fillna(0.0) - out["confirmed_surprise"].abs().fillna(0.0))
        * (1.0 - out["recent_confirmation_gate"].fillna(0.0))
        + 0.10 * out["observation_noise"].fillna(0.0)
        + 0.08 * out["impact_pressure"].fillna(0.0)
    )
    out["state_quality_margin"] = (
        0.48 * out["precision_gain"].fillna(0.0)
        + 0.30 * out["state_persistence"].fillna(0.0)
        + 0.26 * out["recent_confirmation"].fillna(0.0)
        - 0.24 * out["observation_noise"].fillna(0.0)
        - 0.20 * out["impact_pressure"].fillna(0.0)
        - 0.10 * out["stale_state_penalty"].fillna(0.0)
        - 0.06
    )
    out["state_quality"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["state_quality_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["net_edge_load"] = (
        out["hysteretic_state"].abs().fillna(0.0) * out["state_quality"].fillna(0.0)
        - out["expected_cost_boundary"].fillna(0.0)
        - out["stale_state_penalty"].fillna(0.0)
    )
    out["no_trade_band"] = (
        0.10
        + 0.12 * out["impact_pressure"].fillna(0.0)
        + 0.10 * out["observation_noise"].fillna(0.0)
        - 0.08 * out["precision_gain"].fillna(0.0)
    ).clip(lower=0.04)
    out["factor_value"] = (
        _factorforge_np.sign(out["hysteretic_state"].fillna(0.0))
        * _factorforge_positive(out["net_edge_load"].fillna(0.0) - out["no_trade_band"].fillna(0.0))
        * (1.0 + 0.10 * out["precision_gain"].fillna(0.0))
        - 0.10 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - 0.06 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _posterior_hold_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["posterior_tail_pressure_H_z_lag1"] = out.groupby("ts_code", sort=False)["tail_pressure_z"].shift(1)
    out["cost_viability_margin"] = (
        out["tail_pressure_z"].abs().fillna(0.0)
        - 0.25
        - 0.35 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        - 0.25 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        - 0.24 * out["noise_z"].abs().fillna(0.0)
    )
    out["cost_viability_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["cost_viability_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["entry_boundary_margin"] = (
        out["tail_pressure_z"].fillna(0.0)
        + 0.45 * out["cost_viability_margin"].fillna(0.0)
        - 0.35
        - 0.18 * out["prior_overheat"].fillna(0.0)
    )
    out["continuation_boundary_margin"] = (
        out["tail_pressure_z"].fillna(0.0)
        + 0.30 * out["posterior_tail_pressure_H_z_lag1"].fillna(0.0)
        + 0.30 * out["cost_viability_margin"].fillna(0.0)
        - 0.10
        - 0.14 * out["prior_overheat"].fillna(0.0)
    )
    out["entry_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["entry_boundary_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["continuation_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["continuation_boundary_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["posterior_hold_gate"] = (0.65 * out["entry_gate"].fillna(0.0) + 0.35 * out["continuation_gate"].fillna(0.0)).clip(0.0, 1.0)
    out["liquidity_noise_penalty"] = (
        0.26 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.22 * out["noise_z"].abs().fillna(0.0)
        + 0.18 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
    )
    out["factor_value"] = (
        out["tail_pressure_z"].fillna(0.0) * out["posterior_hold_gate"].fillna(0.0)
        - 0.50 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - out["liquidity_noise_penalty"].fillna(0.0)
        - 0.08 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _ewma_cost_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["cost_viability_margin"] = (
        out["tail_pressure_z"].abs().fillna(0.0)
        - 0.15
        - 0.25 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        - 0.20 * out["noise_z"].abs().fillna(0.0)
    )
    out["cost_viability_gate"] = 1.0 / (
        1.0 + _factorforge_np.exp(-out["cost_viability_margin"].clip(lower=-20.0, upper=20.0))
    )
    out["liquidity_noise_penalty"] = (
        0.20 * out["turnover_prev_z"].abs().fillna(0.0)
        + 0.16 * out["noise_z"].abs().fillna(0.0)
    )
    out["factor_value"] = (
        out["tail_pressure_z"].fillna(0.0) * out["cost_viability_gate"].fillna(0.0)
        - 0.42 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - out["liquidity_noise_penalty"].fillna(0.0)
        - 0.06 * out["size_prev_z"].abs().fillna(0.0)
    )
    return out


def _pressure_default_factor(out):
    """Evaluate one historical pressure law on prepared states."""
    out["liquidity_noise_penalty"] = 0.18 * out["turnover_prev_z"].abs().fillna(0.0) + 0.12 * out["noise_z"].abs().fillna(0.0)
    out["factor_value"] = (
        out["tail_pressure_z"].fillna(0.0)
        - 0.35 * out["right_tail_overpricing_penalty"].fillna(0.0)
        - out["liquidity_noise_penalty"].fillna(0.0)
        - out["size_residual_penalty"].fillna(0.0)
    )
    return out


def _apply_pressure_law(out, _factorforge_direct_code_law_id):
    """Dispatch existing pressure laws, retaining the original default."""
    if _factorforge_direct_code_law_id == "miller_flow_sparse_posterior_cost_boundary_v4":
        out = _sparse_posterior_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_residualized_posterior_hold_gate_v5":
        out = _residual_posterior_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_fisher_innovation_ratio_v1":
        out = _fisher_innovation_factor(out)
    elif _factorforge_direct_code_law_id in {
        "miller_flow_fisher_hysteretic_expected_cost_boundary_v1",
        "miller_flow_fisher_quality_cost_boundary_v9a",
        "miller_flow_profit_payer_ecology_v9b_lite",
        "miller_flow_posterior_odds_convex_cost_v10a",
        "miller_flow_durable_surplus_crossing_v10b",
            "miller_flow_v9a_leader_state_soft_cost_v1",
            "miller_flow_distribution_moment_proxy_filter_v1",
            "miller_flow_v7_information_v9a_soft_cost_v1",
            "miller_flow_v9a_profit_payer_soft_gate_v1",
            "miller_flow_v9a_small_mid_liquidity_filter_v1",
            "miller_flow_v9a_hot_money_preposition_filter_v1",
            "miller_flow_v11_distribution_shape_fixed_small_v1",
            "miller_flow_v11_repair_absorption_full_v1",
            "miller_flow_v11_repair_absorption_mid_core_v1",
            "miller_flow_v11_first_passage_lite_v1",
            "miller_flow_v12_midcore_first_passage_separator_v1",
            "miller_flow_v13_full_first_passage_separator_v1",
            "miller_flow_v14_absorption_momentum_first_passage_v1",
                    "miller_flow_v15_repair_confirmed_absorption_fp_v1",
                    "miller_flow_v16_positive_repair_core_fp_v1",
                    "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
                    "miller_flow_v18a_absolute_long_edge_gate_v1",
                    "miller_flow_v18b_first_passage_repair_edge_v1",
                    "miller_flow_v18c_crowding_filtered_repair_v1",
                }:
        out = _apply_hysteretic_family(out, _factorforge_direct_code_law_id)
    elif _factorforge_direct_code_law_id == "miller_flow_fisher_net_edge_state_decay_v1":
        out = _net_edge_decay_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_posterior_hold_gate_v3":
        out = _posterior_hold_factor(out)
    elif _factorforge_direct_code_law_id == "miller_flow_ewma_cost_gate_v2":
        out = _ewma_cost_factor(out)
    else:
        out = _pressure_default_factor(out)
    return out


def _pressure_states(daily, agg, _factorforge_direct_code_law_id):
    """Build lagged pressure, daily controls and prior-window participation states."""
    agg["flow_ratio_state"] = agg["signed_pressure_sum"] / agg["gross_pressure_sum"]
    agg["participation_concentration"] = agg["pressure_sq_sum"] / (agg["gross_pressure_sum"] * agg["gross_pressure_sum"])
    agg["concentration_confidence"] = _factorforge_np.log1p(
        _factorforge_np.maximum(agg["participation_concentration"] * agg["minute_count"] - 1.0, 0.0)
    )
    agg["noise_load"] = agg["intraday_ret_noise"].fillna(0.0) + (
        agg["absolute_move_sum"] / agg["minute_count"].replace(0, _factorforge_np.nan)
    )
    agg["flow_state_z"] = _factorforge_z_by_day(agg, "flow_ratio_state")
    agg["concentration_z"] = _factorforge_z_by_day(agg, "concentration_confidence")
    agg["noise_z"] = _factorforge_z_by_day(agg, "noise_load")
    agg["tail_precision_state"] = 0.60 * agg["concentration_z"].fillna(0.0) - 0.35 * agg["noise_z"].fillna(0.0)
    agg["miller_tail_pressure"] = agg["flow_state_z"].fillna(0.0) * (
        1.0 + 0.25 * agg["tail_precision_state"].fillna(0.0)
    )
    agg = agg.sort_values(["ts_code", "trade_date"])
    for _lag in (1, 2, 3):
        agg[f"miller_tail_pressure_lag{_lag}"] = agg.groupby("ts_code", sort=False)["miller_tail_pressure"].shift(_lag)
    if _factorforge_direct_code_law_id in {
        "miller_flow_posterior_hold_gate_v3",
        "miller_flow_sparse_posterior_cost_boundary_v4",
        "miller_flow_residualized_posterior_hold_gate_v5",
        "miller_flow_fisher_innovation_ratio_v1",
        "miller_flow_fisher_hysteretic_expected_cost_boundary_v1",
        "miller_flow_fisher_net_edge_state_decay_v1",
        "miller_flow_fisher_quality_cost_boundary_v9a",
        "miller_flow_profit_payer_ecology_v9b_lite",
        "miller_flow_posterior_odds_convex_cost_v10a",
            "miller_flow_durable_surplus_crossing_v10b",
            "miller_flow_v9a_leader_state_soft_cost_v1",
            "miller_flow_distribution_moment_proxy_filter_v1",
            "miller_flow_v7_information_v9a_soft_cost_v1",
            "miller_flow_v9a_profit_payer_soft_gate_v1",
            "miller_flow_v9a_small_mid_liquidity_filter_v1",
            "miller_flow_v9a_hot_money_preposition_filter_v1",
            "miller_flow_v11_distribution_shape_fixed_small_v1",
            "miller_flow_v11_repair_absorption_full_v1",
            "miller_flow_v11_repair_absorption_mid_core_v1",
            "miller_flow_v11_first_passage_lite_v1",
            "miller_flow_v12_midcore_first_passage_separator_v1",
            "miller_flow_v13_full_first_passage_separator_v1",
            "miller_flow_v14_absorption_momentum_first_passage_v1",
            "miller_flow_v15_repair_confirmed_absorption_fp_v1",
            "miller_flow_v16_positive_repair_core_fp_v1",
            "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
            "miller_flow_v18a_absolute_long_edge_gate_v1",
            "miller_flow_v18b_first_passage_repair_edge_v1",
            "miller_flow_v18c_crowding_filtered_repair_v1",
        }:
        agg["persistent_tail_pressure"] = (
            0.45 * agg["miller_tail_pressure"].fillna(0.0)
            + 0.30 * agg["miller_tail_pressure_lag1"].fillna(0.0)
            + 0.15 * agg["miller_tail_pressure_lag2"].fillna(0.0)
            + 0.10 * agg["miller_tail_pressure_lag3"].fillna(0.0)
        )
        agg["posterior_tail_pressure_H"] = (
            agg.groupby("ts_code", sort=False)["persistent_tail_pressure"]
            .transform(lambda _s: _s.ewm(alpha=0.20, adjust=False, min_periods=1).mean())
        )
        agg["posterior_tail_pressure_H_lag1"] = agg.groupby("ts_code", sort=False)["posterior_tail_pressure_H"].shift(1)
        agg["persistent_tail_pressure"] = agg["posterior_tail_pressure_H"]
    elif _factorforge_direct_code_law_id == "miller_flow_ewma_cost_gate_v2":
        agg["persistent_tail_pressure"] = (
            0.45 * agg["miller_tail_pressure"].fillna(0.0)
            + 0.30 * agg["miller_tail_pressure_lag1"].fillna(0.0)
            + 0.15 * agg["miller_tail_pressure_lag2"].fillna(0.0)
            + 0.10 * agg["miller_tail_pressure_lag3"].fillna(0.0)
        )
    else:
        agg["persistent_tail_pressure"] = (
            0.70 * agg["miller_tail_pressure"].fillna(0.0)
            + 0.30 * agg["miller_tail_pressure_lag1"].fillna(0.0)
        )

    control_cols = ["total_mv", "turnover_rate", "turnover_rate_f", "volume_ratio", "pct_chg"]
    keep = ["ts_code", "trade_date"] + [col for col in control_cols if col in daily.columns]
    controls = daily[keep].copy().sort_values(["ts_code", "trade_date"])
    for col in control_cols:
        if col not in controls.columns:
            controls[col] = _factorforge_np.nan
        controls[col] = _factorforge_pd.to_numeric(controls[col], errors="coerce")
        controls[col + "_prev"] = controls.groupby("ts_code", sort=False)[col].shift(1)
    controls = controls[["ts_code", "trade_date"] + [col + "_prev" for col in control_cols]]
    out = agg.merge(controls, on=["ts_code", "trade_date"], how="left")
    out["ln_total_mv_prev"] = _factorforge_np.log(out["total_mv_prev"].where(out["total_mv_prev"] > 0))
    z_inputs = {
        "size_prev_z": "ln_total_mv_prev",
        "turnover_prev_z": "turnover_rate_prev",
        "float_turnover_prev_z": "turnover_rate_f_prev",
        "volume_ratio_prev_z": "volume_ratio_prev",
        "pct_chg_prev_z": "pct_chg_prev",
    }
    for z_col, raw_col in z_inputs.items():
        out[z_col] = _factorforge_z_by_day(out, raw_col)
    out["tail_pressure_z"] = _factorforge_z_by_day(out, "persistent_tail_pressure")
    if "gross_pressure_baseline20" not in out.columns:
        out["gross_pressure_baseline20"] = (
            out.groupby("ts_code", sort=False)["gross_pressure_sum"]
            .transform(lambda _s: _s.shift(1).rolling(20, min_periods=5).mean())
        )
    out["relative_participation"] = (
        out["gross_pressure_sum"]
        / out["gross_pressure_baseline20"].replace(0, _factorforge_np.nan)
    ).replace([_factorforge_np.inf, -_factorforge_np.inf], _factorforge_np.nan)
    out["relative_participation_z"] = _factorforge_z_by_day(out, "relative_participation")
    out["prior_overheat"] = (
        _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.75 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        + 0.50 * _factorforge_positive(out["pct_chg_prev_z"]).fillna(0.0)
    )
    out["right_tail_overpricing_penalty"] = _factorforge_positive(out["tail_pressure_z"]).fillna(0.0) * out["prior_overheat"].fillna(0.0)
    out["size_residual_penalty"] = 0.08 * out["size_prev_z"].abs().fillna(0.0)
    return out


def _compute_pressure_factor(daily, agg, _factorforge_direct_code_law_id):
    """Normalize legacy aliases and return sorted finite pressure-factor values."""
    alias_pairs = {
        "signed_pressure_sum": "signed_amt_sum",
        "gross_pressure_sum": "gross_amt",
        "pressure_sq_sum": "amt_sq_sum",
        "absolute_move_sum": "abs_ret_sum",
        "intraday_ret_noise": "ret_std",
    }
    for _dst_col, _alias in alias_pairs.items():
        if _dst_col not in agg.columns and _alias in agg.columns:
            agg[_dst_col] = agg[_alias]
    required = [
        "ts_code",
        "trade_date",
        "signed_pressure_sum",
        "gross_pressure_sum",
        "pressure_sq_sum",
        "absolute_move_sum",
        "intraday_ret_noise",
        "minute_count",
    ]
    missing = [col for col in required if col not in agg.columns]
    if missing:
        raise ValueError(f"minute_derived_flow_state_v1 missing required columns: {missing}")
    for col in required:
        if col not in {"ts_code", "trade_date"}:
            agg[col] = _factorforge_pd.to_numeric(agg[col], errors="coerce")
    agg = agg.dropna(subset=["ts_code", "trade_date", "signed_pressure_sum", "gross_pressure_sum"])
    agg = agg[agg["gross_pressure_sum"] > 0].copy()
    if len(agg) == 0:
        return _factorforge_pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])

    out = _pressure_states(daily, agg, _factorforge_direct_code_law_id)
    out = _apply_pressure_law(out, _factorforge_direct_code_law_id)
    out = out.replace([_factorforge_np.inf, -_factorforge_np.inf], _factorforge_np.nan).dropna(subset=["factor_value"])
    return out[["ts_code", "trade_date", "factor_value"]].sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
