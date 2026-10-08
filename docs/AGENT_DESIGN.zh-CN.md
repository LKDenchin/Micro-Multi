# Agent 设计与取舍

Micro-Multi 把多 Agent 协作放在执行层：主 Agent 负责理解任务和分工，调度器负责批准版本、依赖、文件预留和重复执行。插件继续由 DeepSeek Harness 的原生运行时管理。

## 从 pi 借鉴什么

参考 [pi](https://github.com/earendil-works/pi) 的 Agent 核心、系统提示词和技能加载设计（阅读日期：2026-10-08）。pi 将模型请求、工具执行与事件分开；上下文可以在请求边界处理，技能先公布名称和描述，需要时再读取内容。它的核心默认不内置团队规划，扩展承担额外流程。

这给我们的启发是：保留小的模型执行循环，把协作规则落实为程序。多 Agent 是 Micro-Multi 的主要功能，不能为了简化循环删掉依赖调度、方案审核或插件服务。

| 设计 | 在 Micro-Multi 中的应用 |
| --- | --- |
| 请求、工具、界面分别处理 | 工作区先恢复，插件清单与客户端随后加载，避免插件页面阻塞聊天启动。 |
| 明确的运行状态 | 批准前等待规划轮保存完成；使用服务端版本核对方案。过期或已消费的批准返回冲突，不重新进入规划。 |
| 减少重复流程 | 确认调用合并；批准轮明确告知主 Agent 成员已经启动，避免再次提交同一方案。 |
| 按需读取详细内容 | 后续可改进插件工具发现与成员上下文裁剪；此次没有改变模型可用工具集，也没有替换 dsh 的依赖机制。 |

源码参考：[Agent loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)、[system prompt](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/system-prompt.ts)、[Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)。

## 把协作约束写进程序

[Open Code Review](https://github.com/alibaba/open-code-review) 把明确规则交给程序，把需要判断和检索的步骤交给 Agent。我们借鉴这种职责划分：模型可以建议成员、文件和依赖，但任务校验、路径协调和批准消费由程序处理。

`start_subagents` 校验完整任务列表和依赖图。独立任务在并发上限内运行；依赖任务等待前置报告，前置失败则停止后续写入。`owned_paths` 声明文件归属，路径锁和预留协调共享工作区。同一派发可以复用正在运行或已完成的执行。主 Agent 收取报告后完成集成和验收。

这些措施减少重复派发和误启动，不能保证团队一定比单 Agent 便宜。成员数量、输入上下文、模型价格、失败重试和任务依赖都会影响费用与耗时。此次没有统一任务集上的成本基准，因此不公布节省比例。

## 保持 dsh 兼容

保留 Cordis Loader、服务注入、插件生命周期、原生设置表单、ClientModuleSystem、RPC 和订阅接口。页面探测不启动没有客户端的插件；插件客户端最多三个并发加载；同一客户端版本的构建共用锁，不同版本可以同时构建。运行时源码摘要按文件元数据复用，源码变化时重新计算。

这些优化改变启动与缓存方式，没有删除插件所需服务，也没有按插件名称裁剪依赖。实际兼容范围仍取决于包的入口、依赖和所需服务。

仓库已依赖 `@deepseek-ai/dsh-llm-pi-ai`。当前锁定版本将 pi-ai 接在 dsh 的 LLM 接口上，其包说明是 DeepSeek 适配器；仅安装这个包不等于完整 pi Agent 运行时已接入，也不等于支持 pi 的全部模型服务。此次不切换执行引擎。

## 后续值得做的测量

固定同一模型和任务，分别记录单 Agent、两成员和三成员的输入/输出 token、首个响应时间、总完成时间、重试次数和验收结果。插件测试则区分冷启动、已有构建缓存和无前端插件，记录聊天可用时间与全部客户端加载时间。测量后再决定是否加入按需工具发现和更短的成员上下文。

参见[协作流程](AUTONOMOUS_COLLABORATION.zh-CN.md)、[插件兼容](NATIVE_CORDIS.zh-CN.md)和[架构](architecture.zh-CN.md)。
