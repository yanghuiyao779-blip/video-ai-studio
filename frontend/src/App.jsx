import { useEffect, useMemo, useState } from 'react'
import { api, getToken, setToken } from './api.js'

const PROVIDERS = {
  deepseek: { label: 'DeepSeek', hint: '适合通用总结与中文内容处理', base_url: 'https://api.deepseek.com', model: 'deepseek-v4-flash' },
  zhipu: { label: '智谱 GLM', hint: '智谱开放平台 OpenAI 兼容接口', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-5.2' },
  openai: { label: 'OpenAI', hint: '使用 OpenAI 官方兼容接口', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  custom: { label: '自定义兼容接口', hint: '适用于 OpenAI-compatible 网关或私有服务', base_url: '', model: '' },
}

const SUMMARY_PRESETS = {
  standard: { label: '标准总结', desc: '概览、关键观点、结论与重点时间点' },
  detailed: { label: '详细笔记', desc: '尽量保留论证、案例、数据和重要细节' },
  course: { label: '课程笔记', desc: '知识框架、核心概念、例子与复习清单' },
  meeting: { label: '会议纪要', desc: '议题、结论、决策与行动项' },
  interview: { label: '访谈整理', desc: '核心问答、观点、案例与立场' },
  knowledge: { label: '知识点提取', desc: '定义、方法、事实、数据与关联关系' },
  short_copy: { label: '短视频文案', desc: '标题、开场、口播与行动引导' },
  transcript: { label: '仅整理原文', desc: '不调用 AI，仅生成可搜索文字稿和字幕' },
  custom: { label: '自定义', desc: '按照你的要求整理内容' },
}

const ASR_PROFILES = {
  quick: { label: '快速', model: 'base', desc: '速度优先，适合快速预览' },
  balanced: { label: '均衡（推荐）', model: 'small', desc: '速度与准确率平衡，适合大多数视频' },
  accurate: { label: '高精度', model: 'medium', desc: '准确率更高，CPU 处理时间更长' },
}

const STATUS = {
  queued: ['等待中', 'neutral'],
  processing: ['处理中', 'info'],
  cancel_requested: ['正在取消', 'warning'],
  completed: ['已完成', 'success'],
  failed: ['失败', 'danger'],
  cancelled: ['已取消', 'neutral'],
}

const STAGE_LABELS = {
  queued: '等待任务开始',
  resummarize_queued: '等待重新生成摘要',
  claimed: '任务已接收',
  validating_url: '检查视频链接',
  downloading: '下载视频',
  loading_upload: '读取本地文件',
  downloaded: '视频下载完成',
  extracting_audio: '提取音频',
  transcribing: '语音识别',
  segmenting: '整理文字稿',
  saving_transcript: '保存文字稿',
  loading_transcript: '读取已有文字稿',
  summarizing: '生成 AI 摘要',
  synthesizing_summary: '合并长视频摘要',
  resummarizing: '重新生成 AI 摘要',
  resynthesizing_summary: '合并新摘要',
  reexporting: '更新结果文件',
  summary_skipped_no_api_key: '未配置 AI，跳过摘要',
  summary_disabled: '已关闭 AI 摘要',
  exporting: '生成导出文件',
  completed: '处理完成',
  failed: '处理失败',
  cancel_requested: '正在安全停止任务',
  cancelled: '任务已取消',
}

const PLATFORM_LABELS = {
  bilibili: 'B站',
  douyin: '抖音',
  youtube: 'YouTube',
  generic: '在线视频',
  local: '本地文件',
}

const ERROR_HELP = {
  unsafe_url: '请确认链接是正常的公网 HTTP/HTTPS 视频地址。',
  unsupported_url: '可以尝试使用视频详情页地址，避免分享页、直播页或播放列表。',
  login_required: '如该视频需要登录，请在服务器配置 yt-dlp Cookie 文件后重试。',
  source_forbidden: '视频站点拒绝了当前请求。请确认链接公开可访问；需要登录时配置 Cookie，也可尝试更新 yt-dlp。',
  video_too_long: '可以截取需要的片段，或由管理员调整最大视频时长。',
  video_too_large: '可以降低视频清晰度或调整服务器下载大小限制。',
  disk_full: '删除不再需要的历史任务，释放服务器存储空间。',
  media_tool_missing: '管理员需要检查 Docker 镜像或服务器中的 FFmpeg。',
  no_speech: '请确认视频中存在清晰的人声或语音内容。',
  asr_memory: '建议使用“均衡”或“快速”识别档位后重新执行。',
  llm_rate_limit: '稍后重新生成摘要即可，不需要重新下载和转写。',
  llm_empty_response: 'AI 服务已收到请求但没有返回可用摘要。可稍后仅重新生成摘要，文字稿不会丢失。',
  llm_auth: '前往“设置 → AI 模型”检查 API Key、模型和服务地址。',
  llm_quota: '请检查 AI 服务商账户余额或额度。',
  network_timeout: '检查服务器网络后重试；已完成的步骤可继续复用。',
  network_error: '检查服务器 DNS、代理与公网访问能力。',
  queue_error: '请检查 Worker 和 Redis 是否正常运行。',
  source_missing: '本地源文件已不存在；已完成任务仍可以直接重新生成摘要。',
  unsupported_media: '请确认文件可以正常播放，或转换为 MP4 / MP3 / WAV 后重试。',
  processing_error: '可以先重试；如持续失败，请在服务器查看 Worker 日志。',
}

const ERROR_TITLES = {
  login_required: '视频需要登录', source_forbidden: '视频暂时无法下载',
  unsupported_url: '暂不支持这个链接', unsafe_url: '链接不可用',
  video_too_long: '视频时长超过限制', video_too_large: '视频文件过大',
  disk_full: '服务器存储空间不足', no_speech: '未识别到清晰语音',
  asr_memory: '语音识别内存不足', llm_rate_limit: 'AI 服务请求过于频繁',
  llm_empty_response: 'AI 服务未返回摘要内容',
  llm_auth: 'AI 模型配置有误', llm_quota: 'AI 服务额度不足',
  network_timeout: '处理请求超时', network_error: '服务器网络异常',
}

function taskIdFromPath() {
  const matched = window.location.pathname.match(/^\/tasks\/([^/]+)\/?$/)
  return matched ? decodeURIComponent(matched[1]) : null
}

function formatDuration(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n) || n <= 0) return '未知时长'
  const h = Math.floor(n / 3600)
  const m = Math.floor((n % 3600) / 60)
  const s = Math.floor(n % 60)
  if (h) return `${h}小时${m}分${s}秒`
  if (m) return `${m}分${s}秒`
  return `${s}秒`
}

function formatTimestamp(seconds) {
  const n = Math.max(0, Number(seconds) || 0)
  const h = Math.floor(n / 3600)
  const m = Math.floor((n % 3600) / 60)
  const s = Math.floor(n % 60)
  return h ? `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** exponent)).toFixed(exponent < 2 ? 0 : 1)} ${units[exponent]}`
}

function platformLabel(value) {
  return PLATFORM_LABELS[value] || value || '待识别'
}

function statusInfo(value) {
  return STATUS[value] || [value || '未知', 'neutral']
}

function Logo() {
  return <div className="brand-mark" aria-hidden="true">VA</div>
}

function Login({ onLogin }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api.login(username, password)
      setToken(result.access_token)
      onLogin()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-shell">
      <div className="login-side">
        <div className="brand-lockup"><Logo /><div><strong>视频 AI 工作台</strong><span>Video AI Studio</span></div></div>
        <div className="login-copy">
          <span className="kicker">视频内容解析</span>
          <h1>把视频变成可搜索、可阅读、可复用的知识。</h1>
          <p>输入视频链接或上传本地媒体，自动完成语音识别、时间轴整理和 AI 总结。</p>
          <div className="feature-list"><span>✓ 本地语音识别</span><span>✓ AI Key 加密保存</span><span>✓ Markdown / TXT / SRT / JSON</span></div>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="mobile-login-brand"><Logo /><strong>视频 AI 工作台</strong></div>
        <h2>登录</h2>
        <p>使用管理员账号进入工作台。</p>
        <label>用户名<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label>密码<input autoComplete="current-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="请输入密码" /></label>
        {error && <Alert type="error">{error}</Alert>}
        <button className="primary large" disabled={busy || !password}>{busy ? '正在登录…' : '登录工作台'}</button>
      </form>
    </main>
  )
}

