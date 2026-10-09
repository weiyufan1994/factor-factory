"""Compatibility import; implementation lives in factor_factory.step5.archiver."""

from factor_factory.step5.archiver import (
    _resolve_factorforge_root,
    init_archive_dir,
    copy_file_if_exists,
    copy_many_preserve_existing,
    normalize_archive_subdirs,
)

__all__ = [
    "_resolve_factorforge_root",
    "init_archive_dir",
    "copy_file_if_exists",
    "copy_many_preserve_existing",
    "normalize_archive_subdirs"
]
