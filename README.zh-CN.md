<div align="center">
  <img src="src/masp/web/micro-multi.svg" alt="Micro-Multi" width="88" />
  <h1>Micro-Multi</h1>
  <p>在本地项目中与 AI 智能体一起工作。</p>
  <p><a href="README.md">English</a> · 简体中文</p>
  <p><a href="https://lkdenchin.github.io/Micro-Multi/zh/">官网</a> · <a href="#安装">安装</a> · <a href="#完成第一个任务">开始使用</a> · <a href="https://lkdenchin.github.io/Micro-Multi/docs/readme-zh-cn.html">文档</a></p>
</div>

Micro-Multi 是一个用于本地项目的 AI 桌面应用。连接模型服务、打开项目后，你可以让智能体阅读代码、修改文件、运行命令，或调用已经启用的工具。对话、文件浏览、代码差异和工具输出都能在应用内查看。

小范围改动可以只交给主智能体。需要多人分工时，选择多智能体协作：主智能体先提出方案，你检查成员和任务安排，确认后再启动团队。执行过程中可以查看每个成员的进展，完成后对照项目文件检查结果。

应用支持 Windows 和 Linux，提供中文、英文界面。模型接口和凭据由你配置；Skills、MCP 服务以及 deepseek-harness（dsh）生态插件可以补充指令和工具。

## 可以用来做什么

| 任务 | 使用方式 |
| --- | --- |
| 了解代码库 | 让智能体追踪程序入口、解释模块，或找出某项功能涉及的文件。 |
| 修改代码并验证 | 直接在项目目录中工作，查看改动差异以及命令、测试的输出。 |
| 拆分较大的任务 | 让不同成员负责实现、测试或审查，并为他们选择模型。 |
| 接入外部工具 | 配置 MCP 服务、安装 dsh 插件，或用 Skill 保存常用的工作要求。 |
| 继续之前的工作 | 重新打开对话，查看消息、工具记录和成员报告，再接着处理。 |

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
3. 在该项目中新建对话，选择模型、**仅主智能体**模式和允许的操作权限。
4. 说明要修改什么，以及怎样检查。例如：

   ```text
   找到订单列表接口，添加分页，并保留现有响应字段。
   运行相关测试，说明是否通过；如果失败，解释原因。
   ```

5. 阅读回复，打开改动的文件并查看差异。命令输出保存在工具记录中；需要调整时，直接在对话里补充要求。

你可以向对话添加附件，也可以打开右侧工作区查看文件、审查、预览和终端活动。[项目与对话](docs/WORKSPACE.zh-CN.md)介绍主要操作，[模型配置](docs/MODELS.zh-CN.md)说明接口连接方式。

## 使用团队协作

任务涉及不同职责时，在输入区选择多智能体协作。主智能体会准备方案，列出成员职责、任务、负责文件和模型。通过“**调整团队**”修改安排，再点击“**确认执行**”启动这版方案。新任务或新一轮反馈需要重新确认。

成员默认跟随主模型，也可以单独选择其他模型。团队视图显示状态和报告，工具记录展示实际执行的操作。运行中可以补充说明、暂停对话或停止执行。验收时应查看改动和测试输出；具体流程见[团队协作](docs/AUTONOMOUS_COLLABORATION.zh-CN.md)。

## 添加指令和工具

在“**自定义**”中管理扩展。

| 扩展 | 用途 |
| --- | --- |
| Skills | 在 `SKILL.md` 中保存可复用的工作指令。项目技能放在 `.agents/skills/`。 |
| MCP 服务 | 接入本地或远程服务提供的工具。 |
| dsh 插件 | 使用 deepseek-harness 生态中的工具、模型提供者和界面组件。 |
| 命令插件 | 调用本地命令实现的工具。 |

安装后打开插件详情配置参数。有些插件需要先填写账号、API 密钥或安装外部程序，才能使用其工具。输入区的 **+** 菜单列出已启用能力。选择扩展类型可参考[扩展指南](docs/extensions.zh-CN.md)，安装或开发 dsh 插件可参考[dsh 指南](docs/NATIVE_CORDIS.zh-CN.md)。

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
