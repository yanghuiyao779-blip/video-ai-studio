/** Candidate detection is pure; the server still validates URL safety. */
export function mediaCandidates(value) {
    return [...new Set((value.match(/https?:\/\/[^\s<>]+/g) || []).map(x => x.replace(/[.,;!?。，；！？）】》)"\]}]+$/, '')).filter(url => {
            try {
                const u = new URL(url), h = u.hostname.toLowerCase();
                if (u.username || u.password)
                    return false;
                if (h === 'youtube.com' || h.endsWith('.youtube.com'))
                    return /^\/(watch|shorts\/|live\/|embed\/)/.test(u.pathname);
                if (h === 'bilibili.com' || h.endsWith('.bilibili.com'))
                    return u.pathname.startsWith('/video/');
                if (h === 'douyin.com' || h.endsWith('.douyin.com'))
                    return !u.pathname.startsWith('/user/') && (h.startsWith('v.') || u.pathname.includes('/video/') || u.search.includes('modal_id='));
                return ['b23.tv', 'youtu.be', 'iesdouyin.com'].some(d => h === d || h.endsWith('.' + d)) || /\.(mp4|mov|webm|mkv|mp3|wav|m4a|flac|ogg)$/i.test(u.pathname);
            }
            catch {
                return false;
            }
        }))];
}
