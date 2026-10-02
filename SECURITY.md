# Security policy / 安全政策

Micro-Multi is a single-user loopback application. Keep its API on the local machine. Security fixes are provided for the latest published version.

## Trust boundaries

- Model services receive conversation context and selected tool results.
- Profile keys use the OS credential store. Extension configuration and logs may contain sensitive values; redact before sharing.
- Local commands run on the host. Permission checks do not provide an OS sandbox.
- Optional Docker verification refuses host fallback; it does not isolate all chat tools or extensions.
- Skills, MCP servers, native packages, and plugins are trusted inputs. Review their source and requested access.
- Uninstall preserves data. See the README for erasure instructions.

## Reporting

Use [Security → Report a vulnerability](https://github.com/LKDenchin/Micro-Multi/security/advisories/new) to send a private vulnerability report. Never post credentials, exploit details or unredacted logs in public issues.

Include affected versions, reproduction steps, impact, and a minimal sanitized example. No response time or bug bounty is currently guaranteed.

## 中文

本应用仅面向本机单用户，不应暴露 API。模型请求会发送会话上下文和工具结果；本地命令在主机执行，权限检查不等于系统沙箱。Docker 验证不隔离所有聊天工具和扩展。

仅安装可信扩展，分享日志前脱敏。漏洞通过[仓库私密报告](https://github.com/LKDenchin/Micro-Multi/security/advisories/new)提交，不在公开 Issue 中发布漏洞细节或密钥。目前不承诺响应时限或奖励。
