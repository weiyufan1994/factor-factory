"""Small, common factor-object interface. No data fetching or backtesting here.

Implement ``compute(inputs)``; call the instance or ``run(inputs)`` to obtain a
validated (datetime, instrument) DataFrame with one ``factor_value`` column.
Inputs are named pandas frames. Treat them as read-only; copy before changing
columns. The mapping is read-only, but pandas objects are not a security sandbox.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pandas as pd


class BaseFactor(ABC):
    """A factor instance describes one estimator, not a research/backtest engine.

    ``input_columns`` declares input roles and required columns. Units, timing,
    lookback and missing-value rules belong in the concrete class's docstring
    and annotated implementation. This base cannot infer their economic truth.
    """

    name: str = ""
    domain: str = ""
    input_columns: Mapping[str, tuple[str, ...]] = {}

    def __init__(self, **parameters: Any) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("factor class must declare a nonempty name")
        if self.domain not in {"price_volume", "fundamental"}:
            raise ValueError("factor domain must be price_volume or fundamental")
        self.parameters = MappingProxyType(dict(parameters))

    @abstractmethod
    def compute(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Calculate values only; do not fetch data, construct labels or evaluate."""

    def run(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Validate named inputs, execute exactly once, validate the common output."""
        from .research_api import normalize_factor_frame

        if not isinstance(inputs, Mapping):
            raise TypeError("factor inputs must be a mapping of names to DataFrames")
        for role, columns in self.input_columns.items():
            if role not in inputs or inputs[role] is None:
                raise ValueError(f"missing factor input: {role}")
            frame = inputs[role]
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"factor input {role} must be a pandas DataFrame")
            if not frame.columns.is_unique:
                raise ValueError(f"factor input {role} has duplicate column names")
            missing = sorted(set(columns) - set(frame.columns))
            if missing:
                raise ValueError(f"factor input {role} missing columns: {missing}")
        # No positional guessing, exception-based retries or alternate formula.
        result = normalize_factor_frame(self.compute(MappingProxyType(dict(inputs))))
        result.attrs["factor"] = {
            "name": self.name,
            "domain": self.domain,
            "parameters": dict(self.parameters),
        }
        return result

    def __call__(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        return self.run(inputs)


class PriceVolumeFactor(BaseFactor):
    """Base for price/volume estimators; shares the same output as fundamental."""

    domain = "price_volume"


class FundamentalFactor(BaseFactor):
    """Base for fundamental estimators over already correctly timed PIT inputs.

    An announcement/report date is not automatically a daily availability date.
    The researcher must make that observation map explicit before calling run.
    """

    domain = "fundamental"


class FormulaFactor(BaseFactor):
    """An operator expression as an ordinary factor instance, with no new runner."""

    def __init__(self, expression: str, *, name: str = "formula_factor",
                 domain: str = "price_volume", input_role: str = "daily_df") -> None:
        self.name, self.domain, self.input_role = name, domain, input_role
        self.input_columns = {input_role: ("ts_code", "trade_date")}
        super().__init__(expression=expression)

    def compute(self, inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        from .formula import parse_formula
        from .formula.evaluator import evaluate_formula_frame

        frame = inputs[self.input_role]
        formula_ir = parse_formula(
            self.parameters["expression"], list(frame.columns), raise_on_error=True,
        )
        return evaluate_formula_frame(formula_ir, frame)
