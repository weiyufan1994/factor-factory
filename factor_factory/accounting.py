"""Cash/units transitions extracted from the existing local-IS account engine.

Kept deliberately small: order policy, quote validity and valuation are owned
by each caller. adj_factor=1 means literal fractional shares in one price basis.
"""
from __future__ import annotations

import math


def buy_fill(cash, gross_budget, price, cost_rate, *, adj_factor=1.0):
    """Return cash after fill, units, and the explicit buy fee."""
    if not all(math.isfinite(x) for x in (cash, gross_budget, price, cost_rate, adj_factor)):
        raise ValueError('nonfinite buy inputs')
    if cash < 0 or gross_budget < 0 or price <= 0 or adj_factor <= 0 or cost_rate < 0:
        raise ValueError('invalid buy inputs')
    cost = gross_budget * cost_rate
    new_cash = cash - (gross_budget + cost)
    if new_cash < -1e-10 * max(1.0, abs(cash)):
        raise ValueError('buy exceeds available cash')
    units = gross_budget / (price * adj_factor)
    if not all(math.isfinite(x) for x in (cost, new_cash, units)):
        raise ValueError('buy overflow')
    return new_cash, units, cost


def sell_fill(cash, units, price, cost_rate, *, adj_factor=1.0):
    """Return cash after fill, gross sale amount, and explicit sell fee."""
    if not all(math.isfinite(x) for x in (cash, units, price, cost_rate, adj_factor)):
        raise ValueError('nonfinite sell inputs')
    if units < 0 or price <= 0 or adj_factor <= 0 or not 0 <= cost_rate < 1:
        raise ValueError('invalid sell inputs')
    gross = units * price * adj_factor
    cost = gross * cost_rate
    new_cash = cash + (gross - cost)
    if not all(math.isfinite(x) for x in (gross, cost, new_cash)):
        raise ValueError('sell overflow')
    return new_cash, gross, cost
