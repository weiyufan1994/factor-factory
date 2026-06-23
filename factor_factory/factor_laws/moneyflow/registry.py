from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from factor_factory.factor_laws.moneyflow.derived_state import (
    SUPPORTED_MILLER_DERIVED_STATE_LAWS,
    minute_derived_flow_state_law_source,
)

BLOCK_LAW_MISSING = "BLOCK_FACTORFORGE_DIRECT_CODE_LAW_MISSING"
BLOCK_LAW_HASH_MISMATCH = "BLOCK_FACTORFORGE_DIRECT_CODE_LAW_HASH_MISMATCH"
BLOCK_LAW_DUPLICATE = "BLOCK_FACTORFORGE_DIRECT_CODE_LAW_DUPLICATE"


def stable_source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DirectCodeLaw:
    law_id: str
    source_code: str
    law_family: str = "moneyflow"
    adapter_options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def code_law_hash(self) -> str:
        return stable_source_hash(self.source_code)

    def to_contract(self) -> dict[str, Any]:
        return {
            "law_id": self.law_id,
            "law_family": self.law_family,
            "code_law_hash": self.code_law_hash,
            "source_code": self.source_code,
            "adapter_options": self.adapter_options,
            "metadata": self.metadata,
            "source_registry": "factor_factory.factor_laws.moneyflow.registry",
        }


_REGISTRY: dict[str, DirectCodeLaw] = {}


def register_law(law: DirectCodeLaw) -> DirectCodeLaw:
    existing = _REGISTRY.get(law.law_id)
    if existing and existing.code_law_hash != law.code_law_hash:
        raise SystemExit(f"{BLOCK_LAW_DUPLICATE}: law_id={law.law_id}")
    _REGISTRY[law.law_id] = law
    return law


def get_law(law_id: str) -> DirectCodeLaw | None:
    return _REGISTRY.get(str(law_id or "").strip())


def resolve_law(law_id: str, expected_hash: str | None = None) -> DirectCodeLaw:
    clean_id = str(law_id or "").strip()
    law = get_law(clean_id)
    if law is None:
        raise SystemExit(f"{BLOCK_LAW_MISSING}: law_id={clean_id}")
    if expected_hash and str(expected_hash).strip() != law.code_law_hash:
        raise SystemExit(
            f"{BLOCK_LAW_HASH_MISMATCH}: law_id={clean_id} "
            f"expected={expected_hash} actual={law.code_law_hash}"
        )
    return law


def resolve_contract(law_id: str, expected_hash: str | None = None) -> dict[str, Any]:
    return resolve_law(law_id, expected_hash=expected_hash).to_contract()


_SMOKE_SIGNED_AMOUNT_SOURCE = r'''
def compute_factor(daily_df=None, minute_df=None):
    import pandas as pd

    frame = minute_df if minute_df is not None else daily_df
    if frame is None:
        return pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])
    df = frame.copy()
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])
    code_col = "ts_code" if "ts_code" in df.columns else "instrument"
    date_col = "trade_date" if "trade_date" in df.columns else "datetime"
    if "signed_amount" in df.columns:
        value_col = "signed_amount"
    elif {"amount", "direction"}.issubset(df.columns):
        df["_signed_amount"] = df["amount"] * df["direction"]
        value_col = "_signed_amount"
    else:
        numeric = [c for c in df.columns if c not in {code_col, date_col} and pd.api.types.is_numeric_dtype(df[c])]
        value_col = numeric[0] if numeric else None
    if value_col is None:
        out = df[[code_col, date_col]].drop_duplicates()
        out["factor_value"] = 0.0
    else:
        out = df.groupby([code_col, date_col], as_index=False)[value_col].sum()
        out = out.rename(columns={value_col: "factor_value"})
    return out.rename(columns={code_col: "ts_code", date_col: "trade_date"})[["ts_code", "trade_date", "factor_value"]]
'''.strip()


_SMOKE_DERIVED_STATE_SOURCE = r'''
def compute_factor(daily_df=None, minute_df=None):
    import pandas as pd

    frame = minute_df if minute_df is not None else daily_df
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])
    df = frame.copy()
    code_col = "ts_code" if "ts_code" in df.columns else "instrument"
    date_col = "trade_date" if "trade_date" in df.columns else "datetime"
    if "minute_derived_flow_state_v1" in df.columns and "posterior_flow_pressure" in df.columns:
        value_col = "posterior_flow_pressure"
    elif "flow_pressure" in df.columns:
        value_col = "flow_pressure"
    else:
        numeric = [c for c in df.columns if c not in {code_col, date_col} and pd.api.types.is_numeric_dtype(df[c])]
        value_col = numeric[0] if numeric else None
    out = df[[code_col, date_col]].drop_duplicates() if value_col is None else df.groupby([code_col, date_col], as_index=False)[value_col].mean().rename(columns={value_col: "factor_value"})
    if "factor_value" not in out.columns:
        out["factor_value"] = 0.0
    return out.rename(columns={code_col: "ts_code", date_col: "trade_date"})[["ts_code", "trade_date", "factor_value"]]
'''.strip()


