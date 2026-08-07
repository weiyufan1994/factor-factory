#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.validator import validate_component_council_packet


def valid_packet() -> dict:
    return {
        'component_revision_axes': [{'component': 'rank(vwap)', 'axis': 'ablation'}],
        'component_ablation_plan': [{'component': 'rank(vwap)', 'metric': 'rank_ic'}],
        'direction_losing_transform_review': {'abs_corr': 'reviewed'},
        'component_independence_review': {'components': 'not assumed independent'},
        'market_outcome_projection_falsification': {'metric': 'long_side_return'},
        'branch_kill_criteria': ['kill if long-side remains negative after sign review'],
        'time_scale_consistency_review': {'mixed_horizon': 'reviewed'},
        'positive_ic_negative_long_branch': {'branch': 'direction anomaly'},
    }


def has(reasons: list[str], token: str) -> bool:
    return any(token in reason for reason in reasons)


def main() -> None:
    formula = 'rank(vwap) + abs(corr(close, volume, 5)) + sum(returns, 250)'
    metrics = {'rank_ic_mean': 0.02, 'long_side_annual_return': -0.1}
    cases: dict[str, dict] = {}

    packet = valid_packet()
    packet['component_ablation_plan'] = []
    reasons = validate_component_council_packet(packet, formula_text=formula, metrics=metrics)
    cases['composite_formula_without_ablation_blocks'] = {'ok': has(reasons, 'BLOCK_COUNCIL_COMPONENT_ABLATION_MISSING'), 'reasons': reasons}

    packet = valid_packet()
    packet['direction_losing_transform_review'] = {}
    reasons = validate_component_council_packet(packet, formula_text=formula, metrics=metrics)
    cases['abs_corr_without_direction_review_blocks'] = {'ok': has(reasons, 'BLOCK_COUNCIL_DIRECTION_LOSS_REVIEW_MISSING'), 'reasons': reasons}

    packet = valid_packet()
    packet.pop('time_scale_consistency_review')
    reasons = validate_component_council_packet(packet, formula_text=formula, metrics=metrics)
    cases['mixed_horizon_without_time_scale_review_blocks'] = {'ok': has(reasons, 'BLOCK_COUNCIL_TIME_SCALE_REVIEW_MISSING'), 'reasons': reasons}

    packet = valid_packet()
    packet.pop('positive_ic_negative_long_branch')
    reasons = validate_component_council_packet(packet, formula_text=formula, metrics=metrics)
    cases['positive_ic_negative_long_without_branch_blocks'] = {'ok': has(reasons, 'BLOCK_COUNCIL_POSITIVE_IC_NEGATIVE_LONG_BRANCH_MISSING'), 'reasons': reasons}

    reasons = validate_component_council_packet(valid_packet(), formula_text=formula, metrics=metrics)
    cases['valid_composite_council_packet_passes'] = {'ok': not reasons, 'reasons': reasons}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
