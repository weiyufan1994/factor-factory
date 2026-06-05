from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROMPT_FILES = {
    "step2": ROOT / "skills/factor-forge-step2/references/prompts.md",
    "step3": ROOT / "skills/factor-forge-step3/SKILL.md",
    "step4": ROOT / "skills/factor-forge-step4/SKILL.md",
    "step6": ROOT / "skills/factor-forge-step6/references/prompts.md",
}

REQUIRED_TERMS = {
    "all": [
        "unit policy",
        "lookback policy",
        "leakage policy",
    ],
    "step2": [
        "standard_formula_fields_contract",
        "derive if needed",
        "source fields",
    ],
    "step3": ["derived_field_contract", "Step3B formal factor values"],
    "step4": ["acceptance_summary", "qlib_native_status", "qlib partial success"],
    "step6": [
        "evidence_status",
        "formula_implied_information",
        "metric_anomaly_review",
        "model_linked_metric_signature",
        "volatility_drag",
        "drawdown_recovery_area",
        "component_ablation",
        "direction_losing_transform_review",
        "partial run",
        "raw formula restatement",
        "generic stochastic process",
    ],
}

FORBIDDEN_PATTERNS = [
    "derive if needed without source fields",
    "qlib partial success",
    "Step3B formal factor values",
    "partial run without layer",
    "raw formula restatement as mechanism",
    "generic stochastic process as explanation",
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
            results[f"{key}_mentions_ban_{pattern}"] = pattern.lower() in lower
    failed = [name for name, ok in results.items() if not ok]
    print({"verdict": "ACCEPT" if not failed else "BLOCK", "failed": failed})
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
