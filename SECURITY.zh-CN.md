# 安全政策

Micro-Multi 面向本机单用户，API 保持在本机。最新发布版提供安全修复。

## 信任边界

- 模型服务接收会话上下文及选择的工具结果。
- 模型配置密钥使用系统凭据库；扩展配置和日志可能包含敏感值，分享前脱敏。
- 本地命令在主机执行，权限检查不构成系统沙箱。
- 可选 Docker 验证拒绝主机回退，但不隔离全部聊天工具或扩展。
- Skills、MCP、原生包和插件是可信输入，安装前检查来源与访问要求。
- 卸载保留用户数据，数据目录见 README。

## 漏洞报告

通过 [Security → Report a vulnerability](https://github.com/LKDenchin/Micro-Multi/security/advisories/new) 私密报告。不要在公开 Issue 发布凭据、利用细节或未脱敏日志。

说明受影响版本、复现步骤、影响及最小脱敏示例。目前不保证响应时限，也不承诺漏洞奖励。
