from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from factor_factory.research_conjecture import validate_protocol_bundle
from factor_factory.research_proof import validate_factor_proof_certificate
from factor_factory.ultimate_loop.state import validate_wrapper_proof_for_loop


SUMMARY_CONTRACT_VERSION = "factorforge_console_ultimate_summary_v2"
VALID_FACTOR_VERDICTS = {"ACCEPT", "REJECT", "ITERATE", "BLOCK", "UNKNOWN"}
PAUSE_STATES = {
    "awaiting_main_agent_mechanism_memo",
    "awaiting_main_agent_mechanism_memo_revision",
    "awaiting_main_agent_mechanism_manual_review",
    "awaiting_agent_results",
    "awaiting_main_agent_council_synthesis",
    "awaiting_next_derivation",
}
MAX_EVIDENCE_BYTES = 12 * 1024 * 1024
BLOCK_FORMAL_VALIDATION_EXCEPTION = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_VALIDATION_EXCEPTION"
BLOCK_FORMAL_VERIFIER_MISSING = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_VERIFIER_MISSING"
BLOCK_FORMAL_VERIFIER_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_VERIFIER_MISMATCH"
BLOCK_FORMAL_VERDICT_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_VERDICT_MISMATCH"
BLOCK_FORMAL_WRAPPER_INVALID = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_WRAPPER_INVALID"
BLOCK_EVIDENCE_LINEAGE_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_EVIDENCE_LINEAGE_MISMATCH"
BOUND_VERIFIER_VERSION = "factorforge_console_bound_factor_proof_verifier_v1"

ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "loop_report": ("objects/runtime_context/ultimate_loop_report*.json",),
    "wrapper_report": ("objects/runtime_context/ultimate_run_report*.json",),
    "proof_certificate": ("objects/research_protocol/factor_proof_certificate*.json",),
    "proof_verifier": ("objects/research_protocol/factor_proof_verifier_report*.json",),
    "quality_gate": ("objects/research_protocol/research_quality_gate*.json",),
    "main_agent_mechanism_memo": (
        "objects/research_iteration_master/main_agent_mechanism_memo__*.json",
    ),
    "loop_research_brief": (
        "objects/research_iteration_master/loop_research_brief*.json",
    ),
    "research_state": ("objects/research_protocol/research_state*.json",),
    "factor_spec": ("objects/factor_spec_master/factor_spec_master*.json",),
    "data_prep": ("objects/data_prep_master/data_prep_master*.json",),
    "implementation_plan": (
        "objects/implementation_plan_master/implementation_plan_master*.json",
    ),
    "factor_case": ("objects/factor_case_master/factor_case_master*.json",),
    "factor_evaluation": ("objects/validation/factor_evaluation*.json",),
    "research_iteration": (
        "objects/research_iteration_master/research_iteration_master*.json",
    ),
    "paused_note": ("objects/research_iteration_master/paused_research_note*.json",),
    "council_dispatch": (
        "objects/research_iteration_master/**/agentic_council_dispatch_manifest*.json",
        "objects/runtime_context/ultimate_step6_council_dispatch_proof*.json",
    ),
    "council_summary": (
        "objects/research_iteration_master/**/revision_council_summary*.json",
    ),
    "council_synthesis": (
        "objects/research_iteration_master/**/main_agent_council_synthesis*.json",
    ),
    "terminal_rejection": (
        "objects/research_iteration_master/**/terminal_council_rejection*.json",
    ),
    "step6_handoff": ("objects/handoff/handoff_to_step6*.json",),
}

DATA_CONTRACT_FIELDS = (
    "is_window",
    "oos_window",
    "universe",
    "universe_id",
    "investability_mask_id",
    "sample_frequency",
    "forward_return_horizon",
    "forward_return_horizon_days",
    "holding_period_days",
    "rebalance_frequency",
    "signal_timestamp",
    "execution_timestamp",
    "label_start_timestamp",
    "label_end_timestamp",
    "forward_return_formula",
    "path_is_disjoint",
    "label_contract_version",
    "return_convention",
    "cost_policy_id",
    "verification_scope",
    "oos_status",
    "evaluation_window_role",
    "minimum_periods",
    "signal_period_count",
    "signal_coverage_ratio",
    "search_frozen_before_oos_release",
    "oos_evidence_included",
    "same_sample_for_all_required_metrics",
)
IMPLEMENTATION_FIELDS = (
    "implementation_mode",
    "implementation_status",
    "producer",
    "function_name",
    "entrypoint",
    "formal_entrypoint",
    "dependencies",
    "dataset_id",
    "state_dataset",
    "required_fields",
    "input_schema",
    "output_schema",
    "information_set_rules",
    "execution_semantics",
    "step4_contract",
    "implementation_mode_decision",
)
MATH_FIELDS = (
    "math_model_status",
    "model_family",
    "math_toolkits",
    "random_object",
    "state_or_object",
    "latent_state",
    "target_statistic",
    "target_functional",
    "observation_equation",
    "factor_to_state_mapping",
    "factor_as_estimator",
    "observable_estimator",
    "process_hypothesis",
    "conditional_distribution_hypothesis",
    "relationship_shape",
    "information_set",
    "deleted_information",
    "necessary_conditions",
    "expected_metric_signature",
    "mechanism_claim_ceiling",
    "falsification_tests",
    "mechanism_falsification_tests",
    "kill_criteria",
    "selected_model_family",
    "why_this_model",
    "why_not_generic_template",
    "process_or_distribution",
    "formula_as_estimator",
)
ECONOMIC_FIELDS = (
    "preferred_claim",
    "economic_mechanism",
    "economic_hypothesis",
    "payer_candidates",
    "payer",
    "receiver",
    "persistent_constraint",
    "observable_proxies",
    "current_limit",
    "failure_regimes",
    "return_source_class",
    "payer_or_counterparty",
    "why_they_pay",
    "necessary_market_structure",
)

BACKTEST_ARTIFACT_FILENAMES = {
    "rank_ic_chart": "rank_ic_timeseries.png",
    "pearson_ic_chart": "pearson_ic_timeseries.png",
    "gross_nav_chart": "long_side_nav.png",
    "net_nav_chart": "cost_adjusted_long_side_nav.png",
    "quantile_nav_chart": "quantile_nav_10groups.png",
    "long_short_diagnostic_chart": "long_short_nav_10groups.png",
    "coverage_chart": "coverage_by_day.png",
    "long_side_returns_table": "long_side_returns.csv",
    "long_side_nav_table": "long_side_nav.csv",
    "long_side_turnover_table": "long_side_turnover.csv",
    "quantile_returns_table": "quantile_returns_10groups.csv",
    "quantile_nav_table": "quantile_nav_10groups.csv",
    "quantile_summary_table": "quantile_summary_table.csv",
}

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "ic": ("ic", "pearson_ic", "ic_mean", "pearson_ic_mean"),
    "rank_ic": ("rank_ic", "rank_ic_mean", "mean_rank_ic"),
    "icir": ("icir", "rank_ic_ir", "rank_icir", "ic_ir"),
    "fama_macbeth": (
        "fama_macbeth",
        "fama_macbeth_regression",
        "fama_macbeth_risk_premium",
        "fmb",
    ),
    "long_side_after_cost": (
        "long_side_after_cost",
        "long_end",
        "cost_adjusted_long_side_return",
        "net_geometric_return_annual",
        "net_return_annual",
        "long_side_net_return",
    ),
    "turnover": (
        "turnover",
        "annual_turnover",
        "daily_turnover",
        "turnover_mean",
        "long_side_turnover_mean_daily",
        "transaction_cost",
    ),
    "drawdown": ("drawdown", "max_drawdown", "long_side_max_drawdown", "mdd"),
    "recovery": (
        "recovery",
        "recovery_days",
        "long_side_recovery_days",
        "drawdown_recovery_days",
        "recovery_area",
    ),
    "monotonicity": (
        "bucket_monotonicity",
        "monotonicity",
        "monotonicity_score",
        "decile_monotonicity",
        "quintile_monotonicity",
    ),
    "gross_final_nav": ("long_side_final_nav",),
    "net_final_nav": ("cost_adjusted_long_side_final_nav",),
    "gross_sharpe": ("long_side_sharpe",),
    "net_sharpe": ("cost_adjusted_long_side_sharpe",),
    "annual_volatility": ("long_side_annual_volatility",),
    "trading_cost": ("trading_cogs_annual", "trading_cogs_daily"),
}

