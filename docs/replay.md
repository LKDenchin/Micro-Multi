# 运行记录与复盘

Web 的运行详情提供需求、任务依赖、Agent 会话、事件、代码差异、审查、验证和产物。
CLI 使用 `masp replay RUN_ID`，与 Web 读取同一 API；`masp logs RUN_ID` 读取事件。
事件分页参数 `after` 是最后看到的 sequence；每批最多 500 条。
SSE `/api/runs/{id}/stream` 支持 Last-Event-ID 和历史补发。

`retry` 从当前托管仓库新建 Run，重新规划与执行，会产生新 ID、模型输出及日志。
它不是缓存级精确重放，也不覆盖原 Run。

失败运行保留每次检查的命令、退出码、日志，工作区路径和已有提交。
不要将 `HUMAN_REVIEW_REQUIRED` 或未完成状态当作成功。
服务器重新启动时，未完成 Run 进入人工处理状态。
