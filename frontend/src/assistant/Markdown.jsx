import { Fragment, useState } from 'react';
import { Icon } from './ui.jsx';
export function safeHref(value) {
    try {
        const u = new URL(value);
        return ['http:', 'https:'].includes(u.protocol) ? u.href : null;
    }
    catch {
        return null;
    }
}
function inline(text, onCitation) {
    return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`|\[[VWF]\d+\]|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g).filter(Boolean).map((part, index) => {
        if (/^\[[VWF]\d+\]$/.test(part))
            return onCitation ? <button key={index} className="va-citation" onClick={() => onCitation(part.slice(1, -1))}>{part.slice(1, -1)}</button> : <span key={index} className="va-citation-text">{part}</span>;
        if (part.startsWith('**'))
            return <strong key={index}>{part.slice(2, -2)}</strong>;
        if (part.startsWith('`'))
            return <code key={index}>{part.slice(1, -1)}</code>;
        const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (link && safeHref(link[2]))
            return <a key={index} href={safeHref(link[2])} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
        return <Fragment key={index}>{part}</Fragment>;
    });
}
function Code({ language, text }) {
    const [copied, setCopied] = useState(false);
    return <div className="va-code"><div><span>{language || 'text'}</span><button onClick={async () => { try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
    }
    catch {
        setCopied(false);
    } }}><Icon name="copy" size={14}/>{copied ? '已复制' : '复制'}</button></div><pre><code>{text}</code></pre></div>;
}
/** Intentionally no raw HTML, innerHTML, remote images or executable diagrams. */
export default function Markdown({ text = '', content, evidence = [], onCitation }) {
    if (content !== undefined)
        text = content;
    const sourceCallback = onCitation;
    onCitation = sourceCallback ? id => { const item = evidence.find(e => e.id === id); if (item)
        sourceCallback(item); } : undefined;
    const lines = String(text).replace(/\r/g, '').split('\n');
    const output = [];
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.startsWith('```')) {
            const code = [], language = line.slice(3).trim();
            while (++i < lines.length && !lines[i].startsWith('```'))
                code.push(lines[i]);
            output.push(<Code key={`code-${i}`} language={language} text={code.join('\n')}/>);
            continue;
        }
        if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
            const split = l => l.trim().replace(/^\||\|$/g, '').split('|').map(x => x.trim());
            const headers = split(line), rows = [];
            i++;
            while (i + 1 < lines.length && lines[i + 1].includes('|') && lines[i + 1].trim())
                rows.push(split(lines[++i]));
            output.push(<div className="va-table-scroll" key={`table-${i}`}><table><thead><tr>{headers.map((x, n) => <th key={n}>{inline(x, onCitation)}</th>)}</tr></thead><tbody>{rows.map((row, n) => <tr key={n}>{row.map((x, j) => <td key={j}>{inline(x, onCitation)}</td>)}</tr>)}</tbody></table></div>);
            continue;
        }
        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            const Tag = `h${Math.min(heading[1].length + 1, 6)}`;
            output.push(<Tag key={i}>{inline(heading[2], onCitation)}</Tag>);
            continue;
        }
        if (/^\s*[-*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
            const ordered = /^\s*\d/.test(line), rows = [], test = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/;
            do {
                rows.push(lines[i].replace(test, ''));
                i++;
            } while (i < lines.length && test.test(lines[i]));
            i--;
            const Tag = ordered ? 'ol' : 'ul';
            output.push(<Tag key={`list-${i}`}>{rows.map((row, j) => <li key={j}>{inline(row, onCitation)}</li>)}</Tag>);
            continue;
        }
        if (/^\s*---+\s*$/.test(line)) {
            output.push(<hr key={i}/>);
            continue;
        }
        if (line.startsWith('> ')) {
            output.push(<blockquote key={i}>{inline(line.slice(2), onCitation)}</blockquote>);
            continue;
        }
        if (!line.trim())
            continue;
        output.push(<p key={i}>{inline(line, onCitation)}</p>);
    }
    return <div className="va-markdown">{output}</div>;
}
