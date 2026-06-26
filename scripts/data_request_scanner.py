#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.request_scanner import scan_request_inbox, watch_request_inbox  # noqa: E402

DEFAULT_INBOX = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'inbox'
DEFAULT_CLAIMED = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'claimed'
DEFAULT_RESOLVED = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'resolved'


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Scan FactorForge Data API request inbox and claim pending work.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    once = sub.add_parser('once')
    once.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))
    once.add_argument('--claimed-dir', default=str(DEFAULT_CLAIMED))
    once.add_argument('--resolved-dir', default=str(DEFAULT_RESOLVED))
    once.add_argument('--claimed-by', default='data-api-scanner')
    once.add_argument('--note', default='Data API scanner claimed request for triage.')
    once.add_argument('--limit', type=int)

    watch = sub.add_parser('watch')
    watch.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))
    watch.add_argument('--claimed-dir', default=str(DEFAULT_CLAIMED))
    watch.add_argument('--resolved-dir', default=str(DEFAULT_RESOLVED))
    watch.add_argument('--claimed-by', default='data-api-scanner')
    watch.add_argument('--note', default='Data API scanner claimed request for triage.')
    watch.add_argument('--interval-seconds', type=float, default=30.0)
    watch.add_argument('--max-iterations', type=int)
    watch.add_argument('--limit-per-scan', type=int)
    return ap.parse_args()


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    args = parse_args()
    if args.cmd == 'once':
        print_json(
            scan_request_inbox(
                args.inbox_dir,
                args.claimed_dir,
                args.resolved_dir,
                claimed_by=args.claimed_by,
                note=args.note,
                limit=args.limit,
            )
        )
    elif args.cmd == 'watch':
        print_json(
            watch_request_inbox(
                args.inbox_dir,
                args.claimed_dir,
                args.resolved_dir,
                claimed_by=args.claimed_by,
                note=args.note,
                interval_seconds=args.interval_seconds,
                max_iterations=args.max_iterations,
                limit_per_scan=args.limit_per_scan,
            )
        )
    else:
        raise SystemExit(f'unknown command: {args.cmd}')


if __name__ == '__main__':
    main()
