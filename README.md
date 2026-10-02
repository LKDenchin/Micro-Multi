<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="96" />
  <h1>Micro-Multi</h1>
  <p><strong>Your local workspace for a team of AI agents.</strong></p>
  <p>English · <a href="README.zh-CN.md">简体中文</a></p>
  <p><a href="#quick-install">Install</a> · <a href="#getting-started">Get started</a> · <a href="#documentation">Documentation</a> · <a href="CONTRIBUTING.md">Contribute</a></p>
  <p><a href="https://github.com/LKDenchin/Micro-Multi/releases/latest"><img src="https://img.shields.io/github/v/release/LKDenchin/Micro-Multi" alt="Release" /></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0" /></a> <a href="https://github.com/LKDenchin/Micro-Multi/actions/workflows/ci.yml"><img src="https://github.com/LKDenchin/Micro-Multi/actions/workflows/ci.yml/badge.svg" alt="CI" /></a> <img src="https://img.shields.io/badge/dsh-plugins%20compatible-4C8CFA" alt="dsh plugins compatible" /></p>
</div>

Micro-Multi brings conversations, code, tools, and a team of agents into one desktop workspace. Describe what you want to build: the lead agent can break down the work, bring in specialists, run tasks in parallel, review their results, and continue until the work is ready for you to inspect.

Connect your own OpenAI-compatible model endpoint, choose models for different agents, and work with your local Git projects. You can follow what each agent is doing, inspect the files it changes, and keep the conversation for the next session.


**Compatible with the deepseek-harness (dsh) plugin ecosystem.** Micro-Multi runs native dsh Cordis Host plugins, bringing their tools into the lead agent and specialist agents in your desktop workspace.

| | What you can do |
| --- | --- |
| **dsh plugin compatibility** | Load native deepseek-harness Cordis Host packages with tool registration, services, dependency injection, events, and lifecycle management. |
| **A team that works together** | Delegate to specialist agents, run independent tasks concurrently, and collect reports as they finish. |
| **Your models, your choice** | Configure compatible API endpoints, test connections, and choose a model for each agent. |
| **A visible workspace** | Browse projects, files, diffs, reviews, previews, terminal output, and tool records without switching apps. |
| **Conversations that continue** | Keep streamed replies and task history locally; resume work and compact context as a session grows. |
| **Tools you can extend** | Add Skills, MCP servers, local command plugins, and Cordis Host packages. |
| **Control when you need it** | Choose permissions, inspect requested operations, pause work, and stop a running turn. |
| **A desktop that fits your workflow** | Paste attachments, pick project folders, and switch between English and Chinese, light and dark themes. |

---

## Quick Install