function Alert({ type = 'info', title, children, actions }) {
  return <div className={`alert ${type}`}><div className="alert-body">{title && <strong>{title}</strong>}<div>{children}</div></div>{actions && <div className="alert-actions">{actions}</div>}</div>
}

function ThemeButton({ theme, onToggle }) {
  return <button className="icon-button" onClick={onToggle} title="切换明暗主题" aria-label="切换明暗主题">{theme === 'dark' ? '☀' : '☾'}</button>
}

function VideoPreview({ preview }) {
  return (
    <div className="video-preview">
      <div className="preview-thumb">
        {preview.thumbnail ? <img src={preview.thumbnail} alt="视频封面" referrerPolicy="no-referrer" /> : <div className="thumb-placeholder">▶</div>}
      </div>
      <div className="preview-info">
        <div className="preview-badges"><span>{platformLabel(preview.platform)}</span><span>{formatDuration(preview.duration)}</span><span className="valid-badge">✓ 链接有效</span></div>
        <h3>{preview.title}</h3>
        <p>{preview.uploader ? `作者 / 发布者：${preview.uploader}` : '已获取视频基本信息'}</p>
      </div>
    </div>
  )
}

function estimateProcessing(preview, model, summaryEnabled) {
  const seconds = Number(preview?.duration || 0)
  if (!seconds) return '识别视频后显示预估时间'
  const factor = { tiny: 0.10, base: 0.16, small: 0.27, medium: 0.48, 'large-v3': 0.80 }[model] || 0.27
  const minutes = Math.max(2, Math.round(seconds / 60 * factor + (summaryEnabled ? 2 : 0)))
  return `约 ${minutes}–${Math.ceil(minutes * 1.7)} 分钟`
}

function MissingKeyDialog({ onTranscriptOnly, onGoSettings, onCancel }) {
  return <div className="modal-backdrop" role="presentation"><section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="missing-key-title"><h2 id="missing-key-title">尚未配置 AI 模型</h2><p>当前仍可以生成文字稿和字幕，但无法生成 AI 摘要。</p><div className="dialog-actions"><button className="secondary" onClick={onCancel}>取消</button><button className="secondary" onClick={onTranscriptOnly}>仅进行语音转写</button><button className="primary" onClick={onGoSettings}>去配置 AI 模型</button></div></section></div>
}

