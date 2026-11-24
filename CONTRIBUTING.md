# Contributing

## Setup and checks

Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just).

```bash
just sync   # install dependencies
just lint   # ruff, ruff format, basedpyright
just test   # pytest with coverage
```

CI runs the same checks on every PR and push to `main`, and the tests on Linux, macOS and
Windows with Python 3.11 and 3.13. The integration test reads a real table from your
workspace; it runs when `DATABRICKS_TEST_TABLE` (`catalog.schema.table`, ideally a Lakeflow pipeline
table) is set and you have run `databricks_external_access.login(...)` before, and skips
itself otherwise, including in CI.
Run it before changing anything in `fetch.py`, and after bumping `duckdb` or
`databricks-sdk`: it is what catches a client no longer reading Lakeflow tables.

Branch off `main` (`feature/…`, `fix/…`, `docs/…`, `chore/…`), open a PR, and keep README,
docstrings and comments correct in the same PR.

## Releasing

Releases are tags on `main`; consumers pin them. Versions follow SemVer (while `0.x`, a
breaking API change bumps the minor version).

1. In a PR, bump `version` in `pyproject.toml` and run `uv lock` (CI uses `--locked`).
   Merge it to `main`.
2. Tag the merge commit and push the tag:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

3. The `Release` workflow checks that the tag is on `main` and equals the `pyproject.toml`
   version, builds the package, and creates the GitHub Release with generated notes and the wheel and
   sdist attached.
4. Consumers bump their pin to the new tag.

Never move or delete a published tag; cut a new version instead. Consider a repository
rule restricting who can create `v*` tags.