Download the package for your system from the **[Releases page](https://github.com/LKDenchin/Micro-Multi/releases/latest)**. To build a package yourself, follow the [desktop build guide](docs/DESKTOP_RELEASE.md).

| Platform / 平台 | Download / 下载 |
| --- | --- |
| Windows x64 | [Micro-Multi-Setup-0.1.0-x64.exe](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-Setup-0.1.0-x64.exe) |
| Debian / Ubuntu x64 | [Micro-Multi-0.1.0-amd64.deb](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-amd64.deb) |
| Linux x64 AppImage | [Micro-Multi-0.1.0-x86_64.AppImage](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-x86_64.AppImage) |
| SHA-256 | [SHA256SUMS.txt](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/SHA256SUMS.txt) |

### Windows

Run `Micro-Multi-Setup-0.1.0-x64.exe`, choose an installation directory, and launch Micro-Multi from the Start menu.

### Linux — Debian / Ubuntu

```bash
sudo apt install ./Micro-Multi-0.1.0-amd64.deb
micro-multi
```

### Linux — AppImage

```bash
chmod +x Micro-Multi-0.1.0-x86_64.AppImage
./Micro-Multi-0.1.0-x86_64.AppImage
```

If FUSE is unavailable, run the AppImage with `--appimage-extract-and-run`.

On Ubuntu 24.04+, enable the application-specific user namespace policy described in the [AppImage setup guide](docs/DESKTOP_RELEASE.md#ubuntu-appimage-sandbox-policy).

The desktop packages include Python and Node. Install Git for repository operations; Docker and external extension tools are optional and installed separately. Linux model-key storage requires an active Secret Service keyring, such as GNOME Keyring. Compare your download against `SHA256SUMS.txt`; the Windows installer is currently unsigned.

---

## Getting Started

1. **Connect a model.** Open Models, enter your API endpoint, model ID, and key, then test the connection.
2. **Open a project.** Create a project or import a local Git repository.
3. **Describe the outcome.** Start a conversation with a task such as “Add pagination to this API and verify the behavior.”
4. **Let the team work.** Choose multi-agent collaboration when the task benefits from specialists, or use the lead agent alone.
5. **Review the result.** Inspect changed files, tool activity, reviews, and verification before using the work.

You can adjust an agent's model or responsibility, add an attachment, and continue the conversation with feedback. Projects and conversations are kept locally across sessions.

---

## Models and Extensions

Use an endpoint compatible with OpenAI Chat Completions. Micro-Multi stores model-profile keys in the operating system credential store; no model credentials are included in the app.

Skills give agents reusable instructions. Discover project Skills in `.agents/skills/`, or add user Skills through the workspace. MCP servers and plugins connect additional tools. Install trusted extensions from Settings and inspect the access they request.

See [autonomous collaboration](docs/AUTONOMOUS_COLLABORATION.md) and the [extension guide](docs/NATIVE_CORDIS.md) for more details.

---

## deepseek-harness Plugin Ecosystem

Micro-Multi uses the official dsh Cordis and tools runtimes. Load a built dsh Cordis Host package from Settings → Extensions: its tools become available to both the lead agent and specialist agents. Plugins can register services, inject dependencies, validate configuration and tool parameters, publish events, and release resources when disabled or removed.

Each package keeps its own state within a workspace. The host provides `tools`, `systemPrompt`, and `microMulti` services; `microMulti.workspace` and `microMulti.pluginRoot` expose the workspace and package locations. Use these host services when developing plugins.

Try the included [`examples/native-cordis`](examples/native-cordis) package, or follow the [dsh plugin guide](docs/NATIVE_CORDIS.md) to load your own package. See the [dsh repository](https://github.com/deepseek-ai/deepseek-harness) for the plugin framework.

---

## Workspace Quick Reference

| Action | Where to find it |
| --- | --- |
| Add or test a model | Models |
| Create or import a project | Project navigation |
| Start or reopen a conversation | Conversation list |
| Choose collaboration mode or a model | Conversation composer |
| Follow individual agents | Team view and tool records |
| Inspect files, diffs, reviews, or terminal activity | Workspace inspector |
| Add Skills, MCP servers, or plugins | Settings / extensions |
| Change language, theme, or layout | Settings |

---

## Run from Source

Use Python 3.11+, Node.js 24+, npm, and Git. From the repository root:

```bash
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on Linux/macOS or `.\.venv\Scripts\Activate.ps1` in Windows PowerShell, then run:

```bash
python -m pip install -e ".[dev]"
npm ci
npm run desktop
```

For browser access, run `python -m masp.cli serve` and open <http://127.0.0.1:8765/>.

| Setting | Purpose |
| --- | --- |
| `MASP_HOME` | Override local data storage; source default is `.masp` |
| `MASP_PORT` | Desktop backend port; default `8765` |
| `MASP_MODEL_BASE_URL` | Optional environment-configured model endpoint |
| `MASP_MODEL_NAME` | Optional environment-configured model ID |
| `MASP_MODEL_API_KEY` | Optional model credential; never commit it |

Installed data defaults to `%APPDATA%\Micro-Multi\data` on Windows and `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data` on Linux. Updates and uninstall preserve user data.

---

## Documentation

| Guide | What's covered |
| --- | --- |
| [Desktop build and release](docs/DESKTOP_RELEASE.md) | Building installers, running checks, and publishing packages |
| [Autonomous collaboration](docs/AUTONOMOUS_COLLABORATION.md) | Delegation, parallel work, progress, and review |
| [Extensions](docs/NATIVE_CORDIS.md) | Cordis Host packages and a working example |
| [Persistence and recovery](docs/DURABLE_TURNS_AND_MODEL_RECOVERY.md) | Saved turns, interruptions, and recovery |
| [Security](SECURITY.md) | Data, command permissions, and reporting vulnerabilities |
| [Contributing](CONTRIBUTING.md) | Development setup, checks, and pull requests |
| [Changelog](CHANGELOG.md) | Release history |

---

## Contributing

Contributions are welcome: bug fixes, tests, translations, documentation, and extensions. Read [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md), and include the validation you actually ran.

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m mypy src/masp
```

## Community

Use [Issues](https://github.com/LKDenchin/Micro-Multi/issues) for reproducible bugs and feature requests. Include your version, operating system, reproduction steps, and sanitized logs. For questions and ideas, visit [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions). Report vulnerabilities through the private channel described in [SECURITY.md](SECURITY.md).

Your conversations and uploads stay in local storage, but configured models and enabled extensions can receive the context needed to perform tasks. Local command execution runs on your machine; permission checks are not an operating system sandbox.

---

## License

[Apache-2.0](LICENSE). Third-party components retain their licenses and notices; see [NOTICE](NOTICE) and [runtime provenance](docs/UPSTREAM_RUNTIME_PROVENANCE.md).
