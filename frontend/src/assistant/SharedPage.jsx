import { useEffect, useState } from 'react';
import { assistantApi } from './api.js';
import { Loading, ErrorNotice, Icon } from './ui.jsx';
import Markdown from './Markdown.jsx';
import { SourceModal } from './ChatPage.jsx';
export default function SharedPage({ token }) {
    const [data, setData] = useState(null), [error, setError] = useState(''), [source, setSource] = useState(null);
    useEffect(() => { let alive = true; assistantApi.shared(token).then(r => { if (alive)
        setData(r); }).catch(e => { if (alive)
        setError(e.message); }); return () => { alive = false; }; }, [token]);
    return <main className="va-shared"><header><div className="va-brand"><span>VA</span><strong>Video AI Studio</strong></div><a href="/">返回应用</a></header>{error ? <ErrorNotice error={error}/> : !data ? <Loading /> : <><h1>{data.title}</h1><p className="va-muted">只读分享快照 · 内容由分享者提供，AI 回答可能有误</p>{data.messages.map((m, i) => <article className={`va-message ${m.role}`} key={i}><div className="va-avatar">{m.role === 'user' ? '问' : <Icon name="sparkle" size={18}/>}</div><div className="va-message-body"><Markdown content={m.content} evidence={m.evidence || []} onCitation={setSource}/></div></article>)}</>}{source && <SourceModal source={source} onClose={() => setSource(null)}/>}</main>;
}
