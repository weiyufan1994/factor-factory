"""Compatibility import; implementation lives in factor_factory.step5."""

from factor_factory.step5 import (
    load_json,
    write_json,
    ensure_dir,
    init_archive_dir,
    copy_file_if_exists,
    copy_many_preserve_existing,
    normalize_archive_subdirs,
    check_file_exists,
    check_archive_dir_nonempty,
    check_final_status_enum,
    check_archive_paths_exist,
    check_no_placeholder_text,
)

__all__ = [
    "load_json",
    "write_json",
    "ensure_dir",
    "init_archive_dir",
    "copy_file_if_exists",
    "copy_many_preserve_existing",
    "normalize_archive_subdirs",
    "check_file_exists",
    "check_archive_dir_nonempty",
    "check_final_status_enum",
    "check_archive_paths_exist",
    "check_no_placeholder_text"
]
