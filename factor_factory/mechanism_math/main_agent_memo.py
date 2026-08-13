from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ..formula.parser import parse_formula
from ..formula.registry import operator_meta
from ..knowledge_reference import validate_knowledge_reference_contract
from ..measurement_program import validate_measurement_program
from .formula_specific import BASELINE_MODEL_FAMILIES, build_formula_understanding


CONTRACT_VERSION = "factorforge_main_agent_mechanism_memo_v1"
QUESTIONNAIRE_VERSION = "factorforge_main_agent_mechanism_questionnaire_v1"
PRODUCER = "step6_main_agent"
MAX_TARGET_HORIZON = 4096
MAX_MECHANISM_MEMO_REVISIONS = 3
REQUIRED_QA_FIELDS = [
    "mathematical_object_answer",
    "economic_hypothesis_answer",
    "math_model_answer",
    "payer_answer",
    "payoff_answer",
    "observation_mapping_answer",
    "metric_signature_answer",
    "falsification_answer",
]
LEGACY_QA_FIELD_ALIASES = {
    "mathematical_object_answer": "formula_state_answer",
    "observation_mapping_answer": "estimator_mapping_answer",
}
REQUIRED_METRIC_SIGNATURE_FIELDS = {
    "rank_ic",
    "long_side",
    "cost_adjusted",
    "monotonicity",
    "turnover",
}
PUBLIC_MEMO_TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_version",
        "resume_attempt_id",
        "report_id",
        "factor_id",
        "research_id",
        "created_at_utc",
        "updated_at_utc",
        "revision_number",
        "producer",
        "agent_authorship",
        "source_refs",
        "formula",
        "formula_understanding",
        "formula_component_map",
        "mechanism_qa",
        "economic_hypothesis",
        "math_hypothesis",
        "math_model_selection",
        "payer",
        "mathematical_object_mapping",
        "formula_state_estimator",
        "expected_metric_signature",
        "falsification_tests",
        "evidence_comparison",
        "operator_claim_consistency",
        "council_questions",
        "canonical_write_permission",
        "execution_allowed_by_default",
    }
)
PUBLIC_MEMO_AUTHORSHIP_FIELDS = frozenset(
    {
        "authoring_mode",
        "agent_role",
        "runtime",
        "answered_without_deterministic_template",
        "note",
    }
)
PUBLIC_MEMO_QA_FIELDS = frozenset(
    {
        *REQUIRED_QA_FIELDS,
        *LEGACY_QA_FIELD_ALIASES.values(),
    }
)
PUBLIC_MEMO_ECONOMIC_FIELDS = frozenset(
    {
        "return_source_class",
        "payer_or_counterparty",
        "why_they_pay",
        "necessary_market_structure",
    }
)
PUBLIC_MEMO_MATH_FIELDS = frozenset(
    {
        "selected_model_family",
        "model_family",
        "why_this_model",
        "why_not_generic_template",
        "mathematical_object",
        "random_object",
        "latent_state",
        "mechanism_equation_or_functional",
        "process_or_distribution",
        "target_functional",
        "market_outcome_projection",
        "observation_mapping",
        "formula_as_estimator",
        "expected_metric_signature",
    }
)
PUBLIC_MEMO_MODEL_SELECTION_FIELDS = frozenset(
    {
        "model_family",
        "baseline_model",
        "mechanism_equation_or_functional",
        "model_mutation",
    }
)
PUBLIC_MEMO_PAYER_FIELDS = frozenset(
    {"payer_or_counterparty", "why_they_pay", "necessary_market_structure"}
)
PUBLIC_MEMO_OBJECT_MAPPING_FIELDS = frozenset(
    {
        "mathematical_object",
        "observation_mapping",
        "component_links",
        "latent_state",
        "observable_mapping",
    }
)
PUBLIC_MEMO_COMPONENT_FIELDS = frozenset(
    {
        "component_id",
        "formula_subexpression",
        "operators",
        "observable_estimator",
        "economic_state",
        "mathematical_object",
        "expected_role",
        "metric_link",
    }
)
PUBLIC_MEMO_FORMULA_UNDERSTANDING_FIELDS = frozenset(
    {
        "formula_understanding_version",
        "formula_features",
        "component_interpretations",
        "interaction_structure",
        "mathematical_object_candidates",
    }
)
PUBLIC_MEMO_FORMULA_FEATURE_FIELDS = frozenset(
    {
        "formula_text",
        "fields",
        "mechanism_observable_inputs",
        "mechanism_inputs_not_in_formula",
        "formula_missing_mechanism_inputs",
        "operators",
        "constants",
        "has_volume",
        "has_high_low",
        "has_sign_or_threshold",
        "has_long_window",
        "has_250_window",
        "has_short_delay_or_delta",
        "has_raw_additive",
        "has_open_close_position",
    }
)
PUBLIC_MEMO_FORMULA_COMPONENT_INTERPRETATION_FIELDS = frozenset(
    {"component", "formula_feature", "economic_state", "modelling_role"}
)
PUBLIC_MEMO_EVIDENCE_FIELDS = frozenset(
    {
        "observed_metrics",
        "observed_metric_conflict_keys",
        "mechanism_supported",
        "contradictions",
        "revision_implications",
        "kill_criteria_triggered",
    }
)
PUBLIC_MEMO_SOURCE_REF_FIELDS = frozenset(
    {
        "factor_spec_master",
        "factor_case_master",
        "evaluation_summary",
        "research_iteration",
        "mechanism_math_contract",
        "candidate_research_iteration",
    }
)
PUBLIC_MEMO_OBSERVED_METRIC_FIELDS = frozenset(
    {
        "metric_period",
        "rank_ic_mean",
        "rank_ic_std",
        "rank_ic_ir",
        "rank_icir",
        "pearson_ic_mean",
        "pearson_ic_std",
        "pearson_ic_ir",
        "fama_macbeth",
        "fama_macbeth_beta",
        "fama_macbeth_premium",
        "fama_macbeth_risk_premium",
        "fama_macbeth_t_stat",
        "fama_macbeth_tstat",
        "fama_macbeth_p_value",
        "long_side_return_daily",
        "long_side_annual_return",
        "long_side_annual_volatility",
        "long_side_sharpe",
        "cost_adjusted_annual_return",
        "cost_adjusted_return_daily",
        "cost_adjusted_long_side_sharpe",
        "cost_adjusted_long_side_max_drawdown",
        "cost_adjusted_long_side_recovery_days",
        "long_side_max_drawdown",
        "long_side_recovery_days",
        "long_side_turnover_mean_daily",
        "turnover_mean",
        "daily_turnover",
        "trading_cogs_daily",
        "trading_cogs_annual",
        "transaction_cost",
        "long_short_spread_mean",
        "long_short_spread_std",
        "long_short_spread_ir",
        "monotonicity",
        "monotonicity_score",
        "monotonicity_diagnostic",
        "decile_monotonicity",
        "quintile_monotonicity",
        "coverage_ratio",
        "coverage_rate",
        "valid_observation_ratio",
        "coverage_row_count",
        "coverage_date_count",
        "coverage_ticker_count",
        "coverage_period_count",
        "group_member_count_min",
        "group_member_count_median",
        "group_member_count_max",
        "long_end_return",
        "long_end_annual_return",
        "top_decile_mean_return",
        "bottom_decile_mean_return",
        "group_top_decile_mean_return",
        "group_bottom_decile_mean_return",
        "group_g9_mean_return",
        "group_g10_mean_return",
        "g9_mean_return",
        "g10_mean_return",
        *{f"group_{index}_mean_return" for index in range(1, 11)},
        *{f"decile_{index}_mean_return" for index in range(1, 11)},
        *{f"quintile_{index}_mean_return" for index in range(1, 6)},
        *{f"quantile_{index}_mean_return" for index in range(1, 11)},
        *{f"g{index}" for index in range(1, 11)},
    }
)
PUBLIC_MEMO_OBSERVED_STRING_METRIC_FIELDS = frozenset(
    {"metric_period", "monotonicity_diagnostic"}
)


def _is_public_observed_metric_key(key: str) -> bool:
    return key in PUBLIC_MEMO_OBSERVED_METRIC_FIELDS


def public_observed_metric_value_is_valid(key: str, value: Any) -> bool:
    if value is None:
        return True
    if key in PUBLIC_MEMO_OBSERVED_STRING_METRIC_FIELDS:
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value.bit_length() <= 1024
    return isinstance(value, float) and math.isfinite(value)


def project_public_observed_metrics(value: Any) -> dict[str, Any]:
    """Keep only scalar Host metrics accepted by the public memo contract."""
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in sorted(value.items())
        if _is_public_observed_metric_key(str(key))
        and public_observed_metric_value_is_valid(str(key), item)
    }


def project_public_observed_metric_conflict_keys(value: Any) -> list[str]:
    """Expose disputed metric names without publishing backend payloads."""
    if not isinstance(value, dict):
        return []
    conflicts: set[str] = set()
    recorded = value.get("backend_metric_conflicts")
    if isinstance(recorded, dict):
        conflicts.update(str(key) for key in recorded)
    conflicts.update(
        str(key)
        for key, item in value.items()
        if isinstance(item, dict) and item.get("status") == "backend_conflict"
    )
    return sorted(key for key in conflicts if _is_public_observed_metric_key(key))


PUBLIC_MEMO_OPERATOR_CONSISTENCY_FIELDS = frozenset(
    {
        "claims_correlation_or_covariance",
        "formula_has_correlation_or_covariance_operator",
        "claims_dependence_without_operator_justification",
        "explicit_dependence_justification",
        "has_sign_or_threshold",
        "sign_threshold_discussion_present",
        "has_volume_ratio",
        "volume_ratio_participation_discussion_present",
        "has_additive_rank_raw_ratio",
        "additive_scale_commensurability_discussion_present",
    }
)

MODEL_FAMILY_ALIASES = {
    "discounted cash-flow valuation": "valuation_identity",
    "discounted_cash_flow": "valuation_identity",
    "dcf": "valuation_identity",
    "residual-income valuation": "valuation_identity",
    "residual_income": "valuation_identity",
    # Accounting identities also support earnings-quality, cash-conversion,
    # capital-allocation, financing-constraint, and unit-economic mechanisms.
    # They become valuation identities only when the researcher explicitly
    # selects that model family; fundamental-domain routing alone is not enough.
    "accounting identity": "other",
    "accounting quality": "other",
    "unit economics": "other",
    "structural causal model": "other",
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


def _qa_answer(qa: dict[str, Any], field: str) -> Any:
    value = qa.get(field)
    if value not in (None, ""):
        return value
    legacy_field = LEGACY_QA_FIELD_ALIASES.get(field)
    return qa.get(legacy_field) if legacy_field else value


def _math_value(math: dict[str, Any], current: str, *legacy: str) -> Any:
    value = math.get(current)
    if value not in (None, ""):
        return value
    for field in legacy:
        value = math.get(field)
        if value not in (None, ""):
            return value
    return value


def formula_specific_qa_terms(
    formula_text: Any,
    *,
    operators: Any = (),
    fields: Any = (),
) -> set[str]:
    """Return the literal formula terms accepted by the open-answer gate."""
    operator_items = (
        operators
        if isinstance(operators, (set, frozenset))
        else _as_list(operators)
    )
    field_items = (
        fields if isinstance(fields, (set, frozenset)) else _as_list(fields)
    )
    return {
        term
        for term in (
            set(re.findall(r"[a-z_][a-z0-9_]*", str(formula_text or "").lower()))
            | {
                str(item).lower()
                for item in operator_items
                if str(item).strip()
            }
            | {
                str(item).lower()
                for item in field_items
                if str(item).strip()
            }
        )
        if term
        not in {
            "rank",
            "plus",
            "minus",
            "multiply",
            "divide",
            "negate",
            "signedpower",
        }
    }


def _nonempty_str_list(value: Any, min_count: int = 2) -> bool:
    return isinstance(value, list) and len([item for item in value if isinstance(item, str) and item.strip()]) >= min_count


def _has_explicit_forward_price_payoff(
    value: Any,
    allowed_information_names: set[str] | None = None,
    *,
    include_default_information_names: bool = True,
) -> bool:
    payoff = _conditional_target_payoff(
        value,
        allowed_information_names,
        include_default_information_names=include_default_information_names,
    )
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
    *,
    include_default_information_names: bool = True,
) -> bool:
    payoff = _conditional_target_payoff(
        value,
        allowed_information_names,
        include_default_information_names=include_default_information_names,
    )
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
    return end > start


def _conditional_target_payoff(
    value: Any,
    allowed_information_names: set[str] | None,
    *,
    include_default_information_names: bool = True,
) -> str | None:
    compact = (
        re.sub(r"\s+", "", str(value or "").lower())
        .replace("−", "-")
        .replace("→", "->")
        .replace(r"\to", "->")
    )
    trusted_information_names = (
        set(TRUSTED_INFORMATION_NAMES)
        if include_default_information_names
        else set()
    )
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
    normalized = str(name or "").strip().casefold()
    if re.fullmatch(r"[a-z][a-z0-9_]*", normalized) is None:
        return True
    tokens = normalized.split("_")
    future_tokens = {
        "following",
        "forward",
        "future",
        "fwd",
        "label",
        "later",
        "lead",
        "lookahead",
        "next",
        "outcome",
        "subsequent",
        "target",
        "tomorrow",
        "upcoming",
    }
    if any(token in future_tokens for token in tokens):
        return True
    if any(
        re.fullmatch(
            r"(?:following|forward|future|fwd|label|later|lookahead|next|outcome|"
            r"subsequent|target|tomorrow|upcoming)[a-z0-9]+",
            token,
        )
        for token in tokens
    ):
        return True
    if any(
        re.fullmatch(r"(?:t|tp)0*[1-9][0-9]*", token)
        or token.startswith("tplus") and token != "tpluszero"
        for token in tokens
    ):
        return True
    return bool(
        len(tokens) >= 2
        and tokens[-2] == "t"
        and re.fullmatch(r"0*[1-9][0-9]*", tokens[-1])
    )


