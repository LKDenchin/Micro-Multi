# Micro-Multi v0.1.0 — 桌面发布说明

Micro-Multi 将本地多 Agent 开发工作台带到 Windows 和 Linux。

- Windows x64 安装程序，支持目录选择、快捷方式及卸载。
- Linux x64 Debian 包及 AppImage 单文件。
- 内置 Python 后端和 Node，无需额外安装两者即可启动应用。
- 持久化对话、剪贴板附件、项目浏览、差异/审查和桌面恢复。
- 主 Agent 与成员协作，提供模型选择、取消、进度及验证记录。
- 兼容 deepseek-harness Cordis Host 生态，同时支持 Skills、MCP 及本地命令插件。
- 中英文文档及界面。
- 首次启动不携带个人项目、上传、对话历史或模型凭据。

## 安装

根据系统选择并对照 `SHA256SUMS.txt` 校验：

| 系统 | 附件 |
| --- | --- |
| Windows x64 | `Micro-Multi-Setup-0.1.0-x64.exe` |
| Debian / Ubuntu x64 | `Micro-Multi-0.1.0-amd64.deb` |
| Linux x64 便携版 | `Micro-Multi-0.1.0-x86_64.AppImage` |

Windows 运行安装程序；Debian 使用 `sudo apt install ./<package>.deb`；AppImage 添加执行权限后运行。Ubuntu 的应用专用命名空间策略见[桌面指南](DESKTOP_RELEASE.zh-CN.md#ubuntu-appimage-沙箱策略)。启动后连接自己的模型并创建/导入项目。仓库工作需要 Git；插件外部工具和 Docker 另行安装。

## 运行与安装注意事项

安装前验证校验和。Windows 安装包未签名，更新手动安装；卸载保留数据。Linux 密钥使用 Secret Service 凭据库。启动后配置自己的模型接口与凭据。

本页记录 0.1.0 发布基线，后续源码变化见[当前变化](CURRENT_CHANGES.zh-CN.md)，不代表重新发布安装包。

[文档](https://lkdenchin.github.io/Micro-Multi/docs/readme-zh-cn.html) · [更新记录](../CHANGELOG.zh-CN.md) · [问题](https://github.com/LKDenchin/Micro-Multi/issues) · [交流](https://github.com/LKDenchin/Micro-Multi/discussions)
