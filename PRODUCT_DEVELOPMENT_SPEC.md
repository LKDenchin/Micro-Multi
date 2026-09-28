# Multi-Agent Software Engineering Platform

> 独立多 Agent 软件工程工具 App 开发规格书
>
> 工作名称：`Multi-Agent Software Engineering Platform`（最终项目名称待定）
>
> 文档版本：v1.0
>
> 状态：Development Specification

---

## 1. 项目定义

### 1.1 产品目标

本项目最终交付物不是一个简单的 Agent Demo，也不是某个大模型的代码生成包装器，而是一个可以独立运行、独立部署、可扩展、可观察、可复现的 **Multi-Agent Software Engineering Platform**。

用户输入一个软件需求后，系统应能够完成：

```text
Requirement
    ↓
Planning
    ↓
Contract / Schema
    ↓
Dependency Analysis
    ↓
Task Scheduling
    ↓
Parallel Agent Development
    ↓
Review
    ↓
Build / Test / Static Analysis / Security
    ↓
Automatic Repair
    ↓
Integration
    ↓
Final Verification
    ↓
Project Artifact
```

产品核心理念：

> **让多个 Agent 在统一的软件工程契约下并行工作，并通过可执行验证、自动修复、版本隔离和完整追踪，将生成式代码转化为可验证、可追踪、可复现的软件工程产物。**

---

## 2. 产品定位

### 2.1 不做什么

本项目第一阶段不定位为：

- 单纯聊天式 Coding Agent；
- 单纯 IDE 插件；
- 单纯代码生成 API；
- 单纯 Prompt 管理器；
- 只展示多个 Agent 对话的 Demo；
- 只依赖 LLM 自我 Review 的自动编程系统。

### 2.2 要做什么

产品应定位为：

> **AI-native Software Engineering Workspace**

面向以下使用场景：

1. 从自然语言需求创建完整项目；
2. 对已有代码库进行多模块并行开发；
3. 自动分配任务给不同 Agent；
4. 通过 Contract 控制模块之间的接口一致性；
5. 自动运行代码质量和测试工具；
6. 发现问题后将任务退回 Agent 修复；
7. 自动进行 Git 分支、Worktree、Commit、Merge 管理；
8. 提供完整运行记录、差异、日志和 Replay；
9. 允许用户随时介入、暂停、批准、拒绝和修改流程。

---

# 3. 核心设计原则

## 3.1 Contract-First

所有可并行开发的任务必须建立在统一 Contract 之上。

Contract 至少包含：

```text
Project Contract
├── API Contract
├── Data Schema
├── Interface Contract
├── Dependency Contract
├── Coding Constraints
└── Acceptance Criteria
```

Agent 不允许私自修改共享接口而不更新 Contract。

Contract 是模块协作的 Single Source of Truth。

---

## 3.2 Evidence-Driven Verification

LLM 的判断不能作为最终代码正确性的唯一依据。

系统必须优先使用真实执行证据：

```text
Build Result
Test Result
Lint Result
Type Check
Security Scan
Contract Validation
Integration Test
```

LLM Reviewer 的结论只能作为一种判断信号，不能替代程序执行结果。

---

## 3.3 Isolated Parallel Development

每个可并行任务必须具有独立的：

- Agent Session；
- Context；
- Workspace；
- Git Branch / Worktree；
- Tool Execution Context；
- Task State。

不同 Agent 默认不能直接修改其他 Agent 的工作目录。

---

## 3.4 Dependency-Aware Scheduling

任务并行不是简单 `N 个 Agent 同时启动`。

Scheduler 必须根据任务依赖关系构建 DAG：

```text
Task A ─────┐
            ├── Task D
Task B ─────┤
            │
Task C ─────┘
```

无依赖任务并行，有依赖任务等待前置任务完成。

---

## 3.5 Verify → Repair → Verify

任何失败不能直接终止整个流程，除非达到重试上限或触发安全策略。

标准闭环：

```text
Implement
   ↓
Verify
   ↓
Failure
   ↓
Diagnose
   ↓
Repair
   ↓
Verify Again
```

---

## 3.6 Model-Agnostic

平台不得与单一模型提供商强绑定。

支持抽象：

```text
OpenAI-compatible API
Anthropic-compatible API
Gemini-compatible API
Qwen / DeepSeek / other APIs
Ollama
vLLM
Local Models
Fine-tuned LoRA Models
```

