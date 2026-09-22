from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Sequence


BLOCK_PRIVATE_JOB_ROOT_INVALID = "BLOCK_FACTORFORGE_PRIVATE_JOB_ROOT_INVALID"

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_SHARED_DIRECTORY_MODES = frozenset({0o700, 0o750, 0o770})
_PRIVATE_DIRECTORY_MODE = 0o700


class PrivateJobRootError(RuntimeError):
    pass


def _fail(reason: str) -> PrivateJobRootError:
    return PrivateJobRootError(f"{BLOCK_PRIVATE_JOB_ROOT_INVALID}:{reason}")


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _validate_directory_descriptor(
    descriptor: int,
    *,
    label: str,
    allowed_modes: frozenset[int],
) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) not in allowed_modes
    ):
        raise _fail(f"unsafe_{label}")


def _open_directory(
    path: Path,
    *,
    label: str,
    allowed_modes: frozenset[int],
) -> int:
    if path.is_symlink():
        raise _fail(f"unsafe_{label}")
    try:
        descriptor = os.open(path, _directory_flags())
    except OSError as exc:
        raise _fail(f"unsafe_{label}") from exc
    try:
        _validate_directory_descriptor(
            descriptor,
            label=label,
            allowed_modes=allowed_modes,
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _open_or_create_child_directory(
    parent_descriptor: int,
    component: str,
    *,
    label: str,
    mode: int,
    create: bool,
) -> int:
    if not _SAFE_COMPONENT.fullmatch(component) or component in {".", ".."}:
        raise _fail(f"unsafe_{label}_component")
    if create:
        try:
            os.mkdir(component, mode=mode, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _fail(f"unsafe_{label}") from exc
    try:
        descriptor = os.open(component, _directory_flags(), dir_fd=parent_descriptor)
    except OSError as exc:
        raise _fail(f"unsafe_{label}") from exc
    try:
        _validate_directory_descriptor(
            descriptor,
            label=label,
            allowed_modes=frozenset({mode}),
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def ensure_host_private_job_root(
    state_root: Path | str,
    job_id: str,
    *,
    create: bool = True,
) -> Path:
    """Resolve the one Host-private 0700 leaf below a shared Console state root.

    The Console state root and ``jobs`` directory may be shared with the service
    group (0750/0770), but a job leaf is private from its first creation.  An
    existing wider leaf is rejected and is never repaired with a late chmod.
    """

    state = Path(state_root).expanduser()
    state_descriptor = _open_directory(
        state,
        label="state_root",
        allowed_modes=_SHARED_DIRECTORY_MODES,
    )
    jobs_descriptor = -1
    job_descriptor = -1
    try:
        if create:
            try:
                os.mkdir("jobs", mode=0o770, dir_fd=state_descriptor)
            except FileExistsError:
                pass
            except OSError as exc:
                raise _fail("unsafe_jobs_root") from exc
        try:
            jobs_descriptor = os.open(
                "jobs", _directory_flags(), dir_fd=state_descriptor
            )
        except OSError as exc:
            raise _fail("unsafe_jobs_root") from exc
        _validate_directory_descriptor(
            jobs_descriptor,
            label="jobs_root",
            allowed_modes=_SHARED_DIRECTORY_MODES,
        )
        job_descriptor = _open_or_create_child_directory(
            jobs_descriptor,
            job_id,
            label="private_job_root",
            mode=_PRIVATE_DIRECTORY_MODE,
            create=create,
        )
    finally:
        if job_descriptor >= 0:
            os.close(job_descriptor)
        if jobs_descriptor >= 0:
            os.close(jobs_descriptor)
        os.close(state_descriptor)

    resolved_state = state.resolve(strict=True)
    job = resolved_state / "jobs" / job_id
    try:
        resolved_job = job.resolve(strict=True)
        resolved_job.relative_to(resolved_state / "jobs")
    except (OSError, ValueError) as exc:
        raise _fail("unsafe_private_job_root") from exc
    return resolved_job


def ensure_host_private_job_subdirectory(
    state_root: Path | str,
    job_id: str,
    components: Sequence[str],
    *,
    create: bool = True,
) -> Path:
    """Open/create an exact 0700 descendant of the private job leaf."""

    job = ensure_host_private_job_root(state_root, job_id, create=create)
    descriptor = _open_directory(
        job,
        label="private_job_root",
        allowed_modes=frozenset({_PRIVATE_DIRECTORY_MODE}),
    )
    current = job
    try:
        for component in components:
            child_descriptor = _open_or_create_child_directory(
                descriptor,
                component,
                label="private_job_subdirectory",
                mode=_PRIVATE_DIRECTORY_MODE,
                create=create,
            )
            os.close(descriptor)
            descriptor = child_descriptor
            current /= component
    finally:
        os.close(descriptor)
    return current.resolve(strict=True)
