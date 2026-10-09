"""Pure derived-state entry point shared by generation and direct callers."""

from .derived_state_common import _factorforge_date_key
from .derived_state_moments import _compute_moment_factor
from .derived_state_pressure import _compute_pressure_factor


def compute_derived_state(daily_df=None, derived_state_df=None, law_id=""):
    """Pure DataFrame kernel; inputs are copied and no data is fetched."""
    _factorforge_direct_code_law_id = str(law_id or "").strip()
    if daily_df is None or derived_state_df is None:
        raise ValueError("daily_df and derived_state_df are required")
    daily = _factorforge_date_key(daily_df)
    agg = _factorforge_date_key(derived_state_df)

    if (
        _factorforge_direct_code_law_id in {
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
        }
        and "signed_flow_imbalance" in agg.columns
        and "ret_excess_kurtosis" in agg.columns
    ):
        return _compute_moment_factor(daily, agg, _factorforge_direct_code_law_id)

    return _compute_pressure_factor(daily, agg, _factorforge_direct_code_law_id)

