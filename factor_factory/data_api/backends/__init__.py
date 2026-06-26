from .duckdb_backend import load_duckdb_file
from .local_file import load_local_file
from .s3_file import load_s3_file

__all__ = ['load_duckdb_file', 'load_local_file', 'load_s3_file']