function NewJob({ jobs, llmConfigured, defaults, onCreated, onGoSettings, onOpenJob, onOpenHistory }) {
  const [sourceMode, setSourceMode] = useState('url')
  const [url, setUrl] = useState('')
  const [localFile, setLocalFile] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [preview, setPreview] = useState(null)
  const [previewedUrl, setPreviewedUrl] = useState('')
  const [previewBusy, setPreviewBusy] = useState(false)
  const [profile, setProfile] = useState(defaults?.asr_model === 'base' ? 'quick' : defaults?.asr_model === 'medium' || defaults?.asr_model === 'large-v3' ? 'accurate' : 'balanced')
  const [model, setModel] = useState(defaults?.asr_model || 'small')
  const [language, setLanguage] = useState(defaults?.language || '')
  const [summaryEnabled, setSummaryEnabled] = useState(defaults?.summary_enabled ?? true)
  const [summaryPreset, setSummaryPreset] = useState(defaults?.summary_preset || 'standard')
  const [summaryInstruction, setSummaryInstruction] = useState('')
  const [summaryDepth, setSummaryDepth] = useState(defaults?.summary_depth || 'standard')
  const [showExtra, setShowExtra] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showMissingKey, setShowMissingKey] = useState(false)
  const [defaultsApplied, setDefaultsApplied] = useState(false)

  useEffect(() => {
    if (!defaults || defaultsApplied) return
    setModel(defaults.asr_model || 'small')
    setProfile(defaults.asr_model === 'base' ? 'quick' : ['medium', 'large-v3'].includes(defaults.asr_model) ? 'accurate' : 'balanced')
    setLanguage(defaults.language || '')
    setSummaryEnabled(defaults.summary_enabled ?? true)
    setSummaryPreset(defaults.summary_preset || 'standard')
    setSummaryDepth(defaults.summary_depth || 'standard')
    setDefaultsApplied(true)
  }, [defaults, defaultsApplied])

  const validUrl = useMemo(() => {
    try {
      const parsed = new URL(url)
      return ['http:', 'https:'].includes(parsed.protocol)
    } catch {
      return false
    }
  }, [url])
  const validSource = sourceMode === 'url' ? validUrl : Boolean(localFile)
  const sourceReady = sourceMode === 'url' ? validUrl && previewedUrl === url.trim() : Boolean(localFile)

  useEffect(() => {
    if (sourceMode !== 'url' || !validUrl || previewedUrl === url.trim()) return undefined
    const timer = window.setTimeout(() => { previewUrl() }, 500)
    return () => window.clearTimeout(timer)
  }, [url, validUrl, sourceMode]) // previewUrl only reads current state

  function setProfileValue(value) {
    setProfile(value)
    setModel(ASR_PROFILES[value].model)
  }

  async function previewUrl() {
    if (!validUrl) {
      setError('请输入有效的 http:// 或 https:// 视频链接')
      return
    }
    setPreviewBusy(true)
    setError('')
    setPreview(null)
    try {
      const result = await api.previewVideo(url.trim())
      setPreview(result)
      setPreviewedUrl(url.trim())
    } catch (err) {
      setError(err.message)
    } finally {
      setPreviewBusy(false)
    }
  }

  async function pasteUrl() {
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        setUrl(text.trim())
        setPreview(null)
        setPreviewedUrl('')
        setError('')
      }
    } catch {
      setError('浏览器未允许读取剪贴板，请手动粘贴链接')
    }
  }

  async function submit(event, transcriptOnly = false) {
    event?.preventDefault()
    setError('')
    if (!validSource) {
      setError(sourceMode === 'url' ? '请先输入有效的视频链接' : '请先选择要处理的视频或音频文件')
      return
    }
    if (sourceMode === 'url' && previewedUrl !== url.trim()) {
      setError('请先点击“识别视频”并确认视频信息，再开始解析。')
      return
    }
    const needsLLM = summaryEnabled && summaryPreset !== 'transcript' && !transcriptOnly
    if (needsLLM && !llmConfigured) { setShowMissingKey(true); return }
    if (summaryPreset === 'custom' && !summaryInstruction.trim()) {
      setError('选择“自定义”摘要后，请填写具体的整理要求')
      return
    }
    setBusy(true)
    try {
      let job
      if (sourceMode === 'url') {
        job = await api.createJob({
          source_url: url.trim(),
          language: language === 'other' ? null : language || null,
          asr_model: model,
          summary_enabled: needsLLM,
          summary_language: 'Chinese',
          summary_preset: summaryPreset,
          summary_instruction: `${summaryInstruction.trim()}${summaryInstruction.trim() ? '\n' : ''}输出深度：${summaryDepth === 'brief' ? '简洁，约500字' : summaryDepth === 'detailed' ? '详细，尽可能完整保留细节' : '标准，约1500字'}`,
        })
        setUrl('')
        setPreview(null)
        setPreviewedUrl('')
      } else {
        const formData = new FormData()
        formData.append('file', localFile)
        formData.append('language', language === 'other' ? '' : language)
        formData.append('asr_model', model)
        formData.append('summary_enabled', String(needsLLM))
        formData.append('summary_language', 'Chinese')
        formData.append('summary_preset', summaryPreset)
        formData.append('summary_instruction', `${summaryInstruction.trim()}${summaryInstruction.trim() ? '\n' : ''}输出深度：${summaryDepth === 'brief' ? '简洁，约500字' : summaryDepth === 'detailed' ? '详细，尽可能完整保留细节' : '标准，约1500字'}`)
        setUploadProgress(0)
        job = await api.uploadJob(formData, setUploadProgress)
        setLocalFile(null)
        setUploadProgress(0)
      }
      await onCreated()
      onOpenJob(job.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="workspace-page">
      <header className="page-header">
        <div><span className="kicker">视频 AI 工作台</span><h1>视频解析</h1><p>粘贴 B站、抖音、YouTube 等视频链接，自动生成文字稿、字幕和 AI 摘要。</p></div>
      </header>

      <section className="card create-card">
        <form onSubmit={submit}>
          <aside className="analysis-summary" aria-label="本次解析">
            <span className="kicker">本次解析</span><h3>{preview?.title || (sourceMode === 'file' ? localFile?.name || '等待选择文件' : '等待识别视频')}</h3>
            <dl><div><dt>识别</dt><dd>{ASR_PROFILES[profile]?.label || model}</dd></div><div><dt>语言</dt><dd>{language ? ({ zh: '中文', en: '英文', ja: '日语', ko: '韩语', other: '其他' }[language] || language) : '自动识别'}</dd></div><div><dt>AI</dt><dd>{summaryEnabled && summaryPreset !== 'transcript' ? SUMMARY_PRESETS[summaryPreset].label : '仅整理原文'}</dd></div><div><dt>预计处理</dt><dd>{estimateProcessing(preview, model, summaryEnabled)}</dd></div></dl>
            <button type="button" className="primary large" disabled={busy || !sourceReady} onClick={() => submit()}>{busy ? '正在创建任务…' : sourceMode === 'url' && validSource && !sourceReady ? '正在识别视频…' : '开始解析'}</button>
            <small>可在高级设置中调整语言和模型。</small>
          </aside>
          <div className="source-tabs"><button type="button" className={sourceMode === 'url' ? 'active' : ''} onClick={() => { setSourceMode('url'); setError('') }}>在线视频</button><button type="button" className={sourceMode === 'file' ? 'active' : ''} onClick={() => { setSourceMode('file'); setError('') }}>本地文件</button></div>
          {sourceMode === 'url' ? <>
            <div className="field-block">
              <label htmlFor="video-url">视频链接</label>
              <div className="url-row">
                <input id="video-url" className="url-input" type="url" placeholder="粘贴 B站、抖音、YouTube 等视频链接" value={url} onChange={(e) => { setUrl(e.target.value); setPreview(null); setPreviewedUrl(''); setError('') }} />
                <button type="button" className="secondary" onClick={pasteUrl}>粘贴</button>
                <button type="button" className="secondary" disabled={!validUrl || previewBusy} onClick={previewUrl}>{previewBusy ? '识别中…' : preview ? '重新检测' : '识别视频'}</button>
              </div>
              <div className="field-hint">支持 B站、抖音、YouTube 以及 yt-dlp 可解析的公开视频。需要登录的视频可在服务器侧配置 Cookie。</div>
            </div>
            {preview && <VideoPreview preview={preview} />}
          </> : <div className="field-block">
            <label>本地视频或音频</label>
            <label className={`upload-zone ${localFile ? 'has-file' : ''}`}>
              <input type="file" accept="video/*,audio/*,.mkv,.m4a,.flac,.opus" onChange={(e) => { setLocalFile(e.target.files?.[0] || null); setError('') }} />
              <span className="upload-icon">⇧</span>
              <strong>{localFile ? localFile.name : '点击选择文件'}</strong>
              <small>{localFile ? `${(localFile.size / 1024 / 1024).toFixed(1)} MB · 点击可重新选择` : '支持 MP4、MOV、MKV、WEBM、MP3、WAV、M4A、FLAC 等常见格式'}</small>
            </label>
            <div className="field-hint">本地文件上传到你的服务器处理；处理成功后默认会清理原始媒体，只保留文字稿和结果文件。</div>
          </div>}

          <div className="section-divider" />
          <div className="form-section-head"><div><h3>处理方式</h3><p>推荐保持默认设置，只有特殊视频才需要调整。</p></div></div>
          <div className="profile-grid">
            {Object.entries(ASR_PROFILES).map(([key, item]) => <button type="button" key={key} className={`choice-card ${profile === key ? 'selected' : ''}`} onClick={() => setProfileValue(key)}><span className="choice-radio" /><strong>{item.label}</strong><small>{item.desc}</small></button>)}
          </div>

          <div className="setting-row">
            <div><strong>生成 AI 摘要</strong><span>基于完整文字稿生成结构化中文总结</span></div>
            <label className="switch"><input type="checkbox" checked={summaryEnabled} onChange={(e) => setSummaryEnabled(e.target.checked)} /><span /></label>
          </div>

          {summaryEnabled && <div className="summary-options">
            {!llmConfigured && summaryPreset !== 'transcript' && <Alert type="warning" title="尚未配置 AI 模型" actions={<button type="button" className="link-button" onClick={onGoSettings}>去配置</button>}>可改选“仅整理原文”，或在开始解析时选择仅进行语音转写。</Alert>}
            <div className="two-cols">
              <label>总结模板<select value={summaryPreset} onChange={(e) => { setSummaryPreset(e.target.value); if (e.target.value === 'custom') setShowExtra(true) }}>{Object.entries(SUMMARY_PRESETS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}</select><small>{SUMMARY_PRESETS[summaryPreset].desc}</small></label>
              <label>摘要长度<select value={summaryDepth} onChange={(e) => setSummaryDepth(e.target.value)}><option value="brief">简洁（约 500 字）</option><option value="standard">标准（约 1500 字）</option><option value="detailed">详细（尽可能完整）</option></select><small>控制摘要篇幅与信息密度。</small></label>
            </div>
            {(showExtra || summaryPreset === 'custom') ? <label className="extra-instruction">额外要求<input value={summaryInstruction} onChange={(e) => setSummaryInstruction(e.target.value)} placeholder="例如：重点整理面试问题、技术观点和时间点" /></label> : <button type="button" className="add-extra" onClick={() => setShowExtra(true)}>+ 添加额外要求</button>}
          </div>}

          <button type="button" className="advanced-toggle" onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级设置' : '高级设置'} <span>{advanced ? '⌃' : '⌄'}</span></button>
          {advanced && <div className="advanced-panel two-cols">
            <label>视频语言<select value={language} onChange={(e) => setLanguage(e.target.value)}><option value="">自动识别（推荐）</option><option value="zh">中文</option><option value="en">英文</option><option value="ja">日语</option><option value="ko">韩语</option><option value="other">其他</option></select></label>
            <label>Whisper 模型<select value={model} onChange={(e) => { setModel(e.target.value); setProfile('custom') }}><option value="tiny">tiny</option><option value="base">base</option><option value="small">small</option><option value="medium">medium</option><option value="large-v3">large-v3</option></select><small>模型越大通常越准确，但需要更多时间和内存。</small></label>
          </div>}

          <div className="output-strip"><span>将自动生成</span><b>完整文字稿</b><b>SRT 字幕</b><b>JSON 数据</b>{summaryEnabled && summaryPreset !== 'transcript' && <b>AI 摘要</b>}</div>
          {error && <Alert type="error">{error}</Alert>}
          <div className="create-actions"><button className="primary large" disabled={busy || !sourceReady}>{busy ? (sourceMode === 'file' && uploadProgress ? `正在上传 ${uploadProgress}%` : '正在创建任务…') : sourceMode === 'url' && validSource && !sourceReady ? '正在识别视频…' : '开始解析'}</button><span>{sourceMode === 'url' && validSource && !sourceReady ? '正在自动获取视频信息。' : '提交后可离开页面，后台会继续处理。'}</span></div>
        </form>
      </section>
      <section className="recent-section"><div className="section-heading"><div><h2>最近任务</h2><p>查看最近的视频解析进度和结果。</p></div><button className="link-button" onClick={onOpenHistory}>查看全部</button></div><div className="card history-card"><div className="jobs-list">{jobs.slice(0, 5).length ? jobs.slice(0, 5).map((job) => <JobRow key={job.id} job={job} onOpen={onOpenJob} />) : <EmptyState title="还没有任务" text="识别一个视频后，任务记录会显示在这里。" />}</div></div></section>
      {showMissingKey && <MissingKeyDialog onCancel={() => setShowMissingKey(false)} onGoSettings={() => { setShowMissingKey(false); onGoSettings() }} onTranscriptOnly={() => { setShowMissingKey(false); submit(null, true) }} />}
    </div>
  )
}

function JobStatus({ job }) {
  const [label, tone] = statusInfo(job.status)
  return <span className={`status-pill ${tone}`}><i />{label}</span>
}

function JobRow({ job, onOpen }) {
  const meta = job.metadata || {}
  return (
    <button className="job-row" onClick={() => onOpen(job.id)}>
      <div className="job-main"><div className="job-icon">{job.status === 'completed' ? '✓' : job.status === 'failed' ? '!' : job.status === 'cancelled' ? '×' : '▶'}</div><div><strong>{job.title || '正在获取视频信息…'}</strong><span>{platformLabel(job.platform)} · {meta.transcript_duration || meta.duration ? formatDuration(meta.transcript_duration || meta.duration) : STAGE_LABELS[job.stage] || '等待处理'}</span></div></div>
      <JobStatus job={job} />
      <div className="job-progress-cell"><div className="mini-progress"><i style={{ width: `${job.progress}%` }} /></div><span>{job.status === 'processing' ? `${job.progress}% · ${STAGE_LABELS[job.stage] || job.stage}` : job.status === 'completed' ? '100%' : job.status === 'failed' ? '需要处理' : `${job.progress}%`}</span></div>
      <time>{formatDate(job.created_at)}</time>
      <span className="row-arrow">›</span>
    </button>
  )
}

function JobHistory({ jobs, onOpen, onRefresh }) {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [platform, setPlatform] = useState('all')
  const [sort, setSort] = useState('newest')
  const filtered = useMemo(() => jobs.filter((job) => {
    const statusOk = filter === 'all' || (filter === 'processing' ? ['queued', 'processing', 'cancel_requested'].includes(job.status) : job.status === filter)
    const q = query.trim().toLowerCase()
    const queryOk = !q || (job.title || '').toLowerCase().includes(q) || job.source_url.toLowerCase().includes(q)
    return statusOk && queryOk && (platform === 'all' || job.platform === platform)
  }).sort((a, b) => sort === 'oldest' ? new Date(a.created_at) - new Date(b.created_at) : new Date(b.created_at) - new Date(a.created_at)), [jobs, filter, query, platform, sort])

  const counts = useMemo(() => ({
    all: jobs.length,
    processing: jobs.filter((j) => ['queued', 'processing', 'cancel_requested'].includes(j.status)).length,
    completed: jobs.filter((j) => j.status === 'completed').length,
    failed: jobs.filter((j) => j.status === 'failed').length,
    cancelled: jobs.filter((j) => j.status === 'cancelled').length,
  }), [jobs])

  return <div className="workspace-page">
    <header className="page-header row"><div><span className="kicker">任务记录</span><h1>所有解析任务</h1><p>查看处理进度、结果文件和失败原因。</p></div><button className="secondary" onClick={onRefresh}>刷新</button></header>
    <section className="card history-card">
      <div className="history-toolbar">
        <div className="filter-tabs">{[['all', '全部'], ['processing', '处理中'], ['completed', '已完成'], ['failed', '失败'], ['cancelled', '已取消']].map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}<span>{counts[key]}</span></button>)}</div>
        <div className="history-controls"><input className="search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索视频标题或链接" /><select value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="all">全部平台</option>{Object.entries(PLATFORM_LABELS).filter(([key]) => key !== 'generic').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select value={sort} onChange={(e) => setSort(e.target.value)}><option value="newest">最新创建</option><option value="oldest">最早创建</option></select></div>
      </div>
      <div className="jobs-head"><span>视频</span><span>状态</span><span>进度</span><span>创建时间</span><span /></div>
      <div className="jobs-list">{filtered.length ? filtered.map((job) => <JobRow key={job.id} job={job} onOpen={onOpen} />) : <EmptyState title="没有符合条件的任务" text={jobs.length ? '尝试切换筛选条件或清空搜索词。' : '创建第一个视频解析任务后，会显示在这里。'} />}</div>
    </section>
  </div>
}

function EmptyState({ title, text }) {
  return <div className="empty-state"><div className="empty-icon">⌁</div><strong>{title}</strong><p>{text}</p></div>
}

function JobSteps({ job }) {
  const isLocal = job.source_type === 'upload'
  const isResummarize = ['resummarize_queued', 'loading_transcript', 'resummarizing', 'resynthesizing_summary', 'reexporting'].includes(job.stage)
  const steps = isResummarize ? [
    ['读取文字稿', 78], ['生成 AI 摘要', 82], ['整理摘要', 92], ['更新文件', 97], ['完成', 100],
  ] : isLocal ? [
    ['读取文件', 6], ['提取音频', 34], ['语音识别', 44], ['整理文字稿', 76], ['AI 摘要', 80], ['生成文件', 97], ['完成', 100],
  ] : [
    ['检查链接', 2], ['下载视频', 8], ['提取音频', 34], ['语音识别', 44], ['整理文字稿', 76], ['AI 摘要', 80], ['生成文件', 97], ['完成', 100],
  ]
  return <div className="steps">{steps.map(([label, threshold], index) => {
    const done = job.progress >= (steps[index + 1]?.[1] || 101) || job.status === 'completed'
    const current = !done && job.progress >= threshold && !['failed', 'cancelled', 'cancel_requested'].includes(job.status)
    return <div className={`step ${done ? 'done' : ''} ${current ? 'current' : ''}`} key={label}><span>{done ? '✓' : index + 1}</span><div><strong>{label}</strong>{current && <small>{STAGE_LABELS[job.stage] || '处理中'} · {job.progress}%</small>}</div></div>
  })}</div>
}

function ResultView({ job, result, onResummarize, onDownload, onResultSaved }) {
  const [tab, setTab] = useState('summary')
  const [query, setQuery] = useState('')
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draftSegments, setDraftSegments] = useState([])
  const [savingTranscript, setSavingTranscript] = useState(false)
  const [editError, setEditError] = useState('')
  const segments = result?.transcript?.segments || []
  const filteredSegments = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return segments
    return segments.filter((item) => String(item.text || '').toLowerCase().includes(q))
  }, [segments, query])

  async function copySummary() {
    if (!result?.summary) return
    await navigator.clipboard.writeText(result.summary)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  async function downloadAll() {
    if (job.artifacts?.zip) return onDownload('zip')
    for (const name of ['markdown', 'txt', 'srt', 'vtt', 'json', 'docx']) if (job.artifacts?.[name]) await onDownload(name)
  }
  function startEditing() { setDraftSegments(segments.map((item) => ({ start: item.start, end: item.end, text: item.text }))); setEditError(''); setEditing(true) }
  async function saveTranscript() {
    setSavingTranscript(true); setEditError('')
    try { const saved = await api.updateTranscript(job.id, draftSegments); onResultSaved(saved); setEditing(false) } catch (err) { setEditError(err.message) } finally { setSavingTranscript(false) }
  }

  return <div className="result-panel">
    <div className="result-tabs"><button className={tab === 'summary' ? 'active' : ''} onClick={() => setTab('summary')}>AI 摘要</button><button className={tab === 'transcript' ? 'active' : ''} onClick={() => setTab('transcript')}>完整文字稿</button><button className={tab === 'subtitles' ? 'active' : ''} onClick={() => setTab('subtitles')}>字幕</button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>下载文件</button><button className={tab === 'info' ? 'active' : ''} onClick={() => setTab('info')}>视频信息</button></div>
    {tab === 'summary' && <div className="result-body"><div className="result-actions"><button className="secondary" onClick={copySummary} disabled={!result?.summary}>{copied ? '已复制' : '复制摘要'}</button><button className="secondary ai-action" onClick={onResummarize}>✦ 重新生成摘要</button><button className="secondary" onClick={() => onDownload('markdown')}>下载 Markdown</button><button className="secondary" onClick={downloadAll}>全部下载</button></div>{result?.summary ? <MarkdownSummary text={result.summary} /> : <EmptyState title="没有 AI 摘要" text="该任务可能关闭了 AI 摘要，或当时尚未配置 API Key。你可以直接重新生成摘要。" />}</div>}
    {['transcript', 'subtitles'].includes(tab) && <div className="result-body"><div className="transcript-toolbar">{tab === 'transcript' ? <><input className="search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索文字稿内容" disabled={editing} /><span>{query ? `找到 ${filteredSegments.length} 段` : `共 ${segments.length} 段`}</span>{!editing ? <button className="secondary" onClick={startEditing}>编辑文字稿</button> : <><button className="secondary" onClick={() => setEditing(false)} disabled={savingTranscript}>取消</button><button className="primary" onClick={saveTranscript} disabled={savingTranscript}>{savingTranscript ? '正在保存…' : '保存并更新文件'}</button></>}</> : <><span>带时间轴的字幕内容，可下载为 SRT 或 VTT 使用。</span><button className="secondary" onClick={() => onDownload('srt')}>下载 SRT 字幕</button></>}</div>{editError && <Alert type="error">{editError}</Alert>}{editing && <Alert type="warning" title="保存后将更新文字稿、字幕和导出文件">已有 AI 摘要会标记为过期；可直接从修正后的文字稿重新生成摘要。</Alert>}<div className="transcript-list">{(tab === 'transcript' ? (editing ? draftSegments : filteredSegments) : segments).map((item, index) => <div className="transcript-line" key={`${item.start}-${index}`}><button className="timestamp-button" title="复制时间点" onClick={() => navigator.clipboard?.writeText(formatTimestamp(item.start))}>{formatTimestamp(item.start)}</button>{editing ? <textarea value={item.text} rows="2" onChange={(event) => setDraftSegments((old) => old.map((segment, position) => position === index ? { ...segment, text: event.target.value } : segment))} /> : <p>{item.text}</p>}</div>)}</div></div>}
    {tab === 'files' && <div className="result-body"><div className="result-actions"><button className="secondary" onClick={downloadAll}>下载全部 ZIP</button></div><div className="file-grid">{[['markdown', 'Markdown', '适合阅读、归档和知识库'], ['txt', 'TXT', '纯文字稿，兼容性最好'], ['srt', 'SRT 字幕', '可直接导入剪辑和播放器'], ['vtt', 'VTT 字幕', '适合网页播放器'], ['docx', 'Word 文档', '便于继续编辑和交付'], ['json', 'JSON', '包含时间轴和结构化数据']].map(([key, name, desc]) => <button key={key} className="file-card" disabled={!job.artifacts?.[key]} onClick={() => onDownload(key)}><span className="file-type">{name}</span><strong>下载 {name}</strong><small>{desc}</small></button>)}</div></div>}
    {tab === 'info' && <div className="result-body"><dl className="info-grid"><div><dt>平台</dt><dd>{platformLabel(job.platform)}</dd></div><div><dt>视频时长</dt><dd>{formatDuration(result?.transcript?.duration || job.metadata?.duration)}</dd></div><div><dt>识别语言</dt><dd>{result?.transcript?.language || job.language || '自动识别'}</dd></div><div><dt>识别模型</dt><dd>{job.asr_model || '默认'}</dd></div><div><dt>摘要类型</dt><dd>{SUMMARY_PRESETS[job.summary_preset]?.label || '标准总结'}</dd></div><div><dt>创建时间</dt><dd>{formatDate(job.created_at)}</dd></div></dl>{job.source_type === 'url' ? <a className="source-link" href={job.source_url} target="_blank" rel="noreferrer">打开原视频 ↗</a> : <div className="local-source-note">本地文件：{job.source_filename || '已上传文件'}（处理完成后默认清理原始媒体）</div>}</div>}
  </div>
}

