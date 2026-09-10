# V2 架构说明

## 用户主流程

### 在线视频

```text
Browser
  ↓
URL 预检 / 元数据
  ↓
创建任务
  ↓
Celery / Redis
  ↓
Worker
  ├─ URL 公网安全检查
  ├─ yt-dlp 下载
  ├─ FFmpeg 提取 16 kHz 单声道 WAV
  ├─ faster-whisper 本地 ASR
  ├─ 时间轴分段
  ├─ LLM Map / Hierarchical Reduce
  └─ Markdown / TXT / SRT / JSON
```

### 本地文件

```text
Browser
  ↓
Nginx streaming upload
  ↓
FastAPI /data/uploads/<job-id>
  ↓
Celery / Redis
  ↓
Worker
  ├─ 文件边界校验
  ├─ FFmpeg
  ├─ faster-whisper
  ├─ 时间轴分段
  ├─ LLM 总结
  └─ 最终产物
```

默认 `KEEP_SOURCE_MEDIA=false` 时，本地源文件和中间媒体在任务成功后清理。

## 服务组成

- `frontend`：React SPA，由 Nginx 提供静态资源并反代 `/api/`。
- `backend`：FastAPI，负责鉴权、设置、视频预检、上传、任务状态、结果读取和文件下载。
- `worker`：Celery worker，执行下载、媒体处理、ASR 和 LLM。
- `redis`：Celery broker / result backend。
- `db`：PostgreSQL；本地开发可以使用 SQLite。
- `app_data`：任务输出与上传的临时媒体。
- `model_cache`：faster-whisper 模型缓存。

## Job 状态模型

主要状态：

```text
queued
processing
cancel_requested
completed
failed
cancelled
```

主要阶段：

```text
validating_url
loading_upload
downloading
extracting_audio
transcribing
segmenting
saving_transcript
summarizing
synthesizing_summary
exporting
completed
```

重新总结走独立阶段：

```text
resummarize_queued
loading_transcript
resummarizing
resynthesizing_summary
reexporting
completed
```

ASR 完成后会在调用外部 LLM 前先写入 `result.json`、TXT 和 SRT 检查点。因此即使 AI 摘要阶段失败，文字稿仍然可用，用户可以直接从已有文字稿重新生成摘要，不再重新下载和识别。

取消采用协作式停止：排队任务立即进入 `cancelled`；处理中任务先进入 `cancel_requested`，Worker 会在下载/FFmpeg/ASR/LLM 当前阻塞步骤结束或下一个进度回调时停止，不会粗暴杀死容器。

## 结果模型

`result.json` 是后续能力的核心持久化格式：

```json
{
  "source_url": "...",
  "platform": "bilibili",
  "title": "...",
  "metadata": {},
  "transcript": {
    "language": "zh",
    "duration": 1234.5,
    "segments": [
      {"start": 1.2, "end": 4.8, "text": "..."}
    ]
  },
  "summary": "..."
}
```

即使原媒体被清理，仍可以：

- 在线阅读文字稿
- 搜索文字稿
- 重新生成摘要
- 重新导出 Markdown / TXT / SRT / JSON

## 安全模型

- LLM API Key 不进入源码和 Docker Compose。
- Key 保存前使用部署级 `APP_ENCRYPTION_KEY` 加密。
- 浏览器读取设置时只收到“是否已配置”和末四位掩码。
- 管理员密码使用 Argon2 哈希。
- JWT 存储在浏览器 `sessionStorage`，关闭会话后不会长期保留。
- URL 入口阻止私网、回环、link-local、reserved、multicast 等 IP，降低 SSRF 风险。
- 本地上传有扩展名白名单和大小上限。
- 上传路径由服务端生成 job UUID，用户文件名只用于最终文件名，不决定目录。
- Artifact 下载使用固定 allow-list，不接受任意服务器文件路径。
- yt-dlp Cookie 只允许服务器侧挂载，并由 `.gitignore` 排除。
- 公网部署要求在 8080 前增加 HTTPS 反向代理。

## 中文错误层

Worker 原始异常只写服务日志；数据库与前端使用稳定错误码和中文用户提示，例如：

```text
login_required
source_forbidden
video_too_long
video_too_large
unsupported_media
asr_memory
llm_auth
llm_quota
llm_rate_limit
network_timeout
queue_error
```

前端根据错误码补充“下一步怎么处理”，避免用户直接面对底层命令行错误。

## 扩展方向

单机 Compose 当前默认一个 Worker，适合 CPU ASR 的资源模型。进一步扩展可考虑：

- GPU ASR Worker 与 CPU Worker 分队列
- S3/OSS/MinIO 替代本地 artifact volume
- Managed PostgreSQL / Redis
- 多用户与项目空间
- 视频播放器与时间轴跳转
- RAG / 向量知识库
- Webhook / 外部 API
