import { useRef, useState } from 'react';
import { assistantApi, changed } from './api.js';
import { navigate } from './router.js';
import Composer from './Composer.jsx';
import { Icon, dateLabel } from './ui.jsx';
import { templates } from './templates.js';
export default function HomePage({ capabilities, conversations = [], workspaceId = null }) {
    const [action, setAction] = useState('chat'), [promptSignal, setPromptSignal] = useState(0), [more, setMore] = useState(false);
    const conversationId = useRef(null);
    async function send(payload) {
        if (!conversationId.current) {
            const c = await assistantApi.createConversation(workspaceId ? { workspace_id: workspaceId } : {});
            conversationId.current = c.id;
        }
        await assistantApi.send(conversationId.current, payload);
        changed();
        navigate(`/c/${conversationId.current}`);
    }
    function choose(id) { setAction(id); setPromptSignal(n => n + 1); }
    return <div className="va-home">
    <div className="va-home-main"><section className="va-welcome"><span className="va-eyebrow"><Icon name="sparkle" size={16}/>{'你的视频知识助手'}</span><h1>{'今天想'}<span>{'了解什么？'}</span></h1><p>{'从一个问题开始，或把视频变成可对话的知识。'}</p></section>
    {!capabilities.chat && <div className="va-setup-note"><Icon name="settings" size={18}/><span>{'转写功能可用。聊天与 AI 总结需先配置模型。'}</span>{capabilities.admin && <button onClick={() => navigate('/settings')}>{'去设置'} &rarr;</button>}</div>}
    <Composer onSend={send} capabilities={capabilities} action={action} setAction={setAction} promptSignal={promptSignal} workspaceId={workspaceId}/>
    <div className="va-quick-chips"><button onClick={() => choose('chat')} className={action === 'chat' ? 'selected' : ''}><Icon name="chat" size={17}/>{'通用对话'}</button><button onClick={() => choose('summary')}><Icon name="link" size={17}/>{'解析视频链接'}</button><button onClick={() => navigate('/videos')}><Icon name="folder" size={17}/>{'打开视频库'}</button>{capabilities.admin && <button onClick={() => navigate('/creators')}><Icon name="users" size={17}/>{'博主研究'}</button>}</div>
    <section className="va-starters"><div className="va-section-title"><h2>{'从这里开始'}</h2><span>{'选择模板，再添加你的素材'}</span></div><div className="va-template-grid">{templates.filter(t => ['summary', 'notes', 'meeting', 'timeline', 'mindmap', 'script'].includes(t.id)).map((t, index) => <button key={t.id} className={`va-template-card accent-${index} ${action === t.id ? 'selected' : ''}`} onClick={() => choose(t.id)}><span className="va-template-icon"><Icon name={t.icon}/></span><strong>{t.title}</strong><small>{t.hint}</small><Icon name="chevron" size={14}/></button>)}</div>
    <button className="va-text-button va-more" onClick={() => setMore(!more)}>{more ? '收起高级工具' : '更多分析工具'} <Icon name="down" size={15}/></button>{more && <div className="va-advanced-tools">{templates.filter(t => ['compare', 'research', 'visual', 'agent', 'study_pack'].includes(t.id)).map(t => <button key={t.id} disabled={Boolean(t.capability && !capabilities[t.capability])} onClick={() => choose(t.id)}><Icon name={t.icon}/><span><strong>{t.title}</strong><small>{t.capability && !capabilities[t.capability] ? '需管理员配置外部服务' : t.hint}</small></span></button>)}</div>}</section>
    {conversations.length > 0 && <section className="va-recent"><div className="va-section-title"><h2>{'最近继续'}</h2><button className="va-text-button" onClick={() => navigate('/conversations')}>{'查看全部'} &rarr;</button></div><div className="va-recent-grid">{conversations.slice(0, 3).map(c => <button key={c.id} onClick={() => navigate(`/c/${c.id}`)}><Icon name="chat"/><span><strong>{c.title}</strong><small>{dateLabel(c.updated_at)}</small></span><Icon name="chevron" size={16}/></button>)}</div></section>}
    </div><aside className="va-home-help"><span className="va-help-icon"><Icon name="sparkle"/></span><h3>{'一个输入框，三种开始'}</h3><div><Icon name="chat"/><section><strong>{'直接提问'}</strong><p>{'无需视频，也能聊天、写作和讨论。'}</p></section></div><div><Icon name="link"/><section><strong>{'粘贴视频链接'}</strong><p>{'发送后自动下载、转写和总结。'}</p></section></div><div><Icon name="upload"/><section><strong>{'上传本地文件'}</strong><p>{'支持视频和音频，已解析的素材可反复使用。'}</p></section></div><footer>{'连接模型后，可基于文字稿继续提问，并追溯时间点。'}</footer></aside>
  </div>;
}
