# 模型、Agent 与工具扩展

## ModelProvider

`generate(role, payload, schema, max_tokens) -> Generation`。
输入为结构化上下文与 JSON Schema，输出 data、model、input_tokens、output_tokens、latency_ms。
核心 Runtime 负责 Pydantic 校验；Provider 不得改数据库、状态或工作区。

内置 `FixtureProvider` 用于固定测试，`CompatibleProvider` 调用兼容 `/chat/completions`。
Ollama、vLLM 或其他提供商可使用兼容端点，或自行实现此 Protocol。
目前没有自动插件发现，应用服务构造是组合入口。

## Agent Runtime

Planner 输入需求和仓库路径清单、README、pyproject；输出明确契约和任务。
Coder/Repair 输入 `AgentInput`，包括身份、提交、契约、任务、失败证据及作用域内代码。
只接受 Proposal.files 文本变更；不支持自由工具调用和二进制文件。
Reviewer 返回包含 blocking 字段的 Findings。
任何模型格式错误、命令失败或阻塞 Finding 都不能生成成功提交。

## ToolAdapter

`execute(root, check, stop) -> CheckResult`。
必须响应取消、设置超时、记录实际退出码、区分失败原因。
验证检查来自已注册计划，Coder 无权替换。
可通过 `Check.command` 调用镜像中安装的 pytest、ruff、mypy 等；每个任务必须至少包含 build/unit。

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| MASP_HOME | .masp | SQLite、项目、worktree、产物目录 |
| MASP_MODEL_BASE_URL | 无 | HTTPS 或 loopback HTTP 的兼容 API 地址 |
| MASP_MODEL_NAME | 无 | 模型标识 |
| MASP_MODEL_API_KEY | 无 | 仅服务端凭证 |
| MASP_SANDBOX_IMAGE | python:3.12-slim | 管理员准备的离线验证镜像 |

Run 请求提供 max_agents、max_retries、max_runtime、max_tokens。
费用没有价格配置时显示未知，不将 token 数量伪装成真实账单。
预算准入按输入长度的保守估计与最大输出预留，并记录提供商实际用量。
