# databricks-external-access

[![CI](https://github.com/Northbridge-Capital/databricks-external-access/actions/workflows/ci.yml/badge.svg)](https://github.com/Northbridge-Capital/databricks-external-access/actions/workflows/ci.yml)

Browse a Databricks workspace (Unity Catalog) and fetch tables to your own machine as Parquet,
with no Databricks compute and no secrets. Sign in once through your workspace's SSO.

```python
import databricks_external_access as dbx

dbx.login("https://dbc-1234abcd-5678.cloud.databricks.com")  # once per machine

dbx.overview()  # everything you can see, as a tree
dbx.describe("main.sales.orders")  # columns and descriptions

path = dbx.fetch(
    "main.sales.orders",
    columns=["order_date", "customer", "total"],
    where="customer = 'ACME'",
    limit=1_000_000,
)
# stderr: main.sales.orders: 2 Parquet files, 51.5 MiB on storage ...

import polars as pl  # or pandas, DuckDB, Spark, ...

df = pl.read_parquet(path)
```

New here? Open the
[tutorial notebook](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/examples/tutorial.ipynb)
(`uv run --group notebook jupyter lab`).

**Status: alpha (`0.x`).** The API may change between minor versions; see the
[changelog](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/CHANGELOG.md).
Available on [PyPI](https://pypi.org/project/databricks-external-access/).

## Setup

1. Install it from PyPI with your package manager:

   ```bash
   uv add databricks-external-access
   # or: pip install databricks-external-access
   ```

2. Run `dbx.login("<your workspace URL>")` once (any `https://` URL works, including a custom
   workspace URL). A browser opens to
   sign in through your workspace's SSO; the workspace is remembered and the token is cached and
   refreshed automatically. Scripts and CI can set `DATABRICKS_HOST` instead, which overrides the
   saved workspace.

Requires Python 3.11+, an AWS workspace and internet access (DuckDB downloads two extensions on
first use). To fetch a table you need `SELECT` on it **and** `EXTERNAL USE SCHEMA` on its schema;
this package never manages grants, so ask your Databricks admin. The full list of requirements
and constraints is in
[docs/requirements.md](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/docs/requirements.md).

## API

| Function | Returns |
|---|---|
| `login("https://...")` | nothing; saves the workspace and signs in (once per machine) |
| `overview(catalog=None)` | nothing; prints catalogs, schemas and tables as a tree (skips `system`, `samples` and `information_schema` unless you name the catalog) |
| `catalogs()` | `list[Entry]`: name, comment |
| `schemas("catalog")` | `list[Entry]`, named `catalog.schema` |
| `tables("catalog.schema")` | `list[Table]`: name, kind, comment, `columns` (name, type, comment) |
| `describe("catalog.schema.table")` | one `Table` |
| `fetch("catalog.schema.table", columns=, where=, limit=, dest="data")` | `Path` to `<dest>/<name>.parquet` |

`fetch` prints the table's size on storage to stderr **before** reading any data; for a slice
this is the whole table, an upper bound. `where` is a DuckDB SQL predicate that runs on your
machine with your own credentials and is not sanitised. A failed fetch leaves no partial file.

## Errors

Everything raises a subclass of `databricks_external_access.Error`, with a message that says what
to do:

| Error | Raised when |
|---|---|
| `NotSignedIn` | Databricks rejects your sign-in; delete the token cache and retry |
| `AccessDenied` | you lack `SELECT` or `EXTERNAL USE SCHEMA` |
| `UnsupportedTable` | views, shared (Delta Sharing), foreign and non-Delta tables, non-AWS workspaces, and pipeline tables whose pipeline has not enabled `pipelines.externalMetadata.enabled` |
| `NotFound` | the table does not exist, or you cannot see it |
| `Error` | anything else actionable, such as no workspace configured or an `http://` URL |

## More

- [Requirements](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/docs/requirements.md):
  what it must do, the conditions it works under, what is out of scope, and how each is verified.
- [Design](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/docs/design.md):
  how it works, why DuckDB, trade-offs, and where to extend it.
- [Contributing](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/CONTRIBUTING.md):
  setup, checks and the release process.

## License

MIT, see
[LICENSE](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/LICENSE).
