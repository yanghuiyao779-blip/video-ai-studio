import { request, getToken, setToken, authenticatedBlob } from '../api.js';
const root = '/api/assistant';
const json = (method, body) => ({ method, body: JSON.stringify(body) });
const enc = encodeURIComponent;
export const assistantApi = {
    capabilities: () => request(`${root}/capabilities`),
    conversations: (params = {}) => request(`${root}/conversations?${new URLSearchParams(params)}`),
    createConversation: (body = {}) => request(`${root}/conversations`, json('POST', body)),
    conversation: id => request(`${root}/conversations/${enc(id)}`),
    olderMessages: (id, offset) => request(`${root}/conversations/${enc(id)}/messages?offset=${offset}`),
    updateConversation: (id, body) => request(`${root}/conversations/${enc(id)}`, json('PATCH', body)),
    deleteConversation: id => request(`${root}/conversations/${enc(id)}`, { method: 'DELETE' }),
    send: (id, body) => request(`${root}/conversations/${enc(id)}/messages`, json('POST', body)),
    addResource: (id, body) => request(`${root}/conversations/${enc(id)}/resources`, json('POST', body)),
    toggleResource: (id, resource, enabled) => request(`${root}/conversations/${enc(id)}/resources/${enc(resource)}`, json('PATCH', { enabled })),
    removeResource: (id, resource) => request(`${root}/conversations/${enc(id)}/resources/${enc(resource)}`, { method: 'DELETE' }),
    run: id => request(`${root}/runs/${enc(id)}`),
    stop: id => request(`${root}/runs/${enc(id)}/stop`, { method: 'POST' }),
    retry: id => request(`${root}/runs/${enc(id)}/retry`, { method: 'POST' }),
    index: id => request(`${root}/videos/${enc(id)}/index`, { method: 'POST' }),
    workspaces: () => request(`${root}/workspaces`),
    createWorkspace: body => request(`${root}/workspaces`, json('POST', body)),
    updateWorkspace: (id, body) => request(`${root}/workspaces/${enc(id)}`, json('PATCH', body)),
    deleteWorkspace: id => request(`${root}/workspaces/${enc(id)}`, { method: 'DELETE' }),
    workspaceResources: id => request(`${root}/workspaces/${enc(id)}/resources`),
    addWorkspaceResource: (id, job) => request(`${root}/workspaces/${enc(id)}/resources`, json('POST', { job_id: job })),
    removeWorkspaceResource: (id, job) => request(`${root}/workspaces/${enc(id)}/resources/${enc(job)}`, { method: 'DELETE' }),
    members: id => request(`${root}/workspaces/${enc(id)}/members`),
    addMember: (id, body) => request(`${root}/workspaces/${enc(id)}/members`, json('POST', body)),
    removeMember: (id, user) => request(`${root}/workspaces/${enc(id)}/members/${enc(user)}`, { method: 'DELETE' }),
    createUser: body => request(`${root}/users`, json('POST', body)),
    createShare: (id, body) => request(`${root}/conversations/${enc(id)}/shares`, json('POST', body)),
    shares: id => request(`${root}/conversations/${enc(id)}/shares`),
    revokeShare: (id, share) => request(`${root}/conversations/${enc(id)}/shares/${enc(share)}`, { method: 'DELETE' }),
    shared: token => request(`${root}/shared/${enc(token)}`),
    export: async (id, format = 'markdown') => {
        const blob = await authenticatedBlob(`${root}/conversations/${enc(id)}/export?format=${enc(format)}`);
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `conversation-${id}.${format === 'markdown' ? 'md' : format}`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
};
/** SSE snapshots are replaceable, versioned messages. Reconnect cannot duplicate tokens. */
export async function streamRun(id, onSnapshot, signal) {
    const response = await fetch(`${root}/runs/${enc(id)}/stream`, {
        headers: { Authorization: `Bearer ${getToken()}`, Accept: 'text/event-stream' }, signal,
    });
    if (response.status === 401) {
        setToken(null);
        window.dispatchEvent(new Event('video-ai-auth-expired'));
    }
    if (!response.ok || !response.body)
        throw new Error(`Stream unavailable (${response.status})`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
        while (true) {
            const { value, done } = await reader.read();
            buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
            buffer = buffer.replace(/\r\n/g, '\n');
            if (buffer.length > 4 * 1024 * 1024)
                throw new Error('SSE frame too large');
            let split;
            while ((split = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, split);
                buffer = buffer.slice(split + 2);
                const lines = frame.split('\n');
                const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
                const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
                if (type === 'snapshot' && data)
                    onSnapshot(JSON.parse(data));
                if (type === 'error')
                    throw new Error(JSON.parse(data).message || 'Stream denied');
            }
            if (done)
                break;
        }
    }
    finally {
        await reader.cancel().catch(() => { });
        reader.releaseLock();
    }
}
export function changed() { window.dispatchEvent(new Event('assistant-changed')); }
export const terminal = status => ['completed', 'failed', 'cancelled'].includes(status);
