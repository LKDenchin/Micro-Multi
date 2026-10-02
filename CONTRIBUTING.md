# Contributing / 贡献指南

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Read the README, [architecture](docs/architecture.md), and relevant runtime documentation. Check existing issues before large changes and use a focused branch.

## Setup and validation

Use Python 3.11+, Node.js 24+, npm, and Git. Follow README setup; use `npm ci` for locked dependencies. Windows installer builds need Python 3.14.7; Linux builds bootstrap and verify the pinned standalone runtime automatically. Build dependencies on the target platform.

Activate your virtual environment and run:

```text
python -m pytest -q
python -m ruff check src tests
python -m mypy src/masp
```

Runtime changes need relevant behavior and failure-path coverage. Desktop changes also need the packaged smoke test in `docs/DESKTOP_RELEASE.md`. Report live model checks only if performed.

## Pull requests

- Describe the concrete problem, resulting behavior, and validation commands/results.
- Update both README languages for user-facing changes.
- Preserve dependency licenses and adapted-source provenance.
- Never commit credentials, uploads, private workspaces, personal screenshots, or logs.
- Run `python scripts/publication_audit.py` before committing.

Bug reports need version, OS, reproduction steps, expected/actual results, and sanitized evidence. Report vulnerabilities through [SECURITY.md](SECURITY.md).

## 中文

请先阅读 README、架构说明和相关文档，较大修改先说明需求，使用独立分支。提交说明包含问题、修复后的行为和实际验证结果；运行时修改增加必要测试，桌面修改运行安装版冒烟检查。用户文档同步维护中英文。

不要提交密钥、上传内容、私人项目、个人会话截图或日志。依赖及上游代码变更保留许可证与来源记录。提交前执行 `python scripts/publication_audit.py`；漏洞采用私密渠道。