def _state_rhs_is_trusted(
    rhs: str,
    *,
    observable_names: set[str],
    operator_names: set[str],
    strict_formula_registry: bool = False,
) -> bool:
    if strict_formula_registry:
        normalized = _normalize_current_observation_indices(
            rhs.strip(),
            observable_names,
        )
        if (
            normalized is None
            or not _formula_source_is_fully_represented(normalized)
        ):
            return False
        parsed = parse_formula(normalized)
        if parsed.get("parse_status") != "success":
            return False
        required_fields = {
            str(field).strip().casefold()
            for field in parsed.get("required_fields") or []
            if str(field).strip()
        }
        parsed_operators = {
            str(operator).strip().casefold()
            for operator in parsed.get("operator_set") or []
            if str(operator).strip()
        }
        structural_operators = {
            "divide",
            "minus",
            "multiply",
            "negate",
            "plus",
            "signedpower",
        }
        return bool(required_fields) and (
            required_fields <= observable_names
            and not any(
                _information_name_has_future_semantics(field)
                for field in required_fields
            )
            and parsed_operators <= operator_names | structural_operators
        )
    try:
        if len(rhs.encode("utf-8")) > 4_096:
            return False
        tree = ast.parse(rhs.strip(), mode="eval")
        nodes = list(ast.walk(tree))
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        SyntaxError,
        UnicodeError,
        ValueError,
    ):
        return False
    if len(nodes) > 512:
        return False

    safe_functions = {
        "abs",
        "clip",
        "exp",
        "kurtosis",
        "log",
        "log1p",
        "max",
        "mean",
        "min",
        "normalize",
        "pow",
        "rank",
        "signed_log1p",
        "skew",
        "sqrt",
        "standardize",
        "std",
        "sum",
        "var",
        "winsorize",
        "zscore",
    }
    allowed_functions = set(safe_functions)
    for operator in operator_names:
        normalized_operator = str(operator).strip().lower()
        if not normalized_operator:
            continue
        allowed_functions.add(normalized_operator)
        try:
            allowed_functions.update(
                str(alias).strip().lower()
                for alias in operator_meta(normalized_operator).get("aliases") or []
                if str(alias).strip()
            )
        except KeyError:
            continue
    allowed_dependencies = set(observable_names)

    allowed_node_types = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.IfExp,
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.Load,
        ast.keyword,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.UAdd,
        ast.USub,
        ast.Not,
        ast.And,
        ast.Or,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )
    if any(not isinstance(node, allowed_node_types) for node in nodes):
        return False

    function_node_ids: set[int] = set()
    temporal_keyword_names = {
        "lag",
        "offset",
        "period",
        "periods",
        "shift",
        "window",
    }
    safe_keyword_names = temporal_keyword_names | {
        "axis",
        "ddof",
        "keepdims",
        "limits",
        "lower",
        "min_periods",
        "standardize",
        "upper",
    }
    temporal_function_tokens = (
        "change",
        "delay",
        "delta",
        "diff",
        "difference",
        "lag",
        "shift",
    )
    for call in (node for node in nodes if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Name):
            return False
        function = call.func.id
        function_node_ids.add(id(call.func))
        if (
            re.fullmatch(r"[a-z][a-z0-9_]*", function) is None
            or function not in allowed_functions
            or _information_name_has_future_semantics(function)
            or any(
                token in function
                for token in ("bidirectional", "centered", "noncausal", "two_sided")
            )
        ):
            return False
        if any(keyword.arg is None for keyword in call.keywords):
            return False
        for keyword in call.keywords:
            if (
                keyword.arg is None
                or re.fullmatch(r"[a-z][a-z0-9_]*", keyword.arg) is None
                or keyword.arg not in safe_keyword_names
                or _information_name_has_future_semantics(keyword.arg)
                or any(
                    token in keyword.arg
                    for token in ("bidirectional", "center", "noncausal", "two_sided")
                )
            ):
                return False
            if keyword.arg in temporal_keyword_names and (
                not isinstance(keyword.value, ast.Constant)
                or isinstance(keyword.value.value, bool)
                or not isinstance(keyword.value.value, int)
                or keyword.value.value < 0
            ):
                return False
        if any(token in function for token in temporal_function_tokens):
            if len(call.args) == 2 and not call.keywords:
                offset = call.args[1]
            elif (
                len(call.args) == 1
                and len(call.keywords) == 1
                and call.keywords[0].arg in temporal_keyword_names
            ):
                offset = call.keywords[0].value
            else:
                return False
            if (
                not isinstance(offset, ast.Constant)
                or isinstance(offset.value, bool)
                or not isinstance(offset.value, int)
                or offset.value < 0
            ):
                return False

    data_dependencies: set[str] = set()
    for node in (node for node in nodes if isinstance(node, ast.Name)):
        if id(node) in function_node_ids:
            continue
        if (
            re.fullmatch(r"[a-z][a-z0-9_]*", node.id) is None
            or _information_name_has_future_semantics(node.id)
            or node.id not in allowed_dependencies
        ):
            return False
        data_dependencies.add(node.id)

    for node in (node for node in nodes if isinstance(node, ast.Constant)):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            return False
        if isinstance(node.value, float) and not math.isfinite(node.value):
            return False
    return bool(data_dependencies & allowed_dependencies)


def _declared_current_state_names(
    memo: dict[str, Any],
    observable_names: set[str],
    operator_names: set[str] | None = None,
    *,
    strict_formula_registry: bool = False,
) -> set[str]:
    math_payload = (
        memo.get("math_hypothesis")
        if isinstance(memo.get("math_hypothesis"), dict)
        else {}
    )
    equation = str(
        math_payload.get("mechanism_equation_or_functional")
        or math_payload.get("process_or_distribution")
        or ""
    ).lower()
    equation = equation.replace("−", "-").replace("→", "->")
    states: set[str] = set()
    assignment = re.compile(
        r"(?P<name>[a-z][a-z0-9_]*)_"
        r"(?:\{(?P<braced_index>[^{}]+)\}|(?P<plain_index>t))\s*="
    )
    allowed_operators = {
        str(operator).strip().lower()
        for operator in operator_names or set()
        if str(operator).strip()
    }
    for match in assignment.finditer(equation):
        name = match.group("name")
        index_parts = [
            part.strip()
            for part in (
                match.group("braced_index")
                or match.group("plain_index")
                or ""
            ).split(",")
        ]
        if (
            name in observable_names
            or _information_name_has_future_semantics(name)
            or index_parts.count("t") != 1
            or any(
                re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", item) is None
                for item in index_parts
            )
            or any(
                _information_name_has_future_semantics(item)
                for item in index_parts
                if item != "t"
            )
        ):
            continue
        end = equation.find(";", match.end())
        rhs = equation[match.end() : end if end >= 0 else len(equation)]
        if (
            not rhs.strip()
            or not _state_rhs_is_trusted(
                rhs,
                observable_names=set(observable_names) | states,
                operator_names=allowed_operators,
                strict_formula_registry=strict_formula_registry,
            )
        ):
            continue
        states.add(name)
    return states


def _has_future_temporal_reference(value: str) -> bool:
    text = str(value or "").lower().replace("−", "-")
    compact = re.sub(r"\s+", "", text)
    prose = re.sub(r"[-_]", " ", text)
    positive_number_word = (
        r"(?:one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
        r"eighty|ninety|hundred|thousand|[1-9][0-9]*|k|h|n)"
    )
    return bool(
        re.search(
            r"(?<![a-z0-9])t\s*\+\s*(?:0*[1-9][0-9]*|k|h|n)(?![a-z0-9])",
            text,
        )
        or re.search(
            r"(?<![a-z0-9])t\s*plus\s*(?:0*[1-9][0-9]*|k|h|n)(?![a-z0-9])",
            text,
        )
        or re.search(
            r"(?<![a-z0-9])tplus(?:0*[1-9][0-9]*|k|h|n)(?![a-z0-9])",
            text,
        )
        or re.search(r"t\^\{\+(?:0*[1-9][0-9]*|k|h|n)\}", compact)
        or re.search(
            r"\.shift\((?:periods=)?-0*[1-9][0-9]*(?:,[^)]*)?\)",
            compact,
        )
        or re.search(
            r"\b(?:shift|delay)\([^;)]*,(?:periods=)?-0*[1-9][0-9]*"
            r"(?:,[^)]*)?\)",
            compact,
        )
        or re.search(r"\b(?:lead|lookahead)\(", compact)
        or re.search(
            rf"\bt\s+(?:plus|after)\s+{positive_number_word}\b",
            prose,
        )
        or re.search(
            rf"(?<![a-z0-9])tplus{positive_number_word}(?![a-z0-9])",
            compact,
        )
        or re.search(
            r"(?<![a-z0-9_])t\s*\+\s*[a-z0-9]+\b",
            text,
        )
        or re.search(
            rf"\b(?:{positive_number_word}\s+)?(?:bar|bars|day|days|horizon|horizons|"
            r"minute|minutes|month|months|period|periods|session|sessions|"
            r"step|steps|week|weeks|year|years)\s+"
            r"(?:ahead|later|after|forward)\b",
            prose,
        )
        or re.search(
            r"\b(?:forthcoming|future|next|tomorrow|subsequent|following|"
            r"upcoming|lookahead)\b",
            prose,
        )
    )


def _contains_future_payoff_object(value: str) -> bool:
    raw = str(value or "").lower().replace("−", "-")
    text = re.sub(r"[_-]+", " ", raw)
    tokens = set(re.findall(r"[a-z][a-z0-9]*", text))
    has_future_semantics = bool(
        _has_future_temporal_reference(raw)
        or re.search(
            r"t\^\{\+(?:0*[1-9][0-9]{0,3}|k|h|n)\}",
            re.sub(r"\s+", "", raw),
        )
        or any(_information_name_has_future_semantics(term) for term in tokens)
    )
    has_payoff_semantics = any(
        re.search(r"(?:return|price|close|payoff|alpha|label|outcome)", term)
        for term in tokens
    ) or bool(
        re.search(
            r"(?<![a-z0-9_])(?:r|p)\s*(?:_\{|\(|_(?:tplus|t\+))",
            raw,
        )
    )
    return has_future_semantics and has_payoff_semantics


def _current_object_alias_names(value: str) -> set[str] | None:
    text = str(value or "").lower().replace("−", "-")
    aliases: set[str] = set()
    indexed_pattern = re.compile(
        r"(?<![a-z0-9_])(?P<name>[a-z][a-z0-9_]*)_\{(?P<index>[^{}]+)\}",
    )
    for match in indexed_pattern.finditer(text):
        parts = [item.strip() for item in match.group("index").split(",")]
        time_parts = [item for item in parts if item == "t"]
        identities = [item for item in parts if item not in time_parts]
        if len(time_parts) != 1 or not all(
            re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", item)
            and not _information_name_has_future_semantics(item)
            for item in identities
        ):
            return None
        aliases.add(match.group("name"))
    without_indexed = indexed_pattern.sub("", text)
    if any(character in without_indexed for character in "{}") or re.search(
        r"_\s+\{", text
    ):
        return None
    aliases.update(
        re.findall(
            r"(?<![a-z0-9_])(?P<name>[a-z][a-z0-9_]*)_t\b",
            without_indexed,
        )
    )
    return aliases


def _annotation_has_dependency_claim(value: str) -> bool:
    normalized = re.sub(r"[-']", " ", str(value or "").casefold())
    return bool(
        re.search(
            r"\b(?:based\s+on|conditioned|conditioning|conditional|depends?|"
            r"computed\s+from|dependencies|dependency|derived\s+from|"
            r"draws\s+on|estimates?|inputs?|incorporates?|incorporated|"
            r"incorporating|leverages?|maps?|needs?|powered\s+by|reads?|"
            r"relies\s+(?:on|upon)|relying\s+(?:on|upon)|requires?|sources?|"
            r"supplies?|uses?|using|via|with)\b",
            normalized,
        )
    )


