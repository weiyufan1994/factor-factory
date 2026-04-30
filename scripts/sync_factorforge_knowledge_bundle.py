#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
import socket
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = 'yufan-data-lake'
DEFAULT_PREFIX = 'factorforge-knowledge'
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
DEFAULT_RUNTIME_ROOT = LEGACY_WORKSPACE / 'factorforge'

KNOWLEDGE_SPECS = {
    'factor_library_all': ('objects/factor_library_all', 'factor_record__*.json'),
    # Step6 currently writes official records using the same factor_record__*.json
    # naming convention as factor_library_all. Accept the canonical pattern here so
    # Mac<->EC2 knowledge sync carries promoted factors correctly.
    'factor_library_official': ('objects/factor_library_official', 'factor_record__*.json'),
    'research_knowledge_base': ('objects/research_knowledge_base', 'knowledge_record__*.json'),
    'research_iteration_master': ('objects/research_iteration_master', '*.json'),
    'research_journal': ('objects/research_journal', '*.json'),
    'factor_case_master': ('objects/factor_case_master', 'factor_case_master__*.json'),
    'factor_evaluation': ('objects/validation', 'factor_evaluation__*.json'),
    'handoff_to_step3b': ('objects/handoff', 'handoff_to_step3b__*.json'),
    'handoff_to_step6': ('objects/handoff', 'handoff_to_step6__*.json'),
}

PROTECTED_OVERWRITE_PREFIXES = (
    'objects/factor_library_official/',
    'objects/factor_case_master/',
    'objects/handoff/',
    'objects/validation/',
)


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')


def resolve_runtime_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_root = os.getenv('FACTORFORGE_ROOT')
    if env_root:
        return Path(env_root).expanduser()
    if DEFAULT_RUNTIME_ROOT.exists():
        return DEFAULT_RUNTIME_ROOT
    return REPO_ROOT


def resolve_objects_root(runtime_root: Path) -> Path:
    if runtime_root.name == 'objects' and runtime_root.is_dir():
        return runtime_root
    return runtime_root / 'objects'


def iter_selected_files(objects_root: Path, include: Iterable[str]) -> list[tuple[Path, str]]:
    pairs: list[tuple[Path, str]] = []
    for key in include:
        rel_dir, pattern = KNOWLEDGE_SPECS[key]
        source_dir = objects_root.parent / rel_dir
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.glob(pattern)):
            if path.is_file():
                rel = str(path.relative_to(objects_root.parent))
                pairs.append((path, rel))
    return pairs


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def action_for_destination(rel: str, dst: Path, allow_official_overwrite: bool) -> str:
    if not dst.exists():
        return 'create'
    protected = rel.startswith(PROTECTED_OVERWRITE_PREFIXES)
    if protected:
        return 'overwrite' if allow_official_overwrite else 'overwrite-blocked'
    return 'skip'


def write_sync_audit(base_root: Path, args: argparse.Namespace, bundle_source: str, planned: list[dict], manifest: dict) -> Path:
    audit_dir = base_root / 'objects' / 'sync_audit'
    audit_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    audit_path = audit_dir / f'sync_audit__{ts}.json'
    changed = [item['destination'] for item in planned if item['action'] == 'create']
    skipped = [item['destination'] for item in planned if item['action'] in {'skip', 'overwrite-blocked'}]
    overwritten = [item['destination'] for item in planned if item['action'] == 'overwrite']
    payload = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'hostname': socket.gethostname(),
        'command_args': vars(args),
        'source_bundle': bundle_source,
        'bundle_manifest': manifest,
        'planned_changes': planned,
        'changed_files': changed,
        'skipped_files': skipped,
        'overwritten_files': overwritten,
    }
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit_path


