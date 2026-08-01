from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ConsoleConfig:
    source_repo: Path
    state_root: Path
    worktree_root: Path
    base_ref: str = "HEAD"
    data_catalogs: tuple[Path, ...] = field(default_factory=tuple)
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
        if self.data_api_pythonpath is not None:
            object.__setattr__(self, "data_api_pythonpath", self.data_api_pythonpath.expanduser().resolve())
        if self.openclaw_auth_seed_db is not None:
            object.__setattr__(self, "openclaw_auth_seed_db", self.openclaw_auth_seed_db.expanduser().resolve())
        if not self.cookie_secret:
            object.__setattr__(self, "cookie_secret", secrets.token_urlsafe(48))
        if self.max_concurrent_jobs != 1:
            raise ValueError("the invitation pilot requires max_concurrent_jobs=1")
        if not self.auth_disabled and not self.invite_password:
            raise ValueError("invite password is required unless auth is explicitly disabled")
        if self.agent_timeout_seconds < 60:
            raise ValueError("agent timeout must be at least 60 seconds")
        if self.openclaw_thinking not in {"off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"}:
            raise ValueError("unsupported OpenClaw thinking level")

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
            agent_timeout_seconds=int(os.getenv("FACTORFORGE_CONSOLE_AGENT_TIMEOUT", "21600")),
            auth_disabled=auth_disabled,
        )