模型应该通过 Adapter 接入，而不是散落在业务代码中。

---

## 3.7 Tool-Agnostic

外部工具必须通过统一 Tool Adapter 接口接入：

```text
pytest
ruff
mypy
clang
cmake
npm
cargo
Docker
Semgrep
Git
```

新增工具不应该修改核心 Orchestrator。

---

# 4. 产品总体架构

```text
┌────────────────────────────────────────────────────────────┐
│                         Client Layer                        │
│                                                            │
│   Web App     CLI     API Client     Future Desktop App    │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                     Application Layer                       │
│                                                            │
│ Project Manager   Workflow Manager   Run Manager           │
│ Agent Manager     Model Manager      Tool Manager           │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                   Orchestration Core                       │
│                                                            │
│ Planner → Scheduler → Dispatcher → Aggregator → Gatekeeper │
└──────────────┬──────────────┬──────────────┬───────────────┘
               │              │              │
      ┌────────▼───────┐ ┌────▼────────┐ ┌───▼─────────────┐
      │ Agent Runtime  │ │Contract Eng.│ │ Workspace Engine │
      │                │ │             │ │                 │
      │ Planner        │ │ API Schema  │ │ Git             │
      │ Coder          │ │ Interfaces  │ │ Worktree        │
      │ Reviewer       │ │ Dependencies│ │ Snapshot        │
      │ Tester         │ │ Constraints │ │ Sandbox         │
      │ Repair         │ │ Versioning  │ │                 │
      │ Integrator     │ │             │ │                 │
      └───────┬────────┘ └─────┬───────┘ └──────┬──────────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Verification Engine │
                    │                     │
                    │ Build / Test / Lint │
                    │ Type / Security     │
                    │ Contract / E2E      │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Trace / Event Store │
                    │                     │
                    │ Logs / Events / Run │
                    │ Artifact / Replay   │
                    └─────────────────────┘
```

---

# 5. 核心模块

## 5.1 Project Manager

负责项目生命周期。

### 功能

- 创建项目；
- 导入已有 Git 仓库；
- 配置项目语言和框架；
- 配置默认模型；
- 配置 Toolchain；
- 保存 Project Configuration；
- 管理项目运行历史。

### 项目状态

```text
CREATED
READY
RUNNING
PAUSED
FAILED
SUCCEEDED
CANCELLED
```

---

## 5.2 Planner Agent

输入自然语言需求，输出结构化开发计划。

输出必须包含：

```yaml
project:
  name: example
  description: ...

architecture:
  modules: []

contracts: []

tasks:
  - id: task-001
    title: ...
    description: ...
    dependencies: []
    module: backend
    acceptance_criteria: []

parallel_groups:
  - [task-001, task-002]
```

Planner 不直接编写业务代码。

---

## 5.3 Contract Engine

这是平台的核心差异化模块之一。

### Contract 类型

```text
API Contract
Schema Contract
Interface Contract
Dependency Contract
Behavior Contract
Acceptance Contract
```

### 关键职责

- 创建 Contract；
- 版本控制；
- 验证 Agent 输出；
- 检查接口变更；
- 检测 Breaking Change；
- 提供 Contract Diff；
- 为 Reviewer 提供验证依据。

### Contract 必须可机器读取

优先采用：

- YAML；
- JSON；
- OpenAPI；
- JSON Schema；
- 或项目语言对应的 IDL。

自然语言文档可以存在，但不能成为唯一事实源。

---

## 5.4 Scheduler

Scheduler 负责将 Planner 输出转换为可执行 DAG。

### 要求

- 解析任务依赖；
- 计算拓扑排序；
- 找出可并行任务；
- 控制最大并发 Agent 数量；
- 管理资源配额；
- 失败任务重试；
- 防止重复执行；
- 支持优先级；
- 支持人工暂停。

### 调度状态

```text
PENDING
QUEUED
RUNNING
BLOCKED
SUCCEEDED
FAILED
RETRYING
CANCELLED
```

---

## 5.5 Agent Runtime

提供统一 Agent 生命周期。

### Agent 生命周期

```text
CREATE
 ↓
LOAD CONTEXT
 ↓
LOAD CONTRACT
 ↓
LOAD TASK
 ↓
EXECUTE
 ↓
PRODUCE ARTIFACT
 ↓
SELF CHECK
 ↓
SUBMIT
 ↓
TERMINATE
```

