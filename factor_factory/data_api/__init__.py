"""Catalog-first Data API consumer boundary for Factor Forge.

The independent ``factorforge_data_api`` distribution is only needed when a
caller actually resolves or fetches a dataset.  Keeping this package boundary
lazy lets offline planning and knowledge tooling import Factor Forge without
also installing a data-provider runtime.
"""

from __future__ import annotations

from typing import Any


def _client() -> Any:
    """Load the optional independent Data API adapter on first use."""
    try:
        from . import client
    except ModuleNotFoundError as exc:
        # Do not turn an error from a dependency *inside* the independent
        # package into a misleading installation hint.
        if exc.name == "factorforge_data_api":
            raise ModuleNotFoundError(
                "Data API access requires the optional 'factorforge_data_api' "
                "distribution. Install/configure that distribution before "
                "calling Factor Forge Data API functions."
            ) from exc
        raise
    return client


def default_catalog_path() -> Any:
    return _client().default_catalog_path()


def fetch_data_api_dataset(*args: Any, **kwargs: Any) -> Any:
    return _client().fetch_data_api_dataset(*args, **kwargs)


def resolve_data_api_dataset(*args: Any, **kwargs: Any) -> Any:
    return _client().resolve_data_api_dataset(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "DataApiClient":
        return _client().DataApiClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DataApiClient",
    "default_catalog_path",
    "fetch_data_api_dataset",
    "resolve_data_api_dataset",
]
