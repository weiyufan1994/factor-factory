from __future__ import annotations

from .schema import VALID_TOOLKITS


TOOLKIT_DESCRIPTIONS = {
    "probability_theory": "State variables, conditional expectations, and measurable information sets.",
    "statistics": "Estimator bias, variance, sampling stability, ranks, and diagnostics.",
    "stochastic_process_calculus": "Latent drift, diffusion, jump, reversal, and stopping-time structure.",
    "time_series_and_filtering": "Lags, rolling windows, smoothing kernels, persistence, and delay tradeoffs.",
    "linear_algebra": "Projection, residualization, covariance, PCA, and exposure decomposition.",
    "functional_analysis": "Kernel transforms, norms, regularization, and stability of functional estimators.",
    "real_analysis": "Monotonicity, continuity, thresholds, and comparative statics.",
    "ordinary_differential_equations": "Continuous-time adjustment or mean-reversion dynamics when explicitly modeled.",
    "partial_differential_equations": "State-dependent evolution surfaces when explicitly modeled.",
    "optimization_and_control": "Constraint optimization, control response, and institutional behavior under rules.",
    "information_theory": "Information compression, signal entropy, and surprise.",
    "accounting_or_valuation_identity": "Residual income, DCF, book value, profitability, and valuation identities.",
    "microstructure_model": "Liquidity, volume pressure, attention, impact, and price-volume dependence.",
    "constraint_model": "Mandates, index rules, funding, capacity, and objective constraints.",
}


def toolkit_description(name: str) -> str:
    if name not in VALID_TOOLKITS:
        return "unknown toolkit"
    return TOOLKIT_DESCRIPTIONS.get(name, name)
