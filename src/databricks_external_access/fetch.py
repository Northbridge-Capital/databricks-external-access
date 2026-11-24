"""Fetch a table (or a slice of it) to a local Parquet file, without Databricks compute.

How it works: Unity Catalog vends short-lived read credentials plus the table's storage
path (`temporary-table-credentials`); DuckDB's Delta extension reads that path directly and
writes the result as Parquet, which every dataframe framework can load.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import duckdb
from databricks.sdk.errors import BadRequest
from databricks.sdk.service.catalog import (
    AwsCredentials,
    DataSourceFormat,
    TableInfo,
    TableOperation,
    TableType,
)

from . import _workspace
from ._workspace import explain, table_info
from .errors import UnsupportedTable

# Unity Catalog can vend credentials only for these; views, foreign and shared
# (DELTASHARING) tables have no storage path to read. Pipeline tables report no format.
_READABLE_KINDS = {
    TableType.MANAGED,
    TableType.EXTERNAL,
    TableType.STREAMING_TABLE,
    TableType.MATERIALIZED_VIEW,
}
_READABLE_FORMATS = {DataSourceFormat.DELTA, None}

# Tables written by pipeline `apply_changes` keep bookkeeping columns in storage; the logical
# table hides them and drops deleted and expectation-failing rows. Unity Catalog records this
# as the table's `spark.internal.streaming_table.reconciliation_query`; these are its filters.
_BOOKKEEPING_FILTERS = {
    "__DeleteVersion": "__DeleteVersion IS NULL",
    "__MEETS_DROP_EXPECTATIONS": "(__MEETS_DROP_EXPECTATIONS IS NULL OR __MEETS_DROP_EXPECTATIONS)",
}


def fetch(
    name: str,
    *,
    columns: Sequence[str] | None = None,
    where: str | None = None,
    limit: int | None = None,
    dest: Path | str = "data",
) -> Path:
    """Write `catalog.schema.table` to `<dest>/<name>.parquet` and return that path.

    Prints the table's size on storage to stderr before reading any data.

    Args:
        name: Full table name, `catalog.schema.table`.
        columns: Columns to keep (default: all).
        where: DuckDB SQL predicate selecting rows, e.g. `"ticker = 'NVDA'"`. It runs on your
            machine with your own credentials, so it is not sanitised.
        limit: Maximum number of rows.
        dest: Directory to write into; created if missing.

    Raises:
        UnsupportedTable: The table cannot be read from outside Databricks.
        AccessDenied: You lack `SELECT` on the table or `EXTERNAL USE SCHEMA` on its schema.
        NotFound: The table does not exist, or you cannot see it.
        NotSignedIn: Databricks rejected your sign-in.
    """
    info = table_info(name)
    _require_readable(info)
    url, aws = _credentials(info)
    full_name = str(info.full_name)
    with _connect(url, aws, _region(full_name)) as con:
        _announce_size(con, full_name, url)
        keep = columns if columns is not None else [str(c.name) for c in info.columns or []]
        query = _select(con, url, keep, where, limit)
        return _write(con, query, url, Path(dest) / f"{full_name}.parquet")


def _require_readable(info: TableInfo) -> None:
    if info.table_type not in _READABLE_KINDS or info.data_source_format not in _READABLE_FORMATS:
        kind = info.table_type.value if info.table_type else "unknown"
        fmt = info.data_source_format.value if info.data_source_format else "none"
        raise UnsupportedTable(
            f"{info.full_name} cannot be fetched: it is a {kind} table in {fmt} format, and only "
            "Delta tables, streaming tables and materialized views can be read from outside "
            "Databricks."
        )


def _credentials(info: TableInfo) -> tuple[str, AwsCredentials]:
    """The table's storage path and short-lived read credentials for it."""
    with explain(f"requesting read credentials for {info.full_name}"):
        try:
            api = _workspace.client().temporary_table_credentials
            vended = api.generate_temporary_table_credentials(
                table_id=info.table_id, operation=TableOperation.READ
            )
        except BadRequest as e:
            raise UnsupportedTable(
                f"{info.full_name} cannot be read from outside Databricks: {e} For pipeline "
                "tables, the owning pipeline must set pipelines.externalMetadata.enabled=true "
                "and run an update."
            ) from e
    if vended.aws_temp_credentials is None or vended.url is None:
        raise UnsupportedTable(
            f"Databricks returned no AWS read credentials for {info.full_name}; only AWS "
            "workspaces are supported."
        )
    return vended.url, vended.aws_temp_credentials


def _region(full_name: str) -> str:
    with explain(f"reading the metastore region for {full_name}"):
        return str(_workspace.client().metastores.summary().region)


def _connect(url: str, aws: AwsCredentials, region: str) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB that can read `url` with the given credentials."""
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta; INSTALL httpfs; LOAD httpfs")
    con.execute(
        "CREATE SECRET (TYPE s3, KEY_ID ?, SECRET ?, SESSION_TOKEN ?, REGION ?, SCOPE ?)",
        [aws.access_key_id, aws.secret_access_key, aws.session_token, region, url],
    )
    return con


def _announce_size(con: duckdb.DuckDBPyConnection, full_name: str, url: str) -> None:
    """Tell the user how much the table holds on storage, before any data is read."""
    rows = con.execute("SELECT data_file FROM delta_list_files(?)", [url]).fetchall()
    files = [row[0] for row in rows]
    size = 0
    if files:
        size = int(con.execute("SELECT sum(size) FROM read_blob(?)", [files]).fetchall()[0][0])
    print(
        f"{full_name}: {len(files)} Parquet files, {_human(size)} on storage "
        "(whole table; a slice reads less). Fetching...",
        file=sys.stderr,
        flush=True,
    )


def _select(
    con: duckdb.DuckDBPyConnection,
    url: str,
    columns: Sequence[str],
    where: str | None,
    limit: int | None,
) -> str:
    """The query for the logical table: declared columns, bookkeeping rows out, then the slice."""
    rows = con.execute("DESCRIBE SELECT * FROM delta_scan(?)", [url]).fetchall()
    physical = {row[0] for row in rows}
    predicates = [f for col, f in _BOOKKEEPING_FILTERS.items() if col in physical]
    if where:
        predicates.append(f"({where})")
    query = f"SELECT {', '.join(_quote(c) for c in columns)} FROM delta_scan(?)"
    if predicates:
        query += f" WHERE {' AND '.join(predicates)}"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    return query


def _write(con: duckdb.DuckDBPyConnection, query: str, url: str, target: Path) -> Path:
    """Run `query` into `target` through a unique temporary file, so a failure leaves nothing."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, partial = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".part")
    os.close(handle)
    try:
        con.execute(f"COPY ({query}) TO ? (FORMAT parquet, COMPRESSION zstd)", [url, partial])
        Path(partial).replace(target)
    finally:
        Path(partial).unlink(missing_ok=True)
    return target


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"
