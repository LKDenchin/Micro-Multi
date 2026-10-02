# Micro-Multi v0.1.0 — Desktop release

## English

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

## 简体中文

Micro-Multi 将本地多 Agent 开发工作台带到 Windows 和 Linux。

- Windows x64 安装程序，支持目录选择、快捷方式和卸载。
- Linux x64 `.deb` 安装包和 AppImage 单文件。
- 内置 Python 后端与 Node 运行时，应用启动不需另外安装这两者。
- 持久化对话、剪贴板附件、项目浏览、改动审查和桌面恢复。
- 主 Agent 与成员自主协作，提供模型选择、取消、进度和验证记录。
- 兼容 deepseek-harness（dsh）Cordis Host 插件体系，同时支持 Skills、MCP 工具与本地命令插件。
- 中英文文档与界面，首次启动不包含个人项目、附件、历史或模型密钥。

根据系统选择上表中的安装包，并对照 `SHA256SUMS.txt` 校验。Windows 运行安装程序；Debian/Ubuntu 使用 `sudo apt install ./<软件包>.deb`；AppImage 添加执行权限后直接运行。Ubuntu 的应用专用命名空间策略见[安装指南](https://github.com/LKDenchin/Micro-Multi/blob/v0.1.0/docs/DESKTOP_RELEASE.md#ubuntu-appimage-sandbox-policy)。启动后配置自己的模型。Git 仓库操作需要 Git，外部插件工具和 Docker 另行安装。

安装前校验软件包。当前 Windows 安装包未签名，更新需手动安装。卸载保留用户数据；Linux 密钥存储使用 Secret Service 凭据库。启动后配置自己的模型接口与凭据。

---

[English documentation](https://github.com/LKDenchin/Micro-Multi/blob/v0.1.0/README.md) · [简体中文文档](https://github.com/LKDenchin/Micro-Multi/blob/v0.1.0/README.zh-CN.md) · [Changelog](https://github.com/LKDenchin/Micro-Multi/blob/v0.1.0/CHANGELOG.md) · [Issues](https://github.com/LKDenchin/Micro-Multi/issues) · [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions)
