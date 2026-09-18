# Video AI Studio v3 · AI 助手与视频知识工作空间

本版本在原视频解析项目上增加了**白色聊天工作台、多轮会话、视频上下文问答、内容模板、项目空间、成员权限、分享快照和受控工具工作流**。旧下载、FFmpeg、Whisper、摘要、导出及管理员博主研究继续保留。

> **这是实施版源码，不是已完成生产验收的发布。** 后端自动化测试 95 通过、1 跳过；前端纯函数/流解析测试 25 通过。本次未完成 npm 生产构建、浏览器实测、完整 Docker/PG/Celery 联调及真实模型/平台验证。详见测试报告，勿据此直接认定全部功能已上线可用。

## 从这里开始

- [升级与启动](docs/UPGRADE_V3.md)：**已有部署先看，保留密钥和数据卷**。
- [P0 / P1 / P2 实现清单与边界](docs/IMPLEMENTATION_STATUS_V3.md)。
- [测试记录与未验证项](docs/TEST_REPORT_V3.md)。
- [真实环境验收清单](docs/ACCEPTANCE_V3.md)。
- [本次修改文件清单](docs/CHANGED_FILES_V3.md)。

新安装仍可使用 `python scripts/init_env.py` 后 `docker compose up --build -d`。
升级旧环境不要重复生成 `.env`，不要执行 `down -v`。

新架构需要原媒体 `worker`、**`assistant-worker`** 和 **`assistant-reconciler`**；SQLite 本地模式用独立的 `python -m app.workers.assistant_worker`，详见升级说明。

## 能力提示

输入普通问题就是聊天；发送视频链接/上传文件后复用原任务管线，完成后可围绕文字稿提问。点击引用可查看对应的原文和时间点。未配置 AI、搜索或视觉服务时明确提示不可用，不使用假数据冒充结果。

没有 Embedding 服务也可关键词检索；向量路径沿用 1536 维限制。思维导图是结构化概念树，视觉功能是用户授权后的抽样帧分析；Agent 是限步只读工具计划，不是任意代码/浏览器执行器。

私有部署不等于所有推理都在本地。使用外部服务时会发送选定的输入，请按数据要求配置。普通账号不会借用部署管理员的 Cookie/平台登录态。

---

## 原项目说明（保留供视频管线和博主功能参考）

以下为升级前的项目说明；与 v3 的导航、权限或进程配置有差异时，以本页上方的 v3 文档为准。

# 视频 AI 工作台（Video AI Studio）

一个可私有部署的中文视频内容解析与创作者研究工作台。它既能把单条在线视频或本地媒体转成带时间轴的文字稿、字幕和 AI 摘要，也能批量研究抖音创作者的公开内容：从视频文本中提炼可追溯的观点、判断规则与思维框架，生成认知模型、可复用 Skill，并以历史文字稿作为检索证据回答新问题。

> 仅处理你有权访问的公开内容，并遵守来源平台规则与适用法律。Creator Skill 是对公开内容的方法论归纳，不代表、也不会冒充创作者本人。

<p align="center">
  <img src="docs/images/video-ai-studio-workspace.png" alt="视频 AI 工作台当前的视频解析页面" width="1200">
</p>

## 两类工作流

### 1. 单条视频解析

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

### 2. 博主研究（Creator Intelligence）

```text
抖音主页 / 任意视频 / 分享短链
          ↓
持久化 Playwright 登录会话识别创作者
          ↓
同步公开作品，数据库去重
          ↓
受控批次：下载 → 转写 → Video Insight
          ↓
跨视频归纳：证据化 Cognitive Profile
          ↓
Creator Skill + pgvector 历史文本检索
          ↓
按该方法论分析新问题，并展示视频证据
```

## 核心功能

### 视频解析