def cmd_bundle(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    objects_root = resolve_objects_root(runtime_root)
    include = args.include or list(KNOWLEDGE_SPECS.keys())
    files = iter_selected_files(objects_root, include)
    if not files:
        raise SystemExit(f'No knowledge files found under {objects_root}')

    with tempfile.TemporaryDirectory(prefix='ff-knowledge-bundle-') as td:
        stage = Path(td) / 'bundle'
        stage.mkdir(parents=True, exist_ok=True)
        for src, rel in files:
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        manifest = {
            'created_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'runtime_root': str(runtime_root),
            'objects_root': str(objects_root),
            'include': include,
            'file_count': len(files),
            'files': [rel for _, rel in files],
        }
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

        out = Path(args.output).expanduser() if args.output else Path(tempfile.gettempdir()) / f'factorforge-knowledge-{utc_ts()}.tgz'
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, 'w:gz') as tar:
            tar.add(stage, arcname='.')

    print(f'[BUNDLE] {out}')
    print(f'[FILES] {len(files)}')

    if args.upload:
        key = f"{args.prefix.rstrip('/')}/{out.name}"
        run(['aws', 's3', 'cp', str(out), f's3://{args.bucket}/{key}'])
        print(f'[S3] s3://{args.bucket}/{key}')
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    base_root = resolve_objects_root(runtime_root).parent

    source = args.source
    temp_download = None
    if source.startswith('s3://'):
        temp_download = Path(tempfile.gettempdir()) / Path(source).name
        run(['aws', 's3', 'cp', source, str(temp_download)])
        bundle_path = temp_download
    else:
        bundle_path = Path(source).expanduser()

    with tempfile.TemporaryDirectory(prefix='ff-knowledge-apply-') as td:
        stage = Path(td) / 'extract'
        stage.mkdir(parents=True, exist_ok=True)
        with tarfile.open(bundle_path, 'r:gz') as tar:
            tar.extractall(stage)
        manifest = json.loads((stage / 'manifest.json').read_text(encoding='utf-8'))
        planned: list[dict] = []
        for rel in manifest.get('files', []):
            src = stage / rel
            dst = base_root / rel
            action = action_for_destination(rel, dst, args.allow_official_overwrite)
            item = {
                'source': str(src),
                'destination': str(dst),
                'exists': dst.exists(),
                'action': action,
            }
            planned.append(item)
            print(json.dumps(item, ensure_ascii=False))

        if not args.apply:
            print('[DRY-RUN] No files written. Re-run with apply --apply to write planned creates.')
            return 0

        base_root.mkdir(parents=True, exist_ok=True)
        for item in planned:
            if item['action'] not in {'create', 'overwrite'}:
                continue
            src = Path(item['source'])
            dst = Path(item['destination'])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f'[APPLY] {dst}')

        audit_path = write_sync_audit(base_root, args, source, planned, manifest)
        print(f'[AUDIT] {audit_path}')

    if args.rebuild_index:
        run(['python3', str(REPO_ROOT / 'scripts' / 'build_factorforge_retrieval_index.py')])
        print('[REBUILD] retrieval index')
    if args.export_obsidian:
        run(['python3', str(REPO_ROOT / 'scripts' / 'export_factorforge_obsidian.py')])
        print('[REBUILD] obsidian vault')
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] not in {'bundle', 'apply', '-h', '--help'}:
        sys.argv[1:2] = ['apply', '--source', sys.argv[1]]
    parser = argparse.ArgumentParser(description='Bundle/apply factorforge knowledge objects for Mac<->EC2 sharing.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_bundle = sub.add_parser('bundle')
    p_bundle.add_argument('--runtime-root')
    p_bundle.add_argument('--output')
    p_bundle.add_argument('--upload', action='store_true')
    p_bundle.add_argument('--bucket', default=DEFAULT_BUCKET)
    p_bundle.add_argument('--prefix', default=DEFAULT_PREFIX)
    p_bundle.add_argument('--include', nargs='*', choices=sorted(KNOWLEDGE_SPECS.keys()))
    p_bundle.set_defaults(func=cmd_bundle)

    p_apply = sub.add_parser('apply')
    p_apply.add_argument('--runtime-root')
    p_apply.add_argument('--source', required=True, help='Local bundle path or s3:// URI')
    p_apply.add_argument('--apply', action='store_true', help='Actually write planned creates. Default is dry-run.')
    p_apply.add_argument('--allow-official-overwrite', action='store_true', help='Allow overwriting protected official/case/handoff/validation records when a future overwrite path is enabled.')
    p_apply.add_argument('--rebuild-index', action='store_true')
    p_apply.add_argument('--export-obsidian', action='store_true')
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