### 基础 Agent 类型

#### Planner Agent

需求 → 计划、模块、Contract、Task。

#### Coder Agent

Task → Code + Tests + Documentation。

#### Reviewer Agent

Code → Review Findings。

#### Tester Agent

Code → Test Result / Diagnosis。

#### Repair Agent

Failure → Patch → Verification。

#### Security Agent

Code → Security Findings。

#### Integration Agent

多个已通过模块 → Integration Result。

#### Merge Agent

在所有 Gate 条件满足后执行合并。

---

# 6. Agent 标准协议

每个 Agent 必须具有统一输入输出结构。

## 6.1 Agent Input

```json
{
  "run_id": "run-001",
  "task_id": "task-001",
  "project_id": "project-001",
  "role": "coder",
  "repository": {
    "commit": "abc123",
    "branch": "task/task-001"
  },
  "contract_version": "v3",
  "task": {},
  "constraints": {},
  "context": {}
}
```

## 6.2 Agent Output

```json
{
  "status": "submitted",
  "artifacts": [],
  "changed_files": [],
  "commit": "def456",
  "tests": {
    "passed": true
  },
  "findings": [],
  "metrics": {
    "input_tokens": 0,
    "output_tokens": 0,
    "latency_ms": 0
  }
}
```

Agent 不应该返回只有自然语言的最终结果。

---

# 7. Workspace Engine

每个执行任务必须拥有隔离工作区。

推荐使用：

```text
Git Repository
      ↓
Git Worktree / Branch
      ↓
Container / Sandbox
      ↓
Agent
```

### Workspace 必须支持

- create；
- checkout；
- snapshot；
- diff；
- commit；
- reset；
- rollback；
- destroy。

禁止多个 Agent 默认同时直接写同一个工作目录。

---

# 8. Verification Engine

Verification Engine 是产品的第二个核心能力。

## 8.1 Verification Pipeline

```text
Contract Check
      ↓
Syntax Check
      ↓
Build
      ↓
Lint
      ↓
Type Check
      ↓
Unit Test
      ↓
Integration Test
      ↓
Security Scan
      ↓
Acceptance Test
```

不是所有项目都必须启用全部步骤，但每个项目必须声明自己的 Verification Policy。

---

## 8.2 Verification Result

```json
{
  "status": "failed",
  "checks": [
    {
      "name": "unit_test",
      "status": "failed",
      "passed": 42,
      "failed": 2,
      "duration_ms": 8340,
      "logs": "..."
    }
  ]
}
```

所有结果必须进入 Trace Store。

---

# 9. Review Engine

Reviewer 不只是检查代码风格，而是分层审查。

## 9.1 Review Levels

### L1 Static Review

- 格式；
- 命名；
- 类型；
- 复杂度；
- 明显错误。

### L2 Logic Review

- 业务逻辑；
- 边界条件；
- 异常处理；
- 状态一致性。

### L3 Contract Review

- API；
- Schema；
- Interface；
- Dependency。

### L4 Security Review

- 注入；
- 权限；
- Secret；
- 不安全依赖；
- 文件/命令执行风险。

### L5 Test Review

检查代码是否具有合理测试覆盖率与关键场景覆盖。

---

# 10. Review Decision

Review 不允许直接依赖一个模糊的 `PASS/FAIL` 字符串。

必须输出结构化 Findings：

```json
{
  "severity": "high",
  "category": "contract",
  "file": "src/api/user.py",
  "line": 81,
  "message": "Response schema differs from registered contract",
  "evidence": "...",
  "suggested_fix": "...",
  "blocking": true
}
```

Severity：

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

只有 Blocking Findings 为 0 且 Verification Gate 通过时，任务才能进入 Merge 阶段。

---

# 11. Repair Engine

失败之后不能简单重新生成整个模块。

Repair Agent 应读取：

```text
Original Task
Code Diff
Review Findings
Build Logs
Test Logs
Contract Diff
Previous Attempts
```

然后生成最小必要 Patch。

### Repair 策略

```text
Failure
 ↓
Classify
 ↓
Locate Root Cause
 ↓
Minimal Patch
 ↓
Targeted Test
 ↓
Full Verification
```

系统必须限制最大 Repair 次数，例如默认 3 次。

超过最大次数后进入：

