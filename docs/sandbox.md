# 沙箱与本地安全边界

真实模型没有 Shell 权限，只能返回经过验证的文件提案。
路径验证拒绝绝对路径、`..`、`.git`、Windows 设备名、符号链接和 junction。
应用只写入任务声明的文件作用域。

Docker Tool Adapter 将文件复制到临时快照，不挂载 Git 元数据或数据库。
快照以只读方式挂载，容器使用 UID 65534、断网、只读 rootfs、移除全部 capabilities、
no-new-privileges、1 CPU、512 MiB 内存、128 进程、64 MiB 临时目录。
单次命令最长 120 秒，工作区最多 20 MB / 2000 文件，输出限额 2 MB，
保存 stdout/stderr 各最多 64 KiB。超限/超时/取消会终止容器。

没有 Docker 时返回 `SECURITY_BLOCK`，禁止宿主机执行降级。
镜像是管理员配置，不接受模型修改。依赖需预装；禁止运行时自由安装网络包。
Docker 是隔离层，不承诺抵御所有内核或容器运行时漏洞。

固定 fixture 模式只解析、编译和解释一个受限算术 AST，不执行模型返回的 Python、Shell 或导入。
它是无需 Docker 的验收基线，不能用于运行任意真实项目。

本地 API 防止 DNS rebinding 与跨域写入，默认仅监听 loopback。
无用户认证与多租户授权；不要直接暴露到公网。
模型凭证只从服务进程环境读取，错误不打印提供商响应体。
不要在需求、README、工具输出或代码中放置秘密；这些内容属于运行记录和模型上下文。

容器参数依据 [Docker run 文档](https://docs.docker.com/engine/containers/run/)。
