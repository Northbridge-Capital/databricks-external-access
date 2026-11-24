"""Reads a real table from your workspace.

Set DATABRICKS_TEST_TABLE (`catalog.schema.table`) and sign in once with
`databricks_external_access.login(...)`; otherwise this test skips itself. Point it at a
Lakeflow pipeline table if you can: those use the Delta features `deletionVectors` and
`v2Checkpoint` and have no storage location of their own, which is what client libraries
most often get wrong, so such a table is what catches a regression in DuckDB, its Delta
extension or the credentials API.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

import databricks_external_access as dc
from databricks_external_access._workspace import TOKEN_CACHE

TABLE = os.environ.get("DATABRICKS_TEST_TABLE", "")

signed_in = any(Path(TOKEN_CACHE).expanduser().glob("*.json"))
pytestmark = pytest.mark.skipif(
    not (signed_in and TABLE),
    reason="needs DATABRICKS_TEST_TABLE and a previous login()",
)


def test_browse_and_fetch_a_real_pipeline_table(tmp_path: Path):
    assert dc.catalogs()
    described = dc.describe(TABLE)
    assert described.columns

    path = dc.fetch(TABLE, limit=100, dest=tmp_path)

    result = duckdb.connect().execute(f"SELECT * FROM '{path.as_posix()}'")
    assert [column[0] for column in result.description] == [c.name for c in described.columns]
    assert len(result.fetchall()) == 100
