import { useEffect, useRef } from 'react';
const paths = {
    plus: 'M12 5v14M5 12h14', chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z',
    home: 'm3 10 9-7 9 7v11h-6v-7H9v7H3Z', video: 'M3 4h18v16H3ZM10 8l6 4-6 4Z',
    search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    folder: 'M3 5h7l2 3h9v13H3Z', settings: 'M4 7h16M4 17h16M8 4v6M16 14v6',
    book: 'M12 5v16M12 5C7 2 3 3 3 3v16s4-1 9 2c5-3 9-2 9-2V3s-4-1-9 2Z',
    link: 'm10 13 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 4a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-2 2',
    upload: 'M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6', send: 'm4 12 16-9-5 18-4-7-7-2Zm7 2 9-11',
    close: 'm6 6 12 12M6 18 18 6', chevron: 'm9 5 7 7-7 7', down: 'm5 9 7 7 7-7',
    file: 'M5 2h9l5 5v15H5ZM14 2v6h5M8 13h8M8 17h6',
    clock: 'M12 7v5l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    tree: 'M12 3v8M4 11h16M4 11v7m16-7v7M2 18h4v4H2Zm16 0h4v4h-4ZM10 1h4v4h-4Z',
    users: 'M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3M13 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0M17 3a4 4 0 0 1 0 8m3 10v-3a4 4 0 0 0-3-4',
    globe: 'M2 12h20M12 2c6 6 6 14 0 20-6-6-6-14 0-20ZM22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    sparkle: 'm12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z',
    copy: 'M8 8h13v13H8ZM16 4V1H1v15h3', trash: 'M3 6h18M5 6v15h14V6M9 6V3h6v3M9 10v7m6-7v7',
    pin: 'm8 3 8 0-1 7 4 4H5l4-4ZM12 14v8', menu: 'M3 6h18M3 12h18M3 18h18',
    check: 'm4 12 5 5L20 6', share: 'M8 12h10m-4-4 4 4-4 4M9 4H3v17h18v-5',
    stop: 'M5 5h14v14H5Z', refresh: 'M20 8a9 9 0 1 0 1 7M20 2v6h-6',
};
export function Icon({ name = 'chat', size = 20, ...props }) {
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}><path d={paths[name] || paths.chat}/></svg>;
}
export function Modal({ title, onClose, children, wide = false }) {
    const ref = useRef(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        const previous = document.activeElement;
        const oldOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        ref.current?.focus();
        const handler = e => {
            if (e.key === 'Escape')
                closeRef.current();
            if (e.key === 'Tab') {
                const nodes = [...ref.current.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')].filter(node => !node.disabled);
                const first = nodes[0], last = nodes.at(-1);
                if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last?.focus();
                }
                else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first?.focus();
                }
            }
        };
        document.addEventListener('keydown', handler);
        return () => { document.removeEventListener('keydown', handler); document.body.style.overflow = oldOverflow; previous?.focus?.(); };
    }, []);
    return <div className="va-modal-mask" onMouseDown={e => { if (e.target === e.currentTarget)
        onClose(); }}><section ref={ref} className={`va-modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}><header><h2>{title}</h2><button className="va-icon-button" aria-label={'关闭'} onClick={onClose}><Icon name="close"/></button></header>{children}</section></div>;
}
export function ErrorNotice({ error, onClose }) {
    if (!error)
        return null;
    return <div className="va-error" role="alert"><span>{error}</span>{onClose && <button onClick={onClose} aria-label={'关闭提示'}><Icon name="close" size={16}/></button>}</div>;
}
export function Loading({ text = '正在加载…' }) { return <div className="va-loading" role="status"><span className="va-spinner"/>{text}</div>; }
export const stamp = value => {
    const n = Math.max(0, Math.floor(Number(value) || 0));
    return n >= 3600 ? `${Math.floor(n / 3600)}:${String(Math.floor(n / 60) % 60).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}` : `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;
};
export const dateLabel = value => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
