from __future__ import annotations

from collections.abc import Mapping
from typing import Any


INFORMATION_POLICY_CONTRACT_VERSION = "factorforge_information_policy_v1"
HOST_INFORMATION_POLICY_ATTESTATION_VERSION = (
    "factorforge_host_information_policy_attestation_v1"
)
SUPPORTED_FORMATION_TIMES = frozenset(
    {
        "daily_pre_open",
        "daily_close",
        "intraday_cutoff",
        "filing_publication_time",
        "event_publication_time",
    }
)
CLEAN_DAILY_BAR_PIT_GUARANTEES_V1 = {
    "abnormal_pct_move": (
        "compares same-day pct_chg against same-day market-board limit regime only"
    ),
    "limit_events": "uses same-day pct_chg and same-day close/high/low only",
    "listing_days": (
        "computed from stock_basic.list_date + trade_cal using the row "
        "trade_date only"
    ),
    "st_windows": (
        "row is dropped only when row trade_date falls inside the stock_st interval"
    ),
    "suspension": "uses same-day vol/amount/close availability only",
}
_POLICY_PROJECTION_KEYS = {
    "contract",
    "pit_guarantees",
    "information_set_legality",
    "no_future_data",
    "no_future_intraday_minutes",
}


def _no_future_flag_consistent(value: Any) -> bool:
    return bool(
        value is None
        or value is True
        or (isinstance(value, str) and value.strip().lower() == "true")
    )


def _closed_policy_siblings_consistent(
    policy: Mapping[str, Any],
    *,
    expected_contract: Mapping[str, Any],
    expected_pit_guarantees: Mapping[str, Any],
) -> bool:
    return bool(
        set(policy) == _POLICY_PROJECTION_KEYS
        and policy.get("contract") == expected_contract
        and policy.get("pit_guarantees") == expected_pit_guarantees
        and policy.get("information_set_legality") == ""
        and _no_future_flag_consistent(policy.get("no_future_data"))
        and _no_future_flag_consistent(
            policy.get("no_future_intraday_minutes")
        )
    )


def project_information_policy_attestation(
    dataset_id: str,
    policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    policy = policy if isinstance(policy, Mapping) else {}
    explicit = policy.get("contract")
    if (
        isinstance(explicit, Mapping)
        and set(explicit)
        == {"version", "formation_time", "future_observations_excluded"}
        and explicit.get("version") == INFORMATION_POLICY_CONTRACT_VERSION
        and explicit.get("formation_time") in SUPPORTED_FORMATION_TIMES
        and explicit.get("future_observations_excluded") is True
        and _closed_policy_siblings_consistent(
            policy,
            expected_contract=explicit,
            expected_pit_guarantees={},
        )
    ):
        return {
            "version": HOST_INFORMATION_POLICY_ATTESTATION_VERSION,
            "verdict": "PASS",
            "rule_id": "explicit_information_policy_contract_v1",
            "formation_time": explicit["formation_time"],
            "future_observations_excluded": True,
        }
    if (
        dataset_id == "clean_daily_bar"
        and _closed_policy_siblings_consistent(
            policy,
            expected_contract={},
            expected_pit_guarantees=CLEAN_DAILY_BAR_PIT_GUARANTEES_V1,
        )
    ):
        return {
            "version": HOST_INFORMATION_POLICY_ATTESTATION_VERSION,
            "verdict": "PASS",
            "rule_id": "clean_daily_bar_pit_guarantees_v1",
            "formation_time": "daily_close",
            "future_observations_excluded": True,
        }
    return {
        "version": HOST_INFORMATION_POLICY_ATTESTATION_VERSION,
        "verdict": "NOT_ATTESTED",
        "rule_id": "none",
        "formation_time": "",
        "future_observations_excluded": False,
    }
