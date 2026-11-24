# databricks-external-access

[![CI](https://github.com/Northbridge-Capital/databricks-external-access/actions/workflows/ci.yml/badge.svg)](https://github.com/Northbridge-Capital/databricks-external-access/actions/workflows/ci.yml)

Browse the catalogs, schemas and tables of a Databricks workspace (Unity Catalog) and fetch
tables to your own machine as Parquet, with no Databricks compute and no secrets. Sign in
once through your workspace's SSO; everything else is a few function calls.

```python
import databricks_external_access as dbx

dbx.overview()  # everything I can see, as a tree
dbx.catalogs()  # or step by step...
dbx.tables("main.sales")  # tables with descriptions and columns
dbx.describe("main.sales.orders")

path = dbx.fetch(
    "main.sales.orders",
    columns=["order_date", "customer", "total"],
    where="customer = 'ACME'",
    limit=1_000_000,
    dest="data",
)
# stderr: main.sales.orders: 2 Parquet files, 51.5 MiB on storage ...

import polars as pl  # or pandas, DuckDB, Spark, ...

df = pl.read_parquet(path)
```

New here? Open the [tutorial notebook](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/notebooks/tutorial.ipynb) (`uv run --group notebook jupyter lab`).

**Status: alpha (`0.x`).** The API may change between minor versions; see the
[changelog](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/CHANGELOG.md).
It is installed from git tags for now; publishing to PyPI is planned.

## Setup (per person)

1. Install a pinned release into your project (see the repository's Releases page for the
   latest tag):

   ```bash
   uv add "databricks-external-access @ git+https://github.com/Northbridge-Capital/databricks-external-access@v0.1.0"
   # or: pip install "databricks-external-access @ git+https://github.com/Northbridge-Capital/databricks-external-access@v0.1.0"
   ```

2. Once per machine, point it at your workspace and sign in:

   ```python
   import databricks_external_access as dbx

   dbx.login("https://dbc-1234abcd-5678.cloud.databricks.com")
   ```

   This opens a browser to sign in through your workspace's SSO and remembers the
   workspace (in `~/.config/databricks-external-access/host`). The sign-in token is cached
   in `~/.config/databricks-sdk-py/oauth` and refreshed automatically; when it can no
   longer be refreshed the browser opens again. Scripts and CI can set `DATABRICKS_HOST`
   instead, which overrides the saved workspace.

That is all: no Databricks CLI, no token, no Java. Requires Python 3.11+ and internet
access (DuckDB downloads its `delta` and `httpfs` extensions on first use into `~/.duckdb`).
A browser is needed to sign in, so this does not run headless.

## Access

Browsing shows what Unity Catalog lets you see. Fetching a table additionally needs
`SELECT` on the table **and** `EXTERNAL USE SCHEMA` on its schema. This package never
manages grants; ask your Databricks admin. Without them `fetch` raises an error naming the
missing grant.

## API

| Function | Returns |
|---|---|
| `login("https://...")` | nothing; saves the workspace and signs in (once per machine) |
| `overview(catalog=None)` | nothing; prints all catalogs, schemas and tables as a tree (skips `system`, `samples` and `information_schema` unless you name the catalog) |
| `catalogs()` | `list[Entry]`: name, comment |
| `schemas("catalog")` | `list[Entry]`, named `catalog.schema` |
| `tables("catalog.schema")` | `list[Table]`: name, kind, comment, `columns` (name, type, comment) |
| `describe("catalog.schema.table")` | one `Table` |
| `fetch("catalog.schema.table", columns=, where=, limit=, dest="data")` | `Path` to `<dest>/<name>.parquet` |

`fetch` prints the table's size on storage (files and compressed bytes of the current
Delta snapshot) to stderr **before** reading any data. For a slice this is the whole
table, an upper bound on what is read. `where` is a DuckDB SQL predicate; it runs on your
machine with your own credentials and is not sanitised. The file is written to a
temporary name and renamed on success, so a failed fetch leaves nothing behind.

Everything raises `databricks_external_access.Error` with a message that says what to do:

| You hit | Message says |
|---|---|
| No workspace configured | run `login("https://...")` once, or set `DATABRICKS_HOST` |
| Not signed in / expired sign-in | the browser opens to sign in; if the server still rejects the token, delete the token cache and retry |
| Missing grant | the missing `SELECT` / `EXTERNAL USE SCHEMA`; ask your Databricks admin |
| Unsupported table | views, shared (Delta Sharing), foreign and non-Delta tables cannot be fetched; pipeline tables whose pipeline has not enabled `pipelines.externalMetadata.enabled` cannot be read from outside |
| Unknown table | not found (Unity Catalog also reports tables you cannot see as missing) |

## Design decisions

The goal was the fewest dependencies and least code. The package depends on exactly two
libraries, `databricks-sdk` and `duckdb`.

**How a fetch works.** The SDK asks Unity Catalog for short-lived, read-only AWS
credentials for the table (`temporary-table-credentials`, which returns the table's S3
path), DuckDB's Delta extension reads the Delta files from that path, and DuckDB writes
the result as Parquet. Verified live on an AWS workspace (duckdb 2.0.1, databricks-sdk 0.169,
Python 3.13) against Lakeflow streaming tables written by `apply_changes` and Lakeflow
materialized views, the largest with 10,825,000 rows.

- **Engine: DuckDB.** One dependency does everything: it reads the Delta log, including
  the `deletionVectors`, `v2Checkpoint` and `columnMapping` features of Lakeflow tables;
  pushes column and filter selection down so slices read less; reports exact file sizes
  (`delta_list_files` plus `read_blob`); and writes Parquet. *Rejected:* Polars
  (`scan_delta`) and delta-rs's pyarrow reader both refuse these tables ("requires reader
  features v2Checkpoint..."), re-verified with polars 2.1.0 and deltalake 1.6.6. Daft and
  DuckDB's `unity_catalog` ATTACH failed in earlier exploration and were not retested.
  delta-rs's SQL engine reads them (earlier exploration; its log reader also reports exact
  file sizes), but was not pursued: DuckDB already covers everything with one dependency.
  *Spark with the Unity Catalog connector* was not tested: it needs Java 17+ and documents
  only token or OAuth M2M auth, which means a shared secret or a bigger setup for everyone.
