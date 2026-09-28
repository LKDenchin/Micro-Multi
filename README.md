# MASP · Multi-Agent Software Engineering Platform

独立运行的多 Agent 工程工作台。输入需求，查看规划、契约、隔离开发、审查、验证、修复和交付的完整过程。

依据 [产品开发规格书](PRODUCT_DEVELOPMENT_SPEC.md) 第 25 节构建的 **MVP**。
界面为中文，提供 REST API、SSE 实时事件及共享同一 API 的 CLI。

## 快速启动

需要 Python 3.11+、Git。Windows PowerShell：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]'
.venv/Scripts/masp serve
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/masp serve
```

打开 **http://127.0.0.1:8765**，点击「体验完整验收流程」。
内置示例会创建真实 Git 仓库，启动两个独立任务，故意产生一次减法测试失败，
修复后通过最终检查，合并到托管项目分支并提供 ZIP 下载。

**示例模式是固定算术 benchmark，不是通用需求代码生成。** 它不调用模型、不消耗 tokens，
不执行任意生成代码：语法编译和有限 AST 解释器提供可复现验证。

## 开发真实需求

先准备 Docker 与受信任的 Python 工具链镜像，并配置兼容模型服务：

```powershell
$env:MASP_MODEL_BASE_URL = 'http://127.0.0.1:8000/v1'
$env:MASP_MODEL_NAME = 'your-model-name'
# 只有服务需要凭证时才设置 MASP_MODEL_API_KEY；不要写入项目或日志。
docker pull python:3.12-slim
.venv/Scripts/masp serve
```

在创建项目时选择「真实模型」。模型通过结构化 JSON 输出计划、文件提案和审查问题。
需要遵循 JSON 指令的模型；不支持的输出会留下失败证据。
真实代码的所有验证仅在限制网络、CPU、内存、进程数与写权限的 Docker 容器中执行。
缺少 Docker 不会降级到宿主机。项目依赖须预装到 `MASP_SANDBOX_IMAGE` 指定镜像。

## CLI

先启动服务，再在另一个终端执行：

```bash
masp init calculator
masp projects
masp run PROJECT_ID "构建加法与减法模块并验证" --inject-failure
masp inspect RUN_ID
masp tasks PROJECT_ID
masp agents PROJECT_ID
masp logs RUN_ID
masp replay RUN_ID
masp verify RUN_ID
masp pause RUN_ID
masp resume RUN_ID
masp cancel RUN_ID
masp retry RUN_ID
```

`masp init NAME --repository ABSOLUTE_PATH` 导入本地 Git 仓库的已提交历史。
源仓库、未提交内容及源分支保持不变。MVP 暂不提供远程 URL 导入。
`verify` 查看已有执行证据；`retry` 从托管仓库当前版本新建运行，不伪称精确重放。

## 验证开发环境

```bash
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src/masp
python -m pytest -q
python -m compileall -q src
python -m build
python scripts/benchmark.py --workers 1 2 4 --output evidence/benchmark.json
```

完整规格符合性、已验证证据与限制见 [验收报告](docs/ACCEPTANCE.md)。
主要架构和扩展接口见 [架构说明](docs/architecture.md)。

## 当前边界

- 单用户本地服务，绑定 loopback；不是面向公网的多租户 SaaS。
- SQLite 持久化；最大 2 个并行 Run，每个 Run 最多 4 个 Coder。
- 暂停在安全边界生效，进行中的模型请求最长等待其超时；取消不会发布未验证产物。
- 服务重启将未完成运行标记为需要人工处理，不推测成功，不自动恢复半执行进程。
- 合并冲突保留工作区与日志，需人工处理；不自动强制覆盖或推送。
- 自定义工作流编辑、通用人工审批节点、模型市场、精确重放与计费属于后续 V1。
- 真实模型和 Docker 运行是否在当前环境验证，以验收报告为准。

Apache-2.0。欢迎通过测试、模型适配器、工具适配器和缺陷报告参与贡献。