function renderInlineMarkdown(text) {
  const parts = String(text || '').split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>
    return <span key={`${part}-${index}`}>{part}</span>
  })
}

function MarkdownSummary({ text }) {
  const lines = String(text || '').replace(/\r/g, '').split('\n')
  return <div className="summary-content markdown-summary">{lines.map((raw, index) => {
    const line = raw.trim()
    if (!line) return <div className="md-space" key={`space-${index}`} />
    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      const Level = heading[1].length <= 2 ? 'h3' : 'h4'
      return <Level key={`h-${index}`}>{renderInlineMarkdown(heading[2])}</Level>
    }
    const bullet = line.match(/^[-*]\s+(.+)$/)
    if (bullet) return <div className="md-list-item" key={`b-${index}`}><span>•</span><p>{renderInlineMarkdown(bullet[1])}</p></div>
    const ordered = line.match(/^(\d+)[.)]\s+(.+)$/)
    if (ordered) return <div className="md-list-item ordered" key={`o-${index}`}><span>{ordered[1]}.</span><p>{renderInlineMarkdown(ordered[2])}</p></div>
    if (/^---+$/.test(line)) return <hr key={`hr-${index}`} />
    return <p key={`p-${index}`}>{renderInlineMarkdown(line)}</p>
  })}</div>
}

