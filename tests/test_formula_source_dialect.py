from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula.evaluator import evaluate_formula_frame, evaluate_formula_ir
from factor_factory.formula.polars_evaluator import polars_dependency_available
from factor_factory.formula.parser import parse_formula, resolve_formula_fields_for_schema
from factor_factory.formula.qlib_codegen import to_qlib_expression
from factor_factory.formula.semantics import (
    max_formula_ir_lookback,
    requires_cross_sectional_sample,
)
from factor_factory.formula.source_dialects import (
    BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
    SourceFormulaDialectError,
    migrate_legacy_source_formula_contract,
    recognize_legacy_source_formula_contract,
    resolve_source_formula,
    valid_source_formula_contract,
)


SOURCE_FORMULA = (
    "-1 * (NORMALIZE(S_LOG_LP(TS_KURTOSIS(CLOSE,5))"
    "+TS_MAX_SKEW(VOLUME,5,3)-TS_MIN_SKEW(VOLUME,20,3)"
    "+TS_MAX_SUM(CHANGE_PCT,20,5),STANDARDIZE=1))"
)


def _choices(**overrides: str) -> dict[str, str]:
    choices = {
        "kurtosis_convention": "excess_unbiased",
        "skew_convention": "inner_window_extrema",
        "max_sum_convention": "contiguous_subwindow",
        "zscore_ddof": "0",
    }
    choices.update(overrides)
    return choices


def _source_evidence_authority(**overrides: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "kind": "specific_source_evidence",
        "reference": "source-report.pdf#page=7",
        "rationale": "The cited operator definitions fix these implementation choices.",
        "source_excerpt": "TS_MAX_SUM uses the maximum contiguous k-period sum.",
        "implementation_choices_not_performance_selected": True,
    }
    authority.update(overrides)
    return authority


def _override_authority(**overrides: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "kind": "explicit_user_research_override",
        "reference": "research-decision:FF-2026-08-09-01",
        "rationale": "Freeze one auditable implementation before evaluation.",
        "override_reason": "The source does not resolve the documented operator conflict.",
        "implementation_choices_not_performance_selected": True,
    }
    authority.update(overrides)
    return authority


def _source_ir(
    *,
    semantic_authority: dict[str, object] | None = None,
    **overrides: str,
) -> tuple[dict, dict]:
    contract = resolve_source_formula(
        SOURCE_FORMULA,
        _choices(**overrides),
        semantic_authority or _source_evidence_authority(),
    )
    formula_ir = parse_formula(
        contract["canonical_formula"],
        available_columns=["close", "volume", "pct_chg"],
        source_dialect_contract=contract,
        raise_on_error=True,
    )
    return contract, formula_ir


def _frame() -> pd.DataFrame:
    rows = []
    for stock_index, ts_code in enumerate(("000001.SZ", "000002.SZ", "600000.SH")):
        for day in range(1, 27):
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": f"2026-01-{day:02d}",
                    "close": 10.0 + stock_index * 0.7 + day * 0.03 + np.sin(day + stock_index),
                    "volume": 1000.0 + stock_index * 90.0 + day * day + (day % 4) * 17.0,
                    "pct_chg": (stock_index + 1) * 0.2 + np.cos(day) * 1.5,
                }
            )
    return pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def test_source_formula_requires_explicit_semantic_resolution() -> None:
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(SOURCE_FORMULA, None)

    assert exc.value.token == BLOCK_SOURCE_SEMANTICS_UNRESOLVED


def test_partial_source_formula_requires_only_relevant_semantic_choices() -> None:
    contract = resolve_source_formula(
        "TS_KURTOSIS(CLOSE,5)+TS_MAX_SKEW(VOLUME,5,3)",
        {
            "kurtosis_convention": "excess_unbiased",
            "skew_convention": "inner_window_extrema",
        },
        _source_evidence_authority(),
    )

    assert contract["semantic_choices"] == {
        "kurtosis_convention": "excess_unbiased",
        "skew_convention": "inner_window_extrema",
    }
    assert contract["implementation_variant_set"]["implemented_variant_count"] == 4
    assert not any("TS_MAX_SUM" in item for item in contract["source_conflicts"])


def test_raw_semantic_enum_selection_without_authority_is_blocked() -> None:
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(SOURCE_FORMULA, _choices())

    assert exc.value.token == BLOCK_SOURCE_SEMANTICS_UNRESOLVED
    assert any("semantic_authority.kind" in reason for reason in exc.value.reasons)
    assert any("not_performance_selected" in reason for reason in exc.value.reasons)


