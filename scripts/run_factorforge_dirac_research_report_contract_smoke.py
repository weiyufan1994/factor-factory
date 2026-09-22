#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.validator import validate_dirac_research_report_contract


def valid_report() -> dict:
    return {
        'research_equation_or_soft_law': {'equation': 'E[r|latent_state] changes with estimator state'},
        'formula_implied_information': [{
            'formula_component': 'rank(vwap)',
            'observable': 'price paid by volume',
            'implied_mathematical_object': 'liquidity pressure state revealed by price-volume execution imbalance',
            'payer_or_constraint': 'liquidity demanders paying immediacy cost',
            'expected_sign': 'negative after crowded high-score state',
            'falsification_metric': 'long_side_annual_return',
        }],
        'metric_anomaly_review': {
            'positive_ic_negative_long_side': True,
            'classifications': [{'classification': 'direction_or_sign_error', 'reasoning': 'rank IC and long-side disagree'}],
        },
        'model_linked_metric_signature': {'rank_ic': 'tests observable estimator ordering'},
        'market_outcome_projection_consistency_check': {'value_payoff_or_return_map': 'explicit', 'falsification_metric': 'rank_ic'},
        'volatility_drag_review': {'volatility_drag': 'reviewed'},
        'drawdown_recovery_area_review': {'drawdown_recovery_area': 'reviewed'},
        'component_level_revision_axes': [{'component': 'vwap', 'axis': 'ablation'}],
        'direction_losing_transform_review': {'abs_corr': 'not used'},
    }


def has(reasons: list[str], token: str) -> bool:
    return any(token in reason for reason in reasons)


def main() -> None:
    cases: dict[str, dict] = {}
    for case_name, field, token in [
        ('missing_formula_implied_information_blocks', 'formula_implied_information', 'BLOCK_DIRAC_FORMULA_IMPLIED_INFORMATION_MISSING'),
        ('missing_anomaly_classification_blocks', 'metric_anomaly_review', 'BLOCK_DIRAC_ANOMALY_CLASSIFICATION_MISSING'),
        ('missing_model_linked_metrics_blocks', 'model_linked_metric_signature', 'BLOCK_DIRAC_MODEL_LINKED_METRICS_MISSING'),
        ('missing_market_outcome_projection_check_blocks', 'market_outcome_projection_consistency_check', 'BLOCK_DIRAC_MARKET_OUTCOME_PROJECTION_CHECK_MISSING'),
        ('missing_volatility_drag_review_blocks', 'volatility_drag_review', 'BLOCK_DIRAC_VOLATILITY_DRAG_REVIEW_MISSING'),
        ('missing_drawdown_recovery_area_review_blocks', 'drawdown_recovery_area_review', 'BLOCK_DIRAC_DRAWDOWN_RECOVERY_AREA_REVIEW_MISSING'),
    ]:
        report = valid_report()
        report.pop(field)
        reasons = validate_dirac_research_report_contract(report)
        cases[case_name] = {'ok': has(reasons, token), 'reasons': reasons}

    report = valid_report()
    report['formula_implied_information'][0]['implied_mathematical_object'] = 'close'
    reasons = validate_dirac_research_report_contract(report)
    cases['raw_formula_restatement_blocks'] = {'ok': has(reasons, 'BLOCK_DIRAC_FORMULA_RAW_RESTATEMENT'), 'reasons': reasons}

    report = valid_report()
    report['metric_anomaly_review']['classifications'] = [{'classification': 'bug', 'reasoning': 'not the required disagreement branch'}]
    reasons = validate_dirac_research_report_contract(report)
    cases['positive_ic_negative_long_without_anomaly_blocks'] = {'ok': has(reasons, 'BLOCK_DIRAC_POSITIVE_IC_NEGATIVE_LONG_WITHOUT_ANOMALY'), 'reasons': reasons}

    reasons = validate_dirac_research_report_contract(valid_report())
    cases['valid_dirac_research_report_passes'] = {'ok': not reasons, 'reasons': reasons}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
