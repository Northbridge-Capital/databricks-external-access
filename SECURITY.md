# Security

This package never stores or logs credentials. It signs in through your workspace's OAuth flow
(tokens are cached by the Databricks SDK in `~/.config/databricks-sdk-py/oauth`) and keeps the
short-lived, read-only storage credentials it requests in memory only.

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub: open the repository's
[Security tab](https://github.com/Northbridge-Capital/databricks-external-access/security) and
choose "Report a vulnerability". Do not open a public issue. Include the affected version and
steps to reproduce, and never include real credentials or data.

## Supported versions

Only the latest release receives fixes while the project is `0.x`.
