#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import load_json, resolve_factorforge_context, utc_now
from factor_factory.child_materialization import (
    MATERIALIZATION_VERSION as CHILD_MATERIALIZATION_VERSION,
    validate_child_materialization_readback,
)
from factor_factory.research_org.runtime_trust import load_runtime_trust_store
from factor_factory.council_terminal import classify_terminal_rejection_result
from factor_factory.research_org.contracts import ResearchOrganizationError
from factor_factory.ultimate_loop.proof import (
    append_note,
    load_json_if_exists,
    make_initial_proof,
    path_snapshot,
    snapshots_differ,
    tail,
    write_json_atomic,
)
from factor_factory.ultimate_loop.state import approved_child_revision_from_handoff, classify_loop_state

METRIC_ALIASES: dict[str, list[str]] = {
    "rank_ic_mean": ["rank_ic_mean", "rank_ic"],
    "long_side_annual_return": ["long_side_annual_return", "annual_return", "long_annual_return"],
    "cost_adjusted_annual_return": ["cost_adjusted_annual_return", "cost_adjusted_return", "net_annual_return"],
    "turnover": ["turnover", "turnover_mean", "long_side_turnover_mean_daily", "daily_turnover", "turnover_mean_daily"],
    "long_side_max_drawdown": ["long_side_max_drawdown", "max_drawdown", "long_side_mdd", "mdd"],
    "long_side_recovery_days": ["long_side_recovery_days", "recovery_days", "long_side_recovery_time_days"],
}

PAUSED_NOTE_STATES = {
    "awaiting_main_agent_mechanism_memo",
    "awaiting_agent_results",
    "awaiting_main_agent_council_synthesis",
    "awaiting_next_derivation",
    "WAITING_EXTERNAL_HUMAN_APPROVAL",
    "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION",
    "max_loops_reached",
}

BUDGET_EXHAUSTION_VERSION = "factorforge_ultimate_loop_budget_exhaustion_v1"
BUDGET_EXHAUSTION_SEMANTICS = "research_budget_exhausted_not_factor_proof"
OOS_HOST_TRUST_ROOT_ENV = "FACTORFORGE_OOS_HOST_TRUST_ROOT"
OOS_HOST_INSTALLATION_ID_ENV = "FACTORFORGE_OOS_HOST_INSTALLATION_ID"
BLOCK_INCIDENT_CONTEXT_REQUIRED = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_REQUIRED"
)
BLOCK_INCIDENT_CONTEXT_INCOMPLETE = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_INCOMPLETE"
)
BLOCK_INCIDENT_CONTEXT_INVALID = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_INVALID"
)
BLOCK_INCIDENT_CONTEXT_MISMATCH = (
    "BLOCK_FACTORFORGE_OOS_INCIDENT_RUNTIME_TRUST_CONTEXT_MISMATCH"
)


def mark_budget_exhausted(
    proof: dict[str, Any],
    iteration: dict[str, Any] | None,
) -> None:
    """Close a bounded search budget without claiming factor-proof completion."""

    pre_budget_can_continue = bool(
        isinstance(iteration, dict) and iteration.get("can_continue") is True
    )
    exhaustion = {
        "contract_version": BUDGET_EXHAUSTION_VERSION,
        "reason": "max_loops_reached",
        "configured_max_loops": proof.get("max_loops"),
        "last_completed_loop_index": (
            iteration.get("loop_index") if isinstance(iteration, dict) else None
        ),
        "pre_budget_state_can_continue": pre_budget_can_continue,
        "completed_iteration_evidence_preserved": isinstance(iteration, dict),
        "factor_proof_completed": False,
        "continuation_requires_new_authorized_budget": True,
    }
    proof["status"] = "PAUSED"
    proof["formal_proof_eligible"] = False
    proof["factor_proof_completed"] = False
    proof["completion_semantics"] = BUDGET_EXHAUSTION_SEMANTICS
    proof["final_outcome"] = "max_loops_reached"
    proof["stop_reason"] = "max_loops_reached"
    proof["budget_exhaustion"] = exhaustion
    proof["updated_at_utc"] = utc_now()
    if isinstance(iteration, dict):
        iteration["outcome"] = "max_loops_reached"
        iteration["stop_reason"] = "max_loops_reached"
        iteration["proof_status"] = "PAUSED"
        iteration["can_continue"] = False
        iteration["formal_proof_eligible"] = False
        iteration["factor_proof_completed"] = False
        iteration["completion_semantics"] = BUDGET_EXHAUSTION_SEMANTICS
        iteration["budget_exhaustion"] = exhaustion.copy()


def paused_note_paths(factorforge_root: Path, report_id: str) -> tuple[Path, Path]:
    base = factorforge_root / "objects" / "research_iteration_master"
    return (
        base / f"paused_research_note__{report_id}.json",
        base / f"paused_research_note__{report_id}.md",
    )


def _paused_next_questions(pause_state: str) -> list[str]:
    if pause_state == "awaiting_main_agent_mechanism_memo":
        return [
            "What is the formula-specific economic mechanism and selected mathematical model?",
            "Which observable estimator and metric signature would falsify this mechanism?",
        ]
    if pause_state == "awaiting_agent_results":
        return [
            "Which Council agents have not returned their advisory packets?",
            "Does the current evidence require waiting, rerun, or manual cancellation?",
        ]
    if pause_state == "awaiting_main_agent_council_synthesis":
        return [
            "Which Council proposal should be selected as the executable revision law?",
            "What are the child formula/code law, expected metric signature, falsification tests, and kill criteria?",
        ]
    if pause_state == "awaiting_next_derivation":
        return [
            "Which research equation component failed?",
            "Should the next branch be bug fix, data artifact check, implementation artifact check, tradable anomaly, or new factor seed?",
        ]
    if pause_state == "WAITING_EXTERNAL_HUMAN_APPROVAL":
        return [
            "Has an external human reviewed the selected law, mechanism delta, economic backprojection, and child intent?",
            "Is a signed approval receipt bound to a fresh sealed OOS allocation available?",
        ]
    if pause_state == "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION":
        return [
            "Has the Host allocated a fresh sealed OOS token and disjoint dataset/window for this child?",
            "Are the child protocol, frozen trial ledger, threshold registration, and lifecycle preregistered?",
        ]
    if pause_state == "max_loops_reached":
        return [
            "Does an external research owner authorize a new bounded loop budget?",
            "Which still-open mechanism test or branch justifies spending that new budget?",
        ]
    return ["What explicit human or agent decision is required before the loop may continue?"]


