# 桌面发布验证 — 2026-10-02

在 Windows 10 x64（Python 3.14.7）和可丢弃 Ubuntu 24.04.5 x64 虚拟机（Python 3.14.8）验证。两种桌面发行版使用 Electron 43.7.7。测试使用临时数据、合成凭据和离线样例。本记录仅描述当日发布基线，不替代当前源码测试。

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q` | 252 项通过，1 项跳过；格式及 lint 修改后复跑（261.20 秒） |
| `python -m ruff check src tests scripts` | 通过 |
| `python -m ruff format --check src tests scripts` | 通过，100 个文件 |
| `python -m mypy src/masp --platform linux` | 通过，45 个源码文件 |
| `python -m mypy src/masp --platform win32` | 通过，45 个源码文件 |
| 原生进程与扩展回归 | 平台保护修正后 34 项通过 |
| `python -m build` | wheel 及源码归档成功 |
| Windows NSIS、Linux AppImage 及 Debian 构建 | 均成功 |
| Linux 独立/已安装程序冒烟 | 在源码目录外，使用 D-Bus、GNOME Keyring 和 Xvfb 通过 |
| Debian 实际重装及移除 | apt 安装退出码 0，移除退出码 0 且程序删除 |
| 必要 Node 依赖闭包 | 每个发行包验证 194 个必要包及 peer |
| 主进程源码一致性 | Windows、已安装 Debian 和最终 AppImage 与当时源码一致 |
| 最终 AppImage 入口 | 解压运行、应用专用 AppArmor 策略及 Chromium 沙箱启用时通过 |
| Windows 实际静默安装/卸载 | 退出码均 0，安装后存在程序，卸载后删除 |
| Windows 已安装程序冒烟 | 实际安装文件通过 |
| 发布审计 | 已知密钥/令牌模式及运行数据路径检查通过 |
| Git 历史扫描 | 323 个 blob，无已知 API/GitHub 令牌或私钥模式 |
| README 及指南链接 | 无缺失本地链接 |
| 安装包 Authenticode | 未签名 |

## 安装版冒烟覆盖

- 内置 Python 后端启动，健康接口报告内置 MCP 就绪。
- 初始项目、对话及模型列表为空。
- 真实渲染界面加载，沙箱 preload 桥可用。
- Windows 使用 WinVaultKeyring，Linux 使用 Secret Service；合成凭据读写删除通过。
- 审查 CLI 可发现，原生 Cordis Host 通过内置 Electron Node 初始化。
- 渲染启动无加载错误；清理临时数据及测试进程树。

未请求模型服务或使用真实 API 凭据，Windows 符号链接测试跳过。

## 干净发行包

当日发布准备清除了 `.masp`、`evidence`、`.research` 和 `docs/screenshots` 中的上传、会话、复制项目、扩展、日志及缓存，并移除两个相应 Windows 模型凭据。应用数据目录外的原始源码和项目仓库保留。这是历史记录，不是此次更新的数据删除指令。

安装允许列表仅包含源码、生产依赖、许可证和图标，排除数据库、日志、附件、私人项目、测试证据和环境文件。安装版数据位于用户可写目录，不位于安装目录。

## 发布附件

[v0.1.0 Release](https://github.com/LKDenchin/Micro-Multi/releases/tag/v0.1.0) 分发：

- `Micro-Multi-Setup-0.1.0-x64.exe`：Windows x64 安装程序。
- `Micro-Multi-0.1.0-amd64.deb`：Debian/Ubuntu x64 包。
- `Micro-Multi-0.1.0-x86_64.AppImage`：Linux x64 单文件。
- `SHA256SUMS.txt`：三种包的 SHA-256。

下载后使用 Release 校验文件验证。Windows 包未签名；包元信息链接官方源码及问题追踪。后续源码变化见[当前变化](CURRENT_CHANGES.zh-CN.md)。
