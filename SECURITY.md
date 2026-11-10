# Security

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting**: open the repository's **Security**
tab and choose **Report a vulnerability**. That opens a private advisory only the
maintainer can see.

If that option is unavailable, open an issue whose title is only
`security: need a private channel` — with no details — and a maintainer will open a
private thread.

Do not disclose vulnerability details in a public issue. When reproducing, use
synthetic data: never attach a real export, database or credential.

The maintainer aims to acknowledge a report within 7 calendar days. That is a
response target, not a fix deadline. Only the newest release receives security fixes.

## What this software does with your data

- It reads the CSV/JSON/JSONL exports you point it at and writes a local SQLite
  database. Nothing is uploaded anywhere.
- The MCP server speaks stdio and opens no network sockets.
- `data/`, `*.db` and export extensions are gitignored **and** refused by
  `scripts/check_no_real_data.py` (pre-commit hook plus CI), so an accidental commit
  fails rather than silently publishing.

## Supported versions

Only the newest release is supported. This repository starts at 0.5.x.
