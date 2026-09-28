# Contract registry v1

唯一来源：`src/masp/domain.py` 中的 Pydantic 模型。
Schema 通过 `Plan.model_json_schema()` 和 HTTP `/openapi.json` 导出。
新增初始版本的作者为 Codex Agent，日期 2026-09-28，依据产品规格 v1.0。
影响 Planner、Coder、Reviewer、任务调度、API、CLI、Web 和全部验收测试。

Plan 必须包括 project、architecture、contracts、tasks、final_checks。
任务必须声明 ID、模块、路径范围、依赖、验收条件和 build/unit 检查。
任务 ID 不重复，DAG 不成环、不存在自依赖或未知依赖，最终 integration 检查不可缺省。
Proposal 只接受声明范围内的文本文件，最多 50 个文件 / 2 MB。

每次注册保存完整 Plan、SHA-256、版本、前后契约差异。
接口变化以最新成功运行的契约为比较基准，任何不同均保守标为潜在破坏性变化。
变更默认阻止运行；调用者检查差异后，可在新 RunCreate 中显式设置
`approve_contract_change=true`，产生 human.contract_override 事件并重跑全部验证。
这不是完整的 OpenAPI 语义兼容性算法。

后续更新记录：谁修改、为什么、影响哪些任务、需要重新运行哪些验证；
破坏性 API 变化应引入新版本，不能只改 Prompt。
