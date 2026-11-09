# Security

## Reporting a vulnerability

Please **do not** open a public issue that contains details of a security problem.

Open a public issue whose title is only "security: need a private channel" — no
details, no reproduction steps — and a maintainer will open a private thread.
This repository has no published security mailbox yet; that is a known gap and is
listed in [COMPLIANCE.md](COMPLIANCE.md) before public release.

## What this software does with your data

- It reads the CSV/JSON/JSONL exports you point it at and writes a local SQLite
  database. Nothing is uploaded anywhere.
- The MCP server speaks stdio; it opens no network sockets.
- `data/` and `*.db` are gitignored — a database you create never lands in a
  commit unless you force it.

## Supported versions

Only the newest release is supported. This repository starts at 0.5.0.
