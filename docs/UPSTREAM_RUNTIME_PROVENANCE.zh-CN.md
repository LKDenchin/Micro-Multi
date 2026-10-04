# 上游运行时溯源

Micro-Multi 直接导入下列发布运行时，它们属于上游实现，不是本项目原创代码。安装元数据与 package-lock.json 标识实际产物；发布包的许可证必须保留。

| 包 | 安装版本 | 声明许可证 |
|---|---|---|
| `@deepseek-ai/cordis` | `4.0.4` | MIT |
| `@deepseek-ai/dsh-agent` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-agent-loop` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-app-boot` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-fs-local` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm-pi-ai` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session-persistence-jsonl` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session-projection` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-skill` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-skill-filesystem` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent-fork-in-process` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent-spawn-in-process` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-system-prompt` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-tools` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-attachment` / `dsh-attachment-local` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm-deepseek` / `dsh-anonymous-user-id` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-user-approval` | `0.2.0-rc.1` | MIT |

Harness 仓库：[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。本地源码审查基线为 `4878cdabd87d4041bdaff61d04c966883b9fd07a`，不声称全部 npm 产物均从该提交发布。

代表性许可证保存在 `docs/licenses/HARNESS_MIT_LICENSE.txt` 和 `docs/licenses/CORDIS_LICENSE.txt`，各安装包仍为完整声明的权威来源。

改编组件保留原许可证及来源记录；再分发说明见 [NOTICE](../NOTICE)。应用编排、传输适配、设置表单与桌面界面由本仓库维护。

## 原生插件兼容来源

原始 `@deepseek-ai/dsh-settings@0.0.1-rc.3` 命名空间 SettingsProvider 未改动地保存在 `src/masp/native/vendor/dsh-settings-namespace/index.mjs`；相邻 LICENSE 和 provenance.json 记录发布 URL 和 SHA-256。该隔离服务与当前 Config 设置实现共存，适配及持久化层由 Micro-Multi 实现。

框架快照从发布 npm 归档提取，按 package-lock.json 完整性及逐源码哈希验证。快照标识采用框架版本、来源和完整性，不受无关锁文件变化影响。宿主加载与浏览器构建使用该基准，不将插件改写的已安装 SDK 当作新基准。当前完整版本见 [package.json](../package.json) 与 [package-lock.json](../package-lock.json)。
