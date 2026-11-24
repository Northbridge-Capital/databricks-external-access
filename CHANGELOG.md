# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/) (while `0.x`, a breaking change bumps the minor
version).

## [Unreleased]

## [0.1.0] - unreleased

First release.

### Added

- Browse Unity Catalog: `overview()`, `catalogs()`, `schemas()`, `tables()`, `describe()`.
- `fetch()` a table or a slice (`columns`, `where`, `limit`) to a local Parquet file, printing
  its size on storage first. Reads Lakeflow pipeline tables (`deletionVectors`,
  `v2Checkpoint`, `columnMapping`) through temporary table credentials and DuckDB.
- `login()` to save the workspace once and sign in through the browser (SSO).
- Actionable errors for missing sign-in, missing grants, unsupported tables and unknown tables.
