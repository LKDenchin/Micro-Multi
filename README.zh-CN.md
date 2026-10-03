<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="96" />
  <h1>Micro-Multi</h1>
  <p><strong>让一支 AI Agent 团队，在你的本地工作区协作。</strong></p>
  <p><a href="README.md">English</a> · 简体中文</p>
  <p><a href="https://lkdenchin.github.io/Micro-Multi/zh/">官网</a> · <a href="#快速安装">安装</a> · <a href="#开始使用">开始使用</a> · <a href="https://lkdenchin.github.io/Micro-Multi/docs/readme-zh-cn.html">文档</a> · <a href="CONTRIBUTING.md">参与贡献</a></p>
  <p><a href="https://github.com/LKDenchin/Micro-Multi/releases/latest"><img src="https://img.shields.io/github/v/release/LKDenchin/Micro-Multi" alt="Release" /></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0" /></a> <a href="https://github.com/LKDenchin/Micro-Multi/actions/workflows/ci.yml"><img src="https://github.com/LKDenchin/Micro-Multi/actions/workflows/ci.yml/badge.svg" alt="CI" /></a> <img src="https://img.shields.io/badge/dsh-plugins%20compatible-4C8CFA" alt="dsh plugins compatible" /></p>
</div>

Micro-Multi 将对话、代码、工具和 Agent 团队放进同一个桌面工作台。描述你想完成的任务，主 Agent 可以拆分工作、创建专业成员、并行执行、审查结果，并继续推进，直到你可以检查交付内容。

连接自己的 OpenAI 兼容模型接口，为不同 Agent 选择模型，直接使用本地 Git 项目。你可以跟踪每个成员的操作、查看文件改动，并保留对话，在下一次打开应用时继续工作。


**兼容 deepseek-harness（dsh）插件体系。** Micro-Multi 原生运行 dsh Cordis Host 插件，让插件工具直接参与桌面工作区中主 Agent 与专业成员的协作。

| | 你可以做什么 |
| --- | --- |
| **dsh 插件体系兼容** | 加载原生 deepseek-harness Cordis Host 扩展包，支持工具注册、服务与依赖注入、事件和生命周期管理。 |
| **一起工作的团队** | 向专业成员委派任务，并行推进独立工作，按完成顺序收集报告。 |
| **自由选择模型** | 配置兼容 API 地址、检测连接，为每个 Agent 选择模型。 |
| **看得见的工作区** | 集中浏览项目、文件、改动、审查、预览、终端输出和工具记录。 |
| **可以继续的对话** | 本地保存流式回复和任务历史，恢复工作，并在会话增长时压缩上下文。 |
| **可以扩展的工具** | 添加 Skills、MCP 服务、本地命令插件与 Cordis Host 扩展包。 |
| **随时掌握控制权** | 选择权限、检查操作请求、暂停工作或停止当前执行。 |
| **适合日常工作的桌面应用** | 粘贴附件、选择项目目录，切换中英文、明暗主题与布局。 |

---

## 快速安装