```text
HUMAN_REVIEW_REQUIRED
```

---

# 12. Merge Engine

Merge 必须是受控操作。

### Merge Gate

```text
Task Completed
AND
Contract Passed
AND
Review Passed
AND
Build Passed
AND
Tests Passed
AND
Security Policy Passed
```

全部满足后才允许 Merge。

### Merge 失败

```text
Merge Conflict
    ↓
Conflict Analyzer
    ↓
Repair / Rebase
    ↓
Verification
    ↓
Retry Merge
```

禁止无条件强制覆盖其他 Agent 代码。

---

# 13. Workflow Engine

系统必须支持自定义工作流，而不是把流程写死。

默认 Workflow：

```yaml
workflow:
  - planner
  - contract
  - schedule
  - parallel_development:
      max_agents: 4
  - review
  - verify
  - repair:
      max_attempts: 3
  - integrate
  - final_verify
  - merge
```

未来支持：

```text
Sequential
Parallel
DAG
Conditional
Loop
Retry
Human Approval
Voting
Debate
Handoff
```

---

# 14. Model Layer

建立统一 Model Provider Interface。

```python
class ModelProvider:
    def generate(self, request): ...
    def stream(self, request): ...
    def count_tokens(self, request): ...
```

模型配置不得直接散落在 Agent 逻辑中。

配置示例：

```yaml
models:
  planner:
    provider: openai-compatible
    model: example-model

  coder:
    provider: local
    model: example-coder

  reviewer:
    provider: openai-compatible
    model: example-reviewer
```

---

# 15. Tool Layer

Tool Adapter 统一封装外部工具。

```python
class ToolAdapter:
    name: str

    def validate(self, project): ...
    def execute(self, context): ...
    def parse_result(self, raw): ...
```

工具执行必须：

- 记录命令；
- 记录参数；
- 限制权限；
- 限制资源；
- 捕获 stdout/stderr；
- 保存退出码；
- 支持 timeout；
- 保存结构化结果。

---

# 16. Sandbox 与安全

因为 Agent 可以生成代码并执行 Shell 命令，Sandbox 是正式产品能力，而不是可选项。

默认禁止 Agent：

- 访问宿主机敏感目录；
- 读取未授权 Secret；
- 修改系统关键配置；
- 无限制执行网络请求；
- 使用宿主机高权限账户；
- 删除工作区之外的文件。

推荐架构：

```text
Host
 │
 ├── Orchestrator
 │
 └── Sandbox
      ├── Agent
      ├── Project Workspace
      ├── Toolchain
      └── Temporary Network Policy
```

所有 Sandbox 操作必须可追踪。

---

# 17. Trace / Event System

所有重要操作采用 Event 形式记录。

事件至少包含：

```text
run.created
plan.generated
contract.created
contract.changed
task.queued
task.started
task.completed
agent.started
agent.message
agent.tool_call
tool.completed
review.created
verification.started
verification.completed
repair.started
repair.completed
merge.started
merge.completed
run.completed
```

### Event Schema

```json
{
  "event_id": "evt-001",
  "timestamp": "...",
  "run_id": "run-001",
  "task_id": "task-001",
  "agent_id": "agent-001",
  "type": "verification.completed",
  "payload": {}
}
```

---

# 18. Replay

每一次 Run 必须能够复盘。

用户应该能够查看：

```text
Run
 ├── Requirement
 ├── Plan
 ├── Contract Version
 ├── Task Graph
 ├── Agent Sessions
 ├── Tool Calls
 ├── Git Diff
 ├── Review Findings
 ├── Verification Logs
 ├── Repair Attempts
 ├── Merge Result
 └── Final Artifact
```

Replay 至少支持“查看”，后续版本支持“重新执行”。

---

# 19. Web App

最终产品必须具有独立 Web UI，不能只有 CLI。

## 19.1 页面

### Dashboard

显示：

- 项目；
- 当前 Run；
- Agent 状态；
- 任务完成度；
- Verification；
- 成本；
- 最近失败。

### Project Page

```text
Overview
Tasks
Contracts
Agents
Runs
Git
Artifacts
Settings
```

### Run Page

核心页面。

显示：

```text
Workflow Graph
Task Status
Agent Status
Live Events
Logs
Code Diff
Review
Tests
```

### Contract Page

显示：

- API Schema；
- Version；
- Diff；
- Breaking Changes；
- Validation。

