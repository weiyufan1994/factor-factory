from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DISPATCH_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
TASK_PACKET_VERSION = "factorforge_agentic_council_task_packet_v1"
BLOCK_COUNCIL_INGRESS_INVALID = "BLOCK_FACTORFORGE_CONSOLE_COUNCIL_INGRESS_INVALID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,180}$")


@dataclass(frozen=True)
class CouncilIngressTask:
    task_id: str
    agent_role: str
    expected_agent_identifier: str
    task_packet_path: str
    task_packet_sha256: str
    expected_result_path: str


def load_council_ingress_tasks(
    workspace: Path,
    report_id: str,
    *,
    require_results_absent: bool = True,
) -> tuple[CouncilIngressTask, ...]:
    root = workspace.resolve(strict=True)
    if not _SAFE_ID.fullmatch(report_id):
        _block("report identity is unsafe")
    council_relative = (
        Path("objects")
        / "research_iteration_master"
        / "revision_council"
        / report_id
    )
    council_root = _resolve_existing_directory(root, council_relative)
    manifest_path = _resolve_existing_file(
        root,
        council_relative / f"dispatch_manifest__{report_id}.json",
    )
    manifest = _read_json(manifest_path, label="dispatch manifest")
    raw_tasks = manifest.get("agent_tasks")
    if (
        manifest.get("dispatch_manifest_version") != DISPATCH_VERSION
        or manifest.get("report_id") != report_id
        or manifest.get("status") != "awaiting_agent_results"
        or not isinstance(raw_tasks, list)
        or not 1 <= len(raw_tasks) <= 16
        or manifest.get("agent_task_count") != len(raw_tasks)
    ):
        _block("dispatch manifest contract is invalid")

    task_root = _resolve_existing_directory(root, council_relative / "agent_tasks")
    result_root = council_root / "agent_results"
    if result_root.is_symlink():
        _block("Council result directory uses a symlink")
    if result_root.exists():
        if not result_root.is_dir() or result_root.resolve(strict=True).parent != council_root:
            _block("Council result directory is unsafe")
        resolved_result_root = result_root.resolve(strict=True)
    else:
        resolved_result_root = result_root

    output: list[CouncilIngressTask] = []
    seen_task_ids: set[str] = set()
    seen_agent_ids: set[str] = set()
    for raw in raw_tasks:
        if not isinstance(raw, dict) or raw.get("required") is not True:
            _block("every Console Council task must be required")
        task_id = str(raw.get("task_id") or "")
        agent_role = str(raw.get("agent_role") or "")
        declared_agent_identifier = raw.get("expected_agent_identifier")
        expected_agent_identifier = str(
            declared_agent_identifier or f"console_council_{task_id}"
        )
        if (
            not _SAFE_ID.fullmatch(task_id)
            or not _SAFE_ID.fullmatch(agent_role)
            or not _SAFE_ID.fullmatch(expected_agent_identifier)
            or task_id in seen_task_ids
            or expected_agent_identifier in seen_agent_ids
        ):
            _block("Council task identity is invalid or not independent")
        seen_task_ids.add(task_id)
        seen_agent_ids.add(expected_agent_identifier)

        expected_packet_relative = (
            council_relative / "agent_tasks" / f"task__{report_id}__{task_id}.json"
        )
        expected_result_relative = (
            council_relative
            / "agent_results"
            / f"agent_result__{report_id}__{task_id}.json"
        )
        if (
            raw.get("task_packet_path") != expected_packet_relative.as_posix()
            or raw.get("expected_result_path") != expected_result_relative.as_posix()
        ):
            _block("Council task paths do not match their immutable identities")
        packet_path = _resolve_existing_file(root, expected_packet_relative)
        if packet_path.parent != task_root:
            _block("Council task packet escapes its task directory")
        packet_sha256 = _sha256(packet_path)
        if raw.get("task_packet_sha256") != packet_sha256:
            _block("Council task packet hash does not match dispatch")
        packet = _read_json(packet_path, label="Council task packet")
        if (
            packet.get("task_packet_version") != TASK_PACKET_VERSION
            or packet.get("report_id") != report_id
            or packet.get("task_id") != task_id
            or packet.get("agent_role") != agent_role
            or (
                declared_agent_identifier is not None
                and packet.get("expected_agent_identifier")
                != expected_agent_identifier
            )
            or packet.get("expected_result_path") != expected_result_relative.as_posix()
            or packet.get("canonical_write_permission") is not False
            or packet.get("execution_allowed_by_default") is not False
            or packet.get("human_approval_required") is not True
        ):
            _block("Council task packet identity or permission contract is invalid")
        result_path = root / expected_result_relative
        if result_path.is_symlink():
            _block("Council result path uses a symlink")
        if result_path.exists():
            if require_results_absent:
                _block("Council result path already exists before isolated ingress")
            resolved_result = result_path.resolve(strict=True)
            if (
                not resolved_result.is_file()
                or resolved_result.parent != resolved_result_root
            ):
                _block("Council result path is unsafe")
        elif result_path.parent != result_root:
            _block("Council result parent escapes the result directory")
        output.append(
            CouncilIngressTask(
                task_id=task_id,
                agent_role=agent_role,
                expected_agent_identifier=expected_agent_identifier,
                task_packet_path=expected_packet_relative.as_posix(),
                task_packet_sha256=packet_sha256,
                expected_result_path=expected_result_relative.as_posix(),
            )
        )
    return tuple(output)