- 在线视频与本地视频、音频上传；提交前可识别标题、作者、封面、时长和平台。
- 基于 `faster-whisper` 的本地语音识别，提供快速、均衡、高精度三档策略。
- 支持标准总结、详细笔记、课程笔记、会议纪要、访谈整理、知识点提取和自定义 AI 摘要。
- 任务记录、阶段进度、取消、全文检索、失败重试；文字稿完成后可单独重新生成摘要，无需重复下载和转写。
- 导出 Markdown、TXT、SRT、JSON。ASR 文字稿会先落盘，即使 LLM 摘要失败也可继续查看、导出或重新总结。

### 博主研究

- 支持粘贴抖音标准主页、任意单条视频、`/user/self?modal_id=...`、`/jingxuan?modal_id=...` 与 `v.douyin.com` 分享短链；系统统一解析为创作者身份。
- 在“设置 → 抖音连接”中扫码登录一次，登录态保存在 Docker 持久卷中的 Playwright Profile。后续可复用会话识别作者、采集主页公开作品，并将 Cookie 快照交给 `yt-dlp` 下载已发现的视频。
- 博主研究按可选的 3 / 5 / 10 条批次执行；可设置自动继续、处理上限（10 / 50 / 全部）和失败率自动暂停阈值，避免一次性占满下载、ASR 与 LLM 资源。
- 每条视频生成 `Video Insight`：主张、推理链、条件—行动判断规则、分析框架、表达模式及精确时间轴证据。
- 跨视频生成证据化认知模型（Cognitive Profile），只保留反复出现且有来源支持的世界观、第一性原则、判断规则、框架、风险偏好与适用边界。
- 自动生成可下载的 `SKILL.md` 和 `references/profile.json`；Skill 保留“如何思考”，不塞入全部视频原文。
- 可为博主全部文字稿建立 `pgvector` 索引，再通过“Skill 与测试”界面以“Skill + 历史证据”的方式回答问题，结果会附带命中视频与时间点。
- 主页同步受平台访问条件影响时，可在博主详情页批量导入视频链接作为兜底。

## 支持来源

### 在线视频

- B站
- 抖音
- YouTube
- 以及 `yt-dlp` 可解析的其他公开视频来源

### 本地文件

```text
视频：MP4 / MOV / MKV / WEBM / AVI / M4V
音频：MP3 / WAV / M4A / AAC / FLAC / OGG / OPUS
```

默认 `KEEP_SOURCE_MEDIA=false`。成功处理后会清理原始上传媒体和中间 WAV，仅保留最终结果；失败任务的临时工作目录也会自动清理。设置页会分别统计任务结果、临时文件、上传源文件、博主 Skill、RAG 索引、抖音登录资料和模型缓存，清理操作不会删除结果、Skill、RAG、模型或登录资料。

## 技术架构

```text
React + Vite
     ↓
   Nginx
     ↓
  FastAPI ── PostgreSQL + pgvector
     ↓              ↑
Celery + Redis ─────┘
     ↓
Video / Creator Worker
├─ yt-dlp              单条媒体下载
├─ Playwright           抖音持久化会话、身份识别、主页作品采集
├─ FFmpeg               音频标准化
├─ faster-whisper       本地 ASR
├─ OpenAI-compatible LLM 视频总结、Video Insight、认知模型
└─ Embedding API        历史文字稿向量检索（当前索引为 1536 维）
```

`result.json` 是视频事实层的核心持久化格式，保存完整时间轴文字稿；`video_insights` 保存认知提取；`creator_analysis_runs` 保存博主认知模型；`creator_skill_versions` 保存版本化 Skill。这样可以在原始媒体清理后继续重新总结、重建检索索引或重新归纳方法论。

## 快速开始

### 环境要求

- Docker Engine 与 Docker Compose v2
- 建议至少 4 GB 内存；大量 CPU ASR 或长视频建议使用更高配置
- 足够的磁盘空间用于模型缓存、上传媒体、任务结果与 Playwright 浏览器资料

### 启动

在项目根目录运行：

```bash
python3 scripts/init_env.py
docker compose up -d --build
```

首次构建后端镜像会安装 Chromium，耗时通常比普通镜像构建更长。启动后检查：

```bash
docker compose ps
docker compose logs -f worker
```