### Agent Page

显示：

- Agent Role；
- Model；
- Status；
- Current Task；
- Context Usage；
- Tool Calls；
- Token Usage；
- Latency。

---

# 20. CLI

必须提供 CLI，以便自动化和 CI 使用。

推荐命令：

```bash
masp init
masp run
masp task list
masp task inspect <id>
masp agent list
masp contract check
masp verify
masp run replay <id>
masp run cancel <id>
masp project status
masp logs
```

CLI 与 Web UI 必须共享同一套后台 API，而不是维护两套业务逻辑。

---

# 21. Backend API

推荐采用 REST API + WebSocket/SSE。

基础资源：

```text
/projects
/projects/{id}
/projects/{id}/runs
/projects/{id}/tasks
/projects/{id}/contracts
/projects/{id}/agents
/projects/{id}/artifacts
/runs/{id}/events
/runs/{id}/logs
/runs/{id}/cancel
/runs/{id}/replay
```

实时状态使用：

```text
SSE / WebSocket
```

---

# 22. 数据模型

核心实体：

```text
Project
Run
Workflow
Task
Agent
AgentSession
Contract
Artifact
Workspace
VerificationRun
ReviewFinding
RepairAttempt
Event
Model
Tool
```

实体之间关系：

```text
Project
  └── Run
       ├── Workflow
       ├── Task
       │    ├── AgentSession
       │    ├── Workspace
       │    ├── ReviewFinding
       │    ├── VerificationRun
       │    └── RepairAttempt
       ├── Contract
       ├── Event
       └── Artifact
```

---

# 23. 推荐代码仓库结构

```text
project-root/
│
├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│   ├── core/
│   ├── agents/
│   ├── orchestration/
│   ├── contracts/
│   ├── scheduler/
│   ├── workspace/
│   ├── verification/
│   ├── tools/
│   ├── models/
│   ├── tracing/
│   └── storage/
│
├── plugins/
│   ├── models/
│   └── tools/
│
├── examples/
│
├── benchmarks/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── benchmark/
│
├── docs/
│
├── scripts/
│
├── docker/
│
├── AGENTS.md
├── README.md
├── LICENSE
└── pyproject.toml / package.json
```

最终技术选型可以根据实现团队调整，但模块边界和依赖方向应保持稳定。

---

# 24. 推荐技术路线

## Backend

优先考虑：

```text
Python
FastAPI
Pydantic
SQLAlchemy
PostgreSQL
Redis
```

Agent 编排层可接入：

```text
AgentScope
```

也可保留自己的 Orchestration Interface，避免锁定框架。

## Frontend

推荐：

```text
React
TypeScript
Next.js / Vite
Tailwind CSS
React Flow
```

## Runtime

```text
Docker
Git
Git Worktree
```

## Observability

```text
Structured Logging
OpenTelemetry-compatible tracing（可选）
Event Store
```

## Model Serving

```text
OpenAI-compatible API
vLLM
Ollama
```

实际实现时，应通过 Adapter 隔离具体框架和供应商。

---

# 25. MVP 范围

第一版不要试图实现所有能力。

## MVP 必须完成

```text
[1] Project 创建
[2] Git 仓库导入
[3] Planner Agent
[4] Contract Registry
[5] Task DAG
[6] 2~4 个 Coder Agent 并行
[7] 独立 Git Worktree
[8] Reviewer Agent
[9] Build/Test Runner
[10] Repair Loop
[11] Integration / Merge
[12] Web Run Dashboard
[13] CLI
[14] Run Trace
```

### MVP 成功标准

用户可以：

```text
输入需求
   ↓
系统自动拆解
   ↓
生成 Contract
   ↓
并行开发多个模块
   ↓
运行 Review
   ↓
自动测试
   ↓
失败自动修复
   ↓
最终合并
   ↓
在 UI 查看完整过程
```

---

# 26. V1 范围

MVP 稳定之后增加：

```text
Custom Workflow
Model Router
Tool Marketplace / Registry
Agent Registry
Human Approval
Security Sandbox
Replay
Artifact Versioning
Cost Tracking
Prompt / Agent Versioning
```

---

# 27. V2 / Advanced

后续研究型功能：

```text
Multi-Reviewer Voting
Agent Debate
Adaptive Scheduling
Dependency-aware Parallelism
Dynamic Agent Allocation
Agent Performance Model
Failure Propagation Analysis
Automatic Task Re-planning
LoRA Agent Specialization
Benchmark Automation
```

