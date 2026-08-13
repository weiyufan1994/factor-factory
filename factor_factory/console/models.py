from __future__ import annotations

from dataclasses import asdict, dataclass, field
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlsplit


VALID_VERDICTS = {"ACCEPT", "REJECT", "ITERATE", "BLOCK", "PARTIAL", "UNKNOWN"}
VALID_EXECUTION_STATUSES = {
    "QUEUED",
    "ALLOCATING",
    "RESEARCHING",
    "VERIFYING",
    "REVIEW_REQUIRED",
    "COMPLETED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
}
VALID_PROTOCOL_STATUSES = {
    "NOT_STARTED",
    "RUNNING",
    "PAUSED",
    "PASS",
    "BLOCK",
    "BLOCKED",
    "FAIL",
    "FAILED",
    "UNKNOWN",
}
VALID_COUNCIL_STATUSES = {
    "NOT_STARTED",
    "RUNNING",
    "PAUSED",
    "PASS",
    "BLOCK",
    "BLOCKED",
    "REJECTED",
    "NOT_REQUIRED",
    "UNKNOWN",
}
TASK_CONTRACT_VERSION = "factorforge_console_task_v1"
RESULT_CONTRACT_VERSION = "factorforge_console_result_v1"
RESEARCH_REQUEST_VERSION = "factorforge_console_research_request_v1"
PILOT_FORWARD_HORIZON = "1d"
PILOT_TRANSACTION_COST_BPS = 30.0
PILOT_COST_MODEL_ID = "factorforge_step4_turnover_30bps_v1"
PILOT_UNIVERSE = "a_share_all"
PILOT_MODEL = "deepseek-v4-flash"
RESEARCH_SCOPE_FULL_FORMAL = "full_formal"
RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY = "preformal_design_only"
VALID_RESEARCH_SCOPES = {
    RESEARCH_SCOPE_FULL_FORMAL,
    RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
}
RESEARCH_JOB_VERSION = "factorforge_console_research_job_v1"
RESEARCH_MESSAGE_VERSION = "factorforge_console_research_message_v1"
VALID_MESSAGE_ROLES = {"user"}
USER_MESSAGE_CONTENT_KINDS = {"hypothesis", "report", "formula", "code", "decision"}
INTERNAL_MESSAGE_CONTENT_KINDS = {"formula_contract"}
VALID_MESSAGE_CONTENT_KINDS = USER_MESSAGE_CONTENT_KINDS | INTERNAL_MESSAGE_CONTENT_KINDS
HOST_PRIVATE_PUBLIC_REDACTION = "[HOST_PRIVATE]"