def _plain_semantic_label(value: str, mathematical_object: str) -> bool:
    text = str(value or "").strip().rstrip(".,")
    if not text:
        return False
    try:
        encoded_length = len(text.encode("utf-8"))
    except UnicodeError:
        return False
    if encoded_length > 512:
        return False
    # Labels are object-bound domain prose, never executable syntax. The
    # expression prefix, not this prose, owns every data dependency.
    if (
        re.search(r"[\[\]{}()=+*/%<>]", text)
        or re.search(r"\s-\s|[a-z0-9]\.[a-z0-9]", text.casefold())
        or "_" in text
    ):
        return False
    words = re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", text.casefold())
    if not words or re.sub(r"[a-z0-9\s,.\-']", "", text.casefold()):
        return False
    for word in words:
        parts = re.split(r"[-']", word)
        if not (
            parts
            and all(part for part in parts)
            and (
                all(part.isalpha() for part in parts)
                or parts[0].isdecimal()
                and len(parts) > 1
                and all(part.isalpha() for part in parts[1:])
            )
        ):
            return False
    label_terms = {
        part
        for word in words
        for part in re.split(r"[-']", word)
        if part and part.isalpha()
    }
    object_terms = set(
        re.findall(r"[a-z][a-z0-9]*", str(mathematical_object or "").casefold())
    )
    structural_terms = {
        "a",
        "an",
        "and",
        "at",
        "best",
        "component",
        "components",
        "current",
        "day",
        "days",
        "direction",
        "feature",
        "for",
        "gap",
        "index",
        "level",
        "measure",
        "object",
        "observable",
        "observed",
        "of",
        "path",
        "proxy",
        "rally",
        "range",
        "ratio",
        "scale",
        "score",
        "semantic",
        "shape",
        "signal",
        "spike",
        "standardization",
        "standardized",
        "state",
        "t",
        "tail",
        "the",
        "value",
        "window",
        "windows",
    }
    normalized_words = re.sub(r"[-']", " ", text.casefold())
    return not (
        _annotation_has_dependency_claim(normalized_words)
        or _has_future_temporal_reference(normalized_words)
        or any(_information_name_has_future_semantics(term) for term in label_terms)
    ) and label_terms <= object_terms | structural_terms


