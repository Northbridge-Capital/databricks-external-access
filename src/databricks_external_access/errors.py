"""The errors this package raises. Catch `Error` for any of them, or a subclass for one case."""

from __future__ import annotations


class Error(Exception):
    """A failure the caller can act on; the message says how."""


class NotSignedIn(Error):
    """Databricks rejected the sign-in token."""


class AccessDenied(Error):
    """You lack a grant: `SELECT` on the table or `EXTERNAL USE SCHEMA` on its schema."""


class NotFound(Error):
    """The object does not exist, or you cannot see it."""


class UnsupportedTable(Error):
    """The table cannot be read from outside Databricks (kind, format, cloud or pipeline setup)."""
