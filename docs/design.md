# Design

## How it works

```
login()/client()  ->  browse (SDK)  ->  describe(name)  ->  fetch(name, ...)
                                                              |
        Unity Catalog: table metadata -> temporary read credentials + storage path
                                                              |
                  DuckDB (Delta extension) reads the Delta files -> local Parquet file
```

1. The Databricks SDK signs in with its browser OAuth flow (`auth_type="external-browser"`)
   and lists catalogs, schemas and tables.
2. For a fetch, Unity Catalog's `temporary-table-credentials` API returns short-lived,
   read-only AWS credentials and the table's S3 path.
3. DuckDB's Delta extension reads that path, applies the column and row selection, and writes
   Parquet through a temporary file that is renamed on success.

## Modules

| Module | Responsibility |
|---|---|
| `_workspace.py` | Workspace URL (`login`, `DATABRICKS_HOST`), the signed-in SDK client, error translation. The only place that knows how authentication works. |
| `browse.py` | `catalogs`, `schemas`, `tables`, `describe`, `overview` and their dataclasses. |
| `fetch.py` | `fetch`, as small steps: `_credentials`, `_connect`, `_announce_size`, `_select`, `_write`. The only module that knows about the read engine and the cloud. |
| `errors.py` | The public exception hierarchy. |

## Decisions

The goal was the fewest dependencies and the least code.

- **Engine: DuckDB.** One dependency reads the Delta log including `deletionVectors`,
  `v2Checkpoint` and `columnMapping` (the features of Lakeflow tables), pushes column and
  filter selection down, reports exact file sizes (`delta_list_files` plus `read_blob`) and
  writes Parquet. *Rejected:* Polars `scan_delta` and delta-rs's pyarrow reader both refuse
  these tables ("requires reader features v2Checkpoint...", re-verified with polars 2.1.0 and
  deltalake 1.6.6). Daft and DuckDB's `unity_catalog` ATTACH failed in earlier exploration and
  were not retested. delta-rs's SQL engine reads them but was not pursued: DuckDB already
  covers everything with one dependency. *Spark with the Unity Catalog connector* was not
  tested: it needs Java 17+ and documents only token or OAuth M2M auth, i.e. a shared secret.
- **Format: Parquet.** Typed, compressed and readable by every framework, so the package stays
  framework-agnostic. *Rejected:* returning a DataFrame (forces a framework), copying raw Delta
  files (breaks on deletion vectors), CSV (loses types).
- **Auth: the SDK's own browser OAuth.** Uses the built-in `databricks-cli` public OAuth client,
  so per-person setup is one `login` call and no CLI install. *Rejected:* the Databricks CLI
  profile (separate install and login), personal access tokens and OAuth M2M (secrets).
  The workspace URL is saved to `~/.config/databricks-external-access/host`, only after sign-in
  succeeds, and `DATABRICKS_HOST` overrides it.
- **Install: PyPI.** Published by the release workflow through trusted publishing (GitHub's OIDC
  identity, no stored token); every release is also a git tag and a GitHub Release with the wheel
  and sdist attached. *Rejected:* GitHub Packages (it has no Python registry).
- **Import name `databricks_external_access`.** It avoids the `databricks` namespace, which
  `databricks-sdk` owns (`databricks.sdk`).
- **One error hierarchy.** Callers can catch `Error`, or a subclass to react to one case (for
  example skip `UnsupportedTable` while looping over tables).

## Trade-offs

- **Pipeline bookkeeping columns.** Lakeflow stores extra columns in a table's files that the
  logical table hides: streaming tables written by `apply_changes` keep `__DeleteVersion`,
  `__MEETS_DROP_EXPECTATIONS` and others, and some materialized views keep helper columns such as
  `__DECOMP_GENERATED_count_0`. `fetch` returns only the columns Unity Catalog declares. For
  `apply_changes` tables Unity Catalog also defines the logical table by dropping deleted and
  expectation-failing rows (its `spark.internal.streaming_table.reconciliation_query`
  property); `fetch` applies those two row filters when it sees the columns. This relies on an
  internal Databricks convention, which is why the integration test compares the fetched columns
  with the declared ones.
- **Read credentials expire after at most an hour.** A transfer that outlives them fails with an
  S3 access error; fetch a smaller slice.
- **The size shown is the whole table**, an upper bound for a slice.
- **`fetch` prints to stderr** (the size line) rather than logging, because telling the user
  the size is a requirement, not a diagnostic.
- **`where` is a DuckDB SQL predicate, not sanitised.** It runs on the user's machine with the
  user's own credentials.
- **No Databricks compute is used,** so the work is bounded by the user's machine and network.

## Extending the package

The seams are in place; build them when a consumer exists, not before.

- **Databricks Connect** (data too large for a laptop): authentication is already one function,
  `_workspace.client()`, whose `config` a Connect session can reuse. Add a function beside
  `fetch` and keep `fetch.py` the only module that knows about engines.
- **Another cloud:** `fetch._credentials` and `fetch._connect` are the only places that assume
  AWS credentials and S3.
- **Another output format:** `fetch._write` is the only place that writes a file.
- **New table kinds:** `fetch._READABLE_KINDS` / `_READABLE_FORMATS` and the pipeline handling in
  `_credentials`.

Anything that adds a runtime dependency, an option kept "just in case", or a second way to do an
existing thing should be discussed in an issue first (see CONTRIBUTING.md).