def _canonical_formula_supports_valuation(
    canonical_formula_ir: dict[str, Any],
) -> bool:
    if canonical_formula_ir.get("parse_status") != "success":
        return False
    normalized_fields = {
        str(field).strip().casefold()
        for field in canonical_formula_ir.get("required_fields") or []
        if str(field).strip()
    }
    if not normalized_fields or any(
        _information_name_has_future_semantics(field)
        for field in normalized_fields
    ):
        return False

    direct_valuation_names = {
        "book_to_market",
        "dividend_yield",
        "earnings_to_price",
        "earnings_yield",
        "ebitda_yield",
        "ebit_yield",
        "ev_to_ebit",
        "ev_to_ebitda",
        "ev_to_sales",
        "fcf_yield",
        "market_to_book",
        "price_to_book",
        "price_to_cash_flow",
        "price_to_earnings",
        "price_to_fcf",
        "price_to_sales",
        "sales_to_price",
        "valuation_gap",
        "value_gap",
    }

    def is_direct_valuation_field(field: str) -> bool:
        return bool(
            field in direct_valuation_names
            or re.fullmatch(
                r"(?:ev|enterprise_value|market_cap|market_price|price)_to_"
                r"(?:book|cash_flow|ebit|ebitda|earnings|fcf|revenue|sales)",
                field,
            )
            or re.fullmatch(
                r"(?:book|cash_flow|dividend|ebit|ebitda|earnings|fcf|revenue|sales)_to_"
                r"(?:ev|enterprise_value|market_cap|market_price|price)",
                field,
            )
        )

    fundamental_value_names = {
        "book_equity",
        "book_value",
        "cash_flow",
        "dividend",
        "earnings",
        "ebit",
        "ebitda",
        "equity_value",
        "fcf",
        "forecast_fcf",
        "free_cash_flow",
        "intrinsic_value",
        "net_debt",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "residual_income",
        "residual_income_value",
        "revenue",
        "sales",
        "total_revenue",
    }
    fundamental_per_share_names = {
        "book_value_per_share",
        "dividend_per_share",
        "earnings_per_share",
        "eps",
        "fcf_per_share",
    }
    market_value_names = {
        "enterprise_value",
        "ev",
        "market_cap",
    }
    market_per_share_names = {
        "close",
        "market_price",
        "price",
    }
    share_count_names = {
        "diluted_shares_outstanding",
        "shares_outstanding",
        "weighted_average_shares",
    }
    discount_rate_names = {
        "cost_of_equity",
        "discount_rate",
        "growth_rate",
        "terminal_growth",
        "terminal_growth_rate",
        "wacc",
    }

    def field_role(field: str) -> str | None:
        if is_direct_valuation_field(field):
            return "direct"
        if field in fundamental_value_names:
            return "fundamental_value"
        if field in fundamental_per_share_names:
            return "fundamental_per_share"
        if field in market_value_names:
            return "market_value"
        if field in market_per_share_names:
            return "market_per_share"
        if field in share_count_names:
            return "shares"
        if field in discount_rate_names:
            return "discount"
        return None

    if any(field_role(field) is None for field in normalized_fields):
        return False

    def subtree_fields(node: Any) -> set[str]:
        if not isinstance(node, dict):
            return set()
        if node.get("type") == "field" and isinstance(node.get("name"), str):
            return {node["name"].casefold()}
        if node.get("type") != "operator":
            return set()
        return {
            field
            for arg in node.get("args") or []
            for field in subtree_fields(arg)
        }

    root = canonical_formula_ir.get("root")
    # Dimensions are powers of (currency, shares). A ratio is (0, 0), a
    # company-level value is (1, 0), and a per-share value is (1, -1).
    Dimension = tuple[int, int]
    ratio_dimension: Dimension = (0, 0)

    def static_numeric_value(node: Any) -> float | None:
        """Evaluate only algebraically certain constants used for liveness."""
        if not isinstance(node, dict):
            return None
        if node.get("type") == "constant":
            value = node.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            numeric = float(value)
            return numeric if math.isfinite(numeric) else None
        if node.get("type") != "operator":
            return None
        operator = str(node.get("operator") or "").casefold()
        args = node.get("args") or []
        identities = [_formula_ir_node_identity(arg) for arg in args]
        if operator == "minus" and len(args) == 2 and identities[0] == identities[1]:
            return 0.0
        if operator == "divide" and len(args) == 2 and identities[0] == identities[1]:
            return 1.0
        values = [static_numeric_value(arg) for arg in args]
        if operator == "negate" and len(values) == 1 and values[0] is not None:
            return -values[0]
        if operator == "abs" and len(values) == 1 and values[0] is not None:
            return abs(values[0])
        if operator in {"plus", "minus", "multiply", "divide"} and len(values) == 2:
            left, right = values
            if operator == "multiply" and (left == 0.0 or right == 0.0):
                return 0.0
            if left is None or right is None:
                return None
            if operator == "plus":
                return left + right
            if operator == "minus":
                return left - right
            if operator == "multiply":
                return left * right
            if right != 0.0:
                return left / right
        return None

    def valuation_dimensions(node: Any) -> set[Dimension]:
        if not isinstance(node, dict):
            return set()
        node_type = node.get("type")
        if node_type == "constant":
            return {ratio_dimension}
        if node_type == "field" and isinstance(node.get("name"), str):
            field = node["name"].casefold()
            role = field_role(field)
            if role in {"direct", "discount"}:
                return {ratio_dimension}
            if role in {"fundamental_value", "market_value"}:
                # Forecast aggregates may be supplied either company-wide or
                # per share; the rest of the expression must resolve the basis.
                return {(1, 0), (1, -1)} if field == "forecast_fcf" else {(1, 0)}
            if role in {"fundamental_per_share", "market_per_share"}:
                return {(1, -1)}
            if role == "shares":
                return {(0, 1)}
            return set()
        if node_type != "operator" or not isinstance(node.get("operator"), str):
            return set()
        operator = node["operator"].casefold()
        args = node.get("args") or []
        dimensions = [valuation_dimensions(arg) for arg in args]
        if any(not dimension for dimension in dimensions):
            return set()
        if operator in {"rank", "scale", "cs_zscore", "sign"}:
            return {ratio_dimension}
        if operator == "log":
            return {ratio_dimension} if dimensions == [{ratio_dimension}] else set()
        if operator in {"correlation", "ts_rank"}:
            return {ratio_dimension}
        if operator in {
            "abs",
            "argmax",
            "argmin",
            "delay",
            "delta",
            "max",
            "mean",
            "min",
            "negate",
            "stddev",
            "sum",
        }:
            return set.intersection(*dimensions) if dimensions else set()
        if operator == "covariance" and len(dimensions) == 2:
            return {
                (left[0] + right[0], left[1] + right[1])
                for left in dimensions[0]
                for right in dimensions[1]
            }
        if operator in {"plus", "minus"} and len(dimensions) == 2:
            return dimensions[0] & dimensions[1]
        if operator == "divide" and len(dimensions) == 2:
            return {
                (left[0] - right[0], left[1] - right[1])
                for left in dimensions[0]
                for right in dimensions[1]
            }
        if operator == "multiply" and len(dimensions) == 2:
            return {
                (left[0] + right[0], left[1] + right[1])
                for left in dimensions[0]
                for right in dimensions[1]
            }
        if operator == "signedpower" and len(args) == 2:
            exponent = args[1]
            if (
                exponent.get("type") == "constant"
                and isinstance(exponent.get("value"), int)
                and not isinstance(exponent.get("value"), bool)
            ):
                power = exponent["value"]
                return {
                    (dimension[0] * power, dimension[1] * power)
                    for dimension in dimensions[0]
                }
            return set()
        return set()

    def contains_valuation_ratio(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        # A valuation-looking subtree cannot authorize a formula when its
        # contribution is provably dead or the surrounding algebra is constant.
        if static_numeric_value(node) is not None:
            return False
        if node.get("type") == "field" and isinstance(node.get("name"), str):
            return field_role(node["name"].casefold()) == "direct"
        if node.get("type") != "operator":
            return False
        args = node.get("args") or []
        if node.get("operator") == "divide" and len(args) == 2:
            left_roles = {
                field_role(field) for field in subtree_fields(args[0])
            }
            right_roles = {
                field_role(field) for field in subtree_fields(args[1])
            }
            left_has_fundamental = bool(
                left_roles & {"fundamental_value", "fundamental_per_share"}
            )
            right_has_fundamental = bool(
                right_roles & {"fundamental_value", "fundamental_per_share"}
            )
            left_has_market = bool(
                left_roles & {"market_value", "market_per_share"}
            )
            right_has_market = bool(
                right_roles & {"market_value", "market_per_share"}
            )
            if ratio_dimension in valuation_dimensions(node) and (
                left_has_fundamental and right_has_market
                or left_has_market and right_has_fundamental
            ):
                return True
        return any(
            static_numeric_value(arg) is None and contains_valuation_ratio(arg)
            for arg in args
        )

    all_fields_are_direct_ratios = all(
        field_role(field) == "direct"
        for field in normalized_fields
    )
    return static_numeric_value(root) is None and ratio_dimension in valuation_dimensions(root) and (
        all_fields_are_direct_ratios
        or contains_valuation_ratio(root)
    )


def _valuation_projection_prose_is_safe(
    value: str,
    allowed_information_names: set[str],
) -> bool:
    text = str(value or "").strip().casefold()
    try:
        if len(text.encode("utf-8")) > 4_096:
            return False
    except UnicodeError:
        return False
    normalized = re.sub(r"\s+", " ", text).strip().rstrip(".")
    match = re.fullmatch(
        r"forward (?:return|payoff|alpha) from t\s*\+\s*"
        r"(?P<start>0*[1-9][0-9]*) to t\s*\+\s*"
        r"(?P<end>0*[1-9][0-9]*) (?:is|should be) "
        r"(?P<direction>positive|negative|increasing|decreasing|monotone) "
        r"(?:in|for) (?P<name>[a-z][a-z0-9_]*_t) under "
        r"(?:the )?(?:declared )?"
        r"(?P<mechanism>convergence|reversal|continuation|valuation) mechanism",
        normalized,
    )
    if match is None:
        return False
    start = int(match.group("start"))
    end = int(match.group("end"))
    name = match.group("name")[:-2]
    allowed = {
        str(item).strip().casefold()
        for item in allowed_information_names
        if str(item).strip()
    }
    return (
        0 < start < end <= MAX_TARGET_HORIZON
        and name in allowed
        and not _information_name_has_future_semantics(name)
        and not _has_future_temporal_reference(
            re.sub(
                r"from t\s*\+\s*[0-9]+ to t\s*\+\s*[0-9]+",
                "",
                normalized,
            )
        )
    )


def _parse_projection_offset(value: str) -> int | str | None:
    text = str(value or "")
    if text in {"k", "h", "n"}:
        return text
    if not text.isdigit() or len(text) > 6:
        return None
    try:
        numeric = int(text)
    except ValueError:
        return None
    return numeric if 0 < numeric <= MAX_TARGET_HORIZON else None


def _single_expectation_projection_suffix_is_safe(value: str) -> bool:
    text = (
        str(value or "").lower().replace("→", "->").replace(r"\to", "->")
    )
    markers = list(re.finditer(r"(?<![a-z0-9_])e\s*\[", text))
    if len(markers) != 1 or text[: markers[0].start()].strip():
        return False
    start = markers[0].end() - 1
    depth = 0
    end = None
    for index in range(start, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                end = index
                break
            if depth < 0:
                return False
    if end is None:
        return False
    body = text[start + 1 : end]
    payoff = _strip_balanced_outer_parentheses(
        re.sub(r"\s+", "", body.split("|", 1)[0])
    )
    price_term = (
        r"(?:close|open|vwap|price|p)"
        r"(?:_\{[^{}]+\}|\.shift\(-(?:[1-9][0-9]{0,3}|h|n)\))?"
    )
    payoff_match = re.fullmatch(
        rf"(?P<exit>{price_term})/(?P<entry>{price_term})-1(?:\.0+)?",
        payoff,
    )
    expected_exit = (
        _price_term_time(payoff_match.group("exit")) if payoff_match else None
    )
    expected_entry = (
        _price_term_time(payoff_match.group("entry")) if payoff_match else None
    )
    expected_named_range: tuple[int | str, int | str] | None = None
    named_return_detected = False
    if payoff_match is None:
        named_match = re.fullmatch(
            r"(?:r|return|forward_return)_\{(?P<braced>[^{}]+)\}"
            r"|(?:r|return|forward_return)_[a-z][a-z0-9_]*,"
            r"(?P<plain>t\+(?:0*[1-9][0-9]*|k|h|n)"
            r"(?:(?:->|:)t\+(?:0*[1-9][0-9]*|k|h|n))?)",
            payoff,
        )
        candidate_parts = (
            named_match.group("braced").split(",")
            if named_match and named_match.group("braced")
            else [named_match.group("plain")]
            if named_match and named_match.group("plain")
            else []
        )
        named_return_detected = bool(named_match)
        for index_part in candidate_parts:
            timing_match = re.fullmatch(
                r"t\+(?P<start>0*[1-9][0-9]*|k|h|n)"
                r"(?:(?:->|:)t\+(?P<end>0*[1-9][0-9]*|k|h|n))?",
                index_part,
            )
            if timing_match:
                start_text = timing_match.group("start")
                end_text = timing_match.group("end")
                parsed_start = _parse_projection_offset(start_text)
                parsed_end = _parse_projection_offset(end_text) if end_text else None
                if parsed_start is not None and parsed_end is not None:
                    expected_named_range = (parsed_start, parsed_end)
                break
    suffix = text[end + 1 :]
    if not suffix.strip():
        return False
    normalized_suffix = re.sub(
        r"\bt\s*\+\s*(?P<offset>0*[1-9][0-9]*|k|h|n)\b",
        lambda match: f" tplus{match.group('offset')} ",
        suffix,
    )
    clauses = [clause.strip() for clause in normalized_suffix.split(";")]
    if not clauses or any(not clause for clause in clauses):
        return False
    sign_clause = clauses[0].replace("-", " ")
    if re.search(r"[^a-z0-9_\s,.()']", sign_clause):
        return False
    sign_tokens = set(re.findall(r"[a-z_][a-z0-9_]*", sign_clause))
    sign_directions = {
        "continuation",
        "convergence",
        "decreasing",
        "higher",
        "increasing",
        "lower",
        "monotone",
        "negative",
        "positive",
        "reversal",
    }
    allowed_sign_tokens = sign_directions | {
        "and",
        "bottom",
        "crowding",
        "decile",
        "deciles",
        "factor",
        "for",
        "group",
        "groups",
        "high",
        "in",
        "long",
        "low",
        "measured",
        "object",
        "quintile",
        "quintiles",
        "rank",
        "short",
        "sign",
        "state",
        "than",
        "the",
        "top",
        "value",
        "values",
    }
    if not sign_tokens & sign_directions or not sign_tokens <= allowed_sign_tokens:
        return False
    signed_directions = sign_tokens & {"negative", "positive"}
    if any(
        pair <= sign_tokens
        for pair in (
            {"higher", "lower"},
            {"increasing", "decreasing"},
            {"continuation", "reversal"},
        )
    ):
        return False
    if len(signed_directions) > 1:
        binding_clause = re.sub(
            r"\((?![^()]*\b(?:positive|negative)\b)[^()]*\)",
            "",
            sign_clause,
        )
        binding_pattern = re.compile(
            r"\b(?P<direction>positive|negative)\s+for\s+"
            r"(?P<group>high|low)\b"
        )
        binding_matches = list(binding_pattern.finditer(binding_clause))
        bindings = [
            (match.group("direction"), match.group("group"))
            for match in binding_matches
        ]
        unmatched_binding_text = binding_pattern.sub("", binding_clause)
        if (
            len(bindings)
            != len(re.findall(r"\b(?:positive|negative)\b", binding_clause))
            or {group for _, group in bindings} != {"high", "low"}
            or any(
                len({group for bound_direction, group in bindings if bound_direction == direction})
                != 1
                for direction in signed_directions
            )
            or re.search(r"\b(?:positive|negative|high|low)\b", unmatched_binding_text)
        ):
            return False

    timing_seen = False
    information_seen = False
    for clause in clauses[1:]:
        timing_match = re.fullmatch(
            r"entry\s+tplus(?P<entry_offset>0*[1-9][0-9]*|k|h|n)\s+"
            r"(?P<entry_field>close|open|vwap|price)\s*,\s*exit\s+"
            r"tplus(?P<exit_offset>0*[1-9][0-9]*|k|h|n)\s+"
            r"(?P<exit_field>close|open|vwap|price)\s*,?",
            clause,
        )
        if timing_match:
            if timing_seen:
                return False
            entry_offset_text = timing_match.group("entry_offset")
            exit_offset_text = timing_match.group("exit_offset")
            entry_offset = _parse_projection_offset(entry_offset_text)
            exit_offset = _parse_projection_offset(exit_offset_text)
            if entry_offset is None or exit_offset is None:
                return False
            normalized_entry_field = timing_match.group("entry_field")
            normalized_exit_field = timing_match.group("exit_field")
            if expected_entry is not None and expected_exit is not None:
                expected_entry_field = (
                    "price" if expected_entry[0] == "p" else expected_entry[0]
                )
                expected_exit_field = (
                    "price" if expected_exit[0] == "p" else expected_exit[0]
                )
                if (
                    (normalized_entry_field, entry_offset)
                    != (expected_entry_field, expected_entry[1])
                    or (normalized_exit_field, exit_offset)
                    != (expected_exit_field, expected_exit[1])
                ):
                    return False
            elif expected_named_range is not None:
                if (
                    (entry_offset, exit_offset) != expected_named_range
                    or normalized_entry_field != normalized_exit_field
                    or isinstance(entry_offset, int)
                    and isinstance(exit_offset, int)
                    and exit_offset <= entry_offset
                ):
                    return False
            elif named_return_detected:
                return False
            elif not (
                isinstance(entry_offset, int)
                and isinstance(exit_offset, int)
                and exit_offset >= entry_offset
            ):
                return False
            timing_seen = True
            continue
        if re.fullmatch(
            r"f_t\s+holds\s+only\s+t(?:-(?:close|open|vwap|price))?\s+"
            r"(?:data|information)\s*[.,]?",
            clause,
        ):
            if information_seen:
                return False
            information_seen = True
            continue
        return False
    return not named_return_detected or timing_seen


def _normalize_current_observation_indices(
    value: str,
    observable_names: set[str],
    *,
    required_index_signatures: dict[str, tuple[str, ...]] | None = None,
) -> str | None:
    text = str(value or "").lower().replace("−", "-")
    if _has_future_temporal_reference(text):
        return None

    allowed_index_names = set(observable_names) | set(TRUSTED_INFORMATION_NAMES)
    required_signatures = required_index_signatures or {}

    def normalize_index_part(part: str) -> str:
        stripped = part.strip()
        return "t" if re.fullmatch(r"t\s*[+-]\s*0", stripped) else stripped

    def replace_indexed(match: re.Match[str]) -> str:
        name = match.group("name")
        index_parts = [
            normalize_index_part(item) for item in match.group("index").split(",")
        ]
        time_parts = [item for item in index_parts if item == "t"]
        identities = [item for item in index_parts if item not in time_parts]
        if (
            len(time_parts) != 1
            or name not in allowed_index_names
            and not re.fullmatch(r"[a-z]", name)
            or any(
                re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", item) is None
                or _information_name_has_future_semantics(item)
                for item in identities
            )
            or (
                name in required_signatures
                and tuple(index_parts) != required_signatures[name]
            )
            or (
                name in observable_names
                and name not in required_signatures
                and tuple(index_parts) not in {("t",), ("i", "t")}
            )
        ):
            return "__invalid_index__"
        return name

    text = re.sub(
        r"(?P<name>[a-z][a-z0-9_]*?)_\{(?P<index>[^{}]+)\}",
        replace_indexed,
        text,
    )
    for name in sorted(observable_names, key=len, reverse=True):
        plain_reference = re.search(
            rf"(?<![a-z0-9_]){re.escape(name)}_t\b",
            text,
        )
        if (
            plain_reference is not None
            and name in required_signatures
            and required_signatures[name] != ("t",)
        ):
            return None
        text = re.sub(
            rf"(?<![a-z0-9_]){re.escape(name)}_t\b",
            name,
            text,
        )
    if "__invalid_index__" in text or "{" in text or "}" in text:
        return None
    return text


def _formula_source_is_fully_represented(value: str) -> bool:
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeError:
        return False
    if "#" in value or encoded_length > 8_192:
        return False
    try:
        tree = ast.parse(value, mode="eval")
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        SyntaxError,
        UnicodeError,
        ValueError,
    ):
        return False
    ignored_keyword_names = {"with_one_col", "fill_predict", "dummies"}
    return not any(
        keyword.arg.casefold() in ignored_keyword_names
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg is not None
    )


def _observation_mapping_formula_contract(
    value: str,
    observable_names: set[str],
    mathematical_object: str,
) -> tuple[tuple[tuple[Any, ...], ...], frozenset[str]] | None:
    if _contains_future_payoff_object(value):
        return None
    normalized = _normalize_current_observation_indices(value, observable_names)
    if normalized is None:
        return None
    identities: list[tuple[Any, ...]] = []
    observed_fields: set[str] = set()
    for clause in re.split(r"[;\n]+", normalized):
        clause = clause.strip()
        if not clause:
            continue
        verb_matches = list(
            re.finditer(
                r"\b(?:estimates?|maps?|standardizes?|normalizes?|scales?|"
                r"transforms?|flips?|measures?|proxies?|captures?|"
                r"represents?)\b",
                clause,
            )
        )
        parsed_clause: tuple[str, str, dict[str, Any]] | None = None
        for verb_match in reversed(verb_matches):
            prefix = clause[: verb_match.start()].strip()
            description = clause[verb_match.end() :].strip()
            if (
                not prefix
                or not description
                or not _formula_source_is_fully_represented(prefix)
            ):
                continue
            parsed = parse_formula(prefix)
            if parsed.get("parse_status") == "success":
                parsed_clause = prefix, description, parsed
                break
        if parsed_clause is None:
            return None
        _, description, parsed = parsed_clause
        if (
            _contains_future_payoff_object(description)
            or any(
                _information_name_has_future_semantics(term)
                for term in re.findall(r"[a-z_][a-z0-9_]*", description)
            )
            or re.search(
                r"\b(?:input|inputs|dependency|dependencies|depends?|using|"
                r"supplies?|conditioned|conditioning|based\s+on|derived\s+from|"
                r"reads?|with|via|through|from|conditional|incorporates?|"
                r"incorporated|incorporating|requires?|relies\s+on|"
                r"relying\s+on|uses?|maps?)\b",
                description,
            )
            or not _plain_semantic_label(description, mathematical_object)
        ):
            return None
        required_fields = {
            str(field).strip().casefold()
            for field in parsed.get("required_fields") or []
            if str(field).strip()
        }
        if (
            not required_fields
            or not required_fields <= observable_names
            or any(
                _information_name_has_future_semantics(field)
                for field in required_fields
            )
        ):
            return None
        identity = _formula_ir_node_identity(parsed.get("root"))
        if identity is None:
            return None
        identities.append(identity)
        observed_fields.update(required_fields)
    if not identities:
        return None
    return tuple(identities), frozenset(observed_fields)


def _mathematical_object_binding_is_safe(
    value: str,
    _operator_names: set[str],
) -> bool:
    text = str(value or "").lower()
    try:
        if len(text.encode("utf-8")) > 4_096:
            return False
    except UnicodeError:
        return False
    if (
        _has_future_temporal_reference(text)
        or _annotation_has_dependency_claim(text)
        or "\\" in text
    ):
        return False
    terms = re.findall(r"[a-z][a-z0-9_]*", text)
    return not (
        any(_information_name_has_future_semantics(term) for term in terms)
        or "[" in text
        or "]" in text
        or "(" in text
        or ")" in text
        or "/*" in text
        or "*/" in text
        or re.search(r"\b[a-z][a-z0-9_]*\s*\.\s*[a-z][a-z0-9_]*\b", text)
    )


def _formula_ir_node_identity(node: Any) -> tuple[Any, ...] | None:
    if not isinstance(node, dict):
        return None
    node_type = node.get("type")
    if node_type == "field" and isinstance(node.get("name"), str):
        return ("field", node["name"].casefold())
    if node_type == "constant" and isinstance(node.get("value"), (int, float)):
        value = node.get("value")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return ("constant", "integer", value)
        if not math.isfinite(value):
            return None
        return ("constant", "float", value.hex())
    if node_type == "operator" and isinstance(node.get("operator"), str):
        args = node.get("args")
        if not isinstance(args, list):
            return None
        identities = [_formula_ir_node_identity(arg) for arg in args]
        if any(identity is None for identity in identities):
            return None
        return (
            "operator",
            node["operator"].casefold(),
            tuple(identities),
        )
    return None


def _formula_identity(value: str) -> tuple[Any, ...] | None:
    parsed = parse_formula(str(value or ""))
    if parsed.get("parse_status") != "success":
        return None
    return _formula_ir_node_identity(parsed.get("root"))


def _expanded_formula_ir_node_identity(
    node: Any,
    state_identities: dict[str, tuple[Any, ...]],
) -> tuple[Any, ...] | None:
    if not isinstance(node, dict):
        return None
    node_type = node.get("type")
    if node_type == "field" and isinstance(node.get("name"), str):
        name = node["name"].casefold()
        return state_identities.get(name, ("field", name))
    if node_type == "constant":
        return _formula_ir_node_identity(node)
    if node_type == "operator" and isinstance(node.get("operator"), str):
        args = node.get("args")
        if not isinstance(args, list):
            return None
        identities = [
            _expanded_formula_ir_node_identity(arg, state_identities)
            for arg in args
        ]
        if any(identity is None for identity in identities):
            return None
        return (
            "operator",
            node["operator"].casefold(),
            tuple(identities),
        )
    return None


def _current_state_formula_identities(
    memo: dict[str, Any],
    observable_names: set[str],
    operator_names: set[str],
) -> dict[tuple[str, tuple[str, ...]], tuple[Any, ...]] | None:
    math_payload = (
        memo.get("math_hypothesis")
        if isinstance(memo.get("math_hypothesis"), dict)
        else {}
    )
    equation = str(
        math_payload.get("mechanism_equation_or_functional")
        or math_payload.get("process_or_distribution")
        or ""
    ).casefold()
    equation = equation.replace("−", "-").replace("→", "->")
    assignment = re.compile(
        r"(?P<name>[a-z][a-z0-9_]*)_"
        r"(?:\{(?P<braced_index>[^{}]+)\}|(?P<plain_index>t))"
        r"\s*=\s*(?P<rhs>.+)"
    )
    state_identities: dict[str, tuple[Any, ...]] = {}
    state_signatures: dict[str, tuple[str, ...]] = {}
    state_bindings: dict[tuple[str, tuple[str, ...]], tuple[Any, ...]] = {}
    structural_operators = {
        "divide",
        "minus",
        "multiply",
        "negate",
        "plus",
        "signedpower",
    }
    allowed_operators = {
        str(operator).strip().casefold()
        for operator in operator_names
        if str(operator).strip()
    }
    clauses = [
        clause.strip()
        for clause in re.split(r"[;\n]+", equation)
        if clause.strip()
    ]
    for clause in clauses:
        match = assignment.fullmatch(clause)
        if match is None:
            return None
        name = match.group("name")
        index_parts = [
            (
                "t"
                if re.fullmatch(r"t\s*[+-]\s*0", part.strip())
                else part.strip()
            )
            for part in (
                match.group("braced_index")
                or match.group("plain_index")
                or ""
            ).split(",")
        ]
        if (
            name in state_identities
            or name in observable_names
            or _information_name_has_future_semantics(name)
            or index_parts.count("t") != 1
            or any(
                re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", item) is None
                or item != "t" and _information_name_has_future_semantics(item)
                for item in index_parts
            )
        ):
            return None
        rhs = match.group("rhs").strip()
        dependencies = set(observable_names) | set(state_identities)
        normalized = _normalize_current_observation_indices(
            rhs,
            dependencies,
            required_index_signatures=state_signatures,
        )
        if (
            not normalized
            or not _formula_source_is_fully_represented(normalized)
        ):
            return None
        parsed = parse_formula(normalized)
        if parsed.get("parse_status") != "success":
            return None
        required_fields = {
            str(field).strip().casefold()
            for field in parsed.get("required_fields") or []
            if str(field).strip()
        }
        parsed_operators = {
            str(operator).strip().casefold()
            for operator in parsed.get("operator_set") or []
            if str(operator).strip()
        }
        if (
            not required_fields
            or not required_fields <= dependencies
            or any(
                _information_name_has_future_semantics(field)
                for field in required_fields
            )
            or not parsed_operators <= allowed_operators | structural_operators
        ):
            return None
        identity = _expanded_formula_ir_node_identity(
            parsed.get("root"),
            state_identities,
        )
        if identity is not None:
            state_identities[name] = identity
            state_signatures[name] = tuple(index_parts)
            state_bindings[(name, tuple(index_parts))] = identity
        else:
            return None
    return state_bindings


def _current_indexed_identifier_references(
    value: str,
) -> set[tuple[str, tuple[str, ...]]] | None:
    text = str(value or "").casefold().replace("−", "-")
    try:
        if len(text.encode("utf-8")) > 8_192:
            return None
    except UnicodeError:
        return None
    if re.search(
        r"\b[a-z][a-z0-9_]*\s*\.\s*(?:delay|lag|shift)\s*\(\s*0\s*\)",
        text,
    ) or re.search(
        r"\b(?:delay|lag|shift)\s*\([^,;()]+,\s*0\s*\)",
        text,
    ):
        return None
    references: set[tuple[str, tuple[str, ...]]] = set()
    indexed_pattern = re.compile(
        r"(?P<name>[a-z][a-z0-9_]*?)_\{(?P<index>[^{}]+)\}",
    )
    for match in indexed_pattern.finditer(text):
        name = match.group("name")
        index_parts = [
            (
                "t"
                if re.fullmatch(r"t\s*[+-]\s*0", part.strip())
                else part.strip()
            )
            for part in match.group("index").split(",")
        ]
        if (
            index_parts.count("t") != 1
            or any(
                re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", part) is None
                or part != "t" and _information_name_has_future_semantics(part)
                for part in index_parts
            )
            or _information_name_has_future_semantics(name)
        ):
            return None
        references.add((name, tuple(index_parts)))
    without_indexed = indexed_pattern.sub("", text)
    if any(character in without_indexed for character in "{}"):
        return None
    if re.search(
        r"(?<![a-z0-9_])[a-z][a-z0-9_]*_t(?:plus[a-z0-9]+|_[0-9]+|0*[1-9][0-9]*)\b",
        without_indexed,
    ):
        return None
    references.update(
        (match.group("name"), ("t",))
        for match in re.finditer(
            r"(?<![a-z0-9_])(?P<name>[a-z][a-z0-9_]*)_t(?![a-z0-9_])",
            without_indexed,
        )
        if not _information_name_has_future_semantics(match.group("name"))
    )
    return references


def _current_indexed_identifier_names(value: str) -> set[str] | None:
    references = _current_indexed_identifier_references(value)
    if references is None:
        return None
    return {name for name, _ in references}


def _mechanism_equation_binds_formula_root(
    memo: dict[str, Any],
    canonical_formula_ir: dict[str, Any],
) -> bool:
    if canonical_formula_ir.get("parse_status") != "success":
        return False
    canonical_identity = _formula_ir_node_identity(canonical_formula_ir.get("root"))
    if canonical_identity is None:
        return False
    observable_names = {
        str(field).strip().casefold()
        for field in canonical_formula_ir.get("required_fields") or []
        if str(field).strip()
    }
    operator_names = {
        str(operator).strip().casefold()
        for operator in canonical_formula_ir.get("operator_set") or []
        if str(operator).strip()
    }
    state_identities = _current_state_formula_identities(
        memo,
        observable_names,
        operator_names,
    )
    if not state_identities:
        return False
    math_payload = (
        memo.get("math_hypothesis")
        if isinstance(memo.get("math_hypothesis"), dict)
        else {}
    )
    projection = str(math_payload.get("market_outcome_projection") or "")
    expectation_body = _first_top_level_expectation_body(projection.casefold())
    projection_object_text = projection
    if expectation_body is not None and expectation_body.count("|") == 1:
        # Payoff-side t+1/t+2 prices are deliberately future-valued. Root
        # binding concerns only the legal conditioning/current-object side.
        projection_object_text = expectation_body.split("|", 1)[1]
    projected_references = _current_indexed_identifier_references(
        projection_object_text
    )
    if projected_references is None:
        return False
    projected_references = {
        reference for reference in projected_references if reference[0] != "f"
    }
    if (
        not projected_references
        or not projected_references <= set(state_identities)
    ):
        return False
    return all(
        state_identities[reference] == canonical_identity
        for reference in projected_references
    )


def _measurement_program_observation_binds_formula_root(
    program: dict[str, Any] | None,
    canonical_formula_ir: dict[str, Any],
) -> bool:
    if (
        not isinstance(program, dict)
        or canonical_formula_ir.get("parse_status") != "success"
    ):
        return False
    observation = program.get("observation_and_estimation")
    if not isinstance(observation, dict):
        return False
    expression = str(observation.get("observation_map") or "").strip().casefold()
    try:
        expression.encode("utf-8")
    except UnicodeError:
        return False
    assignment = re.fullmatch(
        r"(?P<name>[a-z][a-z0-9_]*)_"
        r"(?:\{(?P<braced_index>[^{}]+)\}|(?P<plain_index>t))"
        r"\s*=\s*(?P<rhs>.+)",
        expression,
    )
    if assignment:
        name = assignment.group("name")
        index_parts = [
            (
                "t"
                if re.fullmatch(r"t\s*[+-]\s*0", part.strip())
                else part.strip()
            )
            for part in (
                assignment.group("braced_index")
                or assignment.group("plain_index")
                or ""
            ).split(",")
        ]
        selected_model = _selected_measurement_program_model(program) or {}
        selected_object_references: set[tuple[str, tuple[str, ...]]] = set()
        for field in ("mathematical_object", "target_functional"):
            references = _current_indexed_identifier_references(
                str(selected_model.get(field) or "")
            )
            if references is None:
                return False
            selected_object_references.update(references)
        selected_object_references = {
            reference
            for reference in selected_object_references
            if reference[0] != "f"
        }
        assignment_reference = (name, tuple(index_parts))
        estimand_references = _current_indexed_identifier_references(
            str(observation.get("estimand") or "")
        )
        projection = program.get("market_outcome_projection")
        source_references = _current_indexed_identifier_references(
            str(
                projection.get("source_math_object")
                if isinstance(projection, dict)
                else ""
            )
        )
        observable_names = {
            str(field).strip().casefold()
            for field in canonical_formula_ir.get("required_fields") or []
            if str(field).strip()
        }
        if (
            _information_name_has_future_semantics(name)
            or name in observable_names
            or index_parts.count("t") != 1
            or estimand_references is None
            or source_references is None
            or any(
                re.fullmatch(r"(?:[a-z][a-z0-9_]*|[0-9]+)", part) is None
                or part != "t" and _information_name_has_future_semantics(part)
                for part in index_parts
            )
            or assignment_reference not in selected_object_references
            or assignment_reference not in estimand_references
            or assignment_reference not in source_references
        ):
            return False
        expression = assignment.group("rhs").strip()
    elif "=" in expression:
        return False
    observable_names = {
        str(field).strip().casefold()
        for field in canonical_formula_ir.get("required_fields") or []
        if str(field).strip()
    }
    normalized = _normalize_current_observation_indices(
        expression,
        observable_names,
    )
    if (
        not normalized
        or not _formula_source_is_fully_represented(normalized)
    ):
        return False
    parsed = parse_formula(normalized)
    return (
        parsed.get("parse_status") == "success"
        and _formula_ir_node_identity(parsed.get("root"))
        == _formula_ir_node_identity(canonical_formula_ir.get("root"))
    )


def _formula_subtree_identities(node: Any) -> tuple[tuple[Any, ...], ...]:
    identity = _formula_ir_node_identity(node)
    if identity is None or not isinstance(node, dict):
        return ()
    identities = [identity]
    if node.get("type") == "operator":
        for arg in node.get("args") or []:
            identities.extend(_formula_subtree_identities(arg))
    return tuple(identities)


def _linked_component_formula_contract(
    memo: dict[str, Any],
    factor_spec: dict[str, Any],
) -> tuple[
    tuple[tuple[Any, ...], ...],
    frozenset[str],
    frozenset[str],
] | None:
    mapping = memo.get("mathematical_object_mapping")
    components = memo.get("formula_component_map")
    if not isinstance(mapping, dict) or not isinstance(components, list):
        return None
    links = mapping.get("component_links")
    if (
        not isinstance(links, list)
        or not links
        or "formula_root" not in links
        or any(not isinstance(item, str) or not item.strip() for item in links)
        or len(links) != len(set(links))
    ):
        return None
    component_by_id: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict):
            return None
        component_id = component.get("component_id")
        if (
            not isinstance(component_id, str)
            or not component_id.strip()
            or component_id in component_by_id
        ):
            return None
        component_by_id[component_id] = component
    if not set(links) <= set(component_by_id):
        return None
    canonical_formula = _formula_text(factor_spec)
    if not _formula_source_is_fully_represented(canonical_formula):
        return None
    canonical_ir = parse_formula(canonical_formula)
    if canonical_ir.get("parse_status") != "success":
        return None
    canonical_identity = _formula_ir_node_identity(canonical_ir.get("root"))
    canonical_fields = frozenset(
        str(field).strip().casefold()
        for field in canonical_ir.get("required_fields") or []
        if str(field).strip()
    )
    canonical_operators = frozenset(
        str(operator).strip().casefold()
        for operator in canonical_ir.get("operator_set") or []
        if str(operator).strip()
    )
    canonical_subtrees = Counter(
        _formula_subtree_identities(canonical_ir.get("root"))
    )
    if canonical_identity is None:
        return None
    linked_identities: list[tuple[Any, ...]] = []
    for component_id in links:
        component_formula = str(
            component_by_id[component_id].get("formula_subexpression") or ""
        )
        if not _formula_source_is_fully_represented(component_formula):
            return None
        component_identity = _formula_identity(component_formula)
        if component_identity is None or (
            component_id == "formula_root"
            and component_identity != canonical_identity
        ) or (
            component_id != "formula_root"
            and canonical_subtrees[component_identity] == 0
        ):
            return None
        linked_identities.append(component_identity)
    if not Counter(linked_identities) <= canonical_subtrees:
        return None
    return tuple(linked_identities), canonical_fields, canonical_operators


