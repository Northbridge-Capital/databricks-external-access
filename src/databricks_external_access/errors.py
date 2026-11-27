"""The errors this package raises. Catch ``Error`` for any of them, or a subclass for one case."""

from __future__ import annotations


class Error(Exception):
    """A failure the caller can act on; its message says how."""


class NotSignedIn(Error):
    """A sign-in that Databricks rejected."""


class AccessDenied(Error):
    """A missing grant: ``SELECT`` on the table or ``EXTERNAL USE SCHEMA`` on its schema."""


class NotFound(Error):
    """An object that does not exist, or that you cannot see."""


class UnsupportedTable(Error):
    """A table that cannot be read from outside Databricks (kind, format, cloud or pipeline)."""
