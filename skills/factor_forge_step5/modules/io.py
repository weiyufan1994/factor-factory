"""Compatibility import; implementation lives in factor_factory.step5.io."""

from factor_factory.step5.io import (
    load_json,
    write_json,
    ensure_dir,
)

__all__ = [
    "load_json",
    "write_json",
    "ensure_dir"
]
