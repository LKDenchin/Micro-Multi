# 架构与技术栈

Micro-Multi 由 Electron 桌面外壳、本地 Python 服务，以及 Node.js 智能体/插件运行时组成。主工作区使用 HTML、CSS 和 JavaScript 编写；原生插件组件使用 React，可在主界面中增加控件。

## 任务怎样执行

Electron 启动 Python 服务，并在沙箱渲染进程中打开工作区。preload 桥提供选取目录等有限的桌面操作。Web 界面向 FastAPI 发送请求，后端管理项目、对话、模型和任务执行。

对话使用选定的模型配置。执行层处理模型回复，再调用文件、命令、MCP 或插件工具。团队模式增加 supervisor，保存方案、成员分工和执行状态。界面通过 SSE 接收对话事件，通过 WebSocket 接收长期插件订阅。

原生 dsh 包按插件包与工作区运行独立 Node 进程，官方 Cordis 运行时管理服务注册及插件生命周期。客户端模块系统和渲染器将插件界面贡献挂载到应用内。

## 技术栈

| 部分 | 技术及职责 |
| --- | --- |
| 桌面 | Electron、上下文隔离和沙箱渲染；electron-builder 生成 NSIS、Debian 和 AppImage。 |
| 后端 | Python 3.11+、FastAPI 和 Uvicorn；Pydantic 与 JSON Schema 校验结构化数据。 |
| 主界面 | HTML、CSS 和 JavaScript 模块，支持 Markdown、代码高亮和数学公式。 |
| 插件界面 | React 与 dsh 客户端渲染器；esbuild 构建插件客户端入口。 |
| 智能体与插件执行 | Node.js 24+、Cordis 和 deepseek-harness；MCP 接入额外工具。 |
| 持久化 | SQLite 应用记录、本地附件文件，以及 keyring 访问的系统凭据库。 |
| 通信 | 本地 HTTP 接口、SSE 任务事件、WebSocket 订阅和子进程消息。 |
| 文档 | Python 和 markdown-it-py 生成 GitHub Pages 使用的双语静态页面。 |

桌面包内置 Python 和 Node。Git、Docker 及外部扩展程序单独安装。npm 的具体依赖位于 `package-lock.json`，桌面 Python 依赖位于 `requirements-desktop.lock`。

## 源码目录

| 路径 | 内容 |
| --- | --- |
| `desktop/` | Electron 入口、preload 和平台集成。 |
| `src/masp/api.py` | 界面使用的 HTTP 与流式路由。 |
| `src/masp/web/` | 主工作区页面、样式和 JavaScript。 |
| `src/masp/supervisor.py` | 团队协调与成员执行。 |
| `src/masp/native/` | Node 宿主及原生插件/客户端集成。 |
| `src/masp/storage.py` | 应用记录存储。 |
| `scripts/` | 构建、验证和网站生成。 |
| `tests/` | 运行时与界面回归测试。 |

## 存储与进程边界

数据目录与安装程序分离。SQLite 保存应用记录，附件等工作数据使用本地文件，模型密钥保存在系统凭据库。路径和配置见[部署](deployment.zh-CN.md)。

渲染进程使用沙箱，但本地命令和原生插件仍以用户系统权限运行。独立进程处理插件故障，不构成任意插件代码的沙箱。[权限说明](sandbox.zh-CN.md)介绍用户操作控制，[运行时接口](contracts.zh-CN.md)介绍集成契约。
