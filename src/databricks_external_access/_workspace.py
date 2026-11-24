"""Workspace connection and error translation shared by browsing and fetching."""

from __future__ import annotations

import os
from collections.abc import Iterator
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
TOKEN_CACHE = "~/.config/databricks-sdk-py/oauth"


def login(host: str) -> None:
    """Remember the workspace (e.g. `https://dbc-1234abcd-5678.cloud.databricks.com`) and sign in.

    Run once per machine; later sessions reuse the saved workspace. The environment variable
    `DATABRICKS_HOST` overrides it. The workspace is saved only once sign-in has succeeded,
    so a mistyped URL never replaces a working one.
    """
    host = _normalize(host)
    WorkspaceClient(host=host, auth_type="external-browser")
    path = Path(SAVED_HOST).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(host + "\n")
    client.cache_clear()


def _host() -> str:
    saved = Path(SAVED_HOST).expanduser()
    host = os.environ.get("DATABRICKS_HOST") or (saved.read_text() if saved.exists() else "")
    if not host.strip():
        raise Error(
            "No workspace configured. Run databricks_external_access.login("
            "'https://<your-workspace>.cloud.databricks.com') once, or set DATABRICKS_HOST."
        )
    return _normalize(host)


def _normalize(host: str) -> str:
    host = host.strip().rstrip("/")
    if "://" not in host:
        host = f"https://{host}"
    if not host.startswith("https://"):
        raise Error(f"The workspace URL must use https://, got {host!r}.")
    return host


@cache
def client() -> WorkspaceClient:
    """Sign in to the configured workspace with the SDK's browser OAuth flow.

    Your identity provider (e.g. Google or Okta SSO) does the authentication. The first
    call opens a browser; the SDK caches and refreshes the token afterwards. This is also
    where a future Databricks Connect session would take its auth from (`client().config`).
    """
    return WorkspaceClient(host=_host(), auth_type="external-browser")


def table_info(name: str) -> TableInfo:
    with explain(f"looking up {name}"):
        return client().tables.get(name)


@contextmanager
def explain(action: str) -> Iterator[None]:
    """Turn the Databricks failures people actually hit into actionable errors."""
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
    """The server's message without the SDK's appended `Config: host=...` diagnostics."""
    return str(error).split(" Config:")[0]
