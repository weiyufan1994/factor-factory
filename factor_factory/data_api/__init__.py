"""Catalog-first Data API consumer boundary for Factor Forge."""

from .client import DataApiClient, default_catalog_path, fetch_data_api_dataset, resolve_data_api_dataset

__all__ = [
    "DataApiClient",
    "default_catalog_path",
    "fetch_data_api_dataset",
    "resolve_data_api_dataset",
]
