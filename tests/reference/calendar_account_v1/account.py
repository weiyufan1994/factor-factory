"""Pure adjusted-price-unit close-mark diagnostic, not actual fills or shares.

No data loading. The explicit standard-daily policy permits stale valuation
only for confirmed suspended holdings in the same fixed adjusted-price basis.
Execution checks use raw close against raw limits, never a stale mark. No buy
retry, leverage, external cash, total-return or actual-fill claim.
"""
import math

import numpy as np
import pandas as pd


class AccountBlocked(ValueError):
    pass


SUSPENSION_POLICY = "confirmed_suspension_same_snapshot_last_valid"


def boolean(value):
    return None if pd.isna(value) or value not in (True, False, 0, 1) else bool(value)


def positive_price(value):
    return not pd.isna(value) and isinstance(value, (int, float, np.number)) and np.isfinite(value) and value > 0


def state_is(value, expected):
    return isinstance(value, str) and value == expected


def execution_check(row, side):
    """Conservative daily close assumption, not an assertion of a real fill."""
    if state_is(row.get("suspension_state"), "SUSPENSION_EVENT_PRESENT"):
        action = row.get("buy_execution_action" if side == "BUY" else "sell_execution_action")
        blocked = boolean(row.get("pretrade_buy_blocked" if side == "BUY" else "pretrade_sell_blocked"))
        if blocked is True or state_is(action, "BLOCK") or state_is(action, "CARRY_EXISTING_POSITION"):
            return False, "V17_SUSPENSION_ACTION_NO_TRADE"
        # The current V17 publishes conservative BLOCK/CARRY for S/R events.
        # A contradictory event row has no resolved intraday execution timing;
        # neither the event letter nor an observed close establishes a fill.
        return False, "SUSPENSION_EVENT_EXECUTION_TIMING_UNRESOLVED"
    if boolean(row.get("constraint_complete")) is not True:
        return False, "UNKNOWN_EXECUTION_CONSTRAINTS"
    if not state_is(row.get("suspension_state"), "NOT_SUSPENDED"):
        return False, "UNKNOWN_SUSPENSION_STATE"
    if side == "BUY":
        if not state_is(row.get("st_state"), "NOT_ST"):
            return False, "ST_OR_UNKNOWN_ENTRY_RISK"
        # Optional positive risk evidence is honored. Absence is NOT a claim
        # of historically LISTED status; the input capability gap is disclosed.
        if ("delisting_risk" in row and boolean(row["delisting_risk"]) is not False) or state_is(row.get("listing_status"), "DELISTED"):
            return False, "DELISTING_ENTRY_RISK"
    flag = boolean(row.get("pretrade_buy_blocked" if side == "BUY" else "pretrade_sell_blocked"))
    if flag is not False:
        return False, "PRETRADE_BLOCKED_OR_UNKNOWN"
    expected = ("CHECK_UP_LIMIT_AT_EXECUTION__KEEP_CASH_ON_NO_FILL" if side == "BUY"
                else "CHECK_DOWN_LIMIT_AT_EXECUTION__CARRY_ON_NO_FILL")
    if not state_is(row.get("buy_execution_action" if side == "BUY" else "sell_execution_action"), expected):
        return False, "UNSUPPORTED_EXECUTION_ACTION"
    if not state_is(row.get("execution_price_basis"), "unadjusted_close"):
        return False, "EXECUTION_PRICE_BASIS_UNAVAILABLE_OR_MISMATCH"
    raw = row.get("execution_close_raw", np.nan)
    limit = row.get("up_limit" if side == "BUY" else "down_limit", np.nan)
    if not positive_price(raw):
        return False, "MISSING_RAW_EXECUTION_CLOSE"
    if not positive_price(limit):
        return False, "MISSING_DIRECTIONAL_LIMIT"
    if side == "BUY" and raw >= limit - 1e-8:
        return False, "CLOSE_AT_OR_ABOVE_UP_LIMIT"
    if side == "SELL" and raw <= limit + 1e-8:
        return False, "CLOSE_AT_OR_BELOW_DOWN_LIMIT"
    return True, "DAILY_CLOSE_WITHIN_DIRECTIONAL_LIMIT"