@pytest.mark.parametrize(
    "authority,missing_reason",
    [
        (
            _source_evidence_authority(source_excerpt=""),
            "source_excerpt is required",
        ),
        (_override_authority(override_reason=""), "override_reason"),
        (
            _source_evidence_authority(
                implementation_choices_not_performance_selected=False
            ),
            "not_performance_selected",
        ),
        (_source_evidence_authority(rationale=""), "semantic_authority.rationale"),
    ],
)
def test_semantic_authority_requires_mode_specific_provenance(
    authority: dict[str, object],
    missing_reason: str,
) -> None:
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(SOURCE_FORMULA, _choices(), authority)

    assert any(missing_reason in reason for reason in exc.value.reasons)


def test_source_formula_translation_freezes_semantics_and_true_lookback() -> None:
    contract, formula_ir = _source_ir()

    assert contract["implementation_choices_frozen"] is True
    assert contract["source_meaning_verified"] is True
    assert (
        contract["source_meaning_status"]
        == "verified_from_auditable_specific_source_evidence"
    )
    assert contract["source_authenticity_verified"] is False
    assert contract["source_verification_scope"] == (
        "submitted_request_evidence_integrity"
    )
    assert contract["semantic_authority"]["source_excerpt_sha256"] == hashlib.sha256(
        contract["semantic_authority"]["source_excerpt"].encode("utf-8")
    ).hexdigest()
    evidence = contract["semantic_authority"]["evidence_object"]
    assert evidence["artifact_path"] == "request://semantic_authority/source_excerpt"
    assert evidence["artifact_sha256"] == evidence["excerpt_sha256"]
    assert evidence["hash_verified"] is True
    assert evidence["network_access_used"] is False
    assert contract["implementation_variant_set"] == {
        "scope": "bounded_implementation_set",
        "implemented_variant_count": 16,
        "exhaustive_source_truth": False,
    }
    assert contract["unit_translation"] == {"CHANGE_PCT": "returns=pct_chg/100"}
    assert {
        "cs_zscore",
        "signed_log1p",
        "rolling_excess_kurtosis",
        "rolling_max_inner_skew",
        "rolling_min_inner_skew",
        "rolling_max_subwindow_sum",
    } <= set(formula_ir["operator_set"])
    assert formula_ir["resolved_fields"] == {
        "close": "close",
        "returns": "pct_chg",
        "volume": "volume",
    }
    assert max_formula_ir_lookback(formula_ir) == 20
    assert requires_cross_sectional_sample(formula_ir) is True
    assert formula_ir["operator_semantic_hash"]
    assert valid_source_formula_contract(contract) is True


def test_source_formula_contract_hash_and_semantics_are_not_forgeable() -> None:
    contract, _formula_ir = _source_ir()
    tampered = dict(contract)
    tampered["canonical_formula"] = "close"

    assert valid_source_formula_contract(tampered) is False

    provenance_tampered = json.loads(json.dumps(contract))
    provenance_tampered["semantic_authority"]["rationale"] = "Selected after backtest review."
    assert valid_source_formula_contract(provenance_tampered) is False

    excerpt_tampered = json.loads(json.dumps(contract))
    excerpt_tampered["semantic_authority"]["source_excerpt"] += " tampered"
    assert valid_source_formula_contract(excerpt_tampered) is False


def test_excerpt_hash_only_is_blocked_and_explicit_override_remains_valid() -> None:
    excerpt = "TS_MAX_SUM uses the maximum contiguous k-period sum."
    hash_only = _source_evidence_authority(
        source_excerpt="",
        source_excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    )
    with pytest.raises(SourceFormulaDialectError) as exc:
        _source_ir(semantic_authority=hash_only)

    override_contract, _ = _source_ir(semantic_authority=_override_authority())

    assert any("hash-only evidence" in reason for reason in exc.value.reasons)
    assert override_contract["source_meaning_verified"] is False
    assert (
        override_contract["source_meaning_status"]
        == "not_verified_explicit_user_research_override"
    )
    assert valid_source_formula_contract(override_contract) is True


@pytest.mark.parametrize(
    "authority",
    [
        _source_evidence_authority(
            reference="x",
            source_excerpt="x",
            source_excerpt_sha256="0" * 64,
        ),
        _source_evidence_authority(
            reference="x",
            source_excerpt="x",
            source_excerpt_sha256=hashlib.sha256(b"x").hexdigest(),
        ),
    ],
)
def test_arbitrary_reference_or_forged_excerpt_hash_cannot_verify_source(
    authority: dict[str, object],
) -> None:
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(SOURCE_FORMULA, _choices(), authority)

    assert exc.value.token == BLOCK_SOURCE_SEMANTICS_UNRESOLVED
    assert any(
        "source locator" in reason or "does not match source_excerpt" in reason
        for reason in exc.value.reasons
    )


