# Current source changes — 2026-10-05

This update follows the published 0.1.0 desktop baseline. The package version remains 0.1.0. It updates source and documentation; it does not publish a new Release or replace existing installers.

## Plugins

- Load hosts, service providers and browser clients using native Cordis Loader entries; retain entry options, isolation, validation, lifetime and rollback.
- Discover real required services recursively from dsh base composition and dependency metadata. Include timer, session query, workspace and storage in the production closure.
- Install declared missing libraries and build tools in managed caches. Read hidden package metadata, support synchronous/asynchronous factories and chunks, and keep framework ABI aligned to the locked host SDK.
- Preserve original legacy SettingsProvider semantics alongside native Config forms. Validate changes, restart fully, save atomically and recover previous settings on failure/restart.
- Contain settings and body portals in details; render explicit conversation/shell contributions in their intended regions. Use the native locale runtime and native ownership of nested slots.
- Disable browser Node-internal probes; derive JS/CSS and host cache revisions from current sources and dependencies.
- Protect framework source with integrity-verified published snapshots and retained licenses. Preserve native HTTP binary/streaming routes and use WebSocket for ongoing subscriptions.

## Conversations and teams

- Persist and stream reviewable team plans, require confirmation of each plan version and preserve deliberate member model choices.
- Deduplicate repeated member/task scheduling while allowing new tasks and failure retries; release reservations on cancellation.
- Negotiate explicitly rejected optional model parameters with bounded retries; preserve concrete failure reasons, finish state, reasoning and structured tool output.
- Coalesce stream/storage/render updates, retain SQLite durability, reuse MCP connections and clean up cancelled calls.
- Stabilize startup observers and narrow composer layout; prevent global controls from modifying React-managed plugin controls.

## Documentation and verification

English and Chinese guides have separate bodies, navigation, search and counterpart links. Pages is rebuilt from repository Markdown on main pushes. Historical validation records retain their dates and scope; they are not evidence that current installers were rebuilt. Programmatic regression checks cover services, settings, rollback, browser realms without Node globals, dependency installation, portals and startup. No simulated clicks are used for this update.

Final local validation: 298 Python tests passed, one platform symlink test skipped; all three Node regression suites passed. Ruff lint/format and Mypy passed. Python wheel/source builds include the native settings source and notices. Site checks cover 42 pages, local links, anchors, counterpart navigation and both search indexes. Desktop installers were not rebuilt or released.

See [native plugins](NATIVE_CORDIS.md), [collaboration](AUTONOMOUS_COLLABORATION.md), [recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) and [validation](RELEASE_VALIDATION.md).