# ResearchJob.result is also the private continuation state for EVO V2.  It is
# intentionally persisted verbatim, but the authenticated HTTP API must not
# expose Host control-plane coordinates embedded in that state.  Keep this
# deny-list close to the public model projection so a new API caller cannot
# accidentally bypass it.
_HOST_PRIVATE_RESULT_FIELDS = frozenset(
    {
        "adapter_id",
        "admission_path",
        "assurance_path",
        "calendar_snapshot_path",
        "calendar_projection_path",
        "catalog_snapshot_path",
        "catalog_projection_path",
        "checkpoint_path",
        "completion_journal_path",
        "container_admission_path",
        "container_name",
        "container_state_root",
        "cwd",
        "denied_private_roots",
        "execution_receipt_path",
        "engine_root",
        "host_installation_id",
        "host_trust_root",
        "incident_installation_id",
        "incident_trust_root",
        "installation_id",
        "launch_journal_path",
        "phase_receipt_path",
        "phase_inflight_path",
        "phase_receipt_candidate_path",
        "private_attempt_root",
        "private_root",
        "qualification_receipt_path",
        "recovery_admission_path",
        "research_org_runtime_installation_id",
        "research_org_runtime_private_root",
        "research_org_runtime_trust_root",
        "sealed_oos_carrier",
        "sealed_oos_carrier_path",
        "sealed_oos_private_root",
        "state_root",
        "trust_root",
        "worktree",
        "worktree_path",
        "workspace_path",
    }
)
_HOST_PRIVATE_RESULT_FIELD_SUFFIXES = (
    "_admission_path",
    "_assurance_path",
    "_carrier_path",
    "_checkpoint_path",
    "_journal_path",
    "_private_root",
    "_receipt_path",
    "_state_root",
    "_trust_root",
)
_HOST_PRIVATE_REFERENCE_CONTEXT_TOKENS = (
    "admission",
    "assurance",
    "carrier",
    "checkpoint",
    "container_termination",
    "host_control",
    "private_locator",
    "receipt",
)
_HOST_PRIVATE_ARGV_OPTIONS = frozenset(
    {
        "--agent-execution-container-admission",
        "--agent-execution-sandbox-admission",
        "--evo-child-command-recovery-admission",
        "--evo-child-finalizer-recovery-admission",
        "--evo-child-research-org-assurance",
        "--factor-workspace",
        "--factorforge-root",
        "--host-installation-id",
        "--host-trust-root",
        "--incident-installation-id",
        "--incident-trust-root",
        "--installation-id",
        "--private-root",
        "--research-org-runtime-installation-id",
        "--research-org-runtime-private-root",
        "--research-org-runtime-trust-root",
        "--sealed-oos-agent-visible-root",
        "--sealed-oos-carrier",
        "--sealed-oos-private-root",
        "--state-root",
        "--trust-root",
    }
)
_MESSAGE_SECRET_PATTERN = re.compile(
    r"(?is)(?:"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*[^\s,;]{8,}"
    r")"
)


