# Requirements

What this project must do, the conditions it works under, and what it deliberately does not do.
Each requirement says where it is verified, so a change that breaks one fails a test, not a user.

## Purpose

Give anyone with a Databricks login a **super lean interface to authenticate and read external
Databricks tables**: browse what exists, and fetch a table or a slice of it to their own machine
as Parquet, without Databricks compute and without shared secrets.

## Functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| F1 | Browse catalogs, schemas and tables with descriptions and columns, and see everything in one call. | `tests/test_browse.py`; integration `test_browse` |
| F2 | Fetch a table, or a slice (`columns`, `where`, `limit`), to a local Parquet file. | `tests/test_fetch.py`; integration `test_fetch_*` |
| F3 | Tell the user the table's size **before** reading any data. | `test_size_is_reported_before_data_is_read` |
| F4 | Return exactly the table's logical content: only the columns Unity Catalog declares, and for `apply_changes` tables without deleted or expectation-failing rows. | `test_fetch_writes_the_logical_table`; integration `test_fetch_returns_exactly_the_declared_columns` |
| F5 | Sign in through the workspace's SSO in the browser, once per machine; no shared secrets. | `test_login_*`; verified manually |
| F6 | Fail with a specific, catchable error that says what to do: `NotSignedIn`, `AccessDenied`, `NotFound`, `UnsupportedTable` (all subclasses of `Error`). | `test_databricks_failures_*`, `test_fetch.py` |
| F7 | A failed or interrupted fetch leaves no partial file. | `test_size_is_reported_before_data_is_read` |

## Non-functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| N1 | Works on macOS, Linux and Windows; Python 3.11 and newer. | CI matrix (3 OSes × Python 3.11, 3.13) |
| N2 | The declared dependency lower bounds work, not just the locked versions. | CI `test-lowest` |
| N3 | Two runtime dependencies only: `databricks-sdk` and `duckdb`. A third needs a strong case. | Review (`pyproject.toml`) |
| N4 | Never print or log credentials. | `test_fetch_writes_the_logical_table` |
| N5 | The package builds, renders on PyPI and imports from a clean environment; it is typed. | CI `build` (`twine check --strict`) |
| N6 | 85% or more test coverage. | CI `test` |

## Environment and constraints

- **Cloud:** AWS workspaces with Unity Catalog. Other clouds vend different credentials and are
  unsupported (reported as `UnsupportedTable`).
- **Access control** lives in the Databricks administrator's configuration, not here. To fetch,
  a principal needs `SELECT` on the table **and** `EXTERNAL USE SCHEMA` on its schema. This
  package never manages grants.
- **Readable tables:** Delta tables, streaming tables and materialized views. Views and
  Delta Sharing tables cannot be read. Pipeline tables are readable only when their pipeline
  sets `pipelines.externalMetadata.enabled=true` and has run an update.
- **Network:** internet access, including `extensions.duckdb.org` on first use (DuckDB downloads
  its `delta` and `httpfs` extensions into `~/.duckdb`). A browser is needed to sign in.
- **Repository rules** (managed outside this repo): a code owner must approve every pull
  request, merges are squash-only, and tags matching `v*` are protected. Releases are tags on
  `main` and distribution is from git tags for now, PyPI later (see CONTRIBUTING.md).

## Out of scope

Managing grants or any Databricks object; running queries on Databricks compute; writing to
Databricks; non-AWS clouds; headless authentication (tokens, OAuth M2M); a CLI. A **Databricks
Connect** backend for data too large for a laptop is a planned extension, not built (see
[design.md](design.md#extending-the-package)).

## Verification status

Verified live on an AWS workspace against `apply_changes` streaming tables and materialized
views (the largest with 10,825,000 rows). **Not yet verified against a real workspace:** managed
and external Delta tables (covered by tests on a local Delta table only), and the
`apply_changes` row filter on tables that actually contain deleted or expectation-failing rows
(none of the tables checked had any; covered by a unit test on a synthetic table).
