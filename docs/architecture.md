# Architecture and technology

The core is multi-agent scheduling and DeepSeek Harness plugin integration. Models propose assignments; the Python scheduler validates plans, handles task dependencies and path locks, and returns reports to the lead. The native Node host supplies Cordis services and dsh plugin tools. Tools and events connect these layers. See [Agent design](AGENT_DESIGN.md) for tradeoffs and the pi analysis.

Micro-Multi combines an Electron desktop shell, a local Python service and Node.js agent/plugin runtimes. The main workspace is written in HTML, CSS and JavaScript. Native plugin components use React, so plugins can contribute controls without replacing the workspace.

## How a task runs

Electron starts the Python service and opens the workspace in a sandboxed renderer. A preload bridge exposes a small set of desktop actions, such as choosing a folder. The web interface sends requests to FastAPI, which manages projects, conversations, models and task execution.

A conversation uses the selected model profile. The execution layer processes model replies and dispatches tools for file access, commands, MCP connections or plugins. Team mode adds a supervisor that keeps the plan, member assignments and execution status. The interface receives conversation events through SSE and ongoing plugin subscriptions through WebSocket.

Native dsh packages run in separate Node processes for their package/workspace scope. The official Cordis runtime handles service registration and plugin lifetime. The client module system and renderer host plugin interface contributions inside the main application.

## Technology stack

| Area | Technologies and role |
| --- | --- |
| Desktop | Electron, context isolation and a sandboxed renderer; electron-builder produces NSIS, Debian and AppImage packages. |
| Backend | Python 3.11+, FastAPI and Uvicorn; Pydantic and JSON Schema validate structured data. |
| Main interface | HTML, CSS and JavaScript modules, with Markdown, code highlighting and mathematical notation rendering. |
| Plugin interface | React and the dsh client renderer; esbuild bundles plugin client entries. |
| Agent and plugin execution | Node.js 24+, Cordis and deepseek-harness runtimes; MCP connects additional tools. |
| Persistence | SQLite application records, local attachment files and OS-backed credentials through keyring. |
| Communication | Local HTTP APIs, SSE task events, WebSocket subscriptions and subprocess messages. |
| Documentation | Python and markdown-it-py generate static bilingual pages for GitHub Pages. |

The desktop packages carry their Python and Node runtimes. Git, Docker and external extension programs are installed separately. Exact npm dependencies are in `package-lock.json`; desktop Python dependencies are in `requirements-desktop.lock`.

## Source layout

| Path | Contents |
| --- | --- |
| `desktop/` | Electron entry point, preload and platform integration. |
| `src/masp/api.py` | HTTP and streaming routes used by the interface. |
| `src/masp/web/` | Main workspace markup, styles and JavaScript. |
| `src/masp/supervisor.py` | Team coordination and member execution. |
| `src/masp/native/` | Node hosts and native plugin/client integration. |
| `src/masp/storage.py` | Application record storage. |
| `scripts/` | Builds, validation and site generation. |
| `tests/` | Runtime and interface regression tests. |

## Storage and process boundaries

The data directory is separate from the installed program. SQLite stores application records; attachments and other working data are local files. Model keys use the OS credential store. See [deployment](deployment.md) for paths and configuration.

The renderer is sandboxed, but local commands and native plugins run with the user's system permissions. Process separation handles plugin failures; it is not a sandbox for arbitrary plugin code. [Permissions](sandbox.md) describes the controls users see, and [runtime interfaces](contracts.md) describes the integration contracts.
