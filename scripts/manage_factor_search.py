#!/usr/bin/env python3
"""Host entry for the opt-in research-search interface; no market defaults."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factor_factory.research_search.contracts import SearchError, read_json
from factor_factory.research_search.controller import ResearchSearchController
from factor_factory.research_search.executor import FileNativeExecutor, execute_ready, reconcile_dispatch, stop_preparation
from factor_factory.research_search.ledger import SearchLedger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--campaign", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "register", "prepare"):
        child = commands.add_parser(name)
        child.add_argument("--input", required=True)
        if name == "prepare":
            child.add_argument("--candidate", required=True)
    for name in ("status", "tick", "proposer-context"):
        commands.add_parser(name)
    for name in ("run-native", "reconcile-dispatch", "stop-preparation"):
        child = commands.add_parser(name)
        child.add_argument("--ticket", required=True)
        if name == "stop-preparation":
            child.add_argument("--actor", required=True)
            child.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    ledger = SearchLedger(args.workspace)
    controller = ResearchSearchController(ledger, args.campaign, FileNativeExecutor(args.workspace))
    try:
        if args.command == "create":
            context = read_json(args.input)
            if context.get("campaign_id") != args.campaign:
                raise SearchError("CLI campaign/context mismatch")
            result = ledger.create_campaign(context)
        elif args.command == "register":
            result = ledger.register(args.campaign, read_json(args.input)["proposals"])
        elif args.command == "prepare":
            result = ledger.prepare(args.campaign, args.candidate, read_json(args.input))
        elif args.command == "status":
            result = ledger.snapshot(args.campaign)
        elif args.command == "proposer-context":
            result = controller.proposer_context()
        elif args.command == "run-native":
            result = execute_ready(ledger, args.campaign, args.ticket)
        elif args.command == "reconcile-dispatch":
            result = reconcile_dispatch(ledger, args.campaign, args.ticket)
        elif args.command == "stop-preparation":
            result = stop_preparation(ledger, args.campaign, args.ticket, actor=args.actor, reason=args.reason)
        else:
            result = controller.tick()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (SearchError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"state": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