def write_paused_research_note(
    *,
    factorforge_root: Path,
    report_id: str,
    pause_state: str,
    proof: dict[str, Any],
    iteration: dict[str, Any] | None,
    reason: str | None = None,
) -> dict[str, str]:
    json_path, markdown_path = paused_note_paths(factorforge_root, report_id)
    latest_iteration = iteration or {}
    payload = {
        "version": "factorforge_paused_research_note_v1",
        "status": "paused",
        "report_id": report_id,
        "parent_report_id": latest_iteration.get("parent_report_id"),
        "pause_state": pause_state,
        "reason": reason or proof.get("stop_reason") or latest_iteration.get("stop_reason"),
        "created_at_utc": utc_now(),
        "proof_status": proof.get("status"),
        "final_outcome": proof.get("final_outcome"),
        "wrapper_command_status": (latest_iteration.get("wrapper_command") or {}).get("status"),
        "wrapper_rc": (latest_iteration.get("wrapper_command") or {}).get("rc"),
        "backend_status": {
            "step4": latest_iteration.get("step4_status"),
            "self_quant": latest_iteration.get("self_quant_status"),
            "qlib": latest_iteration.get("qlib_native_status"),
        },
        "core_metrics": latest_iteration.get("core_metrics") or proof.get("core_metrics") or {},
        "evidence_paths": {
            "ultimate_loop_report": proof.get("proof_path"),
            "wrapper_proof_path": latest_iteration.get("wrapper_proof_path"),
            "materialization_report_path": latest_iteration.get("materialization_report_path"),
            "next_derivation_questionnaire_path": proof.get("next_derivation_questionnaire_path"),
        },
        "research_lessons": proof.get("notes") or [],
        "next_questions": _paused_next_questions(pause_state),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(json_path, payload)
    markdown = [
        f"# Paused Research Note: {report_id}",
        "",
        f"- Status: paused",
        f"- Pause state: {pause_state}",
        f"- Reason: {payload['reason']}",
        f"- Wrapper rc: {payload['wrapper_rc']}",
        "",
        "## Next Questions",
        *[f"- {item}" for item in payload["next_questions"]],
        "",
        "## Evidence Paths",
        *[f"- {key}: {value}" for key, value in payload["evidence_paths"].items() if value],
        "",
    ]
    markdown_path.write_text("\n".join(markdown), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def attach_paused_note_if_needed(
    *,
    factorforge_root: Path,
    report_id: str,
    proof: dict[str, Any],
    iteration: dict[str, Any] | None,
    pause_state: str | None = None,
    reason: str | None = None,
) -> None:
    state = pause_state or proof.get("final_outcome")
    if proof.get("status") != "PAUSED" or state not in PAUSED_NOTE_STATES:
        return
    note = write_paused_research_note(
        factorforge_root=factorforge_root,
        report_id=report_id,
        pause_state=str(state),
        proof=proof,
        iteration=iteration,
        reason=reason,
    )
    proof["paused_research_note_json_path"] = note["json_path"]
    proof["paused_research_note_markdown_path"] = note["markdown_path"]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Factor Forge Ultimate in a bounded revision loop.")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--start-step", default="3")
    ap.add_argument("--max-loops", type=int, default=10)
    ap.add_argument("--council-mode", default="auto", choices=["off", "auto", "scaffold", "agentic"])
    ap.add_argument("--auto-council-policy", default="dispatch_manifest", choices=["scaffold", "dispatch_manifest", "block_without_agentic"])
    ap.add_argument("--agentic-council-executor", default="none", choices=["none", "local_mock", "dispatch_manifest", "real_agent"])
    ap.add_argument("--agentic-dispatch-adapter", default="none", choices=["none", "manual_file", "openclaw", "codex", "remote_api"])
    ap.add_argument("--runtime-dispatch", default=None, choices=["codex", "openclaw", "manual_file", "unknown"])
    ap.add_argument("--subagent-provider", default=None)
    ap.add_argument("--subagent-model", default=None)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--factor-workspace", default=None)
    ap.add_argument("--runtime-manifest", default=None)
    ap.add_argument(
        "--expected-host-trust-manifest-sha256",
        default=None,
        help=(
            "Externally pinned Host public trust-manifest digest. Formal EVO "
            "child flows must receive it from the Host control plane; never "
            "derive it from the mutable factor workspace."
        ),
    )
    ap.add_argument(
        "--incident-trust-root",
        default=None,
        help=(
            "Host-private OOS incident trust root. Required together with "
            "--incident-installation-id for every formal non-dry run."
        ),
    )
    ap.add_argument(
        "--incident-installation-id",
        default=None,
        help=(
            "Host installation id bound to --incident-trust-root. Required "
            "for every formal non-dry run."
        ),
    )
    ap.add_argument("--allow-legacy-global-runtime", action="store_true")
    ap.add_argument("--proof-path", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-legacy-research-protocol-smoke",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return ap.parse_args()


def resolve_incident_host_context(
    args: argparse.Namespace,
) -> tuple[Path | None, str | None]:
    """Resolve one explicit Host pair; never upgrade ambient state to authority."""

    trust_raw = str(getattr(args, "incident_trust_root", None) or "").strip()
    installation_id = str(
        getattr(args, "incident_installation_id", None) or ""
    ).strip()
    if bool(trust_raw) != bool(installation_id):
        raise ValueError(BLOCK_INCIDENT_CONTEXT_INCOMPLETE)
    formal_non_dry = bool(
        not getattr(args, "dry_run", False)
        and not getattr(args, "allow_legacy_research_protocol_smoke", False)
    )
    if formal_non_dry and not trust_raw:
        raise ValueError(BLOCK_INCIDENT_CONTEXT_REQUIRED)
    if not trust_raw:
        return None, None
    try:
        trust_root = Path(trust_raw).expanduser().resolve(strict=True)
        load_runtime_trust_store(
            trust_root,
            installation_id=installation_id,
        )
    except (OSError, ValueError, ResearchOrganizationError) as exc:
        raise ValueError(BLOCK_INCIDENT_CONTEXT_INVALID) from exc

    ambient_trust = str(os.environ.get(OOS_HOST_TRUST_ROOT_ENV) or "").strip()
    ambient_installation = str(
        os.environ.get(OOS_HOST_INSTALLATION_ID_ENV) or ""
    ).strip()
    if bool(ambient_trust) != bool(ambient_installation):
        raise ValueError(BLOCK_INCIDENT_CONTEXT_MISMATCH)
    if ambient_trust:
        try:
            ambient_root = Path(ambient_trust).expanduser().resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ValueError(BLOCK_INCIDENT_CONTEXT_MISMATCH) from exc
        if ambient_root != trust_root or ambient_installation != installation_id:
            raise ValueError(BLOCK_INCIDENT_CONTEXT_MISMATCH)
    return trust_root, installation_id


def run_command(command: list[str], *, env: dict[str, str], dry_run: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "command": command,
        "cwd": str(REPO_ROOT),
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "rc": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "status": "RUNNING",
    }
    if dry_run:
        item.update({"finished_at_utc": utc_now(), "rc": 0, "status": "DRY_RUN"})
        return item
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    item.update(
        {
            "finished_at_utc": utc_now(),
            "rc": proc.returncode,
            "stdout_tail": tail(proc.stdout),
            "stderr_tail": tail(proc.stderr),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        }
    )
    return item


def _redact_host_private_text(value: str, denied_values: tuple[str, ...]) -> str:
    redacted = value
    for denied in sorted(
        {item for item in denied_values if item}, key=len, reverse=True
    ):
        redacted = redacted.replace(denied, "[HOST_PRIVATE]")
    return redacted


def public_command_result(
    result: dict[str, Any],
    *,
    denied_values: tuple[str, ...],
) -> dict[str, Any]:
    """Project a command result without persisting Host-private control values."""

    projected = dict(result)

    command = projected.get("command")
    if isinstance(command, list):
        projected["command"] = [
            _redact_host_private_text(item, denied_values)
            if isinstance(item, str)
            else item
            for item in command
        ]
    for field in ("cwd", "stdout_tail", "stderr_tail"):
        if isinstance(projected.get(field), str):
            projected[field] = _redact_host_private_text(
                projected[field], denied_values
            )
    return projected


def public_loop_args(
    args: argparse.Namespace,
    *,
    denied_values: tuple[str, ...],
) -> dict[str, Any]:
    """Return public loop arguments with Host authority coordinates removed."""

    projected = dict(vars(args))
    for key, value in tuple(projected.items()):
        if isinstance(value, str):
            projected[key] = _redact_host_private_text(value, denied_values)
    for key in ("incident_trust_root", "incident_installation_id"):
        if projected.get(key):
            projected[key] = "[HOST_PRIVATE]"
    return projected


def wrapper_factor_workspace(args: argparse.Namespace, factorforge_root: Path) -> Path | None:
    if args.factor_workspace:
        return Path(args.factor_workspace).expanduser()
    if args.runtime_manifest:
        manifest = load_json_if_exists(Path(args.runtime_manifest).expanduser())
        raw_workspace = manifest.get("factor_workspace") if isinstance(manifest, dict) else None
        if raw_workspace:
            return Path(str(raw_workspace)).expanduser()
    if (factorforge_root / "manifest.json").exists():
        return factorforge_root
    return None


def ultimate_command(args: argparse.Namespace, report_id: str, start_step: str, factorforge_root: Path) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_factorforge_ultimate.py"),
        "--report-id",
        report_id,
        "--start-step",
        start_step,
        "--end-step",
        "6",
        "--council-mode",
        args.council_mode,
        "--auto-council-policy",
        args.auto_council_policy,
        "--agentic-council-executor",
        args.agentic_council_executor,
        "--agentic-dispatch-adapter",
        args.agentic_dispatch_adapter,
        "--factorforge-root",
        str(factorforge_root),
    ]
    factor_workspace = wrapper_factor_workspace(args, factorforge_root)
    if factor_workspace is not None:
        command.extend(["--factor-workspace", str(factor_workspace)])
    if args.allow_legacy_global_runtime:
        command.append("--allow-legacy-global-runtime")
    if getattr(args, "expected_host_trust_manifest_sha256", None):
        command.extend(
            [
                "--expected-host-trust-manifest-sha256",
                args.expected_host_trust_manifest_sha256,
            ]
        )
    if args.runtime_dispatch:
        command.extend(["--runtime-dispatch", args.runtime_dispatch])
    if args.subagent_provider:
        command.extend(["--subagent-provider", args.subagent_provider])
    if args.subagent_model:
        command.extend(["--subagent-model", args.subagent_model])
    if args.allow_legacy_research_protocol_smoke:
        command.append("--allow-legacy-research-protocol-smoke")
    if args.dry_run:
        command.append("--dry-run")
    return command


def materialization_command(
    parent_report_id: str,
    child_report_id: str,
    factorforge_root: Path,
    *,
    expected_host_trust_manifest_sha256: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
) -> list[str]:
    if bool(incident_trust_root) != bool(incident_installation_id):
        raise ValueError(BLOCK_INCIDENT_CONTEXT_INCOMPLETE)
    command = [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py"),
        "--parent-report-id",
        parent_report_id,
        "--child-report-id",
        child_report_id,
        "--factorforge-root",
        str(factorforge_root),
    ]
    if expected_host_trust_manifest_sha256:
        command.extend(
            [
                "--expected-host-trust-manifest-sha256",
                expected_host_trust_manifest_sha256,
            ]
        )
    if incident_trust_root is not None and incident_installation_id:
        command.extend(
            [
                "--incident-trust-root",
                str(incident_trust_root),
                "--incident-installation-id",
                incident_installation_id,
            ]
        )
    return command


def multibranch_materialization_command(
    report_id: str,
    factorforge_root: Path,
    loop_index: int,
    *,
    expected_host_trust_manifest_sha256: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    allow_legacy_incident_context_smoke: bool = False,
) -> list[str]:
    if bool(incident_trust_root) != bool(incident_installation_id):
        raise ValueError(BLOCK_INCIDENT_CONTEXT_INCOMPLETE)
    command = [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_multibranch_children.py"),
        "--report-id",
        report_id,
        "--factorforge-root",
        str(factorforge_root),
        "--loop-index",
        str(loop_index),
    ]
    if expected_host_trust_manifest_sha256:
        command.extend(
            [
                "--expected-host-trust-manifest-sha256",
                expected_host_trust_manifest_sha256,
            ]
        )
    if incident_trust_root is not None and incident_installation_id:
        command.extend(
            [
                "--incident-trust-root",
                str(incident_trust_root),
                "--incident-installation-id",
                incident_installation_id,
            ]
        )
    if allow_legacy_incident_context_smoke:
        command.append("--allow-legacy-incident-context-smoke")
    return command


def branch_comparison_command(
    parent_report_id: str,
    selected_child_report_id: str,
    factorforge_root: Path,
    loop_index: int,
    *,
    why: str,
    learned: str,
) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "build_branch_comparison.py"),
        "--parent-report-id",
        parent_report_id,
        "--loop-index",
        str(loop_index),
        "--selected-next-parent-child-report-id",
        selected_child_report_id,
        "--factorforge-root",
        str(factorforge_root),
        "--why",
        why,
        "--what-learned-from-exploration",
        learned,
    ]


