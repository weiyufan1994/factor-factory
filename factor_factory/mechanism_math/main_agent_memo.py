from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .formula_specific import BASELINE_MODEL_FAMILIES, build_formula_understanding


CONTRACT_VERSION = "factorforge_main_agent_mechanism_memo_v1"
QUESTIONNAIRE_VERSION = "factorforge_main_agent_mechanism_questionnaire_v1"
PRODUCER = "step6_main_agent"
MAX_TARGET_HORIZON = 4096
MAX_MECHANISM_MEMO_REVISIONS = 3
REQUIRED_QA_FIELDS = [
    "formula_state_answer",
    "economic_hypothesis_answer",
    "math_model_answer",
    "payer_answer",
    "payoff_answer",
    "estimator_mapping_answer",
    "metric_signature_answer",
    "falsification_answer",
]
REQUIRED_METRIC_SIGNATURE_FIELDS = {
    "rank_ic",
    "long_side",
    "cost_adjusted",
    "monotonicity",
    "turnover",
}

MODEL_FAMILY_ALIASES = {
    "price_volume_microstructure": "transient_impact",
    "price_volume_correlation": "copula_rank_dependence",
    "ranked_price_volume_state_process": "transient_impact",
    "behavioral_microstructure": "transient_impact",
    "liquidity_shock": "transient_impact",
    "linear_factor_projection": "projection_residualization",
    "projection": "projection_residualization",
    "residualization": "projection_residualization",
}

TRUSTED_INFORMATION_NAMES = frozenset(
    {
        "amount",
        "additive_score",
        "close",
        "control",
        "controls",
        "drift_state",
        "estimated_state",
        "factor",
        "formula_state",
        "high",
        "latent_state",
        "low",
        "open",
        "open_close_position_state",
        "participation_ratio",
        "pre_close",
        "process_state",
        "s",
        "score",
        "signal",
        "signed_price_state",
        "state",
        "temporary_pressure",
        "turnover_rate",
        "volume",
        "vwap",
        "x",
        "z",
    }
)


