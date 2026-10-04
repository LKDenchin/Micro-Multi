# Micro-Multi v0.1.0 — Desktop release

Micro-Multi brings its local multi-agent development workspace to Windows and Linux.

- Windows x64 installer with directory selection, shortcuts and uninstall support.
- Linux x64 Debian package and portable AppImage single-file distribution.
- Bundled Python backend and Node runtime; no separate Python or Node installation needed for the app.
- Persistent conversations, clipboard attachments, project browsing, diff/review views and desktop recovery.
- Autonomous lead/worker collaboration with model selection, cancellation, progress and verification records.
- Compatibility with the deepseek-harness (dsh) Cordis Host plugin ecosystem, plus Skills, MCP tools and local command plugins.
- English and Simplified Chinese documentation and UI.
- Clean first launch with no shipped personal projects, uploads, chat history or model credentials.

### Installation

Choose the package for your system and verify it against `SHA256SUMS.txt`:

| System | Asset |
| --- | --- |
| Windows x64 | `Micro-Multi-Setup-0.1.0-x64.exe` |
| Debian / Ubuntu x64 | `Micro-Multi-0.1.0-amd64.deb` |
| Linux x64 portable | `Micro-Multi-0.1.0-x86_64.AppImage` |

Run the Windows installer, install the Debian package with `sudo apt install ./<package>.deb`, or make the AppImage executable and launch it. See the [AppImage setup guide](https://github.com/LKDenchin/Micro-Multi/blob/v0.1.0/docs/DESKTOP_RELEASE.md#ubuntu-appimage-sandbox-policy) for Ubuntu's application-specific namespace policy. Configure your own model and create or import a project. Git is required for repository work; external plugin tools and Docker are installed separately.

### Runtime and installation

Verify package checksums before installation. The Windows installer is unsigned; install updates manually. Uninstall preserves local user data. Linux profile keys use a Secret Service keyring. Configure your own model endpoint and credentials after launch.


[Documentation](https://lkdenchin.github.io/Micro-Multi/docs/readme.html) · [Changelog](../CHANGELOG.md) · [Issues](https://github.com/LKDenchin/Micro-Multi/issues) · [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions)

For subsequent source updates, see [current changes](CURRENT_CHANGES.md).