访问：

```text
http://localhost:8080
```

登录后在“设置 → AI 模型”填写兼容 OpenAI API 的模型配置。可使用 DeepSeek、智谱 GLM 或其他兼容服务；要使用博主检索问答，还需填写 Embedding 模型。当前向量表固定为 1536 维，适配 `text-embedding-3-small` 一类模型；切换到其他维度前，需要调整迁移/索引并重建向量数据。

Windows 可使用 Docker Desktop 的 Linux Containers：

```powershell
py scripts\init_env.py
docker compose up -d --build
```

## 使用博主研究

1. 在“设置 → 抖音连接”点击“连接抖音账号”，使用抖音 App 扫码；状态变为“已连接”后，Profile 会保存在 `/data/playwright/douyin` 对应的 `app_data` Docker 卷中。
2. 打开“博主研究”，粘贴主页、视频或分享链接，点击“识别博主”，核对预览身份后选择“开始研究”。
3. 为首次研究选择批次、处理上限和失败阈值。建议先以 3 条、关闭自动继续验证下载、ASR 与模型配置；确认无误后再开启自动继续或增加批次。
4. 系统依次同步作品、转写、提取 Video Insight、构建认知模型并生成 Skill。每个阶段均可在详情页查看进度、暂停或继续。
5. 打开“Skill 与测试”，下载 `SKILL.md`；填写 Embedding 模型后点击“建立 / 重建检索索引”，即可输入问题，以方法论和检索到的历史文字稿证据进行测试。

浏览器会话会过期，也可能被平台要求人机验证。系统不会绕过验证；请在可信环境重新扫码。主页采集失败时，使用详情页“批量导入视频链接”继续单视频处理。

## Cookie、配置与输出

### `yt-dlp` Cookie 备用方式

Playwright 持久化登录是博主发现与作品采集的主路线。对于需要登录的单条下载，或扫码暂不可用时，也可挂载 Netscape Cookie 文件：

```text
secrets/yt-dlp.cookies.txt
```

在 `.env` 中配置：

```text
YTDLP_COOKIES_FILE=/run/secrets/yt-dlp.cookies.txt
PLAYWRIGHT_PROFILE_DIR=/data/playwright/douyin
```

重建 backend 与 worker 后生效：

```bash
docker compose up -d --build backend worker
```

`secrets/`、Cookie、LLM API Key、本地 `.env`、模型和运行数据均被 `.gitignore` 排除，绝不要提交到 Git。Cookie 过期或出现“需要登录”时，请重新登录、更新 Cookie 或重连抖音账号。

### 文件位置

单视频任务输出：

```text
/data/jobs/<job-id>/output/
├── result.md
├── transcript.txt
├── subtitles.srt
└── result.json
```

博主 Skill 输出：

```text
/data/creators/<creator-id>/skills/v<version>/
├── SKILL.md
└── references/profile.json
```

## 安全与生产建议

- LLM API Key 通过 `APP_ENCRYPTION_KEY` 加密保存，设置页只展示掩码；丢失该密钥后旧 Key 无法解密。
- 管理员密码使用 Argon2 哈希，JWT 仅存浏览器 `sessionStorage`。
- 视频 URL 会拦截私网、回环和保留 IP，降低 SSRF 风险；上传文件有格式与大小限制。
- Playwright Profile、Cookie 和账号凭据不返回前端、不进入 Git；访问登录状态接口也需要登录。
- Creator Skill 明确标注基于公开内容提炼，运行时回答区分事实、推断与不确定性，并引用历史证据。
- 公网部署请在 8080 前配置 Caddy、Nginx 或 Traefik HTTPS 反向代理，示例见 `deploy/Caddyfile.example`。
- 默认资源限制为 `DOWNLOAD_MAX_HEIGHT=1080`、`MAX_VIDEO_DURATION_SECONDS=14400`、`MAX_DOWNLOAD_BYTES=8589934592`，可在 `.env` 按需调整。

## 开源许可

本项目采用 [MIT License](LICENSE)。
