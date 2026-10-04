<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="88" />
  <h1>Micro-Multi</h1>
  <p>A desktop app for working on local projects with AI agents.</p>
  <p>English · <a href="README.zh-CN.md">简体中文</a></p>
  <p><a href="https://lkdenchin.github.io/Micro-Multi/">Website</a> · <a href="#installation">Install</a> · <a href="#your-first-task">Get started</a> · <a href="https://lkdenchin.github.io/Micro-Multi/docs/readme.html">Documentation</a></p>
</div>

Micro-Multi lets you work with AI agents in a local project folder. Connect a model service, open a project and describe the task. The agent can read code, edit files, run commands and use the tools you have enabled. The conversation, file browser, diffs and tool output are available in the same app.

For a small change, use the lead agent on its own. For work that needs several roles, choose team mode: the lead proposes a plan, you review the members and their assignments, and the team starts after you confirm it. You can follow each member's work and check the result against the project files.

The app supports Windows and Linux, with English and Simplified Chinese interfaces. You supply the model endpoint and credentials. Skills, MCP servers and plugins from the deepseek-harness (dsh) ecosystem can add instructions and tools.

## What you can use it for

| Task | How Micro-Multi helps |
| --- | --- |
| Understand a codebase | Ask the agent to trace an entry point, explain a module or find the files involved in a feature. |
| Make and test a change | Work in your project folder, inspect the diff and read the output of commands and tests. |
| Split up a larger task | Assign implementation, testing or review to different team members and choose their models. |
| Use external tools | Connect an MCP server, install a dsh plugin or provide a Skill for a recurring task. |
| Continue existing work | Reopen a saved conversation with its messages, tool records and member reports. |

## Installation

