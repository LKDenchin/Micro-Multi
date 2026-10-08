<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="88" />
  <h1>Micro-Multi</h1>
  <p>把任务分给多个 Agent，在同一个项目里协作。兼容 DeepSeek Harness 插件。</p>
  <p><a href="README.md">English</a> · 简体中文</p>
  <p><a href="https://lkdenchin.github.io/Micro-Multi/zh/">官网</a> · <a href="#安装">安装</a> · <a href="#完成第一个任务">开始使用</a> · <a href="https://lkdenchin.github.io/Micro-Multi/docs/readme-zh-cn.html">文档</a></p>
</div>

Micro-Multi 是一个以**多 Agent 协作**为核心的本地桌面工作区。你提出需求，主 Agent 拆分任务；你确认分工后，成员按负责文件和任务依赖执行，主 Agent 汇总结果。方案、成员进度、工具输出和代码差异放在同一个工作区里。

例如给订单接口加分页：一个成员修改接口，一个成员编写测试，文档成员更新参数说明。互不依赖的任务可以同时做；需要等接口完成的测试按依赖启动。同一文件的并发写入由调度器协调。

另一个重点是 **DeepSeek Harness（dsh）插件兼容性**。应用使用原生 Cordis Host 和 dsh 客户端模块系统，加载插件声明的服务、工具、设置表单和界面贡献。启用的工具也能交给团队成员使用。已有的 Skills 和 MCP 服务可以继续接入。

Windows / Linux · 中英文界面 · 自选模型服务 · Apache-2.0

## 为什么需要协作调度

单 Agent 适合短任务。实现、测试和审查都交给同一个执行循环时，通常需要依次处理，职责和中间结果也混在同一段上下文中。仅在提示词里写“分工”还不够：谁能修改哪些文件、谁必须等待谁、任务是否已启动，需要程序处理。

| 单 Agent 或没有协调器的分工 | Micro-Multi 的处理方式 |
| --- | --- |
| 实现、测试、文档依次执行 | 独立任务并行，依赖任务等待前置报告；可设置并发上限。 |
| 多个成员都修改同一个文件 | 声明文件归属，用路径锁和任务依赖协调写入。 |
| 所有职责使用同一模型 | 成员默认继承主模型，你可以在方案里单独修改。 |
| 重试时容易重复派发 | 同一任务复用正在运行或已完成的执行，批准过的版本只启动一次。 |
| 插件只接到了主 Agent | 已启用的 dsh、MCP 和命令工具可供主 Agent 与成员调用。 |

这些是执行方式的区别，不是性能排名。并行能缩短独立任务的等待时间，但更多成员也可能增加模型调用和费用。小改动可以只用主 Agent；有明确分工的大任务再启用团队。

## 安装

