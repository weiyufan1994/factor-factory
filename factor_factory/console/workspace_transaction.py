from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_THREAD_STATE = threading.local()


def _lock_identity(state_root: Path, workspace: Path) -> str:
    canonical_state_root = state_root.resolve(strict=False)
    canonical_workspace = workspace.resolve(strict=True)
    identity_seed = f"{canonical_state_root}\0{canonical_workspace}".encode("utf-8")
    return hashlib.sha256(identity_seed).hexdigest()


def _process_lock(identity: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(identity, threading.RLock())


def _thread_locks() -> dict[str, tuple[int, int]]:
    locks = getattr(_THREAD_STATE, "locks", None)
    if locks is None:
        locks = {}
        _THREAD_STATE.locks = locks
    return locks


def _state_root_is_safe(state_root: Path, *, allow_missing: bool) -> bool:
    try:
        metadata = state_root.lstat()
    except FileNotFoundError:
        return allow_missing
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and not metadata.st_mode & 0o002
    )


def workspace_transaction_lock_held(state_root: Path, workspace: Path) -> bool:
    if not _state_root_is_safe(state_root, allow_missing=False):
        return False
    identity = _lock_identity(state_root, workspace)
    return identity in _thread_locks()


def _open_transaction_lock(
    state_root: Path,
    identity: str,
    *,
    error_code: str,
) -> int:
    try:
        state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if state_root.is_symlink() or not state_root.is_dir():
            raise RuntimeError(
                f"{error_code}: workspace transaction state root is unsafe"
            )
        root = state_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            f"{error_code}: workspace transaction state root is unavailable"
        ) from exc
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    root_descriptor = -1
    lock_root_descriptor = -1
    try:
        root_descriptor = os.open(root, directory_flags)
        root_metadata = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or root_metadata.st_mode & 0o002
        ):
            raise RuntimeError(
                f"{error_code}: workspace transaction state root is unsafe"
            )
        try:
            os.mkdir("workspace-promotion-locks", 0o700, dir_fd=root_descriptor)
            os.fsync(root_descriptor)
        except FileExistsError:
            pass
        lock_root_descriptor = os.open(
            "workspace-promotion-locks",
            directory_flags,
            dir_fd=root_descriptor,
        )
        directory_metadata = os.fstat(lock_root_descriptor)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != os.geteuid()
            or directory_metadata.st_mode & 0o077
        ):
            raise RuntimeError(
                f"{error_code}: workspace transaction lock root is unsafe"
            )
        descriptor = os.open(
            f"{identity}.lock",
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=lock_root_descriptor,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
        ):
            os.close(descriptor)
            raise RuntimeError(
                f"{error_code}: workspace transaction lock is unsafe"
            )
        os.fchmod(descriptor, 0o600)
        return descriptor
    except OSError as exc:
        raise RuntimeError(
            f"{error_code}: workspace transaction lock is unavailable"
        ) from exc
    finally:
        if lock_root_descriptor >= 0:
            os.close(lock_root_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)


@contextmanager
def workspace_transaction_lock(
    state_root: Path,
    workspace: Path,
    *,
    error_code: str,
) -> Iterator[None]:
    if not _state_root_is_safe(state_root, allow_missing=True):
        raise RuntimeError(
            f"{error_code}: workspace transaction state root is unsafe"
        )
    identity = _lock_identity(state_root, workspace)
    process_lock = _process_lock(identity)
    process_lock.acquire()
    thread_locks = _thread_locks()
    try:
        existing = thread_locks.get(identity)
        if existing is not None:
            depth, descriptor = existing
            thread_locks[identity] = (depth + 1, descriptor)
            try:
                yield
            finally:
                current_depth, current_descriptor = thread_locks[identity]
                thread_locks[identity] = (current_depth - 1, current_descriptor)
            return

        descriptor = _open_transaction_lock(
            state_root,
            identity,
            error_code=error_code,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            thread_locks[identity] = (1, descriptor)
            try:
                yield
            finally:
                depth, current_descriptor = thread_locks.pop(identity)
                if depth != 1 or current_descriptor != descriptor:
                    raise RuntimeError(
                        f"{error_code}: workspace transaction lock state is invalid"
                    )
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    finally:
        process_lock.release()
