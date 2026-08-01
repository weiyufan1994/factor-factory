from __future__ import annotations

import os
import secrets
import ipaddress
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ConsoleConfig:
    source_repo: Path
    state_root: Path
    worktree_root: Path
    base_ref: str = "HEAD"
    data_catalogs: tuple[Path, ...] = field(default_factory=tuple)
    catalog_receipt: Path | None = None
    data_api_pythonpath: Path | None = None
    invite_password: str = ""
    cookie_secret: str = ""
    cookie_secure: bool = False
    openclaw_binary: str = "openclaw"
    openclaw_profile: str = "factorforge-console"
    openclaw_model: str = "deepseek/deepseek-reasoner"
    openclaw_thinking: str = "high"
    openclaw_auth_provider: str = "deepseek"
    openclaw_auth_seed_db: Path | None = None
    execution_mode: str = "container"
    container_runtime: str = "docker"
    container_network: str = "factorforge-console-egress"
    container_network_subnet: str = "172.29.0.0/24"
    container_proxy_url: str = "http://172.29.0.1:3128"
    container_model_broker_url: str = "http://172.29.0.1:8781"
    aws_readonly_role_name: str = ""
    installation_id: str = ""
    agent_container_image: str = "factorforge-console-agent:2026.08.01"
    openclaw_profile_template: Path | None = None
    container_memory: str = "16g"
    container_cpus: float = 4.0
    container_pids_limit: int = 512
    container_tmpfs_size: str = "8g"
    max_concurrent_jobs: int = 1
    agent_timeout_seconds: int = 21_600
    max_request_bytes: int = 65_536
    auth_disabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_repo", self.source_repo.expanduser().resolve())
        object.__setattr__(self, "state_root", self.state_root.expanduser().resolve())
        object.__setattr__(self, "worktree_root", self.worktree_root.expanduser().resolve())
        object.__setattr__(
            self,
            "data_catalogs",
            tuple(path.expanduser().resolve() for path in self.data_catalogs),
        )
        if self.catalog_receipt is not None:
            object.__setattr__(self, "catalog_receipt", self.catalog_receipt.expanduser().resolve())
        if self.data_api_pythonpath is not None:
            object.__setattr__(self, "data_api_pythonpath", self.data_api_pythonpath.expanduser().resolve())
        if self.openclaw_auth_seed_db is not None:
            object.__setattr__(
                self,
                "openclaw_auth_seed_db",
                self.openclaw_auth_seed_db.expanduser().absolute(),
            )
        if self.openclaw_profile_template is None:
            object.__setattr__(
                self,
                "openclaw_profile_template",
                (self.source_repo / "deploy" / "factorforge-console" / "openclaw.json.example").resolve(),
            )
        else:
            object.__setattr__(
                self,
                "openclaw_profile_template",
                self.openclaw_profile_template.expanduser().resolve(),
            )
        if not self.installation_id:
            identity_seed = f"{self.source_repo}\0{self.state_root}".encode("utf-8")
            object.__setattr__(self, "installation_id", hashlib.sha256(identity_seed).hexdigest()[:16])
        if not self.cookie_secret and self.auth_disabled:
            object.__setattr__(self, "cookie_secret", secrets.token_urlsafe(48))
        if self.max_concurrent_jobs != 1:
            raise ValueError("the invitation pilot requires max_concurrent_jobs=1")
        if not self.auth_disabled:
            _validate_secret(self.invite_password, label="invite password", minimum=16)
            _validate_secret(self.cookie_secret, label="cookie secret", minimum=32)
            if self.invite_password == self.cookie_secret:
                raise ValueError("invite password and cookie secret must differ")
        if self.agent_timeout_seconds < 60:
            raise ValueError("agent timeout must be at least 60 seconds")
        if self.openclaw_thinking not in {"off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"}:
            raise ValueError("unsupported OpenClaw thinking level")
        if self.execution_mode not in {"container", "shared_gateway"}:
            raise ValueError("execution_mode must be container or shared_gateway")
        if self.container_cpus <= 0 or self.container_pids_limit < 64:
            raise ValueError("invalid agent container resource limits")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", self.container_network):
            raise ValueError("invalid agent container network name")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,62}", self.installation_id):
            raise ValueError("invalid Console installation identity")
        if (
            self.execution_mode == "container"
            and self.data_catalogs
            and not self.auth_disabled
            and not re.fullmatch(r"[A-Za-z0-9+=,.@_-]{1,64}", self.aws_readonly_role_name)
        ):
            raise ValueError("a pinned read-only AWS role name is required")
        if self.execution_mode == "container" and self.data_catalogs and not self.auth_disabled:
            if self.catalog_receipt is None or self.data_api_pythonpath is None:
                raise ValueError("production Data API requires a catalog receipt and package root")
        if (
            self.execution_mode == "container"
            and not self.auth_disabled
            and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.agent_container_image)
        ):
            raise ValueError("production agent image must be pinned by local image digest")
        network = ipaddress.ip_network(self.container_network_subnet, strict=True)
        if network.version != 4 or network.prefixlen < 24 or network.is_global:
            raise ValueError("agent container network must use a dedicated private IPv4 /24 or smaller")
        proxy = urlsplit(self.container_proxy_url)
        try:
            proxy_address = ipaddress.ip_address(proxy.hostname or "")
        except ValueError as exc:
            raise ValueError("agent container proxy must use a literal bridge address") from exc
        if (
            proxy.scheme != "http"
            or proxy.username
            or proxy.password
            or proxy.port != 3128
            or proxy_address not in network
            or proxy_address != network.network_address + 1
        ):
            raise ValueError("agent container proxy must be the dedicated bridge gateway on port 3128")
        model_broker = urlsplit(self.container_model_broker_url)
        try:
            model_broker_address = ipaddress.ip_address(model_broker.hostname or "")
        except ValueError as exc:
            raise ValueError("agent model broker must use a literal bridge address") from exc
        if (
            model_broker.scheme != "http"
            or model_broker.username
            or model_broker.password
            or model_broker.path not in {"", "/"}
            or model_broker.query
            or model_broker.port != 8781
            or model_broker_address != network.network_address + 1
        ):
            raise ValueError("agent model broker must be the dedicated bridge gateway on port 8781")

    @classmethod
    def from_env(
        cls,
        *,
        source_repo: str | Path,
        state_root: str | Path,
        worktree_root: str | Path,
        base_ref: str = "HEAD",
        data_catalogs: list[str | Path] | None = None,
        data_api_pythonpath: str | Path | None = None,
        auth_disabled: bool = False,
    ) -> "ConsoleConfig":
        return cls(
            source_repo=Path(source_repo),
            state_root=Path(state_root),
            worktree_root=Path(worktree_root),
            base_ref=base_ref,
            data_catalogs=tuple(Path(item) for item in (data_catalogs or [])),
            catalog_receipt=(
                Path(os.environ["FACTORFORGE_CONSOLE_CATALOG_RECEIPT"])
                if os.getenv("FACTORFORGE_CONSOLE_CATALOG_RECEIPT")
                else None
            ),
            data_api_pythonpath=Path(data_api_pythonpath) if data_api_pythonpath else None,
            invite_password=os.getenv("FACTORFORGE_CONSOLE_INVITE_PASSWORD", ""),
            cookie_secret=os.getenv("FACTORFORGE_CONSOLE_COOKIE_SECRET", ""),
            cookie_secure=os.getenv("FACTORFORGE_CONSOLE_COOKIE_SECURE", "0") == "1",
            openclaw_binary=os.getenv("FACTORFORGE_CONSOLE_OPENCLAW", "openclaw"),
            openclaw_profile=os.getenv("FACTORFORGE_CONSOLE_OPENCLAW_PROFILE", "factorforge-console"),
            openclaw_model=os.getenv("FACTORFORGE_CONSOLE_MODEL", "deepseek/deepseek-reasoner"),
            openclaw_thinking=os.getenv("FACTORFORGE_CONSOLE_THINKING", "high"),
            openclaw_auth_provider=os.getenv("FACTORFORGE_CONSOLE_OPENCLAW_AUTH_PROVIDER", "deepseek"),
            openclaw_auth_seed_db=(
                Path(os.environ["FACTORFORGE_CONSOLE_OPENCLAW_AUTH_SEED_DB"])
                if os.getenv("FACTORFORGE_CONSOLE_OPENCLAW_AUTH_SEED_DB")
                else None
            ),
            execution_mode=os.getenv("FACTORFORGE_CONSOLE_EXECUTION_MODE", "container"),
            container_runtime=os.getenv("FACTORFORGE_CONSOLE_CONTAINER_RUNTIME", "docker"),
            container_network=os.getenv(
                "FACTORFORGE_CONSOLE_CONTAINER_NETWORK", "factorforge-console-egress"
            ),
            container_network_subnet=os.getenv(
                "FACTORFORGE_CONSOLE_CONTAINER_NETWORK_SUBNET", "172.29.0.0/24"
            ),
            container_proxy_url=os.getenv(
                "FACTORFORGE_CONSOLE_CONTAINER_PROXY_URL", "http://172.29.0.1:3128"
            ),
            container_model_broker_url=os.getenv(
                "FACTORFORGE_CONSOLE_MODEL_BROKER_URL", "http://172.29.0.1:8781"
            ),
            aws_readonly_role_name=os.getenv("FACTORFORGE_CONSOLE_AWS_READONLY_ROLE_NAME", ""),
            installation_id=os.getenv("FACTORFORGE_CONSOLE_INSTALLATION_ID", ""),
            agent_container_image=os.getenv(
                "FACTORFORGE_CONSOLE_AGENT_IMAGE", "factorforge-console-agent:2026.08.01"
            ),
            openclaw_profile_template=(
                Path(os.environ["FACTORFORGE_CONSOLE_OPENCLAW_PROFILE_TEMPLATE"])
                if os.getenv("FACTORFORGE_CONSOLE_OPENCLAW_PROFILE_TEMPLATE")
                else None
            ),
            container_memory=os.getenv("FACTORFORGE_CONSOLE_CONTAINER_MEMORY", "16g"),
            container_cpus=float(os.getenv("FACTORFORGE_CONSOLE_CONTAINER_CPUS", "4")),
            container_pids_limit=int(os.getenv("FACTORFORGE_CONSOLE_CONTAINER_PIDS", "512")),
            container_tmpfs_size=os.getenv("FACTORFORGE_CONSOLE_CONTAINER_TMPFS", "8g"),
            agent_timeout_seconds=int(os.getenv("FACTORFORGE_CONSOLE_AGENT_TIMEOUT", "21600")),
            auth_disabled=auth_disabled,
        )


def _validate_secret(value: str, *, label: str, minimum: int) -> None:
    lowered = value.strip().lower()
    placeholders = ("replace", "changeme", "change-me", "example", "password", "your-secret")
    if len(value) < minimum or any(token in lowered for token in placeholders):
        raise ValueError(f"{label} is missing, weak, or still a placeholder")
