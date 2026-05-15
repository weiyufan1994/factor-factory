#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    # Human-readable vault exported from objects plus curated research archives.
    # This is read/display material, not a replacement for canonical objects.
    'knowledge_vault': ('knowledge/因子工厂', '**/*.md'),
    'retrieval_index': ('knowledge/retrieval', 'factorforge_*'),
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


def run_with_factorforge_root(cmd: list[str], runtime_root: Path) -> None:
    env = dict(os.environ)
    env['FACTORFORGE_ROOT'] = str(runtime_root)
    subprocess.run(cmd, check=True, env=env)


def current_git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_s3_text(bucket: str, key: str, payload: dict) -> None:
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
        temp_path = f.name
    try:
        run(['aws', 's3', 'cp', temp_path, f's3://{bucket}/{key}', '--content-type', 'application/json'])
    finally:
        Path(temp_path).unlink(missing_ok=True)


def read_json_source(source: str) -> dict:
    if source.startswith('s3://'):
        temp_download = Path(tempfile.gettempdir()) / f'factorforge-latest-{utc_ts()}.json'
        run(['aws', 's3', 'cp', source, str(temp_download)])
        try:
            return json.loads(temp_download.read_text(encoding='utf-8'))
        finally:
            temp_download.unlink(missing_ok=True)
    return json.loads(Path(source).expanduser().read_text(encoding='utf-8'))


def resolve_bundle_source(source: str) -> tuple[str, dict | None]:
    if source.endswith('.json') or source.startswith('latest:'):
        latest_source = source.removeprefix('latest:')
        latest = read_json_source(latest_source)
        bundle_uri = latest.get('bundle_uri')
        if not bundle_uri:
            raise SystemExit(f'latest manifest missing bundle_uri: {latest_source}')
        return bundle_uri, latest
    return source, None


def safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in tar.getmembers():
        dest = (target / member.name).resolve()
        if not str(dest).startswith(str(root) + os.sep) and dest != root:
            raise SystemExit(f'Unsafe path in bundle: {member.name}')
    tar.extractall(target)


def action_for_destination(rel: str, dst: Path, allow_official_overwrite: bool) -> str:
    if not dst.exists():
        return 'create'
    protected = rel.startswith(PROTECTED_OVERWRITE_PREFIXES)
    if protected:
        return 'overwrite' if allow_official_overwrite else 'overwrite-blocked'
    return 'skip'


def serializable_args(args: argparse.Namespace) -> dict:
    payload = {}
    for key, value in vars(args).items():
        if callable(value):
            continue
        payload[key] = str(value) if isinstance(value, Path) else value
    return payload


def write_sync_audit(
    base_root: Path,
    args: argparse.Namespace,
    bundle_source: str,
    planned: list[dict],
    manifest: dict,
    latest_manifest: dict | None = None,
) -> Path:
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
        'command_args': serializable_args(args),
        'source_bundle': bundle_source,
        'latest_manifest': latest_manifest,
        'bundle_manifest': manifest,
        'planned_changes': planned,
        'changed_files': changed,
        'skipped_files': skipped,
        'overwritten_files': overwritten,
    }
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit_path