def terminal_rejection_command(report_id: str, factorforge_root: Path, loop_index: int, max_loops: int) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "close_terminal_council_rejection.py"),
        "--report-id",
        report_id,
        "--factorforge-root",
        str(factorforge_root),
        "--loop-index",
        str(loop_index),
        "--max-loops",
        str(max_loops),
    ]


def final_protocol_validation_command(
    report_id: str,
    factorforge_root: Path,
) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "validate_factorforge_research_protocol.py"),
        "--workspace-root",
        str(factorforge_root),
        "--report-id",
        report_id,
        "--stage",
        "final",
    ]


def terminal_protocol_validated_from_wrapper(
    wrapper_proof: dict[str, Any] | None,
) -> bool:
    proof = wrapper_proof if isinstance(wrapper_proof, dict) else {}
    council = (
        proof.get("revision_council")
        if isinstance(proof.get("revision_council"), dict)
        else {}
    )
    return bool(
        proof.get("status") == "PASS"
        and council.get("terminal_protocol_validated") is True
        and council.get("terminal_decision") == "REJECT"
        and council.get("formal_council_status") == "rejected"
    )


def materialization_report_path(factorforge_root: Path, parent_report_id: str, child_report_id: str) -> Path:
    digest = hashlib.sha256(f"{parent_report_id}\0{child_report_id}".encode("utf-8")).hexdigest()[:16]
    short_parent = parent_report_id[:40].rstrip("_")
    short_child = child_report_id[:40].rstrip("_")
    filename = f"child_revision_materialization__{short_parent}__{short_child}__{digest}.json"
    return factorforge_root / "objects" / "runtime_context" / filename


def branch_falsification_path(factorforge_root: Path, report_id: str) -> Path:
    return (
        factorforge_root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"branch_falsification__{report_id}.json"
    )


def multibranch_materialization_report_path(factorforge_root: Path, report_id: str, loop_index: int) -> Path:
    return factorforge_root / "objects" / "runtime_context" / f"multibranch_child_materialization__{report_id}__loop{loop_index:02d}.json"


def branch_comparison_path(factorforge_root: Path, report_id: str, loop_index: int) -> Path:
    return factorforge_root / "objects" / "research_iteration_master" / f"branch_comparison__{report_id}__loop{loop_index:02d}.json"


def next_derivation_questionnaire_path(factorforge_root: Path, report_id: str) -> Path:
    return (
        factorforge_root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"next_derivation_questionnaire__{report_id}.json"
    )


def synthesis_bridge_ready(factorforge_root: Path, report_id: str) -> bool:
    council_dir = factorforge_root / "objects" / "research_iteration_master" / "revision_council" / report_id
    return (
        (council_dir / f"main_agent_council_synthesis__{report_id}.json").exists()
        and (council_dir / f"revision_council_summary__{report_id}.json").exists()
    )


def multibranch_synthesis_bridge_ready(factorforge_root: Path, report_id: str) -> bool:
    council_dir = factorforge_root / "objects" / "research_iteration_master" / "revision_council" / report_id
    return (
        (council_dir / f"main_agent_multibranch_synthesis__{report_id}.json").exists()
        and (council_dir / f"revision_council_summary__{report_id}.json").exists()
    )


def multibranch_manual_approval_ready(
    factorforge_root: Path, report_id: str
) -> bool:
    council_dir = (
        factorforge_root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
    )
    synthesis_path = council_dir / f"main_agent_multibranch_synthesis__{report_id}.json"
    approval_path = council_dir / f"main_agent_multibranch_synthesis_approval__{report_id}.json"
    if not synthesis_path.is_file() or not approval_path.is_file():
        return False
    conjecture_path = (
        factorforge_root
        / "objects"
        / "research_protocol"
        / f"research_conjecture__{report_id}.json"
    )
    conjecture = load_json_if_exists(conjecture_path)
    if (
        isinstance(conjecture.get("epistemic_evolution"), dict)
        and conjecture["epistemic_evolution"].get("enabled") is True
    ):
        # The legacy multibranch approval artifact has no per-child signed
        # human receipt or fresh OOS allocation binding. EVO V2 therefore
        # remains paused instead of treating that artifact as authorization.
        return False
    synthesis = load_json_if_exists(synthesis_path)
    approval = load_json_if_exists(approval_path)
    forbidden = {
        "ultimate_loop_auto_bridge",
        "ultimate_loop_auto_multibranch_bridge",
        "current_main_agent_orchestration_synthesis",
        "current_main_agent_default_approval",
        "automatic",
        "agent",
        "runtime",
    }
    source = str(approval.get("approval_source") or "").strip().lower()
    branches = approval.get("selected_branches")
    return bool(
        synthesis
        and approval.get("contract_version")
        == "factorforge_main_agent_multibranch_synthesis_approval_v1"
        and approval.get("parent_report_id") == report_id
        and approval.get("source_multibranch_synthesis_sha256")
        == hashlib.sha256(synthesis_path.read_bytes()).hexdigest()
        and source
        and source not in forbidden
        and approval.get("human_approval_required") is True
        and approval.get("execution_allowed_by_default") is False
        and isinstance(branches, list)
        and bool(branches)
        and approval.get("selected_branch_count") == len(branches)
    )


