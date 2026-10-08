# 原生 dsh 插件

Micro-Multi 支持 deepseek-harness（dsh）生态的软件包。插件可以向智能体提供工具、注册模型提供者，或在应用中增加控件。客户端贡献显示在 Micro-Multi 内，不需要另外启动 dsh WebUI。

团队使用同一套已启用工具：主 Agent 可以分配任务，成员按自己的模型与权限调用插件能力。Cordis 服务注入、依赖解析、设置表单和客户端生命周期由原生运行时处理。兼容范围取决于包声明的入口、依赖和所需服务，并非所有第三方包均已验证。

聊天启动先恢复工作区，随后并发加载插件客户端。无前端插件跳过聊天页面探测时的 Host 初始化；详情页仍发现它的模型和设置功能。客户端构建按源码版本缓存，同一版本避免重复构建，不同版本可同时构建。

## 安装与配置

打开“自定义”，选择“插件”，阅读介绍后选择可用来源并安装。来源可以是市场条目、npm 包、Git 仓库或本地包目录。本地包需包含 `package.json` 和受支持的运行时入口，智能体的 `plugin_manager` 工具也可管理安装。

已发布的 JavaScript 入口直接加载。源码需要构建时，应用会展示包含包内依赖和构建命令的方案，确认后执行。包声明的依赖在加载过程中准备；外部 CLI 和服务仍按插件说明配置。

安装后打开详情，使用插件自己的设置界面，或由配置 schema 生成的表单填写参数。保存后查看校验消息。提供模型的插件需要配置供应商，并使用相应模型入口；插件不一定需要提供工具。

## 使用与管理

启用的工具供主智能体和团队成员使用。界面组件显示在插件声明的区域，配置保留在详情页。对话中的工具记录展示智能体实际调用了什么。

禁用可移除活动功能，卸载则从已安装列表移除包。插件可能以你的系统账号读写文件、执行程序或访问服务，应在安装前检查来源，并妥善保管凭据。

## 开发本地插件

可从 [examples/native-cordis](../examples/native-cordis) 开始。包可使用标准运行时导出，也可在 `microMulti.cordis` 中声明本地入口及配置。多个入口可共同声明：

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

入口保持在包目录内，并声明所需依赖。宿主提供 `tools`、`systemPrompt` 和 `microMulti`，其中 `microMulti.workspace`、`microMulti.pluginRoot` 标识工作区和源码位置。服务注入、事件及资源释放使用原生 Cordis API，工具参数与结果遵循官方 dsh 工具运行时。

客户端包通过 dsh 元数据声明入口和依赖，使用官方客户端模块系统及共享渲染器。源码宿主需要 Node.js 24+，桌面包内置该运行时，可用 `MICRO_MULTI_NODE` 指定其他运行时。

实现参考见[架构](architecture.zh-CN.md)、[运行时接口](contracts.zh-CN.md)和[上游溯源](UPSTREAM_RUNTIME_PROVENANCE.zh-CN.md)。上游框架为 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。
