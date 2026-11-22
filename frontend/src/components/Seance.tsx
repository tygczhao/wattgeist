// Séance: Q&A answered by the Kiro Crew "seance" agent, which reads the household only through the WattGeist MCP tools.
// The history lives in the browser and the plain-text turns are sent back in full on every request.
// 后端经 kirocrew chat 调用 agent，只能拿到流式文本，拿不到工具调用事件，所以这里不再展示工具调用标签。
import { useEffect, useRef, useState } from "react";
import { ask } from "../lib/api";

interface Msg { role: "user" | "assistant"; content: string; error?: boolean }

const SUGGESTIONS = [
  "What is my always-on load and is it high?",
  "What happened on my worst haunted night?",
  "Which tariff should I be on?",
  "Why do some months cost more than others?",
];

export function Seance({ id, ai, name }: { id: string; ai: boolean; name: string }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const stop = useRef<(() => void) | null>(null);
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => { setMsgs([]); stop.current?.(); setBusy(false); }, [id]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  function send(q: string) {
    const question = q.trim();
    if (!question || busy) return;
    const history = msgs.filter((m) => !m.error && m.content.trim()).map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "" }]);
    setInput("");
    setBusy(true);
    const update = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    stop.current = ask(id, question, history, (e) => {
      if (e.type === "text") update((m) => ({ ...m, content: m.content + e.delta }));
      else if (e.type === "error") { update((m) => ({ ...m, content: m.content || e.message, error: !m.content })); setBusy(false); }
      else if (e.type === "done") setBusy(false);
    });
  }

  if (!ai) {
    return (
      <div className="card">
        <h2>The séance needs a medium</h2>
        <p className="secondary" style={{ marginTop: 8 }}>
          {/* AI 只来自 Kiro Crew：提示用户安装并登录 Kiro Crew、装上 WattGeist app，而不是配置模型 API key */}
          This server cannot reach Kiro Crew, so questions are switched off. Everything else works without it.
          Install Kiro Crew, sign in to Kiro and install the <code>wattgeist-night-watch</code> app, then restart to
          ask questions about this home.
        </p>
      </div>
    );
  }

  return (
    <section className="card seance">
      <div className="messages" aria-live="polite">
        {msgs.length === 0 && (
          <div className="stack" style={{ alignItems: "flex-start", gap: 12 }}>
            <h2>Ask {name} anything</h2>
            <p className="secondary">A Kiro Crew agent answers from your meter data: every number comes from the WattGeist analysis tools.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => <button key={s} className="btn small" onClick={() => send(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" ? <Markdownish text={m.content || (busy && i === msgs.length - 1 ? "…" : "")} /> : m.content}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea
          value={input} onChange={(e) => setInput(e.target.value)} placeholder="Why was January so expensive?"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
          aria-label="Question"
        />
        {busy ? <button type="button" className="btn" onClick={() => { stop.current?.(); setBusy(false); }}>Stop</button>
          : <button type="submit" className="btn primary" disabled={!input.trim()}>Ask</button>}
      </form>
    </section>
  );
}

/** Minimal Markdown rendering: bold, lists, tables. Everything becomes React elements, never innerHTML, so model output is never executed as HTML. */
function Markdownish({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("|") && lines[i + 1]?.trim().match(/^\|[\s:|-]+\|$/)) {
      const rows: string[][] = [];
      const head = splitRow(line);
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push(
        <table key={`t${i}`}><thead><tr>{head.map((h, k) => <th key={k}>{inline(h)}</th>)}</tr></thead>
          <tbody>{rows.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody></table>,
      );
      continue;
    }
    if (/^\s*[-*] /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*] /.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*] /, ""));
      out.push(<ul key={`u${i}`} style={{ margin: "6px 0", paddingLeft: 20 }}>{items.map((it, k) => <li key={k}>{inline(it)}</li>)}</ul>);
      continue;
    }
    out.push(<span key={`l${i}`}>{inline(line)}{i < lines.length - 1 ? "\n" : ""}</span>);
    i++;
  }
  return <>{out}</>;
}

function splitRow(line: string) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

function inline(s: string): React.ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, k) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={k}>{part.slice(1, -1)}</code>;
    return part.replace(/^#+\s*/, "");
  });
}
