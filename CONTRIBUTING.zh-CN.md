# 贡献指南

遵守[社区规范](CODE_OF_CONDUCT.zh-CN.md)，阅读 README、[架构](docs/architecture.zh-CN.md)及相关运行时文档。较大修改先检查已有 Issue，使用聚焦的分支。

## 环境与验证

使用 Python 3.11+、Node.js 24+、npm 和 Git。按 README 配置，`npm ci` 安装锁定依赖。Windows 安装包构建需要 Python 3.14.7，Linux 自动准备并验证固定独立运行时。依赖应在目标系统安装。

激活虚拟环境后执行：

```text
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src/masp
npm run test:plugin-client
npm run test:chat-startup
node tests/client_dependencies.test.mjs
python scripts/build_site.py
```

运行时改动需要相关行为及失败路径覆盖；桌面改动另需[安装版冒烟检查](docs/DESKTOP_RELEASE.zh-CN.md)。只报告实际执行过的模型检查。

## 提交与问题报告

- 说明具体问题、修复后行为及验证命令和结果。
- 用户变化同步维护成对中英文文档；网站每篇指南有对应语言页面。
- 保留依赖许可证和改编源码溯源。
- 不提交凭据、上传内容、私人工作区、个人截图或日志。
- 提交前执行 `python scripts/publication_audit.py`，仅检查发布候选文件，不删除本地用户数据。

Bug 报告包含版本、系统、复现步骤、预期/实际结果和脱敏证据。漏洞通过[安全政策](SECURITY.zh-CN.md)中的私密渠道报告。
