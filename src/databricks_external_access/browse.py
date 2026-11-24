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
    """A catalog (`dev`) or schema (`dev.silver`), named by its full dotted name."""

    name: str
    comment: str | None


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    comment: str | None


@dataclass(frozen=True)
class Table:
    """A table: full name (`dev.silver.options`), kind (MANAGED, STREAMING_TABLE, ...), columns."""

    name: str
    kind: str
    comment: str | None
    columns: tuple[Column, ...]


def catalogs() -> list[Entry]:
    """The catalogs you can see."""
    with explain("listing catalogs"):
        return [Entry(str(c.name), c.comment) for c in _workspace.client().catalogs.list()]


def schemas(catalog: str) -> list[Entry]:
    """The schemas of one catalog, named `catalog.schema`."""
    with explain(f"listing schemas in {catalog}"):
        found = _workspace.client().schemas.list(catalog)
        return [Entry(str(s.full_name), s.comment) for s in found]


def tables(schema: str) -> list[Table]:
    """List the tables of a schema given as `catalog.schema`."""
    catalog, _, name = schema.partition(".")
    if not name:
        raise Error(f"Expected a schema as 'catalog.schema', got {schema!r}.")
    with explain(f"listing tables in {schema}"):
        return [_to_table(t) for t in _workspace.client().tables.list(catalog, name)]


def overview(catalog: str | None = None) -> None:
    """Print every catalog, schema and table you can see as a tree.

    Skips the Databricks-managed `system` and `samples` catalogs and every
    `information_schema` unless you name a catalog explicitly. Lists the schemas in parallel.
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
    """Describe one table given as `catalog.schema.table`."""
    return _to_table(table_info(name))


def _to_table(info: TableInfo) -> Table:
    columns = tuple(Column(str(c.name), str(c.type_text), c.comment) for c in info.columns or [])
    kind = info.table_type.value if info.table_type else "UNKNOWN"
    return Table(str(info.full_name), kind, info.comment, columns)