Download a package from [GitHub Releases](https://github.com/LKDenchin/Micro-Multi/releases/latest).

| System | Package |
| --- | --- |
| Windows x64 | [NSIS installer](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-Setup-0.1.0-x64.exe) |
| Debian / Ubuntu x64 | [Debian package](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-amd64.deb) |
| Linux x64 | [AppImage](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-x86_64.AppImage) |
| Checksums | [SHA256SUMS.txt](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/SHA256SUMS.txt) |

On Windows, run the installer and open Micro-Multi from the Start menu. On Debian or Ubuntu, install the downloaded package with `sudo apt install ./<package>.deb`. For AppImage, make the file executable with `chmod +x <file>.AppImage` and run it. If FUSE is unavailable, add `--appimage-extract-and-run`.

The packages include Python and Node.js. Install Git for repository work. Docker and any CLI required by a plugin are installed separately. The [desktop guide](docs/DESKTOP_RELEASE.md) covers Linux keyring requirements, Ubuntu AppImage setup, checksums and building your own package.

## Your first task

1. Open **Settings → Models → Add or edit model**. Enter a name, API base URL, model ID and API key, then test the connection.
2. Add a local project folder. Keep **Link this directory** selected to work in the original folder. A folder without Git is initialized as a repository.
3. Start a conversation in that project. Select the model, **Lead agent only**, and the permissions you want to allow.
4. Describe the change and how to check it. For example:

   ```text
   Find the endpoint that lists orders. Add pagination, keeping the existing
   response fields. Run the relevant tests and explain any failures.
   ```

5. Read the reply, open the changed files and inspect the diff. Command output is recorded with the tool calls. Send a follow-up message if the result needs adjustment.

You can attach files to a conversation and open the right-hand inspector to browse files, reviews, previews and terminal activity. See [projects and conversations](docs/WORKSPACE.md) for the main controls and [model setup](docs/MODELS.md) for connection details.

## Working with a team

Choose multi-agent collaboration in the composer when the task has separate responsibilities. The lead prepares a plan with member roles, tasks, file ownership and models. Use **Adjust team** to change it, then **Confirm execution** to start that plan. Each new task or round of feedback needs its own confirmation.

Members follow the lead model unless you select another model for them. The team view shows their status and reports; tool records show what they actually ran. You can add instructions while they work, pause the conversation or stop it. Before accepting the result, inspect the changes and the test output. The [collaboration guide](docs/AUTONOMOUS_COLLABORATION.md) walks through this process.

## Adding instructions and tools

Open **Customization** to manage extensions.

| Extension | Use it for |
| --- | --- |
| Skills | Reusable instructions in a `SKILL.md` file. Project Skills live in `.agents/skills/`. |
| MCP servers | Tools provided by a configured local or remote server. |
| dsh plugins | Tools, model providers and interface components from the deepseek-harness ecosystem. |
| Command plugins | Tools implemented by a local command. |

Open an installed plugin's details to configure it. A plugin may need its own account, API key or external program before its tools can be used. The composer **+** menu lists enabled capabilities. Read the [extension guide](docs/extensions.md) to choose an extension type, or the [dsh guide](docs/NATIVE_CORDIS.md) to install or develop a plugin.

## Permissions and data

The composer offers three permission levels: **Ask for approval** asks before file changes and commands; **Allow file edits** allows file editing but still asks before commands; **Full access** permits file operations, commands and enabled external tools. The [permissions guide](docs/sandbox.md) explains what these settings control.

Projects, conversations and attachments are stored locally. Requests to your configured model service include the context needed for the task; enabled extensions may also send data to their services. Model-profile API keys use the operating system credential store. Local commands and native plugins run with your user account's system permissions.

Installed data lives in `%APPDATA%\Micro-Multi\data` on Windows and `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data` on Linux. Source mode uses `.masp` in the working directory. Set `MASP_HOME` to choose another directory. Updates and uninstall preserve the data; back it up separately from the application files.

## Run from source

Use Python 3.11+, Node.js 24+, npm and Git. From the repository root:

```bash
python -m venv .venv
```

Activate the environment with `.\.venv\Scripts\Activate.ps1` in Windows PowerShell, or `source .venv/bin/activate` on Linux. Then run:

```bash
python -m pip install -e ".[dev]"
npm ci
npm run desktop
```

To use a browser instead, run `python -m masp.cli serve` and open `http://127.0.0.1:3080/`. The [deployment guide](docs/deployment.md) explains configuration and data storage.

## Technology

| Layer | Implementation |
| --- | --- |
| Desktop | Electron, with a sandboxed renderer and a preload bridge for desktop actions. |
| Backend | Python, FastAPI, Uvicorn and Pydantic for local APIs and agent execution. |
| Interface | HTML, CSS and JavaScript; React renders native plugin components. |
| Agent and plugin runtime | Node.js, Cordis and deepseek-harness packages. |
| Storage | SQLite for application records, local files for attachments and the OS credential store for model keys. |
| Connections | HTTP APIs, SSE for streamed conversation events and WebSocket for plugin subscriptions. |
| Builds and documentation | electron-builder, esbuild and a static site generated from Markdown. |

The [architecture guide](docs/architecture.md) describes how these parts communicate and points to the relevant source directories.

## Documentation and contributing

Start with [model setup](docs/MODELS.md), [projects and conversations](docs/WORKSPACE.md), [team collaboration](docs/AUTONOMOUS_COLLABORATION.md) and [extensions](docs/extensions.md). If something does not work as expected, see [troubleshooting](docs/TROUBLESHOOTING.md).

Report reproducible bugs in [Issues](https://github.com/LKDenchin/Micro-Multi/issues), including the steps and sanitized logs. Questions and ideas belong in [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions). Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting code. Report vulnerabilities through the private channel in [SECURITY.md](SECURITY.md).

Micro-Multi is licensed under [Apache-2.0](LICENSE). Third-party components retain their own licenses; see [NOTICE](NOTICE) and [runtime provenance](docs/UPSTREAM_RUNTIME_PROVENANCE.md).
