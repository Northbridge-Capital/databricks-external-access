"""Reads real tables from your workspace.

Set DATABRICKS_TEST_TABLES to a comma-separated list of `catalog.schema.table` and sign in
once with `databricks_external_access.login(...)`; otherwise these tests skip themselves.

Cover more than one kind if you can: a Lakeflow streaming table written by `apply_changes` and a
Lakeflow materialized view. They use the Delta features `deletionVectors` and `v2Checkpoint`,
keep internal columns in storage and have no storage location of their own, which is what
client libraries most often get wrong, so they are what catches a regression in DuckDB, its
Delta extension or the credentials API.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

import databricks_external_access as dbx
from databricks_external_access._workspace import TOKEN_CACHE

TABLES = [t.strip() for t in os.environ.get("DATABRICKS_TEST_TABLES", "").split(",") if t.strip()]

signed_in = any(Path(TOKEN_CACHE).expanduser().glob("*.json"))
pytestmark = pytest.mark.skipif(
    not (signed_in and TABLES),
    reason="needs DATABRICKS_TEST_TABLES and a previous login()",
)


def test_browse():
    assert dbx.catalogs()


@pytest.mark.parametrize("table", TABLES)
def test_fetch_returns_exactly_the_declared_columns(table: str, tmp_path: Path):
    declared = [column.name for column in dbx.describe(table).columns]

    path = dbx.fetch(table, limit=100, dest=tmp_path)

    result = duckdb.connect().execute(f"SELECT * FROM '{path.as_posix()}'")
    assert [column[0] for column in result.description] == declared
    assert 0 < len(result.fetchall()) <= 100
