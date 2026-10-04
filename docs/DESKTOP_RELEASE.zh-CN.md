# 桌面构建与发布

## 软件包

| 平台 | 软件包 | 用法 |
| --- | --- | --- |
| Windows x64 | `Micro-Multi-Setup-0.1.0-x64.exe` | NSIS 安装、快捷方式及卸载 |
| Linux x64 | `Micro-Multi-0.1.0-amd64.deb` | `sudo apt install ./<package>.deb` |
| Linux x64 | `Micro-Multi-0.1.0-x86_64.AppImage` | 添加执行权限后运行，单文件 |

软件包包含 Python 后端、Node、生产依赖及许可证；不包含 Git、Docker 和外部扩展工具。数据位于用户目录，卸载保留。当前 Windows 安装包未签名，更新手动安装。

## Windows 构建

使用 Windows x64、Python 3.14.7、Node.js 24+、npm 及 Git：

```powershell
npm ci
python scripts/prepare_desktop.py
npm exec electron-builder -- --win --x64 --publish never
python scripts/smoke_packaged_desktop.py
python scripts/release_checksums.py
```

`npm run desktop:dist` 合并准备和安装包构建。

## Linux 构建

使用 x64 Linux、Python 3.11+、Node.js 24+、npm 及 Git。在 Linux 或 Linux 虚拟机/容器构建，不能复用 Windows npm 依赖。

Debian 归档需要 `binutils` 提供 `ar`，Debian/Ubuntu 使用 `sudo apt install binutils`。桌面冒烟还需 Linux CI 中的 GUI 库、D-Bus、GNOME Keyring、Xvfb 及 xauth。

```bash
npm ci
python3 scripts/prepare_desktop.py
npm exec electron-builder -- --linux deb AppImage --x64 --publish never
python3 scripts/release_checksums.py
```

`npm run desktop:dist:linux` 合并准备与两个包构建。Linux 准备下载固定 CPython 3.14.8 独立包，校验 SHA-256，并从 `requirements-desktop.lock` 安装依赖；主机 Python 只作构建引导。

### Linux 桌面检查

模型密钥使用 Secret Service 凭据库，需要已解锁的 GNOME Keyring 或兼容服务。在可丢弃 Ubuntu 构建机中，可在独立 D-Bus 会话执行：

```bash
dbus-run-session -- bash -c 'eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets)"; xvfb-run -a python3 scripts/smoke_packaged_desktop.py'
```

解包后的 Electron 在测试前配置 `chrome-sandbox` 后备辅助程序（`root:root`、权限 `4755`）。Debian 安装自动配置沙箱及支持系统的应用专用 AppArmor 策略；AppImage 使用平台支持的 Chromium 沙箱机制。

检查实际 `.deb` 安装：

```bash
sudo apt install ./dist/desktop/Micro-Multi-0.1.0-amd64.deb
python3 scripts/smoke_packaged_desktop.py --app-dir /opt/Micro-Multi
sudo apt remove micro-multi
```

无显示器系统使用上述 D-Bus/Xvfb 会话。AppImage 可 `--appimage-extract` 后用 `--app-dir squashfs-root` 检查；`--appimage-extract-and-run` 无需 FUSE。

### Ubuntu AppImage 沙箱策略

启动器保持 Chromium 沙箱启用。Ubuntu 24.04+ 通过 AppArmor 限制非特权用户命名空间，首次运行前安装应用专用策略，保留系统全局限制：

```bash
cat <<'EOF' | sudo tee /etc/apparmor.d/micro-multi-appimage >/dev/null
abi <abi/4.0>,
include <tunables/global>
profile micro-multi-appimage /tmp/{.mount_Micro-*,appimage_extracted_*}/micro-multi flags=(unconfined) {
  userns,
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/micro-multi-appimage
```

同一策略见 [desktop/micro-multi-appimage.apparmor](../desktop/micro-multi-appimage.apparmor)。路径覆盖 `/tmp` 下默认挂载及解压运行目录；使用其他临时目录时调整。Debian 自动配置安装版辅助程序与命名空间策略。

## 运行时布局

```text
Micro-Multi.exe / micro-multi   Electron 与内置 Node
resources/
  app/desktop/                 主进程与沙箱 preload
  app/src/masp/                后端、界面及原生扩展宿主
  app/node_modules/            生产 JS 依赖及许可证
  python/                      可迁移 Python 与依赖
  runtime-manifest.json        版本、来源 URL 和 SHA-256 溯源
```

真实文件系统路径支持 Python、内置 MCP 子进程、原生宿主和审查 CLI。源码允许列表排除用户数据、上传、日志、证据、测试、研究及本地配置；依赖在目标系统安装。

Windows Python 来自 python.org 嵌入版。Linux 使用 `20261001` 发布的经验证 CPython 独立包，URL 和哈希固定在脚本并记录于运行时清单。生产 Python/npm 的具体版本位于锁文件，第三方许可证随包保留。

安装版数据默认 Windows `%APPDATA%\Micro-Multi\data`，Linux `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data`；`MASP_HOME` 可覆盖。源码默认 `.masp`。

## 验证与发布

冒烟脚本用空临时数据启动实际安装包，不继承模型配置；检查包内 Node 依赖及 peer 闭包、后端健康、内置 MCP、空列表、真实渲染与桥、凭据读写删除、审查程序和原生 dsh。AppImage 检查实际解压资源。临时本机 DevTools 端口与后台渲染开关仅用于检查，结束后清理测试进程及数据。见[验证记录](RELEASE_VALIDATION.zh-CN.md)。

提交前执行 `python scripts/publication_audit.py`。安装包和 `SHA256SUMS.txt` 属于 Release 附件，不纳入源码。手动桌面工作流可构建 Windows/Linux 而不发布。

官方仓库：[Micro-Multi](https://github.com/LKDenchin/Micro-Multi)。已有 v0.1.0 附件保持原发布基线，本次源码更新不创建标签或 Release，见[当前变化](CURRENT_CHANGES.zh-CN.md)。
