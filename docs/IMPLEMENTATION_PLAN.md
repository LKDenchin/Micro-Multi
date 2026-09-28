# 产品 MVP 执行计划

依据 PRODUCT_DEVELOPMENT_SPEC.md v1.0；本计划替代上一轮仅核心 CLI 的原型计划。

## 范围与验收

实现第 25 节的 14 项 MVP，并按第 45 节依次落地：

1. Repository / Project 模型和持久化。
2. Task 模型、统一状态机。
3. Agent 输入输出、Model Provider 接口。
4. 隔离 Git worktree。
5. 版本化 Contract Registry。
6. DAG 和资源冲突调度。
7. Coder、Planner 模型适配器。
8. 2–4 个隔离任务并行。
9. 分层 Verification、Docker Tool Adapter。
10. 结构化 Reviewer 与不可绕过的 Gate。
11. 有限 Repair Loop。
12. 隔离候选分支集成、最终测试、产物。
13. SQLite 事件与运行历史、Replay 查看。
14. 独立 Web UI，全部操作通过 API。
15. 同一 API 的 CLI 客户端。
16. 固定输入的 benchmark 与完整 E2E 验收。

技术选择：Python / FastAPI / Pydantic / SQLite；浏览器原生 ES modules + CSS。
MVP 使用 SQLite 和单服务进程，降低部署要求。前端无需 Node 构建，仍是独立可用 App。

## 关键契约

`src/masp/domain.py` 的 Pydantic 模型是唯一接口源；API 自动生成 OpenAPI。
Plan 中必须包含模块、契约、DAG、任务作用域和可执行验收检查。
Contract 版本由服务登记，计划发布后不能被 Coder 更改。
Code Proposal 只能含声明路径中的 UTF-8 文本文件；没有自由 Shell 工具。
真实模型生成代码仅在受限 Docker 容器执行；Docker 不可用时拒绝执行，绝不降级到宿主机。
内置示例是明确标识的确定性算术项目，用受限 AST 解释器验证，不执行任意生成代码。

## 本次完成门禁

- Ruff / mypy / 编译检查 / wheel + sdist 构建。
- Schema、DAG、状态机、路径边界、模型错误及配额测试。
- Git 隔离、并行、故障注入、修复、合并、取消、重启恢复测试。
- REST、事件、CLI、产物、页面实际浏览器操作验证。
- 第 46 节：两独立任务，其中一个首次测试失败，修复后合并，最终测试通过并可查看历史。
- Docker 真机和真实外部模型若环境不可用，报告为未验证，不冒充通过。

## 后续范围

V1 的通用工作流编辑器、多租户认证、模型路由、Marketplace、完整人工编辑接管、
成本计费、缓存精确重放不属于本次 MVP。暂停/恢复/取消与历史查看优先提供。

开源许可证选择 Apache-2.0；默认不发布仓库、不推送代码、不调用外部模型。
