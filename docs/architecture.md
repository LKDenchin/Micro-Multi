# Architecture

The Electron main process starts the local Python service and opens the workspace in a sandboxed renderer. A narrow preload bridge exposes desktop actions. The FastAPI service owns projects, conversations, model profiles, permissions, and agent execution.

Agent tools connect workspace files, commands, MCP services, Skills, and dsh plugins. Native dsh Cordis Host packages run in separate Node processes per package and workspace. The desktop distribution supplies Python and Electron's Node runtime.

Application state lives in the user's writable data directory. API keys use the operating system credential store. Production packages include only application files, runtime dependencies, and license notices.
