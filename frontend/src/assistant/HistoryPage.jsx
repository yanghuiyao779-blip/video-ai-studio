import { useEffect, useState } from 'react';
import { assistantApi, changed } from './api.js';
import { navigate } from './router.js';
import { Icon, Modal, Loading, ErrorNotice, dateLabel } from './ui.jsx';
export default function HistoryPage({ workspaceId = null, initialQuery = '' }) {
    const [q, setQ] = useState(initialQuery), [filter, setFilter] = useState('all'), [tag, setTag] = useState(''), [data, setData] = useState(null), [offset, setOffset] = useState(0), [error, setError] = useState(''), [edit, setEdit] = useState(null), [busy, setBusy] = useState(false), [tick, setTick] = useState(0);
    useEffect(() => { let alive = true; const t = setTimeout(() => { assistantApi.conversations({ q, archived: filter === 'archived', ...(filter === 'pinned' ? { pinned: true } : {}), ...(tag ? { tag } : {}), ...(workspaceId ? { workspace_id: workspaceId } : {}), offset, limit: 30 }).then(r => { if (alive)
        setData(r); }).catch(e => { if (alive)
        setError(e.message); }); }, 250); return () => { alive = false; clearTimeout(t); }; }, [q, filter, tag, offset, workspaceId, tick]);
    async function mutate(fn) { setBusy(true); setError(''); try {
        await fn();
        setTick(t => t + 1);
        changed();
    }
    catch (e) {
        setError(e.message);
    }
    finally {
        setBusy(false);
    } }
    return <section className="va-page"><header className="va-page-heading"><div><h1>对话记录</h1><p>从上次的问题继续，不必重新整理素材。</p></div><button className="va-primary" onClick={() => navigate(workspaceId ? `/?workspace=${workspaceId}` : '/')}><Icon name="plus"/>新建聊天</button></header><ErrorNotice error={error}/><div className="va-filterbar"><label className="va-search"><Icon name="search"/><input placeholder="搜索标题或消息内容" value={q} onChange={e => { setQ(e.target.value); setOffset(0); }}/></label><div className="va-segments">{[['all', '全部'], ['pinned', '置顶'], ['archived', '已归档']].map(([k, v]) => <button key={k} className={filter === k ? 'active' : ''} onClick={() => { setFilter(k); setOffset(0); }}>{v}</button>)}</div><input className="va-tag-filter" placeholder="按标签筛选" value={tag} onChange={e => { setTag(e.target.value); setOffset(0); }}/></div>
 {!data ? <Loading /> : !data.items.length ? <div className="va-empty"><Icon name="chat" size={40}/><h3>暂无匹配对话</h3><p>可以更换搜索条件，或开始一次新聊天。</p></div> : <div className="va-history-list">{data.items.map(c => <article key={c.id}><button className="va-history-open" onClick={() => navigate(`/c/${c.id}`)}><span className="va-history-icon"><Icon name={c.workspace_id ? 'folder' : 'chat'}/></span><span><strong>{c.pinned ? '★ ' : ''}{c.title}</strong><small>{dateLabel(c.updated_at)} {c.active_run_id ? ' · 任务进行中' : ''}</small>{c.tags?.length > 0 && <span className="va-tags">{c.tags.map(t => <i key={t}>{t}</i>)}</span>}</span></button><div className="va-actions"><button className="va-icon-button" title="置顶" disabled={busy} onClick={() => mutate(() => assistantApi.updateConversation(c.id, { pinned: !c.pinned }))}><Icon name="pin" size={17}/></button><button onClick={() => setEdit({ ...c, tagsText: c.tags.join(', ') })}>编辑</button><button disabled={busy} onClick={() => mutate(() => assistantApi.updateConversation(c.id, { archived: !c.archived }))}>{c.archived ? '恢复' : '归档'}</button><button className="va-icon-button va-danger" title="删除" disabled={busy || Boolean(c.active_run_id)} onClick={() => { if (window.confirm('删除对话及其分享？原始视频任务将保留。'))
        mutate(() => assistantApi.deleteConversation(c.id)); }}><Icon name="trash" size={17}/></button></div></article>)}</div>}
 {data && <div className="va-pagination"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><span>{data.total} 条对话</span><button disabled={data.next_offset == null} onClick={() => setOffset(data.next_offset)}>下一页</button></div>}
 {edit && <Modal title="编辑对话" onClose={() => setEdit(null)}><form className="va-form" onSubmit={e => { e.preventDefault(); mutate(async () => { await assistantApi.updateConversation(edit.id, { title: edit.title, tags: [...new Set(edit.tagsText.split(/[,，]/).map(t => t.trim()).filter(Boolean))] }); setEdit(null); }); }}><label>标题<input required maxLength={200} value={edit.title} onChange={e => setEdit({ ...edit, title: e.target.value })}/></label><label>标签（逗号分隔，最多 12 个）<input value={edit.tagsText} onChange={e => setEdit({ ...edit, tagsText: e.target.value })}/></label><button className="va-primary" disabled={busy}>保存</button></form></Modal>}
 </section>;
}
