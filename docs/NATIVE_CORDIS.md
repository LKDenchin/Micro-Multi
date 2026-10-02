# deepseek-harness（dsh）插件指南

Micro-Multi 兼容 dsh Cordis Host 插件体系，使用 `@deepseek-ai/cordis@4.0.4`、`@deepseek-ai/dsh-tools@0.2.0-rc.1` 和 `@deepseek-ai/dsh-system-prompt@0.2.0-rc.1`。插件通过 `Context.plugin()` 加载，工具通过 dsh `ToolRuntime.execute()` 校验和执行。插件工具同时供主 Agent 与子 Agent 使用。

## 加载插件

在“设置 → 扩展”选择已构建的本地插件目录，或让 Agent 使用 `plugin_manager` 的 `install` 动作。仓库中的 [`examples/native-cordis`](../examples/native-cordis) 注册计数服务、工具和事件，可直接用于体验。对同一工作区重复调用可以观察状态累积；不同工作区使用独立实例。

插件包包含 `package.json`，声明 `@deepseek-ai/cordis` 或 `cordis` 依赖，并提供本地 `main` / `exports` 入口。先安装插件依赖并构建为 ESM/CJS JavaScript；Node 支持的可擦除 TypeScript 入口也可加载。

多个入口可通过包内配置声明：

```json
{
  "name": "my-dsh-plugin",
  "type": "module",
  "microMulti": {
    "cordis": {
      "plugins": [
        {"entry": "counter.mjs", "config": {"start": 10}},
        {"entry": "tool.mjs"}
      ]
    }
  }
}
```

单个入口使用 `microMulti.cordis.entry` 和 `config`。入口位于包目录内，依赖与构建产物随插件准备好。

## 宿主接口

宿主提供 `tools`、`systemPrompt` 和 `microMulti` 服务。`microMulti.workspace` 是工作区路径，`microMulti.pluginRoot` 是插件源目录。插件可以注册自己的服务，并使用 Cordis 的函数、对象或类插件、配置校验、依赖注入、事件与 effect 清理机制。以这些宿主接口声明插件依赖。

工具参数由 dsh 工具运行时校验，执行结果以结构化内容返回。正常禁用、重装、卸载和后端退出时调用 dispose。状态在包与工作区对应的进程内保留，重新启动后初始化。

## 运行与权限

每个包和工作区使用独立 Node 进程，工具调用在实例内串行执行，不同实例可以并行。启动和调用有硬超时，超时后终止实例；下一次明确调用创建新宿主。插件日志按工作区保存并限制大小。

插件以当前用户的系统权限运行。加载和调用遵循工作台的命令权限与操作审批；安装前检查插件来源与代码。桌面包使用内置 Electron Node，源码模式使用 Node.js 24+，也可通过 `MICRO_MULTI_NODE` 指定运行时。

框架源码与接口说明见 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。
