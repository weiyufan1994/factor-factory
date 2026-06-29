from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


VALID_VERDICTS = {"ACCEPT", "BLOCK", "PARTIAL", "UNKNOWN"}
TASK_CONTRACT_VERSION = "factorforge_console_task_v1"
RESULT_CONTRACT_VERSION = "factorforge_console_result_v1"


def _require_verdict(verdict: str) -> str:
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict!r}")
    return verdict


def _require_contract(actual: str, expected: str) -> str:
    if actual != expected:
        raise ValueError(f"contract_version must be {expected}")
    return actual


@dataclass
class CampaignSummary:
    campaign_id: str
    workspace_root: str
    verdict: str
    candidate_count: int
    cheap_screen_passed: int
    research_queue_count: int
    data_gap_count: int
    data_request_count: int
    template_status_counts: dict[str, int]
    artifact_paths: dict[str, str]
    blockers: list[str]
    next_actions: list[str]
    boundary_statement: str

    def __post_init__(self) -> None:
        self.verdict = _require_verdict(self.verdict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CampaignSummary":
        return cls(
            campaign_id=str(payload.get("campaign_id", "")),
            workspace_root=str(payload.get("workspace_root", "")),
            verdict=str(payload.get("verdict", "UNKNOWN")),
            candidate_count=int(payload.get("candidate_count", 0)),
            cheap_screen_passed=int(payload.get("cheap_screen_passed", 0)),
            research_queue_count=int(payload.get("research_queue_count", 0)),
            data_gap_count=int(payload.get("data_gap_count", 0)),
            data_request_count=int(payload.get("data_request_count", 0)),
            template_status_counts=dict(payload.get("template_status_counts", {})),
            artifact_paths=dict(payload.get("artifact_paths", {})),
            blockers=list(payload.get("blockers", [])),
            next_actions=list(payload.get("next_actions", [])),
            boundary_statement=str(payload.get("boundary_statement", "")),
        )


@dataclass
class ConsoleTask:
    contract_version: str
    task_id: str
    task_type: str
    repo_root: str
    execution_workspace: str
    campaign_id: str
    workspace_root: str
    inputs: dict[str, Any]
    steps: list[str]
    boundaries: dict[str, Any]
    expected_outputs: list[str]

    def __post_init__(self) -> None:
        self.contract_version = _require_contract(self.contract_version, TASK_CONTRACT_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConsoleTask":
        return cls(
            contract_version=str(payload.get("contract_version", "")),
            task_id=str(payload.get("task_id", "")),
            task_type=str(payload.get("task_type", "")),
            repo_root=str(payload.get("repo_root", "")),
            execution_workspace=str(payload.get("execution_workspace", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            workspace_root=str(payload.get("workspace_root", "")),
            inputs=dict(payload.get("inputs", {})),
            steps=list(payload.get("steps", [])),
            boundaries=dict(payload.get("boundaries", {})),
            expected_outputs=list(payload.get("expected_outputs", [])),
        )


@dataclass
class ConsoleResult:
    contract_version: str
    task_id: str
    run_id: str
    status: str
    verdict: str
    metrics: dict[str, Any]
    artifact_paths: dict[str, str]
    blockers: list[str]
    next_actions: list[str]
    boundaries_observed: dict[str, Any]

    def __post_init__(self) -> None:
        self.contract_version = _require_contract(self.contract_version, RESULT_CONTRACT_VERSION)
        self.verdict = _require_verdict(self.verdict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConsoleResult":
        return cls(
            contract_version=str(payload.get("contract_version", "")),
            task_id=str(payload.get("task_id", "")),
            run_id=str(payload.get("run_id", "")),
            status=str(payload.get("status", "")),
            verdict=str(payload.get("verdict", "UNKNOWN")),
            metrics=dict(payload.get("metrics", {})),
            artifact_paths=dict(payload.get("artifact_paths", {})),
            blockers=list(payload.get("blockers", [])),
            next_actions=list(payload.get("next_actions", [])),
            boundaries_observed=dict(payload.get("boundaries_observed", {})),
        )