def normalize_derivation_model_family(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in BASELINE_MODEL_FAMILIES:
        return raw
    return MODEL_FAMILY_ALIASES.get(raw)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _nonempty_str_list(value: Any, min_count: int = 2) -> bool:
    return isinstance(value, list) and len([item for item in value if isinstance(item, str) and item.strip()]) >= min_count


def _has_explicit_forward_price_payoff(
    value: Any,
    allowed_information_names: set[str] | None = None,
) -> bool:
    payoff = _conditional_target_payoff(value, allowed_information_names)
    if payoff is None:
        return False
    price_term = (
        r"(?:close|open|vwap|price|p)"
        r"(?:_\{[^{}]+\}|\.shift\(-(?:[1-9][0-9]{0,3}|h|n)\))?"
    )
    payoff_pattern = re.compile(
        rf"(?P<numerator>{price_term})/"
        rf"(?P<denominator>{price_term})-1(?:\.0+)?"
    )
    match = payoff_pattern.fullmatch(payoff)
    if match is None:
        return False
    numerator = _price_term_time(match.group("numerator"))
    denominator = _price_term_time(match.group("denominator"))
    return _is_forward_price_ratio(numerator, denominator)


def _has_explicit_named_return_payoff(
    value: Any,
    allowed_information_names: set[str] | None = None,
) -> bool:
    payoff = _conditional_target_payoff(value, allowed_information_names)
    if payoff is None:
        return False
    named_return = re.fullmatch(
        r"(?:r|return|forward_return)_\{(?P<braced>[^{}]+)\}"
        r"|(?:r|return|forward_return)_(?P<identity>[a-z][a-z0-9_]*),"
        r"(?P<plain>t\+(?:[0-9]{1,4}|k|h|n)(?::t\+(?:[0-9]{1,4}|k|h|n))?)",
        payoff,
    )
    if named_return is None:
        return False
    index = named_return.group("braced")
    if index is None:
        identity = named_return.group("identity") or ""
        if _information_name_has_future_semantics(identity):
            return False
        return _is_forward_return_time_range(named_return.group("plain") or "")
    parts = index.split(",")
    if not parts or any(not part for part in parts):
        return False
    time_parts = [part for part in parts if _is_forward_return_time_range(part)]
    if len(time_parts) != 1:
        return False
    identities = [part for part in parts if part != time_parts[0]]
    return all(
        re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", part)
        and not _information_name_has_future_semantics(part)
        for part in identities
    )


def _is_forward_return_time_range(value: str) -> bool:
    normalized = value.replace("→", "->").replace(r"\to", "->")
    if ":" in normalized and "->" in normalized:
        return False
    parts = normalized.split("->") if "->" in normalized else normalized.split(":")
    if len(parts) not in {1, 2}:
        return False
    offsets: list[int | str] = []
    for part in parts:
        match = re.fullmatch(r"t\+(?P<offset>[0-9]{1,4}|k|h|n)", part)
        if match is None:
            return False
        offset = match.group("offset")
        if offset.isdigit():
            numeric = int(offset)
            if numeric <= 0 or numeric > MAX_TARGET_HORIZON:
                return False
            offsets.append(numeric)
        else:
            offsets.append(offset)
    if len(offsets) == 1:
        return True
    start, end = offsets
    if not isinstance(start, int):
        return False
    if not isinstance(end, int):
        return start == 1
    return end >= start


def _conditional_target_payoff(
    value: Any,
    allowed_information_names: set[str] | None,
) -> str | None:
    compact = (
        re.sub(r"\s+", "", str(value or "").lower())
        .replace("−", "-")
        .replace("→", "->")
        .replace(r"\to", "->")
    )
    trusted_information_names = set(TRUSTED_INFORMATION_NAMES)
    trusted_information_names.update(
        str(name).strip().lower()
        for name in (allowed_information_names or set())
        if re.fullmatch(r"[a-z][a-z0-9_]*", str(name).strip().lower())
    )
    body = _first_top_level_expectation_body(compact)
    if body is None or body.count("|") != 1:
        return None
    payoff, information_set = body.split("|", 1)
    if not _information_set_is_nonanticipative(
        information_set,
        trusted_information_names,
    ):
        return None
    return _strip_balanced_outer_parentheses(payoff)


def _information_set_is_nonanticipative(
    value: str,
    allowed_names: set[str],
) -> bool:
    items = _split_top_level_information_items(value)
    return bool(items) and any(_is_filtration_item(item) for item in items) and all(
        _is_nonanticipative_information_item(item, allowed_names) for item in items
    )


def _split_top_level_information_items(value: str) -> list[str] | None:
    pairs = {"{": "}", "(": ")"}
    stack: list[str] = []
    items: list[str] = []
    start = 0
    for index, character in enumerate(value):
        if character in pairs:
            stack.append(pairs[character])
        elif character in pairs.values():
            if not stack or stack.pop() != character:
                return None
        elif character in "[]":
            return None
        elif character == "," and not stack:
            item = value[start:index]
            if not item:
                return None
            items.append(item)
            start = index + 1
    if stack:
        return None
    final_item = value[start:]
    if not final_item:
        return None
    items.append(final_item)
    return items


def _is_nonanticipative_information_item(
    item: str,
    allowed_names: set[str],
) -> bool:
    if _is_filtration_item(item):
        return True
    shifted = re.fullmatch(
        r"(?P<name>[a-z][a-z0-9_]*)\.shift\((?:0|[1-9][0-9]{0,3}|k|h|n)\)",
        item,
    )
    if shifted is not None:
        return _information_name_is_admissible(shifted.group("name"), allowed_names)
    indexed = re.fullmatch(
        r"(?P<name>[a-z][a-z0-9_]*?)_"
        r"(?:\{(?P<braced>[^{}]+)\}|(?P<plain>t(?:-(?:[0-9]{1,4}|k|h|n))?))",
        item,
    )
    if indexed is None:
        return False
    name = indexed.group("name")
    if not _information_name_is_admissible(name, allowed_names):
        return False
    plain_time = indexed.group("plain")
    if plain_time is not None:
        return True
    parts = (indexed.group("braced") or "").split(",")
    if not parts or any(not part for part in parts):
        return False
    time_parts = [
        part
        for part in parts
        if re.fullmatch(r"t(?:-(?:[0-9]{1,4}|k|h|n))?", part)
    ]
    if len(time_parts) != 1:
        return False
    identities = [part for part in parts if part != time_parts[0]]
    return all(
        re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", part)
        and part != "f_t"
        and not _information_name_has_future_semantics(part)
        for part in identities
    )


def _is_filtration_item(item: str) -> bool:
    if re.fullmatch(
        r"(?:f_t|f_\{t\}|\\math(?:cal|scr)\{f\}_(?:t|\{t\}))",
        item,
    ) is not None:
        return True
    indexed = re.fullmatch(r"f_\{(?P<index>[^{}]+)\}", item)
    if indexed is None:
        return False
    parts = indexed.group("index").split(",")
    if len(parts) != 2 or not parts[0] or parts[1] != "t":
        return False
    identity = parts[0]
    return bool(
        re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", identity)
        and not _information_name_has_future_semantics(identity)
    )


def _information_name_is_admissible(name: str, allowed_names: set[str]) -> bool:
    return name in allowed_names and not _information_name_has_future_semantics(name)


def _information_name_has_future_semantics(name: str) -> bool:
    return re.search(
        r"(?:future|forward|fwd|target|label|outcome|next|lead|lookahead|tomorrow|(?:tp|tplus)0*[1-9][0-9]*)",
        name,
    ) is not None


def _first_top_level_expectation_body(value: str) -> str | None:
    square_depth = 0
    for index, character in enumerate(value):
        if character == "[":
            is_expectation = (
                index > 0
                and value[index - 1] == "e"
                and (index < 2 or not re.fullmatch(r"[a-z0-9_]", value[index - 2]))
            )
            if square_depth == 0 and is_expectation:
                depth = 1
                for end in range(index + 1, len(value)):
                    if value[end] == "[":
                        depth += 1
                    elif value[end] == "]":
                        depth -= 1
                        if depth == 0:
                            return value[index + 1 : end]
                return None
            square_depth += 1
        elif character == "]":
            square_depth -= 1
            if square_depth < 0:
                return None
    return None


def _strip_balanced_outer_parentheses(value: str) -> str:
    stripped = value
    while stripped.startswith("(") and stripped.endswith(")"):
        depth = 0
        closes_at_end = False
        for index, character in enumerate(stripped):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    return stripped
                if depth == 0:
                    closes_at_end = index == len(stripped) - 1
                    break
        if not closes_at_end:
            break
        stripped = stripped[1:-1]
    return stripped


def _price_term_time(
    term: str,
) -> tuple[str, int | str, tuple[str, ...]] | None:
    parsed = re.fullmatch(
        r"(?P<field>close|open|vwap|price|p)"
        r"(?:(?:_\{(?P<index>[^{}]+)\})|(?:\.shift\(-(?P<shift>[1-9][0-9]{0,3}|h|n)\)))?",
        term,
    )
    if parsed is None:
        return None
    field = parsed.group("field")
    shift = parsed.group("shift")
    if shift is not None:
        if shift.isdigit():
            numeric_shift = int(shift)
            return (field, numeric_shift, ()) if numeric_shift <= MAX_TARGET_HORIZON else None
        return field, shift, ()
    index = parsed.group("index")
    if index is None:
        return field, 0, ()
    index_parts = tuple(index.split(","))
    if any(not part for part in index_parts):
        return None
    time_parts = tuple(
        part
        for part in index_parts
        if re.fullmatch(r"t(?:[+-](?:[0-9]{1,4}|h|n))?", part)
    )
    if len(time_parts) != 1:
        return None
    time_part = time_parts[0]
    identities = tuple(part for part in index_parts if part != time_part)
    if not all(
        re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", part)
        for part in identities
    ):
        return None
    time_match = re.fullmatch(
        r"t(?:(?P<sign>[+-])(?P<offset>[0-9]{1,4}|h|n))?",
        time_part,
    )
    if time_match is None:
        return None
    sign = time_match.group("sign")
    offset = time_match.group("offset")
    if sign is None or offset is None:
        return field, 0, identities
    if not offset.isdigit():
        return (field, offset, identities) if sign == "+" else None
    numeric_offset = int(offset)
    if numeric_offset > MAX_TARGET_HORIZON:
        return None
    return (
        field,
        numeric_offset if sign == "+" else -numeric_offset,
        identities,
    )


def _is_forward_price_ratio(
    numerator: tuple[str, int | str, tuple[str, ...]] | None,
    denominator: tuple[str, int | str, tuple[str, ...]] | None,
) -> bool:
    if numerator is None or denominator is None:
        return False
    numerator_field, numerator_time, numerator_identity = numerator
    denominator_field, denominator_time, denominator_identity = denominator
    if numerator_identity != denominator_identity:
        return False
    if isinstance(numerator_time, str):
        return isinstance(denominator_time, int) and denominator_time <= 0
    if numerator_time <= 0 or not isinstance(denominator_time, int):
        return False
    if numerator_time > denominator_time:
        return True
    if numerator_time != denominator_time:
        return False
    same_day_order = {"open": 0, "vwap": 1, "close": 2}
    return (
        numerator_field in same_day_order
        and denominator_field in same_day_order
        and same_day_order[numerator_field] > same_day_order[denominator_field]
    )


def _canonical(factor_spec: dict[str, Any]) -> dict[str, Any]:
    return factor_spec.get("canonical_spec") if isinstance(factor_spec.get("canonical_spec"), dict) else factor_spec


def _formula_text(factor_spec: dict[str, Any]) -> str:
    canonical = _canonical(factor_spec or {})
    return str(
        canonical.get("formula_text")
        or canonical.get("raw_formula_text")
        or factor_spec.get("formula_text")
        or factor_spec.get("raw_formula_text")
        or ""
    )


def _operator_set(factor_spec: dict[str, Any], understanding: dict[str, Any] | None = None) -> set[str]:
    features = (understanding or {}).get("formula_features") or {}
    operators = {str(item).lower() for item in _as_list(features.get("operators")) if str(item).strip()}
    canonical = _canonical(factor_spec or {})
    operators.update(str(item).lower() for item in _as_list(canonical.get("operators") or canonical.get("operator_set")) if str(item).strip())
    return operators


def _field_set(factor_spec: dict[str, Any], understanding: dict[str, Any] | None = None) -> set[str]:
    features = (understanding or {}).get("formula_features") or {}
    fields = {str(item).lower() for item in _as_list(features.get("fields")) if str(item).strip()}
    canonical = _canonical(factor_spec or {})
    fields.update(str(item).lower() for item in _as_list(canonical.get("required_inputs") or canonical.get("required_fields")) if str(item).strip())
    return fields


def _formula_profile(formula: str, operators: set[str], fields: set[str]) -> dict[str, bool]:
    compact = re.sub(r"\s+", "", formula.lower())
    price_fields = {"close", "open", "high", "low", "vwap", "price"}
    has_price = bool(fields & price_fields) or any(f"{field}" in compact for field in price_fields)
    has_volume = "volume" in fields or "volume" in compact
    has_delta = "delta" in operators or "delta(" in compact
    has_sign = "sign" in operators or "sign(" in compact
    has_delay = "delay" in operators or "delay(" in compact
    has_rank = "rank" in operators or "rank(" in compact
    has_plus = bool(operators & {"plus", "add"}) or "plus(" in compact or "+" in formula
    has_divide = "divide" in operators or "divide(" in compact or "/" in formula
    has_sum_volume = "sum(volume" in compact or ("sum" in operators and has_volume)
    has_negate = "negate" in operators or "negate(" in compact or compact.startswith("-")
    has_signed_price_state = has_price and has_delta and has_sign
    has_volume_ratio = has_volume and has_sum_volume and has_divide
    has_open_close_position = has_price and "open" in fields and "close" in fields and (
        bool(operators & {"divide", "div", "minus", "negate", "signedpower"})
        or ("open" in compact and "close" in compact and "/" in formula)
    )
    return {
        "has_price": has_price,
        "has_volume": has_volume,
        "has_signed_price_state": has_signed_price_state,
        "has_volume_ratio": has_volume_ratio,
        "has_additive_score": has_plus and (has_rank or has_negate) and (has_signed_price_state or has_volume_ratio),
        "has_delay": has_delay,
        "has_rank": has_rank,
        "has_plus": has_plus,
        "has_open_close_position": has_open_close_position,
    }


def _observed_metrics(factor_case: dict[str, Any], evaluation_summary: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    candidates = [
        factor_case.get("headline_metrics"),
        factor_case.get("metrics"),
        (factor_case.get("evidence_summary") or {}).get("headline_metrics") if isinstance(factor_case.get("evidence_summary"), dict) else None,
        evaluation_summary.get("headline_metrics"),
        evaluation_summary.get("key_metrics"),
        evaluation_summary.get("metrics"),
    ]
    for item in evaluation_summary.get("backend_summary") or []:
        if isinstance(item, dict):
            candidates.append(item.get("key_metrics"))
    wanted = {
        "rank_ic_mean",
        "long_side_annual_return",
        "cost_adjusted_annual_return",
        "long_side_max_drawdown",
        "long_side_turnover_mean_daily",
        "turnover_mean",
        "daily_turnover",
        "group_top_decile_mean_return",
        "group_bottom_decile_mean_return",
        "group_g9_mean_return",
        "group_g10_mean_return",
        "g9_mean_return",
        "g10_mean_return",
    }
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key, value in candidate.items():
                if key in wanted or key.startswith("group_") or key.lower() in {"g9", "g10"}:
                    metrics[key] = value
    quantile_nav = evaluation_summary.get("quantile_nav") or factor_case.get("quantile_nav")
    if isinstance(quantile_nav, dict):
        metrics["quantile_nav"] = quantile_nav
    return metrics


def _numeric(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _evidence_comparison(observed: dict[str, Any]) -> dict[str, Any]:
    contradictions: list[str] = []
    implications: list[str] = []
    long_ret = _numeric(observed.get("long_side_annual_return"))
    cost_ret = _numeric(observed.get("cost_adjusted_annual_return"))
    g9 = _numeric(observed.get("group_g9_mean_return") or observed.get("g9_mean_return") or observed.get("group_9_mean_return"))
    g10 = _numeric(observed.get("group_g10_mean_return") or observed.get("g10_mean_return") or observed.get("group_top_decile_mean_return"))
    turnover = _numeric(observed.get("long_side_turnover_mean_daily") or observed.get("turnover_mean") or observed.get("daily_turnover"))
    if long_ret is not None and long_ret <= 0:
        contradictions.append("long-side annual return is non-positive")
    if cost_ret is not None and cost_ret <= 0:
        contradictions.append("cost-adjusted annual return is non-positive")
    if g9 is not None and g10 is not None and g9 > g10:
        contradictions.append("G9 exceeds G10, challenging high-score monotonicity")
    if turnover is not None and turnover > 0.5:
        contradictions.append("turnover is high relative to a short-horizon threshold mechanism")
    if contradictions:
        implications.extend([
            "test smoothing or persistence confirmation before promotion",
            "ablate reversal versus continuation sign interpretation",
            "test volume participation gate separately from raw additive score",
            "kill if high-score long side remains negative after costs",
        ])
    else:
        implications.extend([
            "Council should verify whether the apparent mechanism survives cost and monotonicity checks",
            "Council should ablate signed price state and participation-ratio state separately",
        ])
    supported = "no" if any("non-positive" in item or "G9" in item for item in contradictions) else ("partial" if observed else "partial")
    return {
        "observed_metrics": observed,
        "mechanism_supported": supported,
        "contradictions": contradictions,
        "revision_implications": implications,
        "kill_criteria_triggered": ["cost-adjusted high-score long side fails"] if cost_ret is not None and cost_ret <= 0 else [],
    }


def _generic_component_map(factor_spec: dict[str, Any], understanding: dict[str, Any], profile: dict[str, bool]) -> list[dict[str, Any]]:
    components = understanding.get("component_interpretations") or []
    out = []
    if profile.get("has_signed_price_state"):
        out.append({
            "component_id": "signed_price_state",
            "formula_subexpression": "formula terms using sign/delta over price observables",
            "operators": ["sign", "delta"] + (["delay"] if profile.get("has_delay") else []),
            "observable_estimator": "short-horizon signed price state",
            "economic_state": "short-horizon pressure, reversal, continuation, or threshold migration state",
            "mathematical_object": "discrete or threshold state variable",
            "expected_role": "state direction, bucket migration, and turnover pressure",
            "metric_link": "sign-state changes must be consistent with rank IC, group monotonicity, and turnover",
        })
    if profile.get("has_volume_ratio"):
        out.append({
            "component_id": "relative_volume_participation",
            "formula_subexpression": "formula terms comparing short-window volume with longer-window volume",
            "operators": ["sum", "divide", "volume"],
            "observable_estimator": "relative volume participation ratio",
            "economic_state": "participation intensity, liquidity demand, crowded attention, or shock intensity",
            "mathematical_object": "positive scale state",
            "expected_role": "gate or scale the price-state payoff by participation intensity",
            "metric_link": "high participation should improve or identify the claimed state only if long-side and cost-adjusted evidence support it",
        })
    if profile.get("has_open_close_position"):
        out.append({
            "component_id": "open_close_position_state",
            "formula_subexpression": "formula terms comparing open and close prices",
            "operators": sorted(op for op in ["divide", "minus", "negate", "signedpower", "rank"] if op in _operator_set(factor_spec, understanding)),
            "observable_estimator": "open/close relative price-location state",
            "economic_state": "overnight-to-intraday pressure, opening gap digestion, or close-location reversal state",
            "mathematical_object": "short-horizon price-location state variable",
            "expected_role": "test whether the cross-sectional open/close position predicts next-horizon drift or reversal after costs",
            "metric_link": "positive rank IC must translate into long-side and cost-adjusted evidence rather than only short-leg diagnostics",
        })
    if profile.get("has_additive_score") and len(out) >= 2:
        out.append({
            "component_id": "additive_score_combination",
            "formula_subexpression": "formula additive combination of ranked state terms and scale terms",
            "operators": ["rank", "plus"],
            "observable_estimator": "additive score combining rank-normalized state with raw or scaled observable terms",
            "economic_state": "combined latent score with scale commensurability risk",
            "mathematical_object": "additive latent-state proxy",
            "expected_role": "test whether the combined high-score state predicts next-period long-side payoff",
            "metric_link": "G10 should outperform if high-score state is monetizable; adjacent-group inversions challenge monotonicity",
        })
    if out:
        return out
    for index, item in enumerate(components):
        if not isinstance(item, dict):
            continue
        out.append({
            "component_id": str(item.get("component") or f"formula_component_{index+1}"),
            "formula_subexpression": str(item.get("formula_feature") or _formula_text(factor_spec) or "formula component"),
            "operators": _as_list(item.get("operators")) or _as_list(item.get("formula_operator")),
            "observable_estimator": str(item.get("formula_feature") or "formula-defined observable estimator"),
            "economic_state": str(item.get("economic_state") or "formula-defined latent state"),
            "mathematical_object": str(item.get("modelling_role") or "formula-specific state estimator"),
            "expected_role": str(item.get("modelling_role") or "estimate the state linked to next-period return"),
            "metric_link": "rank IC, long-side return, cost-adjusted return, monotonicity, and turnover must match this component's claimed role",
        })
    if out:
        return out
    return [{
        "component_id": "primary_formula_state",
        "formula_subexpression": _formula_text(factor_spec) or "formula",
        "operators": sorted(_operator_set(factor_spec, understanding)),
        "observable_estimator": "formula-defined observable estimator",
        "economic_state": "formula-defined latent return state",
        "mathematical_object": "conditional state variable",
        "expected_role": "estimate a state whose next-period payoff must be verified by Step4/5 metrics",
        "metric_link": "rank IC, long-side return, cost-adjusted return, monotonicity, and turnover must support the claimed state",
    }]


def build_main_agent_mechanism_questionnaire(
    *,
    report_id: str,
    factor_spec: dict[str, Any],
    factor_case: dict[str, Any],
    evaluation_summary: dict[str, Any],
    step6_iteration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the open-ended prompt packet for the currently active main agent.

    This object is intentionally not a mechanism answer. It contains formula
    facts, metric facts, and required questions. The LLM currently operating the
    skill must author the memo separately.
    """
    factor_spec = factor_spec or {}
    factor_case = factor_case or {}
    evaluation_summary = evaluation_summary or {}
    step6_iteration = step6_iteration or {}
    formula = _formula_text(factor_spec)
    understanding = build_formula_understanding(factor_spec)
    operators = sorted(_operator_set(factor_spec, understanding))
    fields = sorted(_field_set(factor_spec, understanding))
    profile = _formula_profile(formula, set(operators), set(fields))
    component_facts = _generic_component_map(factor_spec, understanding, profile)
    observed = _observed_metrics(factor_case, evaluation_summary)
    research_memo = ((step6_iteration.get("research_judgment") or {}).get("research_memo") or {})
    mechanism = research_memo.get("mechanism_analysis") if isinstance(research_memo.get("mechanism_analysis"), dict) else {}
    return {
        "contract_version": QUESTIONNAIRE_VERSION,
        "report_id": report_id,
        "factor_id": step6_iteration.get("factor_id") or factor_spec.get("factor_id") or factor_case.get("factor_id") or report_id,
        "created_at_utc": utc_now(),
        "producer": "step6_questionnaire_builder",
        "purpose": "current_main_agent_must_answer_open_questions_before_step6_finalization",
        "source_refs": {
            "factor_spec_master": f"objects/factor_spec_master/factor_spec_master__{report_id}.json",
            "factor_case_master": f"objects/factor_case_master/factor_case_master__{report_id}.json",
            "evaluation_summary": f"objects/validation/factor_evaluation__{report_id}.json",
            "candidate_research_iteration": "in_memory_run_step6_candidate_before_canonical_write",
        },
        "formula_facts": {
            "formula": formula,
            "fields": fields,
            "operators": operators,
            "formula_understanding": understanding,
            "component_facts": component_facts,
            "profile_flags": profile,
        },
        "upstream_hypothesis_context": {
            "mechanism_analysis": mechanism,
            "decision": (step6_iteration.get("research_judgment") or {}).get("decision"),
            "revision_strategy": research_memo.get("revision_strategy"),
        },
        "metric_facts": observed,
        "required_open_questions": [
            {
                "field": "formula_state_answer",
                "question": "What market state does this exact formula estimate, using its actual fields/operators rather than a factor-family label?",
            },
            {
                "field": "economic_hypothesis_answer",
                "question": "What economic hypothesis makes that state monetizable: risk premium, information advantage, market-structure harvesting, or mixed, and why?",
            },
            {
                "field": "math_model_answer",
                "question": "Which mathematical model is appropriate for this economic hypothesis, and how must that baseline model mutate to fit this formula?",
            },
            {
                "field": "payer_answer",
                "question": "Who is likely paying the return, and what constraint, belief error, risk transfer, or liquidity need makes them pay?",
            },
            {
                "field": "payoff_answer",
                "question": "What is the payoff sign, horizon, and expected-return argument conditional on the formula state?",
            },
            {
                "field": "estimator_mapping_answer",
                "question": "How does each formula component estimate the latent state in the model?",
            },
            {
                "field": "metric_signature_answer",
                "question": "What IC, long-side, cost-adjusted, monotonicity, and turnover signature should appear if the hypothesis is right?",
            },
            {
                "field": "falsification_answer",
                "question": "Which observed metrics or ablations would falsify the mechanism and force mutation or kill criteria?",
            },
        ],
        "answer_contract": {
            "memo_contract_version": CONTRACT_VERSION,
            "required_authoring_mode": "current_agent_freeform",
            "required_qa_fields": REQUIRED_QA_FIELDS,
            "deterministic_template_allowed": False,
            "current_agent_responsibility": "The agent invoking Factor Forge Ultimate must answer these questions before Council. Python may not synthesize the answer.",
        },
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }


def _default_math_hypothesis(
    *,
    profile: dict[str, bool],
    mechanism: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if profile.get("has_signed_price_state") and profile.get("has_volume_ratio"):
        return {
            "selected_model_family": contract.get("model_family") or mechanism.get("factor_family") or "transient_impact_or_threshold_process",
            "why_this_model": mechanism.get("mechanism_hypothesis") or "formula combines short-horizon signed price state with relative participation intensity",
            "why_not_generic_template": "model follows formula-derived signed-price and volume-ratio components rather than a generic price-volume template",
            "random_object": contract.get("random_object") or "security-day forward return conditional on formula state and information set F_t",
            "latent_state": contract.get("state_or_object") or "transient pressure / participation state",
            "process_or_distribution": (
                "P_i,t = F_i,t + I_i,t + epsilon_i,t, with I_i,t governed by a short-horizon "
                "signed price threshold state and scaled by relative volume participation."
            ),
            "target_functional": "E[r_i,t+1 | F_t, signed_price_state_i,t, participation_ratio_i,t, additive_score_i,t]",
            "formula_as_estimator": (
                "signed price-change terms estimate a discrete short-horizon price-pressure state; "
                "short-window versus longer-window volume aggregation terms estimate relative "
                "participation intensity; the additive score tests whether the combined state is "
                "monetizable after costs."
            ),
            "expected_metric_signature": {
                "rank_ic": "sign should match whether the threshold-pressure state is monetizable",
                "long_side": "high-score long side should produce positive return if the state is valid",
                "cost_adjusted": "cost-adjusted long side must survive turnover from threshold bucket migration",
                "monotonicity": "top group should exceed adjacent groups if the combined score is well ordered",
                "turnover": "sign and participation migration must not create cost-destroyed churn",
            },
        }
    if profile.get("has_open_close_position"):
        return {
            "selected_model_family": contract.get("model_family") or mechanism.get("factor_family") or "stochastic_process",
            "why_this_model": "formula maps open/close relative price location into a cross-sectional short-horizon state",
            "why_not_generic_template": "model follows formula-derived open/close price-location state rather than a generic liquidity or turnover template",
            "random_object": contract.get("random_object") or "security-day forward return conditional on open/close state and information set F_t",
            "latent_state": contract.get("state_or_object") or "overnight-to-intraday pressure or close-location reversal state",
            "process_or_distribution": (
                "P_i,t evolves through an opening price, intraday digestion path, and close price; "
                "the open/close location state may drift, reverse, or decay over the next horizon."
            ),
            "target_functional": "E[r_i,t+1 | F_t, open_close_position_state_i,t]",
            "formula_as_estimator": (
                "open/close relative price-location terms estimate an overnight-to-intraday pressure "
                "or close-location reversal state; the rank transform tests whether that state orders "
                "next-horizon returns cross-sectionally."
            ),
            "expected_metric_signature": {
                "rank_ic": "rank IC sign should match the declared open/close state direction",
                "long_side": "highest-score long side must be positive if the state is monetizable",
                "cost_adjusted": "cost-adjusted long side must survive high turnover from daily state refresh",
                "monotonicity": "quantile ordering should match the open/close state direction",
                "turnover": "daily open/close state turnover must not consume the payoff",
            },
        }
    return {
        "selected_model_family": contract.get("model_family") or mechanism.get("factor_family") or "other",
        "why_this_model": mechanism.get("mechanism_hypothesis") or "selected from Step6 mechanism analysis and formula understanding",
        "why_not_generic_template": "memo is tied to formula components, observed metrics, and falsification tests",
        "random_object": contract.get("random_object") or "security-day forward return conditional on formula state and information set F_t",
        "latent_state": contract.get("state_or_object") or "formula-specific latent state",
        "process_or_distribution": contract.get("process_hypothesis") or contract.get("process_or_distribution") or "future returns follow a conditional distribution indexed by the formula-defined state",
        "target_functional": contract.get("target_functional") or "E[r_i,t+1 | F_t, formula_state_i,t]",
        "formula_as_estimator": contract.get("factor_as_estimator") or "formula maps observable inputs into the declared latent state",
        "expected_metric_signature": {
            "rank_ic": "sign and persistence should match the declared return source",
            "long_side": "high-score long side must be positive if the state is monetizable",
            "cost_adjusted": "cost-adjusted long side must survive turnover and impact",
            "monotonicity": "group ordering should match the claimed state direction",
            "turnover": "turnover must be consistent with the stated horizon",
        },
    }


def _default_economic_hypothesis(*, profile: dict[str, bool], mechanism: dict[str, Any]) -> dict[str, Any]:
    if profile.get("has_signed_price_state") and profile.get("has_volume_ratio"):
        return {
            "return_source_class": mechanism.get("return_source") or "mixed",
            "payer_or_counterparty": "liquidity demanders, short-horizon extrapolators, or crowded attention accounts around formula-defined pressure states",
            "why_they_pay": mechanism.get("mechanism_hypothesis") or "they may pay temporary impact or delayed reversal costs when signed price state and high participation identify transient pressure",
            "necessary_market_structure": "; ".join(str(item) for item in _as_list(mechanism.get("necessary_conditions"))) or "short-horizon impact or threshold migration must reprice before turnover consumes the payoff",
        }
    if profile.get("has_open_close_position"):
        return {
            "return_source_class": mechanism.get("return_source") or "behavioral_microstructure",
            "payer_or_counterparty": "overnight extrapolators, opening auction liquidity demanders, or close-location chasers",
            "why_they_pay": "they anchor on the open-to-close price location or chase the intraday move, leaving next-horizon reversal or continuation payoff if the state is persistent enough after costs",
            "necessary_market_structure": "; ".join(str(item) for item in _as_list(mechanism.get("necessary_conditions"))) or "open/close location must predict next-horizon returns strongly enough to overcome daily turnover",
        }
    return {
        "return_source_class": mechanism.get("return_source") or "unknown",
        "payer_or_counterparty": "counterparty specified by Step6 mechanism analysis",
        "why_they_pay": mechanism.get("mechanism_hypothesis") or "the formula-specific state must explain why the other side pays",
        "necessary_market_structure": "; ".join(str(item) for item in _as_list(mechanism.get("necessary_conditions"))) or "necessary conditions require Council critique",
    }


def _structured_top_level_fields(economic: dict[str, Any], math: dict[str, Any], components: list[dict[str, Any]], qa: dict[str, Any] | None = None) -> dict[str, Any]:
    qa = qa if isinstance(qa, dict) else {}
    component_links = [
        {
            "component_id": str(item.get("component_id") or ""),
            "observable_estimator": str(item.get("observable_estimator") or ""),
            "latent_state_claim": str(item.get("economic_state") or ""),
        }
        for item in components
        if isinstance(item, dict) and (item.get("component_id") or item.get("observable_estimator") or item.get("economic_state"))
    ]
    signature = math.get("expected_metric_signature")
    if not isinstance(signature, dict) or not signature:
        signature = {
            "rank_ic": "rank IC must align with the declared payoff direction",
            "long_side": "high-score long side must be positive if the state is monetizable",
            "cost_adjusted": "cost-adjusted return must survive turnover and implementation costs",
            "monotonicity": "quantile ordering must match the stated direction",
            "turnover": "turnover must be consistent with the stated horizon",
        }
    falsification_text = str(qa.get("falsification_answer") or "")
    falsification_tests = [item.strip() for item in re.split(r"[;\n]", falsification_text) if item.strip()]
    if not falsification_tests:
        falsification_tests = [
            "Fail if high-score long-side evidence contradicts the declared payoff direction.",
            "Fail if cost-adjusted evidence remains negative after the formula-level mechanism repair.",
        ]
    return {
        "math_model_selection": {
            "model_family": str(math.get("selected_model_family") or math.get("model_family") or ""),
            "baseline_model": str(math.get("process_or_distribution") or ""),
            "model_mutation": str(math.get("why_this_model") or math.get("why_not_generic_template") or qa.get("math_model_answer") or ""),
        },
        "payer": {
            "payer_or_counterparty": str(economic.get("payer_or_counterparty") or ""),
            "why_they_pay": str(economic.get("why_they_pay") or ""),
            "necessary_market_structure": str(economic.get("necessary_market_structure") or ""),
        },
        "formula_state_estimator": {
            "latent_state": str(math.get("latent_state") or qa.get("formula_state_answer") or ""),
            "observable_mapping": str(math.get("formula_as_estimator") or qa.get("estimator_mapping_answer") or ""),
            "component_links": component_links,
        },
        "expected_metric_signature": signature,
        "falsification_tests": falsification_tests,
    }


def build_main_agent_mechanism_memo(
    *,
    report_id: str,
    factor_spec: dict[str, Any],
    factor_case: dict[str, Any],
    evaluation_summary: dict[str, Any],
    step6_iteration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    factor_spec = factor_spec or {}
    factor_case = factor_case or {}
    evaluation_summary = evaluation_summary or {}
    step6_iteration = step6_iteration or {}
    formula = _formula_text(factor_spec)
    understanding = build_formula_understanding(factor_spec)
    operators = _operator_set(factor_spec, understanding)
    fields = _field_set(factor_spec, understanding)
    profile = _formula_profile(formula, operators, fields)
    component_map = _generic_component_map(factor_spec, understanding, profile)
    observed = _observed_metrics(factor_case, evaluation_summary)
    evidence = _evidence_comparison(observed)
    mechanism = (((step6_iteration.get("research_judgment") or {}).get("research_memo") or {}).get("mechanism_analysis") or {})
    contract = mechanism.get("mechanism_math_contract") or factor_spec.get("mechanism_math_contract") or {}
    math_hypothesis = _default_math_hypothesis(profile=profile, mechanism=mechanism, contract=contract)
    economic = _default_economic_hypothesis(profile=profile, mechanism=mechanism)
    has_volume_ratio_expr = profile.get("has_volume_ratio") is True
    selected_model_family = str(math_hypothesis.get("selected_model_family") or "").lower()
    explicit_dependence_justification = None
    if (
        "price_volume" in selected_model_family
        and "volume" in fields
        and bool(fields & {"close", "open", "high", "low", "vwap", "price"})
    ):
        explicit_dependence_justification = (
            "Formula uses both price and volume observables and Step6 mechanism analysis "
            "selects price_volume_microstructure; this justifies a price-volume state claim "
            "without implying a correlation or covariance operator."
        )

    op_consistency = {
        "claims_correlation_or_covariance": False,
        "formula_has_correlation_or_covariance_operator": bool(operators & {"correlation", "corr", "covariance", "cov"}),
        "claims_dependence_without_operator_justification": False,
        "explicit_dependence_justification": explicit_dependence_justification,
        "has_sign_or_threshold": bool(operators & {"sign", "where"}) or "sign(" in formula.lower(),
        "sign_threshold_discussion_present": any(
            term in json.dumps(component_map + [math_hypothesis], ensure_ascii=False).lower()
            for term in ["threshold", "bucket", "migration", "turnover", "discontinu"]
        ),
        "has_volume_ratio": has_volume_ratio_expr,
        "volume_ratio_participation_discussion_present": any(
            term in json.dumps(component_map + [math_hypothesis, economic], ensure_ascii=False).lower()
            for term in ["relative participation", "participation intensity", "abnormal volume", "crowded attention"]
        ),
        "has_additive_rank_raw_ratio": (
            "rank" in operators
            and has_volume_ratio_expr
            and bool(operators & {"plus", "add"})
        ),
        "additive_scale_commensurability_discussion_present": any(
            term in json.dumps(component_map + [math_hypothesis], ensure_ascii=False).lower()
            for term in ["commensurability", "scale", "raw relative volume ratio"]
        ),
    }
    top_level = _structured_top_level_fields(economic, math_hypothesis, component_map, {})
    return {
        "contract_version": CONTRACT_VERSION,
        "report_id": report_id,
        "factor_id": step6_iteration.get("factor_id") or factor_spec.get("factor_id") or factor_case.get("factor_id") or report_id,
        "created_at_utc": utc_now(),
        "producer": "deterministic_memo_draft_builder",
        "agent_authorship": {
            "authoring_mode": "deterministic_scaffold_draft",
            "agent_role": "none",
            "answered_without_deterministic_template": False,
            "note": "This helper output is a draft scaffold only and is not accepted as the formal main-agent memo.",
        },
        "source_refs": {
            "factor_spec_master": f"objects/factor_spec_master/factor_spec_master__{report_id}.json",
            "factor_case_master": f"objects/factor_case_master/factor_case_master__{report_id}.json",
            "evaluation_summary": f"objects/validation/factor_evaluation__{report_id}.json",
            "research_iteration": f"objects/research_iteration_master/research_iteration_master__{report_id}.json",
            "mechanism_math_contract": "research_judgment.research_memo.mechanism_analysis.mechanism_math_contract",
        },
        "formula": formula,
        "formula_understanding": understanding,
        "formula_component_map": component_map,
        "mechanism_qa": {},
        "economic_hypothesis": economic,
        "math_hypothesis": math_hypothesis,
        **top_level,
        "evidence_comparison": evidence,
        "operator_claim_consistency": op_consistency,
        "council_questions": [
            "Critique whether the formula component mapping explains the measured long-side and cost-adjusted evidence.",
            "Challenge the selected mathematical model and propose a better model only if formula operators support it.",
            "Review payer derivation and evidence contradictions before proposing revision or kill recommendation.",
            "Test ablations that separate signed price state, volume participation, and additive-scale assumptions.",
        ],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }


def _require_open_answer(
    failures: list[str],
    qa: dict[str, Any],
    field: str,
    *,
    formula_terms: set[str],
    generic_terms: list[str],
) -> None:
    value = qa.get(field)
    text = str(value or "").strip().lower()
    if len(text) < 80:
        failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_INCOMPLETE:{field}")
        return
    if any(term in text for term in generic_terms):
        failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_GENERIC:{field}")
    if field in {"formula_state_answer", "estimator_mapping_answer"}:
        if formula_terms and not any(term in text for term in formula_terms):
            failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_NOT_FORMULA_SPECIFIC:{field}")


def formula_specific_derivation_from_main_agent_memo(memo: dict[str, Any], factor_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert an accepted freeform main-agent memo into Step6 derivation fields."""
    qa = memo.get("mechanism_qa") if isinstance(memo.get("mechanism_qa"), dict) else {}
    math = memo.get("math_hypothesis") if isinstance(memo.get("math_hypothesis"), dict) else {}
    economic = memo.get("economic_hypothesis") if isinstance(memo.get("economic_hypothesis"), dict) else {}
    components = memo.get("formula_component_map") if isinstance(memo.get("formula_component_map"), list) else []
    raw_model_family = str(math.get("selected_model_family") or math.get("model_family") or "other")
    model_family = normalize_derivation_model_family(raw_model_family) or raw_model_family
    payer = str(economic.get("payer_or_counterparty") or qa.get("payer_answer") or "")
    why = str(economic.get("why_they_pay") or qa.get("payer_answer") or "")
    payoff = str(math.get("target_functional") or qa.get("payoff_answer") or "")
    formula_state_link = "; ".join(
        str(item.get("component_id") or item.get("formula_subexpression") or "")
        for item in components
        if isinstance(item, dict)
    )
    falsification_tests = [
        item.strip()
        for item in re.split(r"[;\n]", str(qa.get("falsification_answer") or ""))
        if item.strip()
    ][:5]
    if len(falsification_tests) < 2:
        memo_tests = memo.get("falsification_tests")
        if isinstance(memo_tests, list):
            falsification_tests = [str(item).strip() for item in memo_tests if str(item).strip()][:5]
    if len(falsification_tests) < 2:
        falsification_tests = [
            "Fail if long-side evidence contradicts the declared payoff.",
            "Fail if component ablation contradicts the model.",
        ]
    return {
        "version": "factorforge_formula_specific_derivation_v1",
        "economic_to_math_model_selection": {
            "baseline_model_family": model_family,
            "why_selected_from_economic_hypothesis": str(qa.get("math_model_answer") or math.get("why_this_model") or ""),
            "why_not_generic_template": str(math.get("why_not_generic_template") or "The current main agent answered open mechanism questions for this formula before Council."),
            "model_mutations_for_this_formula": [
                str(qa.get("estimator_mapping_answer") or ""),
                str(qa.get("payoff_answer") or ""),
            ],
        },
        "profit_payer_derivation": {
            "payer_or_counterparty": payer,
            "why_they_pay": why,
            "mechanism_generating_profit": str(qa.get("economic_hypothesis_answer") or ""),
            "expected_payoff_expression_or_argument": str(qa.get("payoff_answer") or payoff),
            "economic_hypothesis_source": str(qa.get("economic_hypothesis_answer") or ""),
            "math_model_link": str(qa.get("math_model_answer") or ""),
            "formula_state_link": str(qa.get("estimator_mapping_answer") or formula_state_link),
        },
        "formula_components": [
            {
                "component": str(item.get("component_id") or f"component_{idx + 1}"),
                "formula_feature": str(item.get("formula_subexpression") or ""),
                "state_interpretation": str(item.get("economic_state") or item.get("observable_estimator") or ""),
                "mechanism_requirement": str(item.get("expected_role") or ""),
            }
            for idx, item in enumerate(components)
            if isinstance(item, dict)
        ],
        "latent_state_mapping": [
            {
                "observable_component": str(item.get("component_id") or f"component_{idx + 1}"),
                "latent_state_claim": str(item.get("economic_state") or ""),
                "estimator_mapping": str(item.get("observable_estimator") or ""),
            }
            for idx, item in enumerate(components)
            if isinstance(item, dict)
        ],
        "selected_model_family": model_family,
        "why_this_model_not_generic_template": str(math.get("why_not_generic_template") or qa.get("math_model_answer") or ""),
        "random_object": str(math.get("random_object") or "security-day forward return conditional on legal information set F_t"),
        "latent_state": str(math.get("latent_state") or qa.get("formula_state_answer") or ""),
        "process_or_distribution": str(math.get("process_or_distribution") or qa.get("math_model_answer") or ""),
        "target_functional": str(math.get("target_functional") or payoff or "E[r_i,t+1 | F_t, formula_state_i,t]"),
        "formula_as_estimator": str(math.get("formula_as_estimator") or qa.get("estimator_mapping_answer") or ""),
        "expected_metric_signature": str(qa.get("metric_signature_answer") or math.get("expected_metric_signature") or ""),
        "observed_metric_comparison": str(qa.get("metric_signature_answer") or ""),
        "metric_feedback_to_model": str(qa.get("falsification_answer") or ""),
        "falsification_tests": falsification_tests,
        "kill_criteria": [
            "Kill if no concrete payer remains after evidence review.",
            "Kill if long-only, cost-adjusted evidence stays negative after formula-level mutation.",
        ],
        "revision_implication": "Use only formula/model mutation after a specific answered derivation step is contradicted; do not repair through portfolio construction.",
    }


def _text_blob(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _string_values(nested)]
    return []


def _memo_claim_strings(memo: dict[str, Any]) -> list[str]:
    payload = {
        "formula_component_map": memo.get("formula_component_map"),
        "economic_hypothesis": memo.get("economic_hypothesis"),
        "math_hypothesis": memo.get("math_hypothesis"),
        "evidence_comparison": memo.get("evidence_comparison"),
        "council_questions": memo.get("council_questions"),
    }
    return _string_values(payload)


def _memo_claim_text(memo: dict[str, Any]) -> str:
    return "\n".join(_memo_claim_strings(memo)).lower()


def _claims_correlation_or_covariance_from_text(text: str) -> bool:
    token_pattern = (
        r"(?:correlat(?:e[sd]?|ed|ing|ion(?:s|al|ally)?|ive(?:ly)?)|"
        r"covari(?:ance(?:s)?|ant|ation(?:s)?)|corr|cov)"
    )
    token_re = re.compile(rf"(?<![a-z0-9_])({token_pattern})(?![a-z0-9_])")
    paired_terms = rf"{token_pattern}(?:\s*(?:/|or|and|或|、)\s*{token_pattern})?"
    absence_patterns = [
        re.compile(
            rf"^(?:the\s+)?(?:formula|expression|estimator|model|it)\s+"
            rf"(?:has|contains|uses|includes|implies)\s+no\s+(?:an?\s+)?"
            rf"(?P<target>{paired_terms})(?:\s+(?:operator|claim))?$"
        ),
        re.compile(
            rf"^(?:the\s+)?(?:formula|expression|estimator|model|it)\s+"
            rf"does\s+not\s+(?:use|contain|include|imply|estimate)\s+(?:an?\s+)?"
            rf"(?P<target>{paired_terms})(?:\s+(?:operator|claim))?$"
        ),
        re.compile(
            rf"^without\s+(?:implying|using|assuming|claiming)\s+"
            rf"(?P<target>{paired_terms})$"
        ),
        re.compile(
            rf"^(?P<target>{paired_terms})(?:\s+(?:operator|claim))?\s+"
            rf"(?:is|are)\s+"
            r"(?:absent|not\s+used|not\s+present)$"
        ),
        re.compile(
            rf"^(?:本)?(?:公式|表达式|模型|估计量)\s*(?:无|不含|未使用|没有)\s*"
            rf"(?P<target>{paired_terms})(?:\s*算子)?$"
        ),
    ]
    evaluation_re = re.compile(
        r"^(?:daily\s+)?cross-sectional\s+"
        r"(?:spearman|pearson)(?:\s*/\s*(?:spearman|pearson))?\s+"
        r"(?:rank\s+)?correlation\s+(?:of|between)\s+[^,;；。\n]{1,96}?\s+"
        r"(?:with|and)\s+(?:forward\s+return|r_[a-z0-9_,:+>\-]+)$"
    )

    normalized = str(text or "").lower().strip().rstrip(".!?。").rstrip()
    tokens = list(token_re.finditer(normalized))
    if not tokens:
        return False
    for pattern in absence_patterns:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        target_start, target_end = match.span("target")
        if all(target_start <= token.start() and token.end() <= target_end for token in tokens):
            return False
    if len(tokens) == 1 and evaluation_re.fullmatch(normalized):
        return False
    return True


def _claims_unjustified_dependence_from_text(text: str) -> bool:
    return any(
        term in text
        for term in [
            "dependence estimator",
            "rank dependence",
            "price-volume dependence",
            "co-movement",
            "co movement",
            "comovement",
        ]
    )


def _formula_has_correlation_or_covariance_operator(memo: dict[str, Any], factor_spec: dict[str, Any] | None = None) -> bool:
    understanding = memo.get("formula_understanding") if isinstance(memo.get("formula_understanding"), dict) else {}
    operators = _operator_set(factor_spec or {}, understanding)
    if operators & {"correlation", "corr", "covariance", "cov", "correlation()", "corr()", "covariance()", "cov()"}:
        return True
    formula = str(memo.get("formula") or _formula_text(factor_spec or {}) or "").lower()
    return bool(re.search(r"\b(correlation|corr|covariance|cov)\s*\(", formula))


def _justifies_correlation_or_covariance_claim(justification: Any) -> bool:
    text = str(justification or "").lower()
    if not text:
        return False
    if not any(term in text for term in ["correlation", "covariance", "corr", "cov"]):
        return False
    negating_terms = [
        "without implying",
        "does not imply",
        "not imply",
        "no correlation",
        "no covariance",
        "not correlation",
        "not covariance",
        "has no correlation",
        "has no covariance",
    ]
    if any(term in text for term in negating_terms):
        return False
    return any(
        term in text
        for term in [
            "mathematically equivalent",
            "equivalent to",
            "valid estimator",
            "estimator because",
            "justified because",
            "explicitly estimates",
        ]
    )


def validate_main_agent_mechanism_memo(memo: dict[str, Any], factor_spec: dict[str, Any] | None = None) -> list[str]:
    failures: list[str] = []
    if not isinstance(memo, dict) or not memo:
        return ["BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING"]
    if memo.get("contract_version") != CONTRACT_VERSION:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_CONTRACT_VERSION")
    if memo.get("canonical_write_permission") is True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_CANONICAL_WRITE_PERMISSION")
    if memo.get("execution_allowed_by_default") is True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXECUTION_ALLOWED")
    authorship = memo.get("agent_authorship") if isinstance(memo.get("agent_authorship"), dict) else {}
    if authorship.get("authoring_mode") != "current_agent_freeform":
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_NOT_CURRENT_AGENT_AUTHORED")
    if authorship.get("answered_without_deterministic_template") is not True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_DETERMINISTIC_TEMPLATE")
    if not str(authorship.get("agent_role") or "").strip():
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_AUTHOR_MISSING")
    qa = memo.get("mechanism_qa") if isinstance(memo.get("mechanism_qa"), dict) else {}
    if not qa:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_MISSING")
    formula_text = str(memo.get("formula") or _formula_text(factor_spec or {}) or "").lower()
    understanding = memo.get("formula_understanding") if isinstance(memo.get("formula_understanding"), dict) else {}
    trusted_understanding = build_formula_understanding(factor_spec or {})
    operators = _operator_set(factor_spec or {}, understanding)
    fields = _field_set(factor_spec or {}, understanding)
    trusted_information_fields = _field_set(factor_spec or {}, trusted_understanding)
    formula_terms = {
        term
        for term in set(re.findall(r"[a-z_][a-z0-9_]*", formula_text)) | operators | fields
        if term not in {"rank", "plus", "minus", "multiply", "divide", "negate", "signedpower"}
    }
    qa_generic_terms = [
        "investors",
        "market participants",
        "the factor captures alpha",
        "formula estimates the state",
        "generic payer",
        "under-specified",
        "counterparty specified by",
        "liquidity or turnover shock",
        "volume participation gate",
        "signed price state",
    ]
    for field in REQUIRED_QA_FIELDS:
        _require_open_answer(failures, qa, field, formula_terms=formula_terms, generic_terms=qa_generic_terms)
    components = memo.get("formula_component_map")
    if not isinstance(components, list) or not components:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_COMPONENT_MAP_MISSING")
    else:
        required_component = {"component_id", "formula_subexpression", "observable_estimator", "economic_state", "mathematical_object", "expected_role"}
        for component in components:
            if not isinstance(component, dict) or any(not str(component.get(key) or "").strip() for key in required_component):
                failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_COMPONENT_INCOMPLETE")
                break
    text = _text_blob(memo)
    generic_terms = [
        "formula estimates the state",
        "generic expected payoff",
        "counterparty implied",
        "under-specified counterparty",
    ]
    if any(term in text for term in generic_terms):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC")
    if any(term in text for term in ["deterministic_scaffold_draft", "deterministic_memo_draft_builder"]):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_DETERMINISTIC_TEMPLATE")
    math = memo.get("math_hypothesis") if isinstance(memo.get("math_hypothesis"), dict) else {}
    top_level_contract = {
        "math_model_selection": ("model_family", "baseline_model", "model_mutation"),
        "payer": ("payer_or_counterparty", "why_they_pay", "necessary_market_structure"),
        "formula_state_estimator": ("latent_state", "observable_mapping"),
    }
    for field, required_keys in top_level_contract.items():
        payload = memo.get(field)
        if not isinstance(payload, dict) or not payload:
            failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:{field}")
            continue
        for key in required_keys:
            if not str(payload.get(key) or "").strip():
                failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:{field}.{key}")
    top_signature = memo.get("expected_metric_signature")
    math_signature = math.get("expected_metric_signature")
    signatures_are_complete = all(
        isinstance(signature, dict)
        and REQUIRED_METRIC_SIGNATURE_FIELDS.issubset(signature)
        and all(
            isinstance(signature.get(field), str)
            and bool(signature.get(field).strip())
            for field in REQUIRED_METRIC_SIGNATURE_FIELDS
        )
        for signature in (top_signature, math_signature)
    )
    if not signatures_are_complete or top_signature != math_signature:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXPECTED_METRIC_SIGNATURE_MISSING")
    if not isinstance(top_signature, dict) or not top_signature:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:expected_metric_signature")
    if not _nonempty_str_list(memo.get("falsification_tests"), min_count=2):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:falsification_tests")
    selected_model_family = math.get("selected_model_family") or math.get("model_family")
    if normalize_derivation_model_family(selected_model_family) is None:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID")
    process = str(math.get("process_or_distribution") or "").lower()
    if not process or not any(term in process for term in ["=", "process", "distribution", "decay", "state", "follows", "conditional"]):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC")
    formula_tokens = {"rank", "delta", "sign", "sum", "divide", "plus", "minus", "multiply", "close", "volume"}
    if process and set(re.findall(r"[a-z_]+", process)) <= formula_tokens:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC")
    target = str(math.get("target_functional") or "").lower()
    if (
        not target
        or not (
            _has_explicit_named_return_payoff(
                target,
                allowed_information_names=trusted_information_fields,
            )
            or _has_explicit_forward_price_payoff(
                target,
                allowed_information_names=trusted_information_fields,
            )
        )
    ):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID")
    evidence = memo.get("evidence_comparison") if isinstance(memo.get("evidence_comparison"), dict) else {}
    observed = evidence.get("observed_metrics") if isinstance(evidence, dict) else {}
    if not isinstance(observed, dict) or not observed:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_EVIDENCE_COMPARISON_MISSING")
    op = memo.get("operator_claim_consistency") if isinstance(memo.get("operator_claim_consistency"), dict) else {}
    claim_strings = _memo_claim_strings(memo)
    claims_corr_cov = (
        op.get("claims_correlation_or_covariance") is True
        or any(_claims_correlation_or_covariance_from_text(item) for item in claim_strings)
    )
    claims_dependence = (
        op.get("claims_dependence_without_operator_justification") is True
        or any(_claims_unjustified_dependence_from_text(item.lower()) for item in claim_strings)
    )
    has_corr_cov_operator = (
        op.get("formula_has_correlation_or_covariance_operator") is True
        or _formula_has_correlation_or_covariance_operator(memo, factor_spec)
    )
    has_explicit_justification = bool(op.get("explicit_dependence_justification"))
    has_corr_cov_justification = _justifies_correlation_or_covariance_claim(op.get("explicit_dependence_justification"))
    if claims_corr_cov and not has_corr_cov_operator and not has_corr_cov_justification:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION")
    if claims_dependence and not has_corr_cov_operator and not has_explicit_justification:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION")
    if op.get("has_sign_or_threshold") is True and op.get("sign_threshold_discussion_present") is not True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_SIGN_DISCUSSION_MISSING")
    if op.get("has_volume_ratio") is True and op.get("volume_ratio_participation_discussion_present") is not True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_VOLUME_RATIO_DISCUSSION_MISSING")
    if op.get("has_additive_rank_raw_ratio") is True and op.get("additive_scale_commensurability_discussion_present") is not True:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_ADDITIVE_SCALE_DISCUSSION_MISSING")
    return list(dict.fromkeys(failures))


def render_main_agent_mechanism_memo_markdown(memo: dict[str, Any]) -> str:
    def bullets(items: Any) -> str:
        if isinstance(items, list):
            return "\n".join(f"- {json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item}" for item in items) or "- none"
        if isinstance(items, dict):
            return "\n".join(f"- {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in items.items()) or "- none"
        return f"- {items or 'none'}"

    return f"""# Main Agent Formula-Specific Mechanism Memo

Report ID: {memo.get('report_id')}

## Formula Component Map
{bullets(memo.get('formula_component_map'))}

## Economic Hypothesis
{bullets(memo.get('economic_hypothesis'))}

## Math Hypothesis
{bullets(memo.get('math_hypothesis'))}

## Evidence Comparison
{bullets(memo.get('evidence_comparison'))}

## Operator-Claim Consistency
{bullets(memo.get('operator_claim_consistency'))}

## Council Questions
{bullets(memo.get('council_questions'))}
"""


def render_main_agent_mechanism_questionnaire_markdown(questionnaire: dict[str, Any]) -> str:
    def bullets(items: Any) -> str:
        if isinstance(items, list):
            return "\n".join(f"- {json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item}" for item in items) or "- none"
        if isinstance(items, dict):
            return "\n".join(f"- {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in items.items()) or "- none"
        return f"- {items or 'none'}"

    return f"""# Main Agent Mechanism Questionnaire

Report ID: {questionnaire.get('report_id')}

This is not a mechanism memo. The currently active main agent must answer these
questions in `main_agent_mechanism_memo__<report_id>.json` before Step6 can
finalize or dispatch Council.

## Formula Facts
{bullets(questionnaire.get('formula_facts'))}

## Metric Facts
{bullets(questionnaire.get('metric_facts'))}

## Required Open Questions
{bullets(questionnaire.get('required_open_questions'))}

## Answer Contract
{bullets(questionnaire.get('answer_contract'))}
"""