_LCR_FLOAT_VALUE_DENOMINATOR_SOURCE = r'''
def _factorforge_lcr_unit_multiplier(unit_value, *, kind):
    text = str(unit_value or "").strip().lower()
    if not text:
        return 1.0
    if "万" in text or "10k" in text or "wan" in text:
        return 10000.0
    if "thousand" in text or "千" in text:
        return 1000.0
    if "share" in text or "cny" in text or "yuan" in text or "rmb" in text:
        return 1.0
    return 1.0


def compute_factor_from_derived_state(daily_df=None, derived_state_df=None):
    """Compute retained-chip pressure scaled by current free-float value."""
    import numpy as np
    import pandas as pd

    if derived_state_df is None:
        raise ValueError("derived_state_df is required for intraday_retained_chip_state_v1")
    if daily_df is None:
        raise ValueError("daily_df with close is required for float-value denominator")

    state = derived_state_df.copy()
    daily = daily_df.copy()
    required_state = {"ts_code", "trade_date", "retained_amount_sum", "float_share"}
    missing_state = required_state.difference(state.columns)
    if missing_state:
        raise ValueError(f"intraday_retained_chip_state_v1 missing columns: {sorted(missing_state)}")
    required_daily = {"ts_code", "trade_date", "close"}
    missing_daily = required_daily.difference(daily.columns)
    if missing_daily:
        raise ValueError(f"daily_df missing columns for LCR V2: {sorted(missing_daily)}")

    state_cols = [
        c
        for c in [
            "ts_code",
            "trade_date",
            "retained_amount_sum",
            "float_share",
            "float_share_unit",
            "amount_unit",
            "qa_status",
        ]
        if c in state.columns
    ]
    state = state.loc[:, state_cols].copy()
    daily = daily.loc[:, ["ts_code", "trade_date", "close"]].copy()
    state["trade_date"] = state["trade_date"].astype(str).str.replace("-", "", regex=False)
    daily["trade_date"] = daily["trade_date"].astype(str).str.replace("-", "", regex=False)
    frame = state.merge(daily, on=["ts_code", "trade_date"], how="left", validate="many_to_one")

    retained = pd.to_numeric(frame["retained_amount_sum"], errors="coerce").astype(float)
    float_share = pd.to_numeric(frame["float_share"], errors="coerce").astype(float)
    close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
    if "float_share_unit" in frame.columns:
        share_scale = frame["float_share_unit"].map(
            lambda x: _factorforge_lcr_unit_multiplier(x, kind="share")
        ).astype(float)
    else:
        share_scale = 1.0
    if "amount_unit" in frame.columns:
        amount_scale = frame["amount_unit"].map(
            lambda x: _factorforge_lcr_unit_multiplier(x, kind="amount")
        ).astype(float)
    else:
        amount_scale = 1.0

    retained_cny = retained * amount_scale
    float_value = close * float_share * share_scale
    ratio = retained_cny / float_value.replace(0.0, np.nan)
    ratio = ratio.where((ratio > 0.0) & np.isfinite(ratio))
    frame["factor_value"] = np.log1p(ratio)
    out = frame.loc[:, ["ts_code", "trade_date", "factor_value"]].copy()
    return out.dropna(subset=["factor_value"])


def compute_factor(daily_df=None, minute_df=None, derived_state_df=None):
    state_df = derived_state_df if derived_state_df is not None else minute_df
    return compute_factor_from_derived_state(daily_df=daily_df, derived_state_df=state_df)
'''.strip()


register_law(
    DirectCodeLaw(
        law_id="moneyflow_registry_smoke_signed_amount_v1",
        source_code=_SMOKE_SIGNED_AMOUNT_SOURCE,
        adapter_options={"requires_minute_or_derived_state": True},
        metadata={
            "description": "Smoke-test law entry. Production moneyflow laws must register their reviewed implementation under their own law_id."
        },
    )
)
register_law(
    DirectCodeLaw(
        law_id="moneyflow_registry_smoke_derived_state_v1",
        source_code=_SMOKE_DERIVED_STATE_SOURCE,
        adapter_options={"requires_minute_or_derived_state": True},
        metadata={
            "description": "Smoke-test derived-state law entry. Production moneyflow laws must register their reviewed implementation under their own law_id."
        },
    )
)
register_law(
    DirectCodeLaw(
        law_id="dim_scale_float_value_denominator_v1",
        source_code=_LCR_FLOAT_VALUE_DENOMINATOR_SOURCE,
        law_family="retained_chip",
        adapter_options={
            "requires_minute_or_derived_state": True,
            "supports_intraday_retained_chip_state_v1": True,
            "requires_daily_close": True,
        },
        metadata={
            "description": "LCR V2 retained-chip law: survival-weighted retained amount scaled by current free-float value.",
            "formula_law": "factor_value = log1p(retained_amount_sum / (close * adjusted_float_share))",
            "state_dataset": "intraday_retained_chip_state_v1",
            "source_report": "huaxi_20250529_lcr_retained_chip_ratio",
        },
    )
)


for _law_id in sorted(SUPPORTED_MILLER_DERIVED_STATE_LAWS):
    register_law(
        DirectCodeLaw(
            law_id=_law_id,
            source_code=minute_derived_flow_state_law_source(_law_id),
            adapter_options={
                "requires_minute_or_derived_state": True,
                "supports_minute_derived_flow_state_v1": True,
                "requires_step4_derived_state": True,
            },
            metadata={
                "description": "Miller moneyflow production law migrated from the historical Step3B derived-state adapter.",
                "historical_source": "backup/factorforge-dirty-before-cleanup-20260611-094945:skills/factor-forge-step3/scripts/run_step3b.py",
                "migration_scope": "registry_entry_only_existing_artifacts_must_be_rerun_or_marked_historical_caveat",
                "requires_qlib_adapter_config_rerun": True,
            },
        )
    )
