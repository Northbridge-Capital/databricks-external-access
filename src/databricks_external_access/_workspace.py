"""Workspace connection and error translation shared by browsing and fetching."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from functools import cache
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk import errors as sdk
from databricks.sdk.service.catalog import TableInfo

from .errors import AccessDenied, Error, NotFound, NotSignedIn

# Where `login` remembers the workspace URL.
SAVED_HOST = "~/.config/databricks-external-access/host"
# Where the SDK caches the OAuth tokens of the browser sign-in.
TOKEN_CACHE = "~/.config/databricks-sdk-py/oauth"  # noqa: S105 -- a path, not a credential


def login(host: str) -> None:
    """Remember the workspace and sign in.

    Run once per machine; later sessions reuse the saved workspace, and the environment
    variable ``DATABRICKS_HOST`` overrides it. The workspace is saved only once sign-in has
    succeeded, so a mistyped URL never replaces a working one.

    Parameters
    ----------
    host
        Workspace URL. Any ``https://`` URL works, including a custom workspace URL such as
        ``https://data.example.com``; a missing scheme is added.

    Raises
    ------
    Error
        The URL does not use ``https://``.
    """
    host = _normalize(host)
    WorkspaceClient(host=host, auth_type="external-browser")
    path = Path(SAVED_HOST).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(host + "\n")
    client.cache_clear()


def _host() -> str:
    """Return the workspace URL from ``DATABRICKS_HOST`` or the saved one."""
    saved = Path(SAVED_HOST).expanduser()
    host = os.environ.get("DATABRICKS_HOST") or (saved.read_text() if saved.exists() else "")
    if not host.strip():
        raise Error(
            "No workspace configured. Run databricks_external_access.login("
            "'<your workspace URL>') once, or set DATABRICKS_HOST."
        )
    return _normalize(host)


def _normalize(host: str) -> str:
    """Return ``host`` as an ``https://`` URL without a trailing slash."""
    host = host.strip().rstrip("/")
    if "://" not in host:
        host = f"https://{host}"
    if not host.startswith("https://"):
        raise Error(f"The workspace URL must use https://, got {host!r}.")
    return host


# Your identity provider (for example Google or Okta SSO) does the authentication. The first call
# opens a browser; the SDK caches and refreshes the token afterwards. A future Databricks Connect
# session would take its auth from `client().config`.
@cache
def client() -> WorkspaceClient:
    """Return the cached SDK client, signing in through the browser the first time."""
    return WorkspaceClient(host=_host(), auth_type="external-browser")


def table_info(name: str) -> TableInfo:
    """Look up a table's Unity Catalog info by its full name."""
    with explain(f"looking up {name}"):
        return client().tables.get(name)


@contextmanager
def explain(action: str) -> Generator[None]:
    """Translate the Databricks failures people actually hit into this package's errors."""
    try:
        yield
    except sdk.Unauthenticated as e:
        raise NotSignedIn(
            f"Databricks rejected your sign-in while {action}. Delete the cached tokens in "
            f"{TOKEN_CACHE} and retry; a browser window opens to sign in through your "
            "workspace's SSO."
        ) from e
    except sdk.PermissionDenied as e:
        raise AccessDenied(
            f"Access denied while {action}: {_message(e)} Reading a table from outside "
            "Databricks needs SELECT on the table and EXTERNAL USE SCHEMA on its schema; "
            "ask your Databricks admin for the missing grant."
        ) from e
    except sdk.NotFound as e:
        raise NotFound(
            f"Not found while {action}: {_message(e)} Unity Catalog also reports objects "
            "you cannot see as missing."
        ) from e


def _message(error: Exception) -> str:
    """Return an SDK error's message without its appended ``Config:`` diagnostics."""
    return str(error).split(" Config:")[0]
