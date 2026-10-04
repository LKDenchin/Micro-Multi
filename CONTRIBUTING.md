# Contributing

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Read the README, [architecture](docs/architecture.md), and relevant runtime documentation. Check existing issues before large changes and use a focused branch.

## Setup and validation

Use Python 3.11+, Node.js 24+, npm, and Git. Follow README setup; use `npm ci` for locked dependencies. Windows installer builds need Python 3.14.7; Linux builds bootstrap and verify the pinned standalone runtime automatically. Build dependencies on the target platform.

Activate your virtual environment and run:

```text
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests scripts
python -m mypy src/masp
npm run test:plugin-client
npm run test:chat-startup
node tests/client_dependencies.test.mjs
python scripts/build_site.py
```

Runtime changes need relevant behavior and failure-path coverage. Desktop changes also need the packaged smoke test in `docs/DESKTOP_RELEASE.md`. Report live model checks only if performed.

## Pull requests

- Describe the concrete problem, resulting behavior, and validation commands/results.
- Update paired English and Chinese guides for user-facing changes.
- Preserve dependency licenses and adapted-source provenance.
- Never commit credentials, uploads, private workspaces, personal screenshots, or logs.
- Run `python scripts/publication_audit.py` before committing; it checks publication candidates and preserves local user data.

Bug reports need version, OS, reproduction steps, expected/actual results, and sanitized evidence. Report vulnerabilities through [SECURITY.md](SECURITY.md).
