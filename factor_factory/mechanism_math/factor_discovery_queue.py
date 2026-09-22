from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from factor_factory.mechanism_math.equation_registry import equation_template


@dataclass(frozen=True)
class DiscoveryCandidate:
    candidate_id: str
    source_equation_id: str
    detector_hypothesis: str
    observable_inputs: tuple[str, ...]
    measurement_equation: str
    expected_metric_signature: tuple[str, ...]
    expected_cost_risk_profile: tuple[str, ...]
    stochastic_benchmark_terms: tuple[str, ...]
    falsification_tests: tuple[str, ...]
    branch_action: str
    auto_run_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_discovery_candidate(candidate: DiscoveryCandidate) -> tuple[str, ...]:
    block_codes: list[str] = []
    if not candidate.observable_inputs:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_OBSERVABLES_MISSING")
    if not candidate.expected_metric_signature:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_METRIC_SIGNATURE_MISSING")
    if not candidate.expected_cost_risk_profile:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_COST_RISK_MISSING")
    if not str(candidate.measurement_equation or "").strip():
        block_codes.append("BLOCK_DIRAC_DISCOVERY_MEASUREMENT_EQUATION_MISSING")
    if not candidate.stochastic_benchmark_terms:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_BENCHMARK_TERMS_MISSING")
    if not candidate.falsification_tests:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_FALSIFICATION_TESTS_MISSING")
    if candidate.auto_run_allowed:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_AUTORUN_FORBIDDEN")
    if candidate.branch_action not in {"review_only", "human_approval_required"}:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_BRANCH_ACTION_INVALID")
    if equation_template(candidate.source_equation_id) is None:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_SOURCE_EQUATION_UNKNOWN")
    return tuple(block_codes)


def square_root_impact_candidates() -> list[DiscoveryCandidate]:
    return [
        DiscoveryCandidate(
            candidate_id="sqrt_impact_residual_absorption_v1",
            source_equation_id="square_root_impact_invariance",
            detector_hypothesis="Actual short-horizon impact below sigma*sqrt(Q/V) detects hidden liquidity or absorption capacity.",
            observable_inputs=("minute_price", "minute_volume", "daily_volatility", "adv", "spread_or_proxy"),
            measurement_equation="impact_residual_t = realized_impact_t - sigma_t * sqrt(Q_t / V_t)",
            expected_metric_signature=(
                "negative residual with high absorption predicts continuation if informed demand is being absorbed",
                "positive residual predicts reversal when liquidity withdrawal dominates",
            ),
            expected_cost_risk_profile=(
                "turnover cost is COGS and must be netted before promotion",
                "short-horizon volatility drag and jump risk must be measured",
            ),
            stochastic_benchmark_terms=("friction", "observation_equation", "jump"),
            falsification_tests=("Residual has no conditional return or volatility signature after liquidity controls.",),
            branch_action="review_only",
        )
    ]


def disposition_feedback_candidates() -> list[DiscoveryCandidate]:
    return [
        DiscoveryCandidate(
            candidate_id="trapped_position_absorption_v1",
            source_equation_id="disposition_feedback_pressure",
            detector_hypothesis="Breakout through high trapped-position density with shallow pullback detects absorption of delayed selling pressure.",
            observable_inputs=("close", "volume", "turnover", "cost_basis_density_proxy", "post_break_pullback"),
            measurement_equation="absorption_strength_t = breakout_volume_t / max(post_break_pullback_depth_t, epsilon)",
            expected_metric_signature=(
                "high absorption strength predicts positive forward return",
                "signal weakens when trapped-position density is low",
            ),
            expected_cost_risk_profile=(
                "high turnover raises COGS and can erase gross edge",
                "drawdown recovery area should be small if absorption thesis is correct",
            ),
            stochastic_benchmark_terms=("drift", "friction", "regime_transition"),
            falsification_tests=("Breakout absorption does not improve return after controlling for momentum and liquidity.",),
            branch_action="review_only",
        )
    ]


def build_default_discovery_queue() -> dict[str, Any]:
    candidates = [*square_root_impact_candidates(), *disposition_feedback_candidates()]
    candidate_dicts = []
    all_blocks: dict[str, tuple[str, ...]] = {}
    for candidate in candidates:
        blocks = validate_discovery_candidate(candidate)
        all_blocks[candidate.candidate_id] = blocks
        candidate_dicts.append(candidate.to_dict())
    return {
        "version": "factorforge_dirac_discovery_queue_v1",
        "auto_run_allowed": False,
        "candidates": candidate_dicts,
        "validation_blocks": all_blocks,
    }