def test_workspace_evidence_requires_readable_hash_bound_artifact(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "evidence" / "operator-semantics.md"
    evidence_path.parent.mkdir()
    excerpt = "TS_MAX_SUM uses the maximum contiguous k-period sum."
    evidence_path.write_text(
        "# Operator semantics\n\n" + excerpt + "\n",
        encoding="utf-8",
    )
    artifact_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    authority = {
        "kind": "specific_source_evidence",
        "reference": "evidence/operator-semantics.md#line=3",
        "rationale": "The checked workspace artifact freezes the implementation choice.",
        "implementation_choices_not_performance_selected": True,
        "evidence_object": {
            "storage_kind": "workspace_artifact",
            "artifact_path": "evidence/operator-semantics.md",
            "artifact_sha256": artifact_sha256,
            "locator": "evidence/operator-semantics.md#line=3",
            "excerpt": excerpt,
        },
    }

    contract = resolve_source_formula(
        SOURCE_FORMULA,
        _choices(),
        authority,
        evidence_root=tmp_path,
    )

    assert contract["source_meaning_verified"] is True
    assert contract["source_authenticity_verified"] is True
    assert contract["semantic_authority"]["evidence_object"]["read_verified"] is True
    assert valid_source_formula_contract(contract, evidence_root=tmp_path) is True
    assert valid_source_formula_contract(contract) is False

    forged = json.loads(json.dumps(authority))
    forged["evidence_object"]["artifact_sha256"] = "0" * 64
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(
            SOURCE_FORMULA,
            _choices(),
            forged,
            evidence_root=tmp_path,
        )
    assert any("does not match artifact" in reason for reason in exc.value.reasons)

    evidence_path.write_text("tampered after contract creation\n", encoding="utf-8")
    assert valid_source_formula_contract(contract, evidence_root=tmp_path) is False


def test_workspace_evidence_cannot_escape_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-source-evidence.md"
    outside.write_text("TS_MAX_SUM source meaning", encoding="utf-8")
    authority = {
        "kind": "specific_source_evidence",
        "reference": "../outside-source-evidence.md#line=1",
        "rationale": "Attempted escaped evidence.",
        "implementation_choices_not_performance_selected": True,
        "evidence_object": {
            "storage_kind": "workspace_artifact",
            "artifact_path": "../outside-source-evidence.md",
            "artifact_sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            "locator": "../outside-source-evidence.md#line=1",
            "excerpt": "TS_MAX_SUM source meaning",
        },
    }

    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(
            SOURCE_FORMULA,
            _choices(),
            authority,
            evidence_root=tmp_path,
        )

    assert any(
        "workspace-relative" in reason or "locator" in reason
        for reason in exc.value.reasons
    )


def test_provenance_changes_contract_and_formula_identity_without_changing_formula() -> None:
    first, first_ir = _source_ir()
    second, second_ir = _source_ir(
        semantic_authority=_source_evidence_authority(
            reference="source-report.pdf#page=8",
            rationale="A second specific source location supports the same frozen choices.",
        )
    )

    assert first["canonical_formula"] == second["canonical_formula"]
    assert first["contract_sha256"] != second["contract_sha256"]
    assert first_ir["formula_hash"] != second_ir["formula_hash"]


def test_canonical_formula_remains_valid_without_source_provenance() -> None:
    contract = resolve_source_formula("-(open / pre_close - 1)", None)

    assert contract["dialect_id"] == "canonical_factorforge_formula_ir"
    assert contract["canonical_formula"] == "-(open / pre_close - 1)"
    assert contract["semantic_choices"] == {}
    assert "semantic_authority" not in contract
    assert "contract_sha256" not in contract


def test_v1_contract_is_recognized_only_for_explicit_migration() -> None:
    current, _ = _source_ir()
    legacy = {
        "contract_version": "factorforge_formula_source_dialect_v1",
        "dialect_id": "rongliang_factor365_20260707_v1",
        "source_reference": current["source_reference"],
        "raw_formula": current["raw_formula"],
        "raw_formula_sha256": current["raw_formula_sha256"],
        "canonical_formula": current["canonical_formula"],
        "semantic_choices": current["semantic_choices"],
        "detected_source_operators": current["detected_source_operators"],
        "ambiguities_resolved": True,
        "unit_translation": current["unit_translation"],
        "source_conflicts": current["source_conflicts"],
    }
    legacy["contract_sha256"] = hashlib.sha256(
        json.dumps(
            legacy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert recognize_legacy_source_formula_contract(legacy) is True
    assert valid_source_formula_contract(legacy) is False
    recoverable = migrate_legacy_source_formula_contract(legacy, None)
    assert recoverable["contract_version"] == (
        "factorforge_formula_source_dialect_migration_v1"
    )
    assert recoverable["authority_resolution"]["status"] == "AUTHORITY_REQUIRED"
    assert recoverable["source_meaning_verified"] is False
    assert recoverable["formal_execution_eligible"] is False
    assert recoverable["canonical_formula"] == legacy["canonical_formula"]
    assert valid_source_formula_contract(recoverable) is False

    migrated = migrate_legacy_source_formula_contract(
        legacy,
        _override_authority(),
    )
    assert migrated["contract_version"] == "factorforge_formula_source_dialect_v2"
    assert valid_source_formula_contract(migrated) is True


def test_semantic_choices_change_canonical_identity_instead_of_silently_aliasing() -> None:
    contiguous, contiguous_ir = _source_ir()
    topk, topk_ir = _source_ir(
        kurtosis_convention="pearson_unbiased",
        skew_convention="order_statistic_subset",
        max_sum_convention="topk_values",
        zscore_ddof="1",
    )

    assert contiguous["contract_sha256"] != topk["contract_sha256"]
    assert contiguous_ir["formula_hash"] != topk_ir["formula_hash"]
    assert "rolling_topk_sum" in topk_ir["operator_set"]
    assert "rolling_topk_skew" in topk_ir["operator_set"]
    assert "rolling_bottomk_skew" in topk_ir["operator_set"]
    assert "rolling_pearson_kurtosis" in topk_ir["operator_set"]


def test_source_formula_is_strictly_trailing_and_future_mutation_cannot_change_past() -> None:
    _contract, formula_ir = _source_ir()
    frame = _frame()
    baseline = evaluate_formula_ir(formula_ir, frame, engine="reference")

    mutated = frame.copy()
    future = mutated["trade_date"] == "2026-01-26"
    mutated.loc[future, ["close", "volume", "pct_chg"]] = [999.0, 9_999_999.0, 80.0]
    changed = evaluate_formula_ir(formula_ir, mutated, engine="reference")

    past = frame["trade_date"] < "2026-01-26"
    np.testing.assert_allclose(
        baseline[past].to_numpy(),
        changed[past].to_numpy(),
        rtol=1e-6,
        atol=1e-10,
        equal_nan=True,
    )
    assert baseline[future].notna().all()
    assert not np.allclose(
        baseline[future].to_numpy(),
        changed[future].to_numpy(),
        equal_nan=True,
    )


def test_returns_alias_converts_percentage_points_to_decimal_returns() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["2026-01-01", "2026-01-02"],
            "pct_chg": [1.0, -2.5],
        }
    )

    result = evaluate_formula_ir(formula_ir, frame, engine="reference")

    np.testing.assert_allclose(result.to_numpy(), np.array([0.01, -0.025]))


def test_qlib_codegen_preserves_decimal_return_unit_for_pct_chg_alias() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )

    qlib = to_qlib_expression(formula_ir)

    assert qlib["status"] == "supported"
    assert qlib["expression"] == "($pct_chg / 100.0)"


