# Security

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Email the maintainer at the address in the repository's git commit metadata, with
the word SECURITY in the subject. If that address is unavailable, open a public
issue that says only "security report — need a private channel" without details.

You can expect an acknowledgement within a few days. This is a small project with
no bug bounty; the goal is a quiet fix and credit if you want it.

## What this software does with your data

- It reads the CSV/JSON/JSONL exports you point it at and writes a local SQLite
  database. Nothing is uploaded anywhere.
- The MCP server speaks stdio; it opens no network sockets.
- `data/` and `*.db` are gitignored — a database you create never lands in a
  commit unless you force it.

## Supported versions

Only the newest release is supported. This repository starts at 0.5.0.
