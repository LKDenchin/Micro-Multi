# 本地部署

Windows 使用桌面安装程序，Linux 使用 Debian 或 AppImage 包。[桌面指南](DESKTOP_RELEASE.zh-CN.md)说明可复现构建与软件包验证。

源码运行需要 Python 3.11+、Node.js 24+、Git、Python 依赖和锁定 npm 依赖：

```bash
python -m venv .venv
# 激活虚拟环境后执行
python -m pip install -e ".[dev]"
npm ci
python -m masp.cli serve
```

浏览器访问 `http://127.0.0.1:3080/`；桌面启动使用 `npm run desktop`。服务仅绑定本机。

用 `MASP_HOME` 指定独立可写数据目录。源码默认 `.masp`；安装版默认 Windows `%APPDATA%\Micro-Multi\data`、Linux `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data`。桌面端口可由 `MASP_PORT` 指定。模型凭据通过工作区与系统凭据库配置。数据单独备份，升级或卸载保留用户数据。
