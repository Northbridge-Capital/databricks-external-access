from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import raises, table_info
from databricks.sdk.errors import NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service.catalog import CatalogInfo, SchemaInfo

import databricks_external_access as dc
from databricks_external_access import _workspace


def test_catalogs_and_schemas(workspace: SimpleNamespace):
    workspace.catalogs.list = lambda: [CatalogInfo(name="dev", comment="Development")]
    workspace.schemas.list = lambda catalog: [
        SchemaInfo(full_name=f"{catalog}.silver", comment=None)
    ]

    assert dc.catalogs() == [dc.Entry("dev", "Development")]
    assert dc.schemas("dev") == [dc.Entry("dev.silver", None)]


def test_tables_and_describe_include_columns(workspace: SimpleNamespace):
    info = table_info()
    workspace.tables.list = lambda catalog, schema: (
        [info] if (catalog, schema) == ("dev", "silver") else []
    )
    workspace.tables.get = lambda _name: info
    expected = dc.Table(
        "dev.silver.prices",
        "STREAMING_TABLE",
        "dev.silver.prices comment",
        (
            dc.Column("ticker", "string", "ticker comment"),
            dc.Column("price", "string", "price comment"),
        ),
    )

    assert dc.tables("dev.silver") == [expected]
    assert dc.describe("dev.silver.prices") == expected


def test_tables_requires_catalog_and_schema(workspace: SimpleNamespace):
    with pytest.raises(dc.Error, match=r"catalog\.schema"):
        dc.tables("dev")


@pytest.mark.parametrize(
    ("failure", "error", "expected"),
    [
        (Unauthenticated("token invalid"), dc.NotSignedIn, "databricks-sdk-py/oauth"),
        (PermissionDenied("no access"), dc.AccessDenied, "EXTERNAL USE SCHEMA"),
        (NotFound("gone"), dc.NotFound, "cannot see"),
    ],
)
def test_databricks_failures_become_actionable_errors(
    workspace: SimpleNamespace, failure: Exception, error: type[dc.Error], expected: str
):
    workspace.catalogs.list = raises(failure)

    with pytest.raises(error, match=expected) as raised:
        dc.catalogs()

    assert isinstance(raised.value, dc.Error)


def test_error_drops_sdk_config_diagnostics(workspace: SimpleNamespace):
    failure = PermissionDenied("No SELECT on dev.x. Config: host=https://h, account_id=a")
    workspace.catalogs.list = raises(failure)

    with pytest.raises(dc.AccessDenied) as error:
        dc.catalogs()

    assert "No SELECT on dev.x." in str(error.value)
    assert "account_id" not in str(error.value)


@pytest.fixture
def saved_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config" / "host"
    monkeypatch.setattr(_workspace, "SAVED_HOST", str(path))
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    _workspace.client.cache_clear()
    return path


def test_login_saves_the_workspace_and_signs_in(saved_host: Path, monkeypatch: pytest.MonkeyPatch):
    signed_in_to: list[str] = []
    monkeypatch.setattr(
        _workspace, "WorkspaceClient", lambda host, auth_type: signed_in_to.append(host)
    )

    dc.login("dbc-1.cloud.databricks.com/")

    assert signed_in_to == ["https://dbc-1.cloud.databricks.com"]
    assert saved_host.read_text() == "https://dbc-1.cloud.databricks.com\n"
    _workspace.client.cache_clear()
    assert _workspace._host() == "https://dbc-1.cloud.databricks.com"


@pytest.mark.parametrize("host", ["http://dbc-1.cloud.databricks.com", "ftp://x"])
def test_workspace_url_must_use_https(saved_host: Path, host: str):
    with pytest.raises(dc.Error, match="https://"):
        dc.login(host)

    assert not saved_host.exists()


def test_failed_login_keeps_the_previous_workspace(
    saved_host: Path, monkeypatch: pytest.MonkeyPatch
):
    saved_host.parent.mkdir()
    saved_host.write_text("https://good\n")
    monkeypatch.setattr(_workspace, "WorkspaceClient", raises(RuntimeError("sign-in failed")))

    with pytest.raises(RuntimeError):
        dc.login("https://typo")

    assert saved_host.read_text() == "https://good\n"


def test_environment_overrides_the_saved_workspace(
    saved_host: Path, monkeypatch: pytest.MonkeyPatch
):
    saved_host.parent.mkdir()
    saved_host.write_text("https://saved\n")
    monkeypatch.setenv("DATABRICKS_HOST", "https://from-env/")

    assert _workspace._host() == "https://from-env"


def test_no_workspace_explains_how_to_configure(saved_host: Path):
    with pytest.raises(dc.Error, match=r"login\("):
        _workspace.client()


def test_overview_prints_a_tree_without_managed_catalogs(
    workspace: SimpleNamespace, capsys: pytest.CaptureFixture[str]
):
    workspace.catalogs.list = lambda: [
        CatalogInfo(name=n) for n in ("dev", "system", "ops", "samples")
    ]
    workspace.schemas.list = lambda catalog: [
        SchemaInfo(full_name=f"{catalog}.silver"),
        SchemaInfo(full_name=f"{catalog}.information_schema"),
    ]
    workspace.tables.list = lambda catalog, schema: [
        table_info(f"{catalog}.{schema}.prices"),
        table_info(f"{catalog}.{schema}.fx"),
    ]

    dc.overview()

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "dev"
    assert out[1] == "  silver  (2 tables)"
    assert out[2].startswith("    prices")
    assert "STREAMING_TABLE" in out[2]
    assert "dev.silver.prices comment" in out[2]
    assert out[4:6] == ["ops", "  silver  (2 tables)"]
    assert len(out) == 8  # no system, samples or information_schema


def test_overview_of_a_named_catalog_includes_everything_in_it(
    workspace: SimpleNamespace, capsys: pytest.CaptureFixture[str]
):
    workspace.schemas.list = lambda catalog: [SchemaInfo(full_name=f"{catalog}.information_schema")]
    workspace.tables.list = lambda catalog, schema: []

    dc.overview("system")

    assert capsys.readouterr().out.splitlines() == [
        "system",
        "  information_schema  (0 tables)",
    ]
