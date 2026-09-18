import { useEffect, useState } from 'react';
const read = () => ({ path: window.location.pathname.replace(/\/+$/, '') || '/',
    search: window.location.search, key: window.history.state?.key || 'initial' });
export function navigate(path) {
    if (!path.startsWith('/') || path.startsWith('//'))
        throw new Error('Invalid internal route');
    window.history.pushState({ key: crypto.randomUUID() }, '', path);
    window.dispatchEvent(new Event('app-navigate'));
}
export function useRoute() {
    const [route, setRoute] = useState(read);
    useEffect(() => {
        const sync = () => setRoute(read());
        window.addEventListener('popstate', sync);
        window.addEventListener('app-navigate', sync);
        return () => { window.removeEventListener('popstate', sync); window.removeEventListener('app-navigate', sync); };
    }, []);
    return route;
}
