import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { Icon, ErrorNotice } from './ui.jsx';
import { getTemplate, templates } from './templates.js';
import SourcePicker from './SourcePicker.jsx';
import { safeHref } from './Markdown.jsx';
import { mediaCandidates } from './urls.js';
export default function Composer({ onSend, capabilities = {}, action = 'chat', setAction, contextCount = 0, active = false, onStop, disabled = false, workspaceId = null, promptSignal = 0 }) {
    const [text, setText] = useState(''), [mode, setMode] = useState('auto'), [files, setFiles] = useState([]);
    const [selected, setSelected] = useState([]), [picker, setPicker] = useState(false), [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState(''), [error, setError] = useState(''), [preview, setPreview] = useState(null);
    const [previewBusy, setPreviewBusy] = useState(false), [web, setWeb] = useState(false), [visual, setVisual] = useState(false);
    const textarea = useRef(null), upload = useRef(null), uploaded = useRef(new Map()), requestId = useRef(crypto.randomUUID());
    const candidates = useMemo(() => mode === 'general' || /不(?:要|需要)?(?:下载|解析)|别(?:下载|解析)/.test(text) ? [] : mediaCandidates(text), [text, mode]);
    const firstUrl = candidates[0];
    const template = getTemplate(action);
    useEffect(() => {
        if (action !== 'chat')
            setText(current => current.trim() ? current : template.prompt);
        setWeb(action === 'research' && Boolean(capabilities.web));
        setVisual(action === 'visual' && Boolean(capabilities.visual));
        textarea.current?.focus();
    }, [action, promptSignal]);
    useEffect(() => { requestId.current = crypto.randomUUID(); }, [text, action, mode, files, selected, web, visual]);
    useEffect(() => {
        if (!firstUrl) {
            setPreview(null);
            setPreviewBusy(false);
            return;
        }
        let alive = true;
        setPreview(null);
        const timer = setTimeout(async () => {
            setPreviewBusy(true);
            try {
                const value = await api.previewVideo(firstUrl);
                if (alive)
                    setPreview(value);
            }
            catch {
                if (alive)
                    setPreview({ unavailable: true });
            }
            finally {
                if (alive)
                    setPreviewBusy(false);
            }
        }, 650);
        return () => { alive = false; clearTimeout(timer); };
    }, [firstUrl]);
    useEffect(() => {
        if (textarea.current) {
            textarea.current.style.height = 'auto';
            textarea.current.style.height = Math.min(240, Math.max(72, textarea.current.scrollHeight)) + 'px';
        }
    }, [text]);
    function addFiles(incoming) {
        setFiles(old => [...old, ...Array.from(incoming)].slice(0, 8));
        setMode('auto');
        setError('');
    }
    async function send(event) {
        event?.preventDefault();
        if (busy || active || disabled)
            return;
        if (mode === 'general' && (files.length || selected.length)) {
            setError('已选择视频，请切换为自动或视频模式');
            return;
        }
        if (!text.trim() && !files.length && !selected.length)
            return;
        setBusy(true);
        setError('');
        try {
            const jobIds = selected.map(x => x.id);
            for (let i = 0; i < files.length; i++) {
                const file = files[i], key = `${file.name}-${file.size}-${file.lastModified}`;
                let job = uploaded.current.get(key);
                if (!job) {
                    const data = new FormData();
                    data.append('file', file);
                    data.append('summary_enabled', String(Boolean(capabilities.chat)));
                    job = await api.uploadJob(data, p => setProgress(`上传 ${i + 1}/${files.length} · ${p}%`));
                    uploaded.current.set(key, job);
                }
                jobIds.push(job.id);
            }
            setProgress('正在发送…');
            await onSend({ content: text.trim() || template.prompt || '请总结这些视频的内容。',
                action, mode, client_request_id: requestId.current, job_ids: jobIds, urls: candidates,
                allow_web: web, allow_visual: visual });
            setText('');
            setFiles([]);
            setSelected([]);
            uploaded.current.clear();
            requestId.current = crypto.randomUUID();
            setAction?.('chat');
        }
        catch (err) {
            setError(err.message);
        }
        finally {
            setBusy(false);
            setProgress('');
        }
    }
    const hasSource = contextCount + files.length + selected.length + candidates.length > 0;
    const missingVideo = template.video && !hasSource && !(mode === 'workspace' && workspaceId);
    return <div className="va-composer-wrap">
    <ErrorNotice error={error} onClose={() => setError('')}/>
    <form className={`va-composer ${active ? 'is-running' : ''}`} onSubmit={send} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!active && !busy && !disabled)
        addFiles(e.dataTransfer.files); }}>
      {(files.length > 0 || selected.length > 0) && <div className="va-attachments">{files.map((file, i) => <span key={`${file.name}-${i}`}><Icon name="file" size={15}/>{file.name}<button type="button" disabled={busy} onClick={() => setFiles(old => old.filter((_, n) => n !== i))} aria-label={'移除文件'}><Icon name="close" size={13}/></button></span>)}{selected.map(job => <span key={job.id}><Icon name="video" size={15}/>{job.title || job.id}<button type="button" disabled={busy} onClick={() => setSelected(old => old.filter(x => x.id !== job.id))} aria-label={'移除视频'}><Icon name="close" size={13}/></button></span>)}</div>}
      <textarea ref={textarea} value={text} onChange={e => setText(e.target.value)} disabled={busy || disabled} aria-label={'消息输入框'} placeholder={contextCount ? '继续提问，或添加更多视频…' : '问我任何问题，或粘贴 B站、抖音、YouTube 视频链接…'} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        send();
    } }}/>
      {firstUrl && <div className="va-link-preview"><Icon name="link" size={17}/>{preview?.thumbnail && safeHref(preview.thumbnail) && <img src={preview.thumbnail} alt="" referrerPolicy="no-referrer"/>}<span><strong>{preview?.title || (previewBusy ? '正在获取视频信息…' : '已识别视频链接')}</strong><small>{preview?.unavailable ? '暂未获取预览，可发送后尝试解析' : '发送后开始下载与转写'}{candidates.length > 1 ? ` · ${candidates.length} 个链接` : ''}</small></span></div>}
      <div className="va-composer-toolbar"><div className="va-composer-tools">
        <input ref={upload} type="file" hidden multiple accept=".mp4,.mov,.mkv,.webm,.avi,.m4v,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus" onChange={e => { addFiles(e.target.files); e.target.value = ''; }}/>
        <button className="va-tool" type="button" disabled={busy || active || disabled} onClick={() => upload.current.click()} title={'上传视频或音频'}><Icon name="upload" size={18}/><span>{'上传'}</span></button>
        <button className="va-tool" type="button" disabled={busy || active || disabled} onClick={() => setPicker(true)} title={'从视频库添加'}><Icon name="folder" size={18}/><span>{'视频库'}</span></button>
        <select aria-label={'回答范围'} value={mode} onChange={e => setMode(e.target.value)} disabled={busy || active || disabled}>
          <option value="auto">{'自动'}</option><option value="general">{'仅普通聊天'}</option><option value="video">{'仅视频内容'}</option>{workspaceId && <option value="workspace">{'项目视频库'}</option>}
        </select>
        <select aria-label={'任务模板'} value={action} onChange={e => setAction?.(e.target.value)} disabled={busy || active || disabled}>{templates.map(t => <option key={t.id} value={t.id} disabled={Boolean(t.capability && !capabilities[t.capability])}>{t.title}{t.capability && !capabilities[t.capability] ? ' (未配置)' : ''}</option>)}</select>
      </div>
      {active ? <button type="button" className="va-stop" onClick={onStop}><Icon name="stop" size={16}/>{'停止'}</button> : <button className="va-send" type="submit" aria-label={'发送消息'} disabled={busy || disabled || missingVideo || (!text.trim() && !files.length && !selected.length)}><Icon name="send" size={19}/><span>{busy ? '处理中' : '发送'}</span></button>}
      </div>
      {['research', 'agent', 'visual'].includes(action) && <div className="va-tool-permissions"><label><input type="checkbox" checked={web} disabled={!capabilities.web || busy || active} onChange={e => setWeb(e.target.checked)}/>{'允许联网搜索'}</label><label><input type="checkbox" checked={visual} disabled={!capabilities.visual || busy || active} onChange={e => setVisual(e.target.checked)}/>{'允许发送抽样帧'}</label></div>}
    </form>
    <div className="va-composer-foot">{progress || (missingVideo ? '请先添加视频，再使用该模板' : mode === 'general' ? '仅普通聊天：不解析链接，不使用视频上下文' : 'Enter 发送 · Shift + Enter 换行 · AI 可能出错，请核对原文')}
      {web && <span>{'搜索问题将发送至 Tavily；不会发送文字稿。'}</span>}{visual && <span>{'抽样画面将发送至配置的视觉模型。'}</span>}
    </div>
    {picker && <SourcePicker existing={selected.map(x => x.id)} onClose={() => setPicker(false)} onSelect={job => { setSelected(old => [...old, job]); setMode('auto'); setPicker(false); }}/>}
  </div>;
}
