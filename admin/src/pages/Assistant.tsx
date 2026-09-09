import { useState, useRef, useEffect, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Bot, ArrowUpRight, Send } from "lucide-react";
import { api } from "../lib/api";
interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
}
const prompts = [
  "How does territory capture work? Cite the code.",
  "Help me test a run with the joystick.",
  "Check the current world counts and explain the admin pages.",
];
export default function Assistant() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);
  async function ask(value: string) {
    if (!value.trim() || busy) return;
    const history = messages
      .slice(-6)
      .map(({ role, content }) => ({ role, content: content.slice(0, 8000) }));
    setQuestion("");
    setMessages((m) => [...m, { role: "user", content: value }]);
    setBusy(true);
    setError("");
    try {
      const result = await api.assistant(value, history);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (e) {
      setError((e as Error).message);
      setQuestion(value);
    } finally {
      setBusy(false);
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }
  return (
    <div className="page scout-page">
      <header className="page-title">
        <div>
          <span className="eyebrow">YOUR CODEBASE COPILOT</span>
          <h1>Ask Scout.</h1>
          <p>
            Explore the implementation. Understand the world. Find your next
            move.
          </p>
        </div>
        <Bot size={34} />
      </header>
      <div className="scout-layout">
        <section className="panel chat-panel">
          <div className="chat-scroll">
            {messages.length === 0 && (
              <div className="scout-welcome">
                <Bot size={40} />
                <h2>Let’s explore TerraRun.</h2>
                <p>
                  I can inspect source code, explain features, check live
                  summary counts and draft test plans or notes.
                </p>
                {prompts.map((p) => (
                  <button
                    className="suggestion"
                    key={p}
                    onClick={() => void ask(p)}
                  >
                    {p}
                    <ArrowUpRight size={16} />
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <article key={i} className={`chat-message ${m.role}`}>
                <span className="eyebrow">
                  {m.role === "user" ? "YOU" : "SCOUT"}
                </span>
                <p className="preserve-lines">{m.content}</p>
                {!!m.sources?.length && (
                  <details>
                    <summary>Inspected source files</summary>
                    {m.sources.map((s) => (
                      <code key={s}>{s}</code>
                    ))}
                  </details>
                )}
              </article>
            ))}
            {busy && (
              <p className="chat-thinking" role="status">
                Scout is inspecting the codebase…
              </p>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <div ref={end} />
          </div>
          <form className="chat-compose" onSubmit={submit}>
            <textarea
              aria-label="Ask Scout"
              placeholder="Ask about a feature, bug or next step…"
              maxLength={2000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
            />
            <button
              className="primary-btn"
              disabled={busy || !question.trim()}
              aria-label="Send question"
            >
              <Send size={18} />
            </button>
          </form>
          <small>
            Read-only inspection · drafts need your review · conversations stay
            in this page
          </small>
        </section>
        <aside className="panel scout-shortcuts">
          <span className="eyebrow">QUICK NAVIGATION</span>
          <h2>Where to next?</h2>
          {[
            ["/map", "Explore the world"],
            ["/simulation", "Simulate a run"],
            ["/notes", "Write a field note"],
            ["/system", "Check cloud health"],
            ["/team", "Manage the crew"],
          ].map(([path, label]) => (
            <Link to={path} key={path}>
              {label}
              <ArrowUpRight size={16} />
            </Link>
          ))}
          <p>
            Scout retrieves relevant source files on demand. It can’t change
            production settings or submit runs.
          </p>
        </aside>
      </div>
    </div>
  );
}
