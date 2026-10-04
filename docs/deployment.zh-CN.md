# 从源码运行

源码模式适合开发，或在浏览器中使用界面。准备 Python 3.11+、Node.js 24+、npm 和 Git，并在仓库根目录操作。安装桌面包则参考[安装指南](DESKTOP_RELEASE.zh-CN.md)。

## 安装与启动

先创建 Python 环境：

```bash
python -m venv .venv
```

Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1` 激活，Linux 使用 `source .venv/bin/activate`。然后安装 Python 包及锁定的 JavaScript 依赖：

```bash
python -m pip install -e ".[dev]"
npm ci
```

执行 `npm run desktop` 启动 Electron 应用。使用浏览器时，运行 `python -m masp.cli serve`，再访问 `http://127.0.0.1:3080/`。服务保持在本机，应用面向单用户使用。

## 配置

| 变量 | 用途 |
| --- | --- |
| `MASP_HOME` | 指定可写的数据目录，源码默认使用工作目录下的 `.masp`。 |
| `MASP_PORT` | 设置桌面后端端口，默认为 `3080`。 |
| `MASP_MODEL_BASE_URL` | 提供环境模型的接口地址。 |
| `MASP_MODEL_NAME` | 设置该模型的 ID。 |
| `MASP_MODEL_API_KEY` | 提供模型凭据，不应写入仓库文件。 |
| `MICRO_MULTI_NODE` | 指定原生宿主使用的 Node 运行时。 |

通过界面添加的模型配置将密钥保存在系统凭据库，具体步骤见[模型配置](MODELS.zh-CN.md)。扩展可能另需自己的运行时、账号或环境配置。

## 数据与备份

安装版数据默认位于 Windows 的 `%APPDATA%\Micro-Multi\data`，或 Linux 的 `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data`，`MASP_HOME` 可覆盖。升级和卸载保留这些数据。

数据目录应与程序分开备份，最好先停止活动任务。模型凭据位于系统凭据库，因此复制数据目录并不等于备份密钥；关联到原目录的项目也需要独立备份。存储布局见[架构](architecture.zh-CN.md)，中断任务见[恢复](DURABLE_TURNS_AND_MODEL_RECOVERY.zh-CN.md)。