_BLOCK_KEYS = {
    "blocker",
    "blockers",
    "blocker_tokens",
    "blocking_issue",
    "blocking_issues",
    "unresolved_blockers",
    "failure_reason",
    "failure_reasons",
    "blocked_reason",
    "block_reason",
    "block_reasons",
    "errors",
}
_NEXT_ACTION_KEYS = {
    "next_action",
    "next_actions",
    "recommended_next_action",
    "recommended_next_actions",
    "reopen_criteria",
    "next_questions",
}
_DENIED_PUBLIC_KEYS = re.compile(
    r"(?i)(?:^|_)(?:"
    r"path|paths|root|uri|url|source_code|command|commands|stdout|stderr|env|"
    r"secret|token|password|credential|api_key|access_key|access_key_id|private_key"
    r")(?:$|_)"
)
_PUBLIC_INTERNAL_PATH = re.compile(
    r"(?i)(?:file://\S+|s3://\S+|"
    r"/(?:Users|home|srv|private|tmp|var/lib|root|etc|opt)/[^\s\"'<>]*|"
    r"[A-Za-z]:\\[^\s\"'<>]*)"
)
_PUBLIC_SECRET_ASSIGNMENT = re.compile(
    r"(?im)(\b(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|"
    r"auth(?:orization)?[_-]?token|password|passwd)\b\s*[:=]\s*)"
    r"(?:[\"'][^\"'\r\n]{8,}[\"']|[^\s,;#\]\)}]{8,})"
)
_PUBLIC_BEARER_SECRET = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[a-z0-9._~+/=-]{12,}"
)
_PUBLIC_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)


