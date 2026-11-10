# Contributing

This is a small project with one maintainer and an unusual priority order: a wrong
conclusion is worse than a missing feature. That shapes what is welcome.

## What this project will not accept

- **A data collector or a scraper.** The engine reads exports you already have. No
  crawler, no built-in network access, no "just fetch it for me".
- **Runtime dependencies.** `dependencies = []` is a promise enforced by
  `scripts/check_no_runtime_deps.py`. A patch that adds one needs to change the
  documentation first and say why in the PR.
- **Real data in any form.** No real exports, databases, screenshots of dashboards,
  real company names, or anything derived from them — not in code, tests, issues or
  pull requests.
- **A detector that cannot be scored.** New detection rules need a positive control,
  a negative control and a labelled scenario in the precision matrix.

## Fixtures are synthetic, always

Every data-shaped file lives under `tests/fixtures/` and is invented: entities that
do not exist, dated 2099 so they can never be confused with a capture. If you need a
fixture, generate it, and make the values obviously fake.

`scripts/check_no_real_data.py` enforces this in two places: a pre-commit hook and
CI. It blocks `data/`-style directories, database and export extensions, credential
files and known credential markers. Enable the hook once per clone:

```bash
git config core.hooksPath .githooks
```

The hook can be bypassed with `--no-verify`. CI cannot, but CI runs after the code
is already uploaded — so a first-time contributor should still check their own diff.

## Before opening a pull request

```bash
python scripts/run_release_gate.py   # all five gates, stops at the first failure
```

That single command runs: the data guard, the dependency contract, the tests (0
skips allowed), the precision matrix and the doc truth check. CI runs the same
entry point, so "it passed locally" and "it passes in CI" mean the same thing.

## Reporting a bug

Include: operating system, Python version, the command you ran, and the smallest
input that reproduces it. If the input is data-shaped, **synthesize it** — never
attach a real export.

## Version and support policy

- Patch (`0.5.x`): fixes, docs, guards. Interface and output shapes stay stable.
- Minor (`0.6.0`): new tools, new detectors, changed defaults or storage. Migration
  notes in CHANGELOG.
- Only the newest release is supported.
- Maintainer response is best-effort; there is no SLA and no backporting.

## Security

Do not open a public issue containing vulnerability details. See [SECURITY.md](SECURITY.md).
