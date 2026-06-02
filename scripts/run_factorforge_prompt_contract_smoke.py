from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROMPT_FILES = {
    "step1": ROOT / "skills/factor-forge-step1/references/prompts.md",
    "step2": ROOT / "skills/factor-forge-step2/references/prompts.md",
    "step6": ROOT / "skills/factor-forge-step6/references/prompts.md",
}

REQUIRED_TERMS = {
    "all": [
        "classified research equation",
        "equation_status",
        "assumptions",
        "validity_scope",
        "primary_mathematical_model",
        "t0_t1_stochastic_benchmark",
        "observable_detector_contract",
        "formula_implied_information",
        "expected_metric_signature",
        "falsification_tests",
        "kill_criteria",
    ],
    "step1": [
        "payer_or_forced_counterparty",
        "why_the_payer_cannot_stop",
        "participant_constraint_loop",
        "equation_quality",
        "do not select stochastic process as the primary model by default",
    ],
    "step2": [
        "formula is an observable estimator",
        "measurement_equation",
        "null_state_behavior",
        "direct_code must implement the estimator only after the mechanism contract is coherent",
        "raw-field restatement is invalid",
    ],
    "step6": [
        "research_equation_reviewer",
        "metric_links",
        "turnover cost is COGS",
        "volatility_drag",
        "drawdown_recovery_area",
        "Dirac-style anomaly review",
        "equation-to-factor discovery queue",
    ],
}

FORBIDDEN_PATTERNS = [
    "just explain the formula",
    "stochastic process is always the primary model",
    "IC alone proves the factor",
    "formula_text is the mechanism",
]


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    results: dict[str, bool] = {}
    for key, path in PROMPT_FILES.items():
        text = _read(path)
        lower = text.lower()
        for term in REQUIRED_TERMS["all"] + REQUIRED_TERMS[key]:
            results[f"{key}_contains_{term}"] = term.lower() in lower
        for pattern in FORBIDDEN_PATTERNS:
            results[f"{key}_forbids_{pattern}"] = pattern.lower() not in lower
    failed = [name for name, ok in results.items() if not ok]
    print({"verdict": "ACCEPT" if not failed else "BLOCK", "failed": failed})
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
