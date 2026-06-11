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
