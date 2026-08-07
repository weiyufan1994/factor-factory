from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


SOURCE_DIALECT_CONTRACT_VERSION = "factorforge_formula_source_dialect_v1"
SOURCE_DIALECT_ID = "rongliang_factor365_20260707_v1"
SOURCE_DIALECT_REFERENCE = (
    "https://finance.sina.com.cn/wm/2026-07-07/doc-inifxxwy1421970.shtml"
)
BLOCK_SOURCE_SEMANTICS_UNRESOLVED = (
    "BLOCK_FACTORFORGE_FORMULA_SOURCE_SEMANTICS_UNRESOLVED"
)
BLOCK_SOURCE_FORMULA_INVALID = "BLOCK_FACTORFORGE_FORMULA_SOURCE_DIALECT_INVALID"

SOURCE_OPERATOR_NAMES = frozenset(
    {
        "normalize",
        "s_log_lp",
        "s_log_1p",
        "ts_kurtosis",
        "ts_max_skew",
        "ts_min_skew",
        "ts_max_sum",
    }
)

SEMANTIC_CHOICES = {
    "kurtosis_convention": {"excess_unbiased", "pearson_unbiased"},
    "skew_convention": {"order_statistic_subset", "inner_window_extrema"},
    "max_sum_convention": {"contiguous_subwindow", "topk_values"},
    "zscore_ddof": {"0", "1"},
}


@dataclass(frozen=True)
class SourceFormulaDialectError(ValueError):
    token: str
    reasons: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.token}: {'; '.join(self.reasons)}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def detected_source_operators(formula_text: str) -> list[str]:
    calls = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(formula_text or ""))
    return sorted({name.lower() for name in calls if name.lower() in SOURCE_OPERATOR_NAMES})


def uses_source_dialect(formula_text: str) -> bool:
    return bool(detected_source_operators(formula_text))


def normalize_semantic_choices(raw: Mapping[str, Any] | None) -> dict[str, str]:
    choices = {
        key: str((raw or {}).get(key) or "").strip().lower()
        for key in SEMANTIC_CHOICES
    }
    failures = [
        f"{key} must be one of {','.join(sorted(allowed))}"
        for key, allowed in SEMANTIC_CHOICES.items()
        if choices[key] not in allowed
    ]
    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )
    return choices


class _RongliangDialectTranslator(ast.NodeTransformer):
    def __init__(self, choices: Mapping[str, str]) -> None:
        self.choices = choices

    def visit_Name(self, node: ast.Name) -> ast.AST:
        normalized = node.id.strip().lower()
        if normalized == "change_pct":
            return ast.copy_location(ast.Name(id="returns", ctx=node.ctx), node)
        if normalized in {"close", "volume"}:
            return ast.copy_location(ast.Name(id=normalized, ctx=node.ctx), node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Name):
            return node
        source_name = node.func.id.strip().lower()
        if source_name not in SOURCE_OPERATOR_NAMES:
            return node
        if source_name == "normalize":
            standardize = None
            remaining_keywords: list[ast.keyword] = []
            for keyword in node.keywords:
                if str(keyword.arg or "").strip().lower() == "standardize":
                    if not isinstance(keyword.value, ast.Constant):
                        raise SourceFormulaDialectError(
                            BLOCK_SOURCE_FORMULA_INVALID,
                            ("NORMALIZE.STANDARDIZE must be a literal",),
                        )
                    standardize = keyword.value.value
                else:
                    remaining_keywords.append(keyword)
            if len(node.args) != 1 or remaining_keywords or standardize != 1:
                raise SourceFormulaDialectError(
                    BLOCK_SOURCE_FORMULA_INVALID,
                    ("only NORMALIZE(x, STANDARDIZE=1) is supported by this source dialect",),
                )
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="cs_zscore", ctx=ast.Load()),
                    args=[node.args[0], ast.Constant(value=int(self.choices["zscore_ddof"]))],
                    keywords=[],
                ),
                node,
            )
        if node.keywords:
            raise SourceFormulaDialectError(
                BLOCK_SOURCE_FORMULA_INVALID,
                (f"{node.func.id} does not accept keyword arguments",),
            )
        replacements = {
            "s_log_lp": "signed_log1p",
            "s_log_1p": "signed_log1p",
            "ts_kurtosis": (
                "rolling_excess_kurtosis"
                if self.choices["kurtosis_convention"] == "excess_unbiased"
                else "rolling_pearson_kurtosis"
            ),
            "ts_max_skew": (
                "rolling_topk_skew"
                if self.choices["skew_convention"] == "order_statistic_subset"
                else "rolling_max_inner_skew"
            ),
            "ts_min_skew": (
                "rolling_bottomk_skew"
                if self.choices["skew_convention"] == "order_statistic_subset"
                else "rolling_min_inner_skew"
            ),
            "ts_max_sum": (
                "rolling_max_subwindow_sum"
                if self.choices["max_sum_convention"] == "contiguous_subwindow"
                else "rolling_topk_sum"
            ),
        }
        node.func.id = replacements[source_name]
        return node


def resolve_source_formula(
    formula_text: str,
    semantic_choices: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_formula = str(formula_text or "").strip()
    detected = detected_source_operators(raw_formula)
    if not detected:
        return {
            "contract_version": SOURCE_DIALECT_CONTRACT_VERSION,
            "dialect_id": "canonical_factorforge_formula_ir",
            "source_reference": None,
            "raw_formula": raw_formula,
            "raw_formula_sha256": _sha256_text(raw_formula),
            "canonical_formula": raw_formula,
            "semantic_choices": {},
            "detected_source_operators": [],
            "ambiguities_resolved": True,
        }
    choices = normalize_semantic_choices(semantic_choices)
    try:
        expression = ast.parse(raw_formula, mode="eval")
        translated = _RongliangDialectTranslator(choices).visit(expression)
        ast.fix_missing_locations(translated)
        canonical_formula = ast.unparse(translated)
    except SourceFormulaDialectError:
        raise
    except (SyntaxError, TypeError, ValueError) as exc:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_FORMULA_INVALID,
            (f"{type(exc).__name__}: {exc}",),
        ) from exc
    contract = {
        "contract_version": SOURCE_DIALECT_CONTRACT_VERSION,
        "dialect_id": SOURCE_DIALECT_ID,
        "source_reference": SOURCE_DIALECT_REFERENCE,
        "raw_formula": raw_formula,
        "raw_formula_sha256": _sha256_text(raw_formula),
        "canonical_formula": canonical_formula,
        "semantic_choices": choices,
        "detected_source_operators": detected,
        "ambiguities_resolved": True,
        "unit_translation": {"CHANGE_PCT": "returns=pct_chg/100"},
        "source_conflicts": [
            "TS_MAX_SUM body describes contiguous subwindows while the footnote describes top-k values.",
            "TS_MAX_SKEW and TS_MIN_SKEW do not freeze estimator or nested-window semantics.",
            "S_LOG_LP is treated as the source typo for documented S_LOG_1P.",
        ],
    }
    contract["contract_sha256"] = _sha256_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return contract


def valid_source_formula_contract(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if (
        value.get("contract_version") != SOURCE_DIALECT_CONTRACT_VERSION
        or value.get("dialect_id") != SOURCE_DIALECT_ID
    ):
        return False
    try:
        expected = resolve_source_formula(
            str(value.get("raw_formula") or ""),
            value.get("semantic_choices")
            if isinstance(value.get("semantic_choices"), Mapping)
            else None,
        )
    except SourceFormulaDialectError:
        return False
    return dict(value) == expected
