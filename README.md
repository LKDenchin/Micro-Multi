<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="88" />
  <h1>Micro-Multi</h1>
  <p>Split work across agents in one project. Compatible with DeepSeek Harness plugins.</p>
  <p>English · <a href="README.zh-CN.md">简体中文</a></p>
  <p><a href="https://lkdenchin.github.io/Micro-Multi/">Website</a> · <a href="#installation">Install</a> · <a href="#your-first-task">Get started</a> · <a href="https://lkdenchin.github.io/Micro-Multi/docs/readme.html">Documentation</a></p>
</div>

Micro-Multi is a local desktop workspace built around **multi-agent collaboration**. You describe the job; the lead agent splits it into assignments. After you approve the plan, members work within their file ownership and task dependencies, and the lead combines their results. Plans, member progress, tool output and code diffs share one workspace.

For an order API change, one member implements pagination, another writes boundary tests, and a third documents the parameters. Independent assignments can run together. A test task that needs the implementation waits for its report. The scheduler coordinates concurrent writes to the same file.

**DeepSeek Harness (dsh) plugin compatibility** is the other core part of the project. Native Cordis Host and the dsh client module system load declared services, tools, settings forms and interface contributions. Enabled tools are available to team members as well as the lead. Skills and MCP services also work alongside these plugins.

Windows / Linux · English and Chinese · Your choice of model service · Apache-2.0

## Why coordinate agents?

A single agent works well for short jobs. When implementation, tests and review share one execution loop, they usually happen in sequence and share one context. A prompt that says “divide the work” does not enforce who can edit which files, which task must wait, or whether an assignment has already started. That needs a scheduler.

| A single agent, or agents without a coordinator | What Micro-Multi does |
| --- | --- |
| Implementation, tests and docs run in sequence | Runs independent tasks concurrently; dependencies wait for predecessor reports. Concurrency is bounded. |
| Several members edit the same file | Uses declared file ownership, path locks and dependencies to coordinate writes. |
| Every role uses the same model | Members inherit the lead model; you can change individual models in the plan. |
| Retries dispatch the same assignment again | Reuses running or completed assignments; an approved revision starts once. |
| Plugins are only wired to the lead | Enabled dsh, MCP and command tools are available to the lead and members. |

This compares execution models, not benchmark results. Parallel work can reduce waiting for independent tasks, but extra members can increase model calls and cost. Use the lead alone for a small edit; use a team when the responsibilities are clear.

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
3. Start a conversation in that project. Select the model, **Multi-agent collaboration**, and the permissions you want to allow.
4. Describe the change and how to check it. For example:

   ```text
   Add pagination to the order API, keeping the existing response fields.
   Assign implementation, boundary tests and parameter docs to separate members.
   List their files and dependencies. The lead combines changes and runs tests.
   ```

5. Review the plan in the chat. Adjust members, models or files, then confirm execution.
6. Follow member progress and inspect the diff and test output. Send a follow-up in the same conversation if the result needs adjustment.

You can attach files to a conversation and open the right-hand inspector to browse files, reviews, previews and terminal activity. See [projects and conversations](docs/WORKSPACE.md) for the main controls and [model setup](docs/MODELS.md) for connection details.

## Working with a team

The lead prepares a plan with member roles, tasks, file ownership, dependencies and models. Use **Adjust team** to change it, then **Confirm execution** to start that revision. Member tasks do not run before approval. Each new task or round of feedback needs its own confirmation.

Confirmation checks the saved server revision. If a plan has changed, the chat card shows the updated assignments for review and confirmation in place. You do not need to open the collaboration map.

Members follow the lead model unless you select another model for them. The team view shows their status and reports; tool records show what they actually ran. You can add instructions while they work, pause the conversation or stop it. Before accepting the result, inspect the changes and the test output. The [collaboration guide](docs/AUTONOMOUS_COLLABORATION.md) walks through this process.

## Adding instructions and tools

Open **Customization** to manage extensions.

| Extension | Use it for |
| --- | --- |
| Skills | Reusable instructions in a `SKILL.md` file. Project Skills live in `.agents/skills/`. |
| MCP servers | Tools provided by a configured local or remote server. |
| dsh plugins | Native Cordis services and tools, model providers, settings forms and conversation interface components. |
| Command plugins | Tools implemented by a local command. |

Open an installed plugin's details to configure it. A plugin may need its own account, API key or external program before its tools can be used. The composer **+** menu lists enabled capabilities. Read the [extension guide](docs/extensions.md) to choose an extension type, or the [dsh guide](docs/NATIVE_CORDIS.md) to install or develop a plugin.

Compatibility depends on a package's declared entries, dependencies and required services; it does not mean every third-party package has been tested. Startup restores the chat before loading optional plugin clients. Probing a plugin without a client does not boot its Host. Native services keep dsh's dependency and lifecycle rules.

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
