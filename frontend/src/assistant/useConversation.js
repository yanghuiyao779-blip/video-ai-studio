import { useCallback, useEffect, useRef, useState } from 'react';
import { assistantApi, changed, streamRun, terminal } from './api.js';
export default function useConversation(id) {
    const [conversation, setConversation] = useState(null);
    const [error, setError] = useState('');
    const [connection, setConnection] = useState('');
    const idRef = useRef(id);
    idRef.current = id;
    const latestRun = useRef(null);
    const mounted = useRef(false);
    const refresh = useCallback(async () => {
        try {
            const next = await assistantApi.conversation(id);
            if (!mounted.current || idRef.current !== id)
                return;
            const local = latestRun.current;
            if (next.active_run && local?.id === next.active_run.id && local.revision > next.active_run.revision) {
                next.active_run = local;
                next.messages = next.messages.map(m => m.id === local.message?.id ? local.message : m);
            }
            else if (next.active_run)
                latestRun.current = next.active_run;
            setConversation(next);
        }
        catch (err) {
            if (mounted.current && idRef.current === id)
                setError(err.message);
        }
    }, [id]);
    useEffect(() => {
        mounted.current = true;
        latestRun.current = null;
        setConversation(null);
        setError('');
        refresh();
        return () => { mounted.current = false; };
    }, [id, refresh]);
    const activeId = conversation?.active_run?.id;
    const running = activeId && !terminal(conversation?.active_run?.status);
    useEffect(() => {
        if (!running)
            return;
        const controller = new AbortController();
        let timer;
        let finished = false;
        const snapshot = next => {
            if (controller.signal.aborted || idRef.current !== id)
                return;
            const previous = latestRun.current;
            if (previous?.id === next.id && previous.revision > next.revision)
                return;
            latestRun.current = next;
            setConversation(old => old ? { ...old, active_run: next,
                messages: old.messages.some(m => m.id === next.message?.id)
                    ? old.messages.map(m => m.id === next.message?.id ? next.message : m)
                    : [...old.messages, next.message].filter(Boolean),
            } : old);
            if (terminal(next.status)) {
                finished = true;
                setConnection('');
                changed();
                refresh();
            }
        };
        const connect = async () => {
            try {
                setConnection('connected');
                await streamRun(activeId, snapshot, controller.signal);
                if (!finished && !controller.signal.aborted)
                    throw new Error('Stream interrupted');
            }
            catch {
                if (controller.signal.aborted || finished)
                    return;
                setConnection('reconnecting');
                try {
                    snapshot(await assistantApi.run(activeId));
                }
                catch { /* next refresh shows access errors */ }
                if (!finished && !controller.signal.aborted)
                    timer = setTimeout(connect, 2000);
            }
        };
        connect();
        return () => { controller.abort(); clearTimeout(timer); };
    }, [activeId, running, id, refresh]);
    useEffect(() => {
        if (!running)
            return;
        const timer = setInterval(() => { if (!document.hidden)
            refresh(); }, 2500);
        return () => clearInterval(timer);
    }, [running, refresh]);
    return { conversation, refresh, error, setError, connection, running: Boolean(running) };
}