def simulate_account(calendar, market, targets, *, initial_cash=1., terminal=True, cost_rate=.003,
                     ledger_sink=None, retain_holdings=True, valuation_policy=None,
                     price_basis_id=None, mark_sink=None):
    """Return NAV/ledger or block; target date is actual scheduled close e_t.

    market keyed (trade_date,ts_code) fields:
      price: verified positive same-snapshot adjusted close; constraint_complete,
      buy_allowed,sell_allowed: explicit booleans;
    Explicit standard-daily mode also requires original V17 action/state fields
    and raw execution close/limits. Legacy already-resolved fixture inputs keep
    their original strict behavior when no policy is supplied.
    Quantity means synthetic adjusted_price_units, never legal shares. No
    corporate action multipliers/cash distributions are inferred or invented.
    targets maps scheduled dates to Series({code: pretrade_NAV_weight}); empty
    Series means cash. Caller owns frozen PIT/score/threshold gates.

    New targets supersede deferred sells. At each scheduled date, sell desired
    excess first, then scale all positive buy deficits by one common fee-aware
    factor if cash is insufficient. No reallocation from a blocked buyer.
    Unfilled buys expire; only excess-unit sells persist and retry daily.
    """
    dates = list(pd.to_datetime(calendar).normalize())
    standard_daily = valuation_policy == SUSPENSION_POLICY
    if valuation_policy not in (None, SUSPENSION_POLICY):
        raise ValueError("unsupported_valuation_policy")
    if standard_daily and (not isinstance(price_basis_id, str) or not price_basis_id):
        raise ValueError("explicit_fixed_price_basis_required")
    if not dates or dates != sorted(set(dates)) or not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("invalid_calendar_or_initial_cash")
    daily_loader = getattr(market, "for_day", None)
    if daily_loader is None:
        data = market.copy()
        data["trade_date"] = pd.to_datetime(data.trade_date).dt.normalize()
        if data.duplicated(["trade_date", "ts_code"]).any():
            raise ValueError("duplicate_market_key")
        book = data.set_index(["trade_date", "ts_code"])
    scheduled = {pd.Timestamp(k).normalize(): v.astype(float).copy() for k, v in targets.items()}
    if not set(scheduled).issubset(dates):
        raise ValueError("target_date_outside_calendar")
    for weights in scheduled.values():
        if weights.index.has_duplicates or not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() > 1+1e-12:
            raise ValueError("invalid_target_weights")
    qty, desired = {}, {}
    cash = gross_cash = float(initial_cash)
    cumulative_fees = 0.
    navs, trades, mark_events = [], [], []
    last_marks = {}
    previous = previous_gross = float(initial_cash)
    if cost_rate not in (.003, .006):
        raise ValueError("only_ratified_base30bp_or_stress60bp")
    fee = cost_rate
    for session_index, day in enumerate(dates):
        sellable = dict(qty)  # T+1: only units carried into this session may sell.
        day_rows = {}
        if daily_loader is not None:
            wanted = set(qty)
            if day in scheduled and not (terminal and day == dates[-1]):
                wanted.update(str(k) for k, weight in scheduled[day].items() if weight > 0)
            data = daily_loader(day, wanted)
            if data.duplicated(["trade_date", "ts_code"]).any() or not data.trade_date.eq(day).all():
                raise ValueError("invalid_day_market_keys")
            book = data.set_index(["trade_date", "ts_code"])
        def known_constraints(r):
            return all(not pd.isna(r[field]) and r[field] in (0, 1, False, True)
                       for field in ("constraint_complete", "buy_allowed", "sell_allowed")) and bool(r.constraint_complete)
        def row(code, *, allow_unknown_unheld=False):
            if code in day_rows:
                return day_rows[code]
            if (day, code) not in book.index:
                if not (standard_daily and allow_unknown_unheld and qty.get(code, 0.) <= 1e-14):
                    raise AccountBlocked(f"missing_mark_or_constraints:{day.date()}:{code}")
                r = pd.Series({"price": np.nan})  # an unfilled order, never an invented market observation
            else:
                r = book.loc[(day, code)].copy()
            if standard_daily:
                held = qty.get(code, 0.) > 1e-14
                basis = r.get("price_basis_id", price_basis_id)
                if not state_is(basis, price_basis_id):
                    raise AccountBlocked(f"price_basis_mismatch:{day.date()}:{code}")
                if held and (boolean(r.get("corporate_action_unresolved", False)) is not False
                             or state_is(r.get("listing_status"), "DELISTED")):
                    raise AccountBlocked(f"unresolved_corporate_action_or_delisting:{day.date()}:{code}")
                suspended = state_is(r.get("suspension_state"), "SUSPENSION_EVENT_PRESENT")
                r["execution_price"] = np.nan if suspended else r.price
                r["stale_sessions"] = 0
                r["stale_calendar_days"] = 0
                r["mark_status"] = "OBSERVED_SAME_SNAPSHOT_CLOSE"
                r["mark_date"] = day
                if not positive_price(r.price) and (suspended or not held):
                    if held:
                        previous_mark = last_marks.get(code)
                        if previous_mark is None or previous_mark["basis"] != basis:
                            raise AccountBlocked(f"suspension_without_same_basis_prior_mark:{day.date()}:{code}")
                        r["price"] = previous_mark["price"]
                        r["mark_date"] = previous_mark["day"]
                        r["stale_sessions"] = session_index - previous_mark["session_index"]
                        r["stale_calendar_days"] = (day - previous_mark["day"]).days
                        r["mark_status"] = "CONFIRMED_SUSPENSION_CARRY_LAST_VALID"
                    else:
                        # No price or invented units are needed to reject an
                        # unheld suspended target and reserve its cash budget.
                        r["price"] = np.nan
                        r["mark_status"] = "UNHELD_SUSPENDED_NO_VALUATION" if suspended else "UNHELD_MISSING_MARK_NO_VALUATION"
                    day_rows[code] = r
                    return r
            if not positive_price(r.price):
                raise AccountBlocked(f"invalid_mark:{day.date()}:{code}")
            if standard_daily:
                prior_mark = last_marks.get(code)
                if held and prior_mark is not None and session_index-prior_mark["session_index"] > 1:
                    r["mark_status"] = "OBSERVED_AFTER_STALE"
                last_marks[code] = {"price": float(r.price), "day": day,
                                    "session_index": session_index, "basis": price_basis_id}
                # Observed, same-basis holdings can be valued even when an
                # execution restriction is unknown. Such orders remain blocked;
                # no fill or normal listing status is inferred from the mark.
                day_rows[code] = r
                return r
            # Only an unheld new candidate may retain unknown constraints:
            # it cannot trade, but its allocated buy budget stays idle cash.
            # Held-name uncertainty still fails the account as before.
            if allow_unknown_unheld and qty.get(code, 0.) <= 1e-14 and not known_constraints(r):
                return r
            for field in ("constraint_complete", "buy_allowed", "sell_allowed"):
                if pd.isna(r[field]) or r[field] not in (0, 1, False, True):
                    raise AccountBlocked(f"unknown_constraint:{day.date()}:{code}:{field}")
            if not bool(r.constraint_complete):
                raise AccountBlocked(f"incomplete_constraints:{day.date()}:{code}")
            return r
        value = sum(qty[k]*float(row(k).price) for k in qty)
        pre_nav = cash+value
        if pre_nav <= 0 or not np.isfinite(pre_nav):
            raise AccountBlocked("nonpositive_pretrade_NAV")
        is_terminal = terminal and day == dates[-1]
        is_scheduled = day in scheduled and not is_terminal
        unpriced_targets = {}
        if is_terminal:
            desired = {}
        elif is_scheduled:
            weights = scheduled[day]
            desired = {}
            for code, weight in weights.items():
                if weight <= 0:
                    continue
                code = str(code)
                r = row(code, allow_unknown_unheld=True)
                if standard_daily and not np.isfinite(r.price):
                    unpriced_targets[code] = pre_nav*float(weight)
                else:
                    desired[code] = pre_nav*float(weight)/float(r.price)
        fees_today = notional_today = 0.
        def record(code, side, amount, price, status, reason, requested_notional=None):
            nonlocal cash, gross_cash, cumulative_fees, fees_today, notional_today
            notional = amount*price if status == "FILLED" else 0.
            cost = notional*fee
            if status == "FILLED":
                if side == "SELL":
                    if amount > sellable.get(code, 0.) + 1e-12:
                        raise AccountBlocked("T_PLUS_ONE_SELL_EXCEEDS_CARRIED_UNITS")
                    sellable[code] -= amount
                sign = 1 if side == "SELL" else -1
                cash += sign*notional-cost
                gross_cash += sign*notional
                qty[code] = qty.get(code, 0.)-amount if side == "SELL" else qty.get(code, 0.)+amount
                cumulative_fees += cost
                fees_today += cost
                notional_today += notional
            trade = {"trade_date": day, "ts_code": code, "side": side, "status": status,
                           "reason": reason, "requested_adjusted_price_units": amount,
                           "adjusted_price_units": amount if status == "FILLED" else 0.,
                           "price": price, "notional": notional, "cost": cost, "pretrade_nav": pre_nav}
            if standard_daily:
                r = row(code, allow_unknown_unheld=True)
                trade.update(execution_price=price, valuation_mark=r.price,
                             execution_close_raw=r.get("execution_close_raw", np.nan),
                             requested_notional=requested_notional if requested_notional is not None else amount*r.price,
                             mark_status=r.mark_status, stale_sessions=r.stale_sessions,
                             fill_assumption="conservative_daily_close_not_guaranteed_actual_fill")
            trades.append(trade)
        for code in sorted(qty):
            excess = max(0., qty[code]-desired.get(code, 0.))
            if excess <= 1e-14:
                continue
            r = row(code)
            allowed, reason = execution_check(r, "SELL") if standard_daily else (bool(r.sell_allowed),
                "TERMINAL_EXIT" if is_terminal else "TARGET_EXCESS_SELL" if is_scheduled else "DEFERRED_EXCESS_SELL")
            record(code, "SELL", excess, float(r.execution_price if standard_daily else r.price),
                   "FILLED" if allowed else "BLOCKED", reason)
        if is_scheduled:
            deficits = {k: max(0., desired[k]-qty.get(k, 0.)) for k in desired}
            total = sum(v*float(row(k, allow_unknown_unheld=True).price) for k, v in deficits.items()) + sum(unpriced_targets.values())
            scale = min(1., max(0., cash)/(total*(1+fee))) if total > 0 else 0.
            # Scale includes blocked orders so their unfilled budget stays cash.
            for code in sorted(deficits):
                amount = deficits[code]*scale
                if amount <= 1e-14:
                    continue
                r = row(code, allow_unknown_unheld=True)
                if standard_daily:
                    allowed, reason = execution_check(r, "BUY")
                else:
                    known = known_constraints(r)
                    allowed, reason = known and bool(r.buy_allowed), "SCHEDULED_UPPER_TAIL_TARGET" if known else "UNKNOWN_CONSTRAINTS_UNHELD_NEW_BUY"
                record(code, "BUY", amount, float(r.execution_price if standard_daily else r.price),
                       "FILLED" if allowed else "BLOCKED", reason)
            for code, budget in sorted(unpriced_targets.items()):
                r = row(code, allow_unknown_unheld=True)
                _, reason = execution_check(r, "BUY")
                record(code, "BUY", np.nan, np.nan, "BLOCKED", reason if not positive_price(r.price) and reason != "DAILY_CLOSE_WITHIN_DIRECTIONAL_LIMIT" else "MISSING_NEW_BUY_MARK",
                       requested_notional=budget*scale)
        qty = {k: v for k, v in qty.items() if v > 1e-14}
        marked = sum(qty[k]*float(row(k).price) for k in qty)
        nav, gross_nav = cash+marked, gross_cash+marked
        tolerance = 1e-10*max(1., pre_nav)
        if cash < -tolerance or not math.isclose(nav, pre_nav-fees_today, abs_tol=tolerance, rel_tol=1e-10):
            raise AccountBlocked("self_financing_conservation_failure")
        if not math.isclose(gross_nav-nav, cumulative_fees, abs_tol=tolerance, rel_tol=1e-10):
            raise AccountBlocked("same_quantity_gross_shadow_failure")
        navs.append({"trade_date": day, "nav": nav, "gross_shadow_nav": gross_nav,
                     "cash": cash, "gross_shadow_cash": gross_cash, "market_value": marked,
                     "daily_return": nav/previous-1, "gross_shadow_daily_return": gross_nav/previous_gross-1,
                     "cost": fees_today, "cost_weight": fees_today/pre_nav,
                     "one_way_notional_weight": notional_today/pre_nav,
                     "half_L1_turnover": .5*notional_today/pre_nav,
                     "terminal_residual_weight": marked/nav if is_terminal else np.nan,
                     "holdings": dict(qty) if retain_holdings else None})
        if standard_daily:
            stale_value = sum(qty[k]*float(row(k).price) for k in qty if row(k).stale_sessions > 0)
            navs[-1].update(stale_market_value=stale_value, stale_weight=stale_value/nav,
                           stale_position_count=sum(row(k).stale_sessions > 0 for k in qty),
                           max_stale_sessions=max((row(k).stale_sessions for k in qty), default=0),
                           unknown_execution_position_count=sum(boolean(row(k).get("constraint_complete")) is not True for k in qty))
            events = [{"trade_date": day, "ts_code": k, "valuation_mark": float(row(k).price),
                       "mark_date": row(k).mark_date, "stale_sessions": int(row(k).stale_sessions),
                       "stale_calendar_days": int(row(k).stale_calendar_days),
                       "price_basis_id": price_basis_id, "status": row(k).mark_status,
                       "adjusted_price_units": qty[k]} for k in qty if row(k).stale_sessions > 0 or row(k).mark_status == "OBSERVED_AFTER_STALE"]
            if events:
                if mark_sink is not None:
                    mark_sink(pd.DataFrame(events))
                else:
                    mark_events.extend(events)
        if ledger_sink is not None and trades:
            ledger_sink(pd.DataFrame(trades))
            trades.clear()
        previous, previous_gross = nav, gross_nav
    return {"daily_nav": pd.DataFrame(navs), "trades": pd.DataFrame(trades),
            "stale_marks": pd.DataFrame(mark_events), "valuation_policy": valuation_policy,
            "initial_state": {"cash": initial_cash, "adjusted_price_units": {}},
            "terminal_state": {"cash": cash, "gross_shadow_cash": gross_cash, "adjusted_price_units": dict(qty),
                               "deferred_target_units": dict(desired), "cumulative_fees": cumulative_fees},
            "status": "synthetic_candidate_account_complete",
            "cost_rate": cost_rate,
            "unit_kind": "synthetic_adjusted_price_units",
            "evidence_scope": "same_snapshot_adjusted_close_price_return_diagnostic_not_actual_fills_or_legal_shares_or_total_return",
            "gross_definition": "IDENTICAL_ADJUSTED_PRICE_UNIT_LEDGER_FEES_REFUNDED_TO_IDLE_CASH"}


def simulate_base_and_stress(calendar, market, targets, *, initial_cash=1., terminal=True, **kwargs):
    """60bp uses its own fee-aware quantities; not a pure-fee same-path replay."""
    return {"base30bp": simulate_account(calendar, market, targets, initial_cash=initial_cash, terminal=terminal, **kwargs),
            "stress60bp": simulate_account(calendar, market, targets, initial_cash=initial_cash, terminal=terminal, cost_rate=.006, **kwargs),
            "stress_comparison": "same_signal_rules_dates_constraints_independent_fee_aware_quantities_not_same_unit_path"}
