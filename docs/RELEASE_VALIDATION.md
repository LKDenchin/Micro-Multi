# Desktop release validation — 2026-10-02

Validated locally on Windows 10 x64 with Python 3.14.7 and Ubuntu 24.04.5 x64 in a disposable VM with Python 3.14.8. Both desktop distributions use Electron 43.7.7. Checks use temporary data, synthetic credentials and offline fixtures.

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 252 passed, 1 skipped; repeated after formatting/lint changes (261.20 s) |
| `python -m ruff check src tests scripts` | Passed |
| `python -m ruff format --check src tests scripts` | Passed, 100 files |
| `python -m mypy src/masp` | Passed, 45 source files |
| `python -m build` | Wheel and source archive built successfully |
| Windows NSIS build | Installer generated successfully |
| Linux AppImage build | Single-file x86_64 package generated successfully |
| Linux isolated executable smoke | Passed outside the source checkout with D-Bus, GNOME Keyring and Xvfb |
| Linux Debian build | amd64 package generated successfully |
| Actual Debian reinstall | Exit 0; final package installed through apt |
| Installed Debian executable smoke | Passed using `/opt/Micro-Multi` with empty temporary data |
| Actual Debian removal | Exit 0; installed executable removed |
| Required Node dependency closure | 194 required packages and peers verified inside each distribution |
| Main process source consistency | Windows build, installed Debian and final AppImage match current source |
| Final AppImage entry point | Passed via `--appimage-extract-and-run` with application-specific AppArmor policy and Chromium sandboxing enabled |
| Packaged executable smoke | Passed outside source checkout with isolated data |
| Actual silent installation | Exit 0; executable present in disposable installation directory |
| Installed executable smoke | Passed using the actual installed files |
| Actual silent uninstall | Exit 0; installed executable removed |
| Publication audit | Passed; known token/private-key patterns and runtime paths checked |
| Git history scan | 323 blobs checked; no known API/GitHub token or private-key patterns found |
| README/supporting guide links | Local links checked; none missing |
| Installer Authenticode | NotSigned |

## Packaged smoke coverage

- Python backend starts from the bundled embedded runtime.
- Health endpoint reports built-in MCP ready.
- Initial project, conversation and model-profile lists are empty.
- The actual renderer loads; its sandboxed desktop preload bridge is available.
- OS-backed credentials resolve to `WinVaultKeyring` on Windows and Secret Service on Linux; synthetic set/get/delete checks pass.
- Packaged review CLI is discoverable.
- Native Cordis Host initializes through the bundled Electron Node runtime.
- Renderer startup has no load failure.
- Temporary test data and the test process tree are removed.

No model service requests or real API credentials were used. The Windows symlink test was skipped.

## Clean distribution

The local `.masp`, `evidence`, `.research`, and `docs/screenshots` directories were erased, including uploaded objects, sessions, copied projects, extensions, logs and caches in those directories. Two matching `masp-workspace` credential entries were removed from Windows Credential Manager. Original source code and project repositories outside the application's data directories were preserved.

The installer allowlist includes application source, production runtime dependencies, licenses and icons. It does not include runtime databases, logs, attachments, personal projects, test evidence or local environment files. Installed app data uses the user's writable application directory, not the installation directory.

## Release assets

The [v0.1.0 Release](https://github.com/LKDenchin/Micro-Multi/releases/tag/v0.1.0) distributes:

- `Micro-Multi-Setup-0.1.0-x64.exe` — Windows x64 installer.
- `Micro-Multi-0.1.0-amd64.deb` — Debian / Ubuntu x64 package.
- `Micro-Multi-0.1.0-x86_64.AppImage` — Linux x64 single-file application.
- `SHA256SUMS.txt` — SHA-256 digests for all three installation packages.

Use the Release checksum file to verify downloads. The Windows installer is unsigned. Package metadata links to the official source repository and issue tracker.

## 中文

Windows、Linux deb 与 AppImage 三种包均已生成。Windows 和 deb 的实际安装、启动及卸载检查通过；最终 AppImage 使用单文件解压运行入口验证实际资源、界面和 dsh 运行时。三种包的 194 项必要 Node 依赖及 peer 依赖均完整，主进程与源码一致。252 项测试、静态检查、格式检查和类型检查通过。1 项 Windows 符号链接测试跳过。测试使用临时数据和合成凭据。

用户数据及两个模型凭据条目已清除，首次启动为空白状态。当前安装包未签名。安装包与 SHA-256 校验清单通过 [v0.1.0 Release](https://github.com/LKDenchin/Micro-Multi/releases/tag/v0.1.0) 分发。软件包元信息链接到正式源码仓库和问题追踪页面。