- **Format: Parquet.** Typed, compressed, and readable by every framework, so the package
  stays framework-agnostic. *Rejected:* returning a DataFrame (forces a framework choice);
  copying raw Delta files (breaks on deletion vectors); CSV (loses types).
- **Auth: the SDK's own browser OAuth (`auth_type="external-browser"`).** Uses the
  built-in `databricks-cli` public OAuth client, so per-person setup is one `login` call, with no CLI to install. *Rejected:* the Databricks CLI profile
  (needs a separate install and login step), personal access tokens and OAuth M2M
  (secrets).
- **Install: a git tag.** A pinned `@vX.Y.Z` is versioned and needs no registry or
  credentials. Each GitHub Release also carries the built wheel and sdist. *Rejected:*
  PyPI (a registry to maintain; the name `databricks-external-access` is also taken there) and
  GitHub Packages (it has no Python registry).
- **Import name `databricks_external_access`.** It does not use the `databricks` namespace, which
  `databricks-sdk` owns (`databricks.sdk`).

### Trade-offs to know about

- **Pipeline bookkeeping columns.** Lakeflow stores extra columns in a table's files that
  the logical table hides: streaming tables written by `apply_changes` keep
  `__DeleteVersion`, `__MEETS_DROP_EXPECTATIONS` and others, and some materialized views keep
  helper columns such as `__DECOMP_GENERATED_count_0`. `fetch` returns only the columns Unity
  Catalog declares. For `apply_changes` tables Unity Catalog also defines the logical table by
  dropping deleted and expectation-failing rows (its
  `spark.internal.streaming_table.reconciliation_query` property); `fetch` applies those two
  row filters when it sees the columns. This relies on an internal Databricks convention,
  which is why the integration test checks the fetched columns against the declared ones.
- **Not yet verified against a real workspace:** managed and external Delta tables (expected to
  work; covered only by tests on a local Delta table), and the `apply_changes` row filter on
  tables that actually contain deleted or expectation-failing rows (every table checked so
  far had none; it is covered by a unit test on a synthetic table).
- **Read credentials expire after at most an hour.** A transfer that outlives them fails
  with an S3 access error; fetch a smaller slice.
- **Pipeline tables only work once their pipeline enables
  `pipelines.externalMetadata.enabled=true` and has run an update.**
- **No Databricks compute is used, so the work is bounded by your machine and network.**
- **AWS workspaces only.** Other clouds vend different credentials and are untested.

### Databricks Connect

Considered as the way to scale to data that does not fit on a laptop; deliberately not
built. The seam already exists at no cost: authentication is one function,
`_workspace.client()`, returning an SDK client whose `config` a Connect session can reuse,
and `fetch.py` is the only module that knows about engines. When a consumer needs it, add
a function there; nothing here has to change.

## License

MIT, see [LICENSE](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/LICENSE).

## Development

See [CONTRIBUTING.md](https://github.com/Northbridge-Capital/databricks-external-access/blob/main/CONTRIBUTING.md): setup, checks, and the release process.
