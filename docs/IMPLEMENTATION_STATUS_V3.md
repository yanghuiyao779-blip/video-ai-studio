# v3 分阶段实施清单与实际边界

本包在上传源码的基础上实现三个阶段，保留原视频处理管线、任务页面、摘要导出及部署管理员的博主研究。“已实现”指代码中存在处理逻辑和对应入口，不代表外部服务已经在本次环境中联调通过。

## P0：AI 助手主链路

| 能力 | 实现位置 | 状态 |
|---|---|---|
| 白色首页、统一输入框、左侧新建聊天与最近会话 | `frontend/src/App.jsx`、`assistant/HomePage.jsx`、`Composer.jsx`、`assistant.css` | 已实现 |
| 多轮聊天、流式输出、历史持久化 | `services/llm.py`、`assistant_runner.py`、`db/assistant.py` | 已实现；测试使用模型替身 |
| 视频链接、本地音视频上传、已有视频挂载 | `assistant/urls.js`、`assistant_urls.py`、`api/jobs.py`、`assistant_service.py` | 已接原 Job；真实平台/ASR 需外部验收 |
| 媒体进度、按需显示的右侧上下文 | `ChatPage.jsx`、`useConversation.js` | 使用服务端状态，不写死完成百分比 |
| 词法检索、可选向量融合、时间点查找 | `video_knowledge.py`、`embeddings.py` | 已实现，支持降级 |
| 时间引用与原文回看 | `ChatPage.jsx`、`legacy/VideoPages.jsx` | 定位文字稿时间点，不承诺所有平台视频播放器 seek |
| 幂等提交、运行锁、停止/重试、重连 | `ChatRun`、`assistant_service.py`、`assistant_runner.py` | API/SQLite 自动化测试覆盖 |
| 媒体与问答索引独立状态 | `VideoKnowledgeIndex`、Worker | 索引失败不抹掉文字稿 |

“新建聊天”打开空草稿，首条发送后才入库。仅普通聊天模式不下载视频链接，也不使用当前视频上下文。

## P1：内容加工与会话管理

| 能力 | 实际形态 |
|---|---|
| 视频/课程总结、学习笔记、会议纪要、脚本 | 基于当前素材的模板，位于 `assistant_templates.py` |
| 时间轴 | 模型选择证据片段，后端从原片段提取时间；不采用模型编造的时间 |
| 思维导图 | 可展开的结构化概念树及 Markdown/JSON，不是可拖拽无限画布 |
| 对话搜索、改名、置顶、归档、标签 | 服务端查询/分页，位于 `HistoryPage.jsx` 和 `api/assistant.py` |
| 会话与成果导出 | Markdown、JSON、ZIP；原媒体 MD/TXT/SRT/VTT/JSON/DOCX/ZIP 保留 |
| 博主 → 对话 | 复用该博主已有视频文字稿，限部署管理员 |
| 原视频详情和设置页面 | 拆至 `legacy/VideoPages.jsx`，不是直接删除原功能 |

旧博主采集、研究控制和画像本身没有重写。整库超过默认单次 20 个视频时，应选择具体视频或项目子集。

## P2：项目、分享与受控工具

| 能力 | 实际形态 |
|---|---|
| 多视频对比 | 至少两个已授权视频，有限片段与已有摘要取材 |
| 跨视频知识空间 | Workspace、素材关系和项目指令，显式选择“项目视频库”范围 |
| 多用户权限 | owner / editor / viewer；原 Job 增加归属 |
| 分享对话 | token 哈希、到期、撤销、不可变的匿名只读文字快照 |
| Web + Video | Tavily 搜索摘要 + 视频证据，需配置和当前请求授权 |
| 画面理解 | FFmpeg 抽样帧 + 图片模型分析，不是原生完整视频推理 |
| Agent 工具计划 | 限步、白名单、只读，不支持任意工具名或代码执行 |
| 可恢复学习工作流 | 笔记 → 时间轴 → 思维导图，分步保存，证据版本一致才复用 |
| 队列遗漏与中断识别 | 重投未开始/等待任务，失去心跳的回答标记失败并保留输出，由用户重试 |

没有加入通用可视化工作流编辑器、任意浏览器/终端 Agent、原生长视频模型输入、自动剪辑/视频生成、组织 SSO、用量计费、企业级审计和大规模多租户隔离。没有用占位按钮把这些能力伪装为可用。

## 工程结构

```text
frontend/src/
  App.jsx                       新壳层、白色布局、导航和最近会话
  assistant/
    HomePage.jsx                初始页和快捷场景
    Composer.jsx                输入、预览、上传和范围选择
    ChatPage.jsx                消息、来源、上下文、成果和分享
    HistoryPage.jsx             历史管理
    ProjectsPage.jsx            项目、成员和管理员建号
    SharedPage.jsx              匿名只读快照
    Markdown.jsx                React 安全文本渲染
    useConversation.js          SSE 重连和资源状态
    api.js / urls.js / ...      接口与纯函数
  legacy/VideoPages.jsx         原视频、博主和设置页保留

backend/app/
  api/assistant.py              会话、运行、资源、项目和分享 API
  api/assistant_schemas.py      参数边界
  db/assistant.py              11 张新表
  services/assistant_*.py       授权、执行、模板、工具和成果
  services/video_knowledge.py  单视频/多视频索引与检索
  services/embeddings.py       共用 Embedding 客户端
  workers/assistant_worker.py  SQLite 本地进程
  workers/assistant_reconciler.py
```

## 相比最初方案的调整

1. 不额外引入 Router、Markdown、全局状态和 Agent 框架依赖。保留原 React/Vite 依赖，采用独立模块和安全的 Markdown 渲染器；不是把新功能继续堆进原 App。
2. 新增 `ChatRun` 持久执行状态。长任务不绑定 HTTP 连接，切换页面仅断开观察，不取消后端任务。
3. 通过资源关系表关联视频，一个视频可以被多个授权会话使用。
4. 优先提供不依赖 Embedding 的检索，1536 维向量为可选路径。当前 Embedding 与聊天共用原 Base URL/Key，不支持动态向量维度。
5. 不照搬设计图中的虚构付费卡、专业版升级和假服务成功状态。
6. 落地多账号时收紧全局设置、Cookie 和博主入口。普通账号不能借用管理员的平台身份。
7. PostgreSQL 使用冻结 Alembic 迁移；SQLite 走原 bootstrap，并增量补充所有权字段。

## 默认容量和信任边界

单条消息最多 16000 字符、8 个新增视频链接、单次最多 20 个视频。历史上下文预算默认 24000 字符，素材预算 40000 字符；检索有 20000 chunk 的扫描上限。该实现适用于有限规模工作空间，不是无上限知识库。

长视频/多视频总结可能使用有限片段和已有摘要，界面显示覆盖与降级提示。引用 ID 会校验存在性，但这不等于对每句话完成事实蕴含验证，用户仍需核对原文。历史回答保留当时的引用片段；原文字稿修改后，历史引用和当前文字稿可能不同。

“私有部署”指应用和存储的部署方式。调用外部聊天、Embedding、搜索、图片模型时，所选择的输入仍会发给相应服务。敏感数据场景需要选择合适的兼容本地服务及网络边界。

## 需要人工验收的部分

详见 `TEST_REPORT_V3.md` 和 `ACCEPTANCE_V3.md`：本次没有成功完成 npm 依赖安装/生产构建、浏览器实测、Docker/PostgreSQL/Celery 组合启动和真实平台/模型调用。不能把代码存在等同于已在生产验证。