在 [Releases 页面](https://github.com/LKDenchin/Micro-Multi/releases/latest) 下载对应系统的软件包。自行构建请参考[桌面构建指南](docs/DESKTOP_RELEASE.md)。

| 平台 | 下载 |
| --- | --- |
| Windows x64 | [Micro-Multi-Setup-0.1.0-x64.exe](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-Setup-0.1.0-x64.exe) |
| Debian / Ubuntu x64 | [Micro-Multi-0.1.0-amd64.deb](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-amd64.deb) |
| Linux x64 AppImage | [Micro-Multi-0.1.0-x86_64.AppImage](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-x86_64.AppImage) |
| SHA-256 | [SHA256SUMS.txt](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/SHA256SUMS.txt) |

### Windows

运行 `Micro-Multi-Setup-0.1.0-x64.exe`，选择安装目录，然后从开始菜单启动 Micro-Multi。

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

没有 FUSE 时，可添加 `--appimage-extract-and-run` 运行。

Ubuntu 24.04 及以上系统，请按 [AppImage 安装指南](docs/DESKTOP_RELEASE.md#ubuntu-appimage-sandbox-policy)启用应用专用的用户命名空间策略。

桌面包内置 Python 和 Node。Git 仓库操作需要安装 Git；Docker 和外部扩展工具按需另行安装。Linux 模型密钥存储需要正在运行的 Secret Service 凭据库，例如 GNOME Keyring。下载后对照 `SHA256SUMS.txt` 校验；当前 Windows 安装包未签名。

---

## 开始使用

1. **连接模型。** 在“模型”中输入 API 地址、模型 ID 和密钥，检测连接。
2. **打开项目。** 新建项目或导入本地 Git 仓库。
3. **描述目标。** 创建对话，例如：“给这个 API 添加分页，并验证行为。”
4. **让团队工作。** 需要专业分工时选择多 Agent 协作，也可以只使用主 Agent。
5. **检查结果。** 查看文件改动、工具记录、审查和验证，再使用交付内容。

你可以调整成员模型和职责、添加附件，并通过后续对话给出反馈。项目和对话保存在本地，关闭应用后仍可继续。

---

## 模型与扩展

使用兼容 OpenAI Chat Completions 的接口。Micro-Multi 将模型配置中的密钥存入系统凭据库，应用不附带任何模型凭据。

Skills 为 Agent 提供可复用的工作指令。项目技能可从 `.agents/skills/` 发现，也可以通过工作台添加用户技能。MCP 服务和插件连接额外工具；在设置中安装可信扩展，并检查它们请求的权限。

详见[自主协作](docs/AUTONOMOUS_COLLABORATION.md)和[扩展指南](docs/NATIVE_CORDIS.md)。

---

## deepseek-harness 插件体系

Micro-Multi 使用官方 dsh Cordis 与工具运行时。在“设置 → 扩展”加载已构建的 dsh Cordis Host 插件包后，主 Agent 和专业成员都可以使用其工具。插件可注册服务、注入依赖、校验配置与工具参数、发布事件，并在禁用或移除时释放资源。

每个插件包在工作区内保持独立状态。宿主提供 `tools`、`systemPrompt` 和 `microMulti` 服务，`microMulti.workspace` 与 `microMulti.pluginRoot` 分别提供工作区和插件目录。开发插件时，可使用这些宿主服务。

可以直接体验仓库中的 [`examples/native-cordis`](examples/native-cordis)，或按照 [dsh 插件指南](docs/NATIVE_CORDIS.md)加载自己的插件包。插件框架详见 [dsh 仓库](https://github.com/deepseek-ai/deepseek-harness)。

---

## 工作区速查

| 操作 | 入口 |
| --- | --- |
| 添加模型或检测连接 | 模型 |
| 创建或导入项目 | 项目导航 |
| 创建或重新打开对话 | 对话列表 |
| 选择协作模式或模型 | 对话输入区 |
| 跟踪成员操作 | 团队视图与工具记录 |
| 检查文件、改动、审查和终端 | 工作区检查面板 |
| 添加 Skills、MCP 或插件 | 设置 / 扩展 |
| 修改语言、主题或布局 | 设置 |

---

## 从源码运行

需要 Python 3.11+、Node.js 24+、npm 和 Git。在仓库根目录执行：

```bash
python -m venv .venv
```

Linux/macOS 执行 `source .venv/bin/activate` 激活环境；Windows PowerShell 执行 `.\.venv\Scripts\Activate.ps1`，然后运行：

```bash
python -m pip install -e ".[dev]"
npm ci
npm run desktop
```

使用浏览器时，执行 `python -m masp.cli serve`，打开 <http://127.0.0.1:3080/>。

| 设置 | 用途 |
| --- | --- |
| `MASP_HOME` | 指定本地数据目录；源码运行默认使用 `.masp` |
| `MASP_PORT` | 桌面后端端口，默认 `3080` |
| `MASP_MODEL_BASE_URL` | 可选的环境变量模型 API 地址 |
| `MASP_MODEL_NAME` | 可选的环境变量模型 ID |
| `MASP_MODEL_API_KEY` | 可选模型密钥，不应提交到仓库 |

安装版数据默认位于 Windows 的 `%APPDATA%\Micro-Multi\data` 或 Linux 的 `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data`。更新和卸载保留用户数据。

---

## 文档

| 指南 | 内容 |
| --- | --- |
| [桌面构建与发布](docs/DESKTOP_RELEASE.md) | 构建安装包、运行检查和发布 |
| [自主协作](docs/AUTONOMOUS_COLLABORATION.md) | 任务委派、并行工作、进度和审查 |
| [扩展](docs/NATIVE_CORDIS.md) | Cordis Host 包与可运行示例 |
| [持久化与恢复](docs/DURABLE_TURNS_AND_MODEL_RECOVERY.md) | 保存对话、中断和恢复 |
| [安全](SECURITY.md) | 数据、命令权限和漏洞报告 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、检查和 Pull Request |
| [更新记录](CHANGELOG.md) | 版本历史 |

---

## 参与贡献

欢迎贡献修复、测试、翻译、文档和扩展。请阅读[贡献指南](CONTRIBUTING.md)和[行为准则](CODE_OF_CONDUCT.md)，并说明实际执行的验证。

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m mypy src/masp
```

## 社区

通过[Issues](https://github.com/LKDenchin/Micro-Multi/issues) 报告可复现的问题或提出功能建议，提供版本、系统、复现步骤和脱敏日志。交流使用方法与想法可前往 [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions)。漏洞采用[安全政策](SECURITY.md)中的私密渠道。

会话和上传内容保存在本地，但配置的模型服务和启用的扩展可能接收执行任务所需的上下文。本地命令在你的机器运行，权限检查不等于操作系统沙箱。

---

## 许可证

[Apache-2.0](LICENSE)。第三方组件保留各自许可证和声明，详见 [NOTICE](NOTICE)及[运行时来源](docs/UPSTREAM_RUNTIME_PROVENANCE.md)。