def cmd_bundle(args: argparse.Namespace) -> int:
    if args.update_latest and not args.upload:
        raise SystemExit('--update-latest requires --upload so latest.json can point to a durable S3 bundle')

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
            'schema_version': 'factorforge_knowledge_bundle_v1',
            'created_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'source_role': args.source_role,
            'hostname': socket.gethostname(),
            'git_commit': current_git_commit(),
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

    bundle_sha256 = sha256_file(out)
    bundle_size = out.stat().st_size
    print(f'[BUNDLE] {out}')
    print(f'[FILES] {len(files)}')
    print(f'[SHA256] {bundle_sha256}')

    if args.upload:
        key = f"{args.prefix.rstrip('/')}/{out.name}"
        run(['aws', 's3', 'cp', str(out), f's3://{args.bucket}/{key}'])
        bundle_uri = f's3://{args.bucket}/{key}'
        print(f'[S3] {bundle_uri}')
        if args.update_latest:
            latest_key = f"{args.prefix.rstrip('/')}/{args.latest_name}"
            latest_payload = {
                'schema_version': 'factorforge_knowledge_latest_v1',
                'created_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'source_role': args.source_role,
                'hostname': socket.gethostname(),
                'git_commit': current_git_commit(),
                'bucket': args.bucket,
                'prefix': args.prefix.rstrip('/'),
                'bundle_key': key,
                'bundle_uri': bundle_uri,
                'sha256': bundle_sha256,
                'size_bytes': bundle_size,
                'file_count': len(files),
                'include': include,
                'runtime_root': str(runtime_root),
                'objects_root': str(objects_root),
            }
            write_s3_text(args.bucket, latest_key, latest_payload)
            print(f'[LATEST] s3://{args.bucket}/{latest_key}')
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    runtime_root = resolve_runtime_root(args.runtime_root)
    base_root = resolve_objects_root(runtime_root).parent

    source, latest_manifest = resolve_bundle_source(args.source)
    temp_download = None
    if source.startswith('s3://'):
        temp_download = Path(tempfile.gettempdir()) / Path(source).name
        run(['aws', 's3', 'cp', source, str(temp_download)])
        bundle_path = temp_download
    else:
        bundle_path = Path(source).expanduser()

    expected_sha = (latest_manifest or {}).get('sha256')
    if expected_sha:
        actual_sha = sha256_file(bundle_path)
        if actual_sha != expected_sha:
            raise SystemExit(f'BLOCK_FACTORFORGE_KNOWLEDGE_BUNDLE_SHA256_MISMATCH expected={expected_sha} actual={actual_sha}')
        print(f'[VERIFY_SHA256] {actual_sha}')

    with tempfile.TemporaryDirectory(prefix='ff-knowledge-apply-') as td:
        stage = Path(td) / 'extract'
        stage.mkdir(parents=True, exist_ok=True)
        with tarfile.open(bundle_path, 'r:gz') as tar:
            safe_extract(tar, stage)
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

        audit_path = write_sync_audit(base_root, args, source, planned, manifest, latest_manifest)
        print(f'[AUDIT] {audit_path}')

    if args.rebuild_index:
        run_with_factorforge_root(['python3', str(REPO_ROOT / 'scripts' / 'build_factorforge_retrieval_index.py')], base_root)
        print('[REBUILD] retrieval index')
    if args.export_obsidian:
        run_with_factorforge_root(['python3', str(REPO_ROOT / 'scripts' / 'export_factorforge_obsidian.py')], base_root)
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
    p_bundle.add_argument('--source-role', default='local', choices=['mac_authoritative', 'ec2_results', 'local'])
    p_bundle.add_argument('--update-latest', action='store_true', help='After S3 upload, write latest.json pointing to this immutable bundle.')
    p_bundle.add_argument('--latest-name', default='latest.json')
    p_bundle.add_argument('--include', nargs='*', choices=sorted(KNOWLEDGE_SPECS.keys()))
    p_bundle.set_defaults(func=cmd_bundle)

    p_apply = sub.add_parser('apply')
    p_apply.add_argument('--runtime-root')
    p_apply.add_argument('--source', required=True, help='Local bundle path, s3:// bundle URI, or latest manifest JSON path/s3:// URI')
    p_apply.add_argument('--apply', action='store_true', help='Actually write planned creates. Default is dry-run.')
    p_apply.add_argument('--allow-official-overwrite', action='store_true', help='Allow overwriting protected official/case/handoff/validation records when a future overwrite path is enabled.')
    p_apply.add_argument('--rebuild-index', action='store_true')
    p_apply.add_argument('--export-obsidian', action='store_true')
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
