from __future__ import annotations


class DataApiError(Exception):
    """Base class for Factor Data API errors."""


class DataCatalogNotFound(DataApiError):
    """Catalog path could not be resolved or does not exist."""


class DataSetNotFound(DataApiError):
    """Requested dataset is not registered in the catalog."""


class DataFieldUnavailable(DataApiError):
    """Requested field cannot be resolved from the dataset schema."""


class DataQueryInvalid(DataApiError):
    """Query is invalid before backend access."""


class DataBackendUnavailable(DataApiError):
    """Backend dependency or storage access is unavailable."""


class DataValidationError(DataApiError):
    """Returned data failed validation."""