def _bound_measured_object_projection_aliases(
    memo: dict[str, Any],
    factor_spec: dict[str, Any],
) -> set[str]:
    math_payload = (
        memo.get("math_hypothesis")
        if isinstance(memo.get("math_hypothesis"), dict)
        else {}
    )
    object_mapping = (
        memo.get("mathematical_object_mapping")
        if isinstance(memo.get("mathematical_object_mapping"), dict)
        else {}
    )
    math_object = str(math_payload.get("mathematical_object") or "").strip()
    math_observation = str(math_payload.get("observation_mapping") or "").strip()
    mapped_object = str(object_mapping.get("mathematical_object") or "").strip()
    mapped_observation = str(object_mapping.get("observation_mapping") or "").strip()
    current_object_names = _current_object_alias_names(math_object)
    linked_formula_contract = _linked_component_formula_contract(
        memo,
        factor_spec,
    )
    canonical_observable_names = (
        set(linked_formula_contract[1]) if linked_formula_contract else set()
    )
    canonical_operator_names = (
        set(linked_formula_contract[2]) if linked_formula_contract else set()
    )
    observation_contract = _observation_mapping_formula_contract(
        math_observation,
        canonical_observable_names,
        math_object,
    )
    normalized = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    if (
        not math_object
        or not math_observation
        or linked_formula_contract is None
        or observation_contract is None
        or Counter(observation_contract[0])
        != Counter(linked_formula_contract[0])
        or current_object_names is None
        or normalized(math_object) != normalized(mapped_object)
        or normalized(math_observation) != normalized(mapped_observation)
        or _contains_future_payoff_object(math_object)
        or not _mathematical_object_binding_is_safe(
            math_object,
            canonical_operator_names,
        )
    ):
        return set()

    declared_state_names = _declared_current_state_names(
        memo,
        canonical_observable_names,
        canonical_operator_names,
        strict_formula_registry=True,
    )
    if not current_object_names <= (
        declared_state_names | set(observation_contract[1])
    ):
        return set()

    equation = str(
        math_payload.get("mechanism_equation_or_functional")
        or math_payload.get("process_or_distribution")
        or ""
    ).lower()
    if "measured_object" in equation:
        standard_references = re.findall(
            r"measured_object_\{[^{}]+\}",
            equation,
        )
        unsupported_references = re.sub(
            r"measured_object_\{[^{}]+\}",
            "",
            equation,
        )
        assignments = re.findall(
            r"measured_object_\{[^{}]+\}\s*=",
            equation,
        )
        if (
            not standard_references
            or "measured_object" in unsupported_references
            or len(assignments) != 1
            or re.search(
                r"measured_object_\{[^{}]+\}\s*(?::=|<-|\()",
                equation,
            )
            or "measured_object" not in declared_state_names
        ):
            return set()
    projection = str(math_payload.get("market_outcome_projection") or "")
    expectation_body = _first_top_level_expectation_body(projection.casefold())
    conditioning_text = projection
    if expectation_body is not None and expectation_body.count("|") == 1:
        conditioning_text = expectation_body.split("|", 1)[1]
    conditioning_references = _current_indexed_identifier_references(
        conditioning_text
    )
    measured_object_references = {
        reference
        for reference in conditioning_references or set()
        if reference[0] == "measured_object"
    }
    canonical_formula = _formula_text(factor_spec)
    canonical_ir = (
        parse_formula(canonical_formula)
        if _formula_source_is_fully_represented(canonical_formula)
        else {}
    )
    state_bindings = _current_state_formula_identities(
        memo,
        canonical_observable_names,
        canonical_operator_names,
    )
    canonical_identity = _formula_ir_node_identity(canonical_ir.get("root"))
    allowed_signatures = {
        signature
        for (_name, signature), identity in (state_bindings or {}).items()
        if canonical_identity is not None and identity == canonical_identity
    }
    if not allowed_signatures:
        # The public Pilot notation uses i as the canonical asset identity when
        # no named state assignment is present. Arbitrary identities must not
        # acquire measured-object authority through name-only matching.
        allowed_signatures = {("i", "t")}
    if "measured_object" in projection.casefold() and (
        not measured_object_references
        or any(
            signature not in allowed_signatures
            for _name, signature in measured_object_references
        )
    ):
        return set()
    return {"measured_object"}


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