function ResummarizeBox({ job, onCancel, onDone }) {
  const [preset, setPreset] = useState(job.summary_preset || 'standard')
  const [instruction, setInstruction] = useState(job.summary_instruction || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit() {
    if (preset === 'custom' && !instruction.trim()) { setError('请选择具体摘要模板，或填写自定义整理要求'); return }
    setBusy(true); setError('')
    try {
      await api.resummarizeJob(job.id, { summary_language: 'Chinese', summary_preset: preset, summary_instruction: instruction.trim() || null })
      await onDone()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="inline-dialog"><div><strong>重新生成 AI 摘要</strong><p>会直接复用已有文字稿，不会重新下载视频或运行语音识别。</p></div><div className="two-cols"><label>摘要类型<select value={preset} onChange={(e) => setPreset(e.target.value)}>{Object.entries(SUMMARY_PRESETS).filter(([key]) => key !== 'transcript').map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}</select></label><label>额外要求<input value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="可选，例如：重点整理行动项" /></label></div>{error && <Alert type="error">{error}</Alert>}<div className="dialog-actions"><button className="secondary" onClick={onCancel}>取消</button><button className="primary" disabled={busy} onClick={submit}>{busy ? '正在提交…' : '重新生成'}</button></div></div>
}

function JobDetail({ job, llmConfigured, onBack, onRefresh, onDelete }) {
  const [result, setResult] = useState(null)
  const [resultError, setResultError] = useState('')
  const [resummarize, setResummarize] = useState(false)
  const [actionError, setActionError] = useState('')
  const active = ['queued', 'processing', 'cancel_requested'].includes(job.status)

  useEffect(() => {
    let cancelled = false
    const canReadResult = ['completed', 'failed'].includes(job.status) && Boolean(job.artifacts?.json)
    if (!canReadResult) { setResult(null); setResultError(''); return undefined }
    api.getJobResult(job.id).then((data) => { if (!cancelled) { setResult(data); setResultError('') } }).catch((err) => { if (!cancelled) setResultError(err.message) })
    return () => { cancelled = true }
  }, [job.id, job.status, job.completed_at, job.artifacts?.json])

  async function cancel() {
    setActionError('')
    try { await api.cancelJob(job.id); await onRefresh() } catch (err) { setActionError(err.message) }
  }

  async function retry() {
    setActionError('')
    try { await api.retryJob(job.id); await onRefresh() } catch (err) { setActionError(err.message) }
  }

  async function remove() {
    if (!window.confirm('确定删除这个任务及其所有生成文件吗？此操作无法恢复。')) return
    try { await api.deleteJob(job.id); await onDelete() } catch (err) { setActionError(err.message) }
  }

  async function download(name) {
    try { await api.downloadArtifact(job.id, name) } catch (err) { setActionError(err.message) }
  }

  return <div className="workspace-page detail-page">
    <button className="back-button" onClick={onBack}>← 返回任务列表</button>
    <header className="detail-header"><div className="detail-title"><JobStatus job={job} /><h1>{job.title || '正在获取视频信息…'}</h1><p>{platformLabel(job.platform)} · {formatDuration(job.metadata?.transcript_duration || job.metadata?.duration)} · 创建于 {formatDate(job.created_at)}</p></div><div className="detail-actions">{['queued', 'processing'].includes(job.status) && <button className="secondary" onClick={cancel}>取消任务</button>}{job.status === 'cancel_requested' && <button className="secondary" disabled>正在取消…</button>}{['failed', 'cancelled'].includes(job.status) && <button className="secondary" onClick={retry}>重新执行全部流程</button>}{['completed', 'failed', 'cancelled'].includes(job.status) && <button className="danger-button" onClick={remove}>删除任务</button>}</div></header>

    <section className="card progress-card"><div className="progress-head"><div><h2>{job.status === 'completed' ? '解析完成' : job.status === 'failed' ? '任务处理失败' : job.status === 'cancel_requested' ? '正在安全停止任务' : job.status === 'cancelled' ? '任务已取消' : STAGE_LABELS[job.stage] || '正在处理'}</h2><p>{job.status === 'cancel_requested' ? '已收到取消请求。当前 FFmpeg、语音识别或 AI 请求结束后会停止，不再进入下一步。' : active ? `当前进度 ${job.progress}% · 任务会在后台继续运行` : job.status === 'completed' ? '文字稿、摘要和导出文件已经准备好。' : '查看下面的原因和处理建议。'}</p></div><strong className="big-progress">{job.progress}%</strong></div><div className="progress-track large"><i style={{ width: `${job.progress}%` }} /></div><JobSteps job={job} /><details className="task-log"><summary>查看处理说明</summary><p>系统会依次下载或读取媒体、提取音频、识别语音、整理文字稿、生成摘要并导出文件。底层技术日志默认不直接展示，以免干扰使用；持续失败时可由管理员查看 Worker 日志。</p></details></section>

    {job.status === 'failed' && <Alert type="error" title={ERROR_TITLES[job.error_code] || '任务处理失败'}><p>{job.error_message || ERROR_HELP[job.error_code] || ERROR_HELP.processing_error}</p><p>{ERROR_HELP[job.error_code] || ERROR_HELP.processing_error}</p><div className="inline-actions">{job.artifacts?.json && <button className="secondary ai-action" onClick={() => { if (!llmConfigured) setActionError('尚未配置 AI 模型，请先在设置中配置 API Key。'); else setResummarize(true) }}>✦ 仅重新生成摘要</button>}<button className="secondary" onClick={retry}>重新执行全部流程</button></div>{job.artifacts?.json && <p className="checkpoint-note">语音识别结果已保留，重新生成摘要不会重复下载视频或运行 ASR。</p>}<details className="technical-details"><summary>查看技术信息</summary><code>{job.error_code || 'processing_error'}</code></details></Alert>}
    {actionError && <Alert type="error">{actionError}</Alert>}
    {resummarize && <ResummarizeBox job={job} onCancel={() => setResummarize(false)} onDone={async () => { setResummarize(false); await onRefresh() }} />}
    {['completed', 'failed'].includes(job.status) && !resummarize && job.artifacts?.json && <>{resultError && <Alert type="error">{resultError}</Alert>}{result ? <ResultView job={job} result={result} onResummarize={() => { if (!llmConfigured) setActionError('尚未配置 AI 模型，请先在设置中配置 API Key。'); else setResummarize(true) }} onDownload={download} onResultSaved={async (saved) => { setResult(saved); await onRefresh() }} /> : !resultError && <div className="card loading-card">正在读取已保存结果…</div>}</>}
  </div>
}

function ProviderSettings({ value, onSaved }) {
  const inferProvider = (v) => {
    if (v.provider && v.provider !== 'custom') return v.provider
    if ((v.base_url || '').includes('api.deepseek.com')) return 'deepseek'
    if ((v.base_url || '').includes('bigmodel.cn')) return 'zhipu'
    if ((v.base_url || '').includes('api.openai.com')) return 'openai'
    return 'custom'
  }
  const [form, setForm] = useState({ ...value, provider: inferProvider(value) })
  const [apiKey, setApiKey] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => setForm({ ...value, provider: inferProvider(value) }), [value])

  function pickProvider(provider) {
    const preset = PROVIDERS[provider]
    setForm((old) => ({ ...old, provider, base_url: provider === 'custom' ? old.base_url : preset.base_url, model: provider === 'custom' ? old.model : preset.model }))
    setMessage(''); setError('')
  }

  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('')
    try {
      const saved = await api.saveLLM({ provider: form.provider, base_url: form.base_url, model: form.model, api_key: apiKey || null, temperature: Number(form.temperature), custom_prompt: form.custom_prompt || null })
      setApiKey(''); setMessage('设置已保存，API Key 已在服务端加密存储。'); onSaved(saved)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function test() {
    setBusy(true); setError(''); setMessage('')
    try { const result = await api.testLLM(); setMessage(result.message) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function removeKey() {
    if (!window.confirm('确定清除服务器中保存的 AI API Key 吗？')) return
    setBusy(true); setError(''); setMessage('')
    try {
      const saved = await api.saveLLM({ provider: form.provider, base_url: form.base_url, model: form.model, api_key: null, clear_api_key: true, temperature: Number(form.temperature), custom_prompt: form.custom_prompt || null })
      setMessage('已清除保存的 API Key。'); onSaved(saved)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <section className="settings-section"><div className="settings-title"><h2>AI 模型</h2><p>用于视频摘要。API Key 只在保存时提交，之后浏览器不会读取完整密钥。</p></div><form className="settings-content" onSubmit={save}>
    <label className="field-title">AI 服务商</label><div className="provider-grid">{Object.entries(PROVIDERS).map(([key, item]) => <button type="button" key={key} className={`provider-card ${form.provider === key ? 'selected' : ''}`} onClick={() => pickProvider(key)}><span className="choice-radio" /><strong>{item.label}</strong><small>{item.hint}</small></button>)}</div>
    <div className="two-cols"><label>模型名称<input required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="输入服务商支持的模型名称" /></label><label>API Key<div className="secret-input"><input type="password" autoComplete="off" placeholder={form.api_key_configured ? `已配置 ${form.api_key_masked || ''}，留空表示保持不变` : '粘贴 API Key'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />{form.api_key_configured && <span className="secret-ok">已配置</span>}</div></label></div>
    {form.provider === 'custom' && <label>Base URL<input required value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="例如 https://example.com/v1" /><small>填写到 API 根路径，系统会自动拼接 /chat/completions。</small></label>}
    <button type="button" className="advanced-toggle" onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级参数' : '高级参数'} <span>{advanced ? '⌃' : '⌄'}</span></button>
    {advanced && <div className="advanced-panel"><div className="two-cols"><label>Temperature<input type="number" min="0" max="2" step="0.1" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })} /><small>视频总结建议使用 0.1–0.4。</small></label><div /></div><label>全局系统提示词<textarea rows="5" value={form.custom_prompt || ''} onChange={(e) => setForm({ ...form, custom_prompt: e.target.value })} placeholder="可选。通常保持为空，使用系统内置的事实型总结提示词即可。" /></label></div>}
    {message && <Alert type="success">{message}</Alert>}{error && <Alert type="error">{error}</Alert>}
    <div className="button-row"><button className="primary" disabled={busy}>保存设置</button><button type="button" className="secondary" disabled={busy || !form.api_key_configured} onClick={test}>测试连接</button>{form.api_key_configured && <button type="button" className="text-danger" disabled={busy} onClick={removeKey}>清除 Key</button>}</div>
  </form></section>
}

function SystemSettings({ health, onRefresh }) {
  const items = [
    ['API 服务', true, '当前页面可正常连接后端'],
    ['数据库', Boolean(health?.database), health?.database ? '数据库连接正常' : '数据库连接异常'],
    ['FFmpeg', Boolean(health?.ffmpeg), health?.ffmpeg ? '媒体转码组件可用' : '未找到 FFmpeg'],
    ['FFprobe', Boolean(health?.ffprobe), health?.ffprobe ? '媒体探测组件可用' : '未找到 FFprobe'],
    ['yt-dlp', Boolean(health?.ytdlp), health?.ytdlp ? '在线视频解析组件可用' : '未找到 yt-dlp'],
    ['任务队列', Boolean(health?.queue), health?.queue ? 'Worker 队列连接正常' : 'Redis / 任务队列不可用'],
    ['任务存储', Boolean(health?.data_dir_writable), health?.data_dir_writable ? '任务目录可写' : '任务目录不可写'],
  ]
  return <section className="settings-section"><div className="settings-title"><h2>系统状态</h2><p>快速确认视频处理依赖是否工作正常。</p></div><div className="settings-content"><div className="health-list">{items.map(([name, ok, desc]) => <div className="health-item" key={name}><span className={`health-dot ${ok ? 'ok' : 'bad'}`} /><div><strong>{name}</strong><small>{desc}</small></div><b>{ok ? '正常' : '异常'}</b></div>)}</div><div className="system-meta"><span>任务模式：{health?.queue_mode === 'celery' ? 'Celery / Redis' : health?.queue_mode || '-'}</span><button className="secondary" onClick={onRefresh}>刷新状态</button></div></div></section>
}

function DefaultTaskSettings({ value, onSaved }) {
  const fallback = { asr_model: 'small', language: '', summary_enabled: true, summary_preset: 'standard', summary_depth: 'standard' }
  const [form, setForm] = useState(value || fallback)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (value) setForm(value) }, [value])
  async function save(event) { event.preventDefault(); setBusy(true); setMessage(''); try { const saved = await api.saveTaskDefaults(form); onSaved(saved); setMessage('默认设置已保存，新建任务将使用这些选项。') } finally { setBusy(false) } }
  return <section className="settings-section"><div className="settings-title"><h2>默认任务设置</h2><p>减少重复选择；已创建的任务不会受到影响。</p></div><form className="settings-content" onSubmit={save}><div className="two-cols"><label>默认识别方式<select value={form.asr_model} onChange={(e) => setForm({ ...form, asr_model: e.target.value })}><option value="base">快速</option><option value="small">均衡（推荐）</option><option value="medium">高精度</option><option value="large-v3">最高精度</option></select></label><label>默认视频语言<select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}><option value="">自动识别</option><option value="zh">中文</option><option value="en">英文</option><option value="ja">日语</option><option value="ko">韩语</option></select></label></div><div className="two-cols"><label>默认总结模板<select value={form.summary_preset} onChange={(e) => setForm({ ...form, summary_preset: e.target.value })}>{Object.entries(SUMMARY_PRESETS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}</select></label><label>默认摘要长度<select value={form.summary_depth} onChange={(e) => setForm({ ...form, summary_depth: e.target.value })}><option value="brief">简洁</option><option value="standard">标准</option><option value="detailed">详细</option></select></label></div><div className="setting-row"><div><strong>默认生成 AI 摘要</strong><span>关闭时默认只生成文字稿和字幕。</span></div><label className="switch"><input type="checkbox" checked={form.summary_enabled} onChange={(e) => setForm({ ...form, summary_enabled: e.target.checked })} /><span /></label></div>{message && <Alert type="success">{message}</Alert>}<button className="primary" disabled={busy}>{busy ? '正在保存…' : '保存默认设置'}</button></form></section>
}

function StorageSettings({ storage, onRefresh }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function clean() { if (!window.confirm(`确定清理 ${formatBytes(storage?.removable_temporary_bytes)} 可安全删除的历史临时文件吗？不会删除任务结果。`)) return; setBusy(true); setError(''); try { await api.cleanTemporaryStorage(); await onRefresh() } catch (err) { setError(err.message) } finally { setBusy(false) } }
  const items = [['结果与任务目录', storage?.jobs_bytes], ['上传源文件', storage?.uploads_bytes], ['模型缓存', storage?.models_bytes], ['临时处理文件', storage?.temporary_bytes], ['磁盘剩余空间', storage?.disk_free_bytes]]
  return <section className="settings-section"><div className="settings-title"><h2>下载与存储</h2><p>原始媒体与音频中间文件会按服务器策略清理；结果文件可在任务详情下载或删除。</p></div><div className="settings-content"><div className="storage-list">{items.map(([label, bytes]) => <div key={label}><span>{label}</span><strong>{storage ? formatBytes(bytes) : '读取中…'}</strong></div>)}</div>{error && <Alert type="error">{error}</Alert>}<div className="button-row"><button className="secondary" onClick={onRefresh}>刷新统计</button><button className="danger-button" disabled={busy || !storage?.removable_temporary_bytes} onClick={clean}>{busy ? '正在清理…' : `清理临时文件（${formatBytes(storage?.removable_temporary_bytes)}）`}</button></div></div></section>
}

function SecuritySettings() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault(); setError(''); setMessage('')
    if (newPassword !== confirmPassword) { setError('两次输入的新密码不一致'); return }
    setBusy(true)
    try { await api.changePassword({ current_password: currentPassword, new_password: newPassword }); setCurrentPassword(''); setNewPassword(''); setConfirmPassword(''); setMessage('管理员密码修改成功，下次登录请使用新密码。') } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <section className="settings-section"><div className="settings-title"><h2>账号安全</h2><p>首次部署后建议立即修改初始化管理员密码。</p></div><form className="settings-content" onSubmit={submit}><div className="two-cols"><label>当前密码<input type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required /></label><div /></div><div className="two-cols"><label>新密码<input type="password" autoComplete="new-password" minLength="12" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required /><small>至少 12 个字符。</small></label><label>确认新密码<input type="password" autoComplete="new-password" minLength="12" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required /></label></div>{message && <Alert type="success">{message}</Alert>}{error && <Alert type="error">{error}</Alert>}<div className="button-row"><button className="primary" disabled={busy || !currentPassword || !newPassword || !confirmPassword}>修改密码</button></div></form></section>
}

function SettingsPage({ settings, health, defaults, storage, onSaved, onDefaultsSaved, onRefreshHealth, onRefreshStorage }) {
  const [section, setSection] = useState('ai')
  return <div className="workspace-page"><header className="page-header"><div><span className="kicker">设置</span><h1>工作台设置</h1><p>配置 AI 模型、检查系统运行状态和管理账号安全。</p></div></header><div className="settings-layout"><aside className="settings-nav"><button className={section === 'ai' ? 'active' : ''} onClick={() => setSection('ai')}>AI 模型</button><button className={section === 'defaults' ? 'active' : ''} onClick={() => setSection('defaults')}>默认任务</button><button className={section === 'asr' ? 'active' : ''} onClick={() => setSection('asr')}>语音识别</button><button className={section === 'storage' ? 'active' : ''} onClick={() => setSection('storage')}>下载与存储</button><button className={section === 'system' ? 'active' : ''} onClick={() => setSection('system')}>系统状态</button><button className={section === 'security' ? 'active' : ''} onClick={() => setSection('security')}>账号安全</button></aside><div className="settings-main">{section === 'ai' && <ProviderSettings value={settings} onSaved={onSaved} />}{section === 'defaults' && <DefaultTaskSettings value={defaults} onSaved={onDefaultsSaved} />}{section === 'asr' && <SettingsNotice title="语音识别" text="识别精度在每个任务中选择：快速、均衡和高精度分别映射到不同 Whisper 模型。高级模型设置仍保留在创建任务页面，避免影响普通使用。" />}{section === 'storage' && <StorageSettings storage={storage} onRefresh={onRefreshStorage} />}{section === 'system' && <SystemSettings health={health} onRefresh={onRefreshHealth} />}{section === 'security' && <SecuritySettings />}</div></div></div>
}

function SettingsNotice({ title, text }) { return <section className="settings-section"><div className="settings-title"><h2>{title}</h2><p>{text}</p></div></section> }

function HelpPage() {
  return <div className="workspace-page"><header className="page-header"><div><span className="kicker">帮助</span><h1>使用帮助</h1><p>先识别视频确认链接有效，再选择识别精度并开始解析。</p></div></header><section className="card help-card"><h2>处理视频的三个步骤</h2><ol><li>粘贴公开视频链接，点击“识别视频”查看标题、时长和封面。</li><li>选择识别精度；通常保持“均衡（推荐）”即可。</li><li>开始解析。若尚未配置 AI 模型，可只生成文字稿与字幕。</li></ol><p>需要处理登录后才能访问的视频时，请由管理员在服务器配置对应平台的 Cookie。</p></section></div>
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()))
  const [tab, setTab] = useState('parse')
  const [jobs, setJobs] = useState([])
  const [selectedJobId, setSelectedJobId] = useState(() => taskIdFromPath())
  const [settings, setSettings] = useState({ provider: 'deepseek', base_url: 'https://api.deepseek.com', model: 'deepseek-v4-flash', temperature: 0.2, custom_prompt: '', api_key_configured: false, api_key_masked: null })
  const [taskDefaults, setTaskDefaults] = useState(null)
  const [storage, setStorage] = useState(null)
  const [health, setHealth] = useState(null)
  const [globalError, setGlobalError] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('video-ai-theme') || 'light')
  const [username, setUsername] = useState('管理员')

  const hasActiveJobs = useMemo(() => jobs.some((job) => ['queued', 'processing', 'cancel_requested'].includes(job.status)), [jobs])
  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedJobId) || null, [jobs, selectedJobId])

  function applyTheme(next) {
    setTheme(next)
    localStorage.setItem('video-ai-theme', next)
    document.documentElement.dataset.theme = next
  }

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])

  async function refresh() {
    if (!getToken()) return
    try {
      const [jobData, llmData, healthData, userData, defaultsData, storageData] = await Promise.all([api.jobs(), api.getLLM(), api.health(), api.me(), api.getTaskDefaults(), api.getStorage()])
      setJobs(jobData); setSettings(llmData); setHealth(healthData); setUsername(userData.username || '管理员'); setTaskDefaults(defaultsData); setStorage(storageData); setGlobalError('')
    } catch (err) { setGlobalError(err.message) }
  }

  async function refreshHealth() {
    try { setHealth(await api.health()) } catch (err) { setGlobalError(err.message) }
  }
  async function refreshStorage() { try { setStorage(await api.getStorage()) } catch (err) { setGlobalError(err.message) } }

  useEffect(() => {
    function expired() { setAuthenticated(false) }
    window.addEventListener('video-ai-auth-expired', expired)
    return () => window.removeEventListener('video-ai-auth-expired', expired)
  }, [])

  useEffect(() => { if (authenticated) refresh() }, [authenticated])
  useEffect(() => {
    function handlePopState() { setSelectedJobId(taskIdFromPath()); if (taskIdFromPath()) setTab('history') }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])
  useEffect(() => {
    if (!authenticated) return undefined
    const interval = setInterval(() => { if (hasActiveJobs) refresh() }, 2500)
    return () => clearInterval(interval)
  }, [authenticated, hasActiveJobs])

  if (!authenticated) return <Login onLogin={() => { setAuthenticated(true); refresh() }} />

  function navigate(next) { window.history.pushState({}, '', '/'); setSelectedJobId(null); setTab(next) }
  function openJob(id) { window.history.pushState({}, '', `/tasks/${encodeURIComponent(id)}`); setSelectedJobId(id); setTab('history') }
  const systemOk = Boolean(health?.ffmpeg && health?.ffprobe && health?.ytdlp && health?.database && health?.queue && health?.data_dir_writable)

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup sidebar-brand"><Logo /><div><strong>视频 AI 工作台</strong><span>Video AI Studio</span></div></div>
      <nav className="main-nav"><button className={tab === 'parse' && !selectedJobId ? 'active' : ''} onClick={() => navigate('parse')}><span>◉</span>视频解析</button><button className={tab === 'history' ? 'active' : ''} onClick={() => navigate('history')}><span>▤</span>任务记录{hasActiveJobs && <i className="nav-dot" />}</button></nav>
      <div className="nav-divider" />
      <nav className="main-nav"><button className={tab === 'settings' ? 'active' : ''} onClick={() => navigate('settings')}><span>⚙</span>设置</button><button className={tab === 'help' ? 'active' : ''} onClick={() => navigate('help')}><span>?</span>帮助</button></nav>
      <div className="sidebar-bottom"><button className="system-summary" onClick={() => navigate('settings')}><span className={`health-dot ${systemOk ? 'ok' : 'bad'}`} /><div><strong>{systemOk ? '服务正常' : '服务需检查'}</strong><small>点击查看运行状态</small></div></button></div>
    </aside>
    <main className="content-shell">
      <div className="topbar"><div className="mobile-brand">视频 AI 工作台</div><div className="topbar-actions"><span className={`service-chip ${systemOk ? 'ok' : 'warn'}`}><i />{systemOk ? '服务正常' : '服务异常'}</span><details className="user-menu"><summary>{username} ▾</summary><button onClick={() => navigate('settings')}>账号安全</button><button onClick={() => { setToken(null); setAuthenticated(false) }}>退出登录</button></details><ThemeButton theme={theme} onToggle={() => applyTheme(theme === 'dark' ? 'light' : 'dark')} /></div></div>
      <div className="content">{globalError && <Alert type="error">{globalError}</Alert>}{selectedJob ? <JobDetail job={selectedJob} llmConfigured={settings.api_key_configured} onBack={() => navigate('history')} onRefresh={refresh} onDelete={async () => { navigate('history'); await refresh() }} /> : tab === 'parse' ? <NewJob jobs={jobs} llmConfigured={settings.api_key_configured} defaults={taskDefaults} onCreated={refresh} onGoSettings={() => navigate('settings')} onOpenJob={openJob} onOpenHistory={() => navigate('history')} /> : tab === 'history' ? <JobHistory jobs={jobs} onOpen={openJob} onRefresh={refresh} /> : tab === 'help' ? <HelpPage /> : <SettingsPage settings={settings} health={health} defaults={taskDefaults} storage={storage} onSaved={setSettings} onDefaultsSaved={setTaskDefaults} onRefreshHealth={refreshHealth} onRefreshStorage={refreshStorage} />}</div>
    </main>
  </div>
}
