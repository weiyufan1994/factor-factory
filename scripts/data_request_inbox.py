#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.data_requests import (  # noqa: E402
    DataRequestError,
    build_request_skeleton,
    assert_valid_request,
    assert_valid_resolution,
    claim_request,
    build_resolution_skeleton,
    find_request_status,
    list_requests,
    mirror_request,
    read_json,
    resolution_filename,
    validate_request,
    validate_resolution,
    write_json,
)

DEFAULT_INBOX = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'inbox'
DEFAULT_CLAIMED = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'claimed'
DEFAULT_RESOLVED = REPO_ROOT / 'factorforge' / 'data' / 'requests' / 'resolved'


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Validate and manage FactorForge Data API request inbox.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    new = sub.add_parser('new')
    new.add_argument('--report-id', required=True)
    new.add_argument('--dataset-id', required=True)
    new.add_argument('--request-type', required=True, choices=[
        'new_datamart',
        'coverage_repair',
        'schema_addition',
        'performance_acceleration',
        'read_smoke',
    ])
    new.add_argument('--priority', default='P1', choices=['P0', 'P1', 'P2'])
    new.add_argument('--created-by', default='factorforge-researcher')
    new.add_argument('--economic-purpose', default='')
    new.add_argument('--formula-or-state', default='')
    new.add_argument('--upstream-datasets', default='')
    new.add_argument('--is-start', default='20160104')
    new.add_argument('--is-end', default='20250711')
    new.add_argument('--oos-start', default='20250714')
    new.add_argument('--cutoff-times', default='')
    new.add_argument('--unique-key', default='ts_code,trade_date')
    new.add_argument('--required-fields', default='ts_code,trade_date')
    new.add_argument('--qa-requirements', default='duplicate_key_count=0,missing_dates=[],coverage_summary,representative_read_smoke')
    new.add_argument('--preferred-executor', default='research_worker')
    new.add_argument('--no-batch-spot', action='store_true')
    new.add_argument('--output', required=True)

    validate = sub.add_parser('validate')
    validate.add_argument('path')
    validate.add_argument('--kind', choices=['request', 'resolution'], default='request')

    list_cmd = sub.add_parser('list')
    list_cmd.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))

    status = sub.add_parser('status')
    status.add_argument('request_id')
    status.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))
    status.add_argument('--claimed-dir', default=str(DEFAULT_CLAIMED))
    status.add_argument('--resolved-dir', default=str(DEFAULT_RESOLVED))

    claim = sub.add_parser('claim')
    claim.add_argument('request_id')
    claim.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))
    claim.add_argument('--claimed-dir', default=str(DEFAULT_CLAIMED))
    claim.add_argument('--claimed-by', default='data-api')
    claim.add_argument('--note', default='')

    mirror = sub.add_parser('mirror')
    mirror.add_argument('path')
    mirror.add_argument('--inbox-dir', default=str(DEFAULT_INBOX))

    skeleton = sub.add_parser('resolution-skeleton')
    skeleton.add_argument('request_path')
    skeleton.add_argument('--verdict', choices=['ACCEPT', 'BLOCK'], default='BLOCK')
    skeleton.add_argument('--output')

    resolve = sub.add_parser('resolve')
    resolve.add_argument('resolution_path')
    resolve.add_argument('--resolved-dir', default=str(DEFAULT_RESOLVED))
    resolve.add_argument('--allow-block-with-issues', action='store_true')

    return ap.parse_args()


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def cmd_new(args: argparse.Namespace) -> int:
    request = build_request_skeleton(
        report_id=args.report_id,
        dataset_id=args.dataset_id,
        request_type=args.request_type,
        priority=args.priority,
        created_by=args.created_by,
        economic_purpose=args.economic_purpose,
        formula_or_state=args.formula_or_state,
        upstream_datasets=split_csv(args.upstream_datasets),
        is_start=args.is_start,
        is_end=args.is_end,
        oos_start=args.oos_start,
        cutoff_times=split_csv(args.cutoff_times),
        unique_key=split_csv(args.unique_key),
        required_fields=split_csv(args.required_fields),
        qa_requirements=split_csv(args.qa_requirements),
        preferred_executor=args.preferred_executor,
        batch_spot_allowed=not args.no_batch_spot,
    )
    target = write_json(args.output, request)
    print_json({'wrote': str(target), 'request': request})
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    payload = read_json(args.path)
    issues = validate_request(payload) if args.kind == 'request' else validate_resolution(payload)
    print_json({'path': args.path, 'kind': args.kind, 'valid': not issues, 'issues': [issue.to_dict() for issue in issues]})
    return 0 if not issues else 2


def cmd_list(args: argparse.Namespace) -> int:
    print_json({'inbox_dir': args.inbox_dir, 'requests': list_requests(args.inbox_dir)})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    status = find_request_status(args.request_id, args.inbox_dir, args.resolved_dir, args.claimed_dir)
    print_json(status)
    return 0 if status['status'] in {'PENDING', 'IN_PROGRESS', 'ACCEPT', 'BLOCK'} else 2


def cmd_claim(args: argparse.Namespace) -> int:
    target = claim_request(
        args.request_id,
        args.inbox_dir,
        args.claimed_dir,
        claimed_by=args.claimed_by,
        note=args.note,
    )
    print_json({'claimed_to': str(target), 'request_id': args.request_id})
    return 0


def cmd_mirror(args: argparse.Namespace) -> int:
    target = mirror_request(args.path, args.inbox_dir)
    print_json({'mirrored_to': str(target)})
    return 0


def cmd_resolution_skeleton(args: argparse.Namespace) -> int:
    request = read_json(args.request_path)
    resolution = build_resolution_skeleton(request, verdict=args.verdict)
    if args.output:
        target = write_json(args.output, resolution)
    else:
        target = Path(args.request_path).expanduser().with_name(resolution_filename(resolution))
        write_json(target, resolution)
    print_json({'wrote': str(target), 'resolution': resolution})
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    resolution = read_json(args.resolution_path)
    if args.allow_block_with_issues and resolution.get('verdict') == 'BLOCK':
        issues = validate_resolution(resolution)
        blocking = [issue for issue in issues if issue.field not in {'catalog_path', 'datamart_path', 'qa_json_path'}]
        if blocking:
            raise DataRequestError('; '.join(f'{issue.field}: {issue.message}' for issue in blocking))
    else:
        assert_valid_resolution(resolution)
    target = Path(args.resolved_dir).expanduser() / resolution_filename(resolution)
    write_json(target, resolution)
    print_json({'resolved_to': str(target), 'verdict': resolution.get('verdict')})
    return 0


def main() -> None:
    args = parse_args()
    try:
        if args.cmd == 'new':
            code = cmd_new(args)
        elif args.cmd == 'validate':
            code = cmd_validate(args)
        elif args.cmd == 'list':
            code = cmd_list(args)
        elif args.cmd == 'status':
            code = cmd_status(args)
        elif args.cmd == 'claim':
            code = cmd_claim(args)
        elif args.cmd == 'mirror':
            code = cmd_mirror(args)
        elif args.cmd == 'resolution-skeleton':
            code = cmd_resolution_skeleton(args)
        elif args.cmd == 'resolve':
            code = cmd_resolve(args)
        else:
            raise DataRequestError(f'unknown command: {args.cmd}')
    except DataRequestError as exc:
        print_json({'error': str(exc)})
        code = 2
    raise SystemExit(code)


if __name__ == '__main__':
    main()
