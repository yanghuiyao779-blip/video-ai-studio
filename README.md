# 视频 AI 工作台（Video AI Studio）V2

一个可部署、可复用的中文视频内容解析产品：

```text
在线视频 URL / 本地视频或音频
          ↓
      来源识别 / 上传
          ↓
       FFmpeg 音频提取
          ↓
      faster-whisper ASR
          ↓
       带时间轴文字稿
          ↓
   AI 分块总结 + 分层归并
          ↓
 Markdown / TXT / SRT / JSON
```

V2 在原有可运行版本上完成了中文产品化重构，重点不再只是“能跑”，而是让非开发者也能直接使用。

## V2 主要变化

- 全中文界面，默认浅色专业风格，可切换深色模式。
- 首页重构为“视频解析工作台”，技术参数默认收进高级设置。
- 支持 **在线视频** 和 **本地文件上传** 两种来源。
- 在线视频支持提交前“识别视频”，提前展示标题、作者、封面、时长和平台。
- Whisper 模型映射为“快速 / 均衡（推荐） / 高精度”三个用户档位。
- AI 摘要提供：标准总结、详细笔记、课程笔记、会议纪要、访谈整理、知识点提取、自定义。
- AI 未配置时给出明确中文引导，不再静默跳过。
- 独立“任务记录”页面，支持状态筛选、搜索和实时进度。
- 独立任务详情页，显示完整处理步骤和当前阶段。
- 完成后可直接在线阅读 AI 摘要和完整文字稿，并搜索文字稿。
- 支持只“重新生成 AI 摘要”，直接复用已有文字稿，不重新下载、不重新跑 ASR。
- ASR 完成后会先保存文字稿检查点；即使 AI 摘要失败，文字稿和字幕仍可读取/下载，并可只重试摘要。
- 支持任务取消：排队任务立即取消，处理中任务会在当前不可中断步骤结束后安全停止。
- 统一中文错误分类与解决建议，避免直接把 yt-dlp/FFmpeg/HTTP 原始错误甩给普通用户。
- 设置页拆分为 AI 模型 / 系统状态 / 账号安全。
- 系统状态检查数据库、FFmpeg、FFprobe、yt-dlp、任务队列和任务目录。
- API Key 仍然只在保存时发送，服务端加密保存，前端只看到掩码。
- 数据库迁移兼容 PostgreSQL 与 SQLite。

## 支持来源

### 在线视频

- B站
- 抖音
- YouTube
- 以及 yt-dlp 可解析的其他公开视频来源

需要登录的视频可通过服务器侧 Netscape Cookie 文件处理，Cookie 不进入源码。

### 本地文件

支持常见：

```text
MP4 / MOV / MKV / WEBM / AVI / M4V
MP3 / WAV / M4A / AAC / FLAC / OGG / OPUS
```

本地媒体上传到你的服务器处理。默认 `KEEP_SOURCE_MEDIA=false` 时，成功处理后会删除原始上传媒体和中间 WAV，仅保留最终结果。

## 技术架构

```text
React + Vite
     ↓
   Nginx
     ↓
  FastAPI
  ↙     ↘
PostgreSQL Redis
             ↓
           Celery
             ↓
        Video Worker
        ├─ yt-dlp
        ├─ FFmpeg
        ├─ faster-whisper
        └─ OpenAI-compatible LLM
```

Linux 为主要生产部署环境；Windows 推荐 Docker Desktop + Linux Containers。

---

# 全新部署

## Linux / 服务器

要求：

- Docker Engine
- Docker Compose v2
- 建议至少 4 GB 内存；`small` 模型 CPU 使用建议更高
- 足够的磁盘空间用于模型缓存和任务结果

生成部署密钥：

```bash
python3 scripts/init_env.py
```

会创建 `.env`。其中包含随机：

```text
APP_SECRET_KEY
APP_ENCRYPTION_KEY
ADMIN_PASSWORD
POSTGRES_PASSWORD
```

不会生成任何 LLM API Key。

启动：

```bash
docker compose up -d --build
```

检查：

```bash
docker compose ps
docker compose logs -f worker
```

打开：

```text
http://服务器IP:8080
```

登录后进入：

```text
设置 → AI 模型
```

选择服务商并填写自己的 API Key。

---

# 从 V1 升级到 V2

如果你正在运行之前版本，**不要重新执行 `init_env.py` 覆盖现有 `.env`**。

推荐在原项目目录先备份：

```bash
cp .env .env.backup
```

然后使用 V2 源码替换程序文件，但保留：

```text
.env
secrets/
Docker volumes
```

重新构建：

```bash
docker compose down
docker compose up -d --build
```

后端启动时会自动执行：

```bash
alembic upgrade head
```

V2 会依次执行：

```text
0002_product_ux_fields
0003_local_uploads
```

不会删除已有用户、AI 配置或历史任务数据。

