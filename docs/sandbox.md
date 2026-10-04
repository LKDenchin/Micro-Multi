# Permissions

Choose an operation policy in the conversation composer before starting work. It controls which application tool operations can proceed automatically and which need your confirmation.

| Option | Behavior |
| --- | --- |
| Ask for approval | Reads proceed automatically; file changes and commands require confirmation. |
| Allow file edits | Reads and file edits proceed automatically; commands require confirmation. |
| Full access | Allows file access, commands and enabled external capabilities, including MCP tools. |

When an approval appears, read the requested operation and decide whether it fits the task. A team plan confirmation starts the agreed collaboration; an operation approval controls a particular action. They serve different purposes.

The Electron renderer uses context isolation and Chromium sandboxing. Commands and native plugins run on the host with your system user permissions. The operation policy does not turn arbitrary local programs into sandboxed processes.

Docker-based verification requires a separately installed Docker environment. Its isolated execution refuses to fall back to the host, but it does not isolate all conversation tools and extensions. Keep credentials out of project files and inspect any data you plan to share with a model or extension. See [Security](../SECURITY.md) for trust boundaries and reporting.
