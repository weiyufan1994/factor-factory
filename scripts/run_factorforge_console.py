#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.agent_adapter import OpenClawResearchAgentAdapter  # noqa: E402
from factor_factory.console.auth import InviteAuth  # noqa: E402
from factor_factory.console.config import ConsoleConfig  # noqa: E402
from factor_factory.console.container_agent_adapter import ContainerizedOpenClawResearchAgentAdapter  # noqa: E402
from factor_factory.console.run_service import ResearchRunService  # noqa: E402
from factor_factory.console.static_app import (  # noqa: E402
    ResearchConsoleApplication,
    build_console_server,
    build_research_console_server,
    serve_console_server,
    serve_research_console_server,
)
from factor_factory.console.store import ResearchJobStore  # noqa: E402
from factor_factory.console.worktree_allocator import FactorWorktreeAllocator  # noqa: E402


def _raise_keyboard_interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the invitation-only Factor Forge research Console.")
    parser.add_argument("--source-repo", default=str(REPO_ROOT), help="Clean pinned Factor Factory source checkout.")
    parser.add_argument(
        "--state-root",
        default=os.getenv("FACTORFORGE_CONSOLE_STATE_ROOT", "~/.local/share/factorforge-console"),
        help="External Console ledger and private agent state root.",
    )
    parser.add_argument(
        "--worktree-root",
        default=os.getenv("FACTORFORGE_CONSOLE_WORKTREE_ROOT", "~/.local/share/factorforge-runs"),
        help="Server-owned per-factor worktree root.",
    )
    parser.add_argument("--base-ref", default=os.getenv("FACTORFORGE_CONSOLE_BASE_REF", "HEAD"))
    parser.add_argument("--catalog", action="append", default=[], help="Read-only Data API catalog path.")
    parser.add_argument("--data-api-pythonpath", default=os.getenv("FACTORFORGE_DATA_API_PYTHONPATH"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--auth-disabled", action="store_true", help="Loopback development only.")
    parser.add_argument(
        "--legacy-root",
        action="append",
        default=[],
        help="Run the old read-only Miner dashboard instead of the research Console.",
    )
    args = parser.parse_args()

    if args.legacy_root:
        server = build_console_server([Path(root) for root in args.legacy_root], args.host, args.port)
        print(f"Factor Forge legacy Console running at http://{args.host}:{args.port}", flush=True)
        serve_console_server(server)
        return

    if args.auth_disabled and args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("--auth-disabled is only allowed on loopback")
    env_catalogs = [item for item in os.getenv("FACTORFORGE_DATA_CATALOGS", "").split(",") if item.strip()]
    catalogs = [*env_catalogs, *args.catalog]
    config = ConsoleConfig.from_env(
        source_repo=args.source_repo,
        state_root=args.state_root,
        worktree_root=args.worktree_root,
        base_ref=args.base_ref,
        data_catalogs=catalogs,
        data_api_pythonpath=args.data_api_pythonpath,
        auth_disabled=args.auth_disabled,
    )
    store = ResearchJobStore(config.state_root)
    allocator = FactorWorktreeAllocator(
        source_repo=config.source_repo,
        configured_root=config.worktree_root,
        run_state_root=config.state_root / "allocations",
        base_ref=config.base_ref,
    )
    pinned_commit = allocator.validate_ready()
    if config.execution_mode == "shared_gateway":
        if not args.auth_disabled:
            raise SystemExit("shared_gateway execution is restricted to loopback auth-disabled development")
        adapter = OpenClawResearchAgentAdapter(config)
    else:
        adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    agent_runtime = adapter.validate_ready()
    service = ResearchRunService(
        config=config,
        store=store,
        allocator=allocator,
        agent_adapter=adapter,
    )
    application = ResearchConsoleApplication(
        config=config,
        store=store,
        service=service,
        engine_commit=pinned_commit,
        agent_runtime=agent_runtime,
        auth=InviteAuth(
            config.invite_password,
            config.cookie_secret,
            secure_cookie=config.cookie_secure,
            disabled=config.auth_disabled,
        ),
    )
    server = build_research_console_server(application, args.host, args.port)
    print(
        f"Factor Forge Console running at http://{args.host}:{args.port} "
        f"(engine={pinned_commit[:12]}, agent_runtime={agent_runtime}, concurrency=1)",
        flush=True,
    )
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    serve_research_console_server(server, application)


if __name__ == "__main__":
    main()