def _normalized_public_field_name(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def _is_host_private_result_field(
    key: object,
    *,
    private_reference_context: bool = False,
) -> bool:
    normalized = _normalized_public_field_name(key)
    if normalized in _HOST_PRIVATE_RESULT_FIELDS:
        return True
    if normalized.endswith(_HOST_PRIVATE_RESULT_FIELD_SUFFIXES):
        return True
    return bool(
        private_reference_context and normalized in {"path", "root"}
    )


def _is_host_private_reference_context(key: object) -> bool:
    normalized = _normalized_public_field_name(key)
    return any(
        token in normalized for token in _HOST_PRIVATE_REFERENCE_CONTEXT_TOKENS
    )


def _is_argv_field(key: object) -> bool:
    normalized = _normalized_public_field_name(key)
    return normalized == "argv" or normalized.endswith("_argv") or normalized == "command"


def _is_host_private_argv_option(value: str) -> bool:
    option = value.split("=", 1)[0]
    return option in _HOST_PRIVATE_ARGV_OPTIONS


def _collect_scalar_strings(value: Any, output: set[str]) -> None:
    if isinstance(value, str):
        if value and value != HOST_PRIVATE_PUBLIC_REDACTION:
            output.add(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_scalar_strings(item, output)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_scalar_strings(item, output)


def _collect_host_private_argv_values(value: Any, output: set[str]) -> None:
    if not isinstance(value, (list, tuple)):
        return
    expect_private_value = False
    for item in value:
        if not isinstance(item, str):
            expect_private_value = False
            continue
        if expect_private_value:
            if item and item != HOST_PRIVATE_PUBLIC_REDACTION:
                output.add(item)
            expect_private_value = False
            continue
        if _is_host_private_argv_option(item):
            if "=" in item:
                private_value = item.split("=", 1)[1]
                if private_value:
                    output.add(private_value)
            else:
                expect_private_value = True


def _collect_host_private_result_values(
    value: Any,
    output: set[str],
    *,
    private_reference_context: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            private_field = _is_host_private_result_field(
                key,
                private_reference_context=private_reference_context,
            )
            if private_field:
                _collect_scalar_strings(item, output)
            if _is_argv_field(key):
                _collect_host_private_argv_values(item, output)
            _collect_host_private_result_values(
                item,
                output,
                private_reference_context=(
                    private_reference_context
                    or _is_host_private_reference_context(key)
                ),
            )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_host_private_result_values(
                item,
                output,
                private_reference_context=private_reference_context,
            )


def _redact_host_private_text(value: str, denied_values: tuple[str, ...]) -> str:
    redacted = value
    for denied in denied_values:
        # Direct schema fields are redacted regardless of length.  Cross-field
        # replacement ignores tiny malformed identifiers to avoid replacing
        # ordinary one-character text throughout an otherwise public result.
        if len(denied) >= 4:
            redacted = redacted.replace(denied, HOST_PRIVATE_PUBLIC_REDACTION)
    return redacted


def _redact_host_private_field_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_host_private_field_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_host_private_field_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_host_private_field_value(item) for item in value)
    if value is None or value == "":
        return value
    return HOST_PRIVATE_PUBLIC_REDACTION


def _public_argv_projection(
    value: Any,
    *,
    denied_values: tuple[str, ...],
) -> Any:
    if not isinstance(value, (list, tuple)):
        return _public_result_projection_value(
            value,
            denied_values=denied_values,
        )
    projected: list[Any] = []
    expect_private_value = False
    for item in value:
        if not isinstance(item, str):
            projected.append(
                _public_result_projection_value(
                    item,
                    denied_values=denied_values,
                )
            )
            expect_private_value = False
            continue
        if expect_private_value:
            projected.append(HOST_PRIVATE_PUBLIC_REDACTION)
            expect_private_value = False
            continue
        if _is_host_private_argv_option(item):
            if "=" in item:
                projected.append(
                    f"{item.split('=', 1)[0]}={HOST_PRIVATE_PUBLIC_REDACTION}"
                )
            else:
                projected.append(item)
                expect_private_value = True
            continue
        projected.append(_redact_host_private_text(item, denied_values))
    return tuple(projected) if isinstance(value, tuple) else projected


def _public_result_projection_value(
    value: Any,
    *,
    denied_values: tuple[str, ...],
    private_reference_context: bool = False,
) -> Any:
    if isinstance(value, dict):
        projected: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_host_private_result_field(
                key,
                private_reference_context=private_reference_context,
            ):
                projected[key] = _redact_host_private_field_value(item)
                continue
            if _is_argv_field(key):
                projected[key] = _public_argv_projection(
                    item,
                    denied_values=denied_values,
                )
                continue
            projected[key] = _public_result_projection_value(
                item,
                denied_values=denied_values,
                private_reference_context=(
                    private_reference_context
                    or _is_host_private_reference_context(key)
                ),
            )
        return projected
    if isinstance(value, list):
        return [
            _public_result_projection_value(
                item,
                denied_values=denied_values,
                private_reference_context=private_reference_context,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _public_result_projection_value(
                item,
                denied_values=denied_values,
                private_reference_context=private_reference_context,
            )
            for item in value
        )
    if isinstance(value, str):
        return _redact_host_private_text(value, denied_values)
    return value


def public_research_result_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Return a non-mutating public view of a private Console result payload."""

    denied: set[str] = set()
    _collect_host_private_result_values(result, denied)
    denied_values = tuple(sorted(denied, key=len, reverse=True))
    projected = _public_result_projection_value(
        result,
        denied_values=denied_values,
    )
    if not isinstance(projected, dict):  # defensive; ResearchJob enforces dict
        return {}
    return projected


def _require_verdict(verdict: str) -> str:
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict!r}")
    return verdict


def _require_contract(actual: str, expected: str) -> str:
    if actual != expected:
        raise ValueError(f"contract_version must be {expected}")
    return actual


def _require_choice(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def validate_public_source_url(value: str) -> None:
    if not value:
        return
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("source_url is invalid") from exc
    if parsed.scheme.lower() != "https":
        raise ValueError("source_url must use https")
    if not parsed.hostname or parsed.username or parsed.password or port not in {None, 443}:
        raise ValueError("source_url must be a public HTTPS URL without credentials or a custom port")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("source_url must not target a local or internal host")
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        addresses.add(ipaddress.ip_address(hostname))
    except ValueError:
        try:
            # inet_aton catches legacy spellings such as 127.1 and 2130706433.
            addresses.add(ipaddress.ip_address(socket.inet_aton(hostname)))
        except OSError:
            try:
                answers = socket.getaddrinfo(
                    hostname,
                    443,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise ValueError("source_url hostname could not be resolved") from exc
            for answer in answers:
                address_text = str(answer[4][0]).split("%", 1)[0]
                try:
                    addresses.add(ipaddress.ip_address(address_text))
                except ValueError as exc:
                    raise ValueError("source_url resolved to an invalid address") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("source_url must not target a private or non-global address")


@dataclass(frozen=True)
class ResearchRequest:
    title: str
    hypothesis: str
    input_kind: str = "hypothesis"
    factor_id_hint: str = ""
    universe: str = PILOT_UNIVERSE
    sample_start: str = "2016-01-01"
    sample_end: str = "2025-07-11"
    forward_horizon: str = "1d"
    transaction_cost_bps: float = PILOT_TRANSACTION_COST_BPS
    model: str = ""
    source_url: str = ""
    research_scope: str = RESEARCH_SCOPE_FULL_FORMAL

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.hypothesis.strip():
            raise ValueError("hypothesis is required")
        if len(self.title) > 160:
            raise ValueError("title is too long")
        if len(self.hypothesis) > 20_000:
            raise ValueError("hypothesis is too long")
        if self.input_kind not in {"hypothesis", "report", "formula", "code"}:
            raise ValueError(f"invalid research input_kind: {self.input_kind!r}")
        if self.model and self.model != PILOT_MODEL:
            raise ValueError(f"web Pilot supports only the {PILOT_MODEL} model")
        if self.research_scope not in VALID_RESEARCH_SCOPES:
            raise ValueError(
                f"invalid research_scope: {self.research_scope!r}"
            )
        validate_public_source_url(self.source_url)
        if not 0 <= float(self.transaction_cost_bps) <= 200:
            raise ValueError("transaction_cost_bps must be between 0 and 200")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Keep the historical full-formal wire representation byte-for-byte
        # compatible for persisted request/conversation hash replay.  The new
        # field is emitted only for the non-default scope that needs an
        # explicit authority boundary.
        if self.research_scope == RESEARCH_SCOPE_FULL_FORMAL:
            payload.pop("research_scope", None)
        return {"contract_version": RESEARCH_REQUEST_VERSION, **payload}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchRequest":
        version = str(payload.get("contract_version") or RESEARCH_REQUEST_VERSION)
        _require_contract(version, RESEARCH_REQUEST_VERSION)
        return cls(
            title=str(payload.get("title") or ""),
            hypothesis=str(payload.get("hypothesis") or ""),
            input_kind=str(payload.get("input_kind") or "hypothesis"),
            factor_id_hint=str(payload.get("factor_id_hint") or ""),
            universe=str(payload.get("universe") or PILOT_UNIVERSE),
            sample_start=str(payload.get("sample_start") or "2016-01-01"),
            sample_end=str(payload.get("sample_end") or "2025-07-11"),
            forward_horizon=str(payload.get("forward_horizon") or "1d"),
            transaction_cost_bps=float(
                payload.get("transaction_cost_bps", PILOT_TRANSACTION_COST_BPS)
            ),
            model=str(payload.get("model") or ""),
            source_url=str(payload.get("source_url") or ""),
            research_scope=str(
                payload.get("research_scope") or RESEARCH_SCOPE_FULL_FORMAL
            ),
        )


@dataclass(frozen=True)
class ResearchMessage:
    message_id: str
    job_id: str
    sequence_no: int
    role: str
    content_kind: str
    content: str
    model: str = ""
    idempotency_key: str = ""
    created_at_utc: str = ""

    def __post_init__(self) -> None:
        if self.role not in VALID_MESSAGE_ROLES:
            raise ValueError(f"invalid message role: {self.role!r}")
        if self.content_kind not in VALID_MESSAGE_CONTENT_KINDS:
            raise ValueError(f"invalid message content_kind: {self.content_kind!r}")
        text = self.content.strip()
        if not text:
            raise ValueError("message content is required")
        if len(text) > 20_000:
            raise ValueError("message content is too long")
        if _MESSAGE_SECRET_PATTERN.search(text):
            raise ValueError("message content must not contain API keys, passwords, or private keys")
        if self.sequence_no < 1:
            raise ValueError("message sequence_no must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": RESEARCH_MESSAGE_VERSION, **asdict(self)}


def validate_pilot_evaluation_request(request: ResearchRequest) -> None:
    """Fail closed when the web Pilot cannot execute the submitted evaluation contract."""
    if request.universe != PILOT_UNIVERSE:
        raise ValueError(
            f"web Pilot supports only the {PILOT_UNIVERSE} universe"
        )
    if request.forward_horizon != PILOT_FORWARD_HORIZON:
        raise ValueError(
            f"web Pilot supports only {PILOT_FORWARD_HORIZON} forward horizon"
        )
    if float(request.transaction_cost_bps) != PILOT_TRANSACTION_COST_BPS:
        raise ValueError(
            "web Pilot supports only the formal Step4 30 bps turnover cost model"
        )


@dataclass
class ResearchJob:
    job_id: str
    factor_id: str
    research_id: str
    report_id: str
    request: ResearchRequest
    execution_status: str = "QUEUED"
    protocol_status: str = "NOT_STARTED"
    factor_verdict: str = "UNKNOWN"
    council_status: str = "NOT_STARTED"
    formal_proof_eligible: bool = False
    current_stage: str = "queued"
    base_commit: str = ""
    worktree_path: str = ""
    workspace_path: str = ""
    agent_id: str = ""
    agent_session_key: str = ""
    error_code: str = ""
    error_message: str = ""
    created_at_utc: str = ""
    updated_at_utc: str = ""
    started_at_utc: str = ""
    finished_at_utc: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.execution_status = _require_choice(
            self.execution_status, VALID_EXECUTION_STATUSES, "execution_status"
        )
        self.protocol_status = _require_choice(
            self.protocol_status, VALID_PROTOCOL_STATUSES, "protocol_status"
        )
        self.factor_verdict = _require_verdict(self.factor_verdict)
        self.council_status = _require_choice(self.council_status, VALID_COUNCIL_STATUSES, "council_status")

    def to_dict(self, *, include_private_paths: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_version"] = RESEARCH_JOB_VERSION
        payload["request"] = self.request.to_dict()
        if not include_private_paths:
            payload.pop("worktree_path", None)
            payload.pop("workspace_path", None)
            payload.pop("agent_session_key", None)
            payload["result"] = public_research_result_projection(
                dict(payload.get("result") or {})
            )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchJob":
        version = str(payload.get("contract_version") or RESEARCH_JOB_VERSION)
        _require_contract(version, RESEARCH_JOB_VERSION)
        return cls(
            job_id=str(payload.get("job_id") or ""),
            factor_id=str(payload.get("factor_id") or ""),
            research_id=str(payload.get("research_id") or ""),
            report_id=str(payload.get("report_id") or ""),
            request=ResearchRequest.from_dict(dict(payload.get("request") or {})),
            execution_status=str(payload.get("execution_status") or "QUEUED"),
            protocol_status=str(payload.get("protocol_status") or "NOT_STARTED"),
            factor_verdict=str(payload.get("factor_verdict") or "UNKNOWN"),
            council_status=str(payload.get("council_status") or "NOT_STARTED"),
            formal_proof_eligible=bool(payload.get("formal_proof_eligible")),
            current_stage=str(payload.get("current_stage") or "queued"),
            base_commit=str(payload.get("base_commit") or ""),
            worktree_path=str(payload.get("worktree_path") or ""),
            workspace_path=str(payload.get("workspace_path") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            agent_session_key=str(payload.get("agent_session_key") or ""),
            error_code=str(payload.get("error_code") or ""),
            error_message=str(payload.get("error_message") or ""),
            created_at_utc=str(payload.get("created_at_utc") or ""),
            updated_at_utc=str(payload.get("updated_at_utc") or ""),
            started_at_utc=str(payload.get("started_at_utc") or ""),
            finished_at_utc=str(payload.get("finished_at_utc") or ""),
            result=dict(payload.get("result") or {}),
        )


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
