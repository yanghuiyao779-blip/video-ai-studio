import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Modal, ErrorNotice, Loading, Icon } from './ui.jsx';
export default function SourcePicker({ onClose, onSelect, existing = [], excluded = [] }) {
    const [jobs, setJobs] = useState(null), [query, setQuery] = useState(''), [error, setError] = useState('');
    useEffect(() => { let alive = true; api.jobs().then(x => { if (alive)
        setJobs(x); }).catch(e => { if (alive)
        setError(e.message); }); return () => { alive = false; }; }, []);
    const filtered = jobs?.filter(j => `${j.title || ''} ${j.source_url}`.toLowerCase().includes(query.toLowerCase())) || [];
    return <Modal title={'从视频库选择'} onClose={onClose} wide>
    <p className="va-muted">{'已解析的视频可直接复用，无需重新下载。'}</p>
    <label className="va-search"><Icon name="search"/><input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder={'搜索视频标题'}/></label>
    <ErrorNotice error={error}/>{!jobs && !error ? <Loading /> : <div className="va-picker-list">{filtered.map(job => <button key={job.id} disabled={[...existing, ...excluded].includes(job.id)} onClick={() => onSelect(job)}><Icon name="video"/><span><strong>{job.title || job.source_filename || '等待识别视频'}</strong><small>{job.platform || '本地文件'} &middot; {job.status}</small></span><span>{[...existing, ...excluded].includes(job.id) ? '已添加' : '+'}</span></button>)}{!filtered.length && <p className="va-empty-small">{'暂无匹配视频，可粘贴链接或上传本地文件。'}</p>}</div>}
  </Modal>;
}