@dataclass(frozen=True)
class UltimateRunSummary:
    report_id: str
    factor_id: str
    research_id: str
    execution_status: str
    protocol_status: str
    factor_verdict: str
    council_status: str
    formal_proof_eligible: bool
    current_stage: str
    research_method: dict[str, Any] = field(default_factory=dict)
    economic_game: Any = None
    math_mechanism: Any = None
    data_contract: dict[str, Any] = field(default_factory=dict)
    implementation_contract: dict[str, Any] = field(default_factory=dict)
    core_metrics: dict[str, Any] = field(default_factory=dict)
    metric_sources: dict[str, str] = field(default_factory=dict)
    research_notebook: dict[str, Any] = field(default_factory=dict)
    math_notebook: dict[str, Any] = field(default_factory=dict)
    backtest_center: dict[str, Any] = field(default_factory=dict)
    council: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    timestamps: dict[str, str] = field(default_factory=dict)
    artifact_ids: dict[str, str] = field(default_factory=dict)
    evidence_errors: list[str] = field(default_factory=list)
    contract_version: str = SUMMARY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.factor_verdict not in VALID_FACTOR_VERDICTS:
            raise ValueError(f"invalid factor_verdict: {self.factor_verdict!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Evidence:
    role: str
    artifact_id: str
    payload: dict[str, Any]
    modified_ns: int


@dataclass(frozen=True)
class _FormalValidation:
    attempted: bool = False
    protocol_verdict: str = "NOT_RUN"
    proof_verdict: str = "UNKNOWN"
    blockers: tuple[str, ...] = ()


def read_ultimate_workspace(
    workspace_root: str | Path,
    *,
    report_id: str | None = None,
) -> UltimateRunSummary:
    """Normalize existing Ultimate evidence without running or recomputing research."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    evidence_by_role, evidence_errors = _load_evidence(root)
    workspace_identity = _workspace_identity(root)
    latest_loop = _latest(evidence_by_role.get("loop_report", []))
    selected_report_id = report_id or _report_id_from_loop(latest_loop)
    if not selected_report_id:
        selected_report_id = _first_identifier(
            evidence_by_role,
            roles=("proof_certificate", "wrapper_report", "factor_case", "quality_gate"),
            key="report_id",
        )

    selected: dict[str, _Evidence] = {}
    for role, records in evidence_by_role.items():
        if role == "main_agent_mechanism_memo":
            continue
        selected_record = _latest_for_report(records, selected_report_id)
        if selected_record is not None:
            selected[role] = selected_record
        elif selected_report_id and records:
            evidence_errors.append(
                f"{BLOCK_EVIDENCE_LINEAGE_MISMATCH}:{role}:report_id={selected_report_id}"
            )
    expected_factor_id = _string(workspace_identity.get("factor_id")) or _identifier(
        selected, "factor_id"
    )
    expected_research_id = _string(
        workspace_identity.get("research_id")
    ) or _identifier(selected, "research_id")
    memo_records = evidence_by_role.get("main_agent_mechanism_memo", [])
    memo_record = _latest_main_agent_memo(
        memo_records,
        selected_report_id,
        factor_id=expected_factor_id,
        research_id=expected_research_id,
    )
    if memo_record is not None:
        selected["main_agent_mechanism_memo"] = memo_record
    elif selected_report_id and memo_records:
        evidence_errors.append(
            f"{BLOCK_EVIDENCE_LINEAGE_MISMATCH}:main_agent_mechanism_memo:"
            f"report_id={selected_report_id}"
        )
    matching_records = _matching_records(evidence_by_role, selected_report_id)

    report = selected_report_id or _identifier(selected, "report_id")
    factor_id = _identifier(selected, "factor_id")
    research_id = _identifier(selected, "research_id")
    factor_id = factor_id or _string(workspace_identity.get("factor_id"))
    research_id = research_id or _string(workspace_identity.get("research_id"))

    proof = _payload(selected, "proof_certificate")
    wrapper = _payload(selected, "wrapper_report")
    loop = _payload(selected, "loop_report")
    paused_note = _payload(selected, "paused_note")
    terminal_rejection = _payload(selected, "terminal_rejection")
    quality = _payload(selected, "quality_gate")
    main_agent_memo = _current_main_agent_memo(
        _payload(selected, "main_agent_mechanism_memo"),
        report_id=report,
        factor_id=factor_id,
        research_id=research_id,
    )
    factor_case = _payload(selected, "factor_case")
    factor_spec = _payload(selected, "factor_spec")
    research_state = _payload(selected, "research_state")

    factor_verdict = _factor_verdict(
        proof=proof,
        factor_case=factor_case,
        step6_handoff=_payload(selected, "step6_handoff"),
        terminal_rejection=terminal_rejection,
    )
    pause_state = _pause_state(loop, wrapper, paused_note)
    dry_run = _is_dry_run(loop, wrapper)
    running = _is_running(loop, wrapper)
    formal_validation = _run_formal_validation(
        root=root,
        selected=selected,
        report_id=report,
        factor_id=factor_id,
        research_id=research_id,
        factor_verdict=factor_verdict,
        pause_state=pause_state,
        dry_run=dry_run,
        running=running,
    )
    if formal_validation.attempted and formal_validation.protocol_verdict == "BLOCK":
        factor_verdict = "BLOCK"
    council_status = _council_status(
        selected,
        pause_state=pause_state,
        formal_validation=formal_validation,
    )
    blockers = _collect_blockers(
        matching_records,
        [
            *evidence_errors,
            *_explicit_evidence_blockers(matching_records),
            *_conflicting_evidence_verdict_blockers(matching_records),
            *formal_validation.blockers,
        ],
    )
    next_actions = _collect_next_actions(selected.values())
    blocked = _is_blocked(loop, wrapper, blockers, factor_verdict)
    if blocked:
        factor_verdict = "BLOCK"
    failed = _is_failed(loop, wrapper)
    protocol_status = _protocol_status(
        selected=selected,
        blocked=blocked,
        failed=failed,
        pause_state=pause_state,
        dry_run=dry_run,
        running=running,
        formal_validation=formal_validation,
    )
    formal_proof_eligible = _formal_proof_eligible(
        loop=loop,
        wrapper=wrapper,
        proof=proof,
        selected=selected,
        factor_verdict=factor_verdict,
        blocked=blocked,
        failed=failed,
        dry_run=dry_run,
        pause_state=pause_state,
        council_status=council_status,
        formal_validation=formal_validation,
    )
    execution_status = _execution_status(
        selected=selected,
        factor_verdict=factor_verdict,
        formal_proof_eligible=formal_proof_eligible,
        council_status=council_status,
        blocked=blocked,
        failed=failed,
        dry_run=dry_run,
        pause_state=pause_state,
    )

    research_method, economic_game, math_mechanism = _research_contracts(
        main_agent_memo=main_agent_memo,
        quality=quality,
        factor_case=factor_case,
        factor_spec=factor_spec,
        research_state=research_state,
    )
    data_contract = _data_contract(proof, _payload(selected, "data_prep"), factor_spec)
    implementation_contract = _implementation_contract(
        _payload(selected, "implementation_plan"),
        factor_spec,
    )
    core_metrics, metric_sources = _core_metrics(selected)
    research_notebook, math_notebook = _research_notebooks(
        main_agent_memo=main_agent_memo,
        research_method=research_method,
        economic_game=economic_game,
        math_mechanism=math_mechanism,
    )
    backtest_artifacts = _discover_backtest_artifacts(root, report)
    backtest_center = _backtest_center(
        root=root,
        artifact_ids=backtest_artifacts,
        core_metrics=core_metrics,
        formal_validation=formal_validation,
    )
    council = _council_projection(selected, main_agent_memo)
    timestamps = _timestamps(selected)
    current_stage = (
        pause_state
        or _string(loop.get("final_outcome"))
        or _latest_iteration_value(loop, "outcome")
        or _string(research_state.get("phase"))
        or _string(wrapper.get("status"))
        or "not_started"
    )

    return UltimateRunSummary(
        report_id=report,
        factor_id=factor_id,
        research_id=research_id,
        execution_status=execution_status,
        protocol_status=protocol_status,
        factor_verdict=factor_verdict,
        council_status=council_status,
        formal_proof_eligible=formal_proof_eligible,
        current_stage=current_stage,
        research_method=research_method,
        economic_game=economic_game,
        math_mechanism=math_mechanism,
        data_contract=data_contract,
        implementation_contract=implementation_contract,
        core_metrics=core_metrics,
        metric_sources=metric_sources,
        research_notebook=research_notebook,
        math_notebook=math_notebook,
        backtest_center=backtest_center,
        council=council,
        blockers=blockers,
        next_actions=next_actions,
        timestamps=timestamps,
        artifact_ids={
            **{role: item.artifact_id for role, item in sorted(selected.items())},
            **backtest_artifacts,
        },
        evidence_errors=_dedupe(evidence_errors),
    )


def read_ultimate_summary(
    workspace_root: str | Path,
    *,
    report_id: str | None = None,
) -> UltimateRunSummary:
    return read_ultimate_workspace(workspace_root, report_id=report_id)


def _load_evidence(root: Path) -> tuple[dict[str, list[_Evidence]], list[str]]:
    evidence: dict[str, list[_Evidence]] = {role: [] for role in ROLE_PATTERNS}
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            for candidate in root.glob(pattern):
                if not candidate.is_file():
                    continue
                artifact_id = candidate.relative_to(root).as_posix()
                if role in {"wrapper_report", "main_agent_mechanism_memo"} and re.search(
                    r"__prior_[0-9a-f]{12}(?:_[1-9][0-9]*)?$",
                    candidate.stem,
                ):
                    continue
                identity = (role, artifact_id)
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    payload, modified_ns = _read_internal_json(root, candidate)
                    if not isinstance(payload, dict):
                        raise ValueError("expected a JSON object")
                    evidence[role].append(
                        _Evidence(
                            role=role,
                            artifact_id=artifact_id,
                            payload=payload,
                            modified_ns=modified_ns,
                        )
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    errors.append(f"{artifact_id}: unreadable or unsafe evidence")
    return evidence, _dedupe(errors)


def _workspace_identity(root: Path) -> dict[str, Any]:
    manifest = root / "manifest.json"
    try:
        payload, _ = _read_internal_json(root, manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_internal_json(root: Path, candidate: Path) -> tuple[Any, int]:
    data, modified_ns = _read_internal_bytes(root, candidate)
    return json.loads(data.decode("utf-8")), modified_ns


def _read_internal_bytes(root: Path, candidate: Path) -> tuple[bytes, int]:
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("evidence outside workspace") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("invalid evidence path")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    directories: list[int] = []
    descriptor = -1
    try:
        current = os.open(root, directory_flags)
        directories.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            directories.append(current)
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=current)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("invalid evidence file")
        chunks: list[bytes] = []
        remaining = MAX_EVIDENCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError("unreadable evidence") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for item in reversed(directories):
            os.close(item)
    data = b"".join(chunks)
    if (
        len(data) > MAX_EVIDENCE_BYTES
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or len(data) != after.st_size
    ):
        raise ValueError("evidence changed during read")
    return data, after.st_mtime_ns


def _latest(records: Iterable[_Evidence]) -> _Evidence | None:
    values = list(records)
    return max(values, key=lambda item: (item.modified_ns, item.artifact_id)) if values else None


def _latest_for_report(records: list[_Evidence], report_id: str) -> _Evidence | None:
    if report_id:
        matching = [
            item
            for item in records
            if _record_report_ids(item.payload).intersection({report_id})
        ]
        if matching:
            return _latest(matching)
        return None
    return _latest(records)


def _latest_main_agent_memo(
    records: list[_Evidence],
    report_id: str,
    *,
    factor_id: str,
    research_id: str,
) -> _Evidence | None:
    matching = [
        item
        for item in records
        if not report_id or report_id in _record_report_ids(item.payload)
    ]
    if not matching:
        return None
    valid = [
        item
        for item in matching
        if _current_main_agent_memo(
            item.payload,
            report_id=report_id,
            factor_id=factor_id,
            research_id=research_id,
        )
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda item: (
            _revision_number(item.payload.get("revision_number")),
            item.modified_ns,
            item.artifact_id,
        ),
    )


def _revision_number(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _matching_records(
    evidence_by_role: dict[str, list[_Evidence]],
    report_id: str,
) -> list[_Evidence]:
    if not report_id:
        return [record for records in evidence_by_role.values() for record in records]
    return [
        record
        for records in evidence_by_role.values()
        for record in records
        if report_id in _record_report_ids(record.payload)
    ]


def _record_report_ids(payload: dict[str, Any]) -> set[str]:
    values = {
        _string(payload.get("report_id")),
        _string(payload.get("root_report_id")),
        _string(payload.get("parent_report_id")),
    }
    for iteration in payload.get("iterations") or []:
        if isinstance(iteration, dict):
            values.add(_string(iteration.get("report_id")))
            values.add(_string(iteration.get("child_report_id")))
    return {value for value in values if value}


def _report_id_from_loop(record: _Evidence | None) -> str:
    if record is None:
        return ""
    iterations = record.payload.get("iterations")
    if isinstance(iterations, list):
        for item in reversed(iterations):
            if isinstance(item, dict) and _string(item.get("report_id")):
                return _string(item.get("report_id"))
    return _string(record.payload.get("root_report_id") or record.payload.get("report_id"))


def _first_identifier(
    evidence_by_role: dict[str, list[_Evidence]],
    *,
    roles: tuple[str, ...],
    key: str,
) -> str:
    for role in roles:
        record = _latest(evidence_by_role.get(role, []))
        if record and _string(record.payload.get(key)):
            return _string(record.payload.get(key))
    return ""


def _identifier(selected: dict[str, _Evidence], key: str) -> str:
    for role in (
        "proof_certificate",
        "main_agent_mechanism_memo",
        "quality_gate",
        "research_state",
        "factor_case",
        "factor_spec",
        "wrapper_report",
        "loop_report",
    ):
        value = _string(_payload(selected, role).get(key))
        if value:
            return value
    return ""


def _payload(selected: dict[str, _Evidence], role: str) -> dict[str, Any]:
    record = selected.get(role)
    return record.payload if record else {}


def _factor_verdict(
    *,
    proof: dict[str, Any],
    factor_case: dict[str, Any],
    step6_handoff: dict[str, Any],
    terminal_rejection: dict[str, Any],
) -> str:
    if terminal_rejection:
        return "REJECT"
    candidates = [
        proof.get("declared_verdict"),
        proof.get("factor_verdict"),
        factor_case.get("factor_verdict"),
        factor_case.get("final_verdict"),
        factor_case.get("final_status"),
        step6_handoff.get("factor_verdict"),
        step6_handoff.get("decision"),
        step6_handoff.get("verdict"),
    ]
    for value in candidates:
        normalized = _normalize_verdict(value)
        if normalized != "UNKNOWN":
            return normalized
    return "UNKNOWN"


def _normalize_verdict(value: Any) -> str:
    text = _string(value).upper()
    aliases = {
        "ACCEPTED": "ACCEPT",
        "PROMOTE": "ACCEPT",
        "PROMOTED": "ACCEPT",
        "REJECTED": "REJECT",
        "STOP": "REJECT",
        "ITERATION": "ITERATE",
        "REVISION": "ITERATE",
        "REVISE": "ITERATE",
        "BLOCKED": "BLOCK",
        "FAIL": "BLOCK",
        "FAILED": "BLOCK",
        "PARTIAL": "ITERATE",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in VALID_FACTOR_VERDICTS else "UNKNOWN"


def _pause_state(
    loop: dict[str, Any],
    wrapper: dict[str, Any],
    paused_note: dict[str, Any],
) -> str:
    candidates = [
        paused_note.get("pause_state"),
        paused_note.get("status"),
        loop.get("final_outcome"),
        loop.get("stop_reason"),
        _latest_iteration_value(loop, "outcome"),
        _latest_iteration_value(loop, "stop_reason"),
        wrapper.get("status"),
        _path(wrapper, "revision_council", "status"),
        _path(wrapper, "revision_council", "formal_council_status"),
    ]
    for value in candidates:
        text = _string(value).lower()
        if text in PAUSE_STATES:
            return text
        if text.startswith("awaiting_"):
            return text
        if text == "paused":
            return _string(paused_note.get("pause_state")) or "paused"
    return ""


def _council_status(
    selected: dict[str, _Evidence],
    *,
    pause_state: str,
    formal_validation: _FormalValidation,
) -> str:
    if selected.get("terminal_rejection"):
        return "REJECTED"
    wrapper = _payload(selected, "wrapper_report")
    loop = _payload(selected, "loop_report")
    values = [
        _latest_iteration_value(loop, "council_status"),
        _path(wrapper, "revision_council", "formal_council_status"),
        _path(wrapper, "revision_council", "status"),
        _payload(selected, "council_synthesis").get("status"),
        _payload(selected, "council_summary").get("status"),
        _payload(selected, "council_dispatch").get("status"),
    ]
    normalized = [_string(value).lower() for value in values if _string(value)]
    if any(value in {"block", "blocked", "fail", "failed"} for value in normalized):
        return "BLOCKED"
    if pause_state and ("council" in pause_state or pause_state == "awaiting_agent_results"):
        return "PAUSED"
    if any(value.startswith("awaiting_") or value == "paused" for value in normalized):
        return "PAUSED"
    synthesis_status = _string(_payload(selected, "council_synthesis").get("status")).lower()
    summary_status = _string(_payload(selected, "council_summary").get("status")).lower()
    terminal_council_statuses = {"pass", "passed", "complete", "completed", "finalized"}
    if (
        formal_validation.protocol_verdict == "PASS"
        and synthesis_status in terminal_council_statuses
        and summary_status in terminal_council_statuses
    ):
        return "PASS"
    if any(value in {"pass", "passed", "complete", "completed", "finalized"} for value in normalized):
        return "RUNNING"
    if any(value in {"running", "pending", "dispatched", "collecting"} for value in normalized):
        return "RUNNING"
    if any(value in {"skipped", "off", "disabled", "not_required", "not_triggered"} for value in normalized):
        return "NOT_REQUIRED"
    if selected.get("council_dispatch"):
        return "RUNNING"
    return "NOT_STARTED"


def _explicit_evidence_blockers(records: Iterable[_Evidence]) -> list[str]:
    blockers: list[str] = []
    status_keys = ("status", "verdict", "protocol_status", "validation_status", "proof_status")
    for record in records:
        role = record.role
        payload = record.payload
        if payload.get("blocked") is True:
            blockers.append(f"BLOCK_FACTORFORGE_CONSOLE_EXPLICIT_BLOCKED_EVIDENCE:{role}")
        for key in status_keys:
            status = _string(payload.get(key)).upper()
            if status in {"BLOCK", "BLOCKED", "FAIL", "FAILED", "ERROR"} or status.startswith("BLOCK_"):
                blockers.append(
                    f"BLOCK_FACTORFORGE_CONSOLE_EXPLICIT_BLOCKED_EVIDENCE:{role}:{key}"
                )
    return _dedupe(blockers)


def _conflicting_evidence_verdict_blockers(records: Iterable[_Evidence]) -> list[str]:
    verdicts: set[str] = set()
    for record in records:
        for key in ("declared_verdict", "factor_verdict", "final_verdict", "decision"):
            verdict = _normalize_verdict(record.payload.get(key))
            if verdict in {"ACCEPT", "REJECT", "ITERATE", "BLOCK"}:
                verdicts.add(verdict)
    if len(verdicts) <= 1:
        return []
    return [
        f"{BLOCK_FORMAL_VERDICT_MISMATCH}:conflicting_evidence="
        f"{','.join(sorted(verdicts))}"
    ]


def _collect_blockers(records: Iterable[_Evidence], evidence_errors: list[str]) -> list[str]:
    values: list[str] = list(evidence_errors)
    for record in records:
        values.extend(_collect_named_values(record.payload, _BLOCK_KEYS))
        for key in ("stop_reason", "reason"):
            candidate = _string(record.payload.get(key))
            if candidate.upper().startswith("BLOCK_"):
                values.append(candidate)
    return _dedupe(_sanitize_public_text(value) for value in values if value)


def _collect_next_actions(records: Iterable[_Evidence]) -> list[str]:
    values: list[str] = []
    for record in records:
        values.extend(_collect_named_values(record.payload, _NEXT_ACTION_KEYS))
    return _dedupe(_sanitize_public_text(value) for value in values if value)


def _collect_named_values(value: Any, names: set[str]) -> list[str]:
    output: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in names:
                output.extend(_human_strings(child))
            elif key not in {"commands", "source_code", "stdout_tail", "stderr_tail"}:
                output.extend(_collect_named_values(child, names))
    elif isinstance(value, list):
        for child in value:
            output.extend(_collect_named_values(child, names))
    return output


def _human_strings(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        output: list[str] = []
        for child in value:
            output.extend(_human_strings(child))
        return output
    if isinstance(value, dict):
        label = value.get("code") or value.get("blocker") or value.get("name")
        detail = value.get("message") or value.get("reason") or value.get("error")
        if label and detail:
            return [f"{label}: {detail}"]
        if label:
            return [_string(label)]
        if detail:
            return [_string(detail)]
    return []


def _is_blocked(
    loop: dict[str, Any],
    wrapper: dict[str, Any],
    blockers: list[str],
    factor_verdict: str,
) -> bool:
    if factor_verdict == "BLOCK":
        return True
    statuses = [
        loop.get("status"),
        loop.get("final_outcome"),
        loop.get("stop_reason"),
        _latest_iteration_value(loop, "proof_status"),
        wrapper.get("status"),
    ]
    explicit_status_block = any(
        _string(value).upper() in {"BLOCK", "BLOCKED"}
        or _string(value).upper().startswith("BLOCK_")
        for value in statuses
    )
    if explicit_status_block or any(value.upper().startswith("BLOCK_") for value in blockers):
        return True
    # Negative findings may explain a formal REJECT without invalidating the
    # research protocol itself. Generic blockers imply BLOCK only before a
    # terminal factor verdict exists.
    return bool(blockers and factor_verdict == "UNKNOWN")


def _is_failed(loop: dict[str, Any], wrapper: dict[str, Any]) -> bool:
    statuses = [
        loop.get("status"),
        loop.get("final_outcome"),
        _latest_iteration_value(loop, "proof_status"),
        wrapper.get("status"),
    ]
    return any(_string(value).upper() in {"FAIL", "FAILED", "ERROR"} for value in statuses)


def _is_dry_run(loop: dict[str, Any], wrapper: dict[str, Any]) -> bool:
    return bool(
        loop.get("dry_run") is True
        or wrapper.get("dry_run") is True
        or _string(loop.get("status")).upper() == "DRY_RUN"
        or _string(wrapper.get("status")).upper() == "DRY_RUN"
    )


def _is_running(loop: dict[str, Any], wrapper: dict[str, Any]) -> bool:
    statuses = {
        _string(loop.get("status")).upper(),
        _string(wrapper.get("status")).upper(),
    }
    return bool(statuses.intersection({"RUNNING", "RESEARCHING", "VERIFYING"}))


def _run_formal_validation(
    *,
    root: Path,
    selected: dict[str, _Evidence],
    report_id: str,
    factor_id: str,
    research_id: str,
    factor_verdict: str,
    pause_state: str,
    dry_run: bool,
    running: bool,
) -> _FormalValidation:
    terminal_candidate = factor_verdict in {"ACCEPT", "REJECT", "ITERATE"}
    if not terminal_candidate or pause_state or running or dry_run:
        return _FormalValidation()
    if not report_id or not factor_id or not research_id:
        return _FormalValidation(
            attempted=True,
            protocol_verdict="BLOCK",
            blockers=(f"{BLOCK_EVIDENCE_LINEAGE_MISMATCH}:formal_identity_missing",),
        )

    proof = _payload(selected, "proof_certificate")
    if not proof:
        return _FormalValidation(
            attempted=True,
            protocol_verdict="BLOCK",
            blockers=("BLOCK_FACTORFORGE_FACTOR_PROOF_CERTIFICATE_MISSING",),
        )

    blockers: list[str] = []
    try:
        wrapper = _payload(selected, "wrapper_report")
        wrapper_reasons = validate_wrapper_proof_for_loop(wrapper)
        requested_steps = {
            _string(step)
            for step in (wrapper.get("requested_steps") or [])
        }
        if not {"3", "4", "5", "6"}.issubset(requested_steps):
            wrapper_reasons.append(
                f"{BLOCK_FORMAL_WRAPPER_INVALID}:complete_step3_step6_chain_required"
            )
        wrapper_identity = {
            "report_id": report_id,
            "factor_id": factor_id,
            "research_id": research_id,
        }
        wrapper_identity_mismatch = any(
            _string(wrapper.get(key)) != expected
            for key, expected in wrapper_identity.items()
        )
        if wrapper_reasons or wrapper_identity_mismatch:
            blockers.append(BLOCK_FORMAL_WRAPPER_INVALID)
            blockers.extend(wrapper_reasons)
            if wrapper_identity_mismatch:
                blockers.append(f"{BLOCK_EVIDENCE_LINEAGE_MISMATCH}:wrapper_identity")

        proof_report = validate_factor_proof_certificate(
            proof,
            workspace_root=root,
            expected_report_id=report_id,
            expected_factor_id=factor_id,
        )
        proof_verdict = _normalize_verdict(proof_report.get("verdict"))
        if proof_verdict == "BLOCK":
            blockers.extend(_human_strings(proof_report.get("block_reasons")))
        if proof_verdict != factor_verdict:
            blockers.append(
                f"{BLOCK_FORMAL_VERDICT_MISMATCH}:declared={factor_verdict}:verified={proof_verdict}"
            )

        protocol_report = validate_protocol_bundle(
            root=root,
            report_id=report_id,
            stage="final",
        )
        protocol_verdict = _string(protocol_report.get("verdict")).upper()
        if protocol_verdict != "PASS":
            protocol_blockers = _human_strings(protocol_report.get("block_reasons"))
            blockers.extend(
                protocol_blockers
                or [f"BLOCK_FACTORFORGE_CONSOLE_PROTOCOL_VALIDATOR_NONPASS:{protocol_verdict or 'UNKNOWN'}"]
            )

        verifier = _payload(selected, "proof_verifier")
        if not verifier:
            blockers.append(BLOCK_FORMAL_VERIFIER_MISSING)
        else:
            persisted_status = _normalize_verdict(verifier.get("status"))
            persisted_verdict = (
                "BLOCK"
                if persisted_status == "BLOCK"
                else _normalize_verdict(verifier.get("verdict"))
            )
            persisted_blockers = _human_strings(verifier.get("block_reasons"))
            if (
                verifier.get("verifier_contract_version") != BOUND_VERIFIER_VERSION
                or verifier.get("report_id") != report_id
                or verifier.get("factor_id") != factor_id
                or verifier.get("research_id") != research_id
                or persisted_verdict != proof_verdict
                or persisted_blockers
            ):
                blockers.append(BLOCK_FORMAL_VERIFIER_MISMATCH)
                blockers.extend(persisted_blockers)
    except Exception as exc:
        blockers.append(f"{BLOCK_FORMAL_VALIDATION_EXCEPTION}:{type(exc).__name__}")
        proof_verdict = "BLOCK"

    deduped = tuple(_dedupe(blockers))
    return _FormalValidation(
        attempted=True,
        protocol_verdict="BLOCK" if deduped else "PASS",
        proof_verdict=proof_verdict,
        blockers=deduped,
    )


def _protocol_status(
    *,
    selected: dict[str, _Evidence],
    blocked: bool,
    failed: bool,
    pause_state: str,
    dry_run: bool,
    running: bool,
    formal_validation: _FormalValidation,
) -> str:
    if blocked or failed:
        return "BLOCK"
    if pause_state:
        return "PAUSED"
    if formal_validation.attempted:
        return formal_validation.protocol_verdict
    if running:
        return "RUNNING"
    if dry_run:
        return "UNKNOWN"
    if selected:
        return "UNKNOWN"
    return "NOT_STARTED"


def _formal_proof_eligible(
    *,
    loop: dict[str, Any],
    wrapper: dict[str, Any],
    proof: dict[str, Any],
    selected: dict[str, _Evidence],
    factor_verdict: str,
    blocked: bool,
    failed: bool,
    dry_run: bool,
    pause_state: str,
    council_status: str,
    formal_validation: _FormalValidation,
) -> bool:
    if (
        blocked
        or failed
        or dry_run
        or pause_state
        or council_status not in {"PASS", "REJECTED"}
        or not proof
        or factor_verdict == "UNKNOWN"
        or formal_validation.protocol_verdict != "PASS"
    ):
        return False
    verifier = _payload(selected, "proof_verifier")
    explicit = [
        record.payload.get("formal_proof_eligible")
        for record in selected.values()
        if "formal_proof_eligible" in record.payload
    ]
    return (
        proof.get("formal_proof_eligible") is True
        and verifier.get("formal_proof_eligible") is True
        and all(value is True for value in explicit)
    )


def _execution_status(
    *,
    selected: dict[str, _Evidence],
    factor_verdict: str,
    formal_proof_eligible: bool,
    council_status: str,
    blocked: bool,
    failed: bool,
    dry_run: bool,
    pause_state: str,
) -> str:
    # Terminal evidence always outranks a successful wrapper process.
    if blocked or factor_verdict == "BLOCK":
        return "BLOCKED"
    if pause_state or council_status == "PAUSED":
        return "PAUSED"
    if failed:
        return "FAILED"
    if dry_run:
        return "DRY_RUN"
    if factor_verdict in {"ACCEPT", "REJECT", "ITERATE"} and not formal_proof_eligible:
        return "REVIEW_REQUIRED"
    if factor_verdict == "REJECT" and council_status in {
        "PASS",
        "NOT_REQUIRED",
        "REJECTED",
    }:
        return "REJECTED"
    if factor_verdict == "ITERATE" and council_status in {"PASS", "NOT_REQUIRED"}:
        return "ITERATING"
    wrapper_status = _string(_payload(selected, "wrapper_report").get("status")).upper()
    loop_status = _string(_payload(selected, "loop_report").get("status")).upper()
    if "RUNNING" in {wrapper_status, loop_status}:
        return "RUNNING"
    if factor_verdict == "ACCEPT" and formal_proof_eligible and council_status in {
        "PASS",
        "NOT_REQUIRED",
    }:
        return "COMPLETED"
    if selected:
        return "REVIEW_REQUIRED"
    return "NOT_STARTED"


def _research_contracts(
    *,
    main_agent_memo: dict[str, Any],
    quality: dict[str, Any],
    factor_case: dict[str, Any],
    factor_spec: dict[str, Any],
    research_state: dict[str, Any],
) -> tuple[dict[str, Any], Any, Any]:
    mechanism_contract = factor_case.get("mechanism_math_contract")
    if not isinstance(mechanism_contract, dict):
        mechanism_contract = {}
    step2_context = _find_mapping(factor_spec, "step2_research_context")

    economic_source = main_agent_memo.get("economic_hypothesis")
    if not isinstance(economic_source, dict):
        economic_source = quality.get("economic_mechanism_contract")
    if not isinstance(economic_source, dict):
        economic_source = mechanism_contract
    economic_game = _select_fields(economic_source, ECONOMIC_FIELDS)
    if not economic_game:
        economic_game = _first_public_value(
            (quality, factor_case, factor_spec),
            ("economic_game", "economic_mechanism", "economic_hypothesis"),
        )

    math_source = main_agent_memo.get("math_hypothesis")
    if not isinstance(math_source, dict):
        math_source = quality.get("mathematical_object_contract")
    if not isinstance(math_source, dict):
        math_source = mechanism_contract
    math_mechanism = _select_fields(math_source, MATH_FIELDS)
    for key, value in _select_fields(mechanism_contract, MATH_FIELDS).items():
        math_mechanism.setdefault(key, value)
    if not math_mechanism:
        math_mechanism = _first_public_value(
            (quality, factor_case, factor_spec),
            (
                "math_mechanism",
                "mathematical_mechanism",
                "stochastic_process_contract",
                "dirac_induction_memo",
            ),
        )

    research_method = {
        "source_kind": (
            "current_main_agent_memo" if main_agent_memo else "deterministic_fallback"
        ),
        "producer": _public_copy(main_agent_memo.get("producer")),
        "revision_number": _public_copy(main_agent_memo.get("revision_number")),
        "mechanism_claim_level": _public_copy(quality.get("mechanism_claim_level")),
        "claim_level_assessment": _public_copy(quality.get("claim_level_assessment")),
        "falsification_plan": _public_copy(quality.get("falsification_plan")),
        "research_phase": _public_copy(research_state.get("phase")),
        "transition_reason": _public_copy(research_state.get("transition_reason")),
        "target_statistic": _public_copy(
            step2_context.get("target_statistic")
            or mechanism_contract.get("target_functional")
            or (math_source.get("target_statistic") if isinstance(math_source, dict) else None)
        ),
        "expected_failure_modes": _public_copy(step2_context.get("expected_failure_modes")),
    }
    explicit_method = _first_public_value(
        (quality, factor_case, factor_spec),
        ("research_method", "research_design", "methodology"),
    )
    if explicit_method is not None:
        research_method["methodology"] = explicit_method
    research_method = {key: value for key, value in research_method.items() if value not in (None, {}, [])}
    return research_method, economic_game or None, math_mechanism or None


def _current_main_agent_memo(
    payload: dict[str, Any],
    *,
    report_id: str = "",
    factor_id: str = "",
    research_id: str = "",
) -> dict[str, Any]:
    if not payload:
        return {}
    if payload.get("contract_version") != "factorforge_main_agent_mechanism_memo_v1":
        return {}
    if str(payload.get("producer") or "") != "current_main_agent":
        return {}
    authorship = payload.get("agent_authorship")
    if not isinstance(authorship, dict):
        return {}
    if (
        authorship.get("authoring_mode") != "current_agent_freeform"
        or authorship.get("agent_role") != "main_agent"
        or authorship.get("answered_without_deterministic_template") is not True
    ):
        return {}
    for key, expected in (
        ("report_id", report_id),
        ("factor_id", factor_id),
        ("research_id", research_id),
    ):
        actual = _string(payload.get(key))
        if not actual or (expected and actual != expected):
            return {}
    return payload


def _research_notebooks(
    *,
    main_agent_memo: dict[str, Any],
    research_method: dict[str, Any],
    economic_game: Any,
    math_mechanism: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_kind = (
        "current_main_agent_memo" if main_agent_memo else "deterministic_fallback"
    )
    source_label = (
        "CURRENT MAIN AGENT" if main_agent_memo else "EARLY DETERMINISTIC CONTRACT"
    )
    economic = (
        _public_copy(main_agent_memo.get("economic_hypothesis"))
        if main_agent_memo
        else _public_copy(economic_game)
    ) or {}
    math = (
        _public_copy(main_agent_memo.get("math_hypothesis"))
        if main_agent_memo
        else _public_copy(math_mechanism)
    ) or {}
    components = _public_copy(main_agent_memo.get("formula_component_map")) or []
    evidence = _public_copy(main_agent_memo.get("evidence_comparison")) or {}
    qa = _public_copy(main_agent_memo.get("mechanism_qa")) or {}
    selection = _public_copy(main_agent_memo.get("math_model_selection")) or {}
    estimator = _public_copy(main_agent_memo.get("formula_state_estimator")) or {}
    falsifiers = _public_copy(main_agent_memo.get("falsification_tests")) or []
    council_questions = _public_copy(main_agent_memo.get("council_questions")) or []
    notebook = {
        "contract_version": "factorforge_console_research_notebook_v1",
        "source_kind": source_kind,
        "source_label": source_label,
        "producer": _public_copy(main_agent_memo.get("producer")) or "framework_projection",
        "revision_number": _public_copy(main_agent_memo.get("revision_number")),
        "stages": [
            {
                "id": "economic_hypothesis",
                "title": "Economic hypothesis",
                "content": economic,
            },
            {
                "id": "model_selection",
                "title": "Model selection",
                "content": selection or math,
            },
            {
                "id": "observable_mapping",
                "title": "Observable estimator",
                "content": {"estimator": estimator, "components": components},
            },
            {
                "id": "evidence_update",
                "title": "Evidence update",
                "content": evidence,
            },
            {
                "id": "falsification",
                "title": "Falsification and open questions",
                "content": {
                    "mechanism_qa": qa,
                    "falsification_tests": falsifiers,
                    "council_questions": council_questions,
                },
            },
        ],
    }
    equations: list[dict[str, str]] = []
    equation_candidates = (
        ("Factor law", main_agent_memo.get("formula"), "factor_law"),
        ("Baseline process", math.get("process_or_distribution") or selection.get("baseline_model"), "process"),
        ("Target functional", math.get("target_functional") or math.get("target_statistic"), "target"),
        ("Observation equation", math.get("observation_equation"), "observation"),
        ("Observable estimator", math.get("formula_as_estimator") or estimator.get("observable_mapping"), "estimator"),
    )
    for title, expression, equation_kind in equation_candidates:
        if isinstance(expression, str) and expression.strip():
            equations.append(
                {
                    "title": title,
                    "expression": _sanitize_public_text(expression.strip()),
                    "equation_kind": equation_kind,
                }
            )
    definitions = {
        "random_object": math.get("random_object"),
        "information_set": math.get("information_set"),
        "latent_state": math.get("latent_state") or estimator.get("latent_state"),
        "model_family": math.get("selected_model_family") or selection.get("model_family"),
        "payer": economic.get("payer_or_counterparty") or economic.get("payer"),
    }
    definitions = {key: value for key, value in definitions.items() if value not in (None, "")}
    derivation_steps = [
        {
            "step": 1,
            "title": "Market mechanism to state",
            "statement": economic,
        },
        {
            "step": 2,
            "title": "State to mathematical model",
            "statement": selection or {
                "why_this_model": math.get("why_this_model"),
                "why_not_generic_template": math.get("why_not_generic_template"),
            },
        },
        {
            "step": 3,
            "title": "Model to observable estimator",
            "statement": {"estimator": estimator, "components": components},
        },
        {
            "step": 4,
            "title": "Estimator to metric signature",
            "statement": math.get("expected_metric_signature") or {},
        },
        {
            "step": 5,
            "title": "Evidence to accept, revise, or kill",
            "statement": {"evidence": evidence, "falsification_tests": falsifiers},
        },
    ]
    math_notebook = {
        "contract_version": "factorforge_console_math_notebook_v1",
        "source_kind": source_kind,
        "source_label": source_label,
        "definitions": _public_copy(definitions) or {},
        "equations": equations,
        "derivation_steps": _public_copy(derivation_steps) or [],
        "assumptions": _public_copy(
            economic.get("necessary_market_structure")
            or math.get("necessary_conditions")
            or []
        ),
        "falsification_tests": falsifiers,
        "evidence_class": "AGENT CLAIM" if main_agent_memo else "FORMAL UNVERIFIED",
    }
    return notebook, math_notebook


def _council_projection(
    selected: dict[str, _Evidence],
    main_agent_memo: dict[str, Any],
) -> dict[str, Any]:
    dispatch = _payload(selected, "council_dispatch")
    summary = _payload(selected, "council_summary")
    synthesis = _payload(selected, "council_synthesis")
    questions = _public_copy(main_agent_memo.get("council_questions")) or []
    routes = _first_public_value(
        (summary, dispatch),
        ("route_results", "routes", "assignments", "agent_results"),
    )
    projection = {
        "questions": questions,
        "routes": routes or [],
        "synthesis": _first_public_value(
            (synthesis, summary),
            ("synthesis", "summary", "decision_rationale", "selected_revision"),
        ),
        "selected_revision": _public_copy(synthesis.get("selected_revision")),
        "mutation": _first_public_value(
            (synthesis, summary),
            ("mutation", "selected_mutation", "revision_proposal", "formula_revision"),
        ),
    }
    return {key: value for key, value in projection.items() if value not in (None, {}, [])}


def _data_contract(
    proof: dict[str, Any],
    data_prep: dict[str, Any],
    factor_spec: dict[str, Any],
) -> dict[str, Any]:
    source = proof.get("data_contract")
    if not isinstance(source, dict):
        source = _find_mapping(data_prep, "data_contract")
    if not source:
        source = _find_mapping(factor_spec, "data_contract")
    result = _select_fields(source, DATA_CONTRACT_FIELDS)
    if data_prep:
        for key in ("data_status", "data_profile", "state_dependency_contract", "state_resolution"):
            value = data_prep.get(key)
            if value is not None and not key.endswith(("contract", "resolution")):
                copied = _public_copy(value)
                if copied is not None:
                    result[key] = copied
    return result


def _implementation_contract(
    implementation_plan: dict[str, Any],
    factor_spec: dict[str, Any],
) -> dict[str, Any]:
    result = _select_fields(implementation_plan, IMPLEMENTATION_FIELDS)
    code_contract = implementation_plan.get("code_contract")
    if isinstance(code_contract, dict):
        for key, value in _select_fields(code_contract, IMPLEMENTATION_FIELDS).items():
            result.setdefault(key, value)
    if not result:
        source = _find_mapping(factor_spec, "implementation_contract")
        result = _select_fields(source, IMPLEMENTATION_FIELDS)
    return result


def _core_metrics(selected: dict[str, _Evidence]) -> tuple[dict[str, Any], dict[str, str]]:
    metrics: dict[str, Any] = {}
    sources: dict[str, str] = {}
    metric_records = [
        selected.get(role)
        for role in (
            "proof_certificate",
            "proof_verifier",
            "factor_evaluation",
            "factor_case",
            "research_iteration",
            "loop_report",
            "paused_note",
        )
        if selected.get(role) is not None
    ]
    for normalized_name, aliases in METRIC_ALIASES.items():
        for record in metric_records:
            assert record is not None
            containers = _metric_containers(record.payload)
            found = _find_alias(containers, aliases)
            if found is None:
                continue
            copied = _public_copy(found)
            if copied is None:
                continue
            metrics[normalized_name] = copied
            sources[normalized_name] = record.artifact_id
            break

    ic = metrics.get("ic")
    if "rank_ic" not in metrics and isinstance(ic, dict):
        if _string(ic.get("method")).lower() in {"rank_ic", "both"}:
            metrics["rank_ic"] = _public_copy(ic)
            sources["rank_ic"] = sources["ic"]
    drawdown = metrics.get("drawdown")
    if isinstance(drawdown, dict):
        recovery = {
            key: _public_copy(drawdown.get(key))
            for key in ("recovery_days", "recovery_area")
            if drawdown.get(key) is not None
        }
        if recovery:
            metrics["recovery"] = recovery
            sources["recovery"] = sources["drawdown"]
    return metrics, sources


def _discover_backtest_artifacts(root: Path, report_id: str) -> dict[str, str]:
    if not report_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", report_id):
        return {}
    base = root / "evaluations" / report_id / "self_quant_analyzer"
    artifacts: dict[str, str] = {}
    for role, filename in BACKTEST_ARTIFACT_FILENAMES.items():
        candidate = base / filename
        try:
            data, _ = _read_internal_bytes(root, candidate)
        except (OSError, ValueError):
            continue
        if not data:
            continue
        artifacts[role] = candidate.relative_to(root).as_posix()
    return artifacts


def _backtest_center(
    *,
    root: Path,
    artifact_ids: dict[str, str],
    core_metrics: dict[str, Any],
    formal_validation: _FormalValidation,
) -> dict[str, Any]:
    evidence_class = (
        "FORMAL VERIFIED"
        if formal_validation.attempted
        and formal_validation.protocol_verdict == "PASS"
        else "FORMAL UNVERIFIED"
    )
    nav_summary: dict[str, Any] = {}
    annual_returns: list[dict[str, Any]] = []
    source_id = artifact_ids.get("long_side_nav_table")
    source_sha256 = ""
    if source_id:
        try:
            data, _ = _read_internal_bytes(root, root / source_id)
            source_sha256 = hashlib.sha256(data).hexdigest()
            nav_summary, annual_returns = _summarize_nav_csv(data)
        except (OSError, UnicodeError, ValueError, csv.Error):
            nav_summary, annual_returns = {}, []
    consistency = _nav_consistency(nav_summary, core_metrics)
    chart_roles = {
        key: value
        for key, value in artifact_ids.items()
        if key.endswith("_chart")
    }
    table_roles = {
        key: value
        for key, value in artifact_ids.items()
        if key.endswith("_table")
    }
    required_modules = {
        "gross_net_nav": bool(
            chart_roles.get("gross_nav_chart")
            and chart_roles.get("net_nav_chart")
        ),
        "quantile_nav": bool(chart_roles.get("quantile_nav_chart")),
        "annual_returns": bool(annual_returns),
        "rank_ic_timeseries": bool(chart_roles.get("rank_ic_chart")),
        "pearson_ic_timeseries": bool(chart_roles.get("pearson_ic_chart")),
        "drawdown": bool(core_metrics.get("drawdown")),
        "turnover_and_cost": bool(
            core_metrics.get("turnover") or core_metrics.get("trading_cost")
        ),
        "fama_macbeth": bool(core_metrics.get("fama_macbeth")),
    }
    return {
        "contract_version": "factorforge_console_backtest_center_v1",
        "evidence_class": evidence_class,
        "validator_verdict": formal_validation.protocol_verdict,
        "metrics": _public_copy(core_metrics) or {},
        "charts": chart_roles,
        "tables": table_roles,
        "nav_summary": nav_summary,
        "annual_returns": annual_returns,
        "module_status": {
            key: "available" if available else "not_produced"
            for key, available in required_modules.items()
        },
        "consistency": consistency,
        "provenance": {
            "annual_returns_source": source_id or "",
            "annual_returns_source_sha256": source_sha256,
            "annual_returns_derivation": (
                "calendar-year return from formal gross/net NAV endpoints; no interpolation"
                if annual_returns
                else "not produced"
            ),
        },
    }


def _summarize_nav_csv(data: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = list(reader.fieldnames or [])
    if len(fields) < 2:
        return {}, []
    date_field = fields[0]
    gross_field = next(
        (field for field in fields if field == "long_side_nav"),
        "",
    )
    net_field = next(
        (field for field in fields if field == "cost_adjusted_long_side_nav"),
        "",
    )
    if not gross_field and not net_field:
        return {}, []
    rows: list[tuple[str, float | None, float | None]] = []
    for row in reader:
        date_text = str(row.get(date_field) or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", date_text):
            continue
        gross = _finite_float(row.get(gross_field)) if gross_field else None
        net = _finite_float(row.get(net_field)) if net_field else None
        if gross is None and net is None:
            continue
        rows.append((date_text[:10], gross, net))
    if not rows:
        return {}, []
    rows.sort(key=lambda item: item[0])
    by_year: dict[str, list[tuple[str, float | None, float | None]]] = {}
    for row in rows:
        by_year.setdefault(row[0][:4], []).append(row)
    annual: list[dict[str, Any]] = []
    prior_gross = 1.0
    prior_net = 1.0
    for year in sorted(by_year):
        year_rows = by_year[year]
        end_gross = next((item[1] for item in reversed(year_rows) if item[1] is not None), None)
        end_net = next((item[2] for item in reversed(year_rows) if item[2] is not None), None)
        annual.append(
            {
                "year": int(year),
                "gross_return": (
                    end_gross / prior_gross - 1.0
                    if end_gross is not None and prior_gross > 0
                    else None
                ),
                "net_return": (
                    end_net / prior_net - 1.0
                    if end_net is not None and prior_net > 0
                    else None
                ),
            }
        )
        if end_gross is not None:
            prior_gross = end_gross
        if end_net is not None:
            prior_net = end_net
    final_gross = next((item[1] for item in reversed(rows) if item[1] is not None), None)
    final_net = next((item[2] for item in reversed(rows) if item[2] is not None), None)
    return (
        {
            "start_date": rows[0][0],
            "end_date": rows[-1][0],
            "period_count": len(rows),
            "gross_final_nav": final_gross,
            "net_final_nav": final_net,
        },
        annual,
    )


def _nav_consistency(
    nav_summary: dict[str, Any],
    core_metrics: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for summary_key, metric_key in (
        ("gross_final_nav", "gross_final_nav"),
        ("net_final_nav", "net_final_nav"),
    ):
        observed = _finite_float(nav_summary.get(summary_key))
        expected = _finite_float(core_metrics.get(metric_key))
        if observed is None or expected is None:
            continue
        checks.append(
            {
                "metric": metric_key,
                "status": "PASS" if abs(observed - expected) <= 1e-8 else "CONFLICT",
                "series_value": observed,
                "formal_scalar_value": expected,
            }
        )
    status = "CONFLICT" if any(item["status"] == "CONFLICT" for item in checks) else "PASS"
    return {"status": status if checks else "NOT_CHECKED", "checks": checks}


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _metric_containers(payload: dict[str, Any]) -> list[Any]:
    containers: list[Any] = []
    for key in (
        "metrics",
        "verified_metrics",
        "core_metrics",
        "headline_metrics",
        "evaluation_summary",
        "long_side_performance",
        "performance_profile",
        "extensible_metrics",
        "summary",
    ):
        value = payload.get(key)
        if isinstance(value, (dict, list)):
            containers.append(value)
    long_review = payload.get("long_side_review")
    if isinstance(long_review, dict):
        containers.append(long_review)
    if not containers:
        containers.append(payload)
    return containers


def _find_alias(containers: list[Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        for container in containers:
            found, present = _find_key(container, alias)
            if present:
                return found
    return None


def _find_key(value: Any, target: str) -> tuple[Any, bool]:
    if isinstance(value, dict):
        if target in value and value[target] is not None:
            return value[target], True
        for key, child in value.items():
            if key in {"commands", "source_code", "stdout_tail", "stderr_tail"}:
                continue
            found, present = _find_key(child, target)
            if present:
                return found, True
    elif isinstance(value, list):
        for child in value:
            found, present = _find_key(child, target)
            if present:
                return found, True
    return None, False


def _timestamps(selected: dict[str, _Evidence]) -> dict[str, str]:
    timestamps: dict[str, str] = {}
    priorities = (
        "loop_report",
        "wrapper_report",
        "proof_certificate",
        "proof_verifier",
        "terminal_rejection",
        "council_synthesis",
        "council_summary",
        "factor_case",
        "research_state",
    )
    standard_keys = ("created_at_utc", "started_at_utc", "updated_at_utc", "finished_at_utc")
    for role in priorities:
        record = selected.get(role)
        if not record:
            continue
        for key in standard_keys:
            value = _string(record.payload.get(key))
            if value:
                timestamps.setdefault(key, value)
                timestamps[f"{role}.{key}"] = value
    return timestamps


def _select_fields(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    result: dict[str, Any] = {}
    for key in fields:
        value = source.get(key)
        if value is None:
            continue
        copied = _public_copy(value)
        if copied is not None:
            result[key] = copied
    return result


def _public_copy(value: Any, *, depth: int = 0) -> Any:
    if depth > 7:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        return _sanitize_public_text(text)[:20_000]
    if isinstance(value, list):
        output = [_public_copy(child, depth=depth + 1) for child in value[:200]]
        return [child for child in output if child is not None]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in list(value.items())[:300]:
            if _DENIED_PUBLIC_KEYS.search(str(key)):
                continue
            copied = _public_copy(child, depth=depth + 1)
            if copied is not None:
                output[str(key)] = copied
        return output
    return _string(value)


def _sanitize_public_text(value: str) -> str:
    text = _PUBLIC_PRIVATE_KEY.sub("[redacted-private-key]", value)
    text = _PUBLIC_BEARER_SECRET.sub("Bearer [redacted]", text)
    text = _PUBLIC_SECRET_ASSIGNMENT.sub(r"\1[redacted]", text)
    text = _PUBLIC_INTERNAL_PATH.sub("[internal-path]", text)
    return text


def _first_public_value(payloads: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> Any:
    for key in keys:
        for payload in payloads:
            found, present = _find_key(payload, key)
            if present:
                copied = _public_copy(found)
                if copied not in (None, {}, []):
                    return copied
    return None


def _find_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    found, present = _find_key(payload, key)
    return found if present and isinstance(found, dict) else {}


def _path(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _latest_iteration_value(loop: dict[str, Any], key: str) -> Any:
    iterations = loop.get("iterations")
    if not isinstance(iterations, list):
        return None
    for item in reversed(iterations):
        if isinstance(item, dict) and item.get(key) is not None:
            return item.get(key)
    return None


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _string(value)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output
