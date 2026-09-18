# Video AI Studio v3 实施版：升级与启动

> 本包基于本次上传的源码修改，不是重新创建的示例工程。已提供 P0、P1、P2 的代码实现、迁移、测试及运行配置。
> 这是需要在你的环境继续验收的实施版，不是已完成生产验收的正式发布：本次未完成 npm 安装/生产构建、浏览器实测、Docker/PostgreSQL/Celery 联调以及真实模型和视频平台测试。具体见 `docs/TEST_REPORT_V3.md`。

## 1. 先读这几条

- **保留原 `.env`、`backend/.env`（如使用）、`secrets/`、数据库和数据卷。不要重新生成已有的加密密钥。** 原有模型 Key 依赖 `APP_ENCRYPTION_KEY` 解密。
- **升级不要执行 `docker compose down -v`。** 该命令会删除数据卷。
- **使用原来的 Compose 项目名和目录。** 解压到另一目录后直接启动，Compose 可能创建另一套命名卷，看起来像“历史数据没了”。使用原目录更新源码，或明确指定原项目名 `docker compose -p 原项目名 ...`。
- 现在除了原媒体 `worker`，还需要 `assistant-worker` 和 `assistant-reconciler`。只有 API/前端启动时，聊天会停留在等待状态。
- SQLite 本地开发需要三个 Python 进程：API、原媒体 Worker、Assistant Worker；不要再启动 Celery 版 reconciler。
- 页面默认白色。普通问题直接聊天，视频链接发送后进入原处理管线。**新建聊天先打开空草稿，发送第一条消息时才创建数据库会话。**

## 2. 已部署 Docker 项目：建议的升级顺序

### 2.1 备份

在原项目目录保存数据库备份，并备份 `.env`、`secrets/` 和 `app_data` 卷；备份应保存在项目源码目录之外。

```bash
docker compose ps
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > ../video-ai-before-v3.sql
```

数据库备份**不包含媒体、文字稿及浏览器资料文件**，仍需单独备份 `app_data`。数据卷真实名称可通过 `docker volume ls` 查看。不要把含 Key/Cookie 的备份提交到 Git。

### 2.2 更新源码

将本包源码合并到原目录，保留原环境文件和私有数据。先在测试环境尝试升级，再更新日常环境。已有源码如与本次上传版本不同，应人工合并，不能盲目覆盖。

### 2.3 停止旧的应用进程并启动新版本

先等媒体任务处理结束，再停止应用进程，避免旧、新代码同时操作迁移中的数据库。

```bash
docker compose stop frontend worker backend
docker compose build backend frontend
docker compose up -d
docker compose ps
docker compose logs --tail=120 backend assistant-worker assistant-reconciler worker
```

若旧部署也存在同名 assistant 进程，应一并停止。首次升级通常只有原 `frontend / worker / backend`。

后端容器启动命令会执行 `alembic upgrade head`，新增迁移为：

```text
0009_assistant_workspace
```

该迁移增加 `jobs.owner_id` 及 11 张助手/项目相关表，不删除原 Job、Creator 或结果文件。启动时历史无归属 Job 分配给 `.env` 指定的部署管理员；普通账号不会自动取得这些历史视频。

迁移失败时不要反复换密钥、删除数据或强行跳过迁移。保留日志，回到测试环境查明原因。回退以恢复备份为准；执行 downgrade 会删除新会话/项目数据，不建议对生产库直接尝试。

### 2.4 验收进程

| 进程 | 职责 |
|---|---|
| `backend` | API、登录、权限、会话与状态流 |
| `worker` | 原下载、FFmpeg、ASR、摘要及博主任务 |
| `assistant-worker` | 消费 `assistant` 队列：聊天、视频索引、问答和成果生成 |
| `assistant-reconciler` | 修复遗漏的聊天投递，标记失去心跳的回答；不会擅自重试已失败的付费模型调用 |
| `frontend` | 白色工作台与流式聊天页面 |
| `db / redis` | 持久数据与队列 |

旧管理员账号继续使用。已有账号的密码不会因启动时的 `ADMIN_PASSWORD` 改变而重置。

## 3. 首次安装

仅在没有原配置的新环境中：

```bash
python scripts/init_env.py
docker compose up --build -d
```

脚本会拒绝覆盖已有 `.env`。默认访问端口沿用项目的 `WEB_PORT`，未设置时为 `8080`。首次构建需要下载 Python/Node 依赖、浏览器及相关镜像，首次 ASR 还可能需要下载模型。

## 4. 本地开发（SQLite）

要求 Python 3.11–3.13、Node 22、FFmpeg/FFprobe。先安装项目声明的完整依赖，不应只安装聊天部分。

```bash
cd backend
python -m venv .venv
# Linux / WSL:
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

修改 `backend/.env` 中的密钥和管理员密码。保持：

```dotenv
DATABASE_URL=sqlite:///./video_ai.db
DATA_DIR=./data
QUEUE_MODE=local
```

分别在三个终端激活同一个虚拟环境，并从 `backend/` 目录运行：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
python -m app.workers.local_worker
```

```bash
python -m app.workers.assistant_worker
```

前端第四个终端：

```bash
cd frontend
npm ci
npm run dev
```

Vite 沿用原代理配置。SQLite 升级由 `bootstrap_database()` 增量补充 `owner_id` 和新表；不要在原本使用 SQLite 的库上直接执行历史 PostgreSQL 专用迁移。多人/正式使用优先测试 Docker 中的 PostgreSQL 部署。