---

# 28. 人机协作

系统必须允许用户在关键节点接管。

可人工操作：

```text
Approve
Reject
Pause
Resume
Cancel
Edit Contract
Edit Task
Edit Code
Retry
Force Review
```

但所有强制操作必须产生 Event。

例如：

```text
human.contract_override
human.merge_approval
human.task_replan
```

---

# 29. 失败处理策略

所有异常归入标准类型：

```text
MODEL_ERROR
TOOL_ERROR
BUILD_ERROR
TEST_ERROR
CONTRACT_ERROR
CONTEXT_ERROR
RESOURCE_ERROR
GIT_CONFLICT
SECURITY_BLOCK
TIMEOUT
UNKNOWN_ERROR
```

不同错误采用不同恢复策略。

例如：

```text
TEST_ERROR
→ Repair Agent

GIT_CONFLICT
→ Conflict Resolution

CONTRACT_ERROR
→ Planner / Contract Review

MODEL_ERROR
→ Retry / Model Fallback

SECURITY_BLOCK
→ Human Approval
```

---

# 30. 资源控制

平台必须防止多 Agent 导致资源失控。

每个 Run 支持：

```text
max_agents
max_tokens
max_cost
max_runtime
max_retries
max_workspace_size
```

Scheduler 必须支持资源配额。

---

# 31. 成本与性能指标

每个 Run 至少统计：

```text
Total Duration
Agent Duration
LLM Latency
Input Tokens
Output Tokens
Estimated Cost
Tool Runtime
Build Runtime
Test Runtime
Retry Count
Repair Count
```

UI 显示：

```text
Cost
Latency
Parallelism
Success Rate
Retry Rate
```

---

# 32. 产品核心指标

### Engineering Success Rate

```text
最终通过 Acceptance Test 的任务数
──────────────────────────────
总任务数
```

### Verification Pass Rate

记录每层验证通过率。

### Defect Detection Rate

```text
Reviewer 发现的真实缺陷
────────────────────────
实际缺陷总数
```

### Repair Success Rate

```text
修复后通过验证的缺陷
────────────────────
进入 Repair 的缺陷
```

### Parallel Efficiency

比较并行和串行执行的完成时间。

### Contract Conflict Rate

```text
Contract / Interface 冲突次数
────────────────────────────
总模块交互次数
```

### Cost per Successful Task

统计完成一个成功软件任务的模型和计算成本。

---

# 33. Benchmark

项目必须建立自己的 Benchmark Harness。

第一阶段可使用自建多模块项目集，后续接入公开软件工程 Benchmark。

Benchmark 每个任务应固定：

```text
Repository Version
Requirement
Initial Tests
Expected Behavior
Allowed Tools
Timeout
```

实验结果必须可复现。

---

# 34. 实验设计

项目科研部分重点围绕四个问题：

## Q1：多 Agent 并行是否提高效率？

```text
1 Agent
vs
2 Agents
vs
4 Agents
vs
8 Agents
```

测量：

- Completion Time；
- Success Rate；
- Token Cost；
- Conflict Rate。

## Q2：Contract 是否减少模块冲突？

```text
No Contract
vs
Contract
```

## Q3：Review 是否降低缺陷？

```text
No Review
vs
Single Review
vs
Multi Review
```

## Q4：Execution Verification 是否优于 LLM-only Review？

```text
LLM Review
vs
LLM + Execution
vs
LLM + Contract + Execution
```

---

# 35. 可扩展插件系统

第三方开发者必须可以扩展：

```text
Model Plugin
Agent Plugin
Tool Plugin
Workflow Plugin
Verification Plugin
Storage Plugin
UI Plugin
```

推荐统一 Manifest：

```yaml
name: example-reviewer
version: 0.1.0
type: agent
entrypoint: example_reviewer:Reviewer
capabilities:
  - code_review
  - security_review
```

平台核心不得因为一个插件而耦合具体实现。

---

# 36. 配置设计

所有项目级策略应配置化。

示例：

```yaml
project:
  language: python
  repository: ./repo

agents:
  max_concurrency: 4

workflow:
  max_repair_attempts: 3

verification:
  required:
    - contract
    - build
    - unit_test
    - security

limits:
  max_runtime: 3600
  max_tokens: 1000000
```

