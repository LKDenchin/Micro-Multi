# 架构与接口

```text
Web (ES modules) / CLI (HTTP client)
                ↓
FastAPI + SSE /api
                ↓
Service → State Manager → SQLite records/events
   ↓
Runtime → ModelProvider → Plan / Proposal / Review
   ↓
Contract Registry → DAG Scheduler → Git worktree per task
   ↓
Contract review → Reviewer → ToolAdapter → bounded repair
   ↓
Candidate merge → final verification → managed project merge → ZIP
```

## 模块边界

| 模块 | 输入 | 输出 | 扩展与故障 |
| --- | --- | --- | --- |
| `domain.py` | JSON 请求和模型输出 | Pydantic v1 契约对象 | 拒绝未知字段、循环、非法路径、缺失门禁 |
| `storage.py` | 应用服务记录和事件 | 持久化实体、序列事件 | SQLite WAL；错误向上传递 |
| `agents.py` | 需求或标准 AgentInput | Plan / Proposal / Review、用量 | ModelProvider；不访问数据库或修改文件 |
| `workspace.py` | 提交、任务作用域、文件提案 | 隔离工作区、diff、commit | 禁用 Git hooks；合并冲突保留证据 |
| `contracts.py` | Plan、现有版本 | 注册摘要、接口差异、可执行任务 | 保守变更检测；新接口须重新验收 |
| `verification.py` | 已声明的 Check + 只读代码快照 | CheckResult | ToolAdapter；超时、取消、资源耗尽可区分 |
| `service.py` | ProjectCreate / RunCreate | 可追踪执行和产物 | 单一状态入口；并发、重试和发布门禁 |
| `api.py` | REST / SSE | 项目、任务、Agent、日志、产物 | Web 与 CLI 共享；禁止跨域写入 |

## 技术决策

遵循规格允许的技术调整：采用 Python/FastAPI/Pydantic，SQLite 替代 PostgreSQL/Redis；
前端使用浏览器原生模块，无 Node 构建依赖。核心与 UI 通过 REST/SSE 分离，
以后可替换为 React 客户端，不需要复制业务逻辑。

MVP 保留清晰的模块边界，使用单 Python 包避免过早引入几十个空目录。
`src/masp/domain.py` 是唯一契约来源，`/openapi.json` 自动导出 HTTP 接口。

## 状态与取消

运行经过规划、契约、调度、运行、集成、最终验证到成功。
任务经过排队、执行、审查、验证、有限修复、集成。
状态机拒绝跳过验证直接成功和重新开启终态。
暂停是持久化控制意图 `control=paused`，API 另提供 `display_state=PAUSED`；
底层阶段保留，以免恢复时丢失执行位置。取消阻止后续工作和最终发布。
模型调用不能在任意字节位置中止，HTTP 超时上限 45 秒。

## Git 与发布

每个 Run 有候选集成 worktree；任务在独立分支和 worktree 中运行。
仅通过任务审查和全部检查的提交进入候选分支。
最终集成检查通过、托管仓库未被外部修改后，才快进合并并导出 ZIP。
导入项目使用独立 clone；不会修改原仓库。
失败 worktree 保留用于诊断，不自动删除用户数据或推送远程。

## 事件一致性

事件包含 event_id、sequence、timestamp、run_id、task_id、agent_id、type、payload。
模型身份、输入输出 tokens、延迟，命令、退出码、stdout/stderr，修复证据与 Git 提交都被记录。
状态与事件是分开提交的 SQLite 操作；进程崩溃可能留下最后一条状态没有对应事件。
重启一律标记未完成 Run 需要人工处理，MVP 不声称事务级分布式 Exactly-once。
