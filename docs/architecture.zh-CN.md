# 架构

Electron 主进程启动本地 Python 服务，在沙箱渲染进程中打开工作区。受限 preload 桥暴露桌面操作。FastAPI 服务管理项目、对话、模型配置、权限和 Agent 执行。

Agent 工具连接工作区文件、命令、MCP、Skills 及 dsh 插件。原生 dsh Cordis Host 按插件包与工作区运行独立 Node 进程。桌面发行包提供 Python 和 Electron 的 Node 运行时。

应用状态位于用户可写的数据目录，API 密钥保存在系统凭据库。生产包只包含应用文件、运行依赖和许可证声明。插件服务通过原生 Loader 与元数据按需解析，浏览器贡献通过官方模块系统嵌入应用。参见[原生插件](NATIVE_CORDIS.zh-CN.md)及[当前变化](CURRENT_CHANGES.zh-CN.md)。
