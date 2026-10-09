"""Moment-state and absorption-cutoff calculations for existing Miller laws."""

import numpy as _factorforge_np
import pandas as _factorforge_pd
from .derived_state_common import _factorforge_z_by_day, _factorforge_positive


def _positive_repair_core(_current):
    """Apply the frozen law to a private working frame."""
    _current["v16_positive_repair_core"] = (
        _factorforge_positive(_current["v15_repair_confirmation_z"]).fillna(0.0)
        * (0.40 + 0.34 * _current["v15_repair_gate"].fillna(0.0))
        + 0.24 * _factorforge_positive(_current["v14_absorption_momentum_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(_current["ret_tail_asymmetry_z"]).fillna(0.0)
    )
    _current["v16_buyable_supply_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.44 * _current["v16_positive_repair_core"].fillna(0.0)
                + 0.30 * _current["v15_confirmed_absorption_state"].fillna(0.0)
                + 0.20 * _current["discount_repair_state"].fillna(0.0)
                - 0.42 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.28 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.12 * _current["prior_overheat"].fillna(0.0)
                - 0.10
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v16_distress_without_repair"] = (
        _factorforge_positive(
            _current["absorption_state"].fillna(0.0)
            - _current["v15_confirmed_absorption_state"].fillna(0.0)
        ).fillna(0.0)
        + 0.26 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(-_current["v14_absorption_momentum_z"]).fillna(0.0)
    )
    _current["raw_v11_repair_absorption_signal"] = (
        0.40 * _current["v16_positive_repair_core"].fillna(0.0)
        +
        _current["v16_buyable_supply_gate"].fillna(0.0)
        * (
            0.30
            + 0.46 * _current["v16_positive_repair_core"].fillna(0.0)
            + 0.18 * _current["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
        )
        - _current["v14_breakdown_probability_proxy"].fillna(0.0)
        * (0.56 + 0.22 * _current["v14_downside_distance_proxy"].fillna(0.0))
        - 0.24 * _current["v16_distress_without_repair"].fillna(0.0)
        - 0.12 * _factorforge_positive(0.25 - _current["v16_positive_repair_core"].fillna(0.0))
        - 0.10 * _current["crowded_chasing_state"].fillna(0.0)
        - 0.06 * _current["prior_overheat"].fillna(0.0)
    )
    return _current


def _benchmark_relative_repair(_current):
    """Apply the frozen law to a private working frame."""
    _current["v17_conditional_momentum_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.38 * _current["v15_confirmed_absorption_state"].fillna(0.0)
                + 0.30 * _current["v15_repair_gate"].fillna(0.0)
                + 0.18 * _factorforge_positive(
                    _current["v15_repair_confirmation_z"]
                ).fillna(0.0)
                - 0.34 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.30 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.06
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v17_conditional_repair_momentum"] = (
        _factorforge_positive(_current["v14_absorption_momentum_z"]).fillna(0.0)
        * _current["v17_conditional_momentum_gate"].fillna(0.0)
    )
    _v17_edge_centered = _current["raw_v11_repair_absorption_signal"].fillna(0.0) - _current.groupby(
        "trade_date",
        sort=False,
    )["raw_v11_repair_absorption_signal"].transform("mean").fillna(0.0)
    _v17_ridge = 1.85
    _v17_fit = 0.0
    for _v17_col in (
        "size_prev_z",
        "float_turnover_prev_z",
        "volume_ratio_prev_z",
        "pct_chg_prev_z",
    ):
        _v17_x = _current[_v17_col].fillna(0.0)
        _v17_beta = (
            (_v17_edge_centered * _v17_x)
            .groupby(_current["trade_date"], sort=False)
            .transform("mean")
            / _v17_ridge
        )
        _v17_fit = _v17_fit + _v17_beta.fillna(0.0) * _v17_x
    _current["v17_benchmark_relative_edge"] = _v17_edge_centered - _v17_fit
    _current["v17_benchmark_relative_edge_z"] = _factorforge_z_by_day(
        _current,
        "v17_benchmark_relative_edge",
    )
    _current["v17_microcap_drag"] = (
        _factorforge_positive((0.12 - _current["cap_rank_pct_prev"].fillna(0.50)) / 0.12)
        .fillna(0.0)
        .clip(0.0, 2.5)
        + 0.35
        * _factorforge_positive(-2.0 - _current["size_prev_z"].fillna(0.0))
        .fillna(0.0)
        .clip(0.0, 2.5)
    )
    _current["v17_illiquidity_drag"] = (
        0.42 * _factorforge_positive(-_current["float_turnover_prev_z"]).fillna(0.0)
        + 0.24 * _factorforge_positive(-_current["volume_ratio_prev_z"]).fillna(0.0)
        + 0.18 * _current["bad_selling_noise_state"].fillna(0.0)
    )
    _current["raw_v11_repair_absorption_signal"] = (
        0.58 * _current["v17_benchmark_relative_edge_z"].fillna(0.0)
        + 0.24 * _current["v17_conditional_repair_momentum"].fillna(0.0)
        + 0.14 * _current["v15_confirmed_absorption_state"].fillna(0.0).clip(0.0, 4.0)
        - 0.22 * _current["v17_microcap_drag"].fillna(0.0)
        - 0.18 * _current["v17_illiquidity_drag"].fillna(0.0)
        - 0.12 * _current["v15_unconfirmed_distress_penalty"].fillna(0.0)
        - 0.10 * _current["crowded_chasing_state"].fillna(0.0)
        - 0.08 * _current["prior_overheat"].fillna(0.0)
    )
    return _current


def _absolute_edge_states(_current):
    """Apply the frozen law to a private working frame."""
    _current["v18_positive_repair_core"] = (
        _factorforge_positive(_current["v15_repair_confirmation_z"]).fillna(0.0)
        * (0.42 + 0.36 * _current["v15_repair_gate"].fillna(0.0))
        + 0.26 * _factorforge_positive(_current["v14_absorption_momentum_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(_current["ret_tail_asymmetry_z"]).fillna(0.0)
        + 0.12 * _current["v15_confirmed_absorption_state"].fillna(0.0).clip(0.0, 4.0)
    )
    _current["v18_crowding_overheat"] = (
        0.34 * _current["crowded_chasing_state"].fillna(0.0)
        + 0.28 * _current["prior_overheat"].fillna(0.0)
        + 0.22 * _factorforge_positive(_current["ret_excess_kurtosis_z"]).fillna(0.0)
        + 0.16 * _factorforge_positive(_current["bad_selling_noise_state"]).fillna(0.0)
    )
    _current["v18_tradable_mid_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.36
                + 0.24 * _current["float_turnover_prev_z"].fillna(0.0)
                + 0.18 * _current["volume_ratio_prev_z"].fillna(0.0)
                - 0.42 * _factorforge_positive(0.10 - _current["cap_rank_pct_prev"].fillna(0.50)).fillna(0.0)
                - 0.30 * _factorforge_positive(_current["cap_rank_pct_prev"].fillna(0.50) - 0.85).fillna(0.0)
                - 0.20 * _factorforge_positive(-_current["float_turnover_prev_z"].fillna(0.0)).fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v18_market_drift_support"] = (
        0.22 * _current["pct_chg_prev_z"].fillna(0.0)
        + 0.18 * _factorforge_positive(_current["volume_ratio_prev_z"]).fillna(0.0)
        - 0.18 * _factorforge_positive(-_current["pct_chg_prev_z"].fillna(0.0)).fillna(0.0)
    )
    _current["v18_absolute_long_margin"] = (
        _current["raw_v11_repair_absorption_signal"].fillna(0.0)
        + 0.34 * _current["v18_positive_repair_core"].fillna(0.0)
        + 0.16 * _current["v18_market_drift_support"].fillna(0.0)
        - 0.30 * _current["v18_crowding_overheat"].fillna(0.0)
        - 0.18 * _current["v15_unconfirmed_distress_penalty"].fillna(0.0)
    )
    _current["v18_absolute_long_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.72 * _current["v18_absolute_long_margin"].fillna(0.0)
                + 0.30 * _current["v18_tradable_mid_gate"].fillna(0.0)
                - 0.22
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    return _current


def _absolute_long_edge(_current):
    """Apply the frozen law to a private working frame."""
    _current["raw_v11_repair_absorption_signal"] = (
        _current["v18_absolute_long_margin"].fillna(0.0)
        * _current["v18_absolute_long_gate"].fillna(0.0)
        * (0.70 + 0.36 * _current["v18_tradable_mid_gate"].fillna(0.0))
        - 0.18 * _factorforge_positive(0.50 - _current["v18_absolute_long_gate"].fillna(0.0))
        - 0.08 * _current["v18_crowding_overheat"].fillna(0.0)
    )
    return _current


def _repair_first_passage_edge(_current):
    """Apply the frozen law to a private working frame."""
    _current["v18_up_hit_probability"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.58 * _current["v18_positive_repair_core"].fillna(0.0)
                + 0.36 * _current["v15_confirmed_absorption_state"].fillna(0.0)
                + 0.22 * _current["v14_absorption_momentum_z"].fillna(0.0)
                - 0.34 * _current["v18_crowding_overheat"].fillna(0.0)
                - 0.16
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v18_down_hit_probability"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.52 * _current["bad_selling_noise_state"].fillna(0.0)
                + 0.32 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0)
                + 0.24 * _current["fragile_tail_penalty"].fillna(0.0)
                + 0.20 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.30 * _current["v15_confirmed_absorption_state"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v18_upside_distance"] = (
        0.34 * _current["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.30 * _current["v18_positive_repair_core"].fillna(0.0).clip(0.0, 5.0)
        + 0.18 * _factorforge_positive(-_current["ret_excess_kurtosis_z"]).fillna(0.0).clip(0.0, 3.0)
    )
    _current["v18_downside_distance"] = (
        0.36 * _current["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.24 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0).clip(0.0, 3.0)
        + 0.22 * _current["v18_crowding_overheat"].fillna(0.0).clip(0.0, 5.0)
    )
    _current["raw_v11_repair_absorption_signal"] = (
        _current["v18_up_hit_probability"].fillna(0.0)
        * (0.54 + 0.30 * _current["v18_upside_distance"].fillna(0.0))
        - _current["v18_down_hit_probability"].fillna(0.0)
        * (0.56 + 0.26 * _current["v18_downside_distance"].fillna(0.0))
        - 0.10 * _current["v15_unconfirmed_distress_penalty"].fillna(0.0)
        - 0.08 * _current["prior_overheat"].fillna(0.0)
    ) * _current["v18_tradable_mid_gate"].fillna(0.0)
    return _current


def _crowding_filtered_repair(_current):
    """Apply the frozen law to a private working frame."""
    _current["v18_smart_repair_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.50 * _current["v18_positive_repair_core"].fillna(0.0)
                + 0.24 * _current["v15_repair_gate"].fillna(0.0)
                + 0.18 * _factorforge_positive(_current["amount_hhi_z"]).fillna(0.0)
                - 0.44 * _current["v18_crowding_overheat"].fillna(0.0)
                - 0.20 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.08
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["raw_v11_repair_absorption_signal"] = (
        _current["v18_positive_repair_core"].fillna(0.0)
        * _current["v18_smart_repair_gate"].fillna(0.0)
        * (0.68 + 0.24 * _current["v18_tradable_mid_gate"].fillna(0.0))
        - 0.22 * _current["v18_crowding_overheat"].fillna(0.0)
        - 0.14 * _current["v15_unconfirmed_distress_penalty"].fillna(0.0)
    )
    return _current


def _confirmed_repair_states(_current):
    """Derive confirmation and hitting proxies before variant selection."""
    _current["v15_repair_confirmation_raw"] = (
        0.38
        * (
            _current["ret_tail_asymmetry_z"].fillna(0.0)
            - _current["v15_prior_ret_tail_asymmetry_z"].fillna(0.0)
        )
        + 0.24
        * (
            _current["signed_flow_imbalance_z"].fillna(0.0)
            - _current["v15_prior_signed_flow_imbalance_z"].fillna(0.0)
        )
        + 0.20
        * (
            _current["signed_flow_tail_asymmetry_z"].fillna(0.0)
            - _current["v15_prior_signed_flow_tail_asymmetry_z"].fillna(0.0)
        )
        - 0.20
        * _factorforge_positive(
            _current["ret_excess_kurtosis_z"].fillna(0.0)
            - _current["v15_prior_ret_excess_kurtosis_z"].fillna(0.0)
        ).fillna(0.0)
        - 0.18
        * _factorforge_positive(
            _current["bad_selling_noise_state"].fillna(0.0)
            - _current["v15_prior_bad_selling_noise_state"].fillna(0.0)
        ).fillna(0.0)
    )
    _current["v15_repair_confirmation_z"] = _factorforge_z_by_day(
        _current,
        "v15_repair_confirmation_raw",
    )
    _current["v15_repair_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.52 * _current["v15_repair_confirmation_z"].fillna(0.0)
                + 0.28 * _current["v14_absorption_momentum_z"].fillna(0.0)
                + 0.18 * _current["absorption_state"].fillna(0.0)
                - 0.30 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.18 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.04
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v15_confirmed_absorption_state"] = (
        _current["absorption_state"].fillna(0.0)
        * (0.35 + 0.65 * _current["v15_repair_gate"].fillna(0.0))
    )
    _current["v15_unconfirmed_distress_penalty"] = (
        _factorforge_positive(_current["absorption_state"].fillna(0.0) - 1.35).fillna(0.0)
        * (1.0 - _current["v15_repair_gate"].fillna(0.0))
        + 0.18 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0)
    )
    _current["v14_absorption_probability_proxy"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.40 * _current["v14_latent_absorption_state"].fillna(0.0)
                + 0.30 * _current["v14_absorption_momentum_z"].fillna(0.0)
                + 0.44 * _current["v15_repair_gate"].fillna(0.0)
                + 0.24 * _current["v15_confirmed_absorption_state"].fillna(0.0)
                - 0.38 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.24 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.08
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v14_breakdown_probability_proxy"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.54 * _current["bad_selling_noise_state"].fillna(0.0)
                + 0.28 * _current["fragile_tail_penalty"].fillna(0.0)
                + 0.22 * _current["crowded_chasing_state"].fillna(0.0)
                + 0.28 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0)
                + 0.16 * _factorforge_positive(-_current["v14_absorption_momentum_z"]).fillna(0.0)
                - 0.28 * _current["v15_confirmed_absorption_state"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v14_upside_distance_proxy"] = (
        0.36 * _current["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.30 * _current["v15_confirmed_absorption_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.26 * _factorforge_positive(_current["v15_repair_confirmation_z"]).fillna(0.0).clip(0.0, 3.0)
        + 0.14 * _factorforge_positive(_current["v14_absorption_momentum_z"]).fillna(0.0).clip(0.0, 3.0)
    )
    _current["v14_downside_distance_proxy"] = (
        0.40 * _current["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.28 * _factorforge_positive(-_current["v15_repair_confirmation_z"]).fillna(0.0).clip(0.0, 3.0)
        + 0.22 * _current["crowded_chasing_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.16 * _factorforge_positive(-_current["v14_absorption_momentum_z"]).fillna(0.0).clip(0.0, 3.0)
    )
    _current["raw_v11_repair_absorption_signal"] = (
        _current["v14_absorption_probability_proxy"].fillna(0.0)
        * (0.62 + 0.28 * _current["v14_upside_distance_proxy"].fillna(0.0))
        - _current["v14_breakdown_probability_proxy"].fillna(0.0)
        * (0.58 + 0.24 * _current["v14_downside_distance_proxy"].fillna(0.0))
        - 0.16 * _current["v15_unconfirmed_distress_penalty"].fillna(0.0)
        - 0.08 * _current["crowded_chasing_state"].fillna(0.0)
        - 0.05 * _current["prior_overheat"].fillna(0.0)
    )
    return _current


def _compute_confirmed_repair(_current, _factorforge_direct_code_law_id):
    """Select the repair-confirmed variant; preserve its missing values."""
    _current = _confirmed_repair_states(_current)
    if _factorforge_direct_code_law_id == "miller_flow_v16_positive_repair_core_fp_v1":
        _current = _positive_repair_core(_current)
    if _factorforge_direct_code_law_id == "miller_flow_v17_benchmark_relative_repaired_absorption_v1":
        _current = _benchmark_relative_repair(_current)
    if _factorforge_direct_code_law_id in {
        "miller_flow_v18a_absolute_long_edge_gate_v1",
        "miller_flow_v18b_first_passage_repair_edge_v1",
        "miller_flow_v18c_crowding_filtered_repair_v1",
    }:
        _current = _absolute_edge_states(_current)
    if _factorforge_direct_code_law_id == "miller_flow_v18a_absolute_long_edge_gate_v1":
        _current = _absolute_long_edge(_current)
    if _factorforge_direct_code_law_id == "miller_flow_v18b_first_passage_repair_edge_v1":
        _current = _repair_first_passage_edge(_current)
    if _factorforge_direct_code_law_id == "miller_flow_v18c_crowding_filtered_repair_v1":
        _current = _crowding_filtered_repair(_current)
    _current["factor_value"] = _current["raw_v11_repair_absorption_signal"]
    return _current[["ts_code", "trade_date", "factor_value"]].replace(
        [_factorforge_np.inf, -_factorforge_np.inf],
        _factorforge_np.nan,
    )


def _select_absorption_cutoffs(out):
    """Compare the historical 14:00 and 14:50 cutoff states without relagging."""
    out["v14_latent_absorption_state"] = (
        0.44 * out["absorption_state"].fillna(0.0)
        + 0.22 * out["seller_pressure_state"].fillna(0.0)
        + 0.18 * out["discount_repair_state"].fillna(0.0)
        - 0.32 * out["bad_selling_noise_state"].fillna(0.0)
        - 0.24 * out["crowded_chasing_state"].fillna(0.0)
    )
    if "cutoff_time" in out.columns:
        _cutoff_text = out["cutoff_time"].astype(str).str.slice(0, 8)
        _cutoff_parts = _cutoff_text.str.extract(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})")
        out["_v14_cutoff_minutes"] = (
            _factorforge_pd.to_numeric(_cutoff_parts["hour"], errors="coerce") * 60
            + _factorforge_pd.to_numeric(_cutoff_parts["minute"], errors="coerce")
        )
        _current = (
            out[out["_v14_cutoff_minutes"] <= (14 * 60 + 50)]
            .sort_values(["ts_code", "trade_date", "_v14_cutoff_minutes"])
            .groupby(["ts_code", "trade_date"], sort=False)
            .tail(1)
            .copy()
        )
        _prior = (
            out[out["_v14_cutoff_minutes"] <= (14 * 60)]
            .sort_values(["ts_code", "trade_date", "_v14_cutoff_minutes"])
            .groupby(["ts_code", "trade_date"], sort=False)
            .tail(1)[
                [
                    "ts_code",
                    "trade_date",
                    "v14_latent_absorption_state",
                    "ret_tail_asymmetry_z",
                    "ret_excess_kurtosis_z",
                    "signed_flow_imbalance_z",
                    "signed_flow_tail_asymmetry_z",
                    "bad_selling_noise_state",
                ]
            ]
            .rename(
                columns={
                    "v14_latent_absorption_state": "v14_prior_absorption_state",
                    "ret_tail_asymmetry_z": "v15_prior_ret_tail_asymmetry_z",
                    "ret_excess_kurtosis_z": "v15_prior_ret_excess_kurtosis_z",
                    "signed_flow_imbalance_z": "v15_prior_signed_flow_imbalance_z",
                    "signed_flow_tail_asymmetry_z": "v15_prior_signed_flow_tail_asymmetry_z",
                    "bad_selling_noise_state": "v15_prior_bad_selling_noise_state",
                }
            )
        )
        if len(_current) == 0:
            _current = out.copy()
            _current["v14_prior_absorption_state"] = _current["v14_latent_absorption_state"]
            _current["v15_prior_ret_tail_asymmetry_z"] = _current["ret_tail_asymmetry_z"]
            _current["v15_prior_ret_excess_kurtosis_z"] = _current["ret_excess_kurtosis_z"]
            _current["v15_prior_signed_flow_imbalance_z"] = _current["signed_flow_imbalance_z"]
            _current["v15_prior_signed_flow_tail_asymmetry_z"] = _current["signed_flow_tail_asymmetry_z"]
            _current["v15_prior_bad_selling_noise_state"] = _current["bad_selling_noise_state"]
        else:
            _current = _current.merge(_prior, on=["ts_code", "trade_date"], how="left")
    else:
        _current = out.copy()
        _current["v14_prior_absorption_state"] = _current["v14_latent_absorption_state"]
        _current["v15_prior_ret_tail_asymmetry_z"] = _current["ret_tail_asymmetry_z"]
        _current["v15_prior_ret_excess_kurtosis_z"] = _current["ret_excess_kurtosis_z"]
        _current["v15_prior_signed_flow_imbalance_z"] = _current["signed_flow_imbalance_z"]
        _current["v15_prior_signed_flow_tail_asymmetry_z"] = _current["signed_flow_tail_asymmetry_z"]
        _current["v15_prior_bad_selling_noise_state"] = _current["bad_selling_noise_state"]
    _current["v14_absorption_momentum_raw"] = (
        _current["v14_latent_absorption_state"].fillna(0.0)
        - _current["v14_prior_absorption_state"].fillna(0.0)
    )
    _current["v14_absorption_momentum_z"] = _factorforge_z_by_day(_current, "v14_absorption_momentum_raw")
    return _current


def _compute_absorption_momentum(out, _factorforge_direct_code_law_id):
    """Compute the selected absorption-momentum law."""
    _current = _select_absorption_cutoffs(out)
    if _factorforge_direct_code_law_id in {
        "miller_flow_v15_repair_confirmed_absorption_fp_v1",
        "miller_flow_v16_positive_repair_core_fp_v1",
        "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
        "miller_flow_v18a_absolute_long_edge_gate_v1",
        "miller_flow_v18b_first_passage_repair_edge_v1",
        "miller_flow_v18c_crowding_filtered_repair_v1",
    }:
        return _compute_confirmed_repair(_current, _factorforge_direct_code_law_id)
    _current["v14_absorption_probability_proxy"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.54 * _current["v14_latent_absorption_state"].fillna(0.0)
                + 0.36 * _current["v14_absorption_momentum_z"].fillna(0.0)
                + 0.26 * _current["absorption_state"].fillna(0.0)
                - 0.30 * _current["bad_selling_noise_state"].fillna(0.0)
                - 0.24 * _current["crowded_chasing_state"].fillna(0.0)
                - 0.05
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v14_breakdown_probability_proxy"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.54 * _current["bad_selling_noise_state"].fillna(0.0)
                + 0.30 * _current["fragile_tail_penalty"].fillna(0.0)
                + 0.24 * _current["crowded_chasing_state"].fillna(0.0)
                + 0.18 * _factorforge_positive(-_current["v14_absorption_momentum_z"]).fillna(0.0)
                - 0.32 * _current["absorption_state"].fillna(0.0)
            ).clip(lower=-20.0, upper=20.0)
        )
    )
    _current["v14_upside_distance_proxy"] = (
        0.44 * _current["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.32 * _current["absorption_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.18 * _factorforge_positive(_current["v14_absorption_momentum_z"]).fillna(0.0).clip(0.0, 3.0)
        + 0.10 * _factorforge_positive(-_current["ret_excess_kurtosis_z"]).fillna(0.0).clip(0.0, 3.0)
    )
    _current["v14_downside_distance_proxy"] = (
        0.42 * _current["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.30 * _factorforge_positive(-_current["v14_absorption_momentum_z"]).fillna(0.0).clip(0.0, 3.0)
        + 0.22 * _current["crowded_chasing_state"].fillna(0.0).clip(0.0, 5.0)
        + 0.16 * _factorforge_positive(-_current["ret_tail_asymmetry_z"]).fillna(0.0).clip(0.0, 3.0)
    )
    _current["raw_v11_repair_absorption_signal"] = (
        _current["v14_absorption_probability_proxy"].fillna(0.0)
        * (0.66 + 0.24 * _current["v14_upside_distance_proxy"].fillna(0.0))
        - _current["v14_breakdown_probability_proxy"].fillna(0.0)
        * (0.54 + 0.22 * _current["v14_downside_distance_proxy"].fillna(0.0))
        - 0.10 * _current["crowded_chasing_state"].fillna(0.0)
        - 0.06 * _current["fragile_tail_penalty"].fillna(0.0)
        - 0.04 * _current["prior_overheat"].fillna(0.0)
    )
    _current["factor_value"] = _current["raw_v11_repair_absorption_signal"]
    return _current[["ts_code", "trade_date", "factor_value"]].replace(
        [_factorforge_np.inf, -_factorforge_np.inf],
        _factorforge_np.nan,
    )


def _compute_repair_factor(out, _factorforge_direct_code_law_id):
    """Dispatch historical repair laws on the same moment states."""
    if _factorforge_direct_code_law_id == "miller_flow_v11_first_passage_lite_v1":
        out["raw_v11_repair_absorption_signal"] = (
            out["upside_hitting_proxy"].fillna(0.0)
            * (0.70 + 0.22 * out["discount_repair_state"].fillna(0.0).clip(0.0, 5.0))
            - out["downside_hitting_proxy"].fillna(0.0)
            * (0.56 + 0.18 * out["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0))
            - 0.06 * out["prior_overheat"].fillna(0.0)
        )
    elif _factorforge_direct_code_law_id == "miller_flow_v12_midcore_first_passage_separator_v1":
        out["v12_cost_proxy"] = (
            0.30 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
            + 0.20 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
            + 0.18 * out["prior_overheat"].fillna(0.0)
        )
        out["v12_adverse_separator"] = (
            0.42 * out["crowded_chasing_state"].fillna(0.0)
            + 0.48 * out["bad_selling_noise_state"].fillna(0.0)
            + 0.18 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0)
        )
        out["v12_repair_reward"] = (
            0.72
            + 0.24 * out["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
            + 0.18 * out["absorption_state"].fillna(0.0).clip(0.0, 5.0)
        )
        out["v12_barrier_loss"] = (
            0.60
            + 0.30 * out["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0)
            + 0.20 * out["crowded_chasing_state"].fillna(0.0).clip(0.0, 5.0)
        )
        out["raw_v11_repair_absorption_signal"] = (
            out["upside_hitting_proxy"].fillna(0.0) * out["v12_repair_reward"].fillna(0.0)
            - out["downside_hitting_proxy"].fillna(0.0) * out["v12_barrier_loss"].fillna(0.0)
            - 0.22 * out["v12_adverse_separator"].fillna(0.0)
            - 0.10 * out["v12_cost_proxy"].fillna(0.0)
        ).where(out["mid_core_universe_gate"].fillna(0.0) >= 0.5)
    elif _factorforge_direct_code_law_id == "miller_flow_v13_full_first_passage_separator_v1":
        out["v13_absorption_probability_proxy"] = 1.0 / (
            1.0
            + _factorforge_np.exp(
                -(
                    0.64 * out["absorption_state"].fillna(0.0)
                    + 0.30 * out["seller_pressure_state"].fillna(0.0)
                    + 0.18 * _factorforge_positive(out["amount_hhi_z"]).fillna(0.0)
                    - 0.38 * out["bad_selling_noise_state"].fillna(0.0)
                    - 0.26 * out["crowded_chasing_state"].fillna(0.0)
                    - 0.08
                ).clip(lower=-20.0, upper=20.0)
            )
        )
        out["v13_breakdown_probability_proxy"] = 1.0 / (
            1.0
            + _factorforge_np.exp(
                -(
                    0.60 * out["bad_selling_noise_state"].fillna(0.0)
                    + 0.34 * out["fragile_tail_penalty"].fillna(0.0)
                    + 0.28 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0)
                    + 0.18 * out["crowded_chasing_state"].fillna(0.0)
                    - 0.32 * out["absorption_state"].fillna(0.0)
                ).clip(lower=-20.0, upper=20.0)
            )
        )
        out["v13_upside_distance_proxy"] = (
            0.52 * out["discount_repair_state"].fillna(0.0).clip(0.0, 5.0)
            + 0.34 * out["absorption_state"].fillna(0.0).clip(0.0, 5.0)
            + 0.12 * _factorforge_positive(-out["ret_excess_kurtosis_z"]).fillna(0.0).clip(0.0, 3.0)
        )
        out["v13_downside_distance_proxy"] = (
            0.46 * out["bad_selling_noise_state"].fillna(0.0).clip(0.0, 5.0)
            + 0.34 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0).clip(0.0, 3.0)
            + 0.22 * out["crowded_chasing_state"].fillna(0.0).clip(0.0, 5.0)
        )
        out["raw_v11_repair_absorption_signal"] = (
            out["v13_absorption_probability_proxy"].fillna(0.0)
            * (0.66 + 0.24 * out["v13_upside_distance_proxy"].fillna(0.0))
            - out["v13_breakdown_probability_proxy"].fillna(0.0)
            * (0.54 + 0.22 * out["v13_downside_distance_proxy"].fillna(0.0))
            - 0.12 * out["crowded_chasing_state"].fillna(0.0)
            - 0.06 * out["fragile_tail_penalty"].fillna(0.0)
        )
    elif _factorforge_direct_code_law_id in {
        "miller_flow_v14_absorption_momentum_first_passage_v1",
        "miller_flow_v15_repair_confirmed_absorption_fp_v1",
        "miller_flow_v16_positive_repair_core_fp_v1",
        "miller_flow_v17_benchmark_relative_repaired_absorption_v1",
        "miller_flow_v18a_absolute_long_edge_gate_v1",
        "miller_flow_v18b_first_passage_repair_edge_v1",
        "miller_flow_v18c_crowding_filtered_repair_v1",
    }:
        return _compute_absorption_momentum(out, _factorforge_direct_code_law_id)
    else:
        out["raw_v11_repair_absorption_signal"] = out["repair_drift_state"].fillna(0.0)
    if _factorforge_direct_code_law_id == "miller_flow_v11_repair_absorption_mid_core_v1":
        out["factor_value"] = out["raw_v11_repair_absorption_signal"].where(
            out["mid_core_universe_gate"].fillna(0.0) >= 0.5
        )
    else:
        out["factor_value"] = out["raw_v11_repair_absorption_signal"]
    return out[["ts_code", "trade_date", "factor_value"]].replace(
        [_factorforge_np.inf, -_factorforge_np.inf],
        _factorforge_np.nan,
    )


def _moment_states(daily, agg):
    """Compute cross-sectional shapes and lagged daily controls."""
    agg["signed_flow_imbalance_z"] = _factorforge_z_by_day(agg, "signed_flow_imbalance")
    agg["signed_amount_skew_z"] = _factorforge_z_by_day(agg, "signed_amount_skew")
    agg["signed_flow_tail_asymmetry_z"] = _factorforge_z_by_day(agg, "signed_flow_tail_asymmetry")
    agg["large_small_signed_spread_z"] = _factorforge_z_by_day(agg, "large_small_signed_spread")
    agg["amount_hhi_z"] = _factorforge_z_by_day(agg, "amount_hhi")
    agg["amount_top5_share_z"] = _factorforge_z_by_day(agg, "amount_top5_share")
    agg["amount_entropy_z"] = _factorforge_z_by_day(agg, "amount_entropy")
    agg["ret_tail_asymmetry_z"] = _factorforge_z_by_day(agg, "ret_tail_asymmetry")
    agg["ret_excess_kurtosis_z"] = _factorforge_z_by_day(agg, "ret_excess_kurtosis")
    agg["realized_vol_of_vol_z"] = _factorforge_z_by_day(agg, "realized_vol_of_vol")
    agg["signed_amount_excess_kurtosis_z"] = _factorforge_z_by_day(agg, "signed_amount_excess_kurtosis")
    agg["positive_share_z"] = _factorforge_z_by_day(agg, "positive_signed_amount_share")
    agg["negative_share_z"] = _factorforge_z_by_day(agg, "negative_signed_amount_share")

    agg["directed_flow_shape"] = (
        0.38 * agg["signed_flow_imbalance_z"].fillna(0.0)
        + 0.22 * agg["signed_amount_skew_z"].fillna(0.0)
        + 0.18 * agg["signed_flow_tail_asymmetry_z"].fillna(0.0)
        + 0.14 * agg["large_small_signed_spread_z"].fillna(0.0)
        + 0.08 * (agg["positive_share_z"].fillna(0.0) - agg["negative_share_z"].fillna(0.0))
    )
    agg["concentration_quality"] = (
        0.36 * _factorforge_positive(agg["amount_hhi_z"]).fillna(0.0)
        + 0.24 * _factorforge_positive(agg["amount_top5_share_z"]).fillna(0.0)
        - 0.22 * _factorforge_positive(agg["amount_entropy_z"]).fillna(0.0)
    )
    agg["fragile_tail_penalty"] = (
        0.30 * _factorforge_positive(agg["ret_excess_kurtosis_z"]).fillna(0.0)
        + 0.24 * _factorforge_positive(agg["realized_vol_of_vol_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(agg["signed_amount_excess_kurtosis_z"]).fillna(0.0)
        + 0.14 * _factorforge_positive(-agg["ret_tail_asymmetry_z"]).fillna(0.0)
    )
    agg["shape_quality_gate"] = 1.0 / (
        1.0
        + _factorforge_np.exp(
            -(
                0.46 * agg["concentration_quality"].fillna(0.0)
                + 0.28 * agg["directed_flow_shape"].abs().fillna(0.0)
                - 0.40 * agg["fragile_tail_penalty"].fillna(0.0)
                - 0.08
            ).clip(lower=-20.0, upper=20.0)
        )
    )

    control_cols = [
        "circ_mv",
        "total_mv",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pct_chg",
        "fixed_small_universe_flag",
        "fixed_small_rank_pct",
    ]
    keep = ["ts_code", "trade_date"] + [col for col in control_cols if col in daily.columns]
    controls = daily[keep].copy().sort_values(["ts_code", "trade_date"])
    for col in control_cols:
        if col not in controls.columns:
            controls[col] = _factorforge_np.nan
        controls[col] = _factorforge_pd.to_numeric(controls[col], errors="coerce")
        controls[col + "_prev"] = controls.groupby("ts_code", sort=False)[col].shift(1)
    controls = controls[["ts_code", "trade_date"] + [col + "_prev" for col in control_cols]]
    out = agg.merge(controls, on=["ts_code", "trade_date"], how="left")
    market_cap_prev = out["circ_mv_prev"].where(out["circ_mv_prev"] > 0, out["total_mv_prev"])
    out["ln_market_cap_prev"] = _factorforge_np.log(market_cap_prev.where(market_cap_prev > 0))
    out["size_prev_z"] = _factorforge_z_by_day(out, "ln_market_cap_prev")
    out["float_turnover_prev_z"] = _factorforge_z_by_day(out, "turnover_rate_f_prev")
    out["volume_ratio_prev_z"] = _factorforge_z_by_day(out, "volume_ratio_prev")
    out["pct_chg_prev_z"] = _factorforge_z_by_day(out, "pct_chg_prev")
    out["prior_overheat"] = (
        0.42 * _factorforge_positive(out["float_turnover_prev_z"]).fillna(0.0)
        + 0.30 * _factorforge_positive(out["volume_ratio_prev_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(out["pct_chg_prev_z"]).fillna(0.0)
    )
    out["cap_rank_pct_prev"] = market_cap_prev.groupby(out["trade_date"], sort=False).rank(pct=True)
    out["mid_core_universe_gate"] = (
        (market_cap_prev >= 50000.0)
        & (out["cap_rank_pct_prev"] > 0.10)
        & (out["cap_rank_pct_prev"] <= 0.80)
    ).astype(float)
    out["seller_pressure_state"] = (
        0.46 * _factorforge_positive(-out["signed_flow_imbalance_z"]).fillna(0.0)
        + 0.24 * _factorforge_positive(-out["signed_flow_tail_asymmetry_z"]).fillna(0.0)
        + 0.18 * _factorforge_positive(out["negative_share_z"]).fillna(0.0)
        + 0.12 * _factorforge_positive(-out["large_small_signed_spread_z"]).fillna(0.0)
    )
    out["discount_repair_state"] = (
        0.42 * _factorforge_positive(-_factorforge_z_by_day(out, "pct_chg_prev")).fillna(0.0)
        + 0.22 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0)
        + 0.16 * _factorforge_positive(-out["ret_excess_kurtosis_z"]).fillna(0.0)
    )
    out["absorption_state"] = (
        out["seller_pressure_state"].fillna(0.0)
        * (
            0.54
            + 0.18 * _factorforge_positive(out["amount_hhi_z"]).fillna(0.0).clip(0.0, 3.0)
            + 0.16 * _factorforge_positive(out["amount_top5_share_z"]).fillna(0.0).clip(0.0, 3.0)
            - 0.24 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0).clip(0.0, 3.0)
        )
    )
    out["crowded_chasing_state"] = (
        0.38 * _factorforge_positive(out["signed_flow_imbalance_z"]).fillna(0.0)
        + 0.26 * _factorforge_positive(out["ret_tail_asymmetry_z"]).fillna(0.0)
        + 0.20 * _factorforge_positive(out["signed_amount_skew_z"]).fillna(0.0)
        + 0.16 * out["prior_overheat"].fillna(0.0)
    )
    out["bad_selling_noise_state"] = (
        0.34 * out["fragile_tail_penalty"].fillna(0.0)
        + 0.22 * _factorforge_positive(out["realized_vol_of_vol_z"]).fillna(0.0)
        + 0.20 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0)
        + 0.16 * _factorforge_positive(out["amount_entropy_z"]).fillna(0.0)
    )
    out["repair_drift_state"] = (
        0.36 * out["discount_repair_state"].fillna(0.0)
        + 0.42 * out["absorption_state"].fillna(0.0)
        - 0.34 * out["crowded_chasing_state"].fillna(0.0)
        - 0.26 * out["bad_selling_noise_state"].fillna(0.0)
    )
    out["upside_hitting_proxy"] = (
        1.0 / (
            1.0
            + _factorforge_np.exp(
                -(
                    0.62 * out["repair_drift_state"].fillna(0.0)
                    + 0.24 * out["absorption_state"].fillna(0.0)
                    - 0.36 * out["crowded_chasing_state"].fillna(0.0)
                ).clip(lower=-20.0, upper=20.0)
            )
        )
    )
    out["downside_hitting_proxy"] = (
        1.0 / (
            1.0
            + _factorforge_np.exp(
                -(
                    0.52 * out["bad_selling_noise_state"].fillna(0.0)
                    + 0.32 * _factorforge_positive(-out["ret_tail_asymmetry_z"]).fillna(0.0)
                    - 0.28 * out["absorption_state"].fillna(0.0)
                ).clip(lower=-20.0, upper=20.0)
            )
        )
    )
    return out


def _compute_moment_factor(daily, agg, _factorforge_direct_code_law_id):
    """Validate moment inputs and return the original three-column factor."""
    moment_cols = [
        "signed_flow_imbalance",
        "signed_amount_skew",
        "signed_amount_excess_kurtosis",
        "signed_flow_tail_asymmetry",
        "large_small_signed_spread",
        "amount_hhi",
        "amount_top5_share",
        "amount_entropy",
        "ret_skew",
        "ret_excess_kurtosis",
        "ret_tail_asymmetry",
        "realized_vol",
        "realized_vol_of_vol",
        "positive_signed_amount_share",
        "negative_signed_amount_share",
    ]
    for _col in moment_cols:
        if _col not in agg.columns:
            agg[_col] = _factorforge_np.nan
        agg[_col] = _factorforge_pd.to_numeric(agg[_col], errors="coerce")
    agg = agg.dropna(subset=["ts_code", "trade_date", "signed_flow_imbalance"]).copy()
    if len(agg) == 0:
        return _factorforge_pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])

    out = _moment_states(daily, agg)
    if _factorforge_direct_code_law_id in {
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
        return _compute_repair_factor(out, _factorforge_direct_code_law_id)
    out["raw_v11_distribution_shape_signal"] = (
        out["directed_flow_shape"].fillna(0.0)
        * out["shape_quality_gate"].fillna(0.0)
        * (1.0 + 0.08 * _factorforge_positive(-out["size_prev_z"]).fillna(0.0).clip(0.0, 2.5))
        - 0.18 * out["fragile_tail_penalty"].fillna(0.0)
        - 0.10 * out["prior_overheat"].fillna(0.0)
    )
    fixed_small_gate = out["fixed_small_universe_flag_prev"]
    if fixed_small_gate.notna().any():
        out["factor_value"] = out["raw_v11_distribution_shape_signal"].where(fixed_small_gate.fillna(0.0) >= 0.5)
    else:
        out["factor_value"] = out["raw_v11_distribution_shape_signal"]
    return out[["ts_code", "trade_date", "factor_value"]].replace(
        [_factorforge_np.inf, -_factorforge_np.inf],
        _factorforge_np.nan,
    )
