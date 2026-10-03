"""Identify the executing checkout or an explicitly inventoried source archive.

This is local build provenance, not Host admission or a signature service.
Never infer a release from cwd, a parent Git repository, or an arbitrary env SHA.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

SOURCE_VERSION_FILE = 'factorforge_source_version.json'
SOURCE_VERSION_SCHEMA = 'factorforge_source_version_v1'


def _root(value: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('SOURCE_VERSION_ABSOLUTE_ROOT_REQUIRED')
    return path.resolve()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit(value) -> str:
    if not isinstance(value, str) or re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is None:
        raise ValueError('SOURCE_VERSION_COMMIT_INVALID')
    return value


def _source_file(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or Path(raw).is_absolute() or '..' in Path(raw).parts:
        raise ValueError('SOURCE_VERSION_FILE_PATH_INVALID')
    path = root / raw
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f'SOURCE_VERSION_FILE_UNREADABLE:{raw}')
    return path


def verify_source_archive(repo_root: Path, proof_path: Path | None = None) -> dict:
    """Verify a package marker, or an explicitly selected historical assembly record."""
    root = _root(repo_root)
    proof = Path(proof_path) if proof_path is not None else root / SOURCE_VERSION_FILE
    if not proof.is_absolute() or proof.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('SOURCE_VERSION_PROOF_INVALID')
    raw = proof.read_bytes()
    record = json.loads(raw)
    if not isinstance(record, dict) or not isinstance(record.get('files'), dict):
        raise ValueError('SOURCE_VERSION_INVENTORY_REQUIRED')
    commit = _commit(record.get('framework_commit'))
    if proof_path is None:
        if record.get('schema_version') != SOURCE_VERSION_SCHEMA:
            raise ValueError('SOURCE_VERSION_SCHEMA_INVALID')
        files = record['files']
    else:
        if ((Path(record.get('release', '')) / 'factor-factory').resolve() != root
                or record.get('archive_source') != 'git archive ' + commit):
            raise ValueError('SOURCE_VERSION_RELEASE_BINDING_MISMATCH')
        files = {key[len('factor-factory/'):]: digest for key, digest in record['files'].items()
                 if key.startswith('factor-factory/')}
    if not {'factor_factory/runtime_context.py', 'skills/factor-forge-step4/scripts/run_step4.py'} <= set(files):
        raise ValueError('SOURCE_VERSION_PRODUCER_INVENTORY_MISSING')
    for name, expected in files.items():
        if not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None:
            raise ValueError('SOURCE_VERSION_FILE_DIGEST_INVALID')
        if _sha(_source_file(root, name)) != expected:
            raise ValueError(f'SOURCE_VERSION_FILE_CHANGED:{name}')
    if proof.read_bytes() != raw:
        raise ValueError('SOURCE_VERSION_PROOF_CHANGED')
    return {'commit': commit, 'kind': 'source_archive', 'verified_file_count': len(files),
            'proof_path': str(proof), 'proof_sha256': hashlib.sha256(raw).hexdigest()}


def write_source_archive_version(repo_root: Path, commit: str, source_files: list[str]) -> Path:
    """Packaging entry: call on a fresh git-archive export with its exact member list."""
    root = _root(repo_root)
    commit = _commit(commit)
    if not source_files or len(source_files) != len(set(source_files)) or SOURCE_VERSION_FILE in source_files:
        raise ValueError('SOURCE_VERSION_EXPLICIT_FILE_LIST_REQUIRED')
    files = {name: _sha(_source_file(root, name)) for name in sorted(source_files)}
    if not {'factor_factory/runtime_context.py', 'skills/factor-forge-step4/scripts/run_step4.py'} <= set(files):
        raise ValueError('SOURCE_VERSION_PRODUCER_INVENTORY_MISSING')
    target = root / SOURCE_VERSION_FILE
    with target.open('x') as stream:
        json.dump({'schema_version': SOURCE_VERSION_SCHEMA, 'framework_commit': commit,
                   'files': files}, stream, ensure_ascii=False, indent=2)
    return target


def current_source_commit(repo_root: Path) -> str:
    root = _root(repo_root)
    if (root / SOURCE_VERSION_FILE).exists():
        return verify_source_archive(root)['commit']
    # Worktrees have a .git file; ordinary checkouts have a .git directory.
    if not (root / '.git').exists():
        return 'unknown'
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root,
                             check=False, text=True, capture_output=True)
        if top.returncode or Path(top.stdout.strip()).resolve() != root:
            return 'unknown'
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                              check=False, text=True, capture_output=True)
        return _commit(head.stdout.strip()) if head.returncode == 0 else 'unknown'
    except (OSError, ValueError):
        return 'unknown'