def terminal_rejection_bridge_ready(factorforge_root: Path, report_id: str) -> bool:
    council_dir = factorforge_root / "objects" / "research_iteration_master" / "revision_council" / report_id
    return (
        (council_dir / f"revision_council_summary__{report_id}.json").exists()
        and (council_dir / f"agentic_result_collection__{report_id}.json").exists()
    )


def existing_materialization_report(factorforge_root: Path, parent_report_id: str, child_report_id: str) -> dict[str, Any]:
    path = materialization_report_path(factorforge_root, parent_report_id, child_report_id)
    report = load_json_if_exists(path)
    if not isinstance(report, dict) or not report:
        return {"ok": False, "report_path": str(path), "reason": "materialization_report_missing"}
    if report.get("materialization_version") != CHILD_MATERIALIZATION_VERSION:
        return {"ok": False, "report_path": str(path), "reason": "materialization_version_mismatch"}
    if report.get("parent_report_id") != parent_report_id or report.get("child_report_id") != child_report_id:
        return {"ok": False, "report_path": str(path), "reason": "materialization_identity_mismatch"}
    source_handoff = (
        factorforge_root
        / "objects"
        / "handoff"
        / f"handoff_to_step3b__{parent_report_id}.json"
    )
    if not source_handoff.is_file() or source_handoff.is_symlink():
        return {
            "ok": False,
            "report_path": str(path),
            "reason": "materialization_source_handoff_missing",
        }
    readback_reasons = validate_child_materialization_readback(
        workspace_root=factorforge_root,
        report_path=path,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        source_handoff_sha256=hashlib.sha256(source_handoff.read_bytes()).hexdigest(),
        required_target_kinds={
            "alpha_idea_master",
            "factor_spec_master",
            "data_prep_master",
            "executable_revision_spec",
            "qlib_adapter_config",
            "state_dependency_contract",
            "state_resolution",
        },
    )
    if readback_reasons:
        return {
            "ok": False,
            "report_path": str(path),
            "reason": "materialization_hash_readback_invalid",
            "readback_reasons": readback_reasons,
        }
    artifacts = report.get("materialized_artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return {"ok": False, "report_path": str(path), "reason": "materialized_artifacts_missing"}
    missing: list[str] = []
    for key in ("alpha_idea_master", "factor_spec_master", "data_prep_master", "executable_revision_spec"):
        raw = artifacts.get(key) or (report.get("executable_revision_spec_path") if key == "executable_revision_spec" else None)
        if not isinstance(raw, str) or not raw:
            missing.append(key)
            continue
        artifact_path = Path(raw)
        if not artifact_path.is_absolute():
            artifact_path = factorforge_root / artifact_path
        if not artifact_path.exists():
            missing.append(key)
    if missing:
        return {"ok": False, "report_path": str(path), "reason": "materialized_artifacts_missing_on_disk", "missing": missing}
    return {"ok": True, "report_path": str(path), "report": report}


def collect_key_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if isinstance(evaluation.get("key_metrics"), dict):
        metrics.update(evaluation["key_metrics"])
    for item in evaluation.get("backend_summary") or []:
        if isinstance(item, dict) and isinstance(item.get("key_metrics"), dict):
            metrics.update(item["key_metrics"])
    if isinstance(evaluation.get("metrics"), dict):
        metrics.update(evaluation["metrics"])
    return metrics


def numeric_metric(metrics: dict[str, Any], key: str) -> float | None:
    for candidate in METRIC_ALIASES.get(key, [key]):
        value = metrics.get(candidate)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def factor_evaluation_metrics(factorforge_root: Path, report_id: str) -> dict[str, float]:
    evaluation = load_json_if_exists(factorforge_root / "objects" / "validation" / f"factor_evaluation__{report_id}.json")
    raw = collect_key_metrics(evaluation if isinstance(evaluation, dict) else {})
    metrics: dict[str, float] = {}
    for key in METRIC_ALIASES:
        value = numeric_metric(raw, key)
        if value is not None:
            metrics[key] = value
    return metrics


def select_multibranch_child(factorforge_root: Path, children: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for child in children:
        child_id = str(child.get("child_report_id") or "")
        metrics = factor_evaluation_metrics(factorforge_root, child_id)
        score = (
            metrics.get("cost_adjusted_annual_return", float("-inf")),
            metrics.get("rank_ic_mean", float("-inf")),
            metrics.get("long_side_annual_return", float("-inf")),
            -metrics.get("turnover", float("inf")),
            metrics.get("long_side_max_drawdown", float("-inf")),
            -metrics.get("long_side_recovery_days", float("inf")),
            -float(child.get("branch_index") or 0),
        )
        candidates.append({"child_report_id": child_id, "score": score, "metrics": metrics, "branch": child})
    if not candidates:
        return {"ok": False, "block_reason": "BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_NO_CHILDREN"}
    selected = max(candidates, key=lambda item: item["score"])
    if not selected.get("child_report_id"):
        return {"ok": False, "block_reason": "BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_NO_SELECTED_CHILD"}
    return {
        "ok": True,
        "selected_child_report_id": selected["child_report_id"],
        "selection_metric_order": [
            "cost_adjusted_annual_return",
            "rank_ic_mean",
            "long_side_annual_return",
            "lower_turnover",
            "less_negative_max_drawdown",
            "lower_recovery_days",
        ],
        "selected_metrics": selected["metrics"],
        "candidate_scores": candidates,
    }


def brief_ref(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    iteration_path = factorforge_root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json"
    iteration = load_json_if_exists(iteration_path)
    ref = iteration.get("loop_research_brief") if isinstance(iteration, dict) else None
    return ref if isinstance(ref, dict) else {}


def read_brief_json(factorforge_root: Path, report_id: str) -> dict[str, Any]:
    ref = brief_ref(factorforge_root, report_id)
    path = ref.get("json_path")
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = factorforge_root / candidate
    return load_json_if_exists(candidate)


def write_aggregate_brief(path: Path, proof: dict[str, Any], factorforge_root: Path) -> None:
    lines = [
        f"# Factor Forge Ultimate Loop Brief: {proof['root_report_id']}",
        "",
        f"- Status: {proof.get('status')}",
        f"- Final outcome: {proof.get('final_outcome')}",
        f"- Stop reason: {proof.get('stop_reason')}",
        f"- Iterations: {len(proof.get('iterations') or [])}",
        "",
    ]
    for item in proof.get("iterations") or []:
        report_id = item.get("report_id")
        brief = read_brief_json(factorforge_root, str(report_id))
        decision = (brief.get("decision_snapshot") or {}).get("decision") or item.get("decision")
        economic = brief.get("economic_interpretation") or {}
        metrics = brief.get("metrics") or {}
        math_summary = brief.get("mechanism_math_summary") or {}
        council = brief.get("revision_council_summary") or {}
        next_direction = brief.get("next_research_direction") or {}
        lines.extend(
            [
                f"## Loop {item.get('loop_index')}: {report_id}",
                "",
                "### Economic Interpretation",
                f"- Formula: {economic.get('formula', 'missing')}",
                f"- Mechanism: {economic.get('mechanism_hypothesis', 'missing')}",
                "",
                "### Mechanism Math",
                f"- Status: {math_summary.get('math_model_status', 'missing')}",
                f"- Model family: {math_summary.get('model_family', 'missing')}",
                "",
                "### Metrics",
                f"- Rank IC mean: {metrics.get('rank_ic_mean', 'missing')}",
                f"- Long-side Sharpe: {metrics.get('long_side_sharpe', 'missing')}",
                f"- Cost-adjusted annual return: {metrics.get('cost_adjusted_annual_return', 'missing')}",
                "",
                "### Council",
                f"- Status: {item.get('council_status') or council.get('status', 'not_attached')}",
                f"- Selected proposals: {council.get('selected_proposals', [])}",
                "",
                "### Decision",
                f"- Decision: {decision}",
                f"- Loop authorization: {item.get('loop_authorization')}",
                "",
                "### Next Action",
                f"- Outcome: {item.get('outcome')}",
                f"- Child report: {item.get('child_report_id') or 'none'}",
                f"- Revision direction: {next_direction.get('revision_hypothesis', 'none')}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def finalize_budget_exhaustion(
    *,
    proof: dict[str, Any],
    iteration: dict[str, Any] | None,
    proof_path: Path,
    brief_path: Path,
    factorforge_root: Path,
    report_id: str,
) -> int:
    mark_budget_exhausted(proof, iteration)
    append_note(
        proof,
        (
            f"Research loop budget exhausted for {report_id}; completed iteration "
            "evidence is retained, but no factor-proof completion is claimed"
        ),
    )
    attach_paused_note_if_needed(
        factorforge_root=factorforge_root,
        report_id=report_id,
        proof=proof,
        iteration=iteration,
        pause_state="max_loops_reached",
        reason="max_loops_reached",
    )
    write_json_atomic(proof_path, proof)
    write_aggregate_brief(brief_path, proof, factorforge_root)
    print("max_loops_reached")
    return 0


def ancestor_generated_code_snapshots(factorforge_root: Path, ancestors: list[str]) -> dict[str, dict[str, Any]]:
    return {
        report_id: path_snapshot(factorforge_root / "generated_code" / report_id)
        for report_id in ancestors
    }


def changed_ancestor_snapshots(factorforge_root: Path, before: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for report_id, old in before.items():
        new = path_snapshot(factorforge_root / "generated_code" / report_id)
        if snapshots_differ(old, new):
            changes.append({"report_id": report_id, "before": old, "after": new})
    return changes


def child_control_artifact_paths(factorforge_root: Path, report_id: str) -> dict[str, Path]:
    return {
        "handoff_to_step3b": factorforge_root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json",
        "official_record": factorforge_root / "objects" / "factor_library_official" / f"factor_record__{report_id}.json",
    }


def child_control_artifact_snapshots(factorforge_root: Path, child_report_ids: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    snapshots: dict[str, dict[str, dict[str, Any]]] = {}
    for report_id in child_report_ids:
        if not report_id:
            continue
        snapshots[report_id] = {
            name: path_snapshot(path)
            for name, path in child_control_artifact_paths(factorforge_root, report_id).items()
        }
    return snapshots


def changed_child_control_artifacts(
    factorforge_root: Path,
    before: dict[str, dict[str, dict[str, Any]]],
    selected_child_report_id: str,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for report_id, old_items in before.items():
        paths = child_control_artifact_paths(factorforge_root, report_id)
        new_handoff = path_snapshot(paths["handoff_to_step3b"])
        old_handoff = old_items.get("handoff_to_step3b") or {}
        if report_id != selected_child_report_id and new_handoff.get("exists") is True:
            changes.append(
                {
                    "kind": "non_selected_child_handoff_active",
                    "report_id": report_id,
                    "artifact": "handoff_to_step3b",
                    "path": str(paths["handoff_to_step3b"]),
                    "before": old_handoff,
                    "after": new_handoff,
                }
            )

        new_official = path_snapshot(paths["official_record"])
        old_official = old_items.get("official_record") or {}
        if new_official.get("exists") is True or snapshots_differ(old_official, new_official):
            changes.append(
                {
                    "kind": "child_official_record_written",
                    "report_id": report_id,
                    "artifact": "official_record",
                    "path": str(paths["official_record"]),
                    "before": old_official,
                    "after": new_official,
                }
            )
    return changes


def main() -> int:
    args = parse_args()
    if not (1 <= args.max_loops <= 10):
        print("BLOCK_FACTORFORGE_LOOP_MAX_LOOPS_OUT_OF_RANGE")
        return 1
    try:
        incident_trust_root, incident_installation_id = (
            resolve_incident_host_context(args)
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    explicit_root = args.factorforge_root
    if not explicit_root and args.runtime_manifest:
        manifest = load_json(Path(args.runtime_manifest).expanduser())
        explicit_root = manifest.get("factorforge_root")
    provisional_root = Path(
        explicit_root or os.getenv("FACTORFORGE_ROOT") or REPO_ROOT
    ).expanduser()
    factor_workspace = wrapper_factor_workspace(args, provisional_root)
    ctx = resolve_factorforge_context(
        explicit_root,
        factor_workspace=factor_workspace,
    )
    run_root = ctx.active_root
    if incident_trust_root is not None:
        resolved_run_root = run_root.expanduser().resolve(strict=False)
        if (
            incident_trust_root == resolved_run_root
            or incident_trust_root in resolved_run_root.parents
            or resolved_run_root in incident_trust_root.parents
        ):
            print(BLOCK_INCIDENT_CONTEXT_INVALID)
            return 1
    legacy_protocol_smoke_root = str(run_root.resolve()).startswith(
        ("/tmp/", "/private/tmp/")
    )
    if (
        args.allow_legacy_research_protocol_smoke
        and not legacy_protocol_smoke_root
    ):
        print("BLOCK_FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE_SCOPE_INVALID")
        return 1
    host_private_proof_values = tuple(
        value
        for value in (
            str(getattr(args, "incident_trust_root", None) or ""),
            str(incident_trust_root or ""),
            str(incident_installation_id or ""),
        )
        if value
    )
    proof_path = Path(args.proof_path) if args.proof_path else ctx.runtime_context_root / f"ultimate_loop_report__{args.report_id}.json"
    proof_path = proof_path.expanduser().resolve(strict=False)
    if (
        ctx.factor_workspace is not None
        and proof_path != run_root
        and run_root not in proof_path.parents
    ):
        print("BLOCK_FACTORFORGE_RESEARCH_OUTPUT_OUTSIDE_WORKSPACE")
        return 1
    brief_path = ctx.runtime_context_root / f"ultimate_loop_brief__{args.report_id}.md"

    proof = make_initial_proof(
        root_report_id=args.report_id,
        factorforge_root=run_root,
        max_loops=args.max_loops,
        args=public_loop_args(
            args,
            denied_values=host_private_proof_values,
        ),
    )
    proof["dry_run"] = bool(args.dry_run)
    proof["contract_smoke_only"] = bool(
        args.allow_legacy_research_protocol_smoke
    )
    proof["formal_proof_eligible"] = False
    proof["proof_semantics"] = (
        "execution_plan_only"
        if args.dry_run
        else (
            "contract_smoke_only"
            if args.allow_legacy_research_protocol_smoke
            else "formal_execution_proof"
        )
    )
    proof["proof_path"] = str(proof_path)
    proof["brief_path"] = str(brief_path)
    write_json_atomic(proof_path, proof)

    env = os.environ.copy()
    env.pop(OOS_HOST_TRUST_ROOT_ENV, None)
    env.pop(OOS_HOST_INSTALLATION_ID_ENV, None)
    if incident_trust_root is not None and incident_installation_id:
        env[OOS_HOST_TRUST_ROOT_ENV] = str(incident_trust_root)
        env[OOS_HOST_INSTALLATION_ID_ENV] = incident_installation_id
    env["FACTORFORGE_ROOT"] = str(run_root)
    env["FACTORFORGE_ULTIMATE_RUN"] = "1"
    if args.allow_legacy_research_protocol_smoke:
        env["FACTORFORGE_LEGACY_RESEARCH_PROTOCOL_SMOKE"] = "1"
    if args.runtime_manifest:
        env["FACTORFORGE_RUNTIME_MANIFEST"] = str(Path(args.runtime_manifest).expanduser())

    current_report_id = args.report_id
    current_start_step = args.start_step
    current_parent_report_id: str | None = None
    ancestor_report_ids: list[str] = []
    data_clean_before = path_snapshot(ctx.clean_data_root)

    for loop_index in range(1, args.max_loops + 1):
        ancestor_before = ancestor_generated_code_snapshots(run_root, ancestor_report_ids)
        command = ultimate_command(args, current_report_id, current_start_step, run_root)
        command_result = run_command(command, env=env, dry_run=args.dry_run)

        if (
            env.get("FACTORFORGE_ULTIMATE_LOOP_TEST_DELETE_HANDOFF_AFTER_WRAPPER") == "1"
            and str(run_root.resolve()).startswith(("/tmp/", "/private/tmp/"))
        ):
            handoff = run_root / "objects" / "handoff" / f"handoff_to_step3b__{current_report_id}.json"
            if handoff.exists():
                handoff.unlink()

        ancestor_changes = changed_ancestor_snapshots(run_root, ancestor_before)
        data_clean_after = path_snapshot(ctx.clean_data_root)
        forbidden_changes = []
        if ancestor_changes:
            forbidden_changes.append({"kind": "parent_generated_code_mutation", "changes": ancestor_changes})
        if snapshots_differ(data_clean_before, data_clean_after):
            forbidden_changes.append({"kind": "data_clean_mutation", "before": data_clean_before, "after": data_clean_after})

        if args.dry_run:
            state = {
                "outcome": "dry_run",
                "proof_status": "DRY_RUN",
                "can_continue": False,
                "stop_reason": "BLOCK_FACTORFORGE_LOOP_DRY_RUN_NOT_FORMAL",
                "decision": None,
                "loop_authorization": None,
                "revision_needed": None,
                "council_status": None,
                "official_record_exists": False,
                "handoff_to_step3b_exists": False,
                "prewrite_block_exists": False,
            }
        else:
            state = classify_loop_state(
                run_root,
                current_report_id,
                int(command_result.get("rc") or 0),
                max_reached=loop_index >= args.max_loops,
                contract_smoke_mode=(
                    args.allow_legacy_research_protocol_smoke
                ),
            )
        wrapper_proof_path = (
            ctx.runtime_context_root
            / f"ultimate_run_report__{current_report_id}.json"
        )
        wrapper_proof = load_json_if_exists(wrapper_proof_path)
        iteration = {
            "loop_index": loop_index,
            "report_id": current_report_id,
            "parent_report_id": current_parent_report_id,
            "start_step": current_start_step,
            "wrapper_command": public_command_result(
                command_result,
                denied_values=host_private_proof_values,
            ),
            "wrapper_proof_path": str(wrapper_proof_path),
            "terminal_protocol_validated": (
                terminal_protocol_validated_from_wrapper(wrapper_proof)
            ),
            **state,
            "forbidden_side_effects": forbidden_changes,
        }
        proof.setdefault("iterations", []).append(iteration)
        proof["updated_at_utc"] = utc_now()
        write_json_atomic(proof_path, proof)

        if (
            state.get("outcome") in {"awaiting_agent_results", "exhausted"}
            and multibranch_synthesis_bridge_ready(run_root, current_report_id)
        ):
            if loop_index >= args.max_loops:
                return finalize_budget_exhaustion(
                    proof=proof,
                    iteration=iteration,
                    proof_path=proof_path,
                    brief_path=brief_path,
                    factorforge_root=run_root,
                    report_id=current_report_id,
                )

            if not multibranch_manual_approval_ready(
                run_root, current_report_id
            ):
                iteration["outcome"] = "WAITING_EXTERNAL_HUMAN_APPROVAL"
                iteration["stop_reason"] = "external_human_approval_receipt_required"
                iteration["proof_status"] = "PAUSED"
                iteration["human_approval_boundary"] = {
                    "status": "WAITING_EXTERNAL_HUMAN_APPROVAL",
                    "automatic_approval_allowed": False,
                    "required_action": (
                        "An external human must sign the selected multibranch synthesis "
                        "and fresh sealed OOS child intents before materialization."
                    ),
                }
                proof["status"] = "PAUSED"
                proof["final_outcome"] = "WAITING_EXTERNAL_HUMAN_APPROVAL"
                proof["stop_reason"] = "external_human_approval_receipt_required"
                proof["updated_at_utc"] = utc_now()
                append_note(
                    proof,
                    f"Completed multibranch synthesis for {current_report_id}; waiting for external human approval",
                )
                attach_paused_note_if_needed(
                    factorforge_root=run_root,
                    report_id=current_report_id,
                    proof=proof,
                    iteration=iteration,
                    pause_state="WAITING_EXTERNAL_HUMAN_APPROVAL",
                    reason="external_human_approval_receipt_required",
                )
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("WAITING_EXTERNAL_HUMAN_APPROVAL")
                return 0

            materialize_env = env.copy()
            materialize_env["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
            materialize_cmd = multibranch_materialization_command(
                current_report_id,
                run_root,
                loop_index,
                expected_host_trust_manifest_sha256=getattr(
                    args,
                    "expected_host_trust_manifest_sha256",
                    None,
                ),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                allow_legacy_incident_context_smoke=bool(
                    args.allow_legacy_research_protocol_smoke
                ),
            )
            materialize_result = run_command(materialize_cmd, env=materialize_env, dry_run=args.dry_run)
            materialization_path = multibranch_materialization_report_path(run_root, current_report_id, loop_index)
            materialization = load_json_if_exists(materialization_path)
            children = materialization.get("children") if isinstance(materialization.get("children"), list) else []
            iteration["multibranch_materialization_command"] = (
                public_command_result(
                    materialize_result,
                    denied_values=host_private_proof_values,
                )
            )
            iteration["multibranch_materialization_rc"] = materialize_result.get("rc")
            iteration["multibranch_materialization_report_path"] = str(materialization_path)
            iteration["multibranch_child_count"] = len(children)
            if materialize_result.get("rc") != 0:
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_MATERIALIZATION_FAILED"
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_MATERIALIZATION_FAILED")
                return 1

            protected_ancestors = list(dict.fromkeys([*ancestor_report_ids, current_report_id]))
            multibranch_ancestor_before = ancestor_generated_code_snapshots(run_root, protected_ancestors)
            child_report_ids = [str(child.get("child_report_id") or "") for child in children if isinstance(child, dict)]
            child_control_before = child_control_artifact_snapshots(run_root, child_report_ids)
            iteration["multibranch_child_control_artifact_before"] = child_control_before
            child_runs: list[dict[str, Any]] = []
            for child in children:
                child_report_id = str(child.get("child_report_id") or "")
                child_command = ultimate_command(args, child_report_id, "3b", run_root)
                child_result = run_command(child_command, env=env, dry_run=args.dry_run)
                child_runs.append(
                    {
                        "child_report_id": child_report_id,
                        "branch_role": child.get("branch_role"),
                        "branch_index": child.get("branch_index"),
                        "law_id": child.get("law_id"),
                        "wrapper_command": public_command_result(
                            child_result,
                            denied_values=host_private_proof_values,
                        ),
                        "wrapper_proof_path": str(ctx.runtime_context_root / f"ultimate_run_report__{child_report_id}.json"),
                    }
                )
                if child_result.get("rc") != 0:
                    iteration["multibranch_child_wrapper_runs"] = child_runs
                    proof["status"] = "FAIL"
                    proof["final_outcome"] = "blocked"
                    proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_WRAPPER_FAILED"
                    proof["updated_at_utc"] = utc_now()
                    write_json_atomic(proof_path, proof)
                    write_aggregate_brief(brief_path, proof, run_root)
                    print("BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_WRAPPER_FAILED")
                    return 1
            iteration["multibranch_child_wrapper_runs"] = child_runs

            multibranch_forbidden_changes = []
            multibranch_ancestor_changes = changed_ancestor_snapshots(run_root, multibranch_ancestor_before)
            if multibranch_ancestor_changes:
                multibranch_forbidden_changes.append({"kind": "parent_generated_code_mutation", "changes": multibranch_ancestor_changes})
            data_clean_after_multibranch = path_snapshot(ctx.clean_data_root)
            if snapshots_differ(data_clean_before, data_clean_after_multibranch):
                multibranch_forbidden_changes.append({"kind": "data_clean_mutation", "before": data_clean_before, "after": data_clean_after_multibranch})
            if multibranch_forbidden_changes:
                iteration.setdefault("forbidden_side_effects", []).extend(multibranch_forbidden_changes)
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT"
                proof.setdefault("canonical_side_effects", []).extend(multibranch_forbidden_changes)
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT")
                return 1

            selection = select_multibranch_child(run_root, children)
            iteration["multibranch_selection"] = selection
            if selection.get("ok") is not True:
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = selection.get("block_reason")
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print(selection.get("block_reason"))
                return 1

            selected_child_report_id = str(selection["selected_child_report_id"])
            child_control_changes = changed_child_control_artifacts(run_root, child_control_before, selected_child_report_id)
            iteration["multibranch_child_control_artifact_changes"] = child_control_changes
            if child_control_changes:
                iteration.setdefault("forbidden_side_effects", []).extend(child_control_changes)
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_CONTROL_ARTIFACT"
                proof.setdefault("canonical_side_effects", []).extend(child_control_changes)
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_MULTIBRANCH_CHILD_CONTROL_ARTIFACT")
                return 1

            comparison_cmd = branch_comparison_command(
                current_report_id,
                selected_child_report_id,
                run_root,
                loop_index,
                why="Selected by the production loop branch comparison from executed child evidence.",
                learned="Sibling branch metrics are retained as sibling_branch_memory for the selected child Council packet.",
            )
            comparison_result = run_command(comparison_cmd, env=env, dry_run=args.dry_run)
            comparison_path = branch_comparison_path(run_root, current_report_id, loop_index)
            iteration["branch_comparison_command"] = public_command_result(
                comparison_result,
                denied_values=host_private_proof_values,
            )
            iteration["branch_comparison_rc"] = comparison_result.get("rc")
            iteration["branch_comparison_path"] = str(comparison_path)
            iteration["selected_next_parent_child_report_id"] = selected_child_report_id
            if comparison_result.get("rc") != 0:
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_BRANCH_COMPARISON_FAILED"
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_BRANCH_COMPARISON_FAILED")
                return 1

            append_note(proof, f"Executed multibranch children for {current_report_id}; selected {selected_child_report_id}")
            write_json_atomic(proof_path, proof)

            ancestor_report_ids.append(current_report_id)
            current_parent_report_id = current_report_id
            current_report_id = selected_child_report_id
            current_start_step = "6"
            continue

        if (
            state.get("outcome") in {"awaiting_agent_results", "exhausted"}
            and synthesis_bridge_ready(run_root, current_report_id)
        ):
            iteration["outcome"] = "WAITING_EXTERNAL_HUMAN_APPROVAL"
            iteration["stop_reason"] = "external_human_approval_receipt_required"
            iteration["proof_status"] = "PAUSED"
            iteration["human_approval_boundary"] = {
                "status": "WAITING_EXTERNAL_HUMAN_APPROVAL",
                "automatic_approval_allowed": False,
                "required_receipt_contract": "factorforge_external_human_approval_receipt_v3",
                "required_bindings": [
                    "report_id",
                    "run_id",
                    "synthesis_sha256",
                    "selected_law",
                    "mechanism_delta",
                    "economic_backprojection",
                    "fresh_oos_child_intent",
                ],
            }
            proof["status"] = "PAUSED"
            proof["final_outcome"] = "WAITING_EXTERNAL_HUMAN_APPROVAL"
            proof["stop_reason"] = "external_human_approval_receipt_required"
            proof["updated_at_utc"] = utc_now()
            append_note(
                proof,
                f"Completed Council synthesis for {current_report_id}; waiting for external human approval",
            )
            attach_paused_note_if_needed(
                factorforge_root=run_root,
                report_id=current_report_id,
                proof=proof,
                iteration=iteration,
                pause_state="WAITING_EXTERNAL_HUMAN_APPROVAL",
                reason="external_human_approval_receipt_required",
            )
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, run_root)
            print("WAITING_EXTERNAL_HUMAN_APPROVAL")
            return 0

        if (
            state.get("outcome") in {"awaiting_agent_results", "exhausted"}
            and not synthesis_bridge_ready(run_root, current_report_id)
            and terminal_rejection_bridge_ready(run_root, current_report_id)
        ):
            terminal_cmd = terminal_rejection_command(current_report_id, run_root, loop_index, args.max_loops)
            terminal_result = run_command(terminal_cmd, env=env, dry_run=args.dry_run)
            iteration["terminal_reject_bridge_command"] = public_command_result(
                terminal_result,
                denied_values=host_private_proof_values,
            )
            iteration["terminal_reject_bridge_rc"] = terminal_result.get("rc")
            terminal_text = f"{terminal_result.get('stdout_tail') or ''}\n{terminal_result.get('stderr_tail') or ''}"
            terminal_state = classify_terminal_rejection_result(
                returncode=int(terminal_result.get("rc") or 0),
                output=terminal_text,
                branch_falsification_exists=branch_falsification_path(
                    run_root,
                    current_report_id,
                ).is_file(),
            )
            if terminal_state != "closed":
                if terminal_state == "awaiting_next_derivation":
                    branch_path = branch_falsification_path(run_root, current_report_id)
                    questionnaire_path = next_derivation_questionnaire_path(run_root, current_report_id)
                    iteration["branch_falsification_path"] = str(branch_path)
                    iteration["next_derivation_questionnaire_path"] = str(questionnaire_path)
                    iteration["outcome"] = "awaiting_next_derivation"
                    iteration["stop_reason"] = "revision_branch_falsified_next_derivation_required"
                    iteration["proof_status"] = "PAUSED"
                    proof["status"] = "PAUSED"
                    proof["final_outcome"] = "awaiting_next_derivation"
                    proof["stop_reason"] = "revision_branch_falsified_next_derivation_required"
                    proof["next_derivation_questionnaire_path"] = str(questionnaire_path)
                    proof["updated_at_utc"] = utc_now()
                    append_note(proof, f"Recorded branch falsification for {current_report_id}; next math-mechanism derivation required")
                    attach_paused_note_if_needed(
                        factorforge_root=run_root,
                        report_id=current_report_id,
                        proof=proof,
                        iteration=iteration,
                        pause_state="awaiting_next_derivation",
                        reason="revision_branch_falsified_next_derivation_required",
                    )
                    write_json_atomic(proof_path, proof)
                    write_aggregate_brief(brief_path, proof, run_root)
                    print("awaiting_next_derivation")
                    return 0
                if terminal_state == "awaiting_main_agent_council_synthesis":
                    iteration["outcome"] = "awaiting_main_agent_council_synthesis"
                    iteration["stop_reason"] = "completed_council_requires_main_agent_synthesis"
                    iteration["proof_status"] = "PAUSED"
                    proof["status"] = "PAUSED"
                    proof["final_outcome"] = "awaiting_main_agent_council_synthesis"
                    proof["stop_reason"] = "completed_council_requires_main_agent_synthesis"
                    proof["updated_at_utc"] = utc_now()
                    append_note(proof, f"Completed Council for {current_report_id} requires main-agent synthesis before child materialization")
                    attach_paused_note_if_needed(
                        factorforge_root=run_root,
                        report_id=current_report_id,
                        proof=proof,
                        iteration=iteration,
                        pause_state="awaiting_main_agent_council_synthesis",
                        reason="completed_council_requires_main_agent_synthesis",
                    )
                    write_json_atomic(proof_path, proof)
                    write_aggregate_brief(brief_path, proof, run_root)
                    print("awaiting_main_agent_council_synthesis")
                    return 0
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_TERMINAL_COUNCIL_REJECTION_FAILED"
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_TERMINAL_COUNCIL_REJECTION_FAILED")
                return 1
            final_protocol_result = run_command(
                final_protocol_validation_command(
                    current_report_id,
                    run_root,
                ),
                env=env,
                dry_run=args.dry_run,
            )
            iteration["final_protocol_validation_command"] = (
                public_command_result(
                    final_protocol_result,
                    denied_values=host_private_proof_values,
                )
            )
            if final_protocol_result.get("rc") != 0:
                proof["status"] = "FAIL"
                proof["final_outcome"] = "blocked"
                proof["stop_reason"] = (
                    "BLOCK_FACTORFORGE_LOOP_FINAL_PROTOCOL_VALIDATION_FAILED"
                )
                proof["updated_at_utc"] = utc_now()
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("BLOCK_FACTORFORGE_LOOP_FINAL_PROTOCOL_VALIDATION_FAILED")
                return 1
            iteration["terminal_protocol_validated"] = True
            state = classify_loop_state(
                run_root,
                current_report_id,
                int(command_result.get("rc") or 0),
                max_reached=loop_index >= args.max_loops,
                contract_smoke_mode=(
                    args.allow_legacy_research_protocol_smoke
                ),
            )
            iteration.update(state)
            proof["updated_at_utc"] = utc_now()
            append_note(proof, f"Closed terminal agentic Council rejection for {current_report_id}")
            write_json_atomic(proof_path, proof)

        if forbidden_changes:
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT"
            proof.setdefault("canonical_side_effects", []).extend(forbidden_changes)
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, run_root)
            print("BLOCK_FACTORFORGE_LOOP_FORBIDDEN_SIDE_EFFECT")
            return 1

        if not state.get("can_continue"):
            if state.get("outcome") == "max_loops_reached":
                return finalize_budget_exhaustion(
                    proof=proof,
                    iteration=iteration,
                    proof_path=proof_path,
                    brief_path=brief_path,
                    factorforge_root=run_root,
                    report_id=current_report_id,
                )
            proof["status"] = state.get("proof_status")
            terminal_rejection_closed = (
                run_root
                / "objects"
                / "research_iteration_master"
                / "revision_council"
                / current_report_id
                / f"terminal_council_rejection__{current_report_id}.json"
            ).is_file()
            if (
                terminal_rejection_closed
                and iteration.get("terminal_protocol_validated") is True
                and "final_protocol_validation_command" not in iteration
            ):
                raw_final_protocol_result = run_command(
                    final_protocol_validation_command(
                        current_report_id,
                        run_root,
                    ),
                    env=env,
                    dry_run=args.dry_run,
                )
                iteration["raw_terminal_protocol_revalidation_command"] = (
                    public_command_result(
                        raw_final_protocol_result,
                        denied_values=host_private_proof_values,
                    )
                )
                if raw_final_protocol_result.get("rc") != 0:
                    proof["status"] = "FAIL"
                    proof["formal_proof_eligible"] = False
                    proof["final_outcome"] = "blocked"
                    proof["stop_reason"] = (
                        "BLOCK_FACTORFORGE_LOOP_FINAL_PROTOCOL_VALIDATION_FAILED"
                    )
                    proof["updated_at_utc"] = utc_now()
                    write_json_atomic(proof_path, proof)
                    write_aggregate_brief(brief_path, proof, run_root)
                    print("BLOCK_FACTORFORGE_LOOP_FINAL_PROTOCOL_VALIDATION_FAILED")
                    return 1
            proof["formal_proof_eligible"] = bool(
                proof["status"] == "PASS"
                and not args.dry_run
                and not args.allow_legacy_research_protocol_smoke
                and (
                    not terminal_rejection_closed
                    or iteration.get("terminal_protocol_validated") is True
                )
            )
            proof["terminal_protocol_validated"] = bool(
                terminal_rejection_closed
                and iteration.get("terminal_protocol_validated") is True
            )
            proof["final_outcome"] = state.get("outcome")
            proof["stop_reason"] = state.get("stop_reason")
            attach_paused_note_if_needed(
                factorforge_root=run_root,
                report_id=current_report_id,
                proof=proof,
                iteration=iteration,
                pause_state=str(state.get("outcome") or ""),
                reason=str(state.get("stop_reason") or ""),
            )
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, run_root)
            print(proof["final_outcome"])
            return (
                0
                if proof["status"] in {"PASS", "PAUSED", "DRY_RUN"}
                else 1
            )

        if loop_index >= args.max_loops:
            return finalize_budget_exhaustion(
                proof=proof,
                iteration=iteration,
                proof_path=proof_path,
                brief_path=brief_path,
                factorforge_root=run_root,
                report_id=current_report_id,
            )

        child = approved_child_revision_from_handoff(run_root, current_report_id, loop_index)
        if not child.get("ok"):
            iteration["child_revision_error"] = child
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = child.get("block_reason")
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, run_root)
            print(child.get("block_reason"))
            return 1

        iteration["child_revision_source"] = "handoff_to_step3b"
        iteration["selected_revision_id"] = child.get("revision_id")
        iteration["child_report_id"] = child.get("child_report_id")
        report_path = materialization_report_path(run_root, current_report_id, str(child["child_report_id"]))
        materialization_existed_before = report_path.is_file() and not report_path.is_symlink()
        materialize_cmd = materialization_command(
            current_report_id,
            str(child["child_report_id"]),
            run_root,
            expected_host_trust_manifest_sha256=(
                getattr(args, "expected_host_trust_manifest_sha256", None)
            ),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
        )
        # Never authorize reuse from the loop's structural readback alone.  The
        # canonical materializer performs preregistration/OOS freshness replay
        # and the idempotent report readback while its incident registry guard
        # is the outermost lock.
        materialize_result = run_command(
            materialize_cmd,
            env=env,
            dry_run=args.dry_run,
        )
        materialization_report = load_json_if_exists(report_path)
        iteration["materialization_command"] = public_command_result(
            materialize_result,
            denied_values=host_private_proof_values,
        )
        iteration["materialization_rc"] = materialize_result.get("rc")
        iteration["materialization_reused"] = bool(
            materialization_existed_before
            and materialize_result.get("rc") == 0
        )
        iteration["materialization_report_path"] = str(report_path)
        iteration["materialized_artifact_paths"] = materialization_report.get("materialized_artifacts") or {}
        if iteration["materialization_reused"]:
            append_note(
                proof,
                f"Current-authority replay accepted existing child materialization for {child.get('child_report_id')}",
            )
        if materialize_result.get("rc") != 0:
            materialize_text = (
                f"{materialize_result.get('stdout_tail') or ''}\n"
                f"{materialize_result.get('stderr_tail') or ''}"
            )
            if "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION" in materialize_text:
                iteration["outcome"] = "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION"
                iteration["proof_status"] = "PAUSED"
                iteration["stop_reason"] = "fresh_sealed_oos_allocation_or_child_preregistration_required"
                proof["status"] = "PAUSED"
                proof["final_outcome"] = "WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION"
                proof["stop_reason"] = "fresh_sealed_oos_allocation_or_child_preregistration_required"
                proof["updated_at_utc"] = utc_now()
                attach_paused_note_if_needed(
                    factorforge_root=run_root,
                    report_id=current_report_id,
                    proof=proof,
                    iteration=iteration,
                    pause_state="WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION",
                    reason="fresh_sealed_oos_allocation_or_child_preregistration_required",
                )
                write_json_atomic(proof_path, proof)
                write_aggregate_brief(brief_path, proof, run_root)
                print("WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION")
                return 0
            proof["status"] = "FAIL"
            proof["final_outcome"] = "blocked"
            proof["stop_reason"] = "BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED"
            write_json_atomic(proof_path, proof)
            write_aggregate_brief(brief_path, proof, run_root)
            print("BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED")
            return 1
        append_note(proof, f"Continuing to child loop report {child.get('child_report_id')}")
        write_json_atomic(proof_path, proof)

        ancestor_report_ids.append(current_report_id)
        current_parent_report_id = current_report_id
        current_report_id = str(child["child_report_id"])
        current_start_step = "3b"

    return finalize_budget_exhaustion(
        proof=proof,
        iteration=(proof.get("iterations") or [None])[-1],
        proof_path=proof_path,
        brief_path=brief_path,
        factorforge_root=run_root,
        report_id=current_report_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
