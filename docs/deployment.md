# 本地与 Docker 部署

本地启动命令见 README；数据默认写入启动目录的 `.masp`，可用 MASP_HOME 固定路径。
同一数据目录只运行一个服务进程，MVP 不支持多 worker 调度。

```bash
docker build -f docker/Dockerfile -t masp:local .
docker run --rm -p 127.0.0.1:8765:8765 -v masp-data:/data masp:local
```

该镜像提供 Web/API 与 fixture 验收模式。默认不挂载宿主 Docker socket，
因此镜像内的真实模型沙箱执行会明确阻止。需要真实执行时，推荐先在宿主
loopback 启动平台，使用本机 Docker 做隔离执行；远程受限 runner 属于后续部署能力。

不要将本地无认证 API 暴露公网。生产级多用户部署需要认证、授权、审计、
任务队列、数据库备份及单独沙箱宿主；当前版本不声称具备这些能力。

FastAPI 生命周期使用 [lifespan](https://fastapi.tiangolo.com/advanced/events/)，关闭时取消运行并等待有界调用退出。
