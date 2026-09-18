import { useEffect, useState } from 'react';
import { assistantApi, changed } from './api.js';
import { navigate } from './router.js';
import { Icon, ErrorNotice, Loading, Modal } from './ui.jsx';
import SourcePicker from './SourcePicker.jsx';
import HistoryPage from './HistoryPage.jsx';
export default function ProjectsPage({ selectedId }) {
    const [projects, setProjects] = useState(null), [resources, setResources] = useState([]), [members, setMembers] = useState([]), [error, setError] = useState(''), [editor, setEditor] = useState(null), [picker, setPicker] = useState(false), [memberOpen, setMemberOpen] = useState(false), [username, setUsername] = useState(''), [role, setRole] = useState('viewer'), [busy, setBusy] = useState(false);
    const project = projects?.find(p => p.id === selectedId);
    const load = async () => { const data = await assistantApi.workspaces(); setProjects(data); if (selectedId) {
        const [r, m] = await Promise.all([assistantApi.workspaceResources(selectedId), assistantApi.members(selectedId)]);
        setResources(r);
        setMembers(m);
    } };
    useEffect(() => { setResources([]); setMembers([]); load().catch(e => setError(e.message)); }, [selectedId]);
    async function mutate(fn) { setBusy(true); setError(''); try {
        await fn();
        await load();
        changed();
    }
    catch (e) {
        setError(e.message);
    }
    finally {
        setBusy(false);
    } }
    const writable = project && project.role !== 'viewer';
    return <div className="va-page"><header className="va-page-heading"><div><h1>{project ? project.name : '项目空间'}</h1><p>{project ? '共用素材、对话和项目要求' : '将多个视频和对话收纳到一个研究项目。'}</p></div><div className="va-actions">{selectedId && <button className="va-secondary" onClick={() => navigate('/projects')}>所有项目</button>}<button className="va-primary" onClick={() => setEditor({ name: '', instructions: '' })}><Icon name="plus"/>新建项目</button></div></header><ErrorNotice error={error}/>
 {!projects ? <Loading /> : !selectedId ? <div className="va-project-grid">{projects.map(p => <button key={p.id} className="va-project-card" onClick={() => navigate(`/projects/${p.id}`)}><Icon name="folder" size={28}/><strong>{p.name}</strong><p>{p.instructions || '添加素材开始分析'}</p><small>{({ owner: '拥有者', editor: '可编辑', viewer: '只读' })[p.role]}</small></button>)}{!projects.length && <div className="va-empty">还没有项目。新建一个，同一批视频就可以在不同对话中重复使用。</div>}</div> : !project ? <div className="va-empty">项目不存在或没有访问权限。</div> : <><section className="va-project-panel"><div><h2>项目要求</h2><p className="va-preline">{project.instructions || '未设置，可填写研究目标与输出风格。'}</p></div><div className="va-actions"><button className="va-secondary" onClick={() => setMemberOpen(true)}><Icon name="users"/>成员 ({members.length})</button>{writable && <button className="va-secondary" onClick={() => setEditor(project)}>编辑要求</button>}{project.role === 'owner' && <button className="va-danger" onClick={() => { if (window.confirm('删除项目及其所有对话？原始视频保留。'))
        mutate(async () => { await assistantApi.deleteWorkspace(project.id); navigate('/projects'); }); }}>删除</button>}</div></section><section className="va-project-panel"><div className="va-section-title"><h2>项目素材 ({resources.length})</h2>{writable && <button className="va-secondary" onClick={() => setPicker(true)}><Icon name="plus"/>添加视频</button>}</div><p className="va-muted">在输入框选择“项目素材”范围，即可跨视频检索。项目成员可查看这些素材。</p><div className="va-project-resources">{resources.map(j => <article key={j.id}><Icon name="video"/><button onClick={() => navigate(`/tasks/${j.id}`)}>{j.title || j.id}</button><small>{j.status}</small>{writable && <button className="va-icon-button" title="从项目移除" disabled={busy} onClick={() => { if (window.confirm('将同时从该项目内所有对话移除此素材，原文件保留。'))
        mutate(() => assistantApi.removeWorkspaceResource(project.id, j.id)); }}><Icon name="close" size={16}/></button>}</article>)}</div></section><HistoryPage key={project.id} workspaceId={project.id}/></>}
 {editor && <Modal title={editor.id ? '编辑项目' : '新建项目'} onClose={() => setEditor(null)}><form className="va-form" onSubmit={e => { e.preventDefault(); mutate(async () => { const payload = { name: editor.name, instructions: editor.instructions }; const r = editor.id ? await assistantApi.updateWorkspace(editor.id, payload) : await assistantApi.createWorkspace(payload); setEditor(null); if (!editor.id)
        navigate(`/projects/${r.id}`); }); }}><label>项目名称<input required maxLength={120} value={editor.name} onChange={e => setEditor({ ...editor, name: e.target.value })}/></label><label>项目要求<textarea maxLength={8000} rows={5} value={editor.instructions} onChange={e => setEditor({ ...editor, instructions: e.target.value })}/></label><button className="va-primary" disabled={busy}>保存</button></form></Modal>}
 {picker && <SourcePicker excluded={resources.map(r => r.id)} onClose={() => setPicker(false)} onSelect={async (j) => { setPicker(false); await mutate(() => assistantApi.addWorkspaceResource(selectedId, j.id)); }}/>}
 {memberOpen && project && <Modal title="项目成员与权限" onClose={() => setMemberOpen(false)}><ErrorNotice error={error}/>{members.map(m => <div key={m.id} className="va-simple-row"><strong>{m.username}</strong><span>{({ owner: '拥有者', editor: '编辑者', viewer: '查看者' })[m.role]}</span>{project.role === 'owner' && m.role !== 'owner' && <button disabled={busy} onClick={() => mutate(() => assistantApi.removeMember(project.id, m.id))}>移除</button>}</div>)}{project.role === 'owner' && <form className="va-form" onSubmit={e => { e.preventDefault(); mutate(async () => { await assistantApi.addMember(project.id, { username, role }); setUsername(''); }); }}><h3>添加成员 / 更新权限</h3><label>已有账号的用户名<input value={username} required onChange={e => setUsername(e.target.value)}/></label><label>权限<select value={role} onChange={e => setRole(e.target.value)}><option value="viewer">只读：查看项目、对话和素材</option><option value="editor">编辑：可提问、添加素材及分享对话</option></select></label><button className="va-primary" disabled={busy}>确认授权</button></form>}</Modal>}
 </div>;
}
export function UserAdmin() {
    const [username, setUsername] = useState(''), [password, setPassword] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
    return <section className="va-project-panel"><h2>创建成员账号</h2><p className="va-muted">创建普通账号，再在项目内分配权限。部署配置、Cookie 和博主整库仍仅限管理员。</p><ErrorNotice error={error}/>{message && <p className="va-success">{message}</p>}<form className="va-form" onSubmit={async (e) => { e.preventDefault(); setBusy(true); setError(''); setMessage(''); try {
        await assistantApi.createUser({ username, password });
        setMessage('账号已创建，请通过安全渠道告知对方初始密码。');
        setPassword('');
        setUsername('');
    }
    catch (err) {
        setError(err.message);
    }
    finally {
        setBusy(false);
    } }}><label>用户名<input required pattern="[A-Za-z0-9_.-]{3,80}" value={username} autoComplete="off" onChange={e => setUsername(e.target.value)}/></label><label>初始密码（至少 12 位）<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)}/></label><button className="va-primary" disabled={busy}>创建账号</button></form></section>;
}
