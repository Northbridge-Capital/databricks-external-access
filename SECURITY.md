# Security

This package never stores or logs credentials: it signs in through your workspace's OAuth
flow (tokens are cached by the Databricks SDK in `~/.config/databricks-sdk-py/oauth`) and
uses short-lived, read-only storage credentials in memory only.

Please report vulnerabilities privately through the repository's "Report a vulnerability"
(GitHub security advisories) rather than a public issue.
