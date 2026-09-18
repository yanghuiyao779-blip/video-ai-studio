import { useEffect, useRef, useState } from 'react';
import { assistantApi, changed } from './api.js';
import { navigate } from './router.js';
import { Icon, Modal, ErrorNotice, Loading, stamp, dateLabel } from './ui.jsx';
import Markdown, { safeHref } from './Markdown.jsx';
import Composer from './Composer.jsx';
import SourcePicker from './SourcePicker.jsx';
import useConversation from './useConversation.js';
import { templates } from './templates.js';
import { JobSteps } from '../legacy/VideoPages.jsx';
const statusLabel = { queued: '排队中', waiting: '等待视频', running: '正在生成', completed: '已完成', failed: '失败', cancelled: '已停止', processing: '处理中', cancel_requested: '正在取消' };
const indexLabel = { vector_ready: '语义检索就绪', ready: '语义检索就绪', lexical_ready: '关键词检索就绪', degraded: '关键词检索可用', indexing: '建立索引中', missing: '按需建立索引', stale: '等待更新', failed: '暂不可用' };
export function SourceModal({ source, onClose }) {
    return <Modal title={`来源 ${source.id || ''}`} onClose={onClose}><h3>{source.title || '视频原文'}</h3>{source.start_seconds != null && <p className="va-muted">{stamp(source.start_seconds)} - {stamp(source.end_seconds)}</p>}<blockquote className="va-source-excerpt">{source.excerpt || '此来源没有可展示的文本片段'}</blockquote>{source.job_id && <button className="va-primary" onClick={() => { onClose(); navigate(`/tasks/${source.job_id}?t=${source.start_seconds || 0}`); }}><Icon name="clock"/>打开对应时间的文字稿</button>}{safeHref(source.url) && <a className="va-secondary" href={source.url} target="_blank" rel="noopener noreferrer">打开原始来源</a>}</Modal>;
}
function MindNode({ node, root = false }) {
    if (!node)
        return null;
    return node.children?.length ? <details className={`va-mind-node ${root ? 'root' : ''}`} open={root || undefined}><summary>{node.title}</summary><div>{node.children.map((n, i) => <MindNode key={i} node={n}/>)}</div></details> : <div className="va-mind-leaf">{node.title}</div>;
}
export function ArtifactModal({ artifact, onClose }) {
    function download() { const blob = new Blob([artifact.content], { type: 'text/markdown;charset=utf-8' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${artifact.kind}-${artifact.id}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    return <Modal title={artifact.title} wide onClose={onClose}><div className="va-actions"><button className="va-secondary" onClick={download}><Icon name="file"/>导出 Markdown</button></div>{artifact.kind === 'mindmap' && artifact.structured ? <MindNode node={artifact.structured} root/> : artifact.kind === 'timeline' && artifact.structured?.chapters ? <div className="va-timeline">{artifact.structured.chapters.map((c, i) => <article key={i}><button onClick={() => { onClose(); navigate(`/tasks/${c.job_id}?t=${c.start_seconds}`); }}>{stamp(c.start_seconds)}</button><div><strong>{c.title}</strong><p>{c.summary}</p></div></article>)}</div> : <Markdown content={artifact.content}/>}</Modal>;
}
export function ShareModal({ conversationId, onClose }) {
    const [list, setList] = useState([]), [error, setError] = useState(''), [link, setLink] = useState(''), [days, setDays] = useState(7), [sources, setSources] = useState(false), [busy, setBusy] = useState(false), [copied, setCopied] = useState(false);
    const load = () => assistantApi.shares(conversationId).then(setList).catch(e => setError(e.message));
    useEffect(() => { load(); }, [conversationId]);
    async function create() { setBusy(true); setError(''); try {
        const r = await assistantApi.createShare(conversationId, { expires_in_days: Number(days), include_sources: sources });
        setLink(new URL(r.path, window.location.origin).href);
        await load();
    }
    catch (e) {
        setError(e.message);
    }
    finally {
        setBusy(false);
    } }
    return <Modal title="分享对话快照" onClose={onClose}><ErrorNotice error={error}/><p className="va-warning">持有链接的人无需登录即可查看当前对话的文字内容。请先确认不含敏感信息；后续新消息不会自动同步。</p><label>有效天数<select value={days} onChange={e => setDays(e.target.value)}><option value="1">1 天</option><option value="7">7 天</option><option value="30">30 天</option></select></label><label className="va-checkbox"><input type="checkbox" checked={sources} onChange={e => setSources(e.target.checked)}/>包含引用原文片段（可能包含私有资料）</label><button className="va-primary" disabled={busy} onClick={create}>创建只读链接</button>{link && <div className="va-share-link"><input readOnly value={link} aria-label="分享链接" onFocus={e => e.target.select()}/><button onClick={async () => { try {
        await navigator.clipboard.writeText(link);
        setCopied(true);
    }
    catch {
        setError('请手动复制链接');
    } }}>{copied ? '已复制' : '复制'}</button><small>完整链接仅此次显示。</small></div>}<h3>已创建的分享</h3>{list.map(s => <div className="va-simple-row" key={s.id}><span>{dateLabel(s.expires_at)} 到期</span><button disabled={s.revoked} onClick={async () => { try {
        await assistantApi.revokeShare(conversationId, s.id);
        load();
    }
    catch (e) {
        setError(e.message);
    } }}>{s.revoked ? '已撤销' : '撤销'}</button></div>)}</Modal>;
}
export default function ChatPage({ id, capabilities }) {
    const { conversation: c, refresh, error, setError, connection, running } = useConversation(id);
    const [action, setAction] = useState('chat'), [source, setSource] = useState(null), [artifact, setArtifact] = useState(null), [share, setShare] = useState(false), [picker, setPicker] = useState(false), [contextOpen, setContextOpen] = useState(true), [older, setOlder] = useState([]), [olderBusy, setOlderBusy] = useState(false), [allLoaded, setAllLoaded] = useState(false), [away, setAway] = useState(false), [copied, setCopied] = useState(null);
    const scroll = useRef(null), follow = useRef(true);
    useEffect(() => { setOlder([]); setAllLoaded(false); setAction('chat'); follow.current = true; }, [id]);
    useEffect(() => { if (follow.current && scroll.current)
        scroll.current.scrollTop = scroll.current.scrollHeight; }, [c?.messages?.at(-1)?.content, c?.messages?.length]);
    async function op(fn) { try {
        setError('');
        await fn();
        await refresh();
        changed();
    }
    catch (e) {
        setError(e.message);
    } }
    if (!c)
        return error ? <ErrorNotice error={error}/> : <Loading />;
    const writable = c.can_edit && !c.archived;
    const resources = c.resources || [], enabled = resources.filter(r => r.enabled).length;
    const messages = [...older, ...c.messages].filter((m, i, arr) => arr.findIndex(x => x.id === m.id) === i);
    const active = c.active_run;
    async function loadOlder() { setOlderBusy(true); try {
        const rows = await assistantApi.olderMessages(id, c.messages.length + older.length);
        setOlder(old => [...rows, ...old]);
        if (rows.length < 200)
            setAllLoaded(true);
    }
    catch (e) {
        setError(e.message);
    }
    finally {
        setOlderBusy(false);
    } }
    return <div className={`va-chat-layout ${resources.length && contextOpen ? 'has-context' : ''}`}>
    <section className="va-chat-main">
      <header className="va-chat-header"><div><h1>{c.title}</h1><small>{c.workspace_id ? '项目对话' : '私有对话'}{c.archived ? ' · 已归档' : ''}{!c.can_edit ? ' · 只读' : ''}</small></div><div className="va-actions"><button className={`va-icon-button ${c.pinned ? 'selected' : ''}`} title="置顶" disabled={!c.can_edit} onClick={() => op(() => assistantApi.updateConversation(id, { pinned: !c.pinned }))}><Icon name="pin"/></button><button className="va-icon-button" title="导出对话和成果" onClick={() => op(() => assistantApi.export(id, 'zip'))}><Icon name="file"/></button>{c.can_edit && <button className="va-icon-button" title="分享" disabled={running} onClick={() => setShare(true)}><Icon name="share"/></button>}<button className="va-secondary" onClick={() => resources.length ? setContextOpen(!contextOpen) : setPicker(true)}><Icon name="video"/>{resources.length || '添加视频'}</button></div></header>
      <ErrorNotice error={error} onClose={() => setError('')}/>
      <div className="va-messages" ref={scroll} onScroll={() => { const e = scroll.current; follow.current = e.scrollHeight - e.scrollTop - e.clientHeight < 120; setAway(!follow.current); }}>
        {c.has_older_messages && !allLoaded && <button className="va-load-more" disabled={olderBusy} onClick={loadOlder}>加载更早消息</button>}
        {!messages.length && <div className="va-chat-empty"><Icon name="sparkle" size={40}/><h2>从一个问题开始</h2><p>普通对话、视频总结和素材问答，都在这里完成。</p></div>}
        {messages.map(m => <article className={`va-message ${m.role}`} key={m.id}><div className="va-avatar">{m.role === 'user' ? '我' : <Icon name="sparkle" size={18}/>}</div><div className="va-message-body"><div className="va-message-author">{m.role === 'user' ? '你' : 'AI 助手'}<time>{dateLabel(m.created_at)}</time></div>{m.content ? <Markdown content={m.content} evidence={m.meta?.evidence || []} onCitation={setSource}/> : <div className="va-pending"><span className="va-spinner"/>{active?.message?.id === m.id ? (statusLabel[active.status] || '处理中') : '等待回答'}</div>}
          {m.meta?.warnings?.length > 0 && <details className="va-coverage"><summary>检索范围与提示</summary>{m.meta.warnings.map((w, i) => <p key={i}>{w}</p>)}</details>}
          {m.meta?.evidence?.length > 0 && <div className="va-source-chips">{m.meta.evidence.map(e => <button key={e.id} onClick={() => setSource(e)}><Icon name={e.job_id ? 'clock' : 'globe'} size={13}/>{e.id} {e.start_seconds != null ? stamp(e.start_seconds) : e.title?.slice(0, 18)}</button>)}</div>}
          {m.status === 'failed' && <p className="va-error">{m.meta?.error || '回答中断，已保留已生成内容。'}</p>}
          {m.status === 'cancelled' && <small className="va-muted">已停止生成</small>}
          {m.role === 'assistant' && <div className="va-message-tools"><button title="复制" onClick={async () => { try {
            await navigator.clipboard.writeText(m.content);
            setCopied(m.id);
        }
        catch {
            setError('复制失败，请手动选择文本');
        } }}><Icon name="copy" size={14}/>{copied === m.id ? '已复制' : '复制'}</button>{['failed', 'cancelled'].includes(m.status) && m.meta?.run_id && writable && <button disabled={running} onClick={() => op(() => assistantApi.retry(m.meta.run_id))}><Icon name="refresh" size={14}/>重试</button>}</div>}
        </div></article>)}
        {running && <section className="va-run-card"><strong><span className="va-spinner"/>{statusLabel[active.status] || active.stage}</strong>{resources.filter(r => r.job && ['queued', 'processing', 'cancel_requested'].includes(r.job.status)).map(r => <div key={r.id}><p>{r.job.title || '正在识别视频'}</p><JobSteps job={r.job}/></div>)}{active.trace?.length > 0 && <details><summary>查看执行步骤（非模型思维链）</summary>{active.trace.map((t, i) => <p key={i}>{t.label || t.stage || t.tool || t.message || JSON.stringify(t)}</p>)}</details>}<small>切换页面不会取消任务。停止回答不会删除视频任务。</small></section>}
        {c.artifacts?.length > 0 && <section className="va-artifacts"><h3>生成成果</h3><div>{c.artifacts.map(a => <button key={a.id} onClick={() => setArtifact(a)}><Icon name={a.kind === 'mindmap' ? 'tree' : a.kind === 'timeline' ? 'clock' : 'file'}/><span>{a.title}<small>{dateLabel(a.created_at)}</small></span><Icon name="chevron" size={15}/></button>)}</div></section>}
      </div>
      <div className="va-chat-bottom">{away && <button className="va-back-bottom" onClick={() => { follow.current = true; scroll.current.scrollTop = scroll.current.scrollHeight; setAway(false); }}>回到最新消息 <Icon name="down" size={14}/></button>}{connection === 'reconnecting' && <div className="va-connection">正在重连，任务仍在后台继续。</div>}
        {writable ? <Composer capabilities={capabilities} action={action} setAction={setAction} contextCount={enabled} workspaceId={c.workspace_id} active={running} onStop={() => op(() => assistantApi.stop(active.id))} onSend={async (payload) => { follow.current = true; await assistantApi.send(id, payload); changed(); await refresh(); }}/> : <div className="va-readonly">{c.archived ? '对话已归档' : '当前为只读权限'}{c.archived && c.can_edit && <button onClick={() => op(() => assistantApi.updateConversation(id, { archived: false }))}>取消归档</button>}</div>}
      </div>
    </section>
    {resources.length > 0 && contextOpen && <aside className="va-context"><header><h2><Icon name="video"/>当前上下文</h2><button className="va-icon-button" title="收起" onClick={() => setContextOpen(false)}><Icon name="close" size={16}/></button></header><small className="va-muted">已启用 {enabled} / {resources.length} 项素材</small>{resources.map(r => <section className={`va-context-card ${r.enabled ? '' : 'disabled'}`} key={r.id}><div className="va-resource-title"><Icon name={r.job ? 'video' : 'users'}/><strong>{r.restricted ? '素材访问权限已收回' : r.job?.title || r.creator?.name || '视频处理中'}</strong></div>{r.job && <><p><span className={`va-badge ${r.job.status}`}>{statusLabel[r.job.status] || r.job.status}</span></p><small>{indexLabel[r.index?.status] || r.index?.status}</small>{r.index?.error_message && <p className="va-warning">{r.index.error_message}</p>}<button className="va-text-button" onClick={() => navigate(`/tasks/${r.job_id}`)}>查看文字稿 / 任务</button></>}{r.can_reindex && ['missing', 'lexical_ready', 'degraded', 'failed', 'stale'].includes(r.index?.status) && <button className="va-text-button" disabled={running} onClick={() => op(() => assistantApi.index(r.job_id))}>重建问答索引</button>}<div className="va-resource-controls"><label className="va-checkbox"><input type="checkbox" checked={r.enabled} disabled={running || !writable || r.restricted} onChange={e => op(() => assistantApi.toggleResource(id, r.id, e.target.checked))}/>用于问答</label>{writable && <button className="va-icon-button" disabled={running} title="从对话移除，保留原视频" onClick={() => op(() => assistantApi.removeResource(id, r.id))}><Icon name="close" size={14}/></button>}</div></section>)}{writable && <button className="va-secondary va-full" disabled={running} onClick={() => setPicker(true)}><Icon name="plus"/>添加已有视频</button>}<h3>基于素材继续</h3><div className="va-context-actions">{templates.filter(t => ['summary', 'notes', 'timeline', 'mindmap', 'compare', 'study_pack'].includes(t.id)).map(t => <button key={t.id} disabled={!writable || running} onClick={() => setAction(t.id)}><Icon name={t.icon} size={17}/>{t.title}</button>)}</div><p className="va-muted">时间点引用定位到文字稿。未配置画面分析时，回答基于音频转写，不代表已看到画面。</p></aside>}
    {source && <SourceModal source={source} onClose={() => setSource(null)}/>}{artifact && <ArtifactModal artifact={artifact} onClose={() => setArtifact(null)}/>}{share && <ShareModal conversationId={id} onClose={() => setShare(false)}/>}{picker && <SourcePicker excluded={resources.map(r => r.job_id)} onClose={() => setPicker(false)} onSelect={async (job) => { setPicker(false); await op(() => assistantApi.addResource(id, { job_id: job.id })); }}/>}
  </div>;
}