---

# 37. API 与内部边界原则

模块之间必须通过明确接口通信。

禁止：

- Agent 直接访问数据库内部表；
- UI 直接操作 Workspace；
- Reviewer 直接绕过 Verification Engine；
- Model Provider 直接修改 Task 状态；
- Plugin 直接修改 Orchestrator 内部状态。

推荐：

```text
UI
 ↓
API
 ↓
Application Service
 ↓
Domain Service
 ↓
Adapter
```

---

# 38. 状态机

Run 状态：

```text
CREATED
  ↓
PLANNING
  ↓
CONTRACTING
  ↓
SCHEDULING
  ↓
RUNNING
  ↓
VERIFYING
  ↓
REPAIRING
  ↓
INTEGRATING
  ↓
FINAL_VERIFY
  ↓
SUCCEEDED
```

异常状态：

```text
PAUSED
FAILED
CANCELLED
HUMAN_REVIEW_REQUIRED
```

状态迁移必须经过统一 State Manager。

---

# 39. 测试策略

## Unit Test

覆盖：

- Contract Engine；
- Scheduler；
- State Machine；
- Parser；
- Verification Result；
- Git Operations。

## Integration Test

覆盖：

```text
Planner → Contract
Contract → Scheduler
Scheduler → Agent
Agent → Workspace
Workspace → Verification
Verification → Repair
Repair → Merge
```

## E2E Test

测试完整项目从需求到最终 Artifact。

---

# 40. Definition of Done

一个功能只有同时满足以下条件才能认为完成：

```text
[ ] 有代码
[ ] 有类型检查
[ ] 有单元测试
[ ] 有集成测试（适用时）
[ ] 有错误处理
[ ] 有结构化日志
[ ] 有文档
[ ] 有配置说明
[ ] 不破坏现有 API
[ ] CI 通过
```

Agent 相关功能额外要求：

```text
[ ] 输入输出结构化
[ ] Tool Calls 可追踪
[ ] Token / Latency 可统计
[ ] 支持失败重试
[ ] 支持取消
[ ] 支持日志和 Replay
```

---

# 41. Git 工作流

推荐：

```text
main
 ├── feat/<name>
 ├── fix/<name>
 ├── refactor/<name>
 └── agent/<task-id>
```

Agent 工作必须绑定 Task。

Commit 建议：

```text
feat(core): add task scheduler
feat(agent): add reviewer runtime
fix(contract): validate breaking changes
fix(workspace): isolate agent worktree
```

每个 Agent 完成任务后必须留下可解释的 Commit。

---

# 42. 开源策略

项目必须从第一天开始考虑外部贡献者。

仓库应包含：

```text
README.md
LICENSE
CONTRIBUTING.md
CODE_OF_CONDUCT.md
SECURITY.md
CHANGELOG.md
```

提供：

```text
Quick Start
Docker Quick Start
Local Development
Plugin Development
Agent Development
Tool Development
Architecture Documentation
Benchmark Guide
```

---

# 43. 文档体系

```text
docs/
├── getting-started.md
├── architecture.md
├── concepts.md
├── agents.md
├── contracts.md
├── workflows.md
├── verification.md
├── sandbox.md
├── plugins.md
├── models.md
├── tools.md
├── tracing.md
├── replay.md
└── benchmark.md
```

---

# 44. 最终产品形态

最终用户看到的不是一堆 Agent，而是一个完整的软件工程工作台：

```text
┌──────────────────────────────────────────────────┐
│ Multi-Agent Software Engineering Platform       │
├──────────────────────────────────────────────────┤
│ Projects                                         │
│                                                  │
│  my-project                                      │
│  ├── Run #21   ● Running                         │
│  ├── Tasks      8 / 12                           │
│  ├── Agents     4 Active                         │
│  ├── Contract   v7                               │
│  ├── Tests      183 / 183                        │
│  └── Review     Passed                           │
│                                                  │
│  [ Workflow ] [ Tasks ] [ Contracts ] [ Git ]    │
│  [ Agents ]   [ Logs ]  [ Verify ]    [ Replay ] │
└──────────────────────────────────────────────────┘
```

核心体验应该是：

> **用户描述目标，系统负责组织软件工程过程；用户可以随时观察、干预和接管。**

---

# 45. 第一阶段开发顺序

必须严格按以下顺序降低系统复杂度：

