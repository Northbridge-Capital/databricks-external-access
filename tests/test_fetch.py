from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from conftest import SECRET, raises, serve, table_info
from databricks.sdk.errors import BadRequest, PermissionDenied
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from deltalake import write_deltalake

import databricks_external_access as dc
from databricks_external_access.fetch import _human


def read(path: Path, sql: str = "SELECT * FROM {}") -> list[tuple]:
    return duckdb.connect().execute(sql.format(f"'{path.as_posix()}'")).fetchall()


def test_fetch_writes_the_logical_table(
    workspace: SimpleNamespace,
    delta_table: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    serve(workspace, table_info(), delta_table)

    path = dc.fetch("dev.silver.prices", dest=tmp_path / "out")

    assert path == tmp_path / "out" / "dev.silver.prices.parquet"
    # Bookkeeping columns are hidden; the deleted and expectation-failing rows are dropped.
    assert read(path, "SELECT * FROM {} ORDER BY ticker") == [("AAA", "1"), ("DDD", "4")]
    output = capsys.readouterr()
    assert "dev.silver.prices: 1 Parquet files" in output.err
    assert SECRET not in output.out + output.err


def test_output_is_named_after_the_canonical_table_name(
    workspace: SimpleNamespace, delta_table: Path, tmp_path: Path
):
    serve(workspace, table_info(name="dev.silver.prices"), delta_table)

    path = dc.fetch("`dev`.`silver`.`PRICES`", dest=tmp_path / "out")

    assert path.name == "dev.silver.prices.parquet"  # not the caller's spelling, never a path


def test_fetch_slice(workspace: SimpleNamespace, delta_table: Path, tmp_path: Path):
    serve(workspace, table_info(), delta_table)

    path = dc.fetch("dev.silver.prices", columns=["price"], where="ticker = 'DDD'", dest=tmp_path)

    assert read(path) == [("4",)]
    assert len(read(dc.fetch("dev.silver.prices", limit=1, dest=tmp_path))) == 1


def test_table_without_bookkeeping_columns_is_read_whole(
    workspace: SimpleNamespace, tmp_path: Path
):
    import pyarrow as pa

    storage = tmp_path / "plain"
    write_deltalake(storage, pa.table({"ticker": ["AAA", "BBB"], "price": ["1", "2"]}))
    serve(workspace, table_info(kind=TableType.MANAGED, fmt=DataSourceFormat.DELTA), storage)

    path = dc.fetch("dev.silver.prices", dest=tmp_path)

    assert len(read(path)) == 2


def test_empty_table(
    workspace: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    import pyarrow as pa

    storage = tmp_path / "empty"
    write_deltalake(
        storage, pa.table({"ticker": pa.array([], pa.string()), "price": pa.array([], pa.string())})
    )
    serve(workspace, table_info(), storage)

    path = dc.fetch("dev.silver.prices", dest=tmp_path)

    assert read(path) == []
    assert "0 Parquet files, 0.0 B" in capsys.readouterr().err


def test_size_is_reported_before_data_is_read(
    workspace: SimpleNamespace,
    delta_table: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    serve(workspace, table_info(), delta_table)

    with pytest.raises(duckdb.Error):
        dc.fetch("dev.silver.prices", where="no_such_column = 1", dest=tmp_path / "out")

    assert "Parquet files" in capsys.readouterr().err
    assert list((tmp_path / "out").glob("*")) == []  # no partial file left behind


@pytest.mark.parametrize(
    ("kind", "fmt"),
    [
        (TableType.VIEW, None),
        (TableType.MANAGED, DataSourceFormat.DELTASHARING),
        (TableType.EXTERNAL, DataSourceFormat.PARQUET),
    ],
)
def test_unsupported_tables_are_rejected_before_asking_for_credentials(
    workspace: SimpleNamespace, tmp_path: Path, kind: TableType, fmt: DataSourceFormat | None
):
    workspace.tables.get = lambda _name: table_info(kind=kind, fmt=fmt)

    with pytest.raises(dc.UnsupportedTable, match="cannot be fetched"):
        dc.fetch("dev.silver.prices", dest=tmp_path)


def test_pipeline_table_without_external_metadata(workspace: SimpleNamespace, tmp_path: Path):
    workspace.tables.get = lambda _name: table_info()
    workspace.temporary_table_credentials.generate_temporary_table_credentials = raises(
        BadRequest("Request URL is required for table type STREAMING_TABLE.")
    )

    with pytest.raises(dc.UnsupportedTable, match=r"pipelines\.externalMetadata\.enabled=true"):
        dc.fetch("dev.silver.prices", dest=tmp_path)


def test_missing_grant(workspace: SimpleNamespace, tmp_path: Path):
    workspace.tables.get = lambda _name: table_info()
    workspace.temporary_table_credentials.generate_temporary_table_credentials = raises(
        PermissionDenied("Principal 'x' does not have EXTERNAL USE SCHEMA on Schema 'dev.silver'.")
    )

    with pytest.raises(dc.AccessDenied, match="EXTERNAL USE SCHEMA"):
        dc.fetch("dev.silver.prices", dest=tmp_path)


def test_non_aws_credentials(workspace: SimpleNamespace, tmp_path: Path):
    from databricks.sdk.service.catalog import GenerateTemporaryTableCredentialResponse

    workspace.tables.get = lambda _name: table_info()
    workspace.temporary_table_credentials.generate_temporary_table_credentials = lambda **_: (
        GenerateTemporaryTableCredentialResponse(url="s3://x", aws_temp_credentials=None)
    )

    with pytest.raises(dc.UnsupportedTable, match="only AWS"):
        dc.fetch("dev.silver.prices", dest=tmp_path)


def test_human_sizes():
    assert [_human(n) for n in (0, 1023, 1024, 5 * 1024**2, 3 * 1024**4)] == [
        "0.0 B",
        "1023.0 B",
        "1.0 KiB",
        "5.0 MiB",
        "3.0 TiB",
    ]
