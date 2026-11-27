"""Discover the catalogs, schemas and tables the signed-in user can see."""

from __future__ import annotations

# `_workspace` is this package's private module; it is called as an attribute so tests can patch it.
# pyright: reportPrivateUsage=false
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from databricks.sdk.service.catalog import TableInfo

from . import _workspace
from ._workspace import explain, table_info
from .errors import Error

# Databricks-managed catalogs that `overview()` skips unless asked for by name.
_MANAGED = {"system", "samples"}
_COMMENT_WIDTH = 70


@dataclass(frozen=True)
class Entry:
    """A catalog or schema, named by its full dotted name.

    Attributes
    ----------
    name
        Full dotted name, for example ``dev`` or ``dev.silver``.
    comment
        Description, if any.
    """

    name: str
    comment: str | None


@dataclass(frozen=True)
class Column:
    """A table column.

    Attributes
    ----------
    name
        Column name.
    type
        Data type as Unity Catalog reports it, for example ``string``.
    comment
        Description, if any.
    """

    name: str
    type: str
    comment: str | None


@dataclass(frozen=True)
class Table:
    """A table and its columns.

    Attributes
    ----------
    name
        Full table name, for example ``dev.silver.options``.
    kind
        Table kind, for example ``MANAGED`` or ``STREAMING_TABLE``.
    comment
        Description, if any.
    columns
        The table's columns, in order.
    """

    name: str
    kind: str
    comment: str | None
    columns: tuple[Column, ...]


def catalogs() -> list[Entry]:
    """List the catalogs you can see.

    Returns
    -------
    One entry per catalog.

    Raises
    ------
    NotSignedIn
        Databricks rejected your sign-in.
    AccessDenied
        You lack permission to list them.
    Error
        No workspace is configured.
    """
    with explain("listing catalogs"):
        return [Entry(str(c.name), c.comment) for c in _workspace.client().catalogs.list()]


def schemas(catalog: str) -> list[Entry]:
    """List the schemas of one catalog.

    Parameters
    ----------
    catalog
        Catalog name, for example ``dev``.

    Returns
    -------
    One entry per schema, named ``catalog.schema``.

    Raises
    ------
    NotSignedIn
        Databricks rejected your sign-in.
    AccessDenied
        You lack permission to list the catalog's schemas.
    NotFound
        The catalog does not exist, or you cannot see it.
    Error
        No workspace is configured.
    """
    with explain(f"listing schemas in {catalog}"):
        found = _workspace.client().schemas.list(catalog)
        return [Entry(str(s.full_name), s.comment) for s in found]


def tables(schema: str) -> list[Table]:
    """List the tables of one schema, with their columns.

    Parameters
    ----------
    schema
        Schema name, ``catalog.schema``.

    Returns
    -------
    One table per table in the schema.

    Raises
    ------
    NotSignedIn
        Databricks rejected your sign-in.
    AccessDenied
        You lack permission to list the schema's tables.
    NotFound
        The schema does not exist, or you cannot see it.
    Error
        ``schema`` is not of the form ``catalog.schema``, or no workspace is configured.
    """
    catalog, _, name = schema.partition(".")
    if not name:
        raise Error(f"Expected a schema as 'catalog.schema', got {schema!r}.")
    with explain(f"listing tables in {schema}"):
        return [_to_table(t) for t in _workspace.client().tables.list(catalog, name)]


def overview(catalog: str | None = None) -> None:
    """Print every catalog, schema and table you can see as a tree.

    Lists the schemas in parallel.

    Parameters
    ----------
    catalog
        Catalog to show, including its ``information_schema``. Default: every catalog you can
        see except the Databricks-managed ``system`` and ``samples``, and without any
        ``information_schema``.

    Raises
    ------
    NotSignedIn
        Databricks rejected your sign-in.
    AccessDenied
        You lack permission to list something in the tree.
    NotFound
        ``catalog`` does not exist, or you cannot see it.
    Error
        No workspace is configured.
    """
    names = [catalog] if catalog else [c.name for c in catalogs() if c.name not in _MANAGED]
    with ThreadPoolExecutor(max_workers=8) as pool:
        schema_names = {
            name: [s.name for s in found if catalog or not s.name.endswith(".information_schema")]
            for name, found in zip(names, pool.map(schemas, names), strict=True)
        }
        every_schema = [s for found in schema_names.values() for s in found]
        listing = dict(zip(every_schema, pool.map(tables, every_schema), strict=True))
    print(_render(schema_names, listing))


def _render(schema_names: dict[str, list[str]], listing: dict[str, list[Table]]) -> str:
    """Render the schema listing as an indented tree."""
    lines: list[str] = []
    for catalog, found_schemas in schema_names.items():
        lines.append(catalog)
        for schema in found_schemas:
            found = listing[schema]
            lines.append(f"  {schema.removeprefix(catalog + '.')}  ({len(found)} tables)")
            for table in found:
                comment = (table.comment or "").strip().splitlines()[:1]
                short = comment[0][:_COMMENT_WIDTH] if comment else ""
                lines.append(
                    f"    {table.name.rsplit('.', 1)[-1]:40} {table.kind:18} {short}".rstrip()
                )
    return "\n".join(lines)


def describe(name: str) -> Table:
    """Describe one table.

    Parameters
    ----------
    name
        Full table name, ``catalog.schema.table``.

    Returns
    -------
    The table, with its columns.

    Raises
    ------
    NotSignedIn
        Databricks rejected your sign-in.
    AccessDenied
        You lack permission to see the table.
    NotFound
        The table does not exist, or you cannot see it.
    Error
        No workspace is configured.
    """
    return _to_table(table_info(name))


def _to_table(info: TableInfo) -> Table:
    """Convert Unity Catalog table info to a ``Table``."""
    columns = tuple(Column(str(c.name), str(c.type_text), c.comment) for c in info.columns or [])
    kind = info.table_type.value if info.table_type else "UNKNOWN"
    return Table(str(info.full_name), kind, info.comment, columns)
