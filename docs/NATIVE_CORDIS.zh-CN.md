# 原生 dsh 插件

Micro-Multi 通过官方 Cordis Loader 和 ClientModuleSystem 运行 deepseek-harness 发布插件。宿主 SDK 使用 Cordis 4.0.4 与锁定的 dsh 0.2.0-rc.1。插件工具同时供主 Agent 和团队成员使用。客户端贡献嵌入本程序界面，不另行启动 dsh WebUI。

## 安装与构建

打开“自定义”，选择市场插件、npm 包、Git 来源或本地目录，检查来源和权限。Agent 也可通过 `plugin_manager` 安装扩展。来源需包含 `package.json` 和受支持的宿主或客户端入口。示例见 [examples/native-cordis](../examples/native-cordis)。

已发布的 JavaScript 产物直接加载，运行时激活错误本身不会触发重新构建。确实需要构建时，审核方案先安装包内开发及可选依赖，再运行构建命令；即使外层 npm 环境忽略开发依赖，Vite 等工具也能获得。依赖安装不执行生命周期脚本；源码构建仍使用应用已有的审批流程。

通用解析器读取 npm dependencies、peer/dev 声明和 `dsh.client.inject` 元数据。缺少的已声明库安装到应用自己的依赖缓存。即使 exports 未公开 `package.json`，仍可读取包元数据。框架包使用宿主版本或不高于宿主的兼容发布版本；普通插件依赖保留其包声明。

## 入口与服务注入

单入口可使用 `microMulti.cordis.entry` 和 `config`，多个入口可声明：

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

入口位于包目录内。ESM/CJS 导出、配置校验和原生 Loader 条目 ID 保留。Bundle 的条目选项、隔离、拦截、禁用状态和表达式遵循原生生命周期。

宿主根据官方 dsh 基础组合与提供者元数据递归解析所需服务，包括 `timer`、`sessionQuery`、`workspaceRegistry` 及配置选择的存储后端。提供者按需激活，不提前执行整个插件目录。缺少真实提供者或启动失败时给出明确诊断，并回滚失败激活。

应用提供 `tools`、`systemPrompt` 和 `microMulti`；`microMulti.workspace`、`microMulti.pluginRoot` 暴露对应路径。工具使用官方 dsh 参数校验及结构化输出。服务、事件和 effect 使用原生 Cordis API 注册；禁用、重装、卸载和正常退出释放资源。

## 设置与客户端页面

插件自有设置贡献显示在详情页。没有自定义页面但声明 Config schema 的插件可生成可编辑表单。表单通过原生设置 Remote 保存，支持基础字段、复杂值 JSON 和秘密字段处理。校验与完整生命周期重启成功后才原子持久化；更新失败恢复旧配置。

旧命名空间设置使用原始发布版 SettingsProvider，与当前 Config 表单共存，支持 `get`、`register`、监听、更新、mutate 和版本冲突处理。此前保存的命名空间值在读取时迁移。来源见[运行时溯源](UPSTREAM_RUNTIME_PROVENANCE.zh-CN.md)。

客户端工厂、同步和异步 require、分块注册及缓存使用 ClientModuleSystem。依赖和子槽位通过 JavaScript 语法分析发现；原生父组件拥有其声明的子槽位。设置槽位和 body portal 限制在插件详情中；对话与明确的 shell 贡献挂载到应用对应区域。原生语言及渲染服务提供真实客户端接口。

浏览器构建禁用 Node 内部探测，不依赖浏览器中的 `process` 全局。客户端 JS/CSS 与宿主复用纳入运行时源码及锁文件版本，升级后旧缓存自动失效。长期订阅使用 WebSocket，避免占满浏览器 HTTP 连接池。原生 HTTP 路由保留流、二进制请求体及响应头。

## 运行、权限与诊断

插件包与工作区使用独立 Node 进程，启动、调用和日志有边界。终止后在后续明确调用时重新创建宿主。数据与依赖缓存属于 Micro-Multi，不影响外部 dsh 安装。源码运行需要 Node.js 24+，桌面包内置 Node；可用 `MICRO_MULTI_NODE` 指定运行时。

插件以当前用户系统权限运行。独立进程和经完整性校验的框架源码快照保护宿主稳定性，不构成任意插件代码的系统沙箱。外部 CLI、账号登录、供应商凭据及网络服务仍需各自配置。成功安装不代表所有远端业务已验证。

参见[扩展](extensions.zh-CN.md)、[当前变化](CURRENT_CHANGES.zh-CN.md)和[安全政策](../SECURITY.zh-CN.md)。框架参考：[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。