def build_council_task_prompt(
    *,
    workspace: Path,
    report_id: str,
    task: CouncilIngressTask,
    private_output_path: Path,
) -> str:
    packet_path = workspace / task.task_packet_path
    result_path = private_output_path
    return f"""You are one independent Factor Forge revision-Council researcher.

Read only this immutable task packet:
{packet_path}

Write exactly one JSON result and no other workspace file:
{result_path}

The Host will validate and atomically import that private result to the dispatch-
bound workspace path after every independent route finishes. Do not attempt to
write the workspace result path yourself.

Identity is fixed:
- report_id: {report_id}
- task_id: {task.task_id}
- agent_role: {task.agent_role}
- agent_identifier: {task.expected_agent_identifier}
- source_task_packet_sha256: {task.task_packet_sha256}

The output must be a substantive final
`factorforge_agentic_revision_council_result_v1` with producer `real_agent`,
research_depth `high`, proposal_generation_mode `agentic`, status `final`,
canonical_write_permission=false, execution_allowed_by_default=false, and
human_approval_required=true. Bind dispatch_identity exactly to the packet.
Populate every key listed in `required_outputs`; do not use placeholders.
`public_derivation_record` must include assumptions, mathematical objects,
selected tools, formula claims, derivation steps, at least two limiting cases,
at least two falsification tests, at least two kill criteria, and an overclaim
guard. Each candidate revision law needs expected metric changes, falsifiers,
kill criteria, and why it is not a portfolio-wrapper fix.

Honor the packet's blind-context policy. Do not read another Council task,
another result, a withheld favored thesis, credentials, environment variables,
network resources, raw data, or validator source. Do not execute research or
modify code, canonical knowledge, clean data, handoffs, or official records.
Your result is advisory evidence only and must not claim human approval.
"""


def _resolve_existing_directory(root: Path, relative: Path) -> Path:
    path = _safe_relative_path(root, relative)
    if path.is_symlink() or not path.is_dir():
        _block(f"required directory is unsafe: {relative.as_posix()}")
    return path.resolve(strict=True)


def _resolve_existing_file(root: Path, relative: Path) -> Path:
    path = _safe_relative_path(root, relative)
    if path.is_symlink() or not path.is_file():
        _block(f"required file is unsafe: {relative.as_posix()}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _block(f"file escapes workspace: {relative.as_posix()}")
    return resolved


def _safe_relative_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        _block("absolute or parent-relative Council path is forbidden")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _block(f"Council path uses a symlink: {relative.as_posix()}")
    return current


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{BLOCK_COUNCIL_INGRESS_INVALID}: {label} is invalid") from exc
    if not isinstance(payload, dict):
        _block(f"{label} must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _block(detail: str) -> None:
    raise RuntimeError(f"{BLOCK_COUNCIL_INGRESS_INVALID}: {detail}")