升级后检查：

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
```

浏览器建议强制刷新一次：

```text
Ctrl + F5
```

详细升级步骤见 `UPGRADE_V2.md`。

---

# 使用流程

## 1. 在线视频

进入“视频解析”：

```text
在线视频
→ 粘贴链接
→ 识别视频
→ 确认标题/时长/平台
→ 选择识别档位
→ 选择摘要类型
→ 开始解析
```

“识别视频”只获取元数据，不下载完整媒体，主要用于提前发现：

- 链接错误
- 视频不存在
- 需要登录
- 视频过长
- 平台暂不支持

## 2. 本地文件

```text
本地文件
→ 选择视频/音频
→ 选择识别档位
→ 选择摘要类型
→ 上传并开始解析
```

Nginx 默认允许最大 8 GB 请求，后端最终仍以 `MAX_DOWNLOAD_BYTES` 为实际限制。

## 3. 识别档位

前端默认隐藏 Whisper 技术名称：

```text
快速        → base
均衡（推荐） → small
高精度       → medium
```

需要时可以展开“高级设置”直接选择：

```text
tiny / base / small / medium / large-v3
```

## 4. 摘要模板

提供：

```text
标准总结
详细笔记
课程笔记
会议纪要
访谈整理
知识点提取
自定义
```

还可以填写“额外要求”，例如：

```text
重点提取产品需求、用户痛点和行动项，不需要重复背景信息。
```

## 5. 任务详情

任务会显示：

```text
检查链接 / 读取文件
下载视频
提取音频
语音识别
整理文字稿
AI 摘要
生成文件
完成
```

处理完成后可以直接：

- 在线查看 AI 摘要
- 复制摘要
- 搜索完整文字稿
- 下载 Markdown
- 下载 TXT
- 下载 SRT
- 下载 JSON
- 重新生成 AI 摘要

“重新生成摘要”只调用 LLM，不重复下载和 ASR。

---

# AI 模型配置

进入：

```text
设置 → AI 模型
```

预置：

- DeepSeek
- 智谱 GLM
- 自定义 OpenAI-compatible 接口

服务商预设中的 Base URL / Model 都可以在代码升级后继续由用户调整；自定义服务商会显示 Base URL 输入框。

系统内部请求：

```text
<Base URL>/chat/completions
```

API Key：

- 不写入源码
- 不写入 `.env.example`
- 保存时通过 HTTPS/HTTP 请求发送一次
- 后端使用 `APP_ENCRYPTION_KEY` 加密后存入数据库
- 前端之后只获取掩码，例如 `****1234`

生产公网部署必须使用 HTTPS。

---

# 视频登录 Cookie

将 Netscape 格式 Cookie 放到：

```text
secrets/yt-dlp.cookies.txt
```

`.env`：

```text
YTDLP_COOKIES_FILE=/run/secrets/yt-dlp.cookies.txt
```

`secrets/` 已被 `.gitignore` 排除。

不要把 Cookie 写入 Python、Markdown、Dockerfile 或 Git。

---

# 数据输出

每个任务默认：

```text
/data/jobs/<job-id>/output/
├── result.md
├── transcript.txt
├── subtitles.srt
└── result.json
```

`result.json` 保存完整结构化时间轴，因此即使原媒体被清理，仍可以重新生成 AI 摘要。

---

# Windows

推荐使用 Docker Desktop + Linux Containers：

```powershell
py scripts\init_env.py
docker compose up -d --build
```

打开：

```text
http://localhost:8080
```

升级已有 V1 时同样不要重新生成 `.env`。

---

# 本地开发

## Python

支持 Python 3.11–3.13，推荐 3.12。

```bash
python scripts/init_local_env.py
cd backend
python -m venv .venv
```

Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

安装：

```bash
pip install -e ".[dev]"
```

首次启动或源码升级后先执行数据库迁移：

```bash
alembic upgrade head
```

API：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另一个终端：

```bash
python -m app.workers.local_worker
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

打开：

```text
http://localhost:5173
```

---

# 主要 API

```text
POST /api/auth/login
GET  /api/auth/me
PUT  /api/auth/password

GET  /api/health

GET  /api/settings/llm
PUT  /api/settings/llm
POST /api/settings/llm/test

POST /api/jobs/preview
POST /api/jobs
POST /api/jobs/upload
GET  /api/jobs
GET  /api/jobs/{id}
GET  /api/jobs/{id}/result
POST /api/jobs/{id}/retry
POST /api/jobs/{id}/cancel
POST /api/jobs/{id}/resummarize
DELETE /api/jobs/{id}
GET  /api/jobs/{id}/artifacts/{markdown|txt|srt|json}
```

---

# 资源限制

默认：

```text
DOWNLOAD_MAX_HEIGHT=1080
MAX_VIDEO_DURATION_SECONDS=14400
MAX_DOWNLOAD_BYTES=8589934592
KEEP_SOURCE_MEDIA=false
```

`MAX_DOWNLOAD_BYTES` 同时限制在线视频下载和本地上传。

---

# HTTPS

公网部署请使用 Caddy / Nginx / Traefik 等反向代理提供 TLS。

示例：`deploy/Caddyfile.example`。

---

# 安全说明

1. 不在源码保存 LLM API Key。
2. 不在源码保存平台 Cookie。
3. API Key 服务端加密保存。
4. `APP_ENCRYPTION_KEY` 必须备份；丢失后旧 API Key 无法解密。
5. 视频 URL 会阻止解析到私网、回环和保留 IP，降低 SSRF 风险。
6. 上传文件有扩展名白名单和大小限制。
7. 正常日志不打印 API Key / Cookie。
8. 公网部署必须启用 HTTPS。
