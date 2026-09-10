# V1 → V2 升级指南

V2 可以直接使用 V1 的 PostgreSQL 数据卷、Redis、任务文件和 `.env`。

## 1. 备份

在原项目目录：

```bash
cp .env .env.backup
```

如有重要数据，建议同时备份 Docker volume 或 PostgreSQL。

## 2. 保留这些内容

不要删除：

```text
.env
secrets/
Docker volumes
```

尤其不要重新执行 `scripts/init_env.py` 覆盖原来的 `APP_ENCRYPTION_KEY`，否则数据库里原来加密的 API Key 将无法解密。

## 3. 更新源码

将 V2 源码覆盖原项目程序文件。最简单的方式是保留原目录名 `video-ai-studio`，替换：

```text
backend/
frontend/
docker-compose.yml
scripts/
deploy/
README.md
```

## 4. 重建

```bash
docker compose down
docker compose up -d --build
```

后端容器会在启动 API 前自动：

```bash
alembic upgrade head
```

迁移：

```text
0001_initial
→ 0002_product_ux_fields
→ 0003_local_uploads
```

## 5. 验证

```bash
docker compose ps
```

预期：

```text
db        healthy
redis     healthy
backend   healthy
frontend  running
worker    running
```

然后：

```bash
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
```

浏览器打开：

```text
http://localhost:8080
```

远程 Linux：

```text
http://服务器IP:8080
```

升级后请使用 `Ctrl + F5` 强制刷新前端缓存。

## 6. V2 首次检查

登录后进入：

```text
设置 → 系统状态
```

确认：

```text
API 服务      正常
数据库        正常
FFmpeg        正常
FFprobe       正常
yt-dlp        正常
任务队列      正常
任务存储      正常
```

然后进入：

```text
设置 → AI 模型 → 测试连接
```

最后用一个 2–5 分钟的小视频完成首轮验证。

## 回滚

如果需要回滚程序，优先恢复旧源码并保留数据库备份。不要随意执行 Alembic downgrade 到生产数据库；V1 ORM 不认识 V2 新字段并不会破坏数据，但正式回滚前仍建议先做数据库备份。
