from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest
from databricks.sdk.service.catalog import (
    AwsCredentials,
    ColumnInfo,
    DataSourceFormat,
    GenerateTemporaryTableCredentialResponse,
    TableInfo,
    TableType,
)
from deltalake import write_deltalake

from databricks_external_access import _workspace

SECRET = "super-secret-value"  # must never appear in output or errors


def raises(error: Exception):
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return _raise


def table_info(
    name: str = "dev.silver.prices",
    kind: TableType = TableType.STREAMING_TABLE,
    fmt: DataSourceFormat | None = None,
    columns: tuple[str, ...] = ("ticker", "price"),
) -> TableInfo:
    return TableInfo(
        full_name=name,
        table_id="id-" + name,
        table_type=kind,
        data_source_format=fmt,
        comment=f"{name} comment",
        columns=[ColumnInfo(name=c, type_text="string", comment=f"{c} comment") for c in columns],
    )


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A fake Databricks client; tests set the attributes they exercise."""
    credentials = SimpleNamespace(
        generate_temporary_table_credentials=raises(AssertionError("unexpected credentials call"))
    )
    ws = SimpleNamespace(
        catalogs=SimpleNamespace(),
        schemas=SimpleNamespace(),
        tables=SimpleNamespace(),
        temporary_table_credentials=credentials,
        metastores=SimpleNamespace(summary=lambda: SimpleNamespace(region="eu-west-1")),
    )
    monkeypatch.setattr(_workspace, "client", lambda: ws)
    return ws


def serve(ws: SimpleNamespace, info: TableInfo, storage: Path | str) -> None:
    """Make `ws` describe `info` and vend credentials whose storage path is `storage`."""
    ws.tables.get = lambda _name: info
    ws.temporary_table_credentials.generate_temporary_table_credentials = lambda **_: (
        GenerateTemporaryTableCredentialResponse(
            url=str(storage),
            aws_temp_credentials=AwsCredentials(
                access_key_id="key", secret_access_key=SECRET, session_token=SECRET
            ),
        )
    )


@pytest.fixture
def delta_table(tmp_path: Path) -> Path:
    """A Delta table shaped like a pipeline `apply_changes` table: logical columns plus
    bookkeeping columns, one deleted row and one expectation-failing row."""
    path = tmp_path / "storage" / "prices"
    write_deltalake(
        path,
        pa.table(
            {
                "ticker": ["AAA", "BBB", "CCC", "DDD"],
                "price": ["1", "2", "3", "4"],
                "__DeleteVersion": pa.array([None, "v2", None, None], pa.string()),
                "__MEETS_DROP_EXPECTATIONS": pa.array([True, None, False, None], pa.bool_()),
            }
        ),
    )
    return path