## 5. 模型与可选能力

### 普通聊天、总结、视频问答

用部署管理员登录“设置”，配置 OpenAI-Compatible 的 Base URL、模型、API Key，并执行连接测试。原单轮 `complete()` 接口保留；助手增加多轮与流式调用。

没有聊天 Key 时，不会伪造 AI 回答：视频文字稿及原导出仍可使用，助手提示未配置模型。这里的“已配置”只表示配置存在，不等于实时服务可用。

### 视频检索

没有 Embedding 配置也能使用中文双字词/英文词的 BM25 式关键词检索。配置 Embedding 后尝试词法与向量融合：

- 当前沿用 **1536 维**约束。
- Embedding 与普通聊天共用原 Base URL/API Key，模型名使用设置中的 `embedding_model`。
- PostgreSQL 使用 pgvector 表达式 HNSW 索引；SQLite 使用可移植向量编码和本地计算，适合小规模开发。
- 维度不符、接口不支持或调用失败时保留文字稿和词法检索，不把整个视频任务改成失败。
- 右侧“重建问答索引”是显式操作，可能产生 Embedding 费用。

### 联网研究

在原 `.env` 添加：

```dotenv
ASSISTANT_WEB_API_KEY=你的TavilyKey
```

重建相关服务环境：

```bash
docker compose up -d --force-recreate backend assistant-worker assistant-reconciler worker
```

用户需要在本次请求显式允许搜索。发送至 Tavily 的是搜索问题，不会自动上传完整文字稿；问题本身仍可能含敏感内容。当前取搜索结果摘要与来源 URL，**不是完整网页抓取或浏览器自动化**。

### 画面分析

```dotenv
ASSISTANT_CAPTURE_FRAMES=true
ASSISTANT_VISION_MODEL=支持图片输入的兼容模型
ASSISTANT_VISION_BASE_URL=
ASSISTANT_VISION_API_KEY=
ASSISTANT_MAX_FRAMES=6
```

独立视觉 Base URL/Key 留空时使用普通聊天配置，模型名仍需明确设置。要求接口支持 chat-completions 的 `image_url` 内容项。

此能力是 **FFmpeg 抽样帧 + 图片模型分析**，不是原生视频模型逐帧理解。需要管理员允许在视频处理时保存抽样帧，且用户在当前请求允许将这些帧发给模型。旧任务未保存帧时会明确报错；需重新处理仍有源文件的视频，或重新上传。只添加视觉 Key 不会补出旧视频帧。

### 工具计划与工作流

Agent 仅能调用白名单只读工具：视频检索、视频摘要取材、联网搜索、抽样帧分析。默认最多 4 步；没有终端、任意网页执行或任意代码执行能力。

“生成学习包”按笔记 → 时间轴 → 思维导图顺序运行，每步持久化成果。中途失败可重试；只有证据与文字稿版本一致时才复用之前步骤。

## 6. 多账号、项目与权限

部署管理员可在设置页创建普通账号。项目创建者是 owner，可将已有用户按明确的 `viewer / editor` 加入项目。

- 普通用户默认只能访问自己的视频和会话。
- 项目素材可被该项目成员读取；editor 可以继续项目对话，viewer 只能查看。
- 移除项目成员后，其在该项目内创建的会话也失去访问权限。
- 删除会话不删除原视频；删除项目会删除项目会话及关联关系，但不删除原视频文件。
- 分享是有期限、可撤销的匿名只读**文字快照**，不是开放原始媒体下载。默认不附带引用原文。
- 历史已授权阅读并生成的文字、用户复制的内容或已下载文件不能被“远程收回”。撤销分享使链接失效，不会撤回接收方保存的副本。
- **普通用户的视频链接按匿名方式解析，不借用部署管理员的 Cookie/抖音登录态。** 需要登录的内容由管理员处理并明确共享，或由有权使用该内容的人上传文件。
- 全局模型、服务器存储清理、Cookie/抖音连接和旧博主研究仍限部署管理员；当前不是独立 Cookie 的多租户平台。

## 7. 故障定位

| 现象 | 优先检查 |
|---|---|
| 对话一直等待 | `assistant-worker` 是否在线、队列名是否为 `assistant` |
| 视频一直排队 | 原 `worker` 是否在线，CPU/ASR 模型及平台访问是否正常 |
| 文字稿成功但问答索引降级 | Embedding 接口/模型/1536 维，不必重新下载视频 |
| 流式消息一次性出现 | 反向代理是否关闭 response buffering；本包 Nginx 已关闭 |
| 刷新后看不到旧数据 | 是否换了 Compose 项目名、数据卷、SQLite 相对路径或账号 |
| 不能读取模型 Key | 是否换过 `APP_ENCRYPTION_KEY`，不要继续重置 |
| 抖音普通用户提示登录 | 普通用户不会继承管理员平台身份，按上述授权流程处理 |
| 停止后短暂仍显示运行 | 协作取消需要等下一次模型分片或当前外部请求返回/超时 |

## 8. 上线边界

本包未加入生产级配额/账单、企业 SSO、完整审计、灾备自动化、限流/验证码或任意复杂工作流编辑器。默认用于受信任的私有工作空间。公网部署需要 HTTPS、访问控制、费用限额、备份及受控的网络出口。

URL 预检沿用原安全校验，但不等同于对所有 yt-dlp 重定向和 DNS 变化提供完整网络隔离。不要把能够访问内网的下载 Worker 直接暴露给不可信公众输入。