def _unexpected_fields(
    payload: Any,
    allowed: frozenset[str],
    path: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return [
        f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_UNEXPECTED_FIELD:{path}.{key}"
        for key in sorted(set(payload) - set(allowed))
    ]


def memo_public_schema_failures(memo: dict[str, Any]) -> list[str]:
    """Reject fields that are neither formal contract data nor public research."""
    if not isinstance(memo, dict):
        return ["BLOCK_MAIN_AGENT_MECHANISM_MEMO_NOT_OBJECT"]
    failures = _unexpected_fields(
        memo,
        PUBLIC_MEMO_TOP_LEVEL_FIELDS,
        "memo",
    )
    section_rules = (
        ("agent_authorship", PUBLIC_MEMO_AUTHORSHIP_FIELDS),
        ("mechanism_qa", PUBLIC_MEMO_QA_FIELDS),
        ("economic_hypothesis", PUBLIC_MEMO_ECONOMIC_FIELDS),
        ("math_hypothesis", PUBLIC_MEMO_MATH_FIELDS),
        ("math_model_selection", PUBLIC_MEMO_MODEL_SELECTION_FIELDS),
        ("payer", PUBLIC_MEMO_PAYER_FIELDS),
        ("mathematical_object_mapping", PUBLIC_MEMO_OBJECT_MAPPING_FIELDS),
        ("formula_state_estimator", PUBLIC_MEMO_OBJECT_MAPPING_FIELDS),
        ("expected_metric_signature", frozenset(REQUIRED_METRIC_SIGNATURE_FIELDS)),
        ("evidence_comparison", PUBLIC_MEMO_EVIDENCE_FIELDS),
        (
            "operator_claim_consistency",
            PUBLIC_MEMO_OPERATOR_CONSISTENCY_FIELDS,
        ),
    )
    for field, allowed in section_rules:
        failures.extend(_unexpected_fields(memo.get(field), allowed, field))

    formula_understanding = memo.get("formula_understanding")
    failures.extend(
        _unexpected_fields(
            formula_understanding,
            PUBLIC_MEMO_FORMULA_UNDERSTANDING_FIELDS,
            "formula_understanding",
        )
    )
    if isinstance(formula_understanding, dict):
        formula_features = formula_understanding.get("formula_features")
        failures.extend(
            _unexpected_fields(
                formula_features,
                PUBLIC_MEMO_FORMULA_FEATURE_FIELDS,
                "formula_understanding.formula_features",
            )
        )
        if isinstance(formula_features, dict):
            string_lists = {
                "fields",
                "mechanism_observable_inputs",
                "mechanism_inputs_not_in_formula",
                "formula_missing_mechanism_inputs",
                "operators",
            }
            boolean_fields = {
                "has_volume",
                "has_high_low",
                "has_sign_or_threshold",
                "has_long_window",
                "has_250_window",
                "has_short_delay_or_delta",
                "has_raw_additive",
                "has_open_close_position",
            }
            if "formula_text" in formula_features and not isinstance(
                formula_features.get("formula_text"), str
            ):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    "formula_understanding.formula_features.formula_text"
                )
            for key in string_lists & set(formula_features):
                value = formula_features.get(key)
                if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value
                ):
                    failures.append(
                        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                        f"formula_understanding.formula_features.{key}"
                    )
            constants = formula_features.get("constants")
            if constants is not None and (
                not isinstance(constants, list)
                or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    for item in constants
                )
            ):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    "formula_understanding.formula_features.constants"
                )
            for key in boolean_fields & set(formula_features):
                if not isinstance(formula_features.get(key), bool):
                    failures.append(
                        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                        f"formula_understanding.formula_features.{key}"
                    )

        components = formula_understanding.get("component_interpretations")
        if components is not None:
            if not isinstance(components, list):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    "formula_understanding.component_interpretations"
                )
            else:
                for index, item in enumerate(components):
                    path = f"formula_understanding.component_interpretations[{index}]"
                    failures.extend(
                        _unexpected_fields(
                            item,
                            PUBLIC_MEMO_FORMULA_COMPONENT_INTERPRETATION_FIELDS,
                            path,
                        )
                    )
                    if not isinstance(item, dict) or any(
                        not isinstance(item.get(key), str)
                        for key in item
                        if key in PUBLIC_MEMO_FORMULA_COMPONENT_INTERPRETATION_FIELDS
                    ):
                        failures.append(
                            f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:{path}"
                        )
        for key in (
            "formula_understanding_version",
            "interaction_structure",
        ):
            if key in formula_understanding and not isinstance(
                formula_understanding.get(key), str
            ):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    f"formula_understanding.{key}"
                )
        candidates = formula_understanding.get("mathematical_object_candidates")
        if candidates is not None and (
            not isinstance(candidates, list)
            or any(not isinstance(item, str) for item in candidates)
        ):
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                "formula_understanding.mathematical_object_candidates"
            )

    failures.extend(
        _unexpected_fields(
            memo.get("source_refs"),
            PUBLIC_MEMO_SOURCE_REF_FIELDS,
            "source_refs",
        )
    )

    def require_string_fields(payload: Any, fields: frozenset[str], path: str) -> None:
        if not isinstance(payload, dict):
            return
        for key in fields & set(payload):
            if not isinstance(payload.get(key), str):
                failures.append(
                    f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:{path}.{key}"
                )

    require_string_fields(memo.get("source_refs"), PUBLIC_MEMO_SOURCE_REF_FIELDS, "source_refs")
    require_string_fields(memo.get("mechanism_qa"), PUBLIC_MEMO_QA_FIELDS, "mechanism_qa")
    require_string_fields(
        memo.get("economic_hypothesis"),
        PUBLIC_MEMO_ECONOMIC_FIELDS,
        "economic_hypothesis",
    )
    require_string_fields(
        memo.get("math_hypothesis"),
        PUBLIC_MEMO_MATH_FIELDS - {"expected_metric_signature"},
        "math_hypothesis",
    )
    require_string_fields(
        memo.get("math_model_selection"),
        PUBLIC_MEMO_MODEL_SELECTION_FIELDS,
        "math_model_selection",
    )
    require_string_fields(memo.get("payer"), PUBLIC_MEMO_PAYER_FIELDS, "payer")
    require_string_fields(
        memo.get("expected_metric_signature"),
        frozenset(REQUIRED_METRIC_SIGNATURE_FIELDS),
        "expected_metric_signature",
    )
    authorship = memo.get("agent_authorship")
    if isinstance(authorship, dict):
        for key in ("authoring_mode", "agent_role", "runtime", "note"):
            if key in authorship and not isinstance(authorship.get(key), str):
                failures.append(
                    f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:agent_authorship.{key}"
                )
        if "answered_without_deterministic_template" in authorship and not isinstance(
            authorship.get("answered_without_deterministic_template"), bool
        ):
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                "agent_authorship.answered_without_deterministic_template"
            )

    for mapping_field in ("mathematical_object_mapping", "formula_state_estimator"):
        mapping = memo.get(mapping_field)
        if not isinstance(mapping, dict):
            continue
        require_string_fields(
            mapping,
            PUBLIC_MEMO_OBJECT_MAPPING_FIELDS - {"component_links"},
            mapping_field,
        )
        links = mapping.get("component_links")
        if links is not None and (
            not isinstance(links, list)
            or any(not isinstance(item, str) for item in links)
        ):
            failures.append(
                f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:{mapping_field}.component_links"
            )

    for field in ("falsification_tests", "council_questions"):
        value = memo.get(field)
        if value is not None and (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
        ):
            failures.append(
                f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:{field}"
            )

    refs = memo.get("evidence_comparison")
    if isinstance(refs, dict):
        observed = refs.get("observed_metrics")
        if isinstance(observed, dict):
            for key, value in observed.items():
                if not _is_public_observed_metric_key(str(key)):
                    failures.append(
                        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_UNEXPECTED_FIELD:"
                        f"evidence_comparison.observed_metrics.{key}"
                    )
                elif not public_observed_metric_value_is_valid(str(key), value):
                    failures.append(
                        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                        f"evidence_comparison.observed_metrics.{key}"
                    )
        conflict_keys = refs.get("observed_metric_conflict_keys")
        if conflict_keys is not None and (
            not isinstance(conflict_keys, list)
            or any(
                not isinstance(key, str)
                or not _is_public_observed_metric_key(key)
                for key in conflict_keys
            )
            or len(conflict_keys) != len(set(conflict_keys))
            or conflict_keys != sorted(conflict_keys)
        ):
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                "evidence_comparison.observed_metric_conflict_keys"
            )
        if "mechanism_supported" in refs and not isinstance(
            refs.get("mechanism_supported"), str
        ):
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                "evidence_comparison.mechanism_supported"
            )
        for key in (
            "contradictions",
            "revision_implications",
            "kill_criteria_triggered",
        ):
            value = refs.get(key)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    f"evidence_comparison.{key}"
                )

    math = memo.get("math_hypothesis")
    if isinstance(math, dict):
        failures.extend(
            _unexpected_fields(
                math.get("expected_metric_signature"),
                frozenset(REQUIRED_METRIC_SIGNATURE_FIELDS),
                "math_hypothesis.expected_metric_signature",
            )
        )
    components = memo.get("formula_component_map")
    if isinstance(components, list):
        for index, component in enumerate(components):
            failures.extend(
                _unexpected_fields(
                    component,
                    PUBLIC_MEMO_COMPONENT_FIELDS,
                    f"formula_component_map[{index}]",
                )
            )
            if not isinstance(component, dict):
                continue
            require_string_fields(
                component,
                PUBLIC_MEMO_COMPONENT_FIELDS - {"operators"},
                f"formula_component_map[{index}]",
            )
            operators = component.get("operators")
            if operators is not None and (
                not isinstance(operators, list)
                or any(not isinstance(item, str) for item in operators)
            ):
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    f"formula_component_map[{index}].operators"
                )

    consistency = memo.get("operator_claim_consistency")
    if isinstance(consistency, dict):
        for key in PUBLIC_MEMO_OPERATOR_CONSISTENCY_FIELDS:
            if key not in consistency:
                continue
            value = consistency.get(key)
            valid_type = (
                value is None or isinstance(value, str)
                if key == "explicit_dependence_justification"
                else isinstance(value, bool)
            )
            if not valid_type:
                failures.append(
                    "BLOCK_MAIN_AGENT_MECHANISM_MEMO_PUBLIC_FIELD_TYPE:"
                    f"operator_claim_consistency.{key}"
                )
    return list(dict.fromkeys(failures))


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
            "economic_state": "combined score with scale commensurability risk",
            "mathematical_object": "additive measurement functional",
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
            "economic_state": str(item.get("economic_state") or "formula-defined economic quantity"),
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
        "economic_state": "formula-defined economic quantity",
        "mathematical_object": "researcher-selected mathematical object",
        "expected_role": "estimate an object whose market-outcome projection must be verified by Step4/5 metrics",
        "metric_link": "rank IC, long-side return, cost-adjusted return, monotonicity, and turnover must support the claimed market-outcome projection",
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
                "field": "mathematical_object_answer",
                "question": "What mathematical object or economic quantity should represent this exact hypothesis? It may be a valuation functional, accounting identity, stochastic/path object, spectral component, causal estimand, optimization object, or a newly composed object; justify the choice from the hypothesis rather than from operator availability.",
            },
            {
                "field": "economic_hypothesis_answer",
                "question": "What economic hypothesis makes that mathematical object or measured quantity monetizable: risk premium, information advantage, market-structure harvesting, or mixed, and why?",
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
                "question": "How does the selected mathematical object project into a tradeable payoff, with sign, horizon, and explicit market-outcome map?",
            },
            {
                "field": "observation_mapping_answer",
                "question": "How does each formula or code component observe or estimate the selected mathematical object, and what information does each transformation preserve or discard?",
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
            "mathematical_object": contract.get("mathematical_object") or contract.get("state_or_object") or "transient pressure and participation object",
            "mechanism_equation_or_functional": (
                "P_i,t = F_i,t + I_i,t + epsilon_i,t, with I_i,t governed by a short-horizon "
                "signed price threshold state and scaled by relative volume participation."
            ),
            "target_functional": "E[r_i,t+1 | F_t, signed_price_state_i,t, participation_ratio_i,t, additive_score_i,t]",
            "market_outcome_projection": "E[r_i,t+1|F_t] follows the declared sign of temporary impact decay after costs.",
            "observation_mapping": (
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
            "mathematical_object": contract.get("mathematical_object") or contract.get("state_or_object") or "overnight-to-intraday pressure or close-location reversal object",
            "mechanism_equation_or_functional": (
                "P_i,t evolves through an opening price, intraday digestion path, and close price; "
                "the open/close location state may drift, reverse, or decay over the next horizon."
            ),
            "target_functional": "E[r_i,t+1 | F_t, open_close_position_state_i,t]",
            "market_outcome_projection": "E[r_i,t+1|F_t] follows the declared continuation or reversal sign of the open-close location object after costs.",
            "observation_mapping": (
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
        "mathematical_object": contract.get("mathematical_object") or contract.get("state_or_object") or "researcher-selected mathematical object",
        "mechanism_equation_or_functional": contract.get("mechanism_equation_or_functional") or contract.get("process_hypothesis") or contract.get("process_or_distribution") or "researcher must supply a mechanism-specific equation or functional",
        "target_functional": contract.get("target_functional") or "E[r_i,t+1 | F_t, formula_state_i,t]",
        "market_outcome_projection": contract.get("market_outcome_projection") or "researcher must map the selected object to a signed, timed market payoff",
        "observation_mapping": contract.get("observation_mapping") or contract.get("factor_as_estimator") or "formula or code maps legal-time observables into the selected mathematical object",
        "expected_metric_signature": {
            "rank_ic": "sign and persistence should match the declared return source",
            "long_side": "high-score long side must be positive if the state is monetizable",
            "cost_adjusted": "cost-adjusted long side must survive turnover and impact",
            "monotonicity": "group ordering should match the claimed state direction",
            "turnover": "turnover must be consistent with the stated horizon",
        },
    }


def _selected_measurement_program_model(program: Any) -> dict[str, Any] | None:
    if not isinstance(program, dict):
        return None
    selection = program.get("model_selection")
    if not isinstance(selection, dict):
        return None
    selected = [
        item
        for item in selection.get("candidate_models") or []
        if isinstance(item, dict) and item.get("selected") is True
    ]
    if len(selected) != 1:
        return None
    return selected[0]


def _measurement_program_from_factor_spec(
    factor_spec: dict[str, Any] | None,
) -> dict[str, Any] | None:
    factor_spec = factor_spec if isinstance(factor_spec, dict) else {}
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else {}
    )
    for candidate in (
        factor_spec.get("mechanism_conditioned_measurement_program"),
        canonical.get("mechanism_conditioned_measurement_program"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return None


def _factor_spec_knowledge_node_ids(
    factor_spec: dict[str, Any] | None,
) -> set[str]:
    factor_spec = factor_spec if isinstance(factor_spec, dict) else {}
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else {}
    )
    research_contracts = [
        container.get("research_contract")
        for container in (factor_spec, canonical)
        if isinstance(container.get("research_contract"), dict)
    ]
    knowledge_contracts = [
        container.get("knowledge_reference_contract")
        for container in (*research_contracts, factor_spec, canonical)
        if isinstance(container.get("knowledge_reference_contract"), dict)
    ]
    authorized_ids: set[str] = set()
    for contract in knowledge_contracts:
        cited_ids = contract.get("cited_node_ids")
        if not isinstance(cited_ids, list):
            cited_ids = contract.get("retrieved_case_ids")
        normalized_ids = [
            str(item).strip()
            for item in cited_ids or []
            if str(item).strip()
        ]
        query_hash = str(contract.get("query_hash") or "")
        if (
            validate_knowledge_reference_contract(
                contract,
                retrieval_required=True,
            )
            or contract.get("retrieval_status") != "retrieved"
            or re.fullmatch(r"[0-9a-f]{64}", query_hash.casefold()) is None
            or not isinstance(contract.get("indexes_available"), list)
            or not contract.get("indexes_available")
            or not normalized_ids
            or len(normalized_ids) != len(set(normalized_ids))
            or contract.get("hit_count") != len(normalized_ids)
            or not str(contract.get("producer") or "").strip()
            or (
                contract.get("summary_sha256") is not None
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(contract.get("summary_sha256") or "").casefold(),
                )
                is None
            )
        ):
            continue
        authorized_ids.update(normalized_ids)
    if not authorized_ids:
        return set()

    context_node_ids: set[str] = set()
    contexts = [
        container.get("factor_knowledge_context")
        for container in (*research_contracts, factor_spec, canonical)
        if isinstance(container.get("factor_knowledge_context"), dict)
    ]
    for context in contexts:
        if context.get("schema_version") != "factor_knowledge_context_v1":
            continue
        nodes = context.get("nodes")
        if not isinstance(nodes, list):
            continue
        declared_count = context.get("node_count")
        if declared_count is not None and declared_count != len(nodes):
            continue
        query = context.get("query")
        if not isinstance(query, dict) or not isinstance(query.get("top_k"), int):
            continue
        context_node_ids.update(
            str(item.get("id"))
            for item in nodes
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        )
    return context_node_ids & authorized_ids


def _validated_measurement_program_from_factor_spec(
    factor_spec: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    factor_spec = factor_spec if isinstance(factor_spec, dict) else {}
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else {}
    )
    raw_candidates = [
        container.get("mechanism_conditioned_measurement_program")
        for container in (factor_spec, canonical)
        if "mechanism_conditioned_measurement_program" in container
    ]
    if any(not isinstance(candidate, dict) for candidate in raw_candidates):
        return None, ["measurement_program.copy_type_invalid"]
    candidates = list(raw_candidates)
    program = candidates[0] if candidates else None
    if program is None:
        return None, []
    if any(candidate != program for candidate in candidates[1:]):
        return None, ["measurement_program.copies_mismatch"]
    failures = validate_measurement_program(
        program,
        available_knowledge_node_ids=_factor_spec_knowledge_node_ids(factor_spec),
        require_web_executable=False,
    )
    return (program if not failures else None), failures


def _math_hypothesis_from_measurement_program(
    program: Any,
) -> dict[str, Any] | None:
    if not isinstance(program, dict):
        return None
    selection = program.get("model_selection")
    observation = program.get("observation_and_estimation")
    projection = program.get("market_outcome_projection")
    if not all(isinstance(item, dict) for item in (selection, observation, projection)):
        return None
    model = _selected_measurement_program_model(program)
    if not isinstance(model, dict):
        return None
    model_family = str(model.get("model_family") or "").strip()
    mathematical_object = str(model.get("mathematical_object") or "").strip()
    mechanism_equation = str(
        model.get("mechanism_equation_or_functional") or ""
    ).strip()
    market_projection = str(
        model.get("market_outcome_projection") or ""
    ).strip()
    if (
        not model_family
        or not mathematical_object
        or not mechanism_equation
        or not market_projection
    ):
        return None
    return {
        "selected_model_family": model_family,
        "why_this_model": str(selection.get("selection_argument") or ""),
        "why_not_generic_template": str(
            selection.get("rejected_model_reason") or model.get("decisive_test") or ""
        ),
        "mathematical_object": mathematical_object,
        "mechanism_equation_or_functional": mechanism_equation,
        "target_functional": str(model.get("target_functional") or ""),
        "market_outcome_projection": market_projection,
        "observation_mapping": str(model.get("observation_mapping") or ""),
        "expected_metric_signature": {
            "rank_ic": "direction must match the selected market-outcome projection",
            "long_side": "selected long-side direction must have positive gross payoff",
            "cost_adjusted": "the declared payoff must survive transaction and volatility costs",
            "monotonicity": "required only when the frozen claim class makes ordering a proof obligation",
            "turnover": "turnover must match the selected horizon and implementation route",
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
            "mathematical_object_claim": str(item.get("mathematical_object") or item.get("economic_state") or ""),
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
            "mechanism_equation_or_functional": str(
                _math_value(
                    math,
                    "mechanism_equation_or_functional",
                    "process_or_distribution",
                )
                or ""
            ),
            "model_mutation": str(math.get("why_this_model") or math.get("why_not_generic_template") or qa.get("math_model_answer") or ""),
        },
        "payer": {
            "payer_or_counterparty": str(economic.get("payer_or_counterparty") or ""),
            "why_they_pay": str(economic.get("why_they_pay") or ""),
            "necessary_market_structure": str(economic.get("necessary_market_structure") or ""),
        },
        "mathematical_object_mapping": {
            "mathematical_object": str(
                _math_value(math, "mathematical_object", "latent_state", "random_object")
                or _qa_answer(qa, "mathematical_object_answer")
                or ""
            ),
            "observation_mapping": str(
                _math_value(math, "observation_mapping", "formula_as_estimator")
                or _qa_answer(qa, "observation_mapping_answer")
                or ""
            ),
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
    measurement_program = (
        mechanism.get("mechanism_conditioned_measurement_program")
        or factor_spec.get("mechanism_conditioned_measurement_program")
        or (
            factor_spec.get("canonical_spec", {}).get(
                "mechanism_conditioned_measurement_program"
            )
            if isinstance(factor_spec.get("canonical_spec"), dict)
            else None
        )
    )
    math_hypothesis = (
        _math_hypothesis_from_measurement_program(measurement_program)
        or _default_math_hypothesis(
            profile=profile,
            mechanism=mechanism,
            contract=contract,
        )
    )
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
    value = _qa_answer(qa, field)
    text = str(value or "").strip().lower()
    if len(text) < 80:
        failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_INCOMPLETE:{field}")
        return
    if any(term in text for term in generic_terms):
        failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_GENERIC:{field}")
    if field in {
        "mathematical_object_answer",
        "observation_mapping_answer",
        "formula_state_answer",
        "estimator_mapping_answer",
    }:
        if formula_terms and not any(term in text for term in formula_terms):
            failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_QA_NOT_FORMULA_SPECIFIC:{field}")


def formula_specific_derivation_from_main_agent_memo(memo: dict[str, Any], factor_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert an accepted freeform main-agent memo into Step6 derivation fields."""
    qa = memo.get("mechanism_qa") if isinstance(memo.get("mechanism_qa"), dict) else {}
    math = memo.get("math_hypothesis") if isinstance(memo.get("math_hypothesis"), dict) else {}
    economic = memo.get("economic_hypothesis") if isinstance(memo.get("economic_hypothesis"), dict) else {}
    components = memo.get("formula_component_map") if isinstance(memo.get("formula_component_map"), list) else []
    mathematical_object_mapping = (
        memo.get("mathematical_object_mapping")
        if isinstance(memo.get("mathematical_object_mapping"), dict)
        else (
            memo.get("formula_state_estimator")
            if isinstance(memo.get("formula_state_estimator"), dict)
            else {}
        )
    )
    operator_claim_consistency = (
        memo.get("operator_claim_consistency")
        if isinstance(memo.get("operator_claim_consistency"), dict)
        else {}
    )
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
                str(_qa_answer(qa, "observation_mapping_answer") or ""),
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
            "formula_state_link": str(_qa_answer(qa, "observation_mapping_answer") or formula_state_link),
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
        "mathematical_object_mapping": [
            {
                "observable_component": str(item.get("component_id") or f"component_{idx + 1}"),
                "mathematical_object_claim": str(item.get("mathematical_object") or item.get("economic_state") or ""),
                "observation_mapping": str(item.get("observable_estimator") or ""),
            }
            for idx, item in enumerate(components)
            if isinstance(item, dict)
        ],
        "selected_model_family": model_family,
        "why_this_model_not_generic_template": str(math.get("why_not_generic_template") or qa.get("math_model_answer") or ""),
        "mathematical_object": str(
            _math_value(math, "mathematical_object", "latent_state", "random_object")
            or _qa_answer(qa, "mathematical_object_answer")
            or ""
        ),
        "mechanism_equation_or_functional": str(
            _math_value(
                math,
                "mechanism_equation_or_functional",
                "process_or_distribution",
            )
            or qa.get("math_model_answer")
            or ""
        ),
        "target_functional": str(math.get("target_functional") or payoff or "E[r_i,t+1 | F_t, formula_state_i,t]"),
        "market_outcome_projection": str(
            math.get("market_outcome_projection")
            or qa.get("payoff_answer")
            or ""
        ),
        "observation_mapping": str(
            _math_value(math, "observation_mapping", "formula_as_estimator")
            or _qa_answer(qa, "observation_mapping_answer")
            or ""
        ),
        "mathematical_object_mapping_summary": mathematical_object_mapping,
        "operator_consistency_discussion": {
            "mathematical_object_answer": str(_qa_answer(qa, "mathematical_object_answer") or ""),
            "observation_mapping_answer": str(_qa_answer(qa, "observation_mapping_answer") or ""),
            "operator_claim_consistency": operator_claim_consistency,
        },
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
    failures.extend(memo_public_schema_failures(memo))
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
    operators = _operator_set(factor_spec or {}, understanding)
    fields = _field_set(factor_spec or {}, understanding)
    canonical_formula_text = _formula_text(factor_spec or {})
    canonical_formula_ir = (
        parse_formula(canonical_formula_text)
        if _formula_source_is_fully_represented(canonical_formula_text)
        else {}
    )
    trusted_operators = (
        {
            str(operator).strip().casefold()
            for operator in canonical_formula_ir.get("operator_set") or []
            if str(operator).strip()
        }
        if canonical_formula_ir.get("parse_status") == "success"
        else set()
    )
    trusted_observable_fields = (
        {
            str(field).strip().casefold()
            for field in canonical_formula_ir.get("required_fields") or []
            if str(field).strip()
        }
        if canonical_formula_ir.get("parse_status") == "success"
        else set()
    )
    trusted_information_fields = set(trusted_observable_fields)
    trusted_information_fields.update(
        _declared_current_state_names(
            memo,
            trusted_information_fields,
            trusted_operators,
            strict_formula_registry=True,
        )
    )
    trusted_information_fields.discard("measured_object")
    formula_terms = formula_specific_qa_terms(
        formula_text,
        operators=operators,
        fields=fields,
    )
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
        "math_model_selection": ("model_family", "model_mutation"),
        "payer": ("payer_or_counterparty", "why_they_pay", "necessary_market_structure"),
    }
    for field, required_keys in top_level_contract.items():
        payload = memo.get(field)
        if not isinstance(payload, dict) or not payload:
            failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:{field}")
            continue
        for key in required_keys:
            if not str(payload.get(key) or "").strip():
                failures.append(f"BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:{field}.{key}")
    selection_payload = (
        memo.get("math_model_selection")
        if isinstance(memo.get("math_model_selection"), dict)
        else {}
    )
    if not str(
        selection_payload.get("mechanism_equation_or_functional")
        or selection_payload.get("baseline_model")
        or ""
    ).strip():
        failures.append(
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:"
            "math_model_selection.mechanism_equation_or_functional"
        )
    object_mapping = (
        memo.get("mathematical_object_mapping")
        if isinstance(memo.get("mathematical_object_mapping"), dict)
        else (
            memo.get("formula_state_estimator")
            if isinstance(memo.get("formula_state_estimator"), dict)
            else {}
        )
    )
    if not object_mapping:
        failures.append(
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:"
            "mathematical_object_mapping"
        )
    else:
        if not str(
            object_mapping.get("mathematical_object")
            or object_mapping.get("latent_state")
            or ""
        ).strip():
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:"
                "mathematical_object_mapping.mathematical_object"
            )
        if not str(
            object_mapping.get("observation_mapping")
            or object_mapping.get("observable_mapping")
            or ""
        ).strip():
            failures.append(
                "BLOCK_MAIN_AGENT_MECHANISM_MEMO_TOP_LEVEL_FIELD_MISSING:"
                "mathematical_object_mapping.observation_mapping"
            )
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
    raw_selected_model_family = str(
        math.get("selected_model_family") or math.get("model_family") or ""
    ).strip()
    selection = (
        memo.get("math_model_selection")
        if isinstance(memo.get("math_model_selection"), dict)
        else {}
    )
    raw_selection_model_family = str(selection.get("model_family") or "").strip()
    measurement_program, measurement_program_failures = (
        _validated_measurement_program_from_factor_spec(factor_spec)
    )
    if measurement_program_failures:
        failures.append(
            "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MEASUREMENT_PROGRAM_INVALID"
        )
    selected_program_model = _selected_measurement_program_model(measurement_program)
    program_model_family = str(
        (selected_program_model or {}).get("model_family") or ""
    ).strip()
    if program_model_family:
        expected_normalized = normalize_derivation_model_family(
            program_model_family
        )

        def matches_program_family(value: str) -> bool:
            normalized = normalize_derivation_model_family(value)
            if expected_normalized and normalized:
                return normalized == expected_normalized
            return value.casefold() == program_model_family.casefold()

        if not raw_selected_model_family or not raw_selection_model_family:
            failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID")
        elif (
            not matches_program_family(raw_selected_model_family)
            or not matches_program_family(raw_selection_model_family)
        ):
            failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH")
        selected_model_family = (
            expected_normalized
            or program_model_family
        )
    else:
        selected_model_family = normalize_derivation_model_family(
            raw_selected_model_family
        )
        selection_model_family = normalize_derivation_model_family(
            raw_selection_model_family
        )
        if selected_model_family is None or selection_model_family is None:
            failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID")
        elif selected_model_family != selection_model_family:
            failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH")
    mechanism_equation = str(
        _math_value(
            math,
            "mechanism_equation_or_functional",
            "process_or_distribution",
        )
        or ""
    ).lower()
    if not mechanism_equation or not any(
        term in mechanism_equation
        for term in [
            "=",
            "functional",
            "optimization",
            "projection",
            "valuation",
            "identity",
            "process",
            "distribution",
            "decay",
            "conditional",
        ]
    ):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC")
    formula_tokens = {"rank", "delta", "sign", "sum", "divide", "plus", "minus", "multiply", "close", "volume"}
    if mechanism_equation and set(re.findall(r"[a-z_]+", mechanism_equation)) <= formula_tokens:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC")
    uses_current_math_schema = any(
        field in math
        for field in (
            "mathematical_object",
            "mechanism_equation_or_functional",
            "market_outcome_projection",
            "observation_mapping",
        )
    )
    bound_measured_object_aliases = _bound_measured_object_projection_aliases(
        memo,
        factor_spec or {},
    )
    canonical_valuation_formula_supported = (
        _canonical_formula_supports_valuation(
            canonical_formula_ir,
        )
        and _mechanism_equation_binds_formula_root(
            memo,
            canonical_formula_ir,
        )
    )
    canonical_valuation_root_bound = bool(bound_measured_object_aliases)
    program_valuation_root_bound = (
        bool(program_model_family)
        and _measurement_program_observation_binds_formula_root(
            measurement_program,
            canonical_formula_ir,
        )
    )
    valuation_exemption_allowed = (
        selected_model_family == "valuation_identity"
        and canonical_valuation_formula_supported
        and (
            canonical_valuation_root_bound
            or program_valuation_root_bound
        )
    )
    if (
        uses_current_math_schema
        and selected_model_family == "valuation_identity"
        and not valuation_exemption_allowed
    ):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH")
    target = str(math.get("target_functional") or "").lower()
    target_is_tradeable = (
        _has_explicit_named_return_payoff(
            target,
            allowed_information_names=trusted_information_fields,
        )
        or _has_explicit_forward_price_payoff(
            target,
            allowed_information_names=trusted_information_fields,
        )
    )
    generic_targets = {
        "target",
        "alpha",
        "factor",
        "expected return",
        "mechanism-specific target",
        "under_specified",
    }
    mechanism_specific_target = (
        uses_current_math_schema
        and len(target) >= 24
        and target not in generic_targets
        and any(character in target for character in ["=", "_", "[", "("])
    )
    valuation_target = (
        valuation_exemption_allowed
        and any(
            term in target
            for term in [
                "valuation_gap",
                "intrinsic_value",
                "intrinsic value",
                "fcf",
                "residual_income",
                "residual income",
            ]
        )
        and any(term in target for term in ["/", "=", "sum", "present value"])
    )
    if not target or not (
        target_is_tradeable or valuation_target or mechanism_specific_target
    ):
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID")
    projection = str(
        math.get("market_outcome_projection")
        or (target if target_is_tradeable else "")
        or ""
    ).lower()
    projection_information_fields = (
        set(trusted_information_fields)
        if not uses_current_math_schema or valuation_exemption_allowed
        else set()
    )
    projection_information_fields.update(bound_measured_object_aliases)
    projection_has_expectation = bool(
        re.search(r"(?<![a-z0-9_])e\s*\[", projection)
    )
    measured_object_is_required = (
        uses_current_math_schema and not valuation_exemption_allowed
    )
    measured_object_is_present = "measured_object" in projection
    requires_strict_projection_suffix = (
        measured_object_is_present
        or uses_current_math_schema and projection_has_expectation
    )
    structured_projection_suffix_is_safe = (
        (not measured_object_is_required or measured_object_is_present)
        and (
            not requires_strict_projection_suffix
            or projection_has_expectation
            and _single_expectation_projection_suffix_is_safe(projection)
        )
    )
    projection_is_tradeable = (
        (not measured_object_is_required or measured_object_is_present)
        and (
            structured_projection_suffix_is_safe
            and (
                _has_explicit_named_return_payoff(
                    projection,
                    allowed_information_names=projection_information_fields,
                    include_default_information_names=not uses_current_math_schema,
                )
                or _has_explicit_forward_price_payoff(
                    projection,
                    allowed_information_names=projection_information_fields,
                    include_default_information_names=not uses_current_math_schema,
                )
            )
            or (
                not requires_strict_projection_suffix
                and not projection_has_expectation
                and (
                    not uses_current_math_schema
                    or valuation_exemption_allowed
                    and _valuation_projection_prose_is_safe(
                        projection,
                        trusted_information_fields,
                    )
                )
                and any(
                    term in projection
                    for term in ["return", "payoff", "alpha", "r_"]
                )
                and any(
                    term in projection
                    for term in ["t+1", "t+2", "t+h", "next horizon", "forward"]
                )
                and any(
                    term in projection
                    for term in [
                        "positive",
                        "negative",
                        "increasing",
                        "decreasing",
                        "monotone",
                        "sign",
                        "convergence",
                        "reversal",
                        "continuation",
                    ]
                )
            )
        )
    )
    if not projection_is_tradeable:
        failures.append("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MARKET_PROJECTION_INVALID")
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