在 [GitHub Releases](https://github.com/LKDenchin/Micro-Multi/releases/latest) 下载对应系统的软件包。

| 系统 | 软件包 |
| --- | --- |
| Windows x64 | [NSIS 安装程序](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-Setup-0.1.0-x64.exe) |
| Debian / Ubuntu x64 | [Debian 包](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-amd64.deb) |
| Linux x64 | [AppImage](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/Micro-Multi-0.1.0-x86_64.AppImage) |
| 校验和 | [SHA256SUMS.txt](https://github.com/LKDenchin/Micro-Multi/releases/download/v0.1.0/SHA256SUMS.txt) |

Windows 运行安装程序，然后从开始菜单打开 Micro-Multi。Debian 或 Ubuntu 使用 `sudo apt install ./<package>.deb` 安装下载的包。AppImage 先执行 `chmod +x <file>.AppImage`，再运行该文件；没有 FUSE 时可加上 `--appimage-extract-and-run`。

安装包内置 Python 和 Node.js。仓库操作需要另外安装 Git，Docker 和插件所需的外部 CLI 也按需安装。[桌面指南](docs/DESKTOP_RELEASE.zh-CN.md)介绍 Linux 凭据库、Ubuntu AppImage 配置、校验和及自行构建的方法。

## 完成第一个任务

1. 打开**设置 → 模型 → 添加或编辑模型**，填写名称、API 地址、模型 ID 和密钥，然后点击“检测连接”。
2. 添加本地项目目录。保留“**直接关联此目录**”勾选项，即可在原目录中工作；没有 Git 的目录会自动初始化仓库。
3. 在该项目中新建对话，选择模型、**多 Agent 协作**模式和允许的操作权限。
4. 说明要修改什么，以及怎样检查。例如：

   ```text
   为订单列表接口添加分页，保留现有响应字段。
   将接口实现、边界测试、参数文档拆给不同成员，列出负责文件和依赖。
   主 Agent 汇总改动，运行相关测试并说明结果。
   ```

5. 审核聊天里的协作方案，必要时调整成员、模型和负责文件，然后点击“确认执行”。
6. 查看成员进度，打开改动文件和测试输出；需要调整时在原对话中补充要求。

你可以向对话添加附件，也可以打开右侧工作区查看文件、审查、预览和终端活动。[项目与对话](docs/WORKSPACE.zh-CN.md)介绍主要操作，[模型配置](docs/MODELS.zh-CN.md)说明接口连接方式。

## 使用团队协作

主 Agent 准备方案，列出成员职责、任务、负责文件、依赖和模型。通过“**调整团队**”修改安排，再点击“**确认执行**”启动这版方案。批准前不会执行成员任务。新任务或新一轮反馈需要重新确认。

确认使用服务端保存的方案版本。若方案确实更新了，聊天卡片直接显示新版分工，审核后可以在原处再次确认，无需切到协作导图。

成员默认跟随主模型，也可以单独选择其他模型。团队视图显示状态和报告，工具记录展示实际执行的操作。运行中可以补充说明、暂停对话或停止执行。验收时应查看改动和测试输出；具体流程见[团队协作](docs/AUTONOMOUS_COLLABORATION.zh-CN.md)。

## 添加指令和工具

在“**自定义**”中管理扩展。

| 扩展 | 用途 |
| --- | --- |
| Skills | 在 `SKILL.md` 中保存可复用的工作指令。项目技能放在 `.agents/skills/`。 |
| MCP 服务 | 接入本地或远程服务提供的工具。 |
| dsh 插件 | 原生 Cordis 服务与工具、模型提供者、设置表单和对话界面组件。 |
| 命令插件 | 调用本地命令实现的工具。 |

安装后打开插件详情配置参数。有些插件需要先填写账号、API 密钥或安装外部程序，才能使用其工具。输入区的 **+** 菜单列出已启用能力。选择扩展类型可参考[扩展指南](docs/extensions.zh-CN.md)，安装或开发 dsh 插件可参考[dsh 指南](docs/NATIVE_CORDIS.zh-CN.md)。

兼容范围以包声明的入口、依赖和所需服务为准，不代表每个第三方包都已验证。聊天启动先恢复工作区，插件客户端随后加载；不提供前端的插件不会因页面探测而启动 Host。原生服务仍按 dsh 的依赖与生命周期加载。

## 权限和数据

输入区提供三种权限：“**请求批准**”在修改文件和运行命令前询问；“**帮我批准**”允许修改文件，运行命令仍需确认；“**完全访问**”允许文件操作、命令和已启用的外部工具。[权限说明](docs/sandbox.zh-CN.md)介绍这些设置的作用。

项目记录、对话和附件保存在本地。请求模型时会发送任务需要的上下文，启用的扩展也可能向其服务发送数据。模型配置中的 API 密钥使用系统凭据库保存。本地命令和原生插件以你的系统用户权限运行。

安装版数据位于 Windows 的 `%APPDATA%\Micro-Multi\data`，或 Linux 的 `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data`。源码模式默认使用工作目录下的 `.masp`，可通过 `MASP_HOME` 指定其他位置。升级和卸载保留数据，备份时应将数据目录与应用程序分开处理。

## 从源码运行

准备 Python 3.11+、Node.js 24+、npm 和 Git，在仓库根目录执行：

```bash
python -m venv .venv
```

Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1` 激活虚拟环境，Linux 使用 `source .venv/bin/activate`。随后执行：

```bash
python -m pip install -e ".[dev]"
npm ci
npm run desktop
```

如果使用浏览器，运行 `python -m masp.cli serve`，然后访问 `http://127.0.0.1:3080/`。配置和数据目录见[部署指南](docs/deployment.zh-CN.md)。

## 技术栈

| 部分 | 实现 |
| --- | --- |
| 桌面应用 | Electron，使用沙箱渲染进程及桌面操作 preload 桥。 |
| 后端 | Python、FastAPI、Uvicorn 和 Pydantic，负责本地接口与智能体执行。 |
| 界面 | HTML、CSS 和 JavaScript；原生插件组件由 React 渲染。 |
| 智能体与插件运行时 | Node.js、Cordis 和 deepseek-harness 软件包。 |
| 存储 | SQLite 保存应用记录，本地文件保存附件，系统凭据库保存模型密钥。 |
| 通信 | HTTP 接口、对话事件 SSE 流，以及插件订阅 WebSocket。 |
| 构建与文档 | electron-builder、esbuild，以及由 Markdown 生成的静态网站。 |

[架构说明](docs/architecture.zh-CN.md)介绍各部分如何通信，以及对应的源码目录。

## 文档与参与贡献

开始使用时，可以依次阅读[模型配置](docs/MODELS.zh-CN.md)、[项目与对话](docs/WORKSPACE.zh-CN.md)、[团队协作](docs/AUTONOMOUS_COLLABORATION.zh-CN.md)和[扩展](docs/extensions.zh-CN.md)。遇到问题时，参见[常见问题](docs/TROUBLESHOOTING.zh-CN.md)。

可复现的问题提交到 [Issues](https://github.com/LKDenchin/Micro-Multi/issues)，附上操作步骤和脱敏日志；使用讨论和建议可放在 [Discussions](https://github.com/LKDenchin/Micro-Multi/discussions)。贡献代码前请阅读[贡献指南](CONTRIBUTING.zh-CN.md)，安全漏洞通过[安全政策](SECURITY.zh-CN.md)中的私密渠道报告。

Micro-Multi 使用 [Apache-2.0](LICENSE) 许可证。第三方组件保留各自许可证，参见 [NOTICE](NOTICE) 和[运行时溯源](docs/UPSTREAM_RUNTIME_PROVENANCE.zh-CN.md)。