```text
Step 1  Repository / Project Model
   ↓
Step 2  Task Model + State Machine
   ↓
Step 3  Agent Runtime
   ↓
Step 4  Git Workspace
   ↓
Step 5  Contract Engine
   ↓
Step 6  Scheduler / DAG
   ↓
Step 7  Coder Agent
   ↓
Step 8  Parallel Execution
   ↓
Step 9  Verification Engine
   ↓
Step 10 Reviewer
   ↓
Step 11 Repair Loop
   ↓
Step 12 Integration / Merge
   ↓
Step 13 Event Store / Trace
   ↓
Step 14 Web UI
   ↓
Step 15 CLI
   ↓
Step 16 Benchmark
```

不建议在核心流程尚未跑通之前加入复杂的 LoRA、多模型投票或花哨 UI。

---

# 46. 第一条端到端验收路径

开发团队必须尽快实现下面这个最小闭环：

```text
User Requirement
      ↓
Planner
      ↓
2 Independent Tasks
      ↓
2 Coder Agents
      ↓
2 Git Worktrees
      ↓
Contract Validation
      ↓
Review
      ↓
Build + Unit Test
      ↓
One Intentional Failure
      ↓
Repair Agent
      ↓
Re-test
      ↓
Merge
      ↓
Final Test
      ↓
Run History
```

只要该闭环能够稳定执行，项目就从“架构设计”进入“真正的软件产品开发”。

---

# 47. 产品成功标准

第一版不以“Agent 越多越好”为成功指标。

成功标准应该是：

### Engineering

- 多模块任务可以可靠并行；
- Contract 冲突可检测；
- Agent Workspace 相互隔离；
- Review 和自动化 Verification 能形成闭环；
- 失败任务可以自动 Repair；
- Merge 有明确 Gate；
- 整个过程可以 Trace。

### Product

- 用户无需理解 Agent 内部实现即可完成任务；
- Web UI 可以观察整个工程过程；
- CLI 可以自动化执行；
- Model / Tool / Agent 可以替换；
- 项目可以本地部署；
- 文档可以让第三方开发者快速上手。

### Research

- 能进行 Baseline 对比；
- 能进行 Ablation Study；
- 能测量并行效率、冲突率、缺陷率、修复率和成本；
- 能复现实验。

---

# 48. 核心价值总结

本项目的核心不在于：

```text
“让一个 Agent 写更多代码”
```

而在于：

```text
“让多个 Agent 像一个受工程规则约束的软件团队一样工作。”
```

因此产品核心能力应固定为：

```text
                    ┌──────────────┐
                    │   Planning   │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │   Contract   │
                    └──────┬───────┘
                           ↓
                 ┌─────────┴─────────┐
                 ↓                   ↓
          Parallel Agents        Scheduler
                 │                   │
                 └─────────┬─────────┘
                           ↓
                     Verification
                           ↓
                        Review
                           ↓
                       Repair
                           ↓
                       Integrate
                           ↓
                         Merge
                           ↓
                    Trace / Replay
```

这套闭环就是本项目的产品核心。

---

# 49. 非目标约束

在核心闭环稳定之前，不应优先投入：

- 自研基础大模型；
- 大规模 LoRA 训练平台；
- 复杂社交功能；
- 非必要的在线模型市场；
- 过度复杂的可视化动画；
- 与 IDE 厂商绑定的专有能力。

优先保证：

```text
Correctness > Observability > Extensibility > Performance > UI Polish
```

---

# 50. 最终定义

**本项目最终应当成为一个独立的、开源的 Multi-Agent Software Engineering App。**

用户可以：

```text
输入需求
→ 创建项目
→ 自动规划
→ 自动建立 Contract
→ 自动拆解任务
→ 并行启动多个 Agent
→ 自动 Review
→ 自动 Build/Test/Scan
→ 自动 Repair
→ 自动 Integration
→ 自动 Merge
→ 查看全过程
→ Replay / Debug / Human Takeover
```

并且整个系统具备：

```text
Model Agnostic
Agent Agnostic
Tool Agnostic
Workflow Agnostic
Git Native
Contract First
Evidence Driven
Sandboxed
Observable
Reproducible
Open Source
```

> **最终目标不是“一个能调用很多 Agent 的工具”，而是“一个让 Agent 真正参与软件工程生产流程的平台”。**