def test_schema_rebind_preserves_formula_identity_and_rehashes_execution_binding() -> None:
    original = parse_formula(
        "returns",
        available_columns=["returns"],
        raise_on_error=True,
    )
    rebound = resolve_formula_fields_for_schema(original, ["pct_chg"])
    directly_bound = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )

    assert rebound["formula_hash"] == original["formula_hash"]
    assert rebound["formula_hash"] == directly_bound["formula_hash"]
    assert rebound["resolved_binding_hash"] != original["resolved_binding_hash"]
    assert rebound["resolved_binding_hash"] == directly_bound["resolved_binding_hash"]
    assert rebound["root"] == directly_bound["root"]


@pytest.mark.skipif(
    not polars_dependency_available(),
    reason="Polars dependency is not installed",
)
def test_polars_preserves_decimal_return_unit_for_pct_chg_alias() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["2026-01-01", "2026-01-02"],
            "pct_chg": [1.0, -2.5],
        }
    )

    reference = evaluate_formula_frame(formula_ir, frame, engine="reference")
    optimized = evaluate_formula_frame(formula_ir, frame, engine="optimized")
    polars = evaluate_formula_frame(formula_ir, frame, engine="polars_experimental")

    expected = np.array([0.01, -0.025])
    np.testing.assert_allclose(reference["factor_value"].to_numpy(), expected)
    np.testing.assert_allclose(optimized["factor_value"].to_numpy(), expected)
    np.testing.assert_allclose(polars["factor_value"].to_numpy(), expected)
