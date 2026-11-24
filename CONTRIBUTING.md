# Contributing

Thanks for helping. Bug reports, fixes, docs and features are all welcome; for anything
larger than a small fix, please open an issue first so we can agree on the approach.

## Setup and checks

Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just).

```bash
just sync   # install dependencies
just lint   # ruff, ruff format, basedpyright
just test   # pytest with coverage
```

CI runs the same checks on every pull request (the aggregate `ci-required` job passes only when all
of them do, and is the single check meant for branch protection): lint and types, the tests on Linux, macOS and
Windows with Python 3.11 and 3.13, the tests against the **lowest** dependency versions that
`pyproject.toml` allows, and a build check (`twine check`, clean-environment import).

### The integration test

`tests/test_integration.py` reads real tables from a real workspace. It runs when
`DATABRICKS_TEST_TABLES` (comma-separated `catalog.schema.table`; include a Lakeflow streaming
table written by `apply_changes` and a materialized view) is set and you have run
`databricks_external_access.login(...)` before, and skips itself otherwise, including in CI,
which has no sign-in. Run it before changing anything in `fetch.py` and when
bumping `duckdb` or `databricks-sdk`: it is what catches a client no longer reading Lakeflow
tables.

## Where things are

- [docs/requirements.md](docs/requirements.md): what the project must do and the conditions it
  works under. A change that alters a requirement updates it in the same pull request.
- [docs/design.md](docs/design.md): how it works, the module map, decisions, and where to extend.

## Design rules

- **Lean.** The package has two runtime dependencies (`databricks-sdk`, `duckdb`); adding a
  third needs a strong case. Delete rather than deprecate, and no options kept "just in case".
- **One source of truth.** No logic or constant maintained in two places.
- **Docs move with the code.** README, docstrings, comments and `CHANGELOG.md` (under
  `[Unreleased]`) must be correct in the same pull request.
- **Never print or log credentials.**

## Pull requests

1. Fork the repository (or branch, if you are a maintainer) and branch off `main` using
   `feature/…`, `fix/…`, `docs/…` or `chore/…`.
2. Open a pull request against `main`. Branches are merged by **squash**, so the pull request
   title becomes the commit message: make it a short imperative summary.
3. A code owner must approve before merging (`.github/CODEOWNERS`); other reviews are welcome
   but do not satisfy the merge rule. An author cannot approve their own pull request, so a
   code owner should not open the pull request they are meant to approve.

## Releasing

Releases are tags on `main`; consumers pin a tag. Tags matching `v*` are protected: they
cannot be moved or deleted except by organisation admins, so check before you tag, and never
reuse a version.

1. In a pull request, bump `version` in `pyproject.toml`, run `uv lock` (CI uses `--locked`),
   and in `CHANGELOG.md` move the `[Unreleased]` entries under the new version with its date.
   Merge it.
2. Dry-run the release: Actions > **Release** > Run workflow, on `main`. It performs the same
   checks and build as a real release but publishes nothing. Fix anything it reports; tags
   cannot be undone, so do not skip this.
3. A maintainer tags the merge commit and pushes the tag:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. The `Release` workflow checks that the tag is on `main` and equals the `pyproject.toml`
   version, builds the package, and creates the GitHub Release with that version's `CHANGELOG.md` section
   as the notes and the wheel and sdist attached. It fails if the changelog has no section for
   the version.
5. Consumers bump their pin to the new tag.

### Publishing to PyPI (planned, not wired up yet)

The package is already PyPI-ready: `pyproject.toml` carries full metadata, CI runs
`twine check --strict`, and the wheel ships `py.typed`. Publishing needs repository settings
that live in the infrastructure repo's Terraform, so it is a request to that repo, not a
change here:

1. Register the project name on PyPI and add a **trusted publisher** for this repository,
   workflow `release.yml`, environment `pypi`. This uses GitHub's OIDC identity, so **no
   token or secret is stored anywhere**.
2. Ask for a GitHub environment named `pypi` (ideally with a required reviewer).
3. Add a publish job to `release.yml` that downloads the built distributions and uploads them
   with `pypa/gh-action-pypi-publish` and `id-token: write`. Dry-run it against TestPyPI first.

Until then, install from the git tag as described in the README.
