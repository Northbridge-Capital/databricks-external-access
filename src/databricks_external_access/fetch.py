"""Fetch a table (or a slice of it) to a local Parquet file, without Databricks compute.

How it works: Unity Catalog vends short-lived read credentials plus the table's storage
path (`temporary-table-credentials`); DuckDB's Delta extension reads that path directly and
writes the result as Parquet, which every dataframe framework can load.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb
from databricks.sdk.errors import BadRequest
from databricks.sdk.service.catalog import (
    DataSourceFormat,
    GenerateTemporaryTableCredentialResponse,
    TableInfo,
    TableOperation,
    TableType,
)

from . import _workspace
from ._workspace import Error, explain, table_info

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
    """
    info = table_info(name)
    _require_readable(info)
    credentials = _credentials(info)
    aws = credentials.aws_temp_credentials
    if aws is None or credentials.url is None:
        raise Error(f"Databricks returned no AWS read credentials for {name}.")
    with explain(f"reading the metastore region for {name}"):
        region = _workspace.client().metastores.summary().region

    with duckdb.connect() as con:
        con.execute("INSTALL delta; LOAD delta; INSTALL httpfs; LOAD httpfs")
        con.execute(
            "CREATE SECRET (TYPE s3, KEY_ID ?, SECRET ?, SESSION_TOKEN ?, REGION ?, SCOPE ?)",
            [aws.access_key_id, aws.secret_access_key, aws.session_token, region, credentials.url],
        )
        files, size = _storage_size(con, credentials.url)
        print(
            f"{name}: {files} Parquet files, {_human(size)} on storage "
            "(whole table; a slice reads less). Fetching...",
            file=sys.stderr,
            flush=True,
        )

        physical = {
            row[0] for row in con.execute(_scan("DESCRIBE SELECT *"), [credentials.url]).fetchall()
        }
        keep = columns if columns is not None else [str(c.name) for c in info.columns or []]
        predicates = [f for col, f in _BOOKKEEPING_FILTERS.items() if col in physical]
        if where:
            predicates.append(f"({where})")
        query = _scan(f"SELECT {', '.join(_quote(c) for c in keep)}")
        if predicates:
            query += f" WHERE {' AND '.join(predicates)}"
        if limit is not None:
            query += f" LIMIT {int(limit)}"

        directory = Path(dest)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.parquet"
        partial = target.with_name(target.name + ".part")
        try:
            con.execute(
                f"COPY ({query}) TO ? (FORMAT parquet, COMPRESSION zstd)",
                [credentials.url, str(partial)],
            )
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target


def _require_readable(info: TableInfo) -> None:
    if info.table_type not in _READABLE_KINDS or info.data_source_format not in _READABLE_FORMATS:
        kind = info.table_type.value if info.table_type else "unknown"
        fmt = info.data_source_format.value if info.data_source_format else "none"
        raise Error(
            f"{info.full_name} cannot be fetched: it is a {kind} table in {fmt} format, and only "
            "Delta tables, streaming tables and materialized views can be read from outside "
            "Databricks."
        )


def _credentials(info: TableInfo) -> GenerateTemporaryTableCredentialResponse:
    with explain(f"requesting read credentials for {info.full_name}"):
        try:
            api = _workspace.client().temporary_table_credentials
            return api.generate_temporary_table_credentials(
                table_id=info.table_id, operation=TableOperation.READ
            )
        except BadRequest as e:
            raise Error(
                f"{info.full_name} cannot be read from outside Databricks: {e} For pipeline "
                "tables, the owning pipeline must set pipelines.externalMetadata.enabled=true "
                "and run an update."
            ) from e


def _storage_size(con: duckdb.DuckDBPyConnection, url: str) -> tuple[int, int]:
    """Number and total bytes of the Parquet files in the table's current Delta snapshot."""
    rows = con.execute("SELECT data_file FROM delta_list_files(?)", [url]).fetchall()
    files = [row[0] for row in rows]
    if not files:
        return 0, 0
    total = con.execute("SELECT sum(size) FROM read_blob(?)", [files]).fetchall()[0][0]
    return len(files), int(total)


def _scan(select: str) -> str:
    return f"{select} FROM delta_scan(?)"


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"
