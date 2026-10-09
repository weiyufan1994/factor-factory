"""Pure mapping from an authored evaluation plan to the existing evaluator format.

The historical Web v2 name and serialization remain stable for stored studies;
using this function does not start a Console, acquire data or evaluate a factor.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


RISK_PROOF_CONTROL_COLUMNS = ("total_mv", "turnover_rate")
BEHAVIORAL_PROOF_SOURCE_CONTROL_COLUMNS = (
    "pct_chg",
    "turnover_rate",
    "ln_mcap_free",
    "volume_ratio",
)


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_web_evaluation_contract(plan: dict[str, Any]) -> dict[str, Any]:
    research = plan["research_object"]
    data_plan = plan["data_plan"]
    evidence = plan["evidence_policy"]
    claim_class = plan["economic_mechanism"]["claim_class"]
    proof_control_columns = (
        list(RISK_PROOF_CONTROL_COLUMNS)
        if claim_class == "risk_premium"
        else (
            list(BEHAVIORAL_PROOF_SOURCE_CONTROL_COLUMNS)
            if claim_class != "unknown"
            else []
        )
    )
    measurement_program = plan.get("measurement_program")
    search_policy = (
        measurement_program.get("search_policy")
        if isinstance(measurement_program, dict)
        and isinstance(measurement_program.get("search_policy"), dict)
        else {}
    )
    diagnostic_trials = [
        {
            "trial_id": str(item["trial_id"]),
            "role": str(item["role"]),
            "component_id": str(item["component_id"]),
            "formula_or_law": str(item["formula_or_law"]),
            "signal_column": f"diagnostic__{item['trial_id']}",
            "affects_acceptance": False,
        }
        for item in search_policy.get("registered_diagnostic_trials") or []
        if isinstance(item, dict)
    ]
    return {
        "version": "factorforge_web_evaluation_contract_v2",
        "rebalance_frequency": research["rebalance_frequency"],
        "signal_timestamp_policy": evidence["signal_timestamp_policy"],
        "position_entry_policy": evidence["position_entry_policy"],
        "position_exit_policy": evidence["payoff_contract"]["exit"],
        "payoff_label_expression": evidence["payoff_contract"]["label_expression"],
        "availability_lags": data_plan["availability_lags"],
        "missing_data_policy": data_plan["missing_data_policy"],
        "forward_horizon": evidence["forward_horizon"],
        "label_policy": {
            "horizon": "one_trading_day_after_execution",
            "return_type": "simple",
            "entry_price_field": "close",
            "exit_price_field": "close",
            "execution_lag_sessions": 1,
            "holding_period_sessions": 1,
            "return_window": evidence["payoff_contract"]["return_window"],
        },
        "transaction_cost_bps": evidence["transaction_cost_bps"],
        "cost_model_id": evidence["cost_model_id"],
        "cost_formula": "one_way_turnover * 0.003",
        "proof_control_columns": proof_control_columns,
        "diagnostic_trials": diagnostic_trials,
    }
