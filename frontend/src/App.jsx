import { useCallback, useEffect, useState } from 'react';
import { api, getToken, setToken } from './api.js';
import { assistantApi, changed } from './assistant/api.js';
import { useRoute, navigate } from './assistant/router.js';
import { Icon, Loading, ErrorNotice } from './assistant/ui.jsx';
import HomePage from './assistant/HomePage.jsx';
import ChatPage from './assistant/ChatPage.jsx';
import HistoryPage from './assistant/HistoryPage.jsx';
import ProjectsPage, { UserAdmin } from './assistant/ProjectsPage.jsx';
import SharedPage from './assistant/SharedPage.jsx';
import { Login, NewJob, JobHistory, JobDetail, CreatorsPage, SettingsPage, HelpPage, SecuritySettings } from './legacy/VideoPages.jsx';
export default function App() {
    const route = useRoute();
    const [authenticated, setAuthenticated] = useState(Boolean(getToken())), [me, setMe] = useState(null), [cap, setCap] = useState(null), [recent, setRecent] = useState([]), [jobs, setJobs] = useState([]), [health, setHealth] = useState(null), [settings, setSettings] = useState(null), [defaults, setDefaults] = useState(null), [storage, setStorage] = useState(null), [creators, setCreators] = useState([]), [error, setError] = useState(''), [mobile, setMobile] = useState(false), [search, setSearch] = useState(''), [selectedJob, setSelectedJob] = useState(null);
    const shareToken = route.path.startsWith('/share/') ? route.path.split('/')[2] : null;
    const taskId = route.path.startsWith('/tasks/') ? route.path.split('/')[2] : null;
    const refreshRecent = useCallback(() => assistantApi.conversations({ limit: 30 }).then(r => setRecent(r.items)).catch(e => setError(e.message)), []);
    const refreshJobs = useCallback(() => api.jobs().then(setJobs).catch(e => setError(e.message)), []);
    const loadAdmin = useCallback(async () => { const r = await Promise.allSettled([api.getLLM(), api.getTaskDefaults(), api.getStorage(), api.creators()]); const setters = [setSettings, setDefaults, setStorage, setCreators]; r.forEach((x, i) => { if (x.status === 'fulfilled')
        setters[i](x.value);
    else
        setError(x.reason.message); }); }, []);
    async function refreshAll() { await Promise.all([refreshJobs(), refreshRecent(), ...(cap?.admin ? [loadAdmin()] : [])]); }
    useEffect(() => { document.documentElement.dataset.theme = 'light'; localStorage.setItem('video-ai-theme', 'light'); }, []);
    useEffect(() => { const expired = () => { setAuthenticated(false); setCap(null); setMe(null); setJobs([]); setRecent([]); setCreators([]); setSettings(null); }; window.addEventListener('video-ai-auth-expired', expired); return () => window.removeEventListener('video-ai-auth-expired', expired); }, []);
    useEffect(() => {
        if (!authenticated || shareToken)
            return;
        let alive = true;
        Promise.all([api.me(), assistantApi.capabilities(), api.health()]).then(async ([user, c, h]) => { if (!alive)
            return; setMe(user); setCap(c); setHealth(h); await Promise.all([refreshRecent(), refreshJobs()]); if (c.admin)
            await loadAdmin(); }).catch(e => { if (alive)
            setError(e.message); });
        return () => { alive = false; };
    }, [authenticated, Boolean(shareToken), refreshRecent, refreshJobs, loadAdmin]);
    useEffect(() => { if (!authenticated || shareToken)
        return; const fn = () => { refreshRecent(); assistantApi.capabilities().then(setCap).catch(() => { }); }; window.addEventListener('assistant-changed', fn); return () => window.removeEventListener('assistant-changed', fn); }, [authenticated, Boolean(shareToken), refreshRecent]);
    useEffect(() => { setMobile(false); if (taskId) {
        setSelectedJob(null);
        api.getJob(taskId).then(setSelectedJob).catch(e => setError(e.message));
    } }, [route.key, taskId]);
    const activeJobs = jobs.some(j => ['queued', 'processing', 'cancel_requested'].includes(j.status));
    useEffect(() => { if (!authenticated || shareToken || (!activeJobs && !taskId && !route.path.startsWith('/creators')))
        return; const timer = setInterval(() => { if (document.hidden)
        return; refreshJobs(); if (taskId)
        api.getJob(taskId).then(setSelectedJob).catch(e => setError(e.message)); if (route.path.startsWith('/creators') && cap?.admin)
        api.creators().then(setCreators).catch(() => { }); }, 3000); return () => clearInterval(timer); }, [authenticated, Boolean(shareToken), activeJobs, taskId, route.path, cap?.admin, refreshJobs]);
    function logout() { setToken(null); setAuthenticated(false); setCap(null); setMe(null); setRecent([]); setJobs([]); setCreators([]); setSettings(null); navigate('/'); }
    if (shareToken)
        return <SharedPage key={shareToken} token={shareToken}/>;
    if (!authenticated)
        return <Login onLogin={() => { setAuthenticated(true); setError(''); }}/>;
    const query = new URLSearchParams(route.search);
    const chatId = route.path.startsWith('/c/') ? route.path.split('/')[2] : null;
    const creatorId = route.path.startsWith('/creators/') ? route.path.split('/')[2] : null;
    const projectId = route.path.startsWith('/projects/') ? route.path.split('/')[2] : null;
    const openJob = id => navigate(`/tasks/${encodeURIComponent(id)}`);
    const openCreator = (id, tab = 'overview') => navigate(`/creators/${id}${tab === 'overview' ? '' : `?tab=${encodeURIComponent(tab)}`}`);
    const nav = [['/', 'home', 'AI 助手'], ['/conversations', 'chat', '对话记录'], ['/videos', 'video', '视频库 / 任务'], ['/projects', 'folder', '项目空间'], ...(cap?.admin ? [['/creators', 'users', '博主研究']] : [])];
    const currentNav = chatId ? '/' : taskId || route.path === '/history' ? '/videos' : route.path;
    let page;
    if (!cap)
        page = <Loading />;
    else if (chatId)
        page = <ChatPage key={chatId} id={chatId} capabilities={cap}/>;
    else if (route.path === '/')
        page = <HomePage key={route.key} capabilities={cap} conversations={recent} workspaceId={query.get('workspace')}/>;
    else if (route.path === '/conversations')
        page = <HistoryPage key={route.key} initialQuery={query.get('q') || ''}/>;
    else if (route.path.startsWith('/projects'))
        page = <ProjectsPage key={projectId || 'projects'} selectedId={projectId}/>;
    else if (taskId)
        page = selectedJob ? <div className="va-legacy"><div className="va-actions va-legacy-actions"><button className="va-primary" onClick={async () => { try {
            const c = await assistantApi.createConversation({ title: selectedJob.title || '视频问答' });
            await assistantApi.addResource(c.id, { job_id: taskId });
            changed();
            navigate(`/c/${c.id}`);
        }
        catch (e) {
            setError(e.message);
        } }}><Icon name="chat"/>在新对话中提问</button></div><JobDetail job={selectedJob} llmConfigured={cap.chat} onBack={() => navigate('/videos')} onRefresh={async () => { await refreshJobs(); setSelectedJob(await api.getJob(taskId)); }} onDelete={async () => { navigate('/videos'); await refreshJobs(); }}/></div> : <Loading />;
    else if (['/videos', '/history'].includes(route.path))
        page = <div className="va-legacy"><div className="va-actions va-legacy-actions"><button className="va-primary" onClick={() => navigate('/legacy/new')}><Icon name="plus"/>新建视频解析</button></div><JobHistory jobs={jobs} onOpen={openJob} onRefresh={refreshJobs}/></div>;
    else if (route.path === '/legacy/new')
        page = <div className="va-legacy"><NewJob jobs={jobs} llmConfigured={cap.chat} defaults={defaults} onCreated={refreshJobs} onGoSettings={() => navigate('/settings')} onOpenJob={openJob} onOpenHistory={() => navigate('/videos')}/></div>;
    else if (route.path.startsWith('/creators') && cap.admin)
        page = <div className="va-legacy">{creatorId && <div className="va-actions va-legacy-actions"><button className="va-primary" onClick={async () => { try {
            const c = await assistantApi.createConversation({ title: '博主内容问答' });
            await assistantApi.addResource(c.id, { creator_id: creatorId });
            changed();
            navigate(`/c/${c.id}`);
        }
        catch (e) {
            setError(e.message);
        } }}>基于博主内容新建对话</button></div>}<CreatorsPage creators={creators} onRefresh={refreshAll} selectedCreatorId={creatorId} selectedCreatorTab={query.get('tab') || 'overview'} onOpenCreator={openCreator} onCloseCreator={() => navigate('/creators')} onChangeCreatorTab={openCreator}/></div>;
    else if (route.path === '/settings')
        page = <div className="va-legacy">{cap.admin ? (settings ? <><SettingsPage settings={settings} health={health} defaults={defaults} storage={storage} onSaved={value => { setSettings(value); changed(); }} onDefaultsSaved={setDefaults} onRefreshHealth={async () => setHealth(await api.health())} onRefreshStorage={async () => { const s = await api.getStorage(); setStorage(s); return s; }} storageAutoRefreshing={activeJobs}/><UserAdmin /></> : <Loading />) : <SecuritySettings />}</div>;
    else if (route.path === '/help')
        page = <div className="va-legacy"><section className="va-project-panel"><h1>使用 AI 助手</h1><p>直接输入问题即可聊天。发送视频链接或上传文件后，会创建独立的处理任务。点击回答中的引用可查看原文和时间点。</p><p>聊天模型、联网搜索和视觉模型可能涉及外部服务。私有部署不等于所有推理均在本地，请按数据要求配置。</p><p>无向量模型时使用关键词检索。长视频和多视频会使用有限片段与已有摘要，注意回答下方的覆盖范围提示。</p></section><HelpPage /></div>;
    else
        page = <div className="va-empty"><h1>404</h1><p>页面不存在</p><button onClick={() => navigate('/')}>返回首页</button></div>;
    return <div className={`va-app ${mobile ? 'menu-open' : ''}`}><button className="va-mobile-backdrop" aria-label="关闭菜单" onClick={() => setMobile(false)}/><aside className="va-sidebar"><button className="va-brand" onClick={() => navigate('/')}><span>VA</span><div><strong>视频 AI 工作台</strong><small>Video AI Studio</small></div></button><button className="va-primary va-new-chat" onClick={() => navigate('/')}><Icon name="plus"/>新建聊天</button><nav className="va-nav">{nav.map(([path, icon, title]) => <button key={path} className={currentNav === path || (path !== '/' && currentNav.startsWith(path + '/')) ? 'active' : ''} onClick={() => navigate(path)}><Icon name={icon}/>{title}{path === '/videos' && activeJobs && <i className="va-live-dot"/>}</button>)}</nav><div className="va-sidebar-history"><div className="va-history-label">最近对话 <button className="va-icon-button" title="搜索对话" onClick={() => navigate('/conversations')}><Icon name="search" size={15}/></button></div>{recent.map(c => <button key={c.id} className={chatId === c.id ? 'active' : ''} title={c.title} onClick={() => navigate(`/c/${c.id}`)}>{c.pinned && <Icon name="pin" size={12}/>}<span>{c.title}</span>{c.active_run_id && <i className="va-live-dot"/>}</button>)}{!recent.length && <p className="va-muted">聊天记录会保存在这里</p>}</div><footer className="va-sidebar-footer"><div className="va-actions"><button onClick={() => navigate('/settings')}><Icon name="settings" size={17}/>设置</button><button onClick={() => navigate('/help')}>帮助</button></div><div className="va-account"><span className="va-account-avatar">{me?.username?.[0]?.toUpperCase() || 'U'}</span><div><strong>{me?.username || '用户'}</strong><small>{cap?.admin ? '部署管理员' : '私有工作空间'}</small></div><button onClick={logout}>退出</button></div></footer></aside><main className="va-main"><header className="va-topbar"><button className="va-icon-button va-mobile-toggle" aria-label="展开菜单" onClick={() => setMobile(true)}><Icon name="menu"/></button><form className="va-global-search" onSubmit={e => { e.preventDefault(); navigate(`/conversations?q=${encodeURIComponent(search)}`); }}><Icon name="search" size={17}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索对话和消息内容" aria-label="搜索对话"/></form><span className={`va-service ${cap?.chat ? 'ready' : ''}`}><i />{cap?.chat ? 'AI 已配置' : '待配置 AI'}</span></header>{error && <ErrorNotice error={error} onClose={() => setError('')}/>}<div className={`va-main-body ${chatId ? 'is-chat' : ''}`}>{page}</div></main></div>;
}
