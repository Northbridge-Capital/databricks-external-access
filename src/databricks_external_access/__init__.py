"""Browse Databricks Unity Catalog and fetch tables to local Parquet files."""

from importlib.metadata import version

from ._workspace import login
from .browse import Column, Entry, Table, catalogs, describe, overview, schemas, tables
from .errors import AccessDenied, Error, NotFound, NotSignedIn, UnsupportedTable
from .fetch import fetch

__version__ = version("databricks-external-access")

__all__ = [
    "AccessDenied",
    "Column",
    "Entry",
    "Error",
    "NotFound",
    "NotSignedIn",
    "Table",
    "UnsupportedTable",
    "__version__",
    "catalogs",
    "describe",
    "fetch",
    "login",
    "overview",
    "schemas",
    "tables",
]
